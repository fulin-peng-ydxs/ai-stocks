# 环境与配置加载

> 本文是环境变量、变量文件、YAML 基线配置和数据库配置覆盖层的唯一技术入口。其它 README、AI 协作入口和模块文档只保留链接，不重复加载细节。

## 核心技术

### 1. 配置来源分层

```mermaid
flowchart TD
  Shell["调用脚本前的 Shell 环境"] --> Start["./start.sh"]
  DotEnv[".env.local\n仅 start.sh 自动 source"] --> Start
  Start --> Proc["后端进程环境变量"]
  Proc --> Secret["敏感值/连接派生\nJWT、PG、Redis、admin seed"]
  Proc --> ConfigPath["AI_STOCKS_CONFIG\n可覆盖 YAML 路径"]
  ConfigPath --> YAML["config/settings.yaml\n非敏感基线"]
  YAML --> Raw["backend.config.settings._raw_yaml()"]
  Raw --> Cached["get_settings()\nYAML-only + lru_cache"]
  Raw --> Effective["get_effective_settings()\n每次重新合并"]
  PG["PostgreSQL app_config\n白名单覆盖层"] --> Effective
  Effective --> Runtime["运行期业务参数"]
```

| 层级 | 当前用途 | 代码入口 | 生效边界 |
|------|----------|----------|----------|
| Shell 环境变量 | 进程启动前注入的密钥、连接串、脚本开关 | `os.environ` | 已启动进程通常不会感知外部 shell 后续变化；测试可用 `monkeypatch` 改当前进程 |
| `.env.local` | 本机后端敏感变量模板的实际文件 | `start.sh` | 只由 `./start.sh` 自动读取；直接 `python -m backend.cli ...` 与 `./start-web.sh` 不自动读取 |
| `config/settings.yaml` | 非敏感默认值、路径、端口、运行参数基线 | `backend/config/settings.py` | `get_settings()` 缓存；改 YAML 后需 `/api/config/reload` 或重启刷新缓存 |
| PostgreSQL `app_config` | Web 系统设置白名单覆盖值 | `backend/storage/app_config.py` | `get_effective_settings()` 每次重合并，下一次读取即生效；PG 不可用时回落 YAML |
| PG 布局配置表 | 布局预设、页面默认、组件字段开放策略、页面布局/组件用户层 | `backend/storage/layout_config.py` | `default < preset < page < user` 合并；平台层和用户层均由 PG 承载 |
| PG 用户偏好表 | 主题、导航模式、页面业务偏好、K 线偏好、回测参数记忆、设置抽屉跨页面偏好 | `backend/storage/user_preference.py`、`/api/user-preferences` | 只保存当前登录用户自己的偏好；未登录或接口失败时前端使用本地 fallback |
| 方案/业务表 | 评分、买卖、筛选、定时任务等业务配置 | 各 repo/service | 不属于环境变量链路，按对应模块的版本和权限规则生效 |

### 2. 环境变量总表

