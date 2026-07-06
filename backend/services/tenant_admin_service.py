"""租户管理编排（多租户 RBAC stage3·T9，R14）。

承接租户管理页：列表 / 新建 / 编辑（含指定管理员）/ 启停。守卫（require_system）在 api 层，
业务规则与停用踢下线编排集中在此，api/tenants.py 只做参数校验与响应包装。

业务规则（阶段三铁律）：
- **名称唯一**：租户名全局唯一（撞现有拒）。
- **指定管理员须属该租户**：admin_user_id 指向的用户 tenant_id 必须等于本租户。
- **默认/平台租户保护**：default 租户不可删、不可停用（否则平台管理员自锁）。
- **删除前置**：仍有用户的租户不可删（先迁走/删用户）。
- **停用即时踢下线（Codex P2 + 五轮 P1，原子化）**：停用 → affected(租户成员)写前算定 → **写 status +
  成员 `bump_perm_ver` 同一 PG 事务原子提交** → 提交后 `clear_perms_cache` best-effort。三重保障：①登录/
  刷新被 `_ensure_tenant_active` 拒；②`claims_from_bearer` 每请求实时校验租户 status（不依赖 bump/Redis）；
  ③成员 perm_ver 原子自增使全部**在线** token 失配 → 401。
"""

from __future__ import annotations

from backend.auth import perm_resolver
from backend.common.exceptions import ForbiddenError, NotFoundError, ValidationError
from backend.common.logging import get_logger
from backend.storage.pg_ddl import DEFAULT_TENANT_ID
from backend.storage.tenant_repository import TenantRepository
from backend.storage.user_repository import UserRepository

log = get_logger("services.tenant_admin")

_VALID_STATUS = {"active", "disabled"}


class TenantAdminService:
    def __init__(self, tenants: TenantRepository | None = None,
                 users: UserRepository | None = None):
        self.tenants = tenants or TenantRepository()
        self.users = users or UserRepository()

    # ── 列表 ──
    def list_tenants(self, *, q: str | None, status: str | None, page: int, size: int,
                     sort_by: str, sort_order: str) -> dict:
        return self.tenants.list_all(
            q=q, status=status, page=page, size=size, sort_by=sort_by, sort_order=sort_order)

    # ── 新建 ──
    def create_tenant(self, *, name: str, status: str) -> dict:
        name = (name or "").strip()
        self._check_status(status)
        if not name:
            raise ValidationError("请填写租户名称")
        if self.tenants.get_by_name(name):
            raise ValidationError("租户名称已存在")
        tid = self.tenants.create(name=name, status=status)
        log.info("租户管理：新建租户 %s(%s)", tid, name)
        return self.tenants.get(tid)  # type: ignore[return-value]

    # ── 编辑（名称 + 指定管理员）──
    def update_tenant(self, tenant_id: str, *, name: str, admin_user_id: str | None) -> dict:
        self._load(tenant_id)
        name = (name or "").strip()
        if not name:
            raise ValidationError("请填写租户名称")
        other = self.tenants.get_by_name(name)
        if other and other["id"] != tenant_id:
            raise ValidationError("租户名称已存在")
        admin_user_id = (admin_user_id or "").strip() or None
        if admin_user_id:
            u = self.users.get_by_id(admin_user_id)
            if u is None or u["tenant_id"] != tenant_id:
                raise ValidationError("指定的管理员不属于该租户")
        self.tenants.update(tenant_id, name=name, admin_user_id=admin_user_id)
        log.info("租户管理：编辑租户 %s name=%s admin=%s", tenant_id, name, admin_user_id)
        return self.tenants.get(tenant_id)  # type: ignore[return-value]

    # ── 启停 ──
    def set_status(self, tenant_id: str, status: str) -> dict:
        self._check_status(status)
        cur = self._load(tenant_id)
        if tenant_id == DEFAULT_TENANT_ID and status != "active":
            raise ForbiddenError("默认租户不可停用")
        # 停用即时踢下线：affected 写前算定（成员不因状态变更而变）；停用 + 成员 perm_ver 自增**同事务
        # 原子提交**（Codex 五轮 P1）→ 提交后 best-effort 清缓存。停用另由 login/refresh 及每请求的
        # claims_from_bearer 实时校验租户 status 即时拒绝（三重保障）。
        if status != "active":
            affected = perm_resolver.affected_users_of_tenant(tenant_id)
            with self.tenants.pg.transaction() as conn:
                self.tenants.set_status(tenant_id, status, conn=conn)
                perm_resolver.bump_perm_ver(affected, conn)
            perm_resolver.clear_perms_cache(affected)
            log.info("租户管理：停用租户 %s，%d 个用户 token 失效（新登录亦被拒）", tenant_id, len(affected))
        else:
            self.tenants.set_status(tenant_id, status)
            log.info("租户管理：租户 %s 状态 → %s", tenant_id, status)
        return self.tenants.get(tenant_id)  # type: ignore[return-value]

    # ── 删除 ──
    def delete_tenant(self, tenant_id: str) -> None:
        self._load(tenant_id)
        if tenant_id == DEFAULT_TENANT_ID:
            raise ForbiddenError("默认租户不可删除")
        if self.tenants.user_count(tenant_id) > 0:
            raise ValidationError("该租户仍有用户，请先删除或迁移用户")
        self.tenants.delete(tenant_id)
        log.info("租户管理：删除租户 %s", tenant_id)

    # ── 内部 ──
    def _load(self, tenant_id: str) -> dict:
        t = self.tenants.get(tenant_id)
        if t is None:
            raise NotFoundError("租户不存在")
        return t

    @staticmethod
    def _check_status(status: str) -> None:
        if status not in _VALID_STATUS:
            raise ValidationError(f"无效的状态：{status}")
