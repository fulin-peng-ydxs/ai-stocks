"""逐日股本及市值合并：原始价格、同日事实、源端市值优先。"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd

from backend.dataquality.checker import MV_REL_TOLERANCE
from backend.storage.repository import MarketRepository


class ShareCapitalService:
    """所有采集路径共用的股本写入和最新投影边界。"""

    def __init__(self, client):
        self.c = client
        self.repo = MarketRepository(client)

    @staticmethod
    def review_predicate():
        """缺失和非空不一致共用同一选择条件；容差与市值质检一致。"""
        from backend.services.capital_quality import capital_predicates

        return " OR ".join(f"({sql})" for sql in capital_predicates().values())

    def review_candidates(self, start, end, *, codes=None, limit=50, interval_days=7):
        """历史缺口公平轮询；复用采集日志持久化尝试时间，不让无变化复查刷新数据版本。"""
        condition = "AND b.code IN (SELECT unnest(?::VARCHAR[]))" if codes else ""
        # data_update_log 使用本机无时区时间，重试截止时间保持相同口径。
        now = datetime.now()  # noqa: DTZ005 -- 与既有日志字段保持同一时间口径
        params = [start, end] + ([codes] if codes else []) + [now, interval_days, limit]
        return self.c.query_df(
            "WITH candidates AS (SELECT b.code,count(*) issue_rows,min(b.trade_date) issue_start,"
            "max(b.trade_date) issue_end FROM daily_bar b "
            "LEFT JOIN stock_share_capital_daily s USING(code,trade_date) "
            "LEFT JOIN daily_metrics m USING(code,trade_date) WHERE b.trade_date BETWEEN ? AND ? "
            f"AND (({self.review_predicate()}) OR b.code IN (SELECT code FROM stock_share_capital_event "
            "WHERE active AND (effective_date IS NULL OR total_share<=0 OR float_share<0 OR float_share>total_share))) "
            f"{condition} GROUP BY b.code), "
            "logs AS (SELECT split_part(source,':',2) code,updated_at,status,date_start,date_end "
            "FROM data_update_log WHERE starts_with(source,'capital_review:') "
            "OR starts_with(source,'capital_collect:')), "
            "attempts AS (SELECT c.code,max(l.updated_at) last_attempt,arg_max(l.status,l.updated_at) status "
            "FROM candidates c JOIN logs l ON l.code=c.code AND l.date_start<=c.issue_start "
            "AND l.date_end>=c.issue_end GROUP BY c.code) "
            "SELECT c.* FROM candidates c LEFT JOIN attempts a USING(code) "
            "WHERE a.last_attempt IS NULL OR a.last_attempt <= ?::TIMESTAMP - "
            "(CASE WHEN a.status='failed' THEN 1 ELSE ? END)*INTERVAL '1 day' "
            "ORDER BY a.last_attempt NULLS FIRST,c.code LIMIT ?", params,
        )

    def merge_verified(self, records: list[dict], codes: list[str]) -> int:
        """将逐条核验的公告或交易所日统计作为指定日期事实导入；证据随异步任务参数持久保存。"""
        from backend.services.stock_ingest import normalize_verified_share_facts

        facts = normalize_verified_share_facts(records, codes)
        df = pd.DataFrame(facts)
        df["trade_date"] = pd.to_datetime(df.trade_date).dt.date
        # 先验证整批，避免不存在的交易日被普通合并静默过滤；只改总股本。
        with self.c.temp_view(df, prefix="verified_share") as t:
            invalid = self.c.query_df(
                f"SELECT v.code,v.trade_date FROM {t} v "
                "LEFT JOIN daily_bar b USING(code,trade_date) "
                "LEFT JOIN stock_share_capital_daily s USING(code,trade_date) "
                "WHERE b.code IS NULL OR s.float_share>v.total_share"
            )
        if not invalid.empty:
            raise ValueError("公告股本日期缺少行情或总股本小于现有流通股本，整批未导入")
        df["total_effective_date"] = df.effective_date
        df["total_available_date"] = df.available_date
        return self.merge(df, "verified_notice")

    def merge(self, frame: pd.DataFrame, source: str, *, reported=False) -> int:
        """只接收已有行情日期的有效股本；逐日报告优先，事件比较生效日；冲突不擦除已有有效事实。"""
        if frame is None or frame.empty:
            return 0
        df = frame.copy()
        df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
        df = df.drop_duplicates(["code", "trade_date"], keep="last")
        codes = df.code.unique().tolist()
        # 每批只读一次目标股票日线，同时获得真实最新日期；避免每个字段重复扫大表。
        condition = "code=?" if len(codes) == 1 else "code IN (SELECT unnest(?::VARCHAR[]))"
        market = self.c.query_df(
            "SELECT code,trade_date,close AS _raw_close, "
            f"max(trade_date) OVER (PARTITION BY code) AS latest_date FROM daily_bar WHERE {condition}",
            codes if len(codes) == 1 else [codes],
        )
        if market.empty:
            return 0
        latest = market[["code", "latest_date"]].drop_duplicates()
        market["trade_date"] = pd.to_datetime(market.trade_date).dt.date
        df = df.merge(
            market[["code", "trade_date", "_raw_close"]], on=["code", "trade_date"], how="inner"
        )
        if df.empty:
            return 0
        for field in ("total", "float"):
            col = f"{field}_share"
            value = pd.to_numeric(
                df.get(col, pd.Series(index=df.index, dtype=float)), errors="coerce"
            )
            value = value.round()
            df[col] = value.where(np.isfinite(value) & (value > 0) & (value < 9e18))
            for suffix in ("effective_date", "available_date"):
                name = f"{field}_{suffix}"
                df[name] = pd.to_datetime(df.get(name, df.trade_date)).dt.date
            df.loc[
                df[f"{field}_effective_date"].isna()
                | (df[f"{field}_effective_date"] > df.trade_date),
                col,
            ] = np.nan
            df[f"{field}_source"] = (
                ("verified_" + df.get("source_type", pd.Series("notice", index=df.index)).fillna("notice")
                 + ":" + df["notice_id"]) if source == "verified_notice" else source
            )
        # A 股流通股数不得超过总股本；保留可单独使用的总股本。
        df.loc[df.float_share > df.total_share, "float_share"] = np.nan
        if source == "sse_conversion":
            df["total_source"] = df["evidence_source"]
        if "total_mv_eligible" not in df:
            df["total_mv_eligible"] = False
        cols = [
            "code",
            "trade_date",
            "total_share",
            "float_share",
            "total_source",
            "float_source",
            "total_effective_date",
            "float_effective_date",
            "total_available_date",
            "float_available_date",
            "total_mv_eligible",
            "_raw_close",
        ]
        with self.c.transaction(), self.c.temp_view(df[cols], prefix="share_input") as t:
            previous = self.c.query_df(
                f"SELECT v.code,v.trade_date,s.total_share,s.float_share,m.total_mv,m.float_mv FROM {t} v "
                "LEFT JOIN stock_share_capital_daily s USING(code,trade_date) "
                "LEFT JOIN daily_metrics m USING(code,trade_date)"
            )
            for field in ("total", "float"):
                names = [
                    f"{field}_share",
                    f"{field}_source",
                    f"{field}_effective_date",
                    f"{field}_available_date",
                ]
                if field == "total":
                    names.append("total_mv_eligible")
                # 已报告逐日事实可校正旧值；事件展开和新浪不得覆盖东财逐日报告。
                if source == "verified_notice":
                    predicate = "TRUE"
                elif source == "eastmoney_daily":
                    predicate = (
                        f"NOT coalesce(starts_with(stock_share_capital_daily.{field}_source,"
                        "'verified_'),false)"
                    )
                elif source == "sse_conversion":
                    predicate = (
                        f"(stock_share_capital_daily.{field}_share IS NULL OR "
                        f"stock_share_capital_daily.{field}_source IN ('eastmoney_events','sina_events') OR "
                        f"starts_with(stock_share_capital_daily.{field}_source,'sse_conversion_100share:')) "
                        f"AND (stock_share_capital_daily.{field}_share IS NULL OR "
                        f"abs(excluded.{field}_share-stock_share_capital_daily.{field}_share)>50) "
                        f"AND (stock_share_capital_daily.{field}_share IS NULL OR "
                        f"excluded.{field}_effective_date>=stock_share_capital_daily.{field}_effective_date) "
                        "AND (stock_share_capital_daily.float_share IS NULL OR "
                        "excluded.total_share>=stock_share_capital_daily.float_share)"
                    ) if field == "total" else "FALSE"
                elif source == "sina_daily":
                    predicate = (
                        f"stock_share_capital_daily.{field}_share IS NULL OR "
                        f"stock_share_capital_daily.{field}_source IN ('sina_daily','eastmoney_events','sina_events')"
                    )
                elif source == "eastmoney_events":
                    predicate = (
                        f"stock_share_capital_daily.{field}_share IS NULL OR "
                        f"stock_share_capital_daily.{field}_source='eastmoney_events' OR "
                        f"(stock_share_capital_daily.{field}_source='sina_events' AND "
                        f"(excluded.{field}_effective_date>=stock_share_capital_daily.{field}_effective_date OR "
                        f"abs(excluded.{field}_share-stock_share_capital_daily.{field}_share)<=5))"
                    )
                    if field == "total":
                        # 较新精确事件可校准较旧转股统计；统计未更新时不能把旧股数沿用到新变动后。
                        predicate += (
                            " OR (starts_with(stock_share_capital_daily.total_source,'sse_conversion_100share:') "
                            "AND excluded.total_effective_date>=stock_share_capital_daily.total_effective_date "
                            ")"
                        )
                elif source == "sina_events":
                    # 变更记录先比较生效日期；同日仍以东财为准，旧主源不能压住新变动。
                    predicate = (
                        f"stock_share_capital_daily.{field}_share IS NULL OR "
                        f"stock_share_capital_daily.{field}_source='sina_events' OR "
                        f"(stock_share_capital_daily.{field}_source='eastmoney_events' AND "
                        f"excluded.{field}_effective_date>stock_share_capital_daily.{field}_effective_date AND "
                        f"abs(excluded.{field}_share-stock_share_capital_daily.{field}_share)>5)"
                    )
                else:
                    predicate = (
                        f"stock_share_capital_daily.{field}_share IS NULL OR "
                        f"stock_share_capital_daily.{field}_source = '{source}'"
                    )
                if field == "float" and source in ("sina_daily", "sina_events"):
                    # 新的备用股数与已知总股本冲突时保留旧事实并报告，不先写入再清空。
                    predicate = (f"({predicate}) AND (stock_share_capital_daily.total_share IS NULL OR "
                                 "excluded.float_share<=stock_share_capital_daily.total_share)")
                if source in ("eastmoney_events", "sina_events"):
                    # 新主源变动须撤回备用源更早事件，不能把旧数带过变动日。
                    # 新记录确实无有效股数时撤回旧事件值；公告延迟不撤回历史事实。
                    stale_fallback = (
                        f" OR (s.{field}_source='sina_events' AND "
                        f"s.{field}_effective_date<v.{field}_effective_date)"
                        if source == "eastmoney_events" else ""
                    )
                    self.c.execute(
                        f"UPDATE stock_share_capital_daily s SET {field}_share=NULL "
                        f"FROM {t} v WHERE s.code=v.code AND s.trade_date=v.trade_date "
                        f"AND (s.{field}_source=?{stale_fallback}) AND (v.{field}_effective_date>v.trade_date "
                        f"OR (v.{field}_share IS NULL AND v.{field}_effective_date IS NOT NULL))",
                        [source],
                    )
                confirmation = (
                    f"m.{field}_mv>0 AND NOT coalesce(starts_with(m.{field}_mv_source,'computed:'),false) "
                    f"AND abs(m.{field}_mv-{{share}}*v._raw_close)<=greatest(abs(m.{field}_mv)*{MV_REL_TOLERANCE},1)"
                )
                if source == "eastmoney_events":
                    # 用独立源端市值核验已有股数，不反推股数；避免备用源日期较新但数值错误。
                    self.c.execute(
                        "UPDATE stock_share_capital_daily s SET "
                        + ",".join(f"{name}=v.{name}" for name in names)
                        + f",updated_at=now() FROM {t} v JOIN daily_metrics m USING(code,trade_date) "
                        "WHERE s.code=v.code AND s.trade_date=v.trade_date "
                        f"AND s.{field}_source='sina_events' AND v.{field}_share IS NOT NULL AND ("
                        + confirmation.format(share=f"v.{field}_share") + ") AND NOT ("
                        + confirmation.format(share=f"s.{field}_share") + ")"
                    )
                incoming_filter = ""
                if source == "sina_events":
                    incoming_filter = (
                        " AND NOT EXISTS (SELECT 1 FROM stock_share_capital_daily old "
                        "JOIN daily_metrics m USING(code,trade_date) "
                        f"JOIN {t} v USING(code,trade_date) "
                        "WHERE old.code=s.code AND old.trade_date=s.trade_date "
                        f"AND old.{field}_source='eastmoney_events' AND ("
                        + confirmation.format(share=f"old.{field}_share") + "))"
                    )
                self.c.execute(
                    f"INSERT INTO stock_share_capital_daily (code, trade_date, {', '.join(names)}) "
                    f"SELECT s.code,s.trade_date,{','.join('s.' + n for n in names)} FROM {t} s "
                    f"WHERE s.{field}_share IS NOT NULL " + incoming_filter +
                    " ON CONFLICT (code,trade_date) DO UPDATE SET "
                    + ",".join(f"{n}=excluded.{n}" for n in names)
                    + f", updated_at=now() WHERE {predicate}"
                )
            self.c.execute(
                f"UPDATE stock_share_capital_daily s SET float_share=NULL FROM {t} v "
                "WHERE s.code=v.code AND s.trade_date=v.trade_date AND s.float_share>s.total_share"
            )
            if source in ("eastmoney_events", "sina_events"):
                # 仅保留股份组成证据；总市值按东财口径统一用总股本乘 A 股原价，不以此标记阻断。
                self.c.execute(
                    f"UPDATE stock_share_capital_daily s SET total_mv_eligible=v.total_mv_eligible FROM {t} v "
                    "WHERE s.code=v.code AND s.trade_date=v.trade_date "
                    "AND NOT coalesce(starts_with(s.total_source,'verified_'),false) "
                    + ("AND abs(s.total_share-v.total_share)<=5 " if source == "sina_events"
                       else "AND s.total_share=v.total_share ")
                    + "AND v.total_effective_date<=v.trade_date "
                    + ("AND v.total_mv_eligible=true" if source == "sina_events" else "")
                )
            with self.c.temp_view(latest, prefix="share_latest") as latest_view:
                self._project_latest(latest_view)
            self._merge_market_values(df, t, source, reported)
            self._log_changes(previous, source)
        return len(df)

    def recalculate_missing(self, codes=None) -> dict:
        """按库内同日股本批量补算；不请求外部源，不改股本及有效源端市值。"""
        condition = "AND b.code IN (SELECT unnest(?::VARCHAR[]))" if codes else ""
        # 只加载有股本可补算的缺口，避免把千万行情加载进 Python。
        values = self.c.query_df(
            "SELECT b.code,b.trade_date,b.close _raw_close,s.total_share,s.float_share,m.total_mv,m.float_mv "
            "FROM daily_bar b JOIN stock_share_capital_daily s USING(code,trade_date) "
            "LEFT JOIN daily_metrics m USING(code,trade_date) WHERE "
            "((m.total_mv IS NULL AND s.total_share>0) OR (m.float_mv IS NULL AND s.float_share>0)) "
            + condition, [codes] if codes else None,
        )
        result = {"target": int(values.code.nunique()), "ok": 0, "fail": 0,
                  "total_mv_filled": 0, "float_mv_filled": 0}
        if values.empty:
            return result
        with self.c.transaction(), self.c.temp_view(values, prefix="capital_recalculate") as view:
            self._merge_market_values(values, view, "recalculate", False)
            self._log_changes(values.drop(columns=["_raw_close"]), "a_price_recalculate")
            filled = self.c.query_df(
                f"SELECT count(*) FILTER(WHERE v.total_mv IS NULL AND m.total_mv IS NOT NULL) total_filled,"
                "count(*) FILTER(WHERE v.float_mv IS NULL AND m.float_mv IS NOT NULL) float_filled "
                f"FROM {view} v LEFT JOIN daily_metrics m USING(code,trade_date)"
            ).iloc[0]
            result.update(ok=result["target"], total_mv_filled=int(filled.total_filled),
                          float_mv_filled=int(filled.float_filled))
        return result

    def _log_changes(self, previous, source):
        with self.c.temp_view(previous, prefix="capital_previous") as previous_view:
            changed = self.c.query_df(
                f"SELECT count(*) n,min(p.trade_date) lo,max(p.trade_date) hi FROM {previous_view} p "
                "LEFT JOIN stock_share_capital_daily s USING(code,trade_date) "
                "LEFT JOIN daily_metrics m USING(code,trade_date) WHERE "
                "p.total_share IS DISTINCT FROM s.total_share OR p.float_share IS DISTINCT FROM s.float_share "
                "OR p.total_mv IS DISTINCT FROM m.total_mv OR p.float_mv IS DISTINCT FROM m.float_mv"
            ).iloc[0]
        if changed.n:
            # 修订与数据同事务提交；读取端用现有日志指纹识别新输入，幂等补采不刷版本。
            self.repo.log_update("stock_share_capital_daily", source,
                                 pd.Timestamp(changed.lo).date(), pd.Timestamp(changed.hi).date(),
                                 int(changed.n), "success", "股本/市值实际值变更")

    def _project_latest(self, latest_view):
        # 只投影真实最新行情日；旧范围回填与部分字段缺失不会冒充最新事实。
        for field in ("total", "float"):
            self.c.execute(
                f"UPDATE stock_basic b SET {field}_share=s.{field}_share, "
                f"{field}_share_date=s.trade_date FROM stock_share_capital_daily s "
                f"JOIN {latest_view} l ON s.code=l.code AND s.trade_date=l.latest_date "
                "WHERE b.code=s.code "
                f"AND (s.{field}_share IS NOT NULL OR b.{field}_share_date=s.trade_date) "
                f"AND (b.{field}_share_date IS NULL OR b.{field}_share_date<=s.trade_date)"
            )

    def _merge_market_values(self, df, share_view, source, reported):
        if reported:
            for field in ("total", "float"):
                col = f"{field}_mv"
                if col not in df:
                    continue
                values = df[["code", "trade_date", col]].copy()
                values[col] = pd.to_numeric(values[col], errors="coerce")
                values = values[np.isfinite(values[col]) & (values[col] > 0)]
                with self.c.temp_view(values, prefix="reported_mv") as t:
                    self.c.execute(
                        f"INSERT INTO daily_metrics (code,trade_date,{col},{col}_source) "
                        f"SELECT v.code,v.trade_date,v.{col},? FROM {t} v "
                        f"ON CONFLICT (code,trade_date) DO UPDATE SET {col}=excluded.{col}, "
                        f"{col}_source=excluded.{col}_source",
                        [source],
                    )
        # 计算值仅补空/非正值或刷新已有计算值，永不覆盖有效源端值与来源未知旧值。
        for field in ("total", "float"):
            col = f"{field}_mv"
            self.c.execute(
                f"UPDATE daily_metrics m SET {col}=NULL,{col}_source=NULL "
                f"FROM stock_share_capital_daily s JOIN {share_view} v USING(code,trade_date) "
                "WHERE m.code=s.code AND m.trade_date=s.trade_date "
                f"AND starts_with(m.{col}_source,'computed:') AND "
                f"(s.{field}_share IS NULL"
                + ")"
            )
            self.c.execute(
                f"INSERT INTO daily_metrics (code,trade_date,{col},{col}_source) "
                f"SELECT s.code,s.trade_date,s.{field}_share*v._raw_close,"
                + ("'computed:a_price:'" if field == "total" else "'computed:'")
                + f"||s.{field}_source "
                "FROM stock_share_capital_daily s "
                f"JOIN {share_view} v USING(code,trade_date) "
                f"WHERE s.{field}_share>0 AND v._raw_close>0 AND isfinite(v._raw_close) "
                f"ON CONFLICT (code,trade_date) DO UPDATE SET {col}=excluded.{col}, "
                f"{col}_source=excluded.{col}_source WHERE daily_metrics.{col} IS NULL "
                f"OR daily_metrics.{col}<=0 OR NOT isfinite(daily_metrics.{col}) OR starts_with(daily_metrics.{col}_source,'computed:')"
            )

        # 跨源口径冲突时撤回计算值，保护既有源端/未知来源值；两项先算完再校验，
        # 避免原始价格修订时拿旧的另一项市值阻挡正确更新。
        self.c.execute(
            "UPDATE daily_metrics m SET "
            "total_mv=CASE WHEN starts_with(total_mv_source,'computed:') THEN NULL ELSE m.total_mv END, "
            "float_mv=CASE WHEN starts_with(float_mv_source,'computed:') THEN NULL ELSE m.float_mv END, "
            "total_mv_source=CASE WHEN starts_with(total_mv_source,'computed:') THEN NULL ELSE total_mv_source END, "
            "float_mv_source=CASE WHEN starts_with(float_mv_source,'computed:') THEN NULL ELSE float_mv_source END "
            f"FROM {share_view} v WHERE m.code=v.code AND m.trade_date=v.trade_date "
            f"AND m.total_mv < m.float_mv*(1-{MV_REL_TOLERANCE})"
        )
