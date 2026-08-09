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
    # 本模块验证 DuckDB 数据管理闭环，不依赖 PostgreSQL 审计库；避免本地 PG 状态污染单测。
    monkeypatch.setattr(AsyncTaskService, "_audit_task", lambda *args, **kwargs: None)
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
    assert TASK_CAPABILITIES["board"]["resume_granularity"] == "board_code_or_fund_period"
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


def test_board_task_resume_preserves_phase_checkpoint(client, monkeypatch):
    """续跑把逐阶段 checkpoint 原样交给采集服务，由成员/指数循环跳过已完成板块。"""
    from backend.services import ingest as ingest_mod
    from backend.services.async_task import AsyncTaskService
    from datetime import datetime

    received = {}

    def fake_ingest_board(self, ctx=None, board_type=None, board_codes=None, mode="update"):
        received["board_codes"] = board_codes
        received["checkpoint"] = dict(ctx.checkpoint)
        return {"dict": {"total": 465}, "members": {}, "bar": {"rows": 0},
                "fund_flow": {"rows": 0}, "failed": []}

    monkeypatch.setattr(ingest_mod.IngestionService, "ingest_board", fake_ingest_board, raising=True)
    monkeypatch.setattr(ingest_mod.IngestionService, "__init__", lambda self, source=None: None, raising=True)
    # 种 2 个板块；成员阶段已完成 B，真实循环会按 member_done_codes 跳过。
    client.execute("INSERT INTO board_dict (board_code, name, board_type, has_members) "
                   "VALUES ('309121','AI PC','concept',TRUE)")
    client.execute("INSERT INTO board_dict (board_code, name, board_type, has_members) "
                   "VALUES ('881121','半导体','industry',TRUE)")
    svc = AsyncTaskService(client)
    now = datetime.now()
    client.execute(
        "INSERT INTO async_task (id, task_type, params, status, progress, message, result, created_at, updated_at) "
        "VALUES ('board_x','board','{}','interrupted',0.5,'中断',?, ?, ?)",
        ['{"checkpoint": {"phase": "board_members", "member_done_codes": ["881121"]}}', now, now])
    svc.resume("board_x")
    t = _wait(svc, "board_x")
    assert t["status"] == "done"
    assert received.get("board_codes") is None
    assert received["checkpoint"]["member_done_codes"] == ["881121"]


def test_board_task_partial_result_is_failed_and_resumable(client, monkeypatch):
    """局部失败必须保留 checkpoint；续跑只处理剩余单元并可最终完成。"""
    from backend.services import ingest as ingest_mod
    from backend.services.async_task import AsyncTaskService

    monkeypatch.setattr(ingest_mod.IngestionService, "__init__",
                        lambda self, source=None: None, raising=True)
    calls = {"n": 0}

    def partial_then_ok(self, ctx=None, board_type=None, board_codes=None, mode="update"):
        calls["n"] += 1
        if calls["n"] == 1:
            ctx.set_phase("board_bar", done=1, total=2,
                          bar_done_codes=["881121"], current_item="309121")
            return {"failed": ["bar:309121: timeout"], "ok": False}
        assert ctx.checkpoint["bar_done_codes"] == ["881121"]
        return {"failed": [], "ok": True}

    monkeypatch.setattr(ingest_mod.IngestionService, "ingest_board", partial_then_ok, raising=True)
    svc = AsyncTaskService(client)
    tid = svc.create("board", {"mode": "update"})
    task = _wait(svc, tid)
    assert task["status"] == "failed"
    assert "部分失败" in task["message"]
    assert task["result"]["checkpoint"]["bar_done_codes"] == ["881121"]

    svc.resume(tid)
    task = _wait(svc, tid)
    assert task["status"] == "done"
    assert calls["n"] == 2


