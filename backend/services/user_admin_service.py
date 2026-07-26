"""用户管理编排（多租户 RBAC stage3·T5，R10）。

承接用户管理页：列表(域过滤)/新建/编辑(多角色)/启停锁定/重置密码/删除。守卫与业务规则集中在此，
api/users.py 只做参数校验与响应包装。

隔离与守卫（R9 + 阶段验收铁律）：
- **域过滤**：system 全局（可指定租户）；tenant_admin 仅限本租户，跨租户目标视为不存在(404)。
- **可分配角色**：系统管理员可分配全部角色；租户管理员只能分配租户级系统预设角色。
- **系统管理员保护**：租户管理员不能编辑、启停、重置密码或删除拥有 system 角色的用户。
- **自身保护**：不能停用/删除自己，系统管理员不能移除自己的 system 角色。
- **失效即时生效（Codex 五轮 P1，原子化）**：改角色/停用/重置密码 → **业务写入(conn) + `bump_perm_ver`
  在同一 PG 事务原子提交** → 提交后 `clear_perms_cache` best-effort。停用/删除者另由 `claims_from_bearer`
  每请求实时校验 status/存在性即时拒绝（不依赖 Redis）。删除无需 bump（get_by_id→None 即拒）。
"""

from __future__ import annotations

from backend.auth import perm_resolver
from backend.auth.constants import ROLE_SYSTEM, ROLE_TENANT_ADMIN
from backend.auth.context import AuthContext
from backend.auth.security import check_strength, hash_password
from backend.common.exceptions import ForbiddenError, NotFoundError, ValidationError
from backend.common.logging import get_logger
from backend.config import get_settings
from backend.services.asset_visibility import downgrade_owner_assets_to_private
from backend.storage.role_repository import RoleRepository
from backend.storage.tenant_repository import TenantRepository
from backend.storage.user_repository import UserRepository

log = get_logger("services.user_admin")

_VALID_STATUS = {"active", "disabled", "locked"}


