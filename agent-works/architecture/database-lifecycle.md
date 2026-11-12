# 数据库设计、初始化与演进

## 用途与范围

- 读者与技术问题：开发者和部署维护者在这里统一确定数据库实例、结构、初始化数据、升级与回退边界，以及每次数据库改动必须执行的门禁。
- 依据范围与当前结论：以 `backend/storage/ddl.py`、`pg_ddl.py`、`database_lifecycle.py`、`schema_contract.py`、`backend/cli.py` 和数据库 CI 为事实源。完整初始化只有在实例、结构、必需基础数据和目录全部通过后才登记完成；目标实例是否达标必须实际执行检查，不能由本文推断。

参考：[环境配置](environment-configuration.md) · [项目命令与服务保护](../../AGENTS.md) · [开发验证规范](../testing/guide.md) · [CI 编排与持续维护](continuous-integration.md)。

## 技术全景与边界

- 输入输出与调用者：服务启动和显式维护 CLI 调用 `initialize_database()`；只读验收调用 `verify_database()`。输入是代码内 DDL、系统 seed、连接配置和既有数据，输出是可用结构、按策略补齐的基础数据、结构契约摘要和 PG 完成标记。数据采集和普通用户业务写入不属于初始化。
- 组成与关系：`ddl.py` 维护 DuckDB 结构与兼容升级，`pg_ddl.py` 维护 PG 结构与基础权限/配置；领域仓储提供内置指标、外观和方案初始化。`database_lifecycle.py` 统一编排，`schema_contract.py` 比较物理结构与机器契约，`database_gate.py` 在隔离库中执行回归；Redis 无表结构及永久 seed。
- 共用依赖与事实源：DuckDB `main` 承载行情、参考和分析事实；PG `public` 承载用户资产、身份权限、平台配置、任务、日志、调度及审计；Redis 承载短状态、共享额度和缓存。跨库联合在服务层分别查询后合并，禁止跨库 JOIN、双写或把缓存当永久事实源。

  ```mermaid
  flowchart TD
    A[服务启动 / database init 或 upgrade] --> D[PG 事务与初始化锁]
    D --> B[实例和安装类型预检]
    B --> C[DuckDB 结构升级和指标定义]
    C --> E[PG 结构、基础数据、平台预设]
    E --> F[结构契约 + seed + 目录验收]
    F -->|全部通过| G[提交完成标记及 PG 事务]
    F -->|失败| H[回滚 PG，保留可重跑的 DuckDB 进度]
  ```

  图中箭头是执行依赖，PG 外层事务和锁覆盖初始化；两库没有分布式原子提交。

## 核心机制

### 机制：实例准备与目标识别

- 目标与入口：由部署维护者准备 PostgreSQL 数据库/角色、Redis 和 DuckDB 文件位置；`inspect_instance()` 校验 PG 版本、编码和当前 schema，`database plan` 提供安装类型与目标指纹。
- 处理与结果：应用连接必须落到 PG `public`，PostgreSQL 至少 14、编码 UTF8；隔离门禁的 CI 运行环境见 CI 专题。应用不自动创建 PG 实例、数据库或数据库角色。DuckDB 使用配置解析后的单文件路径，在可写初始化时创建目录/文件；检查和预演不能创建正式文件。Redis 的实例、逻辑库、认证及持久化由部署配置管理，初始化不清空 Redis、不预置会话或缓存。
- 数据、权限与状态：每个环境使用独立 PG 数据库、DuckDB 文件与 Redis 命名空间/逻辑库。PG 数据库所有者及迁移身份应为项目专用角色，不授予业务账号 `SUPERUSER`、`CREATEDB` 或 `CREATEROLE`；当前自动升级启动需要应用角色具备其对象的 DDL 权限，不支持直接切成仅 DML 身份后仍宣称能自动升级。数据库管理身份只负责外部建库与隔离门禁的临时建库。
- 配置与扩展：PG 连接来自 `Settings.pg_conninfo()`，DuckDB 路径来自 `Settings.duckdb_path`；敏感值不得进入 DDL、SQL 夹具或结构契约。非 `dev/test/local` 环境只要需要初始化管理员密码（包括旧库缺失密码），就必须显式提供 `AI_STOCKS_ADMIN_PASSWORD`，不随机生成或打印密码。`./start.sh database ...` 与服务共用变量文件加载；直接 `python -m backend.cli ...` 不加载 `.env.local`。
- 失败与资源边界：PG 连接失败、schema 不符、版本不足或编码不符直接失败；不创建替代库、不猜目标。CLI 写入还须显式 `--apply`，并常量时间比较 `--expected-target-fingerprint` 与 PG 身份、实际连接端点及 DuckDB 解析路径的组合摘要；指纹不匹配时不得创建 DuckDB 文件或写入 PG。启动流程先检查 PG、Redis 和 JWT 密钥，再初始化数据库。
- 局部风险与复核：环境身份仍以有效运行档案为准，不能从 `dev/prod` 启动模式推断。实例备份、容量、TLS、网络 ACL 和恢复演练是部署前提；本地隔离门禁不能证明生产实例配置已达标。

