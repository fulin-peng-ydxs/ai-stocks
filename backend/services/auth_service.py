"""认证服务编排（多租户 RBAC stage2·T4）。

对外能力：login / logout / refresh / register / me / 图形验证码 / 邮箱验证码 / 公开配置。
组合 jwt_tokens（签发/校验）+ security（密码）+ session_store（黑名单/计数/锁定/验证码/限流）
+ user_repository（PG）。安全策略读 settings.auth（阈值/开关可配）。

降级：黑名单/perm_ver 为鉴权关键，Redis 故障时由 session_store 异常上抛 → 上层 fail-closed。
邮箱验证码投递本阶段 **dev 日志打印**（生产须接 SMTP，见 plan §9）。
"""

from __future__ import annotations

import secrets
import time
import uuid

from backend.auth import session_store as ss
from backend.auth.jwt_tokens import (
    TOKEN_ACCESS,
    TOKEN_REFRESH,
    decode,
    issue_access,
    issue_refresh,
)
from backend.auth.security import check_strength, hash_password, verify_password
from backend.common.exceptions import AuthError, RateLimitError, ValidationError
from backend.common.logging import get_logger
from backend.config import get_settings
from backend.storage.user_repository import UserRepository

log = get_logger("services.auth")

_CAPTCHA_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # 去掉易混 O0I1L


