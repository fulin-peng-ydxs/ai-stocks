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

# ── 阶段四资源码基线（stage4·R21，见 stage4-existing-routes/resource-codes.sql）────────────────
# baseline 登录基线共享读码（baseline_locked）：全站/研究基础共享读端点被多个页面或应用启动链路消费，
# **所有已认证非 system 业务用户（有 ≥1 角色）恒可用、角色页不可反选**——由 perm_resolver.resolve 对非
# system 用户强制并入（运行时权威），set_grants 保存时再强制并入（防线），二者互为兜底。无角色用户仍
# fail-closed（不注入）。挂 login 菜单锚点（不可挂 visible='system'，否则被 system_only_resource_ids 误判）。
SHARED_RESOURCE_CODES: tuple[str, ...] = (
    "layout:view",           # GET /api/layout/presets|pages/{k}|effective/{k}（全站布局生效读）
    "trade-calendar:view",   # GET /api/data/trade-dates（全站交易日历）
    "indicator:registry",    # GET /api/indicators/registry（Board/Screen/Config 跨页指标目录读）
)

# 可授权业务码：normal/paid/tenant_admin 默认授予的研究业务功能码（seed 首次写入 + 既有库一次性回填）。
# 不含 baseline（那是强制注入、非授权）与 system-only（挂 visible='system' 菜单，非 system 授不了）。
BUSINESS_RESOURCE_CODES: tuple[str, ...] = (
    "board:view", "board:compute", "score:run", "layout:user-config",
    "screen-profile:view", "screen-profile:save", "screen-profile:delete", "screen:run",
    "stocks:view", "stocks:trade-eval",
    "stock-group:view", "stock-group:create", "stock-group:update", "stock-group:delete",
    "stock-group:member-update",
    "backtest:view", "backtest:run", "backtest:robust", "backtest:delete",
    "training:view", "training:start", "training:trade", "training:review", "training:delete",
)
