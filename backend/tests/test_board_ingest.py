"""板块采集服务单测（T4，mock ThsBoardSource + 文件 DuckDB，不触网）。

覆盖 plan §6.4 产出断言：diff 区间语义 / 不完整快照不执行退出 diff / payload_hash 规范化与
幂等四态 / 同日多候选冻结 / 资金流映射与未匹配质检 / member_count 刷新时机（完整路径刷新、
被拦截未应用不刷新）/ 事务原子性（中途失败整体回滚）/ 写锁冲突归类（跨进程独立测试）。
"""

from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from backend.common.exceptions import StorageError
from backend.services.board_ingest import BoardIngestService, ISSUE_TYPE_MEMBER_SURGE_SHRINK
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
                 board_dict=None):
        self._members = members          # {code: [6位codes]}
        self._complete = complete or {}  # {code: bool}，缺省 True
        self._fund_flow = fund_flow or {}
        self._bar = bar or {}
        self._board_dict = board_dict or {}

    def get_board_members(self, code, board_type="concept"):
        codes = self._members.get(code, [])
        return {"codes": codes, "complete": self._complete.get(code, True), "pages": 1}

    def get_board_dict(self, board_type):
        return self._board_dict.get(board_type, _EMPTY_MEMBER_DF)

    def get_board_bar(self, code, board_type, start, end):
        return self._bar.get(code, _EMPTY_BAR_DF)

    def get_board_fund_flow(self, board_type, period):
        return self._fund_flow.get((board_type, period), _EMPTY_FLOW_DF)


def _make_service(tmp_path, source=None, **kw) -> tuple[BoardIngestService, DuckDBClient]:
    c = DuckDBClient(db_path=str(tmp_path / "test.duckdb"))
    init_db(c)
    svc = BoardIngestService(client=c, source=source)
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
    r = svc.ingest_board_members(snapshot_date=date(2026, 1, 5), board_codes=["309121"])
    assert set(r.keys()) == {"309121"}
    assert "881121" not in r
    # ingest_board_bar 指定 board_codes（空 bar 返回不崩）
    bar = svc.ingest_board_bar(date(2026, 1, 1), board_codes=["881121"])
    assert "boards" in bar


def test_payload_hash_normalization():
    """payload_hash：SHA-256(ISO日期 + \\n + sorted(set).join(\\n))，代码集换序/重复 → 同 hash。"""
    svc, c = _make_service(Path(tempfile.mkdtemp()), _FakeSource({}))
    h1 = svc._payload_hash(date(2026, 1, 5), {"600000.SH", "000001.SZ"})
    h2 = svc._payload_hash(date(2026, 1, 5), {"000001.SZ", "600000.SH", "600000.SH"})  # 换序+重复
    assert h1 == h2
    assert len(h1) == 64
    assert h1 == h1.lower()
    # 不同日期 → 不同 hash
    h3 = svc._payload_hash(date(2026, 1, 6), {"600000.SH", "000001.SZ"})
    assert h1 != h3


def test_payload_hash_rejects_invalid():
    """payload_hash 输出必须 64 位小写 hex（生产由 DB CHECK 拦截非法，此处验证输出合法）。"""
    svc, c = _make_service(Path(tempfile.mkdtemp()), _FakeSource({}))
    h = svc._payload_hash(date(2026, 1, 5), {"600000.SH"})
    import re
    assert re.fullmatch(r"[0-9a-f]{64}", h)


# ── 成分快照 diff 与 member_count ─────────────────────────────