### 机制：目标结构、兼容升级与版本识别

- 目标与入口：表、主键、外键、CHECK、默认值、索引和序列必须进入正式双库 DDL；交易台账复用 `trade_ledger_schema.py` 的共享声明。兼容升级由同一 DDL 模块承接，禁止在共享库手工建表、在路由中另写 DDL 或只改新装定义而不补旧库升级。
- 处理与结果：`database_contract.json` 是从独立声明式空库生成的机器产物，记录列集合、类型、可空性、默认值、主键/唯一/FK/CHECK 定义、索引及序列结构。`schema_report()` 对实际系统目录做完整比较，缺少、额外和定义不符均失败；只检查已有字段说明的目录门禁不能替代它。序列当前值、物理列顺序、OID、行数和业务数据不作为结构版本。
- 数据、权限与状态：`storage_migration` 中的 `database.lifecycle.v1` 在全部验收通过后写 `state=applied`，`details` 保存当前 `contract_sha256`、执行模式和新装来源。完成元数据缺失必要字段或类型非法时拒绝覆盖；完整旧摘要可以通过显式升级更新。摘要是目标结构版本，不能冒充历史数据迁移已完成。专项数据迁移继续使用自己的 marker；禁止手工添加 marker 跳过真实迁移。
- 配置与扩展：新增结构先维护 DDL 和迁移，再运行 `database gate --refresh-contract`。该命令只从门禁随机空库生成契约，并继续执行全部测试；禁止从开发/生产现库导出“期望结构”，禁止手改 JSON 掩盖漂移。正式合并检查使用不带刷新参数的 `database gate`。
- 失败与资源边界：DuckDB 必需兼容语句和维度 seed 失败立即抛出；事务始终在开始时的原连接回滚。表重建前拒绝未知列、类型、索引、约束和主键形态，保留既有临时表，复制按列名映射，不能在重建后靠结构已达标掩盖原数据丢失。PG 初始化在同一事务及 advisory lock 中执行；嵌套事务使用 savepoint，旧兼容 SQL 的通配 CHECK 替换也先核对已识别定义。PG 失败回滚其 DDL、seed 和完成标记；两库不承诺整体回滚。
- 局部风险与复核：当前冻结兼容基线为 `backend/tests/fixtures/database/pre-lifecycle-v1-{duck,pg}.sql`，包含统一生命周期接入前的完整结构及已支持补列的旧形态。升级测试从这份结构建库，而不是先用新 DDL 建库再删几列；以后新增字段没有迁移时，旧基线升级会与新装契约不一致。冻结基线不得随刷新契约覆盖。更早的单主键资产库等仍须先走对应专项迁移；无法收敛的结构漂移应停服定位，不自动删除未知列、表或业务数据。

### 机制：初始化数据范围与覆盖策略

