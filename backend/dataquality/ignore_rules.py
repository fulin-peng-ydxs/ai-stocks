"""数据质检通用忽略范围。

忽略规则复用 ``data_quality_issue`` 历史行作为审计载体：
- occurrence：只抑制当前持续存在的同一事件；完整扫描确认事件消失后自动失效；
- object：持续抑制同一业务对象的同类问题，直到人工恢复监控。
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import date

import pandas as pd

from backend.storage.duckdb_client import DuckDBClient

IGNORE_SCOPES = ("occurrence", "object")


def _date_key(value) -> str | None:
    if value is None or pd.isna(value):
        return None
    return str(pd.Timestamp(value).date())


def subject_key(issue_type: str, code, detail: str | None = None) -> str:
    """返回忽略匹配使用的稳定业务对象标识。"""
    if issue_type == "board_fund_unmatched":
        try:
            payload = json.loads(detail or "{}")
        except (TypeError, ValueError):
            payload = {}
        board_type = str(payload.get("board_type") or "").strip()
        name = str(payload.get("name") or "").strip()
        return f"unmatched:{board_type}:{name}"
    if code is None or pd.isna(code) or not str(code).strip():
        return f"source:{issue_type}"
    return f"code:{str(code).strip()}"


def occurrence_key(issue_type: str, code, trade_date, detail: str | None = None) -> tuple[str, str, str | None]:
    return issue_type, subject_key(issue_type, code, detail), _date_key(trade_date)


def object_key(issue_type: str, code, detail: str | None = None) -> tuple[str, str]:
    return issue_type, subject_key(issue_type, code, detail)


def _scope_value(issue_type: str, value) -> str:
    if value is not None and not pd.isna(value):
        return str(value)
    # 兼容升级前历史行及直接写入的旧调用：沿用当时的类型口径。
    from backend.dataquality.checker import EXACT_IGNORE_ISSUE_TYPES
    return "occurrence" if issue_type in EXACT_IGNORE_ISSUE_TYPES else "object"


def _active_rules(client: DuckDBClient, issue_types: Iterable[str]) -> pd.DataFrame:
    types = tuple(dict.fromkeys(str(x) for x in issue_types))
    if not types:
        return pd.DataFrame()
    placeholders = ",".join("?" * len(types))
    return client.query_df(
        "SELECT id, code, trade_date, issue_type, detail, ignore_scope "
        "FROM data_quality_issue WHERE status='ignored' AND COALESCE(ignore_active, true)=true "
        f"AND issue_type IN ({placeholders})",
        list(types),
    )


def filter_ignored_issues(
    client: DuckDBClient,
    issues: list[dict],
    issue_types: Iterable[str],
    *,
    reconcile_occurrences: bool,
    scope_codes: Iterable[str] | None = None,
) -> list[dict]:
    """过滤有效忽略规则；完整快照可同时收敛已经消失的 occurrence 规则。"""
    types = tuple(dict.fromkeys(str(x) for x in issue_types))
    rules = _active_rules(client, types)
    if scope_codes is not None and not rules.empty:
        rules = rules[rules.code.isin(tuple(scope_codes))]
    if rules.empty:
        return issues

    occurrence_rules: dict[tuple[str, str, str | None], int] = {}
    object_rules: set[tuple[str, str]] = set()
    for _, row in rules.iterrows():
        issue_type = str(row["issue_type"])
        detail = row.get("detail")
        scope = _scope_value(issue_type, row["ignore_scope"])
        if str(scope) == "object":
            object_rules.add(object_key(issue_type, row["code"], detail))
        else:
            occurrence_rules[occurrence_key(
                issue_type, row["code"], row["trade_date"], detail,
            )] = int(row["id"])

    current_occurrences = {
        occurrence_key(x["issue_type"], x.get("code"), x.get("trade_date"), x.get("detail"))
        for x in issues
    }
    if reconcile_occurrences:
        expired = [iid for key, iid in occurrence_rules.items() if key not in current_occurrences]
        if expired:
            client.execute(
                "UPDATE data_quality_issue SET ignore_active=false "
                f"WHERE id IN ({','.join('?' * len(expired))})",
                expired,
            )

    return [
        x for x in issues
        if object_key(x["issue_type"], x.get("code"), x.get("detail")) not in object_rules
        and occurrence_key(
            x["issue_type"], x.get("code"), x.get("trade_date"), x.get("detail")
        ) not in occurrence_rules
    ]


def deactivate_occurrence_ignores(
    client: DuckDBClient,
    issue_type: str,
    code,
    trade_dates: Iterable[date],
) -> int:
    """局部采集确认某些日期已正常时，结束对应的“仅忽略本次”规则。"""
    wanted = {_date_key(value) for value in trade_dates}
    if not wanted:
        return 0
    rules = _active_rules(client, (issue_type,))
    ids = [
        int(row["id"])
        for _, row in rules.iterrows()
        if _scope_value(issue_type, row["ignore_scope"]) == "occurrence"
        and subject_key(issue_type, row["code"], row.get("detail"))
        == subject_key(issue_type, code)
        and _date_key(row["trade_date"]) in wanted
    ]
    if ids:
        client.execute(
            "UPDATE data_quality_issue SET ignore_active=false "
            f"WHERE id IN ({','.join('?' * len(ids))})",
            ids,
        )
    return len(ids)
