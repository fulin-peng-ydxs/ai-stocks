"""股本原始事件归档及统一逐日事实重建。"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

import numpy as np
import pandas as pd

from backend.storage.repository import MarketRepository


def event_date_basis(reason: object) -> str:
    """原始接口日期一律表示该条股本记录的适用起点，不按原因文字猜测日期含义。"""
    return "source_record"


def historical_joins() -> str:
    """展示和质检直接读取与指标、选股、回测相同的逐日事实。"""
    return (
        "LEFT JOIN stock_share_capital_daily s ON s.code=b.code AND s.trade_date=b.trade_date "
        "LEFT JOIN daily_metrics m ON m.code=b.code AND m.trade_date=b.trade_date "
    )


class ShareCapitalHistoryService:
    def __init__(self, client):
        self.c = client

    def record_events(self, code, events, source):
        """完整保存源记录（含未公开日期和无效数值），同源修订保留旧版本。"""
        if events is None or events.empty:
            return 0
        raw = json.loads(events.to_json(orient="records", date_format="iso", force_ascii=False))
        now = datetime.now()  # noqa: DTZ005 -- 与项目 DuckDB 日志时间一致
        rows = []
        for item in raw:
            payload = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            identity = hashlib.sha256(f"{code}|{source}|{payload}".encode()).hexdigest()

            def day(key, record=item):
                value = pd.to_datetime(record.get(key), errors="coerce")
                return None if pd.isna(value) else value.date()

            def number(key, record=item):
                value = pd.to_numeric(record.get(key), errors="coerce")
                return (
                    round(value)
                    if pd.notna(value) and np.isfinite(value) and abs(value) < 9e18
                    else None
                )

            rows.append(
                {
                    "event_id": identity,
                    "code": code,
                    "source": source,
                    "effective_date": day("END_DATE"),
                    "available_date": day("NOTICE_DATE"),
                    "date_basis": event_date_basis(item.get("CHANGE_REASON")),
                    "change_reason": item.get("CHANGE_REASON"),
                    "total_share": number("TOTAL_SHARES"),
                    "float_share": number("LISTED_A_SHARES"),
                    "raw_payload": payload,
                    "active": True,
                    "first_seen_at": now,
                    "last_seen_at": now,
                }
            )
        df = pd.DataFrame(rows).drop_duplicates("event_id")
        previous = set(
            self.c.query_df(
                "SELECT event_id FROM stock_share_capital_event WHERE code=? AND source=? AND active",
                [code, source],
            )["event_id"]
        )
        with self.c.transaction(), self.c.temp_view(df, prefix="capital_events") as view:
            self.c.execute(
                "UPDATE stock_share_capital_event SET active=false WHERE code=? AND source=?",
                [code, source],
            )
            self.c.execute(
                f"INSERT INTO stock_share_capital_event SELECT * FROM {view} "
                "ON CONFLICT(event_id) DO UPDATE SET active=true,last_seen_at=excluded.last_seen_at, date_basis=excluded.date_basis"
            )
            if previous != set(df.event_id):
                MarketRepository(self.c).log_update(
                    "stock_share_capital_event",
                    "raw_events:" + code,
                    None,
                    None,
                    len(df),
                    "success",
                )
        return len(df)

    def rebuild(self, code, *, apply_events=False):
        """从已保存接口记录重建统一逐日股本；普通采集只清理旧版展示补充。"""
        count = 0
        if apply_events:
            from backend.datasource.share_capital import expand_equity_events
            from backend.services.share_capital import ShareCapitalService

            rows = self.c.query_df(
                "SELECT source,raw_payload FROM stock_share_capital_event WHERE code=? AND active "
                "ORDER BY effective_date,available_date,event_id",
                [code],
            )
            dates = self.c.query_df(
                "SELECT trade_date FROM daily_bar WHERE code=? ORDER BY trade_date", [code]
            ).trade_date
            service = ShareCapitalService(self.c)
            primary = pd.DataFrame()
            for source in ("eastmoney_events", "sina_events"):
                raw = pd.DataFrame(
                    [json.loads(x) for x in rows.loc[rows.source.eq(source), "raw_payload"]]
                )
                facts = expand_equity_events(code, raw, dates)
                if source == "eastmoney_events":
                    primary = facts
                elif not facts.empty and not primary.empty:
                    for field in ("total", "float"):
                        stale = pd.to_datetime(facts[field + "_effective_date"]) < pd.to_datetime(
                            primary[field + "_effective_date"]
                        )
                        facts.loc[stale, field + "_share"] = None
                count += service.merge(facts, source)
        # 旧补充表已不参与查询；撤销旧派生值，完整接口原文仍在事件表。
        with self.c.transaction():
            self.c.execute(
                "UPDATE stock_share_capital_event SET date_basis='source_record' "
                "WHERE code=? AND active AND date_basis IS DISTINCT FROM 'source_record'", [code]
            )
            previous = int(
                self.c.query_df(
                    "SELECT count(*) FROM stock_share_capital_history WHERE code=?", [code]
                ).iloc[0, 0]
            )
            if previous:
                self.c.execute("DELETE FROM stock_share_capital_history WHERE code=?", [code])
                MarketRepository(self.c).log_update(
                    "stock_share_capital_history",
                    "unified_daily:" + code,
                    None,
                    None,
                    previous,
                    "success",
                )
        return count

    def rebuild_many(self, codes):
        """日常批量合并的兼容清理；保留旧表撤销审计，避免每只股票重复查空表。"""
        codes = list(dict.fromkeys(codes))
        if not codes:
            return
        with self.c.transaction():
            previous = self.c.query_df(
                "SELECT code,count(*) n FROM stock_share_capital_history "
                "WHERE code IN (SELECT unnest(?::VARCHAR[])) GROUP BY code", [codes])
            self.c.execute(
                "UPDATE stock_share_capital_event SET date_basis='source_record' "
                "WHERE code IN (SELECT unnest(?::VARCHAR[])) AND active "
                "AND date_basis IS DISTINCT FROM 'source_record'", [codes])
            if not previous.empty:
                self.c.execute(
                    "DELETE FROM stock_share_capital_history "
                    "WHERE code IN (SELECT unnest(?::VARCHAR[]))", [codes])
                for row in previous.itertuples():
                    MarketRepository(self.c).log_update(
                        "stock_share_capital_history", "unified_daily:" + row.code,
                        None, None, int(row.n), "success")

    def rebuild_all(self, codes=None, ctx=None):
        """经异步任务重放原始记录；不重复联网、不修改有效源端市值。"""
        from backend.services.capital_quality import CapitalQualityService
        from backend.services.share_capital import ShareCapitalService

        scope = " AND code IN (SELECT unnest(?::VARCHAR[]))" if codes else ""
        targets = self.c.query_df(
            "SELECT DISTINCT code FROM stock_share_capital_event WHERE active"
            + scope
            + " ORDER BY code",
            [codes] if codes else [],
        ).code.tolist()
        checkpoint = getattr(ctx, "checkpoint", {}) or {}
        done = (set(checkpoint.get("event_rebuild_done", []))
                if checkpoint.get("event_rebuild_rule") == "latest_record_precision" else set())
        result = {"target": len(targets), "ok": 0, "skip": 0, "fail": 0, "rows": 0}
        for i, code in enumerate(targets, 1):
            if ctx:
                ctx.check_cancel()
            if code in done:
                result["skip"] += 1
                continue
            result["rows"] += self.rebuild(code, apply_events=True)
            done.add(code)
            result["ok"] += 1
            if ctx:
                ctx.set_checkpoint(event_rebuild_done=sorted(done),
                                   event_rebuild_rule="latest_record_precision")
                ctx.progress(i / max(len(targets), 1) * 0.95, f"历史股本重建 {i}/{len(targets)}")
                if i % 50 == 0:
                    ctx.log(f"历史股本重建 {i}/{len(targets)}")
                    ctx.flush()
        result["recalculated"] = ShareCapitalService(self.c).recalculate_missing(codes)
        result["capital_quality"] = CapitalQualityService(self.c).sync(codes)
        return result
