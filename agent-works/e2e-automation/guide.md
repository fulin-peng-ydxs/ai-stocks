# E2E 自动化验证规范

Playwright 用于少量、稳定、浏览器独有的关键用户路径回归。

参考：[通用验证与总维护清单](../testing/guide.md) · [项目与服务命令](../../AGENTS.md) · [UI 测试锚点](../../DESIGN.md#75-自动化测试锚点) · [环境身份与运行模式](../architecture/environment-configuration.md#环境身份与运行模式) · [测试账号](../multi-tenant-rbac/test-users.md)。

`frontend/playwright.config.ts` 固定测试目录 `frontend/e2e/`、端口 `5181` 和 trace/screenshot/video 策略。登录、数据预置、偏好读写和控制台收集复用 `frontend/e2e/helpers/`；修改流程时核对配置、helper 与相关入口的一致性。

精确 CSS 几何断言统一使用 `helpers/auth.ts::installDisplayScaleBaseline()` 固定 100% 显示比例；登录后的认证快照已调用它，登录前测试须显式调用。自动比例策略仍由对应单测和显示比例专项验证，不能靠放宽像素断言掩盖测试基线差异。

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

### CI 专项入口

已整合的隔离 CI 专项、变更必检清单、文件归属登记和严格报告判据统一见 [CI 编排与持续维护](../architecture/continuous-integration.md#机制隔离浏览器专项与既有-runner-复用)。从仓库根目录执行 `scripts/run-ci.sh assess` 判断影响，`run e2e-shell`、`run e2e-sectors`、`run e2e-correlation`、`run e2e-trade` 或 `run e2e-backtest` 执行登记范围；GitHub 手动运行 `CI` 时填写同名 suite。

这些入口使用可销毁三库并复用下方 runner，无需把业务连接或密码交给 CI；本机会按可信档案暂时停止空闲测试后端并恢复，后端独占 8000，隔离前端优先 5181、被占用时通过既有 `E2E_WEB_PORT` 申请独立端口并记录实际 URL，不接管其它预览。直接执行下方本地 runner 时仍须满足其环境、写开关和 PG 实时指纹前提。新增 E2E 必须按 CI 专题登记物理夹具归属；`manual-e2e` 明确表示尚未整合，不能写成 CI 已通过。

已有套件只覆盖其收集报告中的文件、用例和项目；一般业务修改仍按准入选择最小路径，完整设计验收继续使用既有总入口。源码/条件变化后应重新验证受影响部分，交付分别记录应跑、实跑、通过/失败及未完成原因。

`e2e-trade` 使用当前账户、成交与日结流水，不再以旧逐规则打卡表或手选履约结果作为页面夹具。标准项目执行共享账户的业务及权限链路，默认项目执行未保存协议；CI 登记在收集前选择适用项目/标题，严格要求实际零跳过。覆盖及失败判据统一见 CI 专题的[交易纪律账户日结 E2E](../architecture/continuous-integration.md#验证入口与已知限制)。

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
| 板块 `./start.sh e2e-board-data seed\|cleanup` | `E2E9*` 板块、`9999*.SZ` 股票、2099 年行情及其截面日的准确 ST 固定事实 | 后端停服时独占 DuckDB，复用 `scripts/run-sector-e2e.sh`；ST 按专属代码及固定截面日清理 |
| 关联板块 `./start.sh e2e-stock-board-correlation seed\|cleanup --expected-pg-fingerprint <指纹>` | PG `default/debug_system` 下 `e2e_sbc_*` 方案/快照/任务；DuckDB `9977*.SZ`、`E2ECORR_*`、`E2E相关-*`、2097 年行情/冠军及行情日 ST 固定事实 | PG 目标与在线后端指纹一致，后端停服时 seed/cleanup；runner 校准账号、检查两库零残留 |
| 交易纪律 `./start.sh e2e-trade-discipline seed\|cleanup --expected-pg-fingerprint <指纹>` | PG `debug_tenant` 下四类固定账号的专属规则、账户及日结；规则使用 `e2e_td_` / `E2E纪律-` / `E2E类型-`，默认账户使用下述归属标记；DuckDB `9988*.SZ`、2098 年交易日及行情日 ST 固定事实 | 后端指纹、直连 PG 和调用方环境一致；停服执行，复用 `scripts/run-trade-discipline-e2e.sh` |
| 公开回测 `./start.sh e2e-backtest-run seed\|cleanup --expected-pg-fingerprint <指纹>` | 固定调试账号归属的 `e2e_bt_` 公开回测、opaque run_ref 及对应复用审计 | 夹具独占 DuckDB 写锁，被测后端须 `AI_STOCKS_DUCKDB_READ_ONLY=1`；由完整验收总入口单独编排 |

以上表格说明物理边界，不是日常手动 seed 的替代流程。PG 写夹具和临时用户须在 DDL/账号写入前比对后端实时 PG 指纹；不得使用空值、未知环境、生产/共享目标或未确认归属进行清理。账号校准沿用 `./start.sh dev-users`，需要保留密码时使用 `--keep-password`；自动写账号须传同一可信指纹。

交易纪律默认账户 ID 固定为 `default`，夹具以合成创建时点 `2098-06-02T00:00:00+08:00` 精确标记归属；seed/cleanup 遇到同归属的非夹具默认账户直接失败，不按 owner、空仓或缺少日结推断可覆盖。清理仅删除该标记账户及其日结/修订，其他账户和归属保持不动。独立提交账号预留未初始化账户用于真实页面初始化，其余账号通过共用账本服务生成四类历史和不可变修订；不手填评价或伪造日结快照。PG 可重入事务与 DuckDB 外层事务共同覆盖夹具失败回滚。

上述三组固定行情明确声明为非 ST，统一复用 `backend/devtools/e2e_market_data.py` 写入准确逐日事实；清理同时限定夹具来源、专属代码和固定日期。新增夹具按真实消费日期准备所需事实，不能只填 `daily_bar.is_st`，也不能在业务守卫中为 E2E 放行。

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

| 用例入口（`frontend/e2e/`） | 覆盖能力 | 特殊前提或范围 |
| --- | --- | --- |
| `limit-ladder.spec.ts`、`limit-ladder-analysis.spec.ts`、`limit-ladder-preferences.spec.ts`、`limit-ladder-task-center.spec.ts` | 天梯筛选、分析返回、偏好与任务状态 | `helpers/limitLadder.ts` 确定性接口夹具、debug_system；桌面项目及单独 768 视口 |
| `component-state-preview.spec.ts` | 系统组件四态、审计空表的唯一状态入口 | 三视口；空表接口夹具 |
| `login-initial-render.spec.ts` | 登录首帧、登录/工作台表面一致性 | 三项目、明暗主题；观察真实 DOM 挂载 |
| `app-shell-surfaces.spec.ts` | 外壳基础表面及预设切换 | 三项目、明暗主题 |
| `page-settings-drawer.spec.ts` | 设置抽屉恢复默认及远端偏好清除 | 每日榜单页面 |
| `sectors-workbench.spec.ts` | 板块工作台、图表、跨菜单状态与详情返回 | 三视口；搜索/分页/列偏好及最小权限在标准视口 |
| `sector-quality-recovery.spec.ts` | 质量刷新失败与成分修复反馈 | 标准视口；确定性接口与任务轮询夹具，不证明真实采集 |
| `stock-detail-chart-workspace.spec.ts` | 个股/榜单分析、三图联动、偏好与真实 PG 用户隔离 | 标准视口覆盖完整交互及用户隔离；三项目覆盖布局、主题和 reduced-motion |

图表用例每轮创建并销毁两名 UUID 临时普通用户，须满足本指南的环境、写开关和 PG 指纹守卫，结束后确认 `e2e_%` 用户零残留。具体断言、截图附件和视口分支以各 spec 为准；长期视觉契约见 DESIGN，索引不另维护断言副本。
