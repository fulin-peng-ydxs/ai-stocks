"""认证接口（多租户 RBAC stage2·T4）：/api/auth/*，薄层——参数校验 + 调 AuthService + 响应包装。

白名单（无需 token）：login/register/refresh/captcha/send-email-code/public-config/oauth。
me 需有效 access token（本阶段自解析 Authorization；T5 起由中间件统一鉴权注上下文）。
"""

from __future__ import annotations

from fastapi import APIRouter, Header, Request
from pydantic import BaseModel

from backend.api.response import ApiResponse, ok
from backend.common.exceptions import ValidationError
from backend.services.auth_service import AuthService

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    account: str
    password: str
    captcha_id: str | None = None
    captcha_code: str | None = None


class RegisterIn(BaseModel):
    account: str
    password: str
    email: str | None = None
    email_code: str | None = None


class RefreshIn(BaseModel):
    refresh_token: str


class LogoutIn(BaseModel):
    refresh_token: str | None = None


class EmailCodeIn(BaseModel):
    email: str


def _client_ip(request: Request) -> str:
    """取客户端 IP：反代后优先 X-Forwarded-For 首段，否则连接地址。"""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _bearer(authorization: str | None) -> str | None:
    if authorization and authorization.startswith("Bearer "):
        return authorization[7:]
    return None


@router.post("/login", response_model=ApiResponse)
def login(body: LoginIn, request: Request) -> ApiResponse:
    data = AuthService().login(
        body.account, body.password, ip=_client_ip(request),
        captcha_id=body.captcha_id, captcha_code=body.captcha_code)
    return ok(data, msg="登录成功")


@router.post("/register", response_model=ApiResponse)
def register(body: RegisterIn, request: Request) -> ApiResponse:
    data = AuthService().register(
        body.account, body.password, email=body.email,
        email_code=body.email_code, ip=_client_ip(request))
    return ok(data, msg="注册成功")


@router.post("/refresh", response_model=ApiResponse)
def refresh(body: RefreshIn) -> ApiResponse:
    return ok(AuthService().refresh(body.refresh_token))


@router.post("/logout", response_model=ApiResponse)
def logout(body: LogoutIn, authorization: str | None = Header(default=None)) -> ApiResponse:
    AuthService().logout(_bearer(authorization), body.refresh_token)
    return ok(msg="已登出")


@router.get("/me", response_model=ApiResponse)
def me(authorization: str | None = Header(default=None)) -> ApiResponse:
    svc = AuthService()
    claims = svc.claims_from_bearer(authorization)
    return ok(svc.me(claims["sub"]))


@router.get("/captcha", response_model=ApiResponse)
def captcha() -> ApiResponse:
    return ok(AuthService().issue_captcha())


@router.post("/send-email-code", response_model=ApiResponse)
def send_email_code(body: EmailCodeIn, request: Request) -> ApiResponse:
    AuthService().send_email_code(body.email, ip=_client_ip(request))
    return ok(msg="验证码已发送")


@router.get("/public-config", response_model=ApiResponse)
def public_config() -> ApiResponse:
    return ok(AuthService().public_config())


@router.get("/oauth/{provider}", response_model=ApiResponse)
def oauth_placeholder(provider: str) -> ApiResponse:
    # R6 占位：第三方登录本期仅入口，不发起真实 OAuth
    raise ValidationError(f"第三方登录（{provider}）敬请期待")
