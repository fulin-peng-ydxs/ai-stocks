"""数据完整性体检报告（需求 F-DQ-06 质检报告 / F-STO-04 元数据 / §10.3 数据质量规则）。

全量回填后运行，系统性核查数据完整性，输出结构化报告并写 data_quality_issue：
1. 总览：各表行数、股票数、日期跨度。
2. 交易日历覆盖：窗口内开市日数。
3. 个股覆盖率：每只股票 [首末行情日] 区间内日历开市日 vs 实际行情，找缺口（停牌除外不了，记为疑似）。
4. 关键字段非空：OHLCV、流通市值。
5. 指数覆盖：3 大基准指数 vs 日历。
6. 退市股覆盖：退市股是否有数据、末行情是否接近退市日。
7. 复权跳变 / 异常涨跌幅 抽样汇总。

注意：DuckDB 单写锁——回填进行时本报告无法连库；须等回填结束后运行。
"""

from __future__ import annotations

import json
from datetime import date

import pandas as pd

from backend.common.logging import get_logger
from backend.storage.duckdb_client import DuckDBClient, get_client

log = get_logger("services.data_report")

# 缺口/鲜活判定的近端窗口（DM-D21）：只在近 N 个开市日内判缺口与滞后；
# 更早的历史空洞默认即停牌（老数据稳定，真漏采早暴露），不反复上报、不扣分。
GAP_WINDOW_DAYS = 90

# 覆盖鲜活全景缓存（M2.9.4）：概览页一次会连打 overview/stock-quality/hub 三个接口，
# 各自都要 _coverage_frame（全市场扫描）。用「数据变更签名」做单条缓存，让同一页的多次调用复用；
# 签名 = (最新交易日, 未解决问题数, 日线总行数, 停牌确认数, 窗口)，任一数据变更即失效重算（不会读到陈旧）。
_FRAME_CACHE: dict = {"key": None, "frame": None, "latest": None}


