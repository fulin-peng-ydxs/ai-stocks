"""M2.8-B 后端能力测试：实时日志/checkpoint 续跑/并发互斥/fix 修复/概览缺口/逐股质量/调度/系统设置。

不触网：通过 monkeypatch 把 get_client 指向临时库，并桩掉 IngestionService 的真实采集。
"""

from __future__ import annotations

import time
from datetime import date, datetime

import pandas as pd
import pytest

import backend.storage.duckdb_client as dc
from backend.services.async_task import AsyncTaskService, ConcurrentTaskError
from backend.services.data_report import DataIntegrityReport
from backend.storage.ddl import init_db
from backend.storage.duckdb_client import DuckDBClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    c = DuckDBClient(db_path=str(tmp_path / "t.duckdb"))
    init_db(c)
    monkeypatch.setattr(dc, "_client", c)   # get_client() → 本临时库
    yield c
    c.close()


def _wait(svc, tid, timeout=8.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        t = svc.get(tid)
        if t and t["status"] in ("done", "failed", "interrupted"):
            return t
        time.sleep(0.05)
    raise AssertionError("任务超时")


# ── 并发互斥（FR-DM-11）──
def test_concurrency_mutex(client, monkeypatch):
    svc = AsyncTaskService(client)
    # 桩掉 update：阻塞一会，制造"运行中"
    from backend.services import ingest

    def slow_update(self, codes=None, concurrency=None, ctx=None):
        time.sleep(0.4)
        return {"ok": 1}
    monkeypatch.setattr(ingest.IngestionService, "update", slow_update, raising=True)
    monkeypatch.setattr(ingest.IngestionService, "__init__", lambda self, source=None: None, raising=True)

    t1 = svc.create("update")
    with pytest.raises(ConcurrentTaskError):
        svc.create("update")            # 同类写任务 → 拒绝
    _wait(svc, t1)


def test_quality_scan_and_repair_share_write_mutex(client, monkeypatch):
    svc = AsyncTaskService(client)

    def slow_scan(self):
        time.sleep(0.4)
        return {}

    monkeypatch.setattr(DataIntegrityReport, "scan_quality_issues", slow_scan, raising=True)

    verify_id = svc.create("verify")
    with pytest.raises(ConcurrentTaskError):
        svc.create("fix", {"issue_type": "data_gap"})
    _wait(svc, verify_id)


# ── reconcile + 续跑（FR-DM-10）──
def test_reconcile_marks_interrupted(client):
    svc = AsyncTaskService(client)
    now = datetime.now()
    client.execute(
        "INSERT INTO async_task (id, task_type, params, status, progress, message, result, created_at, updated_at) "
        "VALUES ('task_x','update','{}','running',0.5,'半路',?, ?, ?)",
        ['{"checkpoint": {"done": 10, "total": 100}}', now, now])
    out = svc.reconcile()
    assert out["interrupted"] == 1
    assert svc.get("task_x")["status"] == "interrupted"


def test_resume_interrupted(client, monkeypatch):
    svc = AsyncTaskService(client)
    from backend.services import ingest
    monkeypatch.setattr(ingest.IngestionService, "__init__", lambda self, source=None: None, raising=True)
    monkeypatch.setattr(ingest.IngestionService, "update",
                        lambda self, codes=None, concurrency=None, ctx=None: {"ok": 1}, raising=True)
    monkeypatch.setattr("backend.services.async_task._mark_snapshots_stale", lambda: 0)
    now = datetime.now()
    client.execute(
        "INSERT INTO async_task (id, task_type, params, status, progress, message, result, created_at, updated_at) "
        "VALUES ('task_r','update','{}','interrupted',0.5,'中断',?, ?, ?)",
        ['{"checkpoint": {"done": 10, "total": 100}}', now, now])
    svc.resume("task_r")
    t = _wait(svc, "task_r")
    assert t["status"] == "done"
    # 不可续跑非 interrupted
    with pytest.raises(ValueError):
        svc.resume("task_r")


# ── 实时日志（FR-DM-9）──
def test_task_logs_increment(client):
    svc = AsyncTaskService(client)
    from backend.services.async_task import TaskContext
    now = datetime.now()
    client.execute(
        "INSERT INTO async_task (id, task_type, params, status, progress, message, result, created_at, updated_at) "
        "VALUES ('t_log','verify','{}','running',0.1,'x',NULL,?,?)", [now, now])
    ctx = TaskContext(svc, "t_log")
    for i in range(3):
        ctx.log(f"行 {i}")
    ctx.flush()
    logs = svc.get_logs("t_log", after_seq=0)
    assert [l["message"] for l in logs] == ["行 0", "行 1", "行 2"]
    assert svc.get_logs("t_log", after_seq=2) == [l for l in logs if l["seq"] > 2]


# ── fix 修复回写状态（FR-DM-4）──
def test_fix_resolves_issue(client, monkeypatch):
    svc = AsyncTaskService(client)
    from backend.services import ingest
    monkeypatch.setattr(ingest.IngestionService, "__init__", lambda self, source=None: None, raising=True)
    monkeypatch.setattr(ingest.IngestionService, "ingest_one_daily",
                        lambda self, code, s, e, *a, **k: 1, raising=True)
    monkeypatch.setattr("backend.services.async_task._mark_snapshots_stale", lambda: 0)
    client.execute(
        "INSERT INTO data_quality_issue (id, code, trade_date, issue_type, severity, status, detail, detected_at) "
        "VALUES (1,'600000.SH', DATE '2024-01-03','adj_jump','high','open','x',?)", [datetime.now()])
    tid = svc.create("fix", {"issue_id": 1})
    _wait(svc, tid)
    row = client.query_df("SELECT status, resolved_at FROM data_quality_issue WHERE id=1").iloc[0]
    assert row["status"] == "resolved" and row["resolved_at"] is not None


def test_scheduled_fix_resolves_current_open_issues_by_type(client, monkeypatch):
    """定时 fix 在执行时按类型动态取 open；不处理其它类型/已忽略，空跑正常完成。"""
    svc = AsyncTaskService(client)
    from backend.services import ingest

    monkeypatch.setattr(ingest.IngestionService, "__init__", lambda self, source=None: None, raising=True)

    def restore_daily(self, code, start, end, *args, **kwargs):
        client.execute(
            "INSERT INTO daily_bar (code, trade_date, open, high, low, close) "
            "VALUES (?, ?, 10, 10, 10, 10)",
            [code, start],
        )
        return 1

    monkeypatch.setattr(ingest.IngestionService, "ingest_one_daily", restore_daily, raising=True)
    monkeypatch.setattr("backend.services.async_task._mark_snapshots_stale", lambda: 0)
    now = datetime.now()
    client.execute(
        "INSERT INTO data_quality_issue "
        "(id, code, trade_date, issue_type, severity, status, detail, detected_at) VALUES "
        "(1, 'A.SH', DATE '2024-01-03', 'null_close', 'mid', 'open', 'x', ?),"
        "(2, 'B.SH', DATE '2024-01-03', 'null_close', 'mid', 'ignored', 'x', ?),"
        "(3, 'C.SH', DATE '2024-01-03', 'abnormal_change', 'mid', 'open', 'x', ?)",
        [now, now, now],
    )

    task = _wait(svc, svc.create("fix", {"issue_type": "null_close"}))
    assert task["status"] == "done"
    assert task["result"]["ok"] is True and task["result"]["total"] == 1
    statuses = client.query_df(
        "SELECT id, status FROM data_quality_issue ORDER BY id"
    ).set_index("id")["status"].to_dict()
    assert statuses == {1: "resolved", 2: "ignored", 3: "open"}

    empty = _wait(svc, svc.create("fix", {"issue_type": "null_close"}))
    assert empty["status"] == "done"
    assert empty["result"]["ok"] is True and empty["result"]["total"] == 0


def test_ohl_repaired_fix_reingests_before_resolve(client, monkeypatch):
    """OHL 修补问题不再只做复检；必须先重采当日行情。"""
    svc = AsyncTaskService(client)
    from backend.services import ingest

    monkeypatch.setattr(ingest.IngestionService, "__init__", lambda self, source=None: None, raising=True)
    called: list[tuple] = []

    def restore_daily(self, code, start, end, *args, **kwargs):
        called.append((code, start, end))
        return 1

    monkeypatch.setattr(ingest.IngestionService, "ingest_one_daily", restore_daily, raising=True)
    monkeypatch.setattr("backend.services.async_task._mark_snapshots_stale", lambda: 0)
    client.execute(
        "INSERT INTO data_quality_issue "
        "(id, code, trade_date, issue_type, severity, status, detail, detected_at) "
        "VALUES (1, 'A.SH', DATE '2024-01-03', 'ohl_repaired', 'low', 'open', 'x', ?)",
        [datetime.now()],
    )

    task = _wait(svc, svc.create("fix", {"issue_type": "ohl_repaired"}))
    assert task["result"]["ok"] is True
    assert called == [("A.SH", date(2024, 1, 3), date(2024, 1, 3))]


def test_ohl_repaired_fix_stays_open_without_duplicate_when_source_is_still_bad(
    client, monkeypatch,
):
    """原始 OHL 持续异常时复检不通过，原问题退回 open 且不重复增长台账。"""
    svc = AsyncTaskService(client)
    from backend.services import ingest

    def init_ingestion(instance, source=None):
        instance.c = client

    def still_bad(instance, code, start, end, *args, **kwargs):
        instance._record_issues(code, [start], "ohl_repaired", "开高低仍异常")
        return 1

    monkeypatch.setattr(ingest.IngestionService, "__init__", init_ingestion, raising=True)
    monkeypatch.setattr(ingest.IngestionService, "ingest_one_daily", still_bad, raising=True)
    monkeypatch.setattr("backend.services.async_task._mark_snapshots_stale", lambda: 0)
    client.execute(
        "INSERT INTO data_quality_issue "
        "(id, code, trade_date, issue_type, severity, status, detail, detected_at) "
        "VALUES (1, 'A.SH', DATE '2024-01-03', 'ohl_repaired', 'low', 'open', 'x', ?)",
        [datetime.now()],
    )

    task = _wait(svc, svc.create("fix", {"issue_type": "ohl_repaired"}))
    assert task["result"]["ok"] is False
    rows = client.query_df(
        "SELECT id, status, fix_task_id FROM data_quality_issue "
        "WHERE code='A.SH' AND trade_date=DATE '2024-01-03' AND issue_type='ohl_repaired'"
    )
    assert len(rows) == 1 and rows.iloc[0]["status"] == "open"
    assert rows.iloc[0]["fix_task_id"] is None or pd.isna(rows.iloc[0]["fix_task_id"])


# ── 概览缺口 + 逐股质量（FR-DM-1，DM-D9）──
def _seed_market(c):
    cal = pd.DataFrame({"trade_date": [date(2024, 1, d) for d in (2, 3, 4, 5)], "is_open": True})
    c.register_df("_cal", cal)
    c.execute("INSERT INTO trade_calendar SELECT trade_date, is_open FROM _cal")
    c.unregister("_cal")
    c.execute("INSERT INTO stock_basic (code, name, delist_date, list_date) VALUES "
              "('A.SH','甲',NULL, DATE '2024-01-02'), ('B.SH','乙',NULL, DATE '2024-01-02')")
    # A：4 天全（其中 01-04 停牌）；B：缺 01-04（真缺口）
    rows = [("A.SH", date(2024, 1, d), 10.0, d == 4) for d in (2, 3, 4, 5)]
    rows += [("B.SH", date(2024, 1, d), 20.0, False) for d in (2, 3, 5)]
    df = pd.DataFrame(rows, columns=["code", "trade_date", "close", "is_suspended"])
    c.register_df("_b", df)
    c.execute("INSERT INTO daily_bar (code, trade_date, close, is_suspended) "
              "SELECT code, trade_date, close, is_suspended FROM _b")
    c.unregister("_b")
    # L2 字段契约：A 的有行情日期均具备 total_mv 与 float_mv。
    metrics = pd.DataFrame(
        [{"code": "A.SH", "trade_date": date(2024, 1, d), "total_mv": 1e10, "float_mv": 8e9}
         for d in (2, 3, 4, 5)]
    )
    c.register_df("_m", metrics)
    c.execute("INSERT INTO daily_metrics SELECT code, trade_date, float_mv, total_mv FROM _m")
    c.unregister("_m")


def test_stock_quality_freshness(client):
    _seed_market(client)
    q = DataIntegrityReport(client).stock_quality()
    by = {r["code"]: r for r in q["list"]}
    assert by["A.SH"]["is_fresh"] is True and by["A.SH"]["total_mv_ok"] is True
    assert by["A.SH"]["gap_days"] == 0
    assert by["B.SH"]["is_fresh"] is True     # 末日 01-05 = 全局最新 → 鲜活
    assert by["B.SH"]["total_mv_ok"] is False  # 无 total_mv
    assert by["B.SH"]["gap_days"] == 1         # 缺 01-04（非停牌）


# ── 系统设置（FR-DM-12）──
def _fake_request():
    """save_settings 需 Request（仅用于审计取 IP/method/path）：造最小 ASGI scope。"""
    from starlette.requests import Request
    return Request({"type": "http", "method": "POST", "path": "/api/data/settings",
                    "headers": [], "query_string": b"", "client": ("127.0.0.1", 0),
                    "scheme": "http", "server": ("testserver", 80)})


def test_settings_view_and_save(client):
    from backend.api.data_admin import get_settings_view, save_settings
    view = get_settings_view().data
    assert any(g["key"] == "datasource" for g in view["groups"])
    # 保存覆盖
    resp = save_settings({"updates": {"backtest.cost.slippage": 0.003}}, _fake_request())
    assert resp.code == 0
    from backend.config import get_effective_settings
    assert get_effective_settings().backtest.cost.slippage == 0.003
    # 非法值被拒
    bad = save_settings({"updates": {"datasource.update_concurrency": 0}}, _fake_request())
    assert bad.code == 400


# ── 板块采集任务（R5，T5）───────────────────────────────────


def test_board_task_registered():
    """board 任务类型四要素：TASK_TYPES/WRITE_TASK_TYPES/TASK_CAPABILITIES/_HANDLERS。"""
    from backend.services.async_task import (
        TASK_TYPES, WRITE_TASK_TYPES, TASK_CAPABILITIES, _HANDLERS)
    assert "board" in TASK_TYPES
    assert "board" in WRITE_TASK_TYPES          # 写任务：与其他写任务互斥
    assert TASK_CAPABILITIES["board"]["can_cancel"] is True
    assert TASK_CAPABILITIES["board"]["can_resume"] is True
    assert TASK_CAPABILITIES["board"]["resume_granularity"] == "board_code"
    assert "board" in _HANDLERS


def test_board_task_create_and_run(client, monkeypatch):
    """board 任务可创建并后台执行成功（桩掉采集，验证 handler 调 ingest_board）。"""
    from backend.services import ingest as ingest_mod
    from backend.services.async_task import AsyncTaskService

    calls = {"n": 0}

    def fake_ingest_board(self, ctx=None, board_type=None, board_codes=None, mode="update"):
        calls["n"] += 1
        return {"dict": {"total": 465}, "members": {}, "bar": {"rows": 0},
                "fund_flow": {"rows": 0}, "failed": []}

    monkeypatch.setattr(ingest_mod.IngestionService, "ingest_board", fake_ingest_board, raising=True)
    monkeypatch.setattr(ingest_mod.IngestionService, "__init__", lambda self, source=None: None, raising=True)
    # _h_board 内部读 board_dict（空库无板块 → remaining 空），桩掉 query_df 的读取或容忍空
    svc = AsyncTaskService(client)
    tid = svc.create("board")
    t = _wait(svc, tid)
    assert t["status"] == "done"
    assert calls["n"] == 1


def test_board_task_write_mutex(client, monkeypatch):
    """board 是写任务：运行中禁止并发创建其他写任务。"""
    import time
    from backend.services import ingest as ingest_mod
    from backend.services.async_task import AsyncTaskService, ConcurrentTaskError

    def slow_board(self, ctx=None, board_type=None, board_codes=None, mode="update"):
        time.sleep(0.4)
        return {"dict": {"total": 0}, "members": {}, "bar": {"rows": 0},
                "fund_flow": {"rows": 0}, "failed": []}

    monkeypatch.setattr(ingest_mod.IngestionService, "ingest_board", slow_board, raising=True)
    monkeypatch.setattr(ingest_mod.IngestionService, "__init__", lambda self, source=None: None, raising=True)
    svc = AsyncTaskService(client)
    t1 = svc.create("board")
    with pytest.raises(ConcurrentTaskError):
        svc.create("update")            # board 运行中 → 其他写任务被拒
    _wait(svc, t1)


def test_board_task_resume_skips_done(client, monkeypatch):
    """续跑：有 checkpoint done_codes 时跳过已完成板块（传给 ingest_board 的 board_codes=剩余）。"""
    from backend.services import ingest as ingest_mod
    from backend.services.async_task import AsyncTaskService
    from datetime import datetime

    received = {}

    def fake_ingest_board(self, ctx=None, board_type=None, board_codes=None, mode="update"):
        received["board_codes"] = board_codes
        return {"dict": {"total": 465}, "members": {}, "bar": {"rows": 0},
                "fund_flow": {"rows": 0}, "failed": []}

    monkeypatch.setattr(ingest_mod.IngestionService, "ingest_board", fake_ingest_board, raising=True)
    monkeypatch.setattr(ingest_mod.IngestionService, "__init__", lambda self, source=None: None, raising=True)
    # 种 2 个板块：B 已完成，续跑应只传 A
    client.execute("INSERT INTO board_dict (board_code, name, board_type, has_members) "
                   "VALUES ('309121','AI PC','concept',TRUE)")
    client.execute("INSERT INTO board_dict (board_code, name, board_type, has_members) "
                   "VALUES ('881121','半导体','industry',TRUE)")
    svc = AsyncTaskService(client)
    now = datetime.now()
    client.execute(
        "INSERT INTO async_task (id, task_type, params, status, progress, message, result, created_at, updated_at) "
        "VALUES ('board_x','board','{}','interrupted',0.5,'中断',?, ?, ?)",
        ['{"checkpoint": {"done_codes": ["881121"]}}', now, now])
    svc.resume("board_x")
    t = _wait(svc, "board_x")
    assert t["status"] == "done"
    assert received.get("board_codes") == ["309121"]   # 只处理未完成板块


# ── 板块质检（R12，T7）───────────────────────────────────────


def _seed_board_scan(client):
    """种板块质检所需数据：板块字典 + 成分 + 指数 + 全局最新交易日。"""
    client.execute("INSERT INTO board_dict (board_code, name, board_type, has_members, has_bar, member_count) "
                   "VALUES ('309121','AI PC','concept',TRUE,TRUE,50)")
    client.execute("INSERT INTO board_dict (board_code, name, board_type, has_members, has_bar, member_count) "
                   "VALUES ('881121','半导体','industry',TRUE,TRUE,120)")
    # 全局最新交易日（daily_bar 有数据 → 指数缺口判定基准）
    client.execute("INSERT INTO daily_bar (code, trade_date, close) VALUES ('600000.SH', DATE '2026-08-07', 10.0)")
    # AI PC 指数到 08-07（正常），半导体指数滞后到 08-06（缺口）
    client.execute("INSERT INTO board_bar (board_code, trade_date, close) VALUES ('309121', DATE '2026-08-07', 100.0)")
    client.execute("INSERT INTO board_bar (board_code, trade_date, close) VALUES ('881121', DATE '2026-08-06', 200.0)")


def test_scan_board_quality_member_wave(client, monkeypatch):
    """成分数波动扫描：member_count 基准 vs 有效成员计数，超阈值写 issue。"""
    from backend.services.data_report import DataIntegrityReport
    _seed_board_scan(client)
    # AI PC 有效成员 20（基准 50 → 波动 30 >= threshold 20）→ 触发
    for i in range(20):
        client.execute("INSERT INTO board_member (board_code, code, in_date) "
                       "VALUES ('309121', ?, DATE '2026-01-05')", [f"code{i:06d}"])
    # 半导体有效成员 120（基准 120 → 无波动）
    for i in range(120):
        client.execute("INSERT INTO board_member (board_code, code, in_date) "
                       "VALUES ('881121', ?, DATE '2026-01-05')", [f"8{i:05d}"])
    r = DataIntegrityReport(client).scan_board_quality()
    assert r["member_wave"] >= 1
    waves = client.query_df(
        "SELECT code, issue_type FROM data_quality_issue WHERE issue_type='board_member_wave'")
    assert "309121" in waves["code"].tolist()   # AI PC 波动被报
    assert "881121" not in waves["code"].tolist()  # 半导体稳定不报


def test_scan_board_quality_index_gap(client, monkeypatch):
    """板块指数缺口扫描：board_bar 滞后全局最新交易日写 issue。"""
    from backend.services.data_report import DataIntegrityReport
    _seed_board_scan(client)
    r = DataIntegrityReport(client).scan_board_quality()
    assert r["index_gap"] >= 1
    gaps = client.query_df(
        "SELECT code, issue_type FROM data_quality_issue WHERE issue_type='board_index_gap'")
    assert "881121" in gaps["code"].tolist()   # 半导体滞后被报
    assert "309121" not in gaps["code"].tolist()  # AI PC 指数正常不报


def test_scan_board_quality_config_override(client, monkeypatch):
    """阈值配置覆盖生效：Settings 模型字段 + CONFIG_GROUPS 白名单三环配套。"""
    from backend.config.settings import Settings
    # 默认值（Settings 模型）
    s = Settings()
    assert s.board_quality.relative_change_ratio == 0.5
    assert s.board_quality.absolute_change_threshold == 20
    # CONFIG_GROUPS 白名单允许该字段（T1 契约：三环配套可被 app_config 覆盖）
    from backend.storage.app_config import WHITELIST
    assert "board_quality.relative_change_ratio" in WHITELIST
    assert "board_quality.absolute_change_threshold" in WHITELIST


def test_scan_board_quality_convergence_keeps_member_surge(client, monkeypatch):
    """收敛不误删 member_surge_shrink：扫描后候选关联的 open issue 仍保留。"""
    from backend.services.data_report import DataIntegrityReport
    _seed_board_scan(client)
    # 预置一条 member_surge_shrink open（候选关联，模拟 T4 候选保存）
    client.execute(
        "INSERT INTO board_member_candidate (candidate_id, issue_id, board_code, snapshot_date, "
        "payload_hash, status) VALUES ('c1', 999, '309121', DATE '2026-08-09', ?, 'pending')",
        ["a" * 64])
    client.execute(
        "INSERT INTO data_quality_issue (id, code, issue_type, severity, status, detected_at, fix_task_id) "
        "VALUES (999, '309121', 'member_surge_shrink', 'high', 'open', now(), NULL)")
    # 跑板块扫描（会触发收敛 DELETE open 且 IN SCAN_ISSUE_TYPES）
    DataIntegrityReport(client).scan_board_quality()
    # member_surge_shrink 不在 SCAN_ISSUE_TYPES → 不被删
    left = client.query_df(
        "SELECT count(*) n FROM data_quality_issue WHERE issue_type='member_surge_shrink'")
    assert int(left.iloc[0]["n"]) == 1


def test_board_update_uses_latest_open_day(client, monkeypatch):
    """板块 update 指数区间复用现有交易日语义（_latest_open_day），非裸 today。"""
    from datetime import date, timedelta
    from backend.services import ingest as ingest_mod
    from backend.services.ingest import IngestionService
    from backend.services.board_ingest import BoardIngestService

    captured = {}

    def fake_ingest_board_dict(self, snapshot_date=None):
        return {"concept": 375, "industry": 90, "total": 465}

    def fake_ingest_board_members(self, snapshot_date=None, board_codes=None):
        return {}

    def fake_ingest_board_bar(self, start, end=None, board_codes=None):
        captured["start"] = start
        captured["end"] = end
        return {"rows": 0, "boards": 0}

    def fake_ingest_board_fund_flow(self, snapshot_date=None, periods=None):
        captured["periods"] = periods
        return {"rows": 0, "unmatched": 0}

    # mock BoardIngestService 子方法 + _latest_open_day 返回固定交易日
    monkeypatch.setattr(BoardIngestService, "ingest_board_dict", fake_ingest_board_dict, raising=True)
    monkeypatch.setattr(BoardIngestService, "ingest_board_members", fake_ingest_board_members, raising=True)
    monkeypatch.setattr(BoardIngestService, "ingest_board_bar", fake_ingest_board_bar, raising=True)
    monkeypatch.setattr(BoardIngestService, "ingest_board_fund_flow", fake_ingest_board_fund_flow, raising=True)
    monkeypatch.setattr(ingest_mod.IngestionService, "__init__", lambda self, source=None: None, raising=True)
    # _latest_open_day 返回 2026-08-07（周五交易日）
    monkeypatch.setattr(ingest_mod.IngestionService, "_latest_open_day",
                        lambda self: date(2026, 8, 7), raising=True)

    IngestionService().ingest_board(mode="update")
    # 指数区间：start = 最近交易日 - 7 天 = 07-31；end = 最近交易日
    assert captured["start"] == date(2026, 8, 7) - timedelta(days=7)
    assert captured["end"] == date(2026, 8, 7)
    # 资金流：update 只采即时
    assert captured["periods"] == ("即时",)


def test_scan_board_quality_no_false_wave_without_bar(client, monkeypatch):
    """board_bar 空（指数未采）时，稳定板块成分数波动不误报（此前 max(trade_date) NULL → cur=0）。"""
    from backend.services.data_report import DataIntegrityReport
    c = client
    c.execute("INSERT INTO board_dict (board_code, name, board_type, has_members, has_bar, member_count) "
              "VALUES ('309121','AI PC','concept',TRUE,TRUE,50)")
    for i in range(50):
        c.execute("INSERT INTO board_member (board_code, code, in_date) "
                  "VALUES ('309121', ?, DATE '2026-01-05')", [f"c{i:05d}"])
    # board_bar 无数据
    r = DataIntegrityReport(c).scan_board_quality()
    assert r["member_wave"] == 0   # 稳定 50 只不误报


def test_ingest_board_only_selects_tables(client, monkeypatch):
    """only 分表：only=["bar"] 时只跑指数，不跑字典/成分/资金流。"""
    from backend.services import ingest as ingest_mod
    from backend.services.ingest import IngestionService
    from backend.services.board_ingest import BoardIngestService

    called = {"dict": 0, "members": 0, "bar": 0, "fund": 0}

    monkeypatch.setattr(BoardIngestService, "ingest_board_dict",
                        lambda self, snapshot_date=None: called.__setitem__("dict", 1) or {"total": 0}, raising=True)
    monkeypatch.setattr(BoardIngestService, "ingest_board_members",
                        lambda self, snapshot_date=None, board_codes=None: called.__setitem__("members", 1) or {}, raising=True)
    monkeypatch.setattr(BoardIngestService, "ingest_board_bar",
                        lambda self, start, end=None, board_codes=None: called.__setitem__("bar", 1) or {"rows": 0, "boards": 0}, raising=True)
    monkeypatch.setattr(BoardIngestService, "ingest_board_fund_flow",
                        lambda self, snapshot_date=None, periods=None: called.__setitem__("fund", 1) or {"rows": 0, "unmatched": 0}, raising=True)
    monkeypatch.setattr(ingest_mod.IngestionService, "__init__", lambda self, source=None: None, raising=True)
    monkeypatch.setattr(ingest_mod.IngestionService, "_latest_open_day",
                        lambda self: __import__("datetime").date(2026, 8, 7), raising=True)

    IngestionService().ingest_board(mode="update", only=["bar"])
    assert called == {"dict": 0, "members": 0, "bar": 1, "fund": 0}  # 只跑指数


# ── 候选接口（T9，R2 恢复闭环）───────────────────────────────


def _seed_candidate(client, code="309121", n=50, status="pending"):
    """种一条候选 + 关联 issue + 板块字典。"""
    import json
    client.execute("INSERT INTO board_dict (board_code, name, board_type, has_members) "
                   "VALUES (?,?,?,TRUE)", [code, "AI PC" if code == "309121" else "半导体", "concept"])
    h = "a" * 64
    client.execute(
        "INSERT INTO board_member_candidate (candidate_id, issue_id, board_code, snapshot_date, "
        "codes_json, payload_hash, status) VALUES ('c-test', 9001, ?, DATE '2026-08-09', ?, ?, ?)",
        [code, json.dumps([f"code{i:06d}" for i in range(n)]), h, status])
    client.execute(
        "INSERT INTO data_quality_issue (id, code, issue_type, severity, status, detected_at) "
        "VALUES (9001, ?, 'member_surge_shrink', 'high', 'open', now())", [code])


def test_apply_candidate_applies_diff_and_member_count(client):
    """候选 apply（事务②）：diff 落库 + 候选 applied + issue resolved + member_count 刷新。"""
    from backend.api.board_candidates import apply_candidate
    _seed_candidate(client, n=3)
    resp = apply_candidate("c-test")
    assert resp.code == 0, resp.msg
    # 候选 applied
    st = client.query_df("SELECT status FROM board_member_candidate WHERE candidate_id='c-test'").iloc[0]["status"]
    assert st == "applied"
    # board_member 落库 3 条
    n = client.query_df("SELECT count(*) n FROM board_member").iloc[0]["n"]
    assert int(n) == 3
    # member_count 刷新
    mc = client.query_df("SELECT member_count FROM board_dict WHERE board_code='309121'").iloc[0]["member_count"]
    assert int(mc) == 3
    # issue resolved
    iss = client.query_df("SELECT status FROM data_quality_issue WHERE id=9001").iloc[0]["status"]
    assert iss == "resolved"


def test_discard_candidate(client):
    """候选 discard（事务③）：候选 discarded + issue ignored，board_member 不变。"""
    from backend.api.board_candidates import discard_candidate
    _seed_candidate(client, n=3)
    resp = discard_candidate("c-test")
    assert resp.code == 0
    st = client.query_df("SELECT status FROM board_member_candidate WHERE candidate_id='c-test'").iloc[0]["status"]
    assert st == "discarded"
    iss = client.query_df("SELECT status FROM data_quality_issue WHERE id=9001").iloc[0]["status"]
    assert iss == "ignored"
    assert int(client.query_df("SELECT count(*) n FROM board_member").iloc[0]["n"]) == 0  # 不落库


def test_apply_candidate_already_processed_409(client):
    """候选已 applied/discarded → 409 already_processed。"""
    from backend.api.board_candidates import apply_candidate
    _seed_candidate(client, status="discarded")
    resp = apply_candidate("c-test")
    assert resp.code == 409
    assert resp.data.get("error_code") == "already_processed"


def test_overview_includes_board_stats(client, monkeypatch):
    """数据总览 overview 含板块表行数 + 待处理候选（板块闭环进总览）。"""
    from backend.services.data_report import DataIntegrityReport
    # 板块表有数据 + 一条 pending 候选
    client.execute("INSERT INTO board_dict (board_code, name, board_type) VALUES ('309121','AI PC','concept')")
    client.execute("INSERT INTO board_member_candidate (candidate_id, board_code, snapshot_date, "
                   "payload_hash, status) VALUES ('c1','309121',DATE '2026-08-09',?, 'pending')", ["a" * 64])
    ov = DataIntegrityReport(client).overview()
    assert int(ov["row_counts"]["board_dict"]) == 1
    assert "board_member_candidate" in ov["row_counts"]
    # overview API 也带 board 统计
    from backend.api.data_admin import overview
    resp = overview()
    assert resp.code == 0
    assert resp.data["board"]["board_dict"] == 1
    assert resp.data["board"]["candidate_pending"] == 1


def test_hub_includes_board_stage(client, monkeypatch):
    """hub 闭环图含 board 环节（5 表行数 + 待处理候选 + 板块问题数）。"""
    from backend.api.data_admin import hub
    client.execute("INSERT INTO board_dict (board_code, name, board_type) VALUES ('309121','AI PC','concept')")
    client.execute("INSERT INTO board_member_candidate (candidate_id, board_code, snapshot_date, "
                   "payload_hash, status) VALUES ('c1','309121',DATE '2026-08-09',?, 'pending')", ["a" * 64])
    client.execute("INSERT INTO data_quality_issue (id, code, issue_type, severity, status, detected_at) "
                   "VALUES (1, '309121', 'board_member_wave', 'mid', 'open', now())")
    resp = hub()
    assert resp.code == 0
    board = resp.data["stages"]["board"]
    assert board["board_dict"] == 1
    assert board["candidate_pending"] == 1
    assert board["open_issues"] == 1
    # 风险列表含候选待处理提示
    assert any("候选待确认" in r["text"] for r in resp.data["risk"])