- 目标与入口：基础数据由 `init_pg_db()`、`IndicatorDefRepo.seed_builtins()`、`LayoutConfigRepo` 的内置预设初始化和 `seed_platform_profiles()` 提供；完整路径统一由 `initialize_database()` 调用，`seed-presets` 复用同一个三类方案入口。
- 处理与结果：下表定义哪些数据能进入初始化以及重跑策略。具体稳定键和值复用代码中的 seed 集合，不在文档抄写另一份字典或方案内容。

  | 数据类别 | 范围、归属和入口 | 重跑及更新规则 |
  | --- | --- | --- |
  | 默认身份 | `default` 租户、`admin` 平台管理员 | 缺失时创建；已有密码不覆盖；仅无密码时补初始哈希，默认管理员身份兼容校准沿用 `seed_default_tenant()` |
  | 内置角色、菜单、功能点 | `_SEED_ROLES`、`_SEED_MENU_TREE`、`_SEED_RESOURCES`，平台级数据 | 按稳定键补缺；既有菜单/功能点的父级、标题、类型、路由、图标、顺序和可见性全部保留 |
  | 默认角色授权 | 内置角色首次授权及明确版本化策略迁移 | system 角色全量补齐；普通内置角色由 `migration.builtin_role_defaults_v1.<role>` 保护，完成后即使授权被清空也不重授；授权变化与 `perm_ver` 同事务 |
  | 平台默认配置与字典 | `_STAGE5_APP_CONFIG_DEFAULTS`、`_SEED_DICT_TYPES`、`_SEED_DICT_ITEMS` | 补缺，保留已有值、名称、颜色及停用状态；代码调整默认值不隐含覆盖管理员配置 |
  | 历史敏感配置 | `_protect_legacy_config_secrets()` 的明确安全升级 | 有主密钥时加密旧明文；无主密钥时删除不能安全迁移的明文并告警，关联审计原位脱敏；不把此例外扩大为普通配置覆盖 |
  | 数据维度 | `_DIMENSION_SEED`，平台治理登记 | 缺失补齐；已有状态及自定义值保留；已登记系统表关联的必要升级由明确兼容语句处理 |
  | 内置技术指标 | `REGISTRY`，DuckDB 平台定义 | 校准代码维护的定义语义；保留人工启停和分类，明确标记的历史默认迁移除外 |
  | 内置外观 | `BUILTIN_PRESETS`，PG 平台预设 | 复用外观自身版本 marker 迁移；保留自定义配置；默认预设必须可用，既有迁移与数据路由边界不绕过 |
  | 筛选、评分、买卖预设 | 代码登记的稳定 ID，`PUBLIC_BOARD_OWNER` 平台槽 | 幂等校准代码维护的内容及公开范围；内容不变不增加版本；用户复制的私有方案不改写 |
  | 专项升级状态 | 配置存储、任务运行态、权限策略及结构完成 marker | 只有真实条件成立后才提交；回滚 tombstone 继续生效，禁止借 seed 自动复活 |
  | 行情、参考资料及业务结果 | 股票、日线、ST、日历、股本、板块、分时、筛选结果、回测、任务日志等 | 不生成伪数据，不隐含采集、回填、重算或创建业务调度；使用所属采集/业务入口 |
  | 演示、调试和测试账号 | `debug_*`、E2E 夹具等 | 不进入初始化；继续使用受环境及指纹保护的独立调试入口 |

- 数据、权限与状态：`seed_report()` 校验必需稳定键、内置角色身份/锁定属性、默认管理员归属/密码哈希、默认外观可用性、平台配置类型/范围及预设归属和公开字段；可编辑标题和合法配置不与默认值硬比较。普通角色的授权完成 marker 与授权同事务提交；首次接入时既有角色即使没有 marker 且授权为空也原样保留，只有本次新建角色才补默认授权。用户角色关系只在首次引入 RBAC 表时按遗留 role_code 迁移；已有关系表中的无角色用户保持失败关闭，缺失关系表则拒绝猜测重建。

  菜单和功能点需要覆盖已有配置时，只允许系统管理员通过管理页面/API 显式修改并记录 before/after 审计，或使用独立版本 marker、事务级 advisory lock、精确旧身份检查、确认口令及审计的专项迁移。普通启动、升级 SQL 和测试不得用 `UPDATE/DELETE sys_menu/sys_resource` 或 `ON CONFLICT ... DO UPDATE` 默认覆盖既有行。专项 SQL 还必须包含事务、`app_config` marker、人工显式开关 `ai_stocks.confirm_menu_overwrite` 和 `AI_STOCKS_MENU_OVERWRITE: EXPLICIT_CONFIRMATION_REQUIRED` 标识，由既有 SQL 扫描测试校验；无法无歧义处理的旧菜单保留并告警。

