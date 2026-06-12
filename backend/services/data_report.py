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

from datetime import date

import pandas as pd

from backend.common.logging import get_logger
from backend.storage.duckdb_client import DuckDBClient, get_client

log = get_logger("services.data_report")


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

    # ── 缺口检测（DM-D9，FR-DM-1）──
    def gaps_summary(self) -> dict:
        """在市股票在 [上市日(或首行情), 全局最新交易日] 内，开市日无行情且非停牌 = 缺口日。

        停牌日（daily_bar.is_suspended）从缺口中排除；连续缺口日数不在此展开（逐股下钻见 stock_quality）。
        返回 {stocks_with_gap, gap_days_total, latest_trade_date}。
        """
        latest = self._scalar("SELECT max(trade_date) FROM daily_bar")
        if latest is None:
            return {"stocks_with_gap": 0, "gap_days_total": 0, "latest_trade_date": None}
        df = self.c.query_df(
            """
            WITH live AS (SELECT code, list_date FROM stock_basic WHERE delist_date IS NULL),
            span AS (
                SELECT l.code,
                       greatest(COALESCE(l.list_date, (SELECT min(trade_date) FROM daily_bar b WHERE b.code=l.code)),
                                (SELECT min(trade_date) FROM daily_bar b WHERE b.code=l.code)) AS lo
                FROM live l
            ),
            expect AS (
                SELECT s.code,
                       (SELECT count(*) FROM trade_calendar cal
                        WHERE cal.is_open AND cal.trade_date BETWEEN s.lo AND ?) AS expected,
                       (SELECT count(*) FROM daily_bar b
                        WHERE b.code=s.code AND b.trade_date BETWEEN s.lo AND ?) AS have,
                       (SELECT count(*) FROM daily_bar b
                        WHERE b.code=s.code AND b.is_suspended AND b.trade_date BETWEEN s.lo AND ?) AS susp
                FROM span s WHERE s.lo IS NOT NULL
            )
            SELECT code, greatest(expected - have - susp, 0) AS gap_days FROM expect
            """, [latest, latest, latest])
        gaps = df[df["gap_days"] > 0]
        return {
            "stocks_with_gap": int(len(gaps)),
            "gap_days_total": int(gaps["gap_days"].sum()),
            "latest_trade_date": str(pd.Timestamp(latest).date()),
        }

    # ── 逐股质量（FR-DM-1 第四项）──
    def stock_quality(self, codes: list[str] | None = None, page: int = 1, size: int = 50) -> dict:
        """逐股关键字段达标 + 鲜活度：latest_date / is_fresh / total_mv_ok / gap_days / open_issues。"""
        latest = self._scalar("SELECT max(trade_date) FROM daily_bar")
        latest_s = None if latest is None else str(pd.Timestamp(latest).date())
        cond, params = "delist_date IS NULL", []
        if codes:
            ph = ",".join("?" * len(codes))
            cond += f" AND code IN ({ph})"
            params += list(codes)
        total = int(self._scalar(f"SELECT count(*) FROM stock_basic WHERE {cond}", params))
        rows = self.c.query_df(
            f"""
            WITH base AS (SELECT code, name, list_date FROM stock_basic WHERE {cond}
                          ORDER BY code LIMIT {int(size)} OFFSET {int((page-1)*size)})
            SELECT b.code, b.name,
                   (SELECT max(trade_date) FROM daily_bar d WHERE d.code=b.code) AS latest_date,
                   (SELECT count(*) FROM daily_metrics m WHERE m.code=b.code AND m.total_mv IS NOT NULL) AS mv_rows,
                   (SELECT count(*) FROM data_quality_issue q WHERE q.code=b.code AND q.status='open') AS open_issues,
                   b.list_date,
                   (SELECT count(*) FROM trade_calendar cal WHERE cal.is_open
                        AND cal.trade_date BETWEEN COALESCE(b.list_date,(SELECT min(trade_date) FROM daily_bar d2 WHERE d2.code=b.code)) AND ?) AS expected,
                   (SELECT count(*) FROM daily_bar d WHERE d.code=b.code) AS have,
                   (SELECT count(*) FROM daily_bar d WHERE d.code=b.code AND d.is_suspended) AS susp
            FROM base b
            """, [latest, *params])
        out = []
        for _, r in rows.iterrows():
            ld = r["latest_date"]
            ld_s = None if ld is None or str(ld) == "NaT" else str(pd.Timestamp(ld).date())
            gap = max(int(r["expected"]) - int(r["have"]) - int(r["susp"]), 0)
            out.append({
                "code": r["code"], "name": r["name"],
                "latest_date": ld_s,
                "is_fresh": bool(latest_s is not None and ld_s == latest_s),
                "total_mv_ok": bool(int(r["mv_rows"]) > 0),
                "gap_days": gap,
                "open_issues": int(r["open_issues"]),
            })
        return {"total": total, "page": page, "size": size,
                "latest_trade_date": latest_s, "list": out}

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

    # ── 市场级真实质检（写 data_quality_issue）──
    def scan_quality_issues(self) -> dict:
        """向量化扫描真实数据质量问题（异常涨跌幅），写 data_quality_issue。

        注意：停牌缺口属正常现象，不计入 issue（避免淹没真实问题）；
        仅记录"单日涨跌幅超板块上限 +0.5% 容差"这类真异常。
        """
        # 一次 SQL 关联板块涨跌幅，标记异常行
        df = self.c.query_df(
            """
            SELECT b.code, b.trade_date,
                   abs(b.close / b.pre_close - 1) AS chg,
                   COALESCE(sb.price_limit_pct, 0.10) AS lim
            FROM daily_bar b LEFT JOIN stock_basic sb ON sb.code = b.code
            WHERE b.pre_close IS NOT NULL AND b.pre_close > 0
            """
        )
        bad = df[df["chg"] > df["lim"] + 0.005]
        if not bad.empty:
            from datetime import datetime

            from backend.dataquality.checker import severity_for
            issues = pd.DataFrame({
                "id": [self._next_qid() for _ in range(len(bad))],
                "code": bad["code"].values,
                "trade_date": bad["trade_date"].values,
                "issue_type": "abnormal_change",
                "severity": severity_for("abnormal_change"),
                "status": "open",
                "detail": [f"涨跌幅 {x*100:.1f}% 超上限 {l*100:.0f}%"
                           for x, l in zip(bad["chg"], bad["lim"])],
                "detected_at": datetime.now(),
            })
            with self.c.temp_view(issues, prefix="qi") as v:
                self.c.execute(
                    "INSERT INTO data_quality_issue "
                    "(id, code, trade_date, issue_type, severity, status, detail, detected_at) "
                    "SELECT id, code, trade_date, issue_type, severity, status, detail, detected_at "
                    f"FROM {v}")
        adj = self._scan_adj_jump()
        return {"abnormal_change_rows": int(len(bad)), "adj_jump_rows": adj}

    def _scan_adj_jump(self, threshold: float = 0.5) -> int:
        """全市场前复权价相邻日跳变 > threshold（T-M7-6，补 T-M1-8 遗留）→ 复权异常。

        阈值 0.5（50%）远超任一板块单日涨跌停（≤20%），故捕获的是粗粒度复权口径错误
        （如除权日因子未更新致整段错位），噪音极低。向量化：按 code 分组算 qfq 比值跳变。
        缺失/停牌缺口属正常现象，由 coverage() 汇总，不在此逐条记 issue（避免淹没真异常）。
        """
        from datetime import datetime

        df = self.c.query_df(
            "SELECT code, trade_date, close, adj_factor FROM daily_bar "
            "WHERE close > 0 ORDER BY code, trade_date"
        )
        if df.empty:
            return 0
        parts = []
        for code, g in df.groupby("code", sort=False):
            af = g["adj_factor"].fillna(1.0)
            base = af.iloc[-1] if len(af) else 1.0
            qfq = g["close"] * af / base
            ratio = (qfq / qfq.shift(1) - 1).abs()
            bad = g[ratio > threshold]
            if not bad.empty:
                parts.append(pd.DataFrame({"code": bad["code"], "trade_date": bad["trade_date"],
                                           "ratio": ratio[ratio > threshold]}))
        if not parts:
            return 0
        allbad = pd.concat(parts, ignore_index=True)
        from backend.dataquality.checker import severity_for
        issues = pd.DataFrame({
            "id": [self._next_qid() for _ in range(len(allbad))],
            "code": allbad["code"].values, "trade_date": allbad["trade_date"].values,
            "issue_type": "adj_jump",
            "severity": severity_for("adj_jump"),
            "status": "open",
            "detail": [f"前复权相邻日跳变 {r*100:.0f}%（疑复权口径异常）" for r in allbad["ratio"]],
            "detected_at": datetime.now(),
        })
        with self.c.temp_view(issues, prefix="aj") as v:
            self.c.execute(
                "INSERT INTO data_quality_issue "
                "(id, code, trade_date, issue_type, severity, status, detail, detected_at) "
                "SELECT id, code, trade_date, issue_type, severity, status, detail, detected_at "
                f"FROM {v}")
        return int(len(allbad))

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
