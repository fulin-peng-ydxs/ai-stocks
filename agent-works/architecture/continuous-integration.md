# CI 编排与持续维护

## 用途与范围

- 读者与技术问题：

  通用验证遵循[全局测试规范](~/ai-agent-config/config/force/testing-standards.md)。开发者在这里维护常用/专项 CI 的触发、选择、隔离、报告验收及新增测试接入。日常按改动选择验证和本地命令见[开发验证规范](../testing/guide.md)，浏览器准入与原生 runner 见 [E2E 指南](../e2e-automation/guide.md)，数据库验收语义见[数据库专题](database-lifecycle.md)。

- 依据范围与当前结论：

  实现以 `.github/workflows/ci*.yml`、`backend/devtools/ci*.py`、`isolated_environment.py` 和 `config/ci-suites.json` 为准。规划器、原执行器和结果对账形成同一闭环；路径规则和需求覆盖仍须维护者按实际消费审查；新增页面或契约变更时沿视图/共享组件、前端 API 和实际后端路由同步影响登记。CI 不部署或升级业务实例，远端运行及分支保护须在 GitHub 核实。

## 技术全景与边界

- 输入输出与调用者：

  push（含主分支直推）和 PR 自动执行 `change`；已知变更范围内，普通说明 Markdown 走轻量集合，其余变更执行常用集合并追加命中的专项。每日北京时间 05:00 仅审计依赖。手动可选择 `change`、`common` 或登记套件；本地 `run` 默认 `common`，不会因写文档而自动缩减显式常用验收。

  输出包括本次 `ci-plan.json`、套件回执、实际报告和 `ci-result.json/md`。总状态 `CI common result` 代表 push/PR 规划范围完成，轻量报告会明确标为纯 Markdown 检查，不能解释为业务全量已运行。

- 组成与关系：

  登记表统一维护套件、专项归属、共享/领域影响路径和 Markdown 策略。`ci.yml` 调用规划器后，以矩阵复用 `ci-suite.yml`；本地使用同一执行器。旧前端和数据库 workflow 仅保留手动/可复用入口。

  图中实线为调用或结果汇总，虚线为配置供给。选择范围由运行模式决定，单专项和每日审计不会额外运行常用集合。

  ```mermaid
  flowchart TD
    Push["push / PR：change"] --> Plan["ci.yml / run-ci.sh：prepare / run"]
    Manual["手动：change / common / 登记套件"] --> Plan
    Daily["每日 05:00：dependency-audit"] --> Plan
    Registry["config/ci-suites.json"] -.-> Plan
    Plan --> Mode{"运行模式与实际变更"}
    Mode -->|change：纯说明 Markdown| Light["密钥 + 质量；登记与锁校验"]
    Mode -->|change：其他或未知范围| Change["常用 + 命中专项；未知保持未完成"]
    Mode -->|common| Common["常用集合；依赖审计按条件"]
    Mode -->|单套件或定时审计| Single["仅所选套件"]
    Light --> Runner["同一执行器；复用原 runner"]
    Change --> Runner
    Common --> Runner
    Single --> Runner
    Runner --> Reports["实际报告 + 回执 + 源码/报告摘要"]
    Reports --> Result["result：必跑与实际对账"]
    Plan --> Result
    Result --> Gate["缺项、失败、版本或参数不符均不通过"]
  ```

