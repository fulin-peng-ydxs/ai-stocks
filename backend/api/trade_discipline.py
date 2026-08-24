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
from backend.services.trade_discipline_service import TradeDisciplineService
from backend.storage import get_client

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


class StockRuleBody(StrictBody):
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
    action_subtype: str | None = Field(default=None, max_length=40)
    content: str | None = None
    display_order: int = Field(ge=1)
    enabled: bool = True


class RuleDraftBody(StrictBody):
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
    id: str | None = None
    stock_code: str
    # 兼容旧客户端字段；保存时始终由服务端按 stock_code 解析权威名称。
    stock_name_snapshot: str | None = None
    side: Literal["buy", "sell"]
    stock_rule_id: str
    action_rule_id: str
    price: FourPlaceDecimal | None = None
    quantity: FourPlaceDecimal | None = None
    amount: MoneyDecimal | None = None
    fee: MoneyDecimal | None = None
    operated_at: datetime | None = None
    note: str | None = None
    display_order: int = Field(ge=1)


class CheckinContentBody(StrictBody):
    assessment: Literal["complied", "breached"]
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
    return ok(_call(service.summary, target_date))


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
def delete_rule_type(name: str = Query(min_length=1, max_length=40)) -> ApiResponse:
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
    payload = body.model_dump(exclude={"rule_id", "trade_date"})
    result = _call(_service().submit_checkin, body.rule_id, body.trade_date, payload)
    _audit("checkin_submit", "trade_discipline_checkin", str(result["checkin_id"]), CHECKIN_SUBMIT)
    return ok(result, msg="打卡已提交")


@router.post(
    "/checkins/quick-no-operation",
    response_model=ApiResponse,
    dependencies=[Depends(require_perm(CHECKIN_SUBMIT))],
)
def quick_no_operation(body: QuickNoOperationBody) -> ApiResponse:
    result = _call(_service().quick_no_operation, body.rule_id, body.trade_date)
    _audit(
        "checkin_quick_no_operation",
        "trade_discipline_checkin",
        str(result["checkin_id"]),
        CHECKIN_SUBMIT,
    )
    message = "该交易日已完成打卡" if result.get("idempotent") else "已记录无操作履约"
    return ok(result, msg=message)


@router.post(
    "/checkins/{checkin_id}/amendments",
    response_model=ApiResponse,
    dependencies=[Depends(require_perm(CHECKIN_SUBMIT))],
)
def amend_checkin(checkin_id: str, body: AmendCheckinBody) -> ApiResponse:
    payload = body.model_dump(exclude={"expected_revision"})
    result = _call(
        _service().amend_checkin,
        checkin_id,
        payload,
        expected_revision=body.expected_revision,
    )
    _audit("checkin_amend", "trade_discipline_checkin", checkin_id, CHECKIN_SUBMIT)
    return ok(result, msg="打卡已修正")


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
    assessment: Literal["complied", "breached"] | None = None,
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
    return ok({"q": keyword, "limit": limit, "list": rows})
