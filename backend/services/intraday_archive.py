"""已收盘分时归档、覆盖与质量闭环；读取不触发写入，写入由异步任务互斥。"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from uuid import uuid4

import pandas as pd
import redis

from backend.config import get_settings
from backend.services import eod_dates
from backend.services.intraday_contract import (
    BAR_FIELDS,
    EXPECTED_TIMES,
    INTRADAY_ISSUE_TYPES,
    candidate_rank,
    normalize_intraday_params,
)
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
    """按股票分批处理，内存中最多保留一只股票的近期源窗口。"""

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

    def online_dates(self) -> list[str]:
        """源端近期窗口由真实日历决定，不能因本地日线落后而向历史平移。"""
        cutoff = eod_dates.resolve_end(self.c)
        rows = self.c.query_df(
            "SELECT trade_date FROM trade_calendar WHERE is_open AND trade_date<=? "
            "ORDER BY trade_date DESC LIMIT ?",
            [cutoff, get_settings().intraday.supported_trade_days],
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

    def collect(self, params=None, *, ctx=None):
        from backend.services.intraday_source import IntradaySourceService

        params = normalize_intraday_params(params)
        if not get_settings().intraday.enabled:
            raise ValueError("分时数据功能当前未启用")
        if ctx:
            ctx.check_cancel()
        scope = self._scope(params, ctx)
        self._register_monitoring(scope)
        quotes = self.quotes or IntradaySourceService(ctx=ctx)
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
            ctx.flush()
        errors = []
        failed_codes = dict(ctx.checkpoint.get("intraday_failed", {})) if ctx else {}
        for index, code in enumerate(scope["codes"]):
            if ctx:
                ctx.check_cancel()
            if code in done:
                continue
            if ctx:
                ctx.set_phase(
                    "分时采集", current_item=code, phase_done=index, phase_total=len(scope["codes"])
                )
                ctx.progress(
                    index / max(1, len(scope["codes"])),
                    f"分时采集 {index}/{len(scope['codes'])} · 正在处理 {code}",
                )
            expected = self._ensure_expected(code, scope)
            pending = (
                expected if scope["mode"] == "refetch" else expected[expected.status.ne("ready")]
            )
            stats["skipped"] += len(expected) - len(pending)
            online = self.online_dates()
            available = pending[
                pending.trade_date.map(lambda d, window=online: str(_day(d)) in window)
            ]
            unavailable = pending[~pending.index.isin(available.index)]
            stats["out_of_range"] += len(unavailable)
            outcomes = {"inserted": 0, "updated": 0, "unchanged": 0, "missing": 0}
            if ctx:
                ctx.log(
                    f"[{index + 1}/{len(scope['codes'])}] {code}：应查 {len(expected)} 日，"
                    f"已完整跳过 {len(expected) - len(pending)} 日，待取源 {len(available)} 日，"
                    f"窗口外 {len(unavailable)} 日"
                )
                ctx.flush()
            for row in unavailable.itertuples():
                self.write_day(
                    code,
                    str(_day(row.trade_date)),
                    [],
                    error="超出现有分钟源窗口，历史缺口保留待处理",
                    task_id=getattr(ctx, "tid", None),
                )
            technical_error = ""
            candidates = []
            if not available.empty:
                try:
                    window = quotes.fetch_window(code, [str(_day(d)) for d in available.trade_date])
                    candidates = window.get("candidates", [window])
                    if window.get("errors"):
                        technical_error = "；".join(window["errors"])
                        if len(errors) < 100:
                            errors.append({"code": code, "reason": technical_error})
                except Exception as exc:  # noqa: BLE001 -- 单股失败留证，取消必须穿透
                    if ctx:
                        ctx.check_cancel()
                    technical_error = f"{type(exc).__name__}: {str(exc)[:300]}"
                    if len(errors) < 100:
                        errors.append({"code": code, "reason": technical_error})
                    if ctx:
                        ctx.log(f"{code} 分时请求失败：{technical_error}", "warn")
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
            if not technical_error:
                done.add(code)
                failed_codes.pop(code, None)
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
                cover = self.c.query_df(
                    "SELECT count(*) FILTER(WHERE status='ready') complete_days,"
                    "count(*) FILTER(WHERE status='partial') partial_days,"
                    "count(*) FILTER(WHERE point_count=0) missing_days "
                    "FROM stock_intraday_coverage WHERE code=? AND trade_date BETWEEN ? AND ?",
                    [code, scope.get("starts", {}).get(code, scope["start"]), scope["end"]],
                ).iloc[0]
                message = (
                    f"{code} 落库：新增 {outcomes['inserted']} 日、更新 {outcomes['updated']} 日、"
                    f"未变化 {outcomes['unchanged']} 日；范围内完整 {int(cover.complete_days)} 日、"
                    f"部分 {int(cover.partial_days)} 日、缺失 {int(cover.missing_days)} 日"
                )
                if technical_error:
                    message += f"；取源未完成，未完成项保留重试资格：{technical_error}"
                ctx.log(message, "warn" if technical_error else "info")
                ctx.progress(
                    (index + 1) / max(1, len(scope["codes"])),
                    f"分时采集 {index + 1}/{len(scope['codes'])} · {code}",
                )
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
        if ctx:
            ctx.log("逐股采集结束：正在复检分时覆盖、非法数据及历史整日缺口…")
            ctx.flush()
        quality = self.sync(scope["codes"])
        return {
            "ok": stats["failed"] == 0,
            **stats,
            "errors": errors[:100],
            "target_end": scope["end"],
            "quality": quality,
            "message": f"分时采集完成：新增 {stats['inserted']}、更新 {stats['updated']}、"
            f"部分 {stats['partial']}、缺失 {stats['missing']}、源窗口外 {stats['out_of_range']}、技术失败 {stats['failed']}",
        }

    def _coverage_facts(self, codes=None):
        """按逐日覆盖监控；实际分钟结构另行扫描，杜绝只相信完成标记。"""
        expected_sql, args = self._coverage_sql(codes)
        return self.c.query_df(
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
            args + [sorted(EXPECTED_TIMES), codes, codes],
        )

    def issues(self, codes=None, *, facts=None):
        rows = self._coverage_facts(codes) if facts is None else facts
        online = set(self.online_dates()) if not rows.empty else set()
        result = []
        for row in rows.itertuples():
            kind = (
                "intraday_gap"
                if row.actual_count == 0
                else "intraday_partial"
                if row.expected_count < 240
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
                if row.failure_reason:
                    message += f"；{row.failure_reason}"
                if str(_day(row.trade_date)) not in online:
                    message += "；超出现有分钟源窗口，历史缺口保留待处理"
                result.append(self._issue(row.code, row.trade_date, kind, message, diag))
        for row in self.invalid_facts(codes).itertuples():
            result.append(
                self._issue(
                    row.code, row.trade_date, "intraday_invalid", "归档分钟结构或价格量额非法", {}
                )
            )
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
        # 质量扫描确认物理分钟变化后同步覆盖与修订；概览不能继续显示旧完成标记。
        facts = facts.copy()
        facts["actual_status"] = [
            "missing" if r.actual_count == 0 else "ready" if r.expected_count == 240 else "partial"
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
        expected_sql, args = self._coverage_sql([code] if code else None)
        frame = self.c.query_df(
            "SELECT min(monitoring_start) monitoring_start,max(trade_date) target_end,"
            "max(trade_date) FILTER(WHERE point_count>0) archive_end,"
            "count(DISTINCT code) stocks,count(*) expected_days,"
            "count(*) FILTER(WHERE status='ready') complete_days,"
            "count(*) FILTER(WHERE status='partial') partial_days,"
            "count(*) FILTER(WHERE point_count=0) missing_days "
            f"FROM ({expected_sql})",
            args,
        )
        return json.loads(frame.to_json(orient="records", date_format="iso"))[0]
