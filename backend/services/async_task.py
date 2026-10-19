"""异步任务执行器（SDD §10，M2.6 + M2.8-B）——数据更新/补数/指定采集/重算/体检/修复后台跑。

本地单用户：任务在守护线程里执行，复用 IngestionService / DataVerifier / DataIntegrityReport。
DuckDB 单连接 + RLock 串行化 SQL，线程安全；长任务在 SQL 之间释放锁，不阻塞轻请求。

M2.8-B 增强：
- **实时日志**（FR-DM-9）：TaskContext.log() 批量写 task_log（节流，DM-D8），前端按 after_seq 增量拉。
- **checkpoint / 续跑**（FR-DM-10）：支持续跑的处理器把已完成项写 result.checkpoint；服务重启
  reconcile() 把残留 running/pending 标 interrupted；resume() 仅按任务能力和 checkpoint 续跑。
- **并发互斥**（FR-DM-11）：写任务（采集/质检/恢复等）不允许并发，创建即 409。
- **数据修复**（FR-DM-4）：fix 任务定向重拉单条质检问题对应股票/日期，回写 issue 状态。

采集与数据变化任务只维护原始数据；走势、天梯和榜单结果由显式结果维护任务处理。
"""

from __future__ import annotations

import json
import threading
from contextlib import nullcontext
from datetime import datetime, timedelta

from backend.common.exceptions import ConflictError
from backend.common.logging import get_logger
from backend.storage.duckdb_client import get_client
from backend.storage.task_runtime import (
    get_task_runtime_client,
    is_postgres_task_runtime,
    runtime_json_param,
    task_runtime_backend,
)

log = get_logger("services.async_task")

# 全部任务类型：旧原子任务保持兼容，stock_ingest 按安全方案统一分派既有采集能力。
TASK_TYPES = ("update", "backfill", "ingest_date", "ingest_codes", "rebuild_price_factors",
              "recompute", "verify", "checkup", "fix", "enrich_basic", "audit_cleanup",
              "board", "stock_ingest", "stock_board_correlation", "limit_ladder_invalidate",
              "limit_ladder_recompute", "stock_special_trading_day")
# 写类任务：互斥（写任务之间不并发），且服务重启需 reconcile。
WRITE_TASK_TYPES = frozenset({"update", "backfill", "ingest_date", "ingest_codes",
                              "rebuild_price_factors", "verify", "fix", "enrich_basic",
                              "board", "stock_ingest", "stock_board_correlation",
                              "limit_ladder_invalidate", "limit_ladder_recompute",
                              "stock_special_trading_day"})

# 日志保留（DM-D8）
LOG_MAX_PER_TASK = 2000
LOG_RETENTION_DAYS = 30
_LOG_FLUSH_EVERY = 10  # 累计 N 条即 flush；长任务日志要比进度条更快出现在页面上
# 创建锁覆盖“幂等查询 / 写任务槽位检查 / pending 落库”整个区间，避免多个
# FastAPI/APScheduler 线程同时通过检查。项目运行契约为单后端进程，跨进程写由 DuckDB 文件锁拒绝。
_TASK_CREATE_LOCK = threading.Lock()

TASK_CAPABILITIES: dict[str, dict] = {
    "stock_special_trading_day": {
        "can_cancel": False, "can_resume": False, "cancel_mode": "none",
        "resume_granularity": None, "cancel_message": "公告事实按批次原子维护",
    },
    "update": {
        "can_cancel": True, "can_resume": True, "cancel_mode": "checkpoint",
        "resume_granularity": "phase_code",
        "cancel_message": "会在当前股票/当前外部接口请求结束后的检查点停止",
    },
    "ingest_codes": {
        "can_cancel": True, "can_resume": True, "cancel_mode": "checkpoint",
        "resume_granularity": "phase_code",
        "cancel_message": "会在当前股票/当前外部接口请求结束后的检查点停止",
    },
    "backfill": {
        "can_cancel": True, "can_resume": True, "cancel_mode": "checkpoint",
        "resume_granularity": "code",
        "cancel_message": "会在当前股票/当前外部接口请求结束后的检查点停止",
    },
    "ingest_date": {
        "can_cancel": True, "can_resume": True, "cancel_mode": "checkpoint",
        "resume_granularity": "code",
        "cancel_message": "会在当前股票/当前外部接口请求结束后的检查点停止",
    },
    "rebuild_price_factors": {
        "can_cancel": True, "can_resume": True, "cancel_mode": "checkpoint",
        "resume_granularity": "code",
        "cancel_message": "会在当前股票价格因子重算完成后停止",
    },
    "fix": {
        "can_cancel": True, "can_resume": True, "cancel_mode": "checkpoint",
        "resume_granularity": "issue_id",
        "cancel_message": "会在当前质检问题恢复完成后停止",
    },
    "enrich_basic": {
        "can_cancel": True, "can_resume": False, "cancel_mode": "checkpoint",
        "resume_granularity": None,
        "cancel_message": "会在当前刷新步骤完成后停止；该任务不提供精确续跑",
    },
    "recompute": {
        "can_cancel": False, "can_resume": False, "cancel_mode": "none",
        "resume_granularity": None, "cancel_message": "该任务很短，不支持终止/续跑",
    },
    "verify": {
        "can_cancel": False, "can_resume": False, "cancel_mode": "none",
        "resume_granularity": None, "cancel_message": "质检扫描暂不支持中途终止/续跑",
    },
    "checkup": {
        "can_cancel": False, "can_resume": False, "cancel_mode": "none",
        "resume_granularity": None, "cancel_message": "结构体检暂不支持中途终止/续跑",
    },
    "audit_cleanup": {
        "can_cancel": False, "can_resume": False, "cancel_mode": "none",
        "resume_granularity": None, "cancel_message": "审计清理任务很短，不支持终止/续跑",
    },
    "board": {
        "can_cancel": True, "can_resume": True, "cancel_mode": "checkpoint",
        "resume_granularity": "board_code_or_fund_period",
        "cancel_message": "会在当前板块或资金流类型/周期取数完成后的检查点停止",
    },
    "stock_ingest": {
        "can_cancel": True, "can_resume": True, "cancel_mode": "checkpoint",
        "resume_granularity": "phase_code",
        "cancel_message": "会在当前股票或当前外部接口请求结束后的检查点停止",
    },
    "stock_board_correlation": {
        "can_cancel": True, "can_resume": False, "cancel_mode": "checkpoint",
        "resume_granularity": None,
        "cancel_message": "会在当前计算阶段或原子切换开始前停止；原子切换开始后不中断",
    },
    "limit_ladder_recompute": {
        "can_cancel": False, "can_resume": False, "cancel_mode": "none",
        "resume_granularity": None,
        "cancel_message": "单日快照采用原子切换，不支持中途终止或续跑",
    },
    "limit_ladder_invalidate": {
        "can_cancel": False, "can_resume": False, "cancel_mode": "none",
        "resume_granularity": None,
        "cancel_message": "失效标记为短事务，不支持中途终止或续跑",
    },
}


class ConcurrentTaskError(ConflictError):
    """同类写任务已在运行（FR-DM-11，映射 409）。"""

    def __init__(self, task_type: str, running_id: str):
        self.task_type = task_type
        self.running_id = running_id
        super().__init__(f"已有同类任务在运行: {task_type}（{running_id}）")


class TaskCancelled(Exception):
    """用户请求取消任务（协作式：执行器在步骤间检查到即抛出）。"""


# 协作式取消：被请求取消的任务 id 集合（同进程内执行器线程与 API 共享）。
_CANCEL_LOCK = threading.Lock()
_CANCELLED: set[str] = set()


class TaskContext:
    """处理器运行上下文：进度 / 实时日志 / checkpoint。"""

    def __init__(self, svc: "AsyncTaskService", tid: str, checkpoint: dict | None = None):
        self.svc = svc
        self.tid = tid
        self.checkpoint: dict = checkpoint or {}
        self._buf: list[tuple] = []
        self._seq = svc._max_log_seq(tid)

    def progress(self, p: float, msg: str) -> None:
        self.flush()  # 进度推进时顺带 flush 日志，前端两路同步
        self.svc._set(self.tid, progress=round(float(p), 3), message=msg)

    def log(self, message: str, level: str = "info") -> None:
        self._seq += 1
        self._buf.append((self._seq, datetime.now(), level, message))
        if len(self._buf) >= _LOG_FLUSH_EVERY:
            self.flush()

    def flush(self) -> None:
        if not self._buf:
            return
        rows, self._buf = self._buf, []
        self.svc._write_logs(self.tid, rows)

    def set_checkpoint(self, **data) -> None:
        """合并并持久化 checkpoint（写 result 列），供 resume 跳过已完成。"""
        self.checkpoint.update(data)
        self.svc._set(self.tid, result={"checkpoint": self.checkpoint})

    def set_phase(self, phase: str, **data) -> None:
        """记录当前长子任务阶段；前端据此解释'下一个检查点'在哪里。"""
        self.set_checkpoint(phase=phase, **data)

    def check_cancel(self) -> None:
        """协作式取消检查点：被请求取消则抛 TaskCancelled，由执行器按能力收尾。"""
        with _CANCEL_LOCK:
            cancelled = self.tid in _CANCELLED
        if cancelled:
            raise TaskCancelled()


