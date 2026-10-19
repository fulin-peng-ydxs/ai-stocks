"""质量类型合并兼容：保留历史审计与旧忽略的字段/时间边界。"""
from __future__ import annotations

import json

import pandas as pd

QUALITY_TYPE_ALIASES = {
    "mv_missing": "capital_gap",
    "mv_gap": "capital_gap",
    "mv_invalid": "capital_invalid",
    "data_gap": "history_data_gap",
}


def canonical_quality_type(kind: str) -> str:
    return QUALITY_TYPE_ALIASES.get(kind, kind)


def legacy_ignore_sql(kind: str, code_sql="b.code") -> str:
    """只引用内部常量；旧规则不改名，避免市值豁免扩大到股本或全部历史。"""
    if kind not in QUALITY_TYPE_ALIASES:
        raise ValueError(kind)
    return (
        f"{code_sql} IN (SELECT code FROM data_quality_issue legacy_ignore "
        f"WHERE legacy_ignore.issue_type='{kind}' "
        "AND legacy_ignore.status='ignored' AND coalesce(legacy_ignore.ignore_active,true))"
    )


RECENT_DAY_SQL = """(SELECT min(trade_date) FROM
    (SELECT trade_date FROM trade_calendar WHERE is_open
     AND trade_date<=(SELECT max(trade_date) FROM daily_bar)
     ORDER BY trade_date DESC LIMIT 90))"""
LIVE_STOCK_SQL = """b.code IN (SELECT code FROM stock_basic legacy_stock
    WHERE (legacy_stock.delist_date IS NULL
    OR legacy_stock.delist_date>(SELECT max(trade_date) FROM daily_bar)))"""


def reconcile_legacy_issues(client, codes=None, *, kinds=None):
    """归档旧待办并收敛旧单次忽略；已忽略/处理中记录保持原身份和任务归属。"""
    from backend.services.data_report import DataIntegrityReport

    scope = " AND code IN (SELECT unnest(?::VARCHAR[]))" if codes is not None else ""
    rows = client.query_df(
        "SELECT id,code,issue_type,trade_date,status,ignore_scope,detail FROM data_quality_issue "
        "WHERE issue_type IN (SELECT unnest(?::VARCHAR[])) "
        "AND (status='open' OR (status='ignored' AND coalesce(ignore_active,true) AND ignore_scope='occurrence'))" + scope,
        [list(kinds or QUALITY_TYPE_ALIASES)] + ([codes] if codes is not None else []),
    )
    updates = []
    report = DataIntegrityReport(client)
    for row in rows.itertuples():
        if row.status == "ignored":
            if report.recheck_clean(row.issue_type, row.code, row.trade_date, detail=row.detail):
                client.execute("UPDATE data_quality_issue SET ignore_active=false WHERE id=?", [row.id])
            continue
        target = canonical_quality_type(row.issue_type)
        note = f"质量类型已合并至 {target}，当前异常由统一类型继续跟踪；不是数据已修复。"
        detail = json.dumps({"message": note, "resolution_note": note,
                             "original_detail": row.detail, "merged_into": target}, ensure_ascii=False)
        updates.append({"id": row.id, "detail": detail})
    if updates:
        with client.temp_view(pd.DataFrame(updates), prefix="quality_merge") as view:
            client.execute("UPDATE data_quality_issue q SET status='resolved',resolved_at=now(),detail=v.detail "
                           f"FROM {view} v WHERE q.id=v.id AND q.status='open'")
