"""质量修复的取源材料：有界并发读取，原恢复入口在编排线程校验和落库。"""

from __future__ import annotations

from copy import copy, deepcopy
from datetime import date
from functools import wraps
from threading import local

import pandas as pd

from backend.services import eod_dates

BOARD_BAR_TYPES = frozenset({"board_index_gap", "board_index_gap_daily", "board_index_invalid"})
INDEX_TYPES = frozenset({"market_index_gap", "market_index_gap_daily", "market_index_invalid"})
CAPITAL_TYPES = frozenset({"capital_gap", "capital_invalid", "capital_mismatch", "capital_raw_invalid"})
ST_TYPES = frozenset({"st_status_missing", "st_status_approximate", "st_status_mismatch"})
GAP_TYPES = frozenset({"data_gap", "stale", "history_data_gap"})


class _TaskBoardSource:
    """只缓存任务内至多两类字典、十类资金流材料；日期校验仍先于缓存读取。"""

    def __init__(self, source, service):
        self.source, self.service = source, service
        self.cache = {}
        self.snapshot = None

    def __getattr__(self, name):
        return getattr(self.source, name)

    def _read(self, key, fetch):
        if key not in self.cache:
            try:
                self.cache[key] = (fetch(), None)
            except Exception as exc:  # 同次任务不能按问题条数放大失败请求预算
                from backend.services.async_task import TaskCancelled
                if isinstance(exc, TaskCancelled):
                    raise
                self.cache[key] = (None, exc)
        value, error = self.cache[key]
        if error is not None:
            raise error
        return deepcopy(value)

    def get_board_dict(self, board_type):
        return self._read(("dict", board_type), lambda: self.source.get_board_dict(board_type))

    def get_board_fund_flow(self, board_type, period):
        # 实时源跨交易日/集合竞价边界不可沿用旧快照；原落库入口还会再次校验目标日。
        snapshot = (self.service._validate_fund_snapshot_date()
                    if getattr(self.source, "fund_flow_is_live_snapshot", False) else None)
        if snapshot != self.snapshot:
            self.cache = {key: value for key, value in self.cache.items() if key[0] == "dict"}
            self.snapshot = snapshot
        return self._read(("fund", board_type, period),
                          lambda: self.source.get_board_fund_flow(board_type, period))


def board_repair_service(client, ctx):
    """同一修复任务只初始化一次板块服务；并发材料回放时使用浅拷贝，避免修改取源线程的源。"""
    material = getattr(ctx, "_board_repair_material", None)
    if material is not None:
        return material
    service = getattr(ctx, "_board_repair_base", None)
    if service is None:
        from backend.services.board_ingest import BoardIngestService
        service = BoardIngestService(client)
        service.src = _TaskBoardSource(service.src, service)
        ctx._board_repair_base = service
    return service


def repair_source_scope(method):
    """任务结束/取消均关闭复用会话；材料和来源失败缓存不会跨任务、续跑或进程持久化。"""
    @wraps(method)
    def run(params, ctx):
        try:
            return method(params, ctx)
        finally:
            service = getattr(ctx, "_board_repair_base", None)
            if service is not None:
                try:
                    service.src.close()
                except Exception as exc:  # noqa: BLE001 -- 清理失败不能覆盖已提交结果或取消信号
                    ctx.log(f"板块修复会话清理失败：{exc}", "warn")
                ctx._board_repair_base = None
            ctx._board_repair_material = ctx._market_repair_material = None
            ctx._capital_repair_material = None
            ctx._capital_repair_prefetched = None
            ctx._st_repair_result = ctx._st_repair_error = None
            ctx._stock_repair_material = None
    return run