class UserAdminService:
    def __init__(self, users: UserRepository | None = None, roles: RoleRepository | None = None,
                 tenants: TenantRepository | None = None):
        self.users = users or UserRepository()
        self.roles = roles or RoleRepository()
        self.tenants = tenants or TenantRepository()
        self.cfg = get_settings().auth

    # ── 列表 ──
    def list_users(self, ctx: AuthContext, *, tenant_id: str | None, role: str | None,
                   status: str | None, q: str | None, page: int, size: int,
                   sort_by: str, sort_order: str) -> dict:
        scope_tenant = self._scope_tenant(ctx, tenant_id)
        return self.users.list_users(
            tenant_id=scope_tenant, role=role, status=status, q=q, page=page, size=size,
            sort_by=sort_by, sort_order=sort_order)

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
        self._ensure_tenant_writable(target_tenant)   # P2-b：目标租户须存在且启用（防孤儿用户）
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
        if user_id == ctx.user_id and status != target["status"]:
            raise ValidationError("不能变更自己的账号状态")
        if user_id == ctx.user_id and ROLE_SYSTEM in target["roles"] and ROLE_SYSTEM not in role_ids:
            raise ValidationError("不能移除自己的系统管理员角色")
        role_code = self._validate_roles(ctx, role_ids)

        # 业务写入 + perm_ver 自增**同事务原子提交**（Codex 五轮 P1）→ 提交后 best-effort 清缓存。
        with self.users.pg.transaction() as conn:
            self.users.update_user(user_id, email=email, status=status, role_ids=role_ids,
                                   role_code=role_code, conn=conn)
            perm_resolver.bump_perm_ver([user_id], conn)
        perm_resolver.clear_perms_cache([user_id])
        log.info("用户管理：编辑用户 %s roles=%s status=%s", user_id, role_ids, status)
        return self.users.get_admin_view(user_id)  # type: ignore[return-value]

    # ── 启停 / 锁定 ──
    def set_status(self, ctx: AuthContext, user_id: str, status: str) -> dict:
        self._check_status(status)
        target = self._load_in_scope(ctx, user_id)
        if user_id == ctx.user_id:
            raise ValidationError("不能变更自己的账号状态")
        # 停用/启用 + perm_ver 自增同事务原子提交（Codex 五轮 P1）；停用另由 claims_from_bearer 每请求
        # 实时校验 status 即时生效（双保险）。提交后 best-effort 清缓存。
        with self.users.pg.transaction() as conn:
            self.users.set_status(user_id, status, conn=conn)
            perm_resolver.bump_perm_ver([user_id], conn)
            if status != "active":
                downgrade_owner_assets_to_private(
                    conn, tenant_id=target["tenant_id"], owner_user_id=user_id)
        perm_resolver.clear_perms_cache([user_id])
        log.info("用户管理：用户 %s 状态 → %s", user_id, status)
        return self.users.get_admin_view(user_id)  # type: ignore[return-value]

    # ── 重置密码 ──
    def reset_password(self, ctx: AuthContext, user_id: str, new_password: str) -> None:
        self._load_in_scope(ctx, user_id)
        check_strength(new_password, self.cfg.min_password_len)
        # 改密 + perm_ver 自增同事务原子提交（Codex 五轮 P1），作废旧会话；提交后 best-effort 清缓存。
        with self.users.pg.transaction() as conn:
            self.users.reset_password(user_id, hash_password(new_password), conn=conn)
            perm_resolver.bump_perm_ver([user_id], conn)
        perm_resolver.clear_perms_cache([user_id])
        log.info("用户管理：重置用户 %s 密码", user_id)

    # ── 删除 ──
    def delete_user(self, ctx: AuthContext, user_id: str) -> None:
        target = self._load_in_scope(ctx, user_id)
        if user_id == ctx.user_id:
            raise ValidationError("不能删除自己")
        # 逻辑删除 + 公开资产联动下线,同事务原子提交;删后旧 token 凭 claims_from_bearer 的 deleted_at 实时拒。
        with self.users.pg.transaction() as conn:
            self.users.delete_user(user_id, conn=conn)
            downgrade_owner_assets_to_private(
                conn, tenant_id=target["tenant_id"], owner_user_id=user_id)
        perm_resolver.clear_perms_cache([user_id])
        log.info("用户管理：逻辑删除用户 %s", user_id)

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
        """取目标用户并做域校验，再保护系统管理员不被租户管理员操作。"""
        target = self.users.get_admin_view(user_id)
        if target is None:
            raise NotFoundError("用户不存在")
        if not ctx.is_system and target["tenant_id"] != ctx.tenant_id:
            raise NotFoundError("用户不存在")
        if not ctx.is_system and ROLE_SYSTEM in target["roles"]:
            raise ForbiddenError("租户管理员不能操作系统管理员")
        return target

    def _validate_roles(self, ctx: AuthContext, role_ids: list[str]) -> str:
        """校验角色非空且可分配；按 system→tenant_admin→其它生成兼容 role_code。"""
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
        if ROLE_SYSTEM in codes:
            return ROLE_SYSTEM
        return ROLE_TENANT_ADMIN if ROLE_TENANT_ADMIN in codes else codes[0]

    def _ensure_tenant_writable(self, tenant_id: str) -> None:
        """建用户前校验目标租户存在且启用（P2-b：sys_user.tenant_id 无 FK，服务层硬校验防孤儿）。"""
        t = self.tenants.get(tenant_id)
        if t is None or t.get("deleted_at") is not None:
            raise ValidationError("目标租户不存在")
        if t["status"] != "active":
            raise ValidationError("目标租户已停用，不能在其下新建用户")

    @staticmethod
    def _check_status(status: str) -> None:
        if status not in _VALID_STATUS:
            raise ValidationError(f"无效的状态：{status}")
