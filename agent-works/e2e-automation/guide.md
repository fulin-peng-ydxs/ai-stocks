# E2E 自动化验证规范

Playwright 用于少量、稳定、浏览器独有的关键用户路径回归。

参考：[通用验证与总维护清单](../testing/guide.md) · [项目与服务命令](../../AGENTS.md) · [UI 测试锚点](../../DESIGN.md#75-自动化测试锚点) · [环境身份与运行模式](../architecture/environment-configuration.md#环境身份与运行模式) · [测试账号](../multi-tenant-rbac/test-users.md)。

`frontend/playwright.config.ts` 固定测试目录 `frontend/e2e/`、端口 `5181` 和 trace/screenshot/video 策略。登录、数据预置、偏好读写和控制台收集复用 `frontend/e2e/helpers/`；修改流程时核对配置、helper 与相关入口的一致性。

## Playwright 准入条件

新增 E2E 必须同时满足以下条件；任一不满足时，使用领域/服务/API 测试、Vitest、构建或交互式浏览器复核：

- 风险只有在真实浏览器装配后才能可靠暴露，低层测试无法等价覆盖。
- 路径跨越至少两个稳定边界，例如路由与返回现场、权限与可见命令、浏览器存储与重新进入、真实表单提交与页面终态。
- 路径属于高价值主流程，失败会阻断用户完成业务，而不是样式、文案或局部控件细节。
- 相关业务规则、接口状态和组件分支已经在更低层测试覆盖；E2E 只补浏览器集成缺口。
- 用例可使用确定性数据和稳定选择器长期重复执行，不依赖参数顺序、临时正文、共享可变偏好或不稳定外部数据。

用户明确要求 Playwright 或自动化回归时可以直接使用，但仍须先完成对应的低层业务验证，不得把 E2E 结果写成业务正确性结论。

已有 E2E 路径的契约受改动影响时应同步更新断言，但是否立即执行仍按本节准入和风险判断；需要执行时只运行单项目、单 spec 或 `--grep` 命中的最小路径，只保留最短主路径和必要断言。“已有覆盖”不构成新增场景、运行模块整组或多视口回归的理由。

## 禁止滥用

- 禁止用 E2E 验证计算公式、停牌/缺失判定、数据覆盖率、任务去重、重试次数、并发互斥、事务发布和后端异常映射；这些属于领域、服务、API 和真实数据链路。
- 禁止为纯样式、文案、字段对齐、参数顺序、局部排序函数、单组件显隐或一次性缺陷复现新增长期 E2E；分别使用视觉复核、Vitest 或更低层测试。
- 禁止只用接口 Mock 的页面用例宣称真实采集、计算、落表或恢复闭环已通过。需要证明闭环时必须执行代表性真实入口，并核对真实终态。
- 禁止一个用例堆叠多个无关功能、重复验证低层已经覆盖的分支，或仅为提高覆盖数量增加断言。
- 禁止每次页面交付默认跑模块整组、全量、多视口或完整设计 E2E。只有发布门禁、共享基础设施变更、全局设计改造或用户明确要求时才执行；一般改动即使需要 E2E，也只跑受影响的单文件、单项目和必要视口。

## 运行入口与生命周期

### 按范围选入口

| 目的 | 在 `frontend/` 下执行 | 执行范围 |
|---|---|---|
| 首次安装浏览器 | `npm run test:e2e:install` | 仅浏览器缺失时执行 |
| 普通关键浏览器路径 | `npm run test:e2e -- <spec> --project=chromium-standard --grep='<用例名>'` | 仅满足准入的最小路径；需已准备好被测后端和对应测试账号 |
| 板块路径 | `npm run test:e2e:sectors -- --project=chromium-standard --grep='<用例名>'` | 专用 runner 管理板块夹具；无需过滤参数的三 spec / 三视口整组只用于发布或明确要求 |
| 关联板块路径 | `npm run test:e2e:stock-board-correlation` | 专用 PG + DuckDB 夹具回归；可透传 spec、project 或 grep 缩小范围 |
| 交易纪律路径 | `npm run test:e2e:trade-discipline` | 专用 PG + DuckDB 夹具回归；可透传筛选参数 |
| 完整设计验收 | `npm run test:design` | 安全前检、全量 Vitest、构建，再执行五组 E2E；只在完整验收准入时使用 |

E2E 命令须显式带 `AI_STOCKS_ENV=dev|test|local AI_STOCKS_E2E_WRITE=1`，例如：

```bash
cd frontend
AI_STOCKS_ENV=dev AI_STOCKS_E2E_WRITE=1 npm run test:e2e:sectors -- --project=chromium-standard --grep='<用例名>'
AI_STOCKS_ENV=dev AI_STOCKS_E2E_WRITE=1 npm run test:design
```

`test:design` 的前置检查只校验调用方环境、写开关和本机目标地址，不请求在线后端；原后端运行或停止均可。后续 `scripts/run-design-e2e.sh` 负责启动与健康/PG 指纹核对，按普通读写用例 → 板块 → 关联板块 → 交易纪律 → 公开回测只读五组串行运行。禁止自行 seed 多种固定日期夹具再把全部 spec 放进一轮回归。

`test:e2e` / `test:e2e:ui` 只经 `scripts/run-playwright.sh` 加载 `.env.local` 并透传 Playwright 参数，不管理物理夹具或后端恢复；不能用其无筛选全量运行代替总入口。完整验收只允许默认 `http://127.0.0.1:8000/api`，防止本机夹具与远端 API 错配；普通不涉及物理夹具的聚焦验证可按实际目标设置 `E2E_API_URL`。

### 夹具与服务保护

| 场景 / CLI 夹具 | 唯一可写范围 | 运行约束 |
|---|---|---|
| 板块 `./start.sh e2e-board-data seed\|cleanup` | `E2E9*` 板块、`9999*.SZ` 股票、2099 年行情 | 后端停服时独占 DuckDB，复用 `scripts/run-sector-e2e.sh` |
| 关联板块 `./start.sh e2e-stock-board-correlation seed\|cleanup --expected-pg-fingerprint <指纹>` | PG `default/debug_system` 下 `e2e_sbc_*` 方案/快照/任务；DuckDB `9977*.SZ`、`E2ECORR_*`、`E2E相关-*`、2097 年行情/冠军 | PG 目标与在线后端指纹一致，后端停服时 seed/cleanup；runner 校准账号、检查两库零残留 |
| 交易纪律 `./start.sh e2e-trade-discipline seed\|cleanup --expected-pg-fingerprint <指纹>` | PG `debug_tenant` 下 `debug_normal`、只读、独立提交及租户管理员账号的 `e2e_td_` / `E2E纪律-` / `E2E类型-`；DuckDB `9988*.SZ`、2098 年交易日 | 后端指纹、直连 PG 和调用方环境一致；停服执行，复用 `scripts/run-trade-discipline-e2e.sh` |
| 公开回测 `./start.sh e2e-backtest-run seed\|cleanup --expected-pg-fingerprint <指纹>` | 固定调试账号归属的 `e2e_bt_` 公开回测、opaque run_ref 及对应复用审计 | 夹具独占 DuckDB 写锁，被测后端须 `AI_STOCKS_DUCKDB_READ_ONLY=1`；由完整验收总入口单独编排 |

以上表格说明物理边界，不是日常手动 seed 的替代流程。PG 写夹具和临时用户须在 DDL/账号写入前比对后端实时 PG 指纹；不得使用空值、未知环境、生产/共享目标或未确认归属进行清理。账号校准沿用 `./start.sh dev-users`，需要保留密码时使用 `--keep-password`；自动写账号须传同一可信指纹。

- Playwright 固定前端 `5181`，后端由 `./start.sh` 管理。板块、关联板块和交易纪律 runner，以及完整设计总入口，在后端原本运行时先校验空闲并保存可信运行档案；档案缺失或 PID 不匹配时须在停服前拒绝执行。
- 成功、失败或中断后精确清理本组夹具；原本运行则通过 `restore-runtime` 恢复原模式、变量文件、安全开关及 PG 目标，原本停止则保持停止。清理或恢复失败必须返回失败，不得固定重启为普通 dev；板块 runner 停服或恢复失败时保留原运行档案并报告路径，供后续恢复。
- 多视口密集登录使用 `AI_STOCKS_E2E_LOGIN_BYPASS=1`，仅在本地环境及物理写开关同时成立时放开 login 的 IP 限流；专用 runner 自动管理。回归后恢复原安全开关，禁止遗留豁免。共享固定账号、板块自选和偏好时使用 `--workers=1`。
- `frontend/playwright-report/` 为 Git 忽略的本地产物，截图经 `testInfo.attach()` 进入报告；对外归档由 CI 或发布流程保存整个目录，不提交哈希附件。
- 控制台统一由 `frontend/e2e/helpers/console.ts::collectConsoleIssues()` 收集并阻断 error 与 warning；预期 HTTP 失败使用 `allowedHttpStatuses` 精确声明，不复制监听器或私自放宽口径。

## 选择器规则

- 具有稳定可访问语义的唯一元素优先使用 role + 可访问名称；例如登录页与应用外壳的共享品牌字标统一用 `getByRole('img', { name: '复盘啦' })` 验证，不为同一组件再造场景 test id。其余关键实例使用 `data-testid`，通过 `getByTestId` 和项目 helper 定位，复用组件已有锚点。
- 禁止在长期用例里使用坐标、深层 CSS 结构、DOM 顺序或容易变动的说明文案。
- 新增或修改页面关键交互时，同步检查是否需要补充或调整测试锚点。

## 调试账号

- 页面权限验收使用 `debug_*` 账号，账号事实源为 `agent-works/multi-tenant-rbac/test-users.md`；交易纪律使用 `debug_normal`、`debug_trade_discipline_view`、`debug_trade_discipline_submit`、`debug_board_only`、`debug_tenant_admin` 和 `debug_system` 覆盖全功能、只读、独立提交、无权与默认管理员边界。
- E2E 登录 helper 默认使用 `debug_normal`，密码读取顺序：Playwright 进程继承的 `AI_STOCKS_TEST_USER_PASSWORD`、本地 dev-users 默认值；`.env.local` 由统一启动脚本在 Playwright 进程创建前加载。
- 账号不存在或权限漂移时，由对应专用 runner 校准。普通聚焦 E2E 需单独准备账号时，按上方 PG 指纹前提执行 `AI_STOCKS_ENV=dev ./start.sh dev-users --expected-pg-fingerprint <被测后端实时指纹>`；需要保留已有密码时追加 `--keep-password`。

Playwright 失败时先看 trace/screenshot/console，不直接改产品代码迁就测试；若是选择器不稳定，优先补稳定锚点或 helper。

## 现有用例索引

本节只记录已有资产，方便选择最小回归范围；不构成新增 E2E 或执行全量回归的要求。

- `frontend/e2e/limit-ladder.spec.ts`、`limit-ladder-analysis.spec.ts`、`limit-ladder-preferences.spec.ts` 与 `limit-ladder-task-center.spec.ts`：连板天梯完整回归。共享 `helpers/limitLadder.ts` 的确定性接口夹具，三档桌面与单独 768 视口使用 `debug_system` 真实登录，覆盖组合筛选、短历史、CSV、首次计算与互斥状态、重算轮询、分析/详情返回、偏好闭环，以及任务完成/中断状态、结构化快照/coverage 摘要和控制台告警阻断；截图作为 Playwright 报告附件。
- `frontend/e2e/component-state-preview.spec.ts`：三视口验证系统组件四态预览共用稳定容器、非 ready 态真实复用 `AppStateBlock`，并通过审计空表接口夹具确认表格只呈现一套全局空态图标、业务文案与操作，不嵌套第二套 `el-empty`。
- `frontend/e2e/login-initial-render.spec.ts`：登录页首帧与表面回归。三项目刷新 `/login`，通过页面脚本记录真实 DOM 挂载过程，确保首次路由与鉴权守卫就绪前不会挂载工作台壳；同时验证登录品牌区、认证区和卡片在白天/夜间使用与工作台一致的固定中性底色。
- `frontend/e2e/app-shell-surfaces.spec.ts`：应用外壳底色回归。三项目验证白天与夜间模式下侧栏、顶栏和主工作区使用原型固定中性色，并通过真实视觉环境切换确认预设不会改写基础背景。
- `frontend/e2e/page-settings-drawer.spec.ts`：验证每日榜单页面设置抽屉「恢复默认」会清除 `user_preference(global/settings-drawer)` 中的抽屉自身偏好，并回到默认尺寸。
- `frontend/e2e/sectors-workbench.spec.ts`：板块行情与详情长期回归。三视口覆盖首屏排行、指数基准、周期缩放、自选、对比、K 线、量能、详情高度与分隔条、跨菜单状态保持、成分股跳转及返回；标准视口额外覆盖搜索、排序、分页、列显隐/恢复默认和 `debug_sectors_only` 最小权限 fail-closed。
- `frontend/e2e/sector-quality-recovery.spec.ts`：标准视口以确定性接口夹具覆盖数据质量主动刷新失败后由错误态接管且不残留旧记录，以及 `board_member_incomplete`「重采成分」提交、任务成功轮询和问题列表收敛。
- `frontend/e2e/stock-detail-chart-workspace.spec.ts`：个股行情分析与详情三图长期回归。标准视口先覆盖个股查询远端业务默认值水合、抽屉默认值单向驱动主区、主区切换不反写长期默认、展开分析区时行点击切换当前股票及收起后恢复详情跳转，并覆盖每日榜单走势对比/K线模式切换和显式详情入口；详情页继续串行覆盖默认 K线/量能/MACD、图名、最小权限与路由守卫、MACD 局部失败/重试、辅助图交换/隐藏、指标快照模块显隐与图表自适应填满、pointer 与键盘调高、切股/刷新/重置恢复、偏好 403 本地 fallback，以及每次运行创建并销毁两名 UUID 化普通临时用户的真实 PG 隔离；三项目共同覆盖 1100×620、1366×768、1440×900 的布局、主题、reduced-motion、状态图层和截图附件，并断言柱宽按 K线、量能、MACD 递减、底部日期不被缩放滑块遮挡、标题颜色与折线一致、MA/VMA/MACD 折线消费盘感训练共享色相且在实际明暗背景可辨、任一图缩放后三图窗口同步、光标轴交易日气泡只在 K线显示一次、个股详情常驻行情摘要随 K 线光标更新并在移出后恢复最新读数，详情图内不重复显示行情 tooltip，以及真实画布悬停金叉/死叉标签时显示信号类型和完整交易日期。涉及临时用户的场景必须使用上文双重环境授权与 PG 指纹守卫，结束后确认 `e2e_%` 用户残留为 0。