- 配置与扩展：新 seed 必须明确是代码维护、首次默认、管理员维护还是独立业务数据，并进入相应 seed 集合、只读验收和正反例测试。显式双库操作通过 `storage_client_scope()` 绑定间接仓储和有效配置读取，退出恢复原连接上下文，不污染默认运行态缓存。不能用初始化顺便收回权限、改密码、更新全部配置或删除资产。

  视觉预设旧名称、连板天梯资源的旧父级即使仍等于历史默认值，也不由普通 seed 自动覆盖。名称调整可显式使用[视觉预设专项 SQL](../configurable-layout-system/visual-preset-menu-rename.sql)，按其确认口令、独立 marker 和 before/after 审计执行；不运行脚本即保留原配置。
- 失败与资源边界：必需 seed 缺失导致验收失败；完整入口可补齐缺失数据。显式回滚的资源/权限策略继续以专项 marker 为准，不通过删除 marker“修复”。
- 局部风险与复核：初始化成功只代表系统基础可用；交易日历前瞻、行情覆盖、ST 准确性和计算结果仍由各领域门禁判断。市场数据未准备时页面应按其契约展示空态或失败关闭。

### 机制：新装、升级、验收与失败恢复

- 目标与入口：`./start.sh database plan|init|upgrade|check|gate`；服务启动调用同一初始化器，DuckDB 只读启动只做完整验收。
- 处理与结果：只有 PG 无业务结构且 DuckDB 无业务数据时识别为新装；允许上次失败留下的空结构和内置指标重跑。新装直接写入 PG 任务运行态及平台配置路由标记，不要求用“历史迁移”激活当前架构。旧库结构升级保留已有存储路由，不自动复制资产、任务历史或旧布局。`init` 拒绝没有统一初始化记录的旧库，同版本已完成的新装可重跑；契约变化应使用 `upgrade`。
- 数据、权限与状态：`database check` 只读校验实例、结构、完成摘要、必需 seed 和目录，不修表、不补数据。新装来源持久保存，后续丢失路由 marker 不能被当作正常旧库；任务运行态的合法 `rolled_back` 状态允许保留，由专项流程核对数据。检查失败返回非零退出码。
- 配置与扩展：CLI 默认不写入，`init/upgrade` 不带 `--apply` 仅返回计划。维护路径如下；目标变量文件先按环境配置准备，操作实际库前先保存可信服务模式和参数，通过脚本安全停服以释放 DuckDB 文件锁，完成后恢复原状态。

  ```bash
  ./start.sh status
  # 原服务运行时先保存运行档案并安全停服：
  ./start.sh stop

  ./start.sh database plan
  # 核对实例、安装类型、duckdb_path 及 target_fingerprint；新装使用 init，已有库使用 upgrade。
  ./start.sh database init --apply --expected-target-fingerprint <plan返回的target_fingerprint>
  # 或：./start.sh database upgrade --apply --expected-target-fingerprint <plan返回的target_fingerprint>
  ./start.sh database check
  ```

  `plan` 的成功只代表预检通过，不能当作初始化完成。检查失败时保留报告中的对象路径，核对 DDL、迁移、seed 和目标实例；不先刷新基线让检查“变绿”。实例操作的成功判据是退出码 0、`ok=true`、完成摘要匹配及预期实际路由，不能只看进程启动。