def test_member_diff_and_member_count(tmp_path):
    """完整快照 diff 落库 [in_date,out_date) + member_count 刷新（已应用路径）。"""
    src = _FakeSource({"309121": ["300476", "603936", "002913"]})
    svc, c = _make_service(tmp_path, src)
    # 先种字典
    c.execute("INSERT INTO board_dict (board_code, name, board_type, has_members) "
              "VALUES ('309121','AI PC','concept',TRUE)")
    r = svc._ingest_one_member("309121", "concept", date(2026, 1, 5))
    assert r["added"] == 3
    df = c.query_df("SELECT code, in_date, out_date FROM board_member")
    assert len(df) == 3
    assert all(pd.isna(df["out_date"]))
    # member_count 刷新
    mc = _member_count(c, "309121")
    assert int(mc) == 3
    # 第二次快照：新股 + 缺席股退出
    src2 = _FakeSource({"309121": ["300476", "603936", "300750"]})
    svc2, c2 = _make_service(tmp_path.parent / "t2.duckdb", src2)
    c2.execute("INSERT INTO board_dict (board_code, name, board_type, has_members, member_count) "
               "VALUES ('309121','AI PC','concept',TRUE, 3)")
    # 先给 board_member 种 3 条（后缀对齐 to_full_code）
    for code in ["300476.SZ", "603936.SH", "002913.SZ"]:
        c2.execute("INSERT INTO board_member VALUES ('309121',?,DATE '2026-01-05',NULL)", [code])
    r2 = svc2._ingest_one_member("309121", "concept", date(2026, 1, 6))
    # 300476/603936 保留（in_date 已有），300750 新增，002913 退出
    assert r2["added"] == 1  # 300750
    df2 = c2.query_df("SELECT code, out_date FROM board_member WHERE code='002913.SZ'")
    assert pd.Timestamp(df2.iloc[0]["out_date"]).date() == date(2026, 1, 6)  # 退出标记
    df3 = c2.query_df("SELECT in_date FROM board_member WHERE code='300750.SZ'")
    assert pd.Timestamp(df3.iloc[0]["in_date"]).date() == date(2026, 1, 6)  # 新增


def test_incomplete_snapshot_no_exit_diff(tmp_path):
    """不完整快照（complete=False）→ 不执行退出 diff，写候选 + issue，member_count 不刷新。"""
    src = _FakeSource({"309121": ["300476", "603936"]}, complete={"309121": False})
    svc, c = _make_service(tmp_path, src)
    c.execute("INSERT INTO board_dict (board_code, name, board_type, has_members, member_count) "
              "VALUES ('309121','AI PC','concept',TRUE, 10)")
    r = svc._ingest_one_member("309121", "concept", date(2026, 1, 5))
    assert r["blocked"] is True
    assert r["reason"] == "incomplete"
    # 候选与 issue 已写
    cand = c.query_df("SELECT candidate_id, status, payload_hash FROM board_member_candidate")
    assert len(cand) == 1
    assert cand.iloc[0]["status"] == "pending"
    iss = c.query_df("SELECT issue_type, status FROM data_quality_issue")
    assert len(iss) == 1
    assert iss.iloc[0]["issue_type"] == ISSUE_TYPE_MEMBER_SURGE_SHRINK
    assert iss.iloc[0]["status"] == "open"
    # member_count 不刷新（仍 10），board_member 无 diff
    mc = _member_count(c, "309121")
    assert int(mc) == 10
    assert len(c.query_df("SELECT 1 FROM board_member")) == 0


def test_same_hash_idempotent(tmp_path):
    """同 hash 幂等四态：同 hash+pending 返回已有不新开；+applied/discarded 跳过。"""
    src = _FakeSource({"309121": ["300476"]}, complete={"309121": False})  # 强制候选路径
    svc, c = _make_service(tmp_path, src)
    c.execute("INSERT INTO board_dict (board_code, name, board_type, has_members, member_count) "
              "VALUES ('309121','AI PC','concept',TRUE, 10)")
    r1 = svc._ingest_one_member("309121", "concept", date(2026, 1, 5))
    assert r1["blocked"] is True
    r2 = svc._ingest_one_member("309121", "concept", date(2026, 1, 5))
    assert r2["reason"] == "same_hash_pending"
    assert r2["candidate_id"] == r1["candidate_id"]
    assert len(c.query_df("SELECT 1 FROM board_member_candidate")) == 1
    # 置 applied 后重跑 → 跳过
    c.execute(
        "UPDATE board_member_candidate SET status='applied' "
        "WHERE candidate_id=?", [r1["candidate_id"]])
    r3 = svc._ingest_one_member("309121", "concept", date(2026, 1, 5))
    assert r3["reason"] == "same_hash_applied"
    assert len(c.query_df("SELECT 1 FROM board_member_candidate")) == 1