class DataIntegrityReport:
    def __init__(self, client: DuckDBClient | None = None):
        self.c = client or get_client()

    def _scalar(self, sql: str, params: list | None = None):
        return self.c.query_df(sql, params or []).iloc[0, 0]

    # ── 1. 总览 ──
    def overview(self) -> dict:
        tables = ["stock_basic", "daily_bar", "daily_metrics", "index_bar",
                  "trade_calendar", "data_quality_issue", "data_update_log"]
        counts = {t: int(self._scalar(f"SELECT count(*) FROM {t}")) for t in tables}
        # 板块表（板块概念需求 R6/R21）：仅当表已建才统计，避免未初始化时 COUNT 报错
        try:
            from backend.storage.ddl import list_tables
            have = set(list_tables(self.c))
        except Exception:  # noqa: BLE001
            have = set()
        for bt in ("board_dict", "board_member", "board_bar", "board_fund_flow"):
            counts[bt] = int(self._scalar(f"SELECT count(*) FROM {bt}")) if bt in have else 0
        span = self.c.query_df(
            "SELECT min(trade_date) lo, max(trade_date) hi, count(DISTINCT code) codes FROM daily_bar"
        ).iloc[0]
        live = int(self._scalar("SELECT count(*) FROM stock_basic WHERE delist_date IS NULL"))
        delisted = int(self._scalar("SELECT count(*) FROM stock_basic WHERE delist_date IS NOT NULL"))
        return {
            "row_counts": counts,
            "bar_date_min": str(span["lo"]),
            "bar_date_max": str(span["hi"]),
            "distinct_codes_with_bars": int(span["codes"]),
            "stock_basic_live": live,
            "stock_basic_delisted": delisted,
        }

    # ── 覆盖鲜活单一口径（DM-D20）：scan / quality_model / stock_quality 共用 ──
    # 注：旧 gaps_summary（读已废弃的 daily_bar.is_suspended 死列）已于 M2.9.5 删除，
    #     缺口口径统一到下方 _coverage_frame（减 stock_suspension 确认停牌）。
    def _recent_open_days(self, latest: date, window_days: int) -> tuple[list[date], date | None]:
        """近 window_days 个开市日（含 latest），升序返回 + window_lo。"""
        df = self.c.query_df(
            "SELECT trade_date FROM trade_calendar WHERE is_open AND trade_date <= ? "
            "ORDER BY trade_date DESC LIMIT ?", [latest, int(window_days)])
        days = sorted(pd.Timestamp(d).date() for d in df["trade_date"])
        return days, (days[0] if days else None)

    def _coverage_frame(self, window_days: int = GAP_WINDOW_DAYS):
        """每只在市股票的覆盖鲜活全景（DM-D20 唯一口径）。

        在近 window_days 个开市日窗口内，对每只在市股票：
          missing = 窗口内开市日 ∩ [本股存续起, 全局最新] − 已有行情 − 已确认停牌(stock_suspension)
          - 内部缺口 gap（疑似漏采）：missing 中 ≤ 本股最新行情日的（历史空洞，可重采反向确认）
          - 尾部滞后 stale：missing 中 > 本股最新行情日的（未更新到最新，可增量补尾）
        停牌（已确认入 stock_suspension）一律不计入 → 系统收敛。
        L2 字段契约（M2.9.3）：总市值 total_mv 与流通市值 float_mv 都须有（float_mv 供选股池过滤、
        total_mv 供评分引用）；mv_detail 说明缺哪个。

        性能（M2.9.3-E）：不再逐股关联子查询，改为各扫一次的 GROUP BY 聚合 + pandas 合并。
        返回 (DataFrame, latest_trade_date_str)。
        """
        cols = ["code", "name", "latest_date", "is_fresh", "mv_ok", "mv_detail",
                "mv_gap_days", "mv_gap_lo", "mv_gap_hi", "gap_days", "gap_lo",
                "gap_hi", "stale_days", "stale_lo", "l1_open", "l3_open", "open_total"]
        # 数据变更签名缓存：同一页多接口复用，任一数据变更即失效。
        # openi 只数个股 issue 类型（L1-L4），排除板块 issue（code=board_code 不参与个股 frame）——
        # 板块采集写 fund/member 问题不应击穿个股覆盖帧缓存。
        sig = self.c.query_df(
            "SELECT (SELECT max(trade_date) FROM daily_bar) latest, "
            "(SELECT count(*) FROM daily_bar) bars, "
            "(SELECT count(*) FROM daily_metrics) metrics, "
            "(SELECT count(*) FROM data_quality_issue WHERE status='open' "
            "   AND issue_type NOT IN ('board_index_gap','board_member_incomplete',"
            "'board_fund_unmatched','board_fund_missing','board_fund_stale')) openi, "
            "(SELECT count(*) FROM stock_suspension) susp, "
            "(SELECT count(*) FROM daily_metrics WHERE total_mv IS NULL OR float_mv IS NULL) mvnull"
        ).iloc[0]
        # metrics/mvnull 纳入签名：L2 依赖逐日市值缺口，补市值后（bars/issues 可能没变）
        # 须让缓存失效；metrics 变化覆盖 daily_metrics 整行缺失被补齐的场景。
        key = (id(self.c), str(sig["latest"]), int(sig["bars"]),
               int(sig["metrics"]), int(sig["openi"]), int(sig["susp"]),
               int(sig["mvnull"]), int(window_days))
        if _FRAME_CACHE["key"] == key and _FRAME_CACHE["frame"] is not None:
            return _FRAME_CACHE["frame"], _FRAME_CACHE["latest"]
        latest = self._scalar("SELECT max(trade_date) FROM daily_bar")
        if latest is None:
            return pd.DataFrame(columns=cols), None
        latest = pd.Timestamp(latest).date()
        win, win_lo = self._recent_open_days(latest, window_days)
        if win_lo is None:
            return pd.DataFrame(columns=cols), str(latest)
        # 聚合（各一次全表扫描，避免逐股关联子查询）
        span = self.c.query_df(
            "SELECT code, min(trade_date) min_bar, max(trade_date) max_bar FROM daily_bar GROUP BY code")
        span_map = {r["code"]: (r["min_bar"], r["max_bar"]) for _, r in span.iterrows()}
        mv = self.c.query_df(
            "SELECT code, count(*) FILTER (WHERE total_mv IS NOT NULL) tmv, "
            "count(*) FILTER (WHERE float_mv IS NOT NULL) fmv FROM daily_metrics GROUP BY code")
        mv_map = {r["code"]: (int(r["tmv"]), int(r["fmv"])) for _, r in mv.iterrows()}
        # 窗口内逐日市值缺口（L2 统一口径：与 mv_missing/data_gap/stale 同一份 frame、同一窗口）。
        # 以 daily_bar 为基准，daily_metrics 整行缺失、total_mv 缺失、float_mv 缺失都算近端缺口。
        mvgap = self.c.query_df(
            """
            SELECT b.code,
                   count(*) AS g,
                   count(*) FILTER (WHERE m.code IS NULL OR m.total_mv IS NULL) AS total_g,
                   count(*) FILTER (WHERE m.code IS NULL OR m.float_mv IS NULL) AS float_g,
                   count(*) FILTER (
                       WHERE m.code IS NULL OR (m.total_mv IS NULL AND m.float_mv IS NULL)
                   ) AS both_g,
                   min(b.trade_date) AS lo,
                   max(b.trade_date) AS hi
            FROM daily_bar b
            JOIN stock_basic sb ON sb.code = b.code
            LEFT JOIN daily_metrics m ON m.code = b.code AND m.trade_date = b.trade_date
            WHERE sb.delist_date IS NULL
              AND b.trade_date >= ?
              AND (m.code IS NULL OR m.total_mv IS NULL OR m.float_mv IS NULL)
            GROUP BY b.code
            """, [win_lo])
        mvgap_map = {
            r["code"]: (
                int(r["g"]), int(r["total_g"]), int(r["float_g"]), int(r["both_g"]),
                pd.Timestamp(r["lo"]).date(), pd.Timestamp(r["hi"]).date(),
            )
            for _, r in mvgap.iterrows()
        }
        iss = self.c.query_df(
            "SELECT code, count(*) tot, "
            "count(*) FILTER (WHERE issue_type IN ('null_close','ohl_repaired')) l1, "
            "count(*) FILTER (WHERE issue_type IN ('abnormal_change','adj_jump')) l3 "
            "FROM data_quality_issue WHERE status='open' "
            "AND issue_type NOT IN ('board_index_gap','board_member_incomplete',"
            "'board_fund_unmatched','board_fund_missing','board_fund_stale') "
            "GROUP BY code")
        iss_map = {r["code"]: (int(r["tot"]), int(r["l1"]), int(r["l3"])) for _, r in iss.iterrows()}
        stocks = self.c.query_df("SELECT code, name, list_date FROM stock_basic WHERE delist_date IS NULL")
        bars = self.c.query_df("SELECT code, trade_date FROM daily_bar WHERE trade_date >= ?", [win_lo])
        susp = self.c.query_df("SELECT code, trade_date FROM stock_suspension WHERE trade_date >= ?", [win_lo])
        bar_map: dict[str, set] = {c: set(pd.Timestamp(d).date() for d in g["trade_date"])
                                   for c, g in bars.groupby("code", sort=False)}
        susp_map: dict[str, set] = {c: set(pd.Timestamp(d).date() for d in g["trade_date"])
                                    for c, g in susp.groupby("code", sort=False)}
        rows = []
        win_first = str(win[0]) if win else None
        # 列向量迭代（避免 pandas iterrows 在 5000+ 行上的高开销）
        for code, name, ld_raw in zip(stocks["code"].tolist(), stocks["name"].tolist(),
                                      stocks["list_date"].tolist()):
            mn, mx = span_map.get(code, (None, None))
            min_bar = None if mn is None or pd.isna(mn) else pd.Timestamp(mn).date()
            max_bar = None if mx is None or pd.isna(mx) else pd.Timestamp(mx).date()
            tmv, fmv = mv_map.get(code, (0, 0))
            tot, l1, l3 = iss_map.get(code, (0, 0, 0))
            mv_ok = tmv > 0 and fmv > 0
            mvg_days, mvg_total, mvg_float, mvg_both, mvg_lo, mvg_hi = mvgap_map.get(
                code, (0, 0, 0, 0, None, None)
            )
            if mv_ok and mvg_days == 0:
                mv_detail = ""
            elif tmv == 0 and fmv == 0:
                mv_detail = "缺总市值与流通市值"
            elif tmv == 0:
                mv_detail = "缺总市值"
            elif fmv == 0:
                mv_detail = "缺流通市值"
            else:
                parts = []
                if mvg_total:
                    parts.append(f"总市值 {mvg_total} 天")
                if mvg_float:
                    parts.append(f"流通市值 {mvg_float} 天")
                if mvg_both and mvg_both != mvg_total and mvg_both != mvg_float:
                    parts.append(f"二者均缺 {mvg_both} 天")
                mv_detail = f"近端缺{'、'.join(parts)}（{mvg_lo}~{mvg_hi}）"
            base = {"code": code, "name": name, "mv_ok": mv_ok, "mv_detail": mv_detail,
                    "mv_gap_days": mvg_days,
                    "mv_gap_lo": str(mvg_lo) if mvg_lo else None,
                    "mv_gap_hi": str(mvg_hi) if mvg_hi else None,
                    "l1_open": l1, "l3_open": l3, "open_total": tot}
            if min_bar is None:  # 从未有行情：整窗待采集（计为滞后，不细分内部缺口）
                rows.append({**base, "latest_date": None, "is_fresh": False,
                             "gap_days": 0, "gap_lo": None, "gap_hi": None,
                             "stale_days": len(win), "stale_lo": win_first})
                continue
            ld = None if ld_raw is None or pd.isna(ld_raw) else pd.Timestamp(ld_raw).date()
            span_lo = max(min_bar, ld) if ld else min_bar
            lo = max(span_lo, win_lo)
            have = bar_map.get(code, set())
            suspd = susp_map.get(code, set())
            missing = [d for d in win if d >= lo and d not in have and d not in suspd]
            internal = [d for d in missing if d <= max_bar]
            tail = [d for d in missing if d > max_bar]
            rows.append({
                **base, "latest_date": str(max_bar), "is_fresh": len(tail) == 0,
                "gap_days": len(internal),
                "gap_lo": str(internal[0]) if internal else None,
                "gap_hi": str(internal[-1]) if internal else None,
                "stale_days": len(tail), "stale_lo": str(tail[0]) if tail else None,
            })
        frame = pd.DataFrame(rows, columns=cols)
        _FRAME_CACHE.update(key=key, frame=frame, latest=str(latest))
        return frame, str(latest)

    def missing_days_for(self, code: str, window_days: int = GAP_WINDOW_DAYS) -> list[date]:
        """单股窗口内待补的开市日（内部缺口 + 尾部滞后，已减去确认停牌）——供反向重采。"""
        latest = self._scalar("SELECT max(trade_date) FROM daily_bar")
        if latest is None:
            return []
        latest = pd.Timestamp(latest).date()
        win, win_lo = self._recent_open_days(latest, window_days)
        if win_lo is None:
            return []
        span = self.c.query_df(
            "SELECT min(trade_date) lo, max(trade_date) hi FROM daily_bar WHERE code=?", [code]).iloc[0]
        min_bar = None if pd.isna(span["lo"]) else pd.Timestamp(span["lo"]).date()
        ldf = self.c.query_df("SELECT list_date FROM stock_basic WHERE code=?", [code])
        ld = None
        if not ldf.empty and not pd.isna(ldf.iloc[0]["list_date"]):
            ld = pd.Timestamp(ldf.iloc[0]["list_date"]).date()
        lo = win_lo if min_bar is None else max(max(min_bar, ld) if ld else min_bar, win_lo)
        have = set(pd.Timestamp(d).date() for d in self.c.query_df(
            "SELECT trade_date FROM daily_bar WHERE code=? AND trade_date>=?", [code, win_lo])["trade_date"])
        suspd = set(pd.Timestamp(d).date() for d in self.c.query_df(
            "SELECT trade_date FROM stock_suspension WHERE code=? AND trade_date>=?", [code, win_lo])["trade_date"])
        return [d for d in win if d >= lo and d not in have and d not in suspd]

    def confirm_suspension(self, code: str, dates: list[date]) -> int:
        """把"重采后源端仍无数据"的开市日确认为停牌写入 stock_suspension（去重）。"""
        if not dates:
            return 0
        from datetime import datetime
        existing = set(pd.Timestamp(d).date() for d in self.c.query_df(
            "SELECT trade_date FROM stock_suspension WHERE code=?", [code])["trade_date"])
        fresh = [d for d in dates if d not in existing]
        if not fresh:
            return 0
        df = pd.DataFrame({"code": code, "trade_date": fresh, "confirmed_at": datetime.now()})
        with self.c.temp_view(df, "susp") as v:
            self.c.execute(
                f"INSERT INTO stock_suspension (code, trade_date, confirmed_at) "
                f"SELECT code, trade_date, confirmed_at FROM {v}")
        return len(fresh)

    def gapped_codes(self, window_days: int = GAP_WINDOW_DAYS) -> list[str]:
        """窗口内有内部缺口或末尾滞后的在市股代码——批量一次扫描（复用 _coverage_frame 缓存，
        含减去确认停牌），供增量更新收尾按需收口，避免对全市场逐股跑全局查询。"""
        df, _ = self._coverage_frame(window_days)
        if df.empty:
            return []
        mask = (df["gap_days"] > 0) | (df["stale_days"] > 0)
        return df.loc[mask, "code"].tolist()

    # ── 逐股质量（DM-D15 四层明细 + DM-D17 名称搜索；DM-D20 口径统一）──
    def stock_quality(self, codes: list[str] | None = None, keyword: str | None = None,
                      page: int = 1, size: int = 50) -> dict:
        """逐股分层体检，与全局 quality_model 同一 _coverage_frame 口径（保证三处数字一致）。"""
        df, latest_s = self._coverage_frame()
        if codes:
            df = df[df["code"].isin(codes)]
        if keyword:
            kw = keyword.lower()
            df = df[df["code"].str.lower().str.contains(kw, regex=False)
                    | df["name"].str.lower().str.contains(kw, regex=False, na=False)]
        df = df.sort_values("code")
        total = len(df)
        page_df = df.iloc[int((page - 1) * size): int((page - 1) * size + size)]
        out = []
        for _, r in page_df.iterrows():
            l1, l3 = int(r["l1_open"]), int(r["l3_open"])
            gap, stale = int(r["gap_days"]), int(r["stale_days"])
            mv_gap = int(r["mv_gap_days"])
            # L2 统一口径：整股有值（非"从没采过"）且近端无逐日缺口
            l2_ok = bool(r["mv_ok"]) and mv_gap == 0
            out.append({
                "code": r["code"], "name": r["name"], "latest_date": r["latest_date"],
                "is_fresh": bool(r["is_fresh"]), "total_mv_ok": l2_ok, "gap_days": gap,
                "open_issues": int(r["open_total"]),
                "layers": {
                    "L1": {"name_cn": "入库闸门", "ok": l1 == 0, "issues": l1},
                    "L2": {"name_cn": "字段契约", "ok": l2_ok, "issues": 0 if l2_ok else 1,
                           "mv_gap_days": mv_gap, "mv_gap_lo": r["mv_gap_lo"], "mv_gap_hi": r["mv_gap_hi"]},
                    "L3": {"name_cn": "正确性", "ok": l3 == 0, "issues": l3},
                    "L4": {"name_cn": "覆盖鲜活", "ok": gap == 0 and stale == 0,
                           "gap_days": gap, "gap_lo": r["gap_lo"], "gap_hi": r["gap_hi"],
                           "stale_days": stale, "stale_lo": r["stale_lo"],
                           "is_fresh": bool(r["is_fresh"])},
                },
            })
        return {"total": total, "page": page, "size": size,
                "latest_trade_date": latest_s, "list": out}

    # ── 四层质量模型聚合（DM-D15；DM-D20 口径统一）──
    def quality_model(self) -> dict:
        """全局质量全景：评分 + 各层达标 + 缺口汇总，复用 _coverage_frame（与逐股/质检同口径）。"""
        from backend.dataquality.checker import QUALITY_LAYERS
        df, latest_s = self._coverage_frame()
        empty_layers = [{**spec, "pass_stocks": 0, "total": 0, "pass_rate": 1.0, "issues": 0}
                        for spec in QUALITY_LAYERS]
        n = len(df)
        if n == 0:
            return {"score": 100, "latest_trade_date": latest_s, "by_layer": empty_layers,
                    "gaps": {"stocks_with_gap": 0, "gap_days_total": 0, "latest_trade_date": latest_s}}
        # L2 统一口径：整股有值（非"从没采过"）且近端无逐日市值字段缺口（与质检 mv_missing+mv_gap 一致）
        l2_ok = df["mv_ok"] & (df["mv_gap_days"] == 0)
        ok = {
            "L1": df["l1_open"] == 0,
            "L2": l2_ok,
            "L3": df["l3_open"] == 0,
            "L4": (df["gap_days"] == 0) & (df["stale_days"] == 0),
        }
        issues = {
            "L1": int(df["l1_open"].sum()),
            "L2": int((~l2_ok).sum()),
            "L3": int(df["l3_open"].sum()),
            "L4": int(df["gap_days"].sum() + df["stale_days"].sum()),
        }
        by_layer = []
        for spec in QUALITY_LAYERS:
            k = spec["layer"]
            passed = int(ok[k].sum())
            by_layer.append({**spec, "pass_stocks": passed, "total": n,
                             "pass_rate": round(passed / n, 4), "issues": issues[k]})
        all_ok = ok["L1"] & ok["L2"] & ok["L3"] & ok["L4"]
        score = int(round(100 * float(all_ok.sum()) / n))
        gap_mask = (df["gap_days"] > 0) | (df["stale_days"] > 0)
        return {
            "score": score, "latest_trade_date": latest_s, "by_layer": by_layer,
            "gaps": {"stocks_with_gap": int(gap_mask.sum()),
                     "gap_days_total": int(df["gap_days"].sum() + df["stale_days"].sum()),
                     "latest_trade_date": latest_s},
        }

    # ── 2. 交易日历窗口 ──
    def calendar_open_days(self, start: date, end: date) -> int:
        return int(self._scalar(
            "SELECT count(*) FROM trade_calendar WHERE is_open AND trade_date BETWEEN ? AND ?",
            [start, end],
        ))

    # ── 3. 个股覆盖率（找缺口）──
    def coverage(self, min_coverage: float = 0.999, sample_limit: int = 20) -> dict:
        """逐股：[首行情, 末行情] 区间内日历开市日 vs 实际行情，算覆盖率。"""
        df = self.c.query_df(
            """
            WITH bar_span AS (
                SELECT code, min(trade_date) lo, max(trade_date) hi, count(*) AS bars
                FROM daily_bar GROUP BY code
            ),
            expect AS (
                SELECT bs.code, bs.bars, bs.lo, bs.hi,
                       (SELECT count(*) FROM trade_calendar cal
                        WHERE cal.is_open AND cal.trade_date BETWEEN bs.lo AND bs.hi) AS expected
                FROM bar_span bs
            )
            SELECT code, bars, expected, lo, hi,
                   CASE WHEN expected>0 THEN bars*1.0/expected ELSE 1 END AS coverage
            FROM expect
            """
        )
        low = df[df["coverage"] < min_coverage].sort_values("coverage")
        total_expected = int(df["expected"].sum())
        total_bars = int(df["bars"].sum())
        # 缺口 = 停牌日（存续期内开市但无行情）
        df["suspension_days"] = (df["expected"] - df["bars"]).clip(lower=0)
        return {
            "stocks_total": len(df),
            "overall_coverage": round(total_bars / total_expected, 5) if total_expected else 1.0,
            "stocks_below_threshold": len(low),
            "total_suspension_days": int(df["suspension_days"].sum()),
            "stocks_with_suspension": int((df["suspension_days"] > 0).sum()),
            "worst_samples": low.head(sample_limit)[["code", "bars", "expected", "coverage"]].to_dict("records"),
        }

    def _insert_issues(self, issues: list[dict]) -> int:
        """批量写 data_quality_issue（severity 由类型映射，status=open，detected_at=now）。"""
        if not issues:
            return 0
        from datetime import datetime

        from backend.dataquality.checker import severity_for
        now = datetime.now()
        df = pd.DataFrame([{
            "id": self._next_qid(), "code": x["code"], "trade_date": x.get("trade_date"),
            "issue_type": x["issue_type"], "severity": severity_for(x["issue_type"]),
            "status": "open", "detail": x.get("detail", ""), "detected_at": now,
        } for x in issues])
        with self.c.temp_view(df, prefix="qi") as v:
            self.c.execute(
                "INSERT INTO data_quality_issue "
                "(id, code, trade_date, issue_type, severity, status, detail, detected_at) "
                "SELECT id, code, trade_date, issue_type, severity, status, detail, detected_at "
                f"FROM {v}")
        return len(df)

    @staticmethod
    def _active_l3_mask(df: pd.DataFrame) -> pd.Series:
        """Rows that should be actionable for L3 quality checks."""
        trade_date = pd.to_datetime(df["trade_date"])
        listed_seq = df.get("listing_trade_seq")
        if listed_seq is None:
            after_listing_window = pd.Series(True, index=df.index)
        else:
            after_listing_window = listed_seq.isna() | (listed_seq.astype("float64") > 5)
        delist_date = pd.to_datetime(df.get("delist_date"), errors="coerce")
        before_delist = delist_date.isna() | (trade_date < delist_date)
        name = df.get("name")
        gap_days = df.get("gap_days")
        if name is None or gap_days is None:
            retire_entry = pd.Series(False, index=df.index)
        else:
            retire_entry = (
                name.astype(str).str.contains("退", na=False)
                & (pd.to_numeric(gap_days, errors="coerce").fillna(0) > 10)
            )
        return after_listing_window & before_delist & ~retire_entry

    # ── 市场级四层质检（写 data_quality_issue，DM-D20 统一口径）──
    def scan_quality_issues(self, gap_window_days: int = GAP_WINDOW_DAYS) -> dict:
        """四层统一质检：L2 字段契约 / L3 正确性 / L4 覆盖鲜活，写 data_quality_issue。

        L1（入库闸门）由采集即时记录，质检不重复扫；这里覆盖立即质检 + 每日自动任务质检步（同一方法）。
        幂等（DM-D20）：扫描把上轮 **未解决** 的自动扫描类问题（L2/L3/L4）替换为当前快照，
        已 resolved/ignored 的不动 → 反复跑收敛不堆积。停牌（已确认入 stock_suspension）不计入缺口。

        失败保留语义（对齐 scan_board_quality）：DELETE + 全部 INSERT 在同一事务内原子执行，
        扫描中途失败不提交，旧问题保留。事务块内计算持写锁——质检扫描本身全局互斥（verify
        任务独占，无并发写），与板块 scan 的事务替换语义一致。
        """
        from backend.dataquality.checker import SCAN_ISSUE_TYPES
        ph = ",".join("?" * len(SCAN_ISSUE_TYPES))
        # 已「标记为正常/忽略」的不再上报（DM-D22）：L3 按 (股,类型,日期) 精确豁免；
        # L2/L4 按 (股,类型) 整体豁免（缺口/滞后/市值是状态而非单日事件）。
        ig = self.c.query_df(
            "SELECT code, issue_type, trade_date FROM data_quality_issue WHERE status='ignored'")
        ig_exact, ig_coarse = set(), set()
        for _, r in ig.iterrows():
            ig_coarse.add((r["code"], r["issue_type"]))
            td = None if pd.isna(r["trade_date"]) else str(pd.Timestamp(r["trade_date"]).date())
            ig_exact.add((r["code"], r["issue_type"], td))
        with self.c.transaction():
            # 原子替换：DELETE 与后续 INSERT 同一事务，失败回滚保留旧问题（对齐 scan_board_quality）
            self.c.execute(
                f"DELETE FROM data_quality_issue WHERE status='open' AND issue_type IN ({ph})",
                list(SCAN_ISSUE_TYPES))
            # L3：异常涨跌幅（向量化，关联板块上限）
            df = self.c.query_df(
                """
                SELECT *
                FROM (
                    SELECT b.code, b.trade_date, b.pre_close,
                           abs(b.close / b.pre_close - 1) AS chg,
                           COALESCE(sb.price_limit_pct, 0.10) AS lim,
                           sb.name,
                           sb.delist_date,
                           b.trade_date - lag(b.trade_date) OVER (PARTITION BY b.code ORDER BY b.trade_date)
                               AS gap_days,
                           CASE
                               WHEN sb.list_date IS NOT NULL
                                    AND min(b.trade_date) OVER (PARTITION BY b.code)
                                        <= sb.list_date + INTERVAL 30 DAY
                               THEN row_number() OVER (PARTITION BY b.code ORDER BY b.trade_date)
                               ELSE NULL
                           END AS listing_trade_seq
                    FROM daily_bar b LEFT JOIN stock_basic sb ON sb.code = b.code
                    WHERE b.pre_close IS NOT NULL AND b.pre_close > 0
                ) t
                """)
            df = df[self._active_l3_mask(df)]
            bad = df[df["chg"] > df["lim"] + (0.011 / df["pre_close"]).clip(lower=0.005)]
            ab_rows = [
                {"code": r["code"], "trade_date": r["trade_date"], "issue_type": "abnormal_change",
                 "detail": f"涨跌幅 {r['chg']*100:.1f}% 超上限 {r['lim']*100:.0f}%"}
                for _, r in bad.iterrows()
                if (r["code"], "abnormal_change", str(pd.Timestamp(r["trade_date"]).date())) not in ig_exact]
            self._insert_issues(ab_rows)
            adj = self._scan_adj_jump(ignored_exact=ig_exact)
            # L2 + L4：来自统一的覆盖鲜活全景（与 quality_model/stock_quality 同口径）
            frame, _ = self._coverage_frame(gap_window_days)
            l2 = l4_gap = l4_stale = 0
            rows = []
            for _, r in frame.iterrows():
                code = r["code"]
                if not r["mv_ok"] and (code, "mv_missing") not in ig_coarse:
                    rows.append({"code": code, "issue_type": "mv_missing",
                                 "detail": f"{r['mv_detail']}（字段契约不全，需补估值/市值数据）"})
                    l2 += 1
                if int(r["gap_days"]) > 0 and (code, "data_gap") not in ig_coarse:
                    rows.append({"code": code, "trade_date": r["gap_lo"], "issue_type": "data_gap",
                                 "detail": f"近{gap_window_days}个交易日内 {int(r['gap_days'])} 天无行情"
                                           f"（疑似漏采，待重采确认）：{r['gap_lo']}~{r['gap_hi']}"})
                    l4_gap += 1
                if int(r["stale_days"]) > 0 and (code, "stale") not in ig_coarse:
                    rows.append({"code": code, "trade_date": r["latest_date"], "issue_type": "stale",
                                 "detail": f"数据未更新到最新交易日，滞后 {int(r['stale_days'])} 个交易日"
                                           f"（自 {r['stale_lo']} 起）"})
                    l4_stale += 1
            # L2 逐日市值缺口：在市股「有日线但市值字段为空/缺行」的近端缺口，按 code 聚合一条
            # （detail 写缺失区间）。直接读同一份 frame 的 mv_gap_days（与概览/逐股 L2 完全统一，
            # 同窗口同数据），命中多少写多少——与概览口径一致，台账不再静默。
            l2_gap = 0
            for _, r in frame.iterrows():
                code = r["code"]
                if bool(r["mv_ok"]) and int(r["mv_gap_days"]) > 0 and (code, "mv_gap") not in ig_coarse:
                    rows.append({"code": code, "trade_date": r["mv_gap_hi"], "issue_type": "mv_gap",
                                 "detail": f"近{gap_window_days}个交易日内 {int(r['mv_gap_days'])} 天市值字段缺口"
                                           f"（需补市值）：{r['mv_detail']}"})
                    l2_gap += 1
            self._insert_issues(rows)
        return {"abnormal_change_rows": len(ab_rows), "adj_jump_rows": adj,
                "mv_missing_rows": l2, "mv_gap_rows": l2_gap,
                "data_gap_rows": l4_gap, "stale_rows": l4_stale}

    # ── 板块维度质检（板块概念需求 R12，T7）──────────────────
    def scan_board_quality(self) -> dict:
        """板块数据质检：板块指数缺口 + 资金流缺失扫描，写 data_quality_issue。

        收敛语义：先完整计算本轮两类结果，再在一个事务内替换 open 的
        board_index_gap / board_fund_missing；扫描失败时事务不提交，旧问题不会消失。
        已 ignored 的板块按 (code, type) 整体豁免。

        成分数波动不做质量判断；成分采集完整性由采集层“完整快照才落库”保证。
        """
        # 板块指数缺口：board_bar 最近交易日滞后于 daily_bar 全局最新交易日
        # 已 ignored 的板块豁免（按 (code, type) 整体豁免）
        def _ignored_codes(issue_type: str) -> set[str]:
            ig = set()
            igdf = self.c.query_df(
                "SELECT code FROM data_quality_issue WHERE issue_type=? AND status='ignored'",
                [issue_type])
            for _, r in igdf.iterrows():
                ig.add(str(r["code"]))
            return ig

        gap_issues: list[dict] = []
        latest = self._scalar("SELECT max(trade_date) FROM daily_bar")
        fund_date = None
        if latest is not None:
            latest = pd.Timestamp(latest).date()
            fund_date = latest
            ig_gap = _ignored_codes("board_index_gap")
            gap_df = self.c.query_df(
                """
                SELECT b.board_code, b.name, max(bar.trade_date) AS last_bar
                FROM board_dict b
                LEFT JOIN board_bar bar ON bar.board_code = b.board_code
                WHERE b.has_bar
                GROUP BY b.board_code, b.name
                """)
            for _, r in gap_df.iterrows():
                code = str(r["board_code"])
                if code in ig_gap:
                    continue
                last_bar = r["last_bar"]
                if last_bar is None or pd.Timestamp(last_bar).date() < latest:
                    gap_issues.append({
                        "code": code, "trade_date": latest,
                        "issue_type": "board_index_gap",
                        "detail": f"板块 {r['name']}（{code}）指数缺口：最近指数 {last_bar or '无'}，"
                                  f"全局最新交易日 {latest}",
                    })
        # 资金流缺失：字典中真正参与展示的板块（有成分或指数）却无资金流数据。
        # 来源是数据源资金流榜单未收录该板块（区别于 board_fund_unmatched：源多出而字典缺）。
        # 源侧榜单一经上线，重采资金流会置 has_fund_flow=true，重扫即收敛。
        ig_fund = _ignored_codes("board_fund_missing")
        fund_df = self.c.query_df(
            """
            SELECT board_code, name FROM board_dict
            WHERE (has_members OR has_bar) AND NOT has_fund_flow
            """)
        # 资金流缺失日期：优先全局最新交易日（该日应有资金流但源未收录）；系统未初始化（无 daily_bar）
        # 时用检测日兜底，保证质量页日期列有值。
        if fund_date is None:
            from datetime import date as _date
            fund_date = _date.today()
        fund_issues = [
            {
                "code": str(r["board_code"]),
                "trade_date": fund_date,
                "issue_type": "board_fund_missing",
                "detail": f"板块 {r['name']}（{r['board_code']}）资金流缺失："
                          f"数据源资金流榜单未收录该板块",
            }
            for _, r in fund_df.iterrows()
            if str(r["board_code"]) not in ig_fund
        ]
        # 资金流滞后：全源快照整体停留早于全局最新交易日（资金流整体停采/漏采）。
        # 与逐板块指数缺口不同，资金流是整体批量采集，停摆时所有板块一起滞后，
        # 故记单条源级 issue（code=NULL），修复动作重采全源资金流。
        stale_issues: list[dict] = []
        if latest is not None and not _ignored_codes("board_fund_stale"):
            last_fund = self._scalar("SELECT max(snapshot_date) FROM board_fund_flow")
            if last_fund is not None and not pd.isna(last_fund):
                last_fund = pd.Timestamp(last_fund).date()
                if last_fund < latest:
                    stale_issues.append({
                        "code": None, "trade_date": latest,
                        "issue_type": "board_fund_stale",
                        "detail": f"资金流快照停留在 {last_fund}，全局最新交易日 {latest}，"
                                  f"滞后 {(latest - last_fund).days} 天，待重采资金流",
                    })
        with self.c.transaction():
            for issue_type in ("board_index_gap", "board_fund_missing", "board_fund_stale"):
                self.c.execute(
                    "DELETE FROM data_quality_issue "
                    "WHERE status='open' AND issue_type=?", [issue_type])
            self._insert_issues(gap_issues + fund_issues + stale_issues)
        return {"index_gap": len(gap_issues), "fund_missing": len(fund_issues),
                "fund_stale": len(stale_issues)}

    # ── 单条问题复检（恢复后判断问题是否真消失，DM-D22）──
    def recheck_clean(self, issue_type: str, code: str | None, trade_date: date | None,
                      window_days: int = GAP_WINDOW_DAYS, detail: str | dict | None = None) -> bool:
        """复检：该 (类型,股,日期) 的问题现在是否已不存在。True=已恢复，可置 resolved。"""
        if issue_type == "mv_missing":
            # L2 契约：总市值与流通市值都须有
            r = self.c.query_df(
                "SELECT count(*) FILTER (WHERE total_mv IS NOT NULL) t, "
                "count(*) FILTER (WHERE float_mv IS NOT NULL) f FROM daily_metrics WHERE code=?", [code]).iloc[0]
            return int(r["t"]) > 0 and int(r["f"]) > 0
        if issue_type == "mv_gap":
            # L2 逐日缺口：近端窗口内不再有「有日线但市值字段为空/缺行」的天
            n = self._scalar(
                """SELECT count(*) FROM daily_bar b
                   JOIN stock_basic sb ON sb.code = b.code
                   LEFT JOIN daily_metrics m ON m.code = b.code AND m.trade_date = b.trade_date
                   WHERE b.code = ? AND sb.delist_date IS NULL
                     AND (m.code IS NULL OR m.total_mv IS NULL OR m.float_mv IS NULL)
                     AND b.trade_date >= (
                         SELECT min(trade_date) FROM (
                             SELECT trade_date FROM trade_calendar
                             WHERE is_open AND trade_date <= (SELECT max(trade_date) FROM daily_bar)
                             ORDER BY trade_date DESC LIMIT ?))""", [code, window_days])
            return int(n) == 0
        if issue_type in ("data_gap", "stale"):
            return len(self.missing_days_for(code, window_days)) == 0
        if issue_type == "null_close":
            if trade_date is None:
                return False
            return int(self._scalar(
                "SELECT count(*) FROM daily_bar WHERE code=? AND trade_date=? AND close>0",
                [code, trade_date])) > 0
        if issue_type == "ohl_repaired":
            if trade_date is None:
                return False
            # 当前问题在恢复期间已是 fixing；若重采后原始 OHL 仍异常，
            # 入库闸门会再生成一条 open 问题。以此区分“真正重采正常”与
            # “仍用收盘价回填”，不能只看库内 OHL 非空就误判恢复成功。
            return int(self._scalar(
                "SELECT count(*) FROM data_quality_issue "
                "WHERE code=? AND trade_date=? AND issue_type='ohl_repaired' AND status='open'",
                [code, trade_date])) == 0
        if issue_type == "abnormal_change":
            if trade_date is None:
                return False
            df = self.c.query_df(
                """
                SELECT *
                FROM (
                    SELECT b.trade_date, b.close, b.pre_close, COALESCE(sb.price_limit_pct,0.10) lim,
                           sb.name,
                           sb.delist_date,
                           b.trade_date - lag(b.trade_date) OVER (PARTITION BY b.code ORDER BY b.trade_date)
                               AS gap_days,
                           CASE
                               WHEN sb.list_date IS NOT NULL
                                    AND min(b.trade_date) OVER (PARTITION BY b.code)
                                        <= sb.list_date + INTERVAL 30 DAY
                               THEN row_number() OVER (PARTITION BY b.code ORDER BY b.trade_date)
                               ELSE NULL
                           END AS listing_trade_seq
                    FROM daily_bar b LEFT JOIN stock_basic sb ON sb.code=b.code
                    WHERE b.code=? AND b.pre_close>0
                ) t
                WHERE trade_date=?
                """, [code, trade_date])
            if df.empty:
                return True  # 行已不在（被清洗）→ 不再是异常
            r = df.iloc[0]
            if not bool(self._active_l3_mask(df).iloc[0]):
                return True
            tolerance = max(0.005, 0.011 / float(r["pre_close"]))
            return abs(r["close"] / r["pre_close"] - 1) <= r["lim"] + tolerance
        if issue_type == "adj_jump":
            df = self.c.query_df(
                """
                SELECT b.trade_date, b.close, COALESCE(b.adj_factor_clean, b.adj_factor) AS adj_factor,
                       sb.name,
                       sb.delist_date,
                       CASE
                           WHEN sb.list_date IS NOT NULL
                                AND min(b.trade_date) OVER (PARTITION BY b.code)
                                    <= sb.list_date + INTERVAL 30 DAY
                           THEN row_number() OVER (PARTITION BY b.code ORDER BY b.trade_date)
                           ELSE NULL
                       END AS listing_trade_seq
                FROM daily_bar b LEFT JOIN stock_basic sb ON sb.code=b.code
                WHERE b.code=? AND b.close>0 ORDER BY b.trade_date
                """, [code])
            if len(df) < 2:
                return True
            af = df["adj_factor"].fillna(1.0)
            qfq = df["close"] * af / (af.iloc[-1] or 1.0)
            ratio = (qfq / qfq.shift(1) - 1).abs()
            prev_date = pd.to_datetime(df["trade_date"]).shift(1)
            gap_days = (pd.to_datetime(df["trade_date"]) - prev_date).dt.days
            df = df.assign(gap_days=gap_days)
            actionable = (ratio > 0.5) & self._active_l3_mask(df) & (gap_days.fillna(0) <= 30)
            return not bool(actionable.any())
        if issue_type == "board_index_gap":
            # 板块指数缺口复检：与 scan_board_quality 扫描口径一致——只针对 has_bar 板块。
            # has_bar=false（源端无该板块指数能力）说明本就不该有指数，问题可收敛为已解决；
            # has_bar=true 才要求 board_bar 已到全局最新交易日。
            has_bar = self._scalar(
                "SELECT has_bar FROM board_dict WHERE board_code=?", [code])
            if has_bar is None or not bool(has_bar):
                return True
            latest = self._scalar("SELECT max(trade_date) FROM daily_bar")
            if latest is None:
                return False
            last_bar = self._scalar("SELECT max(trade_date) FROM board_bar WHERE board_code=?", [code])
            if last_bar is None or pd.isna(last_bar):
                return False
            return pd.Timestamp(last_bar).date() >= pd.Timestamp(latest).date()
        if issue_type == "board_member_incomplete":
            # 完整采集会原子更新 member_snapshot_at 并关闭 active issue；历史 member_count 不能证明
            # 本次问题已经修复，否则旧快照会造成假解决。
            row = self.c.query_df(
                "SELECT member_snapshot_at FROM board_dict WHERE board_code=?", [code])
            if row.empty or row.iloc[0]["member_snapshot_at"] is None:
                return False
            active = self._scalar(
                "SELECT count(*) FROM data_quality_issue "
                "WHERE issue_type='board_member_incomplete' AND code=? "
                "AND status IN ('open','fixing')", [code])
            return int(active) == 0
        if issue_type == "board_fund_unmatched":
            # 只有问题里的名称现在确实能映射到同类型字典，才算修复；源仍无稳定代码时保持 open。
            payload = detail if isinstance(detail, dict) else {}
            if not payload and isinstance(detail, str):
                try:
                    payload = json.loads(detail)
                except (TypeError, ValueError):
                    payload = {"name": detail}
            name = str(payload.get("name") or "").strip()
            if not name:
                return False
            board_type = str(payload.get("board_type") or "").strip()
            sql = "SELECT count(*) FROM board_dict WHERE name=?"
            params: list = [name]
            if board_type:
                sql += " AND board_type=?"
                params.append(board_type)
            return int(self._scalar(sql, params)) > 0
        if issue_type == "board_fund_missing":
            # 资金流缺失：与 scan_board_quality 扫描口径一致——只有该板块现在确实具备资金流数据
            # （has_fund_flow=true，源侧已收录并采到）或已不在字典（被移除）才算收敛。
            row = self.c.query_df(
                "SELECT has_fund_flow FROM board_dict WHERE board_code=?", [code])
            if row.empty:
                return True
            return bool(row.iloc[0]["has_fund_flow"])
        if issue_type == "board_fund_stale":
            # 资金流滞后：全局资金流快照已追平全局最新交易日即收敛（源级单条 issue，无 code）。
            latest = self._scalar("SELECT max(trade_date) FROM daily_bar")
            if latest is None:
                return False
            latest = pd.Timestamp(latest).date()
            last_fund = self._scalar("SELECT max(snapshot_date) FROM board_fund_flow")
            if last_fund is None or pd.isna(last_fund):
                return False
            return pd.Timestamp(last_fund).date() >= latest
        return True

    def _scan_adj_jump(self, threshold: float = 0.5, ignored_exact: set | None = None) -> int:
        """全市场前复权价相邻日跳变 > threshold（T-M7-6，补 T-M1-8 遗留）→ 复权异常。

        阈值 0.5（50%）远超任一板块单日涨跌停（≤20%），故捕获的是粗粒度复权口径错误
        （如除权日因子未更新致整段错位），噪音极低。向量化：按 code 分组算 qfq 比值跳变。
        缺失/停牌缺口属正常现象，由 coverage() 汇总，不在此逐条记 issue（避免淹没真异常）。
        """
        df = self.c.query_df(
            """
            SELECT b.code, b.trade_date, b.close,
                   COALESCE(b.adj_factor_clean, b.adj_factor) AS adj_factor,
                   sb.name,
                   sb.delist_date,
                   CASE
                       WHEN sb.list_date IS NOT NULL
                            AND min(b.trade_date) OVER (PARTITION BY b.code)
                                <= sb.list_date + INTERVAL 30 DAY
                       THEN row_number() OVER (PARTITION BY b.code ORDER BY b.trade_date)
                       ELSE NULL
                   END AS listing_trade_seq
            FROM daily_bar b LEFT JOIN stock_basic sb ON sb.code = b.code
            WHERE b.close > 0
            ORDER BY b.code, b.trade_date
            """
        )
        if df.empty:
            return 0
        parts = []
        for code, g in df.groupby("code", sort=False):
            af = g["adj_factor"].fillna(1.0)
            base = af.iloc[-1] if len(af) else 1.0
            qfq = g["close"] * af / base
            ratio = (qfq / qfq.shift(1) - 1).abs()
            prev_date = pd.to_datetime(g["trade_date"]).shift(1)
            gap_days = (pd.to_datetime(g["trade_date"]) - prev_date).dt.days
            g = g.assign(gap_days=gap_days)
            actionable = (ratio > threshold) & self._active_l3_mask(g) & (gap_days.fillna(0) <= 30)
            bad = g[actionable]
            if not bad.empty:
                parts.append(pd.DataFrame({"code": bad["code"], "trade_date": bad["trade_date"],
                                           "ratio": ratio[actionable]}))
        if not parts:
            return 0
        allbad = pd.concat(parts, ignore_index=True)
        ig = ignored_exact or set()
        keep = [(r["code"], r["trade_date"], r["ratio"]) for _, r in allbad.iterrows()
                if (r["code"], "adj_jump", str(pd.Timestamp(r["trade_date"]).date())) not in ig]
        if not keep:
            return 0
        return self._insert_issues([
            {"code": c, "trade_date": td, "issue_type": "adj_jump",
             "detail": f"前复权相邻日跳变 {rt*100:.0f}%（疑复权口径异常）"}
            for c, td, rt in keep])

    def _next_qid(self) -> int:
        return int(self.c.query_df("SELECT nextval('seq_quality_issue') AS v").iloc[0]["v"])

    # ── 4. 关键字段非空 ──
    def null_critical(self) -> dict:
        return {
            "null_close": int(self._scalar("SELECT count(*) FROM daily_bar WHERE close IS NULL")),
            "null_ohlc": int(self._scalar(
                "SELECT count(*) FROM daily_bar WHERE open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL")),
            "null_volume": int(self._scalar("SELECT count(*) FROM daily_bar WHERE volume IS NULL")),
            "zero_or_neg_close": int(self._scalar("SELECT count(*) FROM daily_bar WHERE close <= 0")),
            "null_float_mv": int(self._scalar("SELECT count(*) FROM daily_metrics WHERE float_mv IS NULL")),
        }

    # ── 5. 指数覆盖 ──
    def index_coverage(self, start: date, end: date) -> dict:
        open_days = self.calendar_open_days(start, end)
        df = self.c.query_df(
            "SELECT index_code, count(*) AS days, min(trade_date) lo, max(trade_date) hi "
            "FROM index_bar GROUP BY index_code ORDER BY index_code"
        )
        df["coverage"] = (df["days"] / open_days).round(4) if open_days else 0
        return {"calendar_open_days": open_days, "indices": df.to_dict("records")}

    # ── 6. 退市股覆盖 ──
    def delisted_coverage(self) -> dict:
        df = self.c.query_df(
            """
            SELECT sb.code, sb.name, sb.delist_date,
                   (SELECT count(*) FROM daily_bar b WHERE b.code=sb.code) AS bars,
                   (SELECT max(trade_date) FROM daily_bar b WHERE b.code=sb.code) AS last_bar
            FROM stock_basic sb WHERE sb.delist_date IS NOT NULL
            """
        )
        with_data = int((df["bars"] > 0).sum())
        return {
            "delisted_total": len(df),
            "delisted_with_data": with_data,
            "delisted_no_data": int((df["bars"] == 0).sum()),
        }

    # ── 汇总打印 ──
    def run(self, start: date, end: date, scan_issues: bool = True) -> dict:
        report = {
            "overview": self.overview(),
            "calendar_open_days": self.calendar_open_days(start, end),
            "coverage": self.coverage(),
            "null_critical": self.null_critical(),
            "index_coverage": self.index_coverage(start, end),
            "delisted_coverage": self.delisted_coverage(),
        }
        if scan_issues:
            report["quality_scan"] = self.scan_quality_issues()
        self._print(report)
        return report

    @staticmethod
    def _print(r: dict) -> None:
        o = r["overview"]
        print("\n" + "=" * 60)
        print("数据完整性体检报告")
        print("=" * 60)
        print(f"行情股票数: {o['distinct_codes_with_bars']}  "
              f"(在市 {o['stock_basic_live']} / 退市 {o['stock_basic_delisted']})")
        print(f"日线行数: {o['row_counts']['daily_bar']:,}  "
              f"区间: {o['bar_date_min']} ~ {o['bar_date_max']}")
        print(f"窗口内日历开市日: {r['calendar_open_days']}")
        cov = r["coverage"]
        print(f"\n[覆盖率] 总体 {cov['overall_coverage']*100:.3f}%  "
              f"低于阈值股票数: {cov['stocks_below_threshold']}/{cov['stocks_total']}")
        print(f"[停牌] 推导停牌日合计 {cov['total_suspension_days']:,} 天，"
              f"涉及 {cov['stocks_with_suspension']} 只（缺口=存续期内开市但无行情，属正常）")
        nc = r["null_critical"]
        print(f"[空值] close空 {nc['null_close']}  OHLC空 {nc['null_ohlc']}  "
              f"量空 {nc['null_volume']}  收盘<=0 {nc['zero_or_neg_close']}  市值空 {nc['null_float_mv']}")
        print("[指数]")
        for idx in r["index_coverage"]["indices"]:
            print(f"   {idx['index_code']}: {idx['days']} 天 ({idx['coverage']*100:.1f}%)")
        dc = r["delisted_coverage"]
        print(f"[退市股] 共 {dc['delisted_total']}  有数据 {dc['delisted_with_data']}  "
              f"无数据 {dc['delisted_no_data']}")
        if "quality_scan" in r:
            print(f"[质检] 异常涨跌幅行数: {r['quality_scan']['abnormal_change_rows']}（已写 data_quality_issue）")
        print("=" * 60)
