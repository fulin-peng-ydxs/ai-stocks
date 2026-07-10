# 平台与基础设施

> 横切所有业务模块的地基：FastAPI 全栈、混合持久层、点时安全仓库总闸门、异步任务底座、定时调度、配置覆盖层与前端布局/交互标准。

> 当前持久层边界：行情/参考数据留 DuckDB（只读分析），用户资产、系统菜单、角色权限和平台配置落 PostgreSQL，Redis 承载 token 黑名单、权限缓存、验证码和限流等短状态。系统菜单、权限和多租户技术架构见 [system-rbac-tenant.md](system-rbac-tenant.md)。

<span style="color:#2563eb">●</span> 服务运行　<span style="color:#7c3aed">●</span> 任务调度　<span style="color:#16a34a">●</span> 配置生效　<span style="color:#dc2626">●</span> 平台约束

## 核心技术

- **FastAPI 全栈**：后端 FastAPI（`backend/main.py:40` `create_app`）装配全部业务路由 + 静态托管 + 启动钩子（含三库连通性自检 `_check_storages`）；CLI（`backend/cli.py`）提供 `serve/health/backfill/update/daily/backtest/migrate-rbac` 等子命令，`serve` 内部即 `uvicorn.run("backend.main:app")`。**持久层**：行情 DuckDB + 资产/配置/RBAC PostgreSQL + 短状态 Redis；行情分析、任务编排和调度仍在本进程，用户资产和平台配置在 PG，Redis 承载限流和会话短状态。
- **DuckDB 单文件嵌入式库**：`backend/storage/duckdb_client.py` 封装单文件连接。连接惰性创建、模块级单例 `get_client()`（`:121`）。DuckDB 连接非线程安全，FastAPI 同步端点跑在线程池会并发触碰同一连接，故用一把可重入锁 `RLock`（`:43`）串行化所有 `execute/query_df`；本地查询毫秒级，串行无感。SQL 出错即把 `_conn` 置空，下次访问自动重建（`:64`/`:73`）。幂等写入靠进程内唯一名临时视图 `temp_view()`（`:91`）+ `INSERT ... SELECT`，离开作用域自动注销，避免固定视图名在共享连接下被并发覆盖。
- **点时安全仓库（总闸门）**：`backend/storage/repository.py` 的 `MarketRepository`。一是 `upsert()`（`:47`）按主键 `_PK`（`:22`）做 `ON CONFLICT DO UPDATE` 幂等写，重复运行不产生重复行。二是**防未来函数/防幸存者偏差总闸门**（`:103` 起）：`get_bars()`（`:108`）只返回 `trade_date <= end_date` 的行，复权用去抖因子列 `adj_factor_clean`（为空 `COALESCE` 回落 `adj_factor`），qfq 按 end_date 当日因子点时归一；`get_universe_asof()`（`:182`）以"当日有行情"为存活判据组装点时股票池，含当时存活后来退市的票，并叠加 ST/次新/停牌/一字板/流通市值/板块过滤。
- **异步任务底座**：`backend/services/async_task.py`。`TASK_TYPES`（`:28`）为 10 个原子任务类型；`WRITE_TASK_TYPES`（`:31`）为写库类型，全局只允许一个写任务在跑（单写者互斥）。`AsyncTaskService.create()`（`:164`）写 `async_task` 行后起守护线程跑处理器；`TaskContext`（`:58`）提供进度 `progress()`、节流批量实时日志 `log()`/`flush()`、断点 `set_checkpoint()`、协作式取消检查 `check_cancel()`。`_HANDLERS`（`:624`）按类型分派到各业务服务。
- **APScheduler 定时调度**：`backend/scheduler/scheduler.py`。定义持久化在 `scheduled_job` 表，`SCHEDULABLE_TASK_TYPES`（`:25`）限定可定时的类型。频率 `daily/weekly/monthly/cron` 经 `compile_trigger()`（`:65`）统一编译成 APScheduler `CronTrigger`，注册到进程内 `BackgroundScheduler` 单例（`:22`）。到点回调 `_fire_job()`（`:140`）读最新 job 定义→`trading_day_only` 判交易日→`create()` 创建 `async_task`（`trigger_source='scheduled'`）。
- **配置覆盖层即时生效**：基线 `config/settings.yaml` 经 Pydantic v2 模型校验（`backend/config/settings.py`），`get_settings()`（`:188`）`lru_cache` 单例只读 YAML。Web 表单改的参数落 `app_config` 表（点分路径→JSON，`backend/storage/app_config.py`，仅白名单 `WHITELIST`（`:64`）可改、逐项类型/范围校验）。`get_effective_settings()`（`backend/config/settings.py:199`）每次调用重新合并 `YAML ⊕ 覆盖层`（不缓存），故改参即时生效，DB 不可用时静默回落 YAML。
- **dev/prod 部署**：`start.sh` 用 `nohup` 脱离会话启动 `backend.cli serve`，防误杀。dev 模式 `--reload`（改 `backend/*.py` 热重启 worker）+ 绑 `127.0.0.1`（仅本机，外部走前端 5173 代理）；prod 无热重载、绑 `0.0.0.0` 对外托管。生产期 `frontend/dist` 由 FastAPI `StaticFiles` 同源托管，SPA 深链/刷新回退 `index.html`（`backend/main.py:80-96`）。
- **前端布局自适应 + 列表交互标准**：Vue 3 + Element Plus + Pinia + vue-router（history 模式）。布局走可配置布局系统（`frontend/src/layout/`，地图见根目录 `DESIGN.md`）：页面声明 `PageLayout` schema 交 `<LayoutHost>` 渲染，整页/视口永不滚动、超高内容由页内"成长区"内部消化；契约样式 `.v-page/.v-grow/.v-scroll` 落在 `frontend/src/styles/global.css`，外壳 `App.vue` 的 `.main` 已 `overflow:hidden`+flex 填充。约束由校验器 + `layout-contract.spec.ts` 机制性强制。列表交互走服务端分页/排序/筛选、筛选变更自动触发、多选跨页累积。

