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
from bisect import bisect_left
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import pandas as pd

from backend.common.exceptions import DataSourceError
from backend.common.logging import get_logger
from backend.common.timeutil import years_before
from backend.config import get_effective_settings
from backend.dataquality.checker import (
    MV_REL_TOLERANCE,
    add_markers,
    mv_inverted_sql,
    sanitize_bars,
)
from backend.datasource.akshare_source import classify_board
from backend.datasource.base import (
    DataSource,
    check_thread_cancel,
    get_source,
    thread_cancel_scope,
)
from backend.datasource.request_runtime import session_lock
from backend.limit_ladder.rules import (
    PointInTimeSTStatus,
    STStatusQuality,
)
from backend.services import eod_dates
from backend.services.async_task import TaskCancelled
from backend.services.collection_quality import checked_collection, include_collection_scope
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


@dataclass
class _DailySTMaterial:
    """主线程读取的已有事实与工作线程取得的原始状态，不在工作线程访问数据库。"""

    stored: pd.DataFrame
    fetched: tuple[DataSource, pd.DataFrame] | None = None
    error: Exception | None = None


@dataclass
class _PreparedDaily:
    """已按单股规则校验的材料；批次原子落库前不登记完成。"""

    code: str
    start: date
    end: date
    frame: pd.DataFrame
    bar_columns: list[str]
    st_facts: list[StockSTStatusFact]
    references: pd.DataFrame
    source: str