| 变量 | 消费入口 | 用途 | 必填性与默认 | 生效时机 |
|------|----------|------|--------------|----------|
| `AI_STOCKS_CONFIG` | `backend/config/settings.py::_config_path()` | 覆盖 YAML 基线文件路径 | 可选；缺省为 `config/settings.yaml` | `get_settings()` 缓存后需 reload 或重启；`get_effective_settings()` 每次读原始 YAML |
| `AI_STOCKS_JWT_SECRET` | `Settings.jwt_secret()`、`backend/auth/jwt_tokens.py`、`backend/main.py` startup | JWT HS256 签名密钥 | 后端启动必填；无弱默认 | 启动自检会校验；已运行服务变更后需重启确保一致 |
| `AI_STOCKS_PG_DSN` | `Settings.pg_conninfo()` | PostgreSQL 完整连接串，优先级最高 | 可选；配置后覆盖 YAML 的 PG host/port/db/user 和 `AI_STOCKS_PG_PASSWORD` | 新建 `PostgresClient` 时读取；已创建连接池需重启或重建客户端 |
| `AI_STOCKS_PG_PASSWORD` | `Settings.pg_conninfo()` | PostgreSQL 密码，配合 YAML 连接参数 | 可选；本机 trust 可不填 | 新建 `PostgresClient` 时读取 |
| `AI_STOCKS_REDIS_URL` | `Settings.redis_url()` | Redis 完整 URL，优先级最高 | 可选；配置后覆盖 YAML 的 Redis host/port/db 和 `AI_STOCKS_REDIS_PASSWORD` | 新建 `RedisClient` 时读取；已创建客户端需重启或重建 |
| `AI_STOCKS_REDIS_PASSWORD` | `Settings.redis_url()` | Redis 密码，配合 YAML 连接参数 | 可选；无密码 Redis 可不填 | 新建 `RedisClient` 时读取 |
| `AI_STOCKS_SMTP_ENABLED` | `Settings.mail_config()` | 是否真实发送邮件（注册验证码等）；关闭时降级为 dev 日志、不真发 | 可选；覆盖 YAML `mail.enabled`（基线 false） | 每次 `get_effective_settings().mail_config()` 读取；改 `.env.local` 后需重启进程 |
| `AI_STOCKS_SMTP_USERNAME` | `Settings.mail_config()` | SMTP 登录账号/发信邮箱 | 真实发信必填；覆盖 YAML `mail.username`（基线留空） | 同上 |
| `AI_STOCKS_SMTP_SENDER` | `Settings.mail_config()` | From 显示地址；留空回落 `username` | 可选；覆盖 YAML `mail.sender` | 同上 |
| `AI_STOCKS_SMTP_PASSWORD` | `Settings.smtp_password()`、`backend/common/mailer.py` | SMTP 登录密码/授权码（Gmail 等用应用专用密码） | 真实发信必填；无弱默认 | 真实发信时读取 |
| `AI_STOCKS_ADMIN_PASSWORD` | `backend/storage/pg_ddl.py::seed_default_tenant()` | 首次 seed 或补齐 `admin` 密码哈希 | 生产/共享环境必须显式设置；缺失会随机生成并只在日志告警一次 | 仅在 `admin` 不存在或 `password_hash` 为空时使用；不会覆盖已有密码 |
| `AI_STOCKS_TEST_USER_PASSWORD` | `backend/devtools/rbac_test_users.py` | `debug_*` 本地调试账号统一密码 | 可选；本地开发未设置时回落测试默认值 | 执行 `python -m backend.cli dev-users` 创建/校准时读取 |
| `AI_STOCKS_ENV` / `ENV` | `backend/devtools/rbac_test_users.py` | 阻止在生产标记下创建调试账号 | 可选；值为 `prod` 或 `production` 时拒绝执行 | `dev-users` 命令运行时读取 |
| `AI_STOCKS_FILE_LOG` | `backend/common/logging.py` | 额外写 `logs/ai_stocks.log` | 可选；仅值为 `1` 时开启 | 首次配置 logger 时读取；默认只由 `start.sh` 汇总 stdout/stderr 到 `logs/backend.log` |
| `PYTHON` | `start.sh` | 选择后端启动脚本使用的 Python 可执行文件 | 可选；默认 `python` | 必须在调用 `./start.sh` 前的 shell 环境中设置；当前脚本在读取 `.env.local` 前确定该值 |
| `WEB_PORT` | `start-web.sh` | 选择 Vite dev server 端口 | 可选；默认 `5173` | 必须在调用 `./start-web.sh` 前的 shell 环境中设置；该脚本不读取 `.env.local` |

> 邮件 `mail.*` 采用「YAML 安全基线 + 环境变量覆盖」：`config/settings.yaml` 的 `mail` 段默认 `enabled=false`、账号留空（个人/部署账号不入仓库），真实开关与账号由上表 `AI_STOCKS_SMTP_*` 覆盖（`Settings.mail_config()` 叠加），密码只走 `AI_STOCKS_SMTP_PASSWORD`。另有 `server.trust_forwarded_for`（YAML，默认 `false`）控制是否信任 `X-Forwarded-For` 作为限流键 IP——直连公网时保持 false（用 socket 连接地址，防伪造头绕过 per-IP 限流），仅在可信反代会覆盖 XFF 时置 true。

