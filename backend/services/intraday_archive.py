"""已收盘分时归档、覆盖与质量闭环；读取不触发写入，写入由异步任务互斥。"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from uuid import uuid4

import pandas as pd
import redis

from backend.config import get_effective_settings, get_settings
from backend.services import eod_dates
from backend.services.intraday_contract import (
    BAR_FIELDS,
    EXPECTED_TIMES,
    INTRADAY_ISSUE_TYPES,
    INTRADAY_PROVIDERS,
    PROVIDER_LABELS,
    REQUIRED_TIMES,
    candidate_rank,
    normalize_intraday_params,
)
from backend.services.intraday_evidence import IntradayEvidence, missing_ranges
from backend.storage.repository import MarketRepository

LABELS = {
    "intraday_gap": "分时整日缺失",
    "intraday_partial": "分时分钟不完整",
    "intraday_invalid": "分时数据非法",
}


def _day(value) -> date:
    return pd.Timestamp(value).date()


def _utcnow():
    return datetime.now(UTC).replace(tzinfo=None)


class IntradayArchiveService:
    """有界并发取源，主线程串行归档，内存只保留在途股票窗口。"""

    def __init__(self, client, *, quotes=None):
        self.c = client
        self.quotes = quotes

    def bounds(self, code):
        row = self.c.query_df(
            "SELECT min(trade_date) lo,max(trade_date) hi FROM stock_intraday_coverage "
            "WHERE code=? AND point_count>0",
            [code],
        ).iloc[0]
        return {
            "archive_start": None if pd.isna(row.lo) else str(_day(row.lo)),
            "archive_end": None if pd.isna(row.hi) else str(_day(row.hi)),
        }

    def read(self, code, day, cache=None):
        """每次先查覆盖修订，旧 Redis key 不会跨事实版本复活。缓存故障只降级。"""
        coverage = self.c.query_df(
            "SELECT status,source,fetched_at,revision FROM stock_intraday_coverage "
            "WHERE code=? AND trade_date=? AND point_count>0",
            [code, day],
        )
        if coverage.empty:
            return None
        row = coverage.iloc[0]
        key = f"market:intraday:archive:v1:{code}:{day}:{row.revision}"
        if cache is not None:
            try:
                raw = cache.get(key)
                if raw:
                    payload = json.loads(raw)
                    if payload.get("revision") == row.revision and isinstance(
                        payload.get("rows"), list
                    ):
                        return payload
            except (redis.RedisError, OSError, ValueError, TypeError):
                pass
        frame = self.c.query_df(
            "SELECT timestamp,open,high,low,close,volume,amount FROM stock_intraday_bar "
            "WHERE code=? AND trade_date=? ORDER BY timestamp",
            [code, day],
        )
        if frame.empty:
            return None
        rows = []
        for point in frame.itertuples(index=False, name=None):
            rows.append(
                [str(point[0])[:19]]
                + [None if pd.isna(value) else float(value) for value in point[1:]]
            )
        payload = {
            "status": row.status,
            "source": row.source,
            "revision": row.revision,
            "fetched_at": pd.Timestamp(row.fetched_at).tz_localize("UTC").isoformat(),
            "rows": rows,
        }
        if cache is not None:
            try:
                cache.set(key, json.dumps(payload), ex=get_settings().intraday.cache_ttl_sec)
            except (redis.RedisError, OSError):
                pass
        return payload

    def _coverage_sql(self, codes=None):
        """由独立起点和日历生成应有日期；没有覆盖记录的日期也必须参与质检。"""
        # 兼容尚未迁移的旧覆盖；有独立起点后不再从逐日记录反推边界。
        sql = """
            WITH monitors AS (
                SELECT code,monitoring_start FROM stock_intraday_monitor
                UNION ALL
                SELECT c.code,min(c.trade_date) FROM stock_intraday_coverage c
                WHERE NOT EXISTS (SELECT 1 FROM stock_intraday_monitor m WHERE m.code=c.code)
                GROUP BY c.code
            )
            SELECT m.code,t.trade_date,m.monitoring_start,
                coalesce(c.point_count,0) point_count,coalesce(c.status,'missing') status,
                c.source,c.fetched_at,c.attempted_at,c.failure_reason,c.diagnostics,c.revision
            FROM monitors m JOIN stock_basic s ON s.code=m.code
            JOIN trade_calendar t ON t.is_open AND t.trade_date>=m.monitoring_start
            LEFT JOIN stock_intraday_coverage c ON c.code=m.code AND c.trade_date=t.trade_date
            WHERE t.trade_date<=(SELECT max(trade_date) FROM daily_bar WHERE trade_date<=?)
              AND (s.list_date IS NULL OR t.trade_date>=s.list_date)
              AND (s.delist_date IS NULL OR t.trade_date<s.delist_date)
              AND NOT EXISTS (SELECT 1 FROM stock_suspension x
                              WHERE x.code=m.code AND x.trade_date=t.trade_date)
        """
        args = [eod_dates.time_cutoff()]
        if codes is not None:
            sql += " AND m.code IN (SELECT unnest(?::VARCHAR[]))"
            args.append(codes)
        return sql, args

    def _register_monitoring(self, scope):
        """首跑先固定全股票池起点；空响应、异常或续跑不能抹掉应查日期。"""
        frame = pd.DataFrame(
            {
                "code": scope["codes"],
                "monitoring_start": [
                    _day(
                        scope.get("monitoring_starts", {}).get(
                            code, scope.get("starts", {}).get(code, scope["start"])
                        )
                    )
                    for code in scope["codes"]
                ],
            }
        )
        if not frame.empty:
            with self.c.temp_view(frame, prefix="intraday_monitor") as view:
                self.c.execute(
                    "INSERT INTO stock_intraday_monitor(code,monitoring_start) "
                    f"SELECT code,monitoring_start FROM {view} ON CONFLICT DO NOTHING"
                )

    def online_dates(self, *, provider="sina") -> list[str]:
        """源端近期窗口由真实日历决定，不能因本地日线落后而向历史平移。"""
        # 东财 ndays=5 包含尚未收盘的当前开市日，不能倒推为五个已收盘日。
        cutoff = (eod_dates.shanghai_now().date() if provider == "eastmoney"
                  else eod_dates.resolve_end(self.c))
        limit = 5 if provider == "eastmoney" else get_settings().intraday.supported_trade_days
        rows = self.c.query_df(
            "SELECT trade_date FROM trade_calendar WHERE is_open AND trade_date<=? "
            "ORDER BY trade_date DESC LIMIT ?",
            [cutoff, limit],
        )
        return sorted(str(_day(day)) for day in rows.trade_date)

    def _scope(self, params, ctx):
        frozen = ctx.checkpoint.get("intraday_scope") if ctx else None
        if frozen:
            eod_dates.cap_end(date.fromisoformat(frozen["end"]), strict=True)
            return frozen
        online = self.online_dates()
        if not online:
            raise ValueError("请先完成交易日历与日线采集")
        last = (
            self.c.query_df(
                "SELECT max(trade_date) d FROM daily_bar WHERE trade_date<=?",
                [eod_dates.time_cutoff()],
            )
            .iloc[0]
            .d
        )
        if pd.isna(last):
            raise ValueError("尚无已收盘的本地日线，请先完成日线采集")
        end = min(_day(last), date.fromisoformat(online[-1]))
        if params["mode"] == "update" and end < date.fromisoformat(online[0]):
            raise ValueError("本地日线落后于近期分钟源窗口，请先完成日线采集")
        if params["mode"] == "refetch":
            start, requested = (
                date.fromisoformat(params["date_start"]),
                date.fromisoformat(params["date_end"]),
            )
            eod_dates.cap_end(requested, strict=True)
            end = min(requested, end)
            if start > end:
                raise ValueError("重采区间尚无本地已收盘日线，请先完成日线采集")
        else:
            start = date.fromisoformat(online[0])
        if "codes" in params:
            codes = params["codes"]
            known = set(
                self.c.query_df(
                    "SELECT code FROM stock_basic WHERE code IN (SELECT unnest(?::VARCHAR[]))",
                    [codes],
                ).code
            )
            if known != set(codes):
                raise ValueError("指定股票未入库：" + "、".join(sorted(set(codes) - known)))
            with_bars = set(
                self.c.query_df(
                    "SELECT DISTINCT code FROM daily_bar WHERE code IN (SELECT unnest(?::VARCHAR[])) "
                    "AND trade_date BETWEEN ? AND ?",
                    [codes, start, end],
                ).code
            )
            if with_bars != set(codes):
                raise ValueError(
                    "区间内尚无本地日线，请先完成日线采集："
                    + "、".join(sorted(set(codes) - with_bars))
                )
        else:
            codes = self.c.query_df(
                "SELECT DISTINCT b.code FROM daily_bar b JOIN stock_basic s ON s.code=b.code "
                "WHERE b.trade_date BETWEEN ? AND ? AND b.code NOT LIKE '%.BJ' "
                "UNION SELECT code FROM stock_intraday_coverage "
                "UNION SELECT code FROM stock_intraday_monitor ORDER BY code",
                [start, end],
            ).code.tolist()
        prior = self.c.query_df(
            "SELECT code,min(d) d FROM (SELECT code,monitoring_start d FROM stock_intraday_monitor "
            "UNION ALL SELECT code,trade_date FROM stock_intraday_coverage) "
            "WHERE code IN (SELECT unnest(?::VARCHAR[])) GROUP BY code",
            [codes],
        )
        monitored = {row.code: str(_day(row.d)) for row in prior.itertuples()}
        if params["mode"] == "update":
            starts = monitored
        else:
            # 重采不能将尚未监控的十年日线意外扩展为分钟覆盖义务。
            starts = {
                code: max(str(start), min(monitored.get(code, online[0]), online[0]))
                for code in codes
            }
            if starts and all(value > str(end) for value in starts.values()):
                raise ValueError("重采区间超出现有分钟源窗口且无已监控日期，无法取得任意历史分时")
        frozen = {
            "codes": codes,
            "start": str(start),
            "end": str(end),
            "mode": params["mode"],
            "starts": starts,
            "monitoring_starts": {code: monitored.get(code, online[0]) for code in codes},
        }
        if ctx:
            ctx.set_checkpoint(intraday_scope=frozen)
        return frozen

    def _ensure_expected(self, code, scope):
        start = scope.get("starts", {}).get(code, scope["start"])
        expected_sql, args = self._coverage_sql([code])
        self.c.execute(
            "INSERT INTO stock_intraday_coverage(code,trade_date) "
            f"SELECT code,trade_date FROM ({expected_sql}) "
            "WHERE trade_date BETWEEN ? AND ? ON CONFLICT DO NOTHING",
            args + [start, scope["end"]],
        )
        return self.c.query_df(
            f"SELECT trade_date,status,point_count FROM ({expected_sql}) "
            "WHERE trade_date BETWEEN ? AND ? ORDER BY trade_date",
            args + [start, scope["end"]],
        )

    def write_day(self, code: str, day: str, candidates: list[dict], *, error="", task_id=None):
        """选整日最优候选；事实、修订、覆盖和溯源原子提交，不混用两源分钟。"""
        options = []
        for window in candidates:
            rows = [r for r in window["rows"] if r[0][:10] == day]
            if rows:
                options.append({**window, "rows": rows})
        best = max(options, key=lambda w: candidate_rank(w["rows"], w["source"]), default=None)
        existing = self.read(code, day)
        selected = best
        if existing and (
            not best
            or candidate_rank(existing["rows"], existing["source"])
            > candidate_rank(best["rows"], best["source"])
        ):
            selected = existing
        changed = selected is not None and (
            not existing
            or selected["rows"] != existing["rows"]
            or selected["source"] != existing["source"]
        )
        attempted = _utcnow()
        result = "missing"
        with self.c.transaction():
            if selected:
                rows, source = selected["rows"], selected["source"]
                status = "ready" if candidate_rank(rows, source)[0] else "partial"
                if changed:
                    fetched = (
                        pd.Timestamp(selected["fetched_at"]).tz_convert("UTC").tz_localize(None)
                    )
                    frame = pd.DataFrame(rows, columns=BAR_FIELDS)
                    frame["code"], frame["trade_date"] = code, date.fromisoformat(day)
                    frame["timestamp"] = pd.to_datetime(frame.timestamp)
                    frame["source"], frame["fetched_at"] = source, fetched
                    self.c.execute(
                        "DELETE FROM stock_intraday_bar WHERE code=? AND trade_date=?", [code, day]
                    )
                    with self.c.temp_view(frame, prefix="intraday") as view:
                        self.c.execute(
                            f"INSERT INTO stock_intraday_bar BY NAME SELECT * FROM {view}"
                        )
                    revision = uuid4().hex
                    diag = selected.get("day_diagnostics", {}).get(
                        day, selected.get("diagnostics", {})
                    )
                    self.c.execute(
                        "UPDATE stock_intraday_coverage SET point_count=?,status=?,source=?,fetched_at=?,"
                        "revision=?,diagnostics=? WHERE code=? AND trade_date=?",
                        [len(rows), status, source, fetched, revision, json.dumps(diag), code, day],
                    )
                    self.c.execute(
                        "INSERT INTO data_source_provenance VALUES (?,?,?,?,?,?,?)",
                        [code, "stock_intraday_bar", day, day, source, len(rows), fetched],
                    )
                    MarketRepository(self.c).log_update(
                        "stock_intraday_bar",
                        f"intraday:{source}:{code}",
                        date.fromisoformat(day),
                        date.fromisoformat(day),
                        len(rows),
                        "success",
                        json.dumps({"task_id": task_id, "status": status, "diagnostics": diag}),
                    )
                elif existing["status"] != status:
                    # 规则修订可能只改变覆盖状态；事实不重写，缓存仍需隔离旧状态。
                    self.c.execute(
                        "UPDATE stock_intraday_coverage SET status=?,revision=? "
                        "WHERE code=? AND trade_date=?",
                        [status, uuid4().hex, code, day],
                    )
                if best and selected is best:
                    # 清洗诊断可由重新取得的干净响应消除，即使事实数值没有变化。
                    diag = best.get("day_diagnostics", {}).get(day, best.get("diagnostics", {}))
                    self.c.execute(
                        "UPDATE stock_intraday_coverage SET diagnostics=? WHERE code=? AND trade_date=?",
                        [json.dumps(diag), code, day],
                    )
                result = ("updated" if existing else "inserted") if changed else "unchanged"
            if not selected and best is None and candidates:
                diag = max(
                    (w.get("day_diagnostics", {}).get(day, {}) for w in candidates),
                    key=lambda d: d.get("invalid_rows", 0),
                    default={},
                )
                self.c.execute(
                    "UPDATE stock_intraday_coverage SET diagnostics=CASE WHEN ?<>'{}' THEN ? "
                    "ELSE diagnostics END WHERE code=? AND trade_date=?",
                    [json.dumps(diag), json.dumps(diag), code, day],
                )
            self.c.execute(
                "UPDATE stock_intraday_coverage SET attempted_at=?,failure_reason=? "
                "WHERE code=? AND trade_date=?",
                [attempted, error or ("" if selected else "源端暂无数据"), code, day],
            )
        return result

    def collect(
        self, params=None, *, ctx=None, allow_fallback=False, recheck_source=False, repair_dates=None
    ):
        """统一归档入口；备用源开关仅由质检修复传入，不属于公开任务参数。"""
        params = normalize_intraday_params(params)
        if not get_settings().intraday.enabled:
            raise ValueError("分时数据功能当前未启用")
        if ctx:
            ctx.check_cancel()
        scope = self._scope(params, ctx)
        self._register_monitoring(scope)
        from queue import SimpleQueue

        from backend.services.bounded_parallel import run_bounded_parallel
        from backend.services.intraday_source import IntradaySourceService

        concurrency = get_effective_settings().datasource.update_concurrency
        events = SimpleQueue()

        class SourceContext:
            # 工作线程不写任务日志序号、进度或checkpoint，主线程统一消费。
            def check_cancel(self):
                if ctx:
                    ctx.check_cancel()

            def log(self, message, level="info"):
                events.put((message, level))

            def flush(self):
                pass

        def drain_events():
            while not events.empty():
                message, level = events.get()
                if ctx:
                    ctx.log(message, level)
            if ctx:
                ctx.flush()

        evidence = IntradayEvidence(self.c)
        states = evidence.load(scope["codes"])
        done = set(ctx.checkpoint.get("intraday_done", [])) if ctx else set()
        stats = dict(ctx.checkpoint.get("intraday_stats", {})) if ctx else {}
        for key in (
            "inserted",
            "updated",
            "unchanged",
            "skipped",
            "partial",
            "missing",
            "failed",
            "out_of_range",
        ):
            stats.setdefault(key, 0)
        if ctx:
            ctx.log(
                f"分时{'近期增量补采' if scope['mode'] == 'update' else '日期区间重采'}："
                f"{len(scope['codes'])} 只，目标 {scope['start']} 至 {scope['end']}；"
                f"已成功完成 {len(done)} 只，本轮跳过已完成股票，失败项重试"
            )
            ctx.log(
                "取源策略：新浪优先；质检修复按目标日依次尝试同花顺、东财备用"
                if allow_fallback else
                "取源策略：仅新浪；缺失与不完整进入质检，东财和同花顺仅在质检修复时尝试"
            )
            ctx.log(
                f"完整性口径：{len(REQUIRED_TIMES)} 个必需时点，15:00 收盘柱必需；"
                "14:58、14:59 集合竞价阶段不强制有独立成交柱，不补造分钟"
            )
            ctx.log(
                f"请求保护：并发 {concurrency}，限流、超时、重试及退避统一读取系统配置；"
                "按股票取源，同花顺按目标年份各请求一次，不按每个交易日重复请求"
            )
            ctx.flush()
        errors = []
        failed_codes = dict(ctx.checkpoint.get("intraday_failed", {})) if ctx else {}
        items = [(index, code) for index, code in enumerate(scope["codes"]) if code not in done]
        already_done = len(done)

        def prepare(item):
            index, code = item
            if ctx:
                ctx.check_cancel()
            expected = self._ensure_expected(code, scope)
            if repair_dates is not None:
                selected_dates = repair_dates.get(code, set()) if isinstance(repair_dates, dict) else repair_dates
                expected = expected[expected.trade_date.map(lambda d: str(_day(d)) in selected_dates)]
            pending = (
                expected if scope["mode"] == "refetch" else expected[expected.status.ne("ready")]
            )
            actual_times = {
                str(_day(r.trade_date)): set(r.times) for r in self.c.query_df(
                    "SELECT trade_date,list(strftime(timestamp,'%H:%M')) times "
                    "FROM stock_intraday_bar WHERE code=? AND trade_date IN "
                    "(SELECT unnest(?::DATE[])) GROUP BY trade_date",
                    [code, pending.trade_date.dt.date.tolist()],
                ).itertuples()
            }
            decisions = {
                str(_day(row.trade_date)): evidence.assess(
                    code, str(_day(row.trade_date)),
                    sorted(REQUIRED_TIMES - actual_times.get(str(_day(row.trade_date)), set())),
                    states, allow_fallback=allow_fallback, recheck=recheck_source,
                ) for row in pending.itertuples()
            }
            available = pending[pending.trade_date.map(
                lambda d: decisions[str(_day(d))]["can_repair"]
            )]
            unavailable = pending[~pending.index.isin(available.index)]
            if ctx:
                ctx.log(
                    f"[{index + 1}/{len(scope['codes'])}] {code}：应查 {len(expected)} 日，"
                    f"已完整跳过 {len(expected) - len(pending)} 日，待取源 {len(available)} 日，"
                    f"当前来源无法覆盖 {len(unavailable)} 日"
                )
                ctx.flush()
                if allow_fallback:
                    for day, decision in list(decisions.items())[:10]:
                        for source_decision in decision["decisions"]:
                            action = "候选取源" if source_decision["request"] else "跳过"
                            ctx.log(f"{code} {day} {PROVIDER_LABELS[source_decision['source']]}："
                                    f"{action}；{source_decision['reason']}")
                    if len(decisions) > 10:
                        ctx.log(f"另有 {len(decisions) - 10} 个目标日按相同来源规则判断；逐日依据保留在质量详情")
                    ctx.flush()
            for row in unavailable.itertuples():
                # 未发请求只更新原因，不伪造“最近尝试”，更不改事实或修订。
                self.c.execute(
                    "UPDATE stock_intraday_coverage SET failure_reason=? WHERE code=? AND trade_date=?",
                    [decisions[str(_day(row.trade_date))]["reason"], code, row.trade_date],
                )
            return {"index": index, "code": code, "expected": expected, "pending": pending,
                        "actual_times": actual_times, "decisions": decisions, "available": available,
                        "unavailable": unavailable}

        def fetch(plan):
            code, available, decisions = plan["code"], plan["available"], plan["decisions"]
            quotes = self.quotes or IntradaySourceService(ctx=SourceContext())
            technical_error, candidates = "", []
            if not available.empty:
                try:
                    target_dates = [str(_day(d)) for d in available.trade_date]
                    providers = tuple(p for p in INTRADAY_PROVIDERS if any(
                        p in decisions[d]["providers"] for d in target_dates
                    ))
                    use_fallback = any(p != "sina" for p in providers)
                    window = quotes.fetch_window(
                        code, target_dates, allow_fallback=use_fallback, providers=providers,
                    )
                    candidates = window.get("candidates", [window])
                    if window.get("errors"):
                        technical_error = "；".join(window["errors"])
                except Exception as exc:  # noqa: BLE001 -- 单股失败留证，取消必须穿透
                    if ctx:
                        ctx.check_cancel()
                    candidates = list(getattr(quotes, "last_windows", {}).values())
                    technical_error = f"{type(exc).__name__}: {str(exc)[:300]}"
                    if ctx:
                        events.put((f"{code} 分时请求失败：{technical_error}", "warn"))
            return candidates, technical_error, getattr(quotes, "last_observations", {})

        def complete(completed, plan, value, error, _in_flight):
            if error is not None:
                raise error
            index = already_done + completed - 1
            code, pending = plan["code"], plan["pending"]
            actual_times = plan["actual_times"]
            available, unavailable = plan["available"], plan["unavailable"]
            candidates, technical_error, observations = value
            stats["skipped"] += len(plan["expected"]) - len(pending)
            stats["out_of_range"] += len(unavailable)
            outcomes = {"inserted": 0, "updated": 0, "unchanged": 0, "missing": 0}
            if technical_error and len(errors) < 100:
                errors.append({"code": code, "reason": technical_error})
            if not available.empty:
                evidence.record(
                    code, candidates, observations,
                    task_id=getattr(ctx, "tid", None),
                )
                # 同股为其他日期取源时，若新响应拓宽了范围，立即利用已取得的更好候选。
                # 不必等待下一轮任务，也不为已证明不可覆盖的日期额外发送请求。
                improved = []
                for row in unavailable.itertuples():
                    day = str(_day(row.trade_date))
                    old_count = len(REQUIRED_TIMES & actual_times.get(day, set()))
                    if any(len(REQUIRED_TIMES & {r[0][11:16] for r in w["rows"]
                                                if r[0][:10] == day}) > old_count for w in candidates):
                        improved.append(row.Index)
                if improved:
                    available = pd.concat([available, unavailable.loc[improved]])
                    stats["out_of_range"] -= len(improved)
                for row in available.itertuples():
                    if ctx:
                        ctx.check_cancel()
                    result = self.write_day(
                        code,
                        str(_day(row.trade_date)),
                        candidates,
                        error=technical_error,
                        task_id=getattr(ctx, "tid", None),
                    )
                    if result in outcomes:
                        outcomes[result] += 1
                    if result in stats and result != "missing":
                        stats[result] += 1
            # write_day 已按整日分钟重新判定覆盖；来源报错与目标归档完成分别记账。
            # 诊断仍含非法行时不能按完整放行，最终质量同步继续按事实复检。
            target_days = pending.trade_date.dt.date.tolist()
            cover = self.c.query_df(
                "SELECT count(*) FILTER(WHERE status='ready') complete_days,"
                "count(*) FILTER(WHERE status='partial') partial_days,"
                "count(*) FILTER(WHERE point_count=0) missing_days,"
                "count(*) FILTER(WHERE trade_date IN (SELECT unnest(?::DATE[])) "
                "AND status='ready' AND coalesce(try_cast(json_extract(diagnostics,"
                "'$.invalid_rows') AS INTEGER),0)=0) target_complete_days "
                "FROM stock_intraday_coverage WHERE code=? AND trade_date BETWEEN ? AND ?",
                [target_days, code, scope.get("starts", {}).get(code, scope["start"]), scope["end"]],
            ).iloc[0]
            targets_complete = int(cover.target_complete_days) == len(target_days)
            if technical_error and targets_complete:
                # 消费质量层的实际事实复检，不能仅凭覆盖标记把来源错误降为警告。
                target_facts = self._coverage_facts([code])
                target_facts = target_facts[target_facts.trade_date.dt.date.isin(target_days)]
                targets_complete = not self.issues([code], facts=target_facts)
                # 区间重采全部请求失败时，旧完整归档不能冒充本次取源成功。
                targets_complete = targets_complete and all(
                    any(candidate_rank([r for r in w["rows"] if r[0][:10] == str(day)],
                                       w["source"])[0] for w in candidates)
                    for day in target_days
                )
            if not technical_error or targets_complete:
                done.add(code)
                failed_codes.pop(code, None)
                if technical_error:
                    self.c.execute(
                        "UPDATE stock_intraday_coverage SET failure_reason='' WHERE code=? "
                        "AND trade_date IN (SELECT unnest(?::DATE[]))", [code, target_days],
                    )
            else:
                failed_codes[code] = technical_error
            stats["failed"] = len(failed_codes)
            if ctx:
                ctx.set_checkpoint(
                    intraday_done=sorted(done),
                    intraday_stats=stats,
                    intraday_failed=failed_codes,
                    phase_done=index + 1,
                )
                message = (
                    f"{code} 落库：新增 {outcomes['inserted']} 日、更新 {outcomes['updated']} 日、"
                    f"未变化 {outcomes['unchanged']} 日；范围内完整 {int(cover.complete_days)} 日、"
                    f"部分 {int(cover.partial_days)} 日、缺失 {int(cover.missing_days)} 日"
                )
                if technical_error:
                    message += (
                        f"；目标日期已补齐；来源请求警告：{technical_error}" if targets_complete
                        else f"；目标日期仍有缺口或数据异常，未完成项保留重试资格：{technical_error}"
                    )
                ctx.log(message, "warn" if technical_error else "info")
                ctx.progress(
                    (index + 1) / max(1, len(scope["codes"])),
                    f"分时采集 {index + 1}/{len(scope['codes'])} · {code}",
                )
        # 注入的单实例测试源保留串行；生产每个工作单元拥有独立源和候选证据。
        run_bounded_parallel(items, fetch, concurrency=concurrency if self.quotes is None else 1,
                             ctx=ctx, prepare=prepare, on_complete=complete,
                             on_tick=drain_events, wait_label="分时采集")
        drain_events()
        if ctx:
            ctx.log("逐股采集结束：正在复检分时覆盖、非法数据及历史整日缺口…")
            ctx.flush()
        quality = self.sync(scope["codes"])
        # 汇总须消费复检后的覆盖，不能将旧口径的 partial 带入任务终态。
        expected_sql, args = self._coverage_sql(scope["codes"])
        remaining = self.c.query_df(
            f"SELECT status,count(*) n FROM ({expected_sql}) WHERE trade_date<=? GROUP BY status",
            args + [scope["end"]],
        )
        counts = dict(zip(remaining.status, remaining.n))
        stats["partial"], stats["missing"] = (
            int(counts.get("partial", 0)),
            int(counts.get("missing", 0)),
        )
        return {
            "ok": stats["failed"] == 0,
            **stats,
            "errors": errors[:100],
            "target_end": scope["end"],
            "quality": quality,
            "message": f"分时采集完成：新增 {stats['inserted']}、更新 {stats['updated']}、"
            f"部分 {stats['partial']}、缺失 {stats['missing']}、当前来源无法覆盖 {stats['out_of_range']}、技术失败 {stats['failed']}",
        }

    def _coverage_facts(self, codes=None):
        """按逐日覆盖监控；实际分钟结构另行扫描，杜绝只相信完成标记。"""
        expected_sql, args = self._coverage_sql(codes)
        facts = self.c.query_df(
            "SELECT c.*,coalesce(f.n,0) actual_count,coalesce(f.expected_count,0) expected_count,"
            "f.actual_source,f.actual_fetched_at "
            f"FROM ({expected_sql}) c "
            "LEFT JOIN (SELECT code,trade_date,count(*) n,"
            "count(DISTINCT strftime(timestamp,'%H:%M')) FILTER(WHERE strftime(timestamp,'%H:%M') "
            "IN (SELECT unnest(?::VARCHAR[]))) expected_count,"
            "arg_max(source,fetched_at) actual_source,max(fetched_at) actual_fetched_at "
            "FROM stock_intraday_bar "
            "WHERE (?::VARCHAR[] IS NULL OR code IN (SELECT unnest(?::VARCHAR[]))) "
            "GROUP BY code,trade_date) f ON f.code=c.code AND f.trade_date=c.trade_date",
            args + [sorted(REQUIRED_TIMES), codes, codes],
        )
        # 完整日只需计数；缺失分钟按最多 500 个股票交易日聚合，避免持有全市场分钟列表。
        incomplete = facts.loc[facts.expected_count.lt(len(REQUIRED_TIMES)), ["code", "trade_date"]]
        incomplete = incomplete.sort_values(["code", "trade_date"])
        missing = {}
        for offset in range(0, len(incomplete), 500):
            with self.c.temp_view(incomplete.iloc[offset:offset + 500], prefix="intraday_missing") as view:
                rows = self.c.query_df(
                    "SELECT t.code,t.trade_date,list_filter(?::VARCHAR[],x -> NOT list_contains("
                    "coalesce(f.times,[]::VARCHAR[]),x)) missing_times "
                    f"FROM {view} t LEFT JOIN (SELECT b.code,b.trade_date,"
                    "list(DISTINCT strftime(b.timestamp,'%H:%M')) times FROM stock_intraday_bar b "
                    f"JOIN {view} q ON q.code=b.code AND q.trade_date=b.trade_date "
                    "GROUP BY b.code,b.trade_date) f ON f.code=t.code AND f.trade_date=t.trade_date",
                    [sorted(REQUIRED_TIMES)],
                )
                missing.update({(r.code, _day(r.trade_date)): list(r.missing_times)
                                for r in rows.itertuples()})
        facts["missing_times"] = [missing.get((r.code, _day(r.trade_date)), [])
                                  for r in facts.itertuples()]
        return facts

    def issues(self, codes=None, *, facts=None):
        rows = self._coverage_facts(codes) if facts is None else facts
        evidence = IntradayEvidence(self.c) if not rows.empty else None
        states = evidence.load(codes) if evidence else {}
        result = []
        for row in rows.itertuples():
            kind = (
                "intraday_gap"
                if row.actual_count == 0
                else "intraday_partial"
                if row.expected_count < len(REQUIRED_TIMES)
                else None
            )
            diag = json.loads(row.diagnostics or "{}")
            if diag.get("invalid_rows", 0) or row.actual_count != row.point_count:
                result.append(
                    self._issue(
                        row.code,
                        row.trade_date,
                        "intraday_invalid",
                        "源端含拒用非法记录或归档计数不一致",
                        diag,
                    )
                )
            if kind:
                message = f"{LABELS[kind]}，有效 {row.actual_count} 点"
                if row.failure_reason and not str(row.failure_reason).startswith("超出现有分钟源窗口"):
                    message += f"；{row.failure_reason}"
                missing = list(row.missing_times)
                ranges = missing_ranges(missing)
                availability = evidence.assess(row.code, str(_day(row.trade_date)), missing, states)
                payload = {
                    "message": message, "diagnostics": diag,
                    "coverage": {"trade_date": str(_day(row.trade_date)), "point_count": int(row.actual_count),
                                 "required_count": len(REQUIRED_TIMES),
                                 "covered_count": int(row.expected_count),
                                 "missing_times": missing, "missing_ranges": ranges},
                    "availability": availability,
                    "reason_code": availability["reason_code"] if availability["reason_code"] in ("window_truncated", "outside_observed_window")
                                   else "source_missing_minutes" if any(
                                       x["source"] == row.source for x in availability["sources"]
                                   ) else "needs_verification",
                }
                issue = self._issue(row.code, row.trade_date, kind, message, diag)
                issue["detail"] = json.dumps(payload, ensure_ascii=False)
                result.append(issue)
        for row in self.invalid_facts(codes).itertuples():
            result.append(
                self._issue(
                    row.code, row.trade_date, "intraday_invalid", "归档分钟结构或价格量额非法", {}
                )
            )
        # 数据非法与覆盖缺口同样承接可修复性和分钟证据，不在页面另算。
        by_day = {(r.code, str(_day(r.trade_date))): r for r in rows.itertuples()}
        for issue in result:
            payload = json.loads(issue["detail"])
            fact = by_day.get((issue["code"], str(issue["trade_date"])))
            if "coverage" not in payload and fact is not None:
                missing = list(fact.missing_times)
                payload.update(
                    coverage={"trade_date": str(_day(fact.trade_date)), "point_count": int(fact.actual_count), "required_count": len(REQUIRED_TIMES),
                              "covered_count": int(fact.expected_count), "missing_times": missing,
                              "missing_ranges": missing_ranges(missing)},
                    availability=evidence.assess(issue["code"], str(issue["trade_date"]), missing, states),
                )
                issue["detail"] = json.dumps(payload, ensure_ascii=False)
        # 同日清洗诊断与结构错误合并为一个稳定问题身份。
        return list({(r["code"], r["trade_date"], r["issue_type"]): r for r in result}.values())

    @staticmethod
    def _issue(code, day, kind, message, diagnostics):
        return {
            "code": code,
            "trade_date": _day(day),
            "issue_type": kind,
            "detail": json.dumps(
                {"message": message, "diagnostics": diagnostics}, ensure_ascii=False
            ),
        }

    def invalid_facts(self, codes=None):
        scope = " AND b.code IN (SELECT unnest(?::VARCHAR[]))" if codes is not None else ""
        frame = self.c.query_df(
            "SELECT DISTINCT b.code,b.trade_date FROM stock_intraday_bar b "
            "LEFT JOIN stock_basic s ON s.code=b.code "
            "LEFT JOIN trade_calendar t ON t.trade_date=b.trade_date "
            "WHERE (s.code IS NULL OR NOT coalesce(t.is_open,false) OR CAST(b.timestamp AS DATE)<>b.trade_date "
            "OR strftime(b.timestamp,'%H:%M') NOT IN (SELECT unnest(?::VARCHAR[])) "
            "OR extract(second FROM b.timestamp)<>0 "
            "OR b.close<=0 OR b.low<=0 OR b.high<b.low OR b.close NOT BETWEEN b.low AND b.high "
            "OR NOT isfinite(b.close) OR NOT isfinite(b.high) OR NOT isfinite(b.low) "
            "OR (b.open IS NOT NULL AND (NOT isfinite(b.open) OR b.open<=0 OR b.open NOT BETWEEN b.low AND b.high)) "
            "OR b.volume<0 OR b.amount<0 OR NOT isfinite(b.volume) OR NOT isfinite(b.amount))"
            + scope,
            [sorted(EXPECTED_TIMES | {"09:30", "13:00"})] + ([codes] if codes is not None else []),
        )

        monitor_scope = " AND m.code IN (SELECT unnest(?::VARCHAR[]))" if codes is not None else ""
        monitors = self.c.query_df(
            "SELECT m.code,m.monitoring_start trade_date FROM stock_intraday_monitor m "
            "LEFT JOIN stock_basic s ON s.code=m.code "
            "LEFT JOIN trade_calendar t ON t.trade_date=m.monitoring_start "
            "WHERE (s.code IS NULL OR NOT coalesce(t.is_open,false))" + monitor_scope,
            [codes] if codes is not None else [],
        )
        return pd.concat([frame, monitors], ignore_index=True).drop_duplicates()

    def sync(self, codes=None):
        from backend.services.data_report import DataIntegrityReport

        facts = self._coverage_facts(codes)
        rows = self.issues(codes, facts=facts)
        previous_repairs = self.c.query_df(
            "SELECT code,trade_date,issue_type,json_extract(CASE WHEN json_valid(detail) THEN detail "
            "ELSE '{}' END,'$.last_repair') last_repair FROM data_quality_issue "
            "WHERE issue_type IN (SELECT unnest(?::VARCHAR[])) AND "
            "json_exists(CASE WHEN json_valid(detail) THEN detail ELSE '{}' END,'$.last_repair') "
            "AND (?::VARCHAR[] IS NULL OR code IN (SELECT unnest(?::VARCHAR[])))",
            [list(INTRADAY_ISSUE_TYPES), codes, codes],
        )
        repair_by_day = {(r.code, str(_day(r.trade_date)), r.issue_type): r.last_repair
                         for r in previous_repairs.itertuples()}
        for issue in rows:
            repair = repair_by_day.get((issue["code"], str(issue["trade_date"]), issue["issue_type"]))
            if repair:
                detail = json.loads(issue["detail"])
                detail["last_repair"] = json.loads(repair)
                issue["detail"] = json.dumps(detail, ensure_ascii=False)
        # 质量扫描确认物理分钟变化后同步覆盖与修订；概览不能继续显示旧完成标记。
        facts = facts.copy()
        facts["actual_status"] = [
            "missing" if r.actual_count == 0
            else "ready" if r.expected_count == len(REQUIRED_TIMES) else "partial"
            for r in facts.itertuples()
        ]
        changed = facts[
            (facts.point_count != facts.actual_count) | (facts.status != facts.actual_status)
        ]
        with self.c.transaction():
            expected_sql, args = self._coverage_sql(codes)
            self.c.execute(
                "INSERT INTO stock_intraday_coverage(code,trade_date) "
                f"SELECT code,trade_date FROM ({expected_sql}) ON CONFLICT DO NOTHING",
                args,
            )
            if not changed.empty:
                with self.c.temp_view(
                    changed[
                        [
                            "code",
                            "trade_date",
                            "actual_count",
                            "actual_status",
                            "actual_source",
                            "actual_fetched_at",
                        ]
                    ],
                    prefix="intraday_recheck",
                ) as view:
                    self.c.execute(
                        "UPDATE stock_intraday_coverage c SET point_count=f.actual_count,"
                        "status=f.actual_status,source=coalesce(c.source,f.actual_source),"
                        "fetched_at=coalesce(c.fetched_at,f.actual_fetched_at),"
                        "revision=CAST(uuid() AS VARCHAR) "
                        f"FROM {view} f WHERE c.code=f.code AND c.trade_date=f.trade_date"
                    )
            DataIntegrityReport(self.c)._upsert_scan_issues(rows, INTRADAY_ISSUE_TYPES, codes=codes)
        return {
            kind: sum(row["issue_type"] == kind for row in rows) for kind in INTRADAY_ISSUE_TYPES
        }

    def clean(self, kind, code, day):
        return not any(
            r["issue_type"] == kind and r["trade_date"] == _day(day) for r in self.issues([code])
        )

    def summary_by_stock(self, codes):
        expected_sql, args = self._coverage_sql(codes)
        frame = self.c.query_df(
            "SELECT code,min(monitoring_start) monitoring_start,max(trade_date) target_end,"
            "max(trade_date) FILTER(WHERE point_count>0) archive_end,"
            "count(*) FILTER(WHERE status='ready') complete_days,"
            "count(*) FILTER(WHERE status='partial') partial_days,"
            "count(*) FILTER(WHERE point_count=0) missing_days "
            f"FROM ({expected_sql}) GROUP BY code",
            args,
        )
        return json.loads(frame.to_json(orient="records", date_format="iso"))

    def summary(self, code=None):
        """累计覆盖与目标日逐股覆盖分开统计，不能用单股最大归档日代表全部股票。"""
        expected_sql, args = self._coverage_sql([code] if code else None)
        frame = self.c.query_df(
            f"WITH expected AS ({expected_sql}),target AS (SELECT max(trade_date) AS target_date FROM expected) "
            "SELECT min(monitoring_start) monitoring_start,max(trade_date) target_end,"
            "max(trade_date) FILTER(WHERE point_count>0) archive_end,"
            "count(DISTINCT code) stocks,count(*) expected_days,"
            "count(*) FILTER(WHERE status='ready') complete_days,"
            "count(*) FILTER(WHERE status='partial') partial_days,"
            "count(*) FILTER(WHERE point_count=0) missing_days,"
            "count(*) FILTER(WHERE trade_date=(SELECT target_date FROM target)) latest_expected_stocks,"
            "count(*) FILTER(WHERE trade_date=(SELECT target_date FROM target) AND status='ready') latest_complete_stocks "
            "FROM expected",
            args,
        )
        result = json.loads(frame.to_json(orient="records", date_format="iso"))[0]
        # 全表 COUNT(*) 由 DuckDB 计数；不加载分钟明细，也不把逐日覆盖数当分钟行数。
        scope, params = (" WHERE code=?", [code]) if code else ("", [])
        result["bar_rows"] = int(self.c.query_df(
            "SELECT count(*) n FROM stock_intraday_bar" + scope, params,
        ).iloc[0].n)
        return result
