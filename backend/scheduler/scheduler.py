"""定时任务调度（重构）——用户自定义的多条定时任务，每条 = 任务类型 + 频率 + 参数。

- 定义持久化在 `scheduled_job` 表；调度器启动时加载所有 enabled 的 job 注册到 APScheduler，
  运行时增/删/改即时生效（免重启，复用同进程单例）。
- 触发 → 创建一条 async_task（trigger_source='scheduled' + job_id/job_name），任务中心据此
  展示「定时·{任务名}」并可筛选；与手动任务同一套执行/日志/续跑。
- `trading_day_only` 的任务在非交易日跳过；已有写任务在跑则本次跳过（写任务单例，不排队）。
- 频率：daily/weekly/monthly 预设 + cron 高级表达式，统一编译成 APScheduler CronTrigger。
- 失败仅记日志、不崩调度；下次仍按点触发（任务本身幂等）。
"""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from backend.common.exceptions import ConflictError, NotFoundError, ValidationError
from backend.common.logging import get_logger
from backend.common.timeutil import shanghai_now_naive
from backend.storage.duckdb_client import get_client
from backend.storage.task_runtime import (
    get_task_runtime_client,
    is_postgres_task_runtime,
    runtime_json_param,
    task_runtime_backend,
)

log = get_logger("scheduler")

_scheduler = None   # 进程内 APScheduler 单例（BackgroundScheduler）
_DEFAULT_AUDIT_CLEANUP_NAME = "审计日志清理"
_DEFAULT_AUDIT_CLEANUP_TIME = "03:30"

# 可配成定时任务的类型：原子采集/维护/质检 + 按问题类型动态恢复。
SCHEDULABLE_TASK_TYPES = (
    "update", "backfill", "ingest_date", "stock_ingest", "intraday_ingest", "recompute", "verify", "checkup", "fix", "enrich_basic",
    "audit_cleanup", "board", "stock_board_correlation", "limit_ladder_invalidate",
)
_WEEKDAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]   # 1..7 → APScheduler 名称
_WEEKDAY_CN = ["一", "二", "三", "四", "五", "六", "日"]
_FREQ_TYPES = ("daily", "weekly", "monthly", "cron")
_TRIGGER_MODES = ("time", "dependency")
_RESULT_CONDITIONS = ("success", "failure", "completion")
_DELAY_UNITS = {"second": 1, "minute": 60, "hour": 3600}
_MAX_DELAY_SECONDS = 30 * 24 * 3600
_MAX_RETRIES = 20
_DISPATCH_JOB_ID = "__schedule_dependency_dispatch__"
_LIMIT_LADDER_RECONCILE_JOB_ID = "__limit_ladder_reconcile__"
_limit_ladder_coordinator = None
# 同进程内串行化事件认领、目标启停/删除和任务创建，保证“停用取消等待事件”与分发互斥。
_EVENT_DISPATCH_LOCK = threading.RLock()


def _runtime_client():
    """Resolve runtime storage while preserving the historical DuckDB test seam."""
    return get_client() if task_runtime_backend() == "duckdb" else get_task_runtime_client()


def _condition_matches(condition: str | None, status: str) -> bool:
    """依赖结果口径：人工终止不属于失败或完成，不传播调度链。"""
    if status == "interrupted":
        return False
    return (
        (condition == "success" and status == "done")
        or (condition == "failure" and status == "failed")
        or (condition == "completion" and status in ("done", "failed"))
    )


def _normalize_delay(value: dict | None, *, field: str) -> dict:
    cfg = dict(value or {})
    amount = _strict_int(cfg.get("value", 0), field=field)
    unit = str(cfg.get("unit") or "minute")
    if amount < 0 or unit not in _DELAY_UNITS:
        raise ValueError(f"{field}须为非负整数，单位仅支持秒、分钟、小时")
    if amount * _DELAY_UNITS[unit] > _MAX_DELAY_SECONDS:
        raise ValueError(f"{field}不得超过 30 天")
    return {"value": amount, "unit": unit}


def _strict_int(value, *, field: str) -> int:
    """接受整数及 1.0/"1" 等等价值，拒绝小数、布尔值和非有限数。"""
    if isinstance(value, bool):
        raise ValueError(f"{field}须为整数")  # noqa: TRY004  统一映射为业务参数 400
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field}须为整数") from exc
    if not number.is_finite() or number != number.to_integral_value():
        raise ValueError(f"{field}须为整数")
    return int(number)


def _delay_seconds(value: dict | None) -> int:
    cfg = _normalize_delay(value, field="延迟时间")
    return int(cfg["value"]) * _DELAY_UNITS[cfg["unit"]]


def _normalize_retry(value: dict | None) -> dict:
    cfg = dict(value or {})
    enabled = cfg.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError("重试开关须为布尔值")  # noqa: TRY004  统一映射为业务参数 400
    condition = str(cfg.get("condition") or "failure")
    if condition not in _RESULT_CONDITIONS:
        raise ValueError(f"循环条件非法（可选 {_RESULT_CONDITIONS}）")
    delay = _normalize_delay(cfg.get("delay"), field="重试延迟")
    max_retries = _strict_int(cfg.get("max_retries", 1), field="最大重试次数")
    if enabled and not (1 <= max_retries <= _MAX_RETRIES):
        raise ValueError(f"最大重试次数须为 1-{_MAX_RETRIES}")
    return {
        "enabled": enabled,
        "condition": condition,
        "delay": delay,
        "max_retries": max_retries if enabled else max(1, min(max_retries, _MAX_RETRIES)),
    }


# ── 交易日判断（自愈：缺日历则补采再判，避免"未采到"误当"闭市"）─────────
def _is_trading_day(d: date) -> bool:
    """d 是否开市。查 trade_calendar；若 d 超出已采日历范围则先补采再判——
    交易日历只在采集流程里更新，而采集又在本判断之后才跑，二者会形成「日历停在上次采集日→
    判非交易日→流程跳过→日历永不前进」的死锁。此处自愈：缺这天且 d 已越过日历最大日时，
    先补采日历（数据源发布未来交易日）再复查，把"未采到"与"真闭市"区分开。"""
    import pandas as pd

    c = get_client()
    df = c.query_df("SELECT is_open FROM trade_calendar WHERE trade_date = ?", [d])
    if not df.empty:
        return bool(df.iloc[0]["is_open"])
    mx = c.query_df("SELECT max(trade_date) AS m FROM trade_calendar").iloc[0]["m"]
    if mx is not None and pd.Timestamp(mx).date() >= d:
        return False  # 日历已覆盖到 d 仍无此行 → 确属闭市（如周末/节假日）
    try:  # 日历未采到 d → 补采后复查（ingest_calendar 会尝试把上界延伸到下一自然年末）
        from backend.services.ingest import IngestionService
        IngestionService().ingest_calendar(d - timedelta(days=30), d)
        df = c.query_df("SELECT is_open FROM trade_calendar WHERE trade_date = ?", [d])
        return (not df.empty) and bool(df.iloc[0]["is_open"])
    except Exception as e:  # noqa: BLE001  补采失败：保守按非交易日跳过，不崩调度
        log.warning("[scheduler] %s 不在日历内且补采失败，按非交易日跳过: %s", d, e)
        return False


# ── 频率：编译成 APScheduler 触发器 + 生成人话描述 ───────────────────────
def _parse_hm(t: str | None) -> tuple[int, int]:
    h, m = str(t or "0:0").split(":")[:2]
    h, m = int(h), int(m)
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(f"时间非法: {t}（须 HH:MM，时 0-23 分 0-59）")
    return h, m