- 共用依赖与事实源：

  Python CI 使用 3.12 和带 SHA-256 的 `requirements-ci.lock`，源清单为 `requirements-ci.txt` 及递归 include；前端 Node.js 使用 22.12+ 和 npm 锁。质量套件单独安装同源固定 Ruff 的 `requirements-quality.txt`，工具固定版本及校验和由 `ci_tools.TOOLS` 维护。后端、数据库和浏览器专项共用可销毁存储；本地原生验证不自动获得这一隔离。

  下表只从登记表生成，`scripts/run-ci.sh docs --write` 更新，`check` 校验。常用列描述 `run common`，`change` 还应用影响路径和轻量策略。共享浏览器路径只展示一次，各组列出自身追加路径。

  <!-- ci-inventory:start -->
  | 套件 | 类别 | 常用入口自动调用 | 覆盖 |
  | --- | --- | --- | --- |
  | `secrets` | secrets | 是 | 受控源码及本次提交范围的密钥扫描；精确固定材料例外到期阻断 |
  | `quality` | quality | 是 | 后端 Ruff 默认规则与全部 GitHub workflow 语法检查 |
  | `frontend` | frontend | 是 | 前端设计静态、全量离线 Vitest、类型及生产构建；拒绝不完整执行 |
  | `backend` | backend | 是 | 隔离三库中的后端业务、权限及任务回归；新增测试默认加入 |
  | `database` | database | 是 | 现有数据库新装、旧库升级、结构及初始化数据契约 |
  | `dependency-audit` | audit | 依赖变更时；范围未知时保守执行 | Python CI 锁与 npm 锁的全部依赖漏洞审计；每日及手动可独立调用 |
  | `backend-scale` | backend | 否 | 显式规模参数下的分时、估值与质量修复规模回归 |
  | `secrets-history` | secrets | 否 | 显式扫描全部已获取 Git 历史；首次历史基线及事件调查专项 |
  | `e2e-shell` | e2e | 否 | 现有登录首帧与工作台外壳浏览器专项；标准视口 |
  | `e2e-sectors` | e2e | 否 | 复用板块物理夹具 runner 的数据管理、质量反馈与工作台专项 |
  | `e2e-correlation` | e2e | 否 | 走势关联页面、权限、系统结果及调度表单失败保留专项 |
  | `e2e-trade` | e2e | 否 | 真实账户、成交流水与日结：初始化、持仓回读、修正撤回、历史、规则、权限与未保存保护 |
  | `e2e-backtest` | e2e | 否 | 复用公开回测夹具与只读后端，验证浏览、加载和恢复 |
  | `e2e-assets` | e2e | 否 | 资产搜索跨账号浏览、复制与只读加载 |
  | `e2e-settings` | e2e | 否 | 页面设置分页接线、偏好持久化与恢复默认 |
  | `e2e-rbac` | e2e | 否 | 系统角色权限树键盘操作及菜单功能点装配 |
  | `e2e-schedule` | e2e | 否 | 调度真实保存、依赖条件、停用确认与服务端排序接线 |
  | `e2e-tasks` | e2e | 否 | 统一采集表单、任务轮询及日志抽屉关键路径 |
  | `e2e-ladder` | e2e | 否 | 连板天梯筛选导出、分析返回、真实偏好及任务呈现；固定接口材料 |
  | `e2e-stocks` | e2e | 否 | 个股查询与详情图表、返回现场、故障恢复及真实PG偏好隔离；隔离固定行情 |
  | `e2e-trade-ui` | e2e | 否 | 账户日结历史筛选、修订回看与快捷卡导航；固定接口材料验证页面接线 |

  | 专项文件或用例 | 归属 | 原因 |
  | --- | --- | --- |
  | `backend/tests/test_database_lifecycle.py` | `database` | 由数据库门禁提供独立管理连接与严格执行策略 |
  | `backend/tests/test_api.py` | `manual-market` | 遗留真实行情冒烟，要求已采集行情及前端产物；不作为空库代码回归 |
  | `backend/tests/test_intraday_scale.py` | `backend-scale` | 仅在显式规模参数下执行 |
  | `frontend/e2e/login-initial-render.spec.ts` | `e2e-shell` | 现有登录首帧与工作台外壳浏览器专项；标准视口 |
  | `frontend/e2e/app-shell-surfaces.spec.ts` | `e2e-shell` | 现有登录首帧与工作台外壳浏览器专项；标准视口 |
  | `frontend/e2e/board-data-management.spec.ts` | `e2e-sectors` | 复用板块物理夹具 runner 的数据管理、质量反馈与工作台专项 |
  | `frontend/e2e/sector-quality-recovery.spec.ts` | `e2e-sectors` | 复用板块物理夹具 runner 的数据管理、质量反馈与工作台专项 |
  | `frontend/e2e/sectors-workbench.spec.ts` | `e2e-sectors` | 复用板块物理夹具 runner 的数据管理、质量反馈与工作台专项 |
  | `frontend/e2e/stock-board-correlation.spec.ts` | `e2e-correlation` | 复用走势关联板块 runner 的页面、权限及系统结果专项 |
  | `frontend/e2e/trade-discipline.spec.ts` | `e2e-trade` | 独立账户/规则及固定行情夹具；标准项目执行账本和权限链路，默认项目执行未保存协议 |
  | `frontend/e2e/backtest-public-runs.spec.ts` | `e2e-backtest` | 复用公开回测夹具与只读后端，验证浏览、加载和恢复 |
  | `frontend/e2e/app-row-actions.spec.ts` | `manual-e2e` | 手动设计验证：操作列几何、更多菜单关闭；不作为每次业务变更的完整页面回归 |
  | `frontend/e2e/asset-search-drawer.spec.ts` | `e2e-assets` | 跨账号方案搜索、复制和只读加载；复用外壳隔离账号与正式资产服务 |
  | `frontend/e2e/component-state-preview.spec.ts` | `manual-e2e` | 手动设计验证：组件预览四态和主题token；普通组件行为已有Vitest，保留浏览器呈现验收 |
  | `frontend/e2e/data-overview-low-viewport.spec.ts` | `manual-e2e` | 手动响应式验证：紧凑视口与各档表格铺满，需按视口选择适用项目，当前未接入严格CI |
  | `frontend/e2e/display-scale-navigation.spec.ts` | `manual-e2e` | 手动显示比例验证：跨屏坐标与点击命中，专属预览fixture，不代表业务导航闭环 |
  | `frontend/e2e/display-scale-popper.spec.ts` | `manual-e2e` | 手动显示比例验证：50%至150%浮层几何，需要专项呈现验收，不纳入普通业务路径 |
  | `frontend/e2e/layout-scroll-ownership.spec.ts` | `manual-e2e` | 手动布局验证：主表与主内容区滚动归属，按相关布局变更选择，不代表页面业务闭环 |
  | `frontend/e2e/limit-ladder-analysis.spec.ts` | `e2e-ladder` | 复用确定性天梯接口材料；偏好通过正式PG回读，其他断言只证明浏览器接线 |
  | `frontend/e2e/limit-ladder-preferences.spec.ts` | `e2e-ladder` | 复用确定性天梯接口材料；偏好通过正式PG回读，其他断言只证明浏览器接线 |
  | `frontend/e2e/limit-ladder-task-center.spec.ts` | `e2e-ladder` | 复用确定性天梯接口材料；偏好通过正式PG回读，其他断言只证明浏览器接线 |
  | `frontend/e2e/limit-ladder.spec.ts` | `e2e-ladder` | 复用确定性天梯接口材料；偏好通过正式PG回读，其他断言只证明浏览器接线 |
  | `frontend/e2e/page-settings-drawer.spec.ts` | `e2e-settings` | 设置抽屉分页接线和真实用户偏好恢复；复用外壳隔离环境 |
  | `frontend/e2e/quality-repair-schedule.spec.ts` | `e2e-schedule` | 真实质检恢复调度的创建与回读；复用外壳runner及正式初始化的独立PG |
  | `frontend/e2e/role-permission-tree-accessibility.spec.ts` | `e2e-rbac` | 系统权限树键盘与菜单功能点装配；复用正式RBAC初始化 |
  | `frontend/e2e/schedule-dependency.spec.ts` | `e2e-schedule` | 真实调度依赖保存及停用确认；复用外壳runner及正式初始化的独立PG |
  | `frontend/e2e/schedule-frequency-sort.spec.ts` | `e2e-schedule` | 调度触发规则的真实页面排序；固定接口材料只证明前端消费 |
  | `frontend/e2e/stock-board-correlation-t9.spec.ts` | `e2e-correlation` | 关联计算调度表单、失败保留和权限入口；复用关联runner，Mock不证明计算落表 |
  | `frontend/e2e/stock-chart-workspace-preview.spec.ts` | `manual-e2e` | 手动图表呈现验证：多图几何、光标与比例命中，使用独立预览fixture，不代替行情与权限业务验证 |
  | `frontend/e2e/stock-detail-chart-workspace.spec.ts` | `e2e-stocks` | 复用共用空库行情与既有浏览器runner；当前图表契约和真实PG用户偏好隔离 |
  | `frontend/e2e/stock-ingest-management.spec.ts` | `e2e-tasks` | 统一采集入口与新建调度表单；固定接口材料只证明前端装配 |
  | `frontend/e2e/task-center-polling.spec.ts` | `e2e-tasks` | 任务轮询、操作和日志抽屉；固定接口材料不冒充真实采集 |
  | `frontend/e2e/trade-discipline-history.spec.ts` | `e2e-trade-ui` | 账户日结和不可变修订接口结构；固定材料只证明页面接线，真实账本由e2e-trade验证 |
  | `frontend/e2e/trade-discipline-quick-card.spec.ts` | `e2e-trade-ui` | 账户日结和不可变修订接口结构；固定材料只证明页面接线，真实账本由e2e-trade验证 |
  | `backend/tests/test_intraday_parallel.py::test_repair_commits_quality_and_progress_before_full_market_finishes[5000]` | `backend-scale` | 全市场规模参数 |
  | `backend/tests/test_intraday_performance.py::test_fixed_response_repair_cost[1000]` | `backend-scale` | 千股规模参数 |
  | `backend/tests/test_valuation_batch.py::test_latest_batch_scale_keeps_every_target_and_reported_evidence` | `backend-scale` | 显式估值补采规模参数 |
  | `backend/tests/test_quality_repair_scale.py::test_full_history_repair_scale[capital_gap]` | `backend-scale` | 显式全历史股本修复规模参数 |
  | `backend/tests/test_quality_repair_scale.py::test_full_history_repair_scale[history_data_gap]` | `backend-scale` | 显式全历史行情缺口修复规模参数 |
  | `backend/tests/test_schedule_downstream.py::test_multi_upstream_runtime_migration_round_trip[duckdb]` | `not-applicable` | 该迁移只支持 PG schema；同一测试的 postgres 参数仍在常用回归执行 |

  所有浏览器组共同继承的触发路径：`frontend/playwright*.ts`、`frontend/e2e/helpers/auth.ts`、`frontend/e2e/helpers/console.ts`、`frontend/e2e/helpers/navigation.ts`、`frontend/e2e/helpers/rowActions.ts`、`frontend/e2e/helpers/settings.ts`、`frontend/e2e/helpers/e2e-backend-health.*`、`scripts/run-playwright.sh`、`scripts/e2e-backend-lifecycle.sh`、`backend/devtools/ci*.py`、`.github/workflows/*`、`frontend/src/layout/*`、`backend/api/layout.py`、`backend/storage/layout_config.py`、`backend/api/user_preferences.py`、`backend/storage/user_preference.py`、`frontend/src/router/*`、`frontend/src/App.vue`、`frontend/package*.json`、`frontend/patches/*`、`backend/devtools/environment_guard.py`、`backend/devtools/rbac_test_users.py`、`backend/devtools/e2e_test_users.py`、`backend/devtools/backend_runtime_state.py`、`scripts/load-local-env.sh`、`start.sh`、`config/ci-suites.json`、`frontend/src/components/App*.vue`、`frontend/src/styles/*`、`frontend/src/directives/*`、`backend/auth/*`、`backend/api/auth.py`、`frontend/src/components/PageDrawer.vue`。

  | 专项 | 本组追加路径 | 执行方式 |
  | --- | --- | --- |
  | `backend-scale` | `backend/services/intraday*`、`backend/services/ingest*`、`backend/services/share_capital.py`、`backend/tests/test_*scale.py`、`backend/tests/test_intraday_parallel.py`、`backend/tests/test_intraday_performance.py`、`backend/tests/test_valuation_batch.py`、`backend/devtools/ci*.py`、`config/ci-suites.json`、`backend/services/quality_repair*`、`backend/services/capital_quality.py`、`backend/services/history_quality.py`、`backend/services/collection_quality.py` | `run change` 按命中调用；`run backend-scale` 显式执行 |
  | `e2e-shell` | `frontend/src/views/LoginView.vue`、`frontend/e2e/login-initial-render.spec.ts`、`frontend/e2e/app-shell-surfaces.spec.ts`、`frontend/src/stores/auth.ts`、`frontend/src/components/SideMenu*`、`frontend/src/components/WorkspaceTabs.vue`、`backend/api/stocks.py`、`frontend/src/api/menu.ts`、`backend/api/menus.py` | `run change` 按命中调用；`run e2e-shell` 显式执行 |
  | `e2e-sectors` | `frontend/src/views/Sector*`、`frontend/src/utils/sectorCompare.ts`、`frontend/src/views/data/OverviewView.vue`、`frontend/src/views/data/QualityView.vue`、`frontend/src/views/data/ScheduleView.vue`、`frontend/src/views/ConfigView.vue`、`frontend/src/components/config/*`、`backend/services/board*`、`scripts/run-sector-e2e.sh`、`frontend/e2e/board-data-management.spec.ts`、`frontend/e2e/sector-quality-recovery.spec.ts`、`frontend/e2e/sectors-workbench.spec.ts`、`backend/devtools/e2e_board_data.py`、`backend/devtools/e2e_market_data.py`、`frontend/src/views/data/IngestView.vue`、`frontend/src/api/sectors.ts`、`frontend/src/components/SectorCompareChart.vue`、`frontend/src/components/stock-chart/*`、`frontend/src/components/data/BoardTaskScopeFields.vue`、`backend/api/sectors.py`、`backend/api/data_admin.py`、`backend/scheduler/*`、`frontend/e2e/helpers/sectorData.ts`、`frontend/src/api/data.ts`、`backend/api/data_tasks.py` | `run change` 按命中调用；`run e2e-sectors` 显式执行 |
  | `e2e-correlation` | `frontend/src/components/*RelatedBoard*`、`backend/services/stock_board_correlation*`、`scripts/run-stock-board-correlation-e2e.sh`、`frontend/e2e/stock-board-correlation.spec.ts`、`backend/devtools/e2e_stock_board_correlation.py`、`backend/devtools/e2e_market_data.py`、`frontend/src/views/StocksView.vue`、`frontend/src/views/BoardView.vue`、`frontend/src/views/ScreenView.vue`、`frontend/src/api/stocks.ts`、`frontend/src/components/MarketBoardTag.vue`、`frontend/src/components/asset-search/*`、`backend/api/stocks.py`、`backend/api/board.py`、`frontend/e2e/stock-board-correlation-t9.spec.ts`、`frontend/e2e/helpers/stockBoardCorrelation.ts`、`frontend/src/api/data.ts`、`backend/api/data_tasks.py`、`frontend/src/api/screening.ts`、`backend/api/profiles.py` | `run change` 按命中调用；`run e2e-correlation` 显式执行 |
  | `e2e-trade` | `frontend/src/views/TradeDiscipline*`、`frontend/src/components/trade-discipline/*`、`backend/services/trade_discipline*`、`scripts/run-trade-discipline-e2e.sh`、`frontend/e2e/trade-discipline.spec.ts`、`backend/devtools/e2e_trade_discipline.py`、`backend/devtools/e2e_market_data.py`、`frontend/src/views/trade-discipline/**/*`、`frontend/src/api/tradeDiscipline.ts`、`frontend/src/utils/tradeDiscipline*`、`frontend/src/composables/useTradeDiscipline*`、`backend/storage/trade_discipline_repository.py`、`backend/services/trade_ledger*.py`、`backend/storage/trade_ledger_repository.py`、`frontend/src/api/tradeLedger.ts`、`frontend/src/utils/tradeLedgerRecord.ts`、`frontend/src/utils/tradeNumeric.ts`、`frontend/e2e/helpers/tradeDiscipline.ts`、`backend/api/trade_discipline.py` | `run change` 按命中调用；`run e2e-trade` 显式执行 |
  | `e2e-backtest` | `frontend/src/views/BacktestView.vue`、`backend/services/backtest*`、`backend/devtools/e2e_backtest_runs.py`、`frontend/e2e/backtest-public-runs.spec.ts`、`frontend/src/api/backtest.ts`、`frontend/src/components/asset-search/*`、`backend/api/backtest.py`、`backend/devtools/e2e_market_data.py`、`frontend/e2e/helpers/backtestRuns.ts`、`frontend/src/api/screening.ts`、`backend/api/profiles.py`、`frontend/src/api/scoreProfile.ts`、`frontend/src/api/tradeProfile.ts`、`backend/api/score_profiles.py`、`backend/api/trade_profiles.py` | `run change` 按命中调用；`run e2e-backtest` 显式执行 |
  | `e2e-assets` | `frontend/src/components/asset-search/*`、`frontend/src/views/ScreenView.vue`、`backend/api/profiles.py`、`frontend/e2e/asset-search-drawer.spec.ts`、`frontend/src/api/screening.ts` | `run change` 按命中调用；`run e2e-assets` 显式执行 |
  | `e2e-settings` | `frontend/src/components/PageSettingsDrawer.vue`、`frontend/src/composables/useDrawerPreferences.ts`、`frontend/e2e/page-settings-drawer.spec.ts` | `run change` 按命中调用；`run e2e-settings` 显式执行 |
  | `e2e-rbac` | `frontend/src/views/system/RoleManageView.vue`、`frontend/src/views/system/MenuResourceView.vue`、`frontend/e2e/role-permission-tree-accessibility.spec.ts`、`frontend/src/views/system/PermissionTree.vue`、`frontend/src/views/system/permissionTree.ts`、`frontend/src/api/role.ts`、`frontend/src/api/menu.ts`、`backend/api/roles.py`、`backend/api/menus.py`、`backend/api/resources.py` | `run change` 按命中调用；`run e2e-rbac` 显式执行 |
  | `e2e-schedule` | `frontend/src/views/data/ScheduleView.vue`、`backend/api/data_admin.py`、`backend/scheduler/*`、`frontend/e2e/quality-repair-schedule.spec.ts`、`frontend/e2e/schedule-dependency.spec.ts`、`frontend/e2e/schedule-frequency-sort.spec.ts`、`frontend/src/api/data.ts`、`backend/api/data_tasks.py` | `run change` 按命中调用；`run e2e-schedule` 显式执行 |
  | `e2e-tasks` | `frontend/src/views/data/IngestView.vue`、`frontend/src/views/data/taskLogs.ts`、`backend/api/data_admin.py`、`frontend/e2e/stock-ingest-management.spec.ts`、`frontend/e2e/task-center-polling.spec.ts`、`frontend/src/api/data.ts`、`backend/api/data_tasks.py` | `run change` 按命中调用；`run e2e-tasks` 显式执行 |
  | `e2e-ladder` | `frontend/src/views/LimitLadderView.vue`、`frontend/src/views/limit-ladder/*`、`frontend/src/api/limitLadder.ts`、`frontend/src/stores/limitLadderSession.ts`、`backend/api/limit_ladder.py`、`backend/services/limit_ladder*`、`backend/storage/limit_ladder_task_repository.py`、`frontend/e2e/helpers/limitLadder.ts`、`frontend/e2e/limit-ladder.spec.ts`、`frontend/e2e/limit-ladder-analysis.spec.ts`、`frontend/e2e/limit-ladder-preferences.spec.ts`、`frontend/e2e/limit-ladder-task-center.spec.ts` | `run change` 按命中调用；`run e2e-ladder` 显式执行 |
  | `e2e-stocks` | `frontend/src/views/StockDetailView.vue`、`frontend/src/views/StocksView.vue`、`frontend/src/views/BoardView.vue`、`frontend/src/components/StockAnalysisPanel.vue`、`frontend/src/components/stock-chart/*`、`frontend/src/components/StockChartSettingSection.vue`、`frontend/src/api/stocks.ts`、`frontend/src/composables/useStockChart*`、`frontend/src/composables/useLegacyStockChartPreferenceMigration.ts`、`frontend/src/composables/useRelatedBoardFirstLoad.ts`、`frontend/src/layout/stockChartRatioProfiles.ts`、`backend/api/stocks.py`、`backend/devtools/e2e_market_data.py`、`frontend/e2e/stock-detail-chart-workspace.spec.ts` | `run change` 按命中调用；`run e2e-stocks` 显式执行 |
  | `e2e-trade-ui` | `frontend/src/views/TradeDisciplineView.vue`、`frontend/src/views/trade-discipline/**/*`、`frontend/src/components/trade-discipline/*`、`frontend/src/api/tradeDiscipline.ts`、`frontend/src/api/tradeLedger.ts`、`frontend/src/composables/useTradeDiscipline*`、`frontend/e2e/trade-discipline-history.spec.ts`、`frontend/e2e/trade-discipline-quick-card.spec.ts`、`frontend/e2e/helpers/tradeDiscipline.ts` | `run change` 按命中调用；`run e2e-trade-ui` 显式执行 |

  纯 Markdown 的轻量集合：`secrets`、`quality`；仍执行登记、文档生成块和依赖锁校验。
  必须保留完整检查的 Markdown 输入：`AGENTS.md`、`CLAUDE.md`、`README.md`、`DESIGN.md`、`agent-works/configurable-layout-system/page-template.md`、`agent-works/configurable-layout-system/responsive-components.md`、`agent-works/configurable-layout-system/responsive-pages.md`、`agent-works/testing/guide.md`、`agent-works/e2e-automation/guide.md`。
  <!-- ci-inventory:end -->

