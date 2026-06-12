"""异步任务执行器（SDD §10，M2.6 + M2.8-B）——数据更新/补数/指定采集/重算/体检/修复后台跑。

本地单用户：任务在守护线程里执行，复用 IngestionService / DataVerifier / DataIntegrityReport。
DuckDB 单连接 + RLock 串行化 SQL，线程安全；长任务在 SQL 之间释放锁，不阻塞轻请求。

M2.8-B 增强：
- **实时日志**（FR-DM-9）：TaskContext.log() 批量写 task_log（节流，DM-D8），前端按 after_seq 增量拉。
- **checkpoint / 续跑**（FR-DM-10）：处理器把已完成项写 result.checkpoint；服务重启 reconcile() 把
  残留 running/pending 标 interrupted；resume() 按 checkpoint 跳过已完成续跑。
- **并发互斥**（FR-DM-11）：同类写任务（update/backfill/ingest_*/fix）不允许并发，创建即 409。
- **数据修复**（FR-DM-4）：fix 任务定向重拉单条质检问题对应股票/日期，回写 issue 状态。

数据变更类任务完成后，**惰性标记**评分快照失效（不重算，§10.1）。
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta

from backend.common.logging import get_logger
from backend.storage.duckdb_client import get_client

log = get_logger("services.async_task")

# 全部任务类型
TASK_TYPES = ("update", "backfill", "ingest_date", "ingest_codes", "recompute", "verify", "fix")
# 写类任务：互斥（同类不并发），且服务重启需 reconcile
WRITE_TASK_TYPES = frozenset({"update", "backfill", "ingest_date", "ingest_codes", "fix"})

# 日志保留（DM-D8）
LOG_MAX_PER_TASK = 2000
LOG_RETENTION_DAYS = 30
_LOG_FLUSH_EVERY = 50  # 累计 N 条即 flush


class ConcurrentTaskError(Exception):
    """同类写任务已在运行（FR-DM-11，映射 409）。"""

    def __init__(self, task_type: str, running_id: str):
        self.task_type = task_type
        self.running_id = running_id
        super().__init__(f"已有同类任务在运行: {task_type}（{running_id}）")


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

    def _running_of_type(self, task_type: str) -> str | None:
        df = self.c.query_df(
            "SELECT id FROM async_task WHERE task_type=? AND status IN ('pending','running') "
            "ORDER BY created_at DESC LIMIT 1", [task_type])
        return None if df.empty else df.iloc[0]["id"]

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
    def create(self, task_type: str, params: dict | None = None) -> str:
        if task_type not in TASK_TYPES:
            raise ValueError(f"未知任务类型: {task_type}（可选 {TASK_TYPES}）")
        params = params or {}
        if task_type in WRITE_TASK_TYPES:
            busy = self._running_of_type(task_type)
            if busy:
                raise ConcurrentTaskError(task_type, busy)
        tid = self._new_id(task_type)
        now = datetime.now()
        self.c.execute(
            "INSERT INTO async_task (id, task_type, params, status, progress, message, result, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            [tid, task_type, json.dumps(params, ensure_ascii=False, default=str),
             "pending", 0.0, "已排队", None, now, now])
        threading.Thread(target=self._run, args=(tid, task_type, params, None), daemon=True).start()
        return tid

    def resume(self, tid: str) -> str:
        """续跑被中断的任务：读 checkpoint，重新拉起处理器（按 checkpoint 跳过已完成）。"""
        t = self.get(tid)
        if not t:
            raise ValueError("任务不存在")
        if t["status"] != "interrupted":
            raise ValueError(f"仅可续跑中断任务，当前状态: {t['status']}")
        task_type = t["task_type"]
        if task_type in WRITE_TASK_TYPES:
            busy = self._running_of_type(task_type)
            if busy:
                raise ConcurrentTaskError(task_type, busy)
        params = t.get("params") or {}
        checkpoint = (t.get("result") or {}).get("checkpoint") if isinstance(t.get("result"), dict) else None
        self._set(tid, status="pending", progress=0.0, message="续跑排队…")
        threading.Thread(target=self._run, args=(tid, task_type, params, checkpoint), daemon=True).start()
        return tid

    def _run(self, tid: str, task_type: str, params: dict, checkpoint: dict | None) -> None:
        ctx = TaskContext(self, tid, checkpoint)
        self._set(tid, status="running", progress=0.05, message="开始…")
        if checkpoint:
            done = checkpoint.get("done")
            ctx.log(f"续跑：上次约完成 {done}/{checkpoint.get('total', '?')} 项，幂等续做（跳过已入库）")
        try:
            result = _HANDLERS[task_type](params, ctx)
            ctx.flush()
            self._set(tid, status="done", progress=1.0,
                      message=result.get("message", "完成"),
                      result=json.dumps(result, ensure_ascii=False, default=str))
        except Exception as e:  # noqa: BLE001
            log.exception("异步任务失败 %s", tid)
            ctx.log(f"任务失败: {e}", "error")
            ctx.flush()
            self._set(tid, status="failed", progress=1.0, message=str(e))

    # ── 启动期 reconcile（FR-DM-10 + 日志清理 DM-D8）──
    def reconcile(self) -> dict:
        """服务启动调用：残留 running/pending → interrupted；清理超期日志。"""
        stuck = self.c.query_df(
            "SELECT count(*) AS n FROM async_task WHERE status IN ('pending','running')").iloc[0]["n"]
        self.c.execute(
            "UPDATE async_task SET status='interrupted', message='服务重启中断，可续跑', updated_at=? "
            "WHERE status IN ('pending','running')", [datetime.now()])
        cutoff = datetime.now() - timedelta(days=LOG_RETENTION_DAYS)
        self.c.execute("DELETE FROM task_log WHERE ts < ?", [cutoff])
        n = int(stuck)
        if n:
            log.info("reconcile：%d 个残留任务标记为 interrupted", n)
        return {"interrupted": n}

    def get(self, tid: str) -> dict | None:
        df = self.c.query_df("SELECT * FROM async_task WHERE id=?", [tid])
        if df.empty:
            return None
        return _row(df.iloc[0])

    def list(self, limit: int = 20, status: str | None = None) -> list[dict]:
        if status:
            df = self.c.query_df(
                "SELECT * FROM async_task WHERE status=? ORDER BY created_at DESC LIMIT ?", [status, limit])
        else:
            df = self.c.query_df("SELECT * FROM async_task ORDER BY created_at DESC LIMIT ?", [limit])
        return [_row(r) for _, r in df.iterrows()]


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
    return d


# ── 任务处理器：(params, ctx) → result dict ─────────────────────────
def _mark_snapshots_stale() -> int:
    from backend.scoring.snapshot import ScoreSnapshotRepo
    return ScoreSnapshotRepo(get_client()).mark_stale_all()


def _h_update(params: dict, ctx: TaskContext) -> dict:
    from backend.services.ingest import IngestionService
    ctx.progress(0.1, "增量更新行情中…")
    res = IngestionService().update(codes=params.get("codes"), ctx=ctx)
    ctx.progress(0.9, "标记评分快照失效…")
    stale = _mark_snapshots_stale()
    return {"message": f"更新完成：{res}", "ingest": res, "snapshots_marked_stale": stale}


def _h_backfill(params: dict, ctx: TaskContext) -> dict:
    from backend.services.ingest import IngestionService
    ctx.progress(0.1, "历史补数中（可能较久）…")
    res = IngestionService().backfill(codes=params.get("codes"), years=params.get("years"), ctx=ctx)
    ctx.progress(0.9, "标记评分快照失效…")
    stale = _mark_snapshots_stale()
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
    ctx.progress(0.1, f"采集 {start}~{end} 行情…")
    res = IngestionService().ingest_date(start, end, codes=params.get("codes"), ctx=ctx)
    ctx.progress(0.9, "标记受影响日期评分快照失效…")
    from backend.scoring.snapshot import ScoreSnapshotRepo
    days = res.get("dates", [])
    stale = ScoreSnapshotRepo(get_client()).mark_stale_dates(
        [_date.fromisoformat(x) for x in days]) if days else 0
    return {"message": f"指定采集完成：{res}", "ingest": res, "snapshots_marked_stale": stale}


def _h_ingest_codes(params: dict, ctx: TaskContext) -> dict:
    """指定股票采集（FR-DM-3）：对给定 codes 增量补到今天。"""
    from backend.services.ingest import IngestionService
    codes = params.get("codes")
    if not codes:
        raise ValueError("缺少 codes 参数")
    ctx.progress(0.1, f"采集 {len(codes)} 只指定股票…")
    res = IngestionService().update(codes=codes, ctx=ctx)
    ctx.progress(0.9, "标记评分快照失效…")
    stale = _mark_snapshots_stale()
    return {"message": f"指定股票采集完成：{res}", "ingest": res, "snapshots_marked_stale": stale}


def _h_recompute(params: dict, ctx: TaskContext) -> dict:
    ctx.progress(0.5, "标记评分快照失效…")
    stale = _mark_snapshots_stale()
    return {"message": f"已标记 {stale} 个(交易日×方案) 评分快照失效，将于下次访问时重算",
            "snapshots_marked_stale": stale}


def _h_verify(params: dict, ctx: TaskContext) -> dict:
    from backend.services.data_verify import DataVerifier
    from backend.services.data_report import DataIntegrityReport
    ctx.progress(0.2, "结构/价格/契约校验…")
    ctx.log("开始数据体检：结构 / 价格 / 契约")
    v = DataVerifier(quiet=True)
    v.check_structure()
    v.check_prices()
    v.check_contract()
    fails = v.fails()
    ctx.progress(0.7, "数据质量扫描…")
    ctx.log(f"结构/价格/契约校验完成，{'无异常' if not fails else f'{len(fails)} 项不达标'}")
    quality = DataIntegrityReport().scan_quality_issues()
    return {"message": "体检通过" if not fails else f"发现 {len(fails)} 项问题",
            "fails": fails, "quality": quality}


def _h_fix(params: dict, ctx: TaskContext) -> dict:
    """质检问题定向修复（FR-DM-4）：重拉该股该日期 → mark_stale_dates → 回写 issue 状态。"""
    import pandas as pd
    from backend.services.ingest import IngestionService
    from backend.scoring.snapshot import ScoreSnapshotRepo
    c = get_client()
    issue_id = params.get("issue_id")
    code = params.get("code")
    trade_date = params.get("trade_date")  # 可能为 None / 'YYYY-MM-DD' / Timestamp 串
    if issue_id is not None and (not code):
        df = c.query_df("SELECT code, trade_date FROM data_quality_issue WHERE id=?", [issue_id])
        if df.empty:
            raise ValueError(f"质检问题不存在: id={issue_id}")
        code = df.iloc[0]["code"]
        trade_date = df.iloc[0]["trade_date"]
    if not code:
        raise ValueError("缺少 code（或有效 issue_id）")
    # 统一成 date（容忍 'YYYY-MM-DD 00:00:00' / Timestamp / None）
    td = None if trade_date is None or (isinstance(trade_date, float) and pd.isna(trade_date)) \
        else pd.Timestamp(trade_date).date()
    td_s = str(td) if td else None
    if issue_id is not None:
        c.execute("UPDATE data_quality_issue SET status='fixing' WHERE id=?", [issue_id])
    ctx.progress(0.2, f"重拉 {code} {td_s or '近 30 日'} 行情…")
    ctx.log(f"定向修复：重拉 {code} {td_s or '(近 30 日)'}")
    ing = IngestionService()
    if td:
        rows = ing.ingest_one_daily(code, td, td)
        affected = [td]
    else:
        from datetime import date as _date, timedelta as _td
        end = _date.today()
        rows = ing.ingest_one_daily(code, end - _td(days=30), end)
        affected = []
    ctx.progress(0.7, "标记评分快照失效…")
    stale = ScoreSnapshotRepo(c).mark_stale_dates(affected) if affected else _mark_snapshots_stale()
    now = datetime.now()
    if issue_id is not None:
        c.execute("UPDATE data_quality_issue SET status='resolved', resolved_at=? WHERE id=?", [now, issue_id])
    ctx.log(f"修复完成：写入 {rows} 行，问题标记为已解决")
    return {"message": f"修复完成：{code} 重拉 {rows} 行", "code": code, "trade_date": td_s,
            "rows": int(rows), "snapshots_marked_stale": stale}


_HANDLERS = {
    "update": _h_update,
    "backfill": _h_backfill,
    "ingest_date": _h_ingest_date,
    "ingest_codes": _h_ingest_codes,
    "recompute": _h_recompute,
    "verify": _h_verify,
    "fix": _h_fix,
}
