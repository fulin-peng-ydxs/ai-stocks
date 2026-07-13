# 邮箱认证 · 接入真实 SMTP 投递

> 本文只保留当前最终事实（已并入审查加固结论）。

## 背景

注册邮箱验证码此前只把验证码 `log.warning` 打到后端日志（`auth_service.send_email_code`），
前端却提示"请查收邮箱"，属于误导。验证码的生成 / Redis 存储 / 校验 / 限流 / 审计 / 前端交互
均已完备，唯一缺失的是真实邮件投递。本次补齐"发信"并收敛滥用面。

## 方案选型

- 发信用 Python 标准库 `smtplib` + `email.message`，**零新增依赖**。
- `send_email_code` 为同步 `def`（跑 FastAPI 线程池），`smtplib` 阻塞调用天然兼容，不引入 `aiosmtplib`。
- **配置分层**：`settings.yaml` 的 `mail` 段仅为**安全基线**（`enabled=false`、账号留空）；真实开关与账号
  走环境变量覆盖（对齐 JWT/PG/Redis 模式），个人/部署账号不入仓库：
  `AI_STOCKS_SMTP_ENABLED / _USERNAME / _SENDER / _PASSWORD`，由 `Settings.mail_config()` 叠加。
- `enabled=false` 时降级为 dev 日志（本地开发免配 SMTP），`true` 才真实投递。

## 最终改动清单

| 文件 | 改动 |
| --- | --- |
| `backend/config/settings.py` | 新增 `MailConfig`；`Settings` 加 `mail` 字段；`smtp_password()` 读 `AI_STOCKS_SMTP_PASSWORD`；`mail_config()` 用 `AI_STOCKS_SMTP_ENABLED/_USERNAME/_SENDER` 覆盖 YAML；`AuthConfig` 加 `email_code_ip_rate_per_hour` |
| `config/settings.yaml` | `mail` 段安全基线：`enabled: false`、`username/sender` 留空；`auth` 段加 `email_code_ip_rate_per_hour: 20` |
| `.env.local.example` | 新增 `AI_STOCKS_SMTP_ENABLED/_USERNAME/_SENDER/_PASSWORD` 说明 |
| `backend/common/mailer.py` | 新增 `send_email()` + `MailError`（code 5006）；按 `use_ssl` 选 `SMTP_SSL`(465)/`SMTP+starttls`(587)；读 `mail_config()`；enabled=false 降级 dev 日志；失败统一转译 MailError（不记密码） |
| `backend/auth/session_store.py` | 新增 `delete_email_code_if_match(email, code)`（Lua 原子 CAS 删除：仅当当前值仍是本次 code 才删，防并发误删他人新码） |
| `backend/services/auth_service.py` | `send_email_code`：邮箱规范化+格式校验 → per-email + per-IP 双限流 → **先存后发**（存码在前，发信失败作废码）；`register` 同口径规范化邮箱 |
| `backend/storage/app_config.py` | `auth` 组白名单新增 `email_code_ip_rate_per_hour`（int，1–500） |
| `frontend/src/api/client.ts` | 新增 `skipGlobalError`：登录页请求关闭全局 toast，错误经 `error.uiMessage` 回传 |
| `frontend/src/api/auth.ts` | login/register/sendEmailCode/getPublicConfig/getCaptcha 带 `skipGlobalError` |
| `frontend/src/views/LoginView.vue` | 字段级内联错误态、整体错误条、发码加载态（`emailSending`+spinner）、倒计时单定时器修复（在途锁 + 启动前清旧定时器） |

## 关键决策

- **先存后发**：`save_email_code`（`@_critical`，Redis 不可用抛 503）在发信前执行 → Redis 挂时根本不发信；
  发信 `MailError` 时 `delete_email_code_if_match(email, code)` 按值比较作废本次的码（Lua 原子 CAS，
  并发同邮箱时不误删他人已成功发出的新码；作废失败不掩盖 MailError）。保证「发出的验证码一定可验证」，
  且发信失败仍返回明确失败而非误报"已发送"。（`rate_limit_ok` 在校验阶段已计数，发信失败仍消耗当次配额——按既有限流语义保留。）
