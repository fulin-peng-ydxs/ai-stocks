"""数据管理·概览/质量/调度/数据源/系统设置 API（M2.8-B，FR-DM-1/4/5/7/12）。

配套 4 子页（数据概览 / 数据采集与任务 / 数据质量 / 调度与数据源）+ 配置管理·系统设置。
任务相关见 data_tasks.py。
"""

from __future__ import annotations

import json
from typing import Literal

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, model_validator

from backend.api.response import ApiResponse, err, ok
from backend.auth.context import get_current_context
from backend.auth.deps import require_system_perm
from backend.common.request import trusted_client_ip
from backend.config import get_effective_settings
from backend.storage.duckdb_client import get_client, get_read_client
from backend.storage.task_runtime import get_task_runtime_client

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
    return trusted_client_ip(request)


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
    from backend.services.stock_st_status import StockSTStatusService
    c = get_read_client()
    rep = DataIntegrityReport(c)
    ov = rep.overview()
    qm = rep.quality_model()   # M2.9：质量评分 + 分层达标 + 缺口（一次扫描，避免双扫）
    sev = c.query_df(
        "SELECT severity, count(*) AS n FROM data_quality_issue WHERE status='open' GROUP BY severity"
    )
    by_sev = {r["severity"] or "mid": int(r["n"]) for _, r in sev.iterrows()}
    last_scan = c.query_df(
        "SELECT max(detected_at) AS t FROM data_quality_issue").iloc[0]["t"]
    last_scan_s = None if last_scan is None or str(last_scan) == "NaT" else str(last_scan)[:19]
    board = _board_stage(c)
    from backend.services.intraday_archive import IntradayArchiveService
    return ok({
        "latest_trade_date": qm["latest_trade_date"],
        "codes": {"active": ov["stock_basic_live"], "delisted": ov["stock_basic_delisted"]},
        "bar_rows": ov["row_counts"]["daily_bar"],
        "board": board,
        "intraday": IntradayArchiveService(c).summary(),
        "st_status": StockSTStatusService(c).coverage(),
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

    c = get_read_client()
    rep = DataIntegrityReport(c)
    ov = rep.overview()
    qm = rep.quality_model()
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
        "score": {"latest_board_date": _latest_board_date(c)},
        "board": _board_stage(c),
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
                     "text": f"{tip}——可在「结果维护」中失效后访问榜单按需重算，或用公共榜单 CLI 预生产",
                     "link": "/data/ingest"})
    if days_since_scan is None:
        risk.append({"level": "warning", "text": "尚未做过数据质检", "link": "/data/quality"})
    elif days_since_scan > 3:
        risk.append({"level": "warning", "text": f"已 {days_since_scan} 天未做数据质检", "link": "/data/quality"})
    for s in down:
        risk.append({"level": "danger", "text": f"数据源 {s} 不可达", "link": "/data/schedule"})
    if not sched.get("enabled"):
        risk.append({"level": "info", "text": "未配置启用中的调度任务（数据不会自动更新/质检）",
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


def _board_stage(c) -> dict | None:
    """板块数据闭环环节：规模、覆盖、鲜活、质量问题与最近采集状态。"""
    try:
        from backend.storage.ddl import list_tables
        have = set(list_tables(c))
        bt = {k: (int(c.query_df(f"SELECT count(*) AS n FROM {k}").iloc[0]["n"]) if k in have else 0)
              for k in ("board_dict", "board_member", "board_bar", "board_fund_flow")}
        dims = c.query_df(
            "SELECT count(*) FILTER (WHERE board_type='concept') AS concept, "
            "count(*) FILTER (WHERE board_type='industry') AS industry "
            "FROM board_dict").iloc[0]
        latest_market = c.query_df("SELECT max(trade_date) AS t FROM daily_bar").iloc[0]["t"]
        latest_bar = c.query_df("SELECT max(trade_date) AS t FROM board_bar").iloc[0]["t"]
        latest_fund = c.query_df(
            "SELECT max(snapshot_date) AS t FROM board_fund_flow WHERE period='即时'").iloc[0]["t"]
        fund_expected = latest_market
        if fund_expected is None or str(fund_expected) == "NaT":
            fund_expected = latest_fund
        from backend.services.data_report import DataIntegrityReport

        coverage = DataIntegrityReport(c).board_coverage_summary(latest_market, fund_expected)
        issues_by_type: dict[str, int] = {}
        if "data_quality_issue" in have:
            issues = c.query_df(
                "SELECT issue_type, count(*) AS n FROM data_quality_issue "
                "WHERE status IN ('open','fixing') "
                "AND issue_type IN ('board_index_gap','board_index_gap_daily','board_index_invalid','board_member_incomplete',"
                "'board_fund_unmatched','board_fund_missing','board_fund_stale') "
                "GROUP BY issue_type")
            issues_by_type = {str(r["issue_type"]): int(r["n"]) for _, r in issues.iterrows()}
        last_update = None
        if "data_update_log" in have:
            lu = c.query_df(
                "SELECT table_name, status, detail, updated_at FROM data_update_log "
                "WHERE table_name IN ('board_dict','board_member','board_bar','board_fund_flow') "
                "ORDER BY updated_at DESC LIMIT 1")
            if not lu.empty:
                r = lu.iloc[0]
                last_update = {
                    "table_name": str(r["table_name"]), "status": str(r["status"]),
                    "detail": None if r["detail"] is None else str(r["detail"]),
                    "updated_at": str(r["updated_at"])[:19],
                }
        def _date_text(value):
            return None if value is None or str(value) == "NaT" else str(value)[:10]

        return {
            **bt,
            "concept_count": int(dims["concept"]), "industry_count": int(dims["industry"]),
            **coverage,
            "latest_bar_date": _date_text(latest_bar),
            "latest_fund_date": _date_text(latest_fund),
            "open_issues": sum(issues_by_type.values()),
            "issues_by_type": issues_by_type,
            "last_update": last_update,
        }
    except Exception as exc:  # noqa: BLE001
        from backend.common.logging import get_logger

        get_logger("api.data_admin").exception("板块概览统计失败: %s", exc)
        return None


def _latest_board_date(market=None, pg=None):
    """榜单最新日 = PG 公共预设中仍匹配当前 ST 版本的最新交易日。

    榜单页读 PG 的 PUBLIC_BOARD_OWNER 公共预设快照；这里同时复用其 stale、参数版本
    和 DuckDB ST 输入版本口径。旧 DuckDB score_snapshot_meta 已不是榜单页事实源。
    """
    try:
        from backend.services.public_board import latest_fresh_public_board_date

        t = latest_fresh_public_board_date(pg=pg, market=market)
        return None if t is None else str(t)
    except Exception:  # noqa: BLE001
        return None


@router.get("/catalog", response_model=ApiResponse, dependencies=_OVERVIEW)
def catalog(
    database: Literal["all", "duckdb", "postgres"] = "all",
    include_legacy: bool = False,
    table: str | None = None,
    count_mode: Literal["estimated", "exact"] = "estimated",
) -> ApiResponse:
    from backend.storage.catalog import CatalogExactCountError, build_catalog_payload

    try:
        payload = build_catalog_payload(
            client=get_read_client(),
            database=database,
            include_legacy=include_legacy,
            table=table,
            count_mode=count_mode,
        )
    except ValueError as exc:
        return err(400, str(exc))
    except CatalogExactCountError as exc:
        return err(500, str(exc))
    return ok(payload)


@router.get("/dimensions", response_model=ApiResponse, dependencies=_OVERVIEW)
def dimensions() -> ApiResponse:
    import json
    df = get_read_client().query_df(
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
    return ok(DataIntegrityReport(get_read_client()).stock_quality(code_list, kw, page, size))


@router.get("/boards", response_model=ApiResponse, dependencies=_OVERVIEW)
def search_boards(keyword: str | None = None, board_type: str | None = None,
                  size: int = 30) -> ApiResponse:
    """板块搜索（采集页「指定板块」下拉用）：板块代码/名称模糊匹配，返回 {code, name, board_type}。

    board_dict 未初始化时返回空列表（前端引导先采字典）。
    """
    from backend.storage import get_client
    c = get_client()
    have = "board_dict" in set(
        c.query_df("SELECT table_name FROM information_schema.tables WHERE table_schema='main'")
        ["table_name"].tolist())
    if not have:
        return ok({"list": [], "total": 0})
    conds, params = ["1=1"], []
    kw = keyword.strip() if keyword and keyword.strip() else None
    if kw:
        # board_code 原样模糊；name 用小写匹配 lower(name)（DuckDB LIKE 大小写敏感）
        conds.append("(board_code LIKE ? OR lower(name) LIKE ?)")
        params += [f"%{kw}%", f"%{kw.lower()}%"]
    if board_type:
        conds.append("board_type=?")
        params.append(board_type)
    where = " AND ".join(conds)
    total = int(c.query_df(
        f"SELECT count(*) AS n FROM board_dict WHERE {where}", params).iloc[0]["n"])
    df = c.query_df(
        f"SELECT board_code, name, board_type FROM board_dict WHERE {where} "
        f"ORDER BY board_code LIMIT ?", params + [int(size)])
    rows = [{"code": str(r["board_code"]), "name": str(r["name"]),
             "board_type": str(r["board_type"])} for _, r in df.iterrows()]
    return ok({"list": rows, "total": total})


# ── 质量修复（FR-DM-4）─────────────────────────────────────
def _quality_asset_clause(asset_type, alias="q"):
    """列表、汇总、批量恢复和忽略共用对象过滤，防止处置筛选外问题。"""
    from backend.services.market_benchmark import configured_benchmark_codes

    if asset_type == "index":
        return f"{alias}.code IN (SELECT unnest(?::VARCHAR[]))", [configured_benchmark_codes()]
    if asset_type == "stock":
        return f"{alias}.code IN (SELECT code FROM stock_basic)", []
    if asset_type not in (None, "all", ""):
        raise HTTPException(status_code=400, detail="未知质量问题对象类型")
    return "1=1", []


def _quality_keyword_clause(c, keyword: str, alias: str = "q") -> tuple[str, list[str]]:
    """质量台账对象搜索单一口径：股票、市场指数、板块及未匹配资金流名称。"""
    from backend.services.market_benchmark import BENCHMARK_NAMES

    keyword_text = keyword.strip().lower()
    kw = f"%{keyword.strip().lower()}%"
    clauses = [
        (f"{alias}.code IN (SELECT code FROM stock_basic "
         "WHERE lower(code) LIKE ? OR lower(name) LIKE ?)"),
    ]
    params = [kw, kw]
    have = set(c.query_df(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
    ).get("table_name", []))
    if "board_dict" in have:
        clauses.append(
            f"{alias}.code IN (SELECT board_code FROM board_dict "
            "WHERE lower(board_code) LIKE ? OR lower(name) LIKE ?)")
        params += [kw, kw]
    market_codes = [
        code for code, name in BENCHMARK_NAMES.items()
        if keyword_text in code.lower() or keyword_text in name.lower()
    ]
    if market_codes:
        clauses.append(f"{alias}.code IN ({','.join('?' * len(market_codes))})")
        params += market_codes
    clauses.append(
        f"({alias}.issue_type='board_fund_unmatched' AND "
        f"lower(COALESCE(json_extract_string(try_cast({alias}.detail AS JSON), '$.name'), '')) LIKE ?)")
    params.append(kw)
    return f"({' OR '.join(clauses)})", params


@router.get("/quality", response_model=ApiResponse, dependencies=_QUALITY_VIEW)
def quality(issue_type: str | None = None, severity: str | None = None,
            status: str | None = None, code: str | None = None,
            asset_type: Literal["all", "stock", "index"] = "all",
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
    clause, values = _quality_asset_clause(asset_type)
    base_conds.append(clause)
    base_params += values
    for col, val in (("severity", severity), ("status", status)):
        vals = _multi(val)
        if vals:
            base_conds.append(f"q.{col} IN ({','.join('?' * len(vals))})")
            base_params += vals
    if code:  # 股票/板块代码或名称模糊匹配（M2.9 DM-D17）
        clause, values = _quality_keyword_clause(c, code)
        base_conds.append(clause)
        base_params += values
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
        f"q.detail, q.detected_at, q.resolved_at, q.ignore_scope, q.ignore_active "
        f"FROM data_quality_issue q LEFT JOIN stock_basic sb ON sb.code = q.code WHERE {where} "
        f"ORDER BY {sort_expr} {direction} NULLS LAST, q.detected_at DESC NULLS LAST, q.id "
        f"LIMIT {int(size)} OFFSET {int((page-1)*size)}", params)
    rows = df.to_dict("records")
    from backend.services.data_report import DataIntegrityReport

    DataIntegrityReport(c).normalize_legacy_fund_lags(rows)
    # 非股票问题名称：市场指数走统一名称表；板块 code 走 board_dict；无 code 的资金流读 detail。
    from backend.services.market_benchmark import BENCHMARK_NAMES

    board_issue_codes = {str(x) for x in df["code"].tolist() if x is not None} if not df.empty else set()
    board_names: dict[str, str] = {}
    if board_issue_codes:
        bdf = c.query_df(
            f"SELECT board_code, name FROM board_dict WHERE board_code IN "
            f"({','.join('?' * len(board_issue_codes))})", sorted(board_issue_codes))
        board_names = {str(r["board_code"]): str(r["name"]) for _, r in bdf.iterrows()}
    for r in rows:
        for k in ("trade_date", "detected_at", "resolved_at"):
            v = r.get(k)
            r[k] = None if v is None or pd.isna(v) else str(v)
        nm = r.get("name")
        it = r.get("issue_type")
        detail = r.get("detail")
        if nm is None or pd.isna(nm) or not str(nm).strip():
            if (it in ("market_index_gap", "market_index_gap_daily", "market_index_invalid")
                    or str(it).startswith("intraday_")) \
                    and r.get("code"):
                nm = BENCHMARK_NAMES.get(str(r["code"]), str(r["code"]))
            elif it in ("board_member_incomplete", "board_index_gap", "board_index_gap_daily",
                      "board_index_invalid",
                      "board_fund_missing") and r.get("code"):
                nm = board_names.get(str(r["code"]), "")
            elif it == "board_fund_unmatched" and isinstance(detail, str) and detail.strip():
                try:
                    import json as _json
                    nm = str(_json.loads(detail).get("name") or "")
                except (ValueError, TypeError):
                    nm = ""
            elif it == "board_fund_stale":
                nm = "资金流（全源）"
            else:
                nm = ""
        r["name"] = str(nm)
        # 板块 issue 的 detail 可读化：采集层写的是 JSON（{reason,snapshot_date} 或 {name,board_type}），
        # 直接返回 JSON 字符串对用户不友好；转成自然语言文案。recheck/修复链路用 DB 原始 detail，不受此影响。
        if it in ("board_member_incomplete", "board_fund_unmatched") and isinstance(detail, str) and detail.strip():
            try:
                import json as _json
                payload = _json.loads(detail)
                if it == "board_member_incomplete":
                    r["detail"] = str(payload.get("reason") or detail)
                elif it == "board_fund_unmatched":
                    nm2 = str(payload.get("name") or "").strip()
                    bt2 = str(payload.get("board_type") or "").strip()
                    r["detail"] = f"未匹配到字典：{nm2}（{bt2}）" if nm2 else detail
            except (ValueError, TypeError):
                pass  # 非法 JSON 保留原样
        r["id"] = int(r["id"])
        ignore_active = r.get("ignore_active")
        r["ignore_active"] = False if ignore_active is None or pd.isna(ignore_active) \
            else bool(ignore_active)
    from backend.services.intraday_evidence import IntradayEvidence
    intraday_rows = [r for r in rows if r["issue_type"].startswith("intraday_")]
    if intraday_rows:
        evidence = IntradayEvidence(c)
        states = evidence.load(list({r["code"] for r in intraday_rows}))
        for row in intraday_rows:
            try:
                payload = json.loads(row["detail"] or "{}")
            except (ValueError, TypeError):
                payload = {"message": row["detail"]}
            if not isinstance(payload, dict):
                payload = {"message": str(row["detail"])}
            availability = evidence.assess(
                row["code"], row["trade_date"][:10],
                payload.get("coverage", {}).get("missing_times", []), states,
            )
            payload["availability"] = availability
            row["intraday"] = availability
            row["detail"] = json.dumps(payload, ensure_ascii=False)
    return ok({"summary": summary, "total": total, "page": page, "size": size, "list": rows})


class FixIn(BaseModel):
    issue_id: int | None = None
    code: str | None = None
    trade_date: str | None = None


def _quality_open_issue_ids(c, body: dict) -> tuple[list[int], list[str]]:
    """按质量页的类型、严重度和对象筛选，返回待处理问题 id 与类型筛选。"""
    def _multi(val) -> list[str]:
        if isinstance(val, list):
            return [str(x).strip() for x in val if str(x).strip()]
        return [x.strip() for x in str(val).split(",") if x.strip()] if val else []

    conds = ["status='open'"]
    params: list = []
    clause, values = _quality_asset_clause(body.get("asset_type"), alias="data_quality_issue")
    conds.append(clause)
    params += values
    types = _multi(body.get("issue_type"))
    if types:
        conds.append(f"issue_type IN ({','.join('?' * len(types))})")
        params += types
    sevs = _multi(body.get("severity"))
    if sevs:
        conds.append(f"severity IN ({','.join('?' * len(sevs))})")
        params += sevs
    if body.get("code"):
        clause, values = _quality_keyword_clause(c, str(body["code"]), alias="data_quality_issue")
        conds.append(clause)
        params += values
    ids = c.query_df(
        f"SELECT id FROM data_quality_issue WHERE {' AND '.join(conds)} ORDER BY id",
        params,
    )["id"].tolist()
    return [int(x) for x in ids], types


@router.post("/quality/ignore-batch", response_model=ApiResponse, dependencies=_QUALITY_FIX)
def quality_ignore_batch(body: dict) -> ApiResponse:
    """按当前筛选批量标记正常；只处理 open，忽略范围与单条操作保持一致。"""
    if not any((body.get("issue_type"), body.get("severity"), body.get("code"),
                body.get("asset_type") in ("stock", "index"))):
        return err(400, "请先选择问题类型、严重度或输入代码/名称")
    scope = str(body.get("scope") or "occurrence")
    if scope not in ("occurrence", "object"):
        return err(400, "scope 仅支持 occurrence 或 object")
    from datetime import datetime

    c = get_client()
    with c.transaction():
        ids, _ = _quality_open_issue_ids(c, body)
        if not ids:
            return err(400, "没有符合当前筛选的待处理问题")
        c.execute(
            "UPDATE data_quality_issue SET status='ignored', resolved_at=?, fix_task_id=NULL, "
            "ignore_scope=?, ignore_active=true "
            f"WHERE status='open' AND id IN ({','.join('?' * len(ids))})",
            [datetime.now(), scope, *ids],
        )
    return ok({"count": len(ids), "status": "ignored", "ignore_scope": scope})


@router.post("/quality/{issue_id}/fix", response_model=ApiResponse, dependencies=_QUALITY_FIX)
def quality_fix(issue_id: int, recheck_source: bool = False) -> ApiResponse:
    from backend.services.async_task import AsyncTaskService, ConcurrentTaskError
    row = get_client().query_df(
        "SELECT issue_type, status, fix_task_id FROM data_quality_issue WHERE id=?", [issue_id])
    if row.empty:
        return err(404, f"质检问题不存在: id={issue_id}")
    status = str(row.iloc[0]["status"])
    if status == "fixing":
        return err(409, "该问题正在恢复中，请等待任务完成或终止后复位",
                   {"fix_task_id": row.iloc[0]["fix_task_id"]})
    if status != "open":
        return err(400, f"仅未处理问题可恢复，当前状态: {status}")
    try:
        # 带上 issue_type，任务中心可显示「问题修复·<类型>」
        tid = AsyncTaskService().create("fix", {"issue_id": issue_id, "issue_type": row.iloc[0]["issue_type"],
                                               "recheck_source": recheck_source})
    except ConcurrentTaskError as e:
        return err(409, f"已有修复/采集任务在运行（{e.task_type}），请稍后再试", {"running_id": e.running_id})
    except ValueError as e:
        return err(400, str(e))
    return ok({"task_id": tid})


@router.post("/quality/fix-batch", response_model=ApiResponse, dependencies=_QUALITY_FIX)
def quality_fix_batch(body: dict) -> ApiResponse:
    """批量恢复：分时按股票并发取源，主线程串行归档与逐条复检，沿用单写任务互斥。"""
    from backend.services.async_task import AsyncTaskService, ConcurrentTaskError
    try:
        ids = list(dict.fromkeys(int(x) for x in (body.get("issue_ids") or [])))
    except (TypeError, ValueError):
        return err(400, "issue_ids 必须是整数数组")
    if not ids:
        return err(400, "缺少 issue_ids")
    c = get_client()
    rows = c.query_df(
        f"SELECT id, status FROM data_quality_issue WHERE id IN ({','.join('?' * len(ids))})",
        ids)
    found = {int(r["id"]): str(r["status"]) for _, r in rows.iterrows()}
    missing = [x for x in ids if x not in found]
    if missing:
        return err(404, f"质检问题不存在: {missing}")
    unavailable = {iid: status for iid, status in found.items() if status != "open"}
    if unavailable:
        return err(409, "批量恢复只接受未处理问题", {"unavailable": unavailable})
    try:
        tid = AsyncTaskService().create("fix", {"issue_ids": ids})
    except ConcurrentTaskError as e:
        return err(409, f"已有修复/采集任务在运行（{e.task_type}），请稍后再试", {"running_id": e.running_id})
    return ok({"task_id": tid})


@router.post("/quality/recover-batch", response_model=ApiResponse, dependencies=_QUALITY_FIX)
def quality_recover_batch(body: dict) -> ApiResponse:
    """按当前筛选一键恢复：取匹配的「待处理(open)」问题，建一个 fix 任务顺序恢复+复检。

    只按 issue_type/severity/code 过滤（状态强制 open；fixing 有任务归属，不能被另一任务接管）。
    """
    from backend.services.async_task import AsyncTaskService, ConcurrentTaskError
    c = get_client()
    ids, types = _quality_open_issue_ids(c, body)
    if not ids:
        return err(400, "没有符合当前筛选的待处理问题")
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
    row = c.query_df(
        "SELECT status, fix_task_id FROM data_quality_issue WHERE id=?", [issue_id])
    if row.empty:
        return err(404, f"质检问题不存在: id={issue_id}")
    if row.iloc[0]["status"] != "fixing":
        return err(400, "仅「修复中」的问题可复位")
    fix_task_id = row.iloc[0]["fix_task_id"]
    if fix_task_id:
        task = get_task_runtime_client().query_df(
            "SELECT status FROM async_task WHERE id=?", [fix_task_id]
        )
        if not task.empty and str(task.iloc[0]["status"]) in ("pending", "running"):
            return err(409, "恢复任务仍在运行，请先终止任务或等待完成",
                       {"fix_task_id": str(fix_task_id)})
    c.execute("UPDATE data_quality_issue SET status='open', fix_task_id=NULL WHERE id=?", [issue_id])
    return ok({"id": issue_id, "status": "open"})


class QualityIgnoreIn(BaseModel):
    scope: str = Field(pattern="^(occurrence|object)$")


@router.post("/quality/{issue_id}/ignore", response_model=ApiResponse, dependencies=_QUALITY_FIX)
def quality_ignore(issue_id: int, body: QualityIgnoreIn | None = None) -> ApiResponse:
    """标记正常并选择范围；body 为空兼容旧调用，默认仅忽略本次。"""
    c = get_client()
    from datetime import datetime
    scope = body.scope if body else "occurrence"
    row = c.query_df(
        "SELECT status, fix_task_id, ignore_scope, ignore_active "
        "FROM data_quality_issue WHERE id=?", [issue_id])
    if row.empty:
        return err(404, f"质检问题不存在: id={issue_id}")
    status = str(row.iloc[0]["status"])
    active = row.iloc[0]["ignore_active"]
    is_active = False if active is None or pd.isna(active) else bool(active)
    if status == "ignored" and is_active:
        if str(row.iloc[0]["ignore_scope"]) != scope:
            return err(409, "该问题已有不同范围的生效中忽略规则，请先恢复监控")
        return ok({"id": issue_id, "status": "ignored", "ignore_scope": scope})
    if status == "fixing":
        return err(409, "问题正在恢复中，不能同时标记正常",
                   {"fix_task_id": row.iloc[0]["fix_task_id"]})
    if status != "open":
        return err(400, f"仅未处理问题可标记正常，当前状态: {status}")
    c.execute(
        "UPDATE data_quality_issue SET status='ignored', resolved_at=?, fix_task_id=NULL, "
        "ignore_scope=?, ignore_active=true WHERE id=?",
        [datetime.now(), scope, issue_id],
    )
    return ok({"id": issue_id, "status": "ignored", "ignore_scope": scope})


@router.post("/quality/{issue_id}/restore-monitoring", response_model=ApiResponse,
             dependencies=_QUALITY_FIX)
def quality_restore_monitoring(issue_id: int) -> ApiResponse:
    """停用忽略规则；当前异常若仍存在，会在下一次质检/采集时重新报告。"""
    c = get_client()
    row = c.query_df(
        "SELECT status, ignore_active FROM data_quality_issue WHERE id=?", [issue_id])
    if row.empty:
        return err(404, f"质检问题不存在: id={issue_id}")
    if str(row.iloc[0]["status"]) != "ignored":
        return err(400, "仅已忽略的问题可恢复监控")
    active = row.iloc[0]["ignore_active"]
    if active is None or pd.isna(active) or not bool(active):
        return ok({"id": issue_id, "status": "ignored", "ignore_active": False})
    c.execute(
        "UPDATE data_quality_issue SET ignore_active=false WHERE id=?", [issue_id])
    return ok({"id": issue_id, "status": "ignored", "ignore_active": False})


@router.get("/quality/{issue_id}/delisting", response_model=ApiResponse, dependencies=_QUALITY_VIEW)
def quality_delisting_info(issue_id: int) -> ApiResponse:
    row = get_client().query_df("SELECT s.code,s.list_date,s.delist_date,s.delist_date_manual,s.delist_date_reported,(SELECT max(trade_date) FROM daily_bar b WHERE b.code=s.code) last_bar_date FROM data_quality_issue q JOIN stock_basic s ON s.code=q.code WHERE q.id=?", [issue_id])
    if row.empty:
        return err(404, "股票资料不存在")
    return ok({key: None if pd.isna(value) else (bool(value) if key == "delist_date_manual" else str(value)[:10] if key.endswith('date') or key == 'delist_date_reported' else value) for key,value in row.iloc[0].items()})


class MarkDelistedIn(BaseModel):
    delist_date: str | None = None  # NULL 表示撤销人工覆盖，恢复接口值。
    reason: str = Field(min_length=1, max_length=1000)


@router.post("/quality/{issue_id}/mark-delisted", response_model=ApiResponse, dependencies=_QUALITY_FIX)
def quality_mark_delisted(issue_id: int, body: MarkDelistedIn) -> ApiResponse:
    from backend.services.async_task import AsyncTaskService, ConcurrentTaskError
    from backend.services.manual_delisting import validate_delisting
    try:
        validate_delisting(get_client(), issue_id, body.delist_date, body.reason)
        actor = get_current_context()
        tid = AsyncTaskService().create("fix", {"manual_delisting": {
            "issue_id": issue_id, "delist_date": body.delist_date, "reason": body.reason,
            "actor": {"tenant_id": actor.tenant_id, "user_id": actor.user_id} if actor else None,
        }})
    except ValueError as exc:
        return err(400, str(exc))
    except ConcurrentTaskError as exc:
        return err(409, "已有行情写任务，请等待完成后再修改退市日期", {"running_id": exc.running_id})
    return ok({"task_id": tid})


# ── 定时任务（调度系统重构）：多条用户自定义定时任务的 CRUD + 立即触发 ─────────
class ScheduledJobIn(BaseModel):
    name: str
    task_type: str
    params: dict = Field(default_factory=dict)
    freq_type: str | None = None   # daily | weekly | monthly | cron（时间触发）
    freq_config: dict = Field(default_factory=dict)
    trigger_mode: str = "time"     # time | dependency
    dependency_job_id: str | None = None  # 兼容旧客户端
    dependency_job_ids: list[str] | None = None
    dependency_condition: str | None = None  # success | failure | completion
    dependency_delay: dict = Field(default_factory=lambda: {"value": 0, "unit": "minute"})
    retry_config: dict = Field(default_factory=lambda: {
        "enabled": False,
        "condition": "failure",
        "delay": {"value": 5, "unit": "minute"},
        "max_retries": 1,
    })
    trading_day_only: bool = True
    enabled: bool = True

    @model_validator(mode="after")
    def intraday_default_disabled(self):
        # 仅新分时类型缺省关闭；显式启用和其他任务既有默认值保持不变。
        if self.task_type == "intraday_ingest" and "enabled" not in self.model_fields_set:
            self.enabled = False
        return self


@router.get("/schedules", response_model=ApiResponse, dependencies=_SCHEDULE)
def schedules_list(page: int = 1, size: int = 20,
                   sort_by: Literal["name", "freq"] = "name",
                   sort_order: Literal["asc", "desc"] = "asc") -> ApiResponse:
    """定时任务列表（含频率人话、下次触发、最近触发）+ 可调度类型/频率枚举，前端建表单用。"""
    from backend.dataquality.checker import ACTIVE_QUALITY_ISSUE_TYPES
    from backend.scheduler.scheduler import SCHEDULABLE_TASK_TYPES, ScheduledJobService
    result = ScheduledJobService().list_page(
        page=page, size=size, sort_by=sort_by, sort_order=sort_order,
    )
    result.update({
        "task_types": list(SCHEDULABLE_TASK_TYPES),
        "quality_issue_types": list(ACTIVE_QUALITY_ISSUE_TYPES),
    })
    return ok(result)


@router.get("/schedules/options", response_model=ApiResponse, dependencies=_SCHEDULE)
def schedule_options(q: str = "", limit: int = 50) -> ApiResponse:
    """依赖任务远程选择候选；只返回轻量字段，避免借用分页主表数据。"""
    from backend.scheduler.scheduler import ScheduledJobService

    return ok({"list": ScheduledJobService().list_options(query=q, limit=limit)})


class DownstreamOrderIn(BaseModel):
    job_ids: list[str]
    revision: str = Field(min_length=64, max_length=64)


@router.get("/schedules/{job_id}/downstream", response_model=ApiResponse, dependencies=_SCHEDULE)
def schedules_downstream(job_id: str) -> ApiResponse:
    """完整直接下游及关系版本；不受调度主表分页限制。"""
    from backend.scheduler.scheduler import ScheduledJobService

    return ok(ScheduledJobService().downstream(job_id))


@router.put("/schedules/{job_id}/downstream-order", response_model=ApiResponse,
            dependencies=_SCHEDULE)
def schedules_downstream_order(job_id: str, body: DownstreamOrderIn) -> ApiResponse:
    """原子保存同一上游的完整下游顺序，仅影响以后生成的事件。"""
    from backend.scheduler.scheduler import ScheduledJobService

    return ok(ScheduledJobService().reorder_downstream(job_id, body.job_ids, body.revision),
              msg="下游触发顺序已保存")


@router.post("/schedules", response_model=ApiResponse, dependencies=_SCHEDULE)
def schedules_create(body: ScheduledJobIn) -> ApiResponse:
    from backend.scheduler.scheduler import ScheduledJobService
    try:
        job = ScheduledJobService().create(
            name=body.name, task_type=body.task_type, params=body.params,
            freq_type=body.freq_type, freq_config=body.freq_config,
            trigger_mode=body.trigger_mode, dependency_job_id=body.dependency_job_id,
            dependency_job_ids=body.dependency_job_ids,
            dependency_condition=body.dependency_condition,
            dependency_delay=body.dependency_delay, retry_config=body.retry_config,
            trading_day_only=body.trading_day_only, enabled=body.enabled)
    except ValueError as e:
        return err(400, str(e))
    return ok(job, msg="调度任务已创建")


@router.put("/schedules/{job_id}", response_model=ApiResponse, dependencies=_SCHEDULE)
def schedules_update(job_id: str, body: ScheduledJobIn) -> ApiResponse:
    from backend.scheduler.scheduler import ScheduledJobService
    try:
        job = ScheduledJobService().update(
            job_id, name=body.name, task_type=body.task_type, params=body.params,
            freq_type=body.freq_type, freq_config=body.freq_config,
            trigger_mode=body.trigger_mode, dependency_job_id=body.dependency_job_id,
            dependency_job_ids=body.dependency_job_ids,
            dependency_condition=body.dependency_condition,
            dependency_delay=body.dependency_delay, retry_config=body.retry_config,
            trading_day_only=body.trading_day_only, enabled=body.enabled)
    except ValueError as e:
        return err(400, str(e))
    return ok(job, msg="调度任务已更新")


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
    try:
        ScheduledJobService().delete(job_id)
    except ValueError as e:
        return err(409, str(e))
    return ok({"id": job_id}, msg="调度任务已删除")


@router.get("/schedules/{job_id}/trigger-events", response_model=ApiResponse, dependencies=_SCHEDULE)
def schedules_trigger_events(job_id: str, limit: int = 100) -> ApiResponse:
    """当前调度的所有触发机制记录，供调度页排障抽屉统一展示。"""
    from backend.scheduler.scheduler import ScheduledJobService
    svc = ScheduledJobService()
    if not svc.get(job_id):
        return err(404, "调度任务不存在")
    return ok({"events": svc.list_events(job_id, limit)})


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
def sources_test(source: str | None = None) -> ApiResponse:
    from backend.services.data_sources import source_status
    try:
        return ok(source_status(do_ping=True, source=source), msg="连通测试完成")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


# ── 系统设置（FR-DM-12 / DM-D2/D3）─────────────────────────
@router.get("/settings", response_model=ApiResponse, dependencies=_SETTINGS)
def get_settings_view() -> ApiResponse:
    """分组配置表单：每字段含 当前值 / 默认值 / 是否已覆盖。"""
    from backend.config import get_effective_settings
    from backend.config.settings import Settings, _raw_yaml
    from backend.storage.app_config import (
        CONFIG_GROUPS,
        SECRET_STATUS_UNSET,
        SECRET_STATUS_USABLE,
        AppConfigRepo,
    )

    eff = get_effective_settings().model_dump()
    default = Settings.model_validate(_raw_yaml()).model_dump()  # yaml 基线（不含覆盖）
    repo = AppConfigRepo()
    overrides = repo.get_overrides()
    override_keys = repo.get_override_keys()
    secret_statuses = repo.get_secret_statuses()
    from backend.services.ths_cookie_status import ths_cookie_status
    ths_credential = ths_cookie_status(validate=False, repo=repo)
    groups = []
    for g in CONFIG_GROUPS:
        if g.get("hidden_in_form"):   # 定时调度收敛到调度页，不在系统设置渲染（DM-D14）
            continue
        fields = []
        for f in g["fields"]:
            if f.get("hidden_in_form"):
                continue
            if f.get("app_config_only"):
                default_val = f.get("default")
                val = overrides.get(f["path"], default_val)
            else:
                val = _dig_config_value(eff, f["path"])
                default_val = _dig_config_value(default, f["path"])
            # 敏感字段（password 型）不回显明文：value 与 default 都只返回「是否已设置」掩码，
            # 避免前端拿到 Cookie。前端保存时留空不提交（draft 等于掩码 → 不纳入 updates），
            # 因此不会误清空已存值。
            if f.get("type") == "password":
                secret_status = secret_statuses.get(f["path"], SECRET_STATUS_UNSET)
                val = "••••••已设置" if secret_status == SECRET_STATUS_USABLE else ""
                default_val = "••••••已设置" if default_val else ""
            field_view = {**{k: f[k] for k in f if k != "path"},
                          "path": f["path"],
                          "value": val,
                          "default": default_val,
                          "overridden": f["path"] in override_keys}
            if f.get("nullable") and f["path"].startswith("ths_board."):
                shared_key = f["path"].split(".")[-1]
                shared_key = "socket_timeout_sec" if shared_key == "timeout_sec" else shared_key
                field_view["inherited_value"] = eff["datasource"][shared_key]
            if f.get("type") == "password":
                field_view["secret_status"] = secret_status
                if f["path"] == "ths_board.login_cookie":
                    field_view["credential"] = ths_credential
            fields.append(field_view)
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
    from backend.storage.app_config import CONFIG_GROUPS, AppConfigRepo, ConfigValidationError
    updates = dict(body.get("updates", body))
    # 敏感字段防御：掩码占位符（如前端异常回传「••••••已设置」）不得作为真实值入库。
    password_fields = {
        f["path"] for g in CONFIG_GROUPS for f in g["fields"]
        if f.get("type") == "password"
    }
    for path in list(updates):
        if path in password_fields and isinstance(updates[path], str) and updates[path].startswith("••••••"):
            updates.pop(path)
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
    from backend.storage.app_config import CONFIG_GROUPS, AppConfigRepo

    data = get_effective_settings().model_dump()
    standalone_defaults = {
        field["path"]: field.get("default")
        for group in CONFIG_GROUPS
        for field in group["fields"]
        if field.get("app_config_only")
    }
    overrides = AppConfigRepo().get_overrides()
    return {
        key: overrides.get(key, standalone_defaults.get(key))
        if key in standalone_defaults
        else _dig_config_value(data, key)
        for key in keys
    }


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
        from backend.services.audit_service import AuditService
        from backend.storage.audit_repository import AuditRepository

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
