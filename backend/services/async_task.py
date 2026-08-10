"""异步任务执行器（SDD §10，M2.6 + M2.8-B）——数据更新/补数/指定采集/重算/体检/修复后台跑。

本地单用户：任务在守护线程里执行，复用 IngestionService / DataVerifier / DataIntegrityReport。
DuckDB 单连接 + RLock 串行化 SQL，线程安全；长任务在 SQL 之间释放锁，不阻塞轻请求。

M2.8-B 增强：
- **实时日志**（FR-DM-9）：TaskContext.log() 批量写 task_log（节流，DM-D8），前端按 after_seq 增量拉。
- **checkpoint / 续跑**（FR-DM-10）：处理器把已完成项写 result.checkpoint；服务重启 reconcile() 把
  残留 running/pending 标 interrupted；resume() 按 checkpoint 跳过已完成续跑。
- **并发互斥**（FR-DM-11）：写任务（采集/质检/恢复等）不允许并发，创建即 409。
- **数据修复**（FR-DM-4）：fix 任务定向重拉单条质检问题对应股票/日期，回写 issue 状态。

数据变更类任务完成后标记评分快照失效；评分维护任务会显式生产 PUBLIC_BOARD_OWNER 公共榜单。
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta

from backend.common.logging import get_logger
from backend.storage.duckdb_client import get_client

log = get_logger("services.async_task")

# 全部任务类型（原子任务：定时任务系统按需组合调度，不再有 daily 复合任务）
TASK_TYPES = ("update", "backfill", "ingest_date", "ingest_codes", "rebuild_price_factors",
              "recompute", "verify", "checkup", "fix", "enrich_basic", "audit_cleanup",
              "board")
# 写类任务：互斥（写任务之间不并发），且服务重启需 reconcile。
WRITE_TASK_TYPES = frozenset({"update", "backfill", "ingest_date", "ingest_codes",
                              "rebuild_price_factors", "verify", "fix", "enrich_basic",
                              "board"})

# 日志保留（DM-D8）
LOG_MAX_PER_TASK = 2000
LOG_RETENTION_DAYS = 30
_LOG_FLUSH_EVERY = 10  # 累计 N 条即 flush；长任务日志要比进度条更快出现在页面上

TASK_CAPABILITIES: dict[str, dict] = {
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
}


class ConcurrentTaskError(Exception):
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
        self.svc._set(self.tid, result=json.dumps({"checkpoint": self.checkpoint},
                                                  ensure_ascii=False, default=str))

    def set_phase(self, phase: str, **data) -> None:
        """记录当前长子任务阶段；前端据此解释'下一个检查点'在哪里。"""
        self.set_checkpoint(phase=phase, **data)

    def check_cancel(self) -> None:
        """协作式取消检查点：被请求取消则抛 TaskCancelled（执行器捕获→标记可续跑）。"""
        with _CANCEL_LOCK:
            cancelled = self.tid in _CANCELLED
        if cancelled:
            raise TaskCancelled()


class AsyncTaskService:
    def __init__(self, client=None):
        self.c = client or get_client()
        from backend.storage.ddl import init_db
        init_db(self.c)

    # ── id / 写入辅助 ──
    def _new_id(self, t: str) -> str:
        return f"task_{t}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"

    def _set(self, tid: str, **fields) -> None:
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
        import pandas as pd
        ids = [int(self.c.query_df("SELECT nextval('seq_task_log') AS v").iloc[0]["v"]) for _ in rows]
        df = pd.DataFrame(
            [{"id": i, "task_id": tid, "seq": s, "ts": ts, "level": lv, "message": m}
             for i, (s, ts, lv, m) in zip(ids, rows)])
        with self.c.temp_view(df, "tlog") as v:
            self.c.execute(
                f"INSERT INTO task_log (id, task_id, seq, ts, level, message) "
                f"SELECT id, task_id, seq, ts, level, message FROM {v}")
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
               job_name: str | None = None) -> str:
        """创建并后台执行任务。trigger_source 标记来源（manual/scheduled），定时触发时
        带上 job_id/job_name，供任务中心展示「定时·{job_name}」并据此筛选。"""
        if task_type not in TASK_TYPES:
            raise ValueError(f"未知任务类型: {task_type}（可选 {TASK_TYPES}）")
        params = params or {}
        if task_type in WRITE_TASK_TYPES:
            busy = self._running_write()
            if busy:
                raise ConcurrentTaskError(busy[1], busy[0])
        tid = self._new_id(task_type)
        now = datetime.now()
        self.c.execute(
            "INSERT INTO async_task (id, task_type, params, status, progress, message, result, "
            "trigger_source, job_id, job_name, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [tid, task_type, json.dumps(params, ensure_ascii=False, default=str),
             "pending", 0.0, "已排队", None, trigger_source, job_id, job_name, now, now])
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
        """续跑中断或带 checkpoint 的失败任务，跳过已经成功的工作单元。"""
        t = self.get(tid)
        if not t:
            raise ValueError("任务不存在")
        if t["status"] not in ("interrupted", "failed"):
            raise ValueError(f"仅可续跑中断或失败任务，当前状态: {t['status']}")
        task_type = t["task_type"]
        cap = TASK_CAPABILITIES.get(task_type, {})
        if not cap.get("can_resume"):
            raise ValueError(f"该任务类型不支持续跑: {task_type}")
        checkpoint = (t.get("result") or {}).get("checkpoint") \
            if isinstance(t.get("result"), dict) else None
        if t["status"] == "failed" and not checkpoint:
            raise ValueError("失败任务没有可用 checkpoint，请重新创建任务")
        if task_type in WRITE_TASK_TYPES:
            busy = self._running_write()
            if busy:
                raise ConcurrentTaskError(busy[1], busy[0])
        params = t.get("params") or {}
        self._set(tid, status="pending", progress=0.0, message="续跑排队…")
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
        with _CANCEL_LOCK:           # 清除上一轮残留的取消标记（避免续跑刚启动就被旧标记误终止）
            _CANCELLED.discard(tid)
        ctx = TaskContext(self, tid, checkpoint)
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
            ctx.log(f"续跑：上次阶段 {phase}，位置 {item}，约完成 {done}/{checkpoint.get('total', '?')} 项；"
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
                self._set(tid, status="failed", progress=1.0, message=message,
                          result=json.dumps(result_payload, ensure_ascii=False, default=str))
                self._audit_task(
                    action="finish", result="failed", status="failed",
                    task_id=tid, task_type=task_type, error_summary=message,
                )
                return
            ctx.log(f"■ 任务完成：{result.get('message', '完成')}")
            ctx.flush()
            self._set(tid, status="done", progress=1.0,
                      message=result.get("message", "完成"),
                      result=json.dumps(result, ensure_ascii=False, default=str))
            self._audit_task(
                action="finish",
                result="success",
                status="done",
                task_id=tid,
                task_type=task_type,
            )
        except TaskCancelled:
            ctx.log("⏹ 任务已被用户终止（已完成的部分已入库，可续跑）", "warn")
            self._release_fixing(tid)
            ctx.flush()
            self._set(tid, status="interrupted", message="已终止（可续跑）")
            self._audit_task(
                action="interrupt",
                result="failed",
                status="interrupted",
                task_id=tid,
                task_type=task_type,
                error_summary="任务被用户终止",
            )
        except Exception as e:  # noqa: BLE001
            log.exception("异步任务失败 %s", tid)
            ctx.log(f"任务失败: {e}", "error")
            self._release_fixing(tid)
            ctx.flush()
            self._set(tid, status="failed", progress=1.0, message=str(e))
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

    def _release_fixing(self, tid: str) -> int:
        """把本任务名下仍卡在 fixing 的质检问题复位为 open（任务失败/中断时调用，不留孤儿）。"""
        try:
            stuck = self.c.query_df(
                "SELECT count(*) AS n FROM data_quality_issue WHERE status='fixing' AND fix_task_id=?",
                [tid]).iloc[0]["n"]
            if int(stuck):
                self.c.execute(
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
        stuck = self.c.query_df(
            "SELECT count(*) AS n FROM async_task WHERE status IN ('pending','running')").iloc[0]["n"]
        self.c.execute(
            "UPDATE async_task SET status='interrupted', message='服务重启中断，可续跑', updated_at=? "
            "WHERE status IN ('pending','running')", [datetime.now()])
        # 重启后没有任何任务在跑，故所有 fixing 必为孤儿（绑定的任务已中断）→ 复位为 open，可重新恢复
        fixing = int(self.c.query_df(
            "SELECT count(*) AS n FROM data_quality_issue WHERE status='fixing'").iloc[0]["n"])
        if fixing:
            self.c.execute(
                "UPDATE data_quality_issue SET status='open', fix_task_id=NULL WHERE status='fixing'")
        cutoff = datetime.now() - timedelta(days=LOG_RETENTION_DAYS)
        self.c.execute("DELETE FROM task_log WHERE ts < ?", [cutoff])
        n = int(stuck)
        if n or fixing:
            log.info("reconcile：%d 个残留任务标记 interrupted，%d 条修复中问题复位为待处理", n, fixing)
        return {"interrupted": n, "fixing_reset": fixing}

    def get(self, tid: str) -> dict | None:
        df = self.c.query_df("SELECT * FROM async_task WHERE id=?", [tid])
        if df.empty:
            return None
        return _row(df.iloc[0])

    def cancel(self, tid: str) -> bool:
        """请求终止运行中/排队中的任务（协作式）：执行器在下一个检查点停下并标记可续跑。"""
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
        self._set(tid, message=f"终止中…（{cap.get('cancel_message') or '到下一个检查点停下'}）")
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
    for k in ("created_at", "updated_at"):
        if d.get(k) is not None:
            d[k] = str(d[k])
    if d.get("progress") is not None and not pd.isna(d["progress"]):
        d["progress"] = float(d["progress"])
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
    """标全量评分快照失效。兜底：IngestionService 编排方法收尾已标 stale（见 ingest.py
    _mark_snapshots_stale），此处幂等重复 UPDATE 无害，保留作 handler 级保证。"""
    from backend.scoring.snapshot import ScoreSnapshotRepo
    return ScoreSnapshotRepo(get_client()).mark_stale_all()


def _produce_public_board_snapshots(params: dict) -> dict:
    from backend.services.public_board import produce_public_board_snapshots

    profile_ids = params.get("profile_ids")
    if isinstance(profile_ids, str):
        profile_ids = [x.strip() for x in profile_ids.split(",") if x.strip()]
    run_date = params.get("run_date") or params.get("date")
    return produce_public_board_snapshots(run_date=run_date, profile_ids=profile_ids)


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
    ctx.log("阶段 1/3：增量更新行情")
    ctx.progress(0.1, "增量更新行情中…")
    res = IngestionService().update(codes=params.get("codes"), concurrency=_concurrency(params), ctx=ctx)
    if res.get("skipped"):
        return {"message": "主源当日数据未就绪，本次增量未执行", "ingest": res, "snapshots_marked_stale": 0}
    ctx.log("阶段 2/3：刷新评分缓存")
    ctx.progress(0.9, "刷新评分缓存…")
    stale = _mark_snapshots_stale()
    ctx.log(f"阶段 3/3：增量任务收尾，已标记 {stale} 项评分快照失效")
    return {"message": f"更新完成：{res}", "ingest": res, "snapshots_marked_stale": stale}


def _h_backfill(params: dict, ctx: TaskContext) -> dict:
    from backend.services.ingest import IngestionService
    ctx.log("阶段 1/3：历史行情补数")
    ctx.progress(0.1, "历史补数中（可能较久）…")
    res = IngestionService().backfill(codes=params.get("codes"), years=params.get("years"),
                                      concurrency=_concurrency(params), ctx=ctx)
    ctx.log("阶段 2/3：刷新评分缓存")
    ctx.progress(0.9, "刷新评分缓存…")
    stale = _mark_snapshots_stale()
    ctx.log(f"阶段 3/3：补数任务收尾，已标记 {stale} 项评分快照失效")
    return {"message": f"补数完成：{res}", "ingest": res, "snapshots_marked_stale": stale}


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
    ctx.log(f"阶段 1/3：指定日期行情采集 {start}~{end}")
    ctx.progress(0.1, f"采集 {start}~{end} 行情…")
    res = IngestionService().ingest_date(start, end, codes=params.get("codes"),
                                         concurrency=_concurrency(params), ctx=ctx)
    ctx.log("阶段 2/3：刷新受影响日期评分缓存")
    ctx.progress(0.9, "刷新受影响日期的评分缓存…")
    from backend.scoring.snapshot import ScoreSnapshotRepo
    days = res.get("dates", [])
    # 服务层已按 dates 细粒度标 stale（ingest_date 收尾）；此处幂等兜底，保证 handler 级覆盖
    stale = ScoreSnapshotRepo(get_client()).mark_stale_dates(
        [_date.fromisoformat(x) for x in days]) if days else 0
    ctx.log(f"阶段 3/3：指定日期采集收尾，受影响交易日 {len(days)} 天，已标记 {stale} 项评分快照失效")
    return {"message": f"指定采集完成：{res}", "ingest": res, "snapshots_marked_stale": stale}


def _h_ingest_codes(params: dict, ctx: TaskContext) -> dict:
    """指定股票采集（FR-DM-3）：对给定 codes 增量补到今天。"""
    from backend.services.ingest import IngestionService
    codes = params.get("codes")
    if not codes:
        raise ValueError("缺少 codes 参数")
    ctx.log(f"阶段 1/3：指定股票增量采集，{len(codes)} 只")
    ctx.progress(0.1, f"采集 {len(codes)} 只指定股票…")
    res = IngestionService().update(codes=codes, concurrency=_concurrency(params), ctx=ctx)
    ctx.log("阶段 2/3：刷新评分缓存")
    ctx.progress(0.9, "刷新评分缓存…")
    stale = _mark_snapshots_stale()
    ctx.log(f"阶段 3/3：指定股票采集收尾，已标记 {stale} 项评分快照失效")
    return {"message": f"指定股票采集完成：{res}", "ingest": res, "snapshots_marked_stale": stale}


def _h_recompute(params: dict, ctx: TaskContext) -> dict:
    ctx.log("▶ 评分维护：刷新评分缓存，并生产最新交易日公共榜单快照")
    ctx.progress(0.25, "刷新评分缓存…")
    stale = _mark_snapshots_stale()
    ctx.log(f"阶段 1/2：{stale} 项评分快照已标记为需重算")
    ctx.progress(0.75, "生产公共榜单快照…")
    public_board = _produce_public_board_snapshots(params)
    ctx.log(
        "阶段 2/2：公共榜单生产完成，"
        f"交易日 {public_board.get('run_date') or '-'}，"
        f"方案 {public_board.get('profile_count', 0)} 个，"
        f"明细 {public_board.get('total_rows', 0)} 行"
    )
    return {
        "message": (
            f"评分维护完成：{stale} 项评分标记为需重算；"
            f"公共榜单已生产到 {public_board.get('run_date') or '-'}"
        ),
        "snapshots_marked_stale": stale,
        "public_board": public_board,
    }


def _h_rebuild_price_factors(params: dict, ctx: TaskContext) -> dict:
    from backend.services.ingest import IngestionService
    ctx.log("阶段 1/3：重算价格因子")
    ctx.progress(0.05, "重算价格因子…")
    codes = params.get("codes")
    res = IngestionService().rebuild_price_factors(codes=codes, ctx=ctx)
    ctx.log("阶段 2/3：刷新评分缓存")
    ctx.progress(0.95, "刷新评分缓存…")
    stale = _mark_snapshots_stale()
    ctx.log(f"阶段 3/3：价格因子任务收尾，已标记 {stale} 项评分快照失效")
    return {"message": f"价格因子重算完成：{res}", "rebuild": res,
            "snapshots_marked_stale": stale}


def _h_verify(params: dict, ctx: TaskContext) -> dict:
    """数据质检（与定时/手动质检同一方法 scan_quality_issues，口径一致）。

    四层统一扫描写质量台账（幂等：覆盖上轮未解决的 L2/L3/L4 自动问题）：
    L2 字段契约（市值缺失）/ L3 正确性（异常涨跌、复权跳变）/ L4 覆盖鲜活（缺口、滞后）。
    L1 入库闸门由采集即时记录。停牌（已确认）不计入缺口。
    """
    from backend.services.data_report import DataIntegrityReport
    ctx.progress(0.3, "全市场四层数据质检中…")
    ctx.log("数据质检：扫描市值缺失 / 异常涨跌 / 复权跳变 / 缺口 / 滞后，写入质量台账")
    rep = DataIntegrityReport()
    q = rep.scan_quality_issues()
    # 板块维度质检（指数缺口）同一质检内跑；采集即时问题由采集层写台账。
    q["board"] = rep.scan_board_quality()
    n = sum(int(q.get(k, 0)) for k in
            ("abnormal_change_rows", "adj_jump_rows", "mv_missing_rows", "mv_gap_rows",
             "data_gap_rows", "stale_rows"))
    b = q.get("board") or {}
    ctx.log(f"质检完成：异常涨跌 {q.get('abnormal_change_rows', 0)}、复权跳变 {q.get('adj_jump_rows', 0)}、"
            f"市值缺失 {q.get('mv_missing_rows', 0)}、市值缺口 {q.get('mv_gap_rows', 0)}、"
            f"缺口 {q.get('data_gap_rows', 0)}、滞后 {q.get('stale_rows', 0)}、"
            f"板块指数缺口 {b.get('index_gap', 0)}")
    return {"message": f"质检完成：发现 {n} 项问题" if n else "质检完成：未发现新问题", "quality": q}


def _h_checkup(params: dict, ctx: TaskContext) -> dict:
    """数据结构体检（DataVerifier）：本地 SQL 的结构/价格正确性/字段契约核查，返回结构化报告。

    与质检（_h_verify 写台账+修复闭环）互补：体检查结构合法性与整列/逐行缺失（含质检盲区的
    在市股逐行市值字段缺失），只读、不写台账。cross=True 时附加联网交叉验证（默认关闭）。
    """
    from backend.services.data_verify import DataVerifier
    cross = bool(params.get("cross", False))
    ctx.progress(0.3, "数据结构体检中…")
    ctx.log("数据体检：结构/完整性 + 价格正确性 + 字段契约" + ("（含联网交叉验证）" if cross else ""))
    report = DataVerifier(quiet=True).run_structured(cross=cross)
    for g in report["groups"]:
        bad = [c["name"] for c in g["checks"] if not c["ok"]]
        ctx.log(f"{g['group']}：{len(g['checks']) - len(bad)}/{len(g['checks'])} 通过"
                + (f"；未过：{', '.join(bad)}" if bad else ""))
    msg = (f"体检通过：{report['passed']}/{report['total']}" if report["all_ok"]
           else f"体检发现 {len(report['fails'])} 项未通过（{report['passed']}/{report['total']} 通过）")
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
    """刷新上市/退市标记（含行业），并可选灌退市股历史（防幸存者偏差）。

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
    ctx.progress(0.1, "刷新上市/退市标记（含退市打标）…")
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


