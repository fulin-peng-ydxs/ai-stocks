"""评分规则方案（v2.0 §7，决策 D3）——阈值打分 + 动态权重，可存方案。

模型：用户挑若干技术指标，每个指标独立产出 0~100「达标分」，按权重百分比加权求和。
  - bool   ：满足=100 / 否=0
  - band   ：分段阈值 [[lo,hi,score],...]，值落在哪段给哪分（末段含右端）
  - linear ：在 [min,max] 间线性映射到 [0,100]（min→0、max→100；min>max 即"越小越高"）
权重总和=100%（不足/超出自动按和归一）。综合分 = Σ(达标分 × 权重)。

指标取值来自 wide_snapshot 的列（动态计算）。本期支持映射到现有快照列的指标；
动态传参指标（ma/hhv）按周期映射到对应列。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

import pandas as pd

from backend.auth.context import get_current_owner
from backend.common.ids import uuid_hex_id
from backend.common.logging import get_logger
from backend.config import get_effective_settings
from backend.services.asset_visibility import (
    ASSET_SCORE_PROFILE,
    SCOPE_MINE,
    asset_visibility_locks,
    decorate_asset_row,
    downgrade_backtest_runs_referencing,
    is_asset_visible,
    make_asset_ref,
    normalize_visibility,
    parse_asset_ref,
    publish_platform_presets,
    reconcile_backtest_runs_for_profile_visibility,
    referencing_backtest_runs_by_others,
    resolve_asset_ref_or_legacy_id,
    scoped_query,
    summarize_asset_row,
)
from backend.storage.duckdb_client import get_client
from backend.storage.pg_client import get_pg_client
from backend.storage.pg_ddl import PUBLIC_BOARD_OWNER

log = get_logger("scoring.score_profile")

VISIBILITY_PRIVATE = "private"
VISIBILITY_TENANT = "tenant"
VISIBILITY_PUBLIC = "public"
VISIBILITIES = {VISIBILITY_PRIVATE, VISIBILITY_TENANT, VISIBILITY_PUBLIC}

# 指标 key（含别名）→ 快照列；ma/hhv 走带参解析
_DIRECT_COLS = {
    "rs_pct", "dist_to_high_2y", "close", "float_mv", "total_mv", "float_share",
    "total_share", "turnover_rate", "volume",
    "is_bull_arrange", "ma20_up", "ma60_up", "above_ma250",
    "is_vol_breakout", "is_platform_breakout", "is_turnover_healthy",
    "is_high_60", "is_high_120", "is_high_1y", "is_high_2y",
}
_ALIASES = {"bull_arrange": "is_bull_arrange", "dist_to_high": "dist_to_high_2y"}
_MA_PERIODS = {5, 10, 20, 30, 60, 250}
_HHV_WINDOWS = {60, 120, 240, 480}


def active_score_items(items: list[dict] | None) -> list[dict]:
    """返回参与计算的评分项；旧方案无 enabled 字段时保持启用。"""
    return [item for item in (items or []) if item.get("enabled", True) is not False]


def indicator_value_column(indicator: str, params: dict | None) -> str:
    """返回参数化指标在临时快照中的稳定列名，避免同 key 不同参数互相覆盖。"""
    from backend.indicators.registry import normalize_indicator_reference

    indicator, params, _ = normalize_indicator_reference(indicator, params)
    blob = json.dumps(params, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    suffix = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]
    return f"__indicator_{indicator}_{suffix}"


def resolve_indicator(indicator: str, params: dict, snap: pd.DataFrame) -> pd.Series:
    """把 (指标key, params) 解析为快照中的取值 Series。不支持则抛 ValueError。

    优先取快照中同名列（含已 attach 的表达式型/自定义指标列）；其次内置别名与 ma/hhv 带参映射。
    """
    from backend.indicators.registry import normalize_indicator_reference

    requested_key = indicator
    indicator, params, preset_key = normalize_indicator_reference(indicator, params)
    parameterized = indicator_value_column(indicator, params)
    if parameterized in snap.columns:
        return snap[parameterized]
    # 预设的逻辑语义来自 parent_key + preset_params；存在等价快列时只优化物理执行。
    if preset_key and preset_key in snap.columns:
        return snap[preset_key]
    key = _ALIASES.get(indicator, indicator)
    if requested_key in snap.columns:      # 未治理的历史表达式兼容列
        return snap[requested_key]
    if indicator in snap.columns:          # 表达式型/自定义指标（已 attach，列名=key）
        return snap[indicator]
    if key in snap.columns:                # 内置直出列 / 别名列
        return snap[key]
    if key == "ma":
        n = int((params or {}).get("period", 20))
        if n not in _MA_PERIODS:
            raise ValueError(f"ma 周期暂仅支持 {sorted(_MA_PERIODS)}（动态任意周期在 M2.4 支持）")
        key = f"ma{n}"
    elif key == "hhv":
        w = int((params or {}).get("window", 480))
        if w not in _HHV_WINDOWS:
            raise ValueError(f"hhv 窗口暂仅支持 {sorted(_HHV_WINDOWS)}（动态任意窗口在 M2.4 支持）")
        key = f"hhv{w}"
    elif key not in _DIRECT_COLS:
        raise ValueError(f"指标 {indicator} 暂不支持作为评分项")
    if key not in snap.columns:
        raise ValueError(f"快照缺少列: {key}")
    return snap[key]


def score_one(val: pd.Series, scoring: dict) -> pd.Series:
    """单指标 → 0~100 达标分（向量化，NaN→0）。"""
    t = (scoring or {}).get("type", "bool")
    if t == "bool":
        return (val.astype("boolean").fillna(False).astype(float) * 100.0)
    v = pd.to_numeric(val, errors="coerce")
    if t == "band":
        out = pd.Series(0.0, index=val.index)
        bands = scoring.get("bands", [])
        for i, b in enumerate(bands):
            lo, hi, sc = float(b[0]), float(b[1]), float(b[2])
            m = (v >= lo) & ((v <= hi) if i == len(bands) - 1 else (v < hi))
            out = out.where(~m.fillna(False), sc)
        return out
    if t == "linear":
        lo, hi = float(scoring["min"]), float(scoring["max"])
        if hi == lo:
            return pd.Series(0.0, index=val.index)
        s = ((v - lo) / (hi - lo)).clip(0, 1) * 100.0
        return s.fillna(0.0)
    raise ValueError(f"未知打分方式: {t}")


class ScoreProfileModel:
    """按评分方案对截面快照打分。接口对齐 ScoreModel.score(snap)→DataFrame。"""

    def __init__(self, profile: dict, settings=None):
        self.profile = profile
        self.items = active_score_items(profile.get("items", []))
        g = profile.get("grade_thresholds") or {}
        gd = (settings or get_effective_settings()).scoring.grade_thresholds
        self.grades = {
            "watch": float(g.get("watch", gd.watch)),
            "leader": float(g.get("leader", gd.leader)),
            "core": float(g.get("core", gd.core)),
        }

    def score(self, snap: pd.DataFrame) -> pd.DataFrame:
        if snap.empty or not self.items:
            return pd.DataFrame({"total_score": []})
        total_w = sum(float(it.get("weight", 0)) for it in self.items) or 1.0
        total = pd.Series(0.0, index=snap.index)
        subs: dict[str, pd.Series] = {}
        for it in self.items:
            w = float(it.get("weight", 0))
            val = resolve_indicator(it["indicator"], it.get("params"), snap)
            s = score_one(val, it.get("scoring"))
            subs[it["indicator"]] = s.round(2)
            total = total + s * w
        total_score = (total / total_w).round(2)
        out = pd.DataFrame({"total_score": total_score}, index=snap.index)
        for k, s in subs.items():
            out[k] = s
        out["grade"] = self._grade(total_score)
        return out

    def _grade(self, score: pd.Series) -> pd.Series:
        g = pd.Series("", index=score.index, dtype=object)
        g[score >= self.grades["watch"]] = "观察"
        g[score >= self.grades["leader"]] = "龙头候选"
        g[score >= self.grades["core"]] = "主升浪核心"
        return g


# ── 默认内置评分方案（阈值打分示例，覆盖主要维度）────────────────
DEFAULT_SCORE_PROFILES: list[dict] = [
    {
        "id": "default",
        "name": "默认趋势分",
        "include_st": True,
        "grade_thresholds": {"watch": 80, "leader": 90, "core": 95},
        "items": [
            {"indicator": "dist_to_high_2y", "params": {}, "weight": 0.30,
             "scoring": {"type": "linear", "min": 0.50, "max": 0.0}},
            {"indicator": "bull_arrange", "params": {}, "weight": 0.20,
             "scoring": {"type": "bool"}},
            {"indicator": "is_vol_breakout", "params": {}, "weight": 0.20,
             "scoring": {"type": "bool"}},
            {"indicator": "is_turnover_healthy", "params": {}, "weight": 0.10,
             "scoring": {"type": "bool"}},
            {"indicator": "rs_pct", "params": {}, "weight": 0.20,
             "scoring": {"type": "linear", "min": 0.0, "max": 100.0}},
        ],
    },
]


def validate_profile(items: list[dict], known_keys: set[str] | None = None) -> None:
    """校验评分项合法性（指标可解析或为已知自定义指标、打分方式合法、权重为正）。"""
    active_items = active_score_items(items)
    if not active_items:
        raise ValueError("评分方案至少需要一个已启用的指标项")
    known_keys = known_keys or set()
    snap = pd.DataFrame(columns=list(_DIRECT_COLS) + [f"ma{n}" for n in _MA_PERIODS]
                        + [f"hhv{w}" for w in _HHV_WINDOWS])
    for it in items:
        if "enabled" in it and not isinstance(it["enabled"], bool):
            raise ValueError("评分项 enabled 须为布尔值")
        if "indicator" not in it:
            raise ValueError("评分项缺少 indicator")
        if float(it.get("weight", 0)) <= 0:
            raise ValueError(f"指标 {it['indicator']} 权重须为正")
        if it["indicator"] not in known_keys:  # 已注册的自定义/表达式指标跳过列解析校验
            resolve_indicator(it["indicator"], it.get("params"), snap)
        sc = it.get("scoring") or {}
        if sc.get("type") not in ("bool", "band", "linear"):
            raise ValueError(f"指标 {it['indicator']} 打分方式非法")


class ScoreProfileRepo:
    """评分方案存取（score_profile，用户资产→PG）。

    混合持久层：方案/版本走 PG（self.pg，%s + 归属过滤）；指标定义 indicator_def 仍在
    DuckDB，经 IndicatorDefRepo(self.mkt) 读取。第一位保留为 market 以兼容历史 Repo(c) 调用。
    """

    def __init__(self, market=None, pg=None, *, tenant_id: str | None = None,
                 owner_user_id: str | None = None):
        self.mkt = market or get_client()           # 行情/指标定义库（DuckDB）
        self.pg = pg or get_pg_client()             # 资产库（PG）
        _ctx_t, _ctx_o = get_current_owner()
        self.tenant_id = tenant_id or _ctx_t
        self.owner_user_id = owner_user_id or _ctx_o

    @property
    def _own(self) -> str:
        return "tenant_id=%s AND owner_user_id=%s"

    @property
    def _op(self) -> list:
        return [self.tenant_id, self.owner_user_id]

    @staticmethod
    def make_ref(tenant_id: str, owner_user_id: str, profile_id: str) -> str:
        return make_asset_ref(ASSET_SCORE_PROFILE, tenant_id, owner_user_id, profile_id)

    @staticmethod
    def parse_ref(profile_ref: str) -> tuple[str, str, str]:
        ref = parse_asset_ref(profile_ref, expected_type=ASSET_SCORE_PROFILE)
        return ref.tenant_id, ref.owner_user_id, ref.asset_id

    def _decorate_summary(self, r: dict) -> dict:
        return summarize_asset_row(
            r,
            asset_type=ASSET_SCORE_PROFILE,
            tenant_id=self.tenant_id,
            owner_user_id=self.owner_user_id,
        )

    def _row_to_profile(self, r: dict, *, include_owner: bool = False) -> dict:
        out = decorate_asset_row(
            r,
            asset_type=ASSET_SCORE_PROFILE,
            tenant_id=self.tenant_id,
            owner_user_id=self.owner_user_id,
            include_owner=include_owner,
            ref_key="profile_ref",
        )
        out["version"] = int(out["version"])
        out["is_preset"] = bool(out.get("is_preset"))
        out["include_st"] = bool(out.get("include_st", True))
        out["items"] = json.loads(out["items"]) if out.get("items") else []
        out["grade_thresholds"] = json.loads(out["grade_thresholds"]) if out.get("grade_thresholds") else {}
        out["published_at"] = str(out["published_at"]) if out.get("published_at") else None
        return out

    def _make_id(self, name: str) -> str:
        """生成与方案名称无关的内部身份；name 参数保留以稳定私有调用接口。"""
        del name
        return uuid_hex_id()

    def save(self, pid: str | None, name: str, items: list[dict],
             grade_thresholds: dict | None = None, is_preset: bool = False,
             include_st: bool = True) -> int:
        from backend.indicators.definition import IndicatorDefRepo
        name = (name or "").strip()
        if not name:
            raise ValueError("请填写方案名称")
        pid = (pid or "").strip() or self._make_id(name)
        known = {d["key"] for d in IndicatorDefRepo(self.mkt).list()}
        validate_profile(items, known_keys=known)
        items_json = json.dumps(items, ensure_ascii=False)
        gt_json = json.dumps(grade_thresholds or {}, ensure_ascii=False)
        cur = self.pg.query_df(
            f"SELECT version, name, items, grade_thresholds, include_st, created_at FROM score_profile "
            f"WHERE id=%s AND {self._own}", [pid, *self._op])
        now = datetime.now()
        if not cur.empty:
            old = cur.iloc[0]
            if (
                old["name"] == name
                and old["items"] == items_json
                and old["grade_thresholds"] == gt_json
                and bool(old["include_st"]) == bool(include_st)
            ):
                return int(old["version"])
            version = int(old["version"]) + 1
            created = old["created_at"]
        else:
            version, created = 1, now
        self.pg.execute(
            "INSERT INTO score_profile "
            "(id,tenant_id,owner_user_id,name,version,items,grade_thresholds,include_st,is_preset,visibility,"
            "published_at,published_by,created_at,updated_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (tenant_id, owner_user_id, id) DO UPDATE SET "
            "name=EXCLUDED.name, version=EXCLUDED.version, items=EXCLUDED.items, "
            "grade_thresholds=EXCLUDED.grade_thresholds, include_st=EXCLUDED.include_st, "
            "is_preset=EXCLUDED.is_preset, updated_at=EXCLUDED.updated_at",
            [
                pid, self.tenant_id, self.owner_user_id, name, version, items_json, gt_json,
                bool(include_st),
                is_preset,
                VISIBILITY_PUBLIC if is_preset and (self.tenant_id, self.owner_user_id) == PUBLIC_BOARD_OWNER else VISIBILITY_PRIVATE,
                now if is_preset and (self.tenant_id, self.owner_user_id) == PUBLIC_BOARD_OWNER else None,
                self.owner_user_id if is_preset and (self.tenant_id, self.owner_user_id) == PUBLIC_BOARD_OWNER else None,
                created, now,
            ],
        )
        self.pg.execute(
            "INSERT INTO score_profile_version "
            "(id,tenant_id,owner_user_id,version,name,items,grade_thresholds,include_st,saved_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (tenant_id, owner_user_id, id, version) DO UPDATE SET "
            "name=EXCLUDED.name, items=EXCLUDED.items, grade_thresholds=EXCLUDED.grade_thresholds, "
            "include_st=EXCLUDED.include_st, saved_at=EXCLUDED.saved_at",
            [pid, self.tenant_id, self.owner_user_id, version, name, items_json, gt_json,
             bool(include_st), now],
        )
        return version

    def save_with_id(self, pid: str | None, name: str, items: list[dict],
                     grade_thresholds: dict | None = None, is_preset: bool = False,
                     include_st: bool = True) -> tuple[str, int]:
        name = (name or "").strip()
        pid = (pid or "").strip() or self._make_id(name)
        version = self.save(
            pid, name, items, grade_thresholds, is_preset=is_preset, include_st=include_st
        )
        return pid, version

    def get(self, pid: str) -> dict | None:
        df = self.pg.query_df(
            f"SELECT * FROM score_profile WHERE id=%s AND {self._own}", [pid, *self._op])
        if df.empty:
            return None
        r = self._row_to_profile(df.iloc[0].to_dict())
        for key in ("asset_ref", "profile_ref", "source", "readonly", "owner_label"):
            r.pop(key, None)
        return r

    def list(self) -> list[dict]:
        df = self.pg.query_df(
            f"SELECT id, name, version, is_preset, include_st FROM score_profile WHERE {self._own} "
            f"ORDER BY is_preset DESC, id", self._op)
        return df.to_dict("records")

    def list_visible(self) -> list[dict]:
        df = self.pg.query_df(
            "SELECT id, tenant_id, owner_user_id, name, version, is_preset, visibility, include_st "
            "FROM score_profile "
            "WHERE (tenant_id=%s AND owner_user_id=%s) "
            "OR visibility='public' OR (visibility='tenant' AND tenant_id=%s) "
            "ORDER BY "
            "CASE WHEN tenant_id=%s AND owner_user_id=%s THEN 0 "
            "WHEN tenant_id=%s AND owner_user_id=%s AND is_preset IS TRUE THEN 1 "
            "WHEN visibility='tenant' THEN 2 ELSE 3 END, is_preset DESC, name, id",
            [
                self.tenant_id, self.owner_user_id, self.tenant_id,
                self.tenant_id, self.owner_user_id,
                *PUBLIC_BOARD_OWNER,
            ],
        )
        return [self._decorate_summary(r) for r in df.to_dict("records")]

    def list_mine(self) -> list[dict]:
        """下拉专用：只加载「自己的资产」（纯 owner），不含他人公开与平台槽系统内置段；
        平台槽账号下也剔除全部系统预设，包括尚未完成公开校准的历史数据（R3/C2）。"""
        rows, _ = scoped_query(
            self.pg,
            table="score_profile",
            source=SCOPE_MINE,
            tenant_id=self.tenant_id,
            owner_user_id=self.owner_user_id,
            public_board_owner=PUBLIC_BOARD_OWNER,
        )
        return [self._decorate_summary(r) for r in rows]

    def browse(self, source: str, q: str | None = None, page: int = 1, page_size: int = 20) -> dict:
        """搜索弹窗浏览：preset（系统内置严格公开）/ tenant / public（强制补集），关键字 + 分页（R5/R14）。"""
        if source not in ("preset", "tenant", "public"):
            raise ValueError("browse 仅支持 preset/tenant/public 来源")
        page = max(1, int(page))
        page_size = max(1, min(int(page_size), 100))
        rows, total = scoped_query(
            self.pg,
            table="score_profile",
            source=source,
            tenant_id=self.tenant_id,
            owner_user_id=self.owner_user_id,
            public_board_owner=PUBLIC_BOARD_OWNER,
            q=q,
            page=page,
            page_size=page_size,
        )
        return {
            "items": [self._decorate_summary(r) for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "source": source,
        }

    def get_visible(self, profile_ref_or_id: str, *, include_owner: bool = False) -> dict | None:
        try:
            ref = resolve_asset_ref_or_legacy_id(
                profile_ref_or_id,
                asset_type=ASSET_SCORE_PROFILE,
                tenant_id=self.tenant_id,
                owner_user_id=self.owner_user_id,
            )
        except ValueError:
            return None
        df = self.pg.query_df(
            "SELECT * FROM score_profile WHERE tenant_id=%s AND owner_user_id=%s AND id=%s",
            [ref.tenant_id, ref.owner_user_id, ref.asset_id],
        )
        if df.empty:
            return None
        row = df.iloc[0].to_dict()
        if not is_asset_visible(row, tenant_id=self.tenant_id, owner_user_id=self.owner_user_id):
            return None
        return self._row_to_profile(row, include_owner=include_owner)

    def set_visibility(self, profile_ref_or_id: str, visibility: str, published_by: str | None = None) -> dict | None:
        visibility = normalize_visibility(visibility)
        ref = resolve_asset_ref_or_legacy_id(
            profile_ref_or_id,
            asset_type=ASSET_SCORE_PROFILE,
            tenant_id=self.tenant_id,
            owner_user_id=self.owner_user_id,
        )
        if ref.tenant_id != self.tenant_id or ref.owner_user_id != self.owner_user_id:
            raise PermissionError("只能修改自己的评分方案可见性")
        now = datetime.now() if visibility != VISIBILITY_PRIVATE else None
        with asset_visibility_locks(self.pg, [ref]), self.pg.transaction() as conn:
            with self.pg.cursor_in(conn) as cur:
                cur.execute(
                    "SELECT 1 FROM score_profile "
                    "WHERE tenant_id=%s AND owner_user_id=%s AND id=%s FOR UPDATE",
                    [ref.tenant_id, ref.owner_user_id, ref.asset_id],
                )
                if cur.fetchone() is None:
                    return None
            affected_runs = reconcile_backtest_runs_for_profile_visibility(
                self.pg, asset_type=ASSET_SCORE_PROFILE, ref=ref.asset_id,
                tenant_id=self.tenant_id, owner_user_id=self.owner_user_id,
                target_visibility=visibility, conn=conn,
            )
            with self.pg.cursor_in(conn) as cur:
                cur.execute(
                    "UPDATE score_profile SET visibility=%s, published_at=%s, "
                    "published_by=%s, updated_at=%s "
                    "WHERE tenant_id=%s AND owner_user_id=%s AND id=%s",
                    [visibility, now, published_by if visibility != VISIBILITY_PRIVATE else None,
                     datetime.now(), ref.tenant_id, ref.owner_user_id, ref.asset_id],
                )
        result = self.get_visible(profile_ref_or_id)
        if result is not None:
            result["affected_run_count"] = affected_runs
        return result

    def _insert_copy(self, new_id: str, name: str, items: list[dict],
                     grade_thresholds: dict | None, include_st: bool) -> bool:
        """原子插入一条全新 private 副本（version=1）；id 已存在则不写并返回 False，交上层换 id 重试。

        主表 + 版本表在**同一事务同一游标**内写入：主表 `ON CONFLICT DO NOTHING` 0 行即撞库
        （换 id 重试）；版本表失败则整体回滚，杜绝半成品。副本恒为 private，不带发布字段。"""
        now = datetime.now()
        items_json = json.dumps(items, ensure_ascii=False)
        gt_json = json.dumps(grade_thresholds or {}, ensure_ascii=False)
        with self.pg.transaction() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO score_profile "
                "(id,tenant_id,owner_user_id,name,version,items,grade_thresholds,include_st,is_preset,visibility,"
                "published_at,published_by,created_at,updated_at) "
                "VALUES (%s,%s,%s,%s,1,%s,%s,%s,false,'private',NULL,NULL,%s,%s) "
                "ON CONFLICT (tenant_id, owner_user_id, id) DO NOTHING",
                [new_id, self.tenant_id, self.owner_user_id, name, items_json, gt_json,
                 bool(include_st), now, now],
            )
            if cur.rowcount == 0:
                return False
            # 版本表用普通 INSERT（不 DO NOTHING）：孤儿版本冲突即抛错、整个事务回滚，
            # 不静默吞成「主表新、版本旧」的不一致。
            cur.execute(
                "INSERT INTO score_profile_version "
                "(id,tenant_id,owner_user_id,version,name,items,grade_thresholds,include_st,saved_at) "
                "VALUES (%s,%s,%s,1,%s,%s,%s,%s,%s)",
                [new_id, self.tenant_id, self.owner_user_id, name, items_json, gt_json,
                 bool(include_st), now],
            )
        return True

    def copy_visible(
        self,
        profile_ref_or_id: str,
        new_name: str | None = None,
        version: int | None = None,
    ) -> dict:
        """复制可见方案为「我的」private（C8）：后端生成唯一 id、名称默认「原名 副本」，
        撞库/并发有限次重试；仅真正插入成功才返回新 id/profile_ref/name/version。"""
        src = self.get_visible(profile_ref_or_id, include_owner=True)
        if not src:
            raise ValueError("方案不存在")
        if version is not None:
            version = int(version)
            if version <= 0:
                raise ValueError("版本号必须大于 0")
            snap = self.pg.query_df(
                "SELECT name, items, grade_thresholds, include_st FROM score_profile_version "
                "WHERE id=%s AND tenant_id=%s AND owner_user_id=%s AND version=%s",
                [src["id"], src["tenant_id"], src["owner_user_id"], version],
            )
            if snap.empty:
                raise ValueError(f"方案版本不存在: v{version}")
            row = snap.iloc[0].to_dict()
            src = {
                **src,
                "name": row["name"],
                "items": json.loads(row["items"]),
                "grade_thresholds": (
                    json.loads(row["grade_thresholds"]) if row.get("grade_thresholds") else {}
                ),
                "include_st": bool(row.get("include_st", True)),
            }
        base_name = (new_name or "").strip() or f"{src['name']} 副本"
        for _ in range(5):
            new_id = self._make_id(base_name)
            if self._insert_copy(
                new_id, base_name, src["items"], src["grade_thresholds"],
                bool(src.get("include_st", True)),
            ):
                return {
                    "id": new_id,
                    "profile_ref": self.make_ref(self.tenant_id, self.owner_user_id, new_id),
                    "name": base_name,
                    "version": 1,
                    "include_st": bool(src.get("include_st", True)),
                    "source_version": version,
                }
        raise ValueError("复制失败：目标 id 冲突，请重试")

    def versions(self, pid: str) -> list[dict]:
        df = self.pg.query_df(
            f"SELECT version, name, items, grade_thresholds, include_st, saved_at FROM score_profile_version "
            f"WHERE id=%s AND {self._own} ORDER BY version DESC", [pid, *self._op])
        out = []
        for r in df.to_dict("records"):
            r["items"] = json.loads(r["items"])
            r["grade_thresholds"] = json.loads(r["grade_thresholds"]) if r.get("grade_thresholds") else {}
            r["include_st"] = bool(r.get("include_st", True))
            r["saved_at"] = str(r["saved_at"])
            out.append(r)
        return out

    def versions_visible(self, profile_ref_or_id: str) -> dict | None:
        prof = self.get_visible(profile_ref_or_id, include_owner=True)
        if not prof:
            return None
        df = self.pg.query_df(
            "SELECT version, name, items, grade_thresholds, include_st, saved_at FROM score_profile_version "
            "WHERE id=%s AND tenant_id=%s AND owner_user_id=%s ORDER BY version DESC",
            [prof["id"], prof["tenant_id"], prof["owner_user_id"]],
        )
        out = []
        for r in df.to_dict("records"):
            r["items"] = json.loads(r["items"])
            r["grade_thresholds"] = json.loads(r["grade_thresholds"]) if r.get("grade_thresholds") else {}
            r["include_st"] = bool(r.get("include_st", True))
            r["saved_at"] = str(r["saved_at"])
            out.append(r)
        return {"id": prof["id"], "profile_ref": prof["profile_ref"], "versions": out}

    def delete(self, pid: str) -> None:
        """删除方案及其版本历史（PG，按归属）。

        单事务原子执行（评审 P2）：① 本人引用检查**恒执行**（无论是否他人引用，防悬空引用指向
        已删 profile）；② 存在他人引用时级联降级其公开/租户 run 为 private（逃生口，跳过
        "先收回 private" 可见性限制——他人 run 不是 owner 的，owner 处置不了）；③ 删除主表+版本表。
        校验在事务外执行（直接抛 ValueError），数据变更在事务内原子提交，任一失败整体回滚。
        """
        # 校验（事务外，ValueError 原样抛给 API 层）：本人引用恒拦；无他人引用则须先收回 private
        self._assert_no_own_refs(pid)
        by_others = referencing_backtest_runs_by_others(
            self.pg, asset_type=ASSET_SCORE_PROFILE, ref=pid,
            tenant_id=self.tenant_id, owner_user_id=self.owner_user_id)
        if not by_others:
            self._assert_private(pid)
        # 数据变更（单事务原子）：级联降级他人 run（如有）→ 删除主表 + 版本表
        with self.pg.transaction() as conn:
            if by_others:
                downgrade_backtest_runs_referencing(
                    self.pg, asset_type=ASSET_SCORE_PROFILE, ref=pid,
                    tenant_id=self.tenant_id, owner_user_id=self.owner_user_id, conn=conn)
            with self.pg.cursor_in(conn) as cur:
                cur.execute(
                    f"DELETE FROM score_profile WHERE id=%s AND {self._own}", [pid, *self._op])
                cur.execute(
                    f"DELETE FROM score_profile_version WHERE id=%s AND {self._own}", [pid, *self._op])

    def _assert_private(self, pid: str, *, conn=None) -> None:
        """删除前拦截：公开/租户态方案须先收回 private（无他人引用时生效）。"""
        if conn is not None:
            with self.pg.cursor_in(conn) as cur:
                cur.execute(
                    f"SELECT visibility FROM score_profile WHERE id=%s AND {self._own}",
                    [pid, *self._op])
                r = cur.fetchone()
            vis = r[0] if r else None
        else:
            df = self.pg.query_df(
                f"SELECT visibility FROM score_profile WHERE id=%s AND {self._own}",
                [pid, *self._op])
            vis = df.iloc[0]["visibility"] if not df.empty else None
        if vis is None:
            return
        if normalize_visibility(vis) != VISIBILITY_PRIVATE:
            raise ValueError("请先将方案收回为私有再删除")

    def _assert_no_own_refs(self, pid: str, *, conn=None) -> None:
        """本人回测引用检查（恒执行，P1 防悬空）：本人引用须先删回测。

        本人引用（新 ref 形态 + 旧裸 id 存量）无论是否他人引用都拦，防止悬空引用指向已删 profile。
        他人引用不在此拦（opaque ref 编码真实归属，无法按 owner 过滤排除；由 delete 级联降级）。
        """
        ref = make_asset_ref(ASSET_SCORE_PROFILE, self.tenant_id, self.owner_user_id, pid)
        if conn is not None:
            with self.pg.cursor_in(conn) as cur:
                cur.execute(
                    "SELECT 1 FROM backtest_run WHERE (score_profile_id=%s OR score_profile_id=%s) "
                    "AND tenant_id=%s AND owner_user_id=%s LIMIT 1",
                    [ref, pid, self.tenant_id, self.owner_user_id])
                hit = cur.fetchone() is not None
        else:
            hit = not self.pg.query_df(
                "SELECT 1 FROM backtest_run WHERE (score_profile_id=%s OR score_profile_id=%s) "
                "AND tenant_id=%s AND owner_user_id=%s LIMIT 1",
                [ref, pid, self.tenant_id, self.owner_user_id]).empty
        if hit:
            raise ValueError("该方案仍被回测记录引用，无法删除，请先删除相关回测")

    def seed_defaults(self) -> int:
        for p in DEFAULT_SCORE_PROFILES:
            self.save(
                p["id"], p["name"], p["items"], p.get("grade_thresholds"),
                is_preset=True, include_st=bool(p.get("include_st", True)),
            )
        publish_platform_presets(
            self.pg,
            table="score_profile",
            preset_ids=[p["id"] for p in DEFAULT_SCORE_PROFILES],
            tenant_id=self.tenant_id,
            owner_user_id=self.owner_user_id,
            public_board_owner=PUBLIC_BOARD_OWNER,
        )
        log.info("内置评分方案入库 %d 个", len(DEFAULT_SCORE_PROFILES))
        return len(DEFAULT_SCORE_PROFILES)
