"""认证服务编排（多租户 RBAC stage2·T4）。

对外能力：login / logout / refresh / register / me / 图形验证码 / 邮箱验证码 / 公开配置。
组合 jwt_tokens（签发/校验）+ security（密码）+ session_store（黑名单/计数/锁定/验证码/限流）
+ user_repository（PG）。安全策略读 settings.auth（阈值/开关可配）。

降级：黑名单/perm_ver 为鉴权关键，Redis 故障时由 session_store 异常上抛 → 上层 fail-closed。
邮箱验证码经 backend.common.mailer 投递：mail.enabled=true 走真实 SMTP，false 时降级 dev 日志。
"""

from __future__ import annotations

import re
import secrets
import time
import uuid

from backend.auth import perm_resolver, session_store as ss
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
from backend.common.mailer import MailError, send_email
from backend.config import get_effective_settings
from backend.services.audit_service import AuditService
from backend.storage.menu_repository import MenuRepository
from backend.storage.tenant_repository import TenantRepository
from backend.storage.user_repository import UserRepository

log = get_logger("services.auth")

_CAPTCHA_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # 去掉易混 O0I1L
# 邮箱格式（宽松但可挡明显非法/注入）：本地部分@域名.顶级域，均不含空白/@。
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PUBLIC_APPEARANCE_TOKEN_RE = re.compile(
    r"^tokens\.(?:light|dark)\.(?:primary|success|warning|danger)$"
)


def _normalize_email(email: str | None) -> str:
    """规范化邮箱：去首尾空白 + 全小写。统一存储/校验/限流键口径，杜绝大小写或空白绕过。"""
    return (email or "").strip().lower()


