"""定时调度（T-M7-2 + M2.8-B FR-DM-7）——每交易日收盘后自动跑 DailyPipeline。

- 由 `scheduler.enabled` 控制（默认关）；开启后随 Web 服务启动，每天
  `daily_cron_hour:daily_cron_minute`（默认 18:00）触发；**非交易日跳过**。
- M2.8-B：支持**运行时** enable/disable/reschedule（不需重启进程），开关与时间持久化到
  app_config 覆盖层；提供 status()（enabled / 下次触发 / 最近一次执行结果）。
- 与服务同进程，复用同一 DuckDB 连接（写入经 RLock 串行，安全）。
- 失败仅记日志、不崩调度；下次仍按点触发（流程幂等）。
"""

from __future__ import annotations

from datetime import date, datetime

from backend.common.logging import get_logger
from backend.config import get_effective_settings
from backend.storage.duckdb_client import get_client

log = get_logger("scheduler")

_scheduler = None          # 进程内单例（BackgroundScheduler）
_last_result: dict | None = None   # 最近一次执行结果（内存，进程级）
_JOB_ID = "daily_pipeline"


def _is_trading_day(d: date) -> bool:
    df = get_client().query_df(
        "SELECT is_open FROM trade_calendar WHERE trade_date = ?", [d]
    )
    return (not df.empty) and bool(df.iloc[0]["is_open"])


def _daily_job() -> None:
    from backend.services.pipeline import DailyPipeline

    global _last_result
    today = date.today()
    if not _is_trading_day(today):
        log.info("[scheduler] %s 非交易日，跳过日常流程", today)
        _last_result = {"run_at": str(datetime.now()), "skipped": True, "reason": "非交易日"}
        return
    log.info("[scheduler] %s 触发日常流程", today)
    t0 = datetime.now()
    try:
        res = DailyPipeline().run(skip_update=False, presets=True)
        _last_result = {"run_at": str(t0), "ok": bool(res.get("ok")),
                        "secs": round((datetime.now() - t0).total_seconds(), 1),
                        "steps": res.get("steps")}
        log.info("[scheduler] 日常流程完成 ok=%s", res.get("ok"))
    except Exception as e:  # noqa: BLE001
        _last_result = {"run_at": str(t0), "ok": False, "error": str(e)}
        log.error("[scheduler] 日常流程异常: %s", e)


def _ensure_scheduler():
    """惰性创建 BackgroundScheduler（不加任何 job，不 start）。"""
    global _scheduler
    if _scheduler is None:
        from apscheduler.schedulers.background import BackgroundScheduler
        _scheduler = BackgroundScheduler()
    return _scheduler


def _add_or_reschedule(hour: int, minute: int) -> None:
    from apscheduler.triggers.cron import CronTrigger
    sched = _ensure_scheduler()
    sched.add_job(_daily_job, CronTrigger(hour=hour, minute=minute),
                  id=_JOB_ID, replace_existing=True, misfire_grace_time=3600)
    if not sched.running:
        sched.start()


def start_scheduler():
    """按配置启动调度（enabled=False 时不启动）。返回 scheduler 或 None。"""
    s = get_effective_settings().scheduler
    if not s.enabled:
        log.info("[scheduler] 未启用（scheduler.enabled=false）")
        return None
    _add_or_reschedule(s.daily_cron_hour, s.daily_cron_minute)
    log.info("[scheduler] 已启动：每日 %02d:%02d 跑日常流程（非交易日自动跳过）",
             s.daily_cron_hour, s.daily_cron_minute)
    return _scheduler


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
    _scheduler = None


# ── 运行时控制（FR-DM-7，M2.8-B）──────────────────────────────

def _persist(enabled: bool | None = None, hour: int | None = None, minute: int | None = None) -> None:
    """把开关/时间写入 app_config 覆盖层（保存即生效、重启不丢）。"""
    from backend.storage.app_config import AppConfigRepo
    updates: dict = {}
    if enabled is not None:
        updates["scheduler.enabled"] = bool(enabled)
    if hour is not None:
        updates["scheduler.daily_cron_hour"] = int(hour)
    if minute is not None:
        updates["scheduler.daily_cron_minute"] = int(minute)
    if updates:
        AppConfigRepo().set_many(updates)


def apply_config(enabled: bool, hour: int, minute: int) -> dict:
    """运行时套用调度配置：持久化 + 立即生效（增/删/改 job），返回最新状态。"""
    _persist(enabled=enabled, hour=hour, minute=minute)
    if enabled:
        _add_or_reschedule(hour, minute)
        log.info("[scheduler] 运行时启用：每日 %02d:%02d", hour, minute)
    else:
        sched = _ensure_scheduler()
        if sched.get_job(_JOB_ID):
            sched.remove_job(_JOB_ID)
        log.info("[scheduler] 运行时停用")
    return status()


def status() -> dict:
    """当前调度状态：开关 / cron 时间 / 下次触发 / 最近执行结果。"""
    s = get_effective_settings().scheduler
    next_run = None
    if _scheduler is not None and _scheduler.running:
        job = _scheduler.get_job(_JOB_ID)
        if job and job.next_run_time:
            next_run = str(job.next_run_time)
    return {
        "enabled": bool(s.enabled),
        "cron_hour": int(s.daily_cron_hour),
        "cron_minute": int(s.daily_cron_minute),
        "next_run_time": next_run,
        "running": _scheduler is not None and _scheduler.running,
        "last_result": _last_result,
    }