前端代码没有项目自定义 `VITE_*` 运行配置。当前只使用 Vite 内置的 `import.meta.env.MODE` 和 `import.meta.env.DEV` 做测试/开发期分支；API 基址固定为同源 `/api`，开发期由 Vite proxy 转发到 `127.0.0.1:8000`。

后端 pytest 会在 `backend/tests/conftest.py` 模块导入期用 `os.environ.setdefault("AI_STOCKS_JWT_SECRET", "...")` 注入测试默认密钥，部分用例再用 `monkeypatch` 覆盖或删除环境变量。该默认值只服务测试进程，不代表应用运行有默认 JWT 密钥。

## 运维与开发说明书

### 1. 变量文件

| 文件 | Git 状态 | 自动加载者 | 职责 |
|------|----------|------------|------|
| `.env.local.example` | 跟踪 | 无 | 本机模板，只放变量名和示例注释，不放真实密钥 |
| `.env.local` | 忽略 | `./start.sh` | 本机后端启动变量，可写 `KEY=value` 或 `export KEY=value` |
| `.env` / `.env.*.local` | 忽略 | 当前脚本无自动读取 | 保留给人工或外部工具，项目脚本不依赖它们 |
| `config/settings.yaml` | 跟踪 | 后端配置模块 | 非敏感基线配置；敏感值不写入 |

`start.sh` 在项目根目录执行 `set -a; source .env.local; set +a`，因此 `.env.local` 里的变量会进入后端子进程环境。直接运行 Python CLI 时不会自动 source 该文件；如果 CLI 需要 JWT、PG 密码或 Redis 密码，调用前要确保当前 shell 已经具备这些环境变量。

### 2. YAML 基线与缓存

`get_settings()` 只负责 `config/settings.yaml` 基线读取和 Pydantic 校验，结果用 `lru_cache(maxsize=1)` 缓存。它不能访问数据库，因为 DuckDB/PG/Redis 客户端初始化会依赖 `get_settings()`，在这里合并数据库覆盖层会形成初始化环。

`reload_settings()` 只清 `get_settings()` 缓存并重读 YAML。`GET /api/config` 返回 YAML-only 的 `get_settings()` 结果；`POST /api/config/reload` 适用于人工修改 YAML 后刷新基线缓存，不负责写数据库覆盖层。

### 3. 生效配置与数据库覆盖层

运行期业务参数应优先调用 `get_effective_settings()`。它每次读取 YAML 原始 dict，再从 PostgreSQL `app_config` 读取白名单覆盖项，按点分路径深合并后重新校验为 `Settings`。

PostgreSQL `app_config` 是当前系统设置覆盖层的权威表：

| 字段 | 含义 |
|------|------|
| `key` | 点分路径，例如 `datasource.update_concurrency` |
| `value` | JSON 字符串，保留布尔、整数、浮点等类型 |
| `updated_at` | 覆盖值最后更新时间 |

写入口是 `AppConfigRepo.set_many()`，只接受 `CONFIG_GROUPS` 派生出的 `WHITELIST`，并逐项做类型、枚举和范围校验；任一项非法则整批拒绝。当前 Web 系统设置展示数据源、回测成本、认证与防滥用、审计设置四组；隐藏的 `scheduler.*` 只服务旧配置迁移。

同名的 DuckDB `app_config` 仍存在于旧 DDL 中，但不再作为运行期系统设置覆盖层。DuckDB 旧配置表只允许作为旧版本迁移读取源和回滚依据保留；新增运行期系统配置不要写 DuckDB `app_config`。

布局与用户偏好不走 `app_config`：

| 配置类型 | 权威表 | 说明 |
|----------|--------|------|
| 布局预设 | PostgreSQL `layout_preset` | 系统管理员维护的布局预设层 |
| 页面布局默认 | PostgreSQL `layout_page_config` | 单页面 page 层默认值 |
| 组件字段开放策略 | PostgreSQL `layout_field_policy` | 控制组件字段可开放到 preset/page/user 的策略 |
| 页面布局/组件用户层 | PostgreSQL `layout_user_config` | 只保存真实 pageKey 的布局与组件用户层；组件路径保存必须带真实 `PageLayout` 校验归属 |
| 非布局用户偏好 | PostgreSQL `user_preference` | 主题、导航、K 线、页面业务偏好、回测参数记忆等 |
| 设置抽屉跨页面偏好 | PostgreSQL `user_preference` | `scope='global'`、`pref_key='settings-drawer'`；用户层仅 `size/defaultCollapsed` |

