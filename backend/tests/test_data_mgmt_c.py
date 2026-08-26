"""M2.9 后端：分层质量模型 / 全局质量评分 / 逐股名称搜索+分层明细 /
表级鲜活度 / 质检幂等 / 每日自动任务含质检 / 系统设置去调度开关。

不触网：通过临时库 + 直接 seed 数据，不调用真实采集。
"""

from __future__ import annotations

import threading
import time
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pandas as pd
import pytest

import backend.storage.duckdb_client as dc
from backend.dataquality.checker import sanitize_bars
from backend.services.async_task import AsyncTaskService, ConcurrentTaskError
from backend.services.data_report import DataIntegrityReport
from backend.storage.catalog import build_catalog
from backend.storage.ddl import init_db
from backend.storage.duckdb_client import DuckDBClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    c = DuckDBClient(db_path=str(tmp_path / "t.duckdb"))
    init_db(c)
    monkeypatch.setattr(dc, "_client", c)
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


def _seed(c):
    """A：四层全绿；B：缺 01-04（L4）且无 total_mv（L2）。最新交易日 01-05。"""
    cal = pd.DataFrame({"trade_date": [date(2024, 1, d) for d in (2, 3, 4, 5)], "is_open": True})
    c.register_df("_cal", cal)
    c.execute("INSERT INTO trade_calendar SELECT trade_date, is_open FROM _cal")
    c.unregister("_cal")
    c.execute("INSERT INTO stock_basic (code, name, delist_date, list_date, price_limit_pct) VALUES "
              "('A.SH','甲公司',NULL, DATE '2024-01-02', 0.10), "
              "('B.SH','乙公司',NULL, DATE '2024-01-02', 0.10)")
    rows = [("A.SH", date(2024, 1, d), 10.0, False) for d in (2, 3, 4, 5)]
    rows += [("B.SH", date(2024, 1, d), 20.0, False) for d in (2, 3, 5)]   # 缺 01-04
    df = pd.DataFrame(rows, columns=["code", "trade_date", "close", "is_suspended"])
    c.register_df("_b", df)
    c.execute("INSERT INTO daily_bar (code, trade_date, close, is_suspended) "
              "SELECT code, trade_date, close, is_suspended FROM _b")
    c.unregister("_b")
    # A 四层全绿：L2 契约要求 total_mv 与 float_mv 都在
    metrics = pd.DataFrame(
        [{"code": "A.SH", "trade_date": date(2024, 1, d), "total_mv": 1e10, "float_mv": 8e9}
         for d in (2, 3, 4, 5)]
    )
    c.register_df("_m", metrics)
    c.execute("INSERT INTO daily_metrics SELECT code, trade_date, float_mv, total_mv FROM _m")
    c.unregister("_m")


# ── 分层质量模型 + 全局评分（DM-D15）──
def test_quality_model_score_and_layers(client):
    _seed(client)
    qm = DataIntegrityReport(client).quality_model()
    assert qm["score"] == 50                      # 2 只仅 A 全绿
    by = {l["layer"]: l for l in qm["by_layer"]}
    assert by["L1"]["pass_stocks"] == 2 and by["L3"]["pass_stocks"] == 2
    assert by["L2"]["pass_stocks"] == 1 and by["L2"]["issues"] == 1   # B 无 total_mv
    assert by["L4"]["pass_stocks"] == 1 and by["L4"]["issues"] == 1   # B 1 个缺口日
    assert qm["gaps"]["stocks_with_gap"] == 1 and qm["gaps"]["latest_trade_date"] == "2024-01-05"


def test_quality_model_l1l3_from_issues(client):
    _seed(client)
    # 给 A 注入一条未解决 L3（复权跳变）→ A 的 L3 不达标，全绿数降为 0
    client.execute("INSERT INTO data_quality_issue (id, code, issue_type, severity, status, detected_at) "
                   "VALUES (1,'A.SH','adj_jump','high','open',?)", [datetime.now()])
    qm = DataIntegrityReport(client).quality_model()
    by = {l["layer"]: l for l in qm["by_layer"]}
    assert by["L3"]["pass_stocks"] == 1 and by["L3"]["issues"] == 1
    assert qm["score"] == 0


# ── 逐股名称搜索 + 分层明细（DM-D17/D15）──
def test_stock_quality_keyword_and_layers(client):
    _seed(client)
    rep = DataIntegrityReport(client)
    assert [r["code"] for r in rep.stock_quality(keyword="甲")["list"]] == ["A.SH"]   # 按名称
    assert [r["code"] for r in rep.stock_quality(keyword="b.sh")["list"]] == ["B.SH"]  # 按代码(大小写不敏感)
    by = {r["code"]: r for r in rep.stock_quality()["list"]}
    assert by["A.SH"]["layers"]["L1"]["ok"] is True and by["A.SH"]["layers"]["L4"]["ok"] is True
    assert by["B.SH"]["layers"]["L2"]["ok"] is False
    assert by["B.SH"]["layers"]["L4"]["ok"] is False and by["B.SH"]["layers"]["L4"]["gap_days"] == 1


# ── L1 入库闸门：丢弃行可上报（DM-D15）──
def test_sanitize_reports_dropped_dates():
    df = pd.DataFrame({
        "code": ["A.SH"] * 3,
        "trade_date": [date(2024, 1, d) for d in (2, 3, 4)],
        "open": [1.0, 1.0, 1.0], "high": [1.0, 1.0, 1.0], "low": [1.0, 1.0, 1.0],
        "close": [10.0, None, -1.0],   # 后两行非法 → 丢弃
    })
    out, stats = sanitize_bars(df)
    assert stats["dropped"] == 2 and len(stats["dropped_dates"]) == 2
    assert len(out) == 1


# ── 表级鲜活度纳入质量（修正 M2.8 只数 open_issues 的 bug）──
def test_catalog_freshness(client):
    client.execute("INSERT INTO daily_bar (code, trade_date, close) VALUES "
                   "('A.SH', DATE '2024-01-02', 10.0), ('A.SH', DATE '2024-01-03', 11.0)")
    client.execute("INSERT INTO index_bar (index_code, trade_date, close) "
                   "VALUES ('000300.SH', DATE '2024-01-02', 100.0)")   # 滞后于全局最新 01-03
    cat = {x["table"]: x for x in build_catalog(client)}
    assert cat["daily_bar"]["fresh"] is True        # 最新==全局最新
    assert cat["index_bar"]["fresh"] is False       # 滞后
    assert cat["daily_metrics"]["fresh"] is False    # 空表 → 不算正常
    assert cat["trade_calendar"]["fresh"] is None    # 非时序表无鲜活度概念


# ── 质检幂等：反复扫不堆积（支撑每日自动质检）──
def test_scan_quality_idempotent(client):
    client.execute("INSERT INTO stock_basic (code, name, price_limit_pct) VALUES ('C.SH','丙', 0.10)")
    client.execute("INSERT INTO daily_bar (code, trade_date, close, pre_close) "
                   "VALUES ('C.SH', DATE '2024-01-02', 10.0, 10.0),"
                   "('C.SH', DATE '2024-01-03', 10.0, 10.0),"
                   "('C.SH', DATE '2024-01-04', 10.0, 10.0),"
                   "('C.SH', DATE '2024-01-05', 10.0, 10.0),"
                   "('C.SH', DATE '2024-01-08', 10.0, 10.0),"
                   "('C.SH', DATE '2024-01-09', 20.0, 10.0)")   # 第 6 个交易日 +100% → 异常涨跌
    rep = DataIntegrityReport(client)
    rep.scan_quality_issues()
    n1 = int(client.query_df("SELECT count(*) AS n FROM data_quality_issue "
                             "WHERE issue_type='abnormal_change'").iloc[0]["n"])
    rep.scan_quality_issues()
    n2 = int(client.query_df("SELECT count(*) AS n FROM data_quality_issue "
                             "WHERE issue_type='abnormal_change'").iloc[0]["n"])
    assert n1 == 1 and n2 == 1   # 第二次扫描不再追加重复


