"""买卖指标方案（v2.0 §6，M2.3，决策 D4）——买/卖条件成对保存 + 可选兜底。

条件树（买入 / 卖出各一棵，与评分共用"指标+参数"解析，天然支持内置+自定义指标）：
  节点  = {"op": "AND"|"OR", "children": [...]}
  叶子  = {"indicator": key, "params": {...}, "cmp": ">=|<=|>|<|==|!=|between", "value": 数值|布尔|[lo,hi]}
求值：解析每个叶子指标取值 → 比较 → 按 AND/OR 合并 → 命中布尔 Series（点时安全,沿用动态计算）。

兜底 backstop（可空）：{take_profit, stop_loss, max_hold_days}，回测(M2.5)中作卖出安全网,
与"卖出条件命中"先到先卖（D4：指标组合为主 + 兜底）。
"""

from __future__ import annotations

import json
from datetime import datetime

import pandas as pd

from backend.auth.context import get_current_owner
from backend.common.ids import prefixed_readable_id
from backend.common.logging import get_logger
from backend.scoring.score_profile import resolve_indicator
from backend.services.asset_visibility import (
    ASSET_TRADE_PROFILE,
    VISIBILITY_PRIVATE,
    decorate_asset_row,
    is_asset_visible,
    normalize_visibility,
    resolve_asset_ref_or_legacy_id,
    summarize_asset_row,
    visible_params,
    visible_sql,
)
from backend.storage.duckdb_client import get_client
from backend.storage.pg_client import get_pg_client

log = get_logger("signals.trade_profile")

_CMP = {
    "==": lambda s, v: s == v,
    "!=": lambda s, v: s != v,
    ">": lambda s, v: s > v,
    ">=": lambda s, v: s >= v,
    "<": lambda s, v: s < v,
    "<=": lambda s, v: s <= v,
    "between": lambda s, v: (s >= v[0]) & (s <= v[1]),
}


def _eval_leaf(leaf: dict, snap: pd.DataFrame) -> pd.Series:
    val = resolve_indicator(leaf["indicator"], leaf.get("params"), snap)
    cmp = leaf.get("cmp", "==")
    res = _CMP[cmp](val, leaf.get("value"))
    return res.fillna(False).astype(bool)


def eval_conditions(tree: dict, snap: pd.DataFrame) -> pd.Series:
    """对截面 snap（index=code）求条件树命中 → 布尔 Series。空树视为全不命中。"""
    if not tree:
        return pd.Series(False, index=snap.index)
    if "op" in tree:
        children = tree.get("children", [])
        if not children:
            return pd.Series(False, index=snap.index)
        parts = [eval_conditions(ch, snap) for ch in children]
        res = parts[0]
        for p in parts[1:]:
            res = (res & p) if tree["op"] == "AND" else (res | p)
        return res
    return _eval_leaf(tree, snap)


def collect_indicators(tree: dict) -> list[dict]:
    """提取条件树用到的全部 (indicator, params)（供 attach_columns 预补列）。"""
    if not tree:
        return []
    if "op" in tree:
        out: list[dict] = []
        for ch in tree.get("children", []):
            out.extend(collect_indicators(ch))
        return out
    return [{"indicator": tree["indicator"], "params": tree.get("params")}]


def _validate_tree(tree: dict, known: set[str], where: str) -> None:
    if not tree:
        return
    if "op" in tree:
        if tree["op"] not in ("AND", "OR"):
            raise ValueError(f"{where} 逻辑须为 AND/OR")
        for ch in tree.get("children", []):
            _validate_tree(ch, known, where)
        return
    ind = tree.get("indicator")
    if not ind:
        raise ValueError(f"{where} 条件缺少 indicator")
    if known and ind not in known:
        raise ValueError(f"{where} 指标不存在: {ind}")
    if tree.get("cmp", "==") not in _CMP:
        raise ValueError(f"{where} 比较符非法: {tree.get('cmp')}")


def validate_trade_profile(buy_tree: dict, sell_tree: dict, backstop: dict | None,
                           known: set[str] | None = None) -> None:
    known = known or set()
    if not buy_tree or ("op" in buy_tree and not buy_tree.get("children")):
        raise ValueError("买入条件不能为空")
    has_sell = bool(sell_tree and (("op" not in sell_tree) or sell_tree.get("children")))
    has_backstop = bool(backstop) and any(
        backstop.get(k) not in (None, "") for k in ("take_profit", "stop_loss", "max_hold_days"))
    if not has_sell and not has_backstop:
        raise ValueError("卖出条件与兜底（止盈/止损/最大持仓）至少需配置其一")
    _validate_tree(buy_tree, known, "买入")
    _validate_tree(sell_tree, known, "卖出")