class AuthService:
    def __init__(self, repo: UserRepository | None = None):
        self.repo = repo or UserRepository()
        self.cfg = get_settings().auth

    # ── 内部辅助 ──
    @staticmethod
    def _public_user(u: dict) -> dict:
        """对外用户视图（脱敏，无 password_hash）。"""
        return {
            "id": u["id"], "account": u["account"], "email": u.get("email"),
            "role": u["role_code"], "tenant_id": u["tenant_id"], "status": u["status"],
        }

    def _tokens_and_user(self, u: dict) -> dict:
        ss.cache_perm_ver(u["id"], int(u["perm_ver"]))
        return {
            "access_token": issue_access(u["id"], u["tenant_id"], u["role_code"], int(u["perm_ver"])),
            "refresh_token": issue_refresh(u["id"], u["tenant_id"], u["role_code"], int(u["perm_ver"])),
            "user": self._public_user(u),
        }

    @staticmethod
    def _remaining(claims: dict) -> int:
        return max(0, int(claims.get("exp", 0)) - int(time.time()))

    # ── 登录 / 登出 / 刷新 ──
    def login(self, account: str, password: str, *, ip: str = "unknown",
              captcha_id: str | None = None, captcha_code: str | None = None) -> dict:
        if not ss.rate_limit_ok("login", ip, self.cfg.login_rate_per_min, 60):
            raise RateLimitError("登录尝试过于频繁，请稍后再试")
        if ss.is_locked(account):
            raise AuthError(f"账号已锁定，请 {ss.lock_remaining(account) // 60 + 1} 分钟后重试")
        # 失败达阈值后要求图形验证码（开关控制，默认关）
        if (self.cfg.login_captcha_enabled
                and ss.login_failure_count(account) >= self.cfg.captcha_after_fails):
            if not (captcha_id and captcha_code and ss.take_captcha(captcha_id, captcha_code)):
                raise AuthError("请输入正确的图形验证码")

        user = self.repo.get_by_account(account)
        if user is None or not verify_password(password, user.get("password_hash")):
            self._note_failure(account)
            raise AuthError("账号或密码错误")   # 不区分账号是否存在，防枚举
        if user["status"] != "active":
            raise AuthError("账号已被禁用或锁定，请联系管理员")

        ss.clear_login_failures(account)
        self.repo.update_last_login(user["id"])
        return self._tokens_and_user(user)

    def _note_failure(self, account: str) -> None:
        n = ss.record_login_failure(account, self.cfg.fail_window_min * 60)
        if n >= self.cfg.max_login_fail:
            ss.lock_account(account, self.cfg.lock_minutes * 60)
            log.warning("账号 %s 登录失败 %d 次，锁定 %d 分钟", account, n, self.cfg.lock_minutes)

    def logout(self, access_token: str | None, refresh_token: str | None = None) -> None:
        """登出：把 access/refresh 的 jti 拉黑（剩余寿命内失效）。已过期/无效则跳过。"""
        for tok, typ in ((access_token, TOKEN_ACCESS), (refresh_token, TOKEN_REFRESH)):
            if not tok:
                continue
            try:
                c = decode(tok, expect_typ=typ)
                ss.revoke_jti(c["jti"], self._remaining(c))
            except AuthError:
                pass

    def refresh(self, refresh_token: str) -> dict:
        c = decode(refresh_token, expect_typ=TOKEN_REFRESH)
        if ss.is_jti_revoked(c["jti"]):
            raise AuthError("登录已失效，请重新登录")
        user = self.repo.get_by_id(c["sub"])
        if user is None or user["status"] != "active":
            raise AuthError("账号不可用，请重新登录")
        if int(user["perm_ver"]) != int(c["perm_ver"]):
            raise AuthError("权限已变更，请重新登录")
        ss.revoke_jti(c["jti"], self._remaining(c))   # 轮换：旧 refresh 作废
        return self._tokens_and_user(user)

    # ── 注册 ──
    def register(self, account: str, password: str, *, email: str | None = None,
                 email_code: str | None = None, ip: str = "unknown") -> dict:
        if not ss.rate_limit_ok("register", ip, self.cfg.register_rate_per_hour, 3600):
            raise RateLimitError("注册过于频繁，请稍后再试")
        if not account or not account.strip():
            raise ValidationError("请填写账号")
        check_strength(password, self.cfg.min_password_len)
        if self.cfg.require_email_code:
            if not email:
                raise ValidationError("请填写邮箱")
            if not (email_code and ss.verify_email_code(email, email_code)):
                raise ValidationError("邮箱验证码错误或已过期")
        if self.repo.get_by_account(account):
            raise ValidationError("账号已存在")
        if email and self.repo.get_by_email(email):
            raise ValidationError("邮箱已被注册")
        user = self.repo.register_tenant_and_admin(account, email, hash_password(password))
        return self._tokens_and_user(user)   # 自动登录

    # ── 当前身份 ──
    def claims_from_bearer(self, authorization: str | None) -> dict:
        """从 Authorization 头解出并校验 access token（含黑名单 + perm_ver）。

        本阶段供 /me 使用；T5 起由鉴权中间件统一执行并注入上下文。
        """
        if not authorization or not authorization.startswith("Bearer "):
            raise AuthError("未登录")
        claims = decode(authorization[7:], expect_typ=TOKEN_ACCESS)
        if ss.is_jti_revoked(claims["jti"]):
            raise AuthError("登录已失效，请重新登录")
        current = ss.get_cached_perm_ver(claims["sub"])
        if current is None:
            user = self.repo.get_by_id(claims["sub"])
            if user is None or user["status"] != "active":
                raise AuthError("账号不可用")
            current = int(user["perm_ver"])
            ss.cache_perm_ver(claims["sub"], current)
        if int(claims["perm_ver"]) != int(current):
            raise AuthError("权限已变更，请重新登录")
        return claims

    def me(self, user_id: str) -> dict:
        user = self.repo.get_by_id(user_id)
        if user is None:
            raise AuthError("用户不存在")
        # 固定响应契约（plan §4.7；供 T7 auth store 对接）：{user, tenant, role, menus, permissions}
        # 本阶段 menus/permissions 为空（前端仍用静态 menuConfig），阶段三填充。
        return {
            "user": {
                "id": user["id"], "account": user["account"],
                "email": user.get("email"), "status": user["status"],
            },
            "tenant": {"id": user["tenant_id"]},
            "role": user["role_code"],
            "menus": [],
            "permissions": [],
        }

    # ── 验证码 / 邮箱码 / 公开配置 ──
    def issue_captcha(self) -> dict:
        code = "".join(secrets.choice(_CAPTCHA_ALPHABET) for _ in range(4))
        cid = uuid.uuid4().hex
        ss.save_captcha(cid, code, self.cfg.captcha_ttl_min * 60)
        return {"captcha_id": cid, "svg": _render_captcha_svg(code)}

    def send_email_code(self, email: str, *, ip: str = "unknown") -> None:
        if not email:
            raise ValidationError("请填写邮箱")
        if not ss.rate_limit_ok("emailcode", email, self.cfg.email_code_rate_per_hour, 3600):
            raise RateLimitError("验证码发送过于频繁，请稍后再试")
        code = f"{secrets.randbelow(1_000_000):06d}"
        ss.save_email_code(email, code, self.cfg.email_code_ttl_min * 60)
        # dev 投递：生产须接真实 SMTP（plan §9）；此处仅日志，不回传前端
        log.warning("【开发态·邮箱验证码】%s -> %s（生产须接 SMTP 投递，勿公网放量）", email, code)

    def public_config(self) -> dict:
        """登录页公开配置（无需 token）：告诉前端是否要邮箱码/图形码 + 图形码触发阈值。

        下发 captcha_after_fails 让前端 UI 的图形码显示时机与后端 login() 的强制阈值一致
        （否则前端不知阈值只能失败一次即显示，与「失败达阈值后出现」的口径偏差）。
        """
        return {
            "require_email_code": self.cfg.require_email_code,
            "login_captcha_enabled": self.cfg.login_captcha_enabled,
            "captcha_after_fails": self.cfg.captcha_after_fails,
        }


def _render_captcha_svg(code: str) -> str:
    """极简 SVG 文本验证码（自包含，无第三方图像依赖；T6 可增强扰动）。"""
    texts = "".join(
        f'<text x="{10 + i * 22}" y="27" font-size="24" font-family="monospace" '
        f'fill="#2f81f7" transform="rotate({(-1) ** i * 6} {14 + i * 22} 20)">{c}</text>'
        for i, c in enumerate(code)
    )
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="104" height="40" '
        'viewBox="0 0 104 40">'
        '<rect width="104" height="40" fill="#eef4fb"/>' + texts + '</svg>'
    )