class AsyncTaskService:
    def __init__(self, client=None, *, market_client=None):
        if client is None:
            client = (
                get_client() if task_runtime_backend() == "duckdb" else get_task_runtime_client()
            )
        self.c = client
        self.market = market_client or (get_client() if is_postgres_task_runtime(self.c) else self.c)
        if not is_postgres_task_runtime(self.c):
            from backend.storage.ddl import init_db

            init_db(self.c)

    # ── id / 写入辅助 ──
    def _new_id(self, t: str) -> str:
        return f"task_{t}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"

    def _set(self, tid: str, **fields) -> None:
        if "result" in fields:
            result = fields["result"]
            if isinstance(result, str):
                result = json.loads(result)
            fields["result"] = runtime_json_param(self.c, result)
        fields["updated_at"] = datetime.now()
        cols = ", ".join(f"{k}=?" for k in fields)
        self.c.execute(f"UPDATE async_task SET {cols} WHERE id=?", [*fields.values(), tid])

    def _running_write(self) -> tuple[str, str] | None:
        """任一在跑的写任务（单写者模型）：写任务之间互斥，不只同类——

        update/backfill/ingest_*/fix/daily 都写行情库，并发两个写没意义且易混淆；
        DuckDB 虽 RLock 串行不会损坏，但语义上只允许一个写任务在跑。返回 (id, type)。
        """
        ph = ",".join("?" * len(WRITE_TASK_TYPES))
        df = self.c.query_df(
            f"SELECT id, task_type FROM async_task WHERE task_type IN ({ph}) "
            "AND status IN ('pending','running') ORDER BY created_at DESC LIMIT 1",
            list(WRITE_TASK_TYPES))
        return None if df.empty else (df.iloc[0]["id"], df.iloc[0]["task_type"])

    # ── 实时日志 ──
    def _max_log_seq(self, tid: str) -> int:
        import pandas as pd
        df = self.c.query_df("SELECT max(seq) AS s FROM task_log WHERE task_id=?", [tid])
        s = df.iloc[0]["s"]
        return 0 if s is None or pd.isna(s) else int(s)

    def _write_logs(self, tid: str, rows: list[tuple]) -> None:
        """批量写 task_log（每行带自增 id）。rows=[(seq, ts, level, message)]。"""
        if is_postgres_task_runtime(self.c):
            self.c.executemany(
                "INSERT INTO task_log (task_id, seq, ts, level, message) VALUES (?,?,?,?,?)",
                [(tid, seq, ts, level, message) for seq, ts, level, message in rows],
            )
        else:
            self.c.executemany(
                "INSERT INTO task_log (id, task_id, seq, ts, level, message) "
                "VALUES (nextval('seq_task_log'),?,?,?,?,?)",
                [(tid, seq, ts, level, message) for seq, ts, level, message in rows],
            )
        self._trim_logs(tid)

    def _trim_logs(self, tid: str) -> None:
        """每任务保留最近 LOG_MAX_PER_TASK 条（DM-D8）。"""
        self.c.execute(
            "DELETE FROM task_log WHERE task_id=? AND seq <= "
            "(SELECT max(seq) - ? FROM task_log WHERE task_id=?)",
            [tid, LOG_MAX_PER_TASK, tid])

    def get_logs(self, tid: str, after_seq: int = 0) -> list[dict]:
        df = self.c.query_df(
            "SELECT seq, ts, level, message FROM task_log WHERE task_id=? AND seq > ? ORDER BY seq",
            [tid, int(after_seq)])
        out = df.to_dict("records")
        for r in out:
            r["ts"] = str(r["ts"])
            r["seq"] = int(r["seq"])
        return out

    # ── 创建 / 执行 ──
    def create(self, task_type: str, params: dict | None = None, *,
               trigger_source: str = "manual", job_id: str | None = None,
               job_name: str | None = None, chain_id: str | None = None,
               parent_task_id: str | None = None, trigger_event_id: str | None = None,
               retry_count: int = 0) -> str:
        """创建并后台执行任务，保留调度定义、运行链、父任务和幂等触发事件来源。"""
        if task_type not in TASK_TYPES:
            raise ValueError(f"未知任务类型: {task_type}（可选 {TASK_TYPES}）")
        params = params or {}
        if task_type == "stock_special_trading_day":
            from backend.services.stock_special_trading_day import normalize_special_day_params

            params = normalize_special_day_params(params)
        if task_type == "stock_ingest":
            from backend.services.stock_ingest import normalize_stock_ingest_params

            params = normalize_stock_ingest_params(params)
        if task_type == "board":
            from backend.services.board_ingest import (
                normalize_board_date_range,
                normalize_board_force_current_day,
            )

            mode = str(params.get("mode") or "update")
            force_current_day = normalize_board_force_current_day(
                mode, params.get("force_current_day"),
            )
            normalize_board_date_range(
                mode, params.get("date_start"), params.get("date_end"), force_current_day,
            )
        if task_type == "stock_board_correlation":
            from backend.services.stock_board_correlation import normalize_correlation_task_params

            params = normalize_correlation_task_params(params, client=self.market)
        if task_type == "recompute":
            from backend.services.result_maintenance import normalize_score_invalidation_params

            params = normalize_score_invalidation_params(params)
        if task_type == "limit_ladder_invalidate":
            from backend.services.result_maintenance import normalize_ladder_invalidation_params

            params = normalize_ladder_invalidation_params(params)
        storage_lock = (
            self.c.task_create_transaction()
            if is_postgres_task_runtime(self.c)
            else nullcontext()
        )
        with _TASK_CREATE_LOCK, storage_lock:
            if trigger_event_id:
                existing = self.c.query_df(
                    "SELECT id FROM async_task WHERE trigger_event_id=? ORDER BY created_at LIMIT 1",
                    [trigger_event_id])
                if not existing.empty:
                    return str(existing.iloc[0]["id"])
            if task_type in WRITE_TASK_TYPES:
                busy = self._running_write()
                if busy:
                    raise ConcurrentTaskError(busy[1], busy[0])
            tid = self._new_id(task_type)
            chain_id = chain_id or tid
            now = datetime.now()
            self.c.execute(
                "INSERT INTO async_task (id, task_type, params, status, progress, message, result, "
                "trigger_source, job_id, job_name, chain_id, parent_task_id, trigger_event_id, "
                "retry_count, execution_attempt, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [tid, task_type, runtime_json_param(self.c, params),
                 "pending", 0.0, "已排队", None, trigger_source, job_id, job_name, chain_id,
                 parent_task_id, trigger_event_id, int(retry_count), 1, now, now])
        self._audit_task(
            action="create",
            result="success",
            status="pending",
            task_id=tid,
            task_type=task_type,
            job_id=job_id,
            job_name=job_name,
        )
        threading.Thread(target=self._run, args=(tid, task_type, params, None), daemon=True).start()
        return tid

    def resume(self, tid: str) -> str:
        """继续中断任务或重试带 checkpoint 的失败任务，跳过已成功工作单元。"""
        t = self.get(tid)
        if not t:
            raise ValueError("任务不存在")
        if t["status"] not in ("interrupted", "failed"):
            raise ValueError(f"仅可继续中断任务或重试失败任务，当前状态: {t['status']}")
        task_type = t["task_type"]
        cap = TASK_CAPABILITIES.get(task_type, {})
        if not cap.get("can_resume"):
            raise ValueError(f"该任务类型不支持继续或重试: {task_type}")
        checkpoint = (t.get("result") or {}).get("checkpoint") \
            if isinstance(t.get("result"), dict) else None
        if t["status"] == "failed" and not checkpoint:
            raise ValueError("失败任务没有可用 checkpoint，请重新创建任务")
        params = t.get("params") or {}
        pending_message = "重试未完成项排队…" if t["status"] == "failed" else "继续任务排队…"
        storage_lock = (
            self.c.task_create_transaction()
            if is_postgres_task_runtime(self.c)
            else nullcontext()
        )
        with _TASK_CREATE_LOCK, storage_lock:
            if task_type in WRITE_TASK_TYPES:
                busy = self._running_write()
                if busy:
                    raise ConcurrentTaskError(busy[1], busy[0])
            with _CANCEL_LOCK:
                # 续跑复用原 task id；仅在本次重新排队前清除上一轮已消费的取消标记。
                _CANCELLED.discard(tid)
            self.c.execute(
                "UPDATE async_task SET status='pending', progress=0.0, message=?, "
                "execution_attempt=COALESCE(execution_attempt,1)+1, cancel_requested_at=NULL, "
                "updated_at=? WHERE id=?",
                [pending_message, datetime.now(), tid])
        self._audit_task(
            action="resume",
            result="success",
            status="pending",
            task_id=tid,
            task_type=task_type,
            job_id=t.get("job_id"),
            job_name=t.get("job_name"),
        )
        threading.Thread(target=self._run, args=(tid, task_type, params, checkpoint), daemon=True).start()
        return tid

    def _run(self, tid: str, task_type: str, params: dict, checkpoint: dict | None) -> None:
        ctx = TaskContext(self, tid, checkpoint)
        # 新任务 id 天然没有旧取消标记；续跑已在 resume() 排队前显式清理。
        # 这里不能清理，否则用户在 pending→线程启动竞态窗口发出的终止会被吞掉。
        self._set(tid, status="running", progress=0.05, message="开始…")
        self._audit_task(
            action="start",
            result="success",
            status="running",
            task_id=tid,
            task_type=task_type,
        )
        ctx.log(f"▶ 任务启动：{task_type}，参数 {json.dumps(params, ensure_ascii=False, default=str)}")
        if checkpoint:
            done = checkpoint.get("done")
            phase = checkpoint.get("phase") or "未记录阶段"
            item = checkpoint.get("current_item") or "-"
            ctx.log(f"从检查点继续：上次阶段 {phase}，位置 {item}，约完成 {done}/{checkpoint.get('total', '?')} 项；"
                    "将按 checkpoint/已入库数据跳过已完成部分")
        ctx.flush()
        try:
            result = _HANDLERS[task_type](params, ctx)
            if result.get("ok") is False:
                message = result.get("message", "任务部分失败")
                ctx.log(f"■ 任务失败：{message}", "error")
                ctx.flush()
                # 部分失败不是全量回滚：保留成功工作单元 checkpoint，失败任务可从剩余单元续跑。
                result_payload = dict(result)
                if ctx.checkpoint:
                    result_payload["checkpoint"] = ctx.checkpoint
                self._finish_terminal(
                    tid,
                    status="failed",
                    message=message,
                    result=json.dumps(result_payload, ensure_ascii=False, default=str),
                )
                self._audit_task(
                    action="finish", result="failed", status="failed",
                    task_id=tid, task_type=task_type, error_summary=message,
                )
                return
            ctx.log(f"■ 任务完成：{result.get('message', '完成')}")
            ctx.flush()
            self._finish_terminal(
                tid,
                status="done",
                message=result.get("message", "完成"),
                result=json.dumps(result, ensure_ascii=False, default=str),
            )
            self._audit_task(
                action="finish",
                result="success",
                status="done",
                task_id=tid,
                task_type=task_type,
            )
        except TaskCancelled:
            can_resume = bool(TASK_CAPABILITIES.get(task_type, {}).get("can_resume"))
            if can_resume:
                terminal_message = "已终止（可续跑）"
                ctx.log("⏹ 任务已被用户终止（已完成的部分已入库，可续跑）", "warn")
            else:
                terminal_message = "已终止（不支持续跑，重新执行将完整计算）"
                ctx.log("⏹ 任务已被用户终止（正式结果未发生不完整切换）", "warn")
            self._release_fixing(tid)
            ctx.flush()
            self._set(tid, status="interrupted", message=terminal_message)
            self._audit_task(
                action="interrupt",
                result="failed",
                status="interrupted",
                task_id=tid,
                task_type=task_type,
                error_summary="任务被用户终止",
            )
        except Exception as e:
            log.exception("异步任务失败 %s", tid)
            ctx.log(f"任务失败: {e}", "error")
            self._release_fixing(tid)
            ctx.flush()
            self._finish_terminal(tid, status="failed", message=str(e))
            self._audit_task(
                action="finish",
                result="failed",
                status="failed",
                task_id=tid,
                task_type=task_type,
                error_summary=str(e),
            )
        finally:
            with _CANCEL_LOCK:
                _CANCELLED.discard(tid)

    def _finish_terminal(
        self,
        tid: str,
        *,
        status: str,
        message: str,
        result: str | None = None,
    ) -> None:
        """原子写入终态和依赖事件，避免服务退出后下游链路永久丢失。"""
        from backend.scheduler.scheduler import enqueue_terminal_events

        fields = {"status": status, "progress": 1.0, "message": message}
        if result is not None:
            fields["result"] = result
        with self.c.transaction():
            self._set(tid, **fields)
            enqueue_terminal_events(tid, client=self.c)

    def _release_fixing(self, tid: str) -> int:
        """把本任务名下仍卡在 fixing 的质检问题复位为 open（任务失败/中断时调用，不留孤儿）。"""
        try:
            stuck = self.market.query_df(
                "SELECT count(*) AS n FROM data_quality_issue WHERE status='fixing' AND fix_task_id=?",
                [tid]).iloc[0]["n"]
            if int(stuck):
                self.market.execute(
                    "UPDATE data_quality_issue SET status='open', fix_task_id=NULL "
                    "WHERE status='fixing' AND fix_task_id=?", [tid])
                log.info("任务 %s 终止：复位 %d 条修复中问题为待处理", tid, int(stuck))
            return int(stuck)
        except Exception as e:  # noqa: BLE001  防御：复位失败不影响任务收尾
            log.warning("复位修复中问题失败 tid=%s: %s", tid, e)
            return 0

    # ── 启动期 reconcile（FR-DM-10 + 日志清理 DM-D8）──
    def reconcile(self) -> dict:
        """服务启动调用：残留 running/pending → interrupted；孤儿 fixing → open；清理超期日志。"""
        from backend.services.limit_ladder_snapshot import LimitLadderSnapshotService

        stuck = self.c.query_df(
            "SELECT count(*) AS n FROM async_task WHERE status IN ('pending','running')").iloc[0]["n"]
        resumable_types = sorted(
            task_type for task_type, capability in TASK_CAPABILITIES.items()
            if capability.get("can_resume")
        )
        resume_placeholders = ",".join("?" for _ in resumable_types)
        self.c.execute(
            "UPDATE async_task SET status='interrupted', message=CASE "
            f"WHEN task_type IN ({resume_placeholders}) THEN '服务重启中断，可续跑' "
            "ELSE '服务重启中断，不支持续跑，请重新执行' END, updated_at=? "
            "WHERE status IN ('pending','running')", [*resumable_types, datetime.now()])
        snapshot_states = LimitLadderSnapshotService(
            self.market
        ).recover_processing_after_restart()
        # 重启后没有任何任务在跑，故所有 fixing 必为孤儿（绑定的任务已中断）→ 复位为 open，可重新恢复
        fixing = int(self.market.query_df(
            "SELECT count(*) AS n FROM data_quality_issue WHERE status='fixing'").iloc[0]["n"])
        if fixing:
            self.market.execute(
                "UPDATE data_quality_issue SET status='open', fix_task_id=NULL WHERE status='fixing'")
        cutoff = datetime.now() - timedelta(days=LOG_RETENTION_DAYS)
        self.c.execute("DELETE FROM task_log WHERE ts < ?", [cutoff])
        n = int(stuck)
        if n or fixing or snapshot_states:
            log.info(
                "reconcile：%d 个残留任务标记 interrupted，%d 个天梯处理态转失败，"
                "%d 条修复中问题复位为待处理",
                n,
                snapshot_states,
                fixing,
            )
        return {
            "interrupted": n,
            "limit_ladder_states_recovered": snapshot_states,
            "fixing_reset": fixing,
        }

    def get(self, tid: str) -> dict | None:
        df = self.c.query_df("SELECT * FROM async_task WHERE id=?", [tid])
        if df.empty:
            return None
        return _row(df.iloc[0])

    def cancel(self, tid: str) -> bool:
        """协作式请求终止；执行器在下一检查点停下，并按任务能力声明是否可续跑。"""
        t = self.get(tid)
        if not t or t["status"] not in ("pending", "running"):
            return False
        cap = TASK_CAPABILITIES.get(t["task_type"], {})
        if not cap.get("can_cancel"):
            return False
        with _CANCEL_LOCK:
            _CANCELLED.add(tid)
        self._audit_task(
            action="cancel",
            result="success",
            status="pending",
            task_id=tid,
            task_type=t["task_type"],
        )
        self._set(
            tid,
            message=f"终止中…（{cap.get('cancel_message') or '到下一个检查点停下'}）",
            cancel_requested_at=datetime.now(),
        )
        return True

    @staticmethod
    def _audit_task(
        *,
        action: str,
        result: str,
        status: str,
        task_id: str,
        task_type: str | None = None,
        job_id: str | None = None,
        job_name: str | None = None,
        error_summary: str | None = None,
    ) -> None:
        try:
            from backend.services.audit_service import AuditService

            AuditService().record_task_event(
                action=action,
                result=result,
                status=status,
                task_id=task_id,
                task_type=task_type,
                job_id=job_id,
                job_name=job_name,
                error_summary=error_summary,
            )
        except Exception as e:  # noqa: BLE001
            log.warning("任务审计写入失败，已降级忽略: %s", e)

    _SORT_COLS = {"time": "created_at", "type": "task_type", "status": "status"}

    def list(self, limit: int = 20, status: str | None = None, task_type: str | None = None,
             page: int | None = None, size: int | None = None,
             sort: str = "time", order: str = "desc") -> dict:
        """任务列表（M2.9.5 服务端分页/排序/筛选）。

        page/size 给定 → 分页返回 {tasks,total,page,size}；否则退回 limit 条（兼容旧调用）。
        sort ∈ {time,type,status}，order ∈ {asc,desc}；status/task_type 为精确筛选。
        """
        conds, params = [], []
        if status:
            conds.append("status = ?"); params.append(status)
        if task_type:
            conds.append("task_type = ?"); params.append(task_type)
        where = (" WHERE " + " AND ".join(conds)) if conds else ""
        col = self._SORT_COLS.get(sort, "created_at")
        direction = "ASC" if str(order).lower() == "asc" else "DESC"
        order_sql = f" ORDER BY {col} {direction}, created_at DESC"
        if page is None or size is None:
            df = self.c.query_df(f"SELECT * FROM async_task{where}{order_sql} LIMIT ?", [*params, limit])
            return {"tasks": [_row(r) for _, r in df.iterrows()]}
        total = int(self.c.query_df(
            f"SELECT count(*) AS n FROM async_task{where}", params).iloc[0]["n"])
        off = int((page - 1) * size)
        df = self.c.query_df(
            f"SELECT * FROM async_task{where}{order_sql} LIMIT ? OFFSET ?", [*params, int(size), off])
        return {"tasks": [_row(r) for _, r in df.iterrows()], "total": total,
                "page": page, "size": size}