def test_scan_quality_calculation_does_not_hold_connection_lock(client, monkeypatch):
    """全市质检计算期间不持有连接级长事务锁，状态/日志查询可插入。"""
    rep = DataIntegrityReport(client)
    entered = threading.Event()
    release = threading.Event()
    query_done = threading.Event()
    errors: list[BaseException] = []
    original = rep._coverage_frame

    def slow_coverage(*args, **kwargs):
        entered.set()
        release.wait(timeout=2)
        return original(*args, **kwargs)

    def run_scan():
        try:
            rep.scan_quality_issues()
        except BaseException as exc:  # pragma: no cover - 失败由主线程断言转发
            errors.append(exc)

    def read_status():
        client.query_df("SELECT count(*) FROM async_task")
        query_done.set()

    monkeypatch.setattr(rep, "_coverage_frame", slow_coverage)
    scan_thread = threading.Thread(target=run_scan, daemon=True)
    scan_thread.start()
    assert entered.wait(timeout=1)
    query_thread = threading.Thread(target=read_status, daemon=True)
    query_thread.start()
    readable_during_calculation = query_done.wait(timeout=0.5)
    release.set()
    scan_thread.join(timeout=2)
    query_thread.join(timeout=2)

    assert readable_during_calculation is True
    assert not scan_thread.is_alive() and not query_thread.is_alive()
    assert errors == []


def test_scan_quality_calculation_failure_keeps_previous_open_issues(client, monkeypatch):
    """事务外计算失败时不能先删除上一轮未处理问题。"""
    client.execute(
        "INSERT INTO data_quality_issue "
        "(id, code, issue_type, severity, status, detected_at) "
        "VALUES (99, 'OLD.SH', 'stale', 'high', 'open', ?)",
        [datetime.now(timezone.utc)],
    )
    rep = DataIntegrityReport(client)
    def fail_scan(*_args, **_kwargs):
        raise RuntimeError("scan failed")

    monkeypatch.setattr(rep, "_coverage_frame", fail_scan)

    with pytest.raises(RuntimeError, match="scan failed"):
        rep.scan_quality_issues()

    kept = client.query_df("SELECT status FROM data_quality_issue WHERE id=99")
    assert kept.iloc[0]["status"] == "open"


def test_scan_quality_keeps_ignore_added_during_calculation(client, monkeypatch):
    """计算期间新增的人工豁免必须在最终短事务内重读，不得重新上报。"""
    _seed(client)
    rep = DataIntegrityReport(client)
    original = rep._coverage_frame

    def coverage_then_ignore(*args, **kwargs):
        result = original(*args, **kwargs)
        client.execute(
            "INSERT INTO data_quality_issue "
            "(id, code, issue_type, severity, status, detected_at) "
            "VALUES (99, 'B.SH', 'data_gap', 'mid', 'ignored', ?)",
            [datetime.now(timezone.utc)],
        )
        return result

    monkeypatch.setattr(rep, "_coverage_frame", coverage_then_ignore)
    result = rep.scan_quality_issues()

    rows = client.query_df(
        "SELECT status FROM data_quality_issue WHERE code='B.SH' AND issue_type='data_gap'"
    )
    assert rows["status"].tolist() == ["ignored"]
    assert result["data_gap_rows"] == 0


def test_scan_quality_keeps_resolved(client):
    """已解决的自动扫描问题不被重扫清除（只清 open 的）。"""
    client.execute("INSERT INTO data_quality_issue (id, code, issue_type, severity, status, detected_at) "
                   "VALUES (99,'X.SH','abnormal_change','mid','resolved',?)", [datetime.now()])
    DataIntegrityReport(client).scan_quality_issues()
    kept = client.query_df("SELECT status FROM data_quality_issue WHERE id=99")
    assert len(kept) == 1 and kept.iloc[0]["status"] == "resolved"


def test_scan_quality_skips_listing_but_keeps_delisted_history(client):
    """只豁免真实上市初期；退市股退市前的正常交易阶段仍要扫描。"""
    client.execute(
        "INSERT INTO stock_basic (code, name, price_limit_pct, list_date, delist_date) VALUES "
        "('NEW.SH','新股',0.10,DATE '2024-01-02',NULL), "
        "('OLD.SH','退市样本',0.10,DATE '2020-01-02',DATE '2024-02-01')"
    )
    client.execute("INSERT INTO daily_bar (code, trade_date, close, pre_close) VALUES "
                   "('NEW.SH', DATE '2024-01-02', 20.0, 10.0),"   # 首 5 个交易日内，跳过
                   "('OLD.SH', DATE '2024-01-02', 20.0, 10.0)")   # 退市前历史异常，保留
    rep = DataIntegrityReport(client)
    rep.scan_quality_issues()
    issues = client.query_df(
        "SELECT code FROM data_quality_issue WHERE issue_type='abnormal_change'"
    )
    assert issues["code"].tolist() == ["OLD.SH"]


def test_scan_quality_old_stock_window_start_not_listing(client):
    """近 5 年窗口开头不能误当成老股票上市初期。"""
    client.execute(
        "INSERT INTO stock_basic (code, name, price_limit_pct, list_date) VALUES "
        "('OLDWIN.SH','老股',0.10,DATE '2010-01-02')"
    )
    client.execute("INSERT INTO daily_bar (code, trade_date, close, pre_close) VALUES "
                   "('OLDWIN.SH', DATE '2024-01-02', 20.0, 10.0)")
    rep = DataIntegrityReport(client)
    rep.scan_quality_issues()
    n = int(client.query_df(
        "SELECT count(*) AS n FROM data_quality_issue WHERE issue_type='abnormal_change'"
    ).iloc[0]["n"])
    assert n == 1


# ── 系统设置去调度开关，但 scheduler.* 仍可写（DM-D14）──
def test_settings_view_excludes_scheduler(client, app_cfg):
    from backend.api.data_admin import get_settings_view
    from backend.storage.app_config import WHITELIST
    keys = [g["key"] for g in get_settings_view().data["groups"]]
    assert "scheduler" not in keys and "datasource" in keys
    assert "scheduler.enabled" in WHITELIST          # 仍是白名单（调度页读写）
    assert app_cfg.set_many({"scheduler.daily_cron_hour": 9}) == 1   # 平台配置写 PG


# ── 数据总览 hub：环节统计 + 风险摘要（DM-D12）──
def test_hub_stages_and_risk(client):
    _seed(client)
    from backend.api.data_admin import hub
    data = hub().data
    assert data["quality_score"] == 50
    assert data["stages"]["ingest"]["codes_active"] == 2
    texts = " ".join(r["text"] for r in data["risk"])
    assert "缺口" in texts            # B 有缺口 → 风险提示
    assert "未做过数据质检" in texts   # 无 abnormal/adj 记录 → 提示
    assert all("level" in r and "link" in r for r in data["risk"])


# ── 定时触发的任务带来源标记走任务系统（调度系统重构）──
def test_task_carries_trigger_source(client, monkeypatch):
    """定时/手动触发的任务都走同一套；trigger_source/job_name 落库供任务中心区分展示。"""
    monkeypatch.setattr("backend.services.async_task._mark_snapshots_stale", lambda: 0)
    monkeypatch.setattr(
        "backend.services.async_task._produce_public_board_snapshots",
        lambda _params: {"run_date": "2024-01-05", "profile_count": 0, "total_rows": 0, "profiles": []},
    )
    svc = AsyncTaskService(client)
    tid = svc.create("recompute", trigger_source="scheduled", job_id="job_x", job_name="盘后刷新")
    t = _wait(svc, tid)
    assert t["status"] == "done"
    assert t["trigger_source"] == "scheduled" and t["job_name"] == "盘后刷新" and t["job_id"] == "job_x"


def test_write_tasks_are_mutually_exclusive(client, monkeypatch):
    from backend.services import ingest
    monkeypatch.setattr(ingest.IngestionService, "__init__", lambda self, source=None: None, raising=True)
    monkeypatch.setattr(ingest.IngestionService, "update",
                        lambda self, codes=None, concurrency=None, ctx=None: (time.sleep(0.3), {})[1], raising=True)
    svc = AsyncTaskService(client)
    t1 = svc.create("update")
    with pytest.raises(ConcurrentTaskError):
        svc.create("backfill")       # 另一写任务 → 与 update 互斥（单写者模型）
    _wait(svc, t1)


