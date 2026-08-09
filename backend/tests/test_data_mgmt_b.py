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

    def fake_ingest_board(self, ctx=None, board_type=None, board_codes=None):
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

    def slow_board(self, ctx=None, board_type=None, board_codes=None):
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

    def fake_ingest_board(self, ctx=None, board_type=None, board_codes=None):
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