def _recover_one(c, rep, ing, ctx: TaskContext, issue_id: int) -> tuple[bool, list, str]:
    """恢复单条质检问题 → 复检 → 回写状态。返回 (复检是否通过, 受影响日期, 文案)。"""
    import pandas as pd
    df = c.query_df(
        "SELECT code, trade_date, issue_type, detail FROM data_quality_issue WHERE id=?", [issue_id])
    if df.empty:
        raise ValueError(f"质检问题不存在: id={issue_id}")
    code, trade_date, issue_type = df.iloc[0]["code"], df.iloc[0]["trade_date"], df.iloc[0]["issue_type"]
    issue_detail = df.iloc[0]["detail"]
    td = None if trade_date is None or (isinstance(trade_date, float) and pd.isna(trade_date)) \
        else pd.Timestamp(trade_date).date()
    # 进入 fixing 并绑定本任务 id：任务失败/中断/重启时据 fix_task_id 复位，不留孤儿（DM 修复中闭环）
    c.execute("UPDATE data_quality_issue SET status='fixing', fix_task_id=? WHERE id=?", [ctx.tid, issue_id])

    # 恢复+复检全程包在 try 内：任何异常（如源端取数失败 DataSourceError）都先把状态复位为 open
    # 再上抛——绝不留悬空 fixing，且让 _h_fix 如实计入失败（不再"日志失败、状态修复中、却报成功"）。
    try:
        affected: list = []
        note = ""
        if issue_type == "mv_missing":
            ctx.log(f"恢复(L2 字段契约)：拉取 {code} 估值，补市值字段")
            res = _call_with_ctx(ing.ingest_valuation, codes=[code], ctx=ctx)
            note = f"补市值 {res.get('total_mv_rows', 0)} 行"
        elif issue_type == "mv_gap":
            ctx.log(f"恢复(L2 逐日缺口)：补 {code} 的市值字段缺失天")
            res = _call_with_ctx(ing.ingest_valuation_gaps, codes=[code], ctx=ctx)
            note = f"补市值缺口 {res.get('total_mv_rows', 0)} 行"
        elif issue_type in ("data_gap", "stale"):
            ctx.log(f"恢复(L4 覆盖鲜活)：按缺口收口重采 {code}（与增量更新同口径）")
            r = ing.reconcile_gaps(code, ctx=ctx)
            if not r["miss"]:
                note = "无待补缺口（可能已被其它任务补齐）"
            else:
                affected = r["backfilled"]
                note = ing.reconcile_note(r)
                ctx.log(f"重采写入 {r['rows']} 行；{note}"
                        f"（内部缺口源端无数据者已确认停牌，末尾滞后不强判停牌）")
        elif issue_type in ("null_close", "ohl_repaired", "abnormal_change"):
            if td:
                ctx.log(f"恢复：重采 {code} {td} 单日行情")
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
        elif issue_type == "board_index_gap":
            # 板块指数缺口：重采该板块指数（指定板块），数据补齐后重扫收敛
            from backend.services.board_ingest import BoardIngestService
            from datetime import date as _d
            ctx.log(f"恢复(板块指数缺口)：重采板块 {code} 指数")
            bsvc = BoardIngestService(c)
            res = _call_with_ctx(
                bsvc.ingest_board_bar, _d(2024, 1, 1), board_codes=[code], ctx=ctx)
            if res.get("failed"):
                raise RuntimeError(f"板块指数重采失败：{res['failed']}")
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
            # 资金流未匹配：重采资金流（名称匹配映射），重扫收敛
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
                bsvc.ingest_board_fund_flow, periods=("即时",),
                board_type=repair_board_type, ctx=ctx)
            if res.get("failed"):
                raise RuntimeError(f"板块资金流重采失败：{res['failed']}")
            note = f"重采资金流 {res.get('rows', 0)} 行（未匹配 {res.get('unmatched', 0)}）"
            ctx.log(note)
        elif issue_type == "board_fund_missing":
            # 资金流缺失：数据源资金流榜单未收录该板块。定向重采资金流——源榜单一经上线
            # 即可采到并置 has_fund_flow=true，重扫自动收敛；源仍无则该 issue 保持 open。
            from backend.services.board_ingest import BoardIngestService
            ctx.log(f"恢复(板块资金流缺失)：重采板块 {code} 资金流")
            bsvc = BoardIngestService(c)
            res = _call_with_ctx(
                bsvc.ingest_board_fund_flow, periods=("即时",),
                board_codes=[code], ctx=ctx)
            if res.get("failed"):
                raise RuntimeError(f"板块资金流重采失败：{res['failed']}")
            note = f"重采资金流 {res.get('rows', 0)} 行"
            ctx.log(note)
        elif issue_type == "board_fund_stale":
            # 资金流滞后（源级单条）：全源重采资金流（即时周期），快照追平后重扫收敛。
            from backend.services.board_ingest import BoardIngestService
            ctx.log("恢复(板块资金流滞后)：重采全源资金流")
            bsvc = BoardIngestService(c)
            res = _call_with_ctx(
                bsvc.ingest_board_fund_flow, periods=("即时",), ctx=ctx)
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
    - data_gap/stale(L4)    → 反向重采缺口区间：补回的入库；源端仍无数据的确认为停牌写 stock_suspension（收敛）
    - null_close/abnormal   → 重采该单日；adj_jump → 重采该股整段 + 重算复权
    复检由 DataIntegrityReport.recheck_clean 判定：通过 → resolved；未通过 → 保持 open。
    """
    from backend.services.ingest import IngestionService
    from backend.services.data_report import DataIntegrityReport
    from backend.scoring.snapshot import ScoreSnapshotRepo
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
        return {"message": message, "ok": True, "resolved": 0, "failed": 0, "total": 0,
                "snapshots_marked_stale": 0}
    issue_types = set()
    if ids:
        issue_types = set(c.query_df(
            f"SELECT DISTINCT issue_type FROM data_quality_issue "
            f"WHERE id IN ({','.join('?' for _ in ids)})", ids)["issue_type"].astype(str))
    resolved = 0
    all_affected: list = []
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
            clean, affected, msg = _recover_one(c, rep, ing, ctx, iid)
            resolved += int(clean)
            all_affected += affected
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
    ctx.progress(0.95, "刷新评分缓存…")
    if all_affected:
        stale = ScoreSnapshotRepo(c).mark_stale_dates(sorted(set(all_affected)))
    elif resolved and issue_types.intersection({"mv_missing", "mv_gap", "adj_jump"}):
        stale = _mark_snapshots_stale()
    else:
        # 板块字典/成分/指数/资金流不参与个股评分，修复成功后无需让全部评分快照失效。
        stale = 0
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
    return {"message": msg, "ok": ok, "resolved": resolved, "failed": failed, "total": n,
            "snapshots_marked_stale": stale}


def _h_board(params: dict, ctx: TaskContext) -> dict:
    """板块采集（板块概念需求 R5）：字典→成分快照→指数→资金流。

    params.mode=backfill/update（默认 update）；params.codes 指定板块子集（采集页
    「指定板块」/重采用），未传则全量。中断后续跑会按字典类型、板块代码和资金流周期的
    阶段 checkpoint 跳过已经成功的工作单元。
    """
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
    only = params.get("only")
    if isinstance(only, str):
        only = [x.strip() for x in only.split(",") if x.strip()]
    ingest_kwargs = {
        "ctx": ctx, "board_type": params.get("board_type"),
        "board_codes": spec_codes or None, "mode": mode,
    }
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
        return {"message": f"板块采集部分完成（{len(result['failed'])} 项失败，可续跑补齐）：{result['failed']}",
                "result": result, "ok": False}
    ctx.log("板块采集完成")
    ctx.progress(1.0, "板块采集完成")
    return {"message": "板块采集完成", "result": result, "ok": True}


_HANDLERS = {
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
}
