# RBAC 测试用户维护清单

> 仅用于本地开发/测试库的浏览器调试与权限验收。生产或共享公网环境禁止创建这些账号。

## AI 使用指引

- 页面或接口验收前，先执行 `python -m backend.cli dev-users --list` 查看固定调试账号；账号缺失、角色漂移或权限异常时，执行 `python -m backend.cli dev-users` 重新校准。
- 按测试场景选择最小权限账号：系统页用 system，租户管理用 tenant_admin，普通业务链路用 normal/paid，权限边界用 board_only、stocks_only、stocks_group、backtest_view。
- 不把固定调试账号作为 pytest 依赖；自动化后端用例继续在用例内创建临时用户。
- 不在生产、共享公网或不确定环境创建或使用这些账号，不把测试密码写入需求、计划、提交信息或测试结论。

## 维护命令

```bash
python -m backend.cli dev-users              # 创建/校准全部调试用户，默认重置为统一密码
python -m backend.cli dev-users --list       # 查看当前调试用户
python -m backend.cli dev-users --keep-password
```

密码来源：

- 优先读取环境变量 `AI_STOCKS_TEST_USER_PASSWORD`。
- 未设置时，本地开发默认回落 `Test@12345`。
- `AI_STOCKS_ENV=prod|production` 或 `ENV=prod|production` 时，命令拒绝执行。

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
- 自定义角色同时维护 `sys_role_menu` 和 `sys_role_resource`，保证菜单可进入、接口有权限。
- `layout:view`、`trade-calendar:view`、`indicator:registry` 不写入角色授权表，由 `perm_resolver` 对有角色的非 system 用户运行时注入。
- pytest 仍使用临时用户，不依赖这批固定调试账号。