def repair_capital_once(ingest, code, ctx):
    """同股四类问题共用一次全历史多源核验；按股票分组后仅保留当前股诊断。"""
    cached = getattr(ctx, "_capital_repair_material", None)
    if cached is None or cached[0] != code:
        try:
            material = getattr(ctx, "_capital_repair_prefetched", None)
            if material is not None and material[0] == code and material[3]:
                # 必须在原恢复入口绑定 fixing 之后合并；提前落库会让扫描关闭台账，
                # 从而把部分来源失败掩盖成“已被其它扫描解决”。
                result = ingest._complete_capital_material(
                    [(1, code, material[1], material[2], 0)], ingest._source_for("share_capital"),
                    lambda code, source: ingest.repair_capital_quality(
                        code, ctx=ctx, _source=source),
                )[0]
                if result[3] is not None:
                    raise result[3]
                value = result[2]
            else:
                value = ingest.repair_capital_quality(code, ctx=ctx)
            cached = (code, value, None)
        except Exception as exc:  # 后续同股问题复用失败，不重新扩大请求次数
            from backend.services.async_task import TaskCancelled
            if isinstance(exc, TaskCancelled):
                raise
            cached = (code, None, exc)
        ctx._capital_repair_material = cached
    if cached[2] is not None:
        raise cached[2]
    return cached[1]


def run_st_repairs(ingest, report, ctx, selected, recover):
    """ST三类问题合并一次已有专项刷新，保留它的全市场发布门与成功股票断点。"""
    targets = selected[selected.issue_type.isin(ST_TYPES)]
    if targets.empty:
        return
    from backend.services.async_task import TaskCancelled, _RepairCollectionContext

    pending = []
    for row in targets.itertuples():
        day = None if pd.isna(row.trade_date) else pd.Timestamp(row.trade_date).date()
        if report.recheck_clean(row.issue_type, row.code, day):
            recover(int(row.id))
        else:
            pending.append(row)
    if not pending:
        return
    child = _RepairCollectionContext(ctx, "st_repair_checkpoint")
    try:
        ctx._st_repair_result = ingest.refresh_st_status(
            codes=list(dict.fromkeys(row.code for row in pending)), ctx=child,
        )
    except TaskCancelled:
        raise
    except Exception as exc:  # noqa: BLE001 -- 原恢复入口负责逐条复位、失败归属和诊断
        ctx._st_repair_error = exc
    for row in pending:
        recover(int(row.id))


