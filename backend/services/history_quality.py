"""日线全历史应有日期校验；复用交易日历、上市退市边界及确认停牌事实。"""

from __future__ import annotations

import json

import pandas as pd

from backend.common.timeutil import years_before
from backend.config import get_effective_settings


class HistoryQualityService:
    def __init__(self, client):
        self.c = client

    def missing_sql(self, codes=None):
        """在数据库内做日期反连接；不能用首条行情截掉上市后的头部漏采。"""
        span = self.c.query_df("SELECT min(trade_date) lo,max(trade_date) hi FROM daily_bar").iloc[
            0
        ]
        if pd.isna(span.hi):
            return "SELECT code,trade_date FROM daily_bar WHERE false", []
        hi = pd.Timestamp(span.hi).date()
        lo = min(
            pd.Timestamp(span.lo).date(),
            years_before(hi, get_effective_settings().datasource.history_years),
        )
        scope = " AND s.code IN (SELECT unnest(?::VARCHAR[]))" if codes is not None else ""
        # 北交所不在项目股票池。缺上市日时仅从已知首日检查，不能凭空构造存续期。
        sql = (
            "WITH spans AS (SELECT code,min(trade_date) first_day FROM daily_bar GROUP BY code),"
            "expected AS (SELECT s.code,t.trade_date FROM stock_basic s LEFT JOIN spans p USING(code) "
            "JOIN trade_calendar t ON t.is_open AND t.trade_date BETWEEN ? AND ? "
            "AND t.trade_date>=coalesce(s.list_date,p.first_day) "
            "AND (s.delist_date IS NULL OR t.trade_date<s.delist_date) "
            "WHERE (s.code LIKE '%.SH' OR s.code LIKE '%.SZ')" + scope + ") "
            "SELECT e.code,e.trade_date FROM expected e "
            "ANTI JOIN daily_bar b ON b.code=e.code AND b.trade_date=e.trade_date "
            "ANTI JOIN stock_suspension x ON x.code=e.code AND x.trade_date=e.trade_date"
        )
        return sql, [lo, hi] + ([codes] if codes is not None else [])

    def aggregate(self, codes=None):
        sql, params = self.missing_sql(codes)
        return self.c.query_df(
            "SELECT code,count(*) missing_days,min(trade_date) date_start,max(trade_date) date_end "
            f"FROM ({sql}) gaps GROUP BY code ORDER BY code",
            params,
        )

    def dates(self, code):
        sql, params = self.missing_sql([code])
        return [
            pd.Timestamp(x).date()
            for x in self.c.query_df(sql + " ORDER BY trade_date", params).trade_date
        ]

    def issues(self):
        rows = []
        for row in self.aggregate().itertuples():
            detail = {
                "message": f"全历史日线缺失 {row.missing_days} 个交易日（{row.date_start:%Y-%m-%d}~{row.date_end:%Y-%m-%d}），未取得停牌证据",
                "scope": "configured_history_and_older_stored_history_including_delisted",
                "missing_days": int(row.missing_days),
                "date_start": str(row.date_start)[:10],
                "date_end": str(row.date_end)[:10],
            }
            rows.append(
                {
                    "code": row.code,
                    "trade_date": None,
                    "issue_type": "history_data_gap",
                    "detail": json.dumps(detail, ensure_ascii=False),
                }
            )
        return rows
