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

import json
from datetime import date, datetime, timedelta

from backend.common.logging import get_logger
from backend.storage.duckdb_client import get_client

log = get_logger("scheduler")

_scheduler = None   # 进程内 APScheduler 单例（BackgroundScheduler）
_DEFAULT_AUDIT_CLEANUP_NAME = "审计日志清理"
_DEFAULT_AUDIT_CLEANUP_TIME = "03:30"

# 可配成定时任务的类型：原子采集/维护/质检 + 按问题类型动态恢复。
SCHEDULABLE_TASK_TYPES = (
    "update", "backfill", "ingest_date", "recompute", "verify", "checkup", "fix", "enrich_basic",
    "audit_cleanup", "board",
)
_WEEKDAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]   # 1..7 → APScheduler 名称
_WEEKDAY_CN = ["一", "二", "三", "四", "五", "六", "日"]
_FREQ_TYPES = ("daily", "weekly", "monthly", "cron")


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
    try:  # 日历未采到 d → 补采后复查（ingest_calendar 会一并把上界延伸到年底）
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
    if job["trading_day_only"] and not _is_trading_day(date.today()):
        log.info("[scheduler] 定时任务「%s」%s 非交易日，跳过", name, date.today())
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
    jobs = [j for j in ScheduledJobService().list() if j["enabled"]]
    for j in jobs:
        try:
            register_job(j)
        except Exception as e:  # noqa: BLE001
            log.error("[scheduler] 注册定时任务「%s」失败: %s", j.get("name"), e)
    log.info("[scheduler] 已加载 %d 条启用的定时任务", len(jobs))
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
    nexts = [next_run_time(j["id"]) for j in enabled]
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
    def __init__(self, client=None):
        self.c = client or get_client()
        from backend.storage.ddl import init_db
        init_db(self.c)

    @staticmethod
    def _row(r) -> dict:
        import pandas as pd
        d = r.to_dict()
        for k in ("created_at", "updated_at", "last_run_at"):
            v = d.get(k)
            d[k] = None if v is None or str(v) == "NaT" else str(v)
        d["enabled"] = bool(d.get("enabled"))
        d["trading_day_only"] = bool(d.get("trading_day_only"))
        for k in ("params", "freq_config"):
            if d.get(k):
                try:
                    d[k] = json.loads(d[k])
                except (ValueError, TypeError):
                    pass
        d["freq_text"] = freq_text(d.get("freq_type"), d.get("freq_config"))
        d["next_run_time"] = next_run_time(d["id"]) if d["enabled"] else None
        _ = pd  # 仅为静态可读
        return d

    def list(self) -> list[dict]:
        df = self.c.query_df("SELECT * FROM scheduled_job ORDER BY created_at")
        return [self._row(r) for _, r in df.iterrows()]

    def get(self, jid: str) -> dict | None:
        df = self.c.query_df("SELECT * FROM scheduled_job WHERE id=?", [jid])
        return None if df.empty else self._row(df.iloc[0])

    def _validate(self, task_type: str, params: dict | None,
                  freq_type: str, freq_config: dict | None) -> dict:
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
            mode = str(normalized_params.get("mode") or "update")
            if mode not in ("update", "backfill"):
                raise ValueError("板块定时采集模式仅支持 update/backfill")
            normalized_params["mode"] = mode
        if freq_type not in _FREQ_TYPES:
            raise ValueError(f"未知频率类型: {freq_type}（可选 {_FREQ_TYPES}）")
        compile_trigger(freq_type, freq_config)   # 提前校验频率配置合法
        return normalized_params

    def create(self, *, name: str, task_type: str, params: dict | None,
               freq_type: str, freq_config: dict | None,
               trading_day_only: bool, enabled: bool) -> dict:
        if not (name or "").strip():
            raise ValueError("任务名称不能为空")
        params = self._validate(task_type, params, freq_type, freq_config)
        jid = f"job_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
        now = datetime.now()
        self.c.execute(
            "INSERT INTO scheduled_job (id, name, task_type, params, freq_type, freq_config, "
            "trading_day_only, enabled, last_run_at, last_task_id, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [jid, name.strip(), task_type, json.dumps(params, ensure_ascii=False, default=str),
             freq_type, json.dumps(freq_config or {}, ensure_ascii=False, default=str),
             bool(trading_day_only), bool(enabled), None, None, now, now])
        job = self.get(jid)
        if job["enabled"]:
            register_job(job)
        return self.get(jid)

    def update(self, jid: str, *, name: str, task_type: str, params: dict | None,
               freq_type: str, freq_config: dict | None,
               trading_day_only: bool, enabled: bool) -> dict:
        if not self.get(jid):
            raise ValueError("定时任务不存在")
        if not (name or "").strip():
            raise ValueError("任务名称不能为空")
        params = self._validate(task_type, params, freq_type, freq_config)
        self.c.execute(
            "UPDATE scheduled_job SET name=?, task_type=?, params=?, freq_type=?, freq_config=?, "
            "trading_day_only=?, enabled=?, updated_at=? WHERE id=?",
            [name.strip(), task_type, json.dumps(params, ensure_ascii=False, default=str),
             freq_type, json.dumps(freq_config or {}, ensure_ascii=False, default=str),
             bool(trading_day_only), bool(enabled), datetime.now(), jid])
        job = self.get(jid)
        unregister_job(jid)            # 先注销旧触发器
        if job["enabled"]:
            register_job(job)          # 再按新定义注册
        return self.get(jid)           # 重读：拿到重注册后的 next_run_time（否则是旧触发器的值）

    def set_enabled(self, jid: str, enabled: bool) -> dict:
        if not self.get(jid):
            raise ValueError("定时任务不存在")
        self.c.execute("UPDATE scheduled_job SET enabled=?, updated_at=? WHERE id=?",
                       [bool(enabled), datetime.now(), jid])
        job = self.get(jid)
        unregister_job(jid)
        if enabled:
            register_job(job)
        return self.get(jid)           # 重读：拿到（取消）注册后的 next_run_time

    def delete(self, jid: str) -> None:
        unregister_job(jid)
        self.c.execute("DELETE FROM scheduled_job WHERE id=?", [jid])

    def set_last_run(self, jid: str, task_id: str | None) -> None:
        now = datetime.now()
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
