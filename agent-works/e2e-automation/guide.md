# E2E 自动化验证规范

## 目标

为后续 AI 页面开发提供稳定、可重复的浏览器验证流程。项目内长期回归走 Playwright；交互式浏览器工具用于临时复核和探索性排查。

## 文档入口与关联

- `AGENTS.md`：项目级执行红线，说明何时必须考虑 Playwright E2E，以及端口、后端启动和交付说明要求。
- `DESIGN.md`：UI 组件和 `data-testid` 锚点规范，说明哪些真实组件可以承载测试锚点，以及锚点不表达样式/业务状态。
- 本文件：E2E 执行流程、工具边界、沉淀触发条件和 helper 使用规则。
- `frontend/playwright.config.ts`：Playwright 运行配置，固定 `frontend/e2e/`、`5181`、trace/screenshot/video 策略。
- `frontend/e2e/helpers/`：登录、数据预置、偏好读写和控制台问题收集等长期复用 helper；新增 E2E 不重复手写登录态、接口 seed 或 `page.on('console')`。
- `agent-works/multi-tenant-rbac/test-users.md`：`debug_*` 调试账号事实源。

后续修改上述任一文件影响自动化流程时，必须同步检查其余入口是否仍一致。

## 工具边界

| 场景 | 使用工具 | 要求 |
| --- | --- | --- |
| 已知关键业务路径、交付前回归、CI 候选 | Playwright E2E | 用例放 `frontend/e2e/`，通过 `npm run test:e2e` 执行；list reporter 实时输出，HTML reporter 在 `frontend/playwright-report/` 留存用例主动附件，失败另保留 trace/screenshot/video |
| 新问题复现、视觉细节确认、一次性探索、查看控制台 | 交互式浏览器工具 | 可临时点击和截图；若满足下方“必须沉淀为 Playwright”的条件，本次整改内补 Playwright 用例 |
| 纯 composable、合并逻辑、字段守门、错误分支 | Vitest | 不用浏览器替代单元测试 |

## 必须沉淀为 Playwright 的条件

不要使用“第几次人工复核”作为判断依据。AI 无法可靠知道全历史次数，必须按当前代码和任务事实判断。

满足任一条件时，本次改动必须复用、更新或新增 `frontend/e2e/` 用例；如果确实不能新增，交付说明必须写清楚原因和替代验证：

- 改动影响 `frontend/e2e/` 已覆盖路径，例如页面设置抽屉、登录后页面入口或已有 helper 使用链路。
- 用户明确要求“以后稳定执行”“自动化回归”“Playwright 验证”“不要只临时点页面”。
- 修复的是页面真实点击缺陷、审查复发现象、用户可感知的抽屉/弹窗/表格/表单/路由/权限入口问题。
- 改动涉及跨页面、跨用户、权限、远端存储、本地 fallback、迁移或重置闭环，并且需要浏览器验证才能确认业务成立。
- 新增或改造可复用页面组件，且该组件承载关键命令或配置项，会被多个页面消费。

只做一次性视觉观察、临时定位问题、读取控制台、确认不稳定实验路径时，可以只用交互式浏览器工具；但交付说明必须标注这是临时复核，不能写成已建立长期回归。

这里的“交互式浏览器工具”是工具中立概念，包括 AI 工具内置浏览器、人工浏览器操作、Chrome/浏览器扩展控制、一次性 Playwright 脚本等临时验证方式；它们不等同于项目长期回归资产。

## 固定命令