## 业务架构

- **共用单例与初始化**：所有需要读写库的服务（仓库、异步任务、调度、配置、各业务服务）都经 `get_client()` 拿同一个 DuckDB 连接单例；`AsyncTaskService`/`ScheduledJobService`/`AppConfigRepo` 构造时调 `init_db()`（`backend/storage/ddl.py:645`）幂等建表，保证任意入口先碰到的服务都能把表建好。`init_db` 一次性创建 M1/M2/M3/M5/M6/M28 全部表 + 序列，并跑 `_MIGRATIONS`（`backend/storage/ddl.py:581`）轻量补列/清理旧表，再 seed 数据维度注册表。

- **表与目录分工**：
  - 基础设施自有表：`async_task`（任务状态/进度/结果/来源标记）、`task_log`（实时日志，按 `seq` 增量拉、每任务保留最近 2000 条）、`scheduled_job`（定时任务定义）、`app_config`（配置覆盖层，点分路径→JSON）、`data_update_log`（采集留痕）、`data_dimension_registry`/`data_source_provenance`（数据维度与溯源）。
  - 业务表（行情/方案/结果/回测/快照）由各业务模块拥有，但**统一经 `MarketRepository.upsert` 与点时查询闸门读写**，主键登记在 `repository._PK`。
  - 数据字典文档化：`backend/storage/catalog.py` 用代码内置 `TABLE_CATALOG` 维护表/字段中文说明，运行时 `build_catalog()` 拼上行数/最新数据时间/未解决质检数，供数据概览页渲染——不另建需手维护的字典表。
  - 目录约定：DuckDB 单文件、parquet、导出、日志路径在 `PathsConfig`（`backend/config/settings.py:31`），相对路径按项目根 `PROJECT_ROOT` 解析为绝对路径。

- **被上层共用的能力**：点时闸门被选股/打分/回测/个股查询统一调用，保证全系统同一套"防未来/防幸存者"口径；异步任务底座被数据采集/补数/重算/质检/修复/基础信息刷新复用同一套执行/日志/续跑/取消语义；定时调度只是任务底座的触发器（到点→`create` 一条 `async_task`），与手动任务同一执行通道；配置覆盖层被数据源限流/并发、股票池过滤、回测成本、TopN 等读取点共用。

- **网络模型**：对外只暴露前端入口端口（dev 期前端 5173，经 Vite 代理到后端 8000；prod 期后端 8000 同源托管 `frontend/dist`）。后端 dev 绑 `127.0.0.1` 仅本机，CORS 仅放行 `localhost:5173/127.0.0.1:5173`（`backend/main.py:48`）。API 入口启用 JWT 鉴权、默认拒绝和租户归属上下文。

- **前端壳与路由**：`App.vue` 固定左侧菜单 + 顶栏 + `router-view` 内容区；菜单含个股查询/每日榜单/策略筛选/策略回测/配置管理/数据管理（含数据概览/质量/采集/任务调度四子页）。路由表 `frontend/src/router/index.ts` 懒加载各视图，`/` 重定向 `/board`，已下线页用重定向兜旧链接。`stockSet.ts` 这类 Pinia store 用 localStorage 持久化"当前集合"，支撑列表→详情的上一个/下一个跨页导航。

## 运维与开发说明书

平台层说明的是"系统如何跑起来、如何保持一致、哪里不能乱动"。

### 1. 服务运行模式

