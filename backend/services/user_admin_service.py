"""用户管理编排（多租户 RBAC stage3·T5，R10）。

承接用户管理页：列表(域过滤)/新建/编辑(多角色)/启停锁定/重置密码/删除。守卫与业务规则集中在此，
api/users.py 只做参数校验与响应包装。

隔离与守卫（R9 + 阶段验收铁律）：
- **域过滤**：system 全局（可指定租户）；tenant_admin 仅限本租户，跨租户目标视为不存在(404)。
- **可分配角色**：只能分配 RoleRepository.assignable(调用者)——防 tenant_admin 越权授 system/自建角色。
- **自身保护**：不能停用/删除自己。
- **最后管理员保护**：不能停用/删除/降级掉租户内最后一个 tenant_admin。
- **失效即时生效**：改角色/停用/删除/重置密码 → bump_and_invalidate（perm_ver+1 + 清缓存）→
  被操作用户下次请求 401 重登（停用/删除者重登再被 status/存在性拒绝）。
"""

from __future__ import annotations

from backend.auth import perm_resolver
from backend.auth.constants import ROLE_TENANT_ADMIN
from backend.auth.context import AuthContext
from backend.auth.security import check_strength, hash_password
from backend.common.exceptions import ForbiddenError, NotFoundError, ValidationError
from backend.common.logging import get_logger
from backend.config import get_settings
from backend.storage.role_repository import RoleRepository
from backend.storage.user_repository import UserRepository

log = get_logger("services.user_admin")

_VALID_STATUS = {"active", "disabled", "locked"}


