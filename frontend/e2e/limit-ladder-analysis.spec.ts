import { expect, test, type Page, type TestInfo } from '@playwright/test'
import { loginAsDebugUser } from './helpers/auth'
import { collectConsoleIssues } from './helpers/console'

const tradeDate = '2026-08-28'
const stock = {
  code: '000001.SZ', name: '平安银行', board: '主板', price_limit_pct: 0.1,
  is_st: false, st_quality: 'accurate', st_source: 'e2e', is_one_word: false,
  consecutive_days: 2, amount: 123000000, industry_name: '银行',
  industry_board_code: 'I001', source_version: 'e2e-v1', window_limit_up_days: 3,
  window_start_date: '2026-07-17', actual_trade_days: 31,
  snapshot_concepts: [{ board_code: 'C001', board_name: '金融科技' }],
  latest_related_concept: { board_code: 'C001', board_name: '金融科技', as_of_date: tradeDate },
}
const bar = {
  date: tradeDate, open: 10, high: 11, low: 9.8, close: 10.8, pre_close: 10,
  volume: 100000, amount: 1080000, turnover_rate: 1.2,
}

async function installDeterministicLadder(page: Page): Promise<void> {
  await page.route('**/api/limit-ladder/trade-dates', (route) => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({
      code: 0, msg: 'ok', data: {
        dates: [tradeDate], latest_candidate_date: tradeDate,
        latest_complete_date: tradeDate, latest_candidate_coverage: {},
        latest_candidate_ready: true,
      },
    }),
  }))
  await page.route(`**/api/limit-ladder/${tradeDate}?**`, (route) => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({
      code: 0, msg: 'ok', data: {
        trade_date: tradeDate, business_code: 'READY', snapshot_status: 'valid',
        stored_snapshot_status: 'valid', has_snapshot: true, filters: {},
        snapshot: { snapshot_id: 'e2e-snapshot', trade_date: tradeDate, computed_at: `${tradeDate}T18:00:00`, stock_count: 1, has_approx_st: false, coverage: {} },
        requested_window_start_date: '2026-07-17', requested_window_trade_days: 31,
        dynamic_window_status: 'ready', summary: { stock_count: 1, highest_board: 2, first_board_count: 0 },
        hotspots: { industry: [{ group_key: 'I001', group_name: '银行', stock_count: 1 }], concept: [{ group_key: 'C001', group_name: '金融科技', stock_count: 1 }] },
        layers: [{ consecutive_days: 2, stock_count: 1, stocks: [stock] }],
      },
    }),
  }))
  await page.route('**/api/stocks/benchmarks/*/bars?**', (route) => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({ code: 0, msg: 'ok', data: { code: '000905.SH', name: '中证500', bars: [bar] } }),
  }))
  await page.route('**/api/stocks/000001.SZ/bars?**', (route) => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({ code: 0, msg: 'ok', data: { code: stock.code, name: stock.name, adjust: 'qfq', bars: [bar] } }),
  }))
  await page.route('**/api/stocks/000001.SZ/indicators?**', (route) => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({ code: 0, msg: 'ok', data: { code: stock.code, indicators: [{ trade_date: tradeDate, macd_diff: 1, macd_dea: 0.8, macd_hist: 0.2 }] } }),
  }))
}