## 核心机制

### 机制：常用与专项的统一调用

- 目标与入口：

  默认入口为 `scripts/run-ci.sh run`；具体执行 `scripts/run-ci.sh run backend`、`run database` 或 `run frontend`。`PYTHON` 可指定已安装项目依赖的解释器，脚本默认 `python3`，不加载 `.env.local`。 日常定向开发继续使用原 pytest/Vitest/物理 runner；CI 入口用于完整验收、登记套件的隔离执行及报告核验，不由服务启动或普通测试隐式调用。

- 处理与结果：

  `ci.yml` 在规划阶段执行文档/登记和锁源指纹检查，`prepare change` 调用同一 `plan common` 和 `assess`，选择常用集合及命中的必要专项，以矩阵并行调用 `ci-suite.yml`。依赖条件详见下文；手动指定套件始终执行。总状态 `result` 用 `always()`，审计入选时先按同一 `requirements-ci.lock` 及哈希安装验证依赖，随后下载计划、执行回执和实际报告，调用正式 `result` 命令；审计报告核对依赖 `packaging` 解析锁中的平台条件，不能假设干净 Python 自带该包。规划、任一套件失败/取消、必要回执缺失均失败。本地完整变更验收先专项后常用，记录各项结果，失败不伪造其它项通过；中断保持非零并保留已生成证据。`change` 的纯 Markdown 轻量模式仅选择登记的质量和密钥套件，仍经同一计划、回执和最终汇总；显式 `common` 不受该减量影响。