| 模式 | 命令 | 端口 | 适用场景 |
|------|------|------|----------|
| 开发后端 | `./start.sh` 或 `./start.sh dev` | `127.0.0.1:8000` | 后端热重载，配合前端 Vite |
| 开发前端 | `./start-web.sh` | `0.0.0.0:5173` | 前端 HMR，代理 `/api` 到后端 |
| 自动化验证 | `npm run dev -- --port 5181 --strictPort` | `5181` | AI 截图/交互核查专用，不占用日常 5173 |
| 生产/集成 | `npm run build` 后 `./start.sh prod` | `0.0.0.0:8000` | 后端托管 `frontend/dist` |

开发期浏览器访问 `5173`，生产/集成期访问 `8000`。系统已启用登录鉴权，但邮箱码仍走 dev 日志投递（非真实 SMTP），公网放量前须先接 SMTP，暂不建议把 `prod` 端口直接暴露公网。

自动化验证（AI 用 preview 做截图/交互核查）走**独立端口 5181**，与日常 5173 并存、互不干扰，同样由 Vite 代理 `/api` 回 8000。Claude Code 的 preview 工具配置在 `.claude/launch.json`；它只服务 AI 验证，与日常开发的 `start.sh`/`start-web.sh` 无关。
preview 工具只能托管自己启动的进程，故验证一律用 `ai-stocks-verify`，不要去抢占或杀掉用户手动起的 5173。

### 2. 进程、任务、数据库关系

```mermaid
flowchart LR
  A["浏览器/Vite"] --> B["FastAPI"]
  C["CLI"] --> D["同一套 services"]
  B --> D
  D --> E["DuckDBClient\n单连接+RLock"]
  D --> F["AsyncTaskService\n写任务互斥"]
  G["APScheduler"] --> F
  F --> E
  D --> H["app_config/settings"]
```

关键约束：

- DuckDB 是单文件数据库，所有 SQL 走同一个连接和锁。
- 写库类异步任务同时只允许一个，避免采集/修复/重算互相踩踏。
- CLI 写库命令和 Web 服务同时运行时可能争用库文件；做大规模 CLI 写操作前建议先停服务。
- 调度器和取消状态是进程内状态，不支持多副本部署。

### 3. 异步任务通用语义

| 能力 | 说明 |
|------|------|
| 创建 | API 写入 `async_task` 后启动守护线程 |
| 进度 | 处理器通过 `TaskContext.progress()` 写入进度 |
| 日志 | `task_log` 按 seq 增量拉取，前端实时显示 |
| 取消 | 协作式取消，到下一个检查点停下 |
| 续跑 | 读取 checkpoint，已完成部分幂等跳过 |
| 重启恢复 | startup 把残留 pending/running 标为 interrupted |

所有数据管理页的采集、补数、修复、体检都应复用这套语义，避免单独实现长任务轮询。

### 4. 配置生效边界

| 配置类型 | 读取方式 | 注意 |
|----------|----------|------|
| YAML 基线 | `get_settings()` | 有缓存，reload 或重启后更新 |
| 覆盖层 | `get_effective_settings()` | 每次合并，适合 Web 即时改参 |
| 方案配置 | profile/version 表 | 保存即生成版本，回测记录版本 |
| 指标全局参数 | `build_params` + `param_hash` | 影响指标缓存，需关注是否触发快照失效 |

新增业务读取配置时，先判断它是"启动期路径/连接配置"还是"运行期参数"。运行期参数应优先走 `get_effective_settings()`。

### 5. 前端页面开发约束

| 约束 | 目的 |
|------|------|
| 页面外壳不滚动 | 保持左侧菜单、顶栏和内容区稳定 |
| 长内容放 `.v-grow/.v-scroll` 内 | 表格、日志、图表在内部滚动 |
| 列表走服务端分页/排序 | 避免全量数据压到浏览器 |
| 多选跨页用前端集合 | 避免用户翻页后选择丢失 |
| 图表和表格要有稳定高度 | 避免布局抖动和遮挡 |

详细 CSS 和布局规则见根目录 `DESIGN.md`「布局系统」章与 `frontend/src/layout/`（校验器 + 渲染器 + 契约测试）。

### 6. 常见平台级故障定位

| 现象 | 排查路径 |
|------|----------|
| `/api/health` 不通 | `./start.sh status` → `logs/backend.log` → 端口占用 |
| 写任务一直 pending/running | 数据管理任务详情日志；重启后会被 reconcile 为 interrupted |
| 定时任务没触发 | 检查 job enabled、cron、`trading_day_only`、交易日历 |
| 配置页面改参不生效 | 确认业务读取是否走 `get_effective_settings()` |
| 前端刷新 404 | 生产期应由 FastAPI SPA fallback 返回 `index.html` |
| DuckDB 锁/占用 | 停 Web 服务，确认没有 CLI 写库任务，再重跑 |

## 业务流程