# ── 默认买卖方案（示范:多头放量买入;跌破MA20 或 止盈止损 卖出）──
DEFAULT_TRADE_PROFILES: list[dict] = [
    {
        "id": "default", "name": "趋势买卖",
        "buy_tree": {"op": "AND", "children": [
            {"indicator": "bull_arrange", "cmp": "==", "value": True},
            {"indicator": "is_vol_breakout", "cmp": "==", "value": True},
        ]},
        "sell_tree": {"op": "OR", "children": [
            {"indicator": "below_ma", "params": {"n": 20}, "cmp": "==", "value": True},
        ]},
        "backstop": {"take_profit": 0.20, "stop_loss": 0.08, "max_hold_days": 30},
    },
    {
        # 用户方案：贴近5日线买入、跌破10日线卖出（用直观的 贴近均线/跌破均线 指标）
        "id": "ma5_pullback", "name": "5日线贴近买·跌破10日线卖",
        "buy_tree": {"op": "AND", "children": [
            {"indicator": "near_ma", "params": {"n": 5, "tol": 1}, "cmp": "==", "value": True},
        ]},
        "sell_tree": {"op": "OR", "children": [
            {"indicator": "below_ma", "params": {"n": 10}, "cmp": "==", "value": True},
        ]},
        "backstop": {"take_profit": None, "stop_loss": 0.08, "max_hold_days": None},
    },
]


