"""M2.8-B 后端能力测试：实时日志/checkpoint 续跑/并发互斥/fix 修复/概览缺口/逐股质量/调度/系统设置。

不触网：通过 monkeypatch 把 get_client 指向临时库，并桩掉 IngestionService 的真实采集。
"""

from __future__ import annotations

import json
import time
from datetime import UTC, date, datetime

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


class _CaptureTaskContext:
    """处理器单测使用的最小上下文，捕获日志与进度而不写任务表。"""

    def __init__(self):
        self.logs = []
        self.progresses = []

    def log(self, message, level="info"):
        self.logs.append((message, level))

    def progress(self, value, message):
        self.progresses.append((value, message))


def test_health_reports_active_task_count(client, monkeypatch):
    """停服型验收脚本可通过健康端点在中断业务任务前 fail-closed。"""
    from backend.api import health as health_api

    class AvailableDependency:
        @staticmethod
        def ping():
            return True

    class ReadClient:
        db_path = client.db_path

        @staticmethod
        def query_df(sql, params=None, **_kwargs):
            return client.query_df(sql, params)

        @staticmethod
        def stats():
            return {"enabled": True, "size": 1}

    monkeypatch.setattr(health_api, "get_read_client", ReadClient)
    monkeypatch.setattr(health_api, "get_task_runtime_client", lambda: client)
    monkeypatch.setattr(health_api, "task_runtime_backend", lambda: "duckdb")
    monkeypatch.setattr(health_api, "get_pg_client", AvailableDependency)
    monkeypatch.setattr(health_api, "get_redis_client", AvailableDependency)

    assert health_api.health().data["active_task_count"] == 0
    now = datetime.now(UTC)
    client.execute(
        "INSERT INTO async_task "
        "(id, task_type, params, status, progress, message, result, created_at, updated_at) "
        "VALUES ('task_health','update','{}','running',0,'运行中',NULL,?,?)",
        [now, now],
    )
    assert health_api.health().data["active_task_count"] == 1


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


def test_update_does_not_invalidate_derived_results(monkeypatch):
    """采集任务只维护原始数据，不再触发榜单或天梯失效。"""
    from backend.services import async_task, ingest

    monkeypatch.setattr(ingest.IngestionService, "__init__", lambda self, source=None: None)
    monkeypatch.setattr(
        ingest.IngestionService,
        "update",
        lambda self, codes=None, concurrency=None, ctx=None: {"ok": 1},
    )

    def fail_on_mark():
        raise AssertionError("采集任务不应标记任何衍生结果失效")

    monkeypatch.setattr(async_task, "_mark_snapshots_stale", fail_on_mark)
    ctx = _CaptureTaskContext()
    result = async_task._h_update({}, ctx)

    assert "snapshots_marked_stale" not in result
    messages = [message for message, _ in ctx.logs]
    assert all("失效" not in message for message in messages)


def test_ingest_codes_skipped_does_not_invalidate_snapshots(monkeypatch):
    """指定股票源数据未就绪时没有数据变化，不应执行任务层失效兜底。"""
    from backend.services import async_task, ingest

    monkeypatch.setattr(ingest.IngestionService, "__init__", lambda self, source=None: None)
    monkeypatch.setattr(
        ingest.IngestionService,
        "update",
        lambda self, codes=None, concurrency=None, ctx=None: {"skipped": True},
    )

    def fail_on_mark():
        raise AssertionError("数据未变化，不应标记评分快照失效")

    monkeypatch.setattr(async_task, "_mark_snapshots_stale", fail_on_mark)
    result = async_task._h_ingest_codes({"codes": ["600000.SH"]}, _CaptureTaskContext())

    assert "snapshots_marked_stale" not in result
    assert "未执行" in result["message"]


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
    monkeypatch.setattr(ingest.IngestionService, "_bao_source", lambda self: object())
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
    c.execute("INSERT INTO daily_metrics (code,trade_date,float_mv,total_mv) SELECT code, trade_date, float_mv, total_mv FROM _m")
    c.unregister("_m")
    c.execute("INSERT INTO stock_share_capital_daily "
              "(code,trade_date,total_share,float_share,total_source,float_source,"
              "total_effective_date,total_available_date,float_effective_date,float_available_date) "
              "SELECT code,trade_date,1000000000,800000000,'test','test',trade_date,trade_date,trade_date,trade_date "
              "FROM daily_bar WHERE code='A.SH'")


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
@pytest.fixture()
def settings_pg(monkeypatch):
    """连接内临时表遮蔽全局配置；真实加解密及仓库SQL不接触共享 app_config。"""
    from backend.storage import app_config
    from backend.storage.audit_repository import AuditRepository
    from backend.storage.pg_client import get_pg_client

    class ConnectionPg:
        def __init__(self, conn):
            self.conn = conn

        def execute(self, sql, params=None):
            self.conn.execute(sql, params)

        def query_df(self, sql, params=None):
            cursor = self.conn.execute(sql, params)
            return pd.DataFrame(cursor.fetchall(), columns=[col.name for col in cursor.description])

    with get_pg_client().transaction() as conn:
        conn.execute("CREATE TEMP TABLE app_config (LIKE public.app_config INCLUDING ALL) "
                     "ON COMMIT DROP")
        isolated = ConnectionPg(conn)
        monkeypatch.setattr(app_config, "get_pg_client", lambda: isolated)
        monkeypatch.setattr(AuditRepository, "record", lambda *args, **kwargs: None)
        yield isolated


@pytest.fixture()
def app_cfg(settings_pg):
    from backend.storage.app_config import AppConfigRepo

    return AppConfigRepo(settings_pg)


def _fake_request():
    """save_settings 需 Request（仅用于审计取 IP/method/path）：造最小 ASGI scope。"""
    from starlette.requests import Request
    return Request({"type": "http", "method": "POST", "path": "/api/data/settings",
                    "headers": [], "query_string": b"", "client": ("127.0.0.1", 0),
                    "scheme": "http", "server": ("testserver", 80)})


def test_settings_view_and_save(client, app_cfg):
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


def test_ths_login_cookie_is_encrypted_and_masked(client, settings_pg, app_cfg):
    """同花顺登录 Cookie 可从页面配置，但数据库与响应都不得出现明文。"""
    from backend.api.data_admin import get_settings_view, save_settings
    from backend.config import get_effective_settings
    from backend.security.config_crypto import is_encrypted_config_value

    app_cfg.reset("ths_board.login_cookie")
    view = get_settings_view().data
    ths = next(g for g in view["groups"] if g["key"] == "ths_board")
    field = next(f for f in ths["fields"] if f["path"] == "ths_board.login_cookie")
    assert field["value"] == ""
    assert field["secret_status"] == "unset"

    cookie = "user=xxx; ticket=secret; v=yyy"
    resp = save_settings({"updates": {"ths_board.login_cookie": cookie}}, _fake_request())
    assert resp.code == 0
    stored = settings_pg.query_df(
        "SELECT value FROM app_config WHERE key=%s", ["ths_board.login_cookie"]
    ).iloc[0]["value"]
    stored_value = json.loads(stored)
    assert is_encrypted_config_value(stored_value)
    assert cookie not in stored
    assert get_effective_settings().ths_board.login_cookie == cookie

    masked = get_settings_view().data
    masked_ths = next(g for g in masked["groups"] if g["key"] == "ths_board")
    masked_field = next(f for f in masked_ths["fields"] if f["path"] == "ths_board.login_cookie")
    assert masked_field["value"] == "••••••已设置"
    assert masked_field["secret_status"] == "usable"


@pytest.mark.parametrize("failure_mode", ["missing_key", "wrong_key", "tampered_ciphertext"])
def test_ths_login_cookie_unavailable_status_matches_runtime(
    client, settings_pg, app_cfg, monkeypatch, failure_mode,
):
    """密钥缺失/错误或密文损坏时，接口不得把运行态不可用的 Cookie 显示为已设置。"""
    from cryptography.fernet import Fernet

    from backend.api.data_admin import get_settings_view

    app_cfg.reset("ths_board.login_cookie")
    app_cfg.set_many({"ths_board.login_cookie": "user=valid-before-failure"})
    if failure_mode == "missing_key":
        monkeypatch.delenv("AI_STOCKS_CONFIG_ENCRYPTION_KEY", raising=False)
        monkeypatch.delenv("AI_STOCKS_CONFIG_ENCRYPTION_KEY_FILE", raising=False)
    elif failure_mode == "wrong_key":
        monkeypatch.setenv(
            "AI_STOCKS_CONFIG_ENCRYPTION_KEY",
            Fernet.generate_key().decode("ascii"),
        )
    else:
        row = settings_pg.query_df(
            "SELECT value FROM app_config WHERE key=%s", ["ths_board.login_cookie"]
        ).iloc[0]
        stored = json.loads(row["value"])
        settings_pg.execute(
            "UPDATE app_config SET value=%s WHERE key=%s",
            [json.dumps(f"{stored[:-1]}X"), "ths_board.login_cookie"],
        )

    view = get_settings_view().data
    ths = next(g for g in view["groups"] if g["key"] == "ths_board")
    field = next(f for f in ths["fields"] if f["path"] == "ths_board.login_cookie")
    assert field["secret_status"] == "unavailable"
    assert field["value"] == ""
    assert field["overridden"] is True


