import { expect, test } from '@playwright/test'
import { loginAsDebugUser } from './helpers/auth'
import { collectConsoleIssues } from './helpers/console'
import { openPageAndWaitForHeading } from './helpers/navigation'

const API_URL = process.env.E2E_API_URL || 'http://127.0.0.1:8000/api'

function waitForOverviewLayoutHydration(page: import('@playwright/test').Page) {
  return page.waitForResponse((response) => {
    const pathname = new URL(response.url()).pathname
    return response.request().method() === 'GET'
      && pathname.endsWith('/api/layout/effective/data-overview')
  })
}

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
  const auth = await loginAsDebugUser(page, request, 'debug_system')
  // 预热概览汇总 + 逐股质量两个 DuckDB 重查询接口（走全局读锁 + 数据签名缓存）：
  // 全量三视口并发下冷启动全市场扫描在锁内串行排队，先预热填缓存，避免下方摘要/表格可见性断言撞 8s 超时。
  const headers = { authorization: `Bearer ${auth.accessToken}` }
  await request.get(`${API_URL}/data/overview`, { headers })
  await request.get(`${API_URL}/data/stock-quality?page=1&size=1`, { headers })
  const layoutHydrated = waitForOverviewLayoutHydration(page)
  await openPageAndWaitForHeading(page, '/data/overview', '数据概览')
  await layoutHydrated
  await page.evaluate(() => new Promise<void>((resolve) => {
    requestAnimationFrame(() => requestAnimationFrame(() => resolve()))
  }))

  const summary = page.getByTestId('overview-summary')
  const quality = page.getByTestId('overview-quality-summary')
  const workspace = page.getByTestId('overview-workspace')
  const mixed = page.getByTestId('layout-mixed-region')
  const grow = page.getByTestId('layout-grow-region')
  // 摘要/质量条依赖上述 DuckDB 重查询，并发下读锁排队可能慢于默认 8s——放宽可见性等待（已知架构边界，非渲染缺陷）。
  await expect(summary).toBeVisible({ timeout: 30_000 })
  await expect(quality).toBeVisible({ timeout: 30_000 })
  await expect(workspace).toBeVisible()
  await page.getByRole('tab', { name: '数据资产' }).click()
  await expect(page.getByTestId('overview-asset-table')).toBeVisible()
  await expect(page.getByTestId('overview-assets-toolbar')).toContainText('展开行查看字段字典与表间关联')
  await expect(page.getByTestId('overview-assets-toolbar').getByText('数据资产表', { exact: true })).toHaveCount(0)

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
  expect(geometry.grow.height).toBeGreaterThanOrEqual(200)
  expect(geometry.workspace.top).toBeLessThanOrEqual(geometry.main.bottom)
  expect(geometry.main.scrollTop).toBe(0)
  // 固定摘要 + 质量条 + tabs 最低高在 620 高视口下已超过余量：
  // 应由 mixed 主内容区滚动兜底，而不是压缩 tabs 或让应用外壳滚动。
  expect(geometry.mixed.scrollHeight).toBeGreaterThan(geometry.mixed.clientHeight + 1)
  await mixed.evaluate((node) => { node.scrollTop = node.scrollHeight })
  await expect.poll(() => mixed.evaluate((node) => node.scrollTop)).toBeGreaterThan(0)
  await mixed.evaluate((node) => { node.scrollTop = 0 })
  await expectAdaptiveTableFillsContainer(page, 'overview-asset-table')

  await page.getByRole('tab', { name: '逐股分层体检' }).click()
  await expect(page.getByTestId('overview-stock-table')).toBeVisible()
  const stockToolbar = page.getByTestId('overview-stocks-toolbar')
  await expect(stockToolbar.getByTestId('overview-stock-codes')).toBeVisible()
  await expect(stockToolbar).toContainText('异常入口查看对应台账')
  await expect(stockToolbar.getByText('L1 入库 / L2 契约 / L3 正确性 / L4 覆盖鲜活', { exact: true })).toHaveCount(0)
  await expectAdaptiveTableFillsContainer(page, 'overview-stock-table')
  await expect(summary).toBeVisible()
  await expect(quality).toBeVisible()
  expect(consoleIssues).toEqual([])
})

test('数据概览两类表格在各桌面视口都自适应铺满内容区', async ({ page, request }) => {
  const consoleIssues = collectConsoleIssues(page)
  const auth = await loginAsDebugUser(page, request, 'debug_system')
  // 预热逐股质量接口（stock-quality 走 DuckDB 全局读锁 + _coverage_frame 数据签名缓存）：
  // 三视口并发下冷启动全市场扫描在锁内串行排队，先预热填缓存，避免下方表格可见性断言撞 8s 超时。
  await request.get(`${API_URL}/data/stock-quality?page=1&size=1`, {
    headers: { authorization: `Bearer ${auth.accessToken}` },
  })
  const layoutHydrated = waitForOverviewLayoutHydration(page)
  await openPageAndWaitForHeading(page, '/data/overview', '数据概览')
  await layoutHydrated
  await page.evaluate(() => new Promise<void>((resolve) => {
    requestAnimationFrame(() => requestAnimationFrame(() => resolve()))
  }))

  // 远端布局水合会恢复默认 tab；先等配置落地，避免测试点击被异步恢复覆盖。
  await expect(page.getByTestId('overview-summary')).toBeVisible({ timeout: 30_000 })
  await expect(page.getByTestId('overview-workspace')).toBeVisible()
  await page.getByRole('tab', { name: '数据资产' }).click()
  await expect(page.getByTestId('overview-asset-table')).toBeVisible()
  await expect(page.getByTestId('overview-assets-toolbar')).toBeVisible()
  await expectAdaptiveTableFillsContainer(page, 'overview-asset-table')

  await page.getByRole('tab', { name: '逐股分层体检' }).click()
  // 该表格为 DuckDB 重查询页面，并发下读锁排队可能慢于默认 8s——放宽可见性等待（已知架构边界，非渲染缺陷）。
  await expect(page.getByTestId('overview-stock-table')).toBeVisible({ timeout: 30_000 })
  await expect(page.getByTestId('overview-stocks-toolbar')).toBeVisible()
  await expectAdaptiveTableFillsContainer(page, 'overview-stock-table')
  expect(consoleIssues).toEqual([])
})
