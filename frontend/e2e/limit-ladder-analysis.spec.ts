import { expect, test, type Page, type TestInfo } from '@playwright/test'
import { loginAsDebugUser, readPageSession } from './helpers/auth'
import { collectConsoleIssues } from './helpers/console'
import {
  installDeterministicLimitLadder,
  limitLadderFirstBoardStocks as firstBoardStocks,
  limitLadderStock as stock,
  limitLadderTradeDate as tradeDate,
  makeLimitLadderResult,
} from './helpers/limitLadder'

test.use({ actionTimeout: 15_000 })

test('桌面分析、详情返回与 1100×620 低高度上下文保持', async ({ page, request }, testInfo: TestInfo) => {
  test.skip(testInfo.project.name !== 'chromium-standard', '聚焦串行验证一次')
  await page.setViewportSize({ width: 1100, height: 620 })
  const consoleIssues = collectConsoleIssues(page)
  const auth = await loginAsDebugUser(page, request, 'debug_system')
  const ladderApi = await installDeterministicLimitLadder(page)
  await page.route(
    new RegExp(`/api/sectors/${stock.latest_related_concept.board_code}(?:\\?.*)?$`),
    (route) => route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        code: 0,
        msg: 'ok',
        data: {
          board_code: stock.latest_related_concept.board_code,
          app_code: null,
          name: stock.latest_related_concept.board_name,
          board_type: 'concept',
          member_count: 0,
          has_members: false,
          has_bar: false,
          has_fund_flow: false,
          pct_today: null,
          pct_5d: null,
          pct_10d: null,
          pct_20d: null,
          net_inflow: null,
          net_inflow_3d: null,
          net_inflow_5d: null,
          net_inflow_10d: null,
          net_inflow_20d: null,
          leader_stock: null,
          leader_pct: null,
          up_count: 0,
          down_count: 0,
          trade_date: tradeDate,
          fund_flow_date: null,
        },
      }),
    }),
  )
  ladderApi.setResult(makeLimitLadderResult({
    hotspots: {
      industry: [
        { group_key: 'I900', group_name: '金融服务', stock_count: 1 },
        { group_key: 'I901', group_name: '地产服务', stock_count: 6 },
        ...Array.from({ length: 4 }, (_, index) => ({
          group_key: `IX${index}`,
          group_name: `行业样本${index + 1}`,
          stock_count: 4 - index,
        })),
      ],
      concept: [
        { group_key: 'C001', group_name: '金融科技', stock_count: 1 },
        { group_key: 'C002', group_name: '国企改革', stock_count: 6 },
        ...Array.from({ length: 4 }, (_, index) => ({
          group_key: `CX${index}`,
          group_name: `概念样本${index + 1}`,
          stock_count: 4 - index,
        })),
      ],
    },
  }))

  await page.goto('/limit-ladder')
  await expect(page.getByText('完整工作台')).toHaveCount(0)
  if (!await page.getByTestId('limit-ladder-one-word').isVisible()) {
    await page.locator('[data-search-toggle]').click()
  }
  const boardFilter = page.getByTestId('limit-ladder-boards')
  await expect(boardFilter).toContainText('全部板块')
  await boardFilter.locator('.el-select__wrapper').click()
  for (const name of ['主板', '科创板', '创业板']) {
    await expect(page.getByRole('option', { name, exact: true })).toHaveAttribute('aria-selected', 'true')
  }
  await page.keyboard.press('Escape')
  await expect(boardFilter.getByText('+1', { exact: true })).toHaveCount(0)
  const toolbarGeometry = await page.evaluate(() => {
    const toolbarNode = document.querySelector<HTMLElement>('[data-testid="limit-ladder-filters"]')!
    const toolbar = toolbarNode.getBoundingClientRect()
    const panel = document.querySelector('[data-testid="limit-ladder-page"]')!.getBoundingClientRect()
    const exported = document.querySelector('[data-testid="limit-ladder-export"]')!.getBoundingClientRect()
    const recompute = document.querySelector('[data-testid="limit-ladder-recompute"]')!.getBoundingClientRect()
    const controls = [toolbarNode.querySelector<HTMLElement>('.el-date-editor')!, ...['limit-ladder-window', 'limit-ladder-boards',
      'limit-ladder-ignore-st', 'limit-ladder-one-word', 'limit-ladder-keyword', 'limit-ladder-reset']
      .map(id => toolbarNode.querySelector<HTMLElement>(`[data-testid="${id}"]`)!)]
      .map(node => node.closest<HTMLElement>('.el-input') || node)
    const controlHeights = controls.map(node => node.getBoundingClientRect().height)
    const controlBoxes = controls.map((node) => node.getBoundingClientRect())
    const overlapCount = controlBoxes.reduce((count, box, index) => (
      count + controlBoxes.slice(index + 1).filter((other) => (
        Math.min(box.right, other.right) - Math.max(box.left, other.left) > 1
        && Math.min(box.bottom, other.bottom) - Math.max(box.top, other.top) > 1
      )).length
    ), 0)
    const search = controls[5]!
    const inputSizing = [search, search.querySelector('.el-input__wrapper')!, search.querySelector('input')!]
      .map(node => {
        const style = getComputedStyle(node)
        return { height: style.height, padding: style.padding, boxSizing: style.boxSizing,
          inputHeight: style.getPropertyValue('--el-input-height'), rowHeight: style.getPropertyValue('--app-control-row-height') }
      })
    return {
      panelRight: panel.right,
      exportRight: exported.right,
      exportWidth: exported.width,
      headerActionGap: exported.left - recompute.right,
      headerActionTopDelta: Math.abs(recompute.top - exported.top),
      toolbarOverflow: toolbarNode.scrollWidth - toolbarNode.clientWidth,
      bodyOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      controlHeights,
      controlOverflow: Math.max(...controls.map((node) => node.scrollWidth - node.clientWidth)),
      overlapCount,
      inputSizing,
    }
  })
  expect(toolbarGeometry.exportRight).toBeLessThanOrEqual(toolbarGeometry.panelRight + 1)
  expect(toolbarGeometry.exportWidth).toBeGreaterThan(80)
  expect(toolbarGeometry.headerActionGap).toBeGreaterThanOrEqual(7)
  expect(toolbarGeometry.headerActionTopDelta).toBeLessThanOrEqual(1)
  expect(toolbarGeometry.toolbarOverflow).toBeLessThanOrEqual(1)
  expect(toolbarGeometry.bodyOverflow).toBeLessThanOrEqual(1)
  // 设计契约保留普通开关的自身尺寸，输入、选择、分段与命令仍为标准 32px。
  expect(toolbarGeometry.controlHeights, JSON.stringify(toolbarGeometry.inputSizing)).toEqual([32, 32, 32, 24, 24, 32, 32])
  expect(toolbarGeometry.controlOverflow).toBeLessThanOrEqual(1)
  expect(toolbarGeometry.overlapCount).toBe(0)
  await expect(page.getByTestId('limit-ladder-recompute')).toHaveText('重算当日')
  await expect(page.getByTestId('limit-ladder-recompute')).not.toHaveClass(/el-button--warning/)
  await page.getByTestId('limit-ladder-card-sort').click()
  await page.getByRole('menuitem', { name: '累计涨幅', exact: true }).click()
  await expect(page).toHaveURL(/\/limit-ladder$/)
  await expect(page.getByTestId('limit-ladder-card-sort')).toContainText('累计涨幅')

  const card = page.getByTestId(`limit-ladder-card-${stock.code}`)
  await page.setViewportSize({ width: 1100, height: 900 })
  await expect(card).toBeVisible()
  await card.evaluate((node) => node.scrollIntoView({ block: 'center', inline: 'center' }))
  const cardScreenshotPath = testInfo.outputPath('limit-ladder-card-fields-v6.png')
  await card.screenshot({ path: cardScreenshotPath })
  await testInfo.attach('limit-ladder-card', { path: cardScreenshotPath, contentType: 'image/png' })
  await page.setViewportSize({ width: 1100, height: 620 })

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
      cardLeftOffset: stockCard.left - cards.left,
      layerWidthDelta: Math.max(...layers) - Math.min(...layers),
      cardWidthDelta: Math.max(...cardWidths) - Math.min(...cardWidths),
    }
  })
  expect(density.boardHeight).toBeLessThanOrEqual(34)
  expect(density.cardWidth).toBe(220)
  expect(density.cardWidthDelta).toBeLessThanOrEqual(1)
  expect(density.cardLeftOffset).toBeGreaterThanOrEqual(0)
  expect(density.cardLeftOffset).toBeLessThanOrEqual(10)
  expect(density.layerWidthDelta).toBeLessThanOrEqual(1)
  await page.setViewportSize({ width: 1920, height: 900 })
  const wideCardWidths = await page.locator('.limit-ladder-card').evaluateAll((nodes) => (
    nodes.map((node) => node.getBoundingClientRect().width)
  ))
  expect(Math.max(...wideCardWidths) - Math.min(...wideCardWidths)).toBeLessThanOrEqual(1)
  const wideScreenshotPath = testInfo.outputPath('limit-ladder-layout-wide-v6.png')
  await page.screenshot({ path: wideScreenshotPath, fullPage: true })
  await testInfo.attach('limit-ladder-wide', { path: wideScreenshotPath, contentType: 'image/png' })
  await page.setViewportSize({ width: 1100, height: 620 })
  await expect(card).toContainText('金融服务')
  await expect(card).not.toContainText('专属行业旧值')
  await expect(card).not.toContainText('成交额')
  await expect(card).not.toContainText('截至')
  await expect(card).toContainText(stock.code)
  await expect(card).toContainText('31 日 3 板')
  await expect(card).toContainText('累计涨幅')
  await expect(card).toContainText('+12.34%')
  const headlineAlignment = await card.evaluate((node) => {
    const identity = node.querySelector<HTMLElement>('.limit-ladder-card__identity')!
      .getBoundingClientRect()
    const returns = node.querySelector<HTMLElement>('.limit-ladder-card__return')!
      .getBoundingClientRect()
    return [Math.abs(identity.top - returns.top), Math.abs(identity.bottom - returns.bottom)]
  })
  // 当前卡头为“名称/代码”和“累计涨幅/数值”两列，两列顶底均须对齐。
  expect(Math.max(...headlineAlignment)).toBeLessThanOrEqual(1)
  await expect(card.locator('.limit-ladder-card__window-stat b')).toHaveClass(/is-multiple/)
  await expect(card.locator('.limit-ladder-card__foot')).toBeVisible()
  const cardContentGeometry = await card.evaluate((node) => {
    const cardBox = node.getBoundingClientRect()
    const footer = node.querySelector('.limit-ladder-card__foot')!
    const footerBox = footer.getBoundingClientRect()
    const childTops = [...footer.children].map((child) => child.getBoundingClientRect().top)
    return {
      cardTop: cardBox.top,
      cardBottom: cardBox.bottom,
      footerTop: footerBox.top,
      footerBottom: footerBox.bottom,
      footerTopDelta: Math.max(...childTops) - Math.min(...childTops),
    }
  })
  expect(cardContentGeometry.footerTop).toBeGreaterThanOrEqual(cardContentGeometry.cardTop)
  expect(cardContentGeometry.footerBottom).toBeLessThanOrEqual(cardContentGeometry.cardBottom + 1)
  expect(cardContentGeometry.footerTopDelta).toBeLessThanOrEqual(1)
  await expect(page.getByTestId('limit-ladder-hotspot-industry-I900')).toContainText(/金融服务.*·.*1只/)
  const ladderUrlBeforeSector = new URL(page.url())
  const relatedHref = await page.getByTestId(`limit-ladder-related-${stock.code}`).getAttribute('href')
  expect(relatedHref).toContain(`/sectors/${stock.latest_related_concept.board_code}?return_to=`)
  expect(decodeURIComponent(String(relatedHref).split('return_to=')[1]))
    .toBe('/limit-ladder?restore=1')
  await page.getByTestId(`limit-ladder-related-${stock.code}`).click()
  await expect(page).toHaveURL(new RegExp(`/sectors/${stock.latest_related_concept.board_code}`))
  await expect(page.getByTestId('sector-detail-back')).toHaveText('返回连板天梯')
  await page.getByTestId('sector-detail-back').click()
  await expect(page).toHaveURL(ladderUrlBeforeSector.toString())
  await expect(page.getByTestId(`limit-ladder-card-${stock.code}`)).toBeVisible()
  await page.getByTestId(`limit-ladder-card-select-${stock.code}`).click()
  await expect(page.getByTestId('stock-analysis-panel')).toBeVisible()
  await expect(page.getByTestId('stock-analysis-benchmark')).toContainText('中证 500')
  const benchmarkOverflow = await page.getByTestId('stock-analysis-benchmark').evaluate((node) => {
    const selected = node.querySelector<HTMLElement>('.el-select__selected-item')!
    return selected.scrollWidth - selected.clientWidth
  })
  expect(benchmarkOverflow).toBeLessThanOrEqual(1)
  await expect(page.getByTestId('stock-analysis-open-detail')).toBeVisible()
  await expect(page).toHaveURL(/\/limit-ladder$/)
  // 热点现保留全部材料供宽度测量，折叠通过 inert/裁剪实现，不能再断言旧版截断的 DOM 数量。
  await expect(page.locator('.ladder-hotspots__chip')).toHaveCount(12)
  const hotspots = page.locator('#limit-ladder-hotspots')
  await expect(hotspots).toBeHidden()
  await page.getByRole('button', { name: '展开热点', exact: true }).click()
  await expect(hotspots).toBeVisible()
  await page.getByRole('button', { name: '收起热点', exact: true }).click()
  await expect(hotspots).toBeHidden()
  await expect(page.locator('.limit-ladder__summary-meta')).toHaveCount(0)
  const lowHeightLayout = await page.evaluate(() => {
    const scrollRegion = document.querySelector<HTMLElement>('[data-testid="limit-ladder-scroll-region"] .el-scrollbar__wrap')!
    const summary = document.querySelector<HTMLElement>('.limit-ladder__summary')!
    const metrics = [...summary.children].slice(0, 3).map((node) => node.getBoundingClientRect())
    const toggle = summary.querySelector<HTMLElement>('.limit-ladder__hotspots-toggle')!.getBoundingClientRect()
    return {
      scrollable: scrollRegion.scrollHeight > scrollRegion.clientHeight,
      summaryOverflow: summary.scrollWidth - summary.clientWidth,
      metricTopDelta: Math.max(...metrics.map((box) => box.top)) - Math.min(...metrics.map((box) => box.top)),
      toggleBelowMetrics: toggle.top >= Math.max(...metrics.map((box) => box.bottom)) - 1,
    }
  })
  expect(lowHeightLayout.scrollable).toBe(true)
  expect(lowHeightLayout.summaryOverflow).toBeLessThanOrEqual(1)
  expect(lowHeightLayout.metricTopDelta).toBeLessThanOrEqual(1)
  expect(lowHeightLayout.toggleBelowMetrics).toBe(true)
  await page.getByTestId('limit-ladder-layer-2').scrollIntoViewIfNeeded()
  await expect(page.getByTestId('limit-ladder-layer-2')).toBeInViewport()
  await expect(card).toBeInViewport()
  const cardLayout = await card.evaluate((node) => {
    const cardBox = node.getBoundingClientRect()
    const selectBox = node.querySelector<HTMLElement>('.limit-ladder-card__select')!.getBoundingClientRect()
    const headBox = node.querySelector<HTMLElement>('.limit-ladder-card__head')!.getBoundingClientRect()
    const metricsBox = node.querySelector<HTMLElement>('.limit-ladder-card__metrics')!.getBoundingClientRect()
    const footerBox = node.querySelector<HTMLElement>('.limit-ladder-card__foot')!.getBoundingClientRect()
    return {
      horizontalInset: cardBox.width - selectBox.width,
      headBeforeMetrics: headBox.bottom <= metricsBox.top + 1,
      metricsBeforeFooter: metricsBox.bottom <= footerBox.top + 1,
    }
  })
  expect(cardLayout.horizontalInset).toBeLessThanOrEqual(20)
  expect(cardLayout.headBeforeMetrics).toBe(true)
  expect(cardLayout.metricsBeforeFooter).toBe(true)

  const returnPath = (await readPageSession<{ returnPath?: string }>(page, auth, 'stock-set'))?.returnPath
  expect(returnPath).toBeUndefined()
  await page.getByTestId('stock-analysis-open-detail').click()
  await expect(page).toHaveURL(new RegExp(`/stocks/${stock.code.replace('.', '\\.')}$`))
  const stored = await readPageSession<{ items: unknown[]; returnPath: string }>(page, auth, 'stock-set')
  expect(stored?.items).toEqual([
    { code: stock.code, name: stock.name },
    ...firstBoardStocks.map(({ code, name }) => ({ code, name })),
  ])
  expect(stored?.returnPath).toBe('/limit-ladder?restore=1')

  await page.getByTestId('stock-detail-back').click()
  await expect(page).toHaveURL(/\/limit-ladder$/)
  const restoredCard = page.getByTestId(`limit-ladder-card-${stock.code}`)
  await expect(restoredCard).toHaveAttribute('aria-current', 'true')
  await expect(restoredCard).toBeInViewport()
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

  await page.goto('/limit-ladder')
  await page.getByTestId(`limit-ladder-card-select-${stock.code}`).click()
  const drawer = page.getByTestId('market-analysis-drawer')
  await expect(drawer).toBeVisible()
  const readGeometry = () => page.evaluate(() => {
    const pageRoot = document.querySelector('[data-testid="limit-ladder-page"]')!.getBoundingClientRect()
    const drawerRoot = document.querySelector('[data-testid="market-analysis-drawer"]')!.getBoundingClientRect()
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
