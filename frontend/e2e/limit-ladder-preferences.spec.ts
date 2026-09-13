import { expect, test, type Page, type TestInfo } from '@playwright/test'
import {
  getUserPreference,
  loginAsDebugUser,
  saveUserPreference,
  type E2EAuthSnapshot,
} from './helpers/auth'
import { collectConsoleIssues } from './helpers/console'
import { createDefaultStockChartPreferences } from '../src/composables/useStockChartPreferences'

const defaultPreference = {
  schemaVersion: 1,
  window: 31,
  ignoreSt: true,
  boards: ['main', 'star', 'gem'],
  showAnalysisPanel: false,
  cardSort: 'limitUps',
  cardSortOrder: 'desc',
  defaultChartMode: 'compare',
  compareRange: 60,
  benchmarkCode: '000905.SH',
  compareMetrics: ['cum', 'roll_5d', 'roll_10d', 'roll_20d', 'roll_30d', 'roll_60d'],
  defaultCompareMetric: 'cum',
  adjustMode: 'qfq',
  charts: createDefaultStockChartPreferences(),
}

async function openBusinessSettings(page: Page): Promise<void> {
  await page.getByTestId('page-settings-trigger').click()
  const field = page.getByTestId('limit-ladder-default-window-20')
  if (!await field.isVisible()) {
    await page.getByText('业务选项', { exact: true }).click()
  }
  await expect(field).toBeVisible()
}

async function readPreference(
  request: Parameters<typeof getUserPreference>[0],
  auth: E2EAuthSnapshot,
): Promise<unknown> {
  return getUserPreference(request, auth, {
    scope: 'page',
    pageKey: 'limit-ladder',
    prefKey: 'settings',
  })
}

test('个人默认修改即保存并同步当前页面、详情现场独立于 URL、恢复默认', async ({ page, request }, testInfo: TestInfo) => {
  test.setTimeout(90_000)
  test.skip(
    testInfo.project.name !== 'chromium-standard',
    '偏好写入链路只在标准视口串行执行',
  )
  const consoleIssues = collectConsoleIssues(page)
  // 偏好写用独立普通账号，避免与并行执行的 system 页面用例互相覆盖同一远端偏好。
  const auth = await loginAsDebugUser(page, request, 'debug_normal')
  const originalPreference = await readPreference(request, auth)
  await saveUserPreference(request, auth, {
    scope: 'page',
    pageKey: 'limit-ladder',
    prefKey: 'settings',
    value: defaultPreference,
  })

  try {
    await page.goto('/limit-ladder')
    await expect(page.getByTestId('limit-ladder-main')).toBeVisible()
    await expect(page).toHaveURL(/\/limit-ladder$/)

    await openBusinessSettings(page)
    await page.getByTestId('limit-ladder-default-window-20').click()
    await page.getByTestId('limit-ladder-default-boards')
      .getByText('科创板', { exact: true })
      .click()
    await page.getByTestId('limit-ladder-default-ignore-st-switch').click()
    await page.getByTestId('limit-ladder-default-card-sort-order-asc').click()
    await page.getByTestId('stock-analysis-default-benchmark').locator('.el-select__wrapper').click()
    await page.getByRole('option', { name: '沪深 300' }).click()
    await expect(page.getByTestId('limit-ladder-default-window-20'))
      .toHaveAttribute('aria-pressed', 'true')
    await expect(page.getByTestId('limit-ladder-default-boards')
      .getByRole('checkbox', { name: '科创板' }))
      .not.toBeChecked()
    await expect(page.getByTestId('limit-ladder-default-ignore-st-switch'))
      .not.toHaveClass(/is-checked/)
    await expect(page.getByTestId('limit-ladder-default-card-sort-order-asc'))
      .toHaveAttribute('aria-pressed', 'true')
    await expect(page.getByTestId('limit-ladder-window-20'))
      .toHaveAttribute('aria-pressed', 'true')
    await expect(page.getByTestId('limit-ladder-ignore-st')).not.toBeChecked()
    await expect(page.getByTestId('limit-ladder-boards')).not.toContainText('科创板')
    await expect(page).toHaveURL(/\/limit-ladder$/)

    const screenshotPath = testInfo.outputPath('limit-ladder-preference-auto-save.png')
    await page.screenshot({ path: screenshotPath, fullPage: true })
    await testInfo.attach('limit-ladder-preference-auto-save', {
      path: screenshotPath,
      contentType: 'image/png',
    })

    await expect.poll(() => readPreference(request, auth)).toEqual({
      ...defaultPreference,
      window: 20,
      ignoreSt: false,
      boards: ['main', 'gem'],
      cardSortOrder: 'asc',
      benchmarkCode: '000300.SH',
    })
    await page.getByRole('button', { name: '关闭页面设置' }).click()

    await page.goto('/limit-ladder')
    await expect(page).toHaveURL(/\/limit-ladder$/)
    await expect(page.getByTestId('limit-ladder-window-20'))
      .toHaveAttribute('aria-pressed', 'true')
    await expect(page.getByTestId('limit-ladder-ignore-st')).not.toBeChecked()
    await expect(page.getByTestId('limit-ladder-boards')).not.toContainText('科创板')
    await expect(page.getByTestId('market-show-analysis')).toBeVisible()
    await page.getByTestId('market-show-analysis').click()
    await expect(page.getByTestId('stock-analysis-benchmark')).toContainText('沪深 300')

    await page.goto('/limit-ladder?window=60&boards=star&ignore_st=1')
    await expect(page).toHaveURL(/\/limit-ladder$/)
    await expect(page.getByTestId('limit-ladder-window-20'))
      .toHaveAttribute('aria-pressed', 'true')
    await expect(page.getByTestId('limit-ladder-ignore-st')).not.toBeChecked()

    await openBusinessSettings(page)
    await page.getByTestId('page-settings-reset').click()
    await expect(page).toHaveURL(/\/limit-ladder$/)
    await expect(page.getByTestId('limit-ladder-window-31'))
      .toHaveAttribute('aria-pressed', 'true')
    await expect(page.getByTestId('limit-ladder-ignore-st')).toBeChecked()
    await expect(page.getByTestId('market-show-analysis')).toBeVisible()
    await expect.poll(() => readPreference(request, auth)).toEqual(defaultPreference)
    expect(consoleIssues).toEqual([])
  } finally {
    await saveUserPreference(request, auth, {
      scope: 'page',
      pageKey: 'limit-ladder',
      prefKey: 'settings',
      value: originalPreference ?? defaultPreference,
    })
  }
})