def test_verify_is_scan_only(client, monkeypatch):
    """一键体检（verify）与定时质检同一方法：只跑 scan_quality_issues，不跑 DataVerifier。"""
    import backend.services.data_verify as dv
    called = {"verifier": False}
    monkeypatch.setattr(dv.DataVerifier, "__init__",
                        lambda self, *a, **k: called.__setitem__("verifier", True) or None, raising=True)
    svc = AsyncTaskService(client)
    t = _wait(svc, svc.create("verify"))
    assert t["status"] == "done" and "质检完成" in t["message"]
    assert called["verifier"] is False
    assert "fails" not in (t.get("result") or {})   # 不再夹带结构校验结果


# ════════════ M2.9.2：质检-恢复闭环（四闭环）════════════

def _gap_issue_id(c, code="B.SH"):
    return int(c.query_df(
        "SELECT id FROM data_quality_issue WHERE code=? AND issue_type='data_gap'", [code]).iloc[0]["id"])


def test_scan_emits_four_layers(client):
    """四层统一质检：L2 市值缺失 + L4 缺口都落台账（不再只产 L3）。"""
    _seed(client)
    res = DataIntegrityReport(client).scan_quality_issues()
    assert res["mv_missing_rows"] == 1   # B 无 total_mv
    assert res["data_gap_rows"] == 1     # B 缺 01-04（内部缺口）
    assert res["stale_rows"] == 0        # A/B 最新都=全局最新
    types = set(client.query_df(
        "SELECT DISTINCT issue_type FROM data_quality_issue WHERE status='open'")["issue_type"])
    assert {"mv_missing", "data_gap"} <= types


def test_scan_emits_mv_gap_for_recent_float_mv_gap(client):
    """近端只缺 float_mv 也属于 L2 市值字段缺口，复用 mv_gap 台账与修复闭环。"""
    cal = pd.DataFrame({"trade_date": [date(2024, 1, d) for d in (2, 3)], "is_open": True})
    client.register_df("_cal_float_gap", cal)
    client.execute("INSERT INTO trade_calendar SELECT trade_date, is_open FROM _cal_float_gap")
    client.unregister("_cal_float_gap")
    client.execute("INSERT INTO stock_basic (code, name, delist_date, list_date) "
                   "VALUES ('A.SH','甲公司',NULL, DATE '2024-01-02')")
    client.execute("INSERT INTO daily_bar (code, trade_date, close) VALUES "
                   "('A.SH', DATE '2024-01-02', 10.0),"
                   "('A.SH', DATE '2024-01-03', 11.0)")
    client.execute("INSERT INTO daily_metrics (code, trade_date, total_mv, float_mv) VALUES "
                   "('A.SH', DATE '2024-01-02', 1e10, 8e9),"
                   "('A.SH', DATE '2024-01-03', 1.1e10, NULL)")

    rep = DataIntegrityReport(client)
    qm = rep.quality_model()
    assert {l["layer"]: l for l in qm["by_layer"]}["L2"]["pass_stocks"] == 0
    res = rep.scan_quality_issues()
    assert res["mv_missing_rows"] == 0
    assert res["mv_gap_rows"] == 1
    issue = client.query_df(
        "SELECT issue_type, detail FROM data_quality_issue WHERE code='A.SH' AND status='open'"
    ).iloc[0]
    assert issue["issue_type"] == "mv_gap"
    assert "流通市值" in issue["detail"]


def test_suspension_excluded_from_gap(client):
    """确认停牌后，缺口口径减去它（DM-D20）→ B 不再算缺口。"""
    rep = DataIntegrityReport(client)
    _seed(client)
    rep.confirm_suspension("B.SH", [date(2024, 1, 4)])
    qm = rep.quality_model()
    assert qm["gaps"]["stocks_with_gap"] == 0
    by = {l["layer"]: l for l in qm["by_layer"]}
    assert by["L4"]["pass_stocks"] == 2


def test_reverse_confirm_suspension(client, monkeypatch):
    """反向确定：缺口先按漏采重采 → 源端无数据 → 确认停牌入表 → 复检通过解决 → 再扫不复现（收敛）。"""
    rep = DataIntegrityReport(client)
    _seed(client)
    rep.scan_quality_issues()
    iid = _gap_issue_id(client)
    from backend.services import ingest
    monkeypatch.setattr(ingest.IngestionService, "__init__", lambda self, source=None: None, raising=True)
    monkeypatch.setattr(ingest.IngestionService, "ingest_one_daily",
                        lambda self, code, start, end, *a, **k: 0, raising=True)   # 源端无数据
    monkeypatch.setattr("backend.services.async_task._mark_snapshots_stale", lambda: 0)
    svc = AsyncTaskService(client)
    t = _wait(svc, svc.create("fix", {"issue_id": iid}))
    assert t["status"] == "done"
    assert len(client.query_df("SELECT 1 FROM stock_suspension WHERE code='B.SH'")) == 1
    assert client.query_df("SELECT status FROM data_quality_issue WHERE id=?", [iid]).iloc[0]["status"] == "resolved"
    rep.scan_quality_issues()    # 收敛：不再上报
    assert int(client.query_df("SELECT count(*) AS n FROM data_quality_issue "
                               "WHERE code='B.SH' AND issue_type='data_gap' AND status='open'").iloc[0]["n"]) == 0


def test_reverse_fills_gap(client, monkeypatch):
    """反向确定：源端有数据 → 补回入库（漏采修复），不写停牌，复检通过解决。"""
    rep = DataIntegrityReport(client)
    _seed(client)
    rep.scan_quality_issues()
    iid = _gap_issue_id(client)
    from backend.services import ingest

    def _fill(self, code, start, end, *a, **k):
        client.execute("INSERT INTO daily_bar (code, trade_date, close, is_suspended) "
                       "VALUES (?, DATE '2024-01-04', 20.0, false)", [code])
        return 1
    monkeypatch.setattr(ingest.IngestionService, "__init__", lambda self, source=None: None, raising=True)
    monkeypatch.setattr(ingest.IngestionService, "ingest_one_daily", _fill, raising=True)
    monkeypatch.setattr("backend.services.async_task._mark_snapshots_stale", lambda: 0)
    svc = AsyncTaskService(client)
    _wait(svc, svc.create("fix", {"issue_id": iid}))
    assert len(client.query_df("SELECT 1 FROM stock_suspension WHERE code='B.SH'")) == 0
    assert client.query_df("SELECT status FROM data_quality_issue WHERE id=?", [iid]).iloc[0]["status"] == "resolved"


def test_reconcile_backfill_counts_actual_not_window(client, monkeypatch):
    """次新股(入库前无 bar → 窗口起点 lo 前移)补采：补回数应=实际入库天数，而非整窗天数。
    防回归：曾用 miss−still 计补回，致 lo 前移把上市前"伪缺口"误算成补回（虚报如 90 实补 5）。"""
    _seed(client)   # 全局最新 01-05；日历 01-02..01-05
    # C：list_date 01-04、当前无任何行情 → missing_days_for 因 min_bar=None 取整窗(4 天)为缺口
    client.execute("INSERT INTO stock_basic (code, name, list_date, price_limit_pct) "
                   "VALUES ('C.SH','丙', DATE '2024-01-04', 0.10)")
    from backend.services import ingest

    def _fill_two(self, code, start, end, *a, **k):
        client.execute("INSERT INTO daily_bar (code, trade_date, close, is_suspended) VALUES "
                       "('C.SH', DATE '2024-01-04', 9.0, false), ('C.SH', DATE '2024-01-05', 9.1, false)")
        return 2
    monkeypatch.setattr(ingest.IngestionService, "__init__", lambda self, source=None: None, raising=True)
    monkeypatch.setattr(ingest.IngestionService, "ingest_one_daily", _fill_two, raising=True)
    r = ingest.IngestionService().reconcile_gaps("C.SH", confirm=False)
    assert len(r["backfilled"]) == 2, r           # 实补 2 天（01-04/05），而非整窗 4 天
    assert r["confirmed"] == 0                     # confirm=False：增量收口不自动确认停牌
    assert ingest.IngestionService.reconcile_note(r) == "补回 2 天"


