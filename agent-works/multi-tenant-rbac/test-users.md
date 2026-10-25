# RBAC 测试用户维护清单

## 文档边界

本文维护本地开发/测试库的固定调试租户、账号、角色与权限场景及校准命令；生产或共享公网环境禁止创建这些账号。密码来源、变量文件与环境守卫由 [环境配置架构](../architecture/environment-configuration.md) 维护，权限模型由 [RBAC 架构](../architecture/system-rbac-tenant.md) 维护，E2E 夹具生命周期由 [执行指南](../e2e-automation/guide.md) 维护。

调试账号或权限场景变化时同步本文、`backend/devtools/rbac_test_users.py` 及相关测试；不在本文保存真实密码、运行凭据、测试结果，也不将固定账号变成 pytest 的外部依赖。

## AI 使用指引

- 页面或接口验收前，按 [环境身份与运行模式](../architecture/environment-configuration.md#环境身份与运行模式) 核查本机配置与运行档案；已确认本地开发时在 `.env.local` 持久化 `AI_STOCKS_ENV=dev`（单次命令也可显式设置 `dev|test|local`），再执行 `./start.sh dev-users --list` 查看固定调试账号；账号缺失、角色漂移或权限异常时，执行 `./start.sh dev-users` 重新校准。该入口与后端统一加载 `.env.local`，避免连到另一套 PG。
- 按测试场景选择最小权限账号：系统页用 system，租户管理用 tenant_admin，普通业务链路用 normal，权限边界用 board_only、stocks_only、stocks_group、backtest_view、trade_discipline_view、trade_discipline_submit。
- `admin` 是 README 中的本地开发系统管理员账号，归属 `default` 租户；密码来源和覆盖边界见 [environment-configuration.md](../architecture/environment-configuration.md)。它不属于本清单的 `debug_*` 调试账号，不用于替代最小权限或无权限场景。
- 不把固定调试账号作为 pytest 依赖；自动化后端用例继续在用例内创建临时用户。
- 不在生产、共享公网或不确定环境创建或使用这些账号，不把测试密码写入需求、计划、提交信息或测试结论。

## 与本地环境配置的关系

| 账号体系 | 代表账号 | 密码规则入口 | 用途 |
| --- | --- | --- | --- |
| 平台系统管理员 | `admin` | [environment-configuration.md](../architecture/environment-configuration.md) | 初始化、系统级运维、最高权限验收 |
| RBAC 调试用户 | `debug_*` | [environment-configuration.md](../architecture/environment-configuration.md) | 页面和接口权限验收 |

## 维护命令

```bash
AI_STOCKS_ENV=dev ./start.sh dev-users                 # 创建/校准全部调试用户
AI_STOCKS_ENV=dev ./start.sh dev-users --list          # 查看当前调试用户
AI_STOCKS_ENV=dev ./start.sh dev-users --keep-password
# 仅供已取得被测后端指纹的 E2E 自动入口；普通人工维护无需传入
AI_STOCKS_ENV=dev ./start.sh dev-users --keep-password --expected-pg-fingerprint <64位十六进制>
```

密码来源、默认回落和生产禁用规则见 [environment-configuration.md](../architecture/environment-configuration.md)。环境标记为空、未知、生产或共享公网时均拒绝写入。传入 `--expected-pg-fingerprint` 后，格式或目标不匹配会在 `init_pg_db()` 及任何账号写入前拒绝执行；自动化不得先校准账号、再校验被测后端目标。

## 固定租户

| 租户 ID | 用途 |
| --- | --- |
| `debug_tenant` | 非 system 调试用户统一租户，避免污染 `default/admin` 平台公共资产 |
| `default` | 仅 `debug_system` 使用，模拟平台系统管理员 |

## 固定用户

| 账号 | 租户 | 角色/权限 | 用途 | 预期可访问 |
| --- | --- | --- | --- | --- |
| `debug_system` | `default` | `system` | 系统管理员全量回归 | 全部系统页和业务页 |
| `debug_tenant_admin` | `debug_tenant` | `tenant_admin` | 租户管理员调试 | 业务页 + 用户管理 |
| `debug_normal` | `debug_tenant` | `normal` | 普通默认业务用户 | board/stocks/sectors/screen/backtest/training/trade-discipline |
| `debug_board_only` | `debug_tenant` | `debug_role_board_only`：`board:view` | 每日榜单最小权限 | 仅每日榜单 |
| `debug_stocks_only` | `debug_tenant` | `debug_role_stocks_only`：`stocks:view` | 个股页无分组权限回归 | 个股主体可用；不请求自选分组 |
| `debug_sectors_only` | `debug_tenant` | `debug_role_sectors_only`：`sectors:view`、`sector-watchlist:view`、`sector-watchlist:update` | 板块页无个股权限回归 | 板块列表、详情和自选可用；成分股不可跳个股 |
| `debug_stocks_group` | `debug_tenant` | `debug_role_stocks_group`：`stocks:view`、`stock-group:view`、`stock-group:member-update` | 个股页分组链路调试 | 个股 + 分组查看/成员维护 |
| `debug_backtest_view` | `debug_tenant` | `debug_role_backtest_view`：`backtest:view` | 回测历史只读调试 | 可看历史，不能运行/删除 |
| `debug_trade_discipline_view` | `debug_tenant` | `debug_role_trade_discipline_view`：`trade-discipline:view`、`trade-discipline:checkin-view` | 交易纪律只读边界 | 可看规则与履约历史，不能维护规则或提交打卡 |
| `debug_trade_discipline_submit` | `debug_tenant` | `debug_role_trade_discipline_submit`：`trade-discipline:view`、`trade-discipline:checkin-view`、`trade-discipline:checkin-submit` | R31 独立提交边界 | 可提交打卡和搜索候选股票；不能维护规则，且无 `stocks:view` |

## 维护规则

- 账号和自定义角色均为固定 ID，脚本幂等校准；手工改乱后重新执行命令即可恢复。
- 启动 seed 只为尚无任何 `sys_user_role` 的存量用户按遗留 `role_code` 补角色；已有自定义角色的最小权限账号不会被重新附加 `normal`。若 `--list` 发现漂移，先执行 `dev-users` 校准，再重启并复查。
- 自定义角色同时维护 `sys_role_menu` 和 `sys_role_resource`，保证菜单可进入、接口有权限。
- `layout:view`、`trade-calendar:view`、`indicator:registry` 不写入角色授权表，由 `perm_resolver` 对有角色的非 system 用户运行时注入。
- pytest 仍使用临时用户，不依赖这批固定调试账号。