- 数据、权限与状态：

  GitHub 只授予仓库读取权限，后端/数据库/E2E job 使用临时 PG/Redis，其他 job 不启动业务存储。同分支旧 CI 可取消。为兼容既有绑定，push / PR 和手动 `change` 的最终状态继续名为 `CI common result`，现在同时要求命中的专项证据完整。显式手动 `common` 与单专项使用 `CI suite <套件> result`，不能以同名状态覆盖完整变更结果；每日审计同样是单套件状态。直接推主分支后失败不会自动回退代码；分支必过状态须在 GitHub 核对并绑定完整常用状态，代码不自动修改远端设置。

- 配置与扩展：

  手动运行 `CI` 时 `suite` 填 `change`、`common` 或登记名；手动 `change` 还须提供起点完整 SHA `base_revision`，终点固定为所选分支实际被测提交。不使用容易漏维护的固定选项列表。`backend-scale` 必须显式填写 `scale_stocks=100..5000`；本地示例：`scripts/run-ci.sh run backend-scale --scale-stocks 1000`。`change` 从 `backend-scale.scale_stocks` 读取代表性规模，当前为 1000；显式规模模式仍要求传参。规模模式只选择登记的规模用例，不重跑整套常用测试；其中两个既有参数用例仍固定为 1000/5000 股，输入数量只控制读取环境参数的用例。

- 失败与资源边界：

  未知套件、失效登记、过期文档/锁直接失败。GitHub 每个检查最多 30 分钟，不用自动重试掩盖断言失败；前端 JSON、Python JUnit、覆盖率、安全报告与隔离存储日志归档 7 天。有回执的执行写入 Git 忽略的 `.local/tmp/ai-agent/ci-results-{unique}/`；远端各矩阵使用同一 run ID / attempt 的目录名合并，原始诊断位于其 `artifacts/<套件>/ci-{unique}/`。直接调用底层门禁仍使用原独立目录。入口输出实际目录；退出后保留供排错或上传，可按临时产物清理，不作为长期依赖。

- 局部风险与复核：

  常用 CI 包含全量前端离线测试、生产构建、安全扫描及覆盖率测量；已登记的浏览器 E2E 套件与规模回归按 `change` 命中条件调用，也可显式执行；`manual-e2e` / `manual-market` 仍须按各自指南单独验证。真实来源核验、覆盖率百分比门槛及生产规模达标判定不能由 common 或固定材料专项通过推断为已验收。

### 机制：前端完整回归与构建

- 目标与入口：

  统一执行器调用 `npm --prefix frontend run ci`；`frontend/scripts/run-ci.mjs` 复用正式 `build` 脚本和 `test:ci` 测试协议。`npm run check` 与 `test:contracts` 继续用于本地共享设计快检，不作为完整 CI 的第二次重复执行。

- 处理与结果：

  正式 build 先执行设计静态检查、`vue-tsc` 和 Vite 构建，各一次；构建目标为本轮独立目录，不覆盖 `frontend/dist`。随后 `vitest.ci.config.ts` 继承主 Vitest 配置的 `src/**/*.{test,spec}.ts`，包括布局、组件、指令、页面、API、store、router、工具和 composable 中的现有测试。

- 数据、权限与状态：

  前端测试使用确定性材料，不依赖在线后端、真实行情或业务数据库。需要真实浏览器或业务存储的检查按专项准入单独编排；不能因普通测试夹具不完整就跳过。

- 配置与扩展：

  新增普通前端测试只需进入主配置的命名和目录范围，无逐文件白名单。CI 显式禁止 `only` 和空集合，不接受额外筛选参数，测试重试为 0，工作进程最多 2 个。类型、构建与离线测试都由同一入口执行。

- 失败与资源边界：

  执行器核对 JSON 报告成功标志、用例总数、通过数及逐项状态，失败、skip/todo、空集合、缺失或不完整报告均失败。报告写入独立目录，构建产物在成功和失败后均清理；退出码由统一总入口传播。

- 局部风险与复核：

  `frontend-ci-collection.spec.ts` 在独立夹具中真实调用 package 脚本和 CI 配置，证明深层业务测试自动接入，并验证失败、skip/todo、only、空集合与筛选参数负例。全树静态集成用例需解析生产源码，按共享 `fullSourceAudit.ts` 使用 120 秒有界预算，仅由显式扫描完整生产源码树的用例使用，包括页面注册表递归核对真实组件消费、通过公共函数或预收集文件集合间接遍历的检查；新增同类用例复用该预算，同类全树检查共用预算。样式门禁按 CSS 规则预解析选择器，再逐个匹配真实消费者，避免每个节点重复拆分规则；排除条件仍按各节点分别判断，并以违规反例验证复用前后结果一致。普通单测维持默认时限，断言、违规反例和扫描对象不变；此预算不作为业务性能达标阈值。单元测试和构建仍不能替代真实浏览器交互、页面几何及真实业务闭环验收。

### 机制：常用静态质量检查

- 目标与入口：

  `quality` 是登记表中的常用套件，执行 `ci_quality.run_quality()`；本地和 GitHub 复用同一入口。

- 处理与结果：

  先通过当前 Python 执行 `ruff check backend`，再检查 `.github/workflows/` 中全部 YAML 工作流。Ruff 使用项目当前默认规则，不额外放宽或全局排除；actionlint 校验工作流结构和表达式，不隐式依赖可选 ShellCheck/Pyflakes。

- 数据、权限与状态：

  检查只读取受控源码与工作流，不访问业务存储；工具下载仅访问官方固定版本发布资源。

- 配置与扩展：

  Ruff 固定版本由 `requirements-quality.txt` 维护，后端 CI 锁复用该文件；actionlint 和 Gitleaks 的固定版本统一在 `ci_tools.TOOLS` 维护，共用官方 SHA-256 核验、安全提取及原子缓存安装，运行前核对版本。

- 失败与资源边界：

  工具缺失且无法准备、校验和或版本不符、空工作流集合、Ruff 或 actionlint 非零退出均失败；Ruff 失败后不继续执行工作流检查，不把不可执行状态当作通过。

- 局部风险与复核：

  `test_ci_quality.py` 覆盖失败传播、全部工作流收集、空集合、下载校验和及安全提取；它不替代依赖漏洞或密钥泄漏扫描。

