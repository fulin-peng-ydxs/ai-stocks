"""分时来源证据与可修复性：采集、质量台账、修复和调度共用，不发在线请求。"""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime

import pandas as pd

from backend.common.exceptions import DataSourceError
from backend.config.request_snapshot import get_request_settings
from backend.datasource.base import SINA_INTRADAY_REQUEST_LIMIT
from backend.services import eod_dates
from backend.services.intraday_contract import PROVIDER_LABELS, required_times
from backend.services.intraday_subjects import providers_for

SOURCE_POLICY_VERSION = 2
SOURCE_REQUEST_LIMIT = SINA_INTRADAY_REQUEST_LIMIT


def missing_ranges(times) -> list[str]:
    """合并连续缺失分钟；午休和集合竞价间隔不连接、不补点。"""
    result = []
    start = last = None
    for clock in sorted(set(times)):
        minute = int(clock[:2]) * 60 + int(clock[3:])
        if last is not None and minute != last[0] + 1:
            result.append(start if start == last[1] else f"{start}–{last[1]}")
            start = None
        if start is None:
            start = clock
        last = (minute, clock)
    if last is not None:
        result.append(start if start == last[1] else f"{start}–{last[1]}")
    return result


def window_evidence(window: dict) -> dict:
    """观察完整响应，不能拿只过滤目标日期后的候选推断源窗口。"""
    rows = window.get("rows", [])
    by_day = {}
    for row in rows:
        by_day.setdefault(row[0][:10], set()).add(row[0][11:16])
    required = required_times(window.get("code"))
    return {
        "missing_by_day": {day: sorted(required - times) for day, times in by_day.items()},
        "required_counts": {day: len(required & times) for day, times in by_day.items()},
        "policy_version": SOURCE_POLICY_VERSION,
        "observed_at": window.get("fetched_at"),
        "first": window.get("raw_first") or (min(r[0] for r in rows) if rows else None),
        "last": window.get("raw_last") or (max(r[0] for r in rows) if rows else None),
        "raw_count": window.get("raw_count", len(rows)),
        "valid_count": len(rows),
        "request_limit": window.get("request_limit"),
        "request_years": window.get("request_years", []),
        "days": dict(Counter(r[0][:10] for r in rows)),
    }


