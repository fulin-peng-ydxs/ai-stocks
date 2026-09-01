"""Shared parameter rules for explicit derived-result maintenance tasks."""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from backend.storage.duckdb_client import DuckDBClient, get_client

RESULT_TARGET_MODES = ("latest", "fixed", "all")


def _normalize_target_params(
    params: dict[str, Any] | None,
    *,
    task_label: str,
    allow_all: bool = True,
) -> dict[str, Any]:
    if params is not None and not isinstance(params, dict):
        raise ValueError(f"{task_label}任务参数必须是对象")
    raw = dict(params or {})
    unknown = sorted(set(raw) - {"target_mode", "trade_date"})
    if unknown:
        raise ValueError(f"{task_label}任务不支持参数: {','.join(unknown)}")
    target_mode = str(raw.get("target_mode") or "latest").strip()
    allowed = RESULT_TARGET_MODES if allow_all else RESULT_TARGET_MODES[:-1]
    if target_mode not in allowed:
        raise ValueError(f"{task_label}目标范围非法（可选 {allowed}）")
    raw_date = str(raw.get("trade_date") or "").strip()
    if target_mode == "fixed":
        if not raw_date:
            raise ValueError(f"{task_label}固定日期不能为空")
        try:
            date.fromisoformat(raw_date)
        except ValueError as exc:
            raise ValueError(f"{task_label}固定日期非法，须为 YYYY-MM-DD") from exc
    return {
        "target_mode": target_mode,
        "trade_date": raw_date if target_mode == "fixed" else None,
    }


def normalize_score_invalidation_params(params: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize the explicit daily-board snapshot invalidation task."""
    return _normalize_target_params(params, task_label="每日榜单失效")


def normalize_ladder_invalidation_params(params: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize the explicit limit-ladder invalidation task."""
    return _normalize_target_params(
        params,
        task_label="连板天梯失效",
        allow_all=False,
    )


def resolve_latest_market_date(client: DuckDBClient | None = None) -> date:
    """Return the latest open date that actually has stock daily bars."""
    c = client or get_client()
    row = c.query_df(
        "SELECT max(calendar.trade_date) AS trade_date FROM trade_calendar calendar "
        "WHERE calendar.is_open=true AND EXISTS ("
        "SELECT 1 FROM daily_bar bar WHERE bar.trade_date=calendar.trade_date)"
    ).iloc[0]["trade_date"]
    if row is None or pd.isna(row):
        raise ValueError("没有可维护的行情交易日")
    return pd.Timestamp(row).date()


def resolve_target_date(params: dict[str, Any], client: DuckDBClient | None = None) -> date | None:
    """Resolve latest/fixed/all to a concrete date or ``None`` for all snapshots."""
    mode = params["target_mode"]
    if mode == "all":
        return None
    if mode == "fixed":
        target = date.fromisoformat(str(params["trade_date"]))
        c = client or get_client()
        calendar = c.query_df(
            "SELECT is_open FROM trade_calendar WHERE trade_date=?",
            [target],
        )
        if calendar.empty or not bool(calendar.iloc[0]["is_open"]):
            raise ValueError(f"{target.isoformat()} 不是已登记的交易日")
        return target
    return resolve_latest_market_date(client)