### 机制：密钥扫描与精确例外

- 目标与入口：

  常用 `secrets` 调用 `ci_secrets.run_secrets()`；`run secrets-history` 显式检查已获取的全部 Git 历史，供首次历史基线和事件调查使用，不混入每次常用扫描。

- 处理与结果：

  通过 `git ls-files` 收集受控文件和未被忽略的新文件，复制到独立快照后执行固定 Gitleaks 默认规则；符号链接只扫描链接文本，不读取外部目标。随后扫描已识别的提交范围，能拦截提交后又删除的材料。范围未知时扫描当前提交，完整历史仍须专项；Actions 使用完整 checkout。

- 数据、权限与状态：

  忽略个人环境、业务库和依赖缓存，测试目录正常扫描。扫描显式覆盖自定义配置/忽略文件，不接受散落的 `gitleaks:allow`。日志与 JSON 报告通过 `--redact=100` 脱敏；临时源码快照在正常/异常退出后删除，不上传源码副本。

- 配置与扩展：

  唯一例外登记为 `config/ci-security-exceptions.json`，每项绑定精确路径、规则 ID、命中原始行的 SHA-256、原因及 UTC 到期日期。目前仅登记固定离线测试材料。内容变化、规则变化、到期、重复或失效登记均须重新审查，不自动续期，不排除整个测试目录。

- 失败与资源边界：

  新发现、无效/过期例外、工具异常、超时、空受控集合或缺失报告均失败。扫描器用独立发现退出码区分工具错误；处理脱敏报告中的发现并应用精确例外后才决定总结果，禁止把工具失败当成无泄漏。

- 局部风险与复核：

  真实探针必须证明深层新增测试文件及范围内新增后删除的密钥均阻断，报告不包含探针值。模式扫描不能保证识别所有未知凭据；实际密钥泄漏需要轮换和事件处置，删除文件不能消除历史暴露。

### 机制：可重现依赖与条件审计

- 目标与入口：

  `ci_dependencies.py` 维护 CI 锁和审计，`dependency-audit` 复用同一登记、规划器和执行器。push、PR 的 common 在依赖变化时调用；每日和手动显式选择该套件，不运行全套 common。

- 处理与结果：

  `ci_changes.py` 读取 push 的 before/after 或 PR 共同祖先与 head，校验提交对象；比较时覆盖删除、重命名两侧及本地未提交/新文件。非默认分支首次 push 的 `before` 为零 SHA 时，只有事件明确为创建分支且未删除、默认分支元数据及引用合法、`origin/<默认分支>` 已获取并存在共同祖先，才以该共同祖先和 head 确定完整范围，覆盖首推的全部提交。默认分支自身首推、标签、缺失引用或无共同祖先仍保持未知，不退回 HEAD 的单个父提交。命中登记中的 `dependency_paths` 时审计；范围缺失或浅克隆缺对象时保守审计。本地可传 `--base <完整SHA> --head <完整SHA>`；显式零 SHA 不借事件元数据修正，不传范围时完整常用包含审计。

- 数据、权限与状态：

  `requirements-ci.lock` 固定 Python 3.12 的跨平台发行版本和 SHA-256；Actions 后端/数据库/审计均用 `pip install --require-hashes -r requirements-ci.lock`。执行回归前按当前平台核对实际安装版本。pip-audit 审计同一锁的版本，并核对报告集合；npm audit 读取 `frontend/package-lock.json`，包含开发依赖并显式访问官方 npm 审计接口。私有镜像或代理不支持审计时，可为本轮进程将 `NPM_CONFIG_USERCONFIG`、`NPM_CONFIG_GLOBALCONFIG` 指向两个不同的独立空文件，并按网络实际条件移除失效代理；不修改全局 npm 配置，查询仍失败则阻断。只查询，不调用自动修复。

- 配置与扩展：

  `scripts/run-ci.sh lock` 使用固定 uv 递归编译源清单，默认保留已锁版本；定向升级用 `lock --upgrade-package <包名>==<已核实版本>`。源指纹递归覆盖 include，修改任何源清单而未重建锁会在规划阶段失败。前端的 js-beautify 下 glob/editorconfig 定向 overrides 修复传递漏洞，受 Node 22.12+ 约束；上游解除旧范围后再评估移除，并执行完整回归。

- 失败与资源边界：

  全部严重级别的已知漏洞、查询失败、工具失败、未审计项、报告缺失及 Python 审计集合漂移均阻断；不使用全局忽略、自动升级或只扫描生产依赖来减少告警。每个审计进程最多 300 秒，不把网络不可达解释为零漏洞。

- 局部风险与复核：

  公开漏洞数据库会变化，依赖不变也可能使每日审计失败；应核实公告、选择修复版本并验证兼容性。平台相关依赖按实际执行平台计算锁标记；macOS 本地通过不能替代 Linux Actions 验收，下载产物时也应按远端平台的依赖清单复核。工具升级或清单规则变化须覆盖真实漏洞/错误报告及变更识别正反例。

### 机制：随常用回归输出覆盖率

- 目标与入口：

  前端 CI 用匹配 Vitest 的 V8 provider，后端及 CI 数据库门禁显式加载 pytest-cov；复用本轮测试执行，不为报告再跑第二遍。

- 处理与结果：

  前端输出 JSON 明细、summary 和 LCOV；Python 的后端与数据库套件分别输出 JSON、XML 和终端摘要，比较基线须保持套件和平台一致，不相加百分比。前端 `coverage.include` 包含未导入的业务 TS/Vue 文件，Python 测量 `backend`；测试与声明文件不计业务覆盖率。报告均保存在本轮独立目录。

- 数据、权限与状态：

  覆盖率只观察离线/隔离回归，不连接真实业务环境，不改变既有断言、跳过策略或专项分流。Python 测量本轮 pytest 进程，未对所有派生 CLI/进程池声称完整测量。

- 配置与扩展：

  前端范围在 `vitest.ci.config.ts`，Python 公共配置在 `pyproject.toml`，参数和报告验收由 `ci_coverage.py` 共用。新增普通业务文件自动进入相应分母；基线先用于定位关键模块缺口，不设置全仓库统一百分比硬门槛。

- 失败与资源边界：

  测试失败继续失败；测试通过但报告缺失、损坏或测量集合为空也失败。覆盖率数据文件写入独立目录；前端生产 dist 仍按原机制清理，诊断报告归档。

- 局部风险与复核：

  覆盖率百分比不代表断言有效性，也不替代权限、业务、浏览器和真实来源验收。后续模块门槛须依据测量、业务风险和测试补齐情况单独决定，不能通过缩小分母达标。

### 机制：专项必检范围与实际执行证据

- 目标与入口：

  `scripts/run-ci.sh assess` 生成影响清单；`plan change` 生成矩阵；`prepare change --results-dir <独立目录>` 保存 `ci-plan.json`；`run change --results-dir <独立目录>` 按同一计划实际执行；`result --results-dir <同目录>` 重新核验报告。仅跑常用时继续 `run common`，它的通过不能充当完整变更验收。需要多个提交时显式传 `--base <完整SHA> --head <完整SHA>`，计划与各次执行使用相同范围。

- 处理与结果：

  `impact_paths` 是领域影响路径的唯一登记；所有浏览器组自动继承顶层 `e2e_impact_paths` 的共享执行/装配规则，新增组无需复制基础设施路径。`assess.required_specials` 只表示必跑计划，初始状态 `not-executed`。`change` 合并常用与命中的专项；`ci_results.execute()` 在原执行器外记录 `receipts/<套件>.json`，不另写测试执行逻辑。`reconcile()` 按登记重新核对计划，再检查回执、进程退出及原始报告，生成 `ci-result.json`、`ci-result.md` 和 GitHub 摘要，逐项显示必跑、通过、失败或未执行。

- 数据、权限与状态：

  源码身份包含当前实际被测 commit（PR 可为合并提交）及全部受控/未忽略新文件内容摘要，覆盖未提交、删除和新文件；符号链接只读取链接文本。回执绑定该身份、变更范围和规模参数，并记录报告相对路径与 SHA-256。源码执行中变化、报告修改、路径越界或归属不匹配均失败。报告复制到远端合并目录后仍按同一相对路径验收；矩阵局部计划不会覆盖总计划。每次使用独立结果目录，重跑使用新目录，不能覆盖第一次失败回执。

