# RBAC 测试用户维护清单

> 仅用于本地开发/测试库的浏览器调试与权限验收。生产或共享公网环境禁止创建这些账号。

## AI 使用指引

- 页面或接口验收前，先执行 `python -m backend.cli dev-users --list` 查看固定调试账号；账号缺失、角色漂移或权限异常时，执行 `python -m backend.cli dev-users` 重新校准。
- 按测试场景选择最小权限账号：系统页用 system，租户管理用 tenant_admin，普通业务链路用 normal/paid，权限边界用 board_only、stocks_only、stocks_group、backtest_view。
- `admin` 是 README 中的本地开发系统管理员账号，归属 `default` 租户；密码来源和覆盖边界见 [environment-configuration.md](../architecture/environment-configuration.md)。它不属于本清单的 `debug_*` 调试账号，不用于替代最小权限或无权限场景。
- 不把固定调试账号作为 pytest 依赖；自动化后端用例继续在用例内创建临时用户。
- 不在生产、共享公网或不确定环境创建或使用这些账号，不把测试密码写入需求、计划、提交信息或测试结论。

## 与本地环境配置的关系

| 账号体系 | 代表账号 | 密码规则入口 | 用途 |
| --- | --- | --- | --- |
| 平台系统管理员 | `admin` | [environment-configuration.md](../architecture/environment-configuration.md) | 初始化、系统级运维、最高权限验收 |
| RBAC 调试用户 | `debug_*` | [environment-configuration.md](../architecture/environment-configuration.md) | 页面和接口权限验收 |

本文件只维护固定测试账号、角色和权限边界；变量文件、环境变量、生产禁用和密码生效规则统一维护在环境配置文档。

## 维护命令

```bash
python -m backend.cli dev-users              # 创建/校准全部调试用户，默认重置为统一密码
python -m backend.cli dev-users --list       # 查看当前调试用户
python -m backend.cli dev-users --keep-password
```

密码来源、默认回落和生产禁用规则见 [environment-configuration.md](../architecture/environment-configuration.md)。

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
| `debug_normal` | `debug_tenant` | `normal` | 普通默认业务用户 | board/stocks/screen/backtest/training |
| `debug_paid` | `debug_tenant` | `paid` | 付费角色默认授权验证 | 当前同 normal 默认业务授权 |
| `debug_board_only` | `debug_tenant` | `debug_role_board_only`：`board:view` | 每日榜单最小权限 | 仅每日榜单 |
| `debug_stocks_only` | `debug_tenant` | `debug_role_stocks_only`：`stocks:view` | 个股页无分组权限回归 | 个股主体可用；不请求自选分组 |
| `debug_stocks_group` | `debug_tenant` | `debug_role_stocks_group`：`stocks:view`、`stock-group:view`、`stock-group:member-update` | 个股页分组链路调试 | 个股 + 分组查看/成员维护 |
| `debug_backtest_view` | `debug_tenant` | `debug_role_backtest_view`：`backtest:view` | 回测历史只读调试 | 可看历史，不能运行/删除 |

## 维护规则

- 账号和自定义角色均为固定 ID，脚本幂等校准；手工改乱后重新执行命令即可恢复。
- 启动 seed 只为尚无任何 `sys_user_role` 的存量用户按遗留 `role_code` 补角色；已有自定义角色的最小权限账号不会被重新附加 `normal`。若 `--list` 发现漂移，先执行 `dev-users` 校准，再重启并复查。
- 自定义角色同时维护 `sys_role_menu` 和 `sys_role_resource`，保证菜单可进入、接口有权限。
- `layout:view`、`trade-calendar:view`、`indicator:registry` 不写入角色授权表，由 `perm_resolver` 对有角色的非 system 用户运行时注入。
- pytest 仍使用临时用户，不依赖这批固定调试账号。
