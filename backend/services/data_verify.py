"""数据正确性 + 完整性 系统性核查器（全量，非抽样）。

分五组：
A. 结构/完整性（SQL 全表）：孤儿、键对齐、日历一致、重复。
B. 价格正确性（SQL 全表）：OHLC 序关系、非负、复权因子、涨跌幅越界。
C. 独立数据源交叉验证（联网）：随机若干股，本地存储 vs 实时重拉，
   校验不复权价 + 前复权价（验证 adj_factor / pre_close 逻辑）。
D. 需求字段完整性契约：必填字段非空，已知数据源局限显式豁免。
E. 板块数据：四表孤儿/日历一致/OHLC/枚举取值/能力标记与实际数据一致。
G. 个股走势关联板块：当前态/冠军一致性、数值契约、引用完整性和日期支撑。

每项给 PASS/FAIL + 明细，最后汇总。
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pandas as pd

from backend.common.logging import get_logger
from backend.dataquality.checker import mv_inverted_sql
from backend.services.trade_calendar_readiness import (
    calendar_readiness_detail,
    inspect_trade_calendar,
)
from backend.storage.duckdb_client import DuckDBClient
from backend.storage.duckdb_client import get_read_client as get_client

log = get_logger("services.data_verify")


class DataVerifier:
    def __init__(self, client: DuckDBClient | None = None, quiet: bool = False):
        self.c = client or get_client()
        self.quiet = quiet
        self.results: list[tuple[str, bool, str]] = []
        # 结构化留痕（供 Web 体检报告 run_structured 分组渲染；与 results 3 元组并行，互不影响）
        self._cur_group = ""
        self._structured: list[dict] = []

    def _check(self, name: str, ok: bool, detail: str = "", help_text: str = "") -> None:
        self.results.append((name, ok, detail))
        status = "pass" if ok else "fail"
        self._structured.append({
            "group": self._cur_group,
            "name": name,
            "ok": ok,
            "status": status,
            "detail": detail,
            "help": help_text,
        })
        if not self.quiet:
            flag = "PASS" if ok else "FAIL"
            print(f"  [{flag}] {name}" + (f" — {detail}" if detail else ""))

    def _warn(self, name: str, detail: str, help_text: str = "") -> None:
        """记录不阻断体检的覆盖提醒，并与真正的数据错误明确区分。"""
        self.results.append((name, True, detail))
        self._structured.append(
            {
                "group": self._cur_group,
                "name": name,
                "ok": True,
                "status": "warn",
                "detail": detail,
                "help": help_text,
            }
        )
        if not self.quiet:
            print(f"  [WARN] {name} — {detail}")

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
        self._cur_group = "A. 结构/完整性"
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

        st_missing = self._count(
            "SELECT count(*) FROM daily_bar b LEFT JOIN stock_st_status_daily st "
            "ON st.code=b.code AND st.trade_date=b.trade_date "
            "WHERE st.code IS NULL OR st.quality<>'accurate'"
        )
        self._check(
            "日线均有权威 ST 点时事实",
            st_missing == 0,
            f"缺失或非权威 {st_missing}",
        )
        st_mismatch = self._count(
            "SELECT count(*) FROM daily_bar b JOIN stock_st_status_daily st "
            "ON st.code=b.code AND st.trade_date=b.trade_date "
            "WHERE b.is_st IS DISTINCT FROM st.is_st"
        )
        self._check(
            "daily_bar ST 过渡投影与唯一事实一致",
            st_mismatch == 0,
            f"不一致 {st_mismatch}",
        )
        st_revision_missing = self._count(
            "SELECT count(*) FROM (SELECT DISTINCT st.trade_date "
            "FROM stock_st_status_daily st LEFT JOIN stock_st_status_date_revision revision "
            "ON revision.trade_date=st.trade_date WHERE revision.trade_date IS NULL)"
        )
        self._check(
            "ST 事实日期均有缓存修订版本",
            st_revision_missing == 0,
            f"缺失日期 {st_revision_missing}",
        )
        ladder_versions = self.c.query_df(
            "SELECT trade_date,st_input_version FROM limit_ladder_snapshot_state "
            "WHERE current_snapshot_id IS NOT NULL AND status='valid' ORDER BY trade_date"
        )
        stale_result_versions = 0
        st_gate_error = None
        if not ladder_versions.empty:
            from backend.services.stock_st_status import (
                StockSTStatusService,
                STStatusNotReadyError,
            )

            st_service = StockSTStatusService(self.c)
            try:
                trade_dates = [
                    pd.Timestamp(value).date()
                    for value in ladder_versions["trade_date"].tolist()
                ]
                current_versions = st_service.input_versions_through_dates(trade_dates)
                for row in ladder_versions.to_dict("records"):
                    trade_date = pd.Timestamp(row["trade_date"]).date()
                    expected = current_versions[trade_date]
                    stored = row.get("st_input_version")
                    if pd.isna(stored) or str(stored) != expected:
                        stale_result_versions += 1
            except STStatusNotReadyError as exc:
                st_gate_error = str(exc)
        if st_gate_error:
            self._warn(
                "连板天梯 ST 输入版本暂不可核验",
                st_gate_error,
                "等待 ST 刷新发布后重新运行结构体检；旧快照不会被声明为当前有效结果。",
            )
        elif stale_result_versions:
            self._warn(
                "连板天梯快照待 ST 版本自愈",
                f"待首次读取重算 {stale_result_versions} 个日期",
                "访问对应日期后会复用现有日期任务自动重算，无需批量迁移历史结果。",
            )
        else:
            self._check("连板天梯当前快照均记录 ST 输入版本", True, "待自愈 0")

    def check_calendar_readiness(self, *, as_of: date | None = None) -> None:
        """检查生命周期下一开市日与跨年覆盖；缺失只报告，不推算交易日。"""
        self._cur_group = "F. 运行就绪度"
        self._say("\nF. 运行就绪度")
        readiness = inspect_trade_calendar(self.c, as_of=as_of)
        detail = calendar_readiness_detail(readiness)
        self._check("交易日历存在下一开市日", readiness["lifecycle_ready"], detail)
        self._check("交易日历已覆盖下一自然年", readiness["cross_year_ready"], detail)

    # ── B. 价格正确性 ──
    def check_prices(self) -> None:
        self._cur_group = "B. 价格正确性"
        self._say("\nB. 价格正确性")
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

        price_volume_mismatch = self._count(
            "SELECT count(*) FROM daily_bar "
            "WHERE volume>0 AND amount IS NOT NULL AND low>0 AND high>=low "
            "AND (amount/volume < low*0.99 OR amount/volume > high*1.01)"
        )
        self._check(
            "成交均价位于当日 OHLC 区间",
            price_volume_mismatch == 0,
            f"价量口径错配 {price_volume_mismatch}",
        )

        # 复权因子口径与业务一致：优先 adj_factor_clean（去抖），源 adj_factor 仅作审计。
        # 源因子在个别除权日可能返回 NULL（akshare 源端缺陷），clean 已回填前段因子，
        # 若判源列非空会误报"数据坏"——业务读因子一律 COALESCE(adj_factor_clean, adj_factor)。
        bad_factor = self._count(
            "SELECT count(*) FROM daily_bar "
            "WHERE COALESCE(adj_factor_clean, adj_factor) IS NULL "
            "OR COALESCE(adj_factor_clean, adj_factor)<=0")
        self._check("复权因子为正", bad_factor == 0, f"异常因子 {bad_factor}")

        # 涨跌幅越界：逐日 ST 事实 + 统一市场规则（包含主板 2026-07-06 切换）。
        from backend.market_rules import price_limit_pct_sql

        limit_sql = price_limit_pct_sql("sb.price_limit_pct", "st.is_st", "b.trade_date")
        over = self._count(
            "SELECT count(*) FROM daily_bar b JOIN stock_basic sb ON sb.code=b.code "
            "JOIN stock_st_status_daily st "
            "ON st.code=b.code AND st.trade_date=b.trade_date AND st.quality='accurate' "
            f"WHERE b.pre_close>0 AND abs(b.close/b.pre_close-1) > ({limit_sql})+0.005"
        )
        total = self._count(
            "SELECT count(*) FROM daily_bar b JOIN stock_st_status_daily st "
            "ON st.code=b.code AND st.trade_date=b.trade_date AND st.quality='accurate' "
            "WHERE b.pre_close>0"
        )
        self._check(
            "涨跌幅越界比例极低（<0.1%，余为新股/退市/复牌）",
            over / max(total, 1) < 0.001,
            f"{over}/{total} = {over/max(total,1)*100:.3f}%",
        )

    # ── C. 独立数据源交叉验证 ──
    def cross_validate(self, codes: list[str] | None = None, n_dates: int = 5) -> None:
        self._cur_group = "C. 独立数据源交叉验证"
        self._say("\nC. 独立数据源交叉验证（实时重拉对比）")
        from backend.datasource.akshare_source import AKShareSource

        # 默认覆盖各板块代表
        if codes is None:
            codes = ["600000.SH", "000001.SZ", "300750.SZ", "688981.SH"]
        src = AKShareSource()
        end = datetime.now(UTC).date()
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
                    "SELECT trade_date, close, COALESCE(adj_factor_clean, adj_factor) AS adj_factor "
                    "FROM daily_bar WHERE code=? "
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
        已知数据源局限（免费源无概念、退市股无市值）单列为豁免，不判失败但显式列出。
        """
        self._cur_group = "D. 需求字段完整性契约"
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
            ("daily_bar", "turnover_rate", "", "日线·换手率"),
        ]
        for table, col, where, label in required:
            w = f" AND {where}" if where else ""
            n_null = self._count(f"SELECT count(*) FROM {table} WHERE {col} IS NULL{w}")
            self._check(f"{label} 无缺失", n_null == 0, f"缺 {n_null}")
        pending_ladder_invalidations = self._count(
            "SELECT count(*) FROM limit_ladder_invalidation_outbox WHERE status='pending'"
        )
        self._check(
            "连板天梯·失效 outbox 无积压",
            pending_ladder_invalidations == 0,
            f"待处理 {pending_ladder_invalidations}",
        )
        # 复权因子单独查：与业务口径一致（COALESCE clean→源），源列允许 NULL（仅审计）
        adj_missing = self._count(
            "SELECT count(*) FROM daily_bar WHERE COALESCE(adj_factor_clean, adj_factor) IS NULL")
        self._check("日线·复权因子 无缺失", adj_missing == 0, f"缺 {adj_missing}")
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
        live_mv_nonpositive = self._count(
            "SELECT count(*) FROM daily_metrics m JOIN stock_basic sb ON sb.code=m.code "
            "WHERE sb.delist_date IS NULL AND (m.total_mv <= 0 OR m.float_mv <= 0)"
        )
        self._check(
            "在市股·市值均为正数",
            live_mv_nonpositive == 0,
            f"异常 {live_mv_nonpositive}",
        )
        inverted = mv_inverted_sql("m.total_mv", "m.float_mv")
        live_mv_inverted = self._count(
            "SELECT count(*) FROM daily_metrics m JOIN stock_basic sb ON sb.code=m.code "
            "WHERE sb.delist_date IS NULL AND m.total_mv > 0 AND m.float_mv > 0 "
            f"AND {inverted}"
        )
        recent_mv_inverted = self._count(
            "SELECT count(*) FROM daily_metrics m JOIN stock_basic sb ON sb.code=m.code "
            "WHERE sb.delist_date IS NULL AND m.total_mv > 0 AND m.float_mv > 0 "
            f"AND {inverted} AND m.trade_date >= ("
            "SELECT min(trade_date) FROM (SELECT trade_date FROM trade_calendar "
            "WHERE is_open AND trade_date <= (SELECT max(trade_date) FROM daily_bar) "
            "ORDER BY trade_date DESC LIMIT 90))"
        )
        self._check(
            "在市股·总市值不低于流通市值（万分之一容差）",
            live_mv_inverted == 0,
            f"全历史异常 {live_mv_inverted} 行；近90交易日台账范围 {recent_mv_inverted} 行",
            "结构体检覆盖库内全部年份；日常质量台账只覆盖最近90个交易日，"
            "因此历史异常不会出现在当前台账中。",
        )

        # 已知豁免（数据源固有局限，不判失败，但显式列出，绝不隐藏）
        self._say("  —— 已知豁免（数据源局限，非失败，明示）——")
        gaps = [
            ("stock_basic", "concept", "概念标签：F-DAT-10 属 Could，本期未采"),
        ]
        for table, col, note in gaps:
            n = self._count(f"SELECT count(*) FROM {table} WHERE {col} IS NULL")
            self._say(f"  [豁免] {table}.{col} 缺 {n} 行 — {note}")

    # ── E. 板块数据（结构 / 数值 / 契约）──
    def check_board(self) -> None:
        """板块四表（board_dict/board_member/board_bar/board_fund_flow）核查。

        与质检台账分工：板块缺口/新鲜度（board_index_gap、board_fund_stale 等）由质检台账
        +修复闭环负责；这里只查结构合法性、数值正确性与字段/标记契约（只读、不写台账）。
        """
        self._cur_group = "E. 板块数据"
        self._say("\nE. 板块数据（结构/数值/契约）")

        # 结构：孤儿板块（bar/member/fund 的 board_code 均须在字典）
        for table, label in (("board_bar", "指数"), ("board_member", "成分"), ("board_fund_flow", "资金流")):
            orphan = self._count(
                f"SELECT count(*) FROM (SELECT DISTINCT board_code FROM {table} "
                "WHERE board_code NOT IN (SELECT board_code FROM board_dict))")
            self._check(f"板块{label}无孤儿（均在 board_dict）", orphan == 0, f"孤儿板块 {orphan}")

        # 板块指数与个股同口径：须落在日历开市日
        non_open = self._count(
            "SELECT count(*) FROM board_bar b LEFT JOIN trade_calendar c "
            "ON c.trade_date=b.trade_date WHERE c.is_open IS NOT TRUE")
        self._check("板块指数日均为日历开市日", non_open == 0, f"非开市日 {non_open}")

        # 成分股（沪深）须在 stock_basic；北交所成分属既定宇宙外（include_bse=false），仅提示
        missing = self._count(
            "SELECT count(*) FROM (SELECT DISTINCT code FROM board_member "
            "WHERE code NOT LIKE '%.BJ' AND code NOT IN (SELECT code FROM stock_basic))")
        self._check("成分股（沪深）均有基础信息", missing == 0, f"缺 {missing}")
        bj = self._count(
            "SELECT count(*) FROM (SELECT DISTINCT code FROM board_member WHERE code LIKE '%.BJ')")
        self._say(f"  [INFO] 北交所成分 {bj} 只不在 stock_basic（宇宙剔除北交所，既定边界）")

        # 数值正确性（与个股 B 组同口径）
        nonpos = self._count(
            "SELECT count(*) FROM board_bar WHERE close<=0 OR open<=0 OR high<=0 OR low<=0")
        self._check("板块指数价格全为正", nonpos == 0, f"非正价行 {nonpos}")
        ohlc_bad = self._count(
            "SELECT count(*) FROM board_bar WHERE high < low OR high < open OR high < close "
            "OR low > open OR low > close")
        self._check("板块指数 OHLC 序关系正确", ohlc_bad == 0, f"违反 {ohlc_bad}")
        neg_vol = self._count("SELECT count(*) FROM board_bar WHERE volume<0 OR amount<0")
        self._check("板块指数成交量/额非负", neg_vol == 0, f"负值 {neg_vol}")

        # 字段契约：枚举取值与必填字段
        bad_type = self._count(
            "SELECT count(*) FROM board_dict WHERE board_type NOT IN ('concept','industry')")
        self._check("板块类型取值合法（concept/industry）", bad_type == 0, f"非法 {bad_type}")
        bad_period = self._count(
            "SELECT count(*) FROM board_fund_flow WHERE period NOT IN ('即时','3日','5日','10日','20日')")
        self._check("资金流周期取值合法", bad_period == 0, f"非法 {bad_period}")
        null_net = self._count("SELECT count(*) FROM board_fund_flow WHERE net_inflow IS NULL")
        self._check("资金流·净流入 无缺失", null_net == 0, f"缺 {null_net}")

        # 能力标记与实际数据双向一致（有标记须有数据、有数据须有标记）
        for flag, table, label in (
            ("has_bar", "board_bar", "指数"),
            ("has_members", "board_member", "成分"),
            ("has_fund_flow", "board_fund_flow", "资金流"),
        ):
            miss = self._count(
                f"SELECT count(*) FROM board_dict d WHERE d.{flag} IS TRUE "
                f"AND NOT EXISTS (SELECT 1 FROM {table} t WHERE t.board_code=d.board_code)")
            extra = self._count(
                f"SELECT count(*) FROM board_dict d WHERE d.{flag} IS NOT TRUE "
                f"AND EXISTS (SELECT 1 FROM {table} t WHERE t.board_code=d.board_code)")
            self._check(
                f"{label}能力标记与实际数据一致", miss == 0 and extra == 0,
                f"有标记无数据 {miss} / 有数据无标记 {extra}")

    def check_stock_board_correlation(self) -> None:
        """核查当前相关性派生表，不重算算法，也不写质量台账。

        DDL 约束能阻止新坏数据写入；本组仍显式扫描数值、引用和跨表口径，覆盖旧库、
        人工 SQL、版本升级残留以及底层行情被后续清理后的漂移。
        """
        from backend.indicators.stock_board_correlation import ALGORITHM_VERSION

        self._cur_group = "G. 个股走势关联板块"
        self._say("\nG. 个股走势关联板块（当前态/冠军/行情支撑）")

        duplicate_champions = self._count(
            "SELECT count(*) FROM (SELECT code,board_type,as_of_date FROM stock_board_correlation "
            "GROUP BY code,board_type,as_of_date HAVING count(*)>1)"
        )
        duplicate_states = self._count(
            "SELECT count(*) FROM (SELECT code,as_of_date FROM stock_board_correlation_state "
            "GROUP BY code,as_of_date HAVING count(*)>1)"
        )
        self._check(
            "相关性结果主键无重复",
            duplicate_champions == 0 and duplicate_states == 0,
            f"冠军重复 {duplicate_champions} / 状态重复 {duplicate_states}",
        )

        invalid_domain = self._count(
            "SELECT count(*) FROM stock_board_correlation "
            "WHERE board_type NOT IN ('industry','concept') "
            "OR confidence NOT IN ('high','medium','low')"
        )
        invalid_numeric = self._count(
            "SELECT count(*) FROM stock_board_correlation "
            "WHERE NOT isfinite(score) OR NOT isfinite(corr_20) OR NOT isfinite(corr_60) "
            "OR score NOT BETWEEN -1 AND 1 OR corr_20 NOT BETWEEN -1 AND 1 "
            "OR corr_60 NOT BETWEEN -1 AND 1"
        )
        invalid_samples = self._count(
            "SELECT count(*) FROM stock_board_correlation WHERE sample_20<15 OR sample_60<40"
        )
        self._check(
            "冠军类型与可信度取值合法", invalid_domain == 0, f"非法 {invalid_domain}"
        )
        self._check(
            "冠军分数与相关系数有限且位于 [-1,1]",
            invalid_numeric == 0,
            f"非法 {invalid_numeric}",
        )
        self._check(
            "冠军样本达到 15/40 门槛", invalid_samples == 0, f"不足 {invalid_samples}"
        )

        orphan_boards = self._count(
            "SELECT count(*) FROM stock_board_correlation c LEFT JOIN board_dict d "
            "ON d.board_code=c.board_code AND d.board_type=c.board_type "
            "WHERE d.board_code IS NULL"
        )
        orphan_states = self._count(
            "SELECT count(*) FROM stock_board_correlation c "
            "LEFT JOIN stock_board_correlation_state s "
            "  ON s.code=c.code AND s.as_of_date=c.as_of_date "
            "WHERE s.code IS NULL"
        )
        self._check(
            "冠军板块均有同类型字典记录", orphan_boards == 0, f"孤儿 {orphan_boards}"
        )
        self._check(
            "冠军均有对应每股状态", orphan_states == 0, f"孤儿 {orphan_states}"
        )

        mismatched_champions = self._count(
            "SELECT count(*) FROM stock_board_correlation c "
            "JOIN stock_board_correlation_state s "
            "  ON s.code=c.code AND s.as_of_date=c.as_of_date "
            "WHERE c.computed_at IS DISTINCT FROM s.computed_at "
            "OR c.algorithm_version IS DISTINCT FROM s.algorithm_version "
            "OR c.benchmark_code IS DISTINCT FROM s.benchmark_code "
            "OR c.benchmark_fallback IS DISTINCT FROM s.benchmark_fallback"
        )
        flag_mismatches = self._count(
            "SELECT count(*) FROM stock_board_correlation_state s WHERE "
            "s.has_industry_champion IS DISTINCT FROM EXISTS "
            "(SELECT 1 FROM stock_board_correlation c "
            " WHERE c.code=s.code AND c.as_of_date=s.as_of_date AND c.board_type='industry') OR "
            "s.has_concept_champion IS DISTINCT FROM EXISTS "
            "(SELECT 1 FROM stock_board_correlation c "
            " WHERE c.code=s.code AND c.as_of_date=s.as_of_date AND c.board_type='concept')"
        )
        # 每日快照下，仅对「最新 as_of_date 的快照」强制当前算法版本；历史旧版本不强求。
        stale_versions = self._count(
            "SELECT count(*) FROM stock_board_correlation_state s "
            "WHERE s.algorithm_version<>? AND s.as_of_date=("
            "SELECT max(s2.as_of_date) FROM stock_board_correlation_state s2 WHERE s2.code=s.code)",
            [ALGORITHM_VERSION],
        ) + self._count(
            "SELECT count(*) FROM stock_board_correlation c "
            "WHERE c.algorithm_version<>? AND c.as_of_date=("
            "SELECT max(s2.as_of_date) FROM stock_board_correlation_state s2 "
            "WHERE s2.code=c.code)",
            [ALGORITHM_VERSION],
        )
        self._check(
            "状态与冠军日期/时间/版本/基准一致",
            mismatched_champions == 0,
            f"不一致 {mismatched_champions}",
        )
        self._check(
            "状态冠军标记与实际行一致",
            flag_mismatches == 0,
            f"不一致 {flag_mismatches}",
        )
        self._check(
            f"结果算法版本均为 {ALGORITHM_VERSION}",
            stale_versions == 0,
            f"旧版本 {stale_versions}",
        )

        invalid_benchmarks = self._count(
            "SELECT count(*) FROM stock_board_correlation_state "
            "WHERE benchmark_code NOT IN ('000001.SH','399001.SZ','399006.SZ','000688.SH') "
            "OR (benchmark_fallback AND benchmark_code<>'000001.SH')"
        )
        self._check(
            "状态基准代码与回退标记合法", invalid_benchmarks == 0, f"非法 {invalid_benchmarks}"
        )

        uncovered_stock_dates = self._count(
            "SELECT count(*) FROM stock_board_correlation_state s "
            "WHERE s.as_of_date>COALESCE((SELECT max(b.trade_date) FROM daily_bar b "
            "WHERE b.code=s.code), DATE '0001-01-01')"
        )
        uncovered_board_dates = self._count(
            "SELECT count(*) FROM stock_board_correlation c "
            "WHERE c.as_of_date>COALESCE((SELECT max(b.trade_date) FROM board_bar b "
            "WHERE b.board_code=c.board_code), DATE '0001-01-01')"
        )
        unsupported_benchmark_dates = self._count(
            "SELECT count(*) FROM stock_board_correlation_state s "
            "WHERE s.as_of_date>COALESCE((SELECT max(b.trade_date) FROM index_bar b "
            "WHERE b.index_code=s.benchmark_code), DATE '0001-01-01')"
        )
        if uncovered_stock_dates:
            self._warn(
                "个股行情覆盖至结果日期",
                f"目标日未覆盖 {uncovered_stock_dates} 条",
                "可能是停牌或采集缺口，请以质检台账为准；该日期差异本身不否定结果。",
            )
        else:
            self._check("个股行情覆盖至结果日期", True, "目标日未覆盖 0 条")
        if uncovered_board_dates:
            self._warn(
                "冠军板块行情覆盖至结果日期",
                f"目标日未覆盖 {uncovered_board_dates} 条",
                "相关性结果仍由 15/40 共同有效样本门槛约束。",
            )
        else:
            self._check("冠军板块行情覆盖至结果日期", True, "目标日未覆盖 0 条")
        self._check(
            "基准目标日行情完整",
            unsupported_benchmark_dates == 0,
            f"目标日未覆盖 {unsupported_benchmark_dates} 条",
        )

    def run(self, cross: bool = True) -> bool:
        print("=" * 64)
        print("数据正确性 + 完整性 系统性核查")
        print("=" * 64)
        self.check_structure()
        self.check_prices()
        self.check_contract()
        self.check_board()
        self.check_stock_board_correlation()
        self.check_calendar_readiness()
        if cross:
            self.cross_validate()
        passed = sum(1 for item in self._structured if item["status"] == "pass")
        warnings = sum(1 for item in self._structured if item["status"] == "warn")
        total = len(self._structured)
        print("\n" + "=" * 64)
        print(f"核查结果：{passed} 通过 / {warnings} 提醒 / {total} 总项")
        fails = [n for n, ok, _ in self.results if not ok]
        if fails:
            print("未通过项：", fails)
        print("=" * 64)
        return not fails

    def run_structured(self, cross: bool = False) -> dict:
        """跑体检并返回结构化结果（供 Web 体检报告渲染）。

        默认 cross=False：只跑本地 SQL 的 A/B/D 组（快、无网络风险）；C 组联网交叉验证按需开。
        返回 {passed, warnings, total, all_ok, fails, groups:[{group, checks:[...]}]}。
        """
        self.results = []
        self._structured = []
        self.check_structure()
        self.check_prices()
        self.check_contract()
        self.check_board()
        self.check_stock_board_correlation()
        self.check_calendar_readiness()
        if cross:
            self.cross_validate()
        groups: dict[str, list] = {}
        order: list[str] = []
        for it in self._structured:
            g = it["group"] or "其他"
            if g not in groups:
                groups[g] = []
                order.append(g)
            groups[g].append(
                {
                    "name": it["name"],
                    "ok": it["ok"],
                    "status": it["status"],
                    "detail": it["detail"],
                    "help": it.get("help", ""),
                }
            )
        passed = sum(1 for it in self._structured if it["status"] == "pass")
        warnings = [it["name"] for it in self._structured if it["status"] == "warn"]
        total = len(self._structured)
        fails = [it["name"] for it in self._structured if it["status"] == "fail"]
        return {
            "passed": passed,
            "warning_count": len(warnings),
            "warnings": warnings,
            "total": total,
            "all_ok": not fails,
            "fails": fails,
            "groups": [{"group": g, "checks": groups[g]} for g in order],
        }
