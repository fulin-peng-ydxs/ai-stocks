import { expect, test, type Page, type TestInfo } from '@playwright/test'
import { loginAsDebugUser } from './helpers/auth'
import { collectConsoleIssues } from './helpers/console'
import {
  installDeterministicLimitLadder,
  limitLadderFirstBoardStocks as firstBoardStocks,
  limitLadderStock as stock,
  limitLadderTradeDate as tradeDate,
} from './helpers/limitLadder'

test('桌面分析、详情返回与 1100×620 低高度上下文保持', async ({ page, request }, testInfo: TestInfo) => {
  test.skip(testInfo.project.name !== 'chromium-standard', '聚焦串行验证一次')
  await page.setViewportSize({ width: 1100, height: 620 })
  const consoleIssues = collectConsoleIssues(page)
  await loginAsDebugUser(page, request, 'debug_system')
  const ladderApi = await installDeterministicLimitLadder(page)

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
  await installDeterministicLimitLadder(page)

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
