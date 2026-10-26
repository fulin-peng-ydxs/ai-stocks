"""板块采集服务单测（T4，mock ThsBoardSource + 文件 DuckDB，不触网）。

覆盖 plan §6.4 产出断言：只进不出落库（ON CONFLICT 幂等）/ 不完整快照不落库 /
资金流映射与未匹配质检 / member_count 刷新（完整快照刷新）/ 事务原子性（中途失败整体回滚）
/ 写锁冲突归类（跨进程独立测试）。
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from backend.common.exceptions import StorageError
from backend.services.async_task import TaskCancelled
from backend.services.board_ingest import BoardIngestService
from backend.storage.ddl import init_db
from backend.storage.duckdb_client import DuckDBClient

_EMPTY_MEMBER_DF = pd.DataFrame(columns=["board_code", "name"])
_EMPTY_BAR_DF = pd.DataFrame(columns=["trade_date", "open", "high", "low", "close",
                                      "volume", "amount"])
_EMPTY_FLOW_DF = pd.DataFrame(columns=["name", "inflow", "outflow", "net_inflow", "net_ratio",
                                       "leader_stock", "leader_pct"])


class _FakeSource:
    """mock ThsBoardSource：按 board_code 返回预置成分/完整标记。"""

    def __init__(self, members: dict, complete: dict | None = None, fund_flow=None, bar=None,
                 board_dict=None, app_codes=None):
        self._members = members          # {code: [6位codes]}
        self._complete = complete or {}  # {code: bool}，缺省 True
        self._fund_flow = fund_flow or {}
        self._bar = bar or {}
        self._board_dict = board_dict or {}
        self._app_codes = app_codes or {}

    def get_board_members(self, code, board_type="concept"):
        codes = self._members.get(code, [])
        return {"codes": codes, "complete": self._complete.get(code, True), "pages": 1}

    def fork(self):
        from copy import copy
        return copy(self)

    def close(self):
        pass

    def get_board_dict(self, board_type):
        return self._board_dict.get(board_type, _EMPTY_MEMBER_DF)

    def get_board_app_code(self, code, board_type):
        return self._app_codes.get(code, code if board_type == "industry" else f"88{code[2:]}")

    def get_board_bar(self, code, board_type, start, end):
        return self._bar.get(code, _EMPTY_BAR_DF)

    def get_board_fund_flow(self, board_type, period):
        return self._fund_flow.get((board_type, period), _EMPTY_FLOW_DF)


def _make_service(tmp_path, source=None, **kw) -> tuple[BoardIngestService, DuckDBClient]:
    c = DuckDBClient(db_path=str(tmp_path / "test.duckdb"))
    init_db(c)
    svc = BoardIngestService(client=c, source=source, **kw)
    return svc, c


def _member_count(c: DuckDBClient, board_code: str) -> int:
    """读板块冗余成员数（断言辅助）。"""
    df = c.query_df("SELECT member_count FROM board_dict WHERE board_code=?", [board_code])
    mc = df.iloc[0]["member_count"]
    return 0 if mc is None or pd.isna(mc) else int(mc)


# ── payload_hash 规范化与幂等四态 ─────────────────────────────


def test_board_codes_filter_in_clause(tmp_path):
    """board_codes 过滤走 IN (?,?,...) 占位符展开（DuckDB 对 IN (?) 传 list 会 Conversion Error）。"""
    src = _FakeSource({"309121": ["300476"], "881121": ["600000"]})
    svc, c = _make_service(tmp_path, src)
    for code, name, bt in [("309121", "AI PC", "concept"), ("881121", "半导体", "industry")]:
        c.execute("INSERT INTO board_dict (board_code, name, board_type, has_members) "
                  "VALUES (?,?,?,TRUE)", [code, name, bt])
    # ingest_board_members 指定 board_codes → 不崩且只处理指定板块
    r = svc.ingest_board_members(snapshot_date=date(2026, 1, 5), board_codes=["309121"], force=True)
    assert set(r.keys()) == {"309121"}
    assert "881121" not in r
    # ingest_board_bar 指定 board_codes（空 bar 返回不崩）
    bar = svc.ingest_board_bar(date(2026, 1, 1), board_codes=["881121"])
    assert "boards" in bar


def test_empty_code_scope_never_expands_to_all_boards(tmp_path):
    """显式空代码集合表示空范围，不能因 Python 假值判断退化成全量采集。"""
    src = _FakeSource({"309121": ["300476"]})
    svc, c = _make_service(tmp_path, src)
    c.execute("INSERT INTO board_dict (board_code, name, board_type, has_members, has_bar) "
              "VALUES ('309121','AI PC','concept',TRUE,TRUE)")
    assert svc.ingest_board_members(board_codes=[]) == {}
    r = svc.ingest_board_bar(date(2026, 1, 1), board_codes=[])
    assert r["rows"] == 0 and r["boards"] == 0 and r["failed"] == []
    resumed = svc.ingest_board_bar(
        None, end=date(2026, 1, 2), board_codes=[], resume_from_latest=True,
    )
    assert resumed["start"] is None and resumed["end"] == "2026-01-02"
    assert svc.ingest_board_fund_flow(board_codes=[]) == {
        "rows": 0, "unmatched": 0, "failed": [],
    }
    assert c.query_df("SELECT * FROM board_member").empty


def test_member_snapshot_keeps_raw_count_but_drops_bse_relations(tmp_path):
    """源端快照数保留原口径，项目关系表只落主板、创业板和科创板。"""
    src = _FakeSource({"309121": ["300476", "688981", "920249"]})
    svc, c = _make_service(tmp_path, src)
    c.execute(
        "INSERT INTO board_dict (board_code,name,board_type,has_members) "
        "VALUES ('309121','AI PC','concept',TRUE)"
    )

    result = svc.ingest_board_members(
        snapshot_date=date(2026, 1, 5), board_codes=["309121"], force=True,
    )["309121"]

    assert result == {
        "total": 3,
        "eligible_total": 2,
        "excluded_out_of_scope": 1,
        "added": 2,
    }
    assert c.query_df(
        "SELECT code FROM board_member ORDER BY code"
    )["code"].tolist() == ["300476.SZ", "688981.SH"]
    assert _member_count(c, "309121") == 3


def test_board_type_limits_dictionary_and_members(tmp_path):
    """board_type 是真实作用域：只拉取并处理指定的概念或行业。"""
    src = _FakeSource(
        {"309121": ["300476"], "881121": ["600000"]},
        board_dict={
            "concept": pd.DataFrame([{"board_code": "309121", "name": "AI PC"}]),
            "industry": pd.DataFrame([{"board_code": "881121", "name": "半导体"}]),
        },
    )
    svc, c = _make_service(tmp_path, src)
    result = svc.ingest_board_dict(board_type="concept")
    assert result["concept"] == 1 and result["industry"] == 0
    assert c.query_df("SELECT board_type FROM board_dict")["board_type"].tolist() == ["concept"]
    svc.ingest_board_dict(board_type="industry")
    members = svc.ingest_board_members(board_type="industry", force=True)
    assert set(members) == {"881121"}


def test_member_checkpoint_and_resume_skip_completed(tmp_path):
    """逐板块成功后立即写 checkpoint；中断续跑只处理未完成板块。"""
    src = _FakeSource({"309121": ["300476"], "881121": ["600000"]})
    svc, c = _make_service(tmp_path, src)
    c.execute("INSERT INTO board_dict (board_code, name, board_type, has_members) VALUES "
              "('309121','AI PC','concept',TRUE),('881121','半导体','industry',TRUE)")

    class _Ctx:
        def __init__(self, checkpoint=None, cancel_at=None):
            self.checkpoint = checkpoint or {}
            self.cancel_at = cancel_at
            self.checks = 0

        def check_cancel(self):
            self.checks += 1
            if self.cancel_at and self.checkpoint.get("member_done_codes"):
                raise TaskCancelled()

        def set_phase(self, phase, **data):
            self.checkpoint.update({"phase": phase, **data})

        def log(self, *args, **kwargs):
            pass

    first = _Ctx(cancel_at=2)
    with pytest.raises(TaskCancelled):
        svc.ingest_board_members(
            board_codes=["309121", "881121"], ctx=first, force=True, concurrency=1,
        )
    assert first.checkpoint["member_done_codes"] == ["309121"]

    resumed = _Ctx(checkpoint=dict(first.checkpoint))
    result = svc.ingest_board_members(board_codes=["309121", "881121"], ctx=resumed, force=True)
    assert set(result) == {"881121"}
    assert resumed.checkpoint["member_done_codes"] == ["309121", "881121"]


def test_dict_checkpoint_resume_backfills_counts(tmp_path):
    """续跑命中 dict checkpoint：跳过拉取但按库内数量回填计数，日志不再误报 0。"""
    src = _FakeSource(
        {},
        board_dict={
            "concept": pd.DataFrame([{"board_code": "309121", "name": "AI PC"}]),
            "industry": pd.DataFrame([{"board_code": "881121", "name": "半导体"}]),
        },
    )
    svc, c = _make_service(tmp_path, src)
    first = svc.ingest_board_dict()
    assert first["concept"] == 1 and first["industry"] == 1

    class _Ctx:
        def __init__(self):
            self.checkpoint = {"dict_done_types": ["concept", "industry"]}
            self.logs = []

        def check_cancel(self):
            pass

        def set_phase(self, phase, **data):
            self.checkpoint.update({"phase": phase, **data})

        def log(self, msg, *args, **kwargs):
            self.logs.append(msg)

    ctx = _Ctx()
    resumed = svc.ingest_board_dict(ctx=ctx)
    assert resumed["concept"] == 1 and resumed["industry"] == 1 and resumed["total"] == 2
    assert resumed["failed"] == []
    assert any("跳过" in m for m in ctx.logs)
    # 续跑跳过不重拉、不改库：字典数据保持首跑结果
    assert c.query_df("SELECT count(*) AS n FROM board_dict")["n"].iloc[0] == 2


def test_member_weekly_skip_within_interval(tmp_path):
    """周频跳过：已完整落库且距今不足间隔的板块默认跳过，force 才全量拉。

    前提是「成分完整」= member_snapshot_at 存在；从未完整落库的板块必须拉（不跳过）。
    """
    src = _FakeSource({"309121": ["300476"], "881121": ["600000"]})
    svc, c = _make_service(tmp_path, src, member_interval_days=7)

    # 板块 A 从未完整落库（member_snapshot_at IS NULL）→ 必须拉；板块 B 刚完整拉过 → 跳过
    c.execute("INSERT INTO board_dict (board_code, name, board_type, has_members) "
              "VALUES ('309121','AI PC','concept',TRUE),('881121','半导体','industry',TRUE)")
    c.execute("UPDATE board_dict SET member_snapshot_at=now() WHERE board_code='881121'")

    r = svc.ingest_board_members(board_codes=["309121", "881121"])
    assert r["309121"]["total"] == 1          # 从未完整 → 拉了
    assert r["881121"]["skipped"] is True     # 刚拉过 → 跳过
    # 跳过不写 failed、不写 incomplete issue
    issues = c.query_df("SELECT count(*) AS n FROM data_quality_issue "
                        "WHERE issue_type='board_member_incomplete'")
    assert int(issues.iloc[0]["n"]) == 0

    # force=True → 全量拉（质量修复/backfill 用）
    r2 = svc.ingest_board_members(board_codes=["881121"], force=True)
    assert r2["881121"]["total"] == 1


# ── 成分快照（只进不出）与 member_count ─────────────────────


def test_member_only_append_no_delete(tmp_path):
    """只进不出：完整快照落库 (board_code, code)，重复采集只新增不删除不重复。"""
    src = _FakeSource({"309121": ["300476", "603936", "002913"]})
    svc, c = _make_service(tmp_path, src)
    c.execute("INSERT INTO board_dict (board_code, name, board_type, has_members) "
              "VALUES ('309121','AI PC','concept',TRUE)")
    r = svc._ingest_one_member("309121", "concept", date(2026, 1, 5))
    assert r["total"] == 3
    df = c.query_df("SELECT board_code, code, first_seen_date FROM board_member")
    assert len(df) == 3
    assert set(df["code"]) == {"300476.SZ", "603936.SH", "002913.SZ"}
    assert set(pd.to_datetime(df["first_seen_date"]).dt.date) == {date(2026, 1, 5)}
    # member_count 刷新为本次完整快照返回数
    assert int(_member_count(c, "309121")) == 3
    assert r["added"] == 3
    # 第二次快照：新股 300750 新增，缺席股 002913 保留（不删除）
    src2 = _FakeSource({"309121": ["300476", "603936", "300750"]})
    svc2, c2 = _make_service(tmp_path.parent / "t2.duckdb", src2)
    c2.execute("INSERT INTO board_dict (board_code, name, board_type, has_members, member_count) "
               "VALUES ('309121','AI PC','concept',TRUE, 3)")
    for code in ["300476.SZ", "603936.SH", "002913.SZ"]:
        c2.execute("INSERT INTO board_member (board_code, code) VALUES ('309121',?)", [code])
    r2 = svc2._ingest_one_member("309121", "concept", date(2026, 1, 6))
    # 300750 新增，002913 保留（只进不出）
    assert r2["total"] == 3
    df2 = c2.query_df("SELECT code, first_seen_date FROM board_member")
    assert set(df2["code"]) == {"300476.SZ", "603936.SH", "002913.SZ", "300750.SZ"}
    first_seen = dict(zip(df2["code"], df2["first_seen_date"]))
    assert pd.isna(first_seen["300476.SZ"])
    assert pd.Timestamp(first_seen["300750.SZ"]).date() == date(2026, 1, 6)
    assert int(_member_count(c2, "309121")) == 3  # 当前快照成分数
    assert r2["added"] == 1


def test_incomplete_snapshot_not_applied(tmp_path):
    """不完整快照（complete=False）→ 抛错不落库，member_count 不刷新，写 board_member_incomplete issue。"""
    src = _FakeSource({"309121": ["300476", "603936"]}, complete={"309121": False})
    svc, c = _make_service(tmp_path, src)
    c.execute("INSERT INTO board_dict (board_code, name, board_type, has_members, member_count) "
              "VALUES ('309121','AI PC','concept',TRUE, 10)")
    with pytest.raises(Exception):
        svc._ingest_one_member("309121", "concept", date(2026, 1, 5))
    # board_member 不落库，member_count 不刷新
    assert len(c.query_df("SELECT 1 FROM board_member")) == 0
    assert int(_member_count(c, "309121")) == 10


def test_member_incomplete_ignored_exempt(tmp_path):
    """已忽略的 board_member_incomplete 不重复建（ignored 豁免对齐 fund/index_gap）。"""
    src = _FakeSource({"309121": ["300476"]}, complete={"309121": False})
    svc, c = _make_service(tmp_path, src)
    c.execute("INSERT INTO board_dict (board_code, name, board_type, has_members) "
              "VALUES ('309121','AI PC','concept',TRUE)")
    # 预置一条已忽略的 member issue
    c.execute("INSERT INTO data_quality_issue "
              "(id, code, issue_type, severity, status, detected_at) "
              "VALUES (7, '309121', 'board_member_incomplete', 'mid', 'ignored', now())")
    # 走完整 ingest_board_members：成分不完整 → 触发 _write_incomplete_quality，
    # ignored 已存在则不重复建 open（豁免生效）
    r = svc.ingest_board_members(board_codes=["309121"], force=True)
    assert "error" in r["309121"]
    issues = c.query_df(
        "SELECT status FROM data_quality_issue WHERE issue_type='board_member_incomplete'")
    assert len(issues) == 1
    assert issues.iloc[0]["status"] == "ignored"  # 不翻回 open、不新增


def test_member_upsert_idempotent_on_conflict(tmp_path):
    """ON CONFLICT 幂等：同板块同股重复采集不产生重复行。"""
    src = _FakeSource({"309121": ["300476", "603936"]})
    svc, c = _make_service(tmp_path, src)
    c.execute("INSERT INTO board_dict (board_code, name, board_type, has_members) "
              "VALUES ('309121','AI PC','concept',TRUE)")
    svc._ingest_one_member("309121", "concept", date(2026, 1, 5))
    svc._ingest_one_member("309121", "concept", date(2026, 1, 6))  # 同股重复
    df = c.query_df("SELECT code FROM board_member")
    assert len(df) == 2  # 不重复


def test_member_history_start_date_first_only(tmp_path):
    """member_history_start_date：首次完整采集写入，已存在不覆盖。"""
    src = _FakeSource({"309121": ["300476"]})
    svc, c = _make_service(tmp_path, src)
    c.execute("INSERT INTO board_dict (board_code, name, board_type, has_members) "
              "VALUES ('309121','AI PC','concept',TRUE)")
    svc._ingest_one_member("309121", "concept", date(2026, 1, 5))
    svc._ingest_one_member("309121", "concept", date(2026, 1, 6))
    d = c.query_df(
        "SELECT member_history_start_date FROM board_dict "
        "WHERE board_code='309121'").iloc[0]
    assert pd.Timestamp(d["member_history_start_date"]).date() == date(2026, 1, 5)  # 首日保留


# ── 资金流映射与未匹配质检 ────────────────────────────────────


def test_fund_flow_mapping_and_unmatched(tmp_path):
    """资金流名称匹配映射 + 未匹配写质检（不伪造代码）。"""
    import pandas as pd
    ff = {
        ("concept", "即时"): pd.DataFrame([{
            "name": "AI PC", "inflow": 10.0, "outflow": 5.0, "net_inflow": 5.0,
            "net_ratio": 2.5, "leader_stock": "胜宏科技", "leader_pct": 12.0}]),
        ("concept", "3日"): pd.DataFrame([{
            "name": "不存在的板块", "inflow": 1.0, "outflow": 1.0, "net_inflow": 0.0,
            "net_ratio": 0.5, "leader_stock": None, "leader_pct": None}]),
    }
    src = _FakeSource({}, fund_flow=ff)
    svc, c = _make_service(tmp_path, src)
    # 种字典：AI PC 有代码；不存在板块无
    c.execute("INSERT INTO board_dict (board_code, name, board_type, has_members) "
              "VALUES ('309121','AI PC','concept',TRUE)")
    r = svc.ingest_board_fund_flow(date(2026, 1, 5))
    # AI PC 映射成功写入 board_fund_flow
    ff_row = c.query_df("SELECT board_code, period, net_inflow FROM board_fund_flow")
    assert len(ff_row) == 1
    assert ff_row.iloc[0]["board_code"] == "309121"
    assert ff_row.iloc[0]["net_inflow"] == 5.0
    # 未匹配板块写质检（不伪造代码）
    assert r["unmatched"] >= 1
    iss = c.query_df(
        "SELECT issue_type FROM data_quality_issue "
        "WHERE issue_type='board_fund_unmatched'")
    assert len(iss) == 1
    # 能力字段收口：AI PC has_fund_flow=true
    hf_row = c.query_df("SELECT has_fund_flow FROM board_dict WHERE board_code='309121'")
    hf = hf_row.iloc[0]["has_fund_flow"]
    assert bool(hf) is True


def test_fund_flow_all_periods_default(tmp_path):
    """periods=None 默认采集全周期（即时/3日/5日/10日/20日），concept+industry 都落库。"""
    import pandas as pd

    def flow(name):
        return pd.DataFrame([{
            "name": name, "inflow": 10.0, "outflow": 5.0, "net_inflow": 5.0,
            "net_ratio": 2.5, "leader_stock": None, "leader_pct": None}])

    ff = {
        (bt, period): flow("AI PC" if bt == "concept" else "半导体")
        for bt in ("concept", "industry")
        for period in ("即时", "3日", "5日", "10日", "20日")
    }
    src = _FakeSource({}, fund_flow=ff)
    svc, c = _make_service(tmp_path, src)
    c.execute("INSERT INTO board_dict (board_code, name, board_type, has_members) "
              "VALUES ('309121','AI PC','concept',TRUE),('881121','半导体','industry',TRUE)")
    r = svc.ingest_board_fund_flow(date(2026, 1, 5))
    assert r["failed"] == []
    periods = set(c.query_df("SELECT DISTINCT period FROM board_fund_flow")["period"].tolist())
    assert periods == {"即时", "3日", "5日", "10日", "20日"}
    rows = c.query_df("SELECT board_code, period FROM board_fund_flow")
    assert len(rows) == 10  # 2 板块 × 5 周期


def test_fund_flow_upsert_same_date_and_append_next_date(tmp_path):
    """同 snapshot_date 同周期覆盖；不同 snapshot_date 新增（不误删历史快照）。"""
    import pandas as pd
    ff = {
        (bt, period): pd.DataFrame([{
            "name": "AI PC", "inflow": 10.0, "outflow": 5.0, "net_inflow": 5.0,
            "net_ratio": 2.5, "leader_stock": None, "leader_pct": None}])
        for bt in ("concept",)
        for period in ("即时", "3日", "5日", "10日", "20日")
    }
    src = _FakeSource({}, fund_flow=ff)
    svc, c = _make_service(tmp_path, src)
    c.execute("INSERT INTO board_dict (board_code, name, board_type, has_members) "
              "VALUES ('309121','AI PC','concept',TRUE)")
    # 第一天全周期
    svc.ingest_board_fund_flow(date(2026, 1, 5), board_type="concept")
    # 第二天再次全周期 → 不同 snapshot_date，各周期新增一行
    svc.ingest_board_fund_flow(date(2026, 1, 6), board_type="concept")
    rows = c.query_df("SELECT snapshot_date, period FROM board_fund_flow ORDER BY snapshot_date, period")
    assert len(rows) == 10  # 2 天 × 5 周期
    # 同一天同周期重复入库 → upsert 覆盖，行数不变
    svc.ingest_board_fund_flow(date(2026, 1, 6), board_type="concept")
    assert int(c.query_df("SELECT count(*) AS n FROM board_fund_flow").iloc[0]["n"]) == 10


def test_board_dict_persists_app_code(tmp_path):
    """板块字典持久化路径 code ↔ App clid，幂等重跑不丢既有映射。"""
    src = _FakeSource(
        {},
        board_dict={
            "concept": pd.DataFrame([{"board_code": "309121", "name": "AI PC"}]),
            "industry": pd.DataFrame([{"board_code": "881121", "name": "半导体"}]),
        },
        app_codes={"309121": "886071"},
    )
    svc, c = _make_service(tmp_path, src)
    res = svc.ingest_board_dict(date(2026, 1, 5))
    assert res["failed"] == []
    rows = c.query_df("SELECT board_code, app_code FROM board_dict ORDER BY board_code")
    assert dict(zip(rows["board_code"], rows["app_code"])) == {
        "309121": "886071", "881121": "881121",
    }


def test_unmatched_quality_idempotent_and_net_validation(tmp_path):
    """未匹配问题不重复；净流入不满足流入-流出时跳过并如实返回失败。"""
    ff = {("concept", "即时"): pd.DataFrame([
        {"name": "不存在", "inflow": 1.0, "outflow": 1.0, "net_inflow": 0.0,
         "net_ratio": 0.0, "leader_stock": None, "leader_pct": None},
        {"name": "AI PC", "inflow": 10.0, "outflow": 3.0, "net_inflow": 99.0,
         "net_ratio": 1.0, "leader_stock": "x", "leader_pct": 1.0},
    ])}
    svc, c = _make_service(tmp_path, _FakeSource({}, fund_flow=ff))
    c.execute("INSERT INTO board_dict (board_code, name, board_type) "
              "VALUES ('309121','AI PC','concept')")
    first = svc.ingest_board_fund_flow(date(2026, 1, 5), periods=("即时",))
    second = svc.ingest_board_fund_flow(date(2026, 1, 5), periods=("即时",))
    assert first["failed"] and second["failed"]
    assert c.query_df("SELECT * FROM board_fund_flow").empty
    issues = c.query_df(
        "SELECT * FROM data_quality_issue WHERE issue_type='board_fund_unmatched' AND status='open'")
    assert len(issues) == 1


# ── 事务原子性 ────────────────────────────────────────────────


def test_member_upsert_transaction_atomicity(tmp_path):
    """成分落库事务原子性：中途失败整体回滚（board_member 与 member_count 都不写）。"""
    src = _FakeSource({"309121": ["300476"]})
    svc, c = _make_service(tmp_path, src)
    c.execute("INSERT INTO board_dict (board_code, name, board_type, has_members) "
              "VALUES ('309121','AI PC','concept',TRUE)")
    # 事务内先写成分，再抛错 → 回滚（board_member 与 member_count 都不落）
    try:
        with c.transaction():
            c.execute("INSERT INTO board_member (board_code, code) VALUES ('309121','300476.SZ')")
            raise RuntimeError("注入失败")
    except StorageError:
        pass
    assert len(c.query_df("SELECT 1 FROM board_member WHERE board_code='309121'")) == 0
    assert int(_member_count(c, "309121")) == 0


def test_write_lock_classification():
    """写锁冲突归类：锁关键字命中 → StorageError 消息带「写锁占用」。"""
    from backend.storage.duckdb_client import _LOCK_CONFLICT_RE
    assert _LOCK_CONFLICT_RE.search("Could not set lock on file ... Conflicting lock is held")
    assert _LOCK_CONFLICT_RE.search("IO Error: Conflicting lock is held")
    assert not _LOCK_CONFLICT_RE.search("普通事务错误")


def test_member_upsert_member_count_atomic(tmp_path):
    """成分落库与 member_count 同事务：中途失败整体回滚，member_count 不残留（R2 原子性）。"""
    src = _FakeSource({"309121": ["300476", "603936", "002913"]})
    svc, c = _make_service(tmp_path, src)
    c.execute("INSERT INTO board_dict (board_code, name, board_type, has_members) "
              "VALUES ('309121','AI PC','concept',TRUE)")
    # 事务内先写成分 + member_count，再抛错 → 整体回滚
    with pytest.raises(StorageError):
        with c.transaction():
            c.execute("INSERT INTO board_member (board_code, code) VALUES ('309121','300476.SZ')")
            c.execute("UPDATE board_dict SET member_count=1 WHERE board_code='309121'")
            raise RuntimeError("注入失败")
    # 回滚后：board_member 无新增行、member_count 无残留（仍 NULL/原值）
    assert len(c.query_df("SELECT 1 FROM board_member")) == 0
    mc = _member_count(c, "309121")
    assert mc == 0  # 未写入残留值


def test_fund_flow_batch_not_single_insert(tmp_path):
    """资金流批量 upsert（非逐条）：多板块多周期一次 temp_view INSERT。"""
    import pandas as pd
    # 构造 2 板块 × 1 周期
    ff = {
        ("concept", "即时"): pd.DataFrame([
            {"name": "AI PC", "inflow": 10.0, "outflow": 5.0, "net_inflow": 5.0,
             "net_ratio": 2.5, "leader_stock": "胜宏科技", "leader_pct": 12.0},
            {"name": "人工智能", "inflow": 20.0, "outflow": 8.0, "net_inflow": 12.0,
             "net_ratio": 3.0, "leader_stock": "国科微", "leader_pct": 10.0},
        ]),
    }
    src = _FakeSource({}, fund_flow=ff)
    svc, c = _make_service(tmp_path, src)
    c.execute("INSERT INTO board_dict (board_code, name, board_type, has_members) "
              "VALUES ('309121','AI PC','concept',TRUE)")
    c.execute("INSERT INTO board_dict (board_code, name, board_type, has_members) "
              "VALUES ('302035','人工智能','concept',TRUE)")
    svc.ingest_board_fund_flow(date(2026, 1, 5))
    rows = c.query_df("SELECT board_code, period FROM board_fund_flow")
    assert len(rows) == 2
    assert set(rows["board_code"]) == {"309121", "302035"}


def test_fund_checkpoint_legacy_and_scope(tmp_path):
    """fund checkpoint：同日旧格式兼容；改范围续跑不误命中旧组。"""
    import pandas as pd
    ff = {
        ("concept", "即时"): pd.DataFrame([
            {"name": "AI PC", "inflow": 1, "outflow": 0, "net_inflow": 1,
             "net_ratio": 1, "leader_stock": "x", "leader_pct": 1},
            {"name": "人工智能", "inflow": 2, "outflow": 1, "net_inflow": 1,
             "net_ratio": 1, "leader_stock": "y", "leader_pct": 2},
        ]),
    }
    src = _FakeSource({}, fund_flow=ff)
    svc, c = _make_service(tmp_path, src)
    c.execute("INSERT INTO board_dict (board_code, name, board_type, has_members) "
              "VALUES ('309121','AI PC','concept',TRUE),('302035','人工智能','concept',TRUE)")

    class _Ctx:
        def __init__(self, checkpoint=None):
            self.checkpoint = checkpoint or {}
            self.logs = []
        def check_cancel(self): pass
        def set_phase(self, phase, **data): self.checkpoint.update(data)
        def log(self, *args, **kwargs): self.logs.append(args)

    # 旧格式全量续跑：done_keys="concept:即时" 无前缀 → 平移为 ALL:concept:即时 → 命中跳过
    legacy = _Ctx({"fund_snapshot_date": "2026-01-05", "fund_done_keys": ["concept:即时"]})
    r = svc.ingest_board_fund_flow(date(2026, 1, 5), periods=("即时",), ctx=legacy)
    assert r["rows"] == 0
    assert "ALL:concept:即时" in legacy.checkpoint["fund_done_keys"]

    # 新格式指定子集：scope=md5(309121)，done_keys 与之匹配 → 跳过
    from hashlib import md5
    scope = md5("309121".encode()).hexdigest()[:8]
    scoped = _Ctx({"fund_snapshot_date": "2026-01-05",
                   "fund_done_keys": [f"{scope}:concept:即时"]})
    r2 = svc.ingest_board_fund_flow(date(2026, 1, 5), periods=("即时",),
                                    board_codes=["309121"], ctx=scoped)
    assert r2["rows"] == 0

    # 改范围续跑：旧 scope 键（309121）与新区间（302035）不交 → 重拉 302035 范围资金流
    other_scope = md5("302035".encode()).hexdigest()[:8]
    changed = _Ctx({"fund_snapshot_date": "2026-01-05",
                    "fund_done_keys": [f"{scope}:concept:即时"]})
    r3 = svc.ingest_board_fund_flow(date(2026, 1, 5), periods=("即时",),
                                    board_codes=["302035"], ctx=changed)
    assert r3["rows"] == 1
    assert f"{other_scope}:concept:即时" in changed.checkpoint["fund_done_keys"]


def test_ingest_board_fund_period_selection_and_bar_range(tmp_path):
    """资金流服务支持显式周期子集和默认全周期；指数区间由调用方控制。"""
    import pandas as pd

    from backend.services.board_ingest import BoardIngestService

    # 用真实 BoardIngestService + 假源
    calls = {"fund_periods": [], "bar_start": []}

    class _ModeSource(_FakeSource):
        def get_board_fund_flow(self, board_type, period):
            calls["fund_periods"].append(period)
            return pd.DataFrame([{"name": "AI PC", "inflow": 1, "outflow": 0,
                                  "net_inflow": 1, "net_ratio": 1, "leader_stock": "x", "leader_pct": 1}])

        def get_board_bar(self, code, board_type, start, end):
            calls["bar_start"].append(start)
            return pd.DataFrame(columns=["trade_date", "open", "high", "low", "close", "volume", "amount"])

        def get_board_dict(self, board_type):
            return pd.DataFrame([{"board_code": "309121", "name": "AI PC"}])

    src = _ModeSource({})
    svc = BoardIngestService(client=_make_service(tmp_path, src)[1], source=src)

    # 显式只采即时（用于定向调用；当前 update 主编排默认传全周期）
    svc.ingest_board_dict()
    svc.ingest_board_members(board_codes=["309121"], force=True)
    svc.ingest_board_bar(date(2026, 8, 1), board_codes=["309121"])
    svc.ingest_board_fund_flow(periods=("即时",))
    assert set(calls["fund_periods"]) == {"即时"}    # 概念+行业各一次
    # 不传 periods 时采集全周期
    calls["fund_periods"].clear()
    svc.ingest_board_fund_flow()
    assert set(calls["fund_periods"]) == {"即时", "3日", "5日", "10日", "20日"}  # 默认全周期


def test_ingest_writes_update_log(tmp_path):
    """板块采集各步骤写 data_update_log（对齐现有数据管理更新留痕）。"""
    src = _FakeSource(
        {"309121": ["300476", "603936"]},
        board_dict={"concept": pd.DataFrame([{"board_code": "309121", "name": "AI PC"}])},
    )
    svc, c = _make_service(tmp_path, src)
    c.execute("INSERT INTO board_dict (board_code, name, board_type, has_members, has_bar) "
              "VALUES ('309121','AI PC','concept',TRUE,TRUE)")
    # 字典 + 成分 + 指数 + 资金流都触发 log_update
    svc.ingest_board_dict(date(2026, 8, 9))
    svc.ingest_board_members(snapshot_date=date(2026, 8, 9), board_codes=["309121"], force=True)
    svc.ingest_board_bar(date(2026, 8, 1), board_codes=["309121"])
    svc.ingest_board_fund_flow(date(2026, 8, 9))
    logs = c.query_df("SELECT table_name, source, status FROM data_update_log ORDER BY id")
    tables = set(logs["table_name"])
    assert {"board_dict", "board_member", "board_bar", "board_fund_flow"} <= tables
    assert set(logs["source"]) == {"ths_board"}


# ── 指数增量：源端就绪探测与日志区间/新鲜度透出 ─────────────


def _bar_df(dates: list[date]) -> pd.DataFrame:
    """构造指数日线 DataFrame（仅需 trade_date 有区分度，OHLCV 给占位值）。"""
    n = len(dates)
    return pd.DataFrame({
        "trade_date": dates, "open": [1.0] * n, "high": [1.0] * n, "low": [1.0] * n,
        "close": [1.0] * n, "volume": [1.0] * n, "amount": [1.0] * n,
    })


class _LogCtx:
    """捕获 ctx.log 内容的最小任务上下文（bar 阶段用到 log/set_phase/check_cancel）。"""

    def __init__(self):
        self.checkpoint: dict = {}
        self.logs: list[tuple[str, str]] = []

    def check_cancel(self):
        pass

    def set_phase(self, phase, **data):
        self.checkpoint.update({"phase": phase, **data})

    def log(self, msg, level="info"):
        self.logs.append((level, str(msg)))


def _two_boards(c: DuckDBClient) -> None:
    c.execute("INSERT INTO board_dict (board_code, name, board_type, has_bar) VALUES "
              "('309121','AI PC','concept',TRUE),('881121','半导体','industry',TRUE)")


def test_bar_ready_probe_falls_back_when_source_lagging(tmp_path, fund_clock):
    """全量增量且截止日=今天：未就绪时回退到上一交易日继续补采。"""
    fund_clock('2026-10-20T16:00:00')
    from backend.services.board_ingest import _asia_date
    today = _asia_date()
    yesterday = today - timedelta(days=1)
    src = _FakeSource({}, bar={
        "309121": _bar_df([yesterday]),
        "881121": _bar_df([yesterday]),
    })
    svc, c = _make_service(tmp_path, src)
    _two_boards(c)
    c.execute("INSERT INTO trade_calendar (trade_date, is_open) VALUES (?, TRUE)", [yesterday])
    ctx = _LogCtx()
    r = svc.ingest_board_bar(yesterday - timedelta(days=6), end=today, probe_ready=True, ctx=ctx)
    assert r["fallback"] is True and r["reason"] == "source_not_ready"
    assert r["requested_end"] == today.isoformat() and r["end"] == yesterday.isoformat()
    assert r["rows"] == 2 and r["boards"] == 2 and r["failed"] == []
    assert r["at_end"] == 2 and r["scope_total"] == 2
    assert len(c.query_df("SELECT * FROM board_bar")) == 2
    assert len(c.query_df("SELECT * FROM data_update_log WHERE table_name='board_bar' "
                          "AND status='success'")) == 1
    warns = [m for lv, m in ctx.logs if lv == "warn"]
    assert any("未就绪" in m and str(today) in m and str(yesterday) in m for m in warns)


def test_bar_ready_probe_passes_and_logs_window_freshness(tmp_path, fund_clock):
    """源端已出当日数据：正常采集，日志带采集区间与「已出截止日 K/N」新鲜度。"""
    fund_clock('2026-10-20T16:00:00')
    from backend.services.board_ingest import _asia_date
    today = _asia_date()
    src = _FakeSource({}, bar={
        "309121": _bar_df([today]),
        "881121": _bar_df([today]),
    })
    svc, c = _make_service(tmp_path, src)
    _two_boards(c)
    ctx = _LogCtx()
    start = today - timedelta(days=7)
    r = svc.ingest_board_bar(start, end=today, probe_ready=True, ctx=ctx)
    assert "skipped" not in r
    assert r["rows"] == 2 and r["boards"] == 2
    assert r["at_end"] == 2 and r["scope_total"] == 2
    assert r["start"] == start.isoformat() and r["end"] == today.isoformat()
    # 任务日志：起始行带采集区间
    assert any("采集区间" in m and str(start) in m and str(today) in m
               for _, m in ctx.logs)
    # 更新留痕：成功汇总透出已出截止日覆盖数
    detail = c.query_df("SELECT detail FROM data_update_log WHERE table_name='board_bar' "
                        "AND status='success'").iloc[0]["detail"]
    assert f"已出 {today}：2/2" in detail


def test_bar_probe_applies_to_explicit_board_codes(tmp_path):
    """指定板块增量也执行就绪退级，强制当日由上层显式关闭探测。"""
    from backend.services.board_ingest import _asia_date
    today = _asia_date()
    yesterday = today - timedelta(days=1)
    src = _FakeSource({}, bar={"309121": _bar_df([yesterday])})
    svc, c = _make_service(tmp_path, src)
    _two_boards(c)
    c.execute("INSERT INTO trade_calendar (trade_date, is_open) VALUES (?, TRUE)", [yesterday])
    r = svc.ingest_board_bar(yesterday, end=today, board_codes=["309121"], probe_ready=True)
    assert r["fallback"] is True and r["end"] == yesterday.isoformat()
    assert r["rows"] == 1 and r["at_end"] == 1 and r["scope_total"] == 1


def test_board_update_force_current_day_bypasses_all_fallbacks(monkeypatch, market, fund_clock):
    """强制当日直接使用今天，指数不做就绪探测，资金流沿用同一目标日。"""
    from backend.services import board_ingest as board_module
    from backend.services.ingest import IngestionService

    fund_clock("2026-10-20T16:00:00")
    today = date(2026, 10, 20)
    previous = today - timedelta(days=1)
    market.execute("INSERT INTO trade_calendar VALUES (?,TRUE),(?,TRUE)", [previous, today])
    captured: dict = {}

    class _FakeBoardService:
        c = market
        def ingest_board_bar(self, start, end=None, **kwargs):
            captured["bar_end"] = end
            captured["probe_ready"] = kwargs.get("probe_ready")
            return {
                "rows": 0, "boards": 0, "failed": [], "start": start.isoformat() if start else None,
                "end": end.isoformat(), "requested_end": end.isoformat(), "fallback": False,
                "at_end": 0, "scope_total": 0,
            }

        def ingest_board_fund_flow(self, snapshot_date=None, **kwargs):
            captured["fund_date"] = snapshot_date
            return {"rows": 0, "unmatched": 0, "failed": []}

    monkeypatch.setattr(board_module, "_asia_date", lambda: today)
    monkeypatch.setattr(board_module, "BoardIngestService", _FakeBoardService)
    svc = IngestionService.__new__(IngestionService)
    svc.c = market
    svc._latest_open_day = lambda: previous

    svc.ingest_board(mode="update", only=["bar", "fund"], force_current_day=True)

    assert captured == {
        "bar_end": today,
        "probe_ready": False,
        "fund_date": today,
    }


def test_board_backfill_fund_without_bar_defers_snapshot_date(monkeypatch, market, fund_clock):
    """空库回填没有行情锚点，由资金流服务解析已收盘日，避免凌晨误用今天。"""
    from backend.services import board_ingest as board_module
    from backend.services.ingest import IngestionService

    fund_clock('2026-08-30T16:00:00')
    market.execute("INSERT INTO trade_calendar VALUES ('2026-08-28',TRUE),('2026-08-31',TRUE)")
    latest_open_day = date(2026, 8, 28)
    captured: dict = {}

    class _FakeBoardService:
        # 只采资金流会查询库内指数水位；空库时才回落最近开市日。
        c = market

        def ingest_board_fund_flow(self, snapshot_date=None, **kwargs):
            captured["fund_date"] = snapshot_date
            return {"rows": 0, "unmatched": 0, "failed": []}

    monkeypatch.setattr(board_module, "BoardIngestService", _FakeBoardService)
    svc = IngestionService.__new__(IngestionService)
    svc.c = market
    svc._latest_open_day = lambda: latest_open_day

    svc.ingest_board(mode="backfill", only=["fund"])

    assert captured == {"fund_date": None}


def test_bar_probe_off_by_default_for_backfill(tmp_path, fund_clock):
    """backfill/直接调用默认不就绪探测：全量+截止日=今天但源端滞后也照常采集已有部分。"""
    fund_clock('2026-10-20T16:00:00')
    from backend.services.board_ingest import _asia_date
    today = _asia_date()
    yesterday = today - timedelta(days=1)
    src = _FakeSource({}, bar={
        "309121": _bar_df([yesterday]),
        "881121": _bar_df([yesterday]),
    })
    svc, c = _make_service(tmp_path, src)
    _two_boards(c)
    r = svc.ingest_board_bar(today - timedelta(days=365), end=today)  # 未传 probe_ready
    assert "skipped" not in r and r["boards"] == 2
    assert r["at_end"] == 0


def test_bar_probe_bypassed_for_past_end(tmp_path):
    """截止日早于今天（非交易日回退/历史窗口）：数据必已发布，不探测直接采。"""
    from backend.services.board_ingest import _asia_date
    end = _asia_date() - timedelta(days=1)
    src = _FakeSource({}, bar={
        "309121": _bar_df([end]),
        "881121": _bar_df([end]),
    })
    svc, c = _make_service(tmp_path, src)
    _two_boards(c)
    r = svc.ingest_board_bar(end - timedelta(days=6), end=end)
    assert "skipped" not in r and r["boards"] == 2
    assert r["at_end"] == 2


def test_bar_incremental_resumes_each_board_from_its_latest_date(tmp_path):
    """自动增量逐板块续水位；已到目标日的板块不再请求。"""
    end = date(2026, 8, 7)

    class RecordingSource(_FakeSource):
        def __init__(self):
            super().__init__({})
            self.calls = []

        def get_board_bar(self, code, board_type, start, range_end):
            self.calls.append((code, start, range_end))
            return _bar_df([range_end])

    src = RecordingSource()
    svc, c = _make_service(tmp_path, src)
    _two_boards(c)
    c.execute(
        "INSERT INTO board_bar (board_code, trade_date, open, high, low, close, volume, amount) "
        "VALUES ('309121', '2026-08-05', 1, 1, 1, 1, 1, 1), "
        "('881121', '2026-08-07', 1, 1, 1, 1, 1, 1)"
    )

    result = svc.ingest_board_bar(None, end=end, resume_from_latest=True)

    assert src.calls == [("309121", date(2026, 8, 6), end)]
    assert result["resume_from_latest"] is True
    assert result["start"] == "2026-08-06"


def test_board_date_range_normalization():
    """手动指数区间支持单日简写，并拒绝冲突或逆序参数。"""
    from backend.services.board_ingest import normalize_board_date_range

    assert normalize_board_date_range("update", "2026-08-01", None) == (
        date(2026, 8, 1), date(2026, 8, 1),
    )
    with pytest.raises(ValueError, match="起始日期不能晚于结束日期"):
        normalize_board_date_range("update", "2026-08-02", "2026-08-01")
    with pytest.raises(ValueError, match="不能与强制采集当日"):
        normalize_board_date_range("update", "2026-08-01", None, True)

@pytest.fixture()
def fund_clock(monkeypatch):
    """可推进的北京时间时钟，覆盖跨日与多页取数跨时段边界。"""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    import backend.services.board_ingest as module

    current = [datetime(2026, 10, 20, 3, 57, 24, tzinfo=ZoneInfo("Asia/Shanghai"))]

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return current[0].astimezone(tz) if tz else current[0].replace(tzinfo=None)

    def set_clock(value):
        parsed = datetime.fromisoformat(value)
        current[0] = parsed if parsed.tzinfo else parsed.replace(tzinfo=ZoneInfo("Asia/Shanghai"))

    monkeypatch.setattr(module, "datetime", Clock)
    from backend.services import eod_dates
    monkeypatch.setattr(eod_dates, "shanghai_now", lambda: current[0].astimezone(ZoneInfo("Asia/Shanghai")))
    return set_clock


@pytest.mark.parametrize('clock,target,blocked', [
    ('2026-10-20T00:00:00', '2026-10-19', False),
    ('2026-10-20T03:57:24', '2026-10-19', False),
    ('2026-10-20T03:57:24', '2026-10-20', True),
    ('2026-10-20T03:57:24', '2026-10-16', True),
    ('2026-10-19T19:57:24+00:00', '2026-10-19', False),
    ('2026-10-20T09:14:59', '2026-10-19', False),
    ('2026-10-20T09:15:00', '2026-10-19', True),
    ('2026-10-20T09:15:00', '2026-10-20', True),
    ('2026-10-20T12:00:00', '2026-10-20', True),
    ('2026-10-20T15:00:00', '2026-10-20', True),
    ('2026-10-20T15:29:59', '2026-10-20', True),
    ('2026-10-20T15:30:00', '2026-10-20', False),
    ('2026-10-20T15:30:00', '2026-10-19', True),
    ('2026-10-19T03:00:00', '2026-10-16', False),
    ('2026-10-19T10:00:00', '2026-10-16', True),
    ('2026-10-19T16:00:00', '2026-10-16', True),
    ('2026-10-19T16:00:00', '2026-10-19', False),
    ('2026-10-18T16:00:00', '2026-10-16', False),
    ('2026-10-18T16:00:00', '2026-10-18', True),
    ('2026-10-08T16:00:00', '2026-09-30', False),
    ('2026-10-09T03:00:00', '2026-09-30', False),
])
def test_live_fund_snapshot_date_guard(market, fund_clock, clock, target, blocked):
    from backend.common.exceptions import DataSourceError

    fund_clock(clock)
    market.execute("INSERT INTO trade_calendar VALUES ('2026-09-30',TRUE),"
                   "('2026-10-08',FALSE),('2026-10-09',TRUE),('2026-10-16',TRUE),"
                   "('2026-10-18',FALSE),('2026-10-19',TRUE),('2026-10-20',TRUE)")
    service = BoardIngestService(market, source=_FakeSource({}))
    if blocked:
        with pytest.raises(DataSourceError):
            service._validate_fund_snapshot_date(date.fromisoformat(target))
    else:
        assert service._validate_fund_snapshot_date(date.fromisoformat(target)) == date.fromisoformat(target)


@pytest.fixture()
def live_fund_service(market, fund_clock):
    """真实资金流服务与临时行情库，仅替换外部 HTTP 数据和时钟。"""
    market.execute("INSERT INTO trade_calendar VALUES ('2026-10-16',TRUE),"
                   "('2026-10-18',FALSE),('2026-10-19',TRUE),('2026-10-20',TRUE)")
    market.execute("INSERT INTO board_dict (board_code, name, board_type, has_bar) "
                   "VALUES ('309121', 'AI PC', 'concept', TRUE)")
    flow = pd.DataFrame([{
        "name": "AI PC", "board_code": "309121", "inflow": 2.0, "outflow": 1.0,
        "net_inflow": 1.0, "net_ratio": 1.0, "leader_stock": "x", "leader_pct": 1.0,
    }])
    from backend.datasource.ths_board import FUND_FLOW_PERIODS

    src = _FakeSource({}, fund_flow={("concept", p): flow for p in FUND_FLOW_PERIODS})
    src.fund_flow_is_live_snapshot = True
    return BoardIngestService(market, source=src)


class _FundContext:
    def __init__(self, checkpoint=None):
        self.checkpoint = checkpoint or {}

    def check_cancel(self): pass
    def set_checkpoint(self, **data): self.checkpoint.update(data)
    def set_phase(self, phase, **data): self.checkpoint.update(data)
    def log(self, *args, **kwargs): pass
    def progress(self, *args, **kwargs): pass
    def flush(self): pass


@pytest.mark.parametrize('mode,stages,has_bar,resume', [
    ('update', ['fund'], True, False),
    ('update', ['fund'], False, False),
    ('backfill', ['fund'], False, False),
    ('update', ['bar', 'fund'], True, False),
    ('backfill', ['bar', 'fund'], True, False),
    ('update', ['bar', 'fund'], True, True),
])
def test_board_overnight_ingest_persists_previous_close(
    live_fund_service, monkeypatch, mode, stages, has_bar, resume,
):
    """经真实编排、日期门禁、五周期映射与落库验证凌晨采集，不以桩响应替代闭环。"""
    from backend.services import board_ingest as module
    from backend.services.ingest import IngestionService

    service = live_fund_service
    if has_bar:
        service.c.execute("INSERT INTO board_bar (board_code, trade_date, close) "
                          "VALUES ('309121', DATE '2026-10-19', 100.0)")
        service.src._bar = {"309121": pd.DataFrame([{
            "trade_date": date(2026, 10, 19), "open": 100.0, "high": 101.0,
            "low": 99.0, "close": 100.0, "volume": 1000, "amount": 100000,
        }])}
    monkeypatch.setattr(module, "BoardIngestService", lambda: service)
    ing = IngestionService.__new__(IngestionService)
    ing.c = service.c
    ing._latest_open_day = lambda: date(2026, 10, 20)
    ctx = _FundContext({'bar_done_codes': ['309121']} if resume else None)
    result = ing.ingest_board(mode=mode, only=stages, board_type="concept", ctx=ctx)

    assert result['ok'] is True
    assert result['fund_flow']['rows'] == 5
    rows = service.c.query_df("SELECT snapshot_date, period FROM board_fund_flow")
    assert len(rows) == 5
    assert {d.date() for d in rows['snapshot_date']} == {date(2026, 10, 19)}
    assert service.c.query_df("SELECT date_end FROM data_update_log "
                              "WHERE table_name='board_fund_flow'").iloc[0]['date_end'].date() == date(2026, 10, 19)


@pytest.mark.parametrize('target', [None, date(2026, 10, 19)])
def test_live_fund_direct_ingest_overnight(live_fund_service, target):
    """未匹配修复的默认日期与缺失/滞后修复的显式日期共享凌晨归属规则。"""
    result = live_fund_service.ingest_board_fund_flow(target, board_type="concept")
    assert result['rows'] == 5 and result['failed'] == []
    assert live_fund_service.c.query_df(
        "SELECT DISTINCT snapshot_date FROM board_fund_flow"
    ).iloc[0]['snapshot_date'].date() == date(2026, 10, 19)


def test_board_force_today_cannot_bypass_fund_guard(live_fund_service, monkeypatch):
    """强制当日仍不能在凌晨把上一交易日资金流写成今天。"""
    from backend.services import board_ingest as module
    from backend.services.ingest import IngestionService

    monkeypatch.setattr(module, 'BoardIngestService', lambda: live_fund_service)
    monkeypatch.setattr(live_fund_service.src, 'get_board_fund_flow',
                        lambda *_: pytest.fail('错误目标日期应在取数前拒绝'))
    from backend.common.exceptions import DataSourceError
    with pytest.raises(DataSourceError, match='目标2026-10-20'):
        IngestionService.__new__(IngestionService).ingest_board(
            mode='update', only=['fund'], force_current_day=True,
        )
    assert live_fund_service.c.query_df('SELECT * FROM board_fund_flow').empty


def test_live_fund_fetch_crossing_midnight_keeps_previous_close(
    live_fund_service, fund_clock, monkeypatch,
):
    """跨午夜不改变已收盘日，同一收盘快照仍可安全写入。"""
    fund_clock('2026-10-19T23:59:59')
    fetch = live_fund_service.src.get_board_fund_flow

    def overnight_fetch(*args):
        frame = fetch(*args)
        fund_clock('2026-10-20T00:00:00')
        return frame

    monkeypatch.setattr(live_fund_service.src, 'get_board_fund_flow', overnight_fetch)
    result = live_fund_service.ingest_board_fund_flow(board_type='concept')
    assert result['rows'] == 5 and result['failed'] == []
    assert live_fund_service.c.query_df(
        'SELECT DISTINCT snapshot_date FROM board_fund_flow'
    ).iloc[0]['snapshot_date'].date() == date(2026, 10, 19)


@pytest.mark.parametrize('clock,target', [
    ('2026-10-20T03:57:24', date(2026, 10, 20)),
    ('2026-10-20T03:57:24', date(2026, 10, 16)),
    ('2026-10-20T09:15:00', None),
    ('2026-10-20T12:00:00', date(2026, 10, 20)),
    ('2026-10-20T16:00:00', date(2026, 10, 19)),
])
def test_live_fund_invalid_date_rejects_before_fetch(
    live_fund_service, fund_clock, monkeypatch, clock, target,
):
    from backend.common.exceptions import DataSourceError

    fund_clock(clock)
    monkeypatch.setattr(live_fund_service.src, 'get_board_fund_flow',
                        lambda *_: pytest.fail('禁采时间或错误日期不应请求实时源'))
    with pytest.raises(DataSourceError):
        live_fund_service.ingest_board_fund_flow(target, board_type='concept')
    assert live_fund_service.c.query_df('SELECT * FROM board_fund_flow').empty


@pytest.mark.parametrize('issue_type', ['board_fund_missing', 'board_fund_stale'])
def test_overnight_fund_repair_rechecks_and_resolves(live_fund_service, monkeypatch, issue_type):
    """真实恢复处理器经采集落库、同日复检、关联扫描后关闭问题，不残留 fixing。"""
    import json

    from backend.datasource.ths_board import FUND_FLOW_PERIODS
    from backend.services import board_ingest as module
    from backend.services.async_task import AsyncTaskService, TaskContext, _recover_one
    from backend.services.data_report import DataIntegrityReport

    service = live_fund_service
    c = service.c
    c.execute("INSERT INTO daily_bar (code, trade_date, close) "
              "VALUES ('600000.SH', DATE '2026-10-19', 10.0)")
    c.execute("INSERT INTO board_bar (board_code, trade_date, close) "
              "VALUES ('309121', DATE '2026-10-19', 100.0)")
    for period in FUND_FLOW_PERIODS:
        c.execute("INSERT INTO board_fund_flow (board_code, snapshot_date, period, net_inflow) "
                  "VALUES ('309121', ?, ?, 1.0)",
                  [date(2026, 10, 16) if period == '即时' else date(2026, 10, 19), period])
    c.execute("INSERT INTO data_quality_issue "
              "(id, code, trade_date, issue_type, severity, status, detail, detected_at) "
              "VALUES (500, ?, DATE '2026-10-19', ?, 'mid', 'open', ?, now())",
              ['309121' if issue_type == 'board_fund_missing' else None,
               issue_type, json.dumps({'periods': ['即时']})])
    # 滞后恢复拉全源，需要同时验证行业返回，不把概念数据冒充行业快照。
    c.execute("INSERT INTO board_dict (board_code, name, board_type) "
              "VALUES ('881121', '半导体', 'industry')")
    service.src._fund_flow[('industry', '即时')] = service.src._fund_flow[
        ('concept', '即时')
    ].assign(board_code='881121', name='半导体')
    monkeypatch.setattr(module, 'BoardIngestService', lambda _client=None: service)

    clean, _, note = _recover_one(
        c, DataIntegrityReport(c), None,
        TaskContext(AsyncTaskService(c), 'test_overnight_fix', {}), 500,
    )

    assert clean is True
    assert '复检通过' in note
    issue = c.query_df('SELECT status, fix_task_id FROM data_quality_issue WHERE id=500').iloc[0]
    assert issue['status'] == 'resolved' and pd.isna(issue['fix_task_id'])
    assert c.query_df("SELECT count(*) n FROM board_fund_flow "
                      "WHERE snapshot_date='2026-10-20'").iloc[0]['n'] == 0
    assert DataIntegrityReport(c).recheck_clean(
        issue_type, '309121' if issue_type == 'board_fund_missing' else None,
        date(2026, 10, 19), detail={'periods': ['即时']},
    ) is True


@pytest.mark.parametrize('calendar_sql', [
    "DELETE FROM trade_calendar WHERE trade_date='2026-10-20'",
    "DELETE FROM trade_calendar WHERE trade_date<'2026-10-20'",
])
def test_live_fund_missing_calendar_rejects_before_fetch(live_fund_service, calendar_sql, monkeypatch):
    from backend.common.exceptions import DataSourceError

    service = live_fund_service
    service.c.execute(calendar_sql)
    monkeypatch.setattr(service.src, "get_board_fund_flow",
                        lambda *_: pytest.fail("日历不齐时不应请求实时数据"))
    with pytest.raises(DataSourceError, match="交易日历"):
        service.ingest_board_fund_flow(board_type="concept")
    assert service.c.query_df("SELECT * FROM board_fund_flow").empty


@pytest.mark.parametrize('clock', ['2026-10-20T09:15:00', '2026-10-20T16:00:00'])
def test_live_fund_fetch_crossing_session_rejects_before_write(
    live_fund_service, fund_clock, clock, monkeypatch,
):
    from backend.common.exceptions import DataSourceError

    service = live_fund_service
    fetch = service.src.get_board_fund_flow

    def slow_fetch(*args):
        frame = fetch(*args)
        fund_clock(clock)
        return frame

    monkeypatch.setattr(service.src, "get_board_fund_flow", slow_fetch)
    ctx = _FundContext()
    with pytest.raises(DataSourceError):
        service.ingest_board_fund_flow(board_type="concept", ctx=ctx)
    assert service.c.query_df("SELECT * FROM board_fund_flow").empty
    assert ctx.checkpoint['fund_done_keys'] == []


@pytest.mark.parametrize('checkpoint_date,expected_rows', [
    (None, 5), ('2026-10-16', 5), ('2026-10-19', 0),
])
def test_live_fund_checkpoint_requires_same_snapshot_date(
    live_fund_service, monkeypatch, checkpoint_date, expected_rows,
):
    from backend.datasource.ths_board import FUND_FLOW_PERIODS

    ctx = _FundContext({
        'fund_snapshot_date': checkpoint_date,
        'fund_done_keys': [f'ALL:concept:{p}' for p in FUND_FLOW_PERIODS],
    })
    if not expected_rows:
        monkeypatch.setattr(live_fund_service.src, 'get_board_fund_flow',
                            lambda *_: pytest.fail('同日已完成周期不应重复拉取'))
    result = live_fund_service.ingest_board_fund_flow(board_type='concept', ctx=ctx)
    assert result['rows'] == expected_rows
    assert ctx.checkpoint['fund_snapshot_date'] == '2026-10-19'


class _MemberCtx:
    """只在主线程写断点；取消信号可被工作线程读取。"""

    def __init__(self, checkpoint=None, cancel_after_commit=False):
        from backend.datasource.observability import RequestTracker

        self.checkpoint = dict(checkpoint or {})
        self.request_tracker = RequestTracker()
        self.cancel_after_commit = cancel_after_commit
        self.logs = []

    def check_cancel(self):
        if self.cancel_after_commit and self.checkpoint.get('member_done_codes'):
            raise TaskCancelled()

    def set_phase(self, phase, **data):
        self.checkpoint.update(phase=phase, **data)

    def set_checkpoint(self, **data):
        self.checkpoint.update(data)

    def log(self, message, *args):
        self.logs.append(message)

    def flush(self):
        pass


def test_parallel_members_market_scale_main_thread_writes_and_source_cleanup(tmp_path, monkeypatch):
    """481板块走真实服务读清单→并发取源→串行完整性门禁/事务落表，验证工作线程隔离。"""
    import threading
    import time
    from backend.config.settings import Settings

    settings = Settings()
    settings.ths_board.member_concurrency = 8
    monkeypatch.setattr('backend.services.board_ingest.get_effective_settings', lambda: settings)
    codes = [f'{310000+i}' for i in range(481)]
    members = [f'{600000+i}' for i in range(10)]
    barrier = threading.Barrier(8)
    main_thread = threading.get_ident()
    sources = []
    fetched = []
    source_guard = threading.Lock()

    class Source:
        def __init__(self):
            self.started = False
            self.thread = None
            self.closed = False

        def get_board_members(self, code, board_type):
            if not self.started:
                self.started = True
                self.thread = threading.get_ident()
                barrier.wait(timeout=10)
            assert self.thread == threading.get_ident() != main_thread
            with source_guard:
                fetched.append(code)
            time.sleep(0.001)
            return {'codes': members, 'complete': True, 'pages': 1}

        def close(self):
            assert threading.get_ident() == main_thread
            self.closed = True

    def factory():
        instance = Source()
        with source_guard:
            sources.append(instance)
        return instance

    svc, c = _make_service(tmp_path, _FakeSource({}), source_factory=factory)
    c.executemany(
        'INSERT INTO board_dict(board_code,name,board_type,has_members) VALUES (?,?,?,true)',
        [[code, code, 'concept'] for code in codes],
    )
    store = svc._store_member_snapshot

    def store_on_main(*args):
        assert threading.get_ident() == main_thread
        return store(*args)

    monkeypatch.setattr(svc, '_store_member_snapshot', store_on_main)
    ctx = _MemberCtx()
    result = svc.ingest_board_members(force=True, ctx=ctx)
    assert set(result) == set(fetched) == set(codes)
    assert len(fetched) == 481
    assert len(sources) == len({s.thread for s in sources}) == 8
    assert all(s.closed for s in sources)
    assert c.query_df('SELECT count(*) AS n FROM board_member').iloc[0]['n'] == 4810
    assert c.query_df('SELECT count(*) AS n FROM board_dict WHERE member_snapshot_at IS NOT NULL').iloc[0]['n'] == 481
    assert ctx.checkpoint['member_done_codes'] == sorted(codes)
    assert ctx.checkpoint['phase_done'] == ctx.checkpoint['phase_total'] == 481
    assert ctx.request_tracker.meta['work_concurrency'] == 8


def test_parallel_members_failure_cancellation_resume_and_cleanup(tmp_path):
    """取消后没有孤儿写入，断点只保留已提交板块；续跑拒绝不完整快照并保留旧数据。"""
    import threading

    members = {'309121': ['300476'], '309122': ['600000'], '309123': ['688981']}
    svc, c = _make_service(tmp_path, _FakeSource(members))
    c.executemany(
        'INSERT INTO board_dict(board_code,name,board_type,has_members) VALUES (?,?,?,true)',
        [[code, code, 'concept'] for code in members],
    )
    barrier = threading.Barrier(2)
    closed = []

    class Source(_FakeSource):
        def get_board_members(self, code, board_type='concept'):
            barrier.wait(timeout=5)
            return super().get_board_members(code, board_type)

        def close(self):
            closed.append(id(self))

    svc._source_factory = lambda: Source(members)
    first = _MemberCtx(cancel_after_commit=True)
    with pytest.raises(TaskCancelled):
        svc.ingest_board_members(force=True, concurrency=2, ctx=first)
    committed = first.checkpoint['member_done_codes']
    assert len(committed) == 1
    assert c.query_df('SELECT DISTINCT board_code FROM board_member')['board_code'].tolist() == committed
    assert len(closed) == 2
    assert c.query_df("SELECT * FROM data_update_log WHERE status='failed'").empty
    pending = sorted(set(members)-set(committed))
    # 本轮一个源端不完整，一个完整；失败项不得进入成功断点。
    failed = pending[0]
    c.execute('INSERT INTO board_member(board_code,code,first_seen_date) VALUES (?, ?, ?)',
              [failed, '000001.SZ', date(2026, 1, 1)])
    svc._source_factory = lambda: _FakeSource(members, complete={failed: False})
    resumed = _MemberCtx(first.checkpoint)
    result = svc.ingest_board_members(force=True, concurrency=2, ctx=resumed)
    assert set(result) == set(pending)
    assert 'error' in result[failed]
    assert resumed.checkpoint['member_done_codes'] == sorted(set(members)-{failed})
    assert c.query_df('SELECT code FROM board_member WHERE board_code=?', [failed])['code'].tolist() == ['000001.SZ']
    assert c.query_df('SELECT member_snapshot_at FROM board_dict WHERE board_code=?', [failed]).iloc[0]['member_snapshot_at'] is pd.NaT
    assert resumed.checkpoint['phase_done'] == resumed.checkpoint['phase_total'] == 3


@pytest.mark.parametrize('concurrency', [0, 17, True, 1.5, '8'])
def test_member_concurrency_rejects_invalid_values(tmp_path, concurrency):
    svc, _ = _make_service(tmp_path, _FakeSource({}))
    with pytest.raises(ValueError, match='并发数'):
        svc.ingest_board_members(concurrency=concurrency)


def test_board_task_passes_concurrency_to_collection_entry(monkeypatch):
    """任务并发覆盖送达正式编排入口，强制刷新参数保持独立。"""
    from types import SimpleNamespace
    from backend.services import ingest
    from backend.services.async_task import _h_board

    captured = {}

    class Service:
        def ingest_board(self, **kwargs):
            captured.update(kwargs)
            return {'failed': []}

    monkeypatch.setattr(ingest, 'IngestionService', Service)
    ctx = SimpleNamespace(log=lambda *a: None, progress=lambda *a: None,
                          check_cancel=lambda: None)
    result = _h_board({'codes': ['309121'], 'only': ['members'],
                       'force_members': True, 'concurrency': 3}, ctx)
    assert result['ok'] is True
    assert captured['concurrency'] == 3
    assert captured['force_members'] is True
    assert captured['board_codes'] == ['309121']
    assert captured['ctx'] is ctx
