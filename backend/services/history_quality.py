"""日线全历史应有日期校验；复用交易日历、上市退市边界及确认停牌事实。"""

from __future__ import annotations

import json

import pandas as pd

from backend.common.timeutil import years_before
from backend.config import get_effective_settings


class HistoryQualityService:
    def __init__(self, client):
        self.c = client

    def missing_sql(self, codes=None, *, respect_legacy_ignores=False):
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
            "WITH spans AS (SELECT code,min(trade_date) first_day FROM daily_bar "
            + ("WHERE code IN (SELECT unnest(?::VARCHAR[])) " if codes is not None else "")
            + "GROUP BY code),"
            "expected AS (SELECT s.code,t.trade_date FROM stock_basic s LEFT JOIN spans p USING(code) "
            "JOIN trade_calendar t ON t.is_open AND t.trade_date BETWEEN ? AND ? "
            "AND t.trade_date>=coalesce(s.list_date,p.first_day) "
            "AND (s.delist_date IS NULL OR t.trade_date<s.delist_date) "
            "WHERE (s.code LIKE '%.SH' OR s.code LIKE '%.SZ')" + scope + ") "
            "SELECT e.code,e.trade_date FROM expected e "
            "ANTI JOIN daily_bar b ON b.code=e.code AND b.trade_date=e.trade_date "
            "ANTI JOIN stock_suspension x ON x.code=e.code AND x.trade_date=e.trade_date"
        )
        if respect_legacy_ignores:
            from backend.dataquality.consolidation import RECENT_DAY_SQL, legacy_ignore_sql
            # 旧近端内部缺口忽略不覆盖历史头部、较早日期或最新行情之后的滞后。
            sql += (
                f" WHERE NOT ({legacy_ignore_sql('data_gap', 'e.code')} "
                f"AND e.trade_date>={RECENT_DAY_SQL} "
                "AND e.trade_date BETWEEN (SELECT min(trade_date) FROM daily_bar WHERE code=e.code) "
                "AND (SELECT max(trade_date) FROM daily_bar WHERE code=e.code) "
                "AND EXISTS (SELECT 1 FROM stock_basic ls WHERE ls.code=e.code "
                "AND (ls.delist_date IS NULL OR ls.delist_date>(SELECT max(trade_date) FROM daily_bar))))"
            )
        return sql, ([codes] if codes is not None else []) + [lo, hi] + ([codes] if codes is not None else [])

    def aggregate(self, codes=None, *, respect_legacy_ignores=False):
        sql, params = self.missing_sql(codes, respect_legacy_ignores=respect_legacy_ignores)
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

    def issues(self, codes=None):
        rows = []
        for row in self.aggregate(codes, respect_legacy_ignores=True).itertuples():
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

    def sync(self, codes):
        """定向修复后刷新剩余日期；不重扫全市场，也不改变其它股票台账。"""
        from backend.services.data_report import DataIntegrityReport
        rows = self.issues(codes)
        with self.c.transaction():
            DataIntegrityReport(self.c)._upsert_scan_issues(rows, ("history_data_gap",), codes=codes)
