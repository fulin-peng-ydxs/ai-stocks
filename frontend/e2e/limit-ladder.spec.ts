import { expect, test, type TestInfo } from '@playwright/test'
import { loginAsDebugUser } from './helpers/auth'
import { collectConsoleIssues } from './helpers/console'
import {
  installDeterministicLimitLadder,
  limitLadderStock,
  limitLadderTradeDate,
  makeLimitLadderResult,
  makeUnavailableLadderResult,
} from './helpers/limitLadder'

function latestQueryParams(urls: string[]): URLSearchParams {
  const latest = urls.at(-1)
  if (!latest) throw new Error('连板天梯未发起查询')
  return new URL(latest).searchParams
}

test('三档桌面视口完成组合筛选、热点、短历史与 CSV 导出', async ({
  page,
  request,
}, testInfo: TestInfo) => {
  const consoleIssues = collectConsoleIssues(page)
  await loginAsDebugUser(page, request, 'debug_system')
  const fixture = await installDeterministicLimitLadder(page)

  await page.goto(`/limit-ladder?date=${limitLadderTradeDate}&window=31&boards=main,star,gem&ignore_st=1`)
  await expect(page.getByTestId(`limit-ladder-card-${limitLadderStock.code}`)).toBeVisible()
  await expect(page.getByTestId('limit-ladder-short-history').first())
    .toContainText('窗口仅 8 日 · 自 2026-08-20 起')

  await page.getByTestId('limit-ladder-window-20').click()
  await expect.poll(() => latestQueryParams(fixture.queryUrls()).get('window')).toBe('20')
  await page.getByTestId('limit-ladder-one-word').check()
  await expect.poll(() => latestQueryParams(fixture.queryUrls()).get('one_word_only')).toBe('true')
  await page.getByTestId('limit-ladder-hotspot-concept-C001').click()
  await expect.poll(() => ({
    type: latestQueryParams(fixture.queryUrls()).get('hotspot_type'),
    key: latestQueryParams(fixture.queryUrls()).get('hotspot_key'),
  })).toEqual({ type: 'concept', key: 'C001' })
  await page.getByPlaceholder('代码 / 名称').fill('平安')
  await page.getByPlaceholder('代码 / 名称').press('Enter')
  await expect.poll(() => latestQueryParams(fixture.queryUrls()).get('keyword')).toBe('平安')

  const downloadPromise = page.waitForEvent('download')
  await page.getByTestId('limit-ladder-export').click()
  const download = await downloadPromise
  expect(download.suggestedFilename()).toBe(`limit-ladder-${limitLadderTradeDate}-20d.csv`)

  await page.getByTestId('limit-ladder-reset').click()
  await expect.poll(() => ({
    window: latestQueryParams(fixture.queryUrls()).get('window'),
    oneWordOnly: latestQueryParams(fixture.queryUrls()).get('one_word_only'),
    keyword: latestQueryParams(fixture.queryUrls()).get('keyword'),
  })).toEqual({ window: '31', oneWordOnly: 'false', keyword: null })
  await expect(page.getByTestId('limit-ladder-reset').locator('.el-icon')).toHaveCount(0)

  const geometry = await page.evaluate(() => {
    const pageRoot = document.querySelector('[data-testid="limit-ladder-page"]')!
      .getBoundingClientRect()
    const cards = [...document.querySelectorAll('.limit-ladder-card')]
      .map((node) => node.getBoundingClientRect())
    const controls = [...document.querySelectorAll<HTMLElement>(
      '.limit-ladder__toolbar .app-control-row > *',
    )].map((node) => node.getBoundingClientRect())
    const overlaps = controls.reduce((count, box, index) => (
      count + controls.slice(index + 1).filter((other) => (
        Math.min(box.right, other.right) - Math.max(box.left, other.left) > 1
        && Math.min(box.bottom, other.bottom) - Math.max(box.top, other.top) > 1
      )).length
    ), 0)
    return {
      pageOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      pageWidth: pageRoot.width,
      cardWidthDelta: Math.max(...cards.map((box) => box.width))
        - Math.min(...cards.map((box) => box.width)),
      controlHeights: controls.map((box) => box.height),
      overlaps,
    }
  })
  expect(geometry.pageOverflow).toBeLessThanOrEqual(1)
  expect(geometry.pageWidth).toBeGreaterThan(0)
  expect(geometry.cardWidthDelta).toBeLessThanOrEqual(1)
  expect(geometry.controlHeights.every((height) => Math.abs(height - 32) <= 1)).toBe(true)
  expect(geometry.overlaps).toBe(0)

  const screenshotPath = testInfo.outputPath(`limit-ladder-${testInfo.project.name}.png`)
  await page.screenshot({ path: screenshotPath, fullPage: true })
  await testInfo.attach(`limit-ladder-${testInfo.project.name}`, {
    path: screenshotPath,
    contentType: 'image/png',
  })
  expect(consoleIssues).toEqual([])
})

