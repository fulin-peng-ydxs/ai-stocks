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
ROLE_PAID = "paid"                   # 付费用户（阶段三预留：仅 seed 内置角色，无创建入口/配额）

# 内置系统预设角色（kind 同名）；自定义角色 kind='custom'、is_builtin=false
BUILTIN_ROLES: tuple[str, ...] = (ROLE_SYSTEM, ROLE_TENANT_ADMIN, ROLE_NORMAL, ROLE_PAID)

# 可分配给用户的系统预设角色（排除 system 超管；tenant_admin 用户管理页只在此集合内选）
ASSIGNABLE_PRESET_ROLES: tuple[str, ...] = (ROLE_TENANT_ADMIN, ROLE_NORMAL, ROLE_PAID)

# ── 登录基线资源码（stage4·R21 + config-storage-pg-migration T2）────────────────
# baseline 登录基线码（baseline_locked）：全站共享读端点、当前用户自持久化偏好端点被多个页面或应用启动链路消费，
# **所有已认证非 system 业务用户（有 ≥1 角色）恒可用、角色页不可反选**——**唯一权威**由
# perm_resolver.resolve 对非 system 用户运行时强制并入（见 perm_resolver.resolve）；**不落 role_resource
# 授权行、set_grants 有意不持久化 baseline**（保持 grants 表=显式授权、set/get 幂等，且无法被前端漏传/
# 直调绕过）。无角色用户仍 fail-closed（不注入）。挂 login 菜单锚点（不可挂 visible='system'，否则被
# system_only_resource_ids 误判）。
SHARED_RESOURCE_CODES: tuple[str, ...] = (
    "layout:view",           # GET /api/layout/presets|pages/{k}|effective/{k}（全站布局生效读）
    "layout:user-config",    # GET/POST /api/layout/users/{k}（当前用户页面布局/组件偏好）
    "user-preference:manage",  # GET/POST /api/user-preferences*（当前用户非布局偏好）
    "trade-calendar:view",   # GET /api/data/trade-dates（全站交易日历）
    "indicator:registry",    # GET /api/indicators/registry（Board/Screen/Config 跨页指标目录读）
    "dict:read",             # GET /api/dict/items/public（登录基线字典消费读；管理页仍 system-only）
)

# 可授权业务码：normal/paid/tenant_admin 默认授予的研究业务功能码（seed 首次写入 + 既有库一次性回填）。
# 不含 baseline（那是强制注入、非授权）与 system-only（挂 visible='system' 菜单，非 system 授不了）。
BUSINESS_RESOURCE_CODES: tuple[str, ...] = (
    "board:view", "board:compute", "score:run",
    "score-profile:view", "score-profile:save", "score-profile:delete",
    "trade-profile:view", "trade-profile:save", "trade-profile:delete", "trade-profile:preview",
    "screen-profile:view", "screen-profile:save", "screen-profile:delete", "screen:run",
    "stocks:view", "stocks:trade-eval",
    "stock-group:view", "stock-group:create", "stock-group:update", "stock-group:delete",
    "stock-group:member-update",
    "backtest:view", "backtest:run", "backtest:robust", "backtest:delete",
    "training:view", "training:start", "training:trade", "training:review", "training:delete",
)

# 阶段六资产公开权限码：tenant publish 默认给 tenant_admin/system，public publish 仅 system。
# 不放入 BUSINESS_RESOURCE_CODES，避免 normal/paid 在默认业务授权中获得发布能力。
ASSET_TENANT_PUBLISH_RESOURCE_CODES: tuple[str, ...] = (
    "score-profile:publish-tenant",
    "screen-profile:publish-tenant",
    "trade-profile:publish-tenant",
    "backtest:publish-tenant",
)

ASSET_PUBLIC_PUBLISH_RESOURCE_CODES: tuple[str, ...] = (
    "score-profile:publish-public",
    "screen-profile:publish-public",
    "trade-profile:publish-public",
    "backtest:publish-public",
)
