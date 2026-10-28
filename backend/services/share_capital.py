"""逐日股本及市值合并：同日事实×原始价格优先，接口值核验与兜底。"""

from __future__ import annotations

from contextlib import nullcontext
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

        return " OR ".join(f"({sql})" for sql in capital_predicates(include_sources=True).values())

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

    def merge(self, frame: pd.DataFrame, source: str, *, reported=False,
              _in_transaction: bool = False) -> int:
        """只接收已有行情日期的有效股本；逐日报告优先，事件比较生效日；冲突不擦除已有有效事实。"""
        if frame is None or frame.empty:
            return 0
        df = frame.copy()
        df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
        df = df.drop_duplicates(["code", "trade_date"], keep="last")
        # 每批只读一次目标股票日线，同时获得真实最新日期；避免每个字段重复扫大表。
        # 日常通常只合并一天；按目标日期取价格，最新日单独聚合，避免每股装载十年
        # 行情到 pandas。历史补采同样使用真实目标键，最新投影边界保持不变。
        with self.c.temp_view(df[["code", "trade_date"]], prefix="share_targets") as targets:
            market = self.c.query_df(
                "WITH latest AS (SELECT code,max(trade_date) latest_date FROM daily_bar "
                f"WHERE code IN (SELECT code FROM {targets}) GROUP BY code) "
                f"SELECT b.code,b.trade_date,b.close AS _raw_close,l.latest_date FROM {targets} t "
                "JOIN daily_bar b USING(code,trade_date) JOIN latest l USING(code)"
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
        # 日线批次调用方已持有同连接事务，股本与行情必须一起提交或回滚。
        transaction = nullcontext() if _in_transaction else self.c.transaction()
        with transaction, self.c.temp_view(df[cols], prefix="share_input") as t:
            bounds = [df.trade_date.min(), df.trade_date.max()]
            previous = self.c.query_df(
                f"SELECT v.code,v.trade_date,s.total_share,s.float_share,m.total_mv,m.float_mv,"
                f"m.reported_total_mv,m.reported_float_mv,m.reported_total_close,m.reported_float_close FROM {t} v "
                "LEFT JOIN (SELECT * FROM stock_share_capital_daily "
                "WHERE trade_date BETWEEN ? AND ?) s USING(code,trade_date) "
                "LEFT JOIN (SELECT * FROM daily_metrics "
                "WHERE trade_date BETWEEN ? AND ?) m USING(code,trade_date)",
                bounds * 2,
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
                    f"coalesce(m.reported_{field}_mv,CASE WHEN NOT coalesce(starts_with(m.{field}_mv_source,'computed:'),false) THEN m.{field}_mv END)>0 "
                    f"AND abs(coalesce(m.reported_{field}_mv,CASE WHEN NOT coalesce(starts_with(m.{field}_mv_source,'computed:'),false) THEN m.{field}_mv END)-{{share}}*v._raw_close)<=greatest(abs(coalesce(m.reported_{field}_mv,m.{field}_mv))*{MV_REL_TOLERANCE},1)"
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

    @staticmethod
    def _calculation_valid(field, price="b.close"):
        """有效股本和本地未复权收盘价才可计算；来源公告日不作门槛。"""
        return (
            f"s.{field}_share>0 AND s.{field}_effective_date<=s.trade_date "
            f"AND s.{field}_source IS NOT NULL AND {price}>0 AND isfinite({price}) "
            + ("AND (s.total_share IS NULL OR s.float_share<=s.total_share) " if field == "float" else "")
        )

    @staticmethod
    def _computed_source(field):
        prefix = "computed:a_price:" if field == "total" else "computed:"
        return f"'{prefix}'||s.{field}_source"

    def recalculate_missing(self, codes=None, *, ctx=None) -> dict:
        """统一补缺及刷新已有市值，按股票分批，避免加载千万日线到内存。"""
        if codes is None:
            codes = self.c.query_df("SELECT DISTINCT code FROM daily_bar ORDER BY code").code.tolist()
        codes = list(dict.fromkeys(codes))
        result = {"target": 0, "ok": 0, "fail": 0, "total_mv_filled": 0,
                  "float_mv_filled": 0, "rows_recalculated": 0}
        for offset in range(0, len(codes), 200):
            if ctx:
                ctx.check_cancel()
            batch = codes[offset:offset + 200]
            predicates = []
            for field in ("total", "float"):
                col = f"{field}_mv"
                valid = self._calculation_valid(field)
                expected = (f"CASE WHEN {valid} THEN s.{field}_share*b.close "
                            f"ELSE coalesce(m.reported_{col},CASE WHEN NOT coalesce("
                            f"starts_with(m.{col}_source,'computed:'),false) AND m.{col}>0 "
                            f"AND isfinite(m.{col}) THEN m.{col} END) END")
                predicates.extend([
                    f"m.{col} IS DISTINCT FROM ({expected})",
                    f"(({valid}) AND m.{col}_source IS DISTINCT FROM ({self._computed_source(field)}))",
                    (f"(m.reported_{col} IS NULL AND m.{col}>0 AND isfinite(m.{col}) "
                     f"AND NOT coalesce(starts_with(m.{col}_source,'computed:'),false))"),
                ])
            values = self.c.query_df(
                "SELECT b.code,b.trade_date,b.close _raw_close,s.total_share,s.float_share,m.total_mv,m.float_mv "
                "FROM daily_bar b LEFT JOIN stock_share_capital_daily s USING(code,trade_date) "
                "LEFT JOIN daily_metrics m USING(code,trade_date) "
                "WHERE b.code IN (SELECT unnest(?::VARCHAR[])) AND (" + " OR ".join(predicates) + ")",
                [batch],
            )
            if not values.empty:
                with self.c.transaction(), self.c.temp_view(values, prefix="capital_recalculate") as view:
                    self._merge_market_values(values, view, "recalculate", False)
                    self._log_changes(values.drop(columns=["_raw_close"]), "a_price_recalculate")
                    filled = self.c.query_df(
                        "SELECT count(*) FILTER(WHERE v.total_mv IS NULL AND m.total_mv IS NOT NULL) total_filled,"
                        "count(*) FILTER(WHERE v.float_mv IS NULL AND m.float_mv IS NOT NULL) float_filled "
                        f"FROM {view} v LEFT JOIN daily_metrics m USING(code,trade_date)"
                    ).iloc[0]
                    count = int(values.code.nunique())
                    result["target"] += count
                    result["ok"] += count
                    result["rows_recalculated"] += len(values)
                    result["total_mv_filled"] += int(filled.total_filled)
                    result["float_mv_filled"] += int(filled.float_filled)
            if ctx:
                ctx.progress(min(offset + len(batch), len(codes)) / max(len(codes), 1),
                             f"市值统一重算：已检查 {min(offset + len(batch), len(codes))}/{len(codes)} 只股票")
        return result

    def _log_changes(self, previous, source):
        bounds = [previous.trade_date.min(), previous.trade_date.max()]
        with self.c.temp_view(previous, prefix="capital_previous") as previous_view:
            changed = self.c.query_df(
                f"SELECT count(*) n,min(p.trade_date) lo,max(p.trade_date) hi FROM {previous_view} p "
                "LEFT JOIN (SELECT * FROM stock_share_capital_daily "
                "WHERE trade_date BETWEEN ? AND ?) s USING(code,trade_date) "
                "LEFT JOIN (SELECT * FROM daily_metrics "
                "WHERE trade_date BETWEEN ? AND ?) m USING(code,trade_date) WHERE "
                "p.total_share IS DISTINCT FROM s.total_share OR p.float_share IS DISTINCT FROM s.float_share "
                "OR p.total_mv IS DISTINCT FROM m.total_mv OR p.float_mv IS DISTINCT FROM m.float_mv"
                + "".join(f" OR p.{col} IS DISTINCT FROM m.{col}" for col in
                          ("reported_total_mv", "reported_float_mv", "reported_total_close", "reported_float_close")
                          if col in previous), bounds * 2,
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
        # 显式日期边界让小批增量裁剪历史行组；键关联仍决定实际读写对象。
        bounds = [df.trade_date.min(), df.trade_date.max()]
        # 先保全旧接口值，随后写入本次接口证据；计算值绝不归档为接口值。
        for field in ("total", "float"):
            col = f"{field}_mv"
            self.c.execute(
                f"UPDATE daily_metrics m SET reported_{col}=m.{col}, "
                f"reported_{col}_source=coalesce(m.{col}_source,'legacy_unknown') "
                f"FROM {share_view} v WHERE m.code=v.code AND m.trade_date=v.trade_date "
                f"AND m.reported_{col} IS NULL AND m.{col}>0 AND isfinite(m.{col}) "
                f"AND NOT coalesce(starts_with(m.{col}_source,'computed:'),false)"
            )
            if reported and col in df:
                values = df[["code", "trade_date", col]].copy()
                values[col] = pd.to_numeric(values[col], errors="coerce")
                values["valuation_close"] = pd.to_numeric(df.get("valuation_close"), errors="coerce")
                values.loc[~(values.valuation_close.gt(0) & np.isfinite(values.valuation_close)), "valuation_close"] = np.nan
                values = values[np.isfinite(values[col]) & (values[col] > 0)]
                with self.c.temp_view(values, prefix="reported_mv") as t:
                    self.c.execute(
                        f"INSERT INTO daily_metrics (code,trade_date,reported_{col},reported_{col}_source,reported_{field}_close) "
                        f"SELECT code,trade_date,{col},?,valuation_close FROM {t} "
                        f"ON CONFLICT (code,trade_date) DO UPDATE SET reported_{col}=excluded.reported_{col}, "
                        f"reported_{col}_source=excluded.reported_{col}_source, "
                        f"reported_{field}_close=excluded.reported_{field}_close", [source],
                    )
            valid = self._calculation_valid(field, "v._raw_close")
            # 每次根据当前输入重新决策：可计算则统一计算，不可计算才退回留存接口值。
            self.c.execute(
                f"INSERT INTO daily_metrics (code,trade_date,{col},{col}_source) "
                f"SELECT v.code,v.trade_date,CASE WHEN {valid} THEN s.{field}_share*v._raw_close "
                f"ELSE m.reported_{col} END,CASE WHEN {valid} THEN {self._computed_source(field)} "
                f"ELSE m.reported_{col}_source END FROM {share_view} v "
                "LEFT JOIN (SELECT * FROM stock_share_capital_daily "
                "WHERE trade_date BETWEEN ? AND ?) s USING(code,trade_date) "
                "LEFT JOIN (SELECT * FROM daily_metrics "
                "WHERE trade_date BETWEEN ? AND ?) m USING(code,trade_date) "
                f"ON CONFLICT (code,trade_date) DO UPDATE SET {col}=excluded.{col}, "
                f"{col}_source=excluded.{col}_source", bounds * 2,
            )