- 配置与扩展：

  资产搜索、设置偏好、系统权限树、调度与任务等既有关键路径按领域拆成较小检查组，复用现有基础浏览器或关联 runner 接入；未整合文件保留手动设计/几何验证；已接入范围以生成表为准。具体文件、原因、`review_status` 与必要 `impact_paths` 只维护在登记表。未整合文件须明确 `review_status=manual-design|migration-required`，关键业务对应文件须登记影响路径，不能继续使用无具体前提的泛化原因。直接改动未整合测试，或命中其已登记业务路径时，完整验收明确列为 `pending_checks` 并失败；不能把登记为待迁移当成通过。其余手动呈现边界仍按 E2E 指南由维护者判断，自动路径匹配不能替代语义审查。路径匹配是自动选组，远端执行该组登记的固定文件/项目集合；本地一般业务验证才按 E2E 指南选择最小路径，原生聚焦结果不自动替代 CI 回执。

- 失败与资源边界：

  必跑回执缺失、旧版本、错误参数、非零退出、异常、报告缺失/损坏、空集合、跳过、重试或计划删项都不能通过。范围未知时保守列出专项与未整合检查，完整变更验收保持未完成，先补可验证的变更范围。常用的条件审计不能被省略；显式单套件结果只声明该套件范围。执行器退出恢复原服务和临时存储的协议保持不变；未恢复也失败。

- 局部风险与复核：

  `test_ci_results.py` 通过真实 CLI、子进程和原报告协议证明漏跑、损坏、版本不符、过期清单、错误执行器和未接入业务路径被拒绝；`test_ci.py` / `test_ci_e2e.py` 保留收集与报告负例。每次后端/规模执行保存实际 nodeid 清单，规模 JUnit 保存行数、请求数、耗时和内存；数据量/生产容量门槛、真实来源与部署恢复尚不由本机制证明。远端配置生效仍须推送后验证，分支规则是否阻止合并以 GitHub 实际设置为准。

  | 改动影响 | 必须完成的验证 | 范围判定 |
  | --- | --- | --- |
  | Playwright/CI E2E 配置、共享 helper、物理夹具 runner、生命周期或报告判定 | 受影响的已登记 E2E 专项，并验证失败/清理/恢复出口 | 共享执行基础设施变化允许完整受影响组；项目和用例以实际收集清单为准 |
  | 登录、鉴权/路由接线、缓存返回、权限可见命令、跨页状态、真实提交及持久化回读 | 低层回归之外，按 E2E 指南执行受影响的最小浏览器关键路径 | 本地一般业务修改按准入选择最小路径；远端按登记整组执行，未接入 CI 的用例按指南单独验证并保留证据 |
  | 分时、估值、股本/历史质量修复的批量 SQL、分批、并发、进度持久化或数据量复杂度 | `backend-scale` 的代表性真实服务/落表/重跑回归 | 显式选择 100..5000，记录实际股票、日期、行数及固定参数；不能以小夹具替代规模风险 |
  | 纯文档、注释、无浏览器装配影响的纯计算或局部呈现 | 按开发验证规范选择差异、低层测试或临时呈现复核 | 不机械增加 E2E；不适用或复用证据的依据写入当次交付 |

### 机制：隔离浏览器专项与既有 runner 复用

- 目标与入口：

  `scripts/run-ci.sh run <登记的 e2e 套件>` 执行上表的对应范围（例如 `run e2e-trade`），最终调用 `ci_e2e.run_e2e()`；GitHub 的 `change` 条件矩阵或手动运行同一套件，通过 `kind=e2e` 准备 Node、Python CI 锁、PG 16、Redis 和 Chromium。范围只从登记生成，不开放任意 grep/project 参数给 CI 总入口。

- 处理与结果：

  沿用现有 `run-playwright.sh`、板块/走势关联/交易纪律 runner 和公开回测 helper，先真实 `--list` 保存 `e2e-planned.json`，再执行并保存 `e2e-actual.json`、HTML、trace/screenshot/video 及 `e2e-execution.json`。`playwright.ci.config.ts` 继承主配置，固定单 worker、零重试、禁止 only、独立产物和不复用前端服务；每个登记文件及项目均须收集到用例，再逐项核对计划/实际 test id 与项目相等，全部 passed 才成功，防止两份报告同时少跑。

- 数据、权限与状态：

  复用临时 PG/DuckDB/Redis 上下文与正式初始化，清除继承的业务连接及 E2E 目标。后端固定本机 8000，前端复用既有 `E2E_WEB_PORT`，优先 5181、被占用时申请独立空闲端口并记录 `base_url`，不复用或停止已有预览。调试账号、物理夹具和实时 PG 指纹仍走既有守卫；公开回测独立启用 DuckDB 只读，文件缓存/锁也位于本轮临时目录。本机存在健康空闲且可信的 dev/test/local 服务时先快照、停服，专项成功/失败后恢复原运行方式；未知环境、异常服务或未知后端端口占用拒绝执行，不能接管未知进程。

  CI 空库行情入口 `e2e_market_data.seed_ci_market()` 只接受与调用方一致的 `e2e-backtest` / `e2e-stocks` 隔离身份；写入前检查行情、证券、指标、ST、基准和日历表均为空，任一已有材料直接拒写。事务内准备两只固定证券、181 个自然日的日历及其中交易日的日线、逐日市值和准确 ST，异常全部回滚。公开回测保留原 `e2e_backtest_runs.seed_ci_market()` 薄入口及中证 500 基准；个股图表追加沪深 300 基准，不依赖本机行情或在线接口。公开回测后端继续切换只读，通过正式 `BacktestService.run_strategy()` 撮合并写 PG；个股专项的用户/偏好仍由正式 PG 及既有实时指纹守卫管理，不伪造记账或权限结果。非 CI 本地公开回测夹具仍只读已准备的行情。

  天梯与交易纪律界面使用固定材料：`e2e-ladder` 复用四个既有脚本及 `helpers/limitLadder.ts`，筛选、导出、状态、分析返回和任务结果使用确定性接口材料，业务偏好及布局用户层默认值由正式 PG 保存、回读和恢复；这些固定材料不证明真实天梯计算或任务执行。`e2e-trade-ui` 验证账户日结、历史修订、部分规则确认和当前导航结构，使用共用 `helpers/tradeDiscipline.ts` 构造完整账本 DTO 并提供交易日；它只证明页面消费和提交参数。真实账本、成交流水、修正及撤回仍由 `e2e-trade` 的独立物理夹具证明。

  个股专项使用当前图表与偏好接口：`e2e-stocks` 复用 `run-playwright.sh` 和完整的既有图表脚本，在标准项目执行全部路径；跨页返回、局部失败重试、当前 SVG 图表、两栏空间适配、最小权限、偏好回退与两名临时用户的真实 PG 隔离各按实际用例判定。模拟偏好按页面分别隔离，避免前一用例改写后端调试账号影响后续路径；真实隔离用例仍使用正式接口创建、核对和销毁 UUID 用户。组件默认值统一保存布局用户层，业务筛选保留用户偏好，恢复默认分别核对两者，不按旧偏好结构推断保存成功。

  共享布局和偏好接口是跨页输入：`backend/api/layout.py`、`backend/storage/layout_config.py`、`backend/api/user_preferences.py` 和 `backend/storage/user_preference.py` 变化会选择全部已登记浏览器专项，防止只验证接口而漏掉跨页消费者。运行期布局读取与数据库升级的边界由 [前端布局实现](frontend-layout.md) 维护，常用后端回归同时检查读取请求不会重新执行市场库全量升级。

- 配置与扩展：

  文件及归属唯一登记在 `special_files`，runner 与项目选择在对应套件的 `e2e` 字段维护。三个物理 runner 共用 `e2e-backend-lifecycle.sh::run_e2e_playwright()`：本地保留原默认 spec，CI 不再追加硬编码文件过滤，只消费登记生成的配置，防止新增登记却少跑。交易纪律消费当前账户/成交/日结模型：标准视口执行历史、写入、初始化、快捷卡、规则及权限链路，默认视口执行壳层未保存协议。固定账户写入只执行一次，项目筛选来自登记，实际报告不得包含 skip。不删除断言、不把运行时 skip 计为通过。更多页面/视口仍按 E2E 指南准入，不把已登记执行入口称为完整设计验收。

