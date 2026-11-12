"""资产归属审查修复回归测试。

- 平台槽账号（PUBLIC_BOARD_OWNER）下 list_mine 不得混入任何系统预设，包括历史 private 行。
- 三类平台预设的 seed 必须补齐缺失记录并把历史状态幂等校准为 public。
- P1-1：发布态回测的方案引用列已改写成 opaque ref，q 必须在解析 ref、补全方案名之后过滤，
  按引用方案名能命中发布态回测。
- P1-2：复制走原子 INSERT ... ON CONFLICT DO NOTHING，撞到同 id 既有资产时不覆盖、返回 False。

用 market 内存库 + PG，避开文件 DuckDB 锁。
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date

import pytest

from backend.common.exceptions import StorageError
from backend.scoring import score_profile as score_profile_module
from backend.screening.presets import PRESET_PROFILES
from backend.screening import profile as screen_profile_module
from backend.screening.profile import ProfileRepo
from backend.scoring.score_profile import ScoreProfileRepo
from backend.services.asset_visibility import make_asset_ref
from backend.services.asset_visibility import ASSET_SCREEN_PROFILE
from backend.services.backtest_service import BacktestService
from backend.signals import trade_profile as trade_profile_module
from backend.signals.trade_profile import TradeProfileRepo
from backend.storage.pg_ddl import PUBLIC_BOARD_OWNER
from backend.tests.conftest import TEST_OWNER, TEST_TENANT

_EXPR = PRESET_PROFILES[0]["expression"]
_ITEMS = [{"indicator": "rs_pct", "weight": 1.0, "scoring": {"type": "linear", "min": 0, "max": 100}}]
_BUY = {"op": "AND", "children": [{"indicator": "bull_arrange", "cmp": "==", "value": True}]}
_SELL = {"op": "OR", "children": [{"indicator": "below_ma", "params": {"n": 20}, "cmp": "==", "value": True}]}
_SLOT_T, _SLOT_O = PUBLIC_BOARD_OWNER


# ── 故障注入：让「版本表」INSERT 抛错，验证复制的事务原子性（R2-P1）──────────
class _FaultCursor:
    """代理游标：命中版本表 INSERT（含 profile_version）即抛错，其余透传。"""

    def __init__(self, real):
        self._real = real

    def execute(self, sql, params=None):
        if "profile_version" in sql:
            raise RuntimeError("fault-injected: version insert failure")
        return self._real.execute(sql, params)

    @property
    def rowcount(self):
        return self._real.rowcount


class _FaultConn:
    def __init__(self, real):
        self._real = real

    @contextmanager
    def cursor(self):
        with self._real.cursor() as c:
            yield _FaultCursor(c)


class _FaultPG:
    """包装真实 pg：仅 transaction() 内的版本表 INSERT 故障；其余方法透传。"""

    def __init__(self, real):
        self._real = real

    def __getattr__(self, name):
        return getattr(self._real, name)

    @contextmanager
    def transaction(self):
        with self._real.transaction() as conn:
            yield _FaultConn(conn)


# ── P1-3：平台槽 mine 与 preset 互斥 ────────────────────────────────
def test_platform_slot_mine_excludes_public_and_legacy_private_presets(market, pg):
    """平台槽 mine 排除全部系统预设，包括初始化修复前遗留的 private 预设。"""
    slot = ScoreProfileRepo(market=market, pg=pg, tenant_id=_SLOT_T, owner_user_id=_SLOT_O)
    try:
        slot.save("slot_preset_x", "平台内置预设X", _ITEMS, is_preset=True)   # owner==slot → 自动 public
        pg.execute(
            "UPDATE score_profile SET visibility='private', published_at=NULL, published_by=NULL "
            "WHERE tenant_id=%s AND owner_user_id=%s AND id=%s",
            [_SLOT_T, _SLOT_O, "slot_preset_x"],
        )
        slot.save("slot_private_x", "平台私有X", _ITEMS)                       # private
        mine_ids = {r["id"] for r in slot.list_mine()}
        assert "slot_private_x" in mine_ids            # 自己的私有资产仍在 mine
        assert "slot_preset_x" not in mine_ids         # private preset 也不能伪装成 mine
        assert "slot_preset_x" not in {
            r["id"] for r in slot.browse("preset")["items"]
        }                                               # 未修复前也不泄露到公开浏览
    finally:
        for table in ("score_profile", "score_profile_version"):
            pg.execute(
                f"DELETE FROM {table} WHERE tenant_id=%s AND owner_user_id=%s "
                "AND id IN (%s,%s)",
                [_SLOT_T, _SLOT_O, "slot_preset_x", "slot_private_x"],
            )


def test_platform_seed_restores_and_publishes_all_profile_presets(market, pg, monkeypatch):
    """统一 seed 补齐评分默认项，并修复筛选/买卖历史 private 预设。"""
    screen_id = "pytest_seed_screen"
    score_id = "pytest_seed_score"
    trade_id = "pytest_seed_trade"
    monkeypatch.setattr(screen_profile_module, "PRESET_PROFILES", [{
        "id": screen_id, "name": "测试筛选预设", "expression": _EXPR,
    }])
    monkeypatch.setattr(score_profile_module, "DEFAULT_SCORE_PROFILES", [{
        "id": score_id,
        "name": "测试评分预设",
        "items": _ITEMS,
        "grade_thresholds": {"watch": 80, "leader": 90, "core": 95},
    }])
    monkeypatch.setattr(trade_profile_module, "DEFAULT_TRADE_PROFILES", [{
        "id": trade_id,
        "name": "测试买卖预设",
        "buy_tree": _BUY,
        "sell_tree": _SELL,
        "backstop": {},
    }])
    screen = ProfileRepo(pg=pg, tenant_id=_SLOT_T, owner_user_id=_SLOT_O)
    score = ScoreProfileRepo(market=market, pg=pg, tenant_id=_SLOT_T, owner_user_id=_SLOT_O)
    trade = TradeProfileRepo(market=market, pg=pg, tenant_id=_SLOT_T, owner_user_id=_SLOT_O)
    try:
        assert screen.seed_presets() == 1
        assert score.seed_defaults() == 1
        assert trade.seed_defaults() == 1
        for table, preset_id in (
            ("screen_profile", screen_id),
            ("score_profile", score_id),
            ("trade_profile", trade_id),
        ):
            row = pg.query_df(
                f"SELECT is_preset, visibility, published_at, published_by FROM {table} "
                "WHERE tenant_id=%s AND owner_user_id=%s AND id=%s",
                [_SLOT_T, _SLOT_O, preset_id],
            ).iloc[0]
            assert bool(row["is_preset"]) is True
            assert row["visibility"] == "public"
            assert row["published_at"] is not None
            assert row["published_by"] == _SLOT_O

        # 模拟旧库回退：再次 seed 必须自愈，且不创建重复记录。
        pg.execute(
            "UPDATE screen_profile SET visibility='private', published_at=NULL, published_by=NULL "
            "WHERE tenant_id=%s AND owner_user_id=%s AND id=%s",
            [_SLOT_T, _SLOT_O, screen_id],
        )
        assert screen.seed_presets() == 1
        healed = pg.query_df(
            "SELECT visibility, published_at, published_by FROM screen_profile "
            "WHERE tenant_id=%s AND owner_user_id=%s AND id=%s",
            [_SLOT_T, _SLOT_O, screen_id],
        ).iloc[0]
        assert healed["visibility"] == "public"
        assert healed["published_at"] is not None
        assert healed["published_by"] == _SLOT_O
    finally:
        for table, preset_id in (
            ("screen_profile", screen_id),
            ("score_profile", score_id),
            ("trade_profile", trade_id),
        ):
            pg.execute(
                f"DELETE FROM {table} WHERE tenant_id=%s AND owner_user_id=%s AND id=%s",
                [_SLOT_T, _SLOT_O, preset_id],
            )
            pg.execute(
                f"DELETE FROM {table}_version WHERE tenant_id=%s AND owner_user_id=%s AND id=%s",
                [_SLOT_T, _SLOT_O, preset_id],
            )


# ── P1-1：发布态回测按引用方案名搜索 ────────────────────────────────
def test_published_backtest_q_matches_referenced_profile_name(pg, market):
    """发布回测把 profile_id 改写成 opaque ref；q 需在解析 ref 后过滤，按方案名能命中。"""
    other = "pytest_pub_bt_owner"
    B = ProfileRepo(pg=pg, tenant_id=TEST_TENANT, owner_user_id=other)
    viewer = BacktestService(market, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER)
    ref = make_asset_ref(ASSET_SCREEN_PROFILE, TEST_TENANT, other, "pub_screen_bt")
    try:
        B.save("pub_screen_bt", "发布态独特名PZ", _EXPR)
        B.set_visibility("pub_screen_bt", "public")
        # 模拟发布态回测：profile_id 已是 opaque ref（非裸 id），run 自身 public
        pg.execute(
            "INSERT INTO backtest_run (id, tenant_id, owner_user_id, kind, profile_id, "
            "date_start, date_end, params, status, visibility, published_at, published_by, "
            "created_at, finished_at) "
            "VALUES (%s,%s,%s,'strategy',%s,%s,%s,'{}','done','public',now(),%s,now(),now())",
            ["pub_run_pz", TEST_TENANT, other, ref, date(2024, 1, 1), date(2024, 1, 31), other],
        )
        # 不带 q：发布态回测可见且方案名被补全
        no_q = {r["id"]: r for r in viewer.list_runs(source="public")}
        assert "pub_run_pz" in no_q
        assert no_q["pub_run_pz"].get("profile_name") == "发布态独特名PZ"
        # 带 q（按引用方案名）：修复前 SQL JOIN 裸 id 取不到 ref → 0 条；修复后命中
        hit = {r["id"] for r in viewer.list_runs(source="public", q="发布态独特名")}
        assert "pub_run_pz" in hit
        # q 不匹配 → 不出现
        miss = {r["id"] for r in viewer.list_runs(source="public", q="绝不匹配ZZZ")}
        assert "pub_run_pz" not in miss
    finally:
        pg.execute("DELETE FROM backtest_run WHERE owner_user_id=%s", [other])
        pg.execute("DELETE FROM screen_profile WHERE owner_user_id=%s", [other])
        pg.execute("DELETE FROM screen_profile_version WHERE owner_user_id=%s", [other])


# ── P1-2：复制原子插入不覆盖同 id 既有资产 ──────────────────────────
def test_insert_copy_does_not_clobber_existing_asset(pg):
    """_insert_copy 撞到同 id 既有资产：返回 False，且既有资产内容不被覆盖。"""
    A = ProfileRepo(pg=pg, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER)
    try:
        A.save("clobber_target", "原始不可被覆盖", _EXPR)
        original = A.get("clobber_target")
        # 用不同名/表达式尝试插入到同一个 id
        other_expr = PRESET_PROFILES[1]["expression"] if len(PRESET_PROFILES) > 1 else _EXPR
        ok = A._insert_copy("clobber_target", "企图覆盖的名字", other_expr, {})
        assert ok is False
        after = A.get("clobber_target")
        assert after["name"] == original["name"] == "原始不可被覆盖"
        assert after["version"] == original["version"]
    finally:
        pg.execute("DELETE FROM screen_profile WHERE owner_user_id=%s", [TEST_OWNER])
        pg.execute("DELETE FROM screen_profile_version WHERE owner_user_id=%s", [TEST_OWNER])


# ── R2-P1：复制事务原子性——版本表失败必须整体回滚，杜绝「主表残留、无版本」半成品 ──
def test_screen_insert_copy_rolls_back_when_version_insert_fails(pg):
    A = ProfileRepo(pg=pg, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER)
    A.pg = _FaultPG(pg)
    try:
        with pytest.raises(StorageError):
            A._insert_copy("rb_screen", "回滚测试", _EXPR, {})
        main = pg.query_df(
            "SELECT 1 FROM screen_profile WHERE tenant_id=%s AND owner_user_id=%s AND id=%s",
            [TEST_TENANT, TEST_OWNER, "rb_screen"])
        ver = pg.query_df(
            "SELECT 1 FROM screen_profile_version WHERE tenant_id=%s AND owner_user_id=%s AND id=%s",
            [TEST_TENANT, TEST_OWNER, "rb_screen"])
        assert main.empty and ver.empty  # 主表 + 版本表都零残留
    finally:
        pg.execute("DELETE FROM screen_profile WHERE owner_user_id=%s", [TEST_OWNER])
        pg.execute("DELETE FROM screen_profile_version WHERE owner_user_id=%s", [TEST_OWNER])


def test_score_insert_copy_rolls_back_when_version_insert_fails(market, pg):
    A = ScoreProfileRepo(market=market, pg=pg, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER)
    A.pg = _FaultPG(pg)
    try:
        with pytest.raises(StorageError):
            A._insert_copy("rb_score", "回滚测试", _ITEMS, {}, include_st=True)
        main = pg.query_df(
            "SELECT 1 FROM score_profile WHERE tenant_id=%s AND owner_user_id=%s AND id=%s",
            [TEST_TENANT, TEST_OWNER, "rb_score"])
        ver = pg.query_df(
            "SELECT 1 FROM score_profile_version WHERE tenant_id=%s AND owner_user_id=%s AND id=%s",
            [TEST_TENANT, TEST_OWNER, "rb_score"])
        assert main.empty and ver.empty
    finally:
        pg.execute("DELETE FROM score_profile WHERE owner_user_id=%s", [TEST_OWNER])
        pg.execute("DELETE FROM score_profile_version WHERE owner_user_id=%s", [TEST_OWNER])


def test_trade_insert_copy_rolls_back_when_version_insert_fails(market, pg):
    A = TradeProfileRepo(market=market, pg=pg, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER)
    A.pg = _FaultPG(pg)
    try:
        with pytest.raises(StorageError):
            A._insert_copy("rb_trade", "回滚测试", _BUY, _SELL, {})
        main = pg.query_df(
            "SELECT 1 FROM trade_profile WHERE tenant_id=%s AND owner_user_id=%s AND id=%s",
            [TEST_TENANT, TEST_OWNER, "rb_trade"])
        ver = pg.query_df(
            "SELECT 1 FROM trade_profile_version WHERE tenant_id=%s AND owner_user_id=%s AND id=%s",
            [TEST_TENANT, TEST_OWNER, "rb_trade"])
        assert main.empty and ver.empty
    finally:
        pg.execute("DELETE FROM trade_profile WHERE owner_user_id=%s", [TEST_OWNER])
        pg.execute("DELETE FROM trade_profile_version WHERE owner_user_id=%s", [TEST_OWNER])


# ── R2-P1：score/trade 两实现的撞库不覆盖 + 撞库候选换 id（并发/双击等价路径）──
def test_score_insert_copy_does_not_clobber_and_retries_new_id(market, pg):
    A = ScoreProfileRepo(market=market, pg=pg, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER)
    try:
        A.save("score_keep", "评分原始", _ITEMS)
        before = A.get("score_keep")
        # 同 id 二次插入：第二次撞库返回 False，不覆盖
        assert A._insert_copy("score_keep", "企图覆盖", _ITEMS, {}, include_st=True) is False
        assert A.get("score_keep")["name"] == before["name"] == "评分原始"
        # copy_visible 连点两次得到不同 id（撞库自动换 id），各自成一份
        r1 = A.copy_visible(A.get_visible("score_keep")["profile_ref"] if hasattr(A, "get_visible") else "score_keep")
        r2 = A.copy_visible("score_keep")
        assert r1["id"] != r2["id"] and r1["version"] == r2["version"] == 1
    finally:
        pg.execute("DELETE FROM score_profile WHERE owner_user_id=%s", [TEST_OWNER])
        pg.execute("DELETE FROM score_profile_version WHERE owner_user_id=%s", [TEST_OWNER])


def test_trade_insert_copy_does_not_clobber(market, pg):
    A = TradeProfileRepo(market=market, pg=pg, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER)
    try:
        A.save("trade_keep", "买卖原始", _BUY, _SELL, {})
        before = A.get("trade_keep")
        assert A._insert_copy("trade_keep", "企图覆盖", _BUY, _SELL, {}) is False
        assert A.get("trade_keep")["name"] == before["name"] == "买卖原始"
    finally:
        pg.execute("DELETE FROM trade_profile WHERE owner_user_id=%s", [TEST_OWNER])
        pg.execute("DELETE FROM trade_profile_version WHERE owner_user_id=%s", [TEST_OWNER])


# ── R3-P1：孤儿版本冲突必须抛错回滚，不静默吞成「主表新、版本旧」──────────────
def test_insert_copy_orphan_version_conflict_rolls_back_main(pg):
    """预置孤儿 version=1（无主表行）后复制到同 id：版本表冲突 → 抛错 → 主表回滚；孤儿不被覆盖。"""
    A = ProfileRepo(pg=pg, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER)
    from datetime import datetime
    try:
        # 孤儿版本行（主表无对应 id）
        pg.execute(
            "INSERT INTO screen_profile_version "
            "(id,tenant_id,owner_user_id,version,name,expression,saved_at) "
            "VALUES (%s,%s,%s,1,%s,%s,%s)",
            ["orphan_v", TEST_TENANT, TEST_OWNER, "stale-version",
             __import__("json").dumps(_EXPR, ensure_ascii=False), datetime.now()],
        )
        with pytest.raises(StorageError):
            A._insert_copy("orphan_v", "fresh-main", _EXPR, {})
        # 主表零残留（回滚）
        main = pg.query_df(
            "SELECT 1 FROM screen_profile WHERE tenant_id=%s AND owner_user_id=%s AND id=%s",
            [TEST_TENANT, TEST_OWNER, "orphan_v"])
        assert main.empty
        # 孤儿版本仍是原内容，未被 fresh-main 覆盖
        ver = pg.query_df(
            "SELECT name FROM screen_profile_version WHERE tenant_id=%s AND owner_user_id=%s AND id=%s",
            [TEST_TENANT, TEST_OWNER, "orphan_v"])
        assert not ver.empty and ver.iloc[0]["name"] == "stale-version"
    finally:
        pg.execute("DELETE FROM screen_profile WHERE owner_user_id=%s", [TEST_OWNER])
        pg.execute("DELETE FROM screen_profile_version WHERE owner_user_id=%s", [TEST_OWNER])


# ── R3-P1：回测 q 无扫描上限——靠后的匹配项 + limit 不会静默漏掉 ──────────────
def test_backtest_q_finds_match_regardless_of_position_with_limit(pg, market):
    """撤销有界扫描后：唯一匹配项即使排在很多非匹配之后，limit=1/None 也必须命中（不早停漏掉）。"""
    svc = BacktestService(market, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER)
    try:
        # 多条非匹配（strategy）+ 1 条匹配（score_check）；id 使匹配项排在末位
        for i in range(6):
            pg.execute(
                "INSERT INTO backtest_run (id, tenant_id, owner_user_id, kind, "
                "date_start, date_end, params, status, created_at, finished_at) "
                "VALUES (%s,%s,%s,'strategy',%s,%s,'{}','done',now(),now())",
                [f"qpos_a{i}", TEST_TENANT, TEST_OWNER, date(2024, 1, 1), date(2024, 1, 31)],
            )
        pg.execute(
            "INSERT INTO backtest_run (id, tenant_id, owner_user_id, kind, "
            "date_start, date_end, params, status, created_at, finished_at) "
            "VALUES (%s,%s,%s,'score_check',%s,%s,'{}','done',now(),now())",
            ["qpos_zz_match", TEST_TENANT, TEST_OWNER, date(2024, 1, 1), date(2024, 1, 31)],
        )
        # limit=None 命中
        assert "qpos_zz_match" in {r["id"] for r in svc.list_runs(q="score_check")}
        # limit=1 仍命中（过滤在前、截断在后，不因早停漏掉靠后的匹配）
        hit1 = svc.list_runs(q="score_check", limit=1)
        assert len(hit1) == 1 and hit1[0]["id"] == "qpos_zz_match"
    finally:
        pg.execute("DELETE FROM backtest_run WHERE owner_user_id=%s", [TEST_OWNER])