def _row(r) -> dict:
    import pandas as pd
    d = r.to_dict()
    for k in ("created_at", "updated_at", "cancel_requested_at"):
        value = d.get(k)
        d[k] = None if value is None or pd.isna(value) else str(value)
    if d.get("progress") is not None and not pd.isna(d["progress"]):
        d["progress"] = float(d["progress"])
    for key, default in (("retry_count", 0), ("execution_attempt", 1)):
        value = d.get(key)
        d[key] = default if value is None or pd.isna(value) else int(value)
    for k in ("params", "result"):
        if d.get(k):
            try:
                d[k] = json.loads(d[k])
            except (ValueError, TypeError):
                pass
    cap = dict(TASK_CAPABILITIES.get(d.get("task_type"), {}))
    checkpoint = (d.get("result") or {}).get("checkpoint") if isinstance(d.get("result"), dict) else {}
    if isinstance(checkpoint, dict):
        cap["current_phase"] = checkpoint.get("phase")
        cap["current_item"] = checkpoint.get("current_item")
        cap["checkpoint"] = checkpoint
    d["capability"] = cap
    return d


# ── 任务处理器：(params, ctx) → result dict ─────────────────────────
def _mark_snapshots_stale() -> int:
    """Legacy test seam; data-change handlers no longer invalidate derived results."""
    return 0


def _concurrency(params: dict) -> int | None:
    """从 params 读「采集并发数」并钳到 1~16；缺省返回 None（落回全局默认并发）。

    定时任务可按任务覆盖全局 datasource.update_concurrency；手动任务也能带此参数。
    """
    c = params.get("concurrency")
    if c in (None, "", 0):
        return None
    return max(1, min(int(c), 16))


def _call_with_ctx(fn, *args, ctx: TaskContext, **kwargs):
    """Call newer ctx-aware service methods while keeping tests/old monkeypatches compatible."""
    import inspect

    sig = inspect.signature(fn)
    accepts_ctx = "ctx" in sig.parameters or any(
        p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
    )
    if accepts_ctx:
        return fn(*args, ctx=ctx, **kwargs)
    return fn(*args, **kwargs)


def _h_update(params: dict, ctx: TaskContext) -> dict:
    from backend.services.ingest import IngestionService
    ctx.log("增量更新行情")
    ctx.progress(0.1, "增量更新行情中…")
    res = IngestionService().update(codes=params.get("codes"), concurrency=_concurrency(params), ctx=ctx)
    if res.get("skipped"):
        return {"message": "主源当日数据未就绪，本次增量未执行", "ingest": res}
    return {"message": f"更新完成：{res}", "ingest": res}


def _h_backfill(params: dict, ctx: TaskContext) -> dict:
    from backend.services.ingest import IngestionService
    ctx.log("历史行情补数")
    ctx.progress(0.1, "历史补数中（可能较久）…")
    res = IngestionService().backfill(codes=params.get("codes"), years=params.get("years"),
                                      concurrency=_concurrency(params), ctx=ctx)
    return {"message": f"补数完成：{res}", "ingest": res}


def _h_ingest_date(params: dict, ctx: TaskContext) -> dict:
    """指定日期采集（FR-DM-3 更多选项）：补单日或区间。"""
    from datetime import date as _date

    from backend.services.ingest import IngestionService
    d0 = params.get("date") or params.get("date_start")
    d1 = params.get("date_end") or d0
    if not d0:
        raise ValueError("缺少 date 或 date_start 参数")
    start = _date.fromisoformat(str(d0))
    end = _date.fromisoformat(str(d1))
    ctx.log(f"指定日期行情采集 {start}~{end}")
    ctx.progress(0.1, f"采集 {start}~{end} 行情…")
    res = IngestionService().ingest_date(start, end, codes=params.get("codes"),
                                         concurrency=_concurrency(params), ctx=ctx)
    return {"message": f"指定采集完成：{res}", "ingest": res}


def _h_ingest_codes(params: dict, ctx: TaskContext) -> dict:
    """指定股票采集（FR-DM-3）：对给定 codes 增量补到今天。"""
    from backend.services.ingest import IngestionService
    codes = params.get("codes")
    if not codes:
        raise ValueError("缺少 codes 参数")
    ctx.log(f"指定股票增量采集，{len(codes)} 只")
    ctx.progress(0.1, f"采集 {len(codes)} 只指定股票…")
    res = IngestionService().update(codes=codes, concurrency=_concurrency(params), ctx=ctx)
    if res.get("skipped"):
        return {
            "message": "主源当日数据未就绪，本次指定股票采集未执行",
            "ingest": res,
        }
    return {"message": f"指定股票采集完成：{res}", "ingest": res}