- **双维度限流**：per-email（防单目标轰炸，5/h）+ per-IP（防对海量不同邮箱各发几次，20/h）；email+IP 维度被二者共同覆盖，不单列。
- **邮箱规范化**：`_normalize_email`（strip+lower）+ `_EMAIL_RE` 格式校验，统一 send/verify/存储/限流键口径，堵大小写/空白绕过。
- **fail-open 说明**：`rate_limit_ok` 的 Redis 故障 fail-open 是既有设计（session_store §降级语义、plan §10.2：限流非安全闸，避免抖动锁死全站），**不改其语义**；「先存后发」已等效关闭「fail-open 后仍发信」窗口。
- **MailError 为软失败**（http 200 + code 5006），经 `main.py` `AIStocksError` 处理器统一出码；enabled=true 但 host/username/sender 或密码缺失时直接抛 MailError，不静默放行。
- **前端错误态**：登录/注册相关错误不走顶部全局 toast，改字段内联/整体错误条（DESIGN.md「error 不只依赖全局 toast」）。

## 配置项（运营）

- `auth.email_code_ip_rate_per_hour`（默认 20，范围 1–500）：单 IP 每小时验证码上限。事实源 `AuthConfig`；
  已入 `app_config` 白名单，系统设置页可调、支持 DB 覆盖，与同组限流项一致。
- 邮件开关与账号：`AI_STOCKS_SMTP_ENABLED=1` + `_USERNAME` + `_SENDER` + `_PASSWORD` 放 `.env.local`/部署环境，
  不写仓库。`settings.yaml` 的 `mail` 仅基线默认（关闭、留空）。

## 验证

- 后端 `pytest backend/tests/test_auth_service.py`：16 passed。
- 后端 `pytest backend/tests/test_stage5_config_t2.py`：passed（含新配置项白名单/生效/非法值/设置 API 断言）。
- 后端相邻域 `-k "auth or session or config or middleware or rate or mail"`：全部 passed；曾出现的唯一 FAILED
  （`test_layout_user_config_owner_from_context_not_request`）经隔离复跑确认为 **dev 后端占用 DuckDB 单写锁的环境并发问题**（停后端后 passed），与本改动无关。
- 前端全量 `vitest run`：273 passed；`vue-tsc -b` 无错。
- 浏览器 E2E（早期迭代）：注册页发码 → 收信 → 填码注册 → 自动登录，链路跑通。

## 业务闭环核查整改

- **注册失败不烧码**（confirmed）：`register` 改为验证码「只校验不消费」——门槛用 `check_email_code`（非消费），
  账号/邮箱已存在等失败都不消耗有效码；创建成功后才用 `delete_email_code_if_match` 一次性消费。
  防枚举顺序不变（无有效码不泄露账号/邮箱是否存在）。新增 `session_store.check_email_code`。
- **功能关闭即停用发码**（产品确认）：`send_email_code` 首行判 `require_email_code`，关闭时 fail-closed
  拒绝、不发信、不落码，避免公开接口在功能关闭时产生邮件成本。
- **已注册邮箱抑制发信**（产品确认）：发码在限流后查 `get_by_email`，已注册邮箱返回一致成功但不真发/不落码，
  防账号枚举 + 不骚扰既有用户。
- **per-IP 限流抗 XFF 伪造**（部署确认：可能直连）：新增 `server.trust_forwarded_for`（默认 false）。
  默认用不可伪造的 socket 连接地址作限流键；仅可信反代覆盖 XFF 时置 true 才取 XFF 首段。
  **全部三处客户端 IP 取值统一走此开关**：认证端点 `api/auth._client_ip`、全局 /api 限流中间件
  `middleware._scope_ip`、数据管理审计 `data_admin._client_ip`（后者为已认证系统管理员的审计留痕，非安全闸）。
- **`trust_forwarded_for` 定位为部署级配置，不入系统设置页**（判断无需改）：信任反代头是部署安全属性，
  应由部署人员在 YAML/环境控制；若放开为运行期页面可调，管理员误开即打开 XFF 伪造绕过面，风险更高。故不入 app_config 白名单。
