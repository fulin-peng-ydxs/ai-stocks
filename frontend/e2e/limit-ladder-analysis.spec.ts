import { expect, test, type Page, type TestInfo } from '@playwright/test'
import { loginAsDebugUser } from './helpers/auth'
import { collectConsoleIssues } from './helpers/console'

const tradeDate = '2026-08-28'
const stock = {
  code: '000001.SZ', name: '平安银行', board: '主板', price_limit_pct: 0.1,
  is_st: false, st_quality: 'accurate', st_source: 'e2e', is_one_word: false,
  consecutive_days: 2, amount: 123000000, industry_name: '专属行业旧值',
  industry_board_code: 'I001', source_version: 'e2e-v1', window_limit_up_days: 3,
  window_start_date: '2026-07-17', actual_trade_days: 31,
  snapshot_concepts: [{ board_code: 'C001', board_name: '金融科技' }],
  latest_related_industry: { board_code: 'I900', board_name: '金融服务', as_of_date: tradeDate },
  latest_related_concept: { board_code: 'C001', board_name: '金融科技', as_of_date: tradeDate },
}
const firstBoardStock = {
  ...stock,
  code: '000002.SZ', name: '万科A', consecutive_days: 1, window_limit_up_days: 1,
  industry_name: '房地产',
  latest_related_industry: { board_code: 'I901', board_name: '地产服务', as_of_date: tradeDate },
  latest_related_concept: { board_code: 'C002', board_name: '国企改革', as_of_date: tradeDate },
}
const firstBoardStocks = Array.from({ length: 6 }, (_, index) => index === 0
  ? firstBoardStock
  : {
      ...firstBoardStock,
      code: `00000${index + 2}.SZ`,
      name: `首板样本${index + 1}`,
    })
const bar = {
  date: tradeDate, open: 10, high: 11, low: 9.8, close: 10.8, pre_close: 10,
  volume: 100000, amount: 1080000, turnover_rate: 1.2,
}

async function installDeterministicLadder(page: Page): Promise<{
  recomputeCount: () => number
}> {
  let recomputeRequests = 0
  let recomputeRefreshes = 0
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
  await page.route(`**/api/limit-ladder/${tradeDate}/recompute`, (route) => {
    recomputeRequests += 1
    recomputeRefreshes = 0
    return route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        code: 0, msg: 'ok', data: {
          command_id: 'e2e-command', task_id: 'e2e-task', status: 'requested', reused: false,
        },
      }),
    })
  })
  await page.route(`**/api/limit-ladder/${tradeDate}?**`, (route) => {
    const recalculating = recomputeRequests > 0 && recomputeRefreshes++ === 0
    return route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        code: 0, msg: 'ok', data: {
        trade_date: tradeDate,
        business_code: recalculating ? 'SNAPSHOT_STALE' : 'READY',
        snapshot_status: recalculating ? 'recalculating' : 'valid',
        stored_snapshot_status: 'valid', has_snapshot: true, filters: {},
        snapshot: { snapshot_id: 'e2e-snapshot', trade_date: tradeDate, computed_at: `${tradeDate}T18:00:00`, stock_count: 7, has_approx_st: false, coverage: {} },
        requested_window_start_date: '2026-07-17', requested_window_trade_days: 31,
        dynamic_window_status: 'ready', summary: { stock_count: 7, highest_board: 2, first_board_count: 6 },
        hotspots: {
          industry: [
            { group_key: 'I900', group_name: '金融服务', stock_count: 1 },
            { group_key: 'I901', group_name: '地产服务', stock_count: 6 },
          ],
          concept: [
            { group_key: 'C001', group_name: '金融科技', stock_count: 1 },
            { group_key: 'C002', group_name: '国企改革', stock_count: 6 },
          ],
        },
        layers: [
          { consecutive_days: 2, stock_count: 1, stocks: [stock] },
          { consecutive_days: 1, stock_count: 6, stocks: firstBoardStocks },
        ],
        },
      }),
    })
  })
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
  return { recomputeCount: () => recomputeRequests }
}