def _h_stock_ingest(params: dict, ctx: TaskContext) -> dict:
    """按安全场景编排个股行情、估值、基础资料与退市股采集。"""
    from datetime import date as _date

    from backend.services.ingest import IngestionService
    from backend.services.stock_ingest import (
        STOCK_INGEST_RECIPE_LABELS,
        normalize_stock_ingest_params,
    )

    normalized = normalize_stock_ingest_params(params)
    recipe = normalized["recipe"]
    label = STOCK_INGEST_RECIPE_LABELS[recipe]
    codes = normalized.get("codes")
    concurrency = _concurrency(normalized)
    ing = IngestionService()
    scope = f"指定 {len(codes)} 只股票" if codes else "全市场"
    ctx.log(f"个股采集方案：{label}；范围：{scope}")
    ctx.progress(0.08, f"{label}准备中…")

    if recipe == "daily_update":
        result = ing.update(
            codes=codes,
            concurrency=concurrency,
            force_current_day=bool(normalized.get("force_current_day")),
            ctx=ctx,
        )
    elif recipe == "history_backfill":
        result = ing.backfill(
            codes=codes, years=normalized.get("years"), concurrency=concurrency, ctx=ctx)
    elif recipe == "range_refetch":
        result = ing.ingest_date(
            _date.fromisoformat(normalized["date_start"]),
            _date.fromisoformat(normalized["date_end"]),
            codes=codes,
            concurrency=concurrency,
            ctx=ctx,
        )
    elif recipe == "share_capital_history":
        if normalized.get("review_only"):
            result = ing.review_capital_history(codes=codes, ctx=ctx, concurrency=concurrency)
        elif normalized.get("recalculate_only"):
            from backend.services.share_capital import ShareCapitalService
            ctx.check_cancel()
            result = ShareCapitalService(ing.c).recalculate_missing(codes)
        else:
            verified = normalized.get("verified_facts")
            if verified:
                from backend.services.share_capital import ShareCapitalService
                ctx.check_cancel()
                rows = ShareCapitalService(ing.c).merge_verified(verified, codes)
                ctx.log(f"已按核验证据导入 {rows} 条总股本事实；继续采集并核验剩余字段")
            result = ing.ingest_share_capital(
                codes=codes, years=normalized.get("years"), concurrency=concurrency, ctx=ctx)
    elif recipe == "valuation_history":
        result = ing.ingest_valuation(
            codes=codes, years=normalized.get("years"), concurrency=concurrency, ctx=ctx)
    elif recipe == "valuation_gaps":
        result = ing.ingest_valuation_gaps(codes=codes, concurrency=concurrency, ctx=ctx)
    elif recipe == "valuation_invalid_history":
        result = ing.repair_invalid_valuation_history(
            codes=codes, concurrency=concurrency, ctx=ctx)
    elif recipe == "st_status_refresh":
        result = ing.refresh_st_status(
            codes=codes,
            start=(
                _date.fromisoformat(normalized["date_start"])
                if normalized.get("date_start") else None
            ),
            end=(
                _date.fromisoformat(normalized["date_end"])
                if normalized.get("date_end") else None
            ),
            ctx=ctx,
        )
    elif recipe == "basic_refresh":
        rows = ing.enrich_basic_dates(ctx=ctx)
        result = {"target": rows, "ok": rows, "fail": 0, "rows": rows}
    else:  # delisted_history：与 CLI delisted --enrich 保持同一先后顺序。
        basic_rows = ing.enrich_basic_dates(ctx=ctx)
        result = ing.ingest_delisted(years=normalized.get("years"), ctx=ctx)
        result["basic_rows"] = basic_rows

    if recipe in {"history_backfill", "range_refetch", "share_capital_history", "valuation_history",
                  "valuation_gaps", "valuation_invalid_history", "delisted_history"}:
        from backend.services.capital_quality import CapitalQualityService
        # 批处理最后统一收敛台账，包括无需联网的重算和已不再进入缺口队列的股票。
        result["capital_quality"] = CapitalQualityService(ing.c).sync(codes)
    if normalized.get("verified_facts"):
        result["verified_fact_rows"] = len(normalized["verified_facts"])
    if result.get("skipped"):
        return {"message": "主源当日数据未就绪，本次日常同步未执行", "ingest": result}
    fail = int(result.get("fail") or 0)
    summary = {key: value for key, value in result.items() if key != "diagnostics"}
    message = f"{label}完成：{summary}"
    payload = {"message": message, "recipe": recipe, "ingest": result}
    if fail:
        payload["message"] = f"{label}部分完成（{fail} 项失败，可重试未完成项）"
        payload["ok"] = False
        ctx.log(payload["message"], "warn")
        return payload
    ctx.progress(1.0, f"{label}完成")
    return payload


def _h_recompute(params: dict, ctx: TaskContext) -> dict:
    """Explicitly invalidate daily-board score snapshots; reads rematerialize them later."""
    from backend.scoring.snapshot import ScoreSnapshotRepo
    from backend.services.result_maintenance import (
        normalize_score_invalidation_params,
        resolve_target_date,
    )

    normalized = normalize_score_invalidation_params(params)
    target_date = resolve_target_date(normalized, ctx.svc.market)
    scope = "全部快照" if target_date is None else target_date.isoformat()
    ctx.log(f"每日榜单失效：目标范围 {scope}")
    ctx.progress(0.5, "标记评分快照失效…")
    repo = ScoreSnapshotRepo(ctx.svc.market)
    stale = repo.mark_stale_all() if target_date is None else repo.mark_stale_dates([target_date])
    ctx.log(f"已标记 {stale} 项评分快照失效；下次读取时按需重算")
    return {
        "message": f"每日榜单失效完成：{stale} 项，目标范围 {scope}",
        "snapshots_marked_stale": stale,
        "target_mode": normalized["target_mode"],
        "trade_date": target_date.isoformat() if target_date else None,
    }


def _h_rebuild_price_factors(params: dict, ctx: TaskContext) -> dict:
    from backend.services.ingest import IngestionService
    ctx.log("重算价格因子")
    ctx.progress(0.05, "重算价格因子…")
    codes = params.get("codes")
    res = IngestionService().rebuild_price_factors(codes=codes, ctx=ctx)
    return {"message": f"价格因子重算完成：{res}", "rebuild": res}


def _h_verify(params: dict, ctx: TaskContext) -> dict:
    """数据质检（与定时/手动质检同一方法 scan_quality_issues，口径一致）。

    四层 + ST 点时事实统一扫描写质量台账（幂等覆盖自动问题）：
    L2 字段契约（市值缺失、非正或总市值倒挂超过万分之一容差）/
    L3 正确性（异常涨跌、复权跳变）/ L4 覆盖鲜活（缺口、滞后）。
    L1 入库闸门由采集即时记录。停牌（已确认）不计入缺口。
    """
    from backend.services.data_report import DataIntegrityReport
    ctx.progress(0.3, "全市场四层数据质检中…")
    ctx.log("数据质检：扫描市值 / 行情 / 复权 / 覆盖鲜活 / ST 点时事实，写入质量台账")
    rep = DataIntegrityReport()
    q = rep.scan_quality_issues()
    # 市场指数与板块维度同一质检任务内扫描，统一进入问题台账与恢复闭环。
    q["market_index"] = rep.scan_market_index_quality()
    q["board"] = rep.scan_board_quality()
    base_count = sum(int(q.get(k, 0)) for k in
            ("abnormal_change_rows", "price_volume_mismatch_rows", "adj_jump_rows",
             "mv_missing_rows", "mv_gap_rows", "mv_invalid_rows",
             "capital_gap_rows", "capital_invalid_rows", "capital_mismatch_rows",
             "data_gap_rows", "history_data_gap_rows", "stale_rows", "st_status_missing_rows",
             "st_status_approximate_rows", "st_status_mismatch_rows"))
    market_index = q.get("market_index") or {}
    b = q.get("board") or {}
    n = base_count + sum(int(v) for v in market_index.values()) + sum(int(v) for v in b.values())
    ctx.log(f"质检完成：异常涨跌 {q.get('abnormal_change_rows', 0)}、"
            f"价量错配 {q.get('price_volume_mismatch_rows', 0)}、"
            f"复权跳变 {q.get('adj_jump_rows', 0)}、"
            f"市值缺失 {q.get('mv_missing_rows', 0)}、市值缺口 {q.get('mv_gap_rows', 0)}、"
            f"市值非法 {q.get('mv_invalid_rows', 0)}、"
            f"历史股本市值缺失 {q.get('capital_gap_rows', 0)}、"
            f"股本市值非法 {q.get('capital_invalid_rows', 0)}、"
            f"股本市值不一致 {q.get('capital_mismatch_rows', 0)}、"
            f"历史缺口 {q.get('history_data_gap_rows', 0)}、近端缺口 {q.get('data_gap_rows', 0)}、滞后 {q.get('stale_rows', 0)}、"
            f"ST缺失 {q.get('st_status_missing_rows', 0)}、"
            f"ST非权威 {q.get('st_status_approximate_rows', 0)}、"
            f"ST投影不一致 {q.get('st_status_mismatch_rows', 0)}、"
            f"市场指数缺口 {market_index.get('index_gap', 0)}、"
            f"板块指数缺口 {b.get('index_gap', 0)}")
    return {"message": f"质检完成：发现 {n} 项问题" if n else "质检完成：未发现新问题", "quality": q}


def _h_checkup(params: dict, ctx: TaskContext) -> dict:
    """数据结构体检（DataVerifier）：本地 SQL 的结构/价格正确性/字段契约/板块数据核查，返回结构化报告。

    与质检（_h_verify 写台账+修复闭环）互补：体检覆盖全历史结构、完整性和字段关系；
    股本市值质检覆盖全历史，其余类型按各自窗口聚合问题并写台账。体检只读、不写台账，cross=True 时附加联网交叉验证
    （默认关闭）。
    """
    from backend.services.data_verify import DataVerifier
    cross = bool(params.get("cross", False))
    ctx.progress(0.3, "数据结构体检中…")
    ctx.log("数据体检：结构/完整性 + 价格正确性 + 字段契约 + 板块数据" + ("（含联网交叉验证）" if cross else ""))
    report = DataVerifier(quiet=True).run_structured(cross=cross)
    for g in report["groups"]:
        bad = [c["name"] for c in g["checks"] if c["status"] == "fail"]
        warnings = [c["name"] for c in g["checks"] if c["status"] == "warn"]
        passed = len(g["checks"]) - len(bad) - len(warnings)
        ctx.log(
            f"{g['group']}：{passed} 通过 / {len(warnings)} 提醒 / {len(g['checks'])} 总项"
            + (f"；提醒：{', '.join(warnings)}" if warnings else "")
            + (f"；未过：{', '.join(bad)}" if bad else "")
        )
    if report["all_ok"]:
        msg = f"体检通过：{report['passed']} 通过"
        if report["warning_count"]:
            msg += f"，{report['warning_count']} 项提醒"
    else:
        msg = (
            f"体检发现 {len(report['fails'])} 项未通过"
            f"（{report['passed']} 通过，{report['warning_count']} 提醒）"
        )
    ctx.log(msg)
    return {"message": msg, "checkup": report}