def test_recover_mv_missing_via_valuation(client, monkeypatch):
    """L2 恢复走 ingest_valuation（非重拉行情），补上 total_mv 后复检通过。"""
    rep = DataIntegrityReport(client)
    _seed(client)
    rep.scan_quality_issues()
    iid = int(client.query_df(
        "SELECT id FROM data_quality_issue WHERE code='B.SH' AND issue_type='mv_missing'").iloc[0]["id"])
    from backend.services import ingest

    def _val(self, codes=None, years=None):
        client.execute("INSERT INTO daily_metrics (code, trade_date, total_mv, float_mv) "
                       "VALUES ('B.SH', DATE '2024-01-05', 5e9, 4e9)")
        return {"total_mv_rows": 1}
    monkeypatch.setattr(ingest.IngestionService, "__init__", lambda self, source=None: None, raising=True)
    monkeypatch.setattr(ingest.IngestionService, "ingest_valuation", _val, raising=True)
    monkeypatch.setattr("backend.services.async_task._mark_snapshots_stale", lambda: 0)
    svc = AsyncTaskService(client)
    _wait(svc, svc.create("fix", {"issue_id": iid}))
    assert client.query_df("SELECT status FROM data_quality_issue WHERE id=?", [iid]).iloc[0]["status"] == "resolved"


def test_recover_mv_gap_fills_float_mv_gap(client, monkeypatch):
    """mv_gap 恢复走估值缺口补采；只缺 float_mv 时复检也必须能 resolved。"""
    cal = pd.DataFrame({"trade_date": [date(2024, 1, d) for d in (2, 3)], "is_open": True})
    client.register_df("_cal_float_fix", cal)
    client.execute("INSERT INTO trade_calendar SELECT trade_date, is_open FROM _cal_float_fix")
    client.unregister("_cal_float_fix")
    client.execute("INSERT INTO stock_basic (code, name, delist_date, list_date) "
                   "VALUES ('A.SH','甲公司',NULL, DATE '2024-01-02')")
    client.execute("INSERT INTO daily_bar (code, trade_date, close) VALUES "
                   "('A.SH', DATE '2024-01-02', 10.0),"
                   "('A.SH', DATE '2024-01-03', 11.0)")
    client.execute("INSERT INTO daily_metrics (code, trade_date, total_mv, float_mv) VALUES "
                   "('A.SH', DATE '2024-01-02', 1e10, 8e9),"
                   "('A.SH', DATE '2024-01-03', 1.1e10, NULL)")
    rep = DataIntegrityReport(client)
    rep.scan_quality_issues()
    iid = int(client.query_df(
        "SELECT id FROM data_quality_issue WHERE code='A.SH' AND issue_type='mv_gap'"
    ).iloc[0]["id"])

    from backend.services import ingest

    def _fill_gap(self, codes=None, concurrency=None, ctx=None):
        client.execute("UPDATE daily_metrics SET float_mv=9e9 "
                       "WHERE code='A.SH' AND trade_date=DATE '2024-01-03'")
        return {"total_mv_rows": 0}

    monkeypatch.setattr(ingest.IngestionService, "__init__", lambda self, source=None: None, raising=True)
    monkeypatch.setattr(ingest.IngestionService, "ingest_valuation_gaps", _fill_gap, raising=True)
    monkeypatch.setattr("backend.services.async_task._mark_snapshots_stale", lambda: 0)
    svc = AsyncTaskService(client)
    _wait(svc, svc.create("fix", {"issue_id": iid}))
    assert client.query_df("SELECT status FROM data_quality_issue WHERE id=?", [iid]).iloc[0]["status"] == "resolved"


def test_recheck_keeps_open_if_unfixed(client, monkeypatch):
    """复检未通过（重采后异常仍在）→ 保持 open，不假装已解决。"""
    rep = DataIntegrityReport(client)
    client.execute("INSERT INTO stock_basic (code, name, price_limit_pct) VALUES ('C.SH','丙', 0.10)")
    client.execute("INSERT INTO daily_bar (code, trade_date, close, pre_close) "
                   "VALUES ('C.SH', DATE '2024-01-02', 10.0, 10.0),"
                   "('C.SH', DATE '2024-01-03', 10.0, 10.0),"
                   "('C.SH', DATE '2024-01-04', 10.0, 10.0),"
                   "('C.SH', DATE '2024-01-05', 10.0, 10.0),"
                   "('C.SH', DATE '2024-01-08', 10.0, 10.0),"
                   "('C.SH', DATE '2024-01-09', 20.0, 10.0)")   # 第 6 个交易日 +100% 异常
    rep.scan_quality_issues()
    iid = int(client.query_df(
        "SELECT id FROM data_quality_issue WHERE issue_type='abnormal_change'").iloc[0]["id"])
    from backend.services import ingest
    monkeypatch.setattr(ingest.IngestionService, "__init__", lambda self, source=None: None, raising=True)
    monkeypatch.setattr(ingest.IngestionService, "ingest_one_daily",
                        lambda self, code, start, end, *a, **k: 0, raising=True)  # 重采没改变数据
    monkeypatch.setattr("backend.services.async_task._mark_snapshots_stale", lambda: 0)
    svc = AsyncTaskService(client)
    t = _wait(svc, svc.create("fix", {"issue_id": iid}))
    assert t["result"]["resolved"] == 0
    assert client.query_df("SELECT status FROM data_quality_issue WHERE id=?", [iid]).iloc[0]["status"] == "open"


def test_fix_failure_resets_fixing_and_reports_not_ok(client, monkeypatch):
    """恢复中途抛异常（如源端取数失败）→ 问题必复位 open（不留 fixing 孤儿），
    任务标 failed（带 checkpoint 可续跑）且 result.ok=False、failed=1——
    杜绝"日志失败/状态修复中/弹成功"的假闭环。"""
    rep = DataIntegrityReport(client)
    client.execute("INSERT INTO stock_basic (code, name, price_limit_pct) VALUES ('C.SH','丙', 0.10)")
    client.execute("INSERT INTO daily_bar (code, trade_date, close, pre_close) "
                   "VALUES ('C.SH', DATE '2024-01-02', 10.0, 10.0),"
                   "('C.SH', DATE '2024-01-03', 10.0, 10.0),"
                   "('C.SH', DATE '2024-01-04', 10.0, 10.0),"
                   "('C.SH', DATE '2024-01-05', 10.0, 10.0),"
                   "('C.SH', DATE '2024-01-08', 10.0, 10.0),"
                   "('C.SH', DATE '2024-01-09', 20.0, 10.0)")   # 第 6 个交易日 +100% 异常
    rep.scan_quality_issues()
    iid = int(client.query_df(
        "SELECT id FROM data_quality_issue WHERE issue_type='abnormal_change'").iloc[0]["id"])
    from backend.services import ingest

    def _boom(self, code, start, end, *a, **k):
        raise RuntimeError("_sina_daily 重试 3 次仍失败: No value to decode")
    monkeypatch.setattr(ingest.IngestionService, "__init__", lambda self, source=None: None, raising=True)
    monkeypatch.setattr(ingest.IngestionService, "ingest_one_daily", _boom, raising=True)
    monkeypatch.setattr("backend.services.async_task._mark_snapshots_stale", lambda: 0)
    svc = AsyncTaskService(client)
    t = _wait(svc, svc.create("fix", {"issue_id": iid}))
    assert t["status"] == "failed"                      # 部分失败任务标 failed（可续跑）
    assert t["result"]["ok"] is False and t["result"]["failed"] == 1
    # 关键：绝不留 fixing；fix_task_id 已清
    row = client.query_df("SELECT status, fix_task_id FROM data_quality_issue WHERE id=?", [iid]).iloc[0]
    assert row["status"] == "open" and (row["fix_task_id"] is None or pd.isna(row["fix_task_id"]))


def test_ignore_sticks_across_rescan(client):
    """标记为正常/忽略后，幂等重扫不再把它翻回 open（DM-D22）。"""
    rep = DataIntegrityReport(client)
    _seed(client)
    rep.scan_quality_issues()
    iid = _gap_issue_id(client)
    from backend.api.data_admin import quality_ignore
    quality_ignore(iid)
    rep.scan_quality_issues()   # 重扫
    open_gap = int(client.query_df("SELECT count(*) AS n FROM data_quality_issue "
                                   "WHERE code='B.SH' AND issue_type='data_gap' AND status='open'").iloc[0]["n"])
    assert open_gap == 0   # 被忽略豁免，不再产生 open
    assert client.query_df("SELECT status FROM data_quality_issue WHERE id=?", [iid]).iloc[0]["status"] == "ignored"