def compile_trigger(freq_type: str, freq_config: dict | None):
    """freq_type/freq_config → APScheduler CronTrigger（非法即抛 ValueError）。"""
    from apscheduler.triggers.cron import CronTrigger
    cfg = freq_config or {}
    if freq_type == "daily":
        h, m = _parse_hm(cfg.get("time"))
        return CronTrigger(hour=h, minute=m)
    if freq_type == "weekly":
        h, m = _parse_hm(cfg.get("time"))
        wds = [int(w) for w in (cfg.get("weekdays") or [])]
        if not wds or any(not (1 <= w <= 7) for w in wds):
            raise ValueError("每周任务需选择 1-7 的星期")
        names = ",".join(_WEEKDAY_NAMES[w - 1] for w in sorted(set(wds)))
        return CronTrigger(day_of_week=names, hour=h, minute=m)
    if freq_type == "monthly":
        h, m = _parse_hm(cfg.get("time"))
        day = int(cfg.get("day", 1))
        if not (1 <= day <= 28):
            raise ValueError("每月任务的日期须为 1-28（避开 29-31 的跨月不确定）")
        return CronTrigger(day=day, hour=h, minute=m)
    if freq_type == "cron":
        expr = str(cfg.get("cron") or "").strip()
        if not expr:
            raise ValueError("cron 表达式不能为空")
        return CronTrigger.from_crontab(expr)
    raise ValueError(f"未知频率类型: {freq_type}（可选 {_FREQ_TYPES}）")


def freq_text(freq_type: str, freq_config: dict | None) -> str:
    """频率的人话描述，供列表展示。"""
    cfg = freq_config or {}
    if freq_type == "daily":
        return f"每天 {cfg.get('time', '')}"
    if freq_type == "weekly":
        wds = "、".join("周" + _WEEKDAY_CN[int(w) - 1] for w in (cfg.get("weekdays") or []))
        return f"每{wds} {cfg.get('time', '')}"
    if freq_type == "monthly":
        return f"每月 {cfg.get('day', 1)} 号 {cfg.get('time', '')}"
    if freq_type == "cron":
        return f"cron（{cfg.get('cron', '')}）"
    return freq_type


# ── APScheduler 引擎：注册 / 注销 / 触发 ─────────────────────────────────
def _ensure_scheduler():
    global _scheduler
    if _scheduler is None:
        from apscheduler.schedulers.background import BackgroundScheduler
        _scheduler = BackgroundScheduler()
    return _scheduler


def register_job(job: dict) -> None:
    """把一条定时任务注册/重注册到调度器（按 freq 编译触发器）。"""
    if job.get("trigger_mode", "time") != "time":
        return
    sched = _ensure_scheduler()
    trigger = compile_trigger(job["freq_type"], job.get("freq_config"))
    sched.add_job(_fire_job, trigger, args=[job["id"]], id=job["id"],
                  replace_existing=True, misfire_grace_time=3600)
    if not sched.running:
        sched.start()


def unregister_job(job_id: str) -> None:
    sched = _ensure_scheduler()
    if sched.running and sched.get_job(job_id):
        sched.remove_job(job_id)


def next_run_time(job_id: str) -> str | None:
    if _scheduler is None or not _scheduler.running:
        return None
    j = _scheduler.get_job(job_id)
    return str(j.next_run_time) if j and j.next_run_time else None


def _fire_job(job_id: str) -> None:
    """APScheduler 到点回调：读最新 job 定义 → 交易日判断 → 创建 async 任务。"""
    from backend.services.async_task import AsyncTaskService, ConcurrentTaskError
    from backend.services.audit_service import AuditService

    svc = ScheduledJobService()
    job = svc.get(job_id)
    if not job or not job["enabled"]:
        return
    name = job["name"]
    if job["trading_day_only"] and not _is_trading_day(shanghai_now_naive().date()):
        log.info("[scheduler] 定时任务「%s」%s 非交易日，跳过", name, shanghai_now_naive().date())
        AuditService().record_scheduler_event(
            action="skip",
            result="denied",
            status="skipped",
            job_id=job_id,
            job_name=name,
            task_type=job.get("task_type"),
            error_summary="非交易日跳过",
        )
        return
    try:
        tid = AsyncTaskService().create(job["task_type"], job.get("params") or {},
                                        trigger_source="scheduled", job_id=job_id, job_name=name)
        svc.set_last_run(job_id, tid)
        AuditService().record_scheduler_event(
            action="trigger",
            result="success",
            status="completed",
            job_id=job_id,
            job_name=name,
            task_type=job.get("task_type"),
            task_id=tid,
        )
        log.info("[scheduler] 定时任务「%s」已触发: %s", name, tid)
    except ConcurrentTaskError as e:
        log.warning("[scheduler] 定时任务「%s」跳过：已有写任务在运行（%s）", name, e.task_type)
        AuditService().record_scheduler_event(
            action="skip",
            result="denied",
            status="skipped",
            job_id=job_id,
            job_name=name,
            task_type=job.get("task_type"),
            error_summary=f"已有写任务在运行：{e.task_type}（{e.running_id}）",
        )
    except Exception as e:  # noqa: BLE001
        log.error("[scheduler] 定时任务「%s」触发异常: %s", name, e)
        AuditService().record_scheduler_event(
            action="trigger",
            result="failed",
            status="failed",
            job_id=job_id,
            job_name=name,
            task_type=job.get("task_type"),
            error_summary=str(e),
        )