def _h_audit_cleanup(params: dict, ctx: TaskContext) -> dict:
    """按 audit.retention_days 清理超保留期审计日志，供任务调度页配置执行频率。"""
    from backend.services.audit_service import AuditService

    ctx.progress(0.2, "审计日志清理中…")
    ctx.log("按 audit.retention_days 清理超保留期审计日志")
    result = AuditService().cleanup_expired()
    if not result.get("ok"):
        raise RuntimeError(result.get("error") or result.get("reason") or "审计日志清理失败")
    if result.get("skipped"):
        message = f"审计日志清理跳过：{result.get('reason') or '无可清理数据'}"
    else:
        message = f"审计日志清理完成：删除 {int(result.get('affected_count') or 0)} 条"
    ctx.progress(1.0, message)
    return {"message": message, "audit_cleanup": result}


def _h_enrich_basic(params: dict, ctx: TaskContext) -> dict:
    """刷新基础资料（上市/退市日及行业），并可选灌退市股历史（防幸存者偏差）。

    退市标记 stock_basic.delist_date 仅在此刷新；而增量更新靠 `delist_date IS NULL` 选标的，
    故须定期跑本任务——否则新退市股的 delist_date 恒为 NULL，会被增量当在市股反复采集
    （主源无此股 → 取数失败刷错误日志）。建议每周一次（退市为低频事件）。

    params：
      - ingest_delisted（默认 False）：True 时附带灌入近 N 年退市股历史日线。
      - years/limit：传给 ingest_delisted（仅 ingest_delisted=True 时生效）。
    """
    from backend.services.ingest import IngestionService
    ing = IngestionService()
    ctx.log("阶段 1/2：刷新股票基础信息、上市/退市日、行业")
    ctx.progress(0.1, "刷新基础资料（上市/退市日及行业）…")
    n = ing.enrich_basic_dates(ctx=ctx)
    ctx.log(f"已刷新基础信息 {n} 只（含退市股打标 delist_date）")
    res: dict = {"basic_rows": n}
    if params.get("ingest_delisted"):
        ctx.log("阶段 2/2：灌入退市股历史行情")
        ctx.progress(0.5, "灌入退市股历史（防幸存者偏差，可能较久）…")
        dl = ing.ingest_delisted(years=params.get("years"), limit=params.get("limit"), ctx=ctx)
        ctx.log(f"退市股灌入：{dl}")
        res["delisted"] = dl
    else:
        ctx.log("阶段 2/2：退市股历史灌入跳过（参数未开启）")
    ctx.progress(1.0, "完成")
    return {"message": f"基础信息刷新 {n} 只" + ("（含退市股历史）" if "delisted" in res else ""), **res}


def _reingest_board_bar_with_retry(
    bsvc, code: str, start, end, ctx: TaskContext
) -> dict:
    """板块指数定向重采：返回 0 行时按 ths_board 配置指数退避重试。

    粗粒度末尾缺口可传连续区间，逐日缺口/非法值传单日。源端按年返回 K 线，
    定向请求可能因数据暂未发布而返回空（如盘后源端延迟）。与网络层重试对齐：
    读取系统配置 ths_board.max_retries / retry_backoff_sec。
    """
    from backend.config import get_effective_settings

    cfg = get_effective_settings().ths_board
    max_retries = cfg.max_retries
    backoff = cfg.retry_backoff_sec
    last_res = None
    for attempt in range(1, max_retries + 1):
        # 每次重试都是新的独立采集请求，先清掉上次调用写入的 bar_done_codes，
        # 否则 ingest_board_bar 会把该板块误判为“续跑已完成”而直接跳过。
        ctx.checkpoint.pop("bar_done_codes", None)
        res = _call_with_ctx(
            bsvc.ingest_board_bar, start, end=end, board_codes=[code], ctx=ctx)
        if res.get("failed"):
            raise RuntimeError(f"板块指数重采失败：{res['failed']}")
        last_res = res
        rows = res.get("rows", 0)
        if rows > 0:
            return res
        if attempt < max_retries:
            sleep = backoff * (2 ** (attempt - 1))
            date_range = str(start) if start == end else f"{start}~{end}"
            ctx.log(f"板块 {code} {date_range} 指数重采返回 0 行，"
                    f"{sleep:.1f}s 后第 {attempt + 1} 次重试")
            import time
            time.sleep(sleep)
    return last_res


def _board_trailing_gap_range(c, code: str, fallback_end):
    """返回板块末尾连续缺口的定向恢复区间，避免固定从历史起点整段重采。

    截止日以 daily_bar 当前全局最新日为准，保证旧 issue 延迟执行时仍能追到最新。
    已有指数时从其下一开市日开始；从未入库时无法判断板块成立日，只恢复最新日，
    后续逐日缺口由实际数据起点和质检窗口继续识别。
    """
    import pandas as pd

    latest = c.query_df("SELECT max(trade_date) AS d FROM daily_bar").iloc[0]["d"]
    end = pd.Timestamp(latest).date() if latest is not None and not pd.isna(latest) else fallback_end
    if end is None:
        raise RuntimeError("板块指数缺口缺少可恢复的目标交易日")

    last = c.query_df(
        "SELECT max(trade_date) AS d FROM board_bar WHERE board_code=?", [code]
    ).iloc[0]["d"]
    if last is None or pd.isna(last):
        return end, end
    last = pd.Timestamp(last).date()
    if last >= end:
        return None, end

    next_open = c.query_df(
        "SELECT min(trade_date) AS d FROM trade_calendar "
        "WHERE is_open AND trade_date>? AND trade_date<=?",
        [last, end],
    ).iloc[0]["d"]
    start = pd.Timestamp(next_open).date() if next_open is not None and not pd.isna(next_open) else end
    return start, end


def _market_index_trailing_gap_range(c, code: str, fallback_end):
    """返回配置市场指数的末尾恢复区间；从未入库时回填系统历史窗口。"""
    import pandas as pd

    from backend.config import get_effective_settings

    latest = c.query_df("SELECT max(trade_date) AS d FROM daily_bar").iloc[0]["d"]
    end = pd.Timestamp(latest).date() if latest is not None and not pd.isna(latest) else fallback_end
    if end is None:
        raise RuntimeError("市场指数缺口缺少可恢复的目标交易日")

    last = c.query_df(
        "SELECT max(trade_date) AS d FROM index_bar WHERE index_code=?", [code]
    ).iloc[0]["d"]
    if last is None or pd.isna(last):
        history_start = (
            pd.Timestamp(end)
            - pd.DateOffset(years=get_effective_settings().datasource.history_years)
        ).date()
        first_open = c.query_df(
            "SELECT min(trade_date) AS d FROM trade_calendar "
            "WHERE is_open AND trade_date>=? AND trade_date<=?",
            [history_start, end],
        ).iloc[0]["d"]
        start = pd.Timestamp(first_open).date() \
            if first_open is not None and not pd.isna(first_open) else history_start
        return start, end
    last = pd.Timestamp(last).date()
    if last >= end:
        return None, end
    next_open = c.query_df(
        "SELECT min(trade_date) AS d FROM trade_calendar "
        "WHERE is_open AND trade_date>? AND trade_date<=?",
        [last, end],
    ).iloc[0]["d"]
    start = pd.Timestamp(next_open).date() if next_open is not None and not pd.isna(next_open) else end
    return start, end


def _reingest_market_index(ing, code: str, start, end, ctx: TaskContext) -> int:
    """调用既有指数采集能力定向恢复；0 行视为未恢复并让任务失败回到 open。"""
    rows = ing.ingest_indices(start, end, ctx=ctx, codes=[code])
    if rows <= 0:
        date_range = str(start) if start == end else f"{start}~{end}"
        raise RuntimeError(f"市场指数 {code} {date_range} 重采返回 0 行")
    return int(rows)


