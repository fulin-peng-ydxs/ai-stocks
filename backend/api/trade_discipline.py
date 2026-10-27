"""交易纪律规则、履约打卡与专用股票选择 API。"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, TypeVar

import pandas as pd
from fastapi import APIRouter, Depends, Path, Query
from pydantic import BaseModel, ConfigDict, Field

from backend.api.response import ApiResponse, ok
from backend.auth.context import get_current_context
from backend.auth.deps import require_any_perm, require_perm
from backend.common.exceptions import NotFoundError, ValidationError
from backend.services.audit_service import AuditService
from backend.services.stock_st_status import StockSTStatusService, STStatusNotReadyError
from backend.services.trade_discipline_service import TradeDisciplineService
from backend.services.trade_ledger_service import TradeLedgerService
from backend.storage import get_read_client as get_client

router = APIRouter(prefix="/api/trade-discipline", tags=["trade-discipline"])

VIEW = "trade-discipline:view"
RULE_MANAGE = "trade-discipline:rule-manage"
CHECKIN_VIEW = "trade-discipline:checkin-view"
CHECKIN_SUBMIT = "trade-discipline:checkin-submit"

T = TypeVar("T")


class _ApiNotFoundError(NotFoundError):
    http_status = 404


class _ApiValidationError(ValidationError):
    http_status = 422


def _call(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """只在本模块把服务层软失败映射为 T4 约定的真实 HTTP 状态。"""
    try:
        return func(*args, **kwargs)
    except NotFoundError as exc:
        raise _ApiNotFoundError(exc.msg) from exc
    except ValidationError as exc:
        raise _ApiValidationError(exc.msg) from exc


def _service() -> TradeDisciplineService:
    return TradeDisciplineService()


def _audit(action: str, target_type: str, target_id: str, resource_code: str) -> None:
    ctx = get_current_context()
    AuditService().record_domain_event(
        event_type="trade_discipline",
        action=action,
        target_type=target_type,
        target_id=target_id,
        resource_code=resource_code,
        tenant_id=ctx.tenant_id if ctx else None,
        actor_user_id=ctx.user_id if ctx else None,
    )


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


MoneyDecimal = Annotated[Decimal, Field(ge=0, max_digits=20, decimal_places=2)]
FourPlaceDecimal = Annotated[Decimal, Field(ge=0, max_digits=20, decimal_places=4)]


ConditionFilter = Literal["any", "exclude", "only"]
FactStatus = Literal["yes", "no", "unknown"]


class ChecklistItemBody(StrictBody):
    item_id: str | None = None
    # other 仅兼容旧草稿/客户端；保存时服务层统一转为 technical。
    category: str = Field(default="technical", pattern=r"^[a-z][a-z0-9_:-]{0,63}$")
    category_label: str | None = None
    text: str = ""
    display_order: int = Field(strict=True, ge=1)


class ChecklistResultBody(StrictBody):
    item_id: str
    status: FactStatus


class StockRuleBody(StrictBody):
    checklist_items: list[ChecklistItemBody] = Field(default_factory=list)
    price_min: Annotated[Decimal, Field(gt=0, max_digits=20, decimal_places=4)] | None = None
    price_max: Annotated[Decimal, Field(gt=0, max_digits=20, decimal_places=4)] | None = None
    st_filter: ConditionFilter = "any"
    loss_filter: ConditionFilter = "any"
    st_risk_filter: ConditionFilter = "any"
    detail_id: str | None = None
    name: str | None = None
    max_capital: MoneyDecimal | None = None
    content: str | None = None
    display_order: int = Field(ge=1)
    enabled: bool = True


class ActionRuleBody(StrictBody):
    detail_id: str | None = None
    name: str | None = None
    action_type: Literal["buy", "sell"] | None = None
    action_subtype: str | None = Field(default=None, max_length=64)
    action_subtype_label: str | None = None
    content: str | None = None
    display_order: int = Field(ge=1)
    enabled: bool = True


class RuleDraftBody(StrictBody):
    max_positions: Annotated[int, Field(strict=True, gt=0, le=2147483647)] | None = None
    name: str | None = None
    capital: MoneyDecimal | None = None
    stock_rules: list[StockRuleBody] = Field(default_factory=list)
    action_rules: list[ActionRuleBody] = Field(default_factory=list)


class SaveDraftBody(RuleDraftBody):
    expected_revision: int = Field(ge=1)


class RevisionBody(StrictBody):
    expected_revision: int = Field(ge=1)


class CopyRuleBody(StrictBody):
    source: Literal["published", "draft"] = "published"


class OperationBody(StrictBody):
    checklist_results: list[ChecklistResultBody] | None = None
    loss_status: FactStatus | None = None
    st_risk_status: FactStatus | None = None
    id: str | None = None
    stock_code: str
    # 兼容旧客户端字段；保存时始终由服务端按 stock_code 解析权威名称。
    stock_name_snapshot: str | None = None
    side: Literal["buy", "sell"]
    stock_rule_id: str
    action_rule_id: str
    price: FourPlaceDecimal
    quantity: FourPlaceDecimal
    amount: MoneyDecimal
    fee: MoneyDecimal
    operated_at: datetime | None = None
    note: str | None = None
    compliance_status: Literal["complied", "breached"] | None = None
    display_order: int = Field(ge=1)


class CheckinContentBody(StrictBody):
    violation_items: list[Literal["missed_buy", "missed_sell", "other"]] | None = Field(
        default=None, max_length=3
    )
    peak_positions: Annotated[int, Field(strict=True, ge=0, le=2147483647)] | None = None
    assessment: Literal["complied", "partial", "breached"]
    no_operation: bool
    reason_code: str | None = None
    reason_id: str | None = None
    reason_text: str | None = None
    violation_detail: str | None = None
    review_note: str | None = None
    operations: list[OperationBody] = Field(default_factory=list)


class SubmitCheckinBody(CheckinContentBody):
    rule_id: str
    trade_date: date


class AmendCheckinBody(CheckinContentBody):
    expected_revision: int = Field(ge=1)


class QuickNoOperationBody(StrictBody):
    rule_id: str
    trade_date: date


class LedgerOpeningBody(StrictBody):
    stock_code: str = Field(min_length=1, max_length=32)
    quantity: FourPlaceDecimal
    cost: MoneyDecimal | None = None
    cost_price: FourPlaceDecimal | None = None
    rule_id: str | None = None
    stock_rule_id: str | None = None


class LedgerInitializeBody(StrictBody):
    trade_date: date
    expected_revision: int = Field(strict=True, ge=0)
    positions: list[LedgerOpeningBody] = Field(default_factory=list, max_length=3000)
    cash: MoneyDecimal | None = None


class LedgerRuleCheckBody(StrictBody):
    rule_id: str
    stock_rule_id: str
    action_rule_id: str
    action_matches: bool = True
    stock_matches: bool = True
    checklist_results: list[ChecklistResultBody] = Field(default_factory=list, max_length=1000)
    loss_status: Literal["yes", "no"] | None = None
    st_risk_status: Literal["yes", "no"] | None = None


class LedgerEventBody(StrictBody):
    event_id: str = Field(min_length=1, max_length=96)
    kind: Literal["trade", "position", "cash"] = "trade"
    rule_id: str | None = None
    stock_code: str | None = Field(default=None, max_length=32)
    side: Literal["buy", "sell"] | None = None
    direction: Literal["in", "out"] | None = None
    adjustment_type: Literal["transfer", "bonus", "split", "correction", "deposit", "withdrawal", "dividend", "other"] | None = None
    stock_rule_id: str | None = None
    action_rule_id: str | None = None
    price: FourPlaceDecimal | None = None
    cost_price: FourPlaceDecimal | None = None
    quantity: FourPlaceDecimal | None = None
    amount: MoneyDecimal | None = None
    amount_mode: Literal["auto", "manual"] = "auto"
    fee: MoneyDecimal | None = None
    operated_at: datetime
    display_order: int = Field(strict=True, gt=0)
    note: str | None = Field(default=None, max_length=8000)
    action_matches: bool = True
    stock_matches: bool = True
    checklist_results: list[ChecklistResultBody] = Field(default_factory=list, max_length=1000)
    loss_status: Literal["yes", "no"] | None = None
    st_risk_status: Literal["yes", "no"] | None = None
    rule_checks: list[LedgerRuleCheckBody] = Field(default_factory=list, max_length=100)


class LedgerOmissionBody(StrictBody):
    kind: Literal["missed_buy", "missed_sell"]
    stock_code: str = Field(min_length=1, max_length=32)
    rule_id: str


class LedgerSubmitBody(StrictBody):
    trade_date: date
    request_id: str = Field(min_length=1, max_length=96)
    expected_account_revision: int = Field(strict=True, ge=0)
    expected_revision: int = Field(strict=True, ge=0)
    events: list[LedgerEventBody] = Field(default_factory=list, max_length=3000)
    omissions: list[LedgerOmissionBody] = Field(default_factory=list, max_length=3000)
    review_note: str | None = Field(default=None, max_length=8000)


class LedgerWithdrawBody(StrictBody):
    trade_date: date
    expected_account_revision: int = Field(strict=True, ge=0)


@router.get("/ledger", response_model=ApiResponse,
            dependencies=[Depends(require_perm(CHECKIN_VIEW))])
def ledger_context(trade_date: date) -> ApiResponse:
    return ok(_call(TradeLedgerService().context, trade_date))


@router.post("/ledger/initialize", response_model=ApiResponse,
             dependencies=[Depends(require_perm(CHECKIN_SUBMIT))])
def ledger_initialize(body: LedgerInitializeBody) -> ApiResponse:
    result = _call(TradeLedgerService().initialize, body.trade_date,
                   [p.model_dump() for p in body.positions], body.cash, body.expected_revision)
    _audit("ledger_initialize", "trade_discipline_account", "default", CHECKIN_SUBMIT)
    return ok(result, msg="期初持仓已初始化")


@router.post("/ledger/days", response_model=ApiResponse,
             dependencies=[Depends(require_perm(CHECKIN_SUBMIT))])
def ledger_submit(body: LedgerSubmitBody) -> ApiResponse:
    result = _call(TradeLedgerService().submit, body.trade_date, body.model_dump(exclude={"trade_date"}))
    _audit("ledger_submit", "trade_discipline_ledger_day", str(body.trade_date), CHECKIN_SUBMIT)
    return ok(result, msg="当日记录已保存")


@router.post("/ledger/preview", response_model=ApiResponse,
             dependencies=[Depends(require_perm(CHECKIN_SUBMIT))])
def ledger_preview(body: LedgerSubmitBody) -> ApiResponse:
    return ok(_call(TradeLedgerService().submit, body.trade_date,
                    body.model_dump(exclude={"trade_date"}), preview=True))


@router.post("/ledger/withdraw", response_model=ApiResponse,
             dependencies=[Depends(require_perm(CHECKIN_SUBMIT))])
def ledger_withdraw(body: LedgerWithdrawBody) -> ApiResponse:
    result = _call(TradeLedgerService().withdraw, body.trade_date, body.expected_account_revision)
    _audit("ledger_withdraw", "trade_discipline_ledger_day", str(body.trade_date), CHECKIN_SUBMIT)
    return ok(result, msg="已撤回最新日结，历史修订仍可追溯")


@router.get("/ledger/history", response_model=ApiResponse,
            dependencies=[Depends(require_perm(CHECKIN_VIEW))])
def ledger_history(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    assessment: Literal["complied", "partial", "breached", "pending"] | None = None,
    stock_code: str | None = Query(None, max_length=32), rule_id: str | None = None,
    date_from: date | None = None, date_to: date | None = None,
    sort_order: Literal["asc", "desc"] = "desc",
    include_withdrawn: bool = False,
) -> ApiResponse:
    if date_from and date_to and date_from > date_to:
        raise _ApiValidationError("开始日期不能晚于结束日期")
    return ok(TradeLedgerService().repo.history(
        limit=page_size, offset=(page - 1) * page_size, assessment=assessment,
        stock_code=stock_code, rule_id=rule_id, date_from=date_from, date_to=date_to,
        sort_order=sort_order, include_withdrawn=include_withdrawn,
    ))


@router.get("/ledger/revisions/{trade_date}/{revision_no}", response_model=ApiResponse,
            dependencies=[Depends(require_perm(CHECKIN_VIEW))])
def ledger_revision(trade_date: date, revision_no: int = Path(ge=1)) -> ApiResponse:
    return ok(_call(TradeLedgerService().revisions, trade_date, revision_no))


def _latest_market_date(service: TradeDisciplineService, *, required: bool) -> date | None:
    frame = service.market.query_df("SELECT max(trade_date) AS trade_date FROM daily_bar")
    value = None if frame.empty else frame.iloc[0]["trade_date"]
    if value is None or pd.isna(value):
        if required:
            raise _ApiValidationError("行情数据中没有可用交易日")
        return None
    return pd.Timestamp(value).date()


@router.get(
    "/summary",
    response_model=ApiResponse,
    dependencies=[Depends(require_perm(VIEW)), Depends(require_perm(CHECKIN_VIEW))],
)
def summary(trade_date: date | None = None) -> ApiResponse:
    service = _service()
    target_date = trade_date or _latest_market_date(service, required=True)
    return ok(_call(TradeLedgerService(market=service.market).summary, target_date))


@router.get("/rules", response_model=ApiResponse, dependencies=[Depends(require_perm(VIEW))])
def list_rules(trade_date: date | None = None) -> ApiResponse:
    service = _service()
    target_date = trade_date or _latest_market_date(service, required=False)
    return ok(_call(service.list_rules_with_state, target_date))


@router.get(
    "/rule-types", response_model=ApiResponse, dependencies=[Depends(require_perm(VIEW))]
)
def list_rule_types() -> ApiResponse:
    return ok(_call(_service().list_action_subtypes))


@router.delete(
    "/rule-types", response_model=ApiResponse, dependencies=[Depends(require_perm(RULE_MANAGE))]
)
def delete_rule_type(name: str = Query(min_length=1, max_length=64)) -> ApiResponse:
    result = _call(_service().delete_action_subtype, name)
    _audit("rule_type_delete", "trade_discipline_action_subtype", result["name"], RULE_MANAGE)
    return ok(result, msg="自定义买卖类型已删除")


@router.post(
    "/rules", response_model=ApiResponse, dependencies=[Depends(require_perm(RULE_MANAGE))]
)
def create_rule(body: RuleDraftBody | None = None) -> ApiResponse:
    result = _call(_service().create_rule, body.model_dump() if body else None)
    _audit("rule_create", "trade_discipline_rule", str(result["id"]), RULE_MANAGE)
    return ok(result, msg="规则已创建")


@router.get(
    "/rules/{rule_id}", response_model=ApiResponse, dependencies=[Depends(require_perm(VIEW))]
)
def get_rule(rule_id: str, trade_date: date | None = None) -> ApiResponse:
    service = _service()
    target_date = trade_date or _latest_market_date(service, required=False)
    return ok(_call(service.get_rule_with_state, rule_id, target_date))


@router.post(
    "/rules/{rule_id}/draft/open",
    response_model=ApiResponse,
    dependencies=[Depends(require_perm(RULE_MANAGE))],
)
def open_draft(rule_id: str) -> ApiResponse:
    result = _call(_service().open_draft, rule_id)
    _audit("draft_open", "trade_discipline_rule", rule_id, RULE_MANAGE)
    return ok(result, msg="草稿已就绪")


@router.put(
    "/rules/{rule_id}/draft",
    response_model=ApiResponse,
    dependencies=[Depends(require_perm(RULE_MANAGE))],
)
def save_draft(rule_id: str, body: SaveDraftBody) -> ApiResponse:
    payload = body.model_dump(exclude={"expected_revision"})
    result = _call(
        _service().save_draft,
        rule_id,
        payload,
        expected_revision=body.expected_revision,
    )
    _audit("draft_save", "trade_discipline_rule", rule_id, RULE_MANAGE)
    return ok(result, msg="草稿已保存")


@router.delete(
    "/rules/{rule_id}/draft",
    response_model=ApiResponse,
    dependencies=[Depends(require_perm(RULE_MANAGE))],
)
def discard_draft(rule_id: str) -> ApiResponse:
    result = _call(_service().discard_draft, rule_id)
    _audit("draft_discard", "trade_discipline_rule", rule_id, RULE_MANAGE)
    return ok(result, msg="草稿已放弃")


@router.post(
    "/rules/{rule_id}/publish",
    response_model=ApiResponse,
    dependencies=[Depends(require_perm(RULE_MANAGE))],
)
def publish_rule(rule_id: str, body: RevisionBody) -> ApiResponse:
    result = _call(
        _service().publish_rule,
        rule_id,
        expected_revision=body.expected_revision,
    )
    _audit("rule_publish", "trade_discipline_rule", rule_id, RULE_MANAGE)
    return ok(result, msg="规则已发布")


@router.post(
    "/rules/{rule_id}/archive",
    response_model=ApiResponse,
    dependencies=[Depends(require_perm(RULE_MANAGE))],
)
def archive_rule(rule_id: str) -> ApiResponse:
    result = _call(_service().archive_rule, rule_id)
    _audit("rule_archive", "trade_discipline_rule", rule_id, RULE_MANAGE)
    return ok(result, msg="归档动作已提交")


@router.post(
    "/rules/{rule_id}/restore",
    response_model=ApiResponse,
    dependencies=[Depends(require_perm(RULE_MANAGE))],
)
def restore_rule(rule_id: str) -> ApiResponse:
    result = _call(_service().restore_rule, rule_id)
    _audit("rule_restore", "trade_discipline_rule", rule_id, RULE_MANAGE)
    return ok(result, msg="恢复动作已提交")


@router.post(
    "/rules/{rule_id}/copy",
    response_model=ApiResponse,
    dependencies=[Depends(require_perm(RULE_MANAGE))],
)
def copy_rule(rule_id: str, body: CopyRuleBody) -> ApiResponse:
    result = _call(_service().copy_rule, rule_id, source=body.source)
    _audit("rule_copy", "trade_discipline_rule", str(result["id"]), RULE_MANAGE)
    return ok(result, msg="规则已复制")


@router.delete(
    "/rules/{rule_id}",
    response_model=ApiResponse,
    dependencies=[Depends(require_perm(RULE_MANAGE))],
)
def delete_rule(rule_id: str) -> ApiResponse:
    _call(_service().delete_rule, rule_id)
    _audit("rule_delete", "trade_discipline_rule", rule_id, RULE_MANAGE)
    return ok({"rule_id": rule_id}, msg="规则已删除")


@router.get(
    "/checkins/current",
    response_model=ApiResponse,
    dependencies=[Depends(require_perm(CHECKIN_VIEW))],
)
def current_checkin(rule_id: str, trade_date: date) -> ApiResponse:
    return ok(_call(_service().get_checkin_context, rule_id, trade_date))


@router.post(
    "/checkins",
    response_model=ApiResponse,
    dependencies=[Depends(require_perm(CHECKIN_SUBMIT))],
)
def submit_checkin(body: SubmitCheckinBody) -> ApiResponse:
    raise _ApiValidationError("填报已升级为统一账户日结，请刷新页面后提交")


@router.post(
    "/checkins/quick-no-operation",
    response_model=ApiResponse,
    dependencies=[Depends(require_perm(CHECKIN_SUBMIT))],
)
def quick_no_operation(body: QuickNoOperationBody) -> ApiResponse:
    result = _call(TradeLedgerService().quick_no_operation, body.rule_id, body.trade_date)
    _audit(
        "checkin_quick_no_operation",
        "trade_discipline_checkin",
        str(result["checkin_id"]),
        CHECKIN_SUBMIT,
    )
    message = "本规则在该交易日已完成打卡" if result.get("idempotent") else "已记录本规则无操作履约"
    return ok(result, msg=message)


@router.post(
    "/checkins/{checkin_id}/amendments",
    response_model=ApiResponse,
    dependencies=[Depends(require_perm(CHECKIN_SUBMIT))],
)
def amend_checkin(checkin_id: str, body: AmendCheckinBody) -> ApiResponse:
    raise _ApiValidationError("旧记录只读，请在账户日结中修正最新交易日")


@router.get(
    "/checkins",
    response_model=ApiResponse,
    dependencies=[Depends(require_perm(CHECKIN_VIEW))],
)
def list_checkins(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    date_from: date | None = None,
    date_to: date | None = None,
    rule_id: str | None = None,
    assessment: Literal["complied", "partial", "breached"] | None = None,
    no_operation: bool | None = None,
    amended: bool | None = None,
    stock: str | None = None,
    reason: str | None = None,
    sort_by: Literal["trade_date"] = "trade_date",
    sort_order: Literal["asc", "desc"] = "desc",
) -> ApiResponse:
    if date_from is not None and date_to is not None and date_from > date_to:
        raise _ApiValidationError("开始日期不能晚于结束日期")
    return ok(
        _call(
            _service().list_checkins,
            page=page,
            page_size=page_size,
            date_from=date_from,
            date_to=date_to,
            rule_id=rule_id,
            assessment=assessment,
            no_operation=no_operation,
            amended=amended,
            stock=stock,
            reason=reason,
            sort_by=sort_by,
            sort_order=sort_order,
        )
    )


@router.get(
    "/checkins/{checkin_id}/revisions/{revision_no}",
    response_model=ApiResponse,
    dependencies=[Depends(require_perm(CHECKIN_VIEW))],
)
def get_revision(checkin_id: str, revision_no: int = Path(ge=1)) -> ApiResponse:
    return ok(_call(_service().get_revision, checkin_id, revision_no))


@router.get(
    "/reasons", response_model=ApiResponse, dependencies=[Depends(require_perm(CHECKIN_VIEW))]
)
def list_reasons() -> ApiResponse:
    return ok(_call(_service().list_reasons))


@router.delete(
    "/reasons/{reason_id}",
    response_model=ApiResponse,
    dependencies=[Depends(require_perm(CHECKIN_SUBMIT))],
)
def delete_reason(reason_id: str) -> ApiResponse:
    _call(_service().delete_reason, reason_id)
    _audit("reason_delete", "trade_discipline_reason", reason_id, CHECKIN_SUBMIT)
    return ok({"reason_id": reason_id}, msg="原因已删除")


@router.get(
    "/stock-options",
    response_model=ApiResponse,
    dependencies=[Depends(require_any_perm(CHECKIN_VIEW, CHECKIN_SUBMIT))],
)
def stock_options(
    q: str = Query(min_length=1),
    limit: int = Query(20, ge=1, le=20),
    trade_date: date | None = None,
) -> ApiResponse:
    keyword = q.strip()
    if not keyword:
        raise _ApiValidationError("股票搜索关键词不能为空")
    escaped = keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"
    point_in_time = ""
    params: list[Any] = [pattern, pattern]
    if trade_date is not None:
        # stock_basic.delist_date 表示退出市场之日，项目点时口径不包含该日。
        point_in_time = (
            "AND (list_date IS NULL OR list_date <= ?) "
            "AND (delist_date IS NULL OR ? < delist_date) "
        )
        params.extend([trade_date, trade_date])
    params.extend([f"{escaped}%", f"{escaped}%", limit])
    frame = get_client().query_df(
        "SELECT code,name,board,industry,"
        "CAST(list_date AS VARCHAR) AS list_date,CAST(delist_date AS VARCHAR) AS delist_date "
        "FROM stock_basic "
        "WHERE (code ILIKE ? ESCAPE '\\' OR name ILIKE ? ESCAPE '\\') "
        f"{point_in_time}"
        "ORDER BY CASE WHEN code ILIKE ? ESCAPE '\\' THEN 0 "
        "WHEN name ILIKE ? ESCAPE '\\' THEN 1 ELSE 2 END,code "
        "LIMIT ?",
        params,
    )
    rows = frame.astype(object).where(pd.notna(frame), None).to_dict("records")
    market = get_client()
    point_date = trade_date
    if point_date is None:
        latest = market.query_df("SELECT max(trade_date) AS d FROM daily_bar").iloc[0]["d"]
        point_date = None if pd.isna(latest) else pd.Timestamp(latest).date()
    if rows and point_date is not None:
        try:
            statuses = StockSTStatusService(market).status_map(
                point_date, [str(row["code"]) for row in rows]
            )
        except STStatusNotReadyError:
            # 搜索选择器属于辅助入口，允许保留候选并把状态明确降级为未知。
            statuses = {}
        for row in rows:
            row["is_st"] = statuses.get(str(row["code"]))
            row["st_as_of_date"] = point_date.isoformat()
    else:
        for row in rows:
            row["is_st"] = None
            row["st_as_of_date"] = None
    return ok({"q": keyword, "limit": limit, "list": rows})
