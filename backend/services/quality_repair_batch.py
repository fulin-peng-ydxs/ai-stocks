"""修复的主线程批次提交：复用正常采集合并/质检，原恢复入口逐条发布终态。"""

from __future__ import annotations

import pandas as pd


def commit_stock_repairs(ingest, report, ctx, entries, operation):
    """只接管本任务仍为 open 的问题；未回调或取消的 fixing 由任务作用域复位。"""
    from backend.services.capital_quality import CAPITAL_ISSUE_TYPES, CapitalQualityService
    from backend.services.history_quality import HistoryQualityService

    ctx.check_cancel()
    ctx._stock_batch_client = report.c
    ctx._stock_batch_checks = checks = {}
    ctx._stock_batch_synced = set()
    claimed = getattr(ctx, "_stock_batch_claimed", set())
    ctx._stock_batch_claimed = claimed
    ids = [int(row.id) for _, item, *_ in entries for row in item[1]]
    owned = report.c.query_df(
        "UPDATE data_quality_issue SET status='fixing',fix_task_id=? "
        "WHERE status='open' AND id IN (SELECT unnest(?::BIGINT[])) RETURNING id",
        [ctx.tid, ids],
    )
    claimed.update(owned.id)
    active = [entry for entry in entries if any(int(row.id) in claimed for row in entry[1][1])]
    if not active:
        return entries
    codes = [entry[1][0] for entry in active]
    maintenance = dict(ctx.checkpoint.get("stock_repair_pending", {}))
    force_review = {value.get("code", key.split(":", 1)[-1])
                    for key, value in maintenance.items() if value.get("operation") == "capital"}
    for _index, item, _material, _error, _pending in active:
        code, _rows, _full, dates, lo, hi, _status = item
        if lo is not None:
            maintenance[f"{operation}:{code}"] = {
                "operation": operation, "code": code, "full": _full, "dates": list(map(str, dates)),
            }
    # 数据已提交但因子/来源证据/质检尚未完成时，续跑仍须重新取得这个有界批次。
    ctx.set_checkpoint(stock_repair_pending=maintenance)
    material_by_code = {entry[1][0]: entry[2] for entry in active}
    fetched, windows = [], {}
    if operation != "capital":
        daily, starts, ends = [], {}, {}
        for index, item, material, error, pending in active:
            code, _rows, full, dates, lo, hi, status = item
            if error is not None or material is None:
                continue
            material["initial_missing"] = dates
            material["daily_committed"] = 0
            if full and status.fetched is not None:
                ingest._confirm_gap_suspensions(code, dates, report, ctx=ctx, material=status)
            if material["bars"] is not None or material["error"] is not None:
                starts[code], ends[code] = lo, hi
                daily.append((index, (code, status), material["bars"], material["error"], pending))
        if daily:
            committed = ingest._commit_daily_materials(
                daily, starts, max(ends.values()), ends=ends, ctx=ctx,
            )
            for _index, code, rows, error, _pending in committed:
                material_by_code[code]["daily_committed"] = rows or 0
                material_by_code[code]["daily_error"] = error
        valid = [code for code, material in material_by_code.items()
                 if material is not None and material.get("daily_error") is None]
        dirty = ingest._dirty_daily_codes(valid)
        if dirty:
            factors = ingest._recompute_clean(sorted(dirty), ctx=ctx)
            if not factors["fail"]:
                for material in material_by_code.values():
                    if material is not None:
                        material["factors_complete"] = True
        else:
            for material in material_by_code.values():
                if material is not None:
                    material["factors_complete"] = True
        if operation == "adj":
            return entries
        # 历史全范围复检一次；还有缺口的股票继续原备用源/停牌核验路径。
        remaining = set(HistoryQualityService(report.c).aggregate(codes).code)
        recent_remaining = set(report.missing_days_many(codes).code)
        full = {item[0]: item[2] for _, item, *_ in active}
        closed = [code for code, material in material_by_code.items()
                  if material is not None and code not in (remaining if full[code] else recent_remaining)
                  and material.get("factors_complete") and material.get("daily_error") is None]
        for index, item, material, error, pending in active:
            code, _rows, _full, dates, lo, hi, _status = item
            if code not in closed or material.get("capital") is None:
                continue
            frame_and_prices, source_error = material["capital"]
            frame, prices = frame_and_prices if frame_and_prices is not None else (None, None)
            if frame is not None:
                frame.attrs["source_valuation_prices"] = prices
            fetched.append((index, code, frame, source_error, pending))
            windows[code] = lo, hi
    else:
        closed = []
        for index, item, material, error, pending in active:
            code, _rows, _full, _dates, lo, hi, _status = item
            if lo is None:
                continue
            frame, prices = material if material is not None else (None, None)
            if frame is not None:
                frame.attrs["source_valuation_prices"] = prices
            fetched.append((index, code, frame, error, pending))
            windows[code] = lo, hi
    values = {}
    if fetched:
        def one(code, source):
            if operation == "capital":
                return ingest.repair_capital_quality(code, ctx=ctx, _source=source)
            return ingest._collect_capital_one(code, source, *windows[code])
        merged = ingest._merge_valuation_batch(
            fetched, ingest._source_for("share_capital" if operation == "capital" else "valuation"),
            windows, one, ctx=ctx, checks=checks, force_review=force_review,
        )
        values = {code: (value, error) for _, code, value, error, _ in merged}
    if operation == "capital":
        if len(fetched) != len(active):
            # 已通过预检或无行情的旧问题同样按实际全历史事实收口，不重复联网。
            remaining = CapitalQualityService(report.c).aggregate(codes)
            bad = set(zip(remaining.issue_type, remaining.code, strict=True))
            for code in codes:
                for kind in (*CAPITAL_ISSUE_TYPES, "capital_raw_invalid"):
                    checks[kind, code] = (kind, code) not in bad
        results = []
        for index, item, material, error, pending in entries:
            value, error = values.get(item[0], ({"rows": 0}, error))
            results.append((index, item, value if isinstance(value, dict) else {"rows": value or 0},
                            error, pending))
        # 结果尚未逐条消费；此时取消或单股来源失败，续跑仍须补完来源核验。
        return results
    if closed:
        HistoryQualityService(report.c).sync(closed)
        ctx._stock_batch_synced = set(closed)
        # 从落库事实复用本次原始缺口对应的结果，避免每股重复查询和同步同一全历史规则。
        targets = pd.DataFrame([
            {"code": code, "trade_date": day}
            for code in closed for day in material_by_code[code]["initial_missing"]
        ], columns=["code", "trade_date"])
        with report.c.temp_view(targets, "repair_dates") as view:
            facts = report.c.query_df(
                f"SELECT t.code,t.trade_date,b.code IS NOT NULL has_bar,s.code IS NOT NULL stopped "
                f"FROM {view} t LEFT JOIN daily_bar b USING(code,trade_date) "
                "LEFT JOIN stock_suspension s USING(code,trade_date)"
            )
        for code in closed:
            material = material_by_code[code]
            stock = facts[facts.code.eq(code)]
            error = values.get(code, (None, None))[1]
            stage_errors = {"capital": str(error)} if error is not None else {}
            if material["status"].error is not None:
                stage_errors["suspension"] = str(material["status"].error)
            material["reconciled"] = {
                "miss": material["initial_missing"],
                "backfilled": pd.to_datetime(stock.loc[stock.has_bar, "trade_date"]).dt.date.tolist(),
                "confirmed": int(stock.stopped.sum()), "rows": material["daily_committed"],
                "stage_errors": stage_errors,
            }
            checks["history_data_gap", code] = code not in remaining
            for kind in ("stale", "data_gap"):
                checks[kind, code] = code not in recent_remaining
    for code in closed:
        maintenance.pop(f"{operation}:{code}", None)
    ctx.set_checkpoint(stock_repair_pending=maintenance)
    return entries