class IngestionService:
    def __init__(self, source: DataSource | None = None):
        # 生效配置 = YAML ⊕ 前端 app_config 覆盖（限流/并发/超时改前端即生效）。
        self.s = get_effective_settings()
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
    def _run_bounded_parallel(*args, **kwargs):
        """兼容已有调用；执行机制由采集共享队列维护。"""
        from backend.services.bounded_parallel import run_bounded_parallel
        return run_bounded_parallel(*args, **kwargs)

    @staticmethod
    def _fetch_capital_material(code, source, start, end):
        """历史路径先并发取逐日估值；后续事件补充和所有持久化在编排线程处理。"""
        frame = source.get_valuation(code, start, end)
        return frame, getattr(source, "_last_valuation_prices", None)

    def _complete_capital_material(self, entries, source, one):
        """将已取结果交回原合并链，不重发已完成／预算耗尽的估值请求。"""
        class PreparedSource:
            def __init__(self, material, error):
                object.__setattr__(self, "_source", source)
                object.__setattr__(self, "_material", material)
                object.__setattr__(self, "_error", error)

            def __getattr__(self, name):
                return getattr(self._source, name)

            def __setattr__(self, name, value):
                setattr(self._source, name, value)

            def get_valuation(self, *args):
                if self._error is not None:
                    raise self._error
                frame, prices = self._material
                if prices is not None:
                    self._source._last_valuation_prices = prices
                return frame

        results = []
        for index, item, material, error, pending in entries:
            check_thread_cancel()
            try:
                value = one(item, PreparedSource(material, error))
                error = None
            except TaskCancelled:
                raise
            except Exception as exc:  # noqa: BLE001 -- 单股失败按原回调记录，不能推进成功断点
                value, error = None, exc
            results.append((index, item, value, error, pending))
        return results

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
    @checked_collection
    def ingest_indices(
        self,
        start: date,
        end: date,
        ctx=None,
        codes: list[str] | None = None,
    ) -> int:
        """采集配置内指数；可指定子集供逐指数增量补采复用。"""
        end = eod_dates.cap_range(start, end)
        full_scope = codes is None
        configured = configured_benchmark_codes()
        allowed = set(configured)
        codes = list(dict.fromkeys(codes if codes is not None else configured))
        unsupported = [code for code in codes if code not in allowed]
        if unsupported:
            raise ValueError(f"指数不在系统配置清单中: {unsupported}")
        include_collection_scope(self, "market_index", None if full_scope else codes)
        total = 0
        if ctx:
            ctx.log(f"子任务：指数行情采集开始，{len(codes)} 个指数，区间 {start}~{end}")
            ctx.flush()
        for i, idx in enumerate(codes, 1):
            if ctx:
                ctx.check_cancel()
                ctx.set_phase("market_index", phase_total=len(codes), phase_done=i - 1,
                              current_item=idx)
            try:
                df = self.src.get_index_bar(idx, start, end)
                df = eod_dates.bound_bars(df, start, end)
                total += self.repo.upsert_index_bar(df)
                if ctx:
                    ctx.log(f"指数 {idx} 完成：{len(df) if df is not None else 0} 行")
            except Exception as e:  # noqa: BLE001
                log.warning("指数 %s 入库失败: %s", idx, e)
                if ctx:
                    ctx.log(f"指数 {idx} 采集失败：{e}", "warn")
                self.repo.log_update("index_bar", self.src.name, start, end, 0, "failed", str(e))
            if ctx:
                ctx.set_phase("market_index", phase_total=len(codes), phase_done=i,
                              current_item=idx)
        log.info("指数入库 %d 行（%s）", total, codes)
        if ctx:
            ctx.log(f"子任务：指数行情采集完成，共写入/更新 {total} 行")
        return total

    @checked_collection
    def _ingest_indices_incremental(self, end: date, ctx=None) -> int:
        """逐指数补到目标日；首次加入配置的指数自动回填系统历史窗口。"""
        codes = configured_benchmark_codes()
        include_collection_scope(self, "market_index", None)
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
    @checked_collection
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
        include_collection_scope(self, "stock", basic["code"].tolist())
        n = self.repo.upsert_stock_basic(basic)
        self.repo.log_update("stock_basic", self.src.name, None, None, n, "success")
        log.info("股票基础信息入库 %d 只", n)
        if ctx:
            ctx.log(f"子任务：股票基础信息采集完成，目标板块 {len(basic)} 只，写入/更新 {n} 只")
        return basic

    def _stock_basic_from_db(
        self, codes: list[str] | None = None, *, as_of: date | None = None,
    ) -> pd.DataFrame:
        """续跑用：从库读 stock_basic（首跑已刷新名册），列同 backfill 所需，避免重复触网。"""
        as_of = as_of or self._latest_open_day()
        df = self.repo.c.query_df(
            "SELECT code, name, price_limit_pct FROM stock_basic "
            "WHERE (list_date IS NULL OR list_date<=?) "
            "AND (delist_date IS NULL OR delist_date>?) ORDER BY code",
            [as_of, as_of],
        )
        if codes:
            df = df[df["code"].isin(codes)]
        return df

    # ── 单只股票日线 + 衍生指标 ──
    def _accurate_st_facts(
        self,
        code: str,
        trade_dates: list[date],
        *,
        force: bool = False,
        fetch_start: date | None = None,
        fetch_end: date | None = None,
        ctx=None,
        material: _DailySTMaterial | None = None,
    ) -> list[StockSTStatusFact]:
        """Resolve complete daily ST facts, fetching missing facts from baostock.

        Stored accurate facts are reused. Missing dates are fetched as one contiguous range;
        all source rows in that range are returned so suspended market days also become facts.
        No current-name fallback is allowed in the production path.
        """
        dates = sorted(set(trade_dates))
        if not dates and (fetch_start is None or fetch_end is None):
            return []
        if dates:
            row = material.stored if material is not None else self.c.query_df(
                """
                SELECT trade_date,is_st,source,source_ref,quality
                FROM stock_st_status_daily
                WHERE code=? AND trade_date BETWEEN ? AND ? AND quality='accurate'
                """,
                [code, dates[0], dates[-1]],
            )
            by_date = {
                pd.Timestamp(item["trade_date"]).date(): item
                for _, item in row.iterrows()
            }
        else:
            by_date = {}
        if not force and all(day in by_date for day in dates):
            return [
                StockSTStatusFact(
                    code=code,
                    trade_date=day,
                    status=PointInTimeSTStatus(
                        is_st=bool(by_date[day]["is_st"]),
                        source=str(by_date[day]["source"]),
                        source_ref=(
                            None if pd.isna(by_date[day]["source_ref"])
                            else str(by_date[day]["source_ref"])
                        ),
                        quality=STStatusQuality.ACCURATE,
                    ),
                )
                for day in dates
            ]

        query_start = fetch_start or dates[0]
        query_end = fetch_end or dates[-1]
        if material is not None and material.error is not None:
            raise material.error
        st_source, status_rows = (
            material.fetched if material is not None and material.fetched is not None
            else self._fetch_st_status_rows(code, query_start, query_end, ctx=ctx)
        )
        if status_rows is None or status_rows.empty:
            raise DataSourceError(f"{code} {query_start}~{query_end} ST 点时事实为空")
        status_by_date = {
            pd.Timestamp(row["trade_date"]).date(): bool(row["is_st"])
            for _, row in status_rows.iterrows()
        }
        missing = [day for day in dates if day not in status_by_date]
        if missing:
            raise DataSourceError(
                f"{code} ST 点时事实缺 {len(missing)} 个行情日，示例: "
                f"{','.join(map(str, missing[:5]))}"
            )
        # 同次状态请求已返回明确停牌证据，不能只保存 isST 而丢掉历史停牌。
        # 普通入库排除本次将写入的行情日期；强制 ST 刷新则依靠已有行情反连接排除成交日。
        candidates = set(pd.to_datetime(status_rows.trade_date).dt.date)
        if not force:
            candidates -= set(dates)
        from backend.services.data_report import DataIntegrityReport
        self._persist_gap_status(code, st_source, status_rows, sorted(candidates),
                                 DataIntegrityReport(self.c), ctx=ctx)
        return [
            StockSTStatusFact(
                code=code,
                trade_date=day,
                status=PointInTimeSTStatus(
                    is_st=status_by_date[day],
                    source=st_source.name,
                    source_ref="query_history_k_data_plus:isST",
                    quality=STStatusQuality.ACCURATE,
                ),
            )
            for day in sorted(status_by_date)
        ]

    def _fetch_st_status_rows(
        self, code: str, start: date, end: date, *, ctx=None
    ) -> tuple[DataSource, pd.DataFrame]:
        """Fetch one raw ST interval while respecting Baostock's global session lock."""
        st_source = self._source_for("st_status")
        if ctx:
            ctx.log(f"{code} 补采 ST/逐日交易状态 {start}~{end}（{st_source.name}）")
            ctx.flush()
        lock = session_lock(_BAO_FALLBACK_LOCK, "baostock") if st_source.name == "baostock" else nullcontext()
        with thread_cancel_scope(ctx.check_cancel if ctx else None), lock:
            rows = st_source.get_st_status(code, start, end)
        return st_source, rows

    @staticmethod
    def _st_facts_from_rows(
        code: str, source: DataSource, rows: pd.DataFrame
    ) -> list[StockSTStatusFact]:
        return [
            StockSTStatusFact(
                code=code,
                trade_date=pd.Timestamp(row["trade_date"]).date(),
                status=PointInTimeSTStatus(
                    is_st=bool(row["is_st"]),
                    source=source.name,
                    source_ref="query_history_k_data_plus:isST",
                    quality=STStatusQuality.ACCURATE,
                ),
            )
            for _, row in rows.iterrows()
        ]

    def _fetch_daily_with_fallback(
        self, code: str, start: date, end: date, primary: DataSource, ctx=None, allow_fallback=True,
    ) -> tuple[pd.DataFrame | None, str]:
        """主源取日线；**仅当主源返回空或报错**时用兜底源(baostock)整段重取（不混采，单只股票
        尽量单一来源，避免 ak/baostock 拼接致前复权因子跳变）。返回 (df, 实际来源名)。

        ctx（可选，仅串行路径传入）：把"主源失败/改用兜底源"写入任务实时日志，便于排查。
        """
        primary_error = None
        try:
            lock = session_lock(_BAO_FALLBACK_LOCK, "baostock") if primary.name == "baostock" else nullcontext()
            with thread_cancel_scope(ctx.check_cancel if ctx else None), lock:
                df = primary.get_daily_bar(code, start, end)
        except DataSourceError as e:
            primary_error = e
            log.warning("%s 主源(%s)取数失败，尝试兜底源: %s", code, primary.name, e)
            if ctx:
                ctx.log(f"{code} 主源({primary.name})取数失败，尝试兜底源：{e}", "warn")
            df = None
        if df is not None and not df.empty:
            return df, primary.name
        if not allow_fallback:
            raise DataSourceError(f"{code} 主源无有效行情，已失败的备用源留待后续重试")
        bao = self._bao_source()
        if bao.name == primary.name:
            raise DataSourceError(f"{code} {start}~{end} {primary.name} 无有效行情，"
                                  f"不重复请求同一备用源：{primary_error or '空响应'}") from primary_error
        if not bao.supports("daily"):
            msg = f"{code} {start}~{end}：主源无数据，且未找到可用兜底源，本只写入 0 行"
            log.error(msg)
            if ctx:
                ctx.log(msg, "error")
                ctx.flush()
            raise DataSourceError(msg)
        with thread_cancel_scope(ctx.check_cancel if ctx else None), session_lock(_BAO_FALLBACK_LOCK, "baostock"):
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

    def _verified_price_references(self, code: str, local: pd.DataFrame) -> pd.DataFrame:
        """只接纳直接参考价及同次收盘匹配的证据；缺日/冲突在写行情前失败。"""
        backup = self._bao_source()
        local = local[["trade_date", "close"]].copy()
        local["trade_date"] = pd.to_datetime(local["trade_date"]).dt.date
        try:
            with session_lock(_BAO_FALLBACK_LOCK, "baostock"):
                reference = backup.get_daily_bar(
                    code, local.trade_date.min(), local.trade_date.max()
                )
        except TaskCancelled:
            raise
        except Exception as exc:
            raise DataSourceError(f"{code} 参考价备用源校准失败: {exc}") from exc
        check_thread_cancel()
        if reference is None or reference.empty:
            raise DataSourceError(f"{code} 备用源无校准数据")
        reference = reference[["trade_date", "pre_close", "close"]].copy()
        reference["trade_date"] = pd.to_datetime(reference["trade_date"]).dt.date
        checked = local.merge(
            reference,
            on="trade_date",
            how="left",
            suffixes=("", "_reference"),
            validate="one_to_one",
        )
        refs = pd.to_numeric(checked.pre_close, errors="coerce")
        valid = (
            refs.gt(0)
            & refs.lt(float("inf"))
            & checked.close.sub(checked.close_reference).abs().le(0.011)
        )
        if not valid.all():
            bad = checked.loc[~valid, "trade_date"].astype(str).tolist()
            raise DataSourceError(
                f"{code} {','.join(bad[:10])} 备用源缺少有效官方前收盘或收盘与主源不一致，拒绝混算"
            )
        return checked.rename(
            columns={
                "pre_close": "reference_pre_close",
                "close_reference": "reference_close",
            }
        ).assign(reference_source=backup.name)

    def _calibrate_factor_boundaries(
        self,
        df: pd.DataFrame,
        code: str,
        ctx=None,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """核验重采区间接缝，不能将两个来源的因子绝对基准当作除权。

        入参前收盘由同批来源的前置行情计算，仅用于发现接缝；真正衔接只用备用源
        的直接参考价。右侧及源端漏返的区间内旧行，证据与行情一并提交。
        """
        empty = pd.DataFrame()
        if df.empty:
            return df, empty
        ordered = df.sort_values("trade_date")
        incoming_dates = pd.to_datetime(ordered.trade_date).dt.date.tolist()
        neighbors = self.c.query_df(
            "(SELECT * FROM daily_bar WHERE code=? AND trade_date<? "
            "ORDER BY trade_date DESC LIMIT 1) UNION ALL "
            "(SELECT * FROM daily_bar WHERE code=? AND trade_date>? "
            "ORDER BY trade_date LIMIT 1) UNION ALL "
            "SELECT * FROM daily_bar WHERE code=? AND trade_date BETWEEN ? AND ? "
            "AND trade_date NOT IN (SELECT unnest(?::DATE[]))",
            [
                code,
                incoming_dates[0],
                code,
                incoming_dates[-1],
                code,
                incoming_dates[0],
                incoming_dates[-1],
                incoming_dates,
            ],
        )
        if neighbors.empty:
            return df, empty
        # 只读取请求范围与相邻行；窗口内部保留旧行同样形成来源切换，不能漏掉。
        timeline = pd.concat([ordered.assign(_incoming=True), neighbors.assign(_incoming=False)])
        timeline["trade_date"] = pd.to_datetime(timeline.trade_date)
        timeline = timeline.sort_values("trade_date").reset_index(drop=True)
        switches = timeline._incoming.ne(timeline._incoming.shift())
        suspect = []
        for index in timeline.index[switches & (timeline.index > 0)]:
            previous, current = timeline.iloc[index - 1], timeline.iloc[index]
            ref = current.get("reference_pre_close")
            ref_close = current.get("reference_close")
            if (
                pd.notna(current.get("reference_source"))
                and pd.notna(ref)
                and ref > 0
                and pd.notna(ref_close)
                and abs(ref_close - current.close) <= 0.011
            ):
                continue
            factors = [previous.get("adj_factor"), current.get("adj_factor")]
            expected = current.get("pre_close")
            if any(pd.isna(value) or value <= 0 for value in factors):
                # 缺因子同样不能证明接缝连续，交给直接参考价校验。
                suspect.append(current)
                continue
            implied = previous.close * factors[0] / factors[1]
            if pd.isna(expected) or abs(implied - expected) > 0.011:
                suspect.append(current)
        if not suspect:
            return df, empty
        verified = self._verified_price_references(code, pd.DataFrame(suspect))
        calibrated = df.copy()
        dates = pd.to_datetime(calibrated.trade_date).dt.date
        for row in verified.itertuples():
            mask = dates == row.trade_date
            if mask.any():
                for col in ("reference_pre_close", "reference_close", "reference_source"):
                    calibrated.loc[mask, col] = getattr(row, col)
                calibrated.loc[mask, "pre_close"] = row.reference_pre_close
        retained = verified[~verified.trade_date.isin(incoming_dates)].copy()
        if ctx:
            ctx.log(f"{code} 跨来源因子接缝校验 {len(verified)} 日，保留原始因子并记录官方参考价")
        return calibrated, retained

    def _calibrate_corporate_action_pre_close(
        self,
        df: pd.DataFrame,
        code: str,
        board_limit_pct: float,
        used_source: str,
        ctx=None,
    ) -> tuple[pd.DataFrame, str]:
        """用直接提供 preclose 的备用源校准会改变涨跌停结论的除权日。

        新浪原始价和后复权价都只保留到分，由二者比值反推除权参考价时可能
        相差一分钱；这一分钱在再次计算涨跌停价时最多放大为两分钱。普通日
        不触发额外请求，只有因子真实切换且当前参考价会把收盘判为越界时才
        定向交叉验证，避免把合法除权行情反复列为质量问题。长期停牌后缺少前置成交
        导致参考价为空时，也须获取备用源的官方参考价，不能据空值关闭质检问题。
        """
        marker = df.get("_pre_close_factor_event")
        if marker is None:
            return df, used_source

        from backend.market_rules import limit_prices, price_limit_pct_for, round_price_to_cent

        # 长期停牌后首日的前置窗口可能没有成交，不能用空参考价覆盖已知事实。
        # 与除权边界共用 BaoStock 的直接前收盘校准及来源留痕。
        reference_missing = pd.to_numeric(df["pre_close"], errors="coerce").isna()
        suspect_dates: list[date] = [
            pd.Timestamp(day).date() for day in df.loc[reference_missing, "trade_date"]
        ]
        for _, row in df[marker.fillna(False)].iterrows():
            pre_close = row.get("pre_close")
            close = row.get("close")
            if pd.isna(pre_close) or pd.isna(close) or float(pre_close) <= 0:
                continue
            up, down = limit_prices(
                float(pre_close),
                price_limit_pct_for(board_limit_pct, False, row["trade_date"], code=code),
            )
            rounded_close = round_price_to_cent(float(close))
            if rounded_close < down - 0.011 or rounded_close > up + 0.011:
                suspect_dates.append(pd.Timestamp(row["trade_date"]).date())
        # 来源换码/重置会丢掉此前整段因子，不能只校准断点一天；
        # 此时整段取直接参考价，使前段分红也进入统一清洗链。
        factor = pd.to_numeric(df.get("adj_factor", pd.Series(float("nan"), index=df.index)), errors="coerce")
        close = pd.to_numeric(df["close"], errors="coerce")
        reset = factor.div(factor.shift()).sub(1).abs().gt(0.5) & close.div(close.shift()).sub(1).abs().le(0.3)
        if reset.any():
            suspect_dates = sorted(set(pd.to_datetime(df["trade_date"]).dt.date))
        if not suspect_dates:
            return df, used_source

        backup = self._bao_source()
        selected = df[pd.to_datetime(df.trade_date).dt.date.isin(suspect_dates)]
        verified = self._verified_price_references(code, selected)
        calibrated = df.copy()
        for row in verified.itertuples():
            mask = pd.to_datetime(calibrated.trade_date).dt.date == row.trade_date
            calibrated.loc[mask, "pre_close"] = row.reference_pre_close
            for col in ("reference_pre_close", "reference_close", "reference_source"):
                calibrated.loc[mask, col] = getattr(row, col)
        source = f"{used_source}+{backup.name}:preclose"
        message = (
            f"{code} 校准除权参考价 {len(suspect_dates)} 日："
            f"{','.join(map(str, suspect_dates[:10]))}{'…' if len(suspect_dates) > 10 else ''}（{backup.name}）"
        )
        log.info(message)
        if ctx:
            ctx.log(message)
        return calibrated, source

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
        status_unavailable: bool = False,
        _prefetched=None,
        _fetch_error=None,
        _st_material: _DailySTMaterial | None = None,
        _defer_write: bool = False,
    ) -> int | _PreparedDaily:
        end = eod_dates.cap_range(start, end)
        try:
            if _fetch_error is not None:
                raise _fetch_error
            df, used_source = _prefetched if _prefetched is not None else self._fetch_daily_with_fallback(
                code, start, end, source or self.src, ctx=ctx, **({"allow_fallback": False} if status_unavailable else {})
            )
        except DataSourceError as daily_error:
            if status_unavailable:
                raise
            # Baostock intentionally removes suspended rows from daily_bar but still exposes
            # tradestatus=0 + isST. Only that positive suspension evidence may turn an empty
            # daily result into a successful zero-row update; weekends/source failures still fail.
            try:
                st_source, status_rows = self._fetch_st_status_rows(code, start, end, ctx=ctx)
                if status_rows is None or status_rows.empty:
                    raise DataSourceError("ST 状态亦为空")
                trade_status = pd.to_numeric(status_rows["trade_status"], errors="coerce")
                if trade_status.isna().any() or not trade_status.eq(0).all():
                    raise DataSourceError("ST 状态未确认全区间停牌")
                expected_open = {
                    pd.Timestamp(value).date()
                    for value in self.c.query_df(
                        "SELECT trade_date FROM trade_calendar "
                        "WHERE is_open AND trade_date BETWEEN ? AND ?",
                        [start, end],
                    )["trade_date"].tolist()
                }
                returned_dates = {
                    pd.Timestamp(value).date()
                    for value in status_rows["trade_date"].tolist()
                }
                if not expected_open or not expected_open.issubset(returned_dates):
                    raise DataSourceError("ST 状态未覆盖请求区间全部开市日")
                check_thread_cancel()
                existing = self.c.query_df(
                    "SELECT trade_date,volume,amount FROM daily_bar "
                    "WHERE code=? AND trade_date BETWEEN ? AND ?", [code, start, end]
                )
                if (pd.to_numeric(existing["volume"], errors="coerce").fillna(0).gt(0)
                        | pd.to_numeric(existing["amount"], errors="coerce").fillna(0).gt(0)).any():
                    raise DataSourceError("权威停牌状态与已有成交记录冲突，保留原数据待核验")
                # 两个来源均无成交且逐日状态明确停牌，清掉源端沿用昨收生成的零成交伪K线。
                # 只清实际存在的行及其指标；交易日历与 ST 事实仍保留。
                if not existing.empty:
                    with self.c.transaction():
                        self.c.execute(
                            "DELETE FROM daily_metrics WHERE code=? AND trade_date IN "
                            "(SELECT trade_date FROM daily_bar WHERE code=? AND trade_date BETWEEN ? AND ?)",
                            [code, code, start, end],
                        )
                        self.c.execute(
                            "DELETE FROM stock_share_capital_daily WHERE code=? AND trade_date IN "
                            "(SELECT trade_date FROM daily_bar WHERE code=? AND trade_date BETWEEN ? AND ?)",
                            [code, code, start, end],
                        )
                        self.c.execute(
                            "DELETE FROM daily_bar WHERE code=? AND trade_date BETWEEN ? AND ?",
                            [code, start, end],
                        )
                    if ctx:
                        ctx.log(f"{code} 按权威停牌事实移除 {len(existing)} 条零成交伪K线")
                StockSTStatusService(self.c).upsert_facts(
                    self._st_facts_from_rows(code, st_source, status_rows),
                    change_reason="daily_ingest_st_suspended",
                    task_id=getattr(ctx, "tid", None),
                )
                # 这里已有逐日 tradestatus=0 的正向证据，且覆盖全部请求开市日；
                # 必须同时保存停牌确认，避免成功零行采集后质检仍报告尾部滞后。
                from backend.services.data_report import DataIntegrityReport

                self._persist_gap_status(code, st_source, status_rows, sorted(expected_open), DataIntegrityReport(self.c), ctx=ctx)
                if ctx:
                    ctx.log(f"{code} {start}~{end} 已由 Baostock 确认停牌；保存 ST 事实，日线 0 行")
                return 0
            except DataSourceError as st_error:
                raise DataSourceError(f"{daily_error}；ST 状态无法确认停牌: {st_error}") from daily_error
        # 并发终止可能发生在网络返回与入库之间；此检查保证任务进入 interrupted 后不再遗留写入。
        check_thread_cancel()
        df = eod_dates.bound_bars(df, start, end)
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
        # 板块涨跌幅按代码判定；ST 必须来自与行情日期对齐的 Baostock 点时事实。
        if board_limit_pct is None:
            _, _, board_limit_pct = classify_board(code.split(".")[0])
        df, used_source = self._calibrate_corporate_action_pre_close(
            df, code, float(board_limit_pct), used_source, ctx=ctx
        )
        df, retained_references = self._calibrate_factor_boundaries(df, code, ctx=ctx)
        st_service = StockSTStatusService(self.c)
        trade_dates = [pd.Timestamp(day).date() for day in df["trade_date"].tolist()]
        if st_status is not None or is_st is not None:
            # Explicit values are a test/import seam only and remain visibly approximate.
            injected = st_status or PointInTimeSTStatus(
                is_st=bool(is_st),
                source="explicit_import",
                source_ref=None,
                quality=STStatusQuality.APPROXIMATE,
            )
            incoming_st_facts = [
                StockSTStatusFact(code=code, trade_date=day, status=injected)
                for day in trade_dates
            ]
            effective_st_facts = st_service.prefer_existing_accurate(incoming_st_facts)
        else:
            effective_st_facts = self._accurate_st_facts(
                code,
                trade_dates,
                fetch_start=start,
                fetch_end=end,
                ctx=ctx,
                material=_st_material,
            )
        effective_st_by_date = {
            fact.trade_date: fact.status.is_st for fact in effective_st_facts
        }
        # 质检标记：涨跌停/一字板/ST（回测撮合前提）
        point_in_time_st = [
            effective_st_by_date[pd.Timestamp(trade_day).date()]
            for trade_day in df["trade_date"].tolist()
        ]
        from backend.services.stock_special_trading_day import apply_special_day_markers

        df = apply_special_day_markers(self.c, add_markers(df, board_limit_pct, point_in_time_st))
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
        for col in ("reference_pre_close", "reference_close", "reference_source"):
            if col not in df:
                df[col] = None
        bar_cols = [
            "code", "trade_date", "open", "high", "low", "close",
            "pre_close", "reference_pre_close", "reference_close", "reference_source",
            "volume", "amount", "adj_factor", "turnover_rate",
            "adj_factor_clean", "is_st", "is_suspended", "limit_status", "is_one_word",
        ]
        prepared = _PreparedDaily(
            code, start, end, df, bar_cols, effective_st_facts, retained_references, used_source,
        )
        if _defer_write:
            return prepared
        self._write_daily_batch([prepared], ctx=ctx)
        return len(df)

    def _write_daily_batch(self, materials: list[_PreparedDaily], *, ctx=None) -> None:
        """复用单股校验结果，一批行情、ST、股本市值及来源留痕原子提交。"""
        if not materials:
            return
        from backend.services.share_capital import ShareCapitalService

        check_thread_cancel()
        frames = pd.concat([item.frame for item in materials], ignore_index=True)
        bars = pd.concat([item.frame[item.bar_columns] for item in materials], ignore_index=True)
        with self.c.transaction():
            self.repo.upsert_daily_bar(bars)
            for item in materials:
                if not item.references.empty:
                    with self.c.temp_view(item.references, "factor_boundary") as view:
                        self.c.execute(
                            "UPDATE daily_bar b SET reference_pre_close=r.reference_pre_close, "
                            "reference_close=r.reference_close,reference_source=r.reference_source, "
                            "adj_factor_clean=NULL FROM " + view + " r "
                            "WHERE b.code=? AND b.trade_date=r.trade_date", [item.code],
                        )
            # 成交证据按目标键批量撤销旧停牌；未知量仍不能推翻停牌事实。
            traded = frames.loc[pd.to_numeric(frames.volume, errors="coerce").gt(0),
                                ["code", "trade_date"]]
            if not traded.empty:
                with self.c.temp_view(traded, "traded_keys") as view:
                    old = self.c.query_df(
                        f"SELECT s.code,s.trade_date FROM stock_suspension s JOIN {view} t "
                        "USING(code,trade_date)"
                    )
                    self.c.execute(
                        f"DELETE FROM stock_suspension s USING {view} t "
                        "WHERE s.code=t.code AND s.trade_date=t.trade_date"
                    )
                for item in materials:
                    dates = old.loc[old.code.eq(item.code), "trade_date"]
                    if not dates.empty:
                        self.repo.log_update(
                            "stock_suspension", item.source, item.start, item.end, len(dates),
                            "success", json.dumps({"code": item.code,
                                "action": "revoke_by_traded_bar", "dates": dates.astype(str).tolist(),
                                "task_id": getattr(ctx, "tid", None)}, ensure_ascii=False),
                        )
            StockSTStatusService(self.c).upsert_facts(
                [fact for item in materials for fact in item.st_facts],
                change_reason="daily_ingest_st_sync", task_id=getattr(ctx, "tid", None),
                _in_transaction=True,
            )
            # 备用源无股本列也按已存股本刷新计算市值，保持来源核验口径。
            ShareCapitalService(self.c).merge(frames, "sina_daily", _in_transaction=True)
            for item in materials:
                if item.source != self.s.datasource.primary:
                    self._record_provenance(item.code, "daily_bar", item.start, item.end,
                                            item.source, len(item.frame))

    def _dirty_daily_codes(self, codes) -> set[str]:
        """批次已提交但断点未登记时，续跑仍须完成这些股票的因子收尾。"""
        if not codes:
            return set()
        return set(self.c.query_df(
            "SELECT DISTINCT code FROM daily_bar WHERE adj_factor_clean IS NULL "
            "AND code IN (SELECT unnest(?::VARCHAR[]))", [list(codes)],
        )["code"])

    def _run_daily_parallel(
        self, codes, starts, end, *, concurrency, ctx, label, on_complete, limits=None,
    ):
        """日线三类批任务共用：预读事实、并发取价/状态、主线程校验与批次提交。"""
        tls = threading.local()
        source_name = self.src.name

        def prepare(code):
            start = starts[code]
            stored = self.c.query_df(
                "SELECT trade_date,is_st,source,source_ref,quality FROM stock_st_status_daily "
                "WHERE code=? AND trade_date BETWEEN ? AND ? AND quality='accurate'",
                [code, start, end],
            ) if start <= end else pd.DataFrame()
            return code, _DailySTMaterial(stored)

        def worker(item):
            code, status = item
            start = starts[code]
            if start > end:
                return None
            bars = self._fetch_daily_with_fallback(
                code, start, end, self._thread_source(tls, source_name),
            )
            frame = eod_dates.bound_bars(bars[0], start, end)
            known = set(pd.to_datetime(status.stored.get("trade_date", pd.Series(dtype=object))).dt.date)
            if frame is not None and not frame.empty and any(
                pd.Timestamp(day).date() not in known for day in frame.trade_date
            ):
                try:
                    # BaoStock 自身及共享兜底锁继续保证单会话串行；取数与主线程落库重叠。
                    status.fetched = self._fetch_st_status_rows(code, start, end)
                except TaskCancelled:
                    raise
                except Exception as exc:  # noqa: BLE001 -- 状态失败交回原权威校验，不重复取源
                    status.error = exc
            return bars

        def commit(entries):
            results, prepared = [], []
            for index, item, bars, error, pending in entries:
                code, status = item
                check_thread_cancel()
                try:
                    value = (0 if starts[code] > end else self.ingest_one_daily(
                        code, starts[code], end, (limits or {}).get(code), ctx=ctx,
                        _prefetched=bars, _fetch_error=error, _st_material=status,
                        _defer_write=True,
                    ))
                    if isinstance(value, _PreparedDaily):
                        prepared.append(value)
                        value = len(value.frame)
                    error = None
                except TaskCancelled:
                    raise
                except Exception as exc:  # noqa: BLE001 -- 单股校验失败不阻止其它材料提交
                    value, error = None, exc
                results.append((index, code, value, error, pending))
            # 批次事务失败直接退出，不推进其中任何成功断点；续跑会重取未提交项。
            self._write_daily_batch(prepared, ctx=ctx)
            return results

        self._run_bounded_parallel(
            codes, worker, concurrency=concurrency, ctx=ctx, wait_label=label,
            prepare=prepare, transform_batch=commit, batch_size=concurrency,
            prefetch_next_batch=True, on_complete=on_complete,
        )

    # ── 估值/市值（总市值/总股本，补 G2）──
    def _history_window(self, years: int, ctx=None) -> tuple[date, date]:
        """历史任务首次冻结日期窗口，续跑不随当天日期或默认年限漂移。"""
        checkpoint = getattr(ctx, "checkpoint", {}) or {}
        if checkpoint.get("history_start") and checkpoint.get("history_end"):
            eod_dates.cap_end(date.fromisoformat(checkpoint['history_end']), strict=True)
            return (date.fromisoformat(checkpoint["history_start"]),
                    date.fromisoformat(checkpoint["history_end"]))
        today = eod_dates.shanghai_now().date()
        try:
            eod_dates.is_open_day(self.repo.c, today)
        except DataSourceError:
            # 首次初始化历史库时先补真实日历；源端仍未覆盖则由统一解析明确失败。
            self.ingest_calendar(years_before(today, years), today, ctx=ctx)
        end = self._resolve_update_end(today, _UPDATE_READY_SAMPLE, None, ctx)
        start = years_before(end, years)
        if ctx is not None:
            ctx.set_checkpoint(history_start=start.isoformat(), history_end=end.isoformat())
        return start, end

    @checked_collection
    def ingest_valuation(self, codes: list[str] | None = None, years: int | None = None,
                         concurrency: int | None = None, ctx=None) -> dict:
        """补每日市值字段到 daily_metrics，并把最新总/流通股本写入 stock_basic。

        数据源 stock_value_em（东财市值接口，可用）。按在市股逐只拉取。
        concurrency（与 update 同款）：>1 时线程池并发拉取，每线程独立 DataSource，
        写入由 DuckDB 单写锁串行。默认 1（串行）。并发不放大来源请求频率。
        """
        years = years or self.s.datasource.history_years
        start, end = self._history_window(years, ctx)
        live = self._stock_basic_from_db(codes, as_of=end)["code"].tolist()
        include_collection_scope(self, "stock", live)
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
            return self._collect_capital_one(code, source, start, end)

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
                    _tick(i)
        else:  # 并发：线程局部 DataSource，写入由 DuckDB RLock 串行
            tls = threading.local()
            source_name = val_src.name

            def _worker(code: str) -> int:
                src = self._thread_source(tls, source_name)
                return self._fetch_capital_material(code, src, start, end)

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
                    _tick(i)

            self._run_bounded_parallel(
                pending, _worker, concurrency=concurrency, ctx=ctx,
                wait_label="历史市值字段补采", on_complete=_complete,
                transform_batch=lambda entries: self._complete_capital_material(entries, val_src, _one),
            )
        result = {"target": len(live), "ok": ok, "skip": skip, "fail": fail, "total_mv_rows": rows}
        log.info("估值入库完成: %s", result)
        if ctx:
            ctx.log(f"子任务：历史市值字段补采完成，成功{ok} 跳过{skip} 失败{fail}，写入 {rows} 行")
        return result

    @checked_collection
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
        eod_dates.cap_end(trade_date, strict=True)
        from backend.services.share_capital import ShareCapitalService
        sql = (
            "SELECT b.code AS code FROM daily_bar b "
            "JOIN stock_basic sb ON sb.code = b.code "
            "LEFT JOIN daily_metrics m ON m.code = b.code AND m.trade_date = b.trade_date "
            "LEFT JOIN stock_share_capital_daily s ON s.code=b.code AND s.trade_date=b.trade_date "
            "WHERE b.trade_date = ? AND (sb.delist_date IS NULL OR sb.delist_date>?) "

        )
        params: list = [trade_date, trade_date]
        if codes:
            sql += f" AND b.code IN ({','.join('?' * len(codes))})"
            params += list(codes)
        include_collection_scope(self, "stock", self.repo.c.query_df(sql, params)["code"].tolist())
        pending = self.repo.c.query_df(
            sql + f" AND ({ShareCapitalService.review_predicate()})", params
        )["code"].tolist()
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
            return self._collect_capital_one(code, source, trade_date, trade_date)

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
                if ctx:
                    ctx.set_phase("valuation_latest", phase_total=n, phase_done=i, current_item=code,
                                  valuation_latest_done_codes=sorted(done_latest))
                if i % 20 == 0 or i == n:
                    log.info("补最新日市值进度 %d/%d（成功%d 失败%d，写入 %d行）", i, n, ok, fail, rows)
                    if ctx:
                        ctx.log(f"最新日市值补采进度 {i}/{n}：成功{ok} 失败{fail}，写入 {rows} 行")
                        ctx.flush()
        else:
            tls = threading.local()
            source_name = val_src.name

            def _worker(code: str) -> int:
                src = self._thread_source(tls, source_name)
                frame = src.get_valuation(code, trade_date, trade_date)
                if frame is not None:
                    frame.attrs["source_valuation_prices"] = getattr(src, "_last_valuation_prices", None)
                return frame

            def _merge_batch(entries):
                from backend.services.capital_quality import CapitalQualityService
                frames, normalized = [], []
                for index, code, frame, error, in_flight in entries:
                    if error is None:
                        try:
                            frame = self._validated_valuation_frame(code, frame, trade_date, trade_date)
                            if not frame.empty:
                                frames.append(frame)
                        except Exception as exc:
                            error = exc
                    normalized.append((index, code, frame, error, in_flight))
                # 一批提交后才调用完成回调；事务失败不会把任何待提交股票登记成功。
                check_thread_cancel()
                if frames:
                    ShareCapitalService(self.c).merge(pd.concat(frames, ignore_index=True),
                                                     "eastmoney_daily", reported=True)
                codes_in_batch = [entry[1] for entry in normalized]
                review = set(self.c.query_df(
                    "SELECT DISTINCT b.code FROM daily_bar b "
                    "LEFT JOIN stock_share_capital_daily s USING(code,trade_date) "
                    "LEFT JOIN daily_metrics m USING(code,trade_date) "
                    "WHERE b.trade_date=? AND b.code IN (SELECT unnest(?::VARCHAR[])) "
                    f"AND ({ShareCapitalService.review_predicate()}) UNION "
                    "SELECT code FROM stock_share_capital_event WHERE active "
                    "AND code IN (SELECT unnest(?::VARCHAR[])) AND "
                    "(effective_date IS NULL OR total_share<=0 OR float_share<0 OR float_share>total_share)",
                    [trade_date, codes_in_batch, codes_in_batch])["code"])
                results = []
                for index, code, frame, error, in_flight in normalized:
                    try:
                        # 缺口、拒用原始记录及来源冲突仍走既有多来源补采，不能以批量
                        # 计算一致掩盖来源核验。源请求失败也继续尝试原有补充来源。
                        if error is not None or code in review or frame is None or frame.empty:
                            prices = frame.attrs.get("source_valuation_prices") if frame is not None else None
                            prepared = self._complete_capital_material(
                                [(index, code, (frame, prices), error, in_flight)], val_src, _one)[0]
                            value, error = prepared[2], prepared[3]
                        else:
                            value = int(frame["total_mv"].notna().sum())
                    except TaskCancelled:
                        raise
                    except Exception as exc:
                        value, error = None, exc
                    results.append((index, code, value, error, in_flight))
                CapitalQualityService(self.c).sync(codes_in_batch)
                from backend.services.share_capital_history import ShareCapitalHistoryService
                ShareCapitalHistoryService(self.c).rebuild_many(codes_in_batch)
                return results

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
                if ctx:
                    ctx.set_phase("valuation_latest", phase_total=n, phase_done=i, current_item=code,
                                  valuation_latest_done_codes=sorted(done_latest))
                if i % 20 == 0 or i == n:
                    log.info(
                        "补最新日市值进度 %d/%d（成功%d 失败%d，写入 %d行）",
                        i, n, ok, fail, rows,
                    )
                    if ctx:
                        ctx.log(
                            f"最新日市值补采进度 {i}/{n}：成功{ok} 失败{fail}，"
                            f"写入 {rows} 行"
                        )
                        ctx.flush()

            self._run_bounded_parallel(
                pending, _worker, concurrency=concurrency, ctx=ctx,
                wait_label="最新日市值补采", on_complete=_complete,
                transform_batch=_merge_batch, batch_size=concurrency,
                prefetch_next_batch=True,
            )
        result = {"trade_date": str(trade_date), "ok": ok, "fail": fail, "total_mv_rows": rows}
        log.info("补最新日市值完成: %s", result)
        if ctx:
            ctx.log(f"子任务：最新日市值补采完成，成功{ok} 失败{fail}，写入 {rows} 行")
        return result

    @checked_collection
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
            "LEFT JOIN stock_share_capital_daily s ON s.code=b.code AND s.trade_date=b.trade_date "
            "WHERE (sb.delist_date IS NULL OR sb.delist_date> "
            "(SELECT COALESCE(max(trade_date),current_date) FROM daily_bar)) "
            "AND (m.code IS NULL OR m.total_mv IS NULL OR m.float_mv IS NULL "
            "OR s.total_share IS NULL OR s.float_share IS NULL) "
            "GROUP BY b.code")
        if codes:
            gap = gap[gap["code"].isin(set(codes))]
        include_collection_scope(self, "stock", codes if codes is not None else self.c.query_df(
            "SELECT code FROM stock_basic WHERE delist_date IS NULL OR delist_date>"
            "(SELECT COALESCE(max(trade_date),current_date) FROM daily_bar)"
        )["code"].tolist())
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
            return self._collect_capital_one(code, source, lo, hi)

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
                if ctx:
                    ctx.set_phase("valuation_gap", phase_total=n, phase_done=i, current_item=item[0],
                                  valuation_gap_done_codes=sorted(done_gap_codes))
                if i % 20 == 0 or i == n:
                    log.info("市值回补进度 %d/%d（成功%d 失败%d，写入 %d行）", i, n, ok, fail, rows)
                    if ctx:
                        ctx.log(f"市值缺口回补进度 {i}/{n}：成功{ok} 失败{fail}，写入 {rows} 行")
                        ctx.flush()
        else:
            tls = threading.local()
            source_name = val_src.name

            def _worker(item) -> int:
                src = self._thread_source(tls, source_name)
                return self._fetch_capital_material(item[0], src, item[1], item[2])

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
                if ctx:
                    ctx.set_phase("valuation_gap", phase_total=n, phase_done=i, current_item=code,
                                  valuation_gap_done_codes=sorted(done_gap_codes))
                if i % 20 == 0 or i == n:
                    log.info(
                        "市值回补进度 %d/%d（成功%d 失败%d，写入 %d行）",
                        i, n, ok, fail, rows,
                    )
                    if ctx:
                        ctx.log(
                            f"市值缺口回补进度 {i}/{n}：成功{ok} 失败{fail}，"
                            f"写入 {rows} 行"
                        )
                        ctx.flush()

            self._run_bounded_parallel(
                pending, _worker, concurrency=concurrency, ctx=ctx,
                wait_label="市值缺口回补", on_complete=_complete,
                transform_batch=lambda entries: self._complete_capital_material(entries, val_src, _one),
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
        起点之前的空档必须是非交易日或有停牌证据，不能用宽限天数吞掉缺口。
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
        calendar = [pd.Timestamp(day).date() for day in self.c.query_df(
            "SELECT trade_date FROM trade_calendar WHERE is_open AND trade_date>=? "
            "ORDER BY trade_date", [start]
        )["trade_date"].tolist()]
        suspension = self.c.query_df(
            "SELECT code,trade_date FROM stock_suspension WHERE trade_date>=?", [start]
        )
        suspended = set(zip(suspension["code"], pd.to_datetime(suspension["trade_date"]).dt.date))
        covered = set()
        for code, minimum in loaded_min.items():
            list_date = list_lut.get(code)
            threshold = list_date if (list_date and list_date > start) else start
            if minimum <= threshold:
                covered.add(code)
            elif calendar:
                missing = calendar[bisect_left(calendar, threshold):bisect_left(calendar, minimum)]
                if all((code, day) in suspended for day in missing):
                    covered.add(code)
        return covered

    @checked_collection
    def backfill(self, codes: list[str] | None = None, years: int | None = None, ctx=None,
                 concurrency: int | None = None) -> dict:
        """全量回填近 N 年。codes=None 表示全市场；可断点续跑（跳过已入库）。

        ctx（M2.8-B，可选）：逐股写实时日志 + 进度 + checkpoint。续跑天然幂等（跳过已入库）。
        concurrency（与 update 同款）：>1 时线程池并发拉取，每线程独立 DataSource
        （限流按实际来源共享，不放大来源总限速），写入由 DuckDB 单写锁串行。默认 1（串行）。
        并发仅覆盖网络等待，不放大来源请求频率。
        """
        years = years or self.s.datasource.history_years
        start, end = self._history_window(years, ctx)
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
        include_collection_scope(self, "stock", target_codes)
        # 板块涨跌幅查找表；ST 状态由 ingest_one_daily 按行情日期读取 baostock 点时事实。
        limit_lut = dict(zip(basic["code"], basic["price_limit_pct"]))

        # 断点续跑 + 部分覆盖修复：旧逻辑"有任意数据就跳过"会把仅有部分近期数据的股票
        # （如经缺口兜底补了近窗口、或上次中断）误判为已完成，早期历史永远补不上。改为按
        # "最早入库日是否已覆盖到回填起点(或上市日)"判断：仅非交易日或准确停牌证据允许首日延后，不能宽限吞掉缺口。
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

        def _one(
            code: str, source: DataSource | None = None, ctx_=None, *,
            prefetched=None, fetch_error=None,
        ) -> int:
            return self.ingest_one_daily(code, start, end, limit_lut.get(code),
                                         source=source, ctx=ctx_, _prefetched=prefetched, _fetch_error=fetch_error)

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
            if ctx:
                ctx.set_phase("daily_bar", phase_total=n, phase_done=i, current_item=code)

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
        else:  # 并发：线程局部 DataSource（限流按实际来源共享），写入由 DuckDB RLock 串行
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

            self._run_daily_parallel(
                pending, {code: start for code in pending}, end,
                concurrency=concurrency, ctx=ctx, label="历史补数",
                on_complete=_complete, limits=limit_lut,
            )
        # 上次可在行情写入后、因子收尾前中断；即使本轮行情已覆盖也须补完收尾。
        updated.update(self._dirty_daily_codes(target_codes))
        factor_result = {"target": 0, "ok": 0, "fail": 0, "rows": 0}
        if updated:
            if ctx:
                ctx.log(f"↻ 重算干净复权因子（{len(updated)} 只新入库）…")
            factor_result = self._refresh_clean_factors(sorted(updated), ctx=ctx)
        result = {"target": len(target_codes), "ok": ok, "skip": skip,
                  "fail": fail + factor_result["fail"], "rows": total_rows,
                  "price_factors": factor_result}
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
        start = (last + timedelta(days=1)) if last else years_before(
            end, self.s.datasource.history_years)
        if start > end:
            return 0
        return self.ingest_one_daily(code, start, end, source=source, ctx=ctx)

    def _previous_open_day(self, day: date) -> date:
        return eod_dates.latest_open_day(self.repo.c, day - timedelta(days=1))

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

        先按统一时间/日历规则选已收盘日，再对当天执行源端就绪探测。
        全市场与指定股票使用同一保护；强制当日只能跳过源端回退。
        """
        target = eod_dates.resolve_end(self.repo.c, requested_end, force=force_current_day)
        if force_current_day:
            if ctx:
                ctx.log(f"已确认当日 {target} 收盘，强制采集仅跳过源端就绪回退", "warn")
            return target
        if target != requested_end and ctx:
            ctx.log(f"EOD目标日由 {requested_end} 收敛至已收盘交易日 {target}")

        if not basic:
            return target

        # 只有"今天确是交易日"才做主源当日就绪探测；非交易日已回退，无需探测。
        if target != requested_end or target != eod_dates.shanghai_now().date():
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
                df = eod_dates.bound_bars(df, requested_end, requested_end)
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

    @checked_collection
    def update(
        self,
        codes: list[str] | None = None,
        concurrency: int | None = None,
        force_current_day: bool = False,
        ctx=None,
    ) -> dict:
        """增量更新：每只股票从已入库最新日 +1 起补到今天。

        concurrency（T-M7-7）：>1 时用线程池并发拉取，**每线程独立 DataSource（限流按实际来源共享，
        请求起始频率按实际来源共享限流）**；写入经 DuckDB 单写锁串行，数据零影响。默认读配置
        `datasource.update_concurrency`。并发仅覆盖网络等待，不放大来源请求频率。

        ctx（M2.8-B，可选 TaskContext）：传入则逐股写实时日志 + 进度 + checkpoint（FR-DM-9/10）。
        续跑天然幂等：从各股已入库最新日 +1 起，重复跑只补缺口。
        """
        end = eod_dates.shanghai_now().date()
        explicit_concurrency = concurrency is not None
        concurrency = concurrency or self.s.datasource.update_concurrency
        if getattr(ctx, "request_tracker", None):
            from backend.config.request_snapshot import request_settings_status
            status = request_settings_status()
            ctx.request_tracker.meta.update(
                work_concurrency=concurrency,
                default_concurrency=self.s.datasource.update_concurrency,
                concurrency_origin=ctx.request_tracker.meta.get("concurrency_origin", "task" if explicit_concurrency else "default"),
                policy_version=status["version"], policy_degraded=status["degraded"],
            )
        basic = self._stock_basic_from_db(codes, as_of=end)["code"].tolist()
        # 续跑（FR-DM-10）：串行老任务按 done 兼容跳过；并发任务按 done_codes 精确跳过。
        checkpoint = ctx.checkpoint if (ctx and ctx.checkpoint) else {}
        has_exact_done_codes = "done_codes" in checkpoint
        done_codes = set(checkpoint.get("done_codes") or [])
        # 新版 checkpoint 即使成功集合为空也会显式写 done_codes=[]，不得回退
        # 到旧版位置 done；只有真正没有该字段的历史 checkpoint 才按前 N 只兼容。
        skip_done = 0 if has_exact_done_codes else int(checkpoint.get("done", 0))
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
            eod_dates.cap_end(pinned_end, strict=True)
            end = pinned_end
            if ctx:
                ctx.log(f"续跑：沿用本次任务目标日 {end}，跳过日历/指数前置（已于首跑完成且幂等入库）")
        else:
            self.ingest_calendar(end - timedelta(days=30), end, ctx=ctx)  # 先补日历（判交易日要用）
            end = self._resolve_update_end(
                end, basic, codes, ctx=ctx, force_current_day=force_current_day,
            )
        # 就绪门可能回退日期，续跑也可能沿用旧目标日；以最终目标重取点时名册。
        # 已登记未来退市日的停牌股票仍需每日同步 ST，不能按 delist_date 非空提前排除。
        basic = self._stock_basic_from_db(codes, as_of=end)["code"].tolist()
        include_collection_scope(self, "stock", basic)
        n_total = len(basic)
        completed_codes = (set(done_codes) | set(basic[:skip_done])) & set(basic)
        resumed_count = len(completed_codes)
        pending = [code for code in basic if code not in completed_codes]
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

        def _tick(a: int, code: str, rows: int, *, in_flight: int = 0) -> None:
            if ctx:
                ctx.set_phase("daily_bar", done=len(completed_codes), total=n_total, phase_total=n_total,
                              phase_done=a, current_item=code, done_codes=sorted(completed_codes))
            if a % 20 == 0 or a == n_total:
                log.info("增量进度 %d/%d（成功%d 失败%d，累计%d行，最近 %s +%d）",
                         a, n_total, ok, fail, total_rows, code, rows)
            if ctx and (a % 20 == 0 or a == n_total):
                prefix = "并发增量" if concurrency > 1 else "增量更新"
                in_flight_note = f"，未完成工作单元{in_flight}" if concurrency > 1 else ""
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
                    _tick(a, code, 0)
                    if ctx:
                        ctx.log(f"[{a}/{n_total}] {code} 增量更新失败（补到 {end}，主源+兜底源均未取到）: {e}", "error")
                    self.repo.log_update("daily_bar", self.src.name, None, end, 0, "failed", f"{code}: {e}")
        else:  # 并发：线程局部 DataSource（限流按实际来源共享），写入由 DuckDB RLock 串行
            # 只加载每股最新日期，不在每个工作线程重复查行情库。工作线程只取源，
            # 已有ST事实预读、清洗、参考价校准和落库由编排线程按原业务契约处理；
            # 缺失ST原始材料在工作线程取源，会话仍共享串行锁。
            dates = self.c.query_df(
                "SELECT code,max(trade_date) d FROM daily_bar "
                "WHERE code IN (SELECT unnest(?::VARCHAR[])) GROUP BY code", [pending]
            )
            last_dates = {row.code: pd.Timestamp(row.d).date() for row in dates.itertuples()}
            starts = {code: (last_dates[code] + timedelta(days=1) if code in last_dates
                            else years_before(end, self.s.datasource.history_years)) for code in pending}

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
                    _tick(a, code, 0, in_flight=in_flight)

            self._run_daily_parallel(
                pending, starts, end, concurrency=concurrency, ctx=ctx,
                label="并发增量", on_complete=_complete,
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
                    ctx.set_phase("gap_reconcile", phase_total=gtotal, phase_done=gi - 1,
                                  current_item=gcode)
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
                if ctx:
                    ctx.set_phase("gap_reconcile", phase_total=gtotal, phase_done=gi,
                                  current_item=gcode)
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

        updated.update(self._dirty_daily_codes(basic))
        if updated:
            if ctx:
                ctx.log(f"↻ 增量刷新干净复权因子（{len(updated)} 只有新行）…")
            self._refresh_clean_factors(sorted(updated), ctx=ctx)
        result = {"end": end.isoformat(), "target": n, "ok": ok, "fail": fail,
                  "rows": total_rows, "concurrency": concurrency,
                  "reconcile": recon}
        # 四字段补采独立容错，保留行情成果；失败须进入子阶段汇总，不能把行情成功当全部成功。
        # 最新日期优先补齐；历史中间缺口由后续有界轮询处理，也可显式全量补采。
        try:
            if ctx:
                ctx.log("↻ 补市值估值（total_mv）：优先补最新交易日，随后分批复查历史…")
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
                result["valuation_latest_error"] = str(se)
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
                        f"（随后按配置轮询历史缺口）")
        except TaskCancelled:  # 终止穿透：补市值阶段被终止应转可续跑中断，而非记为失败后跑完
            raise
        except Exception as e:  # noqa: BLE001  市值源异常不影响行情更新结果
            log.warning("补市值估值失败（不影响行情更新）: %s", e)
            result["valuation_error"] = str(e)
            if ctx:
                ctx.log(f"补市值估值失败（不影响行情更新）：{e}", "warn")
        try:
            result["capital_review"] = self.review_capital_history(codes=codes, ctx=ctx, concurrency=concurrency)
        except TaskCancelled:
            raise
        except Exception as error:  # noqa: BLE001 - 保留行情成果，但明确报告历史复查失败
            result["capital_review_error"] = str(error)
            if ctx:
                ctx.log(f"历史股本轮询失败，后续任务重试：{error}", "warn")
        from backend.services.capital_quality import CapitalQualityService
        result["capital_quality"] = CapitalQualityService(self.c).sync(codes)
        if ctx:
            ctx.log(f"■ 增量更新完成：成功 {ok}、失败 {fail}，共写入 {total_rows} 行（{n} 只）")
            ctx.log("说明：最新日四字段已补采，历史缺口及股本/市值不一致按配置分批轮询；"
                    "仍缺的原因保存在 capital_review，需即时全量复查可运行逐日股本补采。")
        if codes is None:
            result["market_day_terminal"] = self._log_market_day_terminal(
                end,
                expected=n_total,
                successful=len(completed_codes),
                failed=fail,
                run_id=str(getattr(ctx, "tid", None) or f"manual-update-{end.isoformat()}"),
            )
        stage_failures = {}
        for key in ("valuation_latest_error", "valuation_error", "capital_review_error"):
            if result.get(key):
                stage_failures[key] = result[key]
        valuation = result.get("valuation", {})
        for name, stage in (("valuation", valuation), ("valuation_latest", valuation.get("latest", {})),
                            ("capital_review", result.get("capital_review", {}))):
            if stage.get("fail"):
                stage_failures[name] = {"failed": int(stage["fail"])}
        result["stage_failures"] = stage_failures
        if stage_failures and ctx:
            ctx.log(f"增量更新部分完成，失败子阶段：{'、'.join(stage_failures)}；后续可重试", "warn")
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
                       through: date | None = None, full_history: bool = False) -> dict:
        """收口单只股票窗口内的覆盖缺口（增量更新与质量修复-补采共用，统一口径）。

        重采后仍缺的日期必须取得逐日 trade_status=0 证据才确认停牌。
        full_history 使用全历史应有日期；through 限定本轮目标日，防止跨日扩大范围。
        """
        from backend.services.data_report import DataIntegrityReport
        from backend.services.history_quality import HistoryQualityService
        rep = DataIntegrityReport(getattr(self, "c", None))
        def missing():
            return (HistoryQualityService(rep.c).dates(code) if full_history
                    else rep.missing_days_for(code))
        miss = missing()
        if through is not None:
            miss = [d for d in miss if d <= through]
        if not miss:
            return {"miss": [], "backfilled": [], "confirmed": 0, "rows": 0}
        lo, hi = min(miss), max(miss)
        status_checked = False
        stage_errors = {}
        # 历史缺口常是未归档的真实停牌。先查窄字段状态，避免为确认停牌重拉十年 OHLC。
        if confirm and full_history:
            try:
                self._confirm_gap_suspensions(code, miss, rep, ctx=ctx)
                status_checked = True
            except TaskCancelled:
                raise
            except DataSourceError as exc:
                status_checked = True  # 本轮不重复等待同一故障状态源，行情渠道继续。
                stage_errors["suspension"] = str(exc)
                if ctx:
                    ctx.log(f"{code} 停牌状态核验失败，继续补行情：{exc}", "warn")
        pending = missing()
        if through is not None:
            pending = [d for d in pending if d <= through]
        rows = 0
        if pending:
            if ctx:
                ctx.check_cancel()
                ctx.log(f"缺口收口：重采 {code} {min(pending)}~{max(pending)}（{len(pending)} 个待补开市日）")
            try:
                rows = self.ingest_one_daily(code, min(pending), max(pending), ctx=ctx, **({"status_unavailable": True} if "suspension" in stage_errors else {}))
            except DataSourceError as exc:
                if not confirm:
                    raise
                if ctx:
                    ctx.log(f"{code} 主源补采未完成：{exc}", "warn")
            still = missing()
            if through is not None:
                still = [d for d in still if d <= through]
            if full_history and still and "suspension" not in stage_errors:
                if ctx:
                    ctx.check_cancel()
                try:
                    rows += self.ingest_one_daily(code, min(still), max(still), source=self._bao_source(), ctx=ctx)
                except DataSourceError as exc:
                    if ctx:
                        ctx.log(f"备用源历史补采未完成：{exc}", "warn")
            still = missing()
            if through is not None:
                still = [d for d in still if d <= through]
            if confirm and still and not status_checked:
                try:
                    self._confirm_gap_suspensions(code, still, rep, ctx=ctx)
                except DataSourceError as exc:
                    stage_errors["suspension"] = str(exc)
        # 补回数 = miss 中重采后"确实已有行情"的日期（按 daily_bar 实判）。不能用 miss−still：次新股
        # 首次入库会令窗口起点 lo 随新 min_bar 前移，把上市前的"伪缺口"误算成补回（虚报如 90 实补 5）。
        have_after = {pd.Timestamp(d).date() for d in rep.c.query_df(
            "SELECT trade_date FROM daily_bar WHERE code=? AND trade_date BETWEEN ? AND ?",
            [code, lo, hi])["trade_date"]}
        backfilled = [d for d in miss if d in have_after]
        # ingest_one_daily 也可能凭权威状态直接确认停牌，不能漏计成“仍无数据”。
        suspension_after = {pd.Timestamp(day).date() for day in rep.c.query_df(
            "SELECT trade_date FROM stock_suspension WHERE code=? AND trade_date BETWEEN ? AND ?",
            [code, lo, hi])["trade_date"]}
        confirmed = len(set(miss) & suspension_after)
        # 收口补市值（DM 口径统一）：补回了行情的天 total_mv 仍空，而 mv_missing 是整股粒度测不出、
        # ingest_valuation 又整股跳过已有 total_mv 的票 → 这些天会永久缺市值。故对实际补回的股顺带补
        # 一次估值（仅这只股 + 补回区间），一步到位。失败不影响补回主结果。
        if backfilled:
            factors = self._recompute_clean([code], ctx=ctx)
            if factors["fail"]:
                raise RuntimeError(f"{code} 补回行情后复权因子重算失败")
            try:
                with thread_cancel_scope(ctx.check_cancel if ctx else None):
                    self._collect_capital_one(code, self._source_for("valuation"),
                                              min(backfilled), max(backfilled))
            except TaskCancelled:
                raise
            except Exception as e:  # noqa: BLE001
                stage_errors["capital"] = str(e)
                log.warning("%s 收口补市值失败(不影响补回): %s", code, e)
                if ctx:
                    ctx.log(f"{code} 行情已补回，股本市值补采失败：{e}", "warn")
            from backend.services.capital_quality import CapitalQualityService
            CapitalQualityService(rep.c).sync([code])
        return {"miss": miss, "backfilled": backfilled, "confirmed": confirmed, "rows": rows,
                "stage_errors": stage_errors}

    def _confirm_gap_suspensions(self, code, dates, report, *, ctx=None):
        """只确认缺口日期上的一致停牌证据；空值、未知、相反重复记录均不算证据。"""
        if not dates:
            return 0
        if ctx:
            ctx.check_cancel()
        source, rows = self._fetch_st_status_rows(code, min(dates), max(dates), ctx=ctx)
        return self._persist_gap_status(code, source, rows, dates, report, ctx=ctx)

    def _persist_gap_status(self, code, source, rows, dates, report, *, ctx=None):
        """保存可核验停牌：仅开市、存续期且未存行情的候选日，附明确逐日来源留痕。"""
        if rows is None or rows.empty or not dates or "trade_status" not in rows.columns:
            return 0
        checked = rows.assign(
            _day=pd.to_datetime(rows.trade_date, errors="coerce").dt.date,
            _stopped=pd.to_numeric(rows.trade_status, errors="coerce").eq(0).fillna(False),
        )
        trading = checked.groupby("_day")["trade_status"].apply(
            lambda values: pd.to_numeric(values, errors="coerce").eq(1).all())
        resumed = list(trading[trading].index)
        if resumed:
            old = report.c.query_df("SELECT trade_date FROM stock_suspension WHERE code=? AND trade_date IN (SELECT unnest(?::DATE[]))", [code, resumed])
            if not old.empty:
                with report.c.transaction():
                    report.c.execute("DELETE FROM stock_suspension WHERE code=? AND trade_date IN (SELECT unnest(?::DATE[]))", [code, resumed])
                    MarketRepository(report.c).log_update("stock_suspension", f"{getattr(source, 'name', source)}:trade_status=1", min(resumed), max(resumed), len(old), "success", json.dumps({"action":"revoke", "code":code,"trade_dates":old.trade_date.astype(str).tolist(),"task_id":getattr(ctx,"tid",None)}))
        by_day = checked.groupby("_day")._stopped.all()
        stopped = sorted(set(dates) & set(by_day[by_day].index))
        if not stopped:
            return 0
        eligible = report.c.query_df(
            "SELECT cal.trade_date FROM trade_calendar cal JOIN stock_basic s ON s.code=? "
            "WHERE cal.is_open AND cal.trade_date IN (SELECT unnest(?::DATE[])) "
            "AND (s.list_date IS NULL OR cal.trade_date>=s.list_date) "
            "AND (s.delist_date IS NULL OR cal.trade_date<s.delist_date) "
            "AND NOT EXISTS (SELECT 1 FROM daily_bar b WHERE b.code=s.code AND b.trade_date=cal.trade_date)",
            [code, stopped],
        )
        stopped = sorted(pd.to_datetime(eligible.trade_date).dt.date)
        if not stopped:
            return 0
        if ctx:
            ctx.check_cancel()
        with report.c.transaction():
            count = report.confirm_suspension(code, stopped)
            report.c.execute("UPDATE stock_suspension SET source=?,task_id=?,confirmed_at=current_timestamp WHERE code=? AND trade_date IN (SELECT unnest(?::DATE[]))",
                             [f"{getattr(source, 'name', source)}:trade_status=0", getattr(ctx, "tid", None), code, stopped])
            if count:
                MarketRepository(report.c).log_update(
                    "stock_suspension", f"{getattr(source, 'name', source)}:trade_status=0",
                    min(stopped), max(stopped), count, "success",
                    json.dumps({"code": code, "trade_dates": list(map(str, stopped)),
                                "task_id": getattr(ctx, "tid", None)}, ensure_ascii=False),
                )
        if ctx and count:
            ctx.log(f"{code} 已确认停牌 {count} 天（{getattr(source, 'name', source)} 逐日 trade_status=0）")
        return count

    def review_suspensions(self, codes=None, ctx=None, purge_candidates=False):
        """正式修复任务复核旧停牌与零量候选；未返回证据保留并报告，不推测。"""
        from backend.services.data_report import DataIntegrityReport
        from backend.services.history_quality import HistoryQualityService

        report = DataIntegrityReport(self.c)
        # 将既有明确证据日志迁入事实表；只接受逐日日期明细，不能用日志日期范围推断。
        proofs = self.c.query_df(
            "SELECT source,detail FROM data_update_log WHERE table_name='stock_suspension' AND source LIKE '%:trade_status=0'"
        )
        for proof in proofs.itertuples():
            try:
                detail = json.loads(proof.detail)
                days = [date.fromisoformat(d) for d in detail.get("trade_dates", [])]
                if days:
                    self.c.execute(
                        "UPDATE stock_suspension SET source=?,task_id=? WHERE source IS NULL AND code=? AND trade_date IN (SELECT unnest(?::DATE[]))",
                        [proof.source, detail.get("task_id"), detail.get("code"), days],
                    )
            except (ValueError, TypeError):
                continue
        # 退市日已不属于存续期，不能继续当停牌；边界校验不依赖网络。
        invalid = self.c.query_df(
            "SELECT s.*,b.list_date,b.delist_date,t.is_open FROM stock_suspension s "
            "LEFT JOIN stock_basic b USING(code) LEFT JOIN trade_calendar t USING(trade_date) "
            "WHERE (s.trade_date<b.list_date OR s.trade_date>=b.delist_date OR t.is_open=false)"
            + (" AND s.code IN (SELECT unnest(?::VARCHAR[]))" if codes is not None else ""),
            [codes] if codes is not None else [],
        )
        if not invalid.empty:
            with self.c.transaction():
                self.repo.log_update(
                    "stock_suspension",
                    "review:outside_lifetime",
                    None,
                    None,
                    len(invalid),
                    "success",
                    json.dumps(
                        {
                            "task_id": getattr(ctx, "tid", None),
                            "records": json.loads(
                                invalid.to_json(orient="records", date_format="iso")
                            ),
                        }
                    ),
                )
                with self.c.temp_view(invalid, "invalid_suspension") as view:
                    self.c.execute(
                        f"DELETE FROM stock_suspension s USING {view} v WHERE s.code=v.code AND s.trade_date=v.trade_date"
                    )
            if ctx:
                ctx.log(f"已撤销 {len(invalid)} 条非开市/上市存续期外停牌记录（已留存原记录）")
        sql = "SELECT code,trade_date FROM stock_suspension WHERE source IS NULL"
        if purge_candidates:
            sql += " UNION SELECT code,trade_date FROM daily_bar WHERE volume=0 OR volume IS NULL"
        targets = self.c.query_df(sql)
        if codes is not None:
            targets = targets[targets.code.isin(codes)]
        result = {
            "confirmed": 0,
            "revoked": len(invalid),
            "purged": 0,
            "unverified": 0,
            "errors": {},
        }
        groups = list(targets.groupby("code"))
        consecutive_source_errors = 0
        for i, (code, group) in enumerate(groups):
            if ctx:
                ctx.check_cancel()
                ctx.progress(i / max(1, len(groups)), f"复查停牌 {code} ({i + 1}/{len(groups)})")
            days = sorted(pd.to_datetime(group.trade_date).dt.date)
            try:
                source, rows = self._fetch_st_status_rows(code, min(days), max(days), ctx=ctx)
                consecutive_source_errors = 0
                states = {}
                if rows is not None and not rows.empty and "trade_status" in rows:
                    for day, items in rows.groupby(pd.to_datetime(rows.trade_date).dt.date):
                        values = pd.to_numeric(items.trade_status, errors="coerce")
                        if values.eq(0).all():
                            states[day] = 0
                        elif values.eq(1).all():
                            states[day] = 1
                stopped = [d for d in days if states.get(d) == 0]
                traded = [d for d in days if states.get(d) == 1]
                with self.c.transaction():
                    if traded:
                        old = self.c.query_df(
                            "SELECT * FROM stock_suspension WHERE code=? AND trade_date IN (SELECT unnest(?::DATE[]))",
                            [code, traded],
                        )
                        self.c.execute(
                            "DELETE FROM stock_suspension WHERE code=? AND trade_date IN (SELECT unnest(?::DATE[]))",
                            [code, traded],
                        )
                        result["revoked"] += len(old)
                        if not old.empty:
                            self.repo.log_update(
                                "stock_suspension",
                                "review:trading",
                                min(traded),
                                max(traded),
                                len(old),
                                "success",
                                old.to_json(orient="records", date_format="iso"),
                            )
                    if stopped:
                        # 正成交与停牌响应冲突，不删行情；仅清理已核实的零量占位行。
                        bad = self.c.query_df(
                            "SELECT * FROM daily_bar WHERE code=? AND trade_date IN (SELECT unnest(?::DATE[])) AND (volume=0 OR volume IS NULL) AND coalesce(amount,0)=0",
                            [code, stopped],
                        )
                        if not bad.empty:
                            # 删除前完整保存行情与市值，便于按任务恢复。
                            metrics = self.c.query_df(
                                "SELECT * FROM daily_metrics WHERE code=? AND trade_date IN (SELECT unnest(?::DATE[]))",
                                [code, bad.trade_date.tolist()],
                            )
                            self.repo.log_update(
                                "daily_bar",
                                "review:suspension_backup",
                                min(stopped),
                                max(stopped),
                                len(bad),
                                "success",
                                json.dumps(
                                    {
                                        "bars": json.loads(
                                            bad.to_json(orient="records", date_format="iso")
                                        ),
                                        "metrics": json.loads(
                                            metrics.to_json(orient="records", date_format="iso")
                                        ),
                                        "task_id": getattr(ctx, "tid", None),
                                    }
                                ),
                            )
                            for table in ("daily_metrics", "daily_bar"):
                                self.c.execute(
                                    f"DELETE FROM {table} WHERE code=? AND trade_date IN (SELECT unnest(?::DATE[]))",
                                    [code, bad.trade_date.tolist()],
                                )
                            result["purged"] += len(bad)
                if stopped:
                    self._persist_gap_status(code, source, rows, stopped, report, ctx=ctx)
                    verified = (
                        self.c.query_df(
                            "SELECT count(*) n FROM stock_suspension WHERE code=? AND trade_date IN (SELECT unnest(?::DATE[])) AND source IS NOT NULL",
                            [code, stopped],
                        )
                        .iloc[0]
                        .n
                    )
                    result["confirmed"] += int(verified)
                    result["unverified"] += len(stopped) - int(verified)
                result["unverified"] += len(days) - len(stopped) - len(traded)
                if traded:
                    self.reconcile_gaps(code, ctx=ctx, full_history=True)
                if stopped and not bad.empty:
                    self._recompute_clean([code], ctx=ctx)
                HistoryQualityService(self.c).sync([code])
            except TaskCancelled:
                raise
            except Exception as exc:
                result["errors"][code] = str(exc)
                result["unverified"] += len(days)
                if ctx:
                    ctx.log(f"{code} 停牌复查失败，保留原记录待重试：{exc}", "warn")
                if isinstance(exc, DataSourceError):
                    consecutive_source_errors += 1
                    if consecutive_source_errors >= 3:
                        remaining = groups[i + 1 :]
                        result["unverified"] += sum(len(frame) for _, frame in remaining)
                        result["deferred_codes"] = [name for name, _ in remaining]
                        if ctx:
                            ctx.log("状态来源连续失败 3 次，本轮停止请求，剩余股票留待重试", "warn")
                        break
        result["ok"] = not result["errors"] and result["unverified"] == 0
        result["message"] = (
            f"停牌复查：确认 {result['confirmed']}，撤销 {result['revoked']}，清理占位 {result['purged']}，待核验 {result['unverified']}"
        )
        return result

    def _invalid_valuation_dates(self, code: str, window_days: int | None = 90) -> set[date]:
        """按统一市值契约返回指定股票的异常日期。

        ``window_days=None`` 表示覆盖库内全历史。
        """
        inverted = mv_inverted_sql("m.total_mv", "m.float_mv")
        window_sql = ""
        params: list = [code]
        if window_days is not None:
            window_sql = """
              AND b.trade_date >= (
                  SELECT min(trade_date) FROM (
                      SELECT trade_date FROM trade_calendar
                      WHERE is_open AND trade_date <= (SELECT max(trade_date) FROM daily_bar)
                      ORDER BY trade_date DESC LIMIT ?))
            """
            params.append(int(window_days))
        invalid = self.repo.c.query_df(
            f"""
            SELECT b.trade_date
            FROM daily_bar b
            JOIN stock_basic sb ON sb.code = b.code
            JOIN daily_metrics m ON m.code = b.code AND m.trade_date = b.trade_date
            WHERE b.code = ? AND (sb.delist_date IS NULL OR sb.delist_date>
                (SELECT COALESCE(max(trade_date),current_date) FROM daily_bar))
              AND (m.total_mv <= 0 OR m.float_mv <= 0 OR {inverted})
              {window_sql}
            ORDER BY b.trade_date
            """,
            params,
        )
        return {
            pd.Timestamp(value).date()
            for value in invalid["trade_date"].tolist()
        }

    def repair_invalid_valuation(self, code: str, window_days: int | None = 90,
                                 ctx=None) -> dict:
        """重拉并强制覆盖已确认非法的市值行。

        正常链路同样统一重算业务市值，接口原值独立留存。
        """
        dates = self._invalid_valuation_dates(code, window_days)
        if not dates:
            return {"target_days": 0, "total_mv_rows": 0}
        if ctx:
            ctx.log(f"刷新 {code} 非法市值 {len(dates)} 天：{min(dates)}~{max(dates)}")
        rows = self._collect_capital_one(
            code,
            self._source_for("valuation"),
            min(dates),
            max(dates),
            overwrite_dates=dates,
        )
        return {"target_days": len(dates), "total_mv_rows": rows}

    @checked_collection
    def repair_invalid_valuation_history(self, codes: list[str] | None = None,
                                         concurrency: int | None = None, ctx=None) -> dict:
        """按结构体检口径修复全历史非法市值，并逐股复检形成闭环。"""
        inverted = mv_inverted_sql("m.total_mv", "m.float_mv")
        invalid = self.repo.c.query_df(
            f"""
            SELECT m.code, m.trade_date
            FROM daily_metrics m
            JOIN stock_basic sb ON sb.code = m.code
            WHERE (sb.delist_date IS NULL OR sb.delist_date>
                (SELECT COALESCE(max(trade_date),current_date) FROM daily_bar))
              AND (m.total_mv <= 0 OR m.float_mv <= 0 OR {inverted})
            ORDER BY m.code, m.trade_date
            """
        )
        if codes:
            invalid = invalid[invalid["code"].isin(set(codes))]
        target_map = {
            str(code): {pd.Timestamp(value).date() for value in rows["trade_date"].tolist()}
            for code, rows in invalid.groupby("code")
        }
        include_collection_scope(self, "stock", codes if codes is not None else self.c.query_df(
            "SELECT code FROM stock_basic WHERE delist_date IS NULL OR delist_date>"
            "(SELECT COALESCE(max(trade_date),current_date) FROM daily_bar)"
        )["code"].tolist())
        target_days = sum(len(dates) for dates in target_map.values())
        done_codes = set(
            ctx.checkpoint.get("valuation_invalid_done_codes") or []
        ) if (ctx and ctx.checkpoint) else set()
        pending = [
            (code, dates) for code, dates in target_map.items()
            if code not in done_codes
        ]
        concurrency = (
            concurrency
            if concurrency is not None
            else self.s.datasource.update_concurrency
        )
        n = len(pending)
        ok = fail = rows = 0
        log.info("全历史异常市值修复开始：%d 只，%d 个交易日", n, target_days)
        if ctx:
            ctx.set_phase(
                "valuation_invalid_history", phase_total=n, phase_done=0,
                current_item=None,
                valuation_invalid_done_codes=sorted(done_codes),
            )
            ctx.log(
                f"子任务：全历史异常市值修复开始，"
                f"待修 {n} 只、{target_days} 个交易日"
            )
            ctx.flush()

        def _one(item, source) -> int:
            code, dates = item
            written = self._collect_capital_one(
                code, source, min(dates), max(dates), overwrite_dates=dates)
            remaining = self._invalid_valuation_dates(code, window_days=None)
            if remaining:
                raise RuntimeError(
                    f"源端返回后仍有 {len(remaining)} 个异常日期"
                    f"（{min(remaining)}~{max(remaining)}）"
                )
            return written

        def _complete(i, item, value, error, _in_flight):
            nonlocal rows, ok, fail
            code, dates = item
            if ctx:
                ctx.set_phase(
                    "valuation_invalid_history", phase_total=n, phase_done=i - 1,
                    current_item=code,
                    valuation_invalid_done_codes=sorted(done_codes),
                )
            if error is None:
                rows += value
                ok += 1
                done_codes.add(code)
            else:
                fail += 1
                log.warning("%s 全历史异常市值修复失败: %s", code, error)
                if ctx:
                    ctx.log(
                        f"{code} 全历史异常市值修复失败"
                        f"（{min(dates)}~{max(dates)}）：{error}",
                        "warn",
                    )
            if ctx:
                ctx.set_phase("valuation_invalid_history", phase_total=n, phase_done=i,
                              current_item=code, valuation_invalid_done_codes=sorted(done_codes))
            if i % 20 == 0 or i == n:
                log.info(
                    "全历史异常市值修复进度 %d/%d（成功%d 失败%d，写入 %d行）",
                    i, n, ok, fail, rows,
                )
                if ctx:
                    ctx.log(
                        f"全历史异常市值修复进度 {i}/{n}："
                        f"成功{ok} 失败{fail}，写入 {rows} 行"
                    )
                    ctx.flush()

        val_src = self._source_for("valuation")
        if concurrency <= 1:
            for i, item in enumerate(pending, 1):
                if ctx:
                    ctx.check_cancel()
                try:
                    value = _one(item, val_src)
                    _complete(i, item, value, None, 0)
                except Exception as error:  # noqa: BLE001
                    _complete(i, item, 0, error, 0)
        else:
            tls = threading.local()
            source_name = val_src.name

            def _worker(item) -> int:
                return self._fetch_capital_material(item[0], self._thread_source(tls, source_name), min(item[1]), max(item[1]))

            self._run_bounded_parallel(
                pending, _worker, concurrency=concurrency, ctx=ctx,
                wait_label="全历史异常市值修复", on_complete=_complete,
                transform_batch=lambda entries: self._complete_capital_material(entries, val_src, _one),
            )

        remaining_by_code = {
            code: self._invalid_valuation_dates(code, window_days=None)
            for code in target_map
        }
        remaining_by_code = {
            code: dates for code, dates in remaining_by_code.items() if dates
        }
        remaining = sum(len(dates) for dates in remaining_by_code.values())
        # checkpoint 只跳过本轮已确认干净的股票，最终状态仍以实时复检为准。
        # 即使断点数据与当前库状态偏离，也不能把仍有异常的任务虚报为成功。
        fail = max(fail, len(remaining_by_code))
        result = {
            "target": n,
            "target_days": target_days,
            "ok": ok,
            "fail": fail,
            "total_mv_rows": rows,
            "remaining_rows": remaining,
        }
        log.info("全历史异常市值修复完成: %s", result)
        if ctx:
            ctx.log(
                f"子任务：全历史异常市值修复完成，成功{ok} 失败{fail}，"
                f"写入 {rows} 行，剩余异常 {remaining} 行"
            )
        return result

    @checked_collection
    def review_capital_history(self, codes=None, ctx=None, concurrency=None):
        """日常更新后的有界历史复查；失败可重试，无证据记录不挤占后续股票。"""
        from backend.services.share_capital import ShareCapitalService

        batch = self.s.datasource.capital_review_batch_size
        if not batch:
            return {"target": 0, "ok": 0, "fail": 0, "disabled": True}
        # 子阶段不改写日常任务已冻结的交易窗口或全量股本任务的检查点。
        checkpoint = getattr(ctx, "checkpoint", {}) or {}
        window = checkpoint.get("capital_review_window")
        if window:
            start, end = (date.fromisoformat(value) for value in window)
        elif checkpoint.get("target_end"):
            end = date.fromisoformat(checkpoint["target_end"])
            start = years_before(end, self.s.datasource.history_years)
        else:
            start, end = self._history_window(self.s.datasource.history_years, None)
        if ctx and not window:
            ctx.set_checkpoint(capital_review_window=[start.isoformat(), end.isoformat()])
        service = ShareCapitalService(self.c)
        targets = checkpoint.get("capital_review_targets")
        if targets is None:
            targets = service.review_candidates(
                start, end, codes=codes, limit=batch,
                interval_days=self.s.datasource.capital_review_interval_days,
            ).code.tolist()
            if ctx:
                ctx.set_checkpoint(capital_review_targets=targets)
        done = set(checkpoint.get("capital_review_done", []))
        diagnostics = dict(checkpoint.get("capital_review_diagnostics", {}))
        include_collection_scope(self, "stock", targets)
        pending = [code for code in targets if code not in done]
        result = {"target": len(targets), "ok": len(done), "fail": 0, "diagnostics": diagnostics}
        if ctx:
            ctx.set_phase("capital_review", phase_total=len(pending), phase_done=0,
                          current_item=None)
        tls = threading.local()
        source_name = self._source_for("share_capital").name

        def worker(code):
            source = self._thread_source(tls, source_name)
            return self._fetch_capital_material(code, source, start, end)

        def complete(i, code, value, error, _in_flight):
            detail = diagnostics.get(code, {})
            if error is not None:
                result["fail"] += 1
                detail = {**detail, "error": str(error)}
            else:
                result["ok"] += 1
                done.add(code)
            # checked 不计入行情版本；只有 merge 中的实际字段变化刷新版本。
            self.repo.log_update(
                "stock_share_capital_daily", f"capital_review:{code}", start, end,
                sum(item["count"] for item in detail.get("remaining", {}).values()),
                "failed" if error is not None else "checked",
                json.dumps(detail, ensure_ascii=False),
            )
            if ctx:
                ctx.set_phase("capital_review", phase_total=len(pending), phase_done=i,
                              current_item=code, capital_review_done=sorted(done),
                              capital_review_diagnostics=dict(diagnostics))
                ctx.log(f"历史股本轮询 {i}/{len(pending)}：{code}，" + ("失败待重试" if error else "已复查"))
                ctx.flush()

        self._run_bounded_parallel(
            pending, worker, concurrency=concurrency or self.s.datasource.update_concurrency, ctx=ctx,
            wait_label="历史股本轮询", on_complete=complete,
            transform_batch=lambda entries: self._complete_capital_material(
                entries, self._source_for("share_capital"),
                lambda code, source: self._collect_capital_one(
                    code, source, start, end, diagnostics=diagnostics)),
        )
        result["remaining_field_issues"] = sum(
            item["count"] for detail in diagnostics.values() for item in detail.get("remaining", {}).values()
        )
        return result

    def _collect_capital_one(self, code, source, start, end, diagnostics=None, overwrite_dates=None):
        """历史与日常共用：四字段独立补缺，源端失败不阻断其它源且保持可重试。"""
        from backend.services.share_capital import ShareCapitalService

        errors = []
        evidence = {}
        count = 0
        try:
            count = (self._valuation_one(code, source, start, end) if overwrite_dates is None else
                     self._valuation_one(code, source, start, end, overwrite_dates=overwrite_dates))
            evidence["eastmoney_daily"] = {"reported_mv_rows": count}
        except TaskCancelled:
            raise
        except Exception as exc:  # noqa: BLE001 - 后续来源继续，最后向任务报告失败
            errors.append(str(exc))
        service = ShareCapitalService(self.c)
        from backend.services.share_capital_history import ShareCapitalHistoryService
        history_service = ShareCapitalHistoryService(self.c)
        dates = self.c.query_df(
            "SELECT trade_date FROM daily_bar WHERE code=? AND trade_date BETWEEN ? AND ?",
            [code, start, end])["trade_date"]
        invalid_raw_sources = set(self.c.query_df(
            "SELECT DISTINCT source FROM stock_share_capital_event WHERE code=? AND active "
            "AND (effective_date IS NULL OR total_share<=0 OR float_share<0 OR float_share>total_share)",
            [code])["source"])
        if diagnostics is None and not errors and not invalid_raw_sources:
            remaining = self.c.query_df(
                "SELECT count(*) n FROM daily_bar b LEFT JOIN stock_share_capital_daily s USING(code,trade_date) "
                "LEFT JOIN daily_metrics m USING(code,trade_date) WHERE b.code=? AND b.trade_date BETWEEN ? AND ? "
                f"AND ({service.review_predicate()})",
                [code, start, end]).iloc[0, 0]
            if remaining == 0:
                history_service.rebuild(code)
                from backend.services.capital_quality import CapitalQualityService
                CapitalQualityService(self.c).sync([code])
                return count
        if diagnostics is None:
            diagnostics = {}
        facts = pd.DataFrame()
        get_events = getattr(source, "get_share_capital", None)
        if get_events is not None:
            try:
                source._last_share_events = None
                facts = get_events(code, dates)
                check_thread_cancel()
                service.merge(facts, "eastmoney_events")
                evidence["eastmoney_events"] = {"expanded_rows": len(facts),
                    "valid_total_rows": int(facts.total_share.notna().sum()) if not facts.empty else 0,
                    "valid_float_rows": int(facts.float_share.notna().sum()) if not facts.empty else 0}
            except TaskCancelled:
                raise
            except Exception as exc:  # noqa: BLE001 - 失败不冒充无数据
                errors.append(str(exc))
            finally:
                check_thread_cancel()
                raw_events = getattr(source, "_last_share_events", None)
                if raw_events is not None and raw_events[0] == code:
                    history_service.record_events(code, raw_events[1], "eastmoney_events")
        converted = pd.DataFrame()
        exchange = getattr(source, "get_exchange_share_capital", None)
        if exchange is not None:
            candidates = self.c.query_df(
                "SELECT b.trade_date FROM daily_bar b LEFT JOIN stock_share_capital_daily s USING(code,trade_date) "
                "LEFT JOIN daily_metrics m USING(code,trade_date) WHERE b.code=? AND b.trade_date BETWEEN ? AND ? "
                "AND (s.total_share IS NULL OR s.total_source IN ('eastmoney_events','sina_events') OR "
                "starts_with(s.total_source,'sse_conversion_100share:'))", [code,start,end])["trade_date"]
            if not candidates.empty:
                try:
                    converted = exchange(code, candidates)
                    check_thread_cancel()
                    service.merge(converted, "sse_conversion")
                    evidence["sse_conversion"] = getattr(source, "_exchange_share_evidence", {"expanded_rows":len(converted)})
                except TaskCancelled:
                    raise
                except Exception as exc:  # noqa: BLE001 - 请求失败仍须重试
                    errors.append(f"sse_conversion: {exc}")
        for method, source_label in [("get_share_capital_fallback", "sina_events"),
                                     ("get_float_share_history", "sina_daily")]:
            fetch = getattr(source, method, None)
            if fetch is None:
                continue
            condition = (service.review_predicate()
                         if source_label == "sina_events" else
                         "s.float_share IS NULL OR (s.float_source IN ('eastmoney_events','sina_events') AND "
                         f"(abs(m.float_mv-s.float_share*b.close)>greatest(abs(m.float_mv)*{MV_REL_TOLERANCE},1) "
                         f"OR abs(m.reported_float_mv-s.float_share*b.close)>greatest(abs(m.reported_float_mv)*{MV_REL_TOLERANCE},1)))")
            missing = self.c.query_df(
                "SELECT b.trade_date FROM daily_bar b LEFT JOIN stock_share_capital_daily s "
                "USING(code,trade_date) LEFT JOIN daily_metrics m USING(code,trade_date) "
                f"WHERE b.code=? AND b.trade_date BETWEEN ? AND ? AND ({condition})",
                [code, start, end])["trade_date"]
            # 原始源记录异常也必须重新请求，不能因逐日字段已被其它来源补齐而跳过修复。
            if missing.empty and source_label in invalid_raw_sources:
                missing = dates
            if missing.empty:
                continue
            try:
                if source_label == "sina_events":
                    source._last_fallback_share_events = None
                fallback = fetch(code, missing)
                check_thread_cancel()
                if source_label == "sina_events" and not facts.empty and not fallback.empty:
                    # 不能拿备用源的旧股本跨越主源已知的真实变动边界。
                    primary = facts.assign(trade_date=pd.to_datetime(facts.trade_date).dt.date).set_index("trade_date")
                    for field in ("total", "float"):
                        boundary = pd.to_datetime(fallback.trade_date).dt.date.map(primary[f"{field}_effective_date"])
                        stale = pd.to_datetime(fallback[f"{field}_effective_date"]) < pd.to_datetime(boundary)
                        fallback.loc[stale, f"{field}_share"] = None
                service.merge(fallback, source_label)
                evidence[source_label] = {"expanded_rows": len(fallback)}
            except TaskCancelled:
                raise
            except Exception as exc:  # noqa: BLE001 - 记录失败，允许后续源尝试
                errors.append(str(exc))
            finally:
                check_thread_cancel()
                raw_events = getattr(source, "_last_fallback_share_events", None)
                if source_label == "sina_events" and raw_events is not None and raw_events[0] == code:
                    history_service.record_events(code, raw_events[1], source_label)
        history_service.rebuild(code)
        evidence["daily_facts"] = {
            "daily_missing": self.c.query_df(
                "SELECT count(*) n FROM daily_bar b LEFT JOIN stock_share_capital_daily s USING(code,trade_date) "
                "WHERE b.code=? AND (s.total_share IS NULL OR s.float_share IS NULL)", [code]).iloc[0,0].item()}

        if diagnostics is not None:
            from backend.services.capital_quality import capital_predicates
            from backend.services.share_capital_history import historical_joins
            predicates = capital_predicates(historical=True, include_sources=True)
            gaps = self.c.query_df(
                "SELECT b.trade_date,b.close,s.total_share,s.float_share,m.total_mv,m.float_mv,"
                "m.reported_total_mv,m.reported_float_mv,m.reported_total_close,m.reported_float_close "
                "FROM (SELECT * FROM daily_bar WHERE code=? AND trade_date BETWEEN ? AND ?) b "
                + historical_joins() + "WHERE (" + " OR ".join(predicates.values()) + ")",
                [code, start, end])
            reasons = {}
            primary = facts.assign(trade_date=pd.to_datetime(facts.trade_date).dt.date).set_index("trade_date") if not facts.empty else None
            exchange_totals = (dict(zip(pd.to_datetime(converted.trade_date).dt.date,
                                       converted.total_share, strict=True)) if not converted.empty else {})
            price_code, prices = getattr(source, "_last_valuation_prices", (None, {}))
            if price_code != code:
                prices = {}
            for _, gap in gaps.sort_values("trade_date").iterrows():
                day = pd.Timestamp(gap.trade_date).date()
                for field in ("total", "float"):
                    if pd.isna(gap[f"{field}_share"]):
                        reason = f"{field}_share_source_unavailable"
                        if primary is not None and day in primary.index:
                            effective = primary.loc[day, f"{field}_effective_date"]
                            if pd.isna(effective):
                                reason = f"{field}_share_no_prior_record"
                            elif pd.isna(primary.loc[day,f"{field}_share"]):
                                reason = f"{field}_share_source_record_invalid"
                        exchange_total = exchange_totals.get(day)
                        conflict = (field == "total" and exchange_total is not None
                                    and pd.notna(gap.float_share) and exchange_total < gap.float_share)
                        if conflict:
                            reason = ("total_share_exchange_precision_conflict"
                                      if gap.float_share - exchange_total <= 50
                                      else "total_share_exchange_count_conflict")
                        group = reasons.setdefault(reason, {"count": 0, "samples": []})
                        group["count"] += 1
                        if len(group["samples"]) < 3:
                            group["samples"].append(str(day))
                            if conflict:
                                group.setdefault("exchange_evidence", []).append({
                                    "trade_date": str(day), "exchange_total": float(exchange_total),
                                    "stored_float": float(gap.float_share), "precision_shares": 100,
                                })
                            if primary is not None and day in primary.index:
                                group.setdefault("evidence", []).append({
                                    "trade_date": str(day),
                                    "effective_date": str(primary.loc[day, f"{field}_effective_date"]),
                                    "available_date": str(primary.loc[day, f"{field}_available_date"]),
                                })
                    elif pd.isna(gap[f"{field}_mv"]):
                        reason = f"{field}_mv_source_conflict"
                        group = reasons.setdefault(reason, {"count": 0, "samples": []})
                        group["count"] += 1
                        if len(group["samples"]) < 3:
                            group["samples"].append(str(day))
                    else:
                        business_mv = gap[f"{field}_mv"]
                        reported_mv = gap[f"reported_{field}_mv"]
                        mismatch_mv = next((mv for mv in (business_mv, reported_mv)
                            if pd.notna(mv) and abs(mv-gap[f"{field}_share"]*gap["close"])
                            > max(abs(mv)*MV_REL_TOLERANCE,1)), None)
                        if mismatch_mv is None:
                            continue
                        saved_price = gap[f"reported_{field}_close"]
                        source_price = saved_price if pd.notna(saved_price) else prices.get(day)
                        price_basis = (source_price is not None and pd.notna(source_price)
                                       and abs(mismatch_mv - gap[f"{field}_share"] * source_price)
                                       <= max(abs(mismatch_mv) * MV_REL_TOLERANCE, 1))
                        reason = f"{field}_mv_price_basis_mismatch" if price_basis else f"{field}_mv_share_mismatch"
                        group = reasons.setdefault(reason, {"count": 0, "samples": []})
                        group["count"] += 1
                        if len(group["samples"]) < 3:
                            group["samples"].append(str(day))
                            group.setdefault("evidence", []).append({
                                "trade_date": str(day), "raw_close": float(gap["close"]),
                                "valuation_close": float(source_price) if source_price is not None and pd.notna(source_price) else None,
                                "share": float(gap[f"{field}_share"]), "mv": float(mismatch_mv),
                                "business_mv": float(business_mv),
                                "reported_mv": float(reported_mv) if pd.notna(reported_mv) else None,
                            })
            from backend.services.capital_quality import capital_predicates
            invalid = self.c.query_df(
                "SELECT b.trade_date FROM (SELECT * FROM daily_bar WHERE code=? AND trade_date BETWEEN ? AND ?) b "
                + historical_joins() + f"WHERE ({predicates['capital_invalid']}) ORDER BY b.trade_date", [code,start,end])
            if not invalid.empty:
                reasons["capital_invalid"] = {"count": len(invalid),
                    "samples": [str(pd.Timestamp(day).date()) for day in invalid.trade_date.head(3)]}
            raw_invalid = self.c.query_df(
                "SELECT source,effective_date,total_share,float_share,count(*) OVER() records "
                "FROM stock_share_capital_event WHERE code=? AND active "
                "AND (effective_date IS NULL OR total_share<=0 OR float_share<0 OR float_share>total_share) "
                "ORDER BY effective_date NULLS FIRST LIMIT 3", [code])
            if not raw_invalid.empty:
                reasons["raw_record_invalid"] = {
                    "count": int(raw_invalid.iloc[0].records),
                    "evidence": json.loads(raw_invalid.to_json(orient="records",date_format="iso")),
                }
            diagnostics[code] = {"sources": evidence, "errors": errors, "remaining": reasons}
        # 诊断进入正式质量台账；失败也留下原因，绝不以请求成功代替复检。
        from backend.services.capital_quality import CapitalQualityService
        check_thread_cancel()
        MarketRepository(self.c).log_update(
            "stock_share_capital_daily", f"capital_collect:{code}", start, end,
            sum(item["count"] for item in diagnostics[code]["remaining"].values()),
            "failed" if errors else "checked", json.dumps(diagnostics[code], ensure_ascii=False),
        )
        CapitalQualityService(self.c).sync([code])
        if errors:
            raise DataSourceError("；".join(errors))
        return count

    def repair_capital_quality(self, code, ctx=None):
        """按已有完整历史走共同多源链路；全量含退市股，不把近端通过当历史已修复。"""
        span = self.c.query_df(
            "SELECT min(trade_date) lo,max(trade_date) hi FROM daily_bar WHERE code=?", [code]).iloc[0]
        if pd.isna(span.lo):
            return {"rows": 0}
        if ctx:
            ctx.check_cancel()
        diagnostics = {}
        rows = self._collect_capital_one(code, self._source_for("share_capital"),
                                        pd.Timestamp(span.lo).date(), pd.Timestamp(span.hi).date(), diagnostics)
        return {"rows": rows, "diagnostics": diagnostics}

    @checked_collection
    def ingest_share_capital(self, codes=None, years=None, concurrency=None, ctx=None):
        """按已有日线覆盖含退市股；不因已有市值跳过股本采集。"""
        start, end = self._history_window(years or self.s.datasource.history_years, ctx)
        stocks = self.c.query_df(
            "SELECT code FROM daily_bar WHERE trade_date BETWEEN ? AND ? GROUP BY code ORDER BY code",
            [start, end])["code"].tolist()
        if codes:
            stocks = [code for code in stocks if code in set(codes)]
        done = set((getattr(ctx, "checkpoint", {}) or {}).get("share_codes_done", []))
        # 旧版本检查点没有逐股证据，升级续跑需补做核验，避免把未诊断股票当作已闭环。
        done &= set((getattr(ctx, "checkpoint", {}) or {}).get("share_diagnostics", {}))
        include_collection_scope(self, "stock", stocks)
        pending = [code for code in stocks if code not in done]
        tls = threading.local()
        source_name = self._source_for("share_capital").name
        result = {"target": len(stocks), "ok": 0, "fail": 0, "valuation_empty": 0, "skip": len(stocks) - len(pending), "diagnostics": dict((getattr(ctx, "checkpoint", {}) or {}).get("share_diagnostics", {}))}

        def worker(code):
            source = self._thread_source(tls, source_name)
            return self._fetch_capital_material(code, source, start, end)

        def complete(i, code, value, error, _in_flight):
            detail = result["diagnostics"].get(code, {})
            self.repo.log_update(
                "stock_share_capital_daily", f"capital_review:{code}", start, end,
                sum(item["count"] for item in detail.get("remaining", {}).values()),
                "failed" if error is not None else "checked",
                json.dumps({**detail, **({"error": str(error)} if error else {})}, ensure_ascii=False),
            )
            if error is not None:
                result["fail"] += 1
                if ctx:
                    ctx.log(f"{code} 逐日股本失败: {error}", "warn")
            else:
                result["ok"] += 1
                result["valuation_empty"] += int(value == 0)
                done.add(code)
            if ctx:
                ctx.progress(0.08 + 0.9 * i / max(len(pending), 1), f"逐日股本 {i}/{len(pending)}")
                ctx.set_checkpoint(share_codes_done=sorted(done), share_diagnostics=dict(result["diagnostics"]))
                ctx.set_phase("share_capital_history", phase_total=len(pending), phase_done=i,
                              current_item=code)
                if i % 20 == 0 or i == len(pending):
                    ctx.log(f"逐日股本进度 {i}/{len(pending)}，成功 {result['ok']} 失败 {result['fail']}")
                    ctx.flush()

        self._run_bounded_parallel(pending, worker,
            concurrency=concurrency or self.s.datasource.update_concurrency, ctx=ctx,
            wait_label="逐日股本采集", on_complete=complete,
            transform_batch=lambda entries: self._complete_capital_material(
                entries, self._source_for("share_capital"),
                lambda code, source: self._collect_capital_one(
                    code, source, start, end, diagnostics=result["diagnostics"])))
        with self.c.temp_view(pd.DataFrame({"code": stocks}), prefix="share_targets") as target:
            coverage = self.c.query_df(
                "SELECT count(*) AS bar_rows,count(s.total_share) AS total_share_rows, "
                "count(s.float_share) AS float_share_rows,count(m.total_mv) AS total_mv_rows, "
                "count(m.float_mv) AS float_mv_rows FROM daily_bar b "
                f"JOIN {target} t USING(code) LEFT JOIN stock_share_capital_daily s USING(code,trade_date) "
                "LEFT JOIN daily_metrics m USING(code,trade_date) WHERE b.trade_date BETWEEN ? AND ?",
                [start, end]).iloc[0]
            result["coverage"] = {key: int(value) for key, value in coverage.items()}
            result["historical_coverage"] = dict(result["coverage"])
        return result

    def _valuation_one(self, code: str, source, start: date, end: date,
                       overwrite_dates: set[date] | None = None) -> int:
        """取单只 [start,end] 的源端估值和逐日股本，市值按同日股本与本地原价计算优先，接口值留存核验与兜底。
        质量修复仅处理 overwrite_dates；基础股本只投影最新行情日。返回总市值写入行数。
        供 ingest_valuation 全量补市值与 reconcile_gaps 收口补市值共用，口径一致。"""
        v = source.get_valuation(code, start, end)
        # 与行情入库保持同一安全边界：取消后不把刚返回的外部结果继续写入 DuckDB。
        check_thread_cancel()
        v = self._validated_valuation_frame(code, v, start, end)
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
        total_mv = pd.to_numeric(v["total_mv"], errors="coerce")
        float_mv = pd.to_numeric(v["float_mv"], errors="coerce")
        invalid = ((total_mv.notna() & (total_mv <= 0))
                   | (float_mv.notna() & (float_mv <= 0))
                   | (total_mv.notna() & float_mv.notna()
                      & (total_mv < float_mv * (1 - MV_REL_TOLERANCE))))
        if invalid.any():
            invalid_dates = sorted(str(pd.Timestamp(d).date()) for d in v.loc[invalid, "trade_date"])
            log.warning(
                "%s 估值源返回非法市值，已拒绝写入 %d 行：%s",
                code,
                len(invalid_dates),
                ",".join(invalid_dates[:10]),
            )
            v = v.copy()
            inverted = total_mv.notna() & float_mv.notna() & (
                total_mv < float_mv * (1 - MV_REL_TOLERANCE)
            )
            total_mv = total_mv.mask((total_mv <= 0) | inverted)
            float_mv = float_mv.mask((float_mv <= 0) | inverted)
        if v.empty:
            return 0
        v["total_mv"] = total_mv
        v["float_mv"] = float_mv

        from backend.services.share_capital import ShareCapitalService

        # 修复任务严格限于已确认异常日期，不扩散覆盖其它交易日。
        if overwrite_dates is not None:
            v = v[v["trade_date"].isin(overwrite_dates)]
        ShareCapitalService(self.c).merge(v, "eastmoney_daily", reported=True)
        added = int(v["total_mv"].notna().sum())
        return added

    @staticmethod
    def _validated_valuation_frame(code, frame, start, end):
        """逐股／批量共用响应边界；保留原始接口值，非法市值不得进入合并层。"""
        if frame is None or frame.empty:
            return pd.DataFrame()
        frame = frame.copy()
        if not frame["code"].eq(code).all():
            raise DataSourceError(f"{code} 估值响应标的不匹配")
        frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.date
        frame = frame[frame.trade_date.between(start, end)].copy()
        total = pd.to_numeric(frame["total_mv"], errors="coerce")
        floating = pd.to_numeric(frame["float_mv"], errors="coerce")
        inverted = total.notna() & floating.notna() & (total < floating * (1 - MV_REL_TOLERANCE))
        frame["total_mv"] = total.mask((total <= 0) | inverted)
        frame["float_mv"] = floating.mask((floating <= 0) | inverted)
        return frame

    # ── 指定日期采集（FR-DM-3 更多选项，M2.8-B）──
    @checked_collection
    def ingest_date(self, start: date, end: date, codes: list[str] | None = None, ctx=None,
                    concurrency: int | None = None) -> dict:
        """补指定日期（或区间）的行情。codes=None 表示全部在市股票。

        逐股拉取 [start, end] 区间并入库（沿用 ingest_one_daily 的清洗/标记/幂等 upsert）。
        返回受影响交易日列表供调用方标记评分快照失效。

        concurrency（与 update 同款）：>1 时用线程池并发拉取，每线程独立 DataSource
        （限流按实际来源共享，请求起始频率按实际来源共享限流），写入经 DuckDB 单写锁串行。
        默认 1（串行，最稳）。并发仅覆盖网络等待，不放大来源请求频率。
        """
        checkpoint = (getattr(ctx, 'checkpoint', {}) or {}) if ctx else {}
        if checkpoint.get('range_end'):
            if checkpoint.get('range_start') != start.isoformat():
                raise ValueError('续跑采集区间与原任务不一致')
            end = date.fromisoformat(checkpoint['range_end'])
            eod_dates.cap_end(end, strict=True)
        else:
            end = eod_dates.cap_range(start, end)
            if ctx:
                ctx.set_checkpoint(range_start=start.isoformat(), range_end=end.isoformat())
        live = self._stock_basic_from_db(codes, as_of=end)
        include_collection_scope(self, "stock", live["code"].tolist())
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

        def _one(
            code: str, source: DataSource | None = None, ctx_=None, *,
            prefetched=None, fetch_error=None,
        ) -> int:
            return self.ingest_one_daily(
                code, start, end, limit_lut.get(code), source=source, ctx=ctx_, _prefetched=prefetched, _fetch_error=fetch_error)

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
            if ctx:
                ctx.set_phase("daily_bar", phase_total=n, phase_done=i, current_item=code)

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
        else:  # 并发：线程局部 DataSource（限流按实际来源共享），写入由 DuckDB RLock 串行
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

            self._run_daily_parallel(
                target, {code: start for code in target}, end,
                concurrency=concurrency, ctx=ctx, label="指定日期采集",
                on_complete=_complete, limits=limit_lut,
            )
        updated.update(self._dirty_daily_codes(live["code"].tolist()))
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

    def refresh_price_references(self, codes, ctx=None):
        """定向重新获取独立参考价，不改原始行情；不允许隐式全市场联网。"""
        if not codes:
            raise ValueError("参考价复核必须明确指定股票范围")
        result = {"updated": 0, "unmatched": 0, "errors": {}}
        for code in codes:
            if ctx:
                ctx.check_cancel()
                ctx.log(f"{code} 重新获取来源参考价并核对同日收盘")
            local = self.c.query_df(
                "SELECT trade_date,close FROM daily_bar WHERE code=? ORDER BY trade_date", [code]
            )
            if local.empty:
                continue
            lo, hi = pd.to_datetime(local.trade_date).dt.date.iloc[[0, -1]]
            try:
                source = self._bao_source()
                with session_lock(_BAO_FALLBACK_LOCK, "baostock"):
                    reference = source.get_daily_bar(code, lo, hi)
                if reference is None or reference.empty:
                    raise DataSourceError("参考价来源为空")
                reference = reference[["trade_date", "pre_close", "close"]].copy()
                reference.trade_date = pd.to_datetime(reference.trade_date).dt.date
                local.trade_date = pd.to_datetime(local.trade_date).dt.date
                joined = local.merge(
                    reference,
                    on="trade_date",
                    how="left",
                    suffixes=("", "_reference"),
                    validate="one_to_one",
                )
                valid = pd.to_numeric(joined.pre_close, errors="coerce").gt(0) & joined.close.sub(
                    joined.close_reference
                ).abs().le(0.011)
                matched = joined[valid].copy()
                result["unmatched"] += int((~valid).sum())
                with self.c.transaction():
                    if not matched.empty:
                        with self.c.temp_view(matched, "price_reference") as view:
                            self.c.execute(
                                f"UPDATE daily_bar b SET reference_pre_close=r.pre_close,reference_close=r.close_reference,reference_source=? FROM {view} r WHERE b.code=? AND b.trade_date=r.trade_date",
                                [source.name, code],
                            )
                    self.repo.log_update(
                        "daily_bar",
                        f"{source.name}:reference_refresh",
                        lo,
                        hi,
                        len(matched),
                        "partial" if (~valid).any() else "success",
                        json.dumps(
                            {
                                "code": code,
                                "unmatched": int((~valid).sum()),
                                "task_id": getattr(ctx, "tid", None),
                            }
                        ),
                    )
                result["updated"] += len(matched)
            except TaskCancelled:
                raise
            except Exception as exc:
                result["errors"][code] = str(exc)
                if ctx:
                    ctx.log(f"{code} 参考价复核失败：{exc}", "warn")
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

    @checked_collection
    def refresh_st_status(
        self,
        codes: list[str] | None = None,
        start: date | None = None,
        end: date | None = None,
        ctx=None,
    ) -> dict:
        """Run one published ST refresh batch and fail closed on partial/cancelled runs."""
        st_service = StockSTStatusService(self.c)
        previous_state = st_service.refresh_state()
        market_hi, spans = self._st_refresh_spans(codes)
        include_collection_scope(self, "stock", spans["code"].tolist())
        target_count = len(spans)
        st_service.begin_refresh(
            task_id=getattr(ctx, "tid", None),
            target_count=target_count,
            start=start,
            end=end,
        )
        try:
            result = self._refresh_st_status_impl(
                codes=codes,
                start=start,
                end=end,
                ctx=ctx,
                prepared_spans=(market_hi, spans),
            )
        except Exception as exc:
            st_service.finish_refresh(ready=False, error=str(exc))
            raise
        source_ready = int(result.get("fail") or 0) == 0
        market_coverage = st_service.coverage()
        coverage_ready = int(market_coverage["accurate"]) == int(market_coverage["expected"])
        ready = source_ready and coverage_ready
        if not source_ready:
            error = f"{result.get('fail', 0)} 个刷新步骤失败"
        elif not coverage_ready:
            error = (
                "全市场 ST 点时事实仍未完整覆盖："
                f"权威 {market_coverage['accurate']}/{market_coverage['expected']}"
            )
        else:
            error = None
        # A failed full refresh can already have committed accurate facts for its successful
        # stocks while deliberately skipping marker publication. If operators recover only the
        # failed subset, the final subset must rebuild every marker before reopening the gate;
        # otherwise facts are complete but old daily_bar projections remain mixed.
        if (
            ready
            and codes is not None
            and (previous_state is None or previous_state.get("status") != "ready")
        ):
            try:
                result["projection_rows"] = st_service.rebuild_daily_bar_markers()
            except Exception as exc:
                st_service.finish_refresh(ready=False, error=str(exc))
                raise
        st_service.finish_refresh(
            ready=ready,
            error=error,
        )
        result["publication_status"] = "ready" if ready else "failed"
        result["coverage"] = st_service.coverage(start, end)
        return result

    def _st_refresh_spans(
        self, codes: list[str] | None = None
    ) -> tuple[date | None, pd.DataFrame]:
        """Resolve the exact ST refresh target set once for state and execution."""
        market_hi_raw = self.c.query_df("SELECT max(trade_date) AS d FROM daily_bar").iloc[0]["d"]
        market_hi = None if pd.isna(market_hi_raw) else pd.Timestamp(market_hi_raw).date()
        if market_hi is None:
            return None, pd.DataFrame(
                columns=["code", "lo", "hi", "delist_date", "price_limit_pct"]
            )
        spans = self.c.query_df(
            """
            WITH target_codes AS (
                SELECT DISTINCT code FROM daily_bar
                UNION
                SELECT code FROM stock_basic
                WHERE list_date IS NOT NULL AND list_date<=?
            )
            SELECT target.code,
                   COALESCE(min(b.trade_date),sb.list_date) AS lo,
                   COALESCE(max(b.trade_date),LEAST(COALESCE(sb.delist_date,?),?)) AS hi,
                   sb.delist_date,COALESCE(sb.price_limit_pct,0.10) AS price_limit_pct
            FROM target_codes target
            LEFT JOIN daily_bar b ON b.code=target.code
            LEFT JOIN stock_basic sb ON sb.code=target.code
            GROUP BY target.code,sb.list_date,sb.delist_date,sb.price_limit_pct
            HAVING COALESCE(min(b.trade_date),sb.list_date) IS NOT NULL
               AND COALESCE(max(b.trade_date),LEAST(COALESCE(sb.delist_date,?),?)) IS NOT NULL
            ORDER BY target.code
            """,
            [market_hi, market_hi, market_hi, market_hi, market_hi],
        )
        if codes:
            spans = spans[spans["code"].isin(set(codes))]
        return market_hi, spans.reset_index(drop=True)

    def _refresh_st_status_impl(
        self,
        codes: list[str] | None = None,
        start: date | None = None,
        end: date | None = None,
        ctx=None,
        prepared_spans: tuple[date | None, pd.DataFrame] | None = None,
    ) -> dict:
        """Backfill canonical ST facts from baostock and publish their daily projection.

        With no date range each selected security uses its listing-to-latest-market span,
        bounded by delisting when applicable. The operation is serial because baostock owns a
        process-global session. A source failure never falls back to the current name and is
        returned as a resumable per-code failure. This source task reports changed dates but
        never mutates downstream result lifecycle state.
        """
        market_hi, spans = prepared_spans or self._st_refresh_spans(codes)
        all_target = spans.to_dict("records")
        target_codes = {str(item["code"]) for item in all_target}
        checkpoint_done_codes = {
            str(code) for code in (getattr(ctx, "checkpoint", {}).get("st_done_codes") or [])
        }
        # A resumed task may see a changed target set after stock metadata is corrected.
        # Count and skip only checkpoints that still belong to this run's resolved target.
        done_codes = checkpoint_done_codes & target_codes
        target = [item for item in all_target if str(item["code"]) not in done_codes]
        source = self._source_for("st_status")
        st_service = StockSTStatusService(self.c)
        changed_dates: set[date] = {
            date.fromisoformat(str(value))
            for value in (getattr(ctx, "checkpoint", {}).get("st_changed_dates") or [])
        }
        touched_dates: set[date] = set()
        rows = ok = fail = 0
        failures: list[dict] = []
        total = len(all_target)
        completed_before = len(done_codes)
        if ctx:
            ctx.set_phase(
                "st_status", phase_total=total, phase_done=completed_before, current_item=None
            )
            ctx.log(
                f"▶ 开始 ST 状态刷新：{total} 只，已完成 {completed_before} 只，"
                f"本轮待处理 {len(target)} 只，源 {source.name}，"
                f"范围 {'指定区间' if start or end else '各股上市日至市场最新日'}（串行）"
            )
            ctx.flush()
        for index, item in enumerate(target, completed_before + 1):
            code = str(item["code"])
            item_lo = pd.Timestamp(item["lo"]).date()
            lo = max(item_lo, start) if start else item_lo
            stored_hi = pd.Timestamp(item["hi"]).date()
            delist = None if pd.isna(item.get("delist_date")) else pd.Timestamp(item["delist_date"]).date()
            natural_hi = min(market_hi or stored_hi, delist) if delist else (market_hi or stored_hi)
            hi = min(natural_hi, end) if end else natural_hi
            if hi < lo:
                done_codes.add(code)
                ok += 1
                if ctx:
                    ctx.set_checkpoint(st_done_codes=sorted(done_codes))
                continue
            if ctx:
                ctx.check_cancel()
                ctx.set_phase(
                    "st_status", phase_total=total, phase_done=index - 1, current_item=code
                )
            changed_for_code: list[date] = []
            try:
                expected = [
                    pd.Timestamp(value).date()
                    for value in self.repo.c.query_df(
                        "SELECT trade_date FROM daily_bar WHERE code=? AND trade_date BETWEEN ? AND ? "
                        "ORDER BY trade_date",
                        [code, lo, hi],
                    )["trade_date"].tolist()
                ]
                if market_hi is not None and hi == market_hi and hi not in expected:
                    expected.append(hi)
                facts = self._accurate_st_facts(
                    code,
                    expected,
                    force=True,
                    fetch_start=lo,
                    fetch_end=hi,
                    ctx=ctx,
                )
                touched_dates.update(fact.trade_date for fact in facts)
                changed_for_code = st_service.upsert_facts(
                    facts,
                    change_reason="baostock_st_refresh",
                    task_id=getattr(ctx, "tid", None),
                )
                changed_dates.update(changed_for_code)
                rows += len(facts)
                ok += 1
                done_codes.add(code)
                if ctx:
                    ctx.set_checkpoint(
                        st_done_codes=sorted(done_codes),
                        st_changed_dates=sorted(str(day) for day in changed_dates),
                    )
            except Exception as exc:  # noqa: BLE001 - per-code resumable boundary
                if ctx and changed_for_code:
                    # Facts may already be committed when checkpoint persistence fails. Preserve
                    # their dates so a resumed task still reports every affected source date.
                    ctx.set_checkpoint(
                        st_done_codes=sorted(done_codes),
                        st_changed_dates=sorted(str(day) for day in changed_dates),
                    )
                fail += 1
                failures.append({"code": code, "error": str(exc)[:500]})
                log.warning("%s ST 状态刷新失败: %s", code, exc)
                if ctx:
                    ctx.log(f"{code} ST 状态刷新失败：{exc}", "warn")
            if ctx and (index % 20 == 0 or index == total):
                ctx.set_phase(
                    "st_status", phase_total=total, phase_done=index, current_item=code
                )
                ctx.progress(min(0.08 + 0.84 * index / max(total, 1), 0.92),
                             f"ST 状态 {index}/{total}（成功{ok} 失败{fail}）")
                ctx.log(f"ST 状态进度 {index}/{total}：成功{ok} 失败{fail}，读取 {rows} 行")
                ctx.flush()

        changed = sorted(changed_dates)
        touched = sorted(touched_dates)
        # Marker publication is one set-based step after a zero-failure source batch. It avoids
        # needlessly recalculating adjustment factors per stock and cannot expose a mixed set.
        projection_rows = (
            st_service.rebuild_daily_bar_markers(codes=codes, start=start, end=end)
            if fail == 0 else 0
        )
        result = {
            "target": total,
            "ok": completed_before + ok,
            "fail": fail,
            "rows": rows,
            "changed_dates": len(changed),
            "changed_date_values": [str(day) for day in changed],
            "touched_dates": len(touched),
            "projection_rows": projection_rows,
            "downstream_results_untouched": True,
            "failures": failures[:50],
            "coverage": st_service.coverage(start, end),
        }
        self.repo.log_update(
            "stock_st_status_daily", source.name, start, end, rows,
            "success" if fail == 0 else "partial",
            json.dumps(result, ensure_ascii=False, default=str),
        )
        if ctx:
            changed_scope = (
                f"{changed[0]}~{changed[-1]}" if changed else "无事实变化"
            )
            ctx.log(
                f"■ ST 状态刷新完成：成功 {ok}、失败 {fail}、事实 {rows} 行、"
                f"影响 {len(changed)} 个交易日（{changed_scope}）；"
                "未直接修改评分、天梯等下游结果；榜单与天梯读取时按 ST 版本自检，"
                "是否提前批量维护仍由用户或显式调度决定"
            )
        return result

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
        basic = self.repo.c.query_df("SELECT code, price_limit_pct FROM stock_basic")
        limit_lut = dict(zip(basic["code"], basic["price_limit_pct"]))
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
                    code, float(limit_lut.get(code) or 0.10), full=full)
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
                # 失败项不得进入完成断点，续跑必须继续重试。
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

    def _recompute_clean_one(
        self, code: str, board_limit_pct: float, full: bool = True
    ) -> int:
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
                "       pre_close, reference_pre_close, reference_close, reference_source, adj_factor, adj_factor_clean FROM daily_bar "
                "WHERE code=? ORDER BY trade_date", [code])
        else:  # 增量：读锚点当日起（含锚点做 shift / 去抖上下文）
            df = self.repo.c.query_df(
                "SELECT code, trade_date, open, high, low, close, "
                "       pre_close, reference_pre_close, reference_close, reference_source, adj_factor, adj_factor_clean FROM daily_bar "
                "WHERE code=? AND trade_date>=? ORDER BY trade_date", [code, anchor_date])
            if len(df) <= 1:  # 只剩锚点本身，无新行
                return 0
        if df.empty:
            return 0

        refs = pd.to_numeric(df["reference_pre_close"], errors="coerce")
        valid_ref = (df.reference_source.notna() & refs.gt(0)
                     & pd.to_numeric(df.reference_close, errors="coerce").sub(df.close).abs().le(0.011))
        refs = refs.where(valid_ref)
        clean = dejitter_adj_factor(df["adj_factor"], df["close"], refs)
        if anchor_date is not None:
            # 去抖只保「段内结构」，绝对基准随窗口起点而变；重缩放使锚点干净因子与库中已存值
            # 连续，新行才能和历史无缝衔接（qfq 看比值，缩放因子在相除时抵消，不改 qfq/pre_close）。
            stored = float(df["adj_factor_clean"].iloc[0])
            head = float(clean.iloc[0])
            if stored > 0 and head > 0:
                clean = clean * (stored / head)
        df = df.copy()
        df["adj_factor_clean"] = clean.to_numpy()
        computed_pre_close = compute_pre_close(df["close"], clean)
        factor_event = clean.div(clean.shift(1)).sub(1).abs().gt(1e-10)
        # 入库时可能已经用直接提供官方 preclose 的备用源校准了除权日。
        # 全量/增量因子重算不得再用低精度的新浪反推值把它覆盖回去。
        existing_pre_close = pd.to_numeric(df["pre_close"], errors="coerce")
        # 序列首行没有上一行可推算，保留采集源提供的前收盘参考价。
        preserve = (factor_event | computed_pre_close.isna()) & valid_ref
        df["pre_close"] = computed_pre_close.where(~preserve, refs)
        # 首行缺少前置行情，仅保留原值用于展示，不让其参与因子推导。
        df.loc[df.index[0], "pre_close"] = df["pre_close"].iloc[0] if pd.notna(df["pre_close"].iloc[0]) else existing_pre_close.iloc[0]
        facts = self.c.query_df(
            """
            SELECT trade_date,is_st,quality FROM stock_st_status_daily
            WHERE code=? AND trade_date BETWEEN ? AND ?
            """,
            [code, pd.Timestamp(df["trade_date"].min()).date(),
             pd.Timestamp(df["trade_date"].max()).date()],
        )
        fact_map = {
            pd.Timestamp(row["trade_date"]).date(): bool(row["is_st"])
            for _, row in facts.iterrows()
            if row["quality"] == STStatusQuality.ACCURATE.value
        }
        missing = [
            pd.Timestamp(day).date() for day in df["trade_date"].tolist()
            if pd.Timestamp(day).date() not in fact_map
        ]
        if missing:
            # 复权因子与 ST 无关，不能因 ST 尚未回填而阻塞因子修复。此时只更新
            # 因子/pre_close；价格标记由 ST 刷新任务在事实齐备后统一重算。
            marked = df
        else:
            point_st = [fact_map[pd.Timestamp(day).date()] for day in df["trade_date"]]
            from backend.services.stock_special_trading_day import apply_special_day_markers

            marked = apply_special_day_markers(self.c, add_markers(df, board_limit_pct, point_st))
        if anchor_date is not None:  # 只写锚点之后的新行
            marked = marked[marked["trade_date"] > pd.Timestamp(anchor_date)]
        if marked.empty:
            return 0
        cols = ["code", "trade_date", "adj_factor_clean", "pre_close"]
        if not missing:
            cols += ["is_st", "is_suspended", "limit_status", "is_one_word"]
        with self.c.transaction(), self.c.temp_view(marked[cols], prefix="clean_rebuild") as v:
            marker_sql = (
                ", is_st = v.is_st, is_suspended = v.is_suspended, "
                "limit_status = v.limit_status, is_one_word = v.is_one_word"
                if not missing else ""
            )
            self.c.execute(
                "UPDATE daily_bar AS b SET "
                f"adj_factor_clean = v.adj_factor_clean, pre_close = v.pre_close{marker_sql} "
                f"FROM {v} AS v "
                "WHERE b.code = v.code AND b.trade_date = v.trade_date"
            )
            # 指标共享缓存按行情更新日志版本读取；纯因子重算也必须推进版本。
            self.repo.log_update(
                "daily_bar", "derived:price_factors",
                pd.Timestamp(marked.trade_date.min()).date(),
                pd.Timestamp(marked.trade_date.max()).date(), len(marked), "success",
                json.dumps({"code": code, "full": full}, ensure_ascii=False),
            )
        return len(marked)

    # ══════════════════════════════════════════════════════════
    # baostock 补充（T-M1-4）：上市/退市日 + 退市股历史（防幸存者偏差）
    # ══════════════════════════════════════════════════════════

    @checked_collection
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
        # 行业源漏返或请求失败不代表原行业失效，禁止把已知分类清空。
        existing_industry = self.c.query_df("SELECT code,industry FROM stock_basic")
        industry_by_code = dict(zip(existing_industry["code"], existing_industry["industry"]))
        out["industry"] = out["industry"].where(
            out["industry"].notna(), out["code"].map(industry_by_code))
        if ctx:
            ctx.check_cancel()
        include_collection_scope(self, "stock", out["code"].tolist())
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

    @checked_collection
    def ingest_delisted(self, years: int | None = None, limit: int | None = None, ctx=None) -> dict:
        """灌入"近 N 年内退市"的退市股历史日线（防幸存者偏差核心）。

        只取退市日落在回测窗口内的票（更早退市的在目标窗口内无数据，跳过）。
        """
        years = years or self.s.datasource.history_years
        start, end = self._history_window(years, ctx)
        bao = self._source_for("delisted")  # 退市股能力源

        dl = bao.get_delisted_list()  # code,name,delist_date
        dl = dl.dropna(subset=["delist_date"])
        dl = dl[dl["delist_date"] >= start]
        # 仅目标板块
        dl = dl[dl["code"].apply(lambda c: self._in_target_board(c.split(".")[0])[0])]
        if limit:
            dl = dl.head(limit)
        include_collection_scope(self, "stock", dl["code"].tolist())
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
                # 补 stock_basic 一行（退市股，含退市日）
                self.repo.upsert_stock_basic(
                    pd.DataFrame([{
                        "code": code, "name": r["name"], "exchange": classify_board(code6)[0],
                        "board": classify_board(code6)[1], "delist_date": r["delist_date"],
                        "price_limit_pct": limit_pct,
                    }])
                )
                rows = self.ingest_one_daily(
                    code, start, r["delist_date"], limit_pct, source=bao
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
        # 退市股同样完成干净因子和历史限幅标记；覆盖已满足但上次中断的也须收尾。
        factor_result = self._refresh_clean_factors(dl["code"].tolist(), ctx=ctx)
        result = {"target": len(dl), "ok": ok, "skip": skip,
                  "fail": fail + factor_result["fail"], "rows": total_rows,
                  "price_factors": factor_result}
        log.info("退市股灌入完成: %s", result)
        if ctx:
            ctx.log(f"子任务：退市股历史灌入完成，成功{ok} 跳过{skip} 失败{fail}，写入 {total_rows} 行")
        return result

    # ── 板块概念采集（字典 / 完整成分快照 / 指数 / 资金流）─────────────────
    @checked_collection
    def ingest_board(self, ctx=None, board_type: str | None = None,
                     board_codes: list[str] | None = None, mode: str = "update",
                     only: list[str] | None = None, limit: int | None = None,
                     force_members: bool | None = None,
                     force_current_day: bool = False,
                     date_start: date | str | None = None,
                     date_end: date | str | None = None,
                     target_end: date | None = None,
                     concurrency: int | None = None) -> dict:
        """板块数据编排：字典 → 成分快照 → 指数 → 资金流。

        承接 plan §6.4 T4：单步骤失败记日志不中断（返回失败清单），供 T5/T6 失败隔离与续跑。
        - mode="backfill"（初始化）：指数全量回填（源端可用起始年 2024 起）+ 资金流全周期；
          成分快照默认绕过周频全量拉（force_members 默认 True）。
        - mode="update"（每日增量）：指数只补最近交易日 + 资金流每日刷新全周期（即时/3日/5日/10日/20日）；
          指数按各板块已落库最大交易日续采到目标日；成分股按周频跳过逻辑拉完整快照，
          force_members=True 时绕过间隔。date_start/date_end 可显式指定指数采集区间。
          force_current_day=True 时跳过非交易日与源端就绪退级，直接尝试当天。
        - only：可选子集（"dict"/"members"/"bar"/"fund"），CLI --dict 等分表运行用。
        board_type 可限制 concept/industry；ctx 提供任务中心进度日志。
        """
        from datetime import date as _d

        from backend.services.board_ingest import (
            BOARD_INGEST_STAGES,
            BoardIngestService,
            normalize_board_date_range,
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
        explicit_start, explicit_end = normalize_board_date_range(
            mode, date_start, date_end, force_current_day,
        )
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
        checkpoint = (getattr(ctx, 'checkpoint', {}) or {}) if ctx else {}
        pinned_end = checkpoint.get('board_target_end')
        update_target = None
        if uses_market_date:
            if pinned_end:
                update_target = date.fromisoformat(pinned_end)
                eod_dates.cap_end(update_target, strict=True)
                if target_end is not None and update_target > target_end:
                    raise DataSourceError('板块续跑目标日不能晚于日常流程目标日')
            else:
                update_target = eod_dates.resolve_end(
                    svc.c, target_end or explicit_end, force=force_current_day,
                )
                if ctx:
                    ctx.set_checkpoint(board_target_end=update_target.isoformat())
        # 资金流源不返回可靠数据日：主编排统一用目标交易日标记快照，
        # 使列表/详情可按行情截面严格同日匹配。无行情锚点时由资金流服务解析已收盘日，
        # 不能把凌晨的“最近开市日”当成已经收盘；backfill 也不按自然日贴标签。
        fund_snapshot_date = update_target if "fund" in steps else None
        if ("fund" in steps and "bar" not in steps and not force_current_day
                and not pinned_end and target_end is None):
            # 只采资金流时没有指数阶段执行源端就绪探测与日期回退，不能直接把“今天是开市日”
            # 当成“今天行情已就绪”。页面以 board_bar 最新日为截面，资金流必须锚定同一日期；
            # 库内尚无板块行情时交由资金流服务解析快照日，供初始化任务建立首个快照。
            fund_snapshot_date = None
            latest_bar = svc.c.query_df(
                "SELECT max(trade_date) AS d FROM board_bar WHERE trade_date<=?",
                [update_target],
            ).iloc[0]["d"]
            if latest_bar is not None and pd.notna(latest_bar):
                fund_snapshot_date = pd.Timestamp(latest_bar).date()
                if ctx:
                    ctx.log(f"只采资金流：按板块行情最新日 {fund_snapshot_date} 标记快照")
        if force_current_day and uses_market_date and ctx:
            ctx.log(f"已确认当日 {update_target} 收盘，强制采集仅跳过源端就绪回退", "warn")
        # 阶段日志对齐现有采集（阶段 i/N + 进度推进，前端任务中心实时可见）
        total = len(steps)
        if board_codes is not None or limit is None:
            quality_codes = board_codes
            if quality_codes is None and board_type is not None:
                quality_codes = svc.c.query_df(
                    "SELECT board_code FROM board_dict WHERE board_type=?", [board_type]
                )["board_code"].tolist()
            include_collection_scope(self, "board", quality_codes)
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
                if board_type is not None and board_codes is None and limit is None:
                    include_collection_scope(self, "board", svc.c.query_df(
                        "SELECT board_code FROM board_dict WHERE board_type=?", [board_type]
                    )["board_code"].tolist())
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
            include_collection_scope(self, "board", board_codes)
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
                    force=force_members, concurrency=concurrency)
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
                        _d(2024, 1, 1), end=update_target, board_codes=board_codes,
                        board_type=board_type, ctx=ctx, concurrency=concurrency)
                else:
                    # 显式区间尊重调用方输入；自动增量按每个板块最大交易日续采，避免固定短窗口
                    # 在任务中断超过窗口后留下永久缺口。
                    assert update_target is not None or explicit_end is not None
                    end = min(explicit_end, update_target) if explicit_end else update_target
                    result["bar"] = svc.ingest_board_bar(explicit_start, end=end,
                                                         board_codes=board_codes,
                                                         board_type=board_type,
                                                         probe_ready=not explicit_start and not force_current_day,
                                                         resume_from_latest=not bool(explicit_start),
                                                         ctx=ctx, concurrency=concurrency)
                    update_target = _d.fromisoformat(result["bar"]["end"])
                    if "fund" in steps:
                        fund_snapshot_date = update_target
                    if ctx:
                        ctx.set_checkpoint(board_target_end=update_target.isoformat())
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
                # update/backfill 均刷新全周期：滚动周期值每个交易日都会变化。
                result["fund_flow"] = svc.ingest_board_fund_flow(
                    snapshot_date=fund_snapshot_date,
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
        # 字典阶段可能新增对象，必须在步骤结束后解析实际类型/limit 范围。
        quality_codes = board_codes
        if quality_codes is None and board_type is not None:
            quality_codes = svc.c.query_df(
                "SELECT board_code FROM board_dict WHERE board_type=?", [board_type]
            )["board_code"].tolist()
        include_collection_scope(self, "board", quality_codes)
        result["failed"] = list(dict.fromkeys(result["failed"]))
        result["ok"] = not result["failed"]
        if ctx:
            ctx.progress(0.9, "板块取数结束，开始收尾质检")
            ctx.log(f"板块采集完成（{mode}）：字典{result['dict']} 成分{len(result['members'])} 板块 "
                    f"指数{result['bar']} 资金流{result['fund_flow']} 失败{result['failed']}")
            ctx.flush()
        return result