def test_three_views_consistent(client):
    """闭环4：概览/逐股/质检三处同口径——缺口数一致。"""
    rep = DataIntegrityReport(client)
    _seed(client)
    qm = rep.quality_model()
    sq = rep.stock_quality()
    sq_gap = sum(1 for r in sq["list"] if r["layers"]["L4"]["ok"] is False)
    scan = rep.scan_quality_issues()
    assert qm["gaps"]["stocks_with_gap"] == sq_gap == scan["data_gap_rows"] + scan["stale_rows"]


# ── 每日自动任务默认含质检步（DM-D14）──
def test_daily_pipeline_includes_quality_step(client):
    """v2.0 精简后每日流程 = 更新（含补市值）→ 数据质检；公共榜单由评分维护/CLI 生产。"""
    from backend.services.pipeline import DailyPipeline
    client.execute("INSERT INTO daily_bar (code, trade_date, close, pre_close) "
                   "VALUES ('A.SH', DATE '2024-01-03', 10.0, 9.9)")
    # 本用例只验证质检编排；关闭独立的板块联网采集，避免单测依赖外部行情源。
    res = DailyPipeline(client).run(skip_update=True, board=False)
    names = [s["step"] for s in res["steps"]]
    assert "数据质检" in names
    # 评分榜单/预设筛选已不再作为每日流程步骤；公共榜单生产由评分维护/CLI 承担。
    assert "打分榜单+买点风险" not in names and "预设筛选" not in names


# ── M2.9.3：补市值已并入更新行情（update 容错子阶段），不再单列流程步骤 ──
def test_update_includes_valuation(client, monkeypatch):
    from backend.config import get_effective_settings
    from backend.services import ingest
    from backend.storage.repository import MarketRepository

    # 只装配 update() 实际用到的依赖，跳过数据源构造（避免引入 akshare）
    def _init(self, source=None):
        self.s = get_effective_settings()
        self.c = client
        self.repo = MarketRepository(client)
    monkeypatch.setattr(ingest.IngestionService, "__init__", _init, raising=True)
    monkeypatch.setattr(ingest.IngestionService, "ingest_calendar", lambda self, *a, **k: None, raising=True)
    monkeypatch.setattr(ingest.IngestionService, "ingest_indices", lambda self, *a, **k: 0, raising=True)
    called = {"val": False}
    monkeypatch.setattr(ingest.IngestionService, "ingest_valuation",
                        lambda self, codes=None, concurrency=None: called.__setitem__("val", True) or {"total_mv_rows": 0},
                        raising=True)
    res = ingest.IngestionService().update()  # 空在市股 → 只跑日历/指数/补市值子阶段
    assert called["val"] is True and "valuation" in res


def test_index_incremental_uses_each_code_latest_date_and_backfills_new_code(client, monkeypatch):
    """旧指数已最新不能阻断新指数按系统历史窗口首次回填。"""
    from backend.config import get_effective_settings
    from backend.services import ingest
    from backend.storage.repository import MarketRepository

    client.execute(
        "INSERT INTO index_bar (index_code, trade_date, close) VALUES "
        "('000905.SH', DATE '2026-08-25', 6000), "
        "('000300.SH', DATE '2026-08-20', 4000)"
    )

    def _init(self, source=None):
        self.s = get_effective_settings()
        self.c = client
        self.repo = MarketRepository(client)

    monkeypatch.setattr(ingest.IngestionService, "__init__", _init, raising=True)
    calls = []
    monkeypatch.setattr(
        ingest.IngestionService,
        "ingest_indices",
        lambda self, start, end, ctx=None, codes=None: calls.append((codes[0], start, end)) or 1,
        raising=True,
    )

    written = ingest.IngestionService()._ingest_indices_incremental(date(2026, 8, 25))
    by_code = {code: (start, end) for code, start, end in calls}
    assert "000905.SH" not in by_code
    assert by_code["000300.SH"] == (date(2026, 8, 21), date(2026, 8, 25))
    assert by_code["000001.SH"] == (date(2021, 8, 25), date(2026, 8, 25))
    assert by_code["000688.SH"] == (date(2021, 8, 25), date(2026, 8, 25))
    assert by_code["399001.SZ"] == (date(2021, 8, 25), date(2026, 8, 25))
    assert by_code["399006.SZ"] == (date(2021, 8, 25), date(2026, 8, 25))
    assert written == 5


# ── 续跑修复：终止信号穿透尾部容错兜底 / 续跑锁定目标日且跳过前置 ──
def test_update_cancel_in_valuation_propagates(client, monkeypatch):
    """回归：补市值阶段被终止时 TaskCancelled 必须穿透 update() 容错兜底（而非被
    except Exception 当成"市值源失败"吞掉后跑完）→ 任务才能转可续跑中断。"""
    from backend.config import get_effective_settings
    from backend.services import ingest
    from backend.services.async_task import TaskCancelled, TaskContext
    from backend.storage.repository import MarketRepository

    def _init(self, source=None):
        self.s = get_effective_settings()
        self.c = client
        self.repo = MarketRepository(client)
    monkeypatch.setattr(ingest.IngestionService, "__init__", _init, raising=True)
    monkeypatch.setattr(ingest.IngestionService, "ingest_calendar", lambda self, *a, **k: None, raising=True)
    monkeypatch.setattr(ingest.IngestionService, "ingest_indices", lambda self, *a, **k: 0, raising=True)

    def _cancel(self, *a, **k):  # 模拟在补最新日市值的检查点点了终止
        raise TaskCancelled()
    monkeypatch.setattr(ingest.IngestionService, "ingest_valuation_latest", _cancel, raising=True)

    ctx = TaskContext(AsyncTaskService(client), "task_cancel_val")
    with pytest.raises(TaskCancelled):
        ingest.IngestionService().update(ctx=ctx)


def test_resume_pins_target_end_and_skips_prep(client, monkeypatch):
    """续跑：checkpoint 有 target_end 时沿用该目标日、跳过日历/指数前置与就绪重探，
    不被重算成今天（修问题 2a/2b）。"""
    from backend.config import get_effective_settings
    from backend.services import ingest
    from backend.services.async_task import TaskContext
    from backend.storage.repository import MarketRepository

    def _init(self, source=None):
        self.s = get_effective_settings()
        self.c = client
        self.repo = MarketRepository(client)
    monkeypatch.setattr(ingest.IngestionService, "__init__", _init, raising=True)
    calls = {"cal": 0, "idx": 0, "resolve": 0}
    monkeypatch.setattr(ingest.IngestionService, "ingest_calendar",
                        lambda self, *a, **k: calls.__setitem__("cal", calls["cal"] + 1), raising=True)
    monkeypatch.setattr(ingest.IngestionService, "ingest_indices",
                        lambda self, *a, **k: calls.__setitem__("idx", calls["idx"] + 1), raising=True)
    monkeypatch.setattr(ingest.IngestionService, "_resolve_update_end",
                        lambda self, *a, **k: calls.__setitem__("resolve", calls["resolve"] + 1) or date.today(),
                        raising=True)
    monkeypatch.setattr(ingest.IngestionService, "ingest_valuation_latest", lambda self, *a, **k: {}, raising=True)
    monkeypatch.setattr(ingest.IngestionService, "ingest_valuation",
                        lambda self, *a, **k: {"total_mv_rows": 0}, raising=True)

    ctx = TaskContext(AsyncTaskService(client), "task_resume_pin",
                      checkpoint={"target_end": "2024-01-05", "done_codes": []})
    ingest.IngestionService().update(ctx=ctx)
    assert calls == {"cal": 0, "idx": 0, "resolve": 0}      # 前置/就绪门全跳过
    assert ctx.checkpoint["target_end"] == "2024-01-05"     # 沿用原目标日，未被重算成今天