test('首次计算、覆盖失败、过期、空结果与 403 保持互斥状态', async ({
  page,
  request,
}, testInfo: TestInfo) => {
  test.skip(testInfo.project.name !== 'chromium-standard', '状态矩阵在标准视口串行验证')
  const consoleIssues = collectConsoleIssues(page, { allowedHttpStatuses: [403] })
  await loginAsDebugUser(page, request, 'debug_system')
  const fixture = await installDeterministicLimitLadder(page)
  fixture.queueResults(
    makeUnavailableLadderResult('SNAPSHOT_PENDING', { snapshot_status: 'calculating' }),
    makeLimitLadderResult(),
  )

  await page.goto(`/limit-ladder?date=${limitLadderTradeDate}&window=31&boards=main,star,gem&ignore_st=1`)
  await expect(page.getByTestId('limit-ladder-state')).toContainText('天梯快照正在计算')
  await expect(page.getByTestId('limit-ladder-state')).toContainText('页面最多等待 2 分钟')
  await expect(page.getByTestId('limit-ladder-summary-total')).toHaveText('7', { timeout: 5_000 })
  await expect(page.getByTestId('limit-ladder-state')).toHaveCount(0)

  fixture.setResult(makeUnavailableLadderResult('NOT_TRADING_DAY', {
    nearest_previous_trade_date: '2026-08-27',
  }))
  await page.reload()
  await expect(page.getByTestId('limit-ladder-state')).toContainText('最近交易日为 2026-08-27')

  const coverageReasons = [
    ['POINT_IN_TIME_POOL_EMPTY', '当日点时股票池为空'],
    ['INGEST_PARTIAL', '当日行情采集未完整成功'],
    ['MISSING_BAR_OR_SUSPENSION', '部分股票缺少行情或停牌确认'],
    ['INVALID_DAILY_BAR', '部分日行情字段无效'],
    ['UNSUPPORTED_LIMIT_RULE', '部分股票无法可靠判断涨停规则'],
  ] as const
  for (const [code, label] of coverageReasons) {
    fixture.setResult(makeUnavailableLadderResult('SNAPSHOT_NOT_READY', {
      coverage: { reason_codes: [code] },
    }))
    await page.reload()
    await expect(page.getByTestId('limit-ladder-state')).toContainText(label)
    if (code === 'INGEST_PARTIAL') {
      await expect(page.getByTestId('limit-ladder-state'))
        .toContainText('请前往“数据采集”执行“日常同步”')
      await expect(page.getByRole('button', { name: '去补采行情' })).toBeVisible()
    }
    await expect(page.getByTestId('limit-ladder-summary-total')).toHaveCount(0)
  }

  fixture.setResult(makeUnavailableLadderResult('SNAPSHOT_FAILED', {
    snapshot_status: 'failed',
    failure_summary: 'MISSING_BAR_OR_SUSPENSION',
  }))
  await page.reload()
  await expect(page.getByTestId('limit-ladder-state')).toContainText('天梯快照计算失败')
  await page.getByRole('button', { name: '重新计算', exact: true }).click()
  await page.getByRole('button', { name: '确认重算' }).click()
  await expect.poll(fixture.recomputeCount).toBe(1)
  await expect(page.getByTestId('limit-ladder-state')).toContainText('天梯快照计算失败', {
    timeout: 5_000,
  })

  fixture.setResult(makeLimitLadderResult({
    business_code: 'SNAPSHOT_STALE',
    snapshot_status: 'failed',
    last_success_at: `${limitLadderTradeDate}T18:00:00`,
    failure_summary: 'INVALID_DAILY_BAR',
  }))
  await page.reload()
  await expect(page.getByTestId('limit-ladder-stale-notice')).toContainText('结果已过期')
  await expect(page.getByTestId('limit-ladder-summary-total')).toHaveText('7')

  fixture.setResult(makeLimitLadderResult({
    business_code: 'EMPTY_SNAPSHOT',
    snapshot: {
      snapshot_id: 'e2e-empty',
      trade_date: limitLadderTradeDate,
      computed_at: `${limitLadderTradeDate}T18:00:00`,
      stock_count: 0,
      has_approx_st: false,
      coverage: {},
    },
    summary: { stock_count: 0, highest_board: null, first_board_count: 0 },
    hotspots: { industry: [], concept: [] },
    layers: [],
  }))
  await page.reload()
  await expect(page.getByTestId('limit-ladder-state')).toContainText('当日无涨停股票')

  fixture.setResult(makeLimitLadderResult({
    business_code: 'FILTER_EMPTY',
    summary: { stock_count: 0, highest_board: null, first_board_count: 0 },
    hotspots: { industry: [], concept: [] },
    layers: [],
  }))
  await page.reload()
  await expect(page.getByTestId('limit-ladder-state')).toContainText('当前筛选无匹配股票')

  fixture.setHttpError(403)
  await page.reload()
  await expect(page.getByTestId('limit-ladder-state')).toContainText('无权限查看连板天梯')
  await expect(page.getByTestId('limit-ladder-state')).toContainText('请联系系统管理员调整权限')
  await expect(page.getByTestId('limit-ladder-state').getByRole('button', { name: '重试' })).toHaveCount(0)
  await expect(page.getByTestId('limit-ladder-summary-total')).toHaveCount(0)
  expect(consoleIssues).toEqual([])
})