def test_quality_recover_batch_code_filter_keeps_other_conditions(client, monkeypatch):
    """板块名称 OR 分支不能越过 status/type；未匹配问题可按 detail.name 搜索。"""
    from backend.api.data_admin import quality_recover_batch

    client.execute("INSERT INTO board_dict (board_code, name, board_type) "
                   "VALUES ('309121','AI PC','concept')")
    client.execute(
        "INSERT INTO data_quality_issue "
        "(id, code, issue_type, severity, status, detail, detected_at) VALUES "
        "(11, '309121', 'board_member_incomplete', 'mid', 'open', '{}', now()), "
        "(12, '309121', 'board_member_incomplete', 'mid', 'resolved', '{}', now()), "
        "(13, '309121', 'board_index_gap', 'mid', 'open', '{}', now()), "
        "(14, NULL, 'board_fund_unmatched', 'mid', 'open', "
        "'{\"name\":\"新概念\",\"board_type\":\"concept\"}', now())")
    captured: list[dict] = []

    def fake_create(self, task_type, params=None, **kwargs):
        captured.append({"task_type": task_type, "params": params})
        return f"task_{len(captured)}"

    monkeypatch.setattr(AsyncTaskService, "create", fake_create, raising=True)

    r1 = quality_recover_batch({
        "issue_type": "board_member_incomplete", "code": "AI PC",
    })
    assert r1.code == 0
    assert captured[-1]["params"]["issue_ids"] == [11]

    r2 = quality_recover_batch({
        "issue_type": "board_fund_unmatched", "code": "新概念",
    })
    assert r2.code == 0
    assert captured[-1]["params"]["issue_ids"] == [14]


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


def test_scan_board_quality_no_member_wave(client, monkeypatch):
    """只进不出模型：成分数波动不再质检（源端真实重组非错误），扫描不产 board_member_wave。"""
    from backend.services.data_report import DataIntegrityReport
    _seed_board_scan(client)
    # 即使 member_count 与当前成员数差异巨大，也不再报波动；返回值无 member_wave 键
    r = DataIntegrityReport(client).scan_board_quality()
    assert "member_wave" not in r
    waves = client.query_df(
        "SELECT count(*) n FROM data_quality_issue WHERE issue_type='board_member_wave'")
    assert int(waves.iloc[0]["n"]) == 0


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


