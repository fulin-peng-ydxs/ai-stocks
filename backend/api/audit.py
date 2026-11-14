"""日志审计只读 API（阶段五 T4）。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from backend.api.response import ApiResponse, ok
from backend.auth.context import get_current_context
from backend.auth.deps import require_perm
from backend.common.exceptions import AuthError
from backend.services.audit_service import AuditService

router = APIRouter(prefix="/api/audit", tags=["audit"])


def _ctx():
    ctx = get_current_context()
    if ctx is None:
        raise AuthError("未登录")
    return ctx


@router.get("", response_model=ApiResponse, dependencies=[Depends(require_perm("audit:view"))])
def list_audit_logs(
    page: int = 1,
    page_size: int = 50,
    start_time: str | None = None,
    end_time: str | None = None,
    event_category: Annotated[list[str] | None, Query()] = None,
    event_type: Annotated[list[str] | None, Query()] = None,
    result: Annotated[list[str] | None, Query()] = None,
    status: Annotated[list[str] | None, Query()] = None,
    resource_code: str | None = None,
    actor_keyword: str | None = None,
    target_keyword: str | None = None,
    tenant_id: Annotated[list[str] | None, Query()] = None,
    sort_by: str = "event_time",
    sort_order: str = "desc",
) -> ApiResponse:
    return ok(AuditService().list_logs(
        _ctx(),
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_order=sort_order,
        start_time=start_time,
        end_time=end_time,
        event_category=event_category,
        event_type=event_type,
        result=result,
        status=status,
        resource_code=resource_code,
        actor_keyword=actor_keyword,
        target_keyword=target_keyword,
        tenant_id=tenant_id,
    ))


@router.get(
    "/summary",
    response_model=ApiResponse,
    dependencies=[Depends(require_perm("audit:view"))],
)
def audit_summary(
    start_time: str | None = None,
    end_time: str | None = None,
    event_category: Annotated[list[str] | None, Query()] = None,
    event_type: Annotated[list[str] | None, Query()] = None,
    result: Annotated[list[str] | None, Query()] = None,
    status: Annotated[list[str] | None, Query()] = None,
    resource_code: str | None = None,
    actor_keyword: str | None = None,
    target_keyword: str | None = None,
    tenant_id: Annotated[list[str] | None, Query()] = None,
) -> ApiResponse:
    return ok(AuditService().summary(
        _ctx(),
        start_time=start_time,
        end_time=end_time,
        event_category=event_category,
        event_type=event_type,
        result=result,
        status=status,
        resource_code=resource_code,
        actor_keyword=actor_keyword,
        target_keyword=target_keyword,
        tenant_id=tenant_id,
    ))


@router.get(
    "/{audit_id}",
    response_model=ApiResponse,
    dependencies=[Depends(require_perm("audit:view"))],
)
def audit_detail(audit_id: str) -> ApiResponse:
    return ok(AuditService().detail(_ctx(), audit_id))