def run_stock_repairs(ingest, report, ctx, selected, recover, *, repair_type=None):
    """个股修复复用采集有界队列；线程只取材料，原恢复入口负责持久化及成功断点。

    同股覆盖/鲜活问题共用材料，股本四类共用一次核验；旧调度仍按原近端范围取源。
    估值事件补充、备用源对剩余坏行的复核仍由原链路按需执行，不能预先重拉全历史。
    """
    from backend.common.exceptions import DataSourceError
    from backend.datasource.baostock_executor import execution_scope
    from backend.services.async_task import TaskCancelled
    from backend.services.ingest import _DailySTMaterial

    effective = selected.assign(issue_type=repair_type) if repair_type else selected
    for operation, types in [("gap", GAP_TYPES), ("adj", {"adj_jump"}), ("capital", CAPITAL_TYPES)]:
        targets = effective[effective.issue_type.isin(types)]
        if targets.empty:
            continue
        units = [
            (code, list(group.itertuples())) for code, group in targets.groupby("code", sort=False)
        ]
        concurrency = min(ingest.s.datasource.update_concurrency, len(units))
        tls = local()

        def prepare(item, *, operation=operation):
            code, rows = item
            ctx.check_cancel()
            full = any(row.issue_type == "history_data_gap" for row in rows)
            if full:
                # 同股同时选中历史缺口和鲜活问题时，先完成包含近端的历史恢复。
                rows = sorted(rows, key=lambda row: row.issue_type != "history_data_gap")
            if operation == "capital" and all(
                report.recheck_clean(row.issue_type, code, None) for row in rows
            ):
                return code, rows, full, [], None, None, None
            if operation == "gap":
                from backend.services.history_quality import HistoryQualityService
                dates = (HistoryQualityService(report.c).dates(code) if full
                         else report.missing_days_for(code))
                lo, hi = (min(dates), max(dates)) if dates else (None, None)
            else:
                span = report.c.query_df(
                    "SELECT min(trade_date) lo,max(trade_date) hi FROM daily_bar WHERE code=?",
                    [code],
                ).iloc[0]
                lo, hi = ((pd.Timestamp(span.lo).date(), pd.Timestamp(span.hi).date())
                          if pd.notna(span.lo) else (None, None))
                dates = []
            status = _DailySTMaterial(report.c.query_df(
                "SELECT trade_date,is_st,source,source_ref,quality FROM stock_st_status_daily "
                "WHERE code=? AND trade_date BETWEEN ? AND ? AND quality='accurate'",
                [code, lo, hi],
            )) if lo is not None and operation != "capital" else None
            return code, rows, full, dates, lo, hi, status

        def fetch(item, *, operation=operation, tls=tls):
            code, _rows, full, dates, lo, hi, status = item
            if lo is None:
                return None
            # 取源之前使用同一收盘上界，不能只在回放落库时裁掉未来响应。
            hi = eod_dates.cap_range(lo, hi)
            dates = [day for day in dates if day <= hi]
            if operation == "capital":
                source = ingest._source_for("share_capital")
                source = ingest._thread_source(tls, source.name)
                return ingest._fetch_capital_material(code, source, lo, hi)
            result = {"status": status, "bars": None, "error": None, "capital": None}

            def fetch_status():
                try:
                    status.fetched = ingest._fetch_st_status_rows(code, lo, hi)
                except TaskCancelled:
                    raise
                except DataSourceError as exc:
                    status.error = exc

            pending = set(dates)
            if full:
                fetch_status()
                if status.fetched is not None:
                    frame = status.fetched[1]
                    if frame is not None and not frame.empty and "trade_status" in frame:
                        # 仅一致的逐日零状态可省去行情请求；主线程仍走原证据门禁。
                        stopped = pd.to_numeric(frame.trade_status, errors="coerce").eq(0)
                        by_day = stopped.groupby(pd.to_datetime(frame.trade_date).dt.date).all()
                        pending -= set(by_day[by_day].index)
                if not pending:
                    return result
            start, end = (min(pending), max(pending)) if pending else (lo, hi)
            try:
                result["bars"] = ingest._fetch_daily_with_fallback(
                    code, start, end, ingest._thread_source(tls, ingest.src.name),
                    allow_fallback=not (full and status.error is not None),
                )
            except TaskCancelled:
                raise
            except DataSourceError as exc:
                result["error"] = exc
            frame = eod_dates.bound_bars(result["bars"][0], start, end) if result["bars"] else None
            known = set(pd.to_datetime(status.stored.trade_date).dt.date)
            returned = (set(pd.to_datetime(frame.trade_date).dt.date)
                        if frame is not None and not frame.empty else set())
            if not full and (result["error"] is not None or returned - known
                             or (operation == "gap" and set(dates) - returned)):
                fetch_status()
            backfilled = sorted(returned & set(dates))
            if operation == "gap" and backfilled:
                try:
                    source = ingest._source_for("valuation")
                    source = ingest._thread_source(tls, source.name)
                    # 主源可能只返回部分日期，备用源随后会补齐其余行情。
                    # 估值预取覆盖计划区间，回放时仍按实际补回范围过滤，避免漏掉来源证据。
                    result["capital"] = (ingest._fetch_capital_material(
                        code, source, start, end), None)
                except TaskCancelled:
                    raise
                except Exception as exc:  # noqa: BLE001 -- 原多源链继续其它来源并记录失败
                    result["capital"] = (None, exc)
            return result

        def complete(_i, item, material, error, _pending, *, operation=operation):
            code, rows, _full, _dates, lo, _hi, _status = item
            if operation == "capital":
                ctx._capital_repair_prefetched = (code, material, error, lo is not None)
            else:
                ctx._stock_repair_material = (code, material, error)
            try:
                for row in rows:
                    recover(int(row.id))
            finally:
                ctx._stock_repair_material = ctx._capital_repair_material = None
                ctx._capital_repair_prefetched = None

        ctx.log(f"个股修复取源：{operation}，{len(targets)} 条问题归并为 {len(units)} 只股票（并发 {concurrency}）")
        tracker = getattr(ctx, "request_tracker", None)
        if tracker:
            tracker.meta.update(work_concurrency=concurrency,
                                configured_work_concurrency=ingest.s.datasource.update_concurrency)
        with execution_scope(concurrency, tracker=tracker):
            ingest._run_bounded_parallel(
                units, fetch, prepare=prepare, concurrency=concurrency, ctx=ctx,
                wait_label="个股修复取源", on_complete=complete, prefetch_next_batch=True,
                transform_batch=lambda entries: entries, batch_size=1,
            )


