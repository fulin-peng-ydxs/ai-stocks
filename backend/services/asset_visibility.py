"""用户资产可见性通用规则。

阶段六 T5 只沉淀三类后续资产（筛选方案、买卖方案、回测记录）的共享 helper；
具体仓库/API 接入在 T6-T8 完成。
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from dataclasses import dataclass
from typing import Any

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
        raise ValueError("不是有效的资产引用")
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
    }
    if ref_key:
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


# 四类公开资产表(评分/筛选/买卖方案 + 回测记录)
PROFILE_ASSET_TABLES: tuple[str, ...] = (
    "score_profile",
    "screen_profile",
    "trade_profile",
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
    payload.update({key: versions.get(key) for key in sorted(versions)})
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def bare_asset_id(ref_or_id: str) -> str:
    """opaque ref → 原始裸 id;非 ref 原样返回。"""
    try:
        return parse_asset_ref(ref_or_id).asset_id
    except ValueError:
        return ref_or_id


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
