import { expect, test, type Locator } from '@playwright/test'
import { loginAsDebugUser } from './helpers/auth'
import { cleanupPublicBacktestRuns, seedPublicBacktestRun } from './helpers/backtestRuns'
import { collectConsoleIssues } from './helpers/console'
import { openPageAndWaitForHeading } from './helpers/navigation'

/** 轮询输入值直至连续两次采样一致（hydration 异步写表单完成），返回稳定值。 */
async function waitForStableValue(input: Locator, timeoutMs = 10_000): Promise<string> {
  const deadline = Date.now() + timeoutMs
  let prev = await input.inputValue()
  while (Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 200))
    const cur = await input.inputValue()
    if (cur === prev && cur !== '') return cur
    prev = cur
  }
  return prev
}

// R5/R6 回测页「浏览公开回测」抽屉（T5 决策4 硬验证项，T6 沉淀）：
// 用固定调试账号真实生成一条跨 owner 公开策略回测（含 DuckDB 撮合 + opaque run_ref），
// 覆盖 tenant/public 浏览脱敏、加载查看不写 mine、关闭恢复进入前表单、只读无删除入口。
// 复用重跑归「我的」+ loading + source_run_ref 审计：调试账号的实盘撮合成本与 DuckDB 锁
// 串行使该链路在 CI 浏览器层不稳定，已由后端真实 PG 回归（§6.8.19/§6.8.20）闭合。
test('回测页浏览公开回测：分段脱敏、加载查看不写 mine、关闭恢复表单、只读无删除', async ({ page, request }) => {
  test.setTimeout(90_000)
  const consoleIssues = collectConsoleIssues(page)
  const seeded = await seedPublicBacktestRun(request, { ownerAccount: 'debug_normal', visibility: 'public' })

  try {
    await loginAsDebugUser(page, request, 'debug_tenant_admin')
    await openPageAndWaitForHeading(page, '/backtest', '策略回测')

    const startInput = page.getByPlaceholder('开始')
    const endInput = page.getByPlaceholder('结束')
    await expect(startInput).toBeVisible()

    // 打开「浏览公开回测」抽屉：kind=backtest，tenant/public 段、无系统内置段。
    await page.getByTestId('backtest-browse-open').click()
    const drawer = page.getByTestId('backtest-run-drawer')
    await expect(drawer).toBeVisible()
    // 回测无系统内置段（无 is_preset）
    await expect(drawer.getByTestId('backtest-run-drawer-segment-preset')).toHaveCount(0)

    // 全体公开段：他人公开回测可见，来源/提供者脱敏，行操作=加载查看 + 复用参数重跑。
    await drawer.getByTestId('backtest-run-drawer-segment-public').click()
    const row = drawer.getByRole('row').filter({ hasText: '策略回测' })
    await expect(row.first()).toBeVisible()
    await expect(row.first()).not.toContainText('debug_normal')
    // 提供者脱敏为「同租户用户」（同租户他人）
    await expect(drawer).toContainText('同租户用户')
    await expect(row.first().getByTestId('backtest-run-drawer-load')).toBeVisible()
    await expect(row.first().getByTestId('backtest-run-drawer-rerun')).toBeVisible()

    // 加载查看：关闭抽屉、注入选择器外只读快照，**不写入 mine 候选、不自动运行**。
    // 基线在点「加载查看」前一刻取（与快照同一时机）：此时表单已经 hydration 与抽屉操作稳定，
    // 避免在页面刚打开、偏好 hydration 未完成时读到过渡态（三视口共享账号下 hydration 时机不确定）。
    const beforeStart = await waitForStableValue(startInput)
    const beforeEnd = await waitForStableValue(endInput)
    await row.first().getByTestId('backtest-run-drawer-load').click()
    await expect(drawer).toBeHidden()
    const externalChip = page.getByTestId('backtest-external-run')
    await expect(externalChip).toBeVisible()
    await expect(externalChip).toContainText('正在查看：')
    // 只读态：无「删除」入口（非本人公开记录 fail-closed）
    await expect(page.getByRole('button', { name: '删除', exact: true })).toHaveCount(0)

    // 关闭公开查看：原子恢复进入前表单日期，运行口径不留公开参数。
    await externalChip.getByLabel('关闭公开回测查看').click()
    await expect(externalChip).toBeHidden()
    await expect(startInput).toHaveValue(beforeStart)
    await expect(endInput).toHaveValue(beforeEnd)

    expect(consoleIssues).toEqual([])
  } finally {
    await cleanupPublicBacktestRuns(request, seeded.pgFingerprint)
  }
})