class TradeProfileRepo:
    """买卖方案存取（trade_profile，用户资产→PG）。

    方案/版本走 PG（self.pg，%s + 归属过滤）；指标定义 indicator_def 仍在 DuckDB，
    经 IndicatorDefRepo(self.mkt) 读取。第一位保留为 market 以兼容历史 Repo(c) 调用。
    """

    def __init__(self, market=None, pg=None, *, tenant_id: str | None = None,
                 owner_user_id: str | None = None):
        self.mkt = market or get_client()
        self.pg = pg or get_pg_client()
        _ctx_t, _ctx_o = get_current_owner()
        self.tenant_id = tenant_id or _ctx_t
        self.owner_user_id = owner_user_id or _ctx_o

    @property
    def _own(self) -> str:
        return "tenant_id=%s AND owner_user_id=%s"

    @property
    def _op(self) -> list:
        return [self.tenant_id, self.owner_user_id]

    def _known(self) -> set[str]:
        from backend.indicators.definition import IndicatorDefRepo
        return {d["key"] for d in IndicatorDefRepo(self.mkt).list()}

    def _make_id(self, name: str) -> str:
        base = prefixed_readable_id(name, prefix="trade_")
        pid = base
        seq = 2
        while self.get(pid):
            pid = f"{base}_{seq}"
            seq += 1
        return pid

    def _decorate_summary(self, r: dict) -> dict:
        return summarize_asset_row(
            r,
            asset_type=ASSET_TRADE_PROFILE,
            tenant_id=self.tenant_id,
            owner_user_id=self.owner_user_id,
        )

    def _row_to_profile(self, r: dict, *, include_owner: bool = False) -> dict:
        out = decorate_asset_row(
            r,
            asset_type=ASSET_TRADE_PROFILE,
            tenant_id=self.tenant_id,
            owner_user_id=self.owner_user_id,
            include_owner=include_owner,
            ref_key="profile_ref",
        )
        out["version"] = int(out["version"])
        out["is_preset"] = bool(out.get("is_preset"))
        out["buy_tree"] = json.loads(out["buy_tree"]) if out.get("buy_tree") else {}
        out["sell_tree"] = json.loads(out["sell_tree"]) if out.get("sell_tree") else {}
        out["backstop"] = json.loads(out["backstop"]) if out.get("backstop") else {}
        out["published_at"] = str(out["published_at"]) if out.get("published_at") else None
        return out

    def save(self, pid: str | None, name: str, buy_tree: dict, sell_tree: dict | None,
             backstop: dict | None = None, is_preset: bool = False) -> int:
        name = (name or "").strip()
        if not name:
            raise ValueError("请填写方案名称")
        pid = (pid or "").strip() or self._make_id(name)
        sell_tree = sell_tree or {}
        validate_trade_profile(buy_tree, sell_tree, backstop, known=self._known())
        bj = json.dumps(buy_tree, ensure_ascii=False)
        sj = json.dumps(sell_tree, ensure_ascii=False)
        kj = json.dumps(backstop or {}, ensure_ascii=False)
        cur = self.pg.query_df(
            f"SELECT version, name, buy_tree, sell_tree, backstop, created_at FROM trade_profile "
            f"WHERE id=%s AND {self._own}", [pid, *self._op])
        now = datetime.now()
        if not cur.empty:
            o = cur.iloc[0]
            if o["name"] == name and o["buy_tree"] == bj and o["sell_tree"] == sj and o["backstop"] == kj:
                return int(o["version"])
            version = int(o["version"]) + 1
            created = o["created_at"]
        else:
            version, created = 1, now
        self.pg.execute(
            "INSERT INTO trade_profile "
            "(id,tenant_id,owner_user_id,name,version,buy_tree,sell_tree,backstop,is_preset,created_at,updated_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (tenant_id, owner_user_id, id) DO UPDATE SET "
            "name=EXCLUDED.name, version=EXCLUDED.version, buy_tree=EXCLUDED.buy_tree, "
            "sell_tree=EXCLUDED.sell_tree, backstop=EXCLUDED.backstop, is_preset=EXCLUDED.is_preset, "
            "updated_at=EXCLUDED.updated_at",
            [pid, self.tenant_id, self.owner_user_id, name, version, bj, sj, kj, is_preset, created, now])
        self.pg.execute(
            "INSERT INTO trade_profile_version "
            "(id,tenant_id,owner_user_id,version,name,buy_tree,sell_tree,backstop,saved_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (tenant_id, owner_user_id, id, version) DO UPDATE SET "
            "name=EXCLUDED.name, buy_tree=EXCLUDED.buy_tree, sell_tree=EXCLUDED.sell_tree, "
            "backstop=EXCLUDED.backstop, saved_at=EXCLUDED.saved_at",
            [pid, self.tenant_id, self.owner_user_id, version, name, bj, sj, kj, now])
        return version

    def save_with_id(self, pid: str | None, name: str, buy_tree: dict, sell_tree: dict | None,
                     backstop: dict | None = None, is_preset: bool = False) -> tuple[str, int]:
        name = (name or "").strip()
        pid = (pid or "").strip() or self._make_id(name)
        version = self.save(pid, name, buy_tree, sell_tree, backstop, is_preset=is_preset)
        return pid, version

    def get(self, pid: str) -> dict | None:
        df = self.pg.query_df(
            f"SELECT * FROM trade_profile WHERE id=%s AND {self._own}", [pid, *self._op])
        if df.empty:
            return None
        r = self._row_to_profile(df.iloc[0].to_dict())
        for key in ("asset_ref", "profile_ref", "source", "readonly", "owner_label"):
            r.pop(key, None)
        return r

    def list(self) -> list[dict]:
        df = self.pg.query_df(
            f"SELECT id, name, version, is_preset FROM trade_profile WHERE {self._own} "
            f"ORDER BY is_preset DESC, id", self._op)
        return df.to_dict("records")

    def list_visible(self) -> list[dict]:
        df = self.pg.query_df(
            "SELECT id, tenant_id, owner_user_id, name, version, is_preset, visibility "
            "FROM trade_profile "
            f"WHERE {visible_sql()} "
            "ORDER BY "
            "CASE WHEN tenant_id=%s AND owner_user_id=%s THEN 0 "
            "WHEN is_preset IS TRUE THEN 1 "
            "WHEN visibility='tenant' THEN 2 ELSE 3 END, is_preset DESC, name, id",
            [
                *visible_params(tenant_id=self.tenant_id, owner_user_id=self.owner_user_id),
                self.tenant_id,
                self.owner_user_id,
            ],
        )
        return [self._decorate_summary(r) for r in df.to_dict("records")]

    def get_visible(self, profile_ref_or_id: str, *, include_owner: bool = False) -> dict | None:
        try:
            ref = resolve_asset_ref_or_legacy_id(
                profile_ref_or_id,
                asset_type=ASSET_TRADE_PROFILE,
                tenant_id=self.tenant_id,
                owner_user_id=self.owner_user_id,
            )
        except ValueError:
            return None
        df = self.pg.query_df(
            "SELECT * FROM trade_profile WHERE tenant_id=%s AND owner_user_id=%s AND id=%s",
            [ref.tenant_id, ref.owner_user_id, ref.asset_id],
        )
        if df.empty:
            return None
        row = df.iloc[0].to_dict()
        if not is_asset_visible(row, tenant_id=self.tenant_id, owner_user_id=self.owner_user_id):
            return None
        return self._row_to_profile(row, include_owner=include_owner)

    def set_visibility(
        self,
        profile_ref_or_id: str,
        visibility: str,
        published_by: str | None = None,
    ) -> dict | None:
        visibility = normalize_visibility(visibility)
        ref = resolve_asset_ref_or_legacy_id(
            profile_ref_or_id,
            asset_type=ASSET_TRADE_PROFILE,
            tenant_id=self.tenant_id,
            owner_user_id=self.owner_user_id,
        )
        if ref.tenant_id != self.tenant_id or ref.owner_user_id != self.owner_user_id:
            raise PermissionError("只能修改自己的买卖方案可见性")
        now = datetime.now() if visibility != VISIBILITY_PRIVATE else None
        affected = self.pg.execute(
            "UPDATE trade_profile SET visibility=%s, published_at=%s, published_by=%s, updated_at=%s "
            "WHERE tenant_id=%s AND owner_user_id=%s AND id=%s",
            [
                visibility,
                now,
                published_by if visibility != VISIBILITY_PRIVATE else None,
                datetime.now(),
                ref.tenant_id,
                ref.owner_user_id,
                ref.asset_id,
            ],
        )
        if affected == 0:
            return None
        return self.get_visible(profile_ref_or_id)

    def copy_visible(self, profile_ref_or_id: str, new_id: str, new_name: str | None = None) -> int:
        new_id = (new_id or "").strip()
        if not new_id:
            raise ValueError("目标方案 id 不能为空")
        src = self.get_visible(profile_ref_or_id, include_owner=True)
        if not src:
            raise ValueError("方案不存在")
        if self.get(new_id):
            raise ValueError("目标方案已存在，请改名后再复制")
        return self.save(
            new_id,
            new_name or f"{src['name']} 副本",
            src["buy_tree"],
            src["sell_tree"],
            src["backstop"],
        )

    def versions(self, pid: str) -> list[dict]:
        df = self.pg.query_df(
            f"SELECT version,name,buy_tree,sell_tree,backstop,saved_at FROM trade_profile_version "
            f"WHERE id=%s AND {self._own} ORDER BY version DESC", [pid, *self._op])
        out = []
        for r in df.to_dict("records"):
            r["buy_tree"] = json.loads(r["buy_tree"]) if r.get("buy_tree") else {}
            r["sell_tree"] = json.loads(r["sell_tree"]) if r.get("sell_tree") else {}
            r["backstop"] = json.loads(r["backstop"]) if r.get("backstop") else {}
            r["saved_at"] = str(r["saved_at"])
            out.append(r)
        return out

    def versions_visible(self, profile_ref_or_id: str) -> dict | None:
        prof = self.get_visible(profile_ref_or_id, include_owner=True)
        if not prof:
            return None
        df = self.pg.query_df(
            "SELECT version,name,buy_tree,sell_tree,backstop,saved_at FROM trade_profile_version "
            "WHERE id=%s AND tenant_id=%s AND owner_user_id=%s ORDER BY version DESC",
            [prof["id"], prof["tenant_id"], prof["owner_user_id"]],
        )
        out = []
        for r in df.to_dict("records"):
            r["buy_tree"] = json.loads(r["buy_tree"]) if r.get("buy_tree") else {}
            r["sell_tree"] = json.loads(r["sell_tree"]) if r.get("sell_tree") else {}
            r["backstop"] = json.loads(r["backstop"]) if r.get("backstop") else {}
            r["saved_at"] = str(r["saved_at"])
            out.append(r)
        return {"id": prof["id"], "profile_ref": prof["profile_ref"], "versions": out}

    def delete(self, pid: str) -> None:
        self.pg.execute(
            f"DELETE FROM trade_profile WHERE id=%s AND {self._own}", [pid, *self._op])
        self.pg.execute(
            f"DELETE FROM trade_profile_version WHERE id=%s AND {self._own}", [pid, *self._op])

    def seed_defaults(self) -> int:
        for p in DEFAULT_TRADE_PROFILES:
            self.save(p["id"], p["name"], p["buy_tree"], p["sell_tree"], p.get("backstop"), is_preset=True)
        log.info("内置买卖方案入库 %d 个", len(DEFAULT_TRADE_PROFILES))
        return len(DEFAULT_TRADE_PROFILES)