def _register_dependency_dispatcher() -> None:
    """注册持久化依赖事件分发器；独立于是否存在时间任务，启动后始终运行。"""
    from apscheduler.triggers.interval import IntervalTrigger

    sched = _ensure_scheduler()
    sched.add_job(
        dispatch_due_events,
        IntervalTrigger(seconds=2),
        id=_DISPATCH_JOB_ID,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    sched.add_job(
        _reconcile_limit_ladder_tasks,
        IntervalTrigger(seconds=30),
        id=_LIMIT_LADDER_RECONCILE_JOB_ID,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    if not sched.running:
        sched.start()


def _reconcile_limit_ladder_tasks() -> None:
    """Best-effort periodic mirror/outbox delivery; coordinator owns the PG advisory lock."""
    global _limit_ladder_coordinator
    try:
        from backend.services.limit_ladder_task_coordinator import LimitLadderTaskCoordinator

        # Reuse the service so the 30-second loop does not rerun all idempotent DuckDB DDL.
        if _limit_ladder_coordinator is None:
            _limit_ladder_coordinator = LimitLadderTaskCoordinator()
        _limit_ladder_coordinator.reconcile()
    except Exception as exc:  # noqa: BLE001 -- scheduler loop must remain healthy
        log.warning("[scheduler] 连板天梯任务对账失败: %s", exc)


def _ensure_default_audit_cleanup_job() -> None:
    """确保审计清理作为普通 scheduled_job 存在，从而频率/启停都可在任务调度页维护。"""
    svc = ScheduledJobService()
    if any(j["task_type"] == "audit_cleanup" for j in svc.list()):
        return
    svc.create(
        name=_DEFAULT_AUDIT_CLEANUP_NAME,
        task_type="audit_cleanup",
        params={},
        freq_type="daily",
        freq_config={"time": _DEFAULT_AUDIT_CLEANUP_TIME},
        trading_day_only=False,
        enabled=True,
    )
    log.info("[scheduler] 已创建默认定时任务「%s」（每天 %s）",
             _DEFAULT_AUDIT_CLEANUP_NAME, _DEFAULT_AUDIT_CLEANUP_TIME)


def register_platform_jobs() -> None:
    """兼容旧调用：平台内置任务统一落到 scheduled_job，避免隐藏的固定调度。"""
    _ensure_default_audit_cleanup_job()


# ── 启动 / 停止 ──────────────────────────────────────────────────────────
def start_scheduler():
    """服务启动调用：迁移旧单一配置 → 加载所有 enabled 定时任务并注册。"""
    try:
        _migrate_legacy_config()
    except Exception as e:  # noqa: BLE001
        log.warning("[scheduler] 旧调度配置迁移跳过: %s", e)
    try:
        register_platform_jobs()
    except Exception as e:  # noqa: BLE001
        log.warning("[scheduler] 创建默认审计清理定时任务失败，已跳过: %s", e)
    svc = ScheduledJobService()
    svc.recover_events()
    _register_dependency_dispatcher()
    jobs = [j for j in svc.list() if j["enabled"] and j.get("trigger_mode") == "time"]
    for j in jobs:
        try:
            register_job(j)
        except Exception as e:  # noqa: BLE001
            log.error("[scheduler] 注册定时任务「%s」失败: %s", j.get("name"), e)
    # 启动后立即处理已经到期的依赖事件，无需等待首个轮询周期。
    dispatch_due_events()
    log.info("[scheduler] 已加载 %d 条启用的时间任务，依赖事件分发器已启动", len(jobs))
    return _scheduler


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
    _scheduler = None


def status() -> dict:
    """调度总览（供数据总览页风险摘要用）：是否有启用任务 / 数量 / 最近一次触发时间。"""
    jobs = ScheduledJobService().list()
    enabled = [j for j in jobs if j["enabled"]]
    nexts = [next_run_time(j["id"]) for j in enabled if j.get("trigger_mode") == "time"]
    nexts = sorted(t for t in nexts if t)
    return {
        "enabled": bool(enabled),
        "jobs_total": len(jobs),
        "jobs_enabled": len(enabled),
        "next_run_time": nexts[0] if nexts else None,
        "running": _scheduler is not None and _scheduler.running,
    }


def _migrate_legacy_config() -> None:
    """旧版「单一每日任务」配置 → 迁移成一条 update 定时任务。

    幂等靠「消费即删除」：迁移后删掉旧 app_config 的 scheduler.* 键，下次启动读不到即不再触发。
    （app_config 白名单不接受自定义标记键，故不用迁移标志位而用消费删除。）
    """
    from backend.storage.app_config import AppConfigRepo
    repo = AppConfigRepo()
    ov = repo.get_overrides()
    if not ov.get("scheduler.enabled"):
        return  # 旧配置未开过 / 已迁移消费掉 → 无需处理
    svc = ScheduledJobService()
    if not svc.list():  # 仅当还没有任何定时任务时迁移，避免覆盖用户已建的
        h = int(ov.get("scheduler.daily_cron_hour", 18) or 18)
        m = int(ov.get("scheduler.daily_cron_minute", 0) or 0)
        svc.create(name="每日增量更新", task_type="update", params={},
                   freq_type="daily", freq_config={"time": f"{h:02d}:{m:02d}"},
                   trading_day_only=True, enabled=True)
        log.info("[scheduler] 已将旧每日配置迁移为定时任务「每日增量更新」（每天 %02d:%02d）", h, m)
    for k in ("scheduler.enabled", "scheduler.daily_cron_hour", "scheduler.daily_cron_minute"):
        repo.reset(k)  # 消费旧键，迁移只发生一次


# ── 定时任务定义的 CRUD（scheduled_job 表）──────────────────────────────
class ScheduledJobService:
    def __init__(self, client=None, *, initialize: bool = True):
        self.c = client or _runtime_client()
        if initialize and not is_postgres_task_runtime(self.c):
            from backend.storage.ddl import init_db

            init_db(self.c)

    @staticmethod
    def _row(r) -> dict:
        import pandas as pd
        d = r.to_dict() if hasattr(r, "to_dict") else dict(r)
        for k in ("created_at", "updated_at", "last_run_at", "next_dependency_run_at"):
            v = d.get(k)
            d[k] = None if v is None or str(v) == "NaT" else str(v)
        for key in (
            "dependency_job_name", "dependency_job_id", "dependency_condition", "dependency_order",
            "freq_type", "last_task_id",
        ):
            if d.get(key) is not None and pd.isna(d[key]):
                d[key] = None
        d["enabled"] = bool(d.get("enabled"))
        d["trading_day_only"] = bool(d.get("trading_day_only"))
        for k in ("params", "freq_config", "dependency_delay", "retry_config"):
            if d.get(k) is not None and not isinstance(d.get(k), (dict, list)) and pd.isna(d[k]):
                d[k] = None
            if d.get(k):
                try:
                    d[k] = json.loads(d[k])
                except (ValueError, TypeError):
                    pass
        d["trigger_mode"] = d.get("trigger_mode") or "time"
        d["dependency_delay"] = d.get("dependency_delay") or {"value": 0, "unit": "minute"}
        d["retry_config"] = d.get("retry_config") or _normalize_retry(None)
        d["freq_text"] = freq_text(d.get("freq_type"), d.get("freq_config")) \
            if d["trigger_mode"] == "time" else "依赖触发"
        if d["trigger_mode"] == "time":
            d["trigger_text"] = d["freq_text"]
        else:
            condition = {"success": "成功后", "failure": "失败后", "completion": "完成后"}.get(
                d.get("dependency_condition"), d.get("dependency_condition") or "")
            delay = d["dependency_delay"]
            unit = {"second": "秒", "minute": "分钟", "hour": "小时"}.get(delay.get("unit"), "")
            parents = d.get("dependency_jobs") or []
            prefix = "、".join(item["name"] for item in parents) \
                or d.get("dependency_job_name") or d.get("dependency_job_id") or "上游任务"
            if len(parents) > 1:
                prefix = f"任一上游（{prefix}）"
            suffix = "立即" if int(delay.get("value", 0)) == 0 else f"延迟{delay.get('value')}{unit}"
            d["trigger_text"] = f"{prefix}·{condition}，{suffix}"
        d["next_run_time"] = next_run_time(d["id"]) \
            if d["enabled"] and d["trigger_mode"] == "time" else d.get("next_dependency_run_at")
        d["waiting_trigger_count"] = int(d.get("waiting_trigger_count") or 0)
        _ = pd  # 仅为静态可读
        return d

    def _rows(self, df) -> list[dict]:
        """批量补齐上游候选与选值，分页列表不逐行查询关系。"""
        if df.empty:
            return []
        job_ids = df["id"].astype(str).tolist()
        parents = self.c.query_df(
            "SELECT d.downstream_job_id, u.id, u.name, u.enabled "
            "FROM scheduled_job_dependency d JOIN scheduled_job u ON u.id=d.upstream_job_id "
            f"WHERE d.downstream_job_id IN ({','.join('?' for _ in job_ids)}) "
            "ORDER BY lower(u.name), u.id", job_ids)
        grouped: dict[str, list[dict]] = {}
        for _, row in parents.iterrows():
            grouped.setdefault(str(row["downstream_job_id"]), []).append({
                "id": str(row["id"]), "name": str(row["name"]), "enabled": bool(row["enabled"]),
            })
        result = []
        for _, row in df.iterrows():
            item = row.to_dict()
            item["dependency_jobs"] = grouped.get(str(row["id"]), [])
            item["dependency_job_ids"] = [parent["id"] for parent in item["dependency_jobs"]]
            result.append(self._row(item))
        return result

    def list(self) -> list[dict]:
        df = self.c.query_df(
            "SELECT j.*, u.name AS dependency_job_name, "
            "(SELECT count(*) FROM scheduled_trigger_event e WHERE e.target_job_id=j.id "
            " AND e.status IN ('waiting','dispatching')) AS waiting_trigger_count, "
            "(SELECT min(due_at) FROM scheduled_trigger_event e WHERE e.target_job_id=j.id "
            " AND e.status IN ('waiting','dispatching')) AS next_dependency_run_at "
            "FROM scheduled_job j LEFT JOIN ("
            "SELECT d.downstream_job_id, string_agg(p.name, '、' ORDER BY p.name, p.id) AS name "
            "FROM scheduled_job_dependency d JOIN scheduled_job p ON p.id=d.upstream_job_id "
            "GROUP BY d.downstream_job_id) u ON u.downstream_job_id=j.id "
            "ORDER BY j.created_at")
        return self._rows(df)

    def _frequency_order_sql(self, direction: str) -> str:
        """Return a cross-runtime frequency order matching the UI's configured frequency fields."""
        if is_postgres_task_runtime(self.c):
            def text_value(key: str) -> str:
                return f"j.freq_config->>'{key}'"

            def weekday(index: int) -> str:
                return f"COALESCE((j.freq_config->'weekdays'->>{index})::INTEGER, 0)"

            month_day = "COALESCE((j.freq_config->>'day')::INTEGER, 1)"
        else:
            def text_value(key: str) -> str:
                return (
                    "json_extract_string(try_cast(j.freq_config AS JSON), "
                    f"'$.{key}')"
                )

            def weekday(index: int) -> str:
                return (
                    "COALESCE(try_cast(json_extract_string(try_cast(j.freq_config AS JSON), "
                    f"'$.weekdays[{index}]') AS INTEGER), 0)"
                )

            month_day = (
                "COALESCE(try_cast(json_extract_string(try_cast(j.freq_config AS JSON), "
                "'$.day') AS INTEGER), 1)"
            )

        rank = (
            "CASE WHEN j.trigger_mode='dependency' OR j.freq_type IS NULL THEN 4 "
            "WHEN j.freq_type='daily' THEN 0 WHEN j.freq_type='weekly' THEN 1 "
            "WHEN j.freq_type='monthly' THEN 2 WHEN j.freq_type='cron' THEN 3 ELSE 4 END"
        )
        parts = [rank]
        parts.extend(
            f"CASE WHEN j.freq_type='weekly' THEN {weekday(index)} ELSE 0 END"
            for index in range(7)
        )
        parts.extend([
            f"CASE WHEN j.freq_type='monthly' THEN {month_day} ELSE 0 END",
            (
                "CASE "
                f"WHEN j.freq_type='cron' THEN trim(COALESCE({text_value('cron')}, '')) "
                "WHEN j.trigger_mode='dependency' OR j.freq_type IS NULL "
                "THEN lower(COALESCE(u.name, j.dependency_job_id, '')) "
                f"ELSE COALESCE({text_value('time')}, '') END"
            ),
            "COALESCE(j.dependency_condition, '')",
        ])
        return ", ".join(f"{part} {direction}" for part in parts)

    def list_page(self, *, page: int, size: int, sort_by: str, sort_order: str) -> dict:
        """Paginate scheduled jobs in storage; the scheduler's internal list() remains unpaged."""
        page = max(1, int(page))
        size = max(1, min(int(size), 200))
        direction = "ASC" if str(sort_order).lower() == "asc" else "DESC"
        if sort_by == "freq":
            primary_order = self._frequency_order_sql(direction)
        else:
            primary_order = f"lower(j.name) {direction}"
        total = int(self.c.query_df(
            "SELECT count(*) AS n FROM scheduled_job",
        ).iloc[0]["n"])
        df = self.c.query_df(
            "SELECT j.*, u.name AS dependency_job_name, "
            "(SELECT count(*) FROM scheduled_trigger_event e WHERE e.target_job_id=j.id "
            " AND e.status IN ('waiting','dispatching')) AS waiting_trigger_count, "
            "(SELECT min(due_at) FROM scheduled_trigger_event e WHERE e.target_job_id=j.id "
            " AND e.status IN ('waiting','dispatching')) AS next_dependency_run_at "
            "FROM scheduled_job j LEFT JOIN ("
            "SELECT d.downstream_job_id, string_agg(p.name, '、' ORDER BY p.name, p.id) AS name "
            "FROM scheduled_job_dependency d JOIN scheduled_job p ON p.id=d.upstream_job_id "
            "GROUP BY d.downstream_job_id) u ON u.downstream_job_id=j.id "
            f"ORDER BY {primary_order}, lower(j.name) {direction}, j.id {direction} "
            "LIMIT ? OFFSET ?",
            [size, (page - 1) * size],
        )
        return {
            "jobs": self._rows(df),
            "total": total,
            "page": page,
            "size": size,
        }

    def list_options(self, *, query: str = "", limit: int = 50) -> list[dict]:
        """Return lightweight dependency candidates for the remote select."""
        query = str(query or "").strip().lower()
        limit = max(1, min(int(limit), 100))
        where = "WHERE lower(name) LIKE ?" if query else ""
        params: list = [f"%{query}%"] if query else []
        df = self.c.query_df(
            f"SELECT id, name, enabled FROM scheduled_job {where} "
            "ORDER BY lower(name), id LIMIT ?",
            [*params, limit],
        )
        return [
            {"id": str(row["id"]), "name": str(row["name"]), "enabled": bool(row["enabled"])}
            for _, row in df.iterrows()
        ]

    def get(self, jid: str) -> dict | None:
        df = self.c.query_df(
            "SELECT j.*, u.name AS dependency_job_name, "
            "(SELECT count(*) FROM scheduled_trigger_event e WHERE e.target_job_id=j.id "
            " AND e.status IN ('waiting','dispatching')) AS waiting_trigger_count, "
            "(SELECT min(due_at) FROM scheduled_trigger_event e WHERE e.target_job_id=j.id "
            " AND e.status IN ('waiting','dispatching')) AS next_dependency_run_at "
            "FROM scheduled_job j LEFT JOIN ("
            "SELECT d.downstream_job_id, string_agg(p.name, '、' ORDER BY p.name, p.id) AS name "
            "FROM scheduled_job_dependency d JOIN scheduled_job p ON p.id=d.upstream_job_id "
            "GROUP BY d.downstream_job_id) u ON u.downstream_job_id=j.id "
            "WHERE j.id=?", [jid])
        return None if df.empty else self._rows(df)[0]

    def downstream(self, jid: str) -> dict:
        """完整读取直接下游；主表分页和启停状态不缩小排序范围。"""
        with _EVENT_DISPATCH_LOCK:
            if not self.get(jid):
                raise NotFoundError("调度任务不存在")
            rows = self.c.query_df(
                "SELECT j.*, d.dependency_order AS edge_order FROM scheduled_job j "
                "JOIN scheduled_job_dependency d ON d.downstream_job_id=j.id "
                "WHERE j.trigger_mode='dependency' AND d.upstream_job_id=? "
                "ORDER BY d.dependency_order, j.created_at, j.id", [jid])
            jobs = self._rows(rows)
            for job in jobs:
                job["dependency_order"] = int(job.pop("edge_order"))
            # 运行时间和启停不改变关系版本，避免任务自动运行造成无意义的保存冲突。
            relation = [(job["id"], job.get("dependency_order")) for job in jobs]
            revision = hashlib.sha256(json.dumps(relation, default=str).encode()).hexdigest()
            return {"jobs": jobs, "revision": revision}

    def reorder_downstream(self, jid: str, job_ids: list[str], revision: str) -> dict:
        """校验完整兄弟集合并原子保存；等待事件的顺序快照不回写。"""
        with _EVENT_DISPATCH_LOCK:
            current = self.downstream(jid)
            if revision != current["revision"]:
                raise ConflictError("下游关系或顺序已变化，请刷新后重新调整")
            actual = {job["id"] for job in current["jobs"]}
            if len(job_ids) != len(set(job_ids)) or set(job_ids) != actual:
                raise ValidationError("请提交全部直接下游且每个任务只出现一次")
            if job_ids:
                now = shanghai_now_naive()
                with self.c.transaction():
                    self.c.executemany(
                        "UPDATE scheduled_job_dependency SET dependency_order=? "
                        "WHERE downstream_job_id=? AND upstream_job_id=?",
                        [(index, child, jid) for index, child in enumerate(job_ids)],
                    )
                    # 单上游旧字段仅作为兼容投影，运行与排序均读取依赖边。
                    self.c.executemany(
                        "UPDATE scheduled_job SET dependency_order=?, updated_at=? "
                        "WHERE id=? AND dependency_job_id=?",
                        [(index, now, child, jid) for index, child in enumerate(job_ids)],
                    )
            return self.downstream(jid)

    def _validate(self, jid: str, task_type: str, params: dict | None,
                  freq_type: str | None, freq_config: dict | None,
                  trigger_mode: str, dependency_job_ids: list[str],
                  dependency_condition: str | None, dependency_delay: dict | None,
                  retry_config: dict | None) -> tuple[dict, dict, dict]:
        normalized_params = dict(params or {})
        if task_type not in SCHEDULABLE_TASK_TYPES:
            raise ValueError(f"该任务类型不支持定时: {task_type}（可选 {SCHEDULABLE_TASK_TYPES}）")
        if task_type == "fix":
            from backend.dataquality.checker import QUALITY_ISSUE_TYPES

            fix_params = normalized_params
            issue_type = str(fix_params.get("issue_type") or "").strip()
            if issue_type not in QUALITY_ISSUE_TYPES:
                raise ValueError(f"质检问题恢复需选择问题类型（可选 {QUALITY_ISSUE_TYPES}）")
            if fix_params.get("issue_id") is not None or fix_params.get("issue_ids"):
                raise ValueError("定时恢复按问题类型动态取数，不接受固定问题 ID")
        if task_type == "board":
            from backend.services.board_ingest import (
                normalize_board_date_range,
                normalize_board_force_current_day,
                normalize_board_stages,
            )

            mode = str(normalized_params.get("mode") or "update")
            if mode not in ("update", "backfill"):
                raise ValueError("板块定时采集模式仅支持 update/backfill")
            normalized_params["mode"] = mode
            # board_type 提前白名单校验（避免非法值留到运行期才在 ingest_board 抛错）
            bt = normalized_params.get("board_type")
            if bt is not None and bt not in ("concept", "industry"):
                raise ValueError("板块定时采集的 board_type 仅支持 concept/industry")
            stages = normalize_board_stages(normalized_params.get("only"))
            if stages is None:
                normalized_params.pop("only", None)
            else:
                normalized_params["only"] = stages
            force_members = normalized_params.get("force_members")
            if force_members is not None and not isinstance(force_members, bool):
                raise ValueError("板块定时采集的 force_members 必须是布尔值")
            force_current_day = normalize_board_force_current_day(
                mode, normalized_params.get("force_current_day"),
            )
            normalize_board_date_range(
                mode, normalized_params.get("date_start"), normalized_params.get("date_end"),
                force_current_day,
            )
        if task_type == "intraday_ingest":
            from backend.services.intraday_contract import normalize_intraday_params
            normalized_params = normalize_intraday_params(normalized_params)
        if task_type == "stock_ingest":
            from backend.services.stock_ingest import normalize_stock_ingest_params

            normalized_params = normalize_stock_ingest_params(normalized_params)
        if task_type == "stock_board_correlation":
            from backend.services.stock_board_correlation import normalize_correlation_task_params

            normalized_params = normalize_correlation_task_params(
                normalized_params, client=get_client())
        if task_type == "recompute":
            from backend.services.result_maintenance import normalize_score_invalidation_params

            normalized_params = normalize_score_invalidation_params(normalized_params)
        if task_type == "limit_ladder_invalidate":
            from backend.services.result_maintenance import normalize_ladder_invalidation_params

            normalized_params = normalize_ladder_invalidation_params(normalized_params)
        if trigger_mode not in _TRIGGER_MODES:
            raise ValueError(f"未知触发方式: {trigger_mode}（可选 {_TRIGGER_MODES}）")
        delay = _normalize_delay(dependency_delay, field="依赖延迟")
        retry = _normalize_retry(retry_config)
        if trigger_mode == "time":
            if freq_type not in _FREQ_TYPES:
                raise ValueError(f"未知频率类型: {freq_type}（可选 {_FREQ_TYPES}）")
            compile_trigger(str(freq_type), freq_config)
        else:
            if not dependency_job_ids:
                raise ValueError("依赖触发必须选择上游任务")
            if jid in dependency_job_ids:
                raise ValueError("任务不能直接依赖自己；循环执行请使用自身重试")
            placeholders = ','.join('?' for _ in dependency_job_ids)
            parents = self.c.query_df(
                f"SELECT id FROM scheduled_job WHERE id IN ({placeholders})", dependency_job_ids)
            if len(parents) != len(dependency_job_ids):
                raise ValueError("上游任务不存在，请刷新后重新选择")
            if dependency_condition not in _RESULT_CONDITIONS:
                raise ValueError(f"依赖结果条件非法（可选 {_RESULT_CONDITIONS}）")
            self._validate_no_cycle(jid, dependency_job_ids)
        return normalized_params, delay, retry

    def _validate_no_cycle(self, jid: str, dependency_job_ids: list[str]) -> None:
        """遍历多上游图；共享祖先不是环，所有分支都必须检查。"""
        from collections import defaultdict

        parents: dict[str, list[str]] = defaultdict(list)
        edges = self.c.query_df(
            "SELECT upstream_job_id, downstream_job_id FROM scheduled_job_dependency")
        for _, edge in edges.iterrows():
            parents[str(edge["downstream_job_id"])].append(str(edge["upstream_job_id"]))
        pending = [(parent, [jid, parent]) for parent in dependency_job_ids]
        visited: set[str] = set()
        while pending:
            current, chain = pending.pop()
            if current == jid:
                names = {job["id"]: job["name"] for job in self.c.query_df(
                    "SELECT id, name FROM scheduled_job").to_dict("records")}
                raise ValueError("检测到循环依赖：" + " → ".join(names.get(x, x) for x in chain))
            if current in visited:
                continue
            visited.add(current)
            pending.extend((parent, [*chain, parent]) for parent in parents[current])

    @staticmethod
    def _dependency_ids(trigger_mode: str, legacy_id: str | None,
                        selected: list[str] | None) -> list[str]:
        """数组为权威输入；缺省数组时兼容旧客户端单上游，显式空数组仍参与校验。"""
        if trigger_mode != "dependency":
            return []
        values = selected if selected is not None else ([legacy_id] if legacy_id else [])
        if any(not isinstance(item, str) or not item.strip() for item in values):
            raise ValueError("上游任务标识不能为空")
        return sorted({item.strip() for item in values})

    def _save_dependencies(self, jid: str, parent_ids: list[str]) -> None:
        """与任务定义在同一事务保存；保留仍存在的边顺序，新增边追加到各上游末尾。"""
        existing = self.c.query_df(
            "SELECT upstream_job_id, dependency_order FROM scheduled_job_dependency "
            "WHERE downstream_job_id=?", [jid])
        orders = {str(row["upstream_job_id"]): int(row["dependency_order"])
                  for _, row in existing.iterrows()}
        added = [parent for parent in parent_ids if parent not in orders]
        if added:
            # 一次查询各新增上游的末尾位置，避免多选数量增加时产生 N+1 查询。
            positions = self.c.query_df(
                "SELECT upstream_job_id, max(dependency_order)+1 AS position "
                "FROM scheduled_job_dependency "
                f"WHERE upstream_job_id IN ({','.join('?' for _ in added)}) "
                "GROUP BY upstream_job_id", added)
            orders.update({str(row["upstream_job_id"]): int(row["position"])
                           for _, row in positions.iterrows()})
        self.c.execute("DELETE FROM scheduled_job_dependency WHERE downstream_job_id=?", [jid])
        saved_orders = {parent: orders.get(parent, 0) for parent in parent_ids}
        if parent_ids:
            self.c.executemany(
                "INSERT INTO scheduled_job_dependency "
                "(upstream_job_id, downstream_job_id, dependency_order) VALUES (?,?,?)",
                [(parent, jid, saved_orders[parent]) for parent in parent_ids])
        # 存量字段只投影一个稳定上游，供旧接口消费者及升级补缺读取。
        primary = parent_ids[0] if parent_ids else None
        self.c.execute(
            "UPDATE scheduled_job SET dependency_job_id=?, dependency_order=? WHERE id=?",
            [primary, saved_orders.get(primary), jid])

    def create(self, *, name: str, task_type: str, params: dict | None,
               freq_type: str | None, freq_config: dict | None,
               trading_day_only: bool, enabled: bool,
               trigger_mode: str = "time", dependency_job_id: str | None = None,
               dependency_job_ids: list[str] | None = None,
               dependency_condition: str | None = None, dependency_delay: dict | None = None,
               retry_config: dict | None = None) -> dict:
        with _EVENT_DISPATCH_LOCK:
            if not (name or "").strip():
                raise ValueError("任务名称不能为空")
            jid = f"job_{shanghai_now_naive().strftime('%Y%m%d%H%M%S%f')}"
            parent_ids = self._dependency_ids(trigger_mode, dependency_job_id, dependency_job_ids)
            params, dependency_delay, retry_config = self._validate(
                jid, task_type, params, freq_type, freq_config, trigger_mode,
                parent_ids, dependency_condition, dependency_delay, retry_config)
            now = shanghai_now_naive()
            with self.c.transaction():
                self.c.execute(
                    "INSERT INTO scheduled_job (id, name, task_type, params, "
                    "freq_type, freq_config, "
                    "trigger_mode, dependency_job_id, dependency_order, dependency_condition, "
                    "dependency_delay, "
                    "retry_config, trading_day_only, enabled, last_run_at, last_task_id, "
                    "created_at, "
                    "updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [jid, name.strip(), task_type, runtime_json_param(self.c, params),
                     freq_type, runtime_json_param(self.c, freq_config or {}),
                     trigger_mode, None, None,
                     dependency_condition if trigger_mode == "dependency" else None,
                     runtime_json_param(self.c, dependency_delay),
                     runtime_json_param(self.c, retry_config),
                     bool(trading_day_only), bool(enabled), None, None, now, now])
                self._save_dependencies(jid, parent_ids)
            job = self.get(jid)
            if job["enabled"]:
                register_job(job)
            return self.get(jid)

    def update(self, jid: str, *, name: str, task_type: str, params: dict | None,
               freq_type: str | None, freq_config: dict | None,
               trading_day_only: bool, enabled: bool,
               trigger_mode: str = "time", dependency_job_id: str | None = None,
               dependency_job_ids: list[str] | None = None,
               dependency_condition: str | None = None, dependency_delay: dict | None = None,
               retry_config: dict | None = None) -> dict:
        with _EVENT_DISPATCH_LOCK:
            previous = self.get(jid)
            if not previous:
                raise ValueError("定时任务不存在")
            if not (name or "").strip():
                raise ValueError("任务名称不能为空")
            parent_ids = self._dependency_ids(trigger_mode, dependency_job_id, dependency_job_ids)
            params, dependency_delay, retry_config = self._validate(
                jid, task_type, params, freq_type, freq_config, trigger_mode,
                parent_ids, dependency_condition, dependency_delay, retry_config)
            with self.c.transaction():
                self.c.execute(
                    "UPDATE scheduled_job SET name=?, task_type=?, params=?, "
                    "freq_type=?, freq_config=?, trigger_mode=?, dependency_job_id=?, "
                    "dependency_order=?, dependency_condition=?, "
                    "dependency_delay=?, "
                    "retry_config=?, trading_day_only=?, enabled=?, updated_at=? WHERE id=?",
                    [name.strip(), task_type, runtime_json_param(self.c, params),
                     freq_type, runtime_json_param(self.c, freq_config or {}),
                     trigger_mode, None, None,
                     dependency_condition if trigger_mode == "dependency" else None,
                     runtime_json_param(self.c, dependency_delay),
                     runtime_json_param(self.c, retry_config),
                     bool(trading_day_only), bool(enabled), shanghai_now_naive(), jid])
                self._save_dependencies(jid, parent_ids)
            job = self.get(jid)
            unregister_job(jid)            # 先注销旧触发器
            if job["enabled"] and job["trigger_mode"] == "time":
                register_job(job)          # 再按新定义注册
            if not job["enabled"]:
                self.c.execute(
                    "UPDATE scheduled_trigger_event SET status='cancelled', "
                    "message='目标任务已停用', updated_at=? WHERE target_job_id=? "
                    "AND status IN ('waiting','dispatching')",
                    [shanghai_now_naive(), jid])
            return self.get(jid)       # 重读：拿到重注册后的 next_run_time

    def set_enabled(self, jid: str, enabled: bool) -> dict:
        with _EVENT_DISPATCH_LOCK:
            if not self.get(jid):
                raise ValueError("定时任务不存在")
            self.c.execute("UPDATE scheduled_job SET enabled=?, updated_at=? WHERE id=?",
                           [bool(enabled), shanghai_now_naive(), jid])
            job = self.get(jid)
            unregister_job(jid)
            if enabled and job["trigger_mode"] == "time":
                register_job(job)
            if not enabled:
                self.c.execute(
                    "UPDATE scheduled_trigger_event SET status='cancelled', "
                    "message='目标任务已停用', updated_at=? WHERE target_job_id=? "
                    "AND status IN ('waiting','dispatching')",
                    [shanghai_now_naive(), jid])
            return self.get(jid)       # 重读：拿到（取消）注册后的 next_run_time

    def delete(self, jid: str) -> None:
        with _EVENT_DISPATCH_LOCK:
            refs = self.c.query_df(
                "SELECT j.name FROM scheduled_job j JOIN scheduled_job_dependency d "
                "ON d.downstream_job_id=j.id WHERE d.upstream_job_id=? ORDER BY j.created_at",
                [jid])
            if not refs.empty:
                raise ValueError(
                    "该任务仍被以下任务依赖：" + "、".join(refs["name"].astype(str).tolist()))
            unregister_job(jid)
            with self.c.transaction():
                self.c.execute(
                    "DELETE FROM scheduled_job_dependency WHERE downstream_job_id=?", [jid])
                self.c.execute(
                    "UPDATE scheduled_trigger_event SET status='cancelled', message='目标任务已删除', "
                    "updated_at=? WHERE target_job_id=? AND status IN ('waiting','dispatching')",
                    [shanghai_now_naive(), jid])
                self.c.execute("DELETE FROM scheduled_job WHERE id=?", [jid])

    def set_last_run(self, jid: str, task_id: str | None) -> None:
        now = shanghai_now_naive()
        self.c.execute(
            "UPDATE scheduled_job SET last_run_at=?, last_task_id=?, updated_at=? WHERE id=?",
            [now, task_id, now, jid])

    def run_now(self, jid: str) -> str:
        """手动立即触发一次（不判交易日）。ConcurrentTaskError 上抛由 API 映射 409。"""
        from backend.services.async_task import AsyncTaskService
        job = self.get(jid)
        if not job:
            raise ValueError("定时任务不存在")
        tid = AsyncTaskService().create(job["task_type"], job.get("params") or {},
                                        trigger_source="manual", job_id=jid, job_name=job["name"])
        self.set_last_run(jid, tid)
        return tid

    def recover_events(self) -> int:
        """服务异常退出可能留下 dispatching；有下游任务则补记 dispatched，否则恢复等待。"""
        rows = self.c.query_df(
            "SELECT id FROM scheduled_trigger_event WHERE status='dispatching'")
        for event_id in rows["id"].astype(str).tolist() if not rows.empty else []:
            task = self.c.query_df(
                "SELECT id,created_at FROM async_task WHERE trigger_event_id=? "
                "ORDER BY created_at LIMIT 1",
                [event_id])
            if task.empty:
                self.c.execute(
                    "UPDATE scheduled_trigger_event SET status='waiting', message='服务重启后恢复等待', "
                    "updated_at=? WHERE id=?", [shanghai_now_naive(), event_id])
            else:
                self.c.execute(
                    "UPDATE scheduled_trigger_event SET status='dispatched', task_id=?, "
                    "dispatched_at=COALESCE(dispatched_at, ?), "
                    "message='已恢复下游任务关联', updated_at=? WHERE id=?",
                    [str(task.iloc[0]["id"]), task.iloc[0]["created_at"], shanghai_now_naive(), event_id])
        return len(rows)

    def list_events(self, jid: str, limit: int = 100) -> list[dict]:
        """统一读取目标调度的触发事件及执行记录，已关联事件的任务只展示一次。"""
        import pandas as pd

        size = max(1, min(int(limit), 200))
        df = self.c.query_df(
            "SELECT * FROM ("
            "SELECT e.id, e.chain_id, e.source_task_id, e.source_attempt, e.source_status, "
            "e.target_job_id, e.trigger_kind, e.trigger_condition, e.retry_count, e.dispatch_order, "
            "e.due_at, e.dispatched_at, e.status, e.task_id, e.job_snapshot, e.message, "
            "e.created_at, e.updated_at, COALESCE(st.job_name, sj.name) AS source_job_name, "
            "t.status AS task_status FROM scheduled_trigger_event e "
            "LEFT JOIN async_task st ON st.id=e.source_task_id "
            "LEFT JOIN scheduled_job sj ON sj.id=st.job_id "
            "LEFT JOIN async_task t ON t.id=e.task_id "
            "WHERE e.target_job_id=? "
            "UNION ALL "
            "SELECT 'task:' || t.id AS id, t.chain_id, t.parent_task_id AS source_task_id, "
            "COALESCE(st.execution_attempt, 1) AS source_attempt, st.status AS source_status, "
            "t.job_id AS target_job_id, COALESCE(t.trigger_source, 'manual') AS trigger_kind, "
            "NULL AS trigger_condition, t.retry_count, 0 AS dispatch_order, NULL AS due_at, "
            "t.created_at AS dispatched_at, 'dispatched' AS status, t.id AS task_id, "
            "NULL AS job_snapshot, t.message, t.created_at, t.updated_at, "
            "COALESCE(st.job_name, sj.name) AS source_job_name, t.status AS task_status "
            "FROM async_task t "
            "LEFT JOIN async_task st ON st.id=t.parent_task_id "
            "LEFT JOIN scheduled_job sj ON sj.id=st.job_id "
            "WHERE t.job_id=? AND NOT EXISTS ("
            "SELECT 1 FROM scheduled_trigger_event e WHERE e.target_job_id=t.job_id "
            "AND (e.id=t.trigger_event_id OR e.task_id=t.id))"
            ") records ORDER BY created_at DESC, id DESC LIMIT ?", [jid, jid, size])
        out = []
        for _, row in df.iterrows():
            item = row.to_dict()
            for key in ("chain_id", "source_task_id", "source_status", "source_job_name",
                        "trigger_condition", "task_id", "task_status", "message", "job_snapshot"):
                if item.get(key) is not None and pd.isna(item[key]):
                    item[key] = None
            for key in ("due_at", "dispatched_at", "created_at", "updated_at"):
                if item.get(key) is not None and str(item[key]) != "NaT":
                    item[key] = str(item[key])
                else:
                    item[key] = None
            if item.get("job_snapshot"):
                try:
                    item["job_snapshot"] = json.loads(item["job_snapshot"])
                except (ValueError, TypeError):
                    pass
            item["retry_count"] = int(item.get("retry_count") or 0)
            item["source_attempt"] = int(item.get("source_attempt") or 1)
            out.append(item)
        return out


def _json_value(value, default):
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return default


def _job_snapshot(row) -> dict:
    return {
        "id": str(row["id"]),
        "name": str(row["name"]),
        "task_type": str(row["task_type"]),
        "params": _json_value(row.get("params"), {}),
        "retry_config": _json_value(row.get("retry_config"), _normalize_retry(None)),
    }


def _insert_trigger_event(
    client,
    *,
    source: dict,
    target,
    trigger_kind: str,
    trigger_condition: str,
    retry_count: int,
    delay: dict,
    status: str = "waiting",
    message: str | None = None,
    batch_time: datetime | None = None,
    dispatch_order: int = 0,
    not_before: str | None = None,
) -> str:
    attempt = int(source.get("execution_attempt") or 1)
    raw = f"{source['id']}|{attempt}|{target['id']}|{trigger_kind}|{retry_count}"
    event_id = "evt_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
    now = batch_time or shanghai_now_naive()
    due_at = now + timedelta(seconds=_delay_seconds(delay))
    if not_before:
        try:
            earliest = datetime.fromisoformat(not_before)
            # 运行态沿用本机无时区时间；带时区业务证据先转换到同一本机时间再比较。
            if earliest.tzinfo is not None:
                earliest = earliest.astimezone().replace(tzinfo=None)
            due_at = max(due_at, earliest)
        except (TypeError, ValueError):
            log.warning("任务返回无效复查时间，沿用调度重试间隔")
    client.execute(
        "INSERT INTO scheduled_trigger_event "
        "(id, chain_id, source_task_id, source_attempt, source_status, target_job_id, "
        "trigger_kind, trigger_condition, retry_count, due_at, dispatched_at, status, task_id, "
        "job_snapshot, message, created_at, updated_at, dispatch_order) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT (id) DO NOTHING",
        [event_id, source.get("chain_id") or source["id"], source["id"], attempt,
         source["status"], target["id"], trigger_kind, trigger_condition, retry_count, due_at,
         None, status, None, runtime_json_param(client, _job_snapshot(target)),
         message, now, now, dispatch_order])
    return event_id


def enqueue_terminal_events(task_id: str, *, client=None) -> int:
    """为任务本次终态尝试生成普通依赖事件和自身重试事件；调用方负责事务边界。"""
    client = client or _runtime_client()
    task_df = client.query_df("SELECT * FROM async_task WHERE id=?", [task_id])
    if task_df.empty:
        return 0
    source = task_df.iloc[0].to_dict()
    if source.get("status") not in ("done", "failed") or not source.get("job_id"):
        return 0

    created = 0
    # 同次终态共享基准时间，使相同延迟产生完全相同的 due_at。
    batch_time = shanghai_now_naive()
    dependents = client.query_df(
        "SELECT j.* FROM scheduled_job j JOIN scheduled_job_dependency d "
        "ON d.downstream_job_id=j.id WHERE j.enabled=true AND j.trigger_mode='dependency' "
        "AND d.upstream_job_id=? "
        "ORDER BY d.dependency_order, j.created_at, j.id", [source["job_id"]])
    for position, (_, target) in enumerate(dependents.iterrows()):
        if not _condition_matches(str(target.get("dependency_condition") or ""), source["status"]):
            continue
        _insert_trigger_event(
            client,
            source=source,
            target=target,
            trigger_kind="dependency",
            trigger_condition=str(target.get("dependency_condition")),
            retry_count=0, batch_time=batch_time, dispatch_order=position,
            delay=_json_value(target.get("dependency_delay"), {"value": 0, "unit": "minute"}),
        )
        created += 1

    job_df = client.query_df("SELECT * FROM scheduled_job WHERE id=? AND enabled=true", [source["job_id"]])
    if not job_df.empty:
        job = job_df.iloc[0]
        retry = _json_value(job.get("retry_config"), _normalize_retry(None))
        current_retry = int(source.get("retry_count") or 0)
        result = _json_value(source.get("result"), {})
        # 已知来源无法覆盖的质量问题保留 open，但不触发无效的任务自身重试。
        if (retry.get("enabled") and result.get("retryable") is not False
                and _condition_matches(retry.get("condition"), source["status"])):
            next_retry = current_retry + 1
            max_retries = int(retry.get("max_retries") or 1)
            if next_retry <= max_retries:
                _insert_trigger_event(
                    client,
                    source=source,
                    target=job,
                    trigger_kind="retry",
                    trigger_condition=str(retry.get("condition")),
                    retry_count=next_retry,
                    batch_time=batch_time, dispatch_order=len(dependents),
                    delay=retry.get("delay") or {"value": 0, "unit": "minute"},
                    not_before=result.get("next_retry_at"),
                )
            else:
                _insert_trigger_event(
                    client,
                    source=source,
                    target=job,
                    trigger_kind="retry",
                    trigger_condition=str(retry.get("condition")),
                    retry_count=next_retry,
                    batch_time=batch_time, dispatch_order=len(dependents),
                    delay={"value": 0, "unit": "minute"},
                    status="exhausted",
                    message=f"已达到最大重试次数 {max_retries}，链路结束",
                )
            created += 1
    return created


def dispatch_due_events() -> int:
    """分发已到期的依赖/重试事件；写槽位繁忙时保持 waiting，下一轮继续。"""
    from backend.services.async_task import AsyncTaskService, ConcurrentTaskError

    svc = ScheduledJobService(_runtime_client(), initialize=False)
    if is_postgres_task_runtime(svc.c):
        events = svc.c.claim_due_events(now=shanghai_now_naive(), limit=50)
    else:
        events = svc.c.query_df(
            "SELECT * FROM scheduled_trigger_event WHERE status='waiting' AND due_at<=? "
            "ORDER BY due_at, created_at, dispatch_order, id LIMIT 50", [shanghai_now_naive()])
    if not events.empty:
        events = events.sort_values(["due_at", "created_at", "dispatch_order", "id"], kind="stable")
    dispatched = 0
    for _, row in events.iterrows():
        event_id = str(row["id"])
        with _EVENT_DISPATCH_LOCK:
            # 到期列表是锁外快照；认领前重读，避免另一分发轮次或停用操作已经改变状态。
            expected_status = "dispatching" if is_postgres_task_runtime(svc.c) else "waiting"
            latest = svc.c.query_df(
                "SELECT * FROM scheduled_trigger_event WHERE id=? AND status=?",
                [event_id, expected_status],
            )
            if latest.empty:
                continue
            event = latest.iloc[0].to_dict()
            target = svc.get(str(event["target_job_id"]))
            if not target or not target["enabled"]:
                svc.c.execute(
                    "UPDATE scheduled_trigger_event SET status='cancelled', message=?, updated_at=? "
                    "WHERE id=? AND status=?",
                    ["目标任务不存在或已停用", shanghai_now_naive(), event_id, expected_status])
                continue
            if not is_postgres_task_runtime(svc.c):
                svc.c.execute(
                    "UPDATE scheduled_trigger_event SET status='dispatching', "
                    "message='正在创建下游任务', updated_at=? WHERE id=? AND status='waiting'",
                    [shanghai_now_naive(), event_id])
            snapshot = _json_value(event.get("job_snapshot"), {})
            try:
                tid = AsyncTaskService(svc.c).create(
                    str(snapshot.get("task_type") or target["task_type"]),
                    snapshot.get("params") or {},
                    trigger_source="retry" if event["trigger_kind"] == "retry" else "dependency",
                    job_id=target["id"],
                    job_name=str(snapshot.get("name") or target["name"]),
                    chain_id=str(event.get("chain_id") or event["source_task_id"]),
                    parent_task_id=str(event["source_task_id"]),
                    trigger_event_id=event_id,
                    retry_count=int(event.get("retry_count") or 0),
                )
                now = shanghai_now_naive()
                svc.c.execute(
                    "UPDATE scheduled_trigger_event SET status='dispatched', task_id=?, "
                    "dispatched_at=?, message='已触发', updated_at=? "
                    "WHERE id=? AND status='dispatching'",
                    [tid, now, now, event_id])
                svc.set_last_run(target["id"], tid)
                dispatched += 1
            except ConcurrentTaskError as exc:
                svc.c.execute(
                    "UPDATE scheduled_trigger_event SET status='waiting', message=?, updated_at=? "
                    "WHERE id=? AND status='dispatching'",
                    [f"等待写任务执行槽位：{exc.task_type}（{exc.running_id}）",
                     shanghai_now_naive(), event_id])
            except Exception as exc:
                log.exception("[scheduler] 依赖事件分发失败 %s", event_id)
                svc.c.execute(
                    "UPDATE scheduled_trigger_event SET status='failed', message=?, updated_at=? "
                    "WHERE id=? AND status='dispatching'",
                    [str(exc), shanghai_now_naive(), event_id])
    return dispatched
