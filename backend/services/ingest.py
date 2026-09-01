"""数据入库编排服务（T-M1-5/6：交易日历+基础信息+日线+衍生指标入库）。

支持：
- backfill：全量回填（近 N 年），按股逐只拉取→入库→留痕；可断点续跑（跳过已入库股票）。
- update：增量更新（每只股票从已入库最新日 +1 起补到今天）。
- 少量股票小批量验证（codes 传入子集）。

防幸存者偏差留待 baostock（T-M1-4）补退市股；本服务先打通在市股票主链路。
"""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import date, datetime, timedelta

import pandas as pd

from backend.common.exceptions import DataSourceError
from backend.common.logging import get_logger
from backend.config import get_effective_settings
from backend.dataquality.checker import add_markers, sanitize_bars
from backend.datasource.akshare_source import classify_board
from backend.datasource.base import (
    DataSource,
    check_thread_cancel,
    get_source,
    thread_cancel_scope,
)
from backend.limit_ladder.rules import (
    PointInTimeSTStatus,
    STStatusQuality,
    resolve_point_in_time_st,
)
from backend.services.async_task import TaskCancelled
from backend.services.market_benchmark import configured_benchmark_codes
from backend.services.stock_st_status import StockSTStatusFact, StockSTStatusService
from backend.services.trade_calendar_readiness import (
    calendar_readiness_detail,
    calendar_request_end,
    inspect_trade_calendar,
)
from backend.storage.ddl import init_db
from backend.storage.duckdb_client import get_client
from backend.storage.repository import MarketRepository

# baostock 是会话型 API，并发不安全；兜底取数全进程串行（兜底本就罕见，几乎不影响整体速度）。
_BAO_FALLBACK_LOCK = threading.Lock()
_UPDATE_READY_SAMPLE = [
    "000001.SZ", "000002.SZ", "000063.SZ", "000333.SZ", "300750.SZ",
    "600000.SH", "600519.SH", "601318.SH", "688981.SH",
]
_UPDATE_READY_RATIO = 0.60

log = get_logger("services.ingest")