### 4. 读取规则

| 场景 | 应使用 |
|------|--------|
| 启动期路径、DuckDB 文件、PG/Redis 连接参数、服务端口 | `get_settings()` + 环境变量派生方法 |
| 数据源限流/并发/超时、回测成本、认证开关/限流、审计保留期等运行期参数 | `get_effective_settings()` |
| 布局预设、页面默认和组件字段开放策略 | `LayoutConfigRepo` 读取 PG 布局配置表 |
| 页面布局/组件用户偏好 | `/api/layout/users/{pageKey}`，保存真实 pageKey 且组件路径带真实 `PageLayout` |
| 主题、导航模式、页面业务偏好、K 线偏好、回测参数记忆 | `/api/user-preferences` / `/api/user-preferences/bulk` |
| 评分方案、买卖方案、筛选方案 | 对应 profile/version 表，不走环境变量 |
| 定时任务定义 | `scheduled_job` 表，不再用 `scheduler.*` 作为运行态配置 |
| 调试账号密码 | `AI_STOCKS_TEST_USER_PASSWORD` 只在 dev-users 命令运行时读取 |

新增配置项时先判断它是敏感启动变量、非敏感 YAML 基线、Web 可改运行期参数、平台布局配置、用户自有偏好，还是业务资产配置。敏感值只放环境变量；可由系统管理员在线修改的运行期参数必须进入 `CONFIG_GROUPS` 白名单并落 PostgreSQL `app_config`；布局配置使用 PG 布局配置表；登录用户自有 UI/页面偏好使用 `user_preference`；方案类配置应进入对应业务表并保留版本/归属规则。

### 5. 前端 localStorage 边界

localStorage 不作为登录用户配置或偏好权威。在配置与偏好链路中，允许范围仅限：

| 用途 | 说明 |
|------|------|
| 登录态 token | 当前认证存储仍由 `frontend/src/api/authToken.ts` 管理，不属于本配置链路 |
| 登录前主题读取 | 首屏可先读本地主题，登录后以 `user_preference(global/theme)` 同步 |
| 离线/接口失败 fallback | 页面可继续使用旧本地值渲染，不能宣称云端已保存 |
| 旧偏好迁移源 | 登录后由前端迁移器一次性迁到 PG，并写迁移 marker |
| 临时交互态 | 例如抽屉本次打开期间的展开/收起状态，不进 PG |

`stockSet` 这类“当前股票集合/工作上下文”不是配置项，也不按用户偏好权威处理；如果后续要云端化，应按用户资产或工作集单独设计。

## 风险事项

| 等级 | 风险点 | 影响 | 建议 |
|------|--------|------|------|
| <span style="color:#dc2626">●</span> 高 | 直接运行 CLI 不加载 `.env.local` | CLI 可能缺 JWT/PG/Redis 环境变量，连接或认证相关命令失败 | 运行前在 shell 中注入变量，或通过服务脚本启动后端 |
| <span style="color:#dc2626">●</span> 高 | `AI_STOCKS_ADMIN_PASSWORD` 不覆盖已有密码 | 以为改变量即可改 admin 密码，但已有 `password_hash` 不会被 seed 覆盖 | 生产首部署前设置好；已有账号改密走系统功能或专门维护脚本 |
| <span style="color:#f59e0b">●</span> 中 | 连接客户端缓存了初始化时的 DSN/URL | 改 PG/Redis 环境变量后旧连接池仍使用旧连接信息 | 改连接类变量后重启服务 |
| <span style="color:#f59e0b">●</span> 中 | `get_settings()` 与 `get_effective_settings()` 用错 | Web 覆盖值不生效，或启动期初始化访问数据库形成依赖环 | 启动期用 `get_settings()`，运行期业务参数用 `get_effective_settings()` |
| <span style="color:#16a34a">●</span> 低 | PG `app_config` 不可用时静默回落 YAML | Web 改参看起来保存了，但读取时回退默认值 | 排查时同时看后端日志、PG 连接和 `/api/data/settings` 的 overridden 状态 |