class IntradayEvidence:
    """最近成功证据持久化；当日证据可用于跳过无效补采，过期只提示待核验。"""

    def __init__(self, client):
        self.c = client
        self.now = eod_dates.shanghai_now()
        self._cutoff = eod_dates.time_cutoff()
        self.calendar_ready = True
        try:
            self.session = str(eod_dates.latest_open_day(client, eod_dates.shanghai_now().date()))
            self.latest_closed = str(eod_dates.latest_open_day(client, self._cutoff))
        except DataSourceError:
            # 旧异常记录可能先于日历存在；只读台账可查看，不能据此认定窗口不可覆盖。
            self.calendar_ready = False
            self.session = str(eod_dates.shanghai_now().date())
            self.latest_closed = self.session

    def load(self, codes=None) -> dict:
        where, args = (
            ("", [])
            if codes is None
            else (
                " WHERE code IN (SELECT unnest(?::VARCHAR[]))",
                [codes],
            )
        )
        rows = self.c.query_df("SELECT * FROM stock_intraday_source_state" + where, args)
        result = {}
        for row in rows.to_dict("records"):
            row["evidence"] = (
                json.loads(row["evidence"]) if isinstance(row["evidence"], str) else {}
            )
            result[(row["code"], row["source"])] = row
        return result

    def record(self, code, windows, observations=None, *, task_id=None):
        observed = {
            w["source"]: {
                "outcome": "ok" if w.get("rows") else "empty",
                "evidence": window_evidence(w),
            }
            for w in windows
            if w.get("source")
        }
        observed.update(observations or {})
        now = datetime.now(UTC).replace(tzinfo=None)
        for source, item in observed.items():
            evidence = item.get("evidence") if item["outcome"] == "ok" else None
            # 网络错误没有新的窗口证据，不能清空上一成功响应。
            self.c.execute(
                "INSERT INTO stock_intraday_source_state VALUES (?,?,?,?,?,?,?) "
                "ON CONFLICT(code,source) DO UPDATE SET checked_at=excluded.checked_at,"
                "outcome=excluded.outcome,failure_reason=excluded.failure_reason,"
                "evidence=coalesce(excluded.evidence,stock_intraday_source_state.evidence),"
                "task_id=excluded.task_id",
                [
                    code,
                    source,
                    now,
                    item["outcome"],
                    item.get("error", ""),
                    json.dumps(evidence) if evidence is not None else None,
                    task_id,
                ],
            )

    def assess(self, code, day, missing, states, *, allow_fallback=True, recheck=False,
               defer_recent=False):
        """共享来源证据；仅采集定向补齐显式暂缓近期无改善响应，质检修复默认立即复查。"""
        now = eod_dates.shanghai_now()
        refresh_calendar = now.date() != self.now.date() or not self.calendar_ready
        if refresh_calendar:
            # 长任务跨交易会话后不能沿用旧会话的跳过证据；目标范围仍由任务检查点冻结。
            try:
                self.session = str(eod_dates.latest_open_day(self.c, now.date()))
                self.calendar_ready = True
            except DataSourceError:
                self.calendar_ready = False
        cutoff = eod_dates.time_cutoff()
        if cutoff != self._cutoff or refresh_calendar:
            try:
                self.latest_closed = str(eod_dates.latest_open_day(self.c, cutoff))
            except DataSourceError:
                self.calendar_ready = False
            self._cutoff = cutoff
        self.now = now
        recheck_interval = get_request_settings().intraday.source_recheck_interval_sec
        providers, observations, blocked, decisions, deferred = [], [], [], [], []
        unknown = False
        expected = required_times(code)
        required = missing or sorted(expected)
        for provider in providers_for(code, allow_fallback):
            retry_at = None
            state = states.get((code, provider), {})
            evidence = state.get("evidence", {})
            observed = evidence.get("observed_at")
            observed_day = (
                str(pd.Timestamp(observed).tz_convert(eod_dates.SHANGHAI).date())
                if observed
                else ""
            )
            fresh = (
                self.calendar_ready
                and observed_day >= self.session
                and evidence.get("policy_version") == SOURCE_POLICY_VERSION
                and (provider != "sina" or evidence.get("request_limit") == SOURCE_REQUEST_LIMIT)
                and evidence.get("first")
                and evidence.get("last")
                and state.get("outcome") == "ok"
            )
            if state:
                observations.append(
                    {
                        "source": provider,
                        **{k: v for k, v in evidence.items() if k != "missing_by_day"},
                        "missing_times": evidence.get("missing_by_day", {}).get(day),
                        "observed_at": pd.Timestamp(observed)
                        .tz_convert(eod_dates.SHANGHAI)
                        .isoformat()
                        if observed
                        else None,
                        "checked_at": pd.Timestamp(state["checked_at"])
                        .tz_localize("UTC")
                        .tz_convert(eod_dates.SHANGHAI)
                        .isoformat(),
                        "outcome": state.get("outcome"),
                        "failure_reason": state.get("failure_reason"),
                    }
                )
            if recheck or not fresh:
                providers.append(provider)
                unknown = True
                if recheck:
                    source_reason = "显式重新核验"
                elif state.get("outcome") == "error":
                    source_reason = f"最近请求失败：{str(state.get('failure_reason') or '未知错误')[:200]}"
                elif state.get("outcome") == "empty":
                    source_reason = "最近响应为空，不能据此判断无数据，需重新核验"
                elif observed_day and observed_day < self.session:
                    source_reason = f"最近成功响应日期 {observed_day}，证据已过期，需重新核验"
                else:
                    source_reason = "尚无有效取源证据，需核验"
            elif (
                provider == "ths"
                and int(day[:4]) in evidence.get("request_years", [])
                and all(f"{day} {clock}:00" < evidence["first"] for clock in required)
            ):
                # 年度路径已返回全响应，不能把年份误解为全年承诺；只跳过当会话无收益重复。
                blocked.append("outside_observed_window")
                source_reason = f"最近年度响应从 {evidence['first']} 开始，未覆盖待补分钟"
            elif (
                evidence.get("request_limit")
                and evidence.get("raw_count", 0) >= evidence["request_limit"]
                and all(f"{day} {clock}:00" < evidence["first"] for clock in required)
            ):
                # 仅达到本次条数且缺口全在响应起点之前，才有截断证据。
                # 尾部尚未就绪、少量返回和日内缺柱不能据此停止重试。
                boundary = str(evidence["first"])[:10] == day
                blocked.append("window_truncated" if boundary else "outside_observed_window")
                source_reason = (f"最近响应 {evidence['first']}～{evidence['last']}，"
                                 f"已达到本次 {evidence['request_limit']} 条，未覆盖待补分钟")
            elif (
                defer_recent
                and (day >= self.latest_closed or evidence["last"] < f"{day} 15:00:00")
                and recheck_interval > 0
                and missing
                and evidence.get("required_counts", {}).get(day, 0) <= len(expected) - len(missing)
                and 0 <= self.now.timestamp() - pd.Timestamp(observed).timestamp()
                < recheck_interval
            ):
                # 最新日仍可能补发，只延后重复请求，不把等待源更新解释为永久不可覆盖。
                retry_at = (pd.Timestamp(observed) + pd.Timedelta(seconds=recheck_interval))
                retry_at = retry_at.tz_convert(eod_dates.SHANGHAI).isoformat()
                reason_code = ("source_not_ready" if evidence["last"] < f"{day} 15:00:00"
                               else "recheck_deferred")
                deferred.append((retry_at, reason_code))
                source_reason = (f"源端待更新，最近响应截至 {evidence['last']}"
                                 if reason_code == "source_not_ready"
                                 else "最近响应未提供更好的整日候选")
                source_reason += f"；{retry_at} 后可复查，人工重新核验可立即请求"
            elif (
                day < self.session
                and evidence["last"] >= f"{day} 15:00:00"
                and day in evidence.get("missing_by_day", {})
                and missing
                and (
                    set(required).issubset(evidence["missing_by_day"][day])
                    or evidence.get("required_counts", {}).get(day, len(expected))
                    <= len(expected) - len(missing)
                )
            ):
                # 历史已收盘日：未提供待补分钟，或整日覆盖不优于已有归档，自动重复无收益。
                # 当日尚可能补发的缺柱仍可重试；历史证据跨会话过期，人工也可随时重新核验。
                boundary = (
                    evidence.get("request_limit")
                    and evidence.get("raw_count", 0) >= evidence["request_limit"]
                    and str(evidence["first"])[:10] == day
                    and any(f"{day} {clock}:00" < evidence["first"] for clock in required)
                )
                blocked.append("window_truncated" if boundary else "source_missing_minutes")
                source_reason = (f"最近响应 {evidence['first']}～{evidence['last']}，"
                                 "目标日未提供比现有归档更完整的整日候选")
            else:
                providers.append(provider)
                source_reason = (
                    f"最近响应截至 {evidence['last']}，尚未覆盖目标日 {day} 的待补分钟，需核验"
                    if evidence["last"] < f"{day} {min(required)}:00"
                    else "最近响应有补采机会"
                )
            decisions.append({"source": provider, "request": provider in providers,
                              "reason": source_reason, "next_retry_at": retry_at})
        status = (("needs_verification" if unknown else "available") if providers
                  else "deferred" if deferred else "unavailable")
        reason = (
            "来源暂待更新或复查，问题继续保留，可在复查时间到达后重试"
            if not providers and deferred else
            "最近有效响应未提供更完整的整日候选，保留问题，可手动重新核验"
            if not providers and "source_missing_minutes" in blocked
            else "当前来源响应未覆盖缺失分钟，保留历史问题，可手动重新核验"
            if not providers
            else "来源证据不足、已过期或最近请求失败，需要核验"
            if unknown
            else "当前来源响应范围覆盖待补分钟，可尝试补采"
        )
        # 同一解释供台账、修复日志及调度复用，不以笼统的“证据不足”掩盖来源差异。
        reason += "；" + "；".join(
            f"{PROVIDER_LABELS[item['source']]}：{item['reason']}" for item in decisions
        )
        return {
            "status": status,
            "can_repair": bool(providers),
            "retryable": bool(providers or deferred),
            "next_retry_at": min((item[0] for item in deferred), default=None),
            "providers": providers,
            "reason": reason,
            "reason_code": (deferred[0][1] if not providers and deferred else
                            blocked[0] if blocked else status),
            "sources": observations,
            "decisions": decisions,
        }
