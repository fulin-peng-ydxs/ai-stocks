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

import base64
import binascii
import json
from datetime import datetime

import pandas as pd

from backend.common.ids import prefixed_readable_id
from backend.common.logging import get_logger
from backend.config import get_settings
from backend.storage.duckdb_client import get_client
from backend.storage.pg_client import get_pg_client
from backend.auth.context import get_current_owner
from backend.storage.pg_ddl import PUBLIC_BOARD_OWNER

log = get_logger("scoring.score_profile")

VISIBILITY_PRIVATE = "private"
VISIBILITY_TENANT = "tenant"
VISIBILITY_PUBLIC = "public"
VISIBILITIES = {VISIBILITY_PRIVATE, VISIBILITY_TENANT, VISIBILITY_PUBLIC}
_PROFILE_REF_PREFIX = "spr_"

# 指标 key（含别名）→ 快照列；ma/hhv 走带参解析
_DIRECT_COLS = {
    "rs_pct", "dist_to_high_2y", "float_mv", "total_mv", "turnover_rate", "volume",
    "is_bull_arrange", "ma20_up", "ma60_up", "above_ma250",
    "is_vol_breakout", "is_platform_breakout", "is_turnover_healthy",
    "is_high_60", "is_high_120", "is_high_1y", "is_high_2y",
}
_ALIASES = {"bull_arrange": "is_bull_arrange", "dist_to_high": "dist_to_high_2y"}
_MA_PERIODS = {5, 10, 20, 60, 250}
_HHV_WINDOWS = {60, 120, 240, 480}