def test_update_resume_retries_failed_code_with_empty_exact_checkpoint(client, monkeypatch):
    """新版精确 checkpoint 的 done_codes=[] 表示没有成功项，不能按 phase_done 跳过失败股票。"""
    from backend.config import get_effective_settings
    from backend.services import ingest
    from backend.services.async_task import TaskContext
    from backend.storage.repository import MarketRepository

    client.execute(
        "INSERT INTO stock_basic (code, name, price_limit_pct) VALUES ('A.SH','甲',0.10)"
    )

    def _init(self, source=None):
        self.s = get_effective_settings()
        self.c = client
        self.repo = MarketRepository(client)
        self.src = SimpleNamespace(name="fake")

    monkeypatch.setattr(ingest.IngestionService, "__init__", _init, raising=True)
    monkeypatch.setattr(DataIntegrityReport, "gapped_codes", lambda self: [], raising=True)
    monkeypatch.setattr(
        ingest.IngestionService, "ingest_valuation_latest", lambda self, *a, **k: {}, raising=True
    )
    monkeypatch.setattr(
        ingest.IngestionService,
        "ingest_valuation",
        lambda self, *a, **k: {"total_mv_rows": 0},
        raising=True,
    )
    monkeypatch.setattr(
        ingest.IngestionService, "_mark_snapshots_stale", lambda self: 0, raising=True
    )

    calls = []

    def _fail(self, code, end, **kwargs):
        calls.append(code)
        raise RuntimeError("source unavailable")

    monkeypatch.setattr(ingest.IngestionService, "_update_one", _fail, raising=True)
    checkpoint = {"target_end": "2024-01-05", "done_codes": []}
    first_ctx = TaskContext(AsyncTaskService(client), "task_resume_failed", checkpoint=checkpoint)
    first = ingest.IngestionService().update(ctx=first_ctx, concurrency=1)
    assert first["fail"] == 1
    assert first_ctx.checkpoint["done"] == 0
    assert first_ctx.checkpoint["done_codes"] == []

    monkeypatch.setattr(
        ingest.IngestionService,
        "_update_one",
        lambda self, code, end, **kwargs: calls.append(code) or 0,
        raising=True,
    )
    retry_ctx = TaskContext(
        AsyncTaskService(client), "task_retry_failed", checkpoint=first_ctx.checkpoint.copy()
    )
    second = ingest.IngestionService().update(ctx=retry_ctx, concurrency=1)
    assert second["ok"] == 1
    assert calls == ["A.SH", "A.SH"]


def test_delisted_history_does_not_skip_partially_covered_code(client, monkeypatch):
    """退市股只有近期一行行情不等于历史已补全，应继续回补目标起点至退市日。"""
    from backend.config import get_effective_settings
    from backend.services import ingest
    from backend.storage.repository import MarketRepository

    client.execute(
        "INSERT INTO stock_basic (code, name, list_date, delist_date, price_limit_pct) "
        "VALUES ('600001.SH','退市样本',DATE '2020-01-01',DATE '2025-12-31',0.10)"
    )
    client.execute(
        "INSERT INTO daily_bar (code, trade_date, close, pre_close) "
        "VALUES ('600001.SH',DATE '2025-01-02',10.0,9.9)"
    )

    source = SimpleNamespace(
        name="fake-delisted",
        get_delisted_list=lambda: pd.DataFrame([{
            "code": "600001.SH", "name": "退市样本", "delist_date": date(2025, 12, 31),
        }]),
    )

    def _init(self, source=None):
        self.s = get_effective_settings()
        self.c = client
        self.repo = MarketRepository(client)

    calls = []
    monkeypatch.setattr(ingest.IngestionService, "__init__", _init, raising=True)
    monkeypatch.setattr(
        ingest.IngestionService, "_latest_open_day", lambda self: date(2026, 1, 5), raising=True
    )
    monkeypatch.setattr(
        ingest.IngestionService, "_source_for", lambda self, capability: source, raising=True
    )
    monkeypatch.setattr(
        ingest.IngestionService,
        "ingest_one_daily",
        lambda self, code, start, end, *a, **k: calls.append((code, start, end)) or 0,
        raising=True,
    )
    monkeypatch.setattr(
        ingest.IngestionService, "_mark_snapshots_stale", lambda self: 0, raising=True
    )

    result = ingest.IngestionService().ingest_delisted(years=5)
    assert result["ok"] == 1 and result["skip"] == 0
    assert calls == [("600001.SH", date(2021, 1, 5), date(2025, 12, 31))]


def test_ingest_date_collects_indices_and_resume_skips_prep(client, monkeypatch):
    """B-2：指定日期采集也补区间指数（避免回测基准缺口）；C：续跑跳过日历/指数前置。"""
    from backend.config import get_effective_settings
    from backend.services import ingest
    from backend.services.async_task import TaskContext
    from backend.storage.repository import MarketRepository

    client.execute("INSERT INTO stock_basic (code, name, price_limit_pct) VALUES ('A.SH','甲',0.10)")

    def _init(self, source=None):
        self.s = get_effective_settings(); self.c = client; self.repo = MarketRepository(client)
    monkeypatch.setattr(ingest.IngestionService, "__init__", _init, raising=True)
    calls = {"cal": 0, "idx": 0}
    monkeypatch.setattr(ingest.IngestionService, "ingest_calendar",
                        lambda self, *a, **k: calls.__setitem__("cal", calls["cal"] + 1), raising=True)
    monkeypatch.setattr(ingest.IngestionService, "ingest_indices",
                        lambda self, *a, **k: calls.__setitem__("idx", calls["idx"] + 1), raising=True)
    monkeypatch.setattr(ingest.IngestionService, "ingest_one_daily", lambda self, *a, **k: 0, raising=True)

    ctx = TaskContext(AsyncTaskService(client), "id_first")
    ingest.IngestionService().ingest_date(date(2024, 1, 2), date(2024, 1, 3), ctx=ctx)
    assert calls == {"cal": 1, "idx": 1}                    # B-2：指数也采了
    assert ctx.checkpoint.get("prep_done") is True

    ctx2 = TaskContext(AsyncTaskService(client), "id_resume",
                       checkpoint={"prep_done": True, "done_codes": []})
    ingest.IngestionService().ingest_date(date(2024, 1, 2), date(2024, 1, 3), ctx=ctx2)
    assert calls == {"cal": 1, "idx": 1}                    # C：续跑没再采前置


def test_backfill_resume_skips_prep_and_reports_mv(client, monkeypatch):
    """C：backfill 续跑跳过日历/指数/基础信息（基础信息改从库读）；B-1：结束报告缺 total_mv 数。"""
    from backend.config import get_effective_settings
    from backend.services import ingest
    from backend.services.async_task import TaskContext
    from backend.storage.repository import MarketRepository

    client.execute("INSERT INTO stock_basic (code, name, price_limit_pct) VALUES ('A.SH','甲',0.10)")

    def _init(self, source=None):
        self.s = get_effective_settings(); self.c = client; self.repo = MarketRepository(client)
    monkeypatch.setattr(ingest.IngestionService, "__init__", _init, raising=True)
    calls = {"cal": 0, "idx": 0, "basic": 0}
    monkeypatch.setattr(ingest.IngestionService, "ingest_calendar",
                        lambda self, *a, **k: calls.__setitem__("cal", calls["cal"] + 1), raising=True)
    monkeypatch.setattr(ingest.IngestionService, "ingest_indices",
                        lambda self, *a, **k: calls.__setitem__("idx", calls["idx"] + 1), raising=True)

    def _basic(self, codes=None, ctx=None):
        calls["basic"] += 1
        return pd.DataFrame([{"code": "A.SH", "name": "甲", "price_limit_pct": 0.10}])
    monkeypatch.setattr(ingest.IngestionService, "ingest_stock_basic", _basic, raising=True)
    monkeypatch.setattr(ingest.IngestionService, "ingest_one_daily", lambda self, *a, **k: 0, raising=True)
    monkeypatch.setattr(ingest.IngestionService, "_post_ingest_validate", lambda self: None, raising=True)

    ctx = TaskContext(AsyncTaskService(client), "bf_first")
    res = ingest.IngestionService().backfill(ctx=ctx)
    assert calls == {"cal": 1, "idx": 1, "basic": 1}        # 首跑前置全采
    assert ctx.checkpoint.get("prep_done") is True
    assert res["mv_missing"] == 1                            # A.SH 尚无 total_mv → 透明提示

    ctx2 = TaskContext(AsyncTaskService(client), "bf_resume", checkpoint={"prep_done": True})
    res2 = ingest.IngestionService().backfill(ctx=ctx2)
    assert calls == {"cal": 1, "idx": 1, "basic": 1}         # C：续跑未再触发前置/基础信息（改从库读）
    assert res2["target"] == 1                               # 从库读到 A.SH