- 失败与资源边界：

  空集合、实际少跑/多跑、skip、预期失败、flaky、重试、报告缺失或汇总不一致均失败。关闭本轮服务及文件锁后才销毁临时存储，再恢复日常服务；清理或恢复失败同样失败，保留必要运行档案。产物与专项结果随 Actions 归档 7 天；通过只证明报告中已实际执行的范围。

- 局部风险与复核：

  `test_ci_e2e.py` 覆盖有效与违规报告、项目漂移、重复/缺失用例、端口归属及服务恢复；真实浏览器结果以对应专项产物为准。`manual-e2e` 文件尚未通过该执行器运行，不能由已整合专项通过推断这些文件、三视口全量或真实来源闭环已验收。E2E 原生准入、选择器和本地夹具操作细节只维护在 [E2E 指南](../e2e-automation/guide.md)。

### 机制：后端与数据库的共用隔离环境

- 目标与入口：

  `run_backend()` 与 `database_gate.run_gate()` 共用 `isolated_environment.isolated_storage_environment()`。`gate_server()` 默认启动独立 PG 集群；显式管理连接 `AI_STOCKS_DB_GATE_ADMIN_DSN` 只供执行器和数据库夹具创建/删除随机测试库，不能作为业务客户端连接。

- 处理与结果：

  共用上下文创建随机 PG 数据库、只监听 Unix socket 的临时 Redis、临时 DuckDB 路径及 YAML，在子进程导入配置前设置全部默认目标。普通 `PostgresClient()`、`get_pg_client()`、`get_client()` 和公共 `pg` / `redis_cli` 夹具均落在这些临时资源。后端套件先调用正式 `initialize_database()` 再运行业务回归；数据库套件保留空库、新装和升级夹具各自的前置状态。

- 数据、权限与状态：

  子进程剥离全部继承的 `AI_STOCKS_*`、`ENV` 和 `PYTEST_*`，再生成测试身份、密码、配置加密密钥和连接；关闭邮件发送，移除本机 E2E/来源凭据。测试可修改全局配置，因为目标是可销毁的独立库。临时 PG/Redis 生命周期归执行器所有，不停止或重启日常后端。

- 配置与扩展：

  后端与数据库执行均需要 `redis-server`，以及本机 `initdb/pg_ctl` 或显式测试管理连接。普通 `backend/tests/test_*.py` 自动发现、默认进入 `backend`；文件级专项在导入前排除，参数级专项在收集后按精确 nodeid 分流。专项表中的 nodeid 失效会失败，避免改名后静默丢覆盖；不要用宽泛文件名匹配排除新业务。

- 失败与资源边界：

  PG/Redis 缺失、初始化失败或清理失败直接失败；复用 `database_gate_plugin` 的严格结果判定，任何未预先分流的 skip/xfail/xpass、空集合或外部取消选择都失败。插件加载和继承的 `-k/-m/--lf` 被清除。setup/call/teardown 失败立即输出阶段、nodeid 与错误栈，后续中断也保留已发生的现场；没有完整报告仍不能通过。退出关闭子进程、连接、随机 PG 库及临时目录；Redis 不开放 TCP、不持久化。

- 局部风险与复核：

  调度时间回归使用明确的北京时间与来源时区材料，跨任务并发回归等待可观察的槽位就绪；来源频率读取共享准入时间，用同步屏障证明请求等待可重叠，不把线程返回时刻、主机墙钟或进程启动速度当作业务预期。改变时间边界时还须在 UTC 等非北京时间进程中复验，并显式覆盖 PG 会话时区；仅设置测试子进程的 `TZ` 不代表已改变先前启动的数据库时区。业务时间语义见[任务运行态](task-runtime.md)。登记的 `manual-market` 为遗留 `test_api.py`，需要已准备的真实行情和前端产物，当前没有可自动调用的专项 CI；按本地服务保护要求准备后单独运行，不能把常用 CI 通过解释为这组已通过。`not-applicable` 仅排除 PG 迁移用例的 DuckDB 参数，其 PG 参数仍常用必跑。普通手动 pytest 的离线 skip 行为不因此改变。

### 机制：数据库专项复用

- 目标与入口：

  `scripts/run-ci.sh run database` 最终调用已有 `database_gate.run_gate()`；`./start.sh database gate` 继续有效，两者不刷新结构契约。

- 处理与结果：

  执行数据库专题规定的新装、冻结旧库升级、重跑、数据保留、负例、故障回滚及真实 CLI/目录验收；具体通过条件和结构维护步骤由该专题定义。

- 数据、权限与状态：

  业务数据库不作为门禁目标；不把隔离新装成功当成某个业务实例已升级。刷新机器契约仍是显式 `database gate --refresh-contract`，CI 不执行刷新。

- 配置与扩展：

  数据库相关变更沿数据库接入流程扩展 `test_database_lifecycle.py`，或把新增测试文件登记到 `database`。`gate_test_paths()` 消费同一登记表并执行这些文件；常用后端在导入前分流，常用 CI 调用数据库专项。执行器统一加载 `backend.tests.database_fixtures`：`databases` 提供每例未初始化的独立双库，`installed` 提供正式初始化后的双库。新装、升级或故障回滚测试按前置状态选择这两个夹具；普通客户端回归可复用公共夹具，仍受共用默认隔离保护。用例不得显式指定业务 DSN 或业务文件路径。Python 用例不能登记到前端执行器，文件级和用例级专项不得重叠。

- 失败与资源边界：

  资源管理和严格结果判定沿用上述共用协议；需要 PG >=14，GitHub 使用 PG 16。新文件接入必须验证真实执行和临时目标，失败后也要清理，不只检查登记表中存在路径。

- 局部风险与复核：

  线上权限、容量、备份及实际存量数据库验收仍由部署维护和 `database check` 承接。

### 机制：纯 Markdown 变更的轻量分流

- 目标与入口：

  `ci.assess()` 和 `ci_results.change_matrix()` 为 `change` 选择 `profile=markdown|standard`；沿用 push/PR、本地 `run change` 和最终汇总，不另建 workflow 或执行器。

- 处理与结果：

  只有已知、非空、全部为 `.md` 且不命中 `markdown_only.full_ci_paths` 的变更才减量；执行 `markdown_only.suites` 中的原密钥、质量套件。登记、生成块和锁指纹仍在执行前校验。代码混改、删除/重命名涉及非 Markdown 文件、符号链接、未知范围或登记的专项/人工要求均保留标准检查。显式 `run common`、`run frontend` 等范围不减量。

- 数据、权限与状态：

  轻量集合不启动业务存储或浏览器，也不记录它们通过。回执、源码和报告摘要、退出码及缺项判定与其他模式相同；JSON 和摘要明确轻量范围。结果汇总只在入选审计时安装完整锁依赖，其余报告核验使用 Python 标准库。

- 配置与扩展：

  轻量集合必须保留常用的质量与密钥检查，受保护的 Markdown 输入只在同一登记表维护。`DESIGN.md`、README、AI 入口、页面模板、响应式登记及验证指南分别承担机器输入、可执行示例或执行约束，保留完整检查。新增 Markdown 消费方须同步保护登记；`test_ci_markdown.py` 检查代码中可静态定位的现有 Markdown 输入，CI 自身文档由原 `check_document()` 校验生成块；动态路径仍须语义审查。

- 失败与资源边界：

  缺少轻量策略时回退标准集合；无效策略、失败/缺失回执、损坏报告或篡改计划仍失败。规划时的 `profile` 在最终验收重新计算，不能给代码改动手填轻量标记。范围不明时不推断为纯文档；新分支首推只有按前述默认分支共同祖先规则取得可验证范围后才参与分类，否则沿用未知范围规则。

- 局部风险与复核：

  `test_ci_markdown.py` 验证纯说明、程序输入、混改、未知/空范围、重命名、登记优先级和正式入口的成功/失败报告。远端复验选择已有分支上的纯说明 Markdown 提交，核对规划集合、实际回执和最终状态，并分别保留代码提交的完整变更验收结果。轻量仅证明所选检查完成，文档语义、引用和事实仍按全局文档规范审查。

## 接入、扩展与变更影响