```bash
AI_STOCKS_ENV=dev ./start.sh dev-users
(cd frontend && npm run test:e2e:install)   # 首次或浏览器缺失时
# 板块发布链路聚焦回归：覆盖数据管理、质量恢复、工作台；脚本负责 seed/cleanup 与恢复服务
(cd frontend && AI_STOCKS_ENV=dev AI_STOCKS_E2E_WRITE=1 npm run test:e2e:sectors)
# 交易纪律聚焦回归：脚本取得/锁定 PG 指纹，管理 PG + DuckDB 夹具并恢复服务
(cd frontend && AI_STOCKS_ENV=dev AI_STOCKS_E2E_WRITE=1 npm run test:e2e:trade-discipline)
# 个股走势关联板块聚焦回归：脚本取得/锁定 PG 指纹，管理 PG + DuckDB 夹具并恢复服务
(cd frontend && AI_STOCKS_ENV=dev AI_STOCKS_E2E_WRITE=1 npm run test:e2e:stock-board-correlation)
# 普通全量回归前先在后端停服状态准备板块确定性数据
./start.sh stop
AI_STOCKS_ENV=dev AI_STOCKS_E2E_WRITE=1 ./start.sh e2e-board-data cleanup
AI_STOCKS_ENV=dev AI_STOCKS_E2E_WRITE=1 ./start.sh e2e-board-data seed
AI_STOCKS_ENV=dev AI_STOCKS_E2E_WRITE=1 AI_STOCKS_E2E_LOGIN_BYPASS=1 ./start.sh
(cd frontend && AI_STOCKS_ENV=dev AI_STOCKS_E2E_WRITE=1 npm run test:e2e -- --grep-invert '回测页浏览公开回测')
# 普通回归后停服并精确清理板块夹具
./start.sh stop
AI_STOCKS_ENV=dev AI_STOCKS_E2E_WRITE=1 ./start.sh e2e-board-data cleanup
# 单独跑公开回测前，将后端按下文切换为 DuckDB 只读：
AI_STOCKS_ENV=dev AI_STOCKS_E2E_WRITE=1 AI_STOCKS_E2E_LOGIN_BYPASS=1 AI_STOCKS_DUCKDB_READ_ONLY=1 ./start.sh
(cd frontend && AI_STOCKS_ENV=dev AI_STOCKS_E2E_WRITE=1 npm run test:e2e -- e2e/backtest-public-runs.spec.ts --workers=1)
# 回归结束后恢复日常后端，不保留 E2E 物理写开关：
AI_STOCKS_ENV=dev ./start.sh restart
```

Playwright 固定使用前端 `5181`，避免抢占日常开发端口 `5173`；后端使用 `127.0.0.1:8000`，由 `./start.sh` 管理。
全量多视口回归必须给后端启用 `AI_STOCKS_E2E_LOGIN_BYPASS=1`，仅单文件聚焦回归可不启用。
`backtest-public-runs.spec.ts` 必须与其余用例拆分：先用读写后端跑其余用例；再停止后端，以
`AI_STOCKS_DUCKDB_READ_ONLY=1`、`AI_STOCKS_E2E_WRITE=1` 和登录限流豁免启动只读后端，单独执行该 spec。
回归结束后始终按上方命令恢复日常后端，不能遗留只读、物理写或限流豁免开关。
三个板块聚焦 spec 均不读取开发者本地真实板块数据；`e2e_board_data.py` 只写入
`E2E9*` 板块、`9999*.SZ` 股票及 2099 年固定行情，并在后端停服时 seed/cleanup。
聚焦运行统一使用 `npm run test:e2e:sectors`，固定执行 `board-data-management.spec.ts`、
`sector-quality-recovery.spec.ts`、`sectors-workbench.spec.ts`；退出 trap 会精确清理并恢复测试前后端状态。三视口共享固定调试账号、板块自选和页面偏好，因此脚本固定 `--workers=1` 串行执行，禁止并行改写状态。
交易纪律聚焦运行统一使用 `npm run test:e2e:trade-discipline`。入口只在进程变量中保存
`/api/health/e2e` 返回的 PG 指纹，停服后把同一值显式传给 cleanup/seed；夹具仅写
`debug_tenant + debug_normal/debug_trade_discipline_view/debug_trade_discipline_submit/debug_tenant_admin`
归属下的 `e2e_td_`/`E2E纪律-`/`E2E类型-` 数据，以及 DuckDB 的 `9988*.SZ` 和 2098 年固定交易日。
被测后端以登录限流豁免和正常 DuckDB 读写模式启动，重启后必须复核指纹未变化；三视口
固定 `--workers=1`。无论通过、失败或中断，EXIT trap 都先停服、按可信指纹精确清理，
再恢复测试前后端运行/停止状态；未取得指纹时禁止尝试物理清理。账号校准必须把同一指纹
传给 `dev-users --expected-pg-fingerprint`，在 DDL 和账号写入前完成比对。若测试前后端正在运行，
入口先快照 `start.sh` 启动时生成的不含密钥运行档案；档案记录环境文件和其余项目环境变量的
不可逆摘要，退出时先核对摘要，再恢复原启动模式、Python 命令、环境文件、E2E/登录/DuckDB
安全开关，并复核恢复后的 PG 指纹；档案缺失、PID 不匹配或内容非法时在停服前拒绝执行，
不能猜测恢复为普通 dev。
`npm run test:e2e` 和 `npm run test:e2e:ui` 均通过 `scripts/run-playwright.sh` 启动，
并复用 `scripts/load-local-env.sh` 加载仓库根目录 `.env.local`；因此登录密码和 PG/E2E
环境与后端使用相同的 `KEY=value` / `export KEY=value` 语义，不在 TypeScript helper 中二次解析变量文件。
涉及临时 PG 用户的用例会先读取后端 `/api/health/e2e` 的不可逆 PG 指纹，再通过
`./start.sh e2e-user` 创建/销毁用户；该入口与后端复用 `.env.local` 加载，且后端、Playwright
和夹具必须同时处于明确 dev/test/local 环境并启用 `AI_STOCKS_E2E_WRITE=1`。任一条件缺失、
PG 指纹不一致或后端运行中切换数据库时均 fail-closed，不执行物理清理。
完整设计验收入口 `npm run test:design` 会在 Vitest、构建和 Playwright 之前请求同一
`/api/health/e2e` 契约；后端不可访问、业务码非 `0` 或 PG 指纹非法时立即停止，并提示使用
相同 `AI_STOCKS_ENV` 与 `AI_STOCKS_E2E_WRITE=1` 重启后端。单独运行前置检查或普通 Playwright
时可统一设置 `E2E_API_URL`；完整设计 E2E 会管理本机后端和物理夹具，为防止远端/本地目标
错配，仅允许默认 `http://127.0.0.1:8000/api`。Playwright 阶段由 `scripts/run-design-e2e.sh` 分组编排：
普通无物理夹具 spec 先共享读写后端串行执行；板块、关联板块、交易纪律分别复用各自专用
runner，在每组之间完成精确 seed/cleanup；公开回测最后切换 DuckDB 只读后端单独执行。
总入口会快照并恢复测试前后端运行参数，失败、中断和成功退出都不保留 E2E 安全开关或夹具。
`frontend/playwright-report/` 是本地忽略的可打开验收产物；用例通过 `testInfo.attach()` 附加的截图会进入该报告。需要对外归档时由 CI 或发布流程保存整个报告目录，不在业务提交中追踪哈希附件。

