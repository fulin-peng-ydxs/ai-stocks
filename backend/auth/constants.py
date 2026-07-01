"""认证/鉴权常量（多租户 RBAC stage2·T1）。

角色码（role_code）本阶段为 sys_user 上的单列粗粒度身份；阶段三引入 sys_role 关联表后
1:1 迁移（system/tenant_admin/normal 直接对应内置角色，再补 paid）。
本模块**零依赖**，供 storage/auth/services 各层引用，避免散落硬编码字符串。
"""

from __future__ import annotations

# 内置角色码（与需求 6.1 sys_role.role_type 对齐；paid/plan_code/quota 阶段二不做）
ROLE_SYSTEM = "system"               # 平台系统管理员：可访问全市场写/平台配置类系统级接口
ROLE_TENANT_ADMIN = "tenant_admin"   # 租户管理员：自助注册用户默认角色，限本租户
ROLE_NORMAL = "normal"               # 普通用户：阶段三用户管理页才创建

BUILTIN_ROLES: tuple[str, ...] = (ROLE_SYSTEM, ROLE_TENANT_ADMIN, ROLE_NORMAL)