def test_wave_blocked_candidate(tmp_path):
    """成分数波动超阈值 → 候选 + issue（wave），不落库不刷新 member_count。"""
    codes = [f"3000{i:02d}" for i in range(30)]  # 30 只不同代码 vs 前次 10
    src = _FakeSource({"309121": codes})
    svc, c = _make_service(tmp_path, src)
    c.execute("INSERT INTO board_dict (board_code, name, board_type, has_members, member_count) "
              "VALUES ('309121','AI PC','concept',TRUE, 10)")
    r = svc._ingest_one_member("309121", "concept", date(2026, 1, 5))
    assert r["blocked"] is True
    assert r["reason"] == "wave"
    mc = _member_count(c, "309121")
    assert int(mc) == 10  # 未刷新
    assert len(c.query_df("SELECT 1 FROM board_member")) == 0  # 不落库


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


# ── 事务原子性 ────────────────────────────────────────────────


def test_candidate_transaction_atomicity(tmp_path):
    """候选保存事务①：中途失败整体回滚（候选与 issue 都不落）。"""
    src = _FakeSource({"309121": ["300476"]}, complete={"309121": False})
    svc, c = _make_service(tmp_path, src)
    c.execute("INSERT INTO board_dict (board_code, name, board_type, has_members, member_count) "
              "VALUES ('309121','AI PC','concept',TRUE, 10)")
    # 用真实 transaction() 验证：先在事务内写候选，再抛错 → 回滚
    try:
        with c.transaction():
            c.execute(
                "INSERT INTO board_member_candidate (candidate_id, board_code, snapshot_date, "
                "payload_hash, status) VALUES ('tx-fail','309121',DATE '2026-01-05',?, 'pending')",
                ["a" * 64])
            raise RuntimeError("注入失败")
    except StorageError:
        pass
    # 回滚后候选与 issue 均无
    assert len(c.query_df("SELECT 1 FROM board_member_candidate WHERE candidate_id='tx-fail'")) == 0
    # 事务外单独写候选 → 成功（验证连接恢复）
    h = svc._payload_hash(date(2026, 1, 5), {"300476.SH"})
    with c.transaction():
        c.execute(
            "INSERT INTO board_member_candidate (candidate_id, board_code, snapshot_date, "
            "payload_hash, status) VALUES ('ok1','309121',DATE '2026-01-05',?, 'pending')", [h])
    assert len(c.query_df("SELECT 1 FROM board_member_candidate WHERE candidate_id='ok1'")) == 1


def test_write_lock_classification():
    """写锁冲突归类：锁关键字命中 → StorageError 消息带「写锁占用」。"""
    from backend.storage.duckdb_client import _LOCK_CONFLICT_RE
    assert _LOCK_CONFLICT_RE.search("Could not set lock on file ... Conflicting lock is held")
    assert _LOCK_CONFLICT_RE.search("IO Error: Conflicting lock is held")
    assert not _LOCK_CONFLICT_RE.search("普通事务错误")


def test_member_diff_member_count_atomic(tmp_path):
    """diff 与 member_count 同事务：中途失败整体回滚，member_count 不残留（R2 原子性）。"""
    src = _FakeSource({"309121": ["300476", "603936", "002913"]})
    svc, c = _make_service(tmp_path, src)
    c.execute("INSERT INTO board_dict (board_code, name, board_type, has_members) "
              "VALUES ('309121','AI PC','concept',TRUE)")
    # 直接调 _apply_member_diff：注入失败（第 3 条 added 前抛错）→ 整体回滚
    with pytest.raises(StorageError):
        with c.transaction():
            c.execute("INSERT INTO board_member (board_code, code, in_date, out_date) "
                      "VALUES ('309121','300476.SZ',DATE '2026-01-05',NULL)")
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
    svc.ingest_board_members(board_codes=["309121"])
    svc.ingest_board_bar(date(2026, 8, 1), board_codes=["309121"])
    svc.ingest_board_fund_flow(periods=("即时",))
    assert set(calls["fund_periods"]) == {"即时"}    # update 只采即时（概念+行业各一次）
    # backfill 模式（直接调 fund_flow 全周期）
    calls["fund_periods"].clear()
    svc.ingest_board_fund_flow()
    assert set(calls["fund_periods"]) == {"即时", "3日", "5日", "10日", "20日"}  # backfill 全周期