控制台问题统一通过 `frontend/e2e/helpers/console.ts::collectConsoleIssues()` 收集，默认同时阻断 `error` 和 `warning`。路由注入形成的预期 HTTP 失败必须通过 `allowedHttpStatuses` 显式声明；不得在用例内复制监听器、只检查 `error` 或私自放宽 warning 口径。

## 选择器规则

- 长期 E2E 优先使用 `data-testid`。
- 具有稳定可访问语义的唯一元素优先使用 role + 可访问名称；例如登录页与应用外壳的共享品牌字标统一用 `getByRole('img', { name: '复盘啦' })` 验证，不为同一组件再造场景 test id。
- 关键复用组件提供可选 `testId`，例如 `PageSegmented` 会输出容器和选项锚点。
- 禁止在长期用例里使用坐标、深层 CSS 结构、DOM 顺序或容易变动的说明文案。
- 新增或修改页面关键交互时，同步检查是否需要补充或调整测试锚点。

## 调试账号

- 页面权限验收使用 `debug_*` 账号，账号事实源为 `agent-works/multi-tenant-rbac/test-users.md`；交易纪律使用 `debug_normal`、`debug_trade_discipline_view`、`debug_trade_discipline_submit`、`debug_board_only`、`debug_tenant_admin` 和 `debug_system` 覆盖全功能、只读、独立提交、无权与默认管理员边界。
- E2E 登录 helper 默认使用 `debug_normal`，密码读取顺序：Playwright 进程继承的 `AI_STOCKS_TEST_USER_PASSWORD`、本地 dev-users 默认值；`.env.local` 由统一启动脚本在 Playwright 进程创建前加载。
- 账号不存在或权限漂移时，先执行 `AI_STOCKS_ENV=dev ./start.sh dev-users` 校准。