class AuthService:
    def __init__(self, repo: UserRepository | None = None,
                 tenants: TenantRepository | None = None,
                 menus: MenuRepository | None = None):
        self.repo = repo or UserRepository()
        self.tenants = tenants or TenantRepository()
        self.menus = menus or MenuRepository()
        self.cfg = get_effective_settings().auth

    def _ensure_tenant_active(self, tenant_id: str) -> None:
        """租户停用即拒绝登录/刷新（T9·R14）：停用后新登录被拒，配合 bump 使在线 token 也失效。"""
        t = self.tenants.get(tenant_id)
        if t is not None and (t.get("deleted_at") is not None or t["status"] != "active"):
            raise AuthError("所属租户已停用，请联系平台管理员")

    # ── 内部辅助 ──
    @staticmethod
    def _public_user(u: dict) -> dict:
        """对外用户视图（脱敏，无 password_hash）。"""
        return {
            "id": u["id"], "account": u["account"], "email": u.get("email"),
            "role": u["role_code"], "tenant_id": u["tenant_id"], "status": u["status"],
        }

    def _tokens_and_user(self, u: dict) -> dict:
        # 不再预热 auth:pv 缓存：perm_ver 已改为每请求以 PG 为权威校验（claims_from_bearer），
        # 缓存该值会成为陈旧来源（Codex 四轮 P1）。
        return {
            "access_token": issue_access(u["id"], u["tenant_id"], int(u["perm_ver"])),
            "refresh_token": issue_refresh(u["id"], u["tenant_id"], int(u["perm_ver"])),
            "user": self._public_user(u),
        }

    def load_perms(self, user_id: str, *, perm_ver: int | None = None) -> dict:
        """取有效权限（缓存优先，缺失/过期实时解析并回填）。供中间件注入上下文 + /me 消费。

        **缓存按 perm_ver 校验（Codex 四轮 P1 整改）**：传入权威 perm_ver 时，仅当缓存内 perm_ver 与之
        一致才采信，否则重解析回填——防"失效后 perms 缓存清理失败或并发回填旧值"导致新令牌读到旧权限
        内容（menus/resources）。resolve() 返回的 dict 已含 perm_ver，作为缓存新鲜度标记。
        缓存故障 → session_store 抛 503（fail-closed，与中间件一致）。
        """
        perms = ss.get_cached_perms(user_id)
        stale = perm_ver is not None and (perms is None or int(perms.get("perm_ver", -1)) != int(perm_ver))
        if perms is None or stale:
            perms = perm_resolver.resolve(user_id)
            ss.cache_perms(user_id, perms, self.cfg.access_ttl_min * 60)
        return perms

    @staticmethod
    def _remaining(claims: dict) -> int:
        return max(0, int(claims.get("exp", 0)) - int(time.time()))

    # ── 登录 / 登出 / 刷新 ──
    def login(self, account: str, password: str, *, ip: str = "unknown",
              captcha_id: str | None = None, captcha_code: str | None = None) -> dict:
        if not ss.rate_limit_ok("login", ip, self.cfg.login_rate_per_min, 60):
            self._record_security(
                event_type="rate_limit",
                action="login",
                result="failed",
                status="blocked",
                actor_account=account,
                ip=ip,
                error_summary="登录尝试过于频繁",
                context={"rate_limit_rule": f"{self.cfg.login_rate_per_min}/min"},
            )
            raise RateLimitError("登录尝试过于频繁，请稍后再试")
        if ss.is_locked(account):
            self._record_security(
                event_type="login",
                action="login",
                result="failed",
                status="blocked",
                actor_account=account,
                ip=ip,
                error_summary="账号已锁定",
            )
            raise AuthError(f"账号已锁定，请 {ss.lock_remaining(account) // 60 + 1} 分钟后重试")
        # 图形验证码开关开启后：前端展示并提交时立即校验；失败达阈值后强制要求。
        captcha_submitted = bool(captcha_id or captcha_code)
        captcha_required = (
            self.cfg.login_captcha_enabled
            and (
                captcha_submitted
                or ss.login_failure_count(account) >= self.cfg.captcha_after_fails
            )
        )
        if captcha_required:
            if not (captcha_id and captcha_code and ss.take_captcha(captcha_id, captcha_code)):
                self._record_security(
                    event_type="captcha",
                    action="login_captcha_verify",
                    result="failed",
                    status="blocked",
                    actor_account=account,
                    ip=ip,
                    error_summary="登录图形验证码错误或缺失",
                )
                raise AuthError("请输入正确的图形验证码")

        user = self.repo.get_by_account(account)
        if user is None or not verify_password(password, user.get("password_hash")):
            self._note_failure(account)
            self._record_security(
                event_type="login",
                action="login",
                result="failed",
                status="failed",
                actor_account=account,
                ip=ip,
                error_summary="账号或密码错误",
            )
            raise AuthError("账号或密码错误")   # 不区分账号是否存在，防枚举
        if user.get("deleted_at") is not None or user["status"] != "active":
            self._record_security(
                event_type="login",
                action="login",
                result="failed",
                status="blocked",
                tenant_id=user["tenant_id"],
                actor_user_id=user["id"],
                actor_account=account,
                ip=ip,
                error_summary="账号状态不可用",
            )
            raise AuthError("账号已被禁用或锁定，请联系管理员")
        self._ensure_tenant_active(user["tenant_id"])   # 租户停用即拒登录（R14）

        ss.clear_login_failures(account)
        self.repo.update_last_login(user["id"])
        self._record_security(
            event_type="login",
            action="login",
            result="success",
            status="completed",
            tenant_id=user["tenant_id"],
            actor_user_id=user["id"],
            actor_account=account,
            ip=ip,
        )
        return self._tokens_and_user(user)

    def _note_failure(self, account: str) -> None:
        n = ss.record_login_failure(account, self.cfg.fail_window_min * 60)
        if n >= self.cfg.max_login_fail:
            ss.lock_account(account, self.cfg.lock_minutes * 60)
            log.warning("账号 %s 登录失败 %d 次，锁定 %d 分钟", account, n, self.cfg.lock_minutes)

    def logout(self, access_token: str | None, refresh_token: str | None = None) -> None:
        """登出：把 access/refresh 的 jti 拉黑（剩余寿命内失效）。已过期/无效则跳过。"""
        revoked = 0
        tenant_id = actor_user_id = None
        for tok, typ in ((access_token, TOKEN_ACCESS), (refresh_token, TOKEN_REFRESH)):
            if not tok:
                continue
            try:
                c = decode(tok, expect_typ=typ)
                ss.revoke_jti(c["jti"], self._remaining(c))
                revoked += 1
                tenant_id = tenant_id or c.get("tenant_id")
                actor_user_id = actor_user_id or c.get("sub")
            except AuthError:
                pass
        if revoked:
            self._record_security(
                event_type="token",
                action="logout_revoke",
                result="success",
                status="completed",
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                context={"affected_count": revoked},
            )

    def refresh(self, refresh_token: str) -> dict:
        c = decode(refresh_token, expect_typ=TOKEN_REFRESH)
        if ss.is_jti_revoked(c["jti"]):
            self._record_security(
                event_type="token",
                action="refresh",
                result="failed",
                status="blocked",
                tenant_id=c.get("tenant_id"),
                actor_user_id=c.get("sub"),
                error_summary="refresh token 已吊销",
            )
            raise AuthError("登录已失效，请重新登录")
        user = self.repo.get_by_id(c["sub"])
        if user is None or user.get("deleted_at") is not None or user["status"] != "active":
            self._record_security(
                event_type="token",
                action="refresh",
                result="failed",
                status="blocked",
                tenant_id=c.get("tenant_id"),
                actor_user_id=c.get("sub"),
                error_summary="账号不可用",
            )
            raise AuthError("账号不可用，请重新登录")
        self._ensure_tenant_active(user["tenant_id"])   # 租户停用即拒刷新（R14）
        if int(user["perm_ver"]) != int(c["perm_ver"]):
            self._record_security(
                event_type="token",
                action="refresh",
                result="failed",
                status="blocked",
                tenant_id=user["tenant_id"],
                actor_user_id=user["id"],
                error_summary="权限版本已变更",
            )
            raise AuthError("权限已变更，请重新登录")
        ss.revoke_jti(c["jti"], self._remaining(c))   # 轮换：旧 refresh 作废
        self._record_security(
            event_type="token",
            action="refresh_rotate",
            result="success",
            status="completed",
            tenant_id=user["tenant_id"],
            actor_user_id=user["id"],
            context={"affected_count": 1},
        )
        return self._tokens_and_user(user)

    # ── 注册 ──
    def register(self, account: str, password: str, *, email: str | None = None,
                 email_code: str | None = None, ip: str = "unknown") -> dict:
        if not ss.rate_limit_ok("register", ip, self.cfg.register_rate_per_hour, 3600):
            self._record_security(
                event_type="rate_limit",
                action="register",
                result="failed",
                status="blocked",
                actor_account=account,
                ip=ip,
                error_summary="注册过于频繁",
                context={"rate_limit_rule": f"{self.cfg.register_rate_per_hour}/hour"},
            )
            raise RateLimitError("注册过于频繁，请稍后再试")
        if not account or not account.strip():
            raise ValidationError("请填写账号")
        check_strength(password, self.cfg.min_password_len)
        # 邮箱规范化+校验：与 send_email_code 同口径，保证验证码键匹配、唯一性判定不被大小写绕过。
        if email:
            email = _normalize_email(email)
            if not _EMAIL_RE.match(email):
                raise ValidationError("邮箱格式不正确")
        # 验证码只校验不消费（check）：门槛不通过直接拒；其余校验（账号/邮箱已存在）失败都不烧码，
        # 直到创建成功后才一次性消费——避免「有效验证码被非最终失败原因消耗」的业务断点。
        # 校验放在账号/邮箱存在性判断之前，保持「无有效码不泄露账号/邮箱是否存在」的防枚举口径不变。
        if self.cfg.require_email_code:
            if not email:
                raise ValidationError("请填写邮箱")
            if not (email_code and ss.check_email_code(email, email_code)):
                self._record_security(
                    event_type="email_code",
                    action="register_email_code_verify",
                    result="failed",
                    status="blocked",
                    actor_account=account,
                    ip=ip,
                    error_summary="邮箱验证码错误或已过期",
                )
                raise ValidationError("邮箱验证码错误或已过期")
        if self.repo.get_by_account(account):
            raise ValidationError("账号已存在")
        if email and self.repo.get_by_email(email):
            raise ValidationError("邮箱已被注册")
        user = self.repo.register_tenant_and_admin(account, email, hash_password(password))
        # 创建成功后再消费验证码（一次性、按值比较）；消费失败不影响注册（码 10 分钟自然过期）。
        if self.cfg.require_email_code and email and email_code:
            try:
                ss.delete_email_code_if_match(email, email_code.strip())
            except Exception:  # noqa: BLE001
                log.warning("注册成功后消费验证码未成功 email=%s", email)
        self._record_security(
            event_type="register",
            action="register",
            result="success",
            status="completed",
            tenant_id=user["tenant_id"],
            actor_user_id=user["id"],
            actor_account=account,
            ip=ip,
        )
        return self._tokens_and_user(user)   # 自动登录

    # ── 当前身份 ──
    def claims_from_bearer(self, authorization: str | None) -> dict:
        """从 Authorization 头解出并校验 access token（签名/过期/黑名单/账号状态/perm_ver）。

        **perm_ver 与账号状态以 PG 为权威、每请求实时校验（Codex 四轮 P1 整改）**：不再信任 Redis 缓存的
        `auth:pv`。否则"权限失效后 Redis 清理失败或并发回填了旧值"会让旧 token 命中陈旧 perm_ver、绕过
        DB 状态检查存活到 TTL（stale-Redis fail-open）。改为每请求读 PG 单行（主键查询，开销极小），
        换取"停用/改权 → 下次请求即拒"的强一致。黑名单仍走 Redis(_critical)：Redis 不可用即 503
        fail-closed（token 吊销语义不可失），故 Redis 宕机不会因本改动而 fail-open。
        供 /me 与鉴权中间件共用（中间件据此注入上下文）。
        """
        if not authorization or not authorization.startswith("Bearer "):
            raise AuthError("未登录")
        claims = decode(authorization[7:], expect_typ=TOKEN_ACCESS)
        if ss.is_jti_revoked(claims["jti"]):   # 黑名单 fail-closed（Redis 挂 → 503）
            raise AuthError("登录已失效，请重新登录")
        user = self.repo.get_by_id(claims["sub"])   # 权威态：每请求查 PG（不采信可能陈旧的 auth:pv）
        if user is None or user.get("deleted_at") is not None or user["status"] != "active":
            raise AuthError("账号不可用")
        # 租户 status 亦每请求实时校验（Codex 五轮）：停租不再仅依赖 perm_ver bump 成功——即便 bump 因
        # 任何原因未前进，停租用户的在线 token 也被此处即时拒绝。
        tenant = self.tenants.get(user["tenant_id"])
        if tenant is not None and (tenant.get("deleted_at") is not None or tenant["status"] != "active"):
            raise AuthError("所属租户已停用，请联系平台管理员")
        if int(claims["perm_ver"]) != int(user["perm_ver"]):
            raise AuthError("权限已变更，请重新登录")
        return claims

    def me(self, user_id: str) -> dict:
        user = self.repo.get_by_id(user_id)
        if user is None:
            raise AuthError("用户不存在")
        # 固定响应契约：{user, tenant, role(兼容单码), roles(多角色), menus(过滤后菜单树), permissions(功能码)}。
        # menus 为按「角色授权 ∩ 可见性」双过滤后的嵌套树（T10），节点形状对齐前端 MenuNode
        # {index,title,icon,children}（叶子 index=route_path、分组 index=code），供 SideMenu 直接渲染；
        # permissions 为扁平功能码列表，供按钮级 v-permission 控制。
        perms = self.load_perms(user_id, perm_ver=int(user["perm_ver"]))   # 按权威 perm_ver 校验缓存
        return {
            "user": {
                "id": user["id"], "account": user["account"],
                "email": user.get("email"), "status": user["status"],
            },
            "tenant": {"id": user["tenant_id"]},
            "role": user["role_code"],
            "roles": perms["roles"],
            "menus": self._visible_menu_tree(perms),
            "permissions": perms["resources"],
        }

    def _visible_menu_tree(self, perms: dict) -> list[dict]:
        """按「角色授权 ∩ 可见性」双过滤构建菜单树（system 全量）。

        规则：① 非 system 用户，visible='system' 的节点及其整棵子树隐藏（系统专属分支）；
        ② 叶子仅当 system 或其 code 在授权集内才保留；③ 分组仅当仍有存活子节点才保留（剪空组）——
        故授权某叶子会自动带出其祖先分组，无需单独授权分组。
        """
        is_system = perms["is_system"]
        granted = set(perms["menus"])

        def walk(nodes: list[dict]) -> list[dict]:
            out: list[dict] = []
            for n in nodes:
                if not is_system and n["visible"] == "system":
                    continue                          # 系统专属分支对非 system 整体隐藏
                kids = walk(n.get("children", []))
                if n["type"] == "group":
                    if kids:                          # 剪掉过滤后为空的分组
                        out.append(self._menu_node(n, kids))
                elif is_system or n["code"] in granted:
                    out.append(self._menu_node(n, []))
            return out

        return walk(self.menus.tree())

    @staticmethod
    def _menu_node(n: dict, kids: list[dict]) -> dict:
        """映射为前端 MenuNode：叶子 index=route_path、分组 index=code；icon 为 EP 图标名。"""
        node: dict = {
            "index": n["route_path"] if n["type"] == "leaf" else n["code"],
            "title": n["title"], "icon": n["icon"],
        }
        if kids:
            node["children"] = kids
        return node

    # ── 验证码 / 邮箱码 / 公开配置 ──
    def issue_captcha(self) -> dict:
        code = "".join(secrets.choice(_CAPTCHA_ALPHABET) for _ in range(4))
        cid = uuid.uuid4().hex
        ss.save_captcha(cid, code, self.cfg.captcha_ttl_min * 60)
        self._record_security(
            event_type="captcha",
            action="issue_captcha",
            result="success",
            status="completed",
            target_type="captcha",
        )
        return {"captcha_id": cid, "svg": _render_captcha_svg(code)}

    def send_email_code(self, email: str, *, ip: str = "unknown") -> None:
        # 功能开关关闭即停用发码（fail-closed）：不真实发信、不落码，避免公开接口在功能关闭时
        # 仍产生邮件成本与外部投递。前端在 require_email_code=false 时本就隐藏入口，此为后端兜底。
        if not self.cfg.require_email_code:
            self._record_security(
                event_type="email_code",
                action="send_email_code",
                result="failed",
                status="blocked",
                ip=ip,
                target_type="email_code",
                error_summary="邮箱验证码功能未启用",
            )
            raise ValidationError("邮箱验证码功能未启用")
        email = _normalize_email(email)
        if not email:
            raise ValidationError("请填写邮箱")
        if not _EMAIL_RE.match(email):
            raise ValidationError("邮箱格式不正确")
        # 双维度限流：单邮箱（防对同一目标轰炸）+ 单 IP（防一个源对海量不同邮箱各发几次）。
        # email+IP 维度被这两者共同覆盖，不再单列（任一超限即拒）。任一 Redis 故障时 fail-open，
        # 但下方 save_email_code 为鉴权关键(@_critical)，Redis 不可用会在发信前 503 兜住。
        if not ss.rate_limit_ok("emailcode", email, self.cfg.email_code_rate_per_hour, 3600):
            self._record_security(
                event_type="rate_limit",
                action="send_email_code",
                result="failed",
                status="blocked",
                ip=ip,
                error_summary="验证码发送过于频繁",
                context={"rate_limit_rule": f"email:{self.cfg.email_code_rate_per_hour}/hour"},
            )
            raise RateLimitError("验证码发送过于频繁，请稍后再试")
        if not ss.rate_limit_ok("emailcode_ip", ip, self.cfg.email_code_ip_rate_per_hour, 3600):
            self._record_security(
                event_type="rate_limit",
                action="send_email_code",
                result="failed",
                status="blocked",
                ip=ip,
                error_summary="验证码发送过于频繁",
                context={"rate_limit_rule": f"ip:{self.cfg.email_code_ip_rate_per_hour}/hour"},
            )
            raise RateLimitError("验证码发送过于频繁，请稍后再试")
        # 防账号枚举 + 不骚扰既有用户：已注册邮箱返回与正常发送一致的成功，但不真实发信、不落码。
        # 置于限流之后，使已注册/未注册两条路径的可观察副作用（限流计数、响应）保持一致。
        if self.repo.get_by_email(email):
            self._record_security(
                event_type="email_code",
                action="send_email_code",
                result="success",
                status="completed",
                ip=ip,
                target_type="email_code",
                context={"suppressed": "email_registered"},
            )
            return
        code = f"{secrets.randbelow(1_000_000):06d}"
        ttl_min = self.cfg.email_code_ttl_min
        # 先存后发：save_email_code 是鉴权关键(@_critical)，Redis 不可用会在发信前抛 503，
        # 保证「发出去的验证码一定可验证」；发信失败再作废刚存的码（发信成功但存码失败的窗口被消除）。
        # mail.enabled=false 时 send_email 降级为 dev 日志（验证码见后端日志），不真正发信。
        ss.save_email_code(email, code, ttl_min * 60)
        try:
            send_email(
                email,
                "【复盘啦】注册验证码",
                f"您的验证码是 {code}，{ttl_min} 分钟内有效。请勿向他人泄露。\n"
                f"如非本人操作，请忽略本邮件。",
            )
        except MailError:
            # 发信失败即作废本次刚存的码，避免留下「可验证但用户没收到」的验证码。
            # 按值比较删除（仅当当前值仍是本次 code）：并发同邮箱时不会误删他人已成功发出的新码。
            # 作废失败不掩盖 MailError（残留码用户未收到，无法被利用，且 10 分钟后自然过期）。
            try:
                ss.delete_email_code_if_match(email, code)
            except Exception:  # noqa: BLE001
                log.warning("发信失败后作废验证码未成功 email=%s", email)
            self._record_security(
                event_type="email_code",
                action="send_email_code",
                result="failed",
                status="failed",
                ip=ip,
                target_type="email_code",
                error_summary="邮箱验证码投递失败",
            )
            raise
        self._record_security(
            event_type="email_code",
            action="send_email_code",
            result="success",
            status="completed",
            ip=ip,
            target_type="email_code",
        )

    def public_config(self) -> dict:
        """登录页公开配置（无需 token）：认证开关和登录前可消费的外观预设。

        前端在 login_captcha_enabled 开启后直接展示图形码；captcha_after_fails 仍作为
        后端强制要求图形码的失败次数兜底。外观预设只公开启用项的语义强调色，
        不下发页面、组件或其他平台布局配置。
        """
        appearance_presets: list[dict] = []
        try:
            # 延迟导入，避免认证服务初始化与布局存储形成模块级耦合。
            from backend.storage.layout_config import LayoutConfigRepo

            for preset in LayoutConfigRepo().list_presets():
                values = preset.get("config", {}).get("values", {})
                public_values = {
                    key: value
                    for key, value in values.items()
                    if _PUBLIC_APPEARANCE_TOKEN_RE.fullmatch(key)
                    and isinstance(value, (str, int, float, bool))
                }
                appearance_presets.append(
                    {
                        "key": preset["key"],
                        "name": preset["name"],
                        "description": preset.get("description", ""),
                        "config": {
                            "schemaVersion": preset.get("schemaVersion", 1),
                            "values": public_values,
                        },
                    }
                )
        except Exception as exc:  # noqa: BLE001
            # 外观目录不可用不能阻断登录；前端会继续使用内置预设或最近一次安全缓存。
            log.warning("登录页公开外观预设读取失败: %s", exc)
        return {
            "require_email_code": self.cfg.require_email_code,
            "login_captcha_enabled": self.cfg.login_captcha_enabled,
            "captcha_after_fails": self.cfg.captcha_after_fails,
            "appearance_presets": appearance_presets,
        }

    @staticmethod
    def _record_security(
        *,
        event_type: str,
        action: str,
        result: str,
        status: str,
        tenant_id: str | None = None,
        actor_user_id: str | None = None,
        actor_account: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        target_label: str | None = None,
        ip: str | None = None,
        error_summary: str | None = None,
        context: dict | None = None,
    ) -> None:
        AuditService().record_security_event(
            event_type=event_type,
            action=action,
            result=result,
            status=status,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            actor_account=actor_account,
            target_type=target_type,
            target_id=target_id,
            target_label=target_label,
            ip=ip,
            error_summary=error_summary,
            context=context,
        )


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
