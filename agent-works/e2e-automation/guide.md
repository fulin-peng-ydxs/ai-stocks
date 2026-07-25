# E2E 自动化验证规范

## 目标

为后续 AI 页面开发提供稳定、可重复的浏览器验证流程。项目内长期回归走 Playwright；交互式浏览器工具用于临时复核和探索性排查。

## 文档入口与关联

- `AGENTS.md`：项目级执行红线，说明何时必须考虑 Playwright E2E，以及端口、后端启动和交付说明要求。
- `DESIGN.md`：UI 组件和 `data-testid` 锚点规范，说明哪些真实组件可以承载测试锚点，以及锚点不表达样式/业务状态。
- 本文件：E2E 执行流程、工具边界、沉淀触发条件和 helper 使用规则。
- `frontend/playwright.config.ts`：Playwright 运行配置，固定 `frontend/e2e/`、`5181`、trace/screenshot/video 策略。
- `frontend/e2e/helpers/`：登录、数据预置、偏好读写等长期复用 helper；新增 E2E 不重复手写登录态和接口 seed。
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
AI_STOCKS_ENV=dev AI_STOCKS_E2E_WRITE=1 ./start.sh restart
cd frontend && npm run test:e2e:install   # 首次或浏览器缺失时
cd frontend && AI_STOCKS_ENV=dev AI_STOCKS_E2E_WRITE=1 npm run test:e2e
# 回归结束后恢复日常后端，不保留 E2E 物理写开关：
cd .. && AI_STOCKS_ENV=dev ./start.sh restart
```

Playwright 固定使用前端 `5181`，避免抢占日常开发端口 `5173`；后端使用 `127.0.0.1:8000`，由 `./start.sh` 管理。
`npm run test:e2e` 和 `npm run test:e2e:ui` 均通过 `scripts/run-playwright.sh` 启动，
并复用 `scripts/load-local-env.sh` 加载仓库根目录 `.env.local`；因此登录密码和 PG/E2E
环境与后端使用相同的 `KEY=value` / `export KEY=value` 语义，不在 TypeScript helper 中二次解析变量文件。
涉及临时 PG 用户的用例会先读取后端 `/api/health/e2e` 的不可逆 PG 指纹，再通过
`./start.sh e2e-user` 创建/销毁用户；该入口与后端复用 `.env.local` 加载，且后端、Playwright
和夹具必须同时处于明确 dev/test/local 环境并启用 `AI_STOCKS_E2E_WRITE=1`。任一条件缺失、
PG 指纹不一致或后端运行中切换数据库时均 fail-closed，不执行物理清理。
`frontend/playwright-report/` 是本地忽略的可打开验收产物；用例通过 `testInfo.attach()` 附加的截图会进入该报告。需要对外归档时由 CI 或发布流程保存整个报告目录，不在业务提交中追踪哈希附件。

## 选择器规则

- 长期 E2E 优先使用 `data-testid`。
- 关键复用组件提供可选 `testId`，例如 `PageSegmented` 会输出容器和选项锚点。
- 禁止在长期用例里使用坐标、深层 CSS 结构、DOM 顺序或容易变动的说明文案。
- 新增或修改页面关键交互时，同步检查是否需要补充或调整测试锚点。

## 调试账号

- 页面权限验收使用 `debug_*` 账号，账号事实源为 `agent-works/multi-tenant-rbac/test-users.md`。
- E2E 登录 helper 默认使用 `debug_normal`，密码读取顺序：Playwright 进程继承的 `AI_STOCKS_TEST_USER_PASSWORD`、本地 dev-users 默认值；`.env.local` 由统一启动脚本在 Playwright 进程创建前加载。
- 账号不存在或权限漂移时，先执行 `AI_STOCKS_ENV=dev ./start.sh dev-users` 校准。

## 后续 AI 执行要求

- 改页面、抽屉、弹窗、配置面板、路由或权限入口时，先检查 `frontend/e2e/` 是否已有相关路径；已有则更新并运行相关用例，没有则按“必须沉淀为 Playwright 的条件”判断是否新增。
- 交付说明必须区分：已跑 Vitest、已跑 build、已跑 Playwright、仅做交互式浏览器临时复核、未执行及原因。
- Playwright 失败时先看 trace/screenshot/console，不直接改产品代码迁就测试；若是选择器不稳定，优先补稳定锚点或 helper。

## 当前基线用例

- `frontend/e2e/page-settings-drawer.spec.ts`：验证每日榜单页面设置抽屉「恢复默认」会清除 `user_preference(global/settings-drawer)` 中的抽屉自身偏好，并回到默认尺寸。
- `frontend/e2e/stock-detail-chart-workspace.spec.ts`：个股详情三图长期回归。标准视口串行覆盖默认 K线/量能/MACD、图名、最小权限与路由守卫、MACD 局部失败/重试、辅助图交换/隐藏、指标快照模块显隐与图表自适应填满、pointer 与键盘调高、切股/刷新/重置恢复、偏好 403 本地 fallback，以及每次运行创建并销毁 UUID 化 normal/paid 临时用户的真实 PG 隔离；三项目共同覆盖 1100×620、1366×768、1440×900 的布局、主题、reduced-motion、状态图层和截图附件，并断言柱宽按 K线/量能/MACD 递减、底部日期不被缩放滑块遮挡、标题颜色与折线一致及任一图缩放后三图窗口同步。涉及临时用户的场景必须使用上文双重环境授权与 PG 指纹守卫，结束后确认 `e2e_%` 用户残留为 0。
