"""板块成分快照候选接口（板块概念需求 R2 恢复闭环，plan §6.9 T9）。

候选（board_member_candidate）由采集拦截写入（事务①：候选 pending + issue open），
数据质量页系统管理员在此确认应用（事务②）或丢弃（事务③）。多语句原子事务走
DuckDBClient.transaction()；写锁冲突（跨进程采集持锁）归类 duckdb_write_unavailable 软失败。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.api.response import ApiResponse, err, ok
from backend.auth.deps import require_system_perm
from backend.common.exceptions import StorageError
from backend.storage.duckdb_client import get_client

router = APIRouter(prefix="/api/data/board-candidates", tags=["data-board-candidates"])

_VIEW = [Depends(require_system_perm("data-quality:view"))]
_FIX = [Depends(require_system_perm("data-quality:fix"))]


def _lock_conflict(e: StorageError) -> bool:
    """写锁冲突归类：transaction() 异常消息含锁关键字 → duckdb_write_unavailable。"""
    from backend.storage.duckdb_client import _LOCK_CONFLICT_RE
    return bool(_LOCK_CONFLICT_RE.search(str(e)))


@router.get("", response_model=ApiResponse, dependencies=_VIEW)
def list_candidates(status: str | None = None, board_type: str | None = None,
                    page: int = 1, size: int = 50) -> ApiResponse:
    """候选列表（默认 pending；可按 status/board_type 过滤）。字段含 apply_allowed/block_reason。"""
    c = get_client()
    conds, params = ["1=1"], []
    if status:
        conds.append("status=?")
        params.append(status)
    if board_type:
        conds.append("d.board_type=?")
        params.append(board_type)
    where = " AND ".join(conds)
    total = int(c.query_df(
        f"SELECT count(*) AS n FROM board_member_candidate cand "
        f"LEFT JOIN board_dict d ON d.board_code=cand.board_code WHERE {where}",
        params).iloc[0]["n"])
    # 同日已有 applied → 新候选 apply_allowed=false（本期不支持同日替换）
    applied = c.query_df(
        "SELECT board_code, snapshot_date FROM board_member_candidate WHERE status='applied'")
    applied_set = {(r["board_code"], str(pd_ts(r["snapshot_date"]))) for _, r in applied.iterrows()}
    df = c.query_df(
        f"""SELECT cand.candidate_id, cand.issue_id, cand.board_code, d.name AS board_name,
                   cand.snapshot_date, cand.diff_summary, cand.status, cand.applied_at
            FROM board_member_candidate cand
            LEFT JOIN board_dict d ON d.board_code=cand.board_code
            WHERE {where} ORDER BY cand.snapshot_date DESC, cand.board_code
            LIMIT ? OFFSET ?""",
        params + [size, (page - 1) * size])
    rows = []
    for _, r in df.iterrows():
        sd = str(pd_ts(r["snapshot_date"])) if r["snapshot_date"] is not None else None
        block = None
        if r["status"] == "pending" and (r["board_code"], sd) in applied_set:
            block = "same_day_snapshot_already_applied"
        rows.append({
            "candidate_id": r["candidate_id"], "issue_id": r["issue_id"],
            "board_code": r["board_code"], "board_name": r["board_name"],
            "snapshot_date": sd, "diff_summary": r["diff_summary"], "status": r["status"],
            "applied_at": str(r["applied_at"]) if r["applied_at"] is not None else None,
            "apply_allowed": not (block is not None), "block_reason": block,
        })
    return ok({"total": total, "page": page, "size": size, "list": rows})


@router.post("/{candidate_id}/apply", response_model=ApiResponse, dependencies=_FIX)
def apply_candidate(candidate_id: str) -> ApiResponse:
    """确认应用（事务②）：board_member diff 落库 + 候选 applied + issue resolved + member_count 刷新。"""
    from backend.services.board_ingest import BoardIngestService
    import json

    c = get_client()
    cand = c.query_df(
        "SELECT candidate_id, issue_id, board_code, snapshot_date, codes_json, status "
        "FROM board_member_candidate WHERE candidate_id=?", [candidate_id])
    if cand.empty:
        return err(404, f"候选不存在: {candidate_id}")
    r = cand.iloc[0]
    if r["status"] != "pending":
        return err(409, f"候选已被处理（当前 {r['status']}）", {"error_code": "already_processed"})
    # 同日已有 applied → 冻结（事务内二次校验 + 表达式唯一索引兜底）
    applied = c.query_df(
        "SELECT count(*) AS n FROM board_member_candidate "
        "WHERE board_code=? AND snapshot_date=? AND status='applied'",
        [r["board_code"], r["snapshot_date"]])
    if int(applied.iloc[0]["n"]) > 0:
        return err(409, "同板块同日已有已应用候选，本期不支持同日替换",
                   {"error_code": "same_day_snapshot_already_applied"})
    codes = json.loads(r["codes_json"])
    sdate = pd_ts(r["snapshot_date"])
    issue_id = int(r["issue_id"]) if r["issue_id"] is not None else None
    try:
        with c.transaction():
            # diff 落库 + member_count 刷新（同一事务内执行 SQL，R2 原子一致；DuckDB 不支持嵌套事务，
            # 故 _apply_member_diff 传 in_transaction=True 不自开事务，由本外层统一提交/回滚）
            svc = BoardIngestService(client=c)
            svc._apply_member_diff(r["board_code"], sdate, set(codes), member_count=len(codes),
                                   in_transaction=True)
            c.execute(
                "UPDATE board_member_candidate SET status='applied', applied_at=now() "
                "WHERE candidate_id=?", [candidate_id])
            if issue_id:
                c.execute(
                    "UPDATE data_quality_issue SET status='resolved', resolved_at=now(), "
                    "fix_task_id=NULL WHERE id=?", [issue_id])
    except StorageError as e:
        if _lock_conflict(e):
            return err(503, "数据库写入暂不可用（采集/回填进行中或外部进程占用），请稍后重试",
                       {"error_code": "duckdb_write_unavailable"})
        return err(500, f"应用候选失败: {e}")
    # best-effort 审计（失败不回滚业务）
    _audit("apply", candidate_id, r["board_code"])
    return ok({"status": "applied", "candidate_id": candidate_id})


@router.post("/{candidate_id}/discard", response_model=ApiResponse, dependencies=_FIX)
def discard_candidate(candidate_id: str) -> ApiResponse:
    """丢弃（事务③）：候选 discarded + issue ignored。"""
    c = get_client()
    cand = c.query_df(
        "SELECT candidate_id, issue_id, board_code, status FROM board_member_candidate "
        "WHERE candidate_id=?", [candidate_id])
    if cand.empty:
        return err(404, f"候选不存在: {candidate_id}")
    r = cand.iloc[0]
    if r["status"] != "pending":
        return err(409, f"候选已被处理（当前 {r['status']}）", {"error_code": "already_processed"})
    issue_id = int(r["issue_id"]) if r["issue_id"] is not None else None
    try:
        with c.transaction():
            c.execute("UPDATE board_member_candidate SET status='discarded' WHERE candidate_id=?",
                      [candidate_id])
            if issue_id:
                c.execute(
                    "UPDATE data_quality_issue SET status='ignored', resolved_at=now(), "
                    "fix_task_id=NULL WHERE id=?", [issue_id])
    except StorageError as e:
        if _lock_conflict(e):
            return err(503, "数据库写入暂不可用（采集/回填进行中或外部进程占用），请稍后重试",
                       {"error_code": "duckdb_write_unavailable"})
        return err(500, f"丢弃候选失败: {e}")
    _audit("discard", candidate_id, r["board_code"])
    return ok({"status": "discarded", "candidate_id": candidate_id})


def _audit(action: str, candidate_id: str, board_code: str) -> None:
    """best-effort 审计（复用 AuditRepository；失败仅 warning 不回滚业务，对齐 R2）。"""
    try:
        from backend.auth.context import get_current_context
        from backend.storage.audit_repository import AuditRepository
        ctx = get_current_context()
        AuditRepository().record(
            event_category="data-quality",
            event_type=f"board_candidate_{action}",
            action=action, result="success", status="completed",
            resource_code="data-quality:fix", target_type="board_member_candidate",
            target_id=candidate_id, target_label=board_code,
            tenant_id=ctx.tenant_id if ctx else None,
            actor_user_id=ctx.user_id if ctx else None,
        )
    except Exception:  # noqa: BLE001
        import logging
        logging.getLogger("api.board_candidates").warning(
            "候选 %s 审计写入失败（best-effort，不影响业务）", candidate_id)


def pd_ts(v) -> object:
    import pandas as pd
    return None if v is None or pd.isna(v) else pd.Timestamp(v)