def _recover_one(c, rep, ing, ctx: TaskContext, issue_id: int) -> tuple[bool, list, str]:
    """恢复单条质检问题 → 复检 → 回写状态。返回 (复检是否通过, 受影响日期, 文案)。"""
    import pandas as pd
    df = c.query_df(
        "SELECT code, trade_date, issue_type, detail, status "
        "FROM data_quality_issue WHERE id=?", [issue_id])
    if df.empty:
        raise ValueError(f"质检问题不存在: id={issue_id}")
    current_status = str(df.iloc[0]["status"])
    if current_status == "resolved":
        # 已被其它扫描/任务收敛为已解决（如板块 fix 修完重扫把兄弟 issue 一并收敛）：
        # 视为已解决跳过，不报失败——批量任务里同板块兄弟问题会被重扫先收敛。
        return True, [], "已被扫描收敛为已解决，无需再修"
    if current_status != "open":
        raise ValueError(f"仅未处理问题可恢复: id={issue_id}, status={current_status}")
    code, trade_date, issue_type = df.iloc[0]["code"], df.iloc[0]["trade_date"], df.iloc[0]["issue_type"]
    issue_detail = df.iloc[0]["detail"]
    td = None if trade_date is None or pd.isna(trade_date) \
        else pd.Timestamp(trade_date).date()
    scan_board_types = {
        "board_index_gap", "board_index_gap_daily", "board_index_invalid",
        "board_fund_missing", "board_fund_stale",
    }
    scan_market_index_types = {
        "market_index_gap", "market_index_gap_daily", "market_index_invalid",
    }
    # 进入 fixing 并绑定本任务 id：任务失败/中断/重启时据 fix_task_id 复位，不留孤儿（DM 修复中闭环）
    c.execute("UPDATE data_quality_issue SET status='fixing', fix_task_id=? WHERE id=?", [ctx.tid, issue_id])

    # 恢复+复检全程包在 try 内：任何异常（如源端取数失败 DataSourceError）都先把状态复位为 open
    # 再上抛——绝不留悬空 fixing，且让 _h_fix 如实计入失败（不再"日志失败、状态修复中、却报成功"）。
    try:
        affected: list = []
        note = ""
        # 质检后普通采集可能已补齐数据；先按同一口径复检，避免旧台账重复请求源端。
        # 仍走下方状态回写和关联扫描，不能只跳过采集而留下 open 旧问题。
        if issue_type in (scan_board_types | scan_market_index_types | {"abnormal_change"}) and rep.recheck_clean(
            issue_type, code, td, detail=issue_detail,
        ):
            note = "目标数据已满足复检要求，无需重复采集"
            ctx.log(f"{code or '全源'}：{note}")
        elif issue_type in ("capital_gap", "capital_invalid", "capital_mismatch"):
            if rep.recheck_clean(issue_type, code, td, detail=issue_detail):
                from backend.services.capital_quality import CapitalQualityService
                CapitalQualityService(c).sync([code])
                note = "全历史复检已通过，无需重复采集"
            else:
                ctx.log(f"恢复(股本市值)：{code} 全历史多来源补采与复检")
                res = ing.repair_capital_quality(code, ctx=ctx)
                note = "多来源核验完成"
                reasons = res.get("diagnostics", {}).get(code, {}).get("remaining", {})
                if reasons:
                    from backend.services.capital_quality import REASON_LABELS, reasons_for_issue
                    reasons = reasons_for_issue(issue_type, reasons)
                    labels = dict.fromkeys(label for reason in reasons for suffix,label in REASON_LABELS.items()
                                           if reason.endswith(suffix))
                    note += "；" + "、".join(labels)
        elif issue_type == "mv_missing":
            ctx.log(f"恢复(L2 字段契约)：拉取 {code} 估值，补市值字段")
            res = _call_with_ctx(ing.ingest_valuation, codes=[code], ctx=ctx)
            note = f"补市值 {res.get('total_mv_rows', 0)} 行"
        elif issue_type == "mv_gap":
            ctx.log(f"恢复(L2 逐日缺口)：补 {code} 的市值字段缺失天")
            res = _call_with_ctx(ing.ingest_valuation_gaps, codes=[code], ctx=ctx)
            note = f"补市值缺口 {res.get('total_mv_rows', 0)} 行"
        elif issue_type == "mv_invalid":
            ctx.log(f"恢复(L2 市值合法性)：刷新 {code} 的非法市值日期")
            res = _call_with_ctx(ing.repair_invalid_valuation, code, ctx=ctx)
            note = (
                f"刷新异常市值 {res.get('total_mv_rows', 0)}/"
                f"{res.get('target_days', 0)} 天"
            )
        elif issue_type in ("data_gap", "stale", "history_data_gap"):
            ctx.log(f"恢复(L4 覆盖鲜活)：按缺口收口重采 {code}（与增量更新同口径）")
            r = ing.reconcile_gaps(code, ctx=ctx, full_history=issue_type == "history_data_gap")
            if not r["miss"]:
                note = "无待补缺口（可能已被其它任务补齐）"
            else:
                affected = r["backfilled"]
                note = ing.reconcile_note(r)
                ctx.log(f"重采写入 {r['rows']} 行；{note}"
                        f"（仅有明确停牌证据者确认停牌，其余保留缺口）")
        elif issue_type in (
            "null_close", "ohl_repaired", "abnormal_change", "price_volume_mismatch"
        ):
            if td:
                ctx.log(f"恢复：重采 {code} {td} 单日行情")
                if issue_type == "abnormal_change":
                    # 主源重采仍可能复现错价/遗漏重整因子；整段用既有备用源保持因子基准一致。
                    span = c.query_df(
                        "SELECT min(trade_date) lo,max(trade_date) hi FROM daily_bar WHERE code=?",
                        [code],
                    ).iloc[0]
                    lo, hi = pd.Timestamp(span["lo"]).date(), pd.Timestamp(span["hi"]).date()
                    ing.ingest_one_daily(code, lo, hi, source=ing._bao_source(), ctx=ctx)
                    factors = ing._recompute_clean([code])
                    if factors["fail"]:
                        raise RuntimeError(f"{code} 备用源历史复权重算失败")
                elif issue_type == "ohl_repaired":
                    # 主源已证实缺少 OHL，重试同一响应不能修复；用既有备用源核验成交/停牌。
                    ing.ingest_one_daily(code, td, td, source=ing._bao_source(), ctx=ctx)
                else:
                    ing.ingest_one_daily(code, td, td, ctx=ctx)
                affected = [td]
            else:
                note = "缺少日期，无法定向重采"
        elif issue_type == "adj_jump":
            span = c.query_df(
                "SELECT min(trade_date) lo, max(trade_date) hi FROM daily_bar WHERE code=?", [code]).iloc[0]
            if not pd.isna(span["lo"]):
                lo, hi = pd.Timestamp(span["lo"]).date(), pd.Timestamp(span["hi"]).date()
                ctx.log(f"恢复(L3 复权口径)：重采 {code} {lo}~{hi} 整段")
                ing.ingest_one_daily(code, lo, hi, ctx=ctx)
            else:
                note = "无行情可重算"
        elif issue_type in (
            "st_status_missing", "st_status_approximate", "st_status_mismatch"
        ):
            ctx.log(f"恢复(ST 点时事实)：刷新 {code} 上市/行情起点至市场最新日的事实（含停牌）")
            res = ing.refresh_st_status(codes=[str(code)], ctx=ctx)
            if int(res.get("fail") or 0):
                raise RuntimeError(f"ST 状态刷新失败：{res.get('failures')}")
            affected = [
                pd.Timestamp(value).date()
                for value in res.get("changed_date_values", [])
            ]
            note = f"刷新 ST 事实 {res.get('rows', 0)} 行"
        elif issue_type == "market_index_gap":
            repair_start, repair_end = _market_index_trailing_gap_range(c, str(code), td)
            if repair_start is None:
                note = f"市场指数已追平 {repair_end}，无需重复重采"
            else:
                ctx.log(f"恢复(市场指数缺口)：重采 {code} {repair_start}~{repair_end}")
                rows = _reingest_market_index(
                    ing, str(code), repair_start, repair_end, ctx
                )
                note = f"重采指数 {rows} 行"
            ctx.log(note)
        elif issue_type in ("market_index_gap_daily", "market_index_invalid"):
            if td is None:
                note = "缺少日期，无法定向重采"
            else:
                reason = "逐日缺口" if issue_type == "market_index_gap_daily" else "数据异常"
                ctx.log(f"恢复(市场指数{reason})：重采 {code} {td}")
                rows = _reingest_market_index(ing, str(code), td, td, ctx)
                note = f"重采指数 {rows} 行"
                ctx.log(note)
        elif issue_type == "board_index_gap":
            # 末尾缺口：只补「最后已有日的下一交易日 → 当前全局最新日」，不再固定从 2024
            # 整段重采。这样连续缺两日会一次补两日，也不会被无关历史年份失败拖累。
            from backend.services.board_ingest import BoardIngestService
            repair_start, repair_end = _board_trailing_gap_range(c, str(code), td)
            if repair_start is None:
                note = f"板块指数已追平 {repair_end}，无需重复重采"
            else:
                ctx.log(f"恢复(板块指数缺口)：重采板块 {code} "
                        f"{repair_start}~{repair_end} 指数")
                bsvc = BoardIngestService(c)
                res = _reingest_board_bar_with_retry(
                    bsvc, str(code), repair_start, repair_end, ctx)
                note = f"重采指数 {res.get('rows', 0)} 行"
            ctx.log(note)
        elif issue_type == "board_index_gap_daily":
            # 板块指数逐日缺口：按缺失日窄窗口重采该板块指数。
            # 源端按年返回 K 线，传入 start=end=缺失日即可触发该年数据回填；幂等 upsert。
            # 单日请求可能因源端数据暂未发布返回 0 行，按 ths_board 配置重试。
            from backend.services.board_ingest import BoardIngestService
            if td is None:
                note = "缺少日期，无法定向重采"
            else:
                ctx.log(f"恢复(板块指数逐日缺口)：重采板块 {code} {td} 指数")
                bsvc = BoardIngestService(c)
                res = _reingest_board_bar_with_retry(bsvc, code, td, td, ctx)
                note = f"重采指数 {res.get('rows', 0)} 行"
                ctx.log(note)
        elif issue_type == "board_index_invalid":
            # 已有记录内容非法：按问题日期定向重采；源端按年返回，仍会幂等覆盖同年记录。
            # 与 board_index_gap_daily 同样对单日 0 行做重试，避免源端延迟误报失败。
            from backend.services.board_ingest import BoardIngestService
            if td is None:
                note = "缺少日期，无法定向重采"
            else:
                ctx.log(f"恢复(板块指数数据异常)：重采板块 {code} {td} 指数")
                bsvc = BoardIngestService(c)
                res = _reingest_board_bar_with_retry(bsvc, code, td, td, ctx)
                note = f"重采指数 {res.get('rows', 0)} 行"
                ctx.log(note)
        elif issue_type == "board_member_incomplete":
            # 成分快照采集不完整/失败：重采该板块成分快照（只进不出，完整才落库）
            from backend.services.board_ingest import BoardIngestService
            ctx.log(f"恢复(成分快照不完整)：重采板块 {code} 成分快照")
            bsvc = BoardIngestService(c)
            # force=True：质量修复必须绕过周频跳过，否则修复会被跳过逻辑挡住
            res = _call_with_ctx(bsvc.ingest_board_members, board_codes=[code], ctx=ctx, force=True)
            r = res.get(code, {})
            if "error" in r:
                raise RuntimeError(f"板块成分重采失败：{r['error']}")
            if not r:
                raise RuntimeError(f"板块成分重采失败：字典中不存在 {code}")
            note = f"成分 {r.get('total', 0)} 只，新增 {r.get('added', 0)} 只"
            ctx.log(note)
        elif issue_type == "board_fund_unmatched":
            # 资金流未匹配：重采全周期资金流（字典补齐后所有周期都可能需要刷新），重扫收敛
            import json as _json

            from backend.services.board_ingest import BoardIngestService
            ctx.log("恢复(资金流未匹配)：重采板块资金流")
            issue_payload = {}
            if isinstance(issue_detail, str):
                try:
                    issue_payload = _json.loads(issue_detail)
                except (TypeError, ValueError):
                    issue_payload = {}
            repair_board_type = issue_payload.get("board_type")
            bsvc = BoardIngestService(c)
            _call_with_ctx(bsvc.ingest_board_dict, board_type=repair_board_type, ctx=ctx)
            res = _call_with_ctx(
                bsvc.ingest_board_fund_flow,
                board_type=repair_board_type, ctx=ctx)
            if res.get("failed"):
                raise RuntimeError(f"板块资金流重采失败：{res['failed']}")
            note = f"重采资金流 {res.get('rows', 0)} 行（未匹配 {res.get('unmatched', 0)}）"
            ctx.log(note)
        elif issue_type == "board_fund_missing":
            # 目标日传入服务做源能力校验；实时排行禁止倒填历史日或混入盘中快照。
            import json as _json

            from backend.services.board_ingest import BoardIngestService
            issue_payload = {}
            if isinstance(issue_detail, str):
                try:
                    issue_payload = _json.loads(issue_detail)
                except (TypeError, ValueError):
                    issue_payload = {}
            periods_list = issue_payload.get("periods") if isinstance(issue_payload, dict) else None
            if not periods_list:
                periods_list = ("即时",)
            if td is None:
                raise RuntimeError("板块资金流缺失问题缺少目标交易日，无法定向重采")
            ctx.log(f"恢复(板块资金流缺失)：重采板块 {code} 周期 {list(periods_list)}")
            bsvc = BoardIngestService(c)
            res = _call_with_ctx(
                bsvc.ingest_board_fund_flow, snapshot_date=td, periods=tuple(periods_list),
                board_codes=[code], ctx=ctx)
            if res.get("failed"):
                raise RuntimeError(f"板块资金流重采失败：{res['failed']}")
            note = f"重采资金流 {res.get('rows', 0)} 行"
            ctx.log(note)
        elif issue_type == "board_fund_stale":
            # 资金流滞后（源级单条）：从 detail.periods 解析滞后周期列表定向重采全源；
            # detail 无 periods（旧纯文本 issue）回退全周期。快照追平后重扫收敛。
            import json as _json

            from backend.services.board_ingest import BoardIngestService
            issue_payload = {}
            if isinstance(issue_detail, str):
                try:
                    issue_payload = _json.loads(issue_detail)
                except (TypeError, ValueError):
                    issue_payload = {}
            stale_periods = issue_payload.get("periods") if isinstance(issue_payload, dict) else None
            if not stale_periods:
                ctx.log("恢复(板块资金流滞后)：重采全源资金流全周期")
                periods_arg = None
            else:
                ctx.log(f"恢复(板块资金流滞后)：重采全源资金流周期 {list(stale_periods)}")
                periods_arg = tuple(stale_periods)
            if td is None:
                raise RuntimeError("板块资金流滞后问题缺少目标交易日，无法定向重采")
            bsvc = BoardIngestService(c)
            res = _call_with_ctx(
                bsvc.ingest_board_fund_flow,
                snapshot_date=td, periods=periods_arg, ctx=ctx)
            if res.get("failed"):
                raise RuntimeError(f"板块资金流重采失败：{res['failed']}")
            note = f"重采资金流 {res.get('rows', 0)} 行"
            ctx.log(note)
        else:
            ctx.log(f"未知问题类型 {issue_type}，仅复检", "warn")

        clean = rep.recheck_clean(issue_type, code, td, detail=issue_detail)
    except Exception:
        # 恢复中途失败：复位为待处理（清绑定）再上抛，由 _h_fix 计入失败、不污染状态
        c.execute("UPDATE data_quality_issue SET status='open', fix_task_id=NULL WHERE id=?", [issue_id])
        raise

    if clean:
        c.execute("UPDATE data_quality_issue SET status='resolved', resolved_at=?, fix_task_id=NULL WHERE id=?",
                  [datetime.now(), issue_id])
        # 扫描型板块问题可能共享同一底层缺口：例如最新日缺失同时产生 index_gap 与
        # index_gap_daily。当前问题解决后立即重扫，收敛兄弟问题并发现全源资金流恢复后的
        # 逐板块缺失；扫描失败不回滚已真实修好的当前问题，但在任务日志中明确告警。
        if issue_type in scan_board_types:
            try:
                scan_result = rep.scan_board_quality()
                ctx.log(f"板块关联问题复检完成：{scan_result}")
            except Exception as scan_error:  # noqa: BLE001 -- 当前问题已复检通过，关联扫描降级告警
                ctx.log("本条问题已复检通过并关闭；其他板块的质量检查未完成，"
                        f"旧问题状态可能尚未更新，请重新质检。错误：{scan_error}", "warn")
                note += "；本条已解决，其他板块的质量检查未完成，请重新质检"
        if issue_type in scan_market_index_types:
            try:
                scan_result = rep.scan_market_index_quality()
                ctx.log(f"市场指数关联问题复检完成：{scan_result}")
            except Exception as scan_error:  # noqa: BLE001 -- 当前问题已真实修复
                ctx.log(f"当前问题已解决，但市场指数关联问题复检失败：{scan_error}", "warn")
                note += "；关联问题复检失败，请稍后重新质检"
    else:
        c.execute("UPDATE data_quality_issue SET status='open', fix_task_id=NULL WHERE id=?", [issue_id])
    msg = (f"已恢复：{code} {note}（复检通过，已解决）" if clean
           else f"{code} {note}（复检未通过：问题仍在，疑源端口径，保持待处理）")
    return bool(clean), affected, msg


