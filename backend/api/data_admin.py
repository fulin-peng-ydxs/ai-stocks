"""数据管理·概览/质量/调度/数据源/系统设置 API（M2.8-B，FR-DM-1/4/5/7/12）。

配套 4 子页（数据概览 / 数据采集与任务 / 数据质量 / 调度与数据源）+ 配置管理·系统设置。
任务相关见 data_tasks.py。
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from backend.api.response import ApiResponse, err, ok
from backend.storage.duckdb_client import get_client

router = APIRouter(prefix="/api/data", tags=["data-admin"])


# ── 概览（FR-DM-1）─────────────────────────────────────────
@router.get("/overview", response_model=ApiResponse)
def overview() -> ApiResponse:
    from backend.services.data_report import DataIntegrityReport
    rep = DataIntegrityReport()
    ov = rep.overview()
    gaps = rep.gaps_summary()
    c = get_client()
    sev = c.query_df(
        "SELECT severity, count(*) AS n FROM data_quality_issue WHERE status='open' GROUP BY severity"
    )
    by_sev = {r["severity"] or "mid": int(r["n"]) for _, r in sev.iterrows()}
    return ok({
        "latest_trade_date": gaps["latest_trade_date"],
        "codes": {"active": ov["stock_basic_live"], "delisted": ov["stock_basic_delisted"]},
        "bar_rows": ov["row_counts"]["daily_bar"],
        "quality": {"open": int(sum(by_sev.values())), "by_severity": by_sev},
        "gaps": gaps,
    })


@router.get("/catalog", response_model=ApiResponse)
def catalog() -> ApiResponse:
    from backend.storage.catalog import build_catalog
    return ok({"tables": build_catalog()})


@router.get("/dimensions", response_model=ApiResponse)
def dimensions() -> ApiResponse:
    import json
    df = get_client().query_df(
        "SELECT dimension, name_cn, status, source, tables, descr FROM data_dimension_registry "
        "ORDER BY CASE status WHEN 'collected' THEN 0 WHEN 'partial' THEN 1 ELSE 2 END, dimension")
    rows = df.to_dict("records")
    for r in rows:
        try:
            r["tables"] = json.loads(r["tables"]) if r.get("tables") else []
        except (ValueError, TypeError):
            r["tables"] = []
    return ok({"dimensions": rows})


@router.get("/stock-quality", response_model=ApiResponse)
def stock_quality(codes: str | None = None, page: int = 1, size: int = 50) -> ApiResponse:
    from backend.services.data_report import DataIntegrityReport
    code_list = [c.strip() for c in codes.split(",") if c.strip()] if codes else None
    return ok(DataIntegrityReport().stock_quality(code_list, page, size))


# ── 质量修复（FR-DM-4）─────────────────────────────────────
@router.get("/quality", response_model=ApiResponse)
def quality(issue_type: str | None = None, severity: str | None = None,
            status: str | None = None, code: str | None = None,
            page: int = 1, size: int = 50) -> ApiResponse:
    """质检问题列表（含 severity/status，服务端分页/筛选）。中文化由前端映射。"""
    import pandas as pd
    c = get_client()
    summary = c.query_df(
        "SELECT issue_type, count(*) AS n FROM data_quality_issue WHERE status != 'resolved' "
        "GROUP BY issue_type ORDER BY n DESC").to_dict("records")
    conds, params = ["1=1"], []
    for col, val in (("issue_type", issue_type), ("severity", severity),
                     ("status", status), ("code", code)):
        if val:
            conds.append(f"{col} = ?")
            params.append(val)
    where = " AND ".join(conds)
    total = int(c.query_df(f"SELECT count(*) AS n FROM data_quality_issue WHERE {where}", params).iloc[0]["n"])
    df = c.query_df(
        f"SELECT id, code, trade_date, issue_type, severity, status, detail, detected_at, resolved_at "
        f"FROM data_quality_issue WHERE {where} "
        f"ORDER BY CASE severity WHEN 'high' THEN 0 WHEN 'mid' THEN 1 ELSE 2 END, detected_at DESC "
        f"LIMIT {int(size)} OFFSET {int((page-1)*size)}", params)
    rows = df.to_dict("records")
    for r in rows:
        for k in ("trade_date", "detected_at", "resolved_at"):
            v = r.get(k)
            r[k] = None if v is None or pd.isna(v) else str(v)
        r["id"] = int(r["id"])
    return ok({"summary": summary, "total": total, "page": page, "size": size, "list": rows})


class FixIn(BaseModel):
    issue_id: int | None = None
    code: str | None = None
    trade_date: str | None = None


@router.post("/quality/{issue_id}/fix", response_model=ApiResponse)
def quality_fix(issue_id: int) -> ApiResponse:
    from backend.services.async_task import AsyncTaskService, ConcurrentTaskError
    exists = get_client().query_df(
        "SELECT 1 FROM data_quality_issue WHERE id=?", [issue_id])
    if exists.empty:
        return err(404, f"质检问题不存在: id={issue_id}")
    try:
        tid = AsyncTaskService().create("fix", {"issue_id": issue_id})
    except ConcurrentTaskError as e:
        return err(409, f"已有修复/采集任务在运行（{e.task_type}），请稍后再试", {"running_id": e.running_id})
    except ValueError as e:
        return err(400, str(e))
    return ok({"task_id": tid})


@router.post("/quality/fix-batch", response_model=ApiResponse)
def quality_fix_batch(body: dict) -> ApiResponse:
    """批量修复（建议项）：按 issue_id 列表逐条建 fix 任务（受并发互斥约束，逐个排队）。"""
    from backend.services.async_task import AsyncTaskService, ConcurrentTaskError
    ids = body.get("issue_ids") or []
    svc = AsyncTaskService()
    started, skipped = [], []
    for iid in ids:
        try:
            started.append(svc.create("fix", {"issue_id": int(iid)}))
        except ConcurrentTaskError:
            skipped.append(iid)
            break  # 已有任务在跑，余下留待下次
        except ValueError:
            skipped.append(iid)
    return ok({"started": started, "skipped": skipped})


# ── 调度（FR-DM-7）─────────────────────────────────────────
@router.get("/scheduler", response_model=ApiResponse)
def scheduler_get() -> ApiResponse:
    from backend.scheduler.scheduler import status
    return ok(status())


class SchedulerIn(BaseModel):
    enabled: bool
    cron_hour: int = 18
    cron_minute: int = 0


@router.post("/scheduler", response_model=ApiResponse)
def scheduler_set(body: SchedulerIn) -> ApiResponse:
    if not (0 <= body.cron_hour <= 23 and 0 <= body.cron_minute <= 59):
        return err(400, "执行时间非法（时 0-23、分 0-59）")
    from backend.scheduler.scheduler import apply_config
    return ok(apply_config(body.enabled, body.cron_hour, body.cron_minute), msg="定时配置已生效")


# ── 数据源状态（FR-DM-5）───────────────────────────────────
@router.get("/sources", response_model=ApiResponse)
def sources(ping: bool = False) -> ApiResponse:
    from backend.services.data_sources import source_status
    return ok(source_status(do_ping=ping))


@router.post("/sources/test", response_model=ApiResponse)
def sources_test() -> ApiResponse:
    from backend.services.data_sources import source_status
    return ok(source_status(do_ping=True), msg="连通测试完成")


# ── 系统设置（FR-DM-12 / DM-D2/D3）─────────────────────────
@router.get("/settings", response_model=ApiResponse)
def get_settings_view() -> ApiResponse:
    """分组配置表单：每字段含 当前值 / 默认值 / 是否已覆盖。"""
    from backend.config import get_effective_settings
    from backend.config.settings import Settings, _raw_yaml
    from backend.storage.app_config import CONFIG_GROUPS, AppConfigRepo, apply_overrides

    def _dig(dump: dict, path: str):
        node = dump
        for p in path.split("."):
            if not isinstance(node, dict):
                return None
            node = node.get(p)
        return node

    eff = get_effective_settings().model_dump()
    default = Settings.model_validate(_raw_yaml()).model_dump()  # yaml 基线（不含覆盖）
    overrides = AppConfigRepo().get_overrides()
    groups = []
    for g in CONFIG_GROUPS:
        fields = []
        for f in g["fields"]:
            fields.append({**{k: f[k] for k in f if k != "path"},
                           "path": f["path"],
                           "value": _dig(eff, f["path"]),
                           "default": _dig(default, f["path"]),
                           "overridden": f["path"] in overrides})
        groups.append({"key": g["key"], "label": g["label"], "fields": fields})
    return ok({"groups": groups})


@router.post("/settings", response_model=ApiResponse)
def save_settings(body: dict) -> ApiResponse:
    """保存覆盖值（写 app_config 即时生效）。body={updates:{path:value}} 或直接 {path:value}。"""
    from backend.storage.app_config import AppConfigRepo, ConfigValidationError
    updates = body.get("updates", body)
    try:
        n = AppConfigRepo().set_many(updates)
    except ConfigValidationError as e:
        return err(400, str(e))
    # 调度相关改动即时套用到运行中的 scheduler
    if any(k.startswith("scheduler.") for k in updates):
        from backend.config import get_effective_settings
        from backend.scheduler.scheduler import apply_config
        s = get_effective_settings().scheduler
        apply_config(s.enabled, s.daily_cron_hour, s.daily_cron_minute)
    return ok({"saved": n}, msg="配置已保存并生效")