class _MaterialSource:
    """将已取得的完整材料交给原入口；按每条问题的原请求区间裁剪，不扩大写入范围。"""

    is_prefetched = True

    def __init__(self, source, operation, code, value, error):
        self.source, self.operation, self.code = source, operation, code
        self.value, self.error = value, error

    def __getattr__(self, name):
        return getattr(self.source, name)

    def _value(self, operation, code):
        if operation != self.operation or code != self.code:
            raise RuntimeError("修复材料与目标不匹配，禁止隐式重复取源")
        if self.error is not None:
            raise self.error
        return deepcopy(self.value)

    def _bars(self, operation, code, start, end):
        value = self._value(operation, code)
        failed = [y for y in value.attrs.get("failed_years", []) if start.year <= y <= end.year]
        if "required_dates" in value.attrs and not any(
            start.isoformat() <= day <= end.isoformat() for day in value.attrs["missing_dates"]
        ):
            failed = []  # 同年度其它目标失败不应否定本条已完整取得的原始记录。
        value = eod_dates.bound_bars(value, start, end)
        value.attrs["failed_years"] = failed
        return value

    def get_board_bar(self, code, board_type, start, end):
        return self._bars("bar", code, start, end)

    def get_board_members(self, code, board_type):
        return self._value("member", code)

    def get_index_bar(self, code, start, end):
        return self._bars("index", code, start, end)


def _ranges(rows, client, *, market=False):
    from backend.services.async_task import (
        _board_trailing_gap_range,
        _market_index_trailing_gap_range,
    )
    trailing = _market_index_trailing_gap_range if market else _board_trailing_gap_range
    intervals = []
    for row in rows:
        day = None if pd.isna(row.trade_date) else pd.Timestamp(row.trade_date).date()
        lo, hi = (trailing(client, row.code, day) if row.issue_type.endswith("index_gap")
                  else (day, day))
        if lo is None or hi is None:
            continue
        hi = eod_dates.cap_range(lo, hi)
        intervals.append((lo, hi))
    return intervals


def _annual_bars(source, code, board_type, intervals, required=None):
    # 同一年度接口只取一次；不为相隔多年的两个问题请求中间未选年份。
    years = {}
    for lo, hi in intervals:
        for year in range(lo.year, hi.year + 1):
            first, last = max(lo, date(year, 1, 1)), min(hi, date(year, 12, 31))
            previous = years.get(year, (first, last))
            years[year] = (min(first, previous[0]), max(last, previous[1]))
    frames, failed, wanted, missing = [], [], [], []
    for lo, hi in years.values():
        options = ({"required_dates": {day for day in (required or []) if lo <= day <= hi}}
                   if getattr(source, "supports_bar_dates", False) else {})
        value = source.get_board_bar(code, board_type, lo, hi, **options)
        failed.extend(value.attrs.get("failed_years", []))
        wanted.extend(value.attrs.get("required_dates", []))
        missing.extend(value.attrs.get("missing_dates", []))
        if not value.empty:
            frames.append(value)
    value = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    value.attrs["failed_years"] = sorted(set(failed))
    if getattr(source, "supports_bar_dates", False):
        value.attrs.update(required_dates=sorted(set(wanted)), missing_dates=sorted(set(missing)))
    return value