- 失败与资源边界：失败时保持停服，不发起业务写入。PG 事务失败保留此前完成标记，不推进版本；修复原因后重跑同一初始化/升级入口。DuckDB 的部分升级可能已提交，必须检查实际结构后前向恢复。涉及删表、不可逆数据转换或跨库复制时先备份并使用领域专项迁移；不提供无条件通用降级或靠删除 marker 回滚。
- 局部风险与复核：旧资产、任务运行态和旧平台配置的搬迁分别复用 `migrate-rbac`、`task-runtime-storage`、`migrate-config-storage`。它们的领域转换及回退协议见[权限与租户](system-rbac-tenant.md#旧版用户资产的一次性迁移)、[任务运行态](task-runtime.md#一次性升级与受控回滚)、[环境配置](environment-configuration.md#3-生效配置与数据库覆盖层)。专项迁移不是每次启动都执行的默认操作，结构完成 marker 不替代其数据验收。

## 接入、扩展与变更影响

- 消费与接入方式：新增或修改数据库对象时，按下列顺序维护；目录页面仍自动发现物理字段，意外对象显示 `unregistered`，但不能带遗漏合并。

1. 确认事实用途与数据库归属，用户私有 PG 表带 `tenant_id + owner_user_id`，主键、冲突更新和全部读写沿用归属条件。
2. 在正式 DDL 声明完整目标结构，并实现受支持旧库到目标结构的幂等升级。循环外键和共享索引复用 DDL 公共片段；构造仓储中的兼容 schema 确保只能调用这些共享定义，不能新增另一套结构或完整 seed。
3. 在 `catalog.py` 登记中文表名、实际用途、业务分类、归属、来源及人类可读关系；字段中文名/说明复用显式注解、数据库列注释和 `catalog_metadata.py` 公共词典，未知字段不得冒充完整元数据。
4. 每表显式登记鲜活度和质量策略，包括 `not_applicable`；PG 默认不适用。规划维度落地时同时更新维度状态及关联表，不能注册尚无物理表的虚构对象。
5. 有初始数据变化时按上表确定所有权、稳定键、覆盖规则、版本 marker、引用与失败恢复，并扩展 `seed_report()`。同步领域仓储、权限、归属和对应测试。
6. 执行 `./start.sh database gate --refresh-contract`，审查目标结构机器差异；修复升级、重跑、数据保留或目录测试失败。冻结旧结构不随之重生成。
7. 执行不带刷新参数的 `./start.sh database gate` 作为本地合并检查。实际实例的升级验收另用 `database check`；目录变更还须通过 `verify-catalog`，隔离门禁已执行该真实 CLI 入口。

- 扩展与兼容边界：新增支持版本时新增不可变旧结构夹具，明确来源与升级路径；不能删除失败旧夹具来缩小兼容承诺。领域数据转换、真实行值保留、大表性能和外部源语义仍需对应测试；空库结构对比不能证明所有数据迁移正确。
- 依赖及消费方影响：初始化语义变化同步本文、统一入口、结构契约、冻结兼容测试和 CI；目录/治理业务语义变化更新[数据管理](data-management.md)。

## 验证入口与已知限制

| 验证或风险事项 | 条件与入口 | 证据状态及位置 | 结果或影响 | 后续处理 |
| --- | --- | --- | --- | --- |
| 可执行隔离门禁 | `./start.sh database gate` | `backend/tests/test_database_lifecycle.py`、`backend/devtools/database_gate.py` | 新装、冻结旧库升级、幂等、数据保留、结构/seed 负例、故障回滚、真实 CLI 和目录验收 | 数据库变更须通过本门禁；自动调用见 CI 专题，结果以本次输出为准 |
| 新装声明与目标契约一致 | 独立声明式空库对比 `database_contract.json` | `create_declared_schema()`、`schema_report()` | 防止漏登记/手改契约，以及新装与升级结构不一致 | 结构变化时刷新机器产物并审查差异 |
| 门禁隔离与失败关闭 | 显式 `AI_STOCKS_DB_GATE_ADMIN_DSN`，或本机 `initdb/pg_ctl` | 临时库名 `ai_stocks_gate_<随机值>`；本地临时集群仅 Unix socket，日志在项目 `logs/` | 不使用业务 DSN；清除环境 Pytest 选项和插件，不接受取消选择、skip/xfail 或空集合冒充完整通过 | 管理连接只用于创建/删除本次随机库；退出关闭连接、删除临时库并停止自建集群 |
| 自动持续检查 | [统一 CI 入口](continuous-integration.md) | 套件、触发与运行环境由 CI 专题维护 | 复用本专题数据库门禁 | 不代表业务实例已升级或验收 |
| 目标实例验收 | 停服释放文件锁后 `database check` | 只读实例、结构、完成摘要、seed、目录报告 | 与隔离门禁分别回答“代码可安装”和“此实例达标” | 不用一个结果代替另一个 |
| 运行和规模边界 | 当前单后端进程；离线初始化/升级 | 双库客户端、初始化锁及专项迁移 | 不支持在线并发结构升级、自动跨库原子回滚或任意历史版本降级 | 变更前备份，失败停服并按具体对象恢复 |
