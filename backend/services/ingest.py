"""数据入库编排服务（T-M1-5/6：交易日历+基础信息+日线+衍生指标入库）。

支持：
- backfill：全量回填（近 N 年），按股逐只拉取→入库→留痕；可断点续跑（跳过已入库股票）。
- update：增量更新（每只股票从已入库最新日 +1 起补到今天）。
- 少量股票小批量验证（codes 传入子集）。

防幸存者偏差留待 baostock（T-M1-4）补退市股；本服务先打通在市股票主链路。
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from backend.common.logging import get_logger
from backend.config import get_settings
from backend.dataquality.checker import add_markers, sanitize_bars
from backend.datasource.akshare_source import classify_board
from backend.datasource.base import DataSource, get_source
from backend.storage.ddl import init_db
from backend.storage.duckdb_client import get_client
from backend.storage.repository import MarketRepository

log = get_logger("services.ingest")


class IngestionService:
    def __init__(self, source: DataSource | None = None):
        self.s = get_settings()
        # 全局 socket 超时：根治公开接口"无超时挂死"——卡住的请求到点抛错，
        # 由 @with_retry 重试，循环不再僵死（需求 §10.1 稳定性）。
        import socket

        socket.setdefaulttimeout(self.s.datasource.socket_timeout_sec)

        # 主源由配置 datasource.primary 决定（可插拔，改配置即换源）
        self.src = source or get_source(self.s.datasource.primary)
        self.c = get_client()
        init_db(self.c)  # 确保表已建
        self.repo = MarketRepository(self.c)
        self._bao: DataSource | None = None

    def _bao_source(self) -> DataSource:
        """惰性创建补充源（默认 baostock，由 datasource.fallback 配置决定）。"""
        if self._bao is None:
            self._bao = get_source(self.s.datasource.fallback)
        return self._bao

    def _source_for(self, capability: str) -> DataSource:
        """按能力选源：主源支持→主源；否则补源支持→补源；都不支持→报错。

        替代"谁负责哪类数据"的硬编码，让分工由各源 capabilities 声明驱动。
        """
        if self.src.supports(capability):
            return self.src
        bao = self._bao_source()
        if bao.supports(capability):
            return bao
        from backend.common.exceptions import DataSourceError

        raise DataSourceError(f"无数据源支持能力: {capability}")

    def _in_target_board(self, code6: str) -> tuple[bool, str, float]:
        """是否纳入目标板块（默认剔除北交所）。返回 (纳入?, board, limit_pct)。"""
        _, board, limit = classify_board(code6)
        if not self.s.universe.include_bse and board == "北交所":
            return False, board, limit
        return board in self.s.universe.boards, board, limit

    # ── 交易日历 ──
    def ingest_calendar(self, start: date, end: date) -> int:
        df = self.src.get_trade_calendar(start, end)
        n = self.repo.upsert_trade_calendar(df)
        self.repo.log_update("trade_calendar", self.src.name, start, end, n, "success")
        log.info("交易日历入库 %d 个交易日", n)
        return n

    # ── 指数 ──
    def ingest_indices(self, start: date, end: date) -> int:
        codes = [self.s.backtest.benchmark_main, *self.s.backtest.benchmark_others]
        total = 0
        for idx in codes:
            try:
                df = self.src.get_index_bar(idx, start, end)
                total += self.repo.upsert_index_bar(df)
            except Exception as e:  # noqa: BLE001
                log.warning("指数 %s 入库失败: %s", idx, e)
                self.repo.log_update("index_bar", self.src.name, start, end, 0, "failed", str(e))
        log.info("指数入库 %d 行（%s）", total, codes)
        return total

    # ── 股票列表 + 基础信息 ──
    def ingest_stock_basic(self, codes: list[str] | None = None) -> pd.DataFrame:
        """入库 stock_basic（板块由代码判定），返回纳入的 code 列表 DataFrame。"""
        listing = self.src.get_stock_list()  # code, code6, name
        if codes:
            listing = listing[listing["code"].isin(codes)]
        rows = []
        for _, r in listing.iterrows():
            exch, board, limit = classify_board(r["code6"])
            # 只写确切已知列；list_date/delist_date 由 baostock enrich 负责，
            # 此处不写以免 upsert 覆盖（保护数据完整性）。
            rows.append(
                {
                    "code": r["code"],
                    "name": r["name"],
                    "exchange": exch,
                    "board": board,
                    "price_limit_pct": limit,
                }
            )
        basic = pd.DataFrame(rows)
        # 仅保留目标板块（默认剔除北交所）
        if not self.s.universe.include_bse:
            basic = basic[basic["board"] != "北交所"]
        n = self.repo.upsert_stock_basic(basic)
        self.repo.log_update("stock_basic", self.src.name, None, None, n, "success")
        log.info("股票基础信息入库 %d 只", n)
        return basic

    # ── 单只股票日线 + 衍生指标 ──
    def _is_st_by_name(self, code: str) -> bool:
        """按 stock_basic 当前名称判定是否 ST（含 ST/*ST），带进程内缓存。"""
        cache = getattr(self, "_st_name_cache", None)
        if cache is None:
            df = self.repo.c.query_df("SELECT code, name FROM stock_basic")
            cache = {r["code"]: ("ST" in str(r["name"]).upper()) for _, r in df.iterrows()}
            self._st_name_cache = cache
        return cache.get(code, False)

    def ingest_one_daily(
        self, code: str, start: date, end: date,
        board_limit_pct: float | None = None, is_st: bool | None = None,
        source: DataSource | None = None,
    ) -> int:
        df = (source or self.src).get_daily_bar(code, start, end)
        if df is None or df.empty:
            return 0
        # 入库闸门：行级自清洗 + 校验（坏行入库前就处理，不再依赖事后手动修）
        df, sanitize_stats = sanitize_bars(df)
        if df.empty:
            return 0
        if sanitize_stats["dropped"] or sanitize_stats["fixed_ohl"]:
            log.warning("%s 入库清洗：丢弃%d 修复OHL%d 零成交填补%d",
                        code, sanitize_stats["dropped"], sanitize_stats["fixed_ohl"],
                        sanitize_stats["filled_zerovol"])
        # 缺省时按代码判定板块涨跌幅；ST 按当前名称推导（T-M7-8：入库即置标，
        # 不再一律 False。免费源无历史每日 ST，故用 stock_basic 当前名称尽力而为）
        if board_limit_pct is None:
            _, _, board_limit_pct = classify_board(code.split(".")[0])
        if is_st is None:
            is_st = self._is_st_by_name(code)
        # 质检标记：涨跌停/一字板/ST（回测撮合前提）
        df = add_markers(df, board_limit_pct, is_st)
        # OHL 修补行：真实振幅未知 → 强制不标一字板，并记入问题台账（不静默/不臆造）
        if "_ohl_repaired" in df.columns and df["_ohl_repaired"].any():
            df.loc[df["_ohl_repaired"], "is_one_word"] = False
            self._record_ohl_repairs(code, df[df["_ohl_repaired"]]["trade_date"])
            df = df.drop(columns=["_ohl_repaired"])
        bar_cols = [
            "code", "trade_date", "open", "high", "low", "close",
            "pre_close", "volume", "amount", "adj_factor", "turnover_rate",
            "is_st", "is_suspended", "limit_status", "is_one_word",
        ]
        n = self.repo.upsert_daily_bar(df[bar_cols])
        # 衍生指标：流通市值 = 收盘 × 当日流通股本（新浪日线自带 float_share）
        if "float_share" in df.columns:
            metrics = pd.DataFrame(
                {
                    "code": df["code"],
                    "trade_date": df["trade_date"],
                    "float_mv": df["close"] * df["float_share"],
                    "total_mv": None,
                }
            )
            self.repo.upsert_daily_metrics(metrics)
        return n

    # ── 估值/市值（总市值/总股本，补 G2）──
    def ingest_valuation(self, codes: list[str] | None = None, years: int | None = None) -> dict:
        """补每日总市值到 daily_metrics.total_mv，并把最新总/流通股本写入 stock_basic。

        数据源 stock_value_em（东财市值接口，可用）。按在市股逐只拉取。
        """
        years = years or self.s.datasource.history_years
        end = date.today()
        start = date(end.year - years, end.month, end.day)
        live = self.repo.c.query_df(
            "SELECT code FROM stock_basic WHERE delist_date IS NULL"
        )["code"].tolist()
        if codes:
            live = [c for c in live if c in codes]
        val_src = self._source_for("valuation")
        # 断点续跑：跳过已有 total_mv 的票
        done = set(self.repo.c.query_df(
            "SELECT DISTINCT code FROM daily_metrics WHERE total_mv IS NOT NULL"
        )["code"].tolist())
        ok, fail, skip, rows = 0, 0, 0, 0
        for i, code in enumerate(live, 1):
            if code in done:
                skip += 1
                continue
            try:
                v = val_src.get_valuation(code, start, end)
                if v is None or v.empty:
                    continue
                # 只保留 daily_bar 已有的交易日，杜绝 value_em 日期错位产生游离 metrics 行
                bar_dates = {
                    pd.Timestamp(d).date()
                    for d in self.repo.c.query_df(
                        "SELECT trade_date FROM daily_bar WHERE code = ?", [code]
                    )["trade_date"]
                }
                v = v[v["trade_date"].isin(bar_dates)]
                if v.empty:
                    continue
                # 每日总市值入 daily_metrics（只更新 total_mv 列，不动 float_mv）
                rows += self.repo.upsert_daily_metrics(v[["code", "trade_date", "total_mv"]])
                # 最新总/流通股本入 stock_basic
                last = v.dropna(subset=["total_share"]).tail(1)
                if not last.empty:
                    self.repo.upsert_stock_basic(pd.DataFrame([{
                        "code": code,
                        "total_share": int(last["total_share"].iloc[0]),
                        "float_share": int(last["float_share"].iloc[0]) if pd.notna(last["float_share"].iloc[0]) else None,
                    }]))
                ok += 1
                if i % 50 == 0 or i == len(live):
                    log.info("估值进度 %d/%d（成功%d 跳过%d 失败%d，total_mv %d行）", i, len(live), ok, skip, fail, rows)
            except Exception as e:  # noqa: BLE001
                fail += 1
                log.warning("%s 估值入库失败: %s", code, e)
                self.repo.log_update("daily_metrics", val_src.name, start, end, 0, "failed", f"{code}: {e}")
        result = {"target": len(live), "ok": ok, "skip": skip, "fail": fail, "total_mv_rows": rows}
        log.info("估值入库完成: %s", result)
        return result

    def _record_ohl_repairs(self, code: str, trade_dates) -> None:
        """把 OHL 修补行记入 data_quality_issue（修补可见、不静默）。"""
        from datetime import datetime

        rows = [
            {
                "id": int(self.c.query_df("SELECT nextval('seq_quality_issue') AS v").iloc[0]["v"]),
                "code": code, "trade_date": td, "issue_type": "ohl_repaired",
                "severity": "low", "status": "open",
                "detail": "开高低缺失，已用收盘价回填（不标一字板）", "detected_at": datetime.now(),
            }
            for td in trade_dates
        ]
        if not rows:
            return
        tmp = pd.DataFrame(rows)
        with self.c.temp_view(tmp, prefix="ohl") as v:
            self.c.execute(
                "INSERT INTO data_quality_issue "
                "(id, code, trade_date, issue_type, severity, status, detail, detected_at) "
                "SELECT id, code, trade_date, issue_type, severity, status, detail, detected_at "
                f"FROM {v}"
            )

    # ── 全量回填 ──
    def backfill(self, codes: list[str] | None = None, years: int | None = None, ctx=None) -> dict:
        """全量回填近 N 年。codes=None 表示全市场；可断点续跑（跳过已入库）。

        ctx（M2.8-B，可选）：逐股写实时日志 + 进度 + checkpoint。续跑天然幂等（跳过已入库）。
        """
        years = years or self.s.datasource.history_years
        end = date.today()
        start = date(end.year - years, end.month, end.day)
        log.info("开始回填 %s ~ %s", start, end)

        self.ingest_calendar(start, end)
        self.ingest_indices(start, end)
        basic = self.ingest_stock_basic(codes)
        target_codes = basic["code"].tolist()
        # 板块涨跌幅 + ST 状态查找表（ST 由名称含 "ST" 判定）
        limit_lut = dict(zip(basic["code"], basic["price_limit_pct"]))
        st_lut = {
            r["code"]: ("ST" in str(r["name"]).upper()) for _, r in basic.iterrows()
        }

        loaded = self.repo.get_loaded_codes()
        ok, skip, fail = 0, 0, 0
        total_rows = 0
        n = len(target_codes)
        for i, code in enumerate(target_codes, 1):
            if code in loaded:
                skip += 1
                continue
            try:
                rows = self.ingest_one_daily(
                    code, start, end, limit_lut.get(code), st_lut.get(code)
                )
                total_rows += rows
                ok += 1
                if i % 20 == 0 or i == n:
                    log.info("进度 %d/%d（成功%d 跳过%d 失败%d，累计%d行）",
                             i, n, ok, skip, fail, total_rows)
                    if ctx:
                        ctx.progress(min(0.1 + 0.78 * i / max(n, 1), 0.88),
                                     f"回填 {i}/{n}（成功{ok} 跳过{skip} 失败{fail}，累计{total_rows}行）")
                        ctx.log(f"[{i}/{n}] {code} 回填 +{rows} 行")
                        ctx.set_checkpoint(done=i, skipped=skip, total=n)
            except Exception as e:  # noqa: BLE001
                fail += 1
                log.warning("%s 回填失败: %s", code, e)
                if ctx:
                    ctx.log(f"[{i}/{n}] {code} 回填失败: {e}", "warn")
                self.repo.log_update("daily_bar", self.src.name, start, end, 0, "failed", f"{code}: {e}")
        result = {"target": len(target_codes), "ok": ok, "skip": skip, "fail": fail, "rows": total_rows}
        log.info("回填完成: %s", result)
        # 入库后自动校验（全市场回填才跑契约检查，避免部分加载误报）
        if codes is None:
            self._post_ingest_validate()
        return result

    def _post_ingest_validate(self) -> None:
        """回填后自动跑结构+契约校验，FAIL 以告警暴露（不必人肉跑 verify-data）。"""
        try:
            from backend.services.data_verify import DataVerifier

            v = DataVerifier(self.c, quiet=True)
            v.check_structure()
            v.check_contract()
            fails = v.fails()
            if fails:
                log.warning("⚠️ 入库后校验发现 %d 项不达标: %s（详情跑 verify-data）", len(fails), fails)
            else:
                log.info("✅ 入库后校验通过（结构+字段契约）")
        except Exception as e:  # noqa: BLE001
            log.warning("入库后自动校验异常: %s", e)

    # ── 增量更新 ──
    def _update_one(self, code: str, end: date, source: DataSource | None = None) -> int:
        """更新单只股票（增量）。供串行/并发共用。返回写入行数。"""
        last = self.repo.get_max_bar_date(code)
        start = (last + timedelta(days=1)) if last else date(
            end.year - self.s.datasource.history_years, end.month, end.day)
        if start > end:
            return 0
        return self.ingest_one_daily(code, start, end, source=source)

    def update(self, codes: list[str] | None = None, concurrency: int | None = None, ctx=None) -> dict:
        """增量更新：每只股票从已入库最新日 +1 起补到今天。

        concurrency（T-M7-7）：>1 时用线程池并发拉取，**每线程独立 DataSource（限流按线程隔离，
        总请求速率≈N×rate_limit_per_sec）**；写入经 DuckDB 单写锁串行，数据零影响。默认读配置
        `datasource.update_concurrency`。⚠️ 调高并发即调高总请求速率，注意免费源封禁风险。

        ctx（M2.8-B，可选 TaskContext）：传入则逐股写实时日志 + 进度 + checkpoint（FR-DM-9/10）。
        续跑天然幂等：从各股已入库最新日 +1 起，重复跑只补缺口。
        """
        end = date.today()
        concurrency = concurrency or self.s.datasource.update_concurrency
        basic = (
            self.repo.c.query_df("SELECT code FROM stock_basic WHERE delist_date IS NULL")["code"].tolist()
        )
        if codes:
            basic = [c for c in basic if c in codes]
        self.ingest_calendar(end - timedelta(days=30), end)
        self.ingest_indices(end - timedelta(days=30), end)
        ok = fail = total_rows = 0
        n = len(basic)

        def _tick(i: int, code: str, rows: int) -> None:
            if ctx and (i % 20 == 0 or i == n):
                ctx.progress(min(0.1 + 0.78 * i / max(n, 1), 0.88),
                             f"增量更新 {i}/{n}（成功{ok} 失败{fail}，累计{total_rows}行）")
                ctx.log(f"[{i}/{n}] {code} 增量 +{rows} 行")
                ctx.set_checkpoint(done=i, total=n)

        if concurrency <= 1:  # 串行（默认，最稳）
            for i, code in enumerate(basic, 1):
                try:
                    rows = self._update_one(code, end)
                    total_rows += rows
                    ok += 1
                    _tick(i, code, rows)
                except Exception as e:  # noqa: BLE001
                    fail += 1
                    log.warning("%s 增量失败: %s", code, e)
                    if ctx:
                        ctx.log(f"[{i}/{n}] {code} 增量失败: {e}", "warn")
                    self.repo.log_update("daily_bar", self.src.name, None, end, 0, "failed", f"{code}: {e}")
        else:  # 并发：线程局部 DataSource（限流按线程隔离），写入由 DuckDB RLock 串行
            import threading
            from concurrent.futures import ThreadPoolExecutor, as_completed

            from backend.datasource.akshare_source import AKShareSource
            tls = threading.local()

            def _worker(code: str) -> int:
                src = getattr(tls, "src", None)
                if src is None:
                    src = AKShareSource()
                    tls.src = src
                return self._update_one(code, end, source=src)

            with ThreadPoolExecutor(max_workers=concurrency) as ex:
                futs = {ex.submit(_worker, c): c for c in basic}
                for i, fut in enumerate(as_completed(futs), 1):
                    code = futs[fut]
                    try:
                        rows = fut.result()
                        total_rows += rows
                        ok += 1
                        _tick(i, code, rows)  # 在调用线程内写日志，线程安全
                    except Exception as e:  # noqa: BLE001
                        fail += 1
                        log.warning("%s 增量失败: %s", code, e)
                        if ctx:
                            ctx.log(f"[{i}/{n}] {code} 增量失败: {e}", "warn")
                        self.repo.log_update("daily_bar", self.src.name, None, end, 0, "failed", f"{code}: {e}")

        result = {"target": n, "ok": ok, "fail": fail, "rows": total_rows, "concurrency": concurrency}
        log.info("增量更新完成: %s", result)
        return result

    # ── 指定日期采集（FR-DM-3 更多选项，M2.8-B）──
    def ingest_date(self, start: date, end: date, codes: list[str] | None = None, ctx=None) -> dict:
        """补指定日期（或区间）的行情。codes=None 表示全部在市股票。

        逐股拉取 [start, end] 区间并入库（沿用 ingest_one_daily 的清洗/标记/幂等 upsert）。
        返回受影响交易日列表供调用方标记评分快照失效。
        """
        live = self.repo.c.query_df(
            "SELECT code, name, price_limit_pct FROM stock_basic WHERE delist_date IS NULL")
        if codes:
            live = live[live["code"].isin(codes)]
        # 确保区间内日历存在
        self.ingest_calendar(start, end)
        limit_lut = dict(zip(live["code"], live["price_limit_pct"]))
        st_lut = {r["code"]: ("ST" in str(r["name"]).upper()) for _, r in live.iterrows()}
        target = live["code"].tolist()
        n = len(target)
        ok = fail = total_rows = 0
        for i, code in enumerate(target, 1):
            try:
                rows = self.ingest_one_daily(code, start, end, limit_lut.get(code), st_lut.get(code))
                total_rows += rows
                ok += 1
                if ctx and (i % 20 == 0 or i == n):
                    ctx.progress(min(0.1 + 0.78 * i / max(n, 1), 0.88), f"采集 {i}/{n}（累计{total_rows}行）")
                    ctx.log(f"[{i}/{n}] {code} {start}~{end} +{rows} 行")
                    ctx.set_checkpoint(done=i, total=n)
            except Exception as e:  # noqa: BLE001
                fail += 1
                log.warning("%s 指定采集失败: %s", code, e)
                if ctx:
                    ctx.log(f"[{i}/{n}] {code} 采集失败: {e}", "warn")
                self.repo.log_update("daily_bar", self.src.name, start, end, 0, "failed", f"{code}: {e}")
        # 受影响交易日 = 区间内开市日
        days = self.repo.c.query_df(
            "SELECT trade_date FROM trade_calendar WHERE is_open AND trade_date BETWEEN ? AND ?",
            [start, end])["trade_date"].tolist()
        dates = [str(pd.Timestamp(d).date()) for d in days]
        result = {"target": n, "ok": ok, "fail": fail, "rows": total_rows,
                  "range": [str(start), str(end)], "dates": dates}
        log.info("指定日期采集完成: %s", {k: v for k, v in result.items() if k != "dates"})
        return result

    # ══════════════════════════════════════════════════════════
    # baostock 补充（T-M1-4）：上市/退市日 + 退市股历史（防幸存者偏差）
    # ══════════════════════════════════════════════════════════

    def enrich_basic_dates(self) -> int:
        """补全 stock_basic 的上市/退市日 + 行业（含新增退市股），按能力选源。"""
        dates_src = self._source_for("basic_dates")
        df = dates_src.get_basic_dates()  # code,name,list_date,delist_date,is_delisted
        # 行业映射（证监会行业）
        try:
            ind = self._source_for("industry").get_industry()
            ind_map = dict(zip(ind["code"], ind["industry"]))
        except Exception as e:  # noqa: BLE001
            log.warning("行业获取失败，industry 置空: %s", e)
            ind_map = {}
        rows = []
        for _, r in df.iterrows():
            code6 = r["code"].split(".")[0]
            ok, board, limit = self._in_target_board(code6)
            if not ok:
                continue
            exch, _, _ = classify_board(code6)
            rows.append(
                {
                    "code": r["code"], "name": r["name"], "exchange": exch, "board": board,
                    "list_date": r["list_date"], "delist_date": r["delist_date"],
                    "industry": ind_map.get(r["code"]),
                    "price_limit_pct": limit,
                }
            )
        out = pd.DataFrame(rows)
        n = self.repo.upsert_stock_basic(out)
        self.repo.log_update("stock_basic", dates_src.name, None, None, n, "success", "补上市/退市日+行业")
        log.info("%s 补全基础信息 %d 只（含退市股+行业）", dates_src.name, n)
        return n

    def ingest_delisted(self, years: int | None = None, limit: int | None = None) -> dict:
        """灌入"近 N 年内退市"的退市股历史日线（防幸存者偏差核心）。

        只取退市日落在回测窗口内的票（更早退市的在 5 年窗口内无数据，跳过）。
        """
        years = years or self.s.datasource.history_years
        end = date.today()
        start = date(end.year - years, end.month, end.day)
        bao = self._source_for("delisted")  # 退市股能力源

        dl = bao.get_delisted_list()  # code,name,delist_date
        dl = dl.dropna(subset=["delist_date"])
        dl = dl[dl["delist_date"] >= start]
        # 仅目标板块
        dl = dl[dl["code"].apply(lambda c: self._in_target_board(c.split(".")[0])[0])]
        if limit:
            dl = dl.head(limit)
        log.info("待灌退市股 %d 只（退市日 >= %s）", len(dl), start)

        loaded = self.repo.get_loaded_codes()
        ok, skip, fail, total_rows = 0, 0, 0, 0
        for _, r in dl.iterrows():
            code = r["code"]
            if code in loaded:
                skip += 1
                continue
            try:
                code6 = code.split(".")[0]
                _, _, limit_pct = self._in_target_board(code6)
                is_st = "ST" in str(r["name"]).upper()
                # 补 stock_basic 一行（退市股，含退市日）
                self.repo.upsert_stock_basic(
                    pd.DataFrame([{
                        "code": code, "name": r["name"], "exchange": classify_board(code6)[0],
                        "board": classify_board(code6)[1], "delist_date": r["delist_date"],
                        "price_limit_pct": limit_pct,
                    }])
                )
                rows = self.ingest_one_daily(
                    code, start, r["delist_date"], limit_pct, is_st, source=bao
                )
                total_rows += rows
                ok += 1
            except Exception as e:  # noqa: BLE001
                fail += 1
                log.warning("退市股 %s 灌入失败: %s", code, e)
                self.repo.log_update("daily_bar", bao.name, start, None, 0, "failed", f"{code}: {e}")
        result = {"target": len(dl), "ok": ok, "skip": skip, "fail": fail, "rows": total_rows}
        log.info("退市股灌入完成: %s", result)
        return result
