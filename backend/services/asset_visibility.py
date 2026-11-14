"""用户资产可见性通用规则。

阶段六 T5 只沉淀三类后续资产（筛选方案、买卖方案、回测记录）的共享 helper；
具体仓库/API 接入在 T6-T8 完成。
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import psycopg

VISIBILITY_PRIVATE = "private"
VISIBILITY_TENANT = "tenant"
VISIBILITY_PUBLIC = "public"
VISIBILITIES = frozenset({VISIBILITY_PRIVATE, VISIBILITY_TENANT, VISIBILITY_PUBLIC})

ASSET_SCORE_PROFILE = "score_profile"
ASSET_SCREEN_PROFILE = "screen_profile"
ASSET_TRADE_PROFILE = "trade_profile"
ASSET_BACKTEST_RUN = "backtest_run"
ASSET_TYPES = frozenset(
    {ASSET_SCORE_PROFILE, ASSET_SCREEN_PROFILE, ASSET_TRADE_PROFILE, ASSET_BACKTEST_RUN}
)

ASSET_REF_PREFIX = "avr_"

# 旧版资产引用前缀过渡兼容:阶段四 B 的评分方案曾用独立前缀 + 3 元 payload(无 asset_type)。
# ref 不入库、仅前端会话内临时持有,这里保留解析兼容,避免部署瞬间旧 ref 失效。
LEGACY_REF_PREFIXES = {"spr_": ASSET_SCORE_PROFILE}


@dataclass(frozen=True)
class AssetRef:
    asset_type: str
    tenant_id: str
    owner_user_id: str
    asset_id: str


def normalize_asset_type(asset_type: str) -> str:
    value = (asset_type or "").strip()
    if value not in ASSET_TYPES:
        raise ValueError(f"不支持的资产类型: {asset_type}")
    return value


def normalize_visibility(visibility: str | None) -> str:
    value = (visibility or VISIBILITY_PRIVATE).strip().lower()
    if value not in VISIBILITIES:
        raise ValueError("visibility 必须是 private、tenant 或 public")
    return value


def make_asset_ref(
    asset_type: str,
    tenant_id: str,
    owner_user_id: str,
    asset_id: str,
) -> str:
    asset_type = normalize_asset_type(asset_type)
    payload = [asset_type, tenant_id, owner_user_id, asset_id]
    if not all(isinstance(item, str) and item for item in payload):
        raise ValueError("资产引用字段不能为空")
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    token = base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")
    return ASSET_REF_PREFIX + token


def _decode_ref_payload(raw: str, *, expected_len: int) -> list[str]:
    raw += "=" * (-len(raw) % 4)
    try:
        data = json.loads(base64.urlsafe_b64decode(raw.encode("ascii")).decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, ValueError, TypeError) as e:
        raise ValueError("不是有效的资产引用") from e
    if (
        not isinstance(data, list)
        or len(data) != expected_len
        or not all(isinstance(item, str) and item for item in data)
    ):
        raise ValueError("不是有效的资产引用")
    return data


def parse_asset_ref(ref: str, *, expected_type: str | None = None) -> AssetRef:
    if expected_type is not None:
        expected_type = normalize_asset_type(expected_type)
    if not isinstance(ref, str):
        raise TypeError("不是有效的资产引用")
    # 旧前缀过渡兼容:3 元 payload,asset_type 由前缀映射补齐
    for prefix, legacy_type in LEGACY_REF_PREFIXES.items():
        if ref.startswith(prefix):
            data = _decode_ref_payload(ref[len(prefix):], expected_len=3)
            asset_type = normalize_asset_type(legacy_type)
            if expected_type is not None and asset_type != expected_type:
                raise ValueError("资产引用类型不匹配")
            return AssetRef(asset_type, data[0], data[1], data[2])
    if not ref.startswith(ASSET_REF_PREFIX):
        raise ValueError("不是有效的资产引用")
    data = _decode_ref_payload(ref[len(ASSET_REF_PREFIX):], expected_len=4)
    asset_type = normalize_asset_type(data[0])
    if expected_type is not None and asset_type != expected_type:
        raise ValueError("资产引用类型不匹配")
    return AssetRef(
        asset_type=asset_type,
        tenant_id=data[1],
        owner_user_id=data[2],
        asset_id=data[3],
    )


def resolve_asset_ref_or_legacy_id(
    ref_or_id: str,
    *,
    asset_type: str,
    tenant_id: str,
    owner_user_id: str,
) -> AssetRef:
    """解析 opaque ref；旧 id 兼容时只能落到当前 owner，不跨 owner 查询。"""
    asset_type = normalize_asset_type(asset_type)
    if isinstance(ref_or_id, str) and (
        ref_or_id.startswith(ASSET_REF_PREFIX)
        or any(ref_or_id.startswith(p) for p in LEGACY_REF_PREFIXES)
    ):
        return parse_asset_ref(ref_or_id, expected_type=asset_type)
    if not isinstance(ref_or_id, str) or not ref_or_id.strip():
        raise ValueError("资产 id 不能为空")
    return AssetRef(asset_type, tenant_id, owner_user_id, ref_or_id.strip())


def is_asset_owner(row: dict[str, Any], *, tenant_id: str, owner_user_id: str) -> bool:
    return row.get("tenant_id") == tenant_id and row.get("owner_user_id") == owner_user_id


def is_asset_visible(row: dict[str, Any], *, tenant_id: str, owner_user_id: str) -> bool:
    if is_asset_owner(row, tenant_id=tenant_id, owner_user_id=owner_user_id):
        return True
    visibility = normalize_visibility(row.get("visibility"))
    if visibility == VISIBILITY_PUBLIC:
        return True
    return visibility == VISIBILITY_TENANT and row.get("tenant_id") == tenant_id


def asset_source(row: dict[str, Any], *, tenant_id: str, owner_user_id: str) -> str:
    if bool(row.get("is_preset")):
        return "preset"
    if is_asset_owner(row, tenant_id=tenant_id, owner_user_id=owner_user_id):
        return "mine"
    return normalize_visibility(row.get("visibility"))


def owner_label(row: dict[str, Any], *, tenant_id: str, owner_user_id: str) -> str:
    if is_asset_owner(row, tenant_id=tenant_id, owner_user_id=owner_user_id):
        return "我"
    if row.get("tenant_id") == tenant_id:
        # 同租户他人:不回显内部 user_id,统一脱敏标签
        return "同租户用户"
    return "其他租户用户"


def decorate_asset_row(
    row: dict[str, Any],
    *,
    asset_type: str,
    tenant_id: str,
    owner_user_id: str,
    include_owner: bool = False,
    ref_key: str | None = None,
) -> dict[str, Any]:
    """补齐通用前端字段：asset_ref/source/readonly/owner_label/visibility。

    传入 ref_key 时(如 "profile_ref")额外写一个领域别名指向 asset_ref,
    供各资产保持既有对外字段名,避免每个仓库手写别名。
    """
    asset_type = normalize_asset_type(asset_type)
    own = is_asset_owner(row, tenant_id=tenant_id, owner_user_id=owner_user_id)
    out = dict(row)
    out["asset_ref"] = make_asset_ref(
        asset_type,
        str(row["tenant_id"]),
        str(row["owner_user_id"]),
        str(row["id"]),
    )
    if ref_key:
        out[ref_key] = out["asset_ref"]
    out["visibility"] = normalize_visibility(row.get("visibility"))
    out["source"] = asset_source(row, tenant_id=tenant_id, owner_user_id=owner_user_id)
    out["readonly"] = not own
    out["owner_label"] = owner_label(row, tenant_id=tenant_id, owner_user_id=owner_user_id)
    if not include_owner:
        out.pop("tenant_id", None)
        out.pop("owner_user_id", None)
    return out


def summarize_asset_row(
    row: dict[str, Any],
    *,
    asset_type: str,
    tenant_id: str,
    owner_user_id: str,
    ref_key: str = "profile_ref",
) -> dict[str, Any]:
    """列表用的统一 summary:只保留通用展示字段,不带 domain 明细。"""
    out = decorate_asset_row(
        row,
        asset_type=asset_type,
        tenant_id=tenant_id,
        owner_user_id=owner_user_id,
        ref_key=ref_key,
    )
    summary = {
        "id": out["id"],
        "asset_ref": out["asset_ref"],
        "name": out["name"],
        "version": int(out["version"]),
        "is_preset": bool(out.get("is_preset")),
        "visibility": out["visibility"],
        "source": out["source"],
        "readonly": out["readonly"],
        "owner_label": out["owner_label"],
        # 方案表均有 updated_at 列（搜索弹窗列表展示「更新时间」）；行内缺列时回退 None。
        "updated_at": str(out["updated_at"]) if out.get("updated_at") is not None else None,
    }
    if ref_key:
        summary[ref_key] = out[ref_key]
    return summary


def summarize_backtest_row(
    row: dict[str, Any],
    *,
    tenant_id: str,
    owner_user_id: str,
    ref_key: str = "run_ref",
) -> dict[str, Any]:
    """回测浏览专用 summary：回测无 name/version/is_preset/updated_at，字段独立于方案类。

    字段清单对齐计划 §4.2：id/kind/date_start/date_end/status/created_at/finished_at
    /visibility/source/readonly/owner_label + run_ref；并透传三类引用方案名供关键字/展示，
    owner 全程脱敏（decorate_asset_row 不回显 tenant_id/owner_user_id）。
    """
    out = decorate_asset_row(
        row,
        asset_type=ASSET_BACKTEST_RUN,
        tenant_id=tenant_id,
        owner_user_id=owner_user_id,
        ref_key=ref_key,
    )

    def _s(key: str) -> Any:
        val = out.get(key)
        return str(val) if val is not None else None

    summary = {
        "id": out["id"],
        "asset_ref": out["asset_ref"],
        "kind": out.get("kind"),
        "date_start": _s("date_start"),
        "date_end": _s("date_end"),
        "status": out.get("status"),
        "created_at": _s("created_at"),
        "finished_at": _s("finished_at"),
        "visibility": out["visibility"],
        "source": out["source"],
        "readonly": out["readonly"],
        "owner_label": out["owner_label"],
        # 回测自身无 name，浏览按三类引用方案名 + kind 过滤/展示（查询已 JOIN，见 backtest_service）
        "profile_name": out.get("profile_name"),
        "score_profile_name": out.get("score_profile_name"),
        "trade_profile_name": out.get("trade_profile_name"),
    }
    summary[ref_key] = out[ref_key]
    return summary


def visible_sql(alias: str = "") -> str:
    prefix = f"{alias}." if alias else ""
    return (
        f"(({prefix}tenant_id=%s AND {prefix}owner_user_id=%s) "
        f"OR {prefix}visibility='public' "
        f"OR ({prefix}visibility='tenant' AND {prefix}tenant_id=%s))"
    )


def visible_params(*, tenant_id: str, owner_user_id: str) -> list[str]:
    return [tenant_id, owner_user_id, tenant_id]


# ── 四来源互斥取数口径（R3/R5/R14，计划 §4.1）──────────────────────
# 搜索弹窗把可见资产切成互斥的四段来源，供下拉（mine）与浏览（preset/tenant/public）复用同一口径：
#   mine   ：纯 owner，下拉只加载自己的非平台预设资产。
#   preset ：系统内置段，严格 is_preset AND public AND 平台槽（PUBLIC_BOARD_OWNER），永不泄露 private。
#   tenant ：本租户公开且排除自己。
#   public ：全体公开且排除自己，且**强制补集**排除平台槽公开预设（只归 preset 段），四段真正互斥。
SCOPE_MINE = "mine"
SCOPE_PRESET = "preset"
SCOPE_TENANT = "tenant"
SCOPE_PUBLIC = "public"
PROFILE_SCOPES = frozenset({SCOPE_MINE, SCOPE_PRESET, SCOPE_TENANT, SCOPE_PUBLIC})
# 回测无 is_preset，无系统内置段，浏览仅 tenant/public（mine 用于「我的」历史置顶，不作过滤段）。
BACKTEST_SCOPES = frozenset({SCOPE_MINE, SCOPE_TENANT, SCOPE_PUBLIC})


def scoped_where(
    source: str,
    *,
    tenant_id: str,
    owner_user_id: str,
    public_board_owner: tuple[str, str],
    alias: str = "",
    has_preset: bool = True,
) -> tuple[str, list[str]]:
    """返回某来源段的互斥 WHERE 片段 + 参数。

    has_preset=False（回测）时：preset 段不支持；public 段省略平台槽预设的强制补集（无 is_preset 列）。
    参数顺序与片段内 %s 顺序严格对应，调用方按此拼接。
    """
    p = f"{alias}." if alias else ""
    pub_t, pub_o = public_board_owner
    if source == SCOPE_MINE:
        base = f"{p}tenant_id=%s AND {p}owner_user_id=%s"
        params = [tenant_id, owner_user_id]
        if has_preset:
            # 平台预设无论历史可见性为何都不是个人资产。这里不依赖 visibility，避免旧库中
            # private preset 泄漏到平台管理员的「我的方案」下拉；公开修复由 seed 命令负责。
            base += (f" AND NOT ({p}is_preset=true "
                     f"AND {p}tenant_id=%s AND {p}owner_user_id=%s)")
            params += [pub_t, pub_o]
        return f"({base})", params
    if source == SCOPE_PRESET:
        if not has_preset:
            raise ValueError("该资产类型无系统内置（preset）来源")
        return (
            (f"({p}is_preset=true AND {p}visibility='public' "
            f"AND {p}tenant_id=%s AND {p}owner_user_id=%s)"),
            [pub_t, pub_o],
        )
    if source == SCOPE_TENANT:
        return (
            (f"({p}visibility='tenant' AND {p}tenant_id=%s "
            f"AND NOT ({p}tenant_id=%s AND {p}owner_user_id=%s))"),
            [tenant_id, tenant_id, owner_user_id],
        )
    if source == SCOPE_PUBLIC:
        base = f"{p}visibility='public' AND NOT ({p}tenant_id=%s AND {p}owner_user_id=%s)"
        params = [tenant_id, owner_user_id]
        if has_preset:
            # 强制补集：平台槽公开预设只归 preset 段，从 public 段剔除，保证四段互斥不重复。
            base += f" AND NOT ({p}is_preset=true AND {p}tenant_id=%s AND {p}owner_user_id=%s)"
            params += [pub_t, pub_o]
        return f"({base})", params
    raise ValueError(f"不支持的取数来源: {source}")


# 方案类三表共用列/排序（回测字段不同，走 backtest_service 独立查询，不用此路径）
_PROFILE_SCOPED_COLUMNS = "id, tenant_id, owner_user_id, name, version, is_preset, visibility, updated_at"
_PROFILE_SCOPED_ORDER = "is_preset DESC, updated_at DESC NULLS LAST, name, id"


def scoped_query(
    pg,
    *,
    table: str,
    source: str,
    tenant_id: str,
    owner_user_id: str,
    public_board_owner: tuple[str, str],
    q: str | None = None,
    page: int | None = None,
    page_size: int = 20,
    has_preset: bool = True,
    columns: str = _PROFILE_SCOPED_COLUMNS,
    order_by: str = _PROFILE_SCOPED_ORDER,
) -> tuple[list[dict], int]:
    """按来源段取方案类资产行（依赖注入 pg，保持本模块无存储层耦合）。

    page 为 None → 不分页，返回全部（下拉 mine 用）；否则按 page/page_size 分页并返回总数（浏览用）。
    q 非空 → name ILIKE 关键字过滤。返回 (rows, total)。四来源互斥口径由 scoped_where 保证。
    """
    where, params = scoped_where(
        source,
        tenant_id=tenant_id,
        owner_user_id=owner_user_id,
        public_board_owner=public_board_owner,
        has_preset=has_preset,
    )
    if q and q.strip():
        where += " AND name ILIKE %s"
        params.append(f"%{q.strip()}%")
    if page is None:
        df = pg.query_df(
            f"SELECT {columns} FROM {table} WHERE {where} ORDER BY {order_by}", params)
        return df.to_dict("records"), len(df)
    total_df = pg.query_df(f"SELECT count(*) AS n FROM {table} WHERE {where}", params)
    total = int(total_df.iloc[0]["n"]) if not total_df.empty else 0
    page = max(1, int(page))
    page_size = max(1, min(int(page_size), 100))
    offset = (page - 1) * page_size
    df = pg.query_df(
        f"SELECT {columns} FROM {table} WHERE {where} ORDER BY {order_by} LIMIT %s OFFSET %s",
        [*params, page_size, offset],
    )
    return df.to_dict("records"), total


# 四类公开资产表(评分/筛选/买卖方案 + 回测记录)
PROFILE_ASSET_TABLES: tuple[str, ...] = (
    "score_profile",
    "screen_profile",
    "trade_profile",
)


def publish_platform_presets(
    pg,
    *,
    table: str,
    preset_ids: list[str],
    tenant_id: str,
    owner_user_id: str,
    public_board_owner: tuple[str, str],
) -> int:
    """把已写入的平台预设幂等校准为 public，只修改平台槽中的指定稳定 id。"""
    if (tenant_id, owner_user_id) != public_board_owner or not preset_ids:
        return 0
    if table not in PROFILE_ASSET_TABLES:
        raise ValueError(f"不支持的平台预设表: {table}")
    placeholders = ",".join(["%s"] * len(preset_ids))
    return pg.execute(
        f"UPDATE {table} SET is_preset=true, visibility='public', "
        "published_at=COALESCE(published_at, now()), "
        "published_by=%s, updated_at=now() "
        f"WHERE tenant_id=%s AND owner_user_id=%s AND id IN ({placeholders}) "
        "AND (is_preset IS DISTINCT FROM true OR visibility IS DISTINCT FROM 'public' "
        "OR published_at IS NULL OR published_by IS DISTINCT FROM %s)",
        [owner_user_id, tenant_id, owner_user_id, *preset_ids, owner_user_id],
    )


ASSET_TABLES: tuple[str, ...] = (
    *PROFILE_ASSET_TABLES,
    "backtest_run",
)

BACKTEST_SIGNATURE_KEYS: tuple[str, ...] = (
    "date_start",
    "date_end",
    "profile_id",
    "score_profile_id",
    "trade_profile_id",
    "top_n",
    "initial_capital",
    "sell_ma_period",
    "max_hold_days",
    "take_profit",
    "stop_loss",
    "rebalance_days",
    "industry_max_pct",
    "benchmark",
    "horizons",
    "thresholds",
)


def backtest_signature(kind: str, params: dict, versions: dict) -> str:
    """回测去重签名的纯数据算法,供手动收回和批量下线共用。"""
    payload: dict = {"kind": "strategy" if kind == "strategy" else "score_check"}
    for key in BACKTEST_SIGNATURE_KEYS:
        val = params.get(key)
        if val is not None:
            payload[key] = str(val) if key in ("date_start", "date_end") else val
    # 发布/收回仅规范化方案引用，不能丢弃原运行的数据版本或套用今天的身份规则。
    stored_versions = params.get("_data_versions") or {}
    for key in ("stock_identity_version", "st_data_version", "capital_data_version",
                "price_consumption_version"):
        if isinstance(stored_versions, dict) and key in stored_versions:
            payload[key] = stored_versions[key]
    payload.update({key: versions.get(key) for key in sorted(versions)})
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def bare_asset_id(ref_or_id: str) -> str:
    """opaque ref → 原始裸 id;非 ref 原样返回。"""
    try:
        return parse_asset_ref(ref_or_id).asset_id
    except (TypeError, ValueError):
        return ref_or_id


# 方案资产类型 → backtest_run 引用列（_assert_no_own_refs / 收回拦截 / 删除级联共用）
_PROFILE_BACKTEST_REF_COL: dict[str, str] = {
    ASSET_SCREEN_PROFILE: "profile_id",
    ASSET_SCORE_PROFILE: "score_profile_id",
    ASSET_TRADE_PROFILE: "trade_profile_id",
}


def backtest_ref_column(asset_type: str) -> str:
    """返回某方案资产类型在 backtest_run 中的引用列名。"""
    col = _PROFILE_BACKTEST_REF_COL.get(normalize_asset_type(asset_type))
    if col is None:
        raise ValueError(f"资产类型 {asset_type} 无回测引用列")
    return col


def _ref_and_pid(asset_type: str, ref: str, tenant_id: str, owner_user_id: str) -> tuple[str, str]:
    """统一构造该方案的 opaque ref 与裸 id（他人 ref 引用 / 本 owner 裸 id 存量引用两种形态）。"""
    col_ref = make_asset_ref(asset_type, tenant_id, owner_user_id, bare_asset_id(ref))
    return col_ref, bare_asset_id(col_ref)


def referencing_backtest_runs(pg, *, asset_type: str, ref: str,
                              tenant_id: str, owner_user_id: str) -> bool:
    """是否有**本 owner**的回测记录引用该方案（裸 id 存量 + opaque ref）。

    用于删除前拦截（P1 防悬空）：本 owner 的记录 owner 可自行处置（先删回测再删方案），
    故删除仍拦。他人引用走 `referencing_backtest_runs_by_others` + 级联降级。
    """
    col = backtest_ref_column(asset_type)
    col_ref, pid = _ref_and_pid(asset_type, ref, tenant_id, owner_user_id)
    hit = pg.query_df(
        f"SELECT 1 FROM backtest_run WHERE {col}=%s AND tenant_id=%s AND owner_user_id=%s "
        f"OR ({col}=%s AND tenant_id=%s AND owner_user_id=%s) LIMIT 1",
        [col_ref, tenant_id, owner_user_id, pid, tenant_id, owner_user_id])
    return not hit.empty


def referencing_backtest_runs_by_others(pg, *, asset_type: str, ref: str,
                                        tenant_id: str, owner_user_id: str,
                                        conn=None) -> bool:
    """是否有**他人**的回测记录（opaque ref 形态）引用该方案。

    公开方案被他人引用后 owner 无法删除的死锁根因：ref 编码真实归属、全局唯一，
    backtest_run 引用列存他人 ref 时不受本 owner 归属限定。存在他人引用 → 删除需先级联降级。
    传 `conn` 时并入调用方事务内查询（与删除同事务，避免查-删窗口竞态）。
    """
    col = backtest_ref_column(asset_type)
    col_ref, _ = _ref_and_pid(asset_type, ref, tenant_id, owner_user_id)
    sql = (
        f"SELECT 1 FROM backtest_run WHERE {col}=%s "
        f"AND NOT (tenant_id=%s AND owner_user_id=%s) LIMIT 1"
    )
    if conn is not None:
        with pg.cursor_in(conn) as cur:
            cur.execute(sql, [col_ref, tenant_id, owner_user_id])
            return cur.fetchone() is not None
    hit = pg.query_df(sql, [col_ref, tenant_id, owner_user_id])
    return not hit.empty


def downgrade_backtest_runs_referencing(pg, *, asset_type: str, ref: str,
                                        tenant_id: str, owner_user_id: str,
                                        conn=None) -> int:
    """删除方案前，把引用它的**他人**公开/租户回测降级为 private 并清发布字段。

    只降级他人引用的 run（本 owner 的 run 由 `_assert_no_own_refs` 拦截，owner 应先删回测）。
    返回受影响行数。传 `conn` 时并入调用方事务（须与删除主表/版本表同事务原子提交，
    避免降级成功但删除失败留下半更新）；否则自建事务自动提交。
    """
    col = backtest_ref_column(asset_type)
    col_ref, _ = _ref_and_pid(asset_type, ref, tenant_id, owner_user_id)
    sql = (
        f"UPDATE backtest_run SET visibility='private', published_at=NULL, published_by=NULL "
        f"WHERE {col}=%s AND NOT (tenant_id=%s AND owner_user_id=%s) AND visibility<>'private'"
    )
    if conn is not None:
        with pg.cursor_in(conn) as cur:
            cur.execute(sql, [col_ref, tenant_id, owner_user_id])
            return max(cur.rowcount or 0, 0)
    return pg.execute(sql, [col_ref, tenant_id, owner_user_id])


@contextmanager
def asset_visibility_locks(pg, refs: list[AssetRef]) -> Iterator[None]:
    """串行化同一方案的“可见性变更”和“依赖回测发布”。

    锁按稳定顺序获取，覆盖跨仓库的校验与写入窗口；使用独立短连接，避免占用业务事务连接后
    再向连接池借连接形成自锁。会话结束会兜底释放 advisory lock。
    """
    keys = sorted({
        f"{ref.asset_type}:{ref.tenant_id}:{ref.owner_user_id}:{ref.asset_id}"
        for ref in refs
    })
    if not keys:
        yield
        return
    try:
        conn = psycopg.connect(pg.conninfo, autocommit=True, connect_timeout=10)
    except psycopg.Error as exc:
        raise RuntimeError("资产可见性并发锁连接失败，请稍后重试") from exc
    try:
        with conn.cursor() as cur:
            for key in keys:
                cur.execute(
                    "SELECT pg_advisory_lock(hashtext(%s), hashtext(%s))",
                    ["asset-visibility", key],
                )
            try:
                yield
            finally:
                for key in reversed(keys):
                    try:
                        cur.execute(
                            "SELECT pg_advisory_unlock(hashtext(%s), hashtext(%s))",
                            ["asset-visibility", key],
                        )
                    except psycopg.Error:
                        # 关闭会话仍会释放锁；不覆盖原业务异常。
                        pass
    finally:
        conn.close()


def reconcile_backtest_runs_for_profile_visibility(
    pg,
    *,
    asset_type: str,
    ref: str,
    tenant_id: str,
    owner_user_id: str,
    target_visibility: str,
    conn=None,
) -> int:
    """收窄方案可见性时，同步收窄引用它的已发布回测。

    private：所有非私有引用回测降为 private；tenant：同租户 public 回测降为 tenant，
    跨租户引用回测降为 private。历史结果保留，只清理不再成立的发布范围。
    裸 id 只匹配方案 owner 自己的历史回测，避免误伤其他 owner 的同名资产。
    """
    target_visibility = normalize_visibility(target_visibility)
    if target_visibility == VISIBILITY_PUBLIC:
        return 0
    col = backtest_ref_column(asset_type)
    col_ref, pid = _ref_and_pid(asset_type, ref, tenant_id, owner_user_id)
    ref_where = (
        f"({col}=%s OR ({col}=%s AND tenant_id=%s AND owner_user_id=%s))"
    )
    ref_params = [col_ref, pid, tenant_id, owner_user_id]
    if target_visibility == VISIBILITY_PRIVATE:
        sql = (
            "UPDATE backtest_run SET visibility='private', published_at=NULL, published_by=NULL "
            f"WHERE {ref_where} AND visibility<>'private'"
        )
        params = ref_params
    else:
        sql = (
            "UPDATE backtest_run SET "
            "visibility=CASE WHEN tenant_id=%s THEN 'tenant' ELSE 'private' END, "
            "published_at=CASE WHEN tenant_id=%s THEN published_at ELSE NULL END, "
            "published_by=CASE WHEN tenant_id=%s THEN published_by ELSE NULL END "
            f"WHERE {ref_where} AND ("
            "(tenant_id=%s AND visibility='public') OR "
            "(tenant_id<>%s AND visibility<>'private'))"
        )
        params = [tenant_id, tenant_id, tenant_id, *ref_params, tenant_id, tenant_id]

    if conn is not None:
        with pg.cursor_in(conn) as cur:
            cur.execute(sql, params)
            return max(cur.rowcount or 0, 0)
    with pg.transaction() as tx:
        return reconcile_backtest_runs_for_profile_visibility(
            pg,
            asset_type=asset_type,
            ref=ref,
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
            target_visibility=target_visibility,
            conn=tx,
        )


def restore_backtest_private_dependencies(run: dict) -> dict | None:
    """回测收回 private 时还原方案引用列并重算 signature。

    发布到 tenant/public 时会把方案引用改写为 opaque ref;收回为 private 后应恢复裸 id。
    返回 None 表示没有 ref 需要还原。
    """
    raw_params = run.get("params") or "{}"
    if isinstance(raw_params, dict):
        params = dict(raw_params)
    else:
        try:
            params = json.loads(raw_params)
        except (TypeError, ValueError):
            params = None
    normalized = {
        "params": raw_params if params is None else params,
        "profile_id": run.get("profile_id"),
        "score_profile_id": run.get("score_profile_id"),
        "trade_profile_id": run.get("trade_profile_id"),
        "profile_version": run.get("profile_version"),
        "score_profile_version": run.get("score_profile_version"),
        "trade_profile_version": run.get("trade_profile_version"),
        "signature": run.get("signature"),
    }
    changed = False
    for key in ("profile_id", "score_profile_id", "trade_profile_id"):
        raw_val = (params.get(key) if isinstance(params, dict) else None) or run.get(key)
        if not raw_val:
            continue
        bare = bare_asset_id(str(raw_val))
        if bare != str(raw_val):
            normalized[key] = bare
            if isinstance(params, dict):
                params[key] = bare
            changed = True
    if not changed:
        return None
    if isinstance(params, dict):
        normalized["signature"] = backtest_signature(
            str(run.get("kind") or "strategy"),
            params,
            {
                "profile_version": normalized["profile_version"],
                "score_profile_version": normalized["score_profile_version"],
                "trade_profile_version": normalized["trade_profile_version"],
            },
        )
    return normalized


def _backtest_downgrade_where(owner_user_id: str | None) -> tuple[str, list]:
    if owner_user_id is None:
        return "tenant_id=%s AND visibility<>'private'", []
    return "tenant_id=%s AND owner_user_id=%s AND visibility<>'private'", [owner_user_id]


def _downgrade_backtest_runs_to_private(
    conn,
    *,
    tenant_id: str,
    owner_user_id: str | None,
) -> int:
    where, extra = _backtest_downgrade_where(owner_user_id)
    params = [tenant_id, *extra]
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, tenant_id, owner_user_id, kind, params, profile_id, score_profile_id, "
            "trade_profile_id, profile_version, score_profile_version, trade_profile_version, "
            f"signature FROM backtest_run WHERE {where}",
            params,
        )
        cols = [desc.name for desc in cur.description]
        rows = [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]
        affected = 0
        for run in rows:
            normalized = restore_backtest_private_dependencies(run)
            raw_params = normalized["params"] if normalized else run.get("params")
            params_json = (
                json.dumps(raw_params, ensure_ascii=False, default=str)
                if isinstance(raw_params, dict)
                else raw_params
            )
            cur.execute(
                "UPDATE backtest_run SET visibility='private', "
                "published_at=NULL, published_by=NULL, "
                "params=%s, profile_id=%s, score_profile_id=%s, trade_profile_id=%s, "
                "profile_version=%s, score_profile_version=%s, trade_profile_version=%s, "
                "signature=%s WHERE tenant_id=%s AND owner_user_id=%s AND id=%s",
                [
                    params_json,
                    normalized["profile_id"] if normalized else run.get("profile_id"),
                    normalized["score_profile_id"] if normalized else run.get("score_profile_id"),
                    normalized["trade_profile_id"] if normalized else run.get("trade_profile_id"),
                    normalized["profile_version"] if normalized else run.get("profile_version"),
                    normalized["score_profile_version"]
                    if normalized
                    else run.get("score_profile_version"),
                    normalized["trade_profile_version"]
                    if normalized
                    else run.get("trade_profile_version"),
                    normalized["signature"] if normalized else run.get("signature"),
                    run["tenant_id"],
                    run["owner_user_id"],
                    run["id"],
                ],
            )
            affected += max(cur.rowcount or 0, 0)
    return affected


def downgrade_owner_assets_to_private(
    conn,
    *,
    tenant_id: str,
    owner_user_id: str | None = None,
) -> int:
    """停用下线(P3):把指定用户/租户名下所有非私有资产降级为 private 并清发布字段。

    `conn` 为调用方事务连接,与停用写入同事务原子提交;`owner_user_id` 为空时降级整租户。
    返回受影响行数。
    """
    affected = 0
    for table in PROFILE_ASSET_TABLES:
        if owner_user_id is None:
            cur = conn.execute(
                f"UPDATE {table} SET visibility='private', published_at=NULL, published_by=NULL "
                "WHERE tenant_id=%s AND visibility<>'private'",
                [tenant_id],
            )
        else:
            cur = conn.execute(
                f"UPDATE {table} SET visibility='private', published_at=NULL, published_by=NULL "
                "WHERE tenant_id=%s AND owner_user_id=%s AND visibility<>'private'",
                [tenant_id, owner_user_id],
            )
        affected += max(getattr(cur, "rowcount", 0) or 0, 0)
    affected += _downgrade_backtest_runs_to_private(
        conn, tenant_id=tenant_id, owner_user_id=owner_user_id)
    return affected