test('桌面分析、详情返回与 1100×620 低高度上下文保持', async ({ page, request }, testInfo: TestInfo) => {
  test.skip(testInfo.project.name !== 'chromium-standard', '聚焦串行验证一次')
  await page.setViewportSize({ width: 1100, height: 620 })
  const consoleIssues = collectConsoleIssues(page)
  await loginAsDebugUser(page, request, 'debug_system')
  await installDeterministicLadder(page)

  await page.goto(`/limit-ladder?date=${tradeDate}&window=31`)
  await expect(page.getByText('完整工作台')).toHaveCount(0)
  const card = page.getByTestId(`limit-ladder-card-${stock.code}`)
  await expect(card).toBeVisible()
  const density = await page.evaluate(() => {
    const board = document.querySelector('[data-testid="limit-ladder-boards"] .el-select__wrapper')!
      .getBoundingClientRect()
    const stockCard = document.querySelector('[data-stock-code="000001.SZ"]')!
      .getBoundingClientRect()
    return { boardHeight: board.height, cardWidth: stockCard.width }
  })
  expect(density.boardHeight).toBeLessThanOrEqual(34)
  expect(density.cardWidth).toBeLessThanOrEqual(197)
  await card.click()
  await expect(page.getByTestId('stock-analysis-panel')).toBeVisible()
  await expect(page.getByTestId('stock-analysis-open-detail')).toBeVisible()
  await expect(page).toHaveURL(new RegExp(`selected=${stock.code.replace('.', '\\.')}`))
  await expect(page).toHaveURL(new RegExp(`anchor=${stock.code.replace('.', '\\.')}`))

  const returnPath = await page.evaluate(() => JSON.parse(localStorage.getItem('ai-stocks:stockSet') || '{}').returnPath)
  expect(returnPath).toBeUndefined()
  await page.getByTestId('stock-analysis-open-detail').click()
  await expect(page).toHaveURL(new RegExp(`/stocks/${stock.code.replace('.', '\\.')}$`))
  const stored = await page.evaluate(() => JSON.parse(localStorage.getItem('ai-stocks:stockSet') || '{}'))
  expect(stored.items).toEqual([{ code: stock.code, name: stock.name }])
  expect(stored.returnPath).toContain(`/limit-ladder?window=31&date=${tradeDate}`)
  expect(stored.returnPath).toContain(`selected=${stock.code}`)
  expect(stored.returnPath).toContain(`anchor=${stock.code}`)

  await page.getByTestId('stock-detail-back').click()
  await expect(page).toHaveURL(new RegExp(`/limit-ladder\\?.*selected=${stock.code.replace('.', '\\.')}`))
  await expect(page.getByTestId(`limit-ladder-card-${stock.code}`)).toHaveAttribute('aria-current', 'true')
  const screenshotPath = testInfo.outputPath('limit-ladder-desktop-return.png')
  await page.screenshot({ path: screenshotPath, fullPage: true })
  await testInfo.attach('limit-ladder-desktop-return', { path: screenshotPath, contentType: 'image/png' })
  expect(consoleIssues).toEqual([])
})

test('768×1024 使用页面边界内全宽分析抽屉并可返回原卡片', async ({ page, request }, testInfo: TestInfo) => {
  test.skip(testInfo.project.name !== 'chromium-standard', '聚焦串行验证一次')
  await page.setViewportSize({ width: 768, height: 1024 })
  const consoleIssues = collectConsoleIssues(page)
  await loginAsDebugUser(page, request, 'debug_system')
  await installDeterministicLadder(page)

  await page.goto(`/limit-ladder?date=${tradeDate}&window=31`)
  await page.getByTestId(`limit-ladder-card-${stock.code}`).click()
  const drawer = page.getByTestId('limit-ladder-analysis-drawer')
  await expect(drawer).toBeVisible()
  const readGeometry = () => page.evaluate(() => {
    const pageRoot = document.querySelector('[data-testid="limit-ladder-page"]')!.getBoundingClientRect()
    const drawerRoot = document.querySelector('[data-testid="limit-ladder-analysis-drawer"]')!.getBoundingClientRect()
    return { pageX: pageRoot.x, pageWidth: pageRoot.width, drawerX: drawerRoot.x, drawerWidth: drawerRoot.width }
  })
  await expect.poll(async () => {
    const geometry = await readGeometry()
    return Math.abs(geometry.drawerX - geometry.pageX)
  }).toBeLessThanOrEqual(1)
  const geometry = await readGeometry()
  expect(Math.abs(geometry.drawerWidth - geometry.pageWidth)).toBeLessThanOrEqual(1)
  await expect(drawer.getByTestId('stock-analysis-panel')).toBeVisible()

  const screenshotPath = testInfo.outputPath('limit-ladder-768-analysis-drawer.png')
  await page.screenshot({ path: screenshotPath, fullPage: true })
  await testInfo.attach('limit-ladder-768-analysis-drawer', { path: screenshotPath, contentType: 'image/png' })
  await page.keyboard.press('Escape')
  await expect(drawer).toBeHidden()
  await expect(page.getByTestId(`limit-ladder-card-${stock.code}`)).toBeVisible()
  await expect(page.getByTestId(`limit-ladder-card-${stock.code}`)).toHaveAttribute('aria-current', 'true')
  expect(consoleIssues).toEqual([])
})