test('桌面分析、详情返回与 1100×620 低高度上下文保持', async ({ page, request }, testInfo: TestInfo) => {
  test.skip(testInfo.project.name !== 'chromium-standard', '聚焦串行验证一次')
  await page.setViewportSize({ width: 1100, height: 620 })
  const consoleIssues = collectConsoleIssues(page)
  await loginAsDebugUser(page, request, 'debug_system')
  const ladderApi = await installDeterministicLadder(page)

  await page.goto(`/limit-ladder?date=${tradeDate}&window=31`)
  await expect(page.getByText('完整工作台')).toHaveCount(0)
  const boardFilter = page.getByTestId('limit-ladder-boards')
  await expect(boardFilter.getByText('主板', { exact: true })).toBeVisible()
  await expect(boardFilter.getByText('科创板', { exact: true })).toBeVisible()
  await expect(boardFilter.getByText('创业板', { exact: true })).toBeVisible()
  await expect(boardFilter.getByText('+1', { exact: true })).toHaveCount(0)
  const toolbarGeometry = await page.evaluate(() => {
    const toolbarNode = document.querySelector<HTMLElement>('.limit-ladder__toolbar')!
    const toolbar = toolbarNode.getBoundingClientRect()
    const panel = document.querySelector('.market-list-panel')!.getBoundingClientRect()
    const exported = document.querySelector('[data-testid="limit-ladder-export"]')!.getBoundingClientRect()
    const controlHeights = [
      toolbarNode.querySelector('.el-date-editor'),
      toolbarNode.querySelector('.page-segmented'),
      toolbarNode.querySelector('.app-filter-select'),
      toolbarNode.querySelector('.limit-ladder__checks'),
      toolbarNode.querySelector('.app-search-input'),
      document.querySelector('[data-testid="limit-ladder-export"]'),
    ].map((node) => node!.getBoundingClientRect().height)
    const controls = [...toolbarNode.querySelectorAll<HTMLElement>('.app-control-row > *')]
    const controlBoxes = controls.map((node) => node.getBoundingClientRect())
    const overlapCount = controlBoxes.reduce((count, box, index) => (
      count + controlBoxes.slice(index + 1).filter((other) => (
        Math.min(box.right, other.right) - Math.max(box.left, other.left) > 1
        && Math.min(box.bottom, other.bottom) - Math.max(box.top, other.top) > 1
      )).length
    ), 0)
    return {
      panelRight: panel.right,
      exportRight: exported.right,
      exportWidth: exported.width,
      toolbarOverflow: toolbarNode.scrollWidth - toolbarNode.clientWidth,
      bodyOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      controlHeights,
      controlOverflow: Math.max(...controls.map((node) => node.scrollWidth - node.clientWidth)),
      overlapCount,
    }
  })
  expect(toolbarGeometry.exportRight).toBeLessThanOrEqual(toolbarGeometry.panelRight + 1)
  expect(toolbarGeometry.exportWidth).toBeGreaterThan(80)
  expect(toolbarGeometry.toolbarOverflow).toBeLessThanOrEqual(1)
  expect(toolbarGeometry.bodyOverflow).toBeLessThanOrEqual(1)
  expect(toolbarGeometry.controlHeights).toEqual([32, 32, 32, 32, 32, 32])
  expect(toolbarGeometry.controlOverflow).toBeLessThanOrEqual(1)
  expect(toolbarGeometry.overlapCount).toBe(0)

  const card = page.getByTestId(`limit-ladder-card-${stock.code}`)
  await page.setViewportSize({ width: 1100, height: 900 })
  await expect(card).toBeVisible()
  await card.evaluate((node) => node.scrollIntoView({ block: 'center', inline: 'center' }))
  const cardScreenshotPath = testInfo.outputPath('limit-ladder-card-fields-v4.png')
  await card.screenshot({ path: cardScreenshotPath })
  await testInfo.attach('limit-ladder-card', { path: cardScreenshotPath, contentType: 'image/png' })
  await page.setViewportSize({ width: 1100, height: 620 })

  await page.getByTestId('limit-ladder-recompute').click()
  await page.getByRole('button', { name: '确认重算' }).click()
  await expect.poll(ladderApi.recomputeCount).toBe(1)
  await expect(page.getByTestId('limit-ladder-stale-notice')).toBeVisible()
  await expect(page.getByTestId('limit-ladder-stale-notice')).toBeHidden({ timeout: 5000 })
  await expect(card).toBeVisible()
  const density = await page.evaluate(() => {
    const board = document.querySelector('[data-testid="limit-ladder-boards"] .el-select__wrapper')!
      .getBoundingClientRect()
    const stockCard = document.querySelector('[data-stock-code="000001.SZ"]')!
      .getBoundingClientRect()
    const cards = document.querySelector('.limit-ladder__cards')!.getBoundingClientRect()
    const layers = [...document.querySelectorAll('.limit-ladder__layer')]
      .map((node) => node.getBoundingClientRect().width)
    const cardWidths = [...document.querySelectorAll('.limit-ladder-card')]
      .map((node) => node.getBoundingClientRect().width)
    return {
      boardHeight: board.height,
      cardWidth: stockCard.width,
      cardCenterOffset: Math.abs(
        (stockCard.left + stockCard.width / 2) - (cards.left + cards.width / 2),
      ),
      layerWidthDelta: Math.max(...layers) - Math.min(...layers),
      cardWidthDelta: Math.max(...cardWidths) - Math.min(...cardWidths),
    }
  })
  expect(density.boardHeight).toBeLessThanOrEqual(34)
  expect(density.cardWidth).toBe(184)
  expect(density.cardWidthDelta).toBeLessThanOrEqual(1)
  expect(density.cardCenterOffset).toBeLessThanOrEqual(1)
  expect(density.layerWidthDelta).toBeLessThanOrEqual(1)
  await page.setViewportSize({ width: 1920, height: 900 })
  const wideCardWidths = await page.locator('.limit-ladder-card').evaluateAll((nodes) => (
    nodes.map((node) => node.getBoundingClientRect().width)
  ))
  expect(Math.max(...wideCardWidths) - Math.min(...wideCardWidths)).toBeLessThanOrEqual(1)
  const wideScreenshotPath = testInfo.outputPath('limit-ladder-layout-wide-v4.png')
  await page.screenshot({ path: wideScreenshotPath, fullPage: true })
  await testInfo.attach('limit-ladder-wide', { path: wideScreenshotPath, contentType: 'image/png' })
  await page.setViewportSize({ width: 1100, height: 620 })
  await expect(card).toContainText('金融服务')
  await expect(card).not.toContainText('专属行业旧值')
  await expect(card).not.toContainText('成交额')
  await expect(card).not.toContainText('截至')
  await expect(card).not.toContainText('+10%')
  await expect(card.locator('.limit-ladder-card__window-stat b')).toHaveClass(/is-multiple/)
  for (const selector of ['.limit-ladder-card__classification', '.limit-ladder-card__concept']) {
    await expect(card.locator(selector)).toBeVisible()
    expect((await card.locator(selector).boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(18)
  }
  const cardContentGeometry = await card.evaluate((node) => {
    const cardBox = node.getBoundingClientRect()
    const industryBox = node.querySelector('.limit-ladder-card__classification')!.getBoundingClientRect()
    const conceptBox = node.querySelector('.limit-ladder-card__concept')!.getBoundingClientRect()
    return {
      cardTop: cardBox.top,
      cardBottom: cardBox.bottom,
      industryTop: industryBox.top,
      conceptBottom: conceptBox.bottom,
    }
  })
  expect(cardContentGeometry.industryTop).toBeGreaterThanOrEqual(cardContentGeometry.cardTop)
  expect(cardContentGeometry.conceptBottom).toBeLessThanOrEqual(cardContentGeometry.cardBottom + 1)
  await expect(page.getByTestId('limit-ladder-hotspot-industry-I900')).toContainText(/金融服务.*·.*1只/)
  const relatedHref = await page.getByTestId(`limit-ladder-related-${stock.code}`).getAttribute('href')
  expect(relatedHref).toContain(`/sectors/${stock.latest_related_concept.board_code}?return_to=`)
  expect(decodeURIComponent(String(relatedHref).split('return_to=')[1])).toContain('/limit-ladder?window=31')
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
  expect(stored.items).toEqual([
    { code: stock.code, name: stock.name },
    ...firstBoardStocks.map(({ code, name }) => ({ code, name })),
  ])
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
