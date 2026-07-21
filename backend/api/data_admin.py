"""数据管理·概览/质量/调度/数据源/系统设置 API（M2.8-B，FR-DM-1/4/5/7/12）。

配套 4 子页（数据概览 / 数据采集与任务 / 数据质量 / 调度与数据源）+ 配置管理·系统设置。
任务相关见 data_tasks.py。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from backend.api.response import ApiResponse, err, ok
from backend.auth.context import get_current_context
from backend.auth.deps import require_system_perm
from backend.config import get_effective_settings
from backend.storage.duckdb_client import get_client

router = APIRouter(prefix="/api/data", tags=["data-admin"])

# stage4·T5：整 router 在 main.py 挂 require_system 硬守卫（system-only 数据管理）；此处每端点叠加精确码
# 供路由扫描（T8）与审计识别，运行时仍由 system 兜底。按功能域拆码（概览/质量看/质量处置/调度/数据源/设置）。
_OVERVIEW = [Depends(require_system_perm("data:overview"))]         # 概览/总览/目录/维度/溯源/单股质量（只读汇总）
_QUALITY_VIEW = [Depends(require_system_perm("data-quality:view"))]  # 质检问题列表
_QUALITY_FIX = [Depends(require_system_perm("data-quality:fix"))]    # 质量处置（修复/复位/忽略/恢复/标记退市）
_SCHEDULE = [Depends(require_system_perm("data-schedule:manage"))]   # 定时任务 CRUD / 启停 / 立即触发
_SOURCE = [Depends(require_system_perm("data-source:test"))]         # 数据源状态 / 连通测试
_SETTINGS = [Depends(require_system_perm("data-settings:manage"))]   # 系统设置读写


def _client_ip(request: Request) -> str | None:
    # 审计留痕用（system 管理员操作者 IP）；XFF 信任与限流同口径：仅可信反代时取 XFF，否则用连接地址。
    if get_effective_settings().server.trust_forwarded_for:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()
    return request.client.host if request.client else None


def _mask_email(addr: str) -> str:
    """脱敏邮箱：保留前 2 位本地部分与完整域名，其余打码。空值返回空串。"""
    addr = (addr or "").strip()
    if not addr:
        return ""
    if "@" not in addr:
        return "***"
    local, _, domain = addr.partition("@")
    head = local[:2]
    return f"{head}{'*' * max(1, len(local) - len(head))}@{domain}"


def _mail_status() -> dict:
    """只读的邮件能力就绪状态（脱敏）：供系统设置页在邮箱码开关旁提示底层是否真发。

    enabled/账号/密码来自部署级环境变量（AI_STOCKS_SMTP_*），不在运行期页面可改；
    此处仅暴露就绪度，避免「开关开了但邮件其实没配」的哑巴故障。

    mode 精确对齐 mailer.send_email 的真实分支（口径同源，防提示漂移）：
    - disabled：enabled=false → 只写 dev 日志、不真发（联调可看日志）；
    - incomplete：enabled=true 但 host/username/sender/密码 任一缺失 → 发信抛 MailError、发码会失败；
    - ready：enabled=true 且配置齐全 → 真实投递。
    """
    s = get_effective_settings()
    mc = s.mail_config()
    password_set = bool(s.smtp_password())
    # 与 mailer 就绪条件一致：host + username + (sender 回落 username) + 密码
    configured = bool(mc.host and mc.username and (mc.sender or mc.username) and password_set)
    if not mc.enabled:
        mode = "disabled"
    elif configured:
        mode = "ready"
    else:
        mode = "incomplete"
    return {
        "enabled": mc.enabled,
        "username_masked": _mask_email(mc.username),
        "password_set": password_set,
        "mode": mode,
        "ready": mode == "ready",
    }


def _dig_config_value(dump: dict, path: str):
    node = dump
    for part in path.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


# ── 概览（FR-DM-1）─────────────────────────────────────────
@router.get("/overview", response_model=ApiResponse, dependencies=_OVERVIEW)
def overview() -> ApiResponse:
    from backend.services.data_report import DataIntegrityReport
    rep = DataIntegrityReport()
    ov = rep.overview()
    qm = rep.quality_model()   # M2.9：质量评分 + 分层达标 + 缺口（一次扫描，避免双扫）
    c = get_client()
    sev = c.query_df(
        "SELECT severity, count(*) AS n FROM data_quality_issue WHERE status='open' GROUP BY severity"
    )
    by_sev = {r["severity"] or "mid": int(r["n"]) for _, r in sev.iterrows()}
    last_scan = c.query_df(
        "SELECT max(detected_at) AS t FROM data_quality_issue").iloc[0]["t"]
    last_scan_s = None if last_scan is None or str(last_scan) == "NaT" else str(last_scan)[:19]
    return ok({
        "latest_trade_date": qm["latest_trade_date"],
        "codes": {"active": ov["stock_basic_live"], "delisted": ov["stock_basic_delisted"]},
        "bar_rows": ov["row_counts"]["daily_bar"],
        "quality": {"open": int(sum(by_sev.values())), "by_severity": by_sev,
                    "score": qm["score"], "by_layer": qm["by_layer"]},
        "gaps": qm["gaps"],
        "last_scan_at": last_scan_s,
    })


# ── 数据总览首页（FR-DM-13，DM-D12）─────────────────────────
@router.get("/hub", response_model=ApiResponse, dependencies=_OVERVIEW)
def hub() -> ApiResponse:
    """数据总览：闭环各环节实时统计 + 风险摘要（服务端算好风险列表，前端直接渲染）。"""
    from datetime import date

    import pandas as pd

    from backend.scheduler.scheduler import status as sched_status
    from backend.services.data_report import DataIntegrityReport
    from backend.services.data_sources import source_status

    rep = DataIntegrityReport()
    ov = rep.overview()
    qm = rep.quality_model()
    c = get_client()
    sev = c.query_df(
        "SELECT severity, count(*) AS n FROM data_quality_issue WHERE status='open' GROUP BY severity")
    by_sev = {r["severity"] or "mid": int(r["n"]) for _, r in sev.iterrows()}
    # 距上次质检天数：自动扫描类问题最近一次 detected_at
    last_scan = c.query_df(
        "SELECT max(detected_at) AS t FROM data_quality_issue").iloc[0]["t"]
    days_since_scan = None
    if last_scan is not None and str(last_scan) != "NaT":
        days_since_scan = (date.today() - pd.Timestamp(last_scan).date()).days
    sched = sched_status()
    srcs = source_status(do_ping=False)
    sources = srcs.get("sources", []) if isinstance(srcs, dict) else srcs
    down = [s["source"] for s in sources if s.get("up") is False]

    # 闭环各环节实时数字（前端画流程图时挂在节点上）
    stages = {
        "ingest": {"bar_rows": ov["row_counts"]["daily_bar"],
                   "codes_active": ov["stock_basic_live"],
                   "latest_trade_date": qm["latest_trade_date"]},
        "quality": {"open": int(sum(by_sev.values())), "by_severity": by_sev,
                    "score": qm["score"], "days_since_scan": days_since_scan},
        "score": {"latest_board_date": _latest_board_date()},
    }

    # 风险摘要（已算好级别/文案/下钻链接）
    risk: list[dict] = []
    if qm["gaps"]["stocks_with_gap"] > 0:
        risk.append({"level": "warning",
                     "text": f"{qm['gaps']['stocks_with_gap']} 只股票存在数据缺口（共 {qm['gaps']['gap_days_total']} 个缺口日）",
                     "link": "/data/overview"})
    if by_sev.get("high", 0) > 0:
        risk.append({"level": "danger", "text": f"{by_sev['high']} 项高危质量问题待处理",
                     "link": "/data/quality?severity=high"})
    # 榜单新鲜度：公共预设快照已生产到的最新日 < 数据最新日 → 尚未对最新数据生产公共榜单。
    # bd 为 None 表示从未生产过任何公共预设快照。两种情况都只是"未算"，info 级提示，不由普通榜单页补算。
    bd, dd = stages["score"]["latest_board_date"], qm["latest_trade_date"]
    if dd and (bd is None or str(bd) < str(dd)):
        tip = "尚未生成榜单快照" if bd is None else f"榜单快照最新到 {bd}，数据已到 {dd}"
        risk.append({"level": "info",
                     "text": f"{tip}——需运行「评分维护」任务或公共榜单 CLI 生产最新公共榜单快照",
                     "link": "/board"})
    if days_since_scan is None:
        risk.append({"level": "warning", "text": "尚未做过数据质检", "link": "/data/quality"})
    elif days_since_scan > 3:
        risk.append({"level": "warning", "text": f"已 {days_since_scan} 天未做数据质检", "link": "/data/quality"})
    for s in down:
        risk.append({"level": "danger", "text": f"数据源 {s} 不可达", "link": "/data/schedule"})
    if not sched.get("enabled"):
        risk.append({"level": "info", "text": "未配置启用中的定时任务（数据不会自动更新/质检）",
                     "link": "/data/schedule"})
    if not risk:
        risk.append({"level": "success", "text": "数据状态良好，无显著风险", "link": "/data/overview"})

    return ok({
        "latest_trade_date": qm["latest_trade_date"],
        "quality_score": qm["score"],
        "stages": stages,
        "risk": risk,
        "scheduler": {"enabled": sched.get("enabled"), "next_run_time": sched.get("next_run_time")},
        "sources": sources,
    })


def _latest_board_date():
    """榜单最新日 = PG 公共预设快照中"已物化且未失效"的最新交易日。

    榜单页读 PG 的 PUBLIC_BOARD_OWNER 公共预设快照，且只读 stale=false；这里复用同一口径。
    旧 DuckDB score_snapshot_meta 已不是榜单页事实源，会把数据总览报旧。
    """
    try:
        from backend.services.public_board import latest_fresh_public_board_date

        t = latest_fresh_public_board_date()
        return None if t is None else str(t)
    except Exception:  # noqa: BLE001
        return None


@router.get("/catalog", response_model=ApiResponse, dependencies=_OVERVIEW)
def catalog() -> ApiResponse:
    from backend.storage.catalog import build_catalog
    return ok({"tables": build_catalog()})


@router.get("/dimensions", response_model=ApiResponse, dependencies=_OVERVIEW)
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


@router.get("/provenance", response_model=ApiResponse, dependencies=_OVERVIEW)
def provenance(code: str | None = None, page: int = 1, size: int = 50) -> ApiResponse:
    """数据来源溯源（审计）：列出用了非默认源（如 baostock 兜底）的取数事件。

    默认主源(akshare)不记录——查某股某段：此表有记录=该非默认源，无记录=默认主源。
    支持按代码或名称模糊筛选，按取数时间倒序分页。
    """
    import pandas as pd
    c = get_client()
    conds, params = ["1=1"], []
    if code:
        kw = f"%{code.strip().lower()}%"
        conds.append("(lower(p.code) LIKE ? OR p.code IN "
                     "(SELECT code FROM stock_basic WHERE lower(name) LIKE ?))")
        params += [kw, kw]
    where = " AND ".join(conds)
    total = int(c.query_df(
        f"SELECT count(*) AS n FROM data_source_provenance p WHERE {where}", params).iloc[0]["n"])
    df = c.query_df(
        f"SELECT p.code, sb.name, p.table_name, p.date_start, p.date_end, p.source, p.rows, p.fetched_at "
        f"FROM data_source_provenance p LEFT JOIN stock_basic sb ON sb.code = p.code WHERE {where} "
        f"ORDER BY p.fetched_at DESC LIMIT {int(size)} OFFSET {int((page-1)*size)}", params)
    rows = df.to_dict("records")
    for r in rows:
        for k in ("date_start", "date_end", "fetched_at"):
            v = r.get(k)
            r[k] = None if v is None or pd.isna(v) else str(v)
        r["rows"] = int(r["rows"]) if r.get("rows") is not None and not pd.isna(r["rows"]) else 0
        nm = r.get("name")
        r["name"] = "" if nm is None or pd.isna(nm) else str(nm)
    return ok({"total": total, "page": page, "size": size, "list": rows})


@router.get("/stock-quality", response_model=ApiResponse, dependencies=_OVERVIEW)
def stock_quality(codes: str | None = None, keyword: str | None = None,
                  page: int = 1, size: int = 50) -> ApiResponse:
    from backend.services.data_report import DataIntegrityReport
    code_list = [c.strip() for c in codes.split(",") if c.strip()] if codes else None
    kw = keyword.strip() if keyword and keyword.strip() else None
    return ok(DataIntegrityReport().stock_quality(code_list, kw, page, size))


# ── 质量修复（FR-DM-4）─────────────────────────────────────
@router.get("/quality", response_model=ApiResponse, dependencies=_QUALITY_VIEW)
def quality(issue_type: str | None = None, severity: str | None = None,
            status: str | None = None, code: str | None = None,
            page: int = 1, size: int = 50,
            sort_by: str = "time", sort_order: str = "desc") -> ApiResponse:
    """质检问题列表（含 severity/status，服务端分页/筛选）。中文化由前端映射。

    issue_type/severity/status 支持逗号分隔多值（前端多选），按 IN 过滤；空串/缺省即不限。
    """
    import pandas as pd
    c = get_client()

    def _multi(val: str | None) -> list[str]:
        return [x.strip() for x in val.split(",") if x.strip()] if val else []

    # 基础筛选（不含 issue_type）：summary 按此分组统计各类型，list 在此基础上再叠加 issue_type。
    # 这样顶部分组标签 = 当前筛选(状态/严重度/代码)下的各类型分布，与列表口径一致、可对得上。
    base_conds, base_params = ["1=1"], []
    for col, val in (("severity", severity), ("status", status)):
        vals = _multi(val)
        if vals:
            base_conds.append(f"q.{col} IN ({','.join('?' * len(vals))})")
            base_params += vals
    if code:  # 代码或名称模糊匹配（M2.9 DM-D17）
        kw = f"%{code.strip().lower()}%"
        base_conds.append("q.code IN (SELECT code FROM stock_basic WHERE lower(code) LIKE ? OR lower(name) LIKE ?)")
        base_params += [kw, kw]
    base_where = " AND ".join(base_conds)
    summary = c.query_df(
        f"SELECT issue_type, count(*) AS n FROM data_quality_issue q WHERE {base_where} "
        f"GROUP BY issue_type ORDER BY n DESC", base_params).to_dict("records")
    summary = [{"issue_type": r["issue_type"], "n": int(r["n"])} for r in summary]
    conds, params = list(base_conds), list(base_params)
    types = _multi(issue_type)
    if types:
        conds.append(f"q.issue_type IN ({','.join('?' * len(types))})")
        params += types
    where = " AND ".join(conds)
    total = int(c.query_df(f"SELECT count(*) AS n FROM data_quality_issue q WHERE {where}", params).iloc[0]["n"])
    direction = "ASC" if sort_order.lower() == "asc" else "DESC"
    sort_expr = {
        "time": "q.detected_at",
        "severity": "CASE q.severity WHEN 'high' THEN 0 WHEN 'mid' THEN 1 ELSE 2 END",
    }.get(sort_by, "q.detected_at")
    df = c.query_df(
        f"SELECT q.id, q.code, sb.name AS name, q.trade_date, q.issue_type, q.severity, q.status, "
        f"q.detail, q.detected_at, q.resolved_at "
        f"FROM data_quality_issue q LEFT JOIN stock_basic sb ON sb.code = q.code WHERE {where} "
        f"ORDER BY {sort_expr} {direction} NULLS LAST, q.detected_at DESC NULLS LAST, q.id "
        f"LIMIT {int(size)} OFFSET {int((page-1)*size)}", params)
    rows = df.to_dict("records")
    for r in rows:
        for k in ("trade_date", "detected_at", "resolved_at"):
            v = r.get(k)
            r[k] = None if v is None or pd.isna(v) else str(v)
        nm = r.get("name")
        r["name"] = "" if nm is None or pd.isna(nm) else str(nm)
        r["id"] = int(r["id"])
    return ok({"summary": summary, "total": total, "page": page, "size": size, "list": rows})


class FixIn(BaseModel):
    issue_id: int | None = None
    code: str | None = None
    trade_date: str | None = None


@router.post("/quality/{issue_id}/fix", response_model=ApiResponse, dependencies=_QUALITY_FIX)
def quality_fix(issue_id: int) -> ApiResponse:
    from backend.services.async_task import AsyncTaskService, ConcurrentTaskError
    row = get_client().query_df(
        "SELECT issue_type FROM data_quality_issue WHERE id=?", [issue_id])
    if row.empty:
        return err(404, f"质检问题不存在: id={issue_id}")
    try:
        # 带上 issue_type，任务中心可显示「问题修复·<类型>」
        tid = AsyncTaskService().create("fix", {"issue_id": issue_id, "issue_type": row.iloc[0]["issue_type"]})
    except ConcurrentTaskError as e:
        return err(409, f"已有修复/采集任务在运行（{e.task_type}），请稍后再试", {"running_id": e.running_id})
    except ValueError as e:
        return err(400, str(e))
    return ok({"task_id": tid})


@router.post("/quality/fix-batch", response_model=ApiResponse, dependencies=_QUALITY_FIX)
def quality_fix_batch(body: dict) -> ApiResponse:
    """批量恢复：一个 fix 任务内顺序恢复所有 issue_ids（单写者模型，逐条写实时日志 + 复检）。"""
    from backend.services.async_task import AsyncTaskService, ConcurrentTaskError
    ids = [int(x) for x in (body.get("issue_ids") or [])]
    if not ids:
        return err(400, "缺少 issue_ids")
    try:
        tid = AsyncTaskService().create("fix", {"issue_ids": ids})
    except ConcurrentTaskError as e:
        return err(409, f"已有修复/采集任务在运行（{e.task_type}），请稍后再试", {"running_id": e.running_id})
    return ok({"task_id": tid})


@router.post("/quality/recover-batch", response_model=ApiResponse, dependencies=_QUALITY_FIX)
def quality_recover_batch(body: dict) -> ApiResponse:
    """按当前筛选一键恢复：取匹配的「待处理(open/fixing)」问题，建一个 fix 任务顺序恢复+复检。

    只按 issue_type/severity/code 过滤（状态强制 open/fixing，恢复已解决/已忽略无意义）。
    """
    from backend.services.async_task import AsyncTaskService, ConcurrentTaskError
    c = get_client()

    def _multi(val) -> list[str]:
        if isinstance(val, list):
            return [str(x).strip() for x in val if str(x).strip()]
        return [x.strip() for x in str(val).split(",") if x.strip()] if val else []

    conds = ["status IN ('open','fixing')"]
    params: list = []
    types = _multi(body.get("issue_type"))
    if types:
        conds.append(f"issue_type IN ({','.join('?' * len(types))})"); params += types
    sevs = _multi(body.get("severity"))
    if sevs:
        conds.append(f"severity IN ({','.join('?' * len(sevs))})"); params += sevs
    if body.get("code"):
        kw = f"%{str(body['code']).lower()}%"
        conds.append("code IN (SELECT code FROM stock_basic WHERE lower(code) LIKE ? OR lower(name) LIKE ?)")
        params += [kw, kw]
    ids = c.query_df(
        f"SELECT id FROM data_quality_issue WHERE {' AND '.join(conds)} ORDER BY id", params)["id"].tolist()
    if not ids:
        return err(400, "没有符合当前筛选的待处理问题")
    ids = [int(x) for x in ids]
    params: dict = {"issue_ids": ids}
    if len(types) == 1:   # 单一类型筛选 → 任务中心显示「问题修复·<类型>」
        params["issue_type"] = types[0]
    try:
        tid = AsyncTaskService().create("fix", params)
    except ConcurrentTaskError as e:
        return err(409, f"已有修复/采集任务在运行（{e.task_type}），请稍后再试", {"running_id": e.running_id})
    return ok({"task_id": tid, "count": len(ids)})


@router.post("/quality/{issue_id}/reset", response_model=ApiResponse, dependencies=_QUALITY_FIX)
def quality_reset(issue_id: int) -> ApiResponse:
    """手动复位「修复中」→「未处理」（DM 修复中闭环）：当绑定的修复任务已失败/中断/卡死，
    用户可一键解套，让该问题重新可被恢复。仅对 fixing 状态生效，并解除任务绑定。"""
    c = get_client()
    row = c.query_df("SELECT status FROM data_quality_issue WHERE id=?", [issue_id])
    if row.empty:
        return err(404, f"质检问题不存在: id={issue_id}")
    if row.iloc[0]["status"] != "fixing":
        return err(400, "仅「修复中」的问题可复位")
    c.execute("UPDATE data_quality_issue SET status='open', fix_task_id=NULL WHERE id=?", [issue_id])
    return ok({"id": issue_id, "status": "open"})


@router.post("/quality/{issue_id}/ignore", response_model=ApiResponse, dependencies=_QUALITY_FIX)
def quality_ignore(issue_id: int) -> ApiResponse:
    """标记为正常/忽略（DM-D22）：不可恢复或真实极端值（如新股首日大涨）人工确认正常，
    置 status='ignored'。质检幂等重扫不会再翻回 open（DELETE 只清 open）。"""
    c = get_client()
    from datetime import datetime
    exists = c.query_df("SELECT 1 FROM data_quality_issue WHERE id=?", [issue_id])
    if exists.empty:
        return err(404, f"质检问题不存在: id={issue_id}")
    c.execute("UPDATE data_quality_issue SET status='ignored', resolved_at=? WHERE id=?",
              [datetime.now(), issue_id])
    return ok({"id": issue_id, "status": "ignored"})


class MarkDelistedIn(BaseModel):
    delist_date: str               # YYYY-MM-DD：人工指定的退市日


@router.post("/quality/{issue_id}/mark-delisted", response_model=ApiResponse, dependencies=_QUALITY_FIX)
def quality_mark_delisted(issue_id: int, body: MarkDelistedIn) -> ApiResponse:
    """标记退市（应对数据源退市识别不准导致的持续缺口/滞后）：把人工指定的退市日写入
    stock_basic.delist_date，并把该股所有未处理的缺口/滞后问题置为已解决——退市后无后续行情属正常，
    覆盖鲜活扫描据 delist_date 自动排除该股，不再复发。仅对缺口(data_gap)/滞后(stale)类问题开放。"""
    from datetime import date as _date, datetime
    c = get_client()
    row = c.query_df("SELECT code, issue_type FROM data_quality_issue WHERE id=?", [issue_id])
    if row.empty:
        return err(404, f"质检问题不存在: id={issue_id}")
    code, issue_type = row.iloc[0]["code"], row.iloc[0]["issue_type"]
    if issue_type not in ("data_gap", "stale"):
        return err(400, "仅缺口/滞后类问题支持标记退市")
    if not code:
        return err(400, "该问题无关联股票代码，无法标记退市")
    try:
        dl = _date.fromisoformat(str(body.delist_date)[:10])   # 容错：截掉可能带的 00:00:00 时间段
    except (ValueError, TypeError):
        return err(400, f"退市日期非法: {body.delist_date}（需 YYYY-MM-DD）")
    c.execute("UPDATE stock_basic SET delist_date=? WHERE code=?", [dl, code])
    now = datetime.now()
    affected = int(c.query_df(
        "SELECT count(*) AS n FROM data_quality_issue WHERE code=? "
        "AND issue_type IN ('data_gap','stale') AND status IN ('open','fixing')", [code]).iloc[0]["n"])
    c.execute(
        "UPDATE data_quality_issue SET status='resolved', resolved_at=?, fix_task_id=NULL "
        "WHERE code=? AND issue_type IN ('data_gap','stale') AND status IN ('open','fixing')",
        [now, code])
    return ok({"code": code, "delist_date": str(dl), "resolved": affected},
              msg=f"已标记 {code} 于 {dl} 退市，解决 {affected} 项缺口/滞后")


# ── 定时任务（调度系统重构）：多条用户自定义定时任务的 CRUD + 立即触发 ─────────
class ScheduledJobIn(BaseModel):
    name: str
    task_type: str
    params: dict = {}
    freq_type: str                 # daily | weekly | monthly | cron
    freq_config: dict = {}         # {time} / {weekdays,time} / {day,time} / {cron}
    trading_day_only: bool = True
    enabled: bool = True


@router.get("/schedules", response_model=ApiResponse, dependencies=_SCHEDULE)
def schedules_list() -> ApiResponse:
    """定时任务列表（含频率人话、下次触发、最近触发）+ 可调度类型/频率枚举，前端建表单用。"""
    from backend.dataquality.checker import QUALITY_ISSUE_TYPES
    from backend.scheduler.scheduler import SCHEDULABLE_TASK_TYPES, ScheduledJobService
    return ok({"jobs": ScheduledJobService().list(),
               "task_types": list(SCHEDULABLE_TASK_TYPES),
               "quality_issue_types": list(QUALITY_ISSUE_TYPES)})


@router.post("/schedules", response_model=ApiResponse, dependencies=_SCHEDULE)
def schedules_create(body: ScheduledJobIn) -> ApiResponse:
    from backend.scheduler.scheduler import ScheduledJobService
    try:
        job = ScheduledJobService().create(
            name=body.name, task_type=body.task_type, params=body.params,
            freq_type=body.freq_type, freq_config=body.freq_config,
            trading_day_only=body.trading_day_only, enabled=body.enabled)
    except ValueError as e:
        return err(400, str(e))
    return ok(job, msg="定时任务已创建")


@router.put("/schedules/{job_id}", response_model=ApiResponse, dependencies=_SCHEDULE)
def schedules_update(job_id: str, body: ScheduledJobIn) -> ApiResponse:
    from backend.scheduler.scheduler import ScheduledJobService
    try:
        job = ScheduledJobService().update(
            job_id, name=body.name, task_type=body.task_type, params=body.params,
            freq_type=body.freq_type, freq_config=body.freq_config,
            trading_day_only=body.trading_day_only, enabled=body.enabled)
    except ValueError as e:
        return err(400, str(e))
    return ok(job, msg="定时任务已更新")


@router.post("/schedules/{job_id}/enabled", response_model=ApiResponse, dependencies=_SCHEDULE)
def schedules_set_enabled(job_id: str, enabled: bool) -> ApiResponse:
    from backend.scheduler.scheduler import ScheduledJobService
    try:
        job = ScheduledJobService().set_enabled(job_id, enabled)
    except ValueError as e:
        return err(400, str(e))
    return ok(job, msg="已启用" if enabled else "已停用")


@router.delete("/schedules/{job_id}", response_model=ApiResponse, dependencies=_SCHEDULE)
def schedules_delete(job_id: str) -> ApiResponse:
    from backend.scheduler.scheduler import ScheduledJobService
    ScheduledJobService().delete(job_id)
    return ok({"id": job_id}, msg="定时任务已删除")


@router.post("/schedules/{job_id}/run", response_model=ApiResponse, dependencies=_SCHEDULE)
def schedules_run_now(job_id: str) -> ApiResponse:
    """立即触发一次（不判交易日）；已有写任务在跑则 409。"""
    from backend.scheduler.scheduler import ScheduledJobService
    from backend.services.async_task import ConcurrentTaskError
    try:
        tid = ScheduledJobService().run_now(job_id)
    except ValueError as e:
        return err(404, str(e))
    except ConcurrentTaskError as e:
        return err(409, f"已有写任务在运行（{e.task_type}），请等待其完成或稍后再试",
                   {"running_id": e.running_id})
    return ok({"task_id": tid}, msg="已触发")


# ── 数据源状态（FR-DM-5）───────────────────────────────────
@router.get("/sources", response_model=ApiResponse, dependencies=_SOURCE)
def sources(ping: bool = False) -> ApiResponse:
    from backend.services.data_sources import source_status
    return ok(source_status(do_ping=ping))


@router.post("/sources/test", response_model=ApiResponse, dependencies=_SOURCE)
def sources_test() -> ApiResponse:
    from backend.services.data_sources import source_status
    return ok(source_status(do_ping=True), msg="连通测试完成")


# ── 系统设置（FR-DM-12 / DM-D2/D3）─────────────────────────
@router.get("/settings", response_model=ApiResponse, dependencies=_SETTINGS)
def get_settings_view() -> ApiResponse:
    """分组配置表单：每字段含 当前值 / 默认值 / 是否已覆盖。"""
    from backend.config import get_effective_settings
    from backend.config.settings import Settings, _raw_yaml
    from backend.storage.app_config import CONFIG_GROUPS, AppConfigRepo, apply_overrides

    eff = get_effective_settings().model_dump()
    default = Settings.model_validate(_raw_yaml()).model_dump()  # yaml 基线（不含覆盖）
    overrides = AppConfigRepo().get_overrides()
    groups = []
    for g in CONFIG_GROUPS:
        if g.get("hidden_in_form"):   # 定时调度收敛到调度页，不在系统设置渲染（DM-D14）
            continue
        fields = []
        for f in g["fields"]:
            fields.append({**{k: f[k] for k in f if k != "path"},
                           "path": f["path"],
                           "value": _dig_config_value(eff, f["path"]),
                           "default": _dig_config_value(default, f["path"]),
                           "overridden": f["path"] in overrides})
        groups.append({
            "key": g["key"],
            "label": g["label"],
            "desc": g.get("desc"),
            "fields": fields,
        })
    return ok({"groups": groups, "mail_status": _mail_status()})


@router.post("/settings", response_model=ApiResponse, dependencies=_SETTINGS)
def save_settings(body: dict, request: Request) -> ApiResponse:
    """保存覆盖值（写 app_config 即时生效）。body={updates:{path:value}} 或直接 {path:value}。"""
    from backend.storage.app_config import AppConfigRepo, ConfigValidationError
    updates = body.get("updates", body)
    keys = sorted(str(k) for k in updates)
    repo = AppConfigRepo()
    before = _effective_setting_values(keys)
    try:
        n = repo.set_many(updates)
    except ConfigValidationError as e:
        return err(400, str(e))
    after = _effective_setting_values(keys)
    _record_settings_audit(updates, n, request, before=before, after=after)
    return ok({"saved": n}, msg="配置已保存并生效")


@router.post("/settings/reset", response_model=ApiResponse, dependencies=_SETTINGS)
def reset_settings(body: dict, request: Request) -> ApiResponse:
    """删除指定覆盖值，回落到 settings.yaml 默认。body={paths:[path,...]}。"""
    from backend.storage.app_config import AppConfigRepo, ConfigValidationError

    paths = body.get("paths")
    if not isinstance(paths, list):
        return err(400, "paths 必须是数组")
    keys = sorted({str(path) for path in paths})
    repo = AppConfigRepo()
    before = _effective_setting_values(keys)
    try:
        n = repo.reset_many(keys)
    except ConfigValidationError as e:
        return err(400, str(e))
    after = _effective_setting_values(keys)
    _record_settings_audit(
        {key: None for key in keys},
        n,
        request,
        before=before,
        after=after,
        action="reset",
    )
    return ok({"reset": n}, msg="配置已重置为默认值")


def _effective_setting_values(keys: list[str]) -> dict:
    from backend.config import get_effective_settings

    data = get_effective_settings().model_dump()
    return {key: _dig_config_value(data, key) for key in keys}


def _record_settings_audit(
    updates: dict,
    saved_count: int,
    request: Request,
    *,
    before: dict | None = None,
    after: dict | None = None,
    action: str = "update",
) -> None:
    """系统设置保存审计：只记录 key 和数量，不记录配置值。"""
    if not updates:
        return
    try:
        from backend.storage.audit_repository import AuditRepository
        from backend.services.audit_service import AuditService

        ctx = get_current_context()
        keys = sorted(str(k) for k in updates)
        changes = AuditService.build_changes(before, after, fields=keys)
        AuditRepository().record(
            event_category="config",
            event_type="config",
            action=action,
            resource_code="data-settings:manage",
            target_type="app_config",
            target_id=",".join(keys),
            target_label="系统设置",
            result="success",
            status="completed",
            tenant_id=ctx.tenant_id if ctx else None,
            actor_user_id=ctx.user_id if ctx else None,
            ip=_client_ip(request),
            method=request.method,
            path=request.url.path,
            context={"config_keys": keys, "affected_count": saved_count},
            changes=changes,
        )
    except Exception as e:  # noqa: BLE001
        from backend.common.logging import get_logger

        get_logger("api.data_admin").warning("系统设置审计写入失败，已降级忽略: %s", e)