- **测试**：新增注册失败保码/成功消费码、发码停用/已注册抑制、`_client_ip` 信任开关等用例。
- **待办（inferred/low，未实现，待产品/运维决定）**：SMTP 真实可用性对运维不可见（基线关闭 + 环境变量），
  建议在健康检查或系统设置暴露脱敏的邮件启用状态；未在本轮实现。

## 能力就绪可观测（已实现 · SMTP 样板）

治「开关开了但底层能力其实没配，验证码只写日志不真发」的哑巴故障：
- 后端 `/api/data/settings` 响应新增只读 `mail_status`（脱敏）：`enabled / username_masked / password_set / mode / ready`，
  来源为部署级环境变量 `AI_STOCKS_SMTP_*`，**不入 app_config 白名单、页面不可编辑**（仅暴露就绪度）。
- `mode` 精确对齐 `mailer.send_email` 真实分支，防提示漂移：`disabled`（enabled=false→只写 dev 日志不真发）/
  `incomplete`（enabled=true 但 host/username/sender/密码任一缺失→**发信抛 MailError、发码会失败**，非只写日志）/
  `ready`（齐全→真投递）。`ready` 判定含 host（与 mailer `host and username and sender and password` 同源）。
- 前端在「注册需邮箱验证码」开关下按 `mode` 渲染只读徽标：ready=绿点「真实发信已就绪（脱敏账号）」，
  incomplete=黄点「真实发信已开启但配置不完整，发码会失败」，disabled=黄点「未启用，验证码只写日志不真发」。
- 机制承载在 `ConfigGroupForm` 的 `fieldStatus?: Record<path, {tone,text}>` 通用 prop（按字段 path 挂就绪徽标）。
- 文件：`backend/api/data_admin.py`（`_mail_status`/`_mask_email` + 响应字段）、`frontend/src/api/data.ts`（`MailStatus`）、
  `frontend/src/views/ConfigView.vue`（`systemFieldStatus`）、`frontend/src/components/config/ConfigGroupForm.vue`（`fieldStatus` 渲染）。

## 后续可扩展：能力注册表 + 就绪探测（未实现，设计预留）

当前 `fieldStatus` + `mail_status` 是**单能力样板**。当出现第 2、第 3 个「运行期开关依赖部署级能力」的场景
（如短信验证码、第三方登录 OAuth、对象存储、推送通道）时，按同一模式推广为通用机制，避免每个能力各写一套：

- **能力注册表**（后端）：以 `capability_key`（如 `mail`/`sms`/`oauth.google`）为键，登记
  `{ready: bool, detail: 脱敏摘要, reason: 未就绪原因, probe: 探测方式}`；由各能力模块提供 `probe()`
  （读环境变量/配置存在性，必要时轻量连通测试），设置接口统一汇总为 `capabilities` 段下发。
- **开关↔能力映射**：在配置字段元信息（如 `CONFIG_GROUPS` 的字段）上声明 `requires_capability`，
  前端据此把对应就绪徽标挂到该开关下（复用现有 `fieldStatus` 机制），形成「开关 + 能力就绪」的稳定范式。
- **就绪探测分级**：轻量（配置/密钥是否存在，同步、无副作用，随设置接口返回）与
  重量（真实连通测试，如 SMTP 握手，按需触发、带缓存与超时），避免每次进设置页都打外部依赖。
- **边界**：能力就绪只读、不可运行期编辑（部署级安全属性保持在环境变量/YAML）；探测失败不阻断设置页主功能。

## 生产启用步骤

1. 邮箱后台开通 SMTP 并生成授权码（Gmail/QQ/企业邮用「应用专用密码」，非登录密码）。
2. `.env.local`（或部署环境变量）设：`AI_STOCKS_SMTP_ENABLED=1`、`AI_STOCKS_SMTP_USERNAME=<发信邮箱>`、
   `AI_STOCKS_SMTP_SENDER="<显示名> <发信邮箱>"`、`AI_STOCKS_SMTP_PASSWORD=<授权码>`；如非 Gmail 再在 `settings.yaml` 改 `host/port/use_ssl`。
3. 系统设置页按需开启 `auth.require_email_code`；重启后端。
4. 用测试邮箱注册，确认收信与验证码有效期（默认 10 分钟）。