def run_batched_repairs(client, report, ingest, ctx, selected, recover):
    """批量只并发联网：板块指数/成分及市场指数复用有界队列，逐对象回原恢复入口。"""
    from backend.services.bounded_parallel import run_bounded_parallel
    for operation, types in [("bar", BOARD_BAR_TYPES), ("member", {"board_member_incomplete"}),
                             ("index", INDEX_TYPES)]:
        targets = selected[selected.issue_type.isin(types)]
        if targets.empty:
            continue
        market = operation == "index"
        if market and not hasattr(ingest, "src"):
            continue  # 兼容仅提供恢复接口的导入/测试适配器。
        metadata = ({} if market else client.query_df(
            "SELECT board_code,board_type FROM board_dict WHERE board_code IN "
            "(SELECT unnest(?::VARCHAR[]))", [targets.code.dropna().unique().tolist()],
        ).set_index("board_code").board_type.to_dict())
        units = []
        for code, group in targets.groupby("code", sort=False):
            rows = list(group.itertuples())
            pending = []
            for row in rows:
                day = None if pd.isna(row.trade_date) else pd.Timestamp(row.trade_date).date()
                if operation != "member" and report.recheck_clean(row.issue_type, code, day):
                    recover(int(row.id))
                else:
                    pending.append(row)
            if not pending or (not market and code not in metadata):
                continue
            if market:
                from backend.services.market_benchmark import configured_benchmark_codes
                if code not in configured_benchmark_codes():
                    continue
            try:
                intervals = [] if operation == "member" else _ranges(pending, client, market=market)
            except Exception as exc:  # noqa: BLE001 -- 非法边界交原入口报告逐条失败，不提前联网
                ctx.log(f"{code} 修复区间未能规划，将按原入口逐条核验：{exc}", "warn")
                continue
            if operation != "member" and not intervals:
                continue
            required = set()
            if operation == "bar":
                dates = client.query_df(
                    "SELECT trade_date FROM trade_calendar WHERE is_open AND trade_date BETWEEN ? AND ?",
                    [min(lo for lo, _ in intervals), max(hi for _, hi in intervals)],
                ).trade_date.dt.date
                required = {day for day in dates if any(lo <= day <= hi for lo, hi in intervals)}
                required.update(hi for _, hi in intervals)
            units.append((code, metadata.get(code), pending, intervals, required))
        if not units:
            continue
        # 本地已收敛的问题直接复检关闭；只有实际需要材料时才创建取源会话。
        base = None if market else board_repair_service(client, ctx)
        ctx.log(f"批量修复取源：{operation}，{len(targets)} 条问题归并为 {len(units)} 个标的；"
                "材料有界并发，原恢复入口逐条落库复检")

        def complete(_i, item, value, error, _pending, *, market=market, base=base, operation=operation):
            code, _board_type, rows, _intervals, _required = item
            service = copy(ingest if market else base)
            service.src = _MaterialSource(service.src, operation, code, value, error)
            attr = "_market_repair_material" if market else "_board_repair_material"
            setattr(ctx, attr, service)
            try:
                for row in rows:
                    recover(int(row.id))
            finally:
                setattr(ctx, attr, None)

        def fetch(source, item, *, operation=operation, market=market):
            code, board_type, _rows, intervals, required = item
            if operation == "member":
                return source.get_board_members(code, board_type)
            if market:
                lo, hi = min(x[0] for x in intervals), max(x[1] for x in intervals)
                return source.get_index_bar(code, lo, hi)
            return _annual_bars(source, code, board_type, intervals, required)

        if market:
            tls = local()
            concurrency = min(ingest.s.datasource.update_concurrency, len(units))
            tracker = getattr(ctx, "request_tracker", None)
            if tracker:
                tracker.meta.update(work_concurrency=concurrency,
                                    configured_work_concurrency=ingest.s.datasource.update_concurrency)
            run_bounded_parallel(
                units, lambda item, tls=tls: fetch(ingest._thread_source(tls, ingest.src.name), item),
                concurrency=concurrency, ctx=ctx, wait_label="市场指数修复取源", on_complete=complete,
            )
        else:
            concurrency = base._work_concurrency("bar" if operation == "bar" else "member", None, ctx)
            base._run_board_units(units, fetch, complete, concurrency=concurrency,
                                  ctx=ctx, label="板块修复取源")