# ── 补市值：流通市值仅填空缺、不覆盖新浪日线已写的更准值（baostock 兜底票靠此拿 float_mv）──
def test_valuation_fills_missing_float_mv_only(client, monkeypatch):
    from backend.config import get_effective_settings
    from backend.services import ingest
    from backend.storage.repository import MarketRepository

    # A：已有 float_mv(新浪写)但缺 total_mv；B：完全缺市值；C：已有 total_mv 但缺 float_mv。
    client.execute("INSERT INTO stock_basic (code, name) VALUES ('A.SH','甲'),('B.SH','乙'),('C.SH','丙')")
    client.execute("INSERT INTO daily_bar (code, trade_date, close, pre_close) VALUES "
                   "('A.SH', DATE '2026-06-12', 10.0, 9.9),"
                   "('B.SH', DATE '2026-06-12', 20.0, 19.9),"
                   "('C.SH', DATE '2026-06-12', 30.0, 29.9)")
    client.execute("INSERT INTO daily_metrics (code, trade_date, float_mv, total_mv) "
                   "VALUES ('A.SH', DATE '2026-06-12', 111.0, NULL),"
                   "('C.SH', DATE '2026-06-12', NULL, 777.0)")

    class _Val:
        name = "akshare"
        def supports(self, cap): return True
        def get_valuation(self, code, start, end):
            return pd.DataFrame({"code": [code], "trade_date": [date(2026, 6, 12)],
                                 "total_mv": [999.0], "float_mv": [888.0],
                                 "total_share": [100], "float_share": [80]})

    def _init(self, source=None):
        self.s = get_effective_settings()
        self.c = client
        self.repo = MarketRepository(client)
        self.src = _Val()
        self._bao = None
    monkeypatch.setattr(ingest.IngestionService, "__init__", _init, raising=True)
    ingest.IngestionService().ingest_valuation()

    rows = client.query_df("SELECT code, total_mv, float_mv FROM daily_metrics ORDER BY code")
    a = rows[rows["code"] == "A.SH"].iloc[0]
    b = rows[rows["code"] == "B.SH"].iloc[0]
    c = rows[rows["code"] == "C.SH"].iloc[0]
    assert a["total_mv"] == 999.0 and a["float_mv"] == 111.0   # total 补上，float 不被覆盖
    assert b["total_mv"] == 999.0 and b["float_mv"] == 888.0   # 兜底票 total/float 都补上
    assert c["total_mv"] == 999.0 and c["float_mv"] == 888.0   # 只有 float 缺口也不能被整股跳过


def test_valuation_latest_with_codes_fills_missing_metrics_row(client, monkeypatch):
    """指定股票补最新日市值时，daily_metrics 整行缺失也应按 daily_bar 命中。"""
    from backend.config import get_effective_settings
    from backend.services import ingest
    from backend.storage.repository import MarketRepository

    client.execute("INSERT INTO stock_basic (code, name) VALUES ('B.SH','乙')")
    client.execute("INSERT INTO daily_bar (code, trade_date, close, pre_close) "
                   "VALUES ('B.SH', DATE '2026-06-12', 20.0, 19.9)")

    class _Val:
        name = "akshare"
        def supports(self, cap): return True
        def get_valuation(self, code, start, end):
            return pd.DataFrame({"code": [code], "trade_date": [date(2026, 6, 12)],
                                 "total_mv": [999.0], "float_mv": [888.0],
                                 "total_share": [100], "float_share": [80]})

    def _init(self, source=None):
        self.s = get_effective_settings()
        self.c = client
        self.repo = MarketRepository(client)
        self.src = _Val()
        self._bao = None

    monkeypatch.setattr(ingest.IngestionService, "__init__", _init, raising=True)
    res = ingest.IngestionService().ingest_valuation_latest(codes=["B.SH"])

    row = client.query_df("SELECT total_mv, float_mv FROM daily_metrics WHERE code='B.SH'").iloc[0]
    assert res["total_mv_rows"] == 1
    assert row["total_mv"] == 999.0 and row["float_mv"] == 888.0


# ── 历史补数：仅有部分近期数据的股票(被兜底/中断补了近窗口)必须重补早期历史，不能误跳过 ──
def test_backfill_refetches_partially_covered_code(client, monkeypatch):
    from backend.config import get_effective_settings
    from backend.services import ingest
    from backend.storage.repository import MarketRepository

    s = get_effective_settings()
    today = date.today()
    start = date(today.year - s.datasource.history_years, today.month, today.day)
    old_day = date(start.year - 1, 3, 1)   # 早于回填起点 → 已覆盖，应跳过
    part_day = date(today.year, 5, 6)       # 仅近期一条 → 部分覆盖（模拟兜底补的近窗口），应重补

    client.execute("INSERT INTO stock_basic (code, name, price_limit_pct, list_date) VALUES "
                   "('OLD.SH','老',0.10, DATE '2010-01-01'),('PART.SH','部',0.10, DATE '2015-01-01')")
    client.execute("INSERT INTO daily_bar (code, trade_date, close, pre_close) VALUES (?, ?, 5.0, 5.0)",
                   ["OLD.SH", old_day])
    client.execute("INSERT INTO daily_bar (code, trade_date, close, pre_close) VALUES (?, ?, 8.0, 8.0)",
                   ["PART.SH", part_day])

    called: list[str] = []

    def _init(self, source=None):
        self.s = s
        self.c = client
        self.repo = MarketRepository(client)
        self.src = type("X", (), {"name": "akshare"})()
    monkeypatch.setattr(ingest.IngestionService, "__init__", _init, raising=True)
    monkeypatch.setattr(ingest.IngestionService, "ingest_calendar", lambda self, *a, **k: None, raising=True)
    monkeypatch.setattr(ingest.IngestionService, "ingest_indices", lambda self, *a, **k: None, raising=True)
    monkeypatch.setattr(ingest.IngestionService, "ingest_stock_basic",
                        lambda self, codes=None: client.query_df(
                            "SELECT code, name, price_limit_pct FROM stock_basic WHERE code IN ('OLD.SH','PART.SH')"),
                        raising=True)
    monkeypatch.setattr(ingest.IngestionService, "ingest_one_daily",
                        lambda self, code, start, end, *a, **k: called.append(code) or 0, raising=True)
    ingest.IngestionService().backfill(codes=["OLD.SH", "PART.SH"])
    assert "PART.SH" in called and "OLD.SH" not in called


# ── 数据源兜底 + 来源标记（主源取不到→baostock；非默认源登记 provenance）──
def test_daily_fallback_to_baostock_and_provenance(client, monkeypatch):
    from backend.config import get_effective_settings
    from backend.services import ingest
    from backend.storage.repository import MarketRepository

    class _Empty:        # 主源：对该股取不到
        name = "akshare"
        def supports(self, cap): return True
        def get_daily_bar(self, code, start, end, adjust=""): return pd.DataFrame()

    class _Bao:          # 兜底源：有数据
        name = "baostock"
        def supports(self, cap): return cap == "daily"
        def get_daily_bar(self, code, start, end, adjust=""):
            return pd.DataFrame({"code": [code], "trade_date": [date(2026, 6, 12)], "close": [35.8]})

    def _init(self, source=None):
        self.s = get_effective_settings()
        self.c = client
        self.repo = MarketRepository(client)
        self.src = _Empty()
        self._bao = _Bao()
    monkeypatch.setattr(ingest.IngestionService, "__init__", _init, raising=True)
    svc = ingest.IngestionService()

    # 主源空 → 兜底命中 baostock，返回其来源名
    df, used = svc._fetch_daily_with_fallback("689009.SH", date(2026, 6, 1), date(2026, 6, 12), svc.src)
    assert used == "baostock" and not df.empty

    # 非默认源登记一条；默认主源不登记
    svc._record_provenance("689009.SH", "daily_bar", date(2026, 6, 1), date(2026, 6, 12), used, len(df))
    svc._record_provenance("X.SH", "daily_bar", date(2026, 6, 1), date(2026, 6, 12), "akshare", 10)
    bao_n = int(client.query_df(
        "SELECT count(*) n FROM data_source_provenance WHERE code='689009.SH' AND source='baostock'").iloc[0]["n"])
    ak_n = int(client.query_df(
        "SELECT count(*) n FROM data_source_provenance WHERE source='akshare'").iloc[0]["n"])
    assert bao_n == 1 and ak_n == 0