## 后续 AI 执行要求

- 改页面、抽屉、弹窗、配置面板、路由或权限入口时，先检查 `frontend/e2e/` 是否已有相关路径；已有则更新并运行相关用例，没有则按“必须沉淀为 Playwright 的条件”判断是否新增。
- 交付说明必须区分：已跑 Vitest、已跑 build、已跑 Playwright、仅做交互式浏览器临时复核、未执行及原因。
- Playwright 失败时先看 trace/screenshot/console，不直接改产品代码迁就测试；若是选择器不稳定，优先补稳定锚点或 helper。

## 当前基线用例

- `frontend/e2e/limit-ladder-task-center.spec.ts`：连板天梯 T5 任务中心承接回归。三视口使用 `debug_system` 真实登录，覆盖任务类型/状态筛选请求、系统来源标签、日志抽屉、快照与 coverage 摘要、控制台告警阻断，并把全页截图作为 Playwright 报告附件。
- `frontend/e2e/component-state-preview.spec.ts`：三视口验证系统组件四态预览共用稳定容器、非 ready 态真实复用 `AppStateBlock`，并通过审计空表接口夹具确认表格只呈现一套全局空态图标、业务文案与操作，不嵌套第二套 `el-empty`。
- `frontend/e2e/login-initial-render.spec.ts`：登录页首帧与表面回归。三项目刷新 `/login`，通过页面脚本记录真实 DOM 挂载过程，确保首次路由与鉴权守卫就绪前不会挂载工作台壳；同时验证登录品牌区、认证区和卡片在白天/夜间使用与工作台一致的固定中性底色。
- `frontend/e2e/app-shell-surfaces.spec.ts`：应用外壳底色回归。三项目验证白天与夜间模式下侧栏、顶栏和主工作区使用原型固定中性色，并通过真实视觉环境切换确认预设不会改写基础背景。
- `frontend/e2e/page-settings-drawer.spec.ts`：验证每日榜单页面设置抽屉「恢复默认」会清除 `user_preference(global/settings-drawer)` 中的抽屉自身偏好，并回到默认尺寸。
- `frontend/e2e/sectors-workbench.spec.ts`：板块行情与详情长期回归。三视口覆盖首屏排行、指数基准、周期缩放、自选、对比、K 线、量能、详情高度与分隔条、跨菜单状态保持、成分股跳转及返回；标准视口额外覆盖搜索、排序、分页、列显隐/恢复默认和 `debug_sectors_only` 最小权限 fail-closed。
- `frontend/e2e/sector-quality-recovery.spec.ts`：标准视口以确定性接口夹具覆盖数据质量主动刷新失败后由错误态接管且不残留旧记录，以及 `board_member_incomplete`「重采成分」提交、任务成功轮询和问题列表收敛。
- `frontend/e2e/stock-detail-chart-workspace.spec.ts`：个股行情分析与详情三图长期回归。标准视口先覆盖个股查询远端业务默认值水合、抽屉默认值单向驱动主区、主区切换不反写长期默认、展开分析区时行点击切换当前股票及收起后恢复详情跳转，并覆盖每日榜单走势对比/K线模式切换和显式详情入口；详情页继续串行覆盖默认 K线/量能/MACD、图名、最小权限与路由守卫、MACD 局部失败/重试、辅助图交换/隐藏、指标快照模块显隐与图表自适应填满、pointer 与键盘调高、切股/刷新/重置恢复、偏好 403 本地 fallback，以及每次运行创建并销毁两名 UUID 化普通临时用户的真实 PG 隔离；三项目共同覆盖 1100×620、1366×768、1440×900 的布局、主题、reduced-motion、状态图层和截图附件，并断言柱宽按 K线、量能、MACD 递减、底部日期不被缩放滑块遮挡、标题颜色与折线一致、MA/VMA/MACD 折线消费盘感训练共享色相且在实际明暗背景可辨、任一图缩放后三图窗口同步、光标轴交易日气泡只在 K线显示一次、只有 K线显示固定左上角且具备涨跌色的行情 tooltip，以及真实画布悬停金叉/死叉标签时显示信号类型和完整交易日期。涉及临时用户的场景必须使用上文双重环境授权与 PG 指纹守卫，结束后确认 `e2e_%` 用户残留为 0。
