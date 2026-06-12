"""数据正确性 + 完整性 系统性核查器（全量，非抽样）。

分三组：
A. 结构/完整性（SQL 全表）：孤儿、键对齐、日历一致、重复。
B. 价格正确性（SQL 全表）：OHLC 序关系、非负、复权因子、涨跌幅越界。
C. 独立数据源交叉验证（联网）：随机若干股，本地存储 vs 实时重拉，
   校验不复权价 + 前复权价（验证 adj_factor / pre_close 逻辑）。

每项给 PASS/FAIL + 明细，最后汇总。
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from backend.common.logging import get_logger
from backend.storage.duckdb_client import DuckDBClient, get_client

log = get_logger("services.data_verify")


class DataVerifier:
    def __init__(self, client: DuckDBClient | None = None, quiet: bool = False):
        self.c = client or get_client()
        self.quiet = quiet
        self.results: list[tuple[str, bool, str]] = []

    def _check(self, name: str, ok: bool, detail: str = "") -> None:
        self.results.append((name, ok, detail))
        if not self.quiet:
            flag = "PASS" if ok else "FAIL"
            print(f"  [{flag}] {name}" + (f" — {detail}" if detail else ""))

    def fails(self) -> list[str]:
        """返回未通过项名称列表。"""
        return [n for n, ok, _ in self.results if not ok]

    def _say(self, msg: str) -> None:
        if not self.quiet:
            print(msg)

    def _count(self, sql: str, params: list | None = None) -> int:
        return int(self.c.query_df(sql, params or []).iloc[0, 0])

    # ── A. 结构 / 完整性 ──
    def check_structure(self) -> None:
        self._say("\nA. 结构 / 完整性")
        orphan = self._count(
            "SELECT count(*) FROM (SELECT DISTINCT b.code FROM daily_bar b "
            "LEFT JOIN stock_basic sb ON sb.code=b.code WHERE sb.code IS NULL)"
        )
        self._check("daily_bar 无孤儿（均有 stock_basic）", orphan == 0, f"孤儿 {orphan}")

        # 市值只对【在市股】要求齐全；退市股 baostock 无流通股本→无市值（数据源固有局限）
        live_no_mv = self._count(
            "SELECT count(*) FROM daily_bar b JOIN stock_basic sb ON sb.code=b.code "
            "LEFT JOIN daily_metrics m ON m.code=b.code AND m.trade_date=b.trade_date "
            "WHERE sb.delist_date IS NULL AND m.code IS NULL"
        )
        self._check("在市股每条日线都有市值", live_no_mv == 0, f"在市缺市值 {live_no_mv}")
        delisted_no_mv = self._count(
            "SELECT count(*) FROM daily_bar b JOIN stock_basic sb ON sb.code=b.code "
            "LEFT JOIN daily_metrics m ON m.code=b.code AND m.trade_date=b.trade_date "
            "WHERE sb.delist_date IS NOT NULL AND m.code IS NULL"
        )
        # 退市股缺市值属已知数据源局限，不算失败，仅提示
        self._say(f"  [INFO] 退市股缺市值 {delisted_no_mv} 行（baostock 无流通股本，已知局限）")

        non_open = self._count(
            "SELECT count(*) FROM daily_bar b LEFT JOIN trade_calendar c "
            "ON c.trade_date=b.trade_date WHERE c.is_open IS NOT TRUE"
        )
        self._check("所有行情日均为日历开市日", non_open == 0, f"非开市日行情 {non_open}")

        dup = self._count(
            "SELECT count(*) FROM (SELECT code, trade_date FROM daily_bar "
            "GROUP BY code, trade_date HAVING count(*)>1)"
        )
        self._check("无重复 (code,trade_date)", dup == 0, f"重复 {dup}")

    # ── B. 价格正确性 ──
    def check_prices(self) -> None:
        print("\nB. 价格正确性")
        nonpos = self._count("SELECT count(*) FROM daily_bar WHERE close<=0 OR open<=0 OR high<=0 OR low<=0")
        self._check("价格全为正", nonpos == 0, f"非正价行 {nonpos}")

        # high 应 >= open/close/low；low 应 <= open/close/high
        ohlc_bad = self._count(
            "SELECT count(*) FROM daily_bar WHERE high < low OR high < open OR high < close "
            "OR low > open OR low > close"
        )
        self._check("OHLC 序关系正确（high≥{o,c,l}, low≤{o,c,h}）", ohlc_bad == 0, f"违反 {ohlc_bad}")

        neg_vol = self._count("SELECT count(*) FROM daily_bar WHERE volume<0 OR amount<0")
        self._check("成交量/额非负", neg_vol == 0, f"负值 {neg_vol}")

        bad_factor = self._count("SELECT count(*) FROM daily_bar WHERE adj_factor IS NULL OR adj_factor<=0")
        self._check("复权因子为正", bad_factor == 0, f"异常因子 {bad_factor}")

        # 涨跌幅越界（按板块口径；不套用当前 ST 状态——见 add_markers 的 ST 时变说明）。
        # 残留越界 = 新股上市初期宽涨跌幅 / 退市整理期 / 极少数待核，比例应 <0.1%。
        over = self._count(
            "SELECT count(*) FROM daily_bar b JOIN stock_basic sb ON sb.code=b.code "
            "WHERE b.pre_close>0 AND abs(b.close/b.pre_close-1) > COALESCE(sb.price_limit_pct,0.10)+0.005"
        )
        total = self._count("SELECT count(*) FROM daily_bar WHERE pre_close>0")
        self._check(
            "涨跌幅越界比例极低（<0.1%，余为新股/退市/复牌）",
            over / max(total, 1) < 0.001,
            f"{over}/{total} = {over/max(total,1)*100:.3f}%",
        )

    # ── C. 独立数据源交叉验证 ──
    def cross_validate(self, codes: list[str] | None = None, n_dates: int = 5) -> None:
        print("\nC. 独立数据源交叉验证（实时重拉对比）")
        from backend.datasource.akshare_source import AKShareSource, to_full_code

        # 默认覆盖各板块代表
        if codes is None:
            codes = ["600000.SH", "000001.SZ", "300750.SZ", "688981.SH"]
        src = AKShareSource()
        end = date.today()
        start = date(end.year - 1, end.month, end.day)

        for code in codes:
            code6 = code.split(".")[0]
            try:
                # 实时重拉（不复权 + 前复权）
                fresh_raw = src._sina_daily(code6, start, end, "")
                fresh_qfq = src._sina_daily(code6, start, end, "qfq")
                if fresh_raw is None or fresh_raw.empty:
                    self._check(f"{code} 交叉验证", False, "实时重拉为空")
                    continue
                fresh_raw["d"] = pd.to_datetime(fresh_raw["date"]).dt.date
                fresh_qfq["d"] = pd.to_datetime(fresh_qfq["date"]).dt.date
                fresh_raw = fresh_raw.set_index("d")
                fresh_qfq = fresh_qfq.set_index("d")

                # 本地不复权 + 前复权（点时取数）
                local = self.c.query_df(
                    "SELECT trade_date, close, adj_factor FROM daily_bar WHERE code=? "
                    "AND trade_date>=? ORDER BY trade_date", [code, start]
                )
                if local.empty:
                    self._check(f"{code} 交叉验证", False, "本地无数据")
                    continue
                local["d"] = local["trade_date"].apply(lambda x: pd.Timestamp(x).date())
                latest_f = local["adj_factor"].iloc[-1]
                local["qfq"] = local["close"] * local["adj_factor"] / latest_f
                local = local.set_index("d")

                # 取末尾 n_dates 个公共交易日比对
                common = [d for d in local.index if d in fresh_raw.index][-n_dates:]
                raw_max_err = qfq_max_err = 0.0
                for d in common:
                    raw_max_err = max(raw_max_err, abs(local.loc[d, "close"] - fresh_raw.loc[d, "close"]))
                    qfq_max_err = max(qfq_max_err, abs(local.loc[d, "qfq"] - fresh_qfq.loc[d, "close"]))
                ok = raw_max_err < 0.02 and qfq_max_err < 0.05  # 2分/5分容差
                self._check(
                    f"{code} 不复权&前复权 vs 实时源（{len(common)}日）",
                    ok, f"原价误差≤{raw_max_err:.3f} 前复权误差≤{qfq_max_err:.3f}",
                )
            except Exception as e:  # noqa: BLE001
                self._check(f"{code} 交叉验证", False, f"异常 {e}")

    # ── D. 需求字段完整性契约（治"整列缺失隐形"）──
    def check_contract(self) -> None:
        """对照需求 F-DAT-02 / §10.2 数据字典，断言必填字段非空。

        与 check_prices 互补：那个查"已有数据对不对"，这个查"该有的字段有没有"。
        已知数据源局限（免费源无总股本/概念、退市股无市值）单列为豁免，不判失败但显式列出。
        """
        self._say("\nD. 需求字段完整性契约（F-DAT-02 / §10.2）")
        # (表, 列, 附加where, 标签) —— 必须非空
        required = [
            ("stock_basic", "name", "", "基础·名称"),
            ("stock_basic", "exchange", "", "基础·交易所"),
            ("stock_basic", "board", "", "基础·板块"),
            ("stock_basic", "list_date", "", "基础·上市日"),
            ("stock_basic", "price_limit_pct", "", "基础·涨跌幅限制"),
            # 行业/总股本仅要求在市股（退市股免费源无）
            ("stock_basic", "industry", "delist_date IS NULL", "在市股·行业"),
            ("stock_basic", "total_share", "delist_date IS NULL", "在市股·总股本"),
            ("daily_bar", "open", "", "日线·开盘"),
            ("daily_bar", "high", "", "日线·最高"),
            ("daily_bar", "low", "", "日线·最低"),
            ("daily_bar", "close", "", "日线·收盘"),
            ("daily_bar", "volume", "", "日线·成交量"),
            ("daily_bar", "amount", "", "日线·成交额"),
            ("daily_bar", "adj_factor", "", "日线·复权因子"),
            ("daily_bar", "turnover_rate", "", "日线·换手率"),
        ]
        for table, col, where, label in required:
            w = f" AND {where}" if where else ""
            n_null = self._count(f"SELECT count(*) FROM {table} WHERE {col} IS NULL{w}")
            self._check(f"{label} 无缺失", n_null == 0, f"缺 {n_null}")
        # 在市股流通市值必须有
        live_mv_null = self._count(
            "SELECT count(*) FROM daily_metrics m JOIN stock_basic sb ON sb.code=m.code "
            "WHERE sb.delist_date IS NULL AND m.float_mv IS NULL"
        )
        self._check("在市股·流通市值无缺失", live_mv_null == 0, f"缺 {live_mv_null}")
        live_totalmv_null = self._count(
            "SELECT count(*) FROM daily_metrics m JOIN stock_basic sb ON sb.code=m.code "
            "WHERE sb.delist_date IS NULL AND m.total_mv IS NULL"
        )
        self._check("在市股·总市值无缺失", live_totalmv_null == 0, f"缺 {live_totalmv_null}")

        # 已知豁免（数据源固有局限，不判失败，但显式列出，绝不隐藏）
        self._say("  —— 已知豁免（数据源局限，非失败，明示）——")
        gaps = [
            ("stock_basic", "concept", "概念标签：F-DAT-10 属 Could，本期未采"),
        ]
        for table, col, note in gaps:
            n = self._count(f"SELECT count(*) FROM {table} WHERE {col} IS NULL")
            self._say(f"  [豁免] {table}.{col} 缺 {n} 行 — {note}")

    def run(self, cross: bool = True) -> bool:
        print("=" * 64)
        print("数据正确性 + 完整性 系统性核查")
        print("=" * 64)
        self.check_structure()
        self.check_prices()
        self.check_contract()
        if cross:
            self.cross_validate()
        passed = sum(1 for _, ok, _ in self.results if ok)
        total = len(self.results)
        print("\n" + "=" * 64)
        print(f"核查结果：{passed}/{total} 通过")
        fails = [n for n, ok, _ in self.results if not ok]
        if fails:
            print("未通过项：", fails)
        print("=" * 64)
        return passed == total