def test_task_cancel_marks_interrupted(client, monkeypatch):
    import time as _t
    from backend.services import ingest
    monkeypatch.setattr(ingest.IngestionService, "__init__", lambda self, source=None: None, raising=True)

    def _slow(self, codes=None, concurrency=None, ctx=None):
        for _ in range(200):
            if ctx:
                ctx.check_cancel()
            _t.sleep(0.02)
        return {}
    monkeypatch.setattr(ingest.IngestionService, "update", _slow, raising=True)
    monkeypatch.setattr("backend.services.async_task._mark_snapshots_stale", lambda: 0)
    svc = AsyncTaskService(client)
    tid = svc.create("update")
    # 等到 running 后请求终止
    for _ in range(40):
        if (svc.get(tid) or {}).get("status") == "running":
            break
        time.sleep(0.05)
    assert svc.cancel(tid) is True
    t = _wait(svc, tid)
    assert t["status"] == "interrupted" and "终止" in (t["message"] or "")


# ── 去抖干净因子：根治 qfq 逐日漂移（福达合金式样本）──

# 福达合金真实样本：非除权日因子本应恒定却带源端舍入噪声，2026-06-11 真实除权。
_FD_DATES = [date(2026, 6, d) for d in (8, 9, 10, 11, 12)]
_FD_CLOSE = [90.00, 89.20, 80.28, 76.01, 72.86]
_FD_AF = [1.448667, 1.448655, 1.448680, 1.451388, 1.451276]  # 反推因子，逐日抖


def _seed_fd(c, dates=_FD_DATES, close=_FD_CLOSE, af=_FD_AF):
    rows = [{"code": "603045.SH", "trade_date": d, "open": px, "high": px, "low": px,
             "close": px, "pre_close": None, "volume": 1000, "amount": 1e5,
             "adj_factor": a, "turnover_rate": 1.0, "is_st": False,
             "is_suspended": False, "limit_status": 0, "is_one_word": False}
            for d, px, a in zip(dates, close, af)]
    c.register_df("_fd", pd.DataFrame(rows))
    c.execute("INSERT INTO daily_bar BY NAME SELECT * FROM _fd")
    c.unregister("_fd")
    c.execute("INSERT INTO stock_basic (code, name, price_limit_pct) "
              "VALUES ('603045.SH', '福达合金', 0.10)")


def test_clean_factor_rebuild_makes_qfq_jitter_free(client):
    """rebuild 后干净因子分段恒定；qfq 非除权日相邻比值 == 原始收盘比值（消除源因子噪声）。"""
    from backend.services.ingest import IngestionService
    from backend.storage.repository import MarketRepository

    _seed_fd(client)
    IngestionService().rebuild_price_factors(codes=["603045.SH"])

    clean = client.query_df(
        "SELECT adj_factor_clean FROM daily_bar WHERE code='603045.SH' ORDER BY trade_date"
    )["adj_factor_clean"].tolist()
    assert clean[0] == clean[1] == clean[2]      # 08~10 非除权日 → 恒定（噪声被消）
    assert clean[3] == clean[4]                  # 11~12 除权后 → 恒定
    assert clean[2] != clean[3]                  # 10→11 真实除权 → 跳变

    repo = MarketRepository(client)
    qfq = repo.get_bars("603045.SH", end_date=date(2026, 6, 12), adjust="qfq")
    q = qfq.set_index(qfq["trade_date"].astype(str))["close"]
    # 非除权日 09→10：qfq 比值精确等于原始收盘比值（旧的裸 adj_factor 会带 ~1e-5 噪声）
    assert abs(q["2026-06-10"] / q["2026-06-09"] - _FD_CLOSE[2] / _FD_CLOSE[1]) < 1e-9
    # 归一基准日（06-12）qfq 收盘 == 原始收盘
    assert abs(q["2026-06-12"] - _FD_CLOSE[4]) < 1e-9


def test_clean_factor_incremental_refresh_carries_forward(client):
    """增量刷新：新非除权日沿用上一日干净因子，与历史连续，qfq 不再生噪声。"""
    from backend.services.ingest import IngestionService
    from backend.storage.repository import MarketRepository

    _seed_fd(client)
    svc = IngestionService()
    svc.rebuild_price_factors(codes=["603045.SH"])  # 历史清洗
    anchor_clean = client.query_df(
        "SELECT adj_factor_clean FROM daily_bar WHERE code='603045.SH' AND trade_date=DATE '2026-06-12'"
    ).iloc[0]["adj_factor_clean"]

    # 追加一个非除权新交易日（裸因子带噪声，clean 留空），模拟日更入库
    new = pd.DataFrame([{"code": "603045.SH", "trade_date": date(2026, 6, 15),
                         "open": 73.50, "high": 73.50, "low": 73.50, "close": 73.50,
                         "pre_close": None, "volume": 1000, "amount": 1e5,
                         "adj_factor": 1.451300, "turnover_rate": 1.0, "is_st": False,
                         "is_suspended": False, "limit_status": 0, "is_one_word": False}])
    client.register_df("_n", new)
    client.execute("INSERT INTO daily_bar BY NAME SELECT * FROM _n")
    client.unregister("_n")

    svc._refresh_clean_factors(["603045.SH"])  # 锚定增量

    new_clean = client.query_df(
        "SELECT adj_factor_clean FROM daily_bar WHERE code='603045.SH' AND trade_date=DATE '2026-06-15'"
    ).iloc[0]["adj_factor_clean"]
    assert abs(new_clean - anchor_clean) < 1e-9   # 非除权 → 沿用上一日干净因子（连续）

    repo = MarketRepository(client)
    qfq = repo.get_bars("603045.SH", end_date=date(2026, 6, 15), adjust="qfq")
    q = qfq.set_index(qfq["trade_date"].astype(str))["close"]
    assert abs(q["2026-06-15"] / q["2026-06-12"] - 73.50 / _FD_CLOSE[4]) < 1e-9


def test_daily_refetch_invalidates_stale_clean_factor(client, monkeypatch):
    """源日线被覆盖修正时，旧 adj_factor_clean 必须清空并从前一干净锚点重算。"""
    from backend.services.ingest import IngestionService
    from backend.storage.repository import MarketRepository

    _seed_fd(
        client,
        dates=[date(2026, 7, 3), date(2026, 7, 6)],
        close=[9.55, 9.28],
        af=[1.994764, 1.994612],
    )
    client.execute(
        "UPDATE daily_bar SET adj_factor_clean = CASE "
        "WHEN trade_date=DATE '2026-07-03' THEN 1.994744 ELSE 3.976995 END "
        "WHERE code='603045.SH'"
    )

    fresh = pd.DataFrame([{
        "code": "603045.SH", "trade_date": date(2026, 7, 6),
        "open": 9.60, "high": 9.76, "low": 9.23, "close": 9.28,
        "pre_close": 9.55, "volume": 1000, "amount": 1e5,
        "adj_factor": 1.994612, "turnover_rate": 1.0,
    }])
    svc = IngestionService()
    monkeypatch.setattr(
        svc, "_fetch_daily_with_fallback", lambda *a, **k: (fresh, svc.s.datasource.primary)
    )

    svc.ingest_one_daily("603045.SH", date(2026, 7, 6), date(2026, 7, 6))
    svc._refresh_clean_factors(["603045.SH"])

    rows = client.query_df(
        "SELECT trade_date, adj_factor_clean, pre_close FROM daily_bar "
        "WHERE code='603045.SH' ORDER BY trade_date"
    )
    assert rows["adj_factor_clean"].tolist() == [1.994744, 1.994744]
    assert abs(rows.iloc[1]["pre_close"] - 9.55) < 1e-9

    qfq = MarketRepository(client).get_bars("603045.SH", end_date=date(2026, 7, 6), adjust="qfq")
    q = qfq.set_index(qfq["trade_date"].astype(str))["close"]
    assert abs(q["2026-07-06"] / q["2026-07-03"] - 9.28 / 9.55) < 1e-9
