import { expect, test } from '@playwright/test'
import { loginAsDebugUser } from './helpers/auth'
import { collectConsoleIssues } from './helpers/console'
import { openPageAndWaitForHeading } from './helpers/navigation'

async function expectAdaptiveTableFillsContainer(
  page: import('@playwright/test').Page,
  testId: string,
) {
  const sizing = await page.getByTestId(testId).evaluate((table) => {
    const root = table as HTMLElement
    const parent = root.parentElement
    const header = root.querySelector<HTMLElement>('.el-table__header')
    const body = root.querySelector<HTMLElement>('.el-table__body')
    if (!parent || !header || !body) throw new Error(`表格 ${root.dataset.testid} 结构不完整`)
    return {
      rootWidth: root.getBoundingClientRect().width,
      parentWidth: parent.getBoundingClientRect().width,
      headerWidth: header.getBoundingClientRect().width,
      bodyWidth: body.getBoundingClientRect().width,
    }
  })

  expect(Math.abs(sizing.rootWidth - sizing.parentWidth)).toBeLessThanOrEqual(1)
  expect(sizing.headerWidth).toBeGreaterThanOrEqual(sizing.rootWidth - 1)
  expect(Math.abs(sizing.headerWidth - sizing.bodyWidth)).toBeLessThanOrEqual(1)
}

test('数据概览在 1100×620 保持固定摘要和可用主工作区', async ({ page, request }, testInfo) => {
  test.skip(testInfo.project.name !== 'chromium-compact', '低视口专项只在 1100×620 档位执行')
  const consoleIssues = collectConsoleIssues(page)
  await loginAsDebugUser(page, request, 'debug_system')
  await openPageAndWaitForHeading(page, '/data/overview', '数据概览')

  const summary = page.getByTestId('overview-summary')
  const quality = page.getByTestId('overview-quality-summary')
  const workspace = page.getByTestId('overview-workspace')
  const mixed = page.getByTestId('layout-mixed-region')
  const grow = page.getByTestId('layout-grow-region')
  await expect(summary).toBeVisible()
  await expect(quality).toBeVisible()
  await expect(workspace).toBeVisible()
  await page.getByRole('tab', { name: '数据资产' }).click()
  await expect(page.getByTestId('overview-asset-table')).toBeVisible()

  const geometry = await page.evaluate(() => {
    const rect = (testId: string) => {
      const node = document.querySelector<HTMLElement>(`[data-testid="${testId}"]`)
      if (!node) throw new Error(`缺少 ${testId}`)
      const box = node.getBoundingClientRect()
      return { top: box.top, bottom: box.bottom, height: box.height }
    }
    const main = document.querySelector<HTMLElement>('[data-testid="app-main-surface"]')
    const mixedRegion = document.querySelector<HTMLElement>('[data-testid="layout-mixed-region"]')
    if (!main || !mixedRegion) throw new Error('缺少布局根节点')
    return {
      summary: rect('overview-summary'),
      quality: rect('overview-quality-summary'),
      workspace: rect('overview-workspace'),
      grow: rect('layout-grow-region'),
      main: { scrollTop: main.scrollTop, bottom: main.getBoundingClientRect().bottom },
      mixed: { clientHeight: mixedRegion.clientHeight, scrollHeight: mixedRegion.scrollHeight },
    }
  })

  expect(geometry.summary.height).toBeGreaterThan(40)
  expect(geometry.quality.top).toBeGreaterThanOrEqual(geometry.summary.bottom)
  expect(geometry.workspace.top).toBeGreaterThanOrEqual(geometry.quality.bottom)
  expect(geometry.grow.height).toBeGreaterThan(100)
  expect(geometry.workspace.bottom).toBeLessThanOrEqual(geometry.main.bottom + 1)
  expect(geometry.main.scrollTop).toBe(0)
  expect(geometry.mixed.scrollHeight).toBeLessThanOrEqual(geometry.mixed.clientHeight + 1)
  await expectAdaptiveTableFillsContainer(page, 'overview-asset-table')

  await page.getByRole('tab', { name: '逐股分层体检' }).click()
  await expect(page.getByTestId('overview-stock-table')).toBeVisible()
  await expectAdaptiveTableFillsContainer(page, 'overview-stock-table')
  await expect(summary).toBeVisible()
  await expect(quality).toBeVisible()
  expect(consoleIssues).toEqual([])
})

test('数据概览两类表格在各桌面视口都自适应铺满内容区', async ({ page, request }) => {
  const consoleIssues = collectConsoleIssues(page)
  await loginAsDebugUser(page, request, 'debug_system')
  await openPageAndWaitForHeading(page, '/data/overview', '数据概览')

  await page.getByRole('tab', { name: '数据资产' }).click()
  await expect(page.getByTestId('overview-asset-table')).toBeVisible()
  await expectAdaptiveTableFillsContainer(page, 'overview-asset-table')

  await page.getByRole('tab', { name: '逐股分层体检' }).click()
  await expect(page.getByTestId('overview-stock-table')).toBeVisible()
  await expectAdaptiveTableFillsContainer(page, 'overview-stock-table')
  expect(consoleIssues).toEqual([])
})