- **异步任务：创建→执行→完成**：`create(task_type, params, trigger_source)`（`async_task.py:164`）先校验类型、写任务类型则查 `_running_write()`（`:113`）有无在跑写任务、有则抛 `ConcurrentTaskError`（映射 409）；写入 `pending` 行后起守护线程跑 `_run()`（`:205`）。`_run` 置 `running`，调对应 `_HANDLERS` 处理器（边跑边 `ctx.progress/ctx.log`），正常完成置 `done` 并写 `result`；数据变更类任务收尾**惰性标记评分快照失效**（`_mark_snapshots_stale`，不立即重算）。
- **协作式取消与续跑**：`cancel()`（`:277`）把 tid 加入进程内 `_CANCELLED` 集合并置"终止中"；处理器在步骤间 `ctx.check_cancel()` 探到即抛 `TaskCancelled`，`_run` 捕获后置 `interrupted`（已完成部分已入库、可续跑），并 `_release_fixing()` 把卡在 fixing 的质检问题复位 open。`resume()`（`:187`）读 `result.checkpoint` 重新拉起处理器，按 checkpoint 幂等跳过已完成项续做。
- **重启恢复（reconcile）**：FastAPI `startup` 钩子（`backend/main.py:99`）调 `AsyncTaskService.reconcile()`（`async_task.py:251`）：残留 `running/pending` 任务标 `interrupted`（可续跑）；重启后无任务在跑故所有 fixing 必为孤儿→复位 open；清理超过 30 天的 `task_log`。
- **定时任务触发**：`startup` 另一钩子调 `start_scheduler()`（`scheduler.py:164`）：迁移旧单一配置→加载所有 `enabled` 的 job 注册到 APScheduler。到点 `_fire_job()` 读最新 job→若 `trading_day_only` 且非交易日则跳过（`_is_trading_day` 缺日历会自愈补采再判，`:32`）→`create` 一条带 `job_id/job_name` 的 `async_task`，记 `last_run`。已有写任务在跑则本次跳过（不排队），失败仅记日志不崩调度。job 的增删改启停即时生效：CRUD 里 `register_job/unregister_job` 复用同进程单例重注册触发器，免重启。
- **配置改参即时生效**：Web 表单提交→`AppConfigRepo.set_many()`（`app_config.py:118`）逐项 `_coerce` 类型/范围校验 + 跨字段约束（市值上界>下界），任一非法整批拒绝，合法则 `upsert` 进 `app_config`。业务读取走 `get_effective_settings()` 每次重新合并覆盖层，下一次读取即生效，无需重启；`reset()` 删某项回落 YAML 默认。
- **dev/prod 启停**：`./start.sh`（dev，热重载，绑 127.0.0.1）/`./start.sh prod`（绑 0.0.0.0 对外）/`stop`/`restart`/`status`/`logs`。启动后轮询 `/api/health`（最多约 15s）确认健康；`stop` 按进程特征 `pgrep/pkill` 优雅停、必要时 `-9` 强杀。`shutdown` 钩子停 APScheduler。

## 风险事项

| 等级 | 风险点 | 影响 | 建议 |
|------|--------|------|------|
| <span style="color:#dc2626">●</span> 高 | DuckDB 单写锁 + 写任务单例 | 长写任务期间其它写请求被 409 拦下；不具备并发写吞吐能力 | 单机部署下写任务排队靠页面状态和人工错峰 |
| <span style="color:#dc2626">●</span> 高 | 公网放量前的运维安全缺口 | 登录鉴权、RBAC、租户隔离、业务路由权限码、审计查询、数据字典和注册防滥用配置已接入；邮箱码仍是 dev 日志投递 | 公网前接 SMTP，并配套反代 TLS、限流、监控与备份；prod 暂不直接暴露公网 |
| <span style="color:#f59e0b">●</span> 中 | 本机绑定与进程内状态 | 多进程/多副本下任务互斥、取消、reconcile 会失效 | 仅按单机单进程部署 |
| <span style="color:#f59e0b">●</span> 中 | 服务重启打断在跑任务 | running/pending 会被标为 interrupted，需续跑 | 重启前确认任务完成；中断后从任务页续跑 |
| <span style="color:#f59e0b">●</span> 中 | 配置覆盖层与连接初始化成环 | 漏用 `get_effective_settings()` 会读不到 Web 覆盖值 | 新增运行期配置读取时明确用有效配置 |
| <span style="color:#16a34a">●</span> 低 | SQL 错误后整连接重建 | 持续性库锁/结构错误会反复重连失败 | 看日志定位根因，不只依赖自动重连 |
| <span style="color:#16a34a">●</span> 低 | DDL 迁移尽力而为 | 个别迁移失败可能与代码假设不一致 | 启动日志出现 warning 时及时核对表结构 |