def _h_fix(params: dict, ctx: TaskContext) -> dict:
    """质检问题定向恢复（FR-DM-4，DM-D22）：按问题类型分派恢复手段 → 复检 → 仅复检通过才置已解决。

    支持单条 `issue_id`、批量 `issue_ids`，或定时任务使用的 `issue_type`。
    `issue_type` 会在每次真正执行时动态查询当前 open 问题，不把过期问题 ID 固化到调度定义。
    - mv_missing(L2)        → ingest_valuation([code])（补市值字段，不是重拉行情）
    - mv_invalid(L2)        → repair_invalid_valuation(code)（只强制覆盖异常日期）
    - data_gap/stale(L4)    → 反向重采缺口区间：补回的入库；取得逐日停牌状态证据后才写 stock_suspension
    - null_close/abnormal   → 重采该单日；adj_jump → 重采该股整段 + 重算复权
    复检由 DataIntegrityReport.recheck_clean 判定：通过 → resolved；未通过 → 保持 open。
    """
    from backend.services.data_report import DataIntegrityReport
    from backend.services.ingest import IngestionService
    c = get_client()
    rep = DataIntegrityReport(c)
    ing = IngestionService()
    ids = params.get("issue_ids")
    if not ids:
        iid = params.get("issue_id")
        if iid is not None:
            ids = [iid]
        else:
            from backend.dataquality.checker import QUALITY_ISSUE_TYPES

            issue_type = str(params.get("issue_type") or "").strip()
            if issue_type not in QUALITY_ISSUE_TYPES:
                raise ValueError(
                    f"缺少或非法的 issue_type: {issue_type or '-'}"
                    f"（可选 {QUALITY_ISSUE_TYPES}）"
                )
            # 定时恢复只接管待处理问题。fixing 属于另一任务或异常残留，
            # 应由在跑任务/reconcile/手工复位收口，避免定时任务抢占归属。
            ids = c.query_df(
                "SELECT id FROM data_quality_issue "
                "WHERE issue_type=? AND status='open' ORDER BY id",
                [issue_type],
            )["id"].tolist()
            ctx.log(f"定时恢复动态取数：{issue_type} 当前待处理 {len(ids)} 条")
    ids = [int(x) for x in ids]
    done_ids = set(int(x) for x in (ctx.checkpoint.get("issue_done_ids") or [])) if ctx.checkpoint else set()
    ids = [x for x in ids if x not in done_ids]
    n = len(ids)
    if n == 0:
        issue_type = str(params.get("issue_type") or "").strip()
        message = f"质检问题恢复完成：{issue_type} 当前无待处理问题"
        ctx.progress(1.0, message)
        return {"message": message, "ok": True, "resolved": 0, "failed": 0, "total": 0}
    resolved = 0
    failed = 0
    last_msg = ""
    last_err = ""
    phase_total = len(done_ids) + n
    ctx.set_phase("fix_issue", done=len(done_ids), total=phase_total,
                  phase_total=phase_total, phase_done=len(done_ids),
                  current_item=None, issue_done_ids=sorted(done_ids))
    for i, iid in enumerate(ids, 1):
        ctx.check_cancel()
        ctx.set_phase("fix_issue", done=len(done_ids), total=phase_total,
                      phase_total=phase_total, phase_done=len(done_ids),
                      current_item=iid, issue_done_ids=sorted(done_ids))
        ctx.progress(min(0.1 + 0.8 * (i - 1) / n, 0.9), f"恢复 {i}/{n}…")
        try:
            clean, _affected, msg = _recover_one(c, rep, ing, ctx, iid)
            resolved += int(clean)
            last_msg = msg
            if clean:
                done_ids.add(iid)
            ctx.set_phase("fix_issue", done=len(done_ids), total=phase_total,
                          phase_total=phase_total, phase_done=len(done_ids),
                          current_item=iid, issue_done_ids=sorted(done_ids))
            ctx.log(f"[{i}/{n}] {msg}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            last_err = str(e)
            ctx.set_phase("fix_issue", done=len(done_ids), total=phase_total,
                          phase_total=phase_total, phase_done=len(done_ids),
                          current_item=iid, issue_done_ids=sorted(done_ids))
            ctx.log(f"[{i}/{n}] 恢复失败 id={iid}: {e}（已退回待处理）", "error")
    # 诚实文案：区分 已解决 / 复检未通过(仍 open) / 恢复失败(异常退回 open)。单条直接给原因。
    if n == 1:
        msg = (last_msg if not failed
               else f"恢复失败，已退回待处理：{last_err or '源端取数失败'}")
    else:
        msg = f"批量恢复完成：{resolved}/{n} 条已解决"
        if failed:
            msg += f"，{failed} 条恢复失败（已退回待处理，详见日志）"
    # ok：单条=是否解决；批量=有解决且无失败时视为成功（部分失败由 ok=false 让前端给警告）
    ok = (resolved == n)
    return {"message": msg, "ok": ok, "resolved": resolved, "failed": failed, "total": n}


def _h_board(params: dict, ctx: TaskContext) -> dict:
    """板块采集（板块概念需求 R5）：字典→成分快照→指数→资金流。

    params.mode=backfill/update（默认 update）；params.codes 指定板块子集（采集页
    「指定板块」/重采用），未传则全量。中断后续跑会按字典类型、板块代码和资金流周期的
    阶段 checkpoint 跳过已经成功的工作单元。
    """
    from backend.services.board_ingest import (
        normalize_board_date_range,
        normalize_board_force_current_day,
        normalize_board_stages,
    )
    from backend.services.ingest import IngestionService
    # codes 兼容数组与逗号分隔字符串（对齐 only 参数的处理，避免字符串被逐字符拆散）
    raw_codes = params.get("codes") or []
    if isinstance(raw_codes, str):
        raw_codes = [x for x in raw_codes.split(",") if x.strip()]
    spec_codes = [str(x).strip() for x in raw_codes if str(x).strip()]
    if spec_codes:
        ctx.log(f"板块采集指定 {len(spec_codes)} 个板块：{spec_codes[:5]}{'…' if len(spec_codes) > 5 else ''}")
    else:
        ctx.log("板块采集开始：全量板块")
    ctx.progress(0.05, "板块采集进行中…")
    ctx.check_cancel()
    mode = str(params.get("mode") or "update")
    force_current_day = normalize_board_force_current_day(
        mode, params.get("force_current_day"),
    )
    date_start, date_end = normalize_board_date_range(
        mode, params.get("date_start"), params.get("date_end"), force_current_day,
    )
    only = normalize_board_stages(params.get("only"))
    ingest_kwargs = {
        "ctx": ctx, "board_type": params.get("board_type"),
        "board_codes": spec_codes or None, "mode": mode,
    }
    if force_current_day:
        ingest_kwargs["force_current_day"] = True
    if date_start:
        ingest_kwargs["date_start"] = date_start
        ingest_kwargs["date_end"] = date_end
    if only:
        ingest_kwargs["only"] = only
    if params.get("limit") is not None:
        ingest_kwargs["limit"] = params["limit"]
    # force_members 透传（任务 API/调度参数指定时强制刷新全量成分，绕过周频跳过）：
    # None=按 mode/board_codes 自动；bool/字符串（"1"/"true"）规范化。
    fm = params.get("force_members")
    if fm is not None:
        if isinstance(fm, str):
            fm = fm.strip().lower() in ("1", "true", "yes", "on")
        ingest_kwargs["force_members"] = bool(fm)
    result = IngestionService().ingest_board(**ingest_kwargs)
    if result.get("failed"):
        # 部分失败保留 checkpoint 供续跑补齐（未完成板块后续重跑）；失败项已在 data_update_log
        # 记 failed 并在日志可见。任务标 failed 但可续跑（对齐数据管理文档「失败任务可续跑」语义）。
        ctx.log(f"板块采集部分完成，失败项：{result['failed']}")
        return {"message": f"板块采集部分完成（{len(result['failed'])} 项失败，可重试未完成项）：{result['failed']}",
                "result": result, "ok": False}
    ctx.log("板块采集完成")
    ctx.progress(1.0, "板块采集完成")
    return {"message": "板块采集完成", "result": result, "ok": True}


def _h_stock_board_correlation(params: dict, ctx: TaskContext) -> dict:
    """计算个股走势行业/概念冠军；正式表只在最后一个短事务中切换。"""
    from backend.indicators.stock_board_correlation import CorrelationInputError
    from backend.services.stock_board_correlation import (
        StockBoardCorrelationService,
        normalize_correlation_task_params,
    )

    labels = {
        "read_candidates": (0.08, "阶段 1/5：读取候选"),
        "load_prices": (0.22, "阶段 2/5：加载行情"),
        "calculate": (0.45, "阶段 3/5：批量计算"),
        "validate": (0.76, "阶段 4/5：结果校验"),
        "switch": (0.92, "阶段 5/5：原子切换"),
    }

    def report_phase(phase: str) -> None:
        progress, message = labels[phase]
        ctx.log(message)
        ctx.progress(progress, message.split("：", 1)[1] + "…")

    def report_compute_phase(phase: str) -> None:
        # 目标范围预校验已作为“读取候选”阶段展示；计算服务重复进入该阶段时不重复日志。
        if phase != "read_candidates":
            report_phase(phase)

    failure_stats = {
        "target_date": None, "target_stock_count": 0, "candidate_relation_count": 0,
        "industry_champion_count": 0, "concept_champion_count": 0,
        "empty_result_count": 0, "skipped_count": 0, "failed_count": 1,
        "benchmark_counts": {}, "fallback_count": 0,
        "calculation_seconds": 0.0, "write_seconds": 0.0, "switched": False,
    }

    def expected_failure(exc: ValueError) -> dict:
        ctx.log(f"完整性校验失败：{exc}", "error")
        return {"ok": False, "message": str(exc), **failure_stats}

    report_phase("read_candidates")
    ctx.check_cancel()
    try:
        normalized = normalize_correlation_task_params(params, client=get_client())
    except ValueError as exc:
        return expected_failure(exc)
    try:
        service = StockBoardCorrelationService()
        requested_date = normalized.get("trade_date")
        upper_bound = (
            datetime.fromisoformat(requested_date).date() if requested_date else None
        )
        target_date = service.resolve_target_date(upper_bound=upper_bound)
        if upper_bound is not None and target_date != upper_bound:
            raise CorrelationInputError(
                f"固定日期 {upper_bound.isoformat()} 不是三类行情共同可用的交易日"
            )
        targets, _ = service.resolve_target_codes(target_date, normalized["codes"])
        failure_stats.update({
            "target_date": target_date.isoformat(),
            "target_stock_count": len(targets),
        })
        result = service.compute_and_replace(
            normalized["codes"], force=normalized["force"],
            upper_bound=target_date,
            phase_callback=report_compute_phase, cancel_check=ctx.check_cancel,
        )
    except CorrelationInputError as exc:
        return expected_failure(exc)
    message = f"个股走势关联板块计算完成：{result.target_count} 只"
    if not result.switched:
        families = service.resolve_data_family_maxima()
        family_text = " / ".join(
            f"{label} {value.isoformat()}" if value else f"{label} 无数据"
            for label, value in (
                ("个股行情", families.get("daily_bar")),
                ("板块指数", families.get("board_bar")),
                ("宽基指数", families.get("index_bar")),
            )
        )
        message = (
            f"目标日期 {result.target_date} 已是当前共同数据的最新可用日（{family_text}），"
            f"{result.target_count} 只股票当前结果已与该日期一致，安全跳过"
        )
        # 个股行情已领先于共同目标日，通常是板块/指数数据未跟上，给出可执行的恢复提示。
        daily = families.get("daily_bar")
        if daily is not None and daily > result.target_date:
            message += (
                f"。若需推进到更新日期（{daily.isoformat()}），"
                "请先补齐板块指数/指数日线后再执行本任务"
            )
        ctx.log(message)
    payload = {
        "ok": True,
        "message": message,
        "target_date": result.target_date.isoformat(),
        "target_stock_count": result.target_count,
        "candidate_relation_count": result.candidate_count,
        "industry_champion_count": result.industry_champion_count,
        "concept_champion_count": result.concept_champion_count,
        "empty_result_count": result.empty_result_count,
        "skipped_count": result.skipped_count,
        "failed_count": 0,
        "benchmark_counts": result.benchmark_counts,
        "fallback_count": result.fallback_count,
        "calculation_seconds": round(result.calculation_seconds, 6),
        "write_seconds": round(result.write_seconds, 6),
        "switched": result.switched,
    }
    ctx.progress(1.0, payload["message"])
    return payload


def _h_limit_ladder_invalidate(params: dict, ctx: TaskContext) -> dict:
    """Explicitly invalidate ladder snapshots without starting their recomputation."""
    from datetime import date as _date

    from backend.services.limit_ladder_query import LimitLadderQueryService
    from backend.services.limit_ladder_snapshot import LimitLadderSnapshotService
    from backend.services.result_maintenance import (
        normalize_ladder_invalidation_params,
        resolve_target_date,
    )

    normalized = normalize_ladder_invalidation_params(params)
    if normalized["target_mode"] == "latest":
        latest = LimitLadderQueryService(ctx.svc.market).trade_dates(limit=1)[
            "latest_complete_date"
        ]
        if not latest:
            raise ValueError("没有通过天梯完整性门禁的交易日")
        target_date = _date.fromisoformat(latest)
    else:
        target_date = resolve_target_date(normalized, ctx.svc.market)
    scope = f"{target_date.isoformat()} 起"
    ctx.log(f"连板天梯失效：目标范围 {scope}")
    ctx.progress(0.5, "标记连板天梯快照失效…")
    service = LimitLadderSnapshotService(ctx.svc.market)
    invalidated = service.request_invalidation(
        [target_date],
        reason="explicit_result_maintenance",
    )
    ctx.log(f"已标记 {invalidated} 个天梯日期失效；访问对应日期时按现有门禁重算")
    return {
        "message": f"连板天梯失效完成：{invalidated} 个日期，目标范围 {scope}",
        "invalidated_count": invalidated,
        "target_mode": normalized["target_mode"],
        "trade_date": target_date.isoformat(),
    }


def _h_limit_ladder_recompute(params: dict, ctx: TaskContext) -> dict:
    """Materialize one ladder date and mirror every execution state to the PG ledger."""
    from datetime import date as _date

    from backend.services.limit_ladder_snapshot import LimitLadderSnapshotService
    from backend.services.limit_ladder_task_coordinator import LimitLadderTaskCoordinator

    command_id = str(params.get("command_id") or "").strip()
    raw_date = str(params.get("trade_date") or "").strip()
    if not command_id or not raw_date:
        raise ValueError("连板天梯任务缺少 command_id 或 trade_date")
    trade_date = _date.fromisoformat(raw_date)
    coordinator = LimitLadderTaskCoordinator(task_service=ctx.svc)
    command = coordinator.repository.get(command_id)
    command_trade_date = command.get("trade_date") if command is not None else None
    if isinstance(command_trade_date, datetime):
        command_trade_date = command_trade_date.date()
    if command is None or command_trade_date != trade_date:
        raise ValueError("连板天梯 PG 命令与 DuckDB 任务参数不一致")
    if not coordinator.mark_running(command_id, ctx.tid):
        raise RuntimeError("连板天梯命令已进入终态，拒绝重复执行")

    ctx.set_phase("limit_ladder", phase_total=3, phase_done=0, current_item=raw_date)
    ctx.log(f"阶段 1/3：校验 {raw_date} 点时股票池与采集终态")
    try:
        outcome = LimitLadderSnapshotService(ctx.svc.market).materialize(
            trade_date,
            task_id=ctx.tid,
        )
        coverage = outcome.coverage.to_dict()
        summary = {
            "trade_date": raw_date,
            "snapshot_id": outcome.snapshot_id,
            "snapshot_status": outcome.status,
            "coverage": coverage,
        }
        if outcome.status != "valid":
            reason = ",".join(outcome.coverage.reason_codes) or "COVERAGE_NOT_READY"
            if outcome.coverage.diagnostics:
                reason += "；" + "；".join(
                    f"{item['code']}: {item['reason']}"
                    for item in outcome.coverage.diagnostics
                )
            coordinator.mark_terminal(
                command_id,
                status="failed",
                task_id=ctx.tid,
                summary=summary,
                error=reason,
            )
            ctx.set_phase("limit_ladder", phase_total=3, phase_done=3, current_item=raw_date)
            return {
                "ok": False,
                "message": f"{raw_date} 连板天梯未发布：{reason}",
                **summary,
            }
        ctx.set_phase("limit_ladder", phase_total=3, phase_done=2, current_item=raw_date)
        ctx.log(f"阶段 2/3：不可变快照已原子切换 {outcome.snapshot_id}")
        try:
            coordinator.mark_terminal(
                command_id,
                status="succeeded",
                task_id=ctx.tid,
                summary=summary,
            )
        except Exception as mirror_exc:  # noqa: BLE001 -- published snapshot remains authoritative
            ctx.log(f"PG 成功终态镜像失败，将由启动/周期对账补齐：{mirror_exc}", "warn")
        ctx.set_phase("limit_ladder", phase_total=3, phase_done=3, current_item=raw_date)
        ctx.progress(1.0, f"{raw_date} 连板天梯快照完成")
        return {"message": f"{raw_date} 连板天梯快照完成", **summary}
    except Exception as exc:
        try:
            coordinator.mark_terminal(
                command_id,
                status="failed",
                task_id=ctx.tid,
                error=str(exc),
            )
        except Exception as mirror_exc:  # noqa: BLE001 -- preserve the original task failure
            ctx.log(f"PG 失败终态镜像失败，将由启动/周期对账补齐：{mirror_exc}", "warn")
        raise


def _h_stock_special_trading_day(params: dict, ctx: TaskContext) -> dict:
    """通过现有系统管理员数据任务入口维护公告事实。"""
    from backend.services.stock_special_trading_day import StockSpecialTradingDayService

    ctx.progress(0.2, "校验并维护特殊交易日事实")
    result = StockSpecialTradingDayService(ctx.svc.market).import_records(params, task_id=ctx.tid)
    ctx.log(result["message"])
    return result


_HANDLERS = {
    "stock_special_trading_day": _h_stock_special_trading_day,
    "update": _h_update,
    "backfill": _h_backfill,
    "ingest_date": _h_ingest_date,
    "ingest_codes": _h_ingest_codes,
    "rebuild_price_factors": _h_rebuild_price_factors,
    "recompute": _h_recompute,
    "verify": _h_verify,
    "checkup": _h_checkup,
    "fix": _h_fix,
    "enrich_basic": _h_enrich_basic,
    "audit_cleanup": _h_audit_cleanup,
    "board": _h_board,
    "stock_ingest": _h_stock_ingest,
    "stock_board_correlation": _h_stock_board_correlation,
    "limit_ladder_invalidate": _h_limit_ladder_invalidate,
    "limit_ladder_recompute": _h_limit_ladder_recompute,
}