def resolve_indicator(indicator: str, params: dict, snap: pd.DataFrame) -> pd.Series:
    """把 (指标key, params) 解析为快照中的取值 Series。不支持则抛 ValueError。

    优先取快照中同名列（含已 attach 的表达式型/自定义指标列）；其次内置别名与 ma/hhv 带参映射。
    """
    key = _ALIASES.get(indicator, indicator)
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
        self.items = profile.get("items", [])
        g = profile.get("grade_thresholds") or {}
        gd = (settings or get_settings()).scoring.grade_thresholds
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
    if not items:
        raise ValueError("评分方案至少需要一个指标项")
    known_keys = known_keys or set()
    snap = pd.DataFrame(columns=list(_DIRECT_COLS) + [f"ma{n}" for n in _MA_PERIODS]
                        + [f"hhv{w}" for w in _HHV_WINDOWS])
    for it in items:
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
        payload = json.dumps([tenant_id, owner_user_id, profile_id], ensure_ascii=False, separators=(",", ":"))
        token = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")
        return _PROFILE_REF_PREFIX + token

    @staticmethod
    def parse_ref(profile_ref: str) -> tuple[str, str, str]:
        if not profile_ref.startswith(_PROFILE_REF_PREFIX):
            raise ValueError("不是有效的评分方案引用")
        raw = profile_ref[len(_PROFILE_REF_PREFIX):]
        raw += "=" * (-len(raw) % 4)
        try:
            data = json.loads(base64.urlsafe_b64decode(raw.encode("ascii")).decode("utf-8"))
        except (binascii.Error, UnicodeDecodeError, ValueError, TypeError) as e:
            raise ValueError("不是有效的评分方案引用") from e
        if (
            not isinstance(data, list)
            or len(data) != 3
            or not all(isinstance(x, str) and x for x in data)
        ):
            raise ValueError("不是有效的评分方案引用")
        return data[0], data[1], data[2]

    def _is_owner(self, tenant_id: str, owner_user_id: str) -> bool:
        return tenant_id == self.tenant_id and owner_user_id == self.owner_user_id

    def _is_visible_row(self, r: dict) -> bool:
        if self._is_owner(r["tenant_id"], r["owner_user_id"]):
            return True
        visibility = r.get("visibility") or VISIBILITY_PRIVATE
        if visibility == VISIBILITY_PUBLIC:
            return True
        return visibility == VISIBILITY_TENANT and r["tenant_id"] == self.tenant_id

    def _source(self, r: dict) -> str:
        if bool(r.get("is_preset")):
            return "preset"
        if self._is_owner(r["tenant_id"], r["owner_user_id"]):
            return "mine"
        return r.get("visibility") or VISIBILITY_PRIVATE

    def _decorate_summary(self, r: dict) -> dict:
        own = self._is_owner(r["tenant_id"], r["owner_user_id"])
        return {
            "profile_ref": self.make_ref(r["tenant_id"], r["owner_user_id"], r["id"]),
            "id": r["id"],
            "name": r["name"],
            "version": int(r["version"]),
            "is_preset": bool(r.get("is_preset")),
            "visibility": r.get("visibility") or VISIBILITY_PRIVATE,
            "source": self._source(r),
            "readonly": not own,
            "owner_label": "我" if own else r["owner_user_id"],
        }

    def _row_to_profile(self, r: dict, *, include_owner: bool = False) -> dict:
        own = self._is_owner(r["tenant_id"], r["owner_user_id"])
        out = {
            "profile_ref": self.make_ref(r["tenant_id"], r["owner_user_id"], r["id"]),
            "id": r["id"],
            "name": r["name"],
            "version": int(r["version"]),
            "items": json.loads(r["items"]) if r.get("items") else [],
            "grade_thresholds": json.loads(r["grade_thresholds"]) if r.get("grade_thresholds") else {},
            "is_preset": bool(r.get("is_preset")),
            "visibility": r.get("visibility") or VISIBILITY_PRIVATE,
            "source": self._source(r),
            "readonly": not own,
            "owner_label": "我" if own else r["owner_user_id"],
            "published_at": str(r["published_at"]) if r.get("published_at") else None,
            "published_by": r.get("published_by"),
        }
        if include_owner:
            out["tenant_id"] = r["tenant_id"]
            out["owner_user_id"] = r["owner_user_id"]
        return out

    def _make_id(self, name: str) -> str:
        base = prefixed_readable_id(name, prefix="score_")
        pid = base
        seq = 2
        while self.get(pid):
            pid = f"{base}_{seq}"
            seq += 1
        return pid

    def save(self, pid: str | None, name: str, items: list[dict],
             grade_thresholds: dict | None = None, is_preset: bool = False) -> int:
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
            f"SELECT version, name, items, grade_thresholds, created_at FROM score_profile "
            f"WHERE id=%s AND {self._own}", [pid, *self._op])
        now = datetime.now()
        if not cur.empty:
            old = cur.iloc[0]
            if old["name"] == name and old["items"] == items_json and old["grade_thresholds"] == gt_json:
                return int(old["version"])
            version = int(old["version"]) + 1
            created = old["created_at"]
        else:
            version, created = 1, now
        self.pg.execute(
            "INSERT INTO score_profile "
            "(id,tenant_id,owner_user_id,name,version,items,grade_thresholds,is_preset,visibility,"
            "published_at,published_by,created_at,updated_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (tenant_id, owner_user_id, id) DO UPDATE SET "
            "name=EXCLUDED.name, version=EXCLUDED.version, items=EXCLUDED.items, "
            "grade_thresholds=EXCLUDED.grade_thresholds, is_preset=EXCLUDED.is_preset, updated_at=EXCLUDED.updated_at",
            [
                pid, self.tenant_id, self.owner_user_id, name, version, items_json, gt_json,
                is_preset,
                VISIBILITY_PUBLIC if is_preset and (self.tenant_id, self.owner_user_id) == PUBLIC_BOARD_OWNER else VISIBILITY_PRIVATE,
                now if is_preset and (self.tenant_id, self.owner_user_id) == PUBLIC_BOARD_OWNER else None,
                self.owner_user_id if is_preset and (self.tenant_id, self.owner_user_id) == PUBLIC_BOARD_OWNER else None,
                created, now,
            ],
        )
        self.pg.execute(
            "INSERT INTO score_profile_version "
            "(id,tenant_id,owner_user_id,version,name,items,grade_thresholds,saved_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (tenant_id, owner_user_id, id, version) DO UPDATE SET "
            "name=EXCLUDED.name, items=EXCLUDED.items, grade_thresholds=EXCLUDED.grade_thresholds, saved_at=EXCLUDED.saved_at",
            [pid, self.tenant_id, self.owner_user_id, version, name, items_json, gt_json, now],
        )
        return version

    def save_with_id(self, pid: str | None, name: str, items: list[dict],
                     grade_thresholds: dict | None = None, is_preset: bool = False) -> tuple[str, int]:
        name = (name or "").strip()
        pid = (pid or "").strip() or self._make_id(name)
        version = self.save(pid, name, items, grade_thresholds, is_preset=is_preset)
        return pid, version

    def get(self, pid: str) -> dict | None:
        df = self.pg.query_df(
            f"SELECT * FROM score_profile WHERE id=%s AND {self._own}", [pid, *self._op])
        if df.empty:
            return None
        r = self._row_to_profile(df.iloc[0].to_dict())
        r.pop("profile_ref", None)
        r.pop("source", None)
        r.pop("readonly", None)
        r.pop("owner_label", None)
        return r

    def list(self) -> list[dict]:
        df = self.pg.query_df(
            f"SELECT id, name, version, is_preset FROM score_profile WHERE {self._own} "
            f"ORDER BY is_preset DESC, id", self._op)
        return df.to_dict("records")

    def list_visible(self) -> list[dict]:
        df = self.pg.query_df(
            "SELECT id, tenant_id, owner_user_id, name, version, is_preset, visibility "
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

    def get_visible(self, profile_ref_or_id: str, *, include_owner: bool = False) -> dict | None:
        try:
            tenant_id, owner_user_id, pid = self.parse_ref(profile_ref_or_id)
        except ValueError:
            tenant_id, owner_user_id, pid = self.tenant_id, self.owner_user_id, profile_ref_or_id
        df = self.pg.query_df(
            "SELECT * FROM score_profile WHERE tenant_id=%s AND owner_user_id=%s AND id=%s",
            [tenant_id, owner_user_id, pid],
        )
        if df.empty:
            return None
        row = df.iloc[0].to_dict()
        if not self._is_visible_row(row):
            return None
        return self._row_to_profile(row, include_owner=include_owner)

    def set_visibility(self, profile_ref_or_id: str, visibility: str, published_by: str | None = None) -> dict | None:
        if visibility not in VISIBILITIES:
            raise ValueError("visibility 必须是 private、tenant 或 public")
        try:
            tenant_id, owner_user_id, pid = self.parse_ref(profile_ref_or_id)
        except ValueError:
            tenant_id, owner_user_id, pid = self.tenant_id, self.owner_user_id, profile_ref_or_id
        if not self._is_owner(tenant_id, owner_user_id):
            raise PermissionError("只能修改自己的评分方案可见性")
        now = datetime.now() if visibility != VISIBILITY_PRIVATE else None
        self.pg.execute(
            "UPDATE score_profile SET visibility=%s, published_at=%s, published_by=%s, updated_at=%s "
            "WHERE tenant_id=%s AND owner_user_id=%s AND id=%s",
            [
                visibility, now, published_by if visibility != VISIBILITY_PRIVATE else None,
                datetime.now(), tenant_id, owner_user_id, pid,
            ],
        )
        return self.get_visible(self.make_ref(tenant_id, owner_user_id, pid))

    def copy_visible(self, profile_ref_or_id: str, new_id: str, new_name: str | None = None) -> int:
        src = self.get_visible(profile_ref_or_id, include_owner=True)
        if not src:
            raise ValueError("方案不存在")
        if self.get(new_id):
            raise ValueError("目标方案已存在，请改名后再复制")
        return self.save(new_id, new_name or f"{src['name']} 副本", src["items"], src["grade_thresholds"])

    def versions(self, pid: str) -> list[dict]:
        df = self.pg.query_df(
            f"SELECT version, name, items, grade_thresholds, saved_at FROM score_profile_version "
            f"WHERE id=%s AND {self._own} ORDER BY version DESC", [pid, *self._op])
        out = []
        for r in df.to_dict("records"):
            r["items"] = json.loads(r["items"])
            r["grade_thresholds"] = json.loads(r["grade_thresholds"]) if r.get("grade_thresholds") else {}
            r["saved_at"] = str(r["saved_at"])
            out.append(r)
        return out

    def versions_visible(self, profile_ref_or_id: str) -> dict | None:
        prof = self.get_visible(profile_ref_or_id, include_owner=True)
        if not prof:
            return None
        df = self.pg.query_df(
            "SELECT version, name, items, grade_thresholds, saved_at FROM score_profile_version "
            "WHERE id=%s AND tenant_id=%s AND owner_user_id=%s ORDER BY version DESC",
            [prof["id"], prof["tenant_id"], prof["owner_user_id"]],
        )
        out = []
        for r in df.to_dict("records"):
            r["items"] = json.loads(r["items"])
            r["grade_thresholds"] = json.loads(r["grade_thresholds"]) if r.get("grade_thresholds") else {}
            r["saved_at"] = str(r["saved_at"])
            out.append(r)
        return {"id": prof["id"], "profile_ref": prof["profile_ref"], "versions": out}

    def delete(self, pid: str) -> None:
        self.pg.execute(
            f"DELETE FROM score_profile WHERE id=%s AND {self._own}", [pid, *self._op])
        self.pg.execute(
            f"DELETE FROM score_profile_version WHERE id=%s AND {self._own}", [pid, *self._op])

    def seed_defaults(self) -> int:
        for p in DEFAULT_SCORE_PROFILES:
            self.save(p["id"], p["name"], p["items"], p.get("grade_thresholds"), is_preset=True)
        log.info("内置评分方案入库 %d 个", len(DEFAULT_SCORE_PROFILES))
        return len(DEFAULT_SCORE_PROFILES)
