"""公共榜单生产与查询辅助。

公共榜单是阶段四的特例：方案与快照固定归属到 PUBLIC_BOARD_OWNER，普通
board:view 入口只读 fresh 快照；生产动作只能由系统任务/CLI 走这里显式触发。
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from backend.common.logging import get_logger
from backend.scoring.score_profile import ScoreProfileRepo
from backend.scoring.snapshot import ScoreSnapshotRepo, _current_param_hash
from backend.services.stock_st_status import StockSTStatusService
from backend.storage.duckdb_client import get_client
from backend.storage.pg_client import get_pg_client
from backend.storage.pg_ddl import PUBLIC_BOARD_OWNER

log = get_logger("services.public_board")

_PUB_TENANT, _PUB_OWNER = PUBLIC_BOARD_OWNER


def _as_date(v) -> date | None:
    if v is None or pd.isna(v):
        return None
    return pd.Timestamp(v).date()


def latest_market_date(market=None) -> date | None:
    """行情库 latest daily_bar 日期；无行情返回 None。"""
    c = market or get_client()
    df = c.query_df("SELECT max(trade_date) AS d FROM daily_bar")
    if df.empty:
        return None
    return _as_date(df.iloc[0]["d"])


def public_profile_repo(market=None, pg=None) -> ScoreProfileRepo:
    return ScoreProfileRepo(
        market or get_client(),
        pg or get_pg_client(),
        tenant_id=_PUB_TENANT,
        owner_user_id=_PUB_OWNER,
    )


def get_public_board_profile(profile_id: str | None, market=None, pg=None) -> dict | None:
    """读取 PUBLIC_BOARD_OWNER 下的公共预设方案；非预设/不存在返回 None。"""
    if not profile_id:
        return None
    prof = public_profile_repo(market, pg).get(profile_id)
    if not prof or not prof.get("is_preset"):
        return None
    return prof


def list_public_board_profiles(market=None, pg=None) -> list[dict]:
    """公共榜单可见方案列表，仅包含预设方案。"""
    return [p for p in public_profile_repo(market, pg).list() if p.get("is_preset")]


def _latest_st_version_matched_date(rows: pd.DataFrame, market=None) -> date | None:
    """Return the latest PG snapshot date that still matches DuckDB ST facts."""
    if rows.empty:
        return None
    service = StockSTStatusService(market or get_client())
    expected_param_hash = _current_param_hash(market or get_client())
    trade_dates = [
        trade_date
        for value in rows["trade_date"].tolist()
        if (trade_date := _as_date(value)) is not None
    ]
    current_versions = service.input_versions_for_dates(trade_dates)
    for row in rows.to_dict("records"):
        trade_date = _as_date(row.get("trade_date"))
        if trade_date is None:
            continue
        stored = row.get("st_input_version")
        if (
            row.get("param_hash") == expected_param_hash
            and pd.notna(stored)
            and str(stored) == current_versions[trade_date]
        ):
            return trade_date
    return None


def latest_fresh_public_snapshot_date(
    profile_id: str,
    profile_version: int,
    pg=None,
    market=None,
) -> date | None:
    """某公共预设当前版本中仍匹配已发布 ST 事实的最新交易日。"""
    client = pg or get_pg_client()
    df = client.query_df(
        "SELECT trade_date,param_hash,st_input_version FROM score_snapshot_meta "
        "WHERE tenant_id=%s AND owner_user_id=%s AND profile_id=%s "
        "AND profile_version=%s AND stale=false ORDER BY trade_date DESC",
        [_PUB_TENANT, _PUB_OWNER, profile_id, int(profile_version)],
    )
    return _latest_st_version_matched_date(df, market)


def latest_fresh_public_board_date(pg=None, market=None) -> date | None:
    """数据总览口径：公共预设中仍匹配已发布 ST 事实的最新榜单日。"""
    client = pg or get_pg_client()
    df = client.query_df(
        "SELECT DISTINCT m.trade_date,m.param_hash,m.st_input_version "
        "FROM score_snapshot_meta m "
        "JOIN score_profile p ON p.tenant_id=m.tenant_id "
        " AND p.owner_user_id=m.owner_user_id "
        " AND p.id=m.profile_id "
        " AND p.version=m.profile_version "
        "WHERE m.tenant_id=%s AND m.owner_user_id=%s "
        "AND p.is_preset=true AND m.stale=false ORDER BY m.trade_date DESC",
        [_PUB_TENANT, _PUB_OWNER],
    )
    return _latest_st_version_matched_date(df, market)


def resolve_public_board_run_date(
    *,
    profile_id: str,
    profile_version: int,
    requested: str | None = None,
    market=None,
    pg=None,
) -> date | None:
    """榜单页默认日期：显式日期优先；否则取该公共预设最新 fresh 快照日。

    若从未生产过 fresh 快照，回落到行情最新日仅用于返回空榜时展示日期，不触发生产。
    """
    if requested:
        return date.fromisoformat(requested)
    fresh = latest_fresh_public_snapshot_date(profile_id, profile_version, pg, market)
    return fresh or latest_market_date(market)


def produce_public_board_snapshots(
    *,
    run_date: date | str | None = None,
    profile_ids: list[str] | None = None,
    market=None,
    pg=None,
) -> dict:
    """为 PUBLIC_BOARD_OWNER 的公共预设物化指定交易日快照。

    run_date 为空时生产行情最新日；profile_ids 为空时生产全部公共预设。返回值用于任务日志/CLI。
    """
    c = market or get_client()
    client = pg or get_pg_client()
    target_date = date.fromisoformat(run_date) if isinstance(run_date, str) else run_date
    target_date = target_date or latest_market_date(c)
    if target_date is None:
        return {"run_date": None, "profiles": [], "profile_count": 0, "total_rows": 0}

    repo = public_profile_repo(c, client)
    if profile_ids:
        profiles = [repo.get(pid) for pid in profile_ids]
        profiles = [p for p in profiles if p and p.get("is_preset")]
    else:
        profiles = [repo.get(p["id"]) for p in repo.list() if p.get("is_preset")]
        profiles = [p for p in profiles if p]

    snapshot_repo = ScoreSnapshotRepo(
        c,
        client,
        tenant_id=_PUB_TENANT,
        owner_user_id=_PUB_OWNER,
    )
    produced: list[dict] = []
    total_rows = 0
    for prof in profiles:
        pid = prof["id"]
        version = int(prof.get("version") or 1)
        board = snapshot_repo.get_board(target_date, pid, profile=prof)
        rows = len(board)
        total_rows += rows
        produced.append({"profile_id": pid, "version": version, "rows": rows})

    log.info("公共榜单生产完成 date=%s profiles=%d rows=%d", target_date, len(produced), total_rows)
    return {
        "run_date": str(target_date),
        "profiles": produced,
        "profile_count": len(produced),
        "total_rows": total_rows,
    }
