# 连板天梯 T12 前端综合测试与视觉验收报告

## 1. 结论

- 前端全量 Vitest 共 995 项，全部通过。
- 连板天梯聚焦 Playwright 共 18 个项目用例，其中 10 项按目标项目执行通过，8 项依据用例内的串行视口约束跳过；没有失败项。
- 验收覆盖 768×1024、1100×620、1366×768、1440×900 四个要求视口，并额外保留 1920×900 宽屏等宽卡片截图。
- 页面覆盖首次计算、非交易日、五类数据未就绪原因、失败、过期旧快照、合法空、筛选空、403、窗口/一字板/热点/关键词组合筛选、短上市窗口、CSV、个人偏好、活动态重算、概念跳转、分析、详情返回、滚动恢复和任务中断态。
- 所有执行用例统一收集浏览器 `error` 与 `warning`，最终没有未放行的控制台问题。

## 2. 验证命令

```bash
cd frontend
npm test
npm run build
AI_STOCKS_ENV=dev npm run test:e2e -- \
  e2e/limit-ladder.spec.ts \
  e2e/limit-ladder-analysis.spec.ts \
  e2e/limit-ladder-preferences.spec.ts \
  e2e/limit-ladder-task-center.spec.ts \
  --workers=1
```

最终结果：

- Vitest：128 个测试文件、995 项测试全部通过。
- 构建：`vue-tsc -b && vite build` 通过，`frontend/dist` 已同步。
- Playwright：10 项通过、8 项按项目视口约束跳过；三档桌面项目均执行综合筛选/CSV/布局用例，标准项目额外串行执行状态矩阵、偏好、分析往返和 768 抽屉用例。
- 后端：验证结束后保持日常开发模式运行，`/api/health=200`。

## 3. 长期回归资产

| 路径 | 覆盖内容 |
| --- | --- |
| `frontend/e2e/helpers/limitLadder.ts` | 分析、状态和筛选用例共用的天梯结果、行情、重算、CSV 与请求记录夹具 |
| `frontend/e2e/limit-ladder.spec.ts` | 三档桌面组合筛选、短历史、CSV、控件/卡片几何，以及首次计算与全部互斥状态 |
| `frontend/e2e/limit-ladder-analysis.spec.ts` | system-only 重算、过期轮询、分析、概念跳转、详情返回、滚动锚点、1100 低高度、768 全宽抽屉和 1920 等宽卡片 |
| `frontend/e2e/limit-ladder-preferences.spec.ts` | 个人默认取消、失败回滚、保存、重新进入、URL 覆盖和恢复默认 |
| `frontend/e2e/limit-ladder-task-center.spec.ts` | 任务类型/完成与中断状态筛选、系统来源、快照/coverage 摘要和日志抽屉 |

## 4. 截图与交互验收

Playwright 报告和忽略目录 `frontend/test-results/` 中保留本次截图附件，包含三档桌面综合页面、卡片字段、1920 宽屏、详情返回、768 分析抽屉、偏好草稿和任务中心中断态。逐张复核确认：

- 筛选控件无重叠，板块默认三项完整显示，控件高度统一为 32px；1100 低宽允许工具栏按完整控件换行。
- 梯级宽度一致，所有卡片宽度差不超过 1px；单卡层在内容区居中，多卡层保持等宽排列。
- 行业/概念名称与数量之间存在明确分隔，卡片短历史信息不越界。
- 768 分析抽屉与 `LayoutHost` 页面内容边界等宽，Esc 关闭后恢复原卡片选中态。
- 任务中断态使用异常状态展示，并保留最后成功快照的 coverage 摘要与结构化日志。

交互式浏览器额外确认未登录直接访问 `/limit-ladder` 会进入登录页，未绕过鉴权；认证后的业务链路由 Playwright 使用真实 `debug_system` 登录完成，不以“需要登录态”为由跳过。

## 5. 复用、自审与阶段边界

- 已将分析用例内原有天梯 mock 抽取为共享 helper，新综合用例不重复实现登录、控制台收集、行情或结果构造。
- 产品代码只为互斥状态块增加稳定 `data-testid`，未新增页面私有组件、样式、业务状态或并行交互机制；无需更新 DESIGN 组件清单。
- 本阶段没有新增接口、权限码、菜单、配置、SQL、seed、环境变量、部署项或数据库写入逻辑；调试账号与偏好继续复用既有受控入口。
- 本阶段仅完成 T12，没有执行 T13 的 SQL 升级/回滚演练、最终开发留痕和发布自审。
