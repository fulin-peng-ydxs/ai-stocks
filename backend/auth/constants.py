"""认证/鉴权常量。

`sys_user.role_code` 保留为登录响应兼容字段，角色与权限事实源是 `sys_user_role` 关联表。
本模块零依赖，供 storage/auth/services 各层引用，避免散落硬编码字符串。
"""

from __future__ import annotations

# 内置角色码
ROLE_SYSTEM = "system"               # 平台系统管理员：可访问全市场写/平台配置类系统级接口
ROLE_TENANT_ADMIN = "tenant_admin"   # 租户管理员：自助注册用户默认角色，限本租户
ROLE_NORMAL = "normal"               # 普通用户：阶段三用户管理页才创建

# 内置系统预设角色（kind 同名）；自定义角色 kind='custom'、is_builtin=false
BUILTIN_ROLES: tuple[str, ...] = (ROLE_SYSTEM, ROLE_TENANT_ADMIN, ROLE_NORMAL)

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

# 普通业务页面内仍仅允许平台系统管理员执行的操作。其余 system-only 资源可由归属菜单
# visible='system' 推导；这里补足不能靠错误菜单归属表达的例外。授权后端和权限树共同消费，
# 接口本身仍必须使用 require_system_perm 做不可降级硬守卫。
EXPLICIT_SYSTEM_ONLY_RESOURCE_CODES: tuple[str, ...] = (
    "limit-ladder:recompute",
)

# 可授权业务码：normal/tenant_admin 默认授予的研究业务功能码（seed 首次写入 + 既有库一次性回填）。
# 不含 baseline（那是强制注入、非授权）与 system-only（由系统菜单或显式集合锁定，非 system 授不了）。
BUSINESS_RESOURCE_CODES: tuple[str, ...] = (
    "board:view", "board:compute", "score:run",
    "limit-ladder:view",
    "score-profile:view", "score-profile:save", "score-profile:delete",
    "trade-profile:view", "trade-profile:save", "trade-profile:delete", "trade-profile:preview",
    "screen-profile:view", "screen-profile:save", "screen-profile:delete", "screen:run",
    "stocks:view", "stocks:trade-eval",
    "sectors:view",  # 板块行情列表/详情（板块概念 R22，T10a）
    "sector-watchlist:view", "sector-watchlist:update",
    "stock-group:view", "stock-group:create", "stock-group:update", "stock-group:delete",
    "stock-group:member-update",
    "backtest:view", "backtest:run", "backtest:robust", "backtest:delete",
    "training:view", "training:start", "training:trade", "training:review", "training:delete",
)

# 交易纪律默认授权由独立 marker 状态机维护，不能并入 BUSINESS_RESOURCE_CODES。
# 否则通用业务授权回填会在显式回滚后把菜单/资源权限重新补回，破坏 tombstone 语义。
TRADE_DISCIPLINE_RESOURCE_CODES: tuple[str, ...] = (
    "trade-discipline:view",
    "trade-discipline:rule-manage",
    "trade-discipline:checkin-view",
    "trade-discipline:checkin-submit",
)

# 后端分阶段先行交付、正式前端尚未接入的菜单。授权和 API 可先完成验证，但 /me 必须对所有角色
# 隐藏这些入口；对应页面的业务数据、关键交互、权限消费和浏览器回归形成完整闭环后才从此集合移除。
STAGED_FRONTEND_MENU_CODES: frozenset[str] = frozenset()

# 资产公开权限码（asset-ownership-refactor C4/R4）：放开普通用户自主发布——
# tenant/public publish 默认授予 normal 与 tenant_admin（system 恒有全量）。
# 守卫仍是 owner-only（api/*_profiles.py、api/backtest.py 的可见性接口只允许改自己的资产），
# 放开的是「能否发布」而非「能否改他人资产」。仍不并入 BUSINESS_RESOURCE_CODES（保持业务码与
# 发布码语义分栏），而是在 _seed_role_grants（新装）+ _backfill_asset_publish_open_v1（存量回填）显式授予。
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