def test_ths_login_cookie_save_without_key_is_rejected_before_other_writes(
    client, settings_pg, app_cfg, monkeypatch,
):
    from backend.storage.app_config import ConfigValidationError

    app_cfg.reset("ths_board.login_cookie")
    app_cfg.reset("audit.retention_days")
    monkeypatch.delenv("AI_STOCKS_CONFIG_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("AI_STOCKS_CONFIG_ENCRYPTION_KEY_FILE", raising=False)

    with pytest.raises(ConfigValidationError, match="缺少 AI_STOCKS_CONFIG_ENCRYPTION_KEY"):
        app_cfg.set_many({
            "audit.retention_days": 31,
            "ths_board.login_cookie": "must-not-persist",
        })

    assert settings_pg.query_df(
        "SELECT 1 FROM app_config WHERE key = ANY(%s)",
        [["audit.retention_days", "ths_board.login_cookie"]],
    ).empty


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


def test_board_task_force_members_passthrough(client, monkeypatch):
    """force_members 参数从任务 params 透传到 ingest_board（异步强制刷新成分）。"""
    from backend.services import ingest as ingest_mod
    from backend.services.async_task import AsyncTaskService

    captured: dict = {}

    def fake_ingest_board(self, ctx=None, board_type=None, board_codes=None,
                          mode="update", force_members=None):
        captured["force_members"] = force_members
        return {"dict": {"total": 465}, "members": {}, "bar": {"rows": 0},
                "fund_flow": {"rows": 0}, "failed": []}

    monkeypatch.setattr(ingest_mod.IngestionService, "ingest_board", fake_ingest_board, raising=True)
    monkeypatch.setattr(ingest_mod.IngestionService, "__init__", lambda self, source=None: None, raising=True)
    svc = AsyncTaskService(client)
    # 显式传 force_members=true → 透传 True；未传 → 不设该键（None 语义由 ingest_board 按 mode/codes 解析）
    tid = svc.create("board", {"force_members": True})
    t = _wait(svc, tid)
    assert t["status"] == "done"
    assert captured["force_members"] is True

    captured.clear()
    tid2 = svc.create("board", {"force_members": "true"})  # 字符串规范化
    t2 = _wait(svc, tid2)
    assert t2["status"] == "done"
    assert captured["force_members"] is True

    captured.clear()
    tid3 = svc.create("board", {})
    t3 = _wait(svc, tid3)
    assert t3["status"] == "done"
    assert captured["force_members"] is None  # 未传 → 不设键，ingest_board 按 mode/codes 自动解析


def test_board_task_force_current_day_passthrough(client, monkeypatch):
    """板块增量任务将强制当日参数透传到采集编排。"""
    from backend.services import ingest as ingest_mod
    from backend.services.async_task import AsyncTaskService

    captured: dict = {}

    def fake_ingest_board(self, ctx=None, board_type=None, board_codes=None,
                          mode="update", force_current_day=False):
        captured["force_current_day"] = force_current_day
        return {"dict": None, "members": {}, "bar": None,
                "fund_flow": None, "failed": []}

    monkeypatch.setattr(ingest_mod.IngestionService, "ingest_board", fake_ingest_board, raising=True)
    monkeypatch.setattr(ingest_mod.IngestionService, "__init__", lambda self, source=None: None, raising=True)
    svc = AsyncTaskService(client)
    task = svc.create("board", {"mode": "update", "force_current_day": True})

    assert _wait(svc, task)["status"] == "done"
    assert captured["force_current_day"] is True


def test_board_task_date_range_passthrough(client, monkeypatch):
    """板块手动指数区间在创建时校验，并以 date 类型透传采集编排。"""
    from datetime import date

    from backend.services import ingest as ingest_mod
    from backend.services.async_task import AsyncTaskService

    captured = {}

    def fake_ingest_board(self, ctx=None, board_type=None, board_codes=None,
                          mode="update", date_start=None, date_end=None):
        captured.update(date_start=date_start, date_end=date_end)
        return {"dict": None, "members": {}, "bar": None,
                "fund_flow": None, "failed": []}

    monkeypatch.setattr(ingest_mod.IngestionService, "ingest_board", fake_ingest_board, raising=True)
    monkeypatch.setattr(ingest_mod.IngestionService, "__init__", lambda self, source=None: None, raising=True)
    svc = AsyncTaskService(client)
    task = svc.create("board", {"mode": "update", "date_start": "2026-08-01",
                                "date_end": "2026-08-03"})

    assert _wait(svc, task)["status"] == "done"
    assert captured == {"date_start": date(2026, 8, 1), "date_end": date(2026, 8, 3)}
    with pytest.raises(ValueError, match="起始日期不能晚于结束日期"):
        svc.create("board", {"date_start": "2026-08-03", "date_end": "2026-08-01"})


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
    """局部失败保留 checkpoint 供续跑；续跑只处理剩余单元并可最终完成。"""
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
    # 部分失败标 failed 但保留 checkpoint（对齐数据管理文档「失败任务可续跑」），不丢成功单元
    assert task["status"] == "failed"
    assert "部分完成" in task["message"]
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


def test_quality_ignore_batch_marks_only_filtered_open_issues(client):
    """一键标记正常复用质量页筛选，只处理 open，并支持本次与整体两种范围。"""
    from backend.api.data_admin import quality_ignore_batch

    client.execute(
        "INSERT INTO board_dict (board_code, name, board_type) VALUES "
        "('309121','AI PC','concept'), ('881121','行业样例','industry')",
    )
    client.execute(
        "INSERT INTO data_quality_issue "
        "(id, code, issue_type, severity, status, detail, detected_at) VALUES "
        "(21, '309121', 'board_fund_missing', 'mid', 'open', '{}', now()), "
        "(22, '309121', 'board_fund_missing', 'mid', 'resolved', '{}', now()), "
        "(23, '309121', 'board_index_gap', 'mid', 'open', '{}', now()), "
        "(24, '881121', 'board_fund_missing', 'mid', 'open', '{}', now())")

    response = quality_ignore_batch({
        "issue_type": ["board_fund_missing"], "severity": ["mid"], "code": "AI PC",
    })

    assert response.code == 0
    assert response.data == {"count": 1, "status": "ignored", "ignore_scope": "occurrence"}
    rows = client.query_df(
        "SELECT id, status, ignore_scope, ignore_active, resolved_at "
        "FROM data_quality_issue ORDER BY id",
    ).set_index("id")
    assert rows.loc[21, "status"] == "ignored"
    assert rows.loc[21, "ignore_scope"] == "occurrence"
    assert bool(rows.loc[21, "ignore_active"])
    assert rows.loc[21, "resolved_at"] is not None
    assert rows.loc[22, "status"] == "resolved"
    assert rows.loc[23, "status"] == "open"
    assert rows.loc[24, "status"] == "open"

    object_response = quality_ignore_batch({
        "issue_type": ["board_fund_missing"], "code": "881121", "scope": "object",
    })
    assert object_response.code == 0
    assert object_response.data == {"count": 1, "status": "ignored", "ignore_scope": "object"}
    object_row = client.query_df(
        "SELECT status, ignore_scope, ignore_active FROM data_quality_issue WHERE id=24",
    ).iloc[0]
    assert object_row["status"] == "ignored"
    assert object_row["ignore_scope"] == "object"
    assert bool(object_row["ignore_active"])

    rejected = quality_ignore_batch({})
    assert rejected.code == 400
    invalid_scope = quality_ignore_batch({"issue_type": ["board_index_gap"], "scope": "forever"})
    assert invalid_scope.code == 400


def test_quality_list_searches_board_code_and_name(client):
    """质量列表的对象搜索与批量恢复共用口径，板块名称不再搜不到。"""
    from backend.api.data_admin import quality

    client.execute(
        "INSERT INTO board_dict (board_code, name, board_type) "
        "VALUES ('309121','AI PC','concept')")
    client.execute(
        "INSERT INTO data_quality_issue "
        "(id, code, issue_type, severity, status, detected_at) "
        "VALUES (21, '309121', 'board_index_invalid', 'mid', 'open', now())")

    by_name = quality(code="AI PC", status="open")
    by_code = quality(code="309121", status="open")
    assert by_name.code == 0 and by_name.data["total"] == 1
    assert by_code.code == 0 and by_code.data["total"] == 1
    assert by_name.data["list"][0]["name"] == "AI PC"


def test_quality_list_searches_market_index_code_and_name(client):
    """市场指数问题复用质量列表，并能按中文名称或代码搜索。"""
    from backend.api.data_admin import quality

    client.execute(
        "INSERT INTO data_quality_issue "
        "(id, code, issue_type, severity, status, detected_at) "
        "VALUES (22, '399006.SZ', 'market_index_gap', 'mid', 'open', now())"
    )
    by_name = quality(code="创业板指", status="open")
    by_code = quality(code="399006.SZ", status="open")
    assert by_name.code == 0 and by_name.data["total"] == 1
    assert by_code.code == 0 and by_code.data["total"] == 1
    assert by_name.data["list"][0]["name"] == "创业板指"


def test_quality_actions_reject_conflicting_status_transitions(client, monkeypatch):
    """已解决不能再恢复，运行中的 fixing 不能被忽略或手工复位。"""
    from backend.api import data_admin
    from backend.api.data_admin import quality_fix, quality_ignore, quality_reset

    now = datetime.now()
    runtime = DuckDBClient(db_path=":memory:")
    init_db(runtime)
    runtime.execute(
        "INSERT INTO async_task "
        "(id, task_type, params, status, progress, created_at, updated_at) "
        "VALUES ('fix_running', 'fix', '{}', 'running', 0.5, ?, ?)",
        [now, now],
    )
    monkeypatch.setattr(data_admin, "get_task_runtime_client", lambda: runtime)
    client.execute(
        "INSERT INTO data_quality_issue "
        "(id, code, issue_type, severity, status, fix_task_id, detected_at) VALUES "
        "(31, '309121', 'board_index_gap', 'mid', 'resolved', NULL, now()), "
        "(32, '309121', 'board_index_gap', 'mid', 'fixing', 'fix_running', now())")

    assert quality_fix(31).code == 400
    assert quality_ignore(32).code == 409
    assert quality_reset(32).code == 409
    state = client.query_df(
        "SELECT status, fix_task_id FROM data_quality_issue WHERE id=32").iloc[0]
    assert state["status"] == "fixing" and state["fix_task_id"] == "fix_running"
    runtime.close()


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
    client.execute(
        "INSERT INTO board_bar (board_code, trade_date, open, high, low, close, volume, amount) "
        "VALUES ('309121', DATE '2026-08-07', 99, 101, 98, 100, 1000, 100000)")
    client.execute(
        "INSERT INTO board_bar (board_code, trade_date, open, high, low, close, volume, amount) "
        "VALUES ('881121', DATE '2026-08-06', 199, 201, 198, 200, 1000, 200000)")
    # 资金流快照整体停留在 08-06（滞后全局最新交易日 08-07 → 触发源级资金流滞后）
    client.execute("INSERT INTO board_fund_flow (board_code, snapshot_date, period, inflow, outflow, net_inflow) "
                   "VALUES ('309121', DATE '2026-08-06', '即时', 1.0, 0.5, 0.5)")


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


def test_scan_board_quality_index_gap_daily(client, monkeypatch):
    """板块指数逐日缺口扫描：近窗口内缺失的每个开市日都生成 issue。"""
    from backend.services.data_report import DataIntegrityReport
    _seed_board_scan(client)
    # 确保全局最新交易日在 trade_calendar 中被识别为开市日
    client.execute(
        "INSERT INTO trade_calendar (trade_date, is_open) VALUES (DATE '2026-08-07', TRUE) "
        "ON CONFLICT DO NOTHING")
    r = DataIntegrityReport(client).scan_board_quality()
    assert r["index_gap_daily"] >= 1
    daily = client.query_df(
        "SELECT code, trade_date FROM data_quality_issue "
        "WHERE issue_type='board_index_gap_daily' AND status='open'")
    # 半导体只有 08-06，缺全局最新交易日 08-07；AI PC 正常
    codes = set(daily["code"].astype(str).tolist())
    assert "881121" in codes
    assert "309121" not in codes


def test_scan_board_quality_index_gap_daily_ignored(client, monkeypatch):
    """板块指数逐日缺口：ignored 只豁免同一日期，后续日期仍须上报。"""
    from backend.services.data_report import DataIntegrityReport
    _seed_board_scan(client)
    client.execute(
        "INSERT INTO trade_calendar (trade_date, is_open) VALUES (DATE '2026-08-07', TRUE) "
        "ON CONFLICT DO NOTHING")
    client.execute(
        "INSERT INTO data_quality_issue "
        "(id, code, trade_date, issue_type, severity, status, detected_at) "
        "VALUES (990, '881121', DATE '2026-08-06', "
        "'board_index_gap_daily', 'mid', 'ignored', now())")
    rep = DataIntegrityReport(client)
    rep.scan_board_quality()
    daily = client.query_df(
        "SELECT code, trade_date FROM data_quality_issue "
        "WHERE issue_type='board_index_gap_daily' AND status='open'")
    hits = daily[daily["code"].astype(str) == "881121"]
    assert len(hits) == 1
    assert pd.Timestamp(hits.iloc[0]["trade_date"]).date() == date(2026, 8, 7)


def test_scan_board_quality_index_gap_daily_ignored_same_date(client):
    """板块指数逐日缺口：同一日期已 ignored 时不得重新生成 open。"""
    _seed_board_scan(client)
    client.execute(
        "INSERT INTO trade_calendar (trade_date, is_open) VALUES (DATE '2026-08-07', TRUE) "
        "ON CONFLICT DO NOTHING")
    client.execute(
        "INSERT INTO data_quality_issue "
        "(id, code, trade_date, issue_type, severity, status, detected_at) "
        "VALUES (991, '881121', DATE '2026-08-07', "
        "'board_index_gap_daily', 'mid', 'ignored', now())")

    DataIntegrityReport(client).scan_board_quality()

    daily = client.query_df(
        "SELECT status FROM data_quality_issue "
        "WHERE code='881121' AND trade_date=DATE '2026-08-07' "
        "AND issue_type='board_index_gap_daily'")
    assert daily["status"].tolist() == ["ignored"]


def test_board_scan_upsert_rechecks_ignored_before_write(client):
    """板块扫描落库前重读 ignored，计算期间人工忽略的同键不得被重新打开。"""
    client.execute(
        "INSERT INTO data_quality_issue "
        "(id, code, trade_date, issue_type, severity, status, detected_at) "
        "VALUES (994, '881121', DATE '2026-08-07', "
        "'board_index_gap_daily', 'mid', 'ignored', now())")

    with client.transaction():
        DataIntegrityReport(client)._upsert_scan_issues(
            [{
                "code": "881121",
                "trade_date": date(2026, 8, 7),
                "issue_type": "board_index_gap_daily",
                "detail": "扫描开始后被人工忽略",
            }],
            ("board_index_gap_daily",),
        )

    issues = client.query_df(
        "SELECT status FROM data_quality_issue "
        "WHERE code='881121' AND trade_date=DATE '2026-08-07' "
        "AND issue_type='board_index_gap_daily'")
    assert issues["status"].tolist() == ["ignored"]


def test_scan_board_quality_keeps_open_ids(client, monkeypatch):
    """板块重扫复用 open id：同键（type+code+trade_date）问题原地更新，不 DELETE+重建。

    回归 2026-08-15：旧实现每次扫描 DELETE open 再重建，id 全换——板块 fix 修完即重扫，
    批量任务后续待修 issue 的旧 id 会被作废（'质检问题不存在'）。复用后 id 跨扫描稳定。
    """
    from backend.services.data_report import DataIntegrityReport
    _seed_board_scan(client)
    client.execute(
        "INSERT INTO trade_calendar (trade_date, is_open) VALUES (DATE '2026-08-07', TRUE) "
        "ON CONFLICT DO NOTHING")
    # 预置 open 行须带与扫描同键的 trade_date：gap 键=全局最新交易日 08-07；daily 键=缺失日 08-07
    client.execute("INSERT INTO data_quality_issue "
                   "(id, code, issue_type, trade_date, severity, status, detected_at) "
                   "VALUES (901, '881121', 'board_index_gap', DATE '2026-08-07', 'mid', 'open', now())")
    client.execute("INSERT INTO data_quality_issue "
                   "(id, code, issue_type, trade_date, severity, status, detected_at) "
                   "VALUES (902, '881121', 'board_index_gap_daily', DATE '2026-08-07', 'mid', 'open', now())")
    rep = DataIntegrityReport(client)
    r1 = rep.scan_board_quality()
    assert r1["index_gap"] == 1 and r1["index_gap_daily"] >= 1
    first = client.query_df(
        "SELECT id, code, trade_date, detail FROM data_quality_issue "
        "WHERE issue_type='board_index_gap' AND status='open'").iloc[0]
    assert int(first["id"]) == 901                 # 同键复用，id 不换
    assert "半导体" in str(first["detail"])        # detail 原位刷新
    daily_kept = client.query_df(
        "SELECT id FROM data_quality_issue "
        "WHERE issue_type='board_index_gap_daily' AND status='open' AND code='881121'")
    assert len(daily_kept) == 1 and int(daily_kept.iloc[0]["id"]) == 902   # 同键复用，id 不换
    r2 = rep.scan_board_quality()
    second = client.query_df(
        "SELECT id FROM data_quality_issue "
        "WHERE issue_type='board_index_gap' AND status='open'").iloc[0]
    assert int(second["id"]) == 901                # 连续扫描 id 保持稳定


def test_scan_board_quality_resolves_missing_open_no_rebuild(client, monkeypatch):
    """板块重扫对已修复的 open 问题不删不重建：同键复用收敛为 resolved（id 保留）。

    数据追平后旧 open 行不再出现在扫描结果里 → 复用其 id 收敛为已解决，而非 DELETE。
    id 跨扫描稳定；批量 fix 里后续条目即使已被重扫收敛，按旧 id 复检仍可走良性跳过闭环。
    """
    from backend.services.data_report import DataIntegrityReport
    _seed_board_scan(client)
    client.execute(
        "INSERT INTO trade_calendar (trade_date, is_open) VALUES (DATE '2026-08-07', TRUE) "
        "ON CONFLICT DO NOTHING")
    client.execute("INSERT INTO data_quality_issue "
                   "(id, code, issue_type, trade_date, severity, status, detected_at) "
                   "VALUES (903, '881121', 'board_index_gap_daily', DATE '2026-08-07', 'mid', 'open', now())")
    rep = DataIntegrityReport(client)
    rep.scan_board_quality()
    # 数据追平最新交易日 08-07：缺漏消失
    client.execute(
        "INSERT INTO board_bar (board_code, trade_date, open, high, low, close, volume, amount) "
        "VALUES ('881121', DATE '2026-08-07', 200, 201, 199, 200, 1000, 200000)")
    rep.scan_board_quality()
    row = client.query_df(
        "SELECT id, status FROM data_quality_issue WHERE id=903")
    assert not row.empty                       # 行保留（未 DELETE）
    assert int(row.iloc[0]["id"]) == 903       # id 不变（未重建）
    assert row.iloc[0]["status"] == "resolved" # 同键复用收敛为已解决


def test_scan_board_quality_index_gap_daily_late_board(client, monkeypatch):
    """板块指数逐日缺口：晚成立板块在数据起点（最早 bar 日）之前的缺失不报。

    板块成立前源端本无数据，起点之前的缺口属正常（不靠人工 ignore，
    每季新板块如「xx一季报预增」自动豁免）；起点之后缺失照报漏采。
    """
    from backend.services.data_report import DataIntegrityReport
    _seed_board_scan(client)
    client.execute(
        "INSERT INTO trade_calendar (trade_date, is_open) VALUES (DATE '2026-08-07', TRUE) "
        "ON CONFLICT DO NOTHING")
    # 晚成立板块：只有 08-07 一天指数（成立日），08-06 及更早源端无数据
    client.execute("INSERT INTO board_dict (board_code, name, board_type, has_members, has_bar, member_count) "
                   "VALUES ('309265','2026一季报预增','concept',TRUE,TRUE,20)")
    client.execute(
        "INSERT INTO board_bar (board_code, trade_date, open, high, low, close, volume, amount) "
        "VALUES ('309265', DATE '2026-08-07', 100, 101, 99, 100, 500, 50000)")
    rep = DataIntegrityReport(client)
    rep.scan_board_quality()
    daily = client.query_df(
        "SELECT code, trade_date FROM data_quality_issue "
        "WHERE issue_type='board_index_gap_daily' AND status='open'")
    codes = set(daily["code"].astype(str).tolist())
    assert "309265" not in codes          # 成立前缺失豁免
    assert "881121" in codes              # 老板块成立后缺失照报（半导体缺 08-07）


def test_scan_board_quality_index_gap_daily_post_start_missing(client, monkeypatch):
    """板块指数逐日缺口：数据起点之后的真实空洞不豁免，仍报缺采。"""
    from backend.services.data_report import DataIntegrityReport
    _seed_board_scan(client)
    client.execute(
        "INSERT INTO trade_calendar (trade_date, is_open) VALUES (DATE '2026-08-07', TRUE) "
        "ON CONFLICT DO NOTHING")
    # 晚成立板块但起点之后出现空洞：08-03 成立，缺 08-07（起点后）→ 必须报
    client.execute("INSERT INTO board_dict (board_code, name, board_type, has_members, has_bar, member_count) "
                   "VALUES ('309268','2026中报预增','concept',TRUE,TRUE,20)")
    for d in ("2026-08-03", "2026-08-06"):
        client.execute(
            "INSERT INTO board_bar (board_code, trade_date, open, high, low, close, volume, amount) "
            f"VALUES ('309268', DATE '{d}', 100, 101, 99, 100, 500, 50000)")
    rep = DataIntegrityReport(client)
    rep.scan_board_quality()
    daily = client.query_df(
        "SELECT code, trade_date FROM data_quality_issue "
        "WHERE issue_type='board_index_gap_daily' AND status='open'")
    hits = daily[daily["code"].astype(str) == "309268"]
    assert len(hits) == 1                  # 起点后只缺 08-07 这一处
    assert pd.Timestamp(hits.iloc[0]["trade_date"]).date() == date(2026, 8, 7)


def test_board_recheck_index_gap_daily(client, monkeypatch):
    """板块指数逐日缺口复检：缺失日补齐后收敛，板块移除/无指数能力后也收敛。"""
    from backend.services.data_report import DataIntegrityReport
    _seed_board_scan(client)
    rep = DataIntegrityReport(client)
    # 半导体缺 08-07
    assert rep.recheck_clean("board_index_gap_daily", "881121", date(2026, 8, 7)) is False
    client.execute(
        "INSERT INTO board_bar (board_code, trade_date, close) "
        "VALUES ('881121', DATE '2026-08-07', 200.0)")
    assert rep.recheck_clean("board_index_gap_daily", "881121", date(2026, 8, 7)) is True
    # has_bar=false 视为收敛
    client.execute("UPDATE board_dict SET has_bar=FALSE WHERE board_code='881121'")
    assert rep.recheck_clean("board_index_gap_daily", "881121", date(2026, 8, 7)) is True


def test_scan_and_recheck_board_index_invalid(client):
    """板块指数有记录不等于可用：OHLC 越界会入台账，覆盖正常值后收敛。"""
    from backend.services.data_report import DataIntegrityReport

    _seed_board_scan(client)
    client.execute(
        "UPDATE board_bar SET open=220, high=210, low=190, close=200 "
        "WHERE board_code='881121' AND trade_date=DATE '2026-08-06'")
    rep = DataIntegrityReport(client)
    result = rep.scan_board_quality()
    assert result["index_invalid"] == 1
    invalid = client.query_df(
        "SELECT code, trade_date FROM data_quality_issue "
        "WHERE issue_type='board_index_invalid' AND status='open'")
    assert invalid["code"].tolist() == ["881121"]
    assert rep.recheck_clean(
        "board_index_invalid", "881121", date(2026, 8, 6)) is False
    client.execute(
        "UPDATE board_bar SET open=200, high=210, low=190, close=200 "
        "WHERE board_code='881121' AND trade_date=DATE '2026-08-06'")
    assert rep.recheck_clean(
        "board_index_invalid", "881121", date(2026, 8, 6)) is True
    client.execute(
        "DELETE FROM board_bar WHERE board_code='881121' AND trade_date=DATE '2026-08-06'")
    assert rep.recheck_clean(
        "board_index_invalid", "881121", date(2026, 8, 6)) is False


def test_scan_board_index_invalid_ignored_is_date_exact(client):
    """板块指数非法值：历史日期 ignored 不得屏蔽同板块新日期的问题。"""
    _seed_board_scan(client)
    client.execute(
        "UPDATE board_bar SET open=220, high=210, low=190, close=200 "
        "WHERE board_code='881121' AND trade_date=DATE '2026-08-06'")
    client.execute(
        "INSERT INTO data_quality_issue "
        "(id, code, trade_date, issue_type, severity, status, detected_at) "
        "VALUES (992, '881121', DATE '2026-08-05', "
        "'board_index_invalid', 'mid', 'ignored', now())")

    DataIntegrityReport(client).scan_board_quality()

    invalid = client.query_df(
        "SELECT trade_date, status FROM data_quality_issue "
        "WHERE code='881121' AND issue_type='board_index_invalid' ORDER BY trade_date")
    assert invalid["status"].tolist() == ["ignored", "open"]
    assert pd.Timestamp(invalid.iloc[1]["trade_date"]).date() == date(2026, 8, 6)


def test_l1_record_respects_ignored_same_date(client):
    """L1 单日问题：同日 ignored 不重开，其他日期仍正常上报。"""
    from backend.services.ingest import IngestionService

    client.execute(
        "INSERT INTO data_quality_issue "
        "(id, code, trade_date, issue_type, severity, status, detected_at) "
        "VALUES (993, 'A.SH', DATE '2026-08-06', 'ohl_repaired', 'low', 'ignored', now())")
    svc = IngestionService.__new__(IngestionService)
    svc.c = client

    svc._record_issues(
        "A.SH", [date(2026, 8, 6), date(2026, 8, 7)], "ohl_repaired", "开高低异常")

    issues = client.query_df(
        "SELECT trade_date, status FROM data_quality_issue "
        "WHERE code='A.SH' AND issue_type='ohl_repaired' ORDER BY trade_date")
    assert issues["status"].tolist() == ["ignored", "open"]


def test_scan_board_quality_member_never_collected(client):
    """字典声明支持成分但从未形成完整快照时，主动补建质检问题。"""
    from backend.services.data_report import DataIntegrityReport

    _seed_board_scan(client)
    result = DataIntegrityReport(client).scan_board_quality()
    assert result["member_incomplete"] == 2
    issues = client.query_df(
        "SELECT code, detail FROM data_quality_issue "
        "WHERE issue_type='board_member_incomplete' AND status='open'")
    assert set(issues["code"].tolist()) == {"309121", "881121"}
    assert all('"reason_type": "never_collected"' in str(x) for x in issues["detail"])


def test_scan_board_quality_fund_missing(client, monkeypatch):
    """资金流缺失扫描：字典中有成分/指数但源未收录资金流的板块写 issue。"""
    from backend.services.data_report import DataIntegrityReport
    _seed_board_scan(client)
    # AI PC 有成分/指数但无资金流 → 缺失；半导体同样
    r = DataIntegrityReport(client).scan_board_quality()
    assert r["fund_missing"] == 2
    missing = client.query_df(
        "SELECT code, issue_type, trade_date FROM data_quality_issue WHERE issue_type='board_fund_missing'")
    assert set(missing["code"].tolist()) == {"309121", "881121"}
    # 日期列：资金流缺失带全局最新交易日（质量页日期列不空）
    assert set(missing["trade_date"].astype(str)) == {"2026-08-07"}


def test_fix_board_fund_missing_targets_periods(client, monkeypatch):
    """资金流缺失 fix：按 issue detail 里的周期列表定向重采，不拉全周期。"""
    import json
    from backend.services.async_task import TaskContext
    from backend.services.board_ingest import BoardIngestService
    from backend.services.data_report import DataIntegrityReport

    _seed_board_scan(client)
    captured: dict = {}

    def fake_ingest_fund(self, snapshot_date=None, periods=None, board_codes=None,
                         board_type=None, ctx=None):
        captured["snapshot_date"] = snapshot_date
        captured["periods"] = periods
        captured["board_codes"] = board_codes
        # 模拟重采写入缺失周期（即时已存在，补 3日）
        for period in periods or ():
            self.c.execute(
                "INSERT INTO board_fund_flow "
                "(board_code, snapshot_date, period, inflow, outflow, net_inflow) "
                "VALUES ('309121', DATE '2026-08-07', ?, 1.0, 0.5, 0.5)", [period])
        return {"rows": 3, "unmatched": 0}

    monkeypatch.setattr(BoardIngestService, "ingest_board_fund_flow", fake_ingest_fund, raising=True)
    rep = DataIntegrityReport(client)
    # 插入一条缺 3日 周期的 issue（detail 带 periods）
    client.execute(
        "INSERT INTO data_quality_issue "
        "(id, code, trade_date, issue_type, severity, status, detail, detected_at) "
        "VALUES (500, '309121', DATE '2026-08-07', 'board_fund_missing', 'mid', 'open', ?, now())",
        [json.dumps({"periods": ["3日"], "message": "板块 AI PC（309121）资金流缺周期3日"})])
    from backend.services.async_task import _recover_one
    clean, affected, note = _recover_one(client, rep, None, TaskContext(
        AsyncTaskService(client), "t_fix", {}), 500)
    # 定向重采只传缺失周期与指定板块
    assert captured["snapshot_date"] == date(2026, 8, 7)
    assert captured["periods"] == ("3日",)
    assert captured["board_codes"] == ["309121"]
    # 重采后复检通过（3日 已追平）→ 可收敛
    assert clean is True
    assert "重采资金流" in note


def test_scan_board_quality_fund_missing_ignored_and_converge(client, monkeypatch):
    """资金流缺失：ignored 豁免 + 资金流采到后重扫收敛。"""
    from backend.services.data_report import DataIntegrityReport
    _seed_board_scan(client)
    client.execute("INSERT INTO data_quality_issue "
                   "(id, code, issue_type, severity, status, detected_at) "
                   "VALUES (998, '309121', 'board_fund_missing', 'mid', 'ignored', now())")
    rep = DataIntegrityReport(client)
    r = rep.scan_board_quality()
    # ignored 的 309121 豁免：本轮不再上报为 open，只剩 881121
    assert r["fund_missing"] == 1
    missing = client.query_df(
        "SELECT code FROM data_quality_issue "
        "WHERE issue_type='board_fund_missing' AND status='open'")
    assert missing["code"].tolist() == ["881121"]
    # 资金流追平最新交易日 → 重扫不再上报；不依赖粘性能力标记。
    # 多周期口径：该板块 5 个周期都须追平才算不缺（任一周期缺仍报 missing）。
    for period in ("即时", "3日", "5日", "10日", "20日"):
        client.execute(
            "INSERT INTO board_fund_flow "
            "(board_code, snapshot_date, period, inflow, outflow, net_inflow) "
            "VALUES ('881121', DATE '2026-08-07', ?, 1.0, 0.5, 0.5)", [period])
    r2 = rep.scan_board_quality()
    assert r2["fund_missing"] == 0
    left = client.query_df(
        "SELECT count(*) n FROM data_quality_issue "
        "WHERE issue_type='board_fund_missing' AND status='open'")
    assert int(left.iloc[0]["n"]) == 0


def test_board_recheck_fund_missing(client, monkeypatch):
    """资金流缺失复检：issue 列出的各周期快照都追平最新交易日才收敛。"""
    from backend.services.data_report import DataIntegrityReport
    _seed_board_scan(client)
    rep = DataIntegrityReport(client)
    # 未采到资金流 → 复检 False（问题仍 open）
    assert rep.recheck_clean("board_fund_missing", "309121", None) is False
    # 能力标记不能让历史快照假解决
    client.execute("UPDATE board_dict SET has_fund_flow=TRUE WHERE board_code='309121'")
    assert rep.recheck_clean("board_fund_missing", "309121", None) is False
    # 无 detail 的旧 issue 默认按即时复检：补即时即收敛（旧格式兼容）
    client.execute(
        "INSERT INTO board_fund_flow "
        "(board_code, snapshot_date, period, inflow, outflow, net_inflow) "
        "VALUES ('309121', DATE '2026-08-07', '即时', 2.0, 1.0, 1.0)")
    assert rep.recheck_clean("board_fund_missing", "309121", None) is True
    # 新格式 detail 带 periods：只补即时不够，须各周期都追平才收敛
    client.execute("DELETE FROM board_fund_flow WHERE board_code='309121'")
    detail = {"periods": ["即时", "3日", "5日", "10日", "20日"]}
    assert rep.recheck_clean("board_fund_missing", "309121", None, detail=detail) is False
    for period in ("即时", "3日", "5日", "10日", "20日"):
        client.execute(
            "INSERT INTO board_fund_flow "
            "(board_code, snapshot_date, period, inflow, outflow, net_inflow) "
            "VALUES ('309121', DATE '2026-08-07', ?, 2.0, 1.0, 1.0)", [period])
    assert rep.recheck_clean("board_fund_missing", "309121", None, detail=detail) is True
    # 板块不在字典 → True（已被移除，无可修复对象）
    assert rep.recheck_clean("board_fund_missing", "no-such-board", None) is True


def test_board_fund_missing_future_snapshot_does_not_replace_trade_date(client):
    """未来日期快照不能让当前行情截面的资金流缺失误收敛。"""
    from backend.services.data_report import DataIntegrityReport

    _seed_board_scan(client)
    for period in ("即时", "3日", "5日", "10日", "20日"):
        client.execute(
            "INSERT INTO board_fund_flow "
            "(board_code, snapshot_date, period, inflow, outflow, net_inflow) "
            "VALUES ('309121', DATE '2026-08-08', ?, 2.0, 1.0, 1.0)", [period])

    rep = DataIntegrityReport(client)
    result = rep.scan_board_quality()
    missing = client.query_df(
        "SELECT trade_date FROM data_quality_issue "
        "WHERE issue_type='board_fund_missing' AND code='309121' AND status='open'")

    assert result["fund_missing"] == 2
    assert missing["trade_date"].astype(str).tolist() == ["2026-08-07"]
    assert rep.recheck_clean(
        "board_fund_missing", "309121", date(2026, 8, 7),
        detail={"periods": ["即时", "3日", "5日", "10日", "20日"]},
    ) is False


def test_scan_board_quality_fund_stale(client, monkeypatch):
    """资金流滞后扫描：有快照但滞后的周期记单条源级 issue（detail 结构化列滞后周期）。"""
    import json
    from backend.services.data_report import DataIntegrityReport
    _seed_board_scan(client)
    client.execute("INSERT INTO trade_calendar VALUES ('2026-08-06',TRUE),('2026-08-07',TRUE)")
    r = DataIntegrityReport(client).scan_board_quality()
    assert r["fund_stale"] == 1
    stale = client.query_df(
        "SELECT code, trade_date, detail FROM data_quality_issue WHERE issue_type='board_fund_stale'")
    assert len(stale) == 1
    assert stale.iloc[0]["code"] is None   # 源级单条，无 code
    assert str(stale.iloc[0]["trade_date"])[:10] == "2026-08-07"  # 日期 = 全局最新交易日
    payload = json.loads(stale.iloc[0]["detail"])
    assert "滞后 1 个交易日" in payload["message"]
    assert payload["periods"] == ["即时"]  # seed 只有即时有快照且滞后


def test_scan_board_quality_fund_stale_keeps_null_code_id(client, monkeypatch):
    """源级资金流滞后（code=NULL）重扫复用 id：同键收敛不因 NULL code 规范化漂移。

    回归 2026-08-15：`str(None)`≠`None` 会导致 code=NULL 的 stale 问题每次扫描
    都被当成"已消失"收敛又重建，id 仍漂移；规范化后同键稳定。
    """
    from backend.services.data_report import DataIntegrityReport
    _seed_board_scan(client)
    rep = DataIntegrityReport(client)
    client.execute("INSERT INTO data_quality_issue "
                   "(id, code, issue_type, trade_date, severity, status, detected_at) "
                   "VALUES (910, NULL, 'board_fund_stale', DATE '2026-08-07', 'mid', 'open', now())")
    rep.scan_board_quality()
    row = client.query_df(
        "SELECT id, status FROM data_quality_issue "
        "WHERE issue_type='board_fund_stale' AND status='open'")
    assert len(row) == 1 and int(row.iloc[0]["id"]) == 910   # 同键复用，id 不换
    rep.scan_board_quality()
    row2 = client.query_df(
        "SELECT id FROM data_quality_issue "
        "WHERE issue_type='board_fund_stale' AND status='open'")
    assert len(row2) == 1 and int(row2.iloc[0]["id"]) == 910  # 连续扫描 id 稳定


def test_scan_board_quality_fund_stale_converge(client, monkeypatch):
    """资金流滞后收敛：快照追平最新交易日 + ignored 豁免后重扫不再上报。"""
    from backend.services.data_report import DataIntegrityReport
    _seed_board_scan(client)
    rep = DataIntegrityReport(client)
    # 快照追平：补 08-07 快照 → 滞后消除
    client.execute("INSERT INTO board_fund_flow (board_code, snapshot_date, period, inflow, outflow, net_inflow) "
                   "VALUES ('309121', DATE '2026-08-07', '即时', 2.0, 1.0, 1.0)")
    r = rep.scan_board_quality()
    assert r["fund_stale"] == 0
    left = client.query_df(
        "SELECT count(*) n FROM data_quality_issue WHERE issue_type='board_fund_stale' AND status='open'")
    assert int(left.iloc[0]["n"]) == 0


def test_fix_board_fund_stale_targets_trade_date_and_periods(client, monkeypatch):
    """资金流滞后 fix：按问题交易日和 detail 周期重采，避免写入当前自然日。"""
    import json

    from backend.services.async_task import TaskContext, _recover_one
    from backend.services.board_ingest import BoardIngestService

    _seed_board_scan(client)
    captured: dict = {}

    def fake_ingest_fund(self, snapshot_date=None, periods=None, board_codes=None,
                         board_type=None, ctx=None):
        captured["snapshot_date"] = snapshot_date
        captured["periods"] = periods
        self.c.execute(
            "INSERT INTO board_fund_flow "
            "(board_code, snapshot_date, period, inflow, outflow, net_inflow) "
            "VALUES ('309121', ?, '即时', 2.0, 1.0, 1.0)", [snapshot_date])
        return {"rows": 1, "unmatched": 0, "failed": []}

    monkeypatch.setattr(BoardIngestService, "ingest_board_fund_flow", fake_ingest_fund, raising=True)
    client.execute(
        "INSERT INTO data_quality_issue "
        "(id, code, trade_date, issue_type, severity, status, detail, detected_at) "
        "VALUES (501, NULL, DATE '2026-08-07', 'board_fund_stale', 'mid', 'open', ?, now())",
        [json.dumps({"periods": ["即时"]})])

    clean, _, note = _recover_one(
        client, DataIntegrityReport(client), None,
        TaskContext(AsyncTaskService(client), "t_fix_stale", {}), 501)

    assert captured == {"snapshot_date": date(2026, 8, 7), "periods": ("即时",)}
    assert clean is True
    assert "重采资金流" in note


def test_board_recheck_fund_stale(client, monkeypatch):
    """资金流滞后复检：无 detail 旧格式检查所有有快照的周期；带 periods 只查报出的滞后周期。"""
    import json
    from backend.services.data_report import DataIntegrityReport
    _seed_board_scan(client)
    rep = DataIntegrityReport(client)
    # 无 detail（旧纯文本 issue 兼容）：seed 只有即时有快照（08-06 滞后）→ 未收敛
    assert rep.recheck_clean("board_fund_stale", None, None) is False
    # 补即时到 08-07：唯一有快照的周期已追平 → 收敛（从未有快照的周期由 missing 覆盖，不算 stale）
    client.execute("INSERT INTO board_fund_flow (board_code, snapshot_date, period, inflow, outflow, net_inflow) "
                   "VALUES ('309121', DATE '2026-08-07', '即时', 2.0, 1.0, 1.0)")
    assert rep.recheck_clean("board_fund_stale", None, None) is True
    # 新格式 detail 带 periods：只复检报出的滞后周期。报 3日 滞后，即使即时已追平仍 False
    stale_detail = json.dumps({"periods": ["3日"], "message": "资金流滞后"})
    assert rep.recheck_clean("board_fund_stale", None, None, detail=stale_detail) is False
    # 3日 追平 → 收敛
    client.execute("INSERT INTO board_fund_flow (board_code, snapshot_date, period, inflow, outflow, net_inflow) "
                   "VALUES ('309121', DATE '2026-08-07', '3日', 2.0, 1.0, 1.0)")
    assert rep.recheck_clean("board_fund_stale", None, None, detail=stale_detail) is True



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
    assert s.ths_board.timeout_sec is None
    assert s.ths_board.max_retries is None
    assert s.ths_board.retry_backoff_sec is None
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
                        lambda self, snapshot_date=None, board_codes=None, ctx=None, **kwargs:
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


def test_board_update_uses_latest_open_day(client, monkeypatch, eod_session):
    """板块 update 指数区间复用现有交易日语义（_latest_open_day），非裸 today。"""
    from backend.services import ingest as ingest_mod
    from backend.services.board_ingest import BoardIngestService
    from backend.services.ingest import IngestionService

    eod_session(client, date(2026, 8, 7))

    captured = {}

    def fake_ingest_board_dict(self, snapshot_date=None, board_type=None, ctx=None):
        captured["dict_type"] = board_type
        return {"concept": 375, "industry": 90, "total": 465}

    def fake_ingest_board_members(self, snapshot_date=None, board_codes=None,
                                  board_type=None, ctx=None, **kwargs):
        captured["member_type"] = board_type
        return {}

    def fake_ingest_board_bar(self, start, end=None, board_codes=None,
                              board_type=None, probe_ready=False,
                              resume_from_latest=False, ctx=None):
        captured["bar_type"] = board_type
        captured["probe_ready"] = probe_ready
        captured["start"] = start
        captured["end"] = end
        captured["resume_from_latest"] = resume_from_latest
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
    # 指数按各板块最新水位续采，不再使用统一 7 天窗口。
    assert captured["start"] is None
    assert captured["end"] == date(2026, 8, 7)
    assert captured["resume_from_latest"] is True
    # 全量增量开启源端就绪探测（指定板块重采才关）
    assert captured["probe_ready"] is True
    # 资金流：update 每日刷新全周期（periods=None → 默认全周期）
    assert captured["periods"] is None
    assert {captured[x] for x in ("dict_type", "member_type", "bar_type", "fund_type")} == {
        "concept",
    }
    with pytest.raises(ValueError, match="concept/industry"):
        IngestionService().ingest_board(board_type="theme")


def test_board_fund_only_uses_latest_board_bar_date(client, monkeypatch, eod_session):
    """只采资金流锚定页面行情截面，不把开市但尚未出行情的今天提前入库。"""
    eod_session(client, date(2026, 8, 7), as_of=date(2026, 8, 10))
    from backend.services import ingest as ingest_mod
    from backend.services.board_ingest import BoardIngestService
    from backend.services.ingest import IngestionService

    captured = {}
    client.execute(
        "INSERT INTO board_dict (board_code, name, board_type, has_bar) "
        "VALUES ('309121', 'AI PC', 'concept', TRUE)")
    client.execute(
        "INSERT INTO board_bar (board_code, trade_date, close) "
        "VALUES ('309121', DATE '2026-08-07', 100.0)")

    def fake_ingest_board_fund_flow(self, snapshot_date=None, periods=None, board_codes=None,
                                    board_type=None, ctx=None):
        captured["snapshot_date"] = snapshot_date
        return {"rows": 0, "unmatched": 0, "failed": []}

    monkeypatch.setattr(BoardIngestService, "ingest_board_fund_flow",
                        fake_ingest_board_fund_flow, raising=True)
    monkeypatch.setattr(ingest_mod.IngestionService, "__init__",
                        lambda self, source=None: None, raising=True)
    monkeypatch.setattr(ingest_mod.IngestionService, "_latest_open_day",
                        lambda self: date(2026, 8, 10), raising=True)

    IngestionService().ingest_board(
        mode="update", only=["fund"], board_codes=["309121"])

    assert captured["snapshot_date"] == date(2026, 8, 7)


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


def test_ingest_board_only_selects_tables(client, monkeypatch, eod_session):
    """only 分表：only=["bar"] 时只跑指数，不跑字典/成分/资金流。"""
    eod_session(client, date(2026, 8, 7))
    from backend.services import ingest as ingest_mod
    from backend.services.ingest import IngestionService
    from backend.services.board_ingest import BoardIngestService

    called = {"dict": 0, "members": 0, "bar": 0, "fund": 0}

    monkeypatch.setattr(BoardIngestService, "ingest_board_dict",
                        lambda self, snapshot_date=None, board_type=None, ctx=None:
                        called.__setitem__("dict", 1) or {"total": 0}, raising=True)
    monkeypatch.setattr(BoardIngestService, "ingest_board_members",
                        lambda self, snapshot_date=None, board_codes=None, board_type=None, ctx=None, **kwargs:
                        called.__setitem__("members", 1) or {}, raising=True)
    monkeypatch.setattr(BoardIngestService, "ingest_board_bar",
                        lambda self, start, end=None, board_codes=None, board_type=None,
                        probe_ready=False, resume_from_latest=False, ctx=None:
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
    """board_index_gap fix：补最后已有日到全局最新日的末尾连续缺口。"""
    svc = AsyncTaskService(client)
    from backend.services import ingest
    from backend.services.board_ingest import BoardIngestService

    monkeypatch.setattr(ingest.IngestionService, "__init__", lambda self, source=None: None, raising=True)
    monkeypatch.setattr("backend.services.async_task._mark_snapshots_stale", lambda: 0)
    monkeypatch.setattr(BoardIngestService, "__init__",
                        lambda self, client=None, source=None: setattr(self, "c", client), raising=True)
    captured = {}

    def fake_ingest_board_bar(self, start, end=None, board_codes=None, ctx=None):
        captured.update({"start": start, "end": end, "board_codes": board_codes})
        self.c.execute(
            "INSERT INTO board_bar "
            "(board_code, trade_date, open, high, low, close, volume, amount) VALUES "
            "('309121', DATE '2026-08-06', 100, 101, 99, 100, 1000, 100000),"
            "('309121', DATE '2026-08-07', 100, 101, 99, 100, 1000, 100000)")
        return {"rows": 2, "boards": 1, "failed": []}

    monkeypatch.setattr(
        BoardIngestService, "ingest_board_bar", fake_ingest_board_bar, raising=True)
    client.execute("INSERT INTO board_dict (board_code, name, board_type, has_bar) "
                   "VALUES ('309121','AI PC','concept',TRUE)")
    client.execute("INSERT INTO daily_bar (code, trade_date, close) VALUES ('600000.SH', DATE '2026-08-07', 10.0)")
    client.execute(
        "INSERT INTO trade_calendar (trade_date, is_open) VALUES "
        "(DATE '2026-08-05', TRUE),(DATE '2026-08-06', TRUE),(DATE '2026-08-07', TRUE)")
    client.execute(
        "INSERT INTO board_bar "
        "(board_code, trade_date, open, high, low, close, volume, amount) "
        "VALUES ('309121', DATE '2026-08-05', 100, 101, 99, 100, 1000, 100000)")
    # issue 是旧扫描生成的 08-06；执行时全局已到 08-07，恢复仍须追到当前最新日。
    client.execute(
        "INSERT INTO data_quality_issue "
        "(id, code, trade_date, issue_type, severity, status, detected_at) "
        "VALUES (1, '309121', DATE '2026-08-06', 'board_index_gap', 'mid', 'open', now())")
    tid = svc.create("fix", {"issue_id": 1})
    _wait(svc, tid)
    row = client.query_df("SELECT status FROM data_quality_issue WHERE id=1").iloc[0]
    assert row["status"] == "resolved"
    assert captured == {
        "start": date(2026, 8, 6),
        "end": date(2026, 8, 7),
        "board_codes": ["309121"],
    }


def test_board_index_gap_fix_without_existing_bar_only_fetches_latest_day(client, monkeypatch):
    """从未入库的板块无法判断成立日，只补全局最新日，不再固定回采 2024 至今。"""
    svc = AsyncTaskService(client)
    from backend.services import ingest
    from backend.services.board_ingest import BoardIngestService

    monkeypatch.setattr(ingest.IngestionService, "__init__", lambda self, source=None: None, raising=True)
    monkeypatch.setattr("backend.services.async_task._mark_snapshots_stale", lambda: 0)
    monkeypatch.setattr(BoardIngestService, "__init__",
                        lambda self, client=None, source=None: setattr(self, "c", client), raising=True)
    captured = {}

    def fake_ingest_board_bar(self, start, end=None, board_codes=None, ctx=None):
        captured.update({"start": start, "end": end})
        self.c.execute(
            "INSERT INTO board_bar "
            "(board_code, trade_date, open, high, low, close, volume, amount) "
            "VALUES ('309268', DATE '2026-08-07', 100, 101, 99, 100, 1000, 100000)")
        return {"rows": 1, "boards": 1, "failed": []}

    monkeypatch.setattr(
        BoardIngestService, "ingest_board_bar", fake_ingest_board_bar, raising=True)
    client.execute("INSERT INTO board_dict (board_code, name, board_type, has_bar) "
                   "VALUES ('309268','中报预增','concept',TRUE)")
    client.execute("INSERT INTO daily_bar (code, trade_date, close) "
                   "VALUES ('600000.SH', DATE '2026-08-07', 10.0)")
    client.execute(
        "INSERT INTO data_quality_issue "
        "(id, code, trade_date, issue_type, severity, status, detected_at) "
        "VALUES (2, '309268', DATE '2026-08-07', 'board_index_gap', 'mid', 'open', now())")

    tid = svc.create("fix", {"issue_id": 2})
    _wait(svc, tid)

    row = client.query_df("SELECT status FROM data_quality_issue WHERE id=2").iloc[0]
    assert row["status"] == "resolved"
    assert captured == {"start": date(2026, 8, 7), "end": date(2026, 8, 7)}


def test_board_index_gap_fix_skips_remote_when_already_caught_up(client, monkeypatch):
    """旧问题执行前已被其它采集追平时直接复检，不重复请求板块源。"""
    svc = AsyncTaskService(client)
    from backend.services import ingest
    from backend.services.board_ingest import BoardIngestService

    monkeypatch.setattr(ingest.IngestionService, "__init__", lambda self, source=None: None, raising=True)
    monkeypatch.setattr("backend.services.async_task._mark_snapshots_stale", lambda: 0)
    monkeypatch.setattr(BoardIngestService, "__init__",
                        lambda self, client=None, source=None: setattr(self, "c", client), raising=True)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("板块指数已追平，不应再次请求源端")

    monkeypatch.setattr(BoardIngestService, "ingest_board_bar", fail_if_called, raising=True)
    client.execute("INSERT INTO board_dict (board_code, name, board_type, has_bar) "
                   "VALUES ('309121','AI PC','concept',TRUE)")
    client.execute("INSERT INTO daily_bar (code, trade_date, close) "
                   "VALUES ('600000.SH', DATE '2026-08-07', 10.0)")
    client.execute(
        "INSERT INTO board_bar "
        "(board_code, trade_date, open, high, low, close, volume, amount) "
        "VALUES ('309121', DATE '2026-08-07', 100, 101, 99, 100, 1000, 100000)")
    client.execute(
        "INSERT INTO data_quality_issue "
        "(id, code, trade_date, issue_type, severity, status, detected_at) "
        "VALUES (3, '309121', DATE '2026-08-07', 'board_index_gap', 'mid', 'open', now())")

    tid = svc.create("fix", {"issue_id": 3})
    _wait(svc, tid)

    row = client.query_df("SELECT status FROM data_quality_issue WHERE id=3").iloc[0]
    assert row["status"] == "resolved"


def test_board_index_gap_daily_fix_reingests_and_resolves(client, monkeypatch):
    """board_index_gap_daily fix：按缺失日窄窗口重采 → 复检通过 → resolved。"""
    svc = AsyncTaskService(client)
    from backend.services import ingest
    from backend.services.board_ingest import BoardIngestService

    monkeypatch.setattr(ingest.IngestionService, "__init__", lambda self, source=None: None, raising=True)
    monkeypatch.setattr("backend.services.async_task._mark_snapshots_stale", lambda: 0)
    monkeypatch.setattr(BoardIngestService, "__init__",
                        lambda self, client=None, source=None: setattr(self, "c", client), raising=True)
    captured = {}

    def fake_ingest_board_bar(self, start, end=None, board_codes=None, board_type=None, ctx=None):
        captured["start"] = start
        captured["end"] = end
        captured["board_codes"] = board_codes
        # 补回缺失的 08-07，使逐日缺口复检通过
        self.c.execute("INSERT INTO board_bar (board_code, trade_date, close) "
                       "VALUES ('309121', DATE '2026-08-07', 100.0)")
        return {"rows": 1, "boards": 1, "failed": []}

    monkeypatch.setattr(BoardIngestService, "ingest_board_bar", fake_ingest_board_bar, raising=True)
    client.execute("INSERT INTO board_dict (board_code, name, board_type, has_bar) "
                   "VALUES ('309121','AI PC','concept',TRUE)")
    client.execute("INSERT INTO daily_bar (code, trade_date, close) VALUES ('600000.SH', DATE '2026-08-07', 10.0)")
    client.execute("INSERT INTO data_quality_issue (id, code, trade_date, issue_type, severity, status, detected_at) "
                   "VALUES (1, '309121', DATE '2026-08-07', 'board_index_gap_daily', 'mid', 'open', now())")

    client.execute("INSERT INTO board_dict (board_code, name, board_type, has_bar) "
                   "VALUES ('never','从未采到指数','concept',TRUE)")
    tid = svc.create("fix", {"issue_id": 1})
    _wait(svc, tid)
    row = client.query_df("SELECT status FROM data_quality_issue WHERE id=1").iloc[0]
    assert row["status"] == "resolved"
    logs = client.query_df("SELECT level, message FROM task_log WHERE task_id=?", [tid])
    assert not logs["level"].isin(["warn", "error"]).any()
    assert any("板块关联问题复检完成" in msg for msg in logs["message"])
    assert captured["start"] == date(2026, 8, 7)
    assert captured["end"] == date(2026, 8, 7)
    assert captured["board_codes"] == ["309121"]


def test_board_index_batch_fix_survives_rescan_of_siblings(client, monkeypatch):
    """批量板块修复：第一条修完触发重扫不再作废后续 open issue 的 id。

    回归 2026-08-15：旧实现板块 fix 修完即重扫（DELETE+重建 open 板块问题），批量任务里
    其余待修 issue 的旧 id 会被重扫重排，循环后续按旧 id 查空报「质检问题不存在」。
    新实现同键复用 id，批量能跑完。
    """
    svc = AsyncTaskService(client)
    from backend.services import ingest
    from backend.services.board_ingest import BoardIngestService

    original_scan = DataIntegrityReport.scan_board_quality
    scopes = []
    def scoped_scan(report, **kwargs):
        scopes.append(kwargs.get("codes"))
        return original_scan(report, **kwargs)
    monkeypatch.setattr(DataIntegrityReport, "scan_board_quality", scoped_scan)

    monkeypatch.setattr(ingest.IngestionService, "__init__", lambda self, source=None: None, raising=True)
    monkeypatch.setattr("backend.services.async_task._mark_snapshots_stale", lambda: 0)
    monkeypatch.setattr(BoardIngestService, "__init__",
                        lambda self, client=None, source=None: setattr(self, "c", client), raising=True)
    # 重采一律把对应板块补到全局最新交易日，使复检通过（OHLC 完整，避免重扫报指数非法）
    def fake_ingest_board_bar(self, start, end=None, board_codes=None, board_type=None, ctx=None):
        for code in (board_codes or []):
            self.c.execute(
                "INSERT INTO board_bar (board_code, trade_date, open, high, low, close, volume, amount) "
                "VALUES (?, DATE '2026-08-07', 100, 101, 99, 100, 1000, 100000)", [code])
        return {"rows": len(board_codes or []), "boards": 1, "failed": []}
    monkeypatch.setattr(BoardIngestService, "ingest_board_bar", fake_ingest_board_bar, raising=True)
    client.execute("INSERT INTO board_dict (board_code, name, board_type, has_bar) "
                   "VALUES ('309121','AI PC','concept',TRUE)")
    client.execute("INSERT INTO board_dict (board_code, name, board_type, has_bar) "
                   "VALUES ('309131','AI Agent','concept',TRUE)")
    client.execute("INSERT INTO daily_bar (code, trade_date, close) VALUES ('600000.SH', DATE '2026-08-07', 10.0)")
    # 手动指定 id 前先推进序列，避免重扫 _insert_issues 复用 nextval 产生 id 冲突
    client.execute("SELECT nextval('seq_quality_issue')")
    client.execute("SELECT nextval('seq_quality_issue')")
    # 两个板块各一条 gap open；第一条(1)修完重扫时，第二条(2)必须仍在批量循环内可修复
    client.execute("INSERT INTO data_quality_issue "
                   "(id, code, issue_type, trade_date, severity, status, detected_at) "
                   "VALUES (1, '309121', 'board_index_gap', DATE '2026-08-07', 'mid', 'open', now())")
    client.execute("INSERT INTO data_quality_issue "
                   "(id, code, issue_type, trade_date, severity, status, detected_at) "
                   "VALUES (2, '309131', 'board_index_gap', DATE '2026-08-07', 'mid', 'open', now())")

    tid = svc.create("fix", {"issue_ids": [1, 2]})
    t = _wait(svc, tid)
    assert t["status"] == "done"
    rows = client.query_df("SELECT id, status FROM data_quality_issue WHERE id IN (1,2)")
    statuses = {int(r["id"]): str(r["status"]) for _, r in rows.iterrows()}
    assert statuses == {1: "resolved", 2: "resolved"}
    assert scopes == [["309121"], ["309131"]]


def test_board_index_gap_daily_fix_retries_on_empty_rows(client, monkeypatch):
    """真实修复任务经来源补取空年度响应，落库、复检并关闭问题；不重复执行整段采集。"""
    from backend.config.settings import Settings
    from backend.datasource import request_policy
    from backend.services import ingest
    from backend.services.board_ingest import BoardIngestService
    from backend.tests.test_ths_board_source import _FakeResp, _make_source

    cfg = Settings()
    cfg.datasource.max_retries = 2
    cfg.datasource.retry_backoff_sec = 0
    assert cfg.ths_board.max_retries is None
    monkeypatch.setattr(request_policy, "get_effective_settings", lambda: cfg)
    monkeypatch.setattr(ingest.IngestionService, "__init__", lambda self, source=None: None)
    monkeypatch.setattr("backend.services.async_task._mark_snapshots_stale", lambda: 0)
    requests = []

    class Session:
        def get(self, url, **kwargs):
            requests.append(url)
            data = "" if len(requests) == 1 else "20260818,100,101,99,100,1000,100000"
            return _FakeResp('quotebridge({"data":"' + data + '"})')

    source = _make_source({})
    source._session = Session()
    source._request_overrides = {"timeout": None, "attempts": None, "backoff": None}
    init = BoardIngestService.__init__
    monkeypatch.setattr(BoardIngestService, "__init__",
                        lambda self, client=None, **kwargs: init(self, client=client, source=source))
    client.execute("INSERT INTO board_dict (board_code, name, board_type, has_bar) "
                   "VALUES ('300037','测试行业','industry',TRUE)")
    client.execute("INSERT INTO daily_bar (code, trade_date, close) "
                   "VALUES ('600000.SH', DATE '2026-08-18', 10.0)")
    client.execute("SELECT nextval('seq_quality_issue')")
    client.execute("INSERT INTO data_quality_issue "
                   "(id, code, issue_type, trade_date, severity, status, detected_at) "
                   "VALUES (100, '300037', 'board_index_gap_daily', DATE '2026-08-18', "
                   "'mid', 'open', now())")

    svc = AsyncTaskService(client)
    task = _wait(svc, svc.create("fix", {"issue_ids": [100]}))
    assert task["status"] == "done", task
    assert len(requests) == 2
    assert requests[0] == requests[1]
    assert client.query_df("SELECT status FROM data_quality_issue WHERE id=100").iloc[0]["status"] == "resolved"
    assert client.query_df("SELECT close FROM board_bar WHERE board_code='300037'").iloc[0]["close"] == 100


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


@pytest.mark.parametrize("today", [date(2026, 8, 7), date(2026, 8, 8), date(2026, 10, 10)])
def test_board_scan_missing_dates_uses_market_day_on_weekend_and_later(client, monkeypatch, today):
    """当天、周末和历史日期复检都只检查行情基准日前的开市日，空指数不能打断扫描。"""
    monkeypatch.setattr("backend.services.data_report._shanghai_today", lambda: today)
    _seed_board_scan(client)
    client.execute(
        "INSERT INTO trade_calendar VALUES (DATE '2026-08-06', TRUE), "
        "(DATE '2026-08-07', TRUE), (DATE '2026-08-08', FALSE), "
        "(DATE '2026-08-10', TRUE)"
    )
    client.execute(
        "INSERT INTO board_dict (board_code, name, board_type, has_bar) VALUES "
        "('never', '从未采到指数', 'concept', TRUE), "
        "('old', '近期无指数', 'concept', TRUE)"
    )
    client.execute(
        "INSERT INTO board_bar (board_code, trade_date, open, high, low, close) "
        "VALUES ('old', DATE '2026-07-01', 100, 101, 99, 100)"
    )
    client.execute(
        "INSERT INTO data_quality_issue "
        "(id, code, trade_date, issue_type, severity, status, detected_at) "
        "VALUES (799, 'never', DATE '2026-08-06', 'board_index_gap_daily', 'mid', 'open', now())"
    )
    result = DataIntegrityReport(client).scan_board_quality()
    assert result["index_gap"] == 3
    daily = client.query_df(
        "SELECT code, trade_date FROM data_quality_issue "
        "WHERE issue_type='board_index_gap_daily' AND status='open'"
    )
    gaps = {(r.code, pd.Timestamp(r.trade_date).date()) for r in daily.itertuples()}
    assert gaps == {
        ("881121", date(2026, 8, 7)),
        ("old", date(2026, 8, 6)),
        ("old", date(2026, 8, 7)),
    }
    assert client.query_df("SELECT status FROM data_quality_issue WHERE id=799").iloc[0, 0] == "resolved"
    assert result["index_invalid"] == 0
    details = client.query_df(
        "SELECT detail FROM data_quality_issue WHERE issue_type='board_index_gap'"
    )["detail"]
    assert all("NaT" not in detail for detail in details)


def test_board_scan_and_recheck_without_market_dates(client):
    """空行情库的聚合日期是 NaT，扫描应正常返回，复检不能误判为已追平。"""
    client.execute(
        "INSERT INTO board_dict (board_code, name, board_type, has_bar) "
        "VALUES ('empty', '无行情', 'concept', TRUE)"
    )
    rep = DataIntegrityReport(client)
    result = rep.scan_board_quality()
    assert result["index_gap"] == result["index_gap_daily"] == 0
    assert rep.recheck_clean("board_index_gap", "empty", None) is False
    assert rep.recheck_clean("board_fund_stale", None, None) is False


def test_board_recheck_missing_member_snapshot_in_mixed_dates(client):
    """NULL 快照在混合日期结果中也是 NaT，不得因没有 active 问题就认定有完整快照。"""
    client.execute(
        "INSERT INTO board_dict (board_code, name, board_type, member_snapshot_at) VALUES "
        "('empty', '未形成快照', 'concept', NULL), "
        "('complete', '已有快照', 'concept', now())"
    )
    assert (
        DataIntegrityReport(client).recheck_clean("board_member_incomplete", "empty", None) is False
    )


@pytest.mark.parametrize(
    "issue_type",
    [
        "board_index_gap",
        "board_index_gap_daily",
        "board_index_invalid",
        "board_fund_missing",
        "board_fund_stale",
        "market_index_gap",
        "market_index_gap_daily",
        "market_index_invalid",
    ],
)
def test_scan_issue_fix_rechecks_collected_data_before_source_request(
    client, monkeypatch, issue_type
):
    """已被普通采集补齐的旧问题只复检收敛，不重复请求板块或市场指数源。"""
    from backend.services.async_task import TaskContext, _recover_one
    from backend.services.board_ingest import BoardIngestService

    _seed_board_scan(client)
    for period in ("即时", "3日", "5日", "10日", "20日"):
        client.execute(
            "INSERT INTO board_fund_flow (board_code, snapshot_date, period) "
            "VALUES ('309121', DATE '2026-08-07', ?)",
            [period],
        )
    client.execute(
        "INSERT INTO index_bar (index_code, trade_date, open, high, low, close) "
        "VALUES ('000905.SH', DATE '2026-08-07', 100, 101, 99, 100)"
    )
    client.execute("INSERT INTO trade_calendar VALUES (DATE '2026-08-07', TRUE)")
    code = "000905.SH" if issue_type.startswith("market_") else "309121"
    if issue_type == "board_fund_stale":
        code = None
    client.execute(
        "INSERT INTO data_quality_issue "
        "(id, code, trade_date, issue_type, severity, status, detected_at) "
        "VALUES (800, ?, DATE '2026-08-07', ?, 'mid', 'open', now())",
        [code, issue_type],
    )

    def unexpected_request(*args, **kwargs):
        raise AssertionError("已补齐的旧问题不得请求采集源")

    monkeypatch.setattr(BoardIngestService, "__init__", unexpected_request)
    rep = DataIntegrityReport(client)
    clean, _, message = _recover_one(
        client, rep, None, TaskContext(AsyncTaskService(client), "test_stale_issue", {}), 800
    )
    assert clean is True
    assert "无需重复采集" in message
    row = client.query_df("SELECT status, fix_task_id FROM data_quality_issue WHERE id=800").iloc[0]
    assert row["status"] == "resolved" and pd.isna(row["fix_task_id"])


@pytest.mark.parametrize("issue_type", ["board_index_gap_daily", "board_index_invalid"])
def test_board_fix_missing_issue_date_does_not_send_nat_to_source(client, monkeypatch, issue_type):
    """旧台账空日期应保持待处理，不可把 NaT 传入定向重采。"""
    from backend.services.async_task import TaskContext, _recover_one
    from backend.services.board_ingest import BoardIngestService

    _seed_board_scan(client)
    client.execute(
        "INSERT INTO data_quality_issue "
        "(id, code, issue_type, severity, status, detected_at) "
        "VALUES (801, '881121', ?, 'mid', 'open', now())",
        [issue_type],
    )

    def unexpected_request(*args, **kwargs):
        raise AssertionError("空日期不得请求采集源")

    monkeypatch.setattr(BoardIngestService, "__init__", unexpected_request)
    clean, _, message = _recover_one(
        client,
        DataIntegrityReport(client),
        None,
        TaskContext(AsyncTaskService(client), "test_null_issue_date", {}),
        801,
    )
    assert clean is False
    assert "缺少日期" in message
    assert (
        client.query_df("SELECT status FROM data_quality_issue WHERE id=801").iloc[0, 0] == "open"
    )


def test_board_fix_closes_current_issue_when_related_scan_fails(client, monkeypatch):
    """本条已补齐但关联扫描失败时，保留真实成功状态，清晰说明其他问题尚未复检。"""
    from backend.services.async_task import TaskContext, _recover_one

    _seed_board_scan(client)
    client.execute(
        "INSERT INTO data_quality_issue "
        "(id, code, trade_date, issue_type, severity, status, detected_at) "
        "VALUES (802, '309121', DATE '2026-08-07', 'board_index_gap_daily', 'mid', 'open', now())"
    )
    rep = DataIntegrityReport(client)

    def failed_scan():
        raise RuntimeError("模拟关联扫描失败")

    monkeypatch.setattr(rep, "scan_board_quality", failed_scan)
    ctx = TaskContext(AsyncTaskService(client), "test_related_scan_failure", {})
    clean, _, message = _recover_one(client, rep, None, ctx, 802)
    ctx.flush()
    assert clean is True
    assert "其他板块的质量检查未完成" in message
    assert (
        client.query_df("SELECT status FROM data_quality_issue WHERE id=802").iloc[0, 0]
        == "resolved"
    )
    logs = client.query_df("SELECT message FROM task_log WHERE task_id='test_related_scan_failure'")
    assert any("旧问题状态可能尚未更新" in text for text in logs["message"])


def test_board_scheduled_fix_converges_481_collected_old_issues(client, monkeypatch):
    """代表性全板块规模：定时任务接到旧缺口台账，真实复检/落表后零重采、零遗留。"""
    from backend.services import ingest
    from backend.services.async_task import TaskContext, _h_fix
    from backend.services.board_ingest import BoardIngestService

    client.execute(
        "INSERT INTO daily_bar (code, trade_date, close) VALUES ('600000.SH', DATE '2026-08-07', 10)"
    )
    client.execute("INSERT INTO trade_calendar VALUES (DATE '2026-08-07', TRUE)")
    client.execute(
        "INSERT INTO board_dict (board_code, name, board_type, has_bar) "
        "SELECT 'board_' || i, '板块' || i, 'concept', TRUE FROM range(481) t(i)"
    )
    client.execute(
        "INSERT INTO board_bar (board_code, trade_date, open, high, low, close) "
        "SELECT board_code, DATE '2026-08-07', 100, 101, 99, 100 FROM board_dict"
    )
    client.execute(
        "INSERT INTO data_quality_issue "
        "(id, code, trade_date, issue_type, severity, status, detected_at) "
        "SELECT row_number() OVER (), board_code, DATE '2026-08-07', "
        "'board_index_gap_daily', 'mid', 'open', now() FROM board_dict"
    )
    monkeypatch.setattr(ingest.IngestionService, "__init__", lambda *args, **kwargs: None)

    def unexpected_request(*args, **kwargs):
        raise AssertionError("普通采集已补齐的板块不得重采")

    monkeypatch.setattr(BoardIngestService, "__init__", unexpected_request)
    result = _h_fix(
        {"issue_type": "board_index_gap_daily"},
        TaskContext(AsyncTaskService(client), "test_collected_board_batch", {}),
    )
    assert result["ok"] is True
    assert result["resolved"] == result["total"] == 481 and result["failed"] == 0
    assert (
        client.query_df(
            "SELECT count(*) FROM data_quality_issue "
            "WHERE issue_type='board_index_gap_daily' AND status='resolved'"
        ).iloc[0, 0]
        == 481
    )
    assert (
        client.query_df(
            "SELECT count(*) FROM data_quality_issue "
            "WHERE issue_type IN ('board_index_gap','board_index_gap_daily') "
            "AND status IN ('open','fixing')"
        ).iloc[0, 0]
        == 0
    )