class UserAdminService:
    def __init__(self, users: UserRepository | None = None, roles: RoleRepository | None = None):
        self.users = users or UserRepository()
        self.roles = roles or RoleRepository()
        self.cfg = get_settings().auth

    # ── 列表 ──
    def list_users(self, ctx: AuthContext, *, tenant_id: str | None, role: str | None,
                   status: str | None, q: str | None, page: int, size: int) -> dict:
        scope_tenant = self._scope_tenant(ctx, tenant_id)
        return self.users.list_users(
            tenant_id=scope_tenant, role=role, status=status, q=q, page=page, size=size)

    # ── 新建 ──
    def create_user(self, ctx: AuthContext, *, account: str, password: str,
                    email: str | None, role_ids: list[str], status: str,
                    tenant_id: str | None) -> dict:
        account = (account or "").strip()
        if not account:
            raise ValidationError("请填写账号")
        self._check_status(status)
        check_strength(password, self.cfg.min_password_len)
        target_tenant = self._scope_tenant_for_write(ctx, tenant_id)
        role_code = self._validate_roles(ctx, role_ids)

        if self.users.get_by_account(account):
            raise ValidationError("账号已存在")
        if email and self.users.get_by_email(email):
            raise ValidationError("邮箱已被注册")

        uid = self.users.create_user(
            account=account, email=email, password_hash=hash_password(password),
            tenant_id=target_tenant, role_ids=role_ids, role_code=role_code, status=status)
        log.info("用户管理：新建用户 %s(%s) tenant=%s roles=%s", uid, account, target_tenant, role_ids)
        return self.users.get_admin_view(uid)  # type: ignore[return-value]

    # ── 编辑（多角色 + 资料 + 状态）──
    def update_user(self, ctx: AuthContext, user_id: str, *, email: str | None,
                    role_ids: list[str], status: str) -> dict:
        target = self._load_in_scope(ctx, user_id)
        self._check_status(status)
        role_code = self._validate_roles(ctx, role_ids)

        # 最后管理员保护：若从最后一个 tenant_admin 上摘掉该角色 / 停用，均阻止
        removing_admin = (ROLE_TENANT_ADMIN in (target["roles"] or [])
                          and ROLE_TENANT_ADMIN not in self._role_codes(role_ids))
        disabling = status != "active" and target["status"] == "active"
        if (removing_admin or disabling) and self._is_last_tenant_admin(target):
            raise ValidationError("该用户是本租户最后一个管理员，不能取消其管理员角色或停用")

        self.users.update_user(
            user_id, email=email, status=status, role_ids=role_ids, role_code=role_code)
        perm_resolver.bump_and_invalidate([user_id])   # 角色/状态变更 → 即时失效
        log.info("用户管理：编辑用户 %s roles=%s status=%s", user_id, role_ids, status)
        return self.users.get_admin_view(user_id)  # type: ignore[return-value]

    # ── 启停 / 锁定 ──
    def set_status(self, ctx: AuthContext, user_id: str, status: str) -> dict:
        self._check_status(status)
        target = self._load_in_scope(ctx, user_id)
        if user_id == ctx.user_id:
            raise ValidationError("不能变更自己的账号状态")
        if status != "active" and ROLE_TENANT_ADMIN in (target["roles"] or []) \
                and self._is_last_tenant_admin(target):
            raise ValidationError("该用户是本租户最后一个管理员，不能停用")
        self.users.set_status(user_id, status)
        perm_resolver.bump_and_invalidate([user_id])   # 停用即时失效：下次请求 401，重登被 status 拒
        log.info("用户管理：用户 %s 状态 → %s", user_id, status)
        return self.users.get_admin_view(user_id)  # type: ignore[return-value]

    # ── 重置密码 ──
    def reset_password(self, ctx: AuthContext, user_id: str, new_password: str) -> None:
        self._load_in_scope(ctx, user_id)
        check_strength(new_password, self.cfg.min_password_len)
        self.users.reset_password(user_id, hash_password(new_password))
        perm_resolver.bump_and_invalidate([user_id])   # 管理员改密 → 强制该用户旧会话失效重登
        log.info("用户管理：重置用户 %s 密码", user_id)

    # ── 删除 ──
    def delete_user(self, ctx: AuthContext, user_id: str) -> None:
        target = self._load_in_scope(ctx, user_id)
        if user_id == ctx.user_id:
            raise ValidationError("不能删除自己")
        if ROLE_TENANT_ADMIN in (target["roles"] or []) and self._is_last_tenant_admin(target):
            raise ValidationError("该用户是本租户最后一个管理员，不能删除")
        perm_resolver.bump_and_invalidate([user_id])   # 先清缓存，避免删后旧 token 借缓存 perm_ver 蒙混
        self.users.delete_user(user_id)
        log.info("用户管理：删除用户 %s", user_id)

    # ── 可分配角色（供前端下拉；endpoint 在 T6 挂 require_perm(user:list)）──
    def assignable_roles(self, ctx: AuthContext) -> list[dict]:
        return self.roles.assignable(is_system=ctx.is_system)

    # ── 内部：域范围 / 校验 ──
    def _scope_tenant(self, ctx: AuthContext, tenant_id: str | None) -> str | None:
        """列表域范围：system 用传入 tenant_id（None=全部）；tenant_admin 恒为本租户。"""
        return tenant_id if ctx.is_system else ctx.tenant_id

    def _scope_tenant_for_write(self, ctx: AuthContext, tenant_id: str | None) -> str:
        """新建归属租户：system 可指定（默认自身租户）；tenant_admin 恒本租户（忽略传入，防越权）。"""
        if not ctx.is_system:
            return ctx.tenant_id
        return tenant_id or ctx.tenant_id

    def _load_in_scope(self, ctx: AuthContext, user_id: str) -> dict:
        """取目标用户并做域校验；tenant_admin 跨租户目标一律视为不存在(404)，不泄露存在性。"""
        target = self.users.get_admin_view(user_id)
        if target is None:
            raise NotFoundError("用户不存在")
        if not ctx.is_system and target["tenant_id"] != ctx.tenant_id:
            raise NotFoundError("用户不存在")
        return target

    def _role_codes(self, role_ids: list[str]) -> set[str]:
        return {r["code"] for r in self.roles.get_by_ids(role_ids)}

    def _validate_roles(self, ctx: AuthContext, role_ids: list[str]) -> str:
        """校验角色非空、存在、均在调用者可分配集合内；返回兼容 role_code（首选 tenant_admin）。"""
        role_ids = list(dict.fromkeys(role_ids or []))
        if not role_ids:
            raise ValidationError("请至少选择一个角色")
        found = self.roles.get_by_ids(role_ids)
        if len(found) != len(role_ids):
            raise ValidationError("包含不存在的角色")
        allowed = {r["id"] for r in self.roles.assignable(is_system=ctx.is_system)}
        if not set(role_ids) <= allowed:
            raise ForbiddenError("包含当前身份不可分配的角色")
        codes = [r["code"] for r in found]
        return ROLE_TENANT_ADMIN if ROLE_TENANT_ADMIN in codes else codes[0]

    def _is_last_tenant_admin(self, target: dict) -> bool:
        """目标是否本租户唯一 tenant_admin（排除自身后再无其他）。"""
        others = self.users.count_tenant_admins(
            target["tenant_id"], exclude_user_id=target["id"])
        return others == 0

    @staticmethod
    def _check_status(status: str) -> None:
        if status not in _VALID_STATUS:
            raise ValidationError(f"无效的状态：{status}")
