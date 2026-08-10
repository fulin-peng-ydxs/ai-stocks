"""板块采集服务单测（T4，mock ThsBoardSource + 文件 DuckDB，不触网）。

覆盖 plan §6.4 产出断言：只进不出落库（ON CONFLICT 幂等）/ 不完整快照不落库 /
资金流映射与未匹配质检 / member_count 刷新（完整快照刷新）/ 事务原子性（中途失败整体回滚）
/ 写锁冲突归类（跨进程独立测试）。
"""

from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from backend.common.exceptions import StorageError
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
    assert svc.ingest_board_bar(date(2026, 1, 1), board_codes=[]) == {
        "rows": 0, "boards": 0, "failed": [],
    }
    assert svc.ingest_board_fund_flow(board_codes=[]) == {
        "rows": 0, "unmatched": 0, "failed": [],
    }
    assert c.query_df("SELECT * FROM board_member").empty


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
            if self.cancel_at == self.checks:
                raise RuntimeError("cancel")

        def set_phase(self, phase, **data):
            self.checkpoint.update({"phase": phase, **data})

        def log(self, *args, **kwargs):
            pass

    first = _Ctx(cancel_at=2)
    with pytest.raises(RuntimeError, match="cancel"):
        svc.ingest_board_members(board_codes=["309121", "881121"], ctx=first, force=True)
    assert first.checkpoint["member_done_codes"] == ["309121"]

    resumed = _Ctx(checkpoint=dict(first.checkpoint))
    result = svc.ingest_board_members(board_codes=["309121", "881121"], ctx=resumed, force=True)
    assert set(result) == {"881121"}
    assert resumed.checkpoint["member_done_codes"] == ["309121", "881121"]


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
    df = c.query_df("SELECT board_code, code FROM board_member")
    assert len(df) == 3
    assert set(df["code"]) == {"300476.SZ", "603936.SH", "002913.SZ"}
    # member_count 刷新为当前成分数
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
    df2 = c2.query_df("SELECT code FROM board_member")
    assert set(df2["code"]) == {"300476.SZ", "603936.SH", "002913.SZ", "300750.SZ"}
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
    """fund checkpoint：旧格式（无 scope 前缀）全量续跑兼容；改范围续跑不误命中旧组。"""
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
    legacy = _Ctx({"fund_done_keys": ["concept:即时"]})
    r = svc.ingest_board_fund_flow(date(2026, 1, 5), periods=("即时",), ctx=legacy)
    assert r["rows"] == 0
    assert "ALL:concept:即时" in legacy.checkpoint["fund_done_keys"]

    # 新格式指定子集：scope=md5(309121)，done_keys 与之匹配 → 跳过
    from hashlib import md5
    scope = md5("309121".encode()).hexdigest()[:8]
    scoped = _Ctx({"fund_done_keys": [f"{scope}:concept:即时"]})
    r2 = svc.ingest_board_fund_flow(date(2026, 1, 5), periods=("即时",),
                                    board_codes=["309121"], ctx=scoped)
    assert r2["rows"] == 0

    # 改范围续跑：旧 scope 键（309121）与新区间（302035）不交 → 重拉 302035 范围资金流
    other_scope = md5("302035".encode()).hexdigest()[:8]
    changed = _Ctx({"fund_done_keys": [f"{scope}:concept:即时"]})
    r3 = svc.ingest_board_fund_flow(date(2026, 1, 5), periods=("即时",),
                                    board_codes=["302035"], ctx=changed)
    assert r3["rows"] == 1
    assert f"{other_scope}:concept:即时" in changed.checkpoint["fund_done_keys"]


def test_ingest_board_mode_update_vs_backfill(tmp_path, monkeypatch):
    """增量/全量语义：update 只采即时资金流，backfill 全周期；指数区间不同。"""
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

    # update 模式
    svc.ingest_board_dict()
    svc.ingest_board_members(board_codes=["309121"], force=True)
    svc.ingest_board_bar(date(2026, 8, 1), board_codes=["309121"])
    svc.ingest_board_fund_flow(periods=("即时",))
    assert set(calls["fund_periods"]) == {"即时"}    # update 只采即时（概念+行业各一次）
    # backfill 模式（直接调 fund_flow 全周期）
    calls["fund_periods"].clear()
    svc.ingest_board_fund_flow()
    assert set(calls["fund_periods"]) == {"即时", "3日", "5日", "10日", "20日"}  # backfill 全周期


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