def test_board_scan_failure_keeps_previous_open_issue(client, monkeypatch):
    """板块扫描替换必须原子化：新问题写入失败时保留上轮 open 问题。"""
    from backend.services.data_report import DataIntegrityReport
    _seed_board_scan(client)
    client.execute("INSERT INTO data_quality_issue "
                   "(id, code, issue_type, severity, status, detected_at) "
                   "VALUES (999, 'old-board', 'board_index_gap', 'mid', 'open', now())")
    rep = DataIntegrityReport(client)
    monkeypatch.setattr(rep, "_insert_issues", lambda issues: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(Exception):
        rep.scan_board_quality()
    old = client.query_df("SELECT status FROM data_quality_issue WHERE id=999")
    assert not old.empty and old.iloc[0]["status"] == "open"


def test_board_recheck_does_not_accept_historical_member_count(client):
    """旧 member_count 不是修复证据；没有新完整快照时必须保持未解决。"""
    from backend.services.data_report import DataIntegrityReport
    client.execute("INSERT INTO board_dict (board_code, name, board_type, member_count) "
                   "VALUES ('309121','AI PC','concept',50)")
    client.execute("INSERT INTO data_quality_issue "
                   "(id, code, issue_type, severity, status, detected_at) "
                   "VALUES (998, '309121', 'board_member_incomplete', 'mid', 'fixing', now())")
    assert DataIntegrityReport(client).recheck_clean(
        "board_member_incomplete", "309121", None) is False



def test_ths_board_config_overridable(client, monkeypatch):
    """同花顺请求参数走覆盖层：Settings 模型字段 + CONFIG_GROUPS 白名单，可被 app_config 覆盖。"""
    from backend.config.settings import Settings
    s = Settings()
    assert s.ths_board.min_interval_sec == 1.0
    assert s.ths_board.timeout_sec == 10.0
    assert s.ths_board.max_retries == 3
    assert s.ths_board.retry_backoff_sec == 2.0
    from backend.storage.app_config import WHITELIST
    assert "ths_board.min_interval_sec" in WHITELIST
    assert "ths_board.timeout_sec" in WHITELIST
    assert "ths_board.max_retries" in WHITELIST
    assert "ths_board.retry_backoff_sec" in WHITELIST


def test_board_member_incomplete_fix_reingests(client, monkeypatch):
    """board_member_incomplete fix：重采成分快照 → 复检通过 → resolved。"""
    svc = AsyncTaskService(client)
    from backend.services import ingest
    from backend.services.board_ingest import BoardIngestService

    monkeypatch.setattr(ingest.IngestionService, "__init__", lambda self, source=None: None, raising=True)
    monkeypatch.setattr("backend.services.async_task._mark_snapshots_stale", lambda: 0)
    monkeypatch.setattr(BoardIngestService, "__init__",
                        lambda self, client=None, source=None: setattr(self, "c", client), raising=True)
    monkeypatch.setattr(BoardIngestService, "ingest_board_members",
                        lambda self, snapshot_date=None, board_codes=None, ctx=None:
                        {"309121": {"total": 50}}, raising=True)
    client.execute("INSERT INTO board_dict (board_code, name, board_type, has_members) "
                   "VALUES ('309121','AI PC','concept',TRUE)")
    client.execute("INSERT INTO data_quality_issue (id, code, issue_type, severity, status, detected_at) "
                   "VALUES (2, '309121', 'board_member_incomplete', 'mid', 'open', now())")
    monkeypatch.setattr("backend.services.data_report.DataIntegrityReport.recheck_clean",
                        lambda self, issue_type, code, td, **kwargs: True, raising=True)
    tid = svc.create("fix", {"issue_id": 2})
    _wait(svc, tid)
    row = client.query_df("SELECT status FROM data_quality_issue WHERE id=2").iloc[0]
    assert row["status"] == "resolved"


def test_board_update_uses_latest_open_day(client, monkeypatch):
    """板块 update 指数区间复用现有交易日语义（_latest_open_day），非裸 today。"""
    from datetime import date, timedelta
    from backend.services import ingest as ingest_mod
    from backend.services.ingest import IngestionService
    from backend.services.board_ingest import BoardIngestService

    captured = {}

    def fake_ingest_board_dict(self, snapshot_date=None, board_type=None, ctx=None):
        captured["dict_type"] = board_type
        return {"concept": 375, "industry": 90, "total": 465}

    def fake_ingest_board_members(self, snapshot_date=None, board_codes=None,
                                  board_type=None, ctx=None):
        captured["member_type"] = board_type
        return {}

    def fake_ingest_board_bar(self, start, end=None, board_codes=None,
                              board_type=None, ctx=None):
        captured["bar_type"] = board_type
        captured["start"] = start
        captured["end"] = end
        return {"rows": 0, "boards": 0}

    def fake_ingest_board_fund_flow(self, snapshot_date=None, periods=None, board_codes=None,
                                    board_type=None, ctx=None):
        captured["fund_type"] = board_type
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

    IngestionService().ingest_board(mode="update", board_type="concept")
    # 指数区间：start = 最近交易日 - 7 天 = 07-31；end = 最近交易日
    assert captured["start"] == date(2026, 8, 7) - timedelta(days=7)
    assert captured["end"] == date(2026, 8, 7)
    # 资金流：update 只采即时
    assert captured["periods"] == ("即时",)
    assert {captured[x] for x in ("dict_type", "member_type", "bar_type", "fund_type")} == {
        "concept",
    }
    with pytest.raises(ValueError, match="concept/industry"):
        IngestionService().ingest_board(board_type="theme")


def test_scan_board_quality_no_false_wave_without_bar(client, monkeypatch):
    """只进不出模型：成分数波动不再质检，扫描无 member_wave 键。"""
    from backend.services.data_report import DataIntegrityReport
    c = client
    c.execute("INSERT INTO board_dict (board_code, name, board_type, has_members, has_bar, member_count) "
              "VALUES ('309121','AI PC','concept',TRUE,TRUE,50)")
    for i in range(50):
        c.execute("INSERT INTO board_member (board_code, code) "
                  "VALUES ('309121', ?)", [f"c{i:05d}"])
    # board_bar 无数据；无全局最新交易日（daily_bar 空）→ index_gap 不报，无 member_wave 键
    r = DataIntegrityReport(c).scan_board_quality()
    assert "member_wave" not in r   # 波动质检已移除


def test_search_boards_by_code_and_name(client):
    """板块搜索：代码/名称模糊匹配（名称用 lower 不区分大小写），返回 code/name/board_type。"""
    from backend.api.data_admin import search_boards
    c = client
    c.execute("INSERT INTO board_dict (board_code, name, board_type, has_members) "
              "VALUES ('309121','AI PC','concept',TRUE)")
    c.execute("INSERT INTO board_dict (board_code, name, board_type, has_members) "
              "VALUES ('881121','半导体','industry',TRUE)")
    # 名称模糊（DuckDB LIKE 大小写敏感，lower(name) 匹配）
    r = search_boards(keyword="AI")
    assert r.data["total"] == 1
    assert r.data["list"][0]["code"] == "309121"
    assert r.data["list"][0]["board_type"] == "concept"
    # 名称含空格也能命中
    r = search_boards(keyword="ai pc")
    assert r.data["total"] == 1
    # 代码模糊
    r = search_boards(keyword="881")
    assert r.data["total"] == 1
    assert r.data["list"][0]["name"] == "半导体"
    # 类型过滤
    r = search_boards(board_type="industry")
    assert r.data["total"] == 1
    assert r.data["list"][0]["code"] == "881121"
    # 无结果
    r = search_boards(keyword="不存在板块")
    assert r.data["total"] == 0


def test_ingest_board_only_selects_tables(client, monkeypatch):
    """only 分表：only=["bar"] 时只跑指数，不跑字典/成分/资金流。"""
    from backend.services import ingest as ingest_mod
    from backend.services.ingest import IngestionService
    from backend.services.board_ingest import BoardIngestService

    called = {"dict": 0, "members": 0, "bar": 0, "fund": 0}

    monkeypatch.setattr(BoardIngestService, "ingest_board_dict",
                        lambda self, snapshot_date=None, board_type=None, ctx=None:
                        called.__setitem__("dict", 1) or {"total": 0}, raising=True)
    monkeypatch.setattr(BoardIngestService, "ingest_board_members",
                        lambda self, snapshot_date=None, board_codes=None, board_type=None, ctx=None:
                        called.__setitem__("members", 1) or {}, raising=True)
    monkeypatch.setattr(BoardIngestService, "ingest_board_bar",
                        lambda self, start, end=None, board_codes=None, board_type=None, ctx=None:
                        called.__setitem__("bar", 1) or {"rows": 0, "boards": 0}, raising=True)
    monkeypatch.setattr(BoardIngestService, "ingest_board_fund_flow",
                        lambda self, snapshot_date=None, periods=None, board_codes=None,
                        board_type=None, ctx=None:
                        called.__setitem__("fund", 1) or {"rows": 0, "unmatched": 0}, raising=True)
    monkeypatch.setattr(ingest_mod.IngestionService, "__init__", lambda self, source=None: None, raising=True)
    monkeypatch.setattr(ingest_mod.IngestionService, "_latest_open_day",
                        lambda self: __import__("datetime").date(2026, 8, 7), raising=True)

    IngestionService().ingest_board(mode="update", only=["bar"])
    assert called == {"dict": 0, "members": 0, "bar": 1, "fund": 0}  # 只跑指数


def test_overview_includes_board_stats(client, monkeypatch):
    """数据概览含板块规模、覆盖、鲜活和问题分项。"""
    from backend.services.data_report import DataIntegrityReport
    client.execute("INSERT INTO board_dict (board_code, name, board_type) VALUES ('309121','AI PC','concept')")
    ov = DataIntegrityReport(client).overview()
    assert int(ov["row_counts"]["board_dict"]) == 1
    # overview API 也带 board 统计
    from backend.api.data_admin import overview
    resp = overview()
    assert resp.code == 0
    board = resp.data["board"]
    assert board["board_dict"] == 1
    assert board["concept_count"] == 1 and board["industry_count"] == 0
    assert board["member_target"] == 0 and board["member_ready"] == 0
    assert board["open_issues"] == 0


def test_hub_includes_board_stage(client, monkeypatch):
    """hub 闭环图含 board 环节（4 表行数 + 板块问题数）。"""
    from backend.api.data_admin import hub
    client.execute("INSERT INTO board_dict (board_code, name, board_type) VALUES ('309121','AI PC','concept')")
    client.execute("INSERT INTO data_quality_issue (id, code, issue_type, severity, status, detected_at) "
                   "VALUES (1, '309121', 'board_member_incomplete', 'mid', 'open', now())")
    resp = hub()
    assert resp.code == 0
    board = resp.data["stages"]["board"]
    assert board["board_dict"] == 1
    assert board["open_issues"] == 1
    assert board["issues_by_type"] == {"board_member_incomplete": 1}


# ── 板块 fix 分派（_h_fix 板块类型，审计后补测）───────────────


def test_board_index_gap_fix_reingests_and_resolves(client, monkeypatch):
    """board_index_gap fix：重采板块指数 → 复检通过 → resolved。"""
    svc = AsyncTaskService(client)
    from backend.services import ingest
    from backend.services.board_ingest import BoardIngestService

    monkeypatch.setattr(ingest.IngestionService, "__init__", lambda self, source=None: None, raising=True)
    monkeypatch.setattr("backend.services.async_task._mark_snapshots_stale", lambda: 0)
    monkeypatch.setattr(BoardIngestService, "__init__",
                        lambda self, client=None, source=None: setattr(self, "c", client), raising=True)
    # mock 板块重采：把 board_bar 补到全局最新交易日，使复检通过
    monkeypatch.setattr(BoardIngestService, "ingest_board_bar",
                        lambda self, start, end=None, board_codes=None: {"rows": 1, "boards": 1}, raising=True)
    client.execute("INSERT INTO board_dict (board_code, name, board_type, has_bar) "
                   "VALUES ('309121','AI PC','concept',TRUE)")
    client.execute("INSERT INTO daily_bar (code, trade_date, close) VALUES ('600000.SH', DATE '2026-08-07', 10.0)")
    client.execute("INSERT INTO data_quality_issue (id, code, issue_type, severity, status, detected_at) "
                   "VALUES (1, '309121', 'board_index_gap', 'mid', 'open', now())")

    # 重采后 board_bar 有数据到最新交易日 → 复检通过
    def fake_recheck(self, issue_type, code, td, **kwargs):
        if issue_type == "board_index_gap":
            # 模拟重采后 board_bar 已到 08-07（全局最新）
            self.c.execute("INSERT INTO board_bar (board_code, trade_date, close) "
                           "VALUES ('309121', DATE '2026-08-07', 100.0)")
            return True
        return True
    monkeypatch.setattr("backend.services.data_report.DataIntegrityReport.recheck_clean",
                        fake_recheck, raising=True)
    tid = svc.create("fix", {"issue_id": 1})
    _wait(svc, tid)
    row = client.query_df("SELECT status FROM data_quality_issue WHERE id=1").iloc[0]
    assert row["status"] == "resolved"


def test_board_fund_unmatched_fix_resolves_only_after_mapping(client, monkeypatch):
    """board_fund_unmatched 修复会先刷新字典，名称真实可映射后才 resolved。"""
    svc = AsyncTaskService(client)
    from backend.services import ingest
    from backend.services.board_ingest import BoardIngestService

    monkeypatch.setattr(ingest.IngestionService, "__init__", lambda self, source=None: None, raising=True)
    monkeypatch.setattr("backend.services.async_task._mark_snapshots_stale", lambda: 0)
    monkeypatch.setattr(BoardIngestService, "__init__",
                        lambda self, client=None, source=None: setattr(self, "c", client), raising=True)
    def refresh_dict(self, snapshot_date=None, board_type=None, ctx=None):
        client.execute("INSERT INTO board_dict (board_code, name, board_type) "
                       "VALUES ('309121','AI PC','concept') ON CONFLICT DO NOTHING")
        return {"concept": 1, "industry": 0, "total": 1, "failed": []}

    monkeypatch.setattr(BoardIngestService, "ingest_board_dict", refresh_dict, raising=True)
    monkeypatch.setattr(BoardIngestService, "ingest_board_fund_flow",
                        lambda self, snapshot_date=None, periods=None, board_codes=None,
                        board_type=None, ctx=None:
                        {"rows": 1, "unmatched": 0, "failed": []}, raising=True)
    client.execute("INSERT INTO data_quality_issue "
                   "(id, code, issue_type, severity, status, detail, detected_at) "
                   "VALUES (3, NULL, 'board_fund_unmatched', 'mid', 'open', "
                   "'{\"name\":\"AI PC\",\"board_type\":\"concept\"}', now())")
    tid = svc.create("fix", {"issue_id": 3})
    _wait(svc, tid)
    row = client.query_df("SELECT status FROM data_quality_issue WHERE id=3").iloc[0]
    assert row["status"] == "resolved"