class IngestionService:
    def __init__(self, source: DataSource | None = None):
        # 生效配置 = YAML ⊕ 前端 app_config 覆盖（限流/并发/超时改前端即生效）。
        self.s = get_effective_settings()
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

    def _mark_snapshots_stale(
        self,
        dates: list[date] | None = None,
        *,
        ladder_dates: list[date] | None = None,
    ) -> int:
        """Legacy test seam; collection no longer invalidates derived results."""
        _ = (dates, ladder_dates)
        return 0

    def _log_market_day_terminal(
        self,
        trade_date: date,
        *,
        expected: int,
        successful: int,
        failed: int,
        run_id: str,
    ) -> dict:
        """Write the only structured market-day terminal fact consumed by the ladder gate."""
        status = "success" if failed == 0 and successful >= expected else (
            "partial" if successful > 0 else "failed"
        )
        detail = {
            "kind": "market_day_terminal",
            "run_id": run_id,
            "expected": expected,
            "successful": successful,
            "failed": failed,
            "status": status,
        }
        self.repo.log_update(
            "daily_bar",
            "pipeline",
            trade_date,
            trade_date,
            successful,
            status,
            json.dumps(detail, ensure_ascii=False, sort_keys=True),
        )
        return detail

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

    def _thread_source(self, tls, source_name: str) -> DataSource:
        """并发采集工作线程内按配置创建数据源实例，避免绕过 Web/YAML 的 source 选择。"""
        src = getattr(tls, "src", None)
        if src is None or getattr(src, "name", None) != source_name:
            src = get_source(source_name)
            tls.src = src
        return src

    @staticmethod
    def _run_bounded_parallel(
        items: list,
        worker,
        *,
        concurrency: int,
        ctx,
        wait_label: str,
        on_complete,
    ) -> None:
        """有界执行可取消采集，不预提交全量任务，也不留下终止后的孤儿写线程。

        收到终止时只取消尚未开始的 Future，并等待最多 ``concurrency`` 个在途工作单元
        到达安全边界。工作线程内的数据源限流/重试会读取同一取消检查器，从而跳过后续
        退避和重试；执行器完全退出后，外层才会把任务标记为 interrupted。
        """
        iterator = iter(items)
        executor = ThreadPoolExecutor(max_workers=concurrency)
        pending: dict = {}
        completed = 0
        last_heartbeat = 0.0

        def _run(item):
            with thread_cancel_scope(ctx.check_cancel if ctx else None):
                return worker(item)

        def _submit_one() -> bool:
            try:
                item = next(iterator)
            except StopIteration:
                return False
            pending[executor.submit(_run, item)] = item
            return True

        for _ in range(min(concurrency, len(items))):
            _submit_one()

        try:
            while pending:
                if ctx:
                    ctx.check_cancel()
                done_futures, _ = wait(
                    set(pending), timeout=1.0, return_when=FIRST_COMPLETED
                )
                now = time.monotonic()
                if not done_futures:
                    if ctx and now - last_heartbeat >= 10:
                        last_heartbeat = now
                        ctx.log(
                            f"{wait_label}等待中：已完成 {completed}/{len(items)}，"
                            f"在途 {len(pending)}，外部接口返回后继续"
                        )
                        ctx.flush()
                    continue
                for future in done_futures:
                    item = pending.pop(future)
                    if ctx:
                        ctx.check_cancel()
                    try:
                        value = future.result()
                        error = None
                    except TaskCancelled:
                        raise
                    except Exception as exc:  # noqa: BLE001 - 单工作单元失败交给调用方记录
                        value = None
                        error = exc
                    completed += 1
                    on_complete(completed, item, value, error, len(pending))
                    if ctx:
                        ctx.check_cancel()
                    _submit_one()
        except TaskCancelled:
            cancelled = sum(1 for future in pending if future.cancel())
            running = sum(1 for future in pending if not future.done() and not future.cancelled())
            if ctx:
                ctx.log(
                    f"终止收尾：已取消 {cancelled} 个排队工作单元，"
                    f"等待 {running} 个在途请求安全结束…",
                    "warn",
                )
                ctx.flush()
            executor.shutdown(wait=True, cancel_futures=True)
            raise
        except BaseException:
            executor.shutdown(wait=True, cancel_futures=True)
            raise
        else:
            executor.shutdown(wait=True)

    def _in_target_board(self, code6: str) -> tuple[bool, str, float]:
        """是否纳入目标板块（默认剔除北交所）。返回 (纳入?, board, limit_pct)。"""
        _, board, limit = classify_board(code6)
        if not self.s.universe.include_bse and board == "北交所":
            return False, board, limit
        return board in self.s.universe.boards, board, limit

    # ── 交易日历 ──
    def ingest_calendar(self, start: date, end: date, ctx=None) -> int:
        # 主动请求到下一自然年末；数据源尚未发布的日期保持缺失，绝不按工作日伪造。
        # 这样源一旦发布跨年日历，日常更新和调度自愈都会自动吸收，无需等年末人工改参数。
        cal_end = calendar_request_end(end)
        if ctx:
            ctx.log(f"子任务：交易日历采集开始（{start}~{cal_end}，源 {self.src.name}；"
                    f"日历是「已知的未来」故按固定窗口回看补缺口、终点尝试延至下一自然年末，"
                    f"与日线按已入库最新日+1 增量不同口径）")
            ctx.flush()
        df = self.src.get_trade_calendar(start, cal_end)
        n = self.repo.upsert_trade_calendar(df)
        readiness = inspect_trade_calendar(self.c)
        detail = calendar_readiness_detail(readiness)
        # date_end 表示请求上界而非源端实际覆盖；detail 必须同时记录真实最远开市日，避免运维误读。
        self.repo.log_update(
            "trade_calendar",
            self.src.name,
            start,
            cal_end,
            n,
            "success",
            f"请求上界 {cal_end}；{detail}",
        )
        log.info("交易日历入库 %d 行（请求至 %s；%s）", n, cal_end, detail)
        if not readiness["lifecycle_ready"] or not readiness["cross_year_ready"]:
            message = (
                f"交易日历前瞻覆盖不足（{detail}）；已请求至 {cal_end}，"
                "若数据源尚未发布下一年度安排，规则发布/归档/恢复继续 fail-closed"
            )
            log.warning(message)
            if ctx:
                ctx.log(message, "warning")
        if ctx:
            ctx.log(f"子任务：交易日历采集完成，写入/更新 {n} 行；{detail}")
        return n

    # ── 指数 ──
    def ingest_indices(
        self,
        start: date,
        end: date,
        ctx=None,
        codes: list[str] | None = None,
    ) -> int:
        """采集配置内指数；可指定子集供逐指数增量补采复用。"""
        configured = configured_benchmark_codes()
        allowed = set(configured)
        codes = list(dict.fromkeys(codes if codes is not None else configured))
        unsupported = [code for code in codes if code not in allowed]
        if unsupported:
            raise ValueError(f"指数不在系统配置清单中: {unsupported}")
        total = 0
        if ctx:
            ctx.log(f"子任务：指数行情采集开始，{len(codes)} 个指数，区间 {start}~{end}")
            ctx.flush()
        for idx in codes:
            try:
                df = self.src.get_index_bar(idx, start, end)
                total += self.repo.upsert_index_bar(df)
                if ctx:
                    ctx.log(f"指数 {idx} 完成：{len(df) if df is not None else 0} 行")
            except Exception as e:  # noqa: BLE001
                log.warning("指数 %s 入库失败: %s", idx, e)
                if ctx:
                    ctx.log(f"指数 {idx} 采集失败：{e}", "warn")
                self.repo.log_update("index_bar", self.src.name, start, end, 0, "failed", str(e))
        log.info("指数入库 %d 行（%s）", total, codes)
        if ctx:
            ctx.log(f"子任务：指数行情采集完成，共写入/更新 {total} 行")
        return total

    def _ingest_indices_incremental(self, end: date, ctx=None) -> int:
        """逐指数补到目标日；首次加入配置的指数自动回填系统历史窗口。"""
        codes = configured_benchmark_codes()
        latest_df = self.repo.c.query_df(
            "SELECT index_code, max(trade_date) AS d FROM index_bar GROUP BY index_code"
        )
        latest = {
            str(row["index_code"]): pd.Timestamp(row["d"]).date()
            for _, row in latest_df.iterrows()
            if pd.notna(row["d"])
        }
        history_start = (
            pd.Timestamp(end) - pd.DateOffset(years=self.s.datasource.history_years)
        ).date()
        total = 0
        pending = 0
        for code in codes:
            last = latest.get(code)
            start = last + timedelta(days=1) if last else history_start
            if start > end:
                continue
            pending += 1
            total += self.ingest_indices(start, end, ctx=ctx, codes=[code])
        if pending == 0 and ctx:
            ctx.log(f"子任务：{len(codes)} 个指数行情均已是最新，本次跳过")
        return total

    # ── 股票列表 + 基础信息 ──
    def ingest_stock_basic(self, codes: list[str] | None = None, ctx=None) -> pd.DataFrame:
        """入库 stock_basic（板块由代码判定），返回纳入的 code 列表 DataFrame。"""
        if ctx:
            scope = f"指定 {len(codes)} 只" if codes else "全市场"
            ctx.log(f"子任务：股票基础信息采集开始（{scope}，源 {self.src.name}）")
            ctx.flush()
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
        if ctx:
            ctx.log(f"子任务：股票基础信息采集完成，目标板块 {len(basic)} 只，写入/更新 {n} 只")
        return basic

    def _stock_basic_from_db(self, codes: list[str] | None = None) -> pd.DataFrame:
        """续跑用：从库读 stock_basic（首跑已刷新名册），列同 backfill 所需，避免重复触网。"""
        df = self.repo.c.query_df(
            "SELECT code, name, price_limit_pct FROM stock_basic WHERE delist_date IS NULL")
        if codes:
            df = df[df["code"].isin(codes)]
        return df

    # ── 单只股票日线 + 衍生指标 ──
    def _st_status_by_name(self, code: str) -> PointInTimeSTStatus:
        """Resolve the current name fallback while preserving approximate provenance."""
        cache = getattr(self, "_st_name_cache", None)
        if cache is None:
            df = self.repo.c.query_df("SELECT code, name FROM stock_basic")
            cache = {
                r["code"]: self._st_status_from_name_value(r["name"])
                for _, r in df.iterrows()
            }
            self._st_name_cache = cache
        return cache.get(code, resolve_point_in_time_st(name=None))

    def _is_st_by_name(self, code: str) -> bool:
        """Compatibility wrapper for existing marker and factor-refresh callers."""
        return self._st_status_by_name(code).is_st

    @staticmethod
    def _st_status_from_name_value(value) -> PointInTimeSTStatus:
        name = None if value is None or pd.isna(value) else str(value)
        return resolve_point_in_time_st(name=name)

    def _fetch_daily_with_fallback(
        self, code: str, start: date, end: date, primary: DataSource, ctx=None,
    ) -> tuple[pd.DataFrame | None, str]:
        """主源取日线；**仅当主源返回空或报错**时用兜底源(baostock)整段重取（不混采，单只股票
        尽量单一来源，避免 ak/baostock 拼接致前复权因子跳变）。返回 (df, 实际来源名)。

        ctx（可选，仅串行路径传入）：把"主源失败/改用兜底源"写入任务实时日志，便于排查。
        """
        try:
            df = primary.get_daily_bar(code, start, end)
        except DataSourceError as e:
            log.warning("%s 主源(%s)取数失败，尝试兜底源: %s", code, primary.name, e)
            if ctx:
                ctx.log(f"{code} 主源({primary.name})取数失败，尝试兜底源：{e}", "warn")
            df = None
        if df is not None and not df.empty:
            return df, primary.name
        bao = self._bao_source()
        if not bao.supports("daily"):
            msg = f"{code} {start}~{end}：主源无数据，且未找到可用兜底源，本只写入 0 行"
            log.error(msg)
            if ctx:
                ctx.log(msg, "error")
                ctx.flush()
            raise DataSourceError(msg)
        with _BAO_FALLBACK_LOCK:   # baostock 会话型，进程内串行
            try:
                if ctx:
                    ctx.log(f"{code} 主源无数据，开始请求兜底源 {bao.name}（{start}~{end}）", "warn")
                    ctx.flush()
                bdf = bao.get_daily_bar(code, start, end)
            except DataSourceError as e:
                log.warning("%s 兜底源(%s)也失败: %s", code, bao.name, e)
                if ctx:
                    ctx.log(f"{code} 兜底源({bao.name})也失败：{e}", "error")
                    ctx.flush()
                raise DataSourceError(f"{code} {start}~{end} 主源+兜底源均取数失败: {e}") from e
        if bdf is not None and not bdf.empty:
            log.info("%s [%s~%s] 主源无数据，改用兜底源 %s（%d 行）", code, start, end, bao.name, len(bdf))
            if ctx:
                ctx.log(f"{code} {start}~{end}：主源无数据，改用兜底源 {bao.name}（{len(bdf)} 行）")
            return bdf, bao.name
        msg = f"{code} {start}~{end}：主源无数据，兜底源 {bao.name} 也无数据，本只写入 0 行"
        log.error(msg)
        if ctx:
            ctx.log(msg, "error")
            ctx.flush()
        raise DataSourceError(msg)

    def _record_provenance(self, code: str, table_name: str, start: date, end: date,
                           source: str, rows: int) -> None:
        """记录非默认源的取数事件（默认主源不记录），供审计/排查。只追加。"""
        if source == self.s.datasource.primary:
            return
        self.repo.c.execute(
            "INSERT INTO data_source_provenance "
            "(code, table_name, date_start, date_end, source, rows, fetched_at) VALUES (?,?,?,?,?,?,?)",
            [code, table_name, start, end, source, int(rows), datetime.now()])

    def ingest_one_daily(
        self, code: str, start: date, end: date,
        board_limit_pct: float | None = None, is_st: bool | None = None,
        source: DataSource | None = None, ctx=None,
        st_status: PointInTimeSTStatus | None = None,
    ) -> int:
        df, used_source = self._fetch_daily_with_fallback(code, start, end, source or self.src, ctx=ctx)
        # 并发终止可能发生在网络返回与入库之间；此检查保证任务进入 interrupted 后不再遗留写入。
        check_thread_cancel()
        if df is None or df.empty:
            raise DataSourceError(f"{code} {start}~{end} 主源+兜底源均无数据")
        source_dates = list(df["trade_date"])
        # 入库闸门：行级自清洗 + 校验（坏行入库前就处理，不再依赖事后手动修）
        df, sanitize_stats = sanitize_bars(df)
        # L1 质量问题：被丢弃的非法收盘价行入台账（M2.9 DM-D15，入库即暴露不静默）
        if sanitize_stats.get("dropped_dates"):
            self._record_issues(code, sanitize_stats["dropped_dates"], "null_close",
                                "收盘价为空或非正，已丢弃该行（原始数据缺损）")
        from backend.dataquality.ignore_rules import deactivate_occurrence_ignores
        dropped_dates = {
            pd.Timestamp(td).date() for td in (sanitize_stats.get("dropped_dates") or [])
        }
        deactivate_occurrence_ignores(
            self.c, "null_close", code,
            [td for td in source_dates if pd.Timestamp(td).date() not in dropped_dates],
        )
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
        if st_status is None:
            fallback = self._st_status_by_name(code)
            st_status = (
                fallback
                if is_st is None
                else PointInTimeSTStatus(
                    is_st=bool(is_st),
                    source=fallback.source,
                    source_ref=fallback.source_ref,
                    quality=STStatusQuality.APPROXIMATE,
                )
            )
        st_service = StockSTStatusService(self.c)
        incoming_st_facts = [
            StockSTStatusFact(
                code=code,
                trade_date=pd.Timestamp(trade_day).date(),
                status=st_status,
            )
            for trade_day in df["trade_date"].tolist()
        ]
        effective_st_facts = st_service.prefer_existing_accurate(incoming_st_facts)
        effective_st_by_date = {
            fact.trade_date: fact.status.is_st for fact in effective_st_facts
        }
        # 质检标记：涨跌停/一字板/ST（回测撮合前提）
        df = add_markers(df, board_limit_pct, st_status.is_st)
        # 名称推断只是兜底。若指定日期已有准确事实，行情行的 ST 派生标记也必须
        # 使用最终有效事实，不能只保护事实表而继续污染 daily_bar。
        df["is_st"] = [
            effective_st_by_date[pd.Timestamp(trade_day).date()]
            for trade_day in df["trade_date"].tolist()
        ]
        # OHL 修补行：真实振幅未知 → 强制不标一字板，并记入问题台账（不静默/不臆造）
        if "_ohl_repaired" in df.columns and df["_ohl_repaired"].any():
            repaired_dates = {
                pd.Timestamp(td).date()
                for td in df.loc[df["_ohl_repaired"], "trade_date"].tolist()
            }
            df.loc[df["_ohl_repaired"], "is_one_word"] = False
            self._record_issues(code, df[df["_ohl_repaired"]]["trade_date"], "ohl_repaired",
                                "开高低缺失，已用收盘价回填（不标一字板）")
            df = df.drop(columns=["_ohl_repaired"])
        else:
            repaired_dates = set()
        deactivate_occurrence_ignores(
            self.c, "ohl_repaired", code,
            [td for td in df["trade_date"].tolist()
             if pd.Timestamp(td).date() not in repaired_dates],
        )
        # 源行情覆盖后，派生清洗因子必须重新计算；否则源 adj_factor 被修正时，
        # 旧 adj_factor_clean 可能继续污染复权价。
        df["adj_factor_clean"] = None
        bar_cols = [
            "code", "trade_date", "open", "high", "low", "close",
            "pre_close", "volume", "amount", "adj_factor", "turnover_rate",
            "adj_factor_clean", "is_st", "is_suspended", "limit_status", "is_one_word",
        ]
        n = self.repo.upsert_daily_bar(df[bar_cols])
        st_service.upsert_facts(
            effective_st_facts,
            change_reason="daily_ingest",
            task_id=getattr(ctx, "tid", None),
        )
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
        # 非默认源（兜底）取的数据登记来源，供审计/排查（默认主源不记录）
        if n and used_source != self.s.datasource.primary:
            self._record_provenance(code, "daily_bar", start, end, used_source, n)
        return n

    # ── 估值/市值（总市值/总股本，补 G2）──
    def ingest_valuation(self, codes: list[str] | None = None, years: int | None = None,
                         concurrency: int | None = None, ctx=None) -> dict:
        """补每日市值字段到 daily_metrics，并把最新总/流通股本写入 stock_basic。

        数据源 stock_value_em（东财市值接口，可用）。按在市股逐只拉取。
        concurrency（与 update 同款）：>1 时线程池并发拉取，每线程独立 DataSource，
        写入由 DuckDB 单写锁串行。默认 1（串行）。⚠️ 并发即提高总请求速率，注意封禁风险。
        """
        years = years or self.s.datasource.history_years
        end = self._latest_open_day()   # 收敛到最近交易日，非交易日不当截止
        start = date(end.year - years, end.month, end.day)
        live = self.repo.c.query_df(
            "SELECT code FROM stock_basic WHERE delist_date IS NULL"
        )["code"].tolist()
        if codes:
            live = [c for c in live if c in codes]
        val_src = self._source_for("valuation")  # 校验能力可用（串行直接用，并发用线程局部源）
        # 断点续跑：跳过已同时具备 total_mv 与 float_mv 的票；只缺流通市值的旧数据也要补。
        done = set(self.repo.c.query_df(
            "SELECT code FROM daily_metrics GROUP BY code "
            "HAVING count(*) FILTER (WHERE total_mv IS NOT NULL) > 0 "
            "   AND count(*) FILTER (WHERE float_mv IS NOT NULL) > 0"
        )["code"].tolist())
        pending = [c for c in live if c not in done]
        skip = len(live) - len(pending)
        concurrency = concurrency if concurrency is not None else self.s.datasource.update_concurrency
        ok = fail = rows = 0
        n = len(pending)
        if ctx:
            ctx.set_phase("valuation_history", phase_total=n, phase_done=0, current_item=None)
            ctx.log(f"子任务：历史市值字段补采开始，目标 {len(live)} 只，跳过 {skip} 只，待补 {n} 只，"
                    f"区间 {start}~{end}（仅补整股从未有过 total_mv 的新票，历史缺口请走 `valuation --fill-gaps`）")
            ctx.flush()

        def _one(code: str, source) -> int:
            return self._valuation_one(code, source, start, end)

        def _tick(i: int) -> None:
            if ctx:
                ctx.set_phase("valuation_history", phase_total=n, phase_done=i)
            if i % 20 == 0 or i == n:
                log.info("估值进度 %d/%d（成功%d 失败%d 跳过%d，写入 %d行）",
                         i, n, ok, fail, skip, rows)
                if ctx:
                    ctx.log(f"历史市值字段补采进度 {i}/{n}：成功{ok} 失败{fail} 跳过{skip}，写入 {rows} 行")
                    ctx.flush()

        def _fail(code: str, e: Exception) -> None:
            log.warning("%s 估值入库失败: %s", code, e)
            if ctx:   # 与日行情家族对齐：单只失败写实时日志，便于页内排查（warn 级，不刷屏进度行）
                ctx.log(f"{code} 历史市值字段补采失败（{start}~{end}，源 {val_src.name}）：{e}", "warn")
            self.repo.log_update("daily_metrics", val_src.name, start, end, 0, "failed", f"{code}: {e}")

        if concurrency <= 1:  # 串行（默认，最稳）
            for i, code in enumerate(pending, 1):
                if ctx:
                    ctx.check_cancel()
                    ctx.set_phase("valuation_history", phase_total=n, phase_done=i - 1, current_item=code)
                try:
                    rows += _one(code, val_src)
                    ok += 1
                    _tick(i)
                except Exception as e:  # noqa: BLE001
                    fail += 1
                    _fail(code, e)
        else:  # 并发：线程局部 DataSource，写入由 DuckDB RLock 串行
            tls = threading.local()
            source_name = val_src.name

            def _worker(code: str) -> int:
                src = self._thread_source(tls, source_name)
                return _one(code, src)

            def _complete(i, code, value, error, _in_flight):
                nonlocal rows, ok, fail
                if ctx:
                    ctx.set_phase(
                        "valuation_history", phase_total=n, phase_done=i - 1,
                        current_item=code,
                    )
                if error is None:
                    rows += value
                    ok += 1
                    _tick(i)
                else:
                    fail += 1
                    _fail(code, error)

            self._run_bounded_parallel(
                pending, _worker, concurrency=concurrency, ctx=ctx,
                wait_label="历史市值字段补采", on_complete=_complete,
            )
        result = {"target": len(live), "ok": ok, "skip": skip, "fail": fail, "total_mv_rows": rows}
        log.info("估值入库完成: %s", result)
        if ctx:
            ctx.log(f"子任务：历史市值字段补采完成，成功{ok} 跳过{skip} 失败{fail}，写入 {rows} 行")
        return result

    def ingest_valuation_latest(self, trade_date: date | None = None,
                                codes: list[str] | None = None,
                                concurrency: int | None = None, ctx=None) -> dict:
        """补『最新交易日』的市值：对当日仍缺 total_mv/float_mv 的在市股，逐只取最新市值。

        治 P1：ingest_valuation 整股跳过已有 total_mv 的票 → 已采票的新交易日永远补不到。
        这里不靠它，直接对"当日有日线但市值字段不完整"的在市股逐只 _valuation_one(code, 当日, 当日)，
        用东财单只 stock_value_em 取真实总市值（准、稳，与 reconcile_gaps 收口同口径）。
        codes 给定时仅补这些票；concurrency 同 ingest_valuation（默认配置值，>1 并发提速）。
        """
        if trade_date is None:
            r = self.repo.c.query_df("SELECT max(trade_date) AS d FROM daily_bar")
            if r.empty or pd.isna(r.iloc[0]["d"]):
                return {"trade_date": None, "ok": 0, "fail": 0, "total_mv_rows": 0}
            trade_date = pd.Timestamp(r.iloc[0]["d"]).date()
        sql = (
            "SELECT b.code AS code FROM daily_bar b "
            "JOIN stock_basic sb ON sb.code = b.code "
            "LEFT JOIN daily_metrics m ON m.code = b.code AND m.trade_date = b.trade_date "
            "WHERE b.trade_date = ? AND sb.delist_date IS NULL "
            "AND (m.code IS NULL OR m.total_mv IS NULL OR m.float_mv IS NULL)"
        )
        params: list = [trade_date]
        if codes:
            sql += f" AND b.code IN ({','.join('?' * len(codes))})"
            params += list(codes)
        pending = self.repo.c.query_df(sql, params)["code"].tolist()
        concurrency = concurrency if concurrency is not None else self.s.datasource.update_concurrency
        ok = fail = rows = 0
        done_latest = set(ctx.checkpoint.get("valuation_latest_done_codes") or []) if (ctx and ctx.checkpoint) else set()
        pending = [c for c in pending if c not in done_latest]
        n = len(pending)
        log.info("补最新日市值：%s 有 %d 只在市股缺市值字段，逐只取最新市值", trade_date, n)
        if ctx:
            ctx.set_phase("valuation_latest", phase_total=n, phase_done=0, current_item=None,
                          valuation_latest_done_codes=sorted(done_latest))
            ctx.log(f"子任务：最新日市值补采开始，交易日 {trade_date}，待补 {n} 只")
            ctx.flush()

        def _one(code: str, source) -> int:
            return self._valuation_one(code, source, trade_date, trade_date)

        val_src = self._source_for("valuation")
        if concurrency <= 1:
            src = val_src
            for i, code in enumerate(pending, 1):
                if ctx:
                    ctx.check_cancel()
                    ctx.set_phase("valuation_latest", phase_total=n, phase_done=i - 1, current_item=code,
                                  valuation_latest_done_codes=sorted(done_latest))
                try:
                    rows += _one(code, src); ok += 1
                    done_latest.add(code)
                except Exception as e:  # noqa: BLE001
                    fail += 1; log.warning("%s 补最新日市值失败: %s", code, e)
                    if ctx:   # 与日行情家族对齐：单只失败写实时日志，便于页内排查
                        ctx.log(f"{code} 最新日市值补采失败（{trade_date}）：{e}", "warn")
                if i % 20 == 0 or i == n:
                    log.info("补最新日市值进度 %d/%d（成功%d 失败%d，写入 %d行）", i, n, ok, fail, rows)
                    if ctx:
                        ctx.set_phase("valuation_latest", phase_total=n, phase_done=i, current_item=code,
                                      valuation_latest_done_codes=sorted(done_latest))
                        ctx.log(f"最新日市值补采进度 {i}/{n}：成功{ok} 失败{fail}，写入 {rows} 行")
                        ctx.flush()
        else:
            tls = threading.local()
            source_name = val_src.name

            def _worker(code: str) -> int:
                src = self._thread_source(tls, source_name)
                return _one(code, src)

            def _complete(i, code, value, error, _in_flight):
                nonlocal rows, ok, fail
                if ctx:
                    ctx.set_phase(
                        "valuation_latest", phase_total=n, phase_done=i - 1,
                        current_item=code,
                        valuation_latest_done_codes=sorted(done_latest),
                    )
                if error is None:
                    rows += value
                    ok += 1
                    done_latest.add(code)
                else:
                    fail += 1
                    log.warning("%s 补最新日市值失败: %s", code, error)
                    if ctx:
                        ctx.log(f"{code} 最新日市值补采失败（{trade_date}）：{error}", "warn")
                if i % 20 == 0 or i == n:
                    log.info(
                        "补最新日市值进度 %d/%d（成功%d 失败%d，写入 %d行）",
                        i, n, ok, fail, rows,
                    )
                    if ctx:
                        ctx.set_phase(
                            "valuation_latest", phase_total=n, phase_done=i,
                            current_item=code,
                            valuation_latest_done_codes=sorted(done_latest),
                        )
                        ctx.log(
                            f"最新日市值补采进度 {i}/{n}：成功{ok} 失败{fail}，"
                            f"写入 {rows} 行"
                        )
                        ctx.flush()

            self._run_bounded_parallel(
                pending, _worker, concurrency=concurrency, ctx=ctx,
                wait_label="最新日市值补采", on_complete=_complete,
            )
        result = {"trade_date": str(trade_date), "ok": ok, "fail": fail, "total_mv_rows": rows}
        log.info("补最新日市值完成: %s", result)
        if ctx:
            ctx.log(f"子任务：最新日市值补采完成，成功{ok} 失败{fail}，写入 {rows} 行")
        return result

    def ingest_valuation_gaps(self, codes: list[str] | None = None,
                              concurrency: int | None = None, ctx=None) -> dict:
        """一次性历史回补（WS2）：补所有『有 daily_bar 但市值字段不完整』的在市股缺口。

        与 ingest_valuation 的整股断点续跑互补——逐(code,缺失区间)驱动 per-stock 回补。
        一次性低并发跑一轮即可清干净；之后由 ingest_valuation_latest 每日维持不再产生新缺口。
        """
        gap = self.repo.c.query_df(
            "SELECT b.code AS code, min(b.trade_date) AS lo, max(b.trade_date) AS hi, "
            "count(*) AS n FROM daily_bar b "
            "JOIN stock_basic sb ON sb.code = b.code "
            "LEFT JOIN daily_metrics m ON m.code = b.code AND m.trade_date = b.trade_date "
            "WHERE sb.delist_date IS NULL "
            "AND (m.code IS NULL OR m.total_mv IS NULL OR m.float_mv IS NULL) "
            "GROUP BY b.code")
        if codes:
            gap = gap[gap["code"].isin(set(codes))]
        pending = [(r["code"], pd.Timestamp(r["lo"]).date(), pd.Timestamp(r["hi"]).date())
                   for _, r in gap.iterrows()]
        concurrency = concurrency if concurrency is not None else self.s.datasource.update_concurrency
        ok = fail = rows = 0
        done_gap_codes = set(ctx.checkpoint.get("valuation_gap_done_codes") or []) if (ctx and ctx.checkpoint) else set()
        pending = [it for it in pending if it[0] not in done_gap_codes]
        n = len(pending)
        log.info("市值缺口回补开始：%d 只在市股有市值字段缺口", n)
        if ctx:
            ctx.set_phase("valuation_gap", phase_total=n, phase_done=0, current_item=None,
                          valuation_gap_done_codes=sorted(done_gap_codes))
            ctx.log(f"子任务：市值缺口回补开始，待补 {n} 只")
            ctx.flush()

        def _one(item, source) -> int:
            code, lo, hi = item
            return self._valuation_one(code, source, lo, hi)

        val_src = self._source_for("valuation")
        if concurrency <= 1:
            for i, item in enumerate(pending, 1):
                if ctx:
                    ctx.check_cancel()
                    ctx.set_phase("valuation_gap", phase_total=n, phase_done=i - 1, current_item=item[0],
                                  valuation_gap_done_codes=sorted(done_gap_codes))
                try:
                    rows += _one(item, val_src); ok += 1
                    done_gap_codes.add(item[0])
                except Exception as e:  # noqa: BLE001
                    fail += 1; log.warning("%s 市值回补失败: %s", item[0], e)
                    if ctx:   # 与日行情家族对齐：单只失败写实时日志，便于页内排查
                        ctx.log(f"{item[0]} 市值缺口回补失败（{item[1]}~{item[2]}）：{e}", "warn")
                if i % 20 == 0 or i == n:
                    log.info("市值回补进度 %d/%d（成功%d 失败%d，写入 %d行）", i, n, ok, fail, rows)
                    if ctx:
                        ctx.set_phase("valuation_gap", phase_total=n, phase_done=i, current_item=item[0],
                                      valuation_gap_done_codes=sorted(done_gap_codes))
                        ctx.log(f"市值缺口回补进度 {i}/{n}：成功{ok} 失败{fail}，写入 {rows} 行")
                        ctx.flush()
        else:
            tls = threading.local()
            source_name = val_src.name

            def _worker(item) -> int:
                src = self._thread_source(tls, source_name)
                return _one(item, src)

            def _complete(i, item, value, error, _in_flight):
                nonlocal rows, ok, fail
                code, lo, hi = item
                if ctx:
                    ctx.set_phase(
                        "valuation_gap", phase_total=n, phase_done=i - 1,
                        current_item=code,
                        valuation_gap_done_codes=sorted(done_gap_codes),
                    )
                if error is None:
                    rows += value
                    ok += 1
                    done_gap_codes.add(code)
                else:
                    fail += 1
                    log.warning("%s 市值回补失败: %s", code, error)
                    if ctx:
                        ctx.log(f"{code} 市值缺口回补失败（{lo}~{hi}）：{error}", "warn")
                if i % 20 == 0 or i == n:
                    log.info(
                        "市值回补进度 %d/%d（成功%d 失败%d，写入 %d行）",
                        i, n, ok, fail, rows,
                    )
                    if ctx:
                        ctx.set_phase(
                            "valuation_gap", phase_total=n, phase_done=i,
                            current_item=code,
                            valuation_gap_done_codes=sorted(done_gap_codes),
                        )
                        ctx.log(
                            f"市值缺口回补进度 {i}/{n}：成功{ok} 失败{fail}，"
                            f"写入 {rows} 行"
                        )
                        ctx.flush()

            self._run_bounded_parallel(
                pending, _worker, concurrency=concurrency, ctx=ctx,
                wait_label="市值缺口回补", on_complete=_complete,
            )
        result = {"target": n, "ok": ok, "fail": fail, "total_mv_rows": rows}
        log.info("市值缺口回补完成: %s", result)
        if ctx:
            ctx.log(f"子任务：市值缺口回补完成，成功{ok} 失败{fail}，写入 {rows} 行")
        return result

    def _record_issues(self, code: str, trade_dates, issue_type: str, detail: str) -> None:
        """把一批问题行记入 data_quality_issue（入库即暴露、不静默）。

        通用于 L1 入库闸门各类（null_close 丢弃 / ohl_repaired 修补），severity 由类型映射。
        同一 (code, date, type) 的 open/fixing 问题幂等复用：定时恢复遇到源端持续坏数据时，
        将原 fixing 问题退回 open，不每次再堆一条重复台账。
        """
        from datetime import datetime

        from backend.dataquality.checker import severity_for
        from backend.dataquality.ignore_rules import filter_ignored_issues

        sev = severity_for(issue_type)
        rows = []
        candidates = filter_ignored_issues(
            self.c,
            [{"code": code, "trade_date": td, "issue_type": issue_type, "detail": detail}
             for td in trade_dates],
            (issue_type,),
            reconcile_occurrences=False,
        )
        for candidate in candidates:
            td = candidate["trade_date"]
            now = datetime.now()
            existing = self.c.query_df(
                "SELECT id, status FROM data_quality_issue WHERE code=? AND trade_date=? AND issue_type=? "
                "AND status IN ('open','fixing') ORDER BY id LIMIT 1",
                [code, td, issue_type],
            )
            if not existing.empty:
                self.c.execute(
                    "UPDATE data_quality_issue SET severity=?, status='open', detail=?, detected_at=?, "
                    "fix_task_id=NULL WHERE id=?",
                    [sev, detail, now, int(existing.iloc[0]["id"])],
                )
                continue
            rows.append({
                "id": int(self.c.query_df("SELECT nextval('seq_quality_issue') AS v").iloc[0]["v"]),
                "code": code, "trade_date": td, "issue_type": issue_type,
                "severity": sev, "status": "open",
                "detail": detail, "detected_at": now,
            })
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
    def _history_start_covered_codes(self, start: date) -> set[str]:
        """返回历史行情已覆盖到目标起点的股票。

        只有任意一行行情不足以判定历史已补全；以回填起点或上市日为边界，
        并保留少量自然日缓冲吸收首个交易日差异。回填与退市股历史共用此口径。
        """
        min_df = self.repo.c.query_df(
            "SELECT code, min(trade_date) AS mn FROM daily_bar GROUP BY code")
        loaded_min = {
            r["code"]: pd.Timestamp(r["mn"]).date()
            for _, r in min_df.iterrows()
            if not pd.isna(r["mn"])
        }
        ld_df = self.repo.c.query_df("SELECT code, list_date FROM stock_basic")
        list_lut = {
            r["code"]: (
                pd.Timestamp(r["list_date"]).date() if not pd.isna(r["list_date"]) else None
            )
            for _, r in ld_df.iterrows()
        }
        buffer = timedelta(days=15)
        covered = set()
        for code, minimum in loaded_min.items():
            list_date = list_lut.get(code)
            threshold = list_date if (list_date and list_date > start) else start
            if minimum <= threshold + buffer:
                covered.add(code)
        return covered

    def backfill(self, codes: list[str] | None = None, years: int | None = None, ctx=None,
                 concurrency: int | None = None) -> dict:
        """全量回填近 N 年。codes=None 表示全市场；可断点续跑（跳过已入库）。

        ctx（M2.8-B，可选）：逐股写实时日志 + 进度 + checkpoint。续跑天然幂等（跳过已入库）。
        concurrency（与 update 同款）：>1 时线程池并发拉取，每线程独立 DataSource
        （限流按线程隔离，总速率≈N×单线程），写入由 DuckDB 单写锁串行。默认 1（串行）。
        ⚠️ 调高并发即调高总请求速率，注意免费源封禁风险。
        """
        years = years or self.s.datasource.history_years
        end = self._latest_open_day()   # 收敛到最近交易日，非交易日不当截止
        start = date(end.year - years, end.month, end.day)
        log.info("开始回填 %s ~ %s", start, end)

        # 续跑跳过前置（与 update 一致）：日历/指数/基础信息首跑已幂等入库，prep_done 标记后续跑跳过；
        # 基础信息改从库读（首跑已刷新名册），避免重复触网与刷屏。
        if ctx and ctx.checkpoint.get("prep_done"):
            ctx.log("续跑：跳过日历/指数/基础信息前置（已于首跑完成），从断点继续补数")
            basic = self._stock_basic_from_db(codes)
        else:
            self.ingest_calendar(start, end, ctx=ctx)
            self.ingest_indices(start, end, ctx=ctx)
            basic = self.ingest_stock_basic(codes, ctx=ctx) if ctx else self.ingest_stock_basic(codes)
            if ctx:
                ctx.set_checkpoint(prep_done=True)
        target_codes = basic["code"].tolist()
        # 板块涨跌幅 + ST 状态查找表（ST 由名称含 "ST" 判定）
        limit_lut = dict(zip(basic["code"], basic["price_limit_pct"]))
        st_lut = {
            r["code"]: self._st_status_from_name_value(r["name"]).is_st
            for _, r in basic.iterrows()
        }

        # 断点续跑 + 部分覆盖修复：旧逻辑"有任意数据就跳过"会把仅有部分近期数据的股票
        # （如经缺口兜底补了近窗口、或上次中断）误判为已完成，早期历史永远补不上。改为按
        # "最早入库日是否已覆盖到回填起点(或上市日)"判断：mn <= max(start, 上市日)+缓冲 才算已覆盖、跳过。
        covered_codes = self._history_start_covered_codes(start)
        pending = [c for c in target_codes if c not in covered_codes]
        skip = len(target_codes) - len(pending)
        concurrency = concurrency if concurrency is not None else self.s.datasource.update_concurrency
        ok = fail = total_rows = 0
        updated: set[str] = set()  # 实际有新行的股票 → 收尾刷新干净因子
        n = len(pending)
        if ctx:
            ctx.set_phase("daily_bar", phase_total=n, phase_done=0, current_item=None)
            ctx.log(f"▶ 开始历史补数：共 {len(target_codes)} 只（已入库跳过 {skip}，待补 {n}），"
                    f"区间 {start}~{end}（并发 {concurrency}）")

        def _one(code: str, source: DataSource | None = None, ctx_=None) -> int:
            return self.ingest_one_daily(code, start, end, limit_lut.get(code), st_lut.get(code),
                                         source=source, ctx=ctx_)

        def _tick(i: int, code: str, rows: int) -> None:
            if ctx:
                ctx.set_checkpoint(phase="daily_bar", done=i, skipped=skip, total=n,
                                   phase_total=n, phase_done=i, current_item=code)
            if i % 20 == 0 or i == n:
                log.info("回填进度 %d/%d（成功%d 失败%d 跳过%d，累计%d行，最近 %s +%d）",
                         i, n, ok, fail, skip, total_rows, code, rows)
            if ctx and (i % 20 == 0 or i == n):
                ctx.progress(min(0.1 + 0.78 * i / max(n, 1), 0.88),
                             f"回填 {i}/{n}（成功{ok} 跳过{skip} 失败{fail}，累计{total_rows}行）")
                ctx.log(f"[{i}/{n}] 进度：成功{ok} 跳过{skip} 失败{fail}，累计 +{total_rows} 行（最近 {code} +{rows}）")

        def _fail(i: int, code: str, e: Exception) -> None:
            log.warning("%s 回填失败: %s", code, e)
            if ctx:
                ctx.log(f"[{i}/{n}] {code} 回填失败（{start}~{end}，主源+兜底源均未取到）: {e}", "error")
            self.repo.log_update("daily_bar", self.src.name, start, end, 0, "failed", f"{code}: {e}")

        if concurrency <= 1:  # 串行（默认，最稳）
            for i, code in enumerate(pending, 1):
                if ctx:
                    ctx.check_cancel()
                    ctx.set_phase("daily_bar", phase_total=n, phase_done=i - 1, current_item=code)
                    if i == 1 or i % 20 == 1:
                        ctx.log(f"[{i}/{n}] 开始历史补数 {code}（串行，当前请求返回后进入下一检查点）")
                        ctx.flush()
                try:
                    rows = _one(code, ctx_=ctx)
                    total_rows += rows
                    if rows:
                        updated.add(code)
                    ok += 1
                    _tick(i, code, rows)
                except Exception as e:  # noqa: BLE001
                    fail += 1
                    _fail(i, code, e)
        else:  # 并发：线程局部 DataSource（限流按线程隔离），写入由 DuckDB RLock 串行
            tls = threading.local()
            source_name = self.src.name

            def _worker(code: str) -> int:
                src = self._thread_source(tls, source_name)
                return _one(code, source=src)

            def _complete(i, code, value, error, _in_flight):
                nonlocal total_rows, ok, fail
                if ctx:
                    ctx.set_phase(
                        "daily_bar", phase_total=n, phase_done=i - 1,
                        current_item=code,
                    )
                if error is None:
                    total_rows += value
                    if value:
                        updated.add(code)
                    ok += 1
                    _tick(i, code, value)
                else:
                    fail += 1
                    _fail(i, code, error)

            self._run_bounded_parallel(
                pending, _worker, concurrency=concurrency, ctx=ctx,
                wait_label="历史补数", on_complete=_complete,
            )
        if updated:
            if ctx:
                ctx.log(f"↻ 重算干净复权因子（{len(updated)} 只新入库）…")
            self._refresh_clean_factors(sorted(updated), ctx=ctx)
        result = {"target": len(target_codes), "ok": ok, "skip": skip, "fail": fail, "rows": total_rows}
        # 市值透明化：历史补数只采行情，total_mv 历史市值不在本任务内采（市值源是慢接口，单列）。
        # 明确告知缺口去向，避免“市值盲区”不透明——增量更新只保最新交易日，历史全段缺口须靠
        # ingest_valuation_gaps/`valuation --fill-gaps`（或质量页补修）一次性回补，增量不自动补历史。
        try:
            valued = set(self.repo.c.query_df(
                "SELECT DISTINCT code FROM daily_metrics WHERE total_mv IS NOT NULL")["code"].tolist())
            mv_missing = [c for c in target_codes if c not in valued]
            result["mv_missing"] = len(mv_missing)
            if ctx:
                if mv_missing:
                    ctx.log(f"说明：历史补数只采行情；其中 {len(mv_missing)} 只尚无任何 total_mv，"
                            "历史市值请运行 `valuation --fill-gaps` 一次性回补（增量更新只保最新交易日，不补历史缺口）")
                else:
                    ctx.log("说明：历史补数只采行情；目标股票均已具备 total_mv（历史缺口如需回补请运行 "
                            "`valuation --fill-gaps`）")
        except Exception as e:  # noqa: BLE001  统计失败不影响回填结果
            log.warning("回填后市值缺口统计失败（不影响结果）: %s", e)
        if ctx:
            ctx.log(f"■ 历史补数完成：成功 {ok}、跳过 {skip}、失败 {fail}，共写入 {total_rows} 行")
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
            v.check_calendar_readiness()
            fails = v.fails()
            if fails:
                log.warning("⚠️ 入库后校验发现 %d 项不达标: %s（详情跑 verify-data）", len(fails), fails)
            else:
                log.info("✅ 入库后校验通过（结构+字段契约）")
        except Exception as e:  # noqa: BLE001
            log.warning("入库后自动校验异常: %s", e)

    # ── 增量更新 ──
    def _update_one(self, code: str, end: date, source: DataSource | None = None, ctx=None) -> int:
        """更新单只股票（增量）。供串行/并发共用。返回写入行数。

        ctx 仅串行路径传入（并发下从工作线程写实时日志不安全），用于把兜底源等细节写进任务日志。
        """
        last = self.repo.get_max_bar_date(code)
        start = (last + timedelta(days=1)) if last else date(
            end.year - self.s.datasource.history_years, end.month, end.day)
        if start > end:
            return 0
        return self.ingest_one_daily(code, start, end, source=source, ctx=ctx)

    def _previous_open_day(self, day: date) -> date:
        df = self.repo.c.query_df(
            "SELECT max(trade_date) AS d FROM trade_calendar WHERE is_open AND trade_date < ?",
            [day],
        )
        if not df.empty and pd.notna(df.iloc[0]["d"]):
            return pd.Timestamp(df.iloc[0]["d"]).date()
        return day - timedelta(days=1)

    def _latest_open_day(self, ref: date | None = None) -> date:
        """≤ ref（默认今天）的最近交易日：ref 本身是交易日则为 ref，否则回退到上一交易日。

        各类"补到最新"的采集（行情/市值/退市/补数）统一用它当截止日，避免把非交易日（周末/节假日）
        当成数据截止，导致日志区间出现"今天=非交易日"这种语义错乱。日历缺该日时回退到 _previous_open_day。
        """
        ref = ref or date.today()
        cal = self.repo.c.query_df(
            "SELECT is_open FROM trade_calendar WHERE trade_date = ?", [ref])
        if not cal.empty and bool(cal.iloc[0]["is_open"]):
            return ref
        return self._previous_open_day(ref)

    def _resolve_update_end(
        self,
        requested_end: date,
        basic: list[str],
        codes: list[str] | None,
        ctx=None,
        *,
        force_current_day: bool = False,
    ) -> date:
        """收敛增量更新的目标截止日：

        ① 非交易日（requested_end 无开市行且日历已覆盖到该日）→ **回退到最新交易日**为截止，
           不跳过任务（周末/节假日跑也能确保补齐到上一交易日；已最新则逐股短路，无网络开销）。
        ② 全市场 + 今天确是交易日 → 抽样探测主源当日日线是否就绪；未就绪 →
           回退到上一交易日继续增量。本轮不拉取当日半成品，下轮仍会重新目标当天。
        ③ 全市场与指定股票都执行同一退级规则；只有 force_current_day 才跳过退级。
        """
        if force_current_day:
            if ctx:
                ctx.log(f"已强制采集当日 {requested_end}，跳过交易日和数据就绪检查", "warn")
            return requested_end

        cal = self.repo.c.query_df(
            "SELECT is_open FROM trade_calendar WHERE trade_date = ?",
            [requested_end],
        )
        # 交易日历只存开市日 → requested_end 无开市行即非交易日。仅当日历确已覆盖到该日
        # （update() 在本方法前已 ingest_calendar 补到年底）才据"缺行"判闭市，避免把"还没采到"误判成闭市。
        is_open = (not cal.empty) and bool(cal.iloc[0]["is_open"])
        target = requested_end
        if not is_open:
            mx = self.repo.c.query_df("SELECT max(trade_date) AS m FROM trade_calendar").iloc[0]["m"]
            covered = mx is not None and pd.notna(mx) and pd.Timestamp(mx).date() >= requested_end
            if covered:
                target = self._previous_open_day(requested_end)
                if ctx:
                    ctx.log(f"今日 {requested_end} 非交易日，回退到最新交易日 {target} 截止")
            # 日历未覆盖到该日（异常）→ 不武断判闭市，沿用 requested_end 继续

        if not basic:
            return target

        # 只有"今天确是交易日"才做主源当日就绪探测；非交易日已回退，无需探测。
        if target != requested_end:
            return target

        basic_set = set(basic)
        sample = [c for c in _UPDATE_READY_SAMPLE if c in basic_set]
        if not sample and basic:
            step = max(len(basic) // 10, 1)
            sample = basic[::step][:10]

        ready = empty = errors = 0
        for code in sample:
            try:
                df = self.src.get_daily_bar(code, requested_end, requested_end)
                if df is not None and not df.empty:
                    ready += 1
                else:
                    empty += 1
            except Exception as e:  # noqa: BLE001
                errors += 1
                log.warning("%s 当日就绪度探测失败: %s", code, e)

        total = max(len(sample), 1)
        ratio = ready / total
        if ratio < _UPDATE_READY_RATIO:
            fallback = self._previous_open_day(requested_end)
            msg = (f"今日 {requested_end} 主源日线未完全就绪：抽样 {ready}/{len(sample)} 有数据"
                   f"（空 {empty}，异常 {errors}），回退到上一交易日 {fallback} "
                   "继续增量，本轮不逐只拉取当日半成品")
            log.warning(msg)
            if ctx:
                ctx.log(msg, "warn")
            return fallback
        return requested_end

    def update(
        self,
        codes: list[str] | None = None,
        concurrency: int | None = None,
        force_current_day: bool = False,
        ctx=None,
    ) -> dict:
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
            self.repo.c.query_df(
                "SELECT code FROM stock_basic WHERE delist_date IS NULL ORDER BY code")["code"].tolist()
        )
        if codes:
            basic = [c for c in basic if c in codes]
        # 续跑（FR-DM-10）：串行老任务按 done 兼容跳过；并发任务按 done_codes 精确跳过。
        n_total = len(basic)
        checkpoint = ctx.checkpoint if (ctx and ctx.checkpoint) else {}
        has_exact_done_codes = "done_codes" in checkpoint
        done_codes = set(checkpoint.get("done_codes") or [])
        # 新版 checkpoint 即使成功集合为空也会显式写 done_codes=[]，不得回退
        # 到旧版位置 done；只有真正没有该字段的历史 checkpoint 才按前 N 只兼容。
        skip_done = 0 if has_exact_done_codes else int(checkpoint.get("done", 0))
        completed_codes = set(done_codes) | set(basic[:skip_done])
        resumed_count = len(completed_codes)
        pending = [c for c in basic if c not in completed_codes]
        # 续跑锁定本次任务目标日：首跑就绪门收敛后固化 target_end，续跑直接取回，避免被重算成
        # 「今天」后又重新触发就绪判定，保证中断前后处理同一截止日。target_end 仅在首跑成功
        # 解析后写入，故"存在即代表前置(日历/指数)已完成"，续跑据此一并跳过这两个幂等前置。
        pinned_end = None
        if ctx and ctx.checkpoint.get("target_end"):
            try:
                pinned_end = date.fromisoformat(ctx.checkpoint["target_end"])
            except (ValueError, TypeError):
                pinned_end = None
        if pinned_end is not None:
            end = pinned_end
            if ctx:
                ctx.log(f"续跑：沿用本次任务目标日 {end}，跳过日历/指数前置（已于首跑完成且幂等入库）")
        else:
            self.ingest_calendar(end - timedelta(days=30), end, ctx=ctx)  # 先补日历（判交易日要用）
            end = self._resolve_update_end(
                end, basic, codes, ctx=ctx, force_current_day=force_current_day,
            )
        if pinned_end is None:
            # 指数行情与日行情同口径：从 index_bar 已入库最新日 +1 增量补到 end（已收敛到最新交易日），
            # 不再每次固定拉「今天-30」窗口；已最新则跳过，不会"凭空一直更新"。
            self._ingest_indices_incremental(end, ctx=ctx)
        if ctx:
            # 固化目标日：此后若被终止，续跑沿用该日，不被重算成「今天」（见上方 pinned_end）。
            ctx.set_checkpoint(target_end=end.isoformat())
        ok = fail = total_rows = 0
        updated: set[str] = set()  # 实际有新行的股票 → 收尾增量刷新干净因子
        n = len(pending)
        if ctx:
            resumed_done = len(completed_codes)
            tail = f"（续跑跳过已完成 {resumed_done}）" if resumed_done else ""
            ctx.set_phase("daily_bar", done=len(completed_codes), total=n_total,
                          phase_total=n_total, phase_done=len(completed_codes), current_item=None,
                          done_codes=sorted(completed_codes))
            ctx.log(f"▶ 开始增量更新：共 {n_total} 只在市股票，待补 {n} 只{tail}，"
                    f"各股从已入库最新日+1 补到 {end}（并发 {concurrency}）")

        def _checkpoint(processed_count: int) -> None:
            if not ctx:
                return
            data = {
                "phase": "daily_bar",
                "done": len(completed_codes),
                "total": n_total,
                "phase_total": n_total,
                "phase_done": processed_count,
                "done_codes": sorted(completed_codes),
            }
            ctx.set_checkpoint(**data)

        def _tick(a: int, code: str, rows: int, *, in_flight: int = 0) -> None:
            if ctx:
                ctx.set_phase("daily_bar", done=len(completed_codes), total=n_total, phase_total=n_total,
                              phase_done=a, current_item=code, done_codes=sorted(completed_codes))
            if a % 20 == 0 or a == n_total:
                log.info("增量进度 %d/%d（成功%d 失败%d，累计%d行，最近 %s +%d）",
                         a, n_total, ok, fail, total_rows, code, rows)
            if ctx and (a % 20 == 0 or a == n_total):
                prefix = "并发增量" if concurrency > 1 else "增量更新"
                in_flight_note = f"，在途{in_flight}" if concurrency > 1 else ""
                ctx.log(f"[{a}/{n_total}] {prefix}进度：成功{ok} 失败{fail}{in_flight_note}，"
                        f"累计 +{total_rows} 行（最近完成 {code} +{rows}）")
                ctx.progress(min(0.1 + 0.78 * a / max(n_total, 1), 0.88),
                             f"{prefix} {a}/{n_total}（成功{ok} 失败{fail}{in_flight_note}，累计{total_rows}行）")

        if concurrency <= 1:  # 串行（默认，最稳）
            for idx, code in enumerate(pending, 1):
                a = resumed_count + idx
                if ctx:
                    ctx.check_cancel()   # 协作式终止：每只之间检查
                    ctx.set_phase("daily_bar", phase_total=n_total, phase_done=a - 1, current_item=code,
                                  done=len(completed_codes), total=n_total, done_codes=sorted(completed_codes))
                    if a == 1 or a % 20 == 1:
                        ctx.log(f"[{a}/{n_total}] 开始增量更新 {code}（串行，当前请求返回后才会进入下一检查点）")
                        ctx.flush()
                try:
                    rows = self._update_one(code, end, ctx=ctx)
                    total_rows += rows
                    if rows:
                        updated.add(code)
                    ok += 1
                    completed_codes.add(code)
                    _tick(a, code, rows)
                except Exception as e:  # noqa: BLE001
                    fail += 1
                    log.warning("%s 增量失败: %s", code, e)
                    _checkpoint(a)
                    if ctx:
                        ctx.log(f"[{a}/{n_total}] {code} 增量更新失败（补到 {end}，主源+兜底源均未取到）: {e}", "error")
                    self.repo.log_update("daily_bar", self.src.name, None, end, 0, "failed", f"{code}: {e}")
        else:  # 并发：线程局部 DataSource（限流按线程隔离），写入由 DuckDB RLock 串行
            tls = threading.local()
            source_name = self.src.name

            def _worker(code: str) -> int:
                src = self._thread_source(tls, source_name)
                return self._update_one(code, end, source=src)

            def _complete(i, code, value, error, in_flight):
                nonlocal total_rows, ok, fail
                a = resumed_count + i
                if error is None:
                    total_rows += value
                    if value:
                        updated.add(code)
                    ok += 1
                    completed_codes.add(code)
                    _tick(a, code, value, in_flight=in_flight)
                else:
                    fail += 1
                    log.warning("%s 增量失败: %s", code, error)
                    if ctx:
                        ctx.log(
                            f"[{a}/{n_total}] {code} 增量更新失败（补到 {end}，"
                            f"主源+兜底源均未取到）: {error}",
                            "error",
                        )
                    self.repo.log_update(
                        "daily_bar", self.src.name, None, end, 0, "failed",
                        f"{code}: {error}",
                    )
                    if a % 20 == 0 or a == n_total:
                        _checkpoint(a)

            self._run_bounded_parallel(
                pending, _worker, concurrency=concurrency, ctx=ctx,
                wait_label="并发增量", on_complete=_complete,
            )

        # ── 缺口收口（DM 口径统一：与质量修复-补采共用 reconcile_gaps，confirm=False 只补不确认）──
        # 常规增量只补 max+1~target_end；若主源返回部分数据则兜底不触发、最新缺口会漏（如停牌次日/源端
        # 当日缺数）。此处用批量缺口口径（同 _coverage_frame，含减确认停牌）找出有缺口/滞后的股，
        # 窄区间重采让兜底正确触发把能补的补回。放在刷因子前，使补回行一并刷净。
        # 注意：自动收口只补回、不自动确认停牌——真停牌交由质检+补采那条有把关的路径确认，避免把
        # "可能只是源端当日未发布"的最新缺口在全市场范围误标成不可逆停牌。
        recon = {"stocks": 0, "backfilled": 0}
        try:
            from backend.services.data_report import DataIntegrityReport
            gapped = DataIntegrityReport(self.repo.c).gapped_codes()
            if codes:
                gapped = [c for c in gapped if c in codes]
            if gapped and ctx:
                ctx.log(f"↻ 缺口收口：{len(gapped)} 只存在缺口/滞后，窄区间重采补回（兜底正确触发；不自动确认停牌）…")
            gtotal = len(gapped)
            for gi, gcode in enumerate(gapped, 1):
                if ctx:
                    ctx.check_cancel()
                    if gi == 1 or gi % 20 == 1:
                        ctx.log(f"缺口收口进度 {gi}/{gtotal}：开始处理 {gcode}")
                        ctx.flush()
                try:
                    # 就绪探测已回退时，库内可能有少数股票曾局部写入当天数据。
                    # 自动收口必须与本轮 target_end 一致，不得再绕过回退去请求当天。
                    r = self.reconcile_gaps(gcode, confirm=False, through=end)
                    if r["rows"]:
                        total_rows += r["rows"]
                        updated.add(gcode)
                    if r["backfilled"]:
                        recon["stocks"] += 1
                        recon["backfilled"] += len(r["backfilled"])
                except Exception as e:  # noqa: BLE001  单只收口失败不影响其余
                    log.warning("%s 缺口收口失败: %s", gcode, e)
                    if ctx:
                        ctx.log(f"缺口收口 {gcode} 失败：{e}", "warn")
                if ctx and (gi % 20 == 0 or gi == gtotal):
                    ctx.log(f"缺口收口进度 {gi}/{gtotal}：已补回 {recon['stocks']} 只 / {recon['backfilled']} 天")
                    ctx.flush()
            if gapped and ctx:
                ctx.log(f"■ 缺口收口完成：{recon['stocks']} 只补回，共补回 {recon['backfilled']} 天"
                        f"（真停牌待质检+补采确认）")
        except TaskCancelled:  # 终止信号必须穿透容错兜底，转为可续跑中断而非吞掉跑完
            raise
        except Exception as e:  # noqa: BLE001  收口阶段异常不影响增量主结果
            log.warning("缺口收口阶段异常（不影响增量结果）: %s", e)

        if updated:
            if ctx:
                ctx.log(f"↻ 增量刷新干净复权因子（{len(updated)} 只有新行）…")
            self._refresh_clean_factors(sorted(updated), ctx=ctx)
        result = {"target": n, "ok": ok, "fail": fail, "rows": total_rows, "concurrency": concurrency,
                  "reconcile": recon}
        # 补市值并入更新行情（容错子阶段）：更新即产出 L2 完整数据（float_mv 由日线自带 + total_mv）。
        # 幂等只补缺失股；失败仅记日志、不让整次更新失败（市值源是慢接口，单独容错隔离）。
        # 注意 total_mv 的增量语义：这里只保「最新交易日」新鲜，历史中间缺口不归 update 管
        # （日线每行写 float_mv、total_mv=None；历史 total_mv 由 ingest_valuation_gaps/--fill-gaps 清）。
        try:
            if ctx:
                ctx.log("↻ 补市值估值（total_mv）：只补最新交易日，历史缺口走 `valuation --fill-gaps`…")
            # 治 P1（已采票新天补不到）：逐只取最新交易日的 total_mv（单只 stock_value_em）。
            # 失败独立隔离，不连累后面的历史补采。
            latest_val: dict = {}
            try:
                # 与本轮已收敛的目标日保持一致：若库内少数股票曾局部写入当天数据，
                # 不得让市值补采又以全库 max(trade_date) 绕过本轮回退。
                latest_val = self.ingest_valuation_latest(
                    trade_date=end, codes=codes, concurrency=concurrency, ctx=ctx
                ) if ctx else self.ingest_valuation_latest(
                    trade_date=end, codes=codes, concurrency=concurrency
                )
            except TaskCancelled:  # 终止穿透：勿与"市值源失败"混为一谈
                raise
            except Exception as se:  # noqa: BLE001
                log.warning("补最新日市值失败（不连累历史补采）: %s", se)
                if ctx:
                    ctx.log(f"补最新日市值失败（不连累历史补采）：{se}", "warn")
            # 再跑历史补采：仅对从未采过估值的票（新上市/新入库）补全历史。
            full_val = (self.ingest_valuation(codes=codes, concurrency=concurrency, ctx=ctx)
                        if ctx else self.ingest_valuation(codes=codes, concurrency=concurrency))
            result["valuation"] = {**full_val, "latest": latest_val}
            if ctx:
                ctx.log(f"■ 补市值完成：最新交易日 {latest_val.get('total_mv_rows', 0)} 行"
                        f" + 新票历史补采 {full_val.get('total_mv_rows', 0)} 行"
                        f"（历史中间缺口请跑 `valuation --fill-gaps` 一次性回补）")
        except TaskCancelled:  # 终止穿透：补市值阶段被终止应转可续跑中断，而非记为失败后跑完
            raise
        except Exception as e:  # noqa: BLE001  市值源异常不影响行情更新结果
            log.warning("补市值估值失败（不影响行情更新）: %s", e)
            result["valuation_error"] = str(e)
            if ctx:
                ctx.log(f"补市值估值失败（不影响行情更新）：{e}", "warn")
        if ctx:
            ctx.log(f"■ 增量更新完成：成功 {ok}、失败 {fail}，共写入 {total_rows} 行（{n} 只）")
            ctx.log("说明：本次已补最新交易日 total_mv；历史中间缺口未在本次覆盖，质检 `mv_gap` 仍显示属正常，"
                    "需跑 `valuation --fill-gaps`（或质量页补修）一次性回补历史市值。")
        if codes is None:
            result["market_day_terminal"] = self._log_market_day_terminal(
                end,
                expected=n_total,
                successful=len(completed_codes),
                failed=fail,
                run_id=str(getattr(ctx, "tid", None) or f"manual-update-{end.isoformat()}"),
            )
        log.info("增量更新完成: %s", result)
        return result

    @staticmethod
    def reconcile_note(r: dict) -> str:
        """收口结果统一文案：只报有意义的部分（避免"补回1天、确认停牌0天"两个数一个为0的误导）。"""
        bf, cf = len(r.get("backfilled", [])), int(r.get("confirmed", 0))
        if bf and cf:
            return f"补回 {bf} 天，确认停牌 {cf} 天"
        if bf:
            return f"补回 {bf} 天"
        if cf:
            return f"确认停牌 {cf} 天"
        return "源端仍无数据，保持待处理"

    def reconcile_gaps(self, code: str, ctx=None, confirm: bool = True,
                       through: date | None = None) -> dict:
        """收口单只股票窗口内的覆盖缺口（增量更新与质量修复-补采共用，统一口径）。

        步骤：窗口内仍缺的开市日 → 窄区间重采（区间收窄到缺口，主源整段无数据时兜底才会触发，
        治"多日区间主源返回部分数据→兜底不触发"的盲区）→（confirm 时）仍无数据者确认为停牌
        （写 stock_suspension 收敛）。返回 {miss, backfilled, confirmed, rows}。

        confirm：是否把"重采后仍无数据"确认为停牌。
          - 质量修复-补采（有人按质检台账把关）传 True：保留"反向确认停牌"收敛语义。
          - 增量更新自动收尾传 False：只补回，不自动确认——避免把"可能只是源端当日未发布"的最新
            缺口在全市场范围内误标成不可逆的停牌；真停牌交由质检+补采这条把关路径确认。
        through：可选的截止日；增量自动收口传入本轮 target_end，防止源端未就绪回退后
          又被库内局部的当天数据抬高缺口窗口。人工质量修复不传，仍处理全部真实缺口。
        """
        from backend.services.data_report import DataIntegrityReport
        rep = DataIntegrityReport()   # 默认 get_client() 单例，与 self.repo.c 同一连接
        miss = rep.missing_days_for(code)
        if through is not None:
            miss = [d for d in miss if d <= through]
        if not miss:
            return {"miss": [], "backfilled": [], "confirmed": 0, "rows": 0}
        lo, hi = min(miss), max(miss)
        if ctx:
            ctx.log(f"缺口收口：重采 {code} {lo}~{hi}（{len(miss)} 个待补开市日）")
        try:
            rows = self.ingest_one_daily(code, lo, hi, ctx=ctx)
        except DataSourceError as e:
            if not confirm:
                raise
            rows = 0
            if ctx:
                ctx.log(f"缺口收口：{code} {lo}~{hi} 源端仍无行情数据，进入停牌确认判断：{e}", "warn")
        still = rep.missing_days_for(code)   # 仍缺的开市日（已随新 min_bar 收窄 lo，排除上市前的伪缺口）
        if through is not None:
            still = [d for d in still if d <= through]
        confirmed = rep.confirm_suspension(code, still) if (confirm and still) else 0
        if ctx and confirmed:
            ctx.log(f"缺口收口：{code} 已确认停牌 {confirmed} 天")
        # 补回数 = miss 中重采后"确实已有行情"的日期（按 daily_bar 实判）。不能用 miss−still：次新股
        # 首次入库会令窗口起点 lo 随新 min_bar 前移，把上市前的"伪缺口"误算成补回（虚报如 90 实补 5）。
        have_after = {pd.Timestamp(d).date() for d in rep.c.query_df(
            "SELECT trade_date FROM daily_bar WHERE code=? AND trade_date BETWEEN ? AND ?",
            [code, lo, hi])["trade_date"]}
        backfilled = [d for d in miss if d in have_after]
        # 收口补市值（DM 口径统一）：补回了行情的天 total_mv 仍空，而 mv_missing 是整股粒度测不出、
        # ingest_valuation 又整股跳过已有 total_mv 的票 → 这些天会永久缺市值。故对实际补回的股顺带补
        # 一次估值（仅这只股 + 补回区间），一步到位。失败不影响补回主结果。
        if backfilled:
            try:
                self._valuation_one(code, self._source_for("valuation"),
                                    min(backfilled), max(backfilled))
            except Exception as e:  # noqa: BLE001
                log.warning("%s 收口补市值失败(不影响补回): %s", code, e)
        return {"miss": miss, "backfilled": backfilled, "confirmed": confirmed, "rows": rows}

    def _valuation_one(self, code: str, source, start: date, end: date) -> int:
        """取单只 [start,end] 估值，幂等合并入 daily_metrics（只补 total_mv；float_mv 仅空缺才回填，
        不覆盖日线更准值）+ 最新总/流通股本入 stock_basic。返回 total_mv 写入行数。
        供 ingest_valuation 全量补市值与 reconcile_gaps 收口补市值共用，口径一致。"""
        v = source.get_valuation(code, start, end)
        # 与行情入库保持同一安全边界：取消后不把刚返回的外部结果继续写入 DuckDB。
        check_thread_cancel()
        if v is None or v.empty:
            return 0
        # 只保留 daily_bar 已有的交易日，杜绝 value_em 日期错位产生游离 metrics 行
        bar_dates = {
            pd.Timestamp(d).date()
            for d in self.repo.c.query_df(
                "SELECT trade_date FROM daily_bar WHERE code = ?", [code]
            )["trade_date"]
        }
        v = v[v["trade_date"].isin(bar_dates)]
        if v.empty:
            return 0
        # 每日总市值入 daily_metrics（只更新 total_mv 列，不动 float_mv）
        added = self.repo.upsert_daily_metrics(v[["code", "trade_date", "total_mv"]])
        # 补流通市值：仅 float_mv 为空的行用估值源「流通市值」回填——保证 baostock 兜底票
        # （日线无 float_share、无 float_mv）也满足 L2 契约；新浪日线已写的更准 float_mv 不覆盖。
        fv = v[["code", "trade_date", "float_mv"]].dropna(subset=["float_mv"])
        if not fv.empty:
            with self.repo.c.temp_view(fv, prefix="fv_metrics") as t:
                self.repo.c.execute(
                    f"UPDATE daily_metrics m SET float_mv = src.float_mv FROM {t} src "
                    f"WHERE m.code = src.code AND m.trade_date = src.trade_date AND m.float_mv IS NULL")
        # 最新总/流通股本入 stock_basic
        last = v.dropna(subset=["total_share"]).tail(1)
        if not last.empty:
            self.repo.upsert_stock_basic(pd.DataFrame([{
                "code": code,
                "total_share": int(last["total_share"].iloc[0]),
                "float_share": int(last["float_share"].iloc[0]) if pd.notna(last["float_share"].iloc[0]) else None,
            }]))
        return added

    # ── 指定日期采集（FR-DM-3 更多选项，M2.8-B）──
    def ingest_date(self, start: date, end: date, codes: list[str] | None = None, ctx=None,
                    concurrency: int | None = None) -> dict:
        """补指定日期（或区间）的行情。codes=None 表示全部在市股票。

        逐股拉取 [start, end] 区间并入库（沿用 ingest_one_daily 的清洗/标记/幂等 upsert）。
        返回受影响交易日列表供调用方标记评分快照失效。

        concurrency（与 update 同款）：>1 时用线程池并发拉取，每线程独立 DataSource
        （限流按线程隔离，总请求速率≈N×rate_limit_per_sec），写入经 DuckDB 单写锁串行。
        默认 1（串行，最稳）。⚠️ 调高并发即调高总请求速率，注意免费源封禁风险。
        """
        live = self.repo.c.query_df(
            "SELECT code, name, price_limit_pct FROM stock_basic WHERE delist_date IS NULL")
        if codes:
            live = live[live["code"].isin(codes)]
        # 确保区间内日历+指数存在（与 update/backfill 一致：补缺口时该区间指数也一并补，避免回测基准留缺口）。
        # 续跑跳过前置：prep_done 标记后续跑不再重采日历/指数（首跑已幂等入库）。
        if ctx and ctx.checkpoint.get("prep_done"):
            ctx.log("续跑：跳过日历/指数前置（已于首跑完成），从断点继续采集")
        else:
            self.ingest_calendar(start, end, ctx=ctx)
            self.ingest_indices(start, end, ctx=ctx)
            if ctx:
                ctx.set_checkpoint(prep_done=True)
        limit_lut = dict(zip(live["code"], live["price_limit_pct"]))
        st_lut = {
            r["code"]: self._st_status_from_name_value(r["name"]).is_st
            for _, r in live.iterrows()
        }
        target = live["code"].tolist()
        done_codes = set(ctx.checkpoint.get("done_codes") or []) if (ctx and ctx.checkpoint) else set()
        target = [c for c in target if c not in done_codes]
        full_total = len(done_codes) + len(target)
        n = len(target)
        concurrency = concurrency if concurrency is not None else self.s.datasource.update_concurrency
        ok = fail = total_rows = 0
        updated: set[str] = set()  # 实际有新行的股票 → 收尾增量刷新干净因子
        if ctx:
            ctx.set_phase("daily_bar", done=len(done_codes), total=full_total,
                          phase_total=full_total, phase_done=len(done_codes),
                          current_item=None, done_codes=sorted(done_codes))
            ctx.log(f"▶ 开始指定日期采集：{n} 只股票，区间 {start}~{end}（并发 {concurrency}）")

        def _one(code: str, source: DataSource | None = None, ctx_=None) -> int:
            return self.ingest_one_daily(
                code, start, end, limit_lut.get(code), st_lut.get(code), source=source, ctx=ctx_)

        def _tick(i: int, code: str, rows: int) -> None:
            if ctx:
                ctx.set_phase("daily_bar", done=len(done_codes), total=full_total,
                              phase_total=full_total, phase_done=len(done_codes),
                              current_item=code, done_codes=sorted(done_codes))
            if i % 20 == 0 or i == n:
                log.info("指定采集进度 %d/%d（成功%d 失败%d，累计%d行，最近 %s +%d）",
                         i, n, ok, fail, total_rows, code, rows)
            if ctx and (i % 20 == 0 or i == n):
                ctx.progress(min(0.1 + 0.78 * i / max(n, 1), 0.88), f"采集 {i}/{n}（累计{total_rows}行）")
                ctx.log(f"[{i}/{n}] 进度：成功{ok} 失败{fail}，累计 +{total_rows} 行（最近 {code} +{rows}）")

        def _fail(i: int, code: str, e: Exception) -> None:
            log.warning("%s 指定采集失败: %s", code, e)
            if ctx:
                ctx.log(f"[{i}/{n}] {code} 采集失败（{start}~{end}，主源+兜底源均未取到）: {e}", "error")
            self.repo.log_update("daily_bar", self.src.name, start, end, 0, "failed", f"{code}: {e}")

        if concurrency <= 1:  # 串行（默认，最稳）
            for i, code in enumerate(target, 1):
                if ctx:
                    ctx.check_cancel()
                    ctx.set_phase("daily_bar", done=len(done_codes), total=full_total,
                                  phase_total=full_total, phase_done=len(done_codes),
                                  current_item=code, done_codes=sorted(done_codes))
                    if i == 1 or i % 20 == 1:
                        ctx.log(f"[{i}/{n}] 开始指定日期采集 {code}（串行，当前请求返回后进入下一检查点）")
                        ctx.flush()
                try:
                    rows = _one(code, ctx_=ctx)
                    total_rows += rows
                    if rows:
                        updated.add(code)
                    ok += 1
                    done_codes.add(code)
                    _tick(i, code, rows)
                except Exception as e:  # noqa: BLE001
                    fail += 1
                    _fail(i, code, e)
        else:  # 并发：线程局部 DataSource（限流按线程隔离），写入由 DuckDB RLock 串行
            tls = threading.local()
            source_name = self.src.name

            def _worker(code: str) -> int:
                src = self._thread_source(tls, source_name)
                return _one(code, source=src)

            def _complete(i, code, value, error, _in_flight):
                nonlocal total_rows, ok, fail
                if ctx:
                    ctx.set_phase(
                        "daily_bar", done=len(done_codes), total=full_total,
                        phase_total=full_total, phase_done=len(done_codes),
                        current_item=code, done_codes=sorted(done_codes),
                    )
                if error is None:
                    total_rows += value
                    if value:
                        updated.add(code)
                    ok += 1
                    done_codes.add(code)
                    _tick(i, code, value)
                else:
                    fail += 1
                    _fail(i, code, error)

            self._run_bounded_parallel(
                target, _worker, concurrency=concurrency, ctx=ctx,
                wait_label="指定日期采集", on_complete=_complete,
            )
        if updated:
            if ctx:
                ctx.log(f"↻ 增量刷新干净复权因子（{len(updated)} 只有新行）…")
            self._refresh_clean_factors(sorted(updated), ctx=ctx)
        # 受影响交易日 = 区间内开市日
        days = self.repo.c.query_df(
            "SELECT trade_date FROM trade_calendar WHERE is_open AND trade_date BETWEEN ? AND ?",
            [start, end])["trade_date"].tolist()
        dates = [str(pd.Timestamp(d).date()) for d in days]
        result = {"target": n, "ok": ok, "fail": fail, "rows": total_rows,
                  "range": [str(start), str(end)], "dates": dates}
        if ctx:
            ctx.log(f"■ 指定日期采集完成：成功 {ok}、失败 {fail}，共写入 {total_rows} 行（{start}~{end}）")
        log.info("指定日期采集完成: %s", {k: v for k, v in result.items() if k != "dates"})
        return result

    def rebuild_price_factors(self, codes: list[str] | None = None, ctx=None) -> dict:
        """全序列重算 adj_factor_clean / pre_close / 涨跌停标记（不联网）。

        源 adj_factor = 后复权收盘 ÷ 不复权收盘，两端皆四舍五入到分，相除后非除权日
        也带逐日舍入噪声；dejitter_adj_factor 把它整理成分段恒定的「干净因子」，写入
        adj_factor_clean。K 线前/后复权（repository.get_bars）改用此列，消除 qfq 的
        逐日漂移；pre_close / 涨跌停同源于该干净因子，口径一致。**不覆盖源 adj_factor**
        （留作审计/后复权绝对价）。历史一次性清洗、或去抖/标记逻辑变更后全量重刷，走此
        入口（CLI rebuild-price-factors / API 手动）。日常增量由入库收尾的
        _refresh_clean_factors 锚定增量维护，无需手动。
        """
        target = codes or self.repo.c.query_df(
            "SELECT DISTINCT code FROM daily_bar ORDER BY code"
        )["code"].tolist()
        return self._recompute_clean(target, ctx=ctx, full=True, verb="重算价格因子")

    def _refresh_clean_factors(self, codes: list[str], ctx=None) -> dict:
        """入库收尾：增量刷新本次更新过股票的 adj_factor_clean / pre_close / 标记。

        锚定库中该股「最后一行已有干净因子」，只对其后新增的行做去抖：非除权日沿用上一日
        干净因子、除权日重构——全程不联网、只算新行，故日常零额外网络负载且全局一致
        （单只按全序列锚定，绕开跨窗口拼接再生噪声的坑）。某股从未算过干净因子（旧库迁移后）
        则首次自动退化为全序列重算。"""
        if not codes:
            return {"target": 0, "ok": 0, "fail": 0, "rows": 0}
        return self._recompute_clean(list(codes), ctx=ctx, full=False, verb="刷新价格因子")

    def _recompute_clean(self, target: list[str], ctx=None, full: bool = True,
                         verb: str = "重算价格因子") -> dict:
        basic = self.repo.c.query_df("SELECT code, name, price_limit_pct FROM stock_basic")
        limit_lut = dict(zip(basic["code"], basic["price_limit_pct"]))
        st_lut = {
            r["code"]: self._st_status_from_name_value(r["name"]).is_st
            for _, r in basic.iterrows()
        }
        done_codes = set(ctx.checkpoint.get("factor_done_codes") or []) if (ctx and ctx.checkpoint) else set()
        target = [c for c in target if c not in done_codes]
        ok = fail = rows = 0
        n = len(target)
        if ctx:
            ctx.set_phase("price_factor", done=len(done_codes), total=len(done_codes) + n,
                          phase_total=len(done_codes) + n, phase_done=len(done_codes),
                          current_item=None, factor_done_codes=sorted(done_codes))
            ctx.log(f"▶ 开始{verb}：{n} 只股票")
        for i, code in enumerate(target, 1):
            if ctx:
                ctx.check_cancel()
                ctx.set_phase("price_factor", done=len(done_codes), total=len(done_codes) + n,
                              phase_total=len(done_codes) + n, phase_done=len(done_codes),
                              current_item=code, factor_done_codes=sorted(done_codes))
            try:
                rows += self._recompute_clean_one(
                    code, float(limit_lut.get(code) or 0.10), bool(st_lut.get(code)), full=full)
                ok += 1
                done_codes.add(code)
                if ctx:
                    ctx.set_phase("price_factor", done=len(done_codes), total=len(done_codes) + n,
                                  phase_total=len(done_codes) + n, phase_done=len(done_codes),
                                  current_item=code, factor_done_codes=sorted(done_codes))
                if ctx and (i % 50 == 0 or i == n):
                    ctx.progress(min(0.1 + 0.8 * i / max(n, 1), 0.9),
                                 f"{verb} {i}/{n}（累计 {rows} 行）")
                    ctx.log(f"[{i}/{n}] {code}，累计 {rows} 行")
            except Exception as e:  # noqa: BLE001
                fail += 1
                done_codes.add(code)
                log.warning("%s %s失败: %s", code, verb, e)
                if ctx:
                    ctx.set_phase("price_factor", done=len(done_codes), total=len(done_codes) + n,
                                  phase_total=len(done_codes) + n, phase_done=len(done_codes),
                                  current_item=code, factor_done_codes=sorted(done_codes))
                    ctx.log(f"[{i}/{n}] {code} {verb}失败: {e}", "warn")
        result = {"target": n, "ok": ok, "fail": fail, "rows": rows}
        log.info("%s完成: %s", verb, result)
        if ctx:
            ctx.log(f"■ {verb}完成：成功 {ok}、失败 {fail}，共处理 {rows} 行")
        return result

    def _recompute_clean_one(self, code: str, board_limit_pct: float, is_st: bool,
                             full: bool = True) -> int:
        """单只去抖重算：写 adj_factor_clean/pre_close/标记。full=False 时只算锚点之后的新行。"""
        from backend.datasource.akshare_source import compute_pre_close, dejitter_adj_factor

        anchor_date = None
        if not full:
            a = self.repo.c.query_df(
                """
                WITH first_dirty AS (
                    SELECT min(trade_date) AS d
                    FROM daily_bar
                    WHERE code=? AND adj_factor_clean IS NULL
                )
                SELECT
                    CASE
                        WHEN (SELECT d FROM first_dirty) IS NOT NULL THEN (
                            SELECT max(trade_date)
                            FROM daily_bar
                            WHERE code=? AND adj_factor_clean IS NOT NULL
                              AND trade_date < (SELECT d FROM first_dirty)
                        )
                        ELSE (
                            SELECT max(trade_date)
                            FROM daily_bar
                            WHERE code=? AND adj_factor_clean IS NOT NULL
                        )
                    END AS d
                """,
                [code, code, code],
            ).iloc[0]["d"]
            anchor_date = None if pd.isna(a) else pd.Timestamp(a).date()

        if anchor_date is None:  # 全量 / 旧库首次：读全序列
            df = self.repo.c.query_df(
                "SELECT code, trade_date, open, high, low, close, "
                "       adj_factor, adj_factor_clean FROM daily_bar "
                "WHERE code=? ORDER BY trade_date", [code])
        else:  # 增量：读锚点当日起（含锚点做 shift / 去抖上下文）
            df = self.repo.c.query_df(
                "SELECT code, trade_date, open, high, low, close, "
                "       adj_factor, adj_factor_clean FROM daily_bar "
                "WHERE code=? AND trade_date>=? ORDER BY trade_date", [code, anchor_date])
            if len(df) <= 1:  # 只剩锚点本身，无新行
                return 0
        if df.empty:
            return 0

        clean = dejitter_adj_factor(df["adj_factor"], df["close"])
        if anchor_date is not None:
            # 去抖只保「段内结构」，绝对基准随窗口起点而变；重缩放使锚点干净因子与库中已存值
            # 连续，新行才能和历史无缝衔接（qfq 看比值，缩放因子在相除时抵消，不改 qfq/pre_close）。
            stored = float(df["adj_factor_clean"].iloc[0])
            head = float(clean.iloc[0])
            if stored > 0 and head > 0:
                clean = clean * (stored / head)
        df = df.copy()
        df["adj_factor_clean"] = clean.to_numpy()
        df["pre_close"] = compute_pre_close(df["close"], clean)
        marked = add_markers(df, board_limit_pct, is_st)
        if anchor_date is not None:  # 只写锚点之后的新行
            marked = marked[marked["trade_date"] > pd.Timestamp(anchor_date)]
        if marked.empty:
            return 0
        cols = ["code", "trade_date", "adj_factor_clean", "pre_close",
                "is_st", "is_suspended", "limit_status", "is_one_word"]
        with self.c.temp_view(marked[cols], prefix="clean_rebuild") as v:
            self.c.execute(
                "UPDATE daily_bar AS b SET "
                "adj_factor_clean = v.adj_factor_clean, pre_close = v.pre_close, "
                "is_st = v.is_st, is_suspended = v.is_suspended, "
                "limit_status = v.limit_status, is_one_word = v.is_one_word "
                f"FROM {v} AS v "
                "WHERE b.code = v.code AND b.trade_date = v.trade_date"
            )
        return len(marked)

    # ══════════════════════════════════════════════════════════
    # baostock 补充（T-M1-4）：上市/退市日 + 退市股历史（防幸存者偏差）
    # ══════════════════════════════════════════════════════════

    def enrich_basic_dates(self, ctx=None) -> int:
        """补全 stock_basic 的上市/退市日 + 行业（含新增退市股），按能力选源。"""
        dates_src = self._source_for("basic_dates")
        if ctx:
            ctx.check_cancel()
            ctx.set_phase(
                "stock_basic", done=0, total=1,
                phase_done=0, phase_total=1, current_item="全市场基础资料",
            )
            ctx.log(f"子任务：上市/退市日采集开始，源 {dates_src.name}")
            ctx.flush()
        df = dates_src.get_basic_dates()  # code,name,list_date,delist_date,is_delisted
        # 行业映射（证监会行业）
        try:
            if ctx:
                ctx.check_cancel()
                ctx.log("子任务：行业信息采集开始")
                ctx.flush()
            ind = self._source_for("industry").get_industry()
            ind_map = dict(zip(ind["code"], ind["industry"]))
            if ctx:
                ctx.log(f"子任务：行业信息采集完成，获得 {len(ind_map)} 条行业映射")
        except Exception as e:  # noqa: BLE001
            log.warning("行业获取失败，industry 置空: %s", e)
            if ctx:
                ctx.log(f"行业获取失败，industry 置空：{e}", "warn")
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
        if ctx:
            ctx.check_cancel()
        n = self.repo.upsert_stock_basic(out)
        self.repo.log_update("stock_basic", dates_src.name, None, None, n, "success", "补上市/退市日+行业")
        log.info("%s 补全基础信息 %d 只（含退市股+行业）", dates_src.name, n)
        if ctx:
            ctx.set_phase(
                "stock_basic", done=1, total=1,
                phase_done=1, phase_total=1, current_item="全市场基础资料",
            )
            ctx.log(f"子任务：上市/退市日与行业入库完成，写入/更新 {n} 只")
        return n

    def ingest_delisted(self, years: int | None = None, limit: int | None = None, ctx=None) -> dict:
        """灌入"近 N 年内退市"的退市股历史日线（防幸存者偏差核心）。

        只取退市日落在回测窗口内的票（更早退市的在 5 年窗口内无数据，跳过）。
        """
        years = years or self.s.datasource.history_years
        end = self._latest_open_day()   # 收敛到最近交易日，非交易日不当截止
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
        if ctx:
            ctx.set_phase("delisted_history", phase_total=len(dl), phase_done=0, current_item=None)
            ctx.log(f"子任务：退市股历史灌入开始，待处理 {len(dl)} 只，区间 {start}~{end}")
            ctx.flush()

        covered_codes = self._history_start_covered_codes(start)
        ok, skip, fail, total_rows = 0, 0, 0, 0
        total = len(dl)
        for i, (_, r) in enumerate(dl.iterrows(), 1):
            code = r["code"]
            if ctx:
                ctx.check_cancel()
                ctx.set_phase("delisted_history", phase_total=total, phase_done=i - 1,
                              current_item=code)
            if code in covered_codes:
                skip += 1
                if ctx and (i % 20 == 0 or i == total):
                    ctx.log(f"退市股灌入进度 {i}/{total}：成功{ok} 跳过{skip} 失败{fail}，累计 {total_rows} 行")
                    ctx.flush()
                continue
            try:
                code6 = code.split(".")[0]
                _, _, limit_pct = self._in_target_board(code6)
                is_st = self._st_status_from_name_value(r["name"]).is_st
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
                if ctx and (i == 1 or i % 20 == 0 or i == total):
                    ctx.set_phase("delisted_history", phase_total=total, phase_done=i,
                                  current_item=code)
                    ctx.log(f"退市股 {code} 完成：写入 {rows} 行；进度 {i}/{total}，成功{ok} 跳过{skip} 失败{fail}")
                    ctx.flush()
            except Exception as e:  # noqa: BLE001
                fail += 1
                log.warning("退市股 %s 灌入失败: %s", code, e)
                if ctx:
                    ctx.log(f"退市股 {code} 灌入失败：{e}", "warn")
                self.repo.log_update("daily_bar", bao.name, start, None, 0, "failed", f"{code}: {e}")
        result = {"target": len(dl), "ok": ok, "skip": skip, "fail": fail, "rows": total_rows}
        log.info("退市股灌入完成: %s", result)
        if ctx:
            ctx.log(f"子任务：退市股历史灌入完成，成功{ok} 跳过{skip} 失败{fail}，写入 {total_rows} 行")
        return result

    # ── 板块概念采集（字典 / 完整成分快照 / 指数 / 资金流）─────────────────
    def ingest_board(self, ctx=None, board_type: str | None = None,
                     board_codes: list[str] | None = None, mode: str = "update",
                     only: list[str] | None = None, limit: int | None = None,
                     force_members: bool | None = None,
                     force_current_day: bool = False) -> dict:
        """板块数据编排：字典 → 成分快照 → 指数 → 资金流。

        承接 plan §6.4 T4：单步骤失败记日志不中断（返回失败清单），供 T5/T6 失败隔离与续跑。
        - mode="backfill"（初始化）：指数全量回填（源端可用起始年 2024 起）+ 资金流全周期；
          成分快照默认绕过周频全量拉（force_members 默认 True）。
        - mode="update"（每日增量）：指数只补最近交易日 + 资金流每日刷新全周期（即时/3日/5日/10日/20日）；
          成分股按周频跳过逻辑拉完整快照（只进不出关系幂等合并），force_members=True 时绕过间隔。
          force_current_day=True 时跳过非交易日与源端就绪退级，直接尝试当天。
        - only：可选子集（"dict"/"members"/"bar"/"fund"），CLI --dict 等分表运行用。
        board_type 可限制 concept/industry；ctx 提供任务中心进度日志。
        """
        from datetime import date as _d
        from datetime import timedelta as _td

        from backend.services.board_ingest import (
            BOARD_INGEST_STAGES,
            BoardIngestService,
            _asia_date,
            normalize_board_stages,
        )

        if mode not in ("backfill", "update"):
            raise ValueError("板块采集模式仅支持 backfill/update")
        if board_type not in (None, "concept", "industry"):
            raise ValueError("板块类型仅支持 concept/industry")
        if limit is not None and limit <= 0:
            raise ValueError("板块采集 limit 必须大于 0")
        if not isinstance(force_current_day, bool):
            raise ValueError("板块强制采集当日必须是布尔值")
        if mode != "update" and force_current_day:
            raise ValueError("只有板块增量采集支持强制采集当日")
        # force_members 未显式指定时：backfill 初始化、或显式指定板块子集（手动重采语义）→ 绕过周频；
        # 默认全量 update 走周频跳过（避免每日增量全量重拉已完整板块）。
        if force_members is None:
            force_members = mode == "backfill" or bool(board_codes)
        svc = BoardIngestService()
        result: dict = {
            "dict": None, "members": {}, "bar": None, "fund_flow": None,
            "failed": [], "ok": True,
        }
        # 分表选择与任务 API/调度共用同一白名单和空值语义。
        normalized_steps = normalize_board_stages(only)
        steps = list(BOARD_INGEST_STAGES if normalized_steps is None else normalized_steps)
        uses_market_date = any(step in steps for step in ("bar", "fund"))
        update_target = (
            _asia_date() if force_current_day else self._latest_open_day()
        ) if mode == "update" and uses_market_date else None
        if force_current_day and uses_market_date and ctx:
            ctx.log(f"已强制采集当日 {update_target}，跳过交易日和数据就绪检查", "warn")
        # 阶段日志对齐现有采集（阶段 i/N + 进度推进，前端任务中心实时可见）
        total = len(steps)
        idx = {"n": 0}
        if ctx:
            ctx.log(f"板块采集开始（{mode}）：{steps}")
            ctx.progress(0.05, f"板块采集（{mode}）…")
            ctx.flush()
        if "dict" in steps:
            idx["n"] += 1
            try:
                result["dict"] = svc.ingest_board_dict(board_type=board_type, ctx=ctx)
                result["failed"] += [f"dict:{x}" for x in result["dict"].get("failed", [])]
                if ctx:
                    ctx.log(f"步骤 {idx['n']}/{total} 板块字典：概念 {result['dict'].get('concept', 0)} / "
                            f"行业 {result['dict'].get('industry', 0)}")
            except TaskCancelled:  # 终止穿透：板块采集被终止应转可续跑中断，而非记为失败后跑完
                raise
            except Exception as e:  # noqa: BLE001
                log.warning("板块字典采集失败: %s", e)
                result["failed"].append(f"dict: {e}")
        if limit is not None and not board_codes:
            limited = svc.c.query_df(
                "SELECT board_code FROM board_dict "
                "WHERE (has_members OR has_bar) "
                + ("AND board_type=? " if board_type else "")
                + "ORDER BY board_type, board_code LIMIT ?",
                [board_type, limit] if board_type else [limit])
            board_codes = [str(x) for x in limited["board_code"].tolist()]
            result["scope_codes"] = board_codes
            if not board_codes:
                result["failed"].append("scope:no_boards")
        if "members" in steps:
            idx["n"] += 1
            if ctx:
                ctx.progress(round(0.05 + 0.25 * idx["n"] / total, 3), "板块成分快照…")
                ctx.flush()
            try:
                result["members"] = svc.ingest_board_members(
                    board_codes=board_codes, board_type=board_type, ctx=ctx,
                    force=force_members)
                errs = [f"members:{c}: {r['error']}" for c, r in result["members"].items()
                        if "error" in r]
                skipped = sum(1 for r in result["members"].values() if r.get("skipped"))
                result["failed"] += errs
                if ctx:
                    ctx.log(f"步骤 {idx['n']}/{total} 成分快照：处理 {len(result['members']) - skipped} 个板块"
                            f"（跳过 {skipped}，失败 {len(errs)}）")
            except TaskCancelled:  # 终止穿透：成分快照阶段被终止应转可续跑中断
                raise
            except Exception as e:  # noqa: BLE001
                log.warning("板块成分快照采集失败: %s", e)
                result["failed"].append(f"members: {e}")
        if "bar" in steps:
            idx["n"] += 1
            if ctx:
                ctx.progress(round(0.05 + 0.25 * idx["n"] / total, 3), "板块指数…")
                ctx.flush()
            try:
                if mode == "backfill":
                    # 全量回填：源端可用起始年到今天（实测 `d.` 域仅近 3 年、2021-2023 404，故 2024 起）
                    result["bar"] = svc.ingest_board_bar(
                        _d(2024, 1, 1), board_codes=board_codes,
                        board_type=board_type, ctx=ctx)
                else:
                    # 增量：复用现有采集交易日语义——截止到最近交易日（非交易日回退），
                    # 区间起点往前取 7 个自然日缓冲覆盖跨周末/长假缺口；
                    # 增量默认开启源端当日就绪探测；强制当日时才跳过。
                    assert update_target is not None
                    end = update_target
                    result["bar"] = svc.ingest_board_bar(end - _td(days=7), end=end,
                                                         board_codes=board_codes,
                                                         board_type=board_type,
                                                         probe_ready=not force_current_day,
                                                         ctx=ctx)
                    update_target = _d.fromisoformat(result["bar"]["end"])
                if ctx:
                    bar = result["bar"]
                    rng = f"区间 {bar.get('start')} ~ {bar.get('end')}"
                    fallback_note = (
                        f"，源端未就绪，已从 {bar.get('requested_end')} 回退"
                        if bar.get("fallback") else ""
                    )
                    ctx.log(f"步骤 {idx['n']}/{total} 板块指数（{rng}{fallback_note}）："
                            f"{bar.get('rows', 0)} 行 / {bar.get('boards', 0)} 板块"
                            f"（已出截止日 {bar.get('at_end', 0)}/{bar.get('scope_total', 0)}）")
                result["failed"] += [f"bar:{x}" for x in result["bar"].get("failed", [])]
            except TaskCancelled:  # 终止穿透：板块指数阶段被终止应转可续跑中断
                raise
            except Exception as e:  # noqa: BLE001
                log.warning("板块指数采集失败: %s", e)
                result["failed"].append(f"bar: {e}")
        if "fund" in steps:
            idx["n"] += 1
            if ctx:
                ctx.progress(round(0.05 + 0.25 * idx["n"] / total, 3), "板块资金流…")
                ctx.flush()
            try:
                if mode == "backfill":
                    result["fund_flow"] = svc.ingest_board_fund_flow(
                        board_codes=board_codes, board_type=board_type, ctx=ctx)
                else:
                    # 增量资金流每日刷新全周期（即时/3日/5日/10日/20日）：
                    # 滚动周期值每个交易日都会更新，只采即时会让多周期数据停在 backfill 当天。
                    result["fund_flow"] = svc.ingest_board_fund_flow(
                        snapshot_date=update_target,
                        board_codes=board_codes, board_type=board_type, ctx=ctx)
                if ctx:
                    ctx.log(f"步骤 {idx['n']}/{total} 板块资金流：{result['fund_flow'].get('rows', 0)} 行"
                            f"（未匹配 {result['fund_flow'].get('unmatched', 0)}）")
                result["failed"] += [f"fund_flow:{x}"
                                     for x in result["fund_flow"].get("failed", [])]
            except TaskCancelled:  # 终止穿透：板块资金流阶段被终止应转可续跑中断
                raise
            except Exception as e:  # noqa: BLE001
                log.warning("板块资金流采集失败: %s", e)
                result["failed"].append(f"fund_flow: {e}")
        if board_codes and any(x in steps for x in ("members", "bar", "fund")):
            type_clause = " AND board_type=?" if board_type else ""
            known = svc.c.query_df(
                f"SELECT board_code FROM board_dict WHERE board_code IN "
                f"({','.join('?' for _ in board_codes)}){type_clause}",
                [*board_codes, board_type] if board_type else board_codes)
            known_codes = {str(x) for x in known["board_code"].tolist()}
            result["failed"] += [f"unknown_board:{code}" for code in board_codes
                                 if code not in known_codes]
        result["failed"] = list(dict.fromkeys(result["failed"]))
        result["ok"] = not result["failed"]
        if ctx:
            ctx.progress(1.0, "板块采集完成")
            ctx.log(f"板块采集完成（{mode}）：字典{result['dict']} 成分{len(result['members'])} 板块 "
                    f"指数{result['bar']} 资金流{result['fund_flow']} 失败{result['failed']}")
            ctx.flush()
        return result