- 消费与接入方式：

  首次按 `requirements-ci.lock` 安装 Python 依赖，前端执行 `npm ci`，本机准备 `initdb/pg_ctl/redis-server`。`PYTHON` 可指定解释器；CI 入口不加载 `.env.local`。`scripts/run-ci.sh check` 校验登记/文档生成块/锁指纹，`assess` 查看影响，`plan` 仅规划；这些命令不证明测试通过。

  日常开发先按[开发验证规范](../testing/guide.md#验证选择与完成条件)选择定向测试或原生 runner。需要完整变更验收时使用 `run change --results-dir <独立目录>`；仅验证常用集合用 `run common`；复核已有同源码报告用 `result --results-dir <同目录>`。多个提交显式提供同一 `--base <完整SHA> --head <完整SHA>`，计划与执行范围一致。手动 `change` 在 GitHub 还须提供 `base_revision`，被测终点固定为所选分支提交。

- 扩展与兼容边界：

  1. 普通后端 `test_*.py`、前端 `src/**/*.{test,spec}.ts` 自动发现；新增行为仍由维护者编写有效断言。数据库文件、专项例外和 E2E 的物理夹具归属按精确文件/nodeid 登记，不能通过改名、宽泛排除或登记为空绕过执行。原生快检继续消费 `vitest.contracts.config.ts`。
  2. 新套件登记 `kind/common/description`；同类复用原执行器，新增执行器类型同步 `registry()`、`run_suite()` 和 `ci-suite.yml` 的环境准备。新 E2E 自动继承共享影响规则，维护领域入口、消费者、项目/标题和固定材料；新增可静态定位的 Markdown 输入同步完整验证登记。
  3. 登记修改后执行 `docs --write`、`check`；生成命令只维护生成块。Python 源清单变化时重建锁、按锁安装并审计；npm 清单/补丁变化同步锁并验证正式 `npm ci`。安全例外精确绑定固定材料和复核期限，不由 CI 自动增补或续期。
  4. 验证受影响的常用/专项实际收集与执行，执行器改动复核失败、跳过、空集合、取消选择、报告损坏和恢复出口。以“变化契约 → 断言 → 执行入口 → 本轮证据”核对覆盖；不能以登记存在或常用绿色替代必要专项。

- 依赖及消费方影响：

  套件和路径登记同时驱动本地、远端和生成表。CI 机制更新本文，项目指南维护本地选择与命令，E2E 指南维护原生准入及物理生命周期；所属领域正文维护业务语义。

  | 维护事项 | 自动检查 | 维护者补充 |
  | --- | --- | --- |
  | 普通测试和归属 | 自动发现，精确分流，失效登记或不完整执行失败 | 有效断言、夹具和真实消费覆盖 |
  | 专项与 Markdown 选择 | 按共享/领域路径和保护规则选组，重新计算计划 | 新入口和动态消费的影响边界 |
  | 文档和锁 | 生成块及源指纹漂移失败 | 正文事实、兼容与依赖升级验证 |
  | 证据 | 源码、范围、参数及原报告逐项对账 | 未编码需求、必要人工呈现和真实环境边界 |

  push/PR 验收分别核对事件、源提交与实际被测提交（PR 可为合并提交）、规划矩阵、总状态及产物；不能以旧提交或另一事件的绿色替代。GitHub 必过规则须读取实际绑定；直接推主分支后失败不会回退已推代码，CI 通过也不代表已配置合并拦截。现有门禁不自动提交修复、刷新契约或创建新调度。表末五项缺口保持待处理，未实现能力不注册空套件；满足各自验收条件并有实际证据后才能关闭。

## 验证入口与已知限制

| 验证或风险事项 | 条件与入口 | 证据状态及位置 | 结果或影响 | 后续处理 |
| --- | --- | --- | --- | --- |
| 常用及专项编排 | `scripts/run-ci.sh plan/check/run` | 执行器、登记与 workflow | 同一分类驱动本地和远端 | 每次交付记录实际运行范围与结果 |
| 自动接入与失败关闭 | `test_ci.py` | 规划、环境清洗、生成块、专项分流及 Pytest 负例 | 防止漏接入或跳过冒充成功 | 变更机制时定向回归 |
| 数据库生命周期 | `scripts/run-ci.sh run database` | 既有数据库门禁 | 验证代码安装与升级契约 | 实际实例另验收 |
| GitHub 执行及分支规则 | 推送后查看 Actions 与仓库设置 | 本地运行不能替代远端证据 | 服务镜像、权限和平台可能影响执行 | 首次推送后确认各矩阵及总状态 |
| 前端与静态质量 | `run frontend`、`run quality` | 完整前端配置、报告判定、构建、Ruff、actionlint | 自动发现和实际执行均须有证据 | 执行器及收集范围变化时验证正反例 |
| 安全与锁漂移 | `run secrets`、`run dependency-audit`、`check` | 脱敏扫描/审计报告、`test_ci_security.py` | 新发现、查询失败、过期例外和清单漂移均阻断 | 定向修复后复验；每日重新查询依赖漏洞 |
| 覆盖率度量 | `run frontend/backend/database` | 本轮 JSON / LCOV / XML | 有效非空报告必须生成，百分比先作基线 | 按关键模块缺口补用例后再决定门槛 |
| TestClient 兼容性 | Python CI 锁中的 Starlette / httpx | 当前回归可用；Starlette 提示 TestClient 的 httpx 支持弃用 | 警告保持可见，不作为测试失败或跳过处理 | 后续升级测试工具时核实 httpx2 迁移并回归客户端契约 |
| 专项选择与执行证据 | `prepare/run change`、`result` | 必跑计划、源码/报告摘要、回执、nodeid 与 E2E 报告 | 缺项、失败或版本/参数不符使整体未完成；常用与完整变更范围明确区分 | 维护登记及适用路径，执行命中专项并从原入口验收 |
| 交易纪律账户日结 E2E | `run e2e-trade` | 当前 `TradeLedgerWorkspace`、正式日结服务生成的固定夹具及计划/实际报告 | 验证账户初始化、真实买卖与资金流水、保存失败保留、持仓回读、修正不累加、撤回追溯、版本历史、快捷入口、规则、权限与未保存保护 | 改动[当前业务契约](trade-discipline.md)时同步夹具与断言；归属、模型或项目变化后实际复验，不能以 common 通过替代 |
| <a id="专项缺口登记"></a>CI-GAP-01：剩余设计、多视口 E2E 整合 | 后续按风险单独接入 | 缺口（待处理）；登记表中仍有 7 个 `manual-e2e` 文件，保留手动设计验证，尚未接入严格 CI；文件及原因见本文生成表，不计作已通过 | 现有常用及已接入专项通过不代表完成 | 按风险复核现行设计契约、夹具和适用视口，复用现有入口接入对应专项；核对计划与实际用例，拒绝跳过、重试和不完整报告 |
| CI-GAP-02：每周规模自动运行 | 后续按风险单独接入 | 缺口（待处理）；`backend-scale` 已支持手动及相关变更调用；`ci.yml` 当前定时触发仅执行每日依赖审计，尚无每周规模任务 | 现有常用及已接入专项通过不代表完成 | 复用现有规模入口与登记参数接入周任务，实际验证触发、规模、正确性、耗时和资源证据及失败汇总；代表性规模回归不代替生产容量判定 |
| CI-GAP-03：真实来源与数据质量在线核验 | 后续按风险单独接入 | 缺口（待处理）；固定材料和已有本地行情检查不能证明当前外部接口可用或实际来源数据质量；尚无统一接入的在线核验专项 | 现有常用及已接入专项通过不代表完成 | 明确来源、数据范围和核验窗口，默认小范围只读，记录来源响应与数据质量结果；不可用、失败和未完成如实列出，采集修复写入另走获批流程 |
| CI-GAP-04：干净环境安装与部署验证 | 后续按风险单独接入 | 缺口（待处理）；已有构建、隔离数据库及开发模式 E2E；尚未统一验证另一台干净机器按项目指引安装、配置、初始化并以生产托管模式完整运行 | 现有常用及已接入专项通过不代表完成 | 在独立环境按真实部署指引执行安装与启动，验证健康检查、前端制品及代表性接口；配置、环境前提和失败诊断可复核，不写入业务实例 |
| CI-GAP-05：实际备份恢复演练 | 后续按风险单独接入 | 缺口（待处理）；数据库 gate 已验证新装、升级和结构契约，尚未统一安排真实备份文件的还原及业务回读；不能由安装成功推断恢复成功 | 现有常用及已接入专项通过不代表完成 | 在隔离测试实例准备并还原备份，核对数据完整性、约束、租户归属和代表性业务回读，验证恢复后实例健康；保留备份版本、环境与验收证据 |
