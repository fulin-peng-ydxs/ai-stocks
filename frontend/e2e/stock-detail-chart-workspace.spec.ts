import {
  expect,
  test,
  type APIRequestContext,
  type BrowserContext,
  type BrowserContextOptions,
  type Page,
  type Locator,
  type TestInfo,
} from '@playwright/test'
import {
  authenticateDebugUser,
  createTemporaryE2EUser,
  destroyTemporaryE2EUsers,
  installAuthSnapshot,
  installPageSession,
  loginAsDebugUser,
  saveUserPreference,
  getUserLayoutValues,
  type E2EAuthSnapshot,
  type TemporaryE2EUser,
} from './helpers/auth'
import { collectConsoleIssues } from './helpers/console'
import { panelMinHeight, stockChartWorkspaceMinHeight } from '../src/components/stock-chart/workspaceOptions'
import { expandSettingsSection } from './helpers/settings'
import { DEFAULT_E2E_API_URL } from './helpers/e2e-backend-health.mjs'

const API_URL = process.env.E2E_API_URL || DEFAULT_E2E_API_URL
test.use({ actionTimeout: 15_000 })

type PreferencePayload = {
  scope: string
  pageKey?: string
  prefKey: string
  value: unknown
  schemaVersion?: number
}

type StockSample = Record<string, unknown> & {
  code: string
  name?: string | null
  groups?: unknown[]
}

const defaultHeightRatios = {
  kline: [1],
  'kline|volume': [0.75, 0.25],
  'kline|macd': [0.75, 0.25],
  'kline|volume|macd': [0.6, 0.2, 0.2],
  'kline|macd|volume': [0.6, 0.2, 0.2],
}

function stockDetailPreference(
  slot2: 'volume' | 'macd' | 'hidden' = 'volume',
  slot3: 'volume' | 'macd' | 'hidden' = 'macd',
) {
  return {
    charts: {
      slot2,
      slot3,
      heightRatios: structuredClone(defaultHeightRatios),
    },
  }
}

const preferenceKey = (item: Pick<PreferencePayload, 'scope' | 'pageKey' | 'prefKey'>) => (
  `${item.scope}|${item.pageKey || ''}|${item.prefKey}`
)

async function getStockChartLayoutPreference(
  request: APIRequestContext,
  auth: E2EAuthSnapshot,
): Promise<{ slot2?: string; slot3?: string }> {
  const values = await getUserLayoutValues(request, auth, 'stock-detail')
  return (values['slots.chart.config.stockChart'] ?? {}) as { slot2?: string; slot3?: string }
}

function runInStandardViewport(testInfo: TestInfo) {
  test.skip(
    testInfo.project.name !== 'chromium-standard',
    '业务与权限闭环在标准视口串行执行；三关键视口由专用视觉用例覆盖',
  )
}

async function assertThreeChartTitles(workspace: Locator) {
  await expect(workspace.locator('.stock-chart-panel__title')).toHaveText(['K线', '量能', 'MACD'])
  await expect(workspace.getByRole('button', { name: 'K线口径说明', exact: true })).toBeVisible()
  await expect(workspace.getByLabel('MACD（12,26,9·前复权）图例与当前值', { exact: true })).toBeVisible()
}

async function installPreferenceEndpoint(page: Page, seeds: PreferencePayload[] = [],
  layoutSeeds: Record<string, Record<string, unknown>> = {}) {
  const store = new Map<string, PreferencePayload>()
  const writes = new Map<string, number>()
  seeds.forEach((item) => store.set(preferenceKey(item), item))
  const seededCharts = (seeds.find((item) => (
    item.scope === 'page' && item.pageKey === 'stock-detail' && item.prefKey === 'settings'
  ))?.value as { charts?: unknown } | undefined)?.charts
  const layouts = new Map<string, Record<string, unknown>>([
    ['stock-detail', seededCharts === undefined ? {} : { 'slots.chart.config.stockChart': structuredClone(seededCharts) }],
    ['stocks', {}], ['board', {}], ['sectors', {}],
  ])
  for (const [key, values] of Object.entries(layoutSeeds)) layouts.set(key, structuredClone(values))
  const layoutWrites = new Map<string, number>()
  // 每个页面都隔离组件默认值，防止上一用例写入真实调试账号后污染下一用例。
  await page.route(/\/api\/layout\/(effective|users)\/[^/?]+(?:\?.*)?$/, async route => {
    const req = route.request()
    const path = new URL(req.url()).pathname
    const pageKey = decodeURIComponent(path.split('/').at(-1)!)
    if (!layouts.has(pageKey)) return route.continue()
    if (req.method() === 'POST') {
      const body = req.postDataJSON() as { config?: { values?: Record<string, unknown> } }
      layouts.set(pageKey, structuredClone(body.config?.values ?? {}))
      layoutWrites.set(pageKey, (layoutWrites.get(pageKey) ?? 0) + 1)
    }
    const values = layouts.get(pageKey)!
    const config = { schemaVersion: 1, values }
    const data = path.includes('/effective/') ? {
      pageKey, userId: 'local', presetKey: null, schemaVersion: 1, values,
      source: Object.fromEntries(Object.keys(values).map(key => [key, 'user'])),
      layers: [{ layer: 'user', config }], componentFieldPolicies: [],
    } : { userId: 'local', pageKey, config }
    return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ code: 0, msg: 'ok', data }) })
  })

  await page.route('**/api/user-preferences*', async (route) => {
    const routedRequest = route.request()
    const url = new URL(routedRequest.url())
    const respond = (data: unknown, msg = 'ok') => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ code: 0, msg, data }),
    })
    const save = (payload: PreferencePayload) => {
      const normalized = {
        ...payload,
        pageKey: payload.pageKey || '',
        schemaVersion: payload.schemaVersion || 1,
      }
      const key = preferenceKey(normalized)
      store.set(key, normalized)
      writes.set(key, (writes.get(key) || 0) + 1)
      return normalized
    }

    if (routedRequest.method() === 'GET') {
      const scope = url.searchParams.get('scope')
      const pageKey = url.searchParams.get('pageKey')
      const prefKey = url.searchParams.get('prefKey')
      const items = [...store.values()].filter((item) => (
        (scope === null || item.scope === scope)
        && (pageKey === null || (item.pageKey || '') === pageKey)
        && (prefKey === null || item.prefKey === prefKey)
      ))
      await respond({ items })
      return
    }

    const body = routedRequest.postDataJSON() as PreferencePayload | {
      items: PreferencePayload[]
    }
    if (url.pathname.endsWith('/bulk')) {
      const items = body && 'items' in body ? body.items.map(save) : []
      await respond({ items }, '用户偏好已批量保存')
      return
    }
    await respond(save(body as PreferencePayload), '用户偏好已保存')
  })

  return {
    store,
    writesFor(key: string) {
      return writes.get(key) || 0
    },
    layoutValue(path = 'slots.chart.config.stockChart') {
      return layouts.get('stock-detail')?.[path]
    },
    layoutWrites() {
      return layoutWrites.get('stock-detail') ?? 0
    },
  }
}

async function installVisualChartEndpoints(page: Page, code: string) {
  const dates: string[] = []
  const cursor = new Date('2026-01-05T00:00:00Z')
  while (dates.length < 90) {
    const day = cursor.getUTCDay()
    if (day !== 0 && day !== 6) dates.push(cursor.toISOString().slice(0, 10))
    cursor.setUTCDate(cursor.getUTCDate() + 1)
  }
  const bars = dates.map((date, index) => {
    const previous = 20 + index * 0.035 + Math.sin((index - 1) / 6) * 0.6
    const close = 20 + index * 0.035 + Math.sin(index / 6) * 0.6
    return {
      date,
      open: Number((previous + Math.sin(index / 4) * 0.08).toFixed(2)),
      high: Number((Math.max(previous, close) + 0.22).toFixed(2)),
      low: Number((Math.min(previous, close) - 0.2).toFixed(2)),
      close: Number(close.toFixed(2)),
      pre_close: Number(previous.toFixed(2)),
      volume: 2_000_000 + index * 18_000,
      amount: 42_000_000 + index * 320_000,
      turnover_rate: 1.2 + index / 500,
    }
  })
  const indicators = dates.map((tradeDate, index) => {
    const diff = Math.sin(index / 7) * 0.42
    const dea = Math.sin((index - 2) / 7) * 0.36
    const previousDiff = Math.sin((index - 1) / 7) * 0.42
    const previousDea = Math.sin((index - 3) / 7) * 0.36
    return {
      trade_date: tradeDate,
      macd_diff: Number(diff.toFixed(4)),
      macd_dea: Number(dea.toFixed(4)),
      macd_hist: Number(((diff - dea) * 2).toFixed(4)),
      macd_golden_cross: previousDiff <= previousDea && diff > dea,
      macd_dead_cross: previousDiff >= previousDea && diff < dea,
    }
  })
  const goldenSignalIndex = indicators.findIndex((item) => item.macd_golden_cross)
  const goldenSignal = {
    index: goldenSignalIndex,
    tradeDate: dates[goldenSignalIndex],
    total: dates.length,
  }

  await page.route('**/api/stocks/*/bars*', async (route) => {
    const url = new URL(route.request().url())
    const result = url.searchParams.get('lookback') === '1' ? bars.slice(-1) : bars
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        code: 0,
        msg: 'ok',
        data: {
          code,
          name: 'E2E 视觉样本',
          adjust: url.searchParams.get('adjust') || '',
          bars: result,
        },
      }),
    })
  })
  await page.route('**/api/stocks/*/indicators*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        code: 0,
        msg: 'ok',
        data: { code, indicators },
      }),
    })
  })
  // 常驻读数必须与图表夹具同源；不能用开发库最新报价断言历史视觉样本。
  await page.route('**/api/stocks/*/quote-summary', async (route) => {
    const latestBar = bars[bars.length - 1]!
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        code: 0,
        msg: 'ok',
        data: {
          ...latestBar,
          code,
          name: 'E2E 视觉样本',
          trade_date: latestBar.date,
          board: '主板',
          industry: null,
          is_st: false,
          volume_ratio: null,
          total_mv: null,
          float_mv: null,
          total_share: null,
          float_share: null,
          pe_ttm: null,
        },
      }),
    })
  })
  await page.route('**/api/data/trade-dates', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        code: 0,
        msg: 'ok',
        data: {
          dates,
          min: dates[0],
          max: dates[dates.length - 1],
          count: dates.length,
        },
      }),
    })
  })
  // 全局快捷卡和图表共用交易日，历史视觉材料不能交给今日真实账本摘要消费。
  await page.route('**/api/trade-discipline/summary*', route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({ code: 0, msg: 'ok', data: {
      trade_date: dates.at(-1), total: 0, completed: 0, pending: 0, rules: [],
    } }),
  }))
  return {
    latestTradeDate: dates[dates.length - 1],
    closesByDate: Object.fromEntries(bars.map((bar) => [bar.date, bar.close.toFixed(2)])),
    goldenSignal,
  }
}

async function loadStockSamples(
  request: APIRequestContext,
  auth: E2EAuthSnapshot,
  size = 2,
): Promise<StockSample[]> {
  const headers = { authorization: `Bearer ${auth.accessToken}` }
  const stocksResponse = await request.get(`${API_URL}/stocks?page=1&size=${size}`, { headers })
  expect(stocksResponse.ok()).toBe(true)
  const stocksBody = await stocksResponse.json()
  expect(stocksBody.code, stocksBody.msg || '读取验收股票失败').toBe(0)
  const rows = stocksBody.data.list as StockSample[]
  expect(rows.length, '本地行情库没有足够的股票用于个股详情验收').toBeGreaterThanOrEqual(size)
  return rows
}

async function installFixedStockListEndpoint(page: Page, samples: StockSample[]) {
  await page.route(/\/api\/stocks(?:\?|$)/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        code: 0,
        msg: 'ok',
        data: {
          total: samples.length,
          page: 1,
          size: samples.length,
          trade_date: '2026-07-23',
          list: samples,
        },
      }),
    })
  })
}

async function installFixedBoardEndpoints(page: Page, samples: StockSample[]) {
  // T5 起榜单方案选择器走 listBoardProfiles('mine')（?source=mine，只拉我的方案），
  // 故 mock 必须给 mine 来源方案，否则 profiles 空 → 页面「暂无可用评分方案」不渲染榜单行。
  await page.route('**/api/board/profiles*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        code: 0,
        msg: 'ok',
        data: [{
          id: 'e2e-board-profile',
          profile_ref: 'e2e-board-profile',
          name: 'E2E 榜单方案',
          version: 1,
          source: 'mine',
          is_preset: false,
        }],
      }),
    })
  })
  await page.route('**/api/board/run', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        code: 0,
        msg: 'ok',
        data: {
          run_date: '2026-07-25',
          top: samples.length,
          count: samples.length,
          cache_status: 'cached',
          list: samples.map((sample, index) => ({
            rank: index + 1,
            code: sample.code,
            name: sample.name,
            total_score: 90 - index,
            grade: index === 0 ? '龙头候选' : '观察',
            sub_scores: {},
          })),
        },
      }),
    })
  })
}

async function loadStocksOnlyContext(page: Page, request: APIRequestContext) {
  const auth = await loginAsDebugUser(page, request, 'debug_stocks_only')
  const headers = { authorization: `Bearer ${auth.accessToken}` }
  const meResponse = await request.get(`${API_URL}/auth/me`, { headers })
  expect(meResponse.ok()).toBe(true)
  const meBody = await meResponse.json()
  expect(meBody.code, meBody.msg || '读取最小权限账号失败').toBe(0)
  expect(meBody.data.roles).toEqual(['debug_role_stocks_only'])
  const permissions = meBody.data.permissions as string[]
  expect(permissions).toContain('stocks:view')
  expect(permissions).not.toContain('stock-group:view')
  expect(permissions).not.toContain('stock-group:member-update')
  expect(permissions).not.toContain('trade-profile:view')
  expect(permissions).not.toContain('stocks:trade-eval')

  const samples = await loadStockSamples(request, auth)
  expect(samples[0].groups).toEqual([])

  return { auth, code: samples[0].code, samples }
}

async function clickStockCodeCell(page: Page, code: string): Promise<void> {
  await page.getByRole('row').filter({ hasText: code })
    .getByText(code, { exact: true })
    .click()
}

test.describe('个股详情三图工作区', () => {
  test('个股查询展开时切换走势，收起后行点击恢复详情跳转', async ({
    page,
    request,
  }, testInfo) => {
    runInStandardViewport(testInfo)
    const consoleIssues = collectConsoleIssues(page)
    const { samples } = await loadStocksOnlyContext(page, request)
    const preferences = await installPreferenceEndpoint(page, [
      {
        scope: 'page',
        pageKey: 'stocks',
        prefKey: 'settings',
        value: {
          defaultView: 'list',
          excludeSt: true,
          defaultChartMode: 'kline',
          showAnalysisPanel: true,
          compareRange: 120,
          benchmarkCode: '000300.SH',
          compareMetrics: ['cum', 'roll_30d', 'roll_60d'],
          defaultCompareMetric: 'roll_30d',
          charts: stockDetailPreference().charts,
        },
      },
      {
        scope: 'page',
        pageKey: 'sectors',
        prefKey: 'settings',
        value: {
          benchmarkCode: '000905.SH',
          compareMetrics: ['cum', 'roll_5d'],
          defaultCompareMetric: 'roll_5d',
        },
      },
    ])
    await installFixedStockListEndpoint(page, samples)
    await page.goto('/stocks')
    const analysisPanel = page.getByTestId('stock-analysis-panel')
    await expect(analysisPanel.getByLabel('股票K线多图联动工作区')).toBeVisible()

    // 主区切换只改变本次会话，不反写抽屉默认。
    await page.getByTestId('stock-analysis-mode-compare').click()
    await expect(analysisPanel.getByText('对比队列', { exact: true })).toBeVisible()
    await expect(page.getByTestId('stock-analysis-metric-roll_30d'))
      .toHaveAttribute('aria-pressed', 'true')
    await expect(page.getByTestId('stock-analysis-metric-roll_60d')).toBeVisible()
    await expect(page.getByTestId('stock-analysis-metric-roll_5d')).toHaveCount(0)
    await expect(page.getByTestId('stock-analysis-benchmark')).toContainText('沪深 300')
    await expect(page.getByTestId('stock-compare-range')).toHaveCount(0)
    await expect(page.getByTestId('stock-analysis-kline-range')).toHaveCount(0)
    await page.waitForTimeout(400)
    const settingsKey = preferenceKey({ scope: 'page', pageKey: 'stocks', prefKey: 'settings' })
    expect((preferences.store.get(settingsKey)?.value as { defaultChartMode?: string }).defaultChartMode)
      .toBeUndefined()

    // 抽屉修改默认值会通过单向会话投影立即驱动主区。
    await page.getByTestId('page-settings-trigger').click()
    const drawer = page.getByTestId('page-settings-drawer')
    const defaultMode = drawer.getByRole('group', { name: '默认图表模式' })
    await defaultMode.getByRole('button', { name: '走势对比', exact: true }).click()
    await defaultMode.getByRole('button', { name: 'K线', exact: true }).click()
    await expect(analysisPanel.getByLabel('股票K线多图联动工作区')).toBeVisible()
    await drawer.getByRole('button', { name: '关闭页面设置' }).click()

    const target = samples[1]
    await clickStockCodeCell(page, target.code)
    await expect(page).toHaveURL(/\/stocks$/)
    await expect(analysisPanel).toContainText(target.code)

    await page.getByTestId('market-hide-analysis').click()
    await clickStockCodeCell(page, target.code)
    await expect(page).toHaveURL(new RegExp(`/stocks/${target.code.replace('.', '\\.')}$`))
    expect(consoleIssues).toEqual([])
  })

  test('个股走势交易日失败可局部重试且不重拉已成功股票', async ({
    page,
    request,
  }, testInfo) => {
    runInStandardViewport(testInfo)
    const consoleIssues = collectConsoleIssues(page, { allowedHttpStatuses: [503] })
    const { auth, samples } = await loadStocksOnlyContext(page, request)
    await installPreferenceEndpoint(page, [{
      scope: 'page',
      pageKey: 'stocks',
      prefKey: 'settings',
      value: {
        defaultView: 'list',
        showAnalysisPanel: true,
        defaultChartMode: 'compare',
        benchmarkCode: '000905.SH',
        compareMetrics: ['cum'],
        defaultCompareMetric: 'cum',
      },
    }])
    await installFixedStockListEndpoint(page, samples)
    const stockBarsResponse = await request.get(
      `${API_URL}/stocks/${samples[0].code}/bars?adjust=qfq&lookback=1250`,
      { headers: { authorization: `Bearer ${auth.accessToken}` } },
    )
    expect(stockBarsResponse.ok()).toBe(true)
    const stockBarsBody = await stockBarsResponse.json()
    expect(stockBarsBody.code, stockBarsBody.msg || '读取验收行情失败').toBe(0)
    const benchmarkBars = stockBarsBody.data.bars

    let calendarRequests = 0
    let stockBarRequests = 0
    let calendarAvailable = false
    page.on('request', (routedRequest) => {
      const pathname = new URL(routedRequest.url()).pathname
      if (/\/api\/stocks\/[^/]+\/bars$/.test(pathname) && !pathname.includes('/benchmarks/')) {
        stockBarRequests += 1
      }
    })
    await page.route('**/api/stocks/benchmarks/*/bars*', async (route) => {
      calendarRequests += 1
      if (!calendarAvailable) {
        await route.fulfill({
          status: 503,
          contentType: 'application/json',
          body: JSON.stringify({ code: 5030, msg: '测试交易日暂时不可用', data: null }),
        })
        return
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          code: 0,
          msg: 'ok',
          data: {
            index_code: '000905.SH',
            name: 'E2E 中证 500',
            end: benchmarkBars.at(-1)?.date || null,
            bars: benchmarkBars,
          },
        }),
      })
    })

    await page.goto('/stocks')
    const analysisPanel = page.getByTestId('stock-analysis-panel')
    await expect(analysisPanel.getByText('市场交易日加载失败', { exact: true })).toBeVisible()
    await expect(analysisPanel).toContainText('测试交易日暂时不可用')
    const initialStockBarRequests = stockBarRequests
    const initialCalendarRequests = calendarRequests
    calendarAvailable = true

    await page.getByTestId('stock-analysis-retry-calendar').click()

    await expect(page.getByTestId('stock-analysis-retry-calendar')).toHaveCount(0)
    await expect(analysisPanel.locator('.stock-compare-chart')).toBeVisible()
    expect(calendarRequests).toBe(initialCalendarRequests + 1)
    expect(stockBarRequests).toBe(initialStockBarRequests)
    expect(consoleIssues).toEqual([])
  })

  test('每日榜单进入第二只股票后集合序号和返回来源保持一致', async ({
    page,
    request,
  }, testInfo) => {
    runInStandardViewport(testInfo)
    const consoleIssues = collectConsoleIssues(page)
    const auth = await loginAsDebugUser(page, request, 'debug_normal')
    const samples = await loadStockSamples(request, auth, 2)
    await installPreferenceEndpoint(page)
    await installFixedBoardEndpoints(page, samples)
    await installFixedStockListEndpoint(page, samples)

    await page.goto('/board')
    await clickStockCodeCell(page, samples[1].code)

    await expect(page).toHaveURL(/\/board$/)
    const analysisPanel = page.getByTestId('stock-analysis-panel')
    await expect(analysisPanel).toContainText(samples[1].code)
    await page.getByTestId('stock-analysis-mode-kline').click()
    await expect(analysisPanel.getByLabel('股票K线多图联动工作区')).toBeVisible()
    await page.getByTestId('stock-analysis-open-detail').click()

    await expect(page).toHaveURL(new RegExp(`/stocks/${samples[1].code.replace('.', '\\.')}$`))
    await expect(page.getByTestId('stock-set-navigation')).toContainText('每日榜单')
    await expect(page.getByTestId('stock-set-navigation')).toContainText('2/2')

    await page.getByTestId('stock-set-select').click()
    await expect(page.getByRole('option', {
      name: `2. ${samples[1].name || ''} ${samples[1].code}`,
    })).toBeVisible()
    await page.keyboard.press('Escape')

    await page.getByRole('button', { name: '返回每日榜单', exact: true }).click()
    await expect(page).toHaveURL(/\/board$/)
    await expect(page.getByRole('heading', { name: '每日榜单' })).toBeVisible()
    expect(consoleIssues).toEqual([])
  })

  test('debug_normal 首次进入默认显示三图和完整图名', async ({ page, request }, testInfo) => {
    runInStandardViewport(testInfo)
    const consoleIssues = collectConsoleIssues(page)
    const auth = await loginAsDebugUser(page, request, 'debug_normal')
    const [sample] = await loadStockSamples(request, auth, 1)
    await installPreferenceEndpoint(page)
    await installPageSession(page, auth, 'stock-set', {
      source: 'list',
      label: '查询结果',
      groupId: '',
      items: [{ code: sample.code, name: sample.name }],
      query: null,
      total: 1,
      loadedPages: [1],
      pageSize: 20,
      listState: null,
    })

    await page.goto(`/stocks/${sample.code}`)
    const workspace = page.getByLabel('行情多图联动工作区')
    await expect(workspace.locator('[data-panel-key]')).toHaveCount(3)
    await assertThreeChartTitles(workspace)
    await expect(workspace.getByRole('separator')).toHaveCount(2)

    await page.getByTestId('page-settings-trigger').click()
    const drawer = page.getByTestId('page-settings-drawer')
    await expect(page.locator('.el-overlay.app-drawer-surface-modal').filter({ has: drawer }))
      .toHaveCSS('background-color', 'rgba(0, 0, 0, 0.32)')
    await expect(page.getByTestId('stock-set-navigation'))
      .toHaveCSS('background-color', 'rgba(0, 0, 0, 0)')
    await expect(page.locator('.market-detail-hero'))
      .toHaveCSS('background-color', 'rgb(255, 255, 255)')
    await expect(page.locator('.stock-chart-splitter').first())
      .toHaveCSS('background-color', 'rgb(255, 255, 255)')
    await expect(drawer.locator('.sg-l1').first())
      .toHaveCSS('background-color', 'rgb(255, 255, 255)')
    await expect(drawer.getByTestId('component-chart-stock-chart-slot1-kline')).toContainText(
      '固定，不可隐藏',
    )
    await expect(drawer.getByTestId('component-chart-stock-chart-slot2-volume')).toHaveClass(/active/)
    await expect(drawer.getByTestId('component-chart-stock-chart-slot3-macd')).toHaveClass(/active/)
    expect(consoleIssues).toEqual([])
  })

  test('隐藏辅助栏后图表填满主区，快照开关即时收展分析栏', async ({ page, request }, testInfo) => {
    runInStandardViewport(testInfo)
    await page.setViewportSize({ width: 1440, height: 1100 })
    const issues = collectConsoleIssues(page)
    const auth = await loginAsDebugUser(page, request, 'debug_normal')
    const [sample] = await loadStockSamples(request, auth, 1)
    await installVisualChartEndpoints(page, sample.code)
    // 当前契约是左右主从布局，通过布局用户层关闭所有辅助内容。
    const preferences = await installPreferenceEndpoint(page, [], { 'stock-detail': {
      'slots.collectionNavigation.visible': false, 'slots.relatedBoards.visible': false,
      'slots.indicatorSnapshot.visible': false, 'slots.tradeEvaluation.visible': false,
    } })
    await page.goto(`/stocks/${sample.code}`)
    const workspace = page.getByLabel('行情多图联动工作区')
    await expect(workspace.locator('[data-panel-key]')).toHaveCount(3)
    await expect(page.getByTestId('stock-indicator-snapshot-card')).toHaveCount(0)
    await expect(page.getByTestId('stock-trade-eval-card')).toHaveCount(0)
    await expect(page.getByTestId('stock-detail-auxiliary-panel')).toBeHidden()
    const readWidth = () => workspace.evaluate(el => el.getBoundingClientRect().width)
    const hiddenWidth = await readWidth()
    const splitWidth = await page.getByTestId('stock-detail-workspace').evaluate(el => el.getBoundingClientRect().width)
    expect(hiddenWidth).toBeGreaterThanOrEqual(splitWidth - 2)
    await page.getByTestId('page-settings-trigger').click()
    const settings = page.getByTestId('page-settings-drawer')
    await expandSettingsSection(settings, '布局')
    const toggle = settings.locator('.page-toggle-row')
      .filter({ hasText: '显示最新指标快照' }).locator('.el-switch')
    await toggle.click()
    await expect(page.getByTestId('stock-indicator-snapshot-card')).toBeVisible()
    await expect(page.getByTestId('stock-detail-auxiliary-panel')).toBeVisible()
    await expect.poll(readWidth).toBeLessThan(hiddenWidth)
    await expect.poll(() => preferences.layoutValue('slots.indicatorSnapshot.visible')).toBe(true)
    await toggle.click()
    await expect(page.getByTestId('stock-indicator-snapshot-card')).toHaveCount(0)
    await expect(page.getByTestId('stock-detail-auxiliary-panel')).toBeHidden()
    await expect.poll(readWidth).toBeGreaterThanOrEqual(hiddenWidth - 2)
    await expect.poll(() => preferences.layoutValue('slots.indicatorSnapshot.visible')).toBe(false)
    expect(preferences.layoutWrites()).toBeGreaterThan(0)
    expect(issues).toEqual([])
  })

  test('debug_board_only 直达个股详情由路由守卫 fail-closed', async (
    { page, request },
    testInfo,
  ) => {
    runInStandardViewport(testInfo)
    const consoleIssues = collectConsoleIssues(page)
    const stocksAuth = await authenticateDebugUser(request, 'debug_stocks_only')
    const [sample] = await loadStockSamples(request, stocksAuth, 1)
    await loginAsDebugUser(page, request, 'debug_board_only')
    await installPreferenceEndpoint(page)

    await page.goto(`/stocks/${sample.code}`)
    await expect(page).toHaveURL(/\/board$/)
    await expect(page.getByRole('heading', { name: '每日榜单' })).toBeVisible()
    await expect(page.getByLabel('行情多图联动工作区')).toHaveCount(0)
    expect(consoleIssues).toEqual([])
  })

  test('最小权限隐藏分组能力且不覆盖被隐藏的分组偏好', async (
    { page, request },
    testInfo,
  ) => {
    runInStandardViewport(testInfo)
    const consoleIssues = collectConsoleIssues(page)
    await loadStocksOnlyContext(page, request)
    const stocksPreference: PreferencePayload = {
      scope: 'page',
      pageKey: 'stocks',
      prefKey: 'settings',
      value: { defaultView: 'group', excludeSt: true },
      schemaVersion: 1,
    }
    await page.addInitScript(value => {
      localStorage.setItem('ai-stocks:page-settings:stocks', JSON.stringify(value))
    }, stocksPreference.value)
    const stocksPreferenceKey = preferenceKey(stocksPreference)
    const preferences = await installPreferenceEndpoint(page, [stocksPreference])
    let unauthorizedSecondaryRequests = 0
    page.on('request', (pageRequest) => {
      const url = pageRequest.url()
      if (url.includes('/api/stock-groups') || url.includes('/api/trade-profiles')) {
        unauthorizedSecondaryRequests += 1
      }
    })

    await page.goto('/stocks')
    await expect(page.getByRole('columnheader', { name: '所属分组' })).toHaveCount(0)
    await page.getByTestId('page-settings-trigger').click()
    const settingsDrawer = page.getByTestId('page-settings-drawer')
    await expect(settingsDrawer).toBeVisible()
    await expect(settingsDrawer.getByTestId('stocks-default-view-list')).toBeVisible()
    await expect(settingsDrawer.getByText('显示所属分组', { exact: true })).toHaveCount(0)
    await expect(settingsDrawer.getByText('分组视图', { exact: true })).toHaveCount(0)
    await expect(settingsDrawer.getByTestId('stocks-default-view-group')).toHaveCount(0)
    await expect.poll(() => (
      (preferences.store.get(stocksPreferenceKey)?.value as { defaultView?: string }).defaultView
    )).toBe('group')

    // 等远端水合后的既有自动保存窗口结束，再统计当前选项的无效点击。
    await page.waitForTimeout(400)
    const writesBeforeListClick = preferences.writesFor(stocksPreferenceKey)
    await settingsDrawer.getByTestId('stocks-default-view-list').click()
    // 跨过 300ms 自动保存窗口，证明唯一可见选项的无效点击不会改写隐藏偏好。
    await page.waitForTimeout(400)
    await expect.poll(() => page.evaluate(() => (
      JSON.parse(window.localStorage.getItem('ai-stocks:page-settings:stocks') || '{}').defaultView
    ))).toBe('group')
    expect(
      (preferences.store.get(stocksPreferenceKey)?.value as { defaultView?: string }).defaultView,
    ).toBe('group')
    expect(preferences.writesFor(stocksPreferenceKey)).toBe(writesBeforeListClick)
    expect(unauthorizedSecondaryRequests).toBe(0)
    await settingsDrawer.getByRole('button', { name: '关闭页面设置' }).click()

    // 模拟同一登录身份恢复分组权限：隐藏期间未被覆盖的 group 偏好应重新生效。
    await page.route('**/api/auth/me', async (route) => {
      const response = await route.fetch()
      const body = await response.json()
      body.data.permissions = [...new Set([
        ...(body.data.permissions as string[]),
        'stock-group:view',
      ])]
      await route.fulfill({ response, json: body })
    })
    await page.route('**/api/stock-groups', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ code: 0, msg: 'ok', data: [] }),
      })
    })
    await page.goto('/stocks')
    await page.getByTestId('page-settings-trigger').click()
    const restoredDrawer = page.getByTestId('page-settings-drawer')
    await expect(restoredDrawer.getByTestId('stocks-default-view-group')).toBeVisible()
    await expect(restoredDrawer.getByTestId('stocks-default-view-group')).toHaveClass(/active/)
    expect(consoleIssues).toEqual([])
  })

  test('MACD 局部失败隔离，图表组合持久化且高度比例按会话或显式默认生效', async (
    { page, request },
    testInfo,
  ) => {
    runInStandardViewport(testInfo)
    const consoleIssues = collectConsoleIssues(page, { allowedHttpStatuses: [503] })
    const { samples } = await loadStocksOnlyContext(page, request)
    const [sample, nextSample] = samples
    const code = sample.code
    const preferences = await installPreferenceEndpoint(page)
    await installFixedStockListEndpoint(page, samples)
    let failNextIndicatorRequest = true
    let indicatorRequests = 0
    await page.route('**/api/stocks/*/indicators*', async (route) => {
      indicatorRequests += 1
      if (failNextIndicatorRequest) {
        failNextIndicatorRequest = false
        await route.fulfill({
          status: 503,
          contentType: 'application/json',
          body: JSON.stringify({ code: 1, msg: 'E2E MACD 局部失败', data: null }),
        })
        return
      }
      await route.continue()
    })

    await page.goto('/stocks')
    await page.getByRole('cell', { name: code, exact: true }).click()
    await expect(page).toHaveURL(/\/stocks$/)
    await page.getByTestId('market-hide-analysis').click()
    await page.getByRole('cell', { name: code, exact: true }).click()
    await expect(page).toHaveURL(new RegExp(`/stocks/${code.replace('.', '\\.')}$`))
    const workspace = page.getByLabel('行情多图联动工作区')
    await assertThreeChartTitles(workspace)
    await expect(workspace.getByText('MACD 加载失败', { exact: true })).toBeVisible()
    await expect(workspace.getByText('E2E MACD 局部失败', { exact: true })).toBeVisible()

    await page.getByRole('button', { name: '重试 MACD' }).click()
    await expect.poll(() => indicatorRequests).toBe(2)
    await expect(workspace.getByText('MACD 加载失败', { exact: true })).toHaveCount(0)

    const range = page.getByTestId('stock-detail-range')
    await range.click()
    await page.getByRole('option', { name: '近 250 日' }).click()
    await expect.poll(() => indicatorRequests).toBe(3)

    await expect(page.locator('[data-panel-key]')).toHaveCount(3)
    await expect(page.getByTestId('stock-group-select')).toHaveCount(0)
    await expect(page.getByTestId('stock-trade-eval-card')).toHaveCount(0)

    const indicatorRequestsBeforeSettings = indicatorRequests
    await page.getByTestId('page-settings-trigger').click()
    const detailSettingsDrawer = page.getByTestId('page-settings-drawer')
    await expect(detailSettingsDrawer).toBeVisible()
    await expandSettingsSection(detailSettingsDrawer, '组件设置')
    await expect(detailSettingsDrawer.getByTestId('component-chart-minHeight')).toHaveCount(0)
    const actualHeight = await workspace.evaluate(el => el.getBoundingClientRect().height)
    expect(actualHeight).toBeGreaterThanOrEqual(stockChartWorkspaceMinHeight(['kline', 'volume', 'macd'], true))
    await expect(detailSettingsDrawer.getByTestId('component-chart-stock-chart-slot1-kline')).toContainText(
      '固定，不可隐藏',
    )

    // 重复选择当前类型、按下后原位释放分隔线均不得产生无业务变化的偏好写入。
    const writesBeforeNoopActions = preferences.layoutWrites()
    await detailSettingsDrawer.getByTestId('component-chart-stock-chart-slot2-volume').click()
    await detailSettingsDrawer.getByRole('button', { name: '关闭页面设置' }).click()
    const initialSeparator = workspace.getByRole('separator').first()
    const separatorBox = await initialSeparator.boundingBox()
    expect(separatorBox).not.toBeNull()
    await page.mouse.move(
      separatorBox!.x + separatorBox!.width / 2,
      separatorBox!.y + separatorBox!.height / 2,
    )
    await page.mouse.down()
    await page.mouse.up()
    await page.waitForTimeout(400)
    expect(preferences.layoutWrites()).toBe(writesBeforeNoopActions)
    await page.getByTestId('page-settings-trigger').click()
    await expect(detailSettingsDrawer).toBeVisible()

    // 目标类型已被另一槽使用时自动交换，不产生新的行情或指标请求。
    await detailSettingsDrawer.getByTestId('component-chart-stock-chart-slot2-macd').click()
    await expect(workspace.locator('[data-panel-key="slot2"]')).toContainText('MACD')
    await expect(workspace.locator('[data-panel-key="slot3"]')).toContainText('量能')

    await detailSettingsDrawer.getByTestId('component-chart-stock-chart-slot3-hidden').click()
    await expect(page.locator('[data-panel-key]')).toHaveCount(2)
    await expect(workspace.getByRole('separator')).toHaveCount(1)
    await expect.poll(() => {
      const value = preferences.layoutValue() as { slot2?: string; slot3?: string } | undefined
      return [value?.slot2, value?.slot3]
    }).toEqual(['macd', 'hidden'])
    expect(indicatorRequests).toBe(indicatorRequestsBeforeSettings)

    await detailSettingsDrawer.getByRole('button', { name: '关闭页面设置' }).click()
    await expect(page.locator('[data-panel-key]')).toHaveCount(2)

    // 重新加载后由隔离远端偏好恢复组合，不依赖共享调试账号 PG 历史值。
    await page.reload()
    await expect(page.locator('[data-panel-key]')).toHaveCount(2)
    await expect(workspace.locator('[data-panel-key="slot2"]')).toContainText('MACD')
    await expect(workspace.locator('[data-panel-key="slot3"]')).toHaveCount(0)

    const draggedSeparator = workspace.getByRole('separator').first()
    await draggedSeparator.scrollIntoViewIfNeeded()
    await draggedSeparator.hover()
    const dragSeparatorBox = await draggedSeparator.boundingBox()
    const workspaceBox = await workspace.boundingBox()
    expect(dragSeparatorBox).not.toBeNull()
    expect(workspaceBox).not.toBeNull()
    const ratioBeforePointer = await draggedSeparator.getAttribute('aria-valuenow')
    await page.mouse.move(
      dragSeparatorBox!.x + dragSeparatorBox!.width / 2,
      dragSeparatorBox!.y + dragSeparatorBox!.height / 2,
    )
    await page.mouse.down()
    await page.mouse.move(
      dragSeparatorBox!.x + dragSeparatorBox!.width / 2,
      Math.max(
        1,
        dragSeparatorBox!.y + dragSeparatorBox!.height / 2 - workspaceBox!.height * 0.8,
      ),
      { steps: 5 },
    )
    await page.mouse.up()
    await expect(draggedSeparator).not.toHaveAttribute('aria-valuenow', ratioBeforePointer || '')
    // 主区拖动只改变当前会话，不写回页面默认比例。
    await expect.poll(() => {
      const value = preferences.layoutValue() as {
        heightRatios?: Record<string, number[]>
      } | undefined
      return value?.heightRatios?.['kline|macd']
    }).toEqual([0.75, 0.25])
    const panelHeights = await workspace.locator('[data-panel-key]').evaluateAll((panels) => (
      panels.map((panel) => panel.getBoundingClientRect().height)
    ))
    expect(panelHeights[0]).toBeGreaterThanOrEqual(panelMinHeight('kline', true))
    expect(panelHeights[1]).toBeGreaterThanOrEqual(panelMinHeight('macd', true))

    await page.getByTestId('stock-set-select').click()
    await page.getByRole('option').filter({ hasText: nextSample.code }).click()
    await expect(page).toHaveURL(new RegExp(`/stocks/${nextSample.code.replace('.', '\\.')}$`))
    await expect(workspace.getByRole('separator').first()).toHaveAttribute(
      'aria-valuenow',
      ratioBeforePointer || '',
    )
    await page.reload()
    await expect(workspace.locator('[data-panel-key="slot2"]')).toContainText('MACD')
    await expect(workspace.getByRole('separator').first()).toHaveAttribute(
      'aria-valuenow',
      ratioBeforePointer || '',
    )
    const firstSeparator = workspace.getByRole('separator').first()
    const ratioBeforeKeyboard = await firstSeparator.getAttribute('aria-valuenow')
    await firstSeparator.press('ArrowDown')
    await expect(firstSeparator).not.toHaveAttribute('aria-valuenow', ratioBeforeKeyboard || '')
    const ratioAfterKeyboard = await firstSeparator.getAttribute('aria-valuenow')
    await expect.poll(() => {
      const value = preferences.layoutValue() as {
        heightRatios?: Record<string, number[]>
      } | undefined
      return value?.heightRatios?.['kline|macd']
    }).toEqual([0.75, 0.25])

    await page.getByTestId('page-settings-trigger').click()
    const resetDrawer = page.getByTestId('page-settings-drawer')
    await resetDrawer.getByTestId('component-chart-stock-chart-save-current-ratios').click()
    await expect.poll(() => {
      const value = preferences.layoutValue() as {
        heightRatios?: Record<string, number[]>
      } | undefined
      return value?.heightRatios?.['kline|macd']
    }).not.toEqual([0.75, 0.25])
    await page.reload()
    await expect(workspace.getByRole('separator').first()).toHaveAttribute(
      'aria-valuenow',
      ratioAfterKeyboard || '',
    )
    const indicatorRequestsAfterPersistenceChecks = indicatorRequests
    await page.getByTestId('page-settings-trigger').click()
    await resetDrawer.getByTestId('page-settings-reset').click()
    await expect(page.locator('[data-panel-key]')).toHaveCount(3)
    await expect(resetDrawer.getByTestId('component-chart-stock-chart-slot2-volume')).toHaveClass(/active/)
    await expect(resetDrawer.getByTestId('component-chart-stock-chart-slot3-macd')).toHaveClass(/active/)
    await expect(workspace.getByRole('separator').first()).toHaveAttribute('aria-valuenow', '60')
    // 重置是清除用户层覆盖，界面回退到 registry 默认值，不再把默认值冗余写回用户层。
    await expect.poll(() => preferences.layoutValue()).toBeUndefined()
    expect(indicatorRequests).toBe(indicatorRequestsAfterPersistenceChecks)
    expect(consoleIssues).toEqual([])
  })

  test('两个临时普通用户的 PG 图表偏好相互隔离', async ({
    browser,
    request,
  }, testInfo) => {
    runInStandardViewport(testInfo)

    const prefParams = { scope: 'page', pageKey: 'stock-detail', prefKey: 'settings' }
    const temporaryUsers: TemporaryE2EUser[] = []
    let normalContext: BrowserContext | undefined
    let secondaryContext: BrowserContext | undefined

    try {
      const normalUser = await createTemporaryE2EUser(request, 'normal')
      temporaryUsers.push(normalUser)
      const secondaryUser = await createTemporaryE2EUser(request, 'normal')
      temporaryUsers.push(secondaryUser)
      const normalAuth = await authenticateDebugUser(request, normalUser.account)
      const secondaryAuth = await authenticateDebugUser(request, secondaryUser.account)
      const [sample] = await loadStockSamples(request, normalAuth, 1)

      await saveUserPreference(request, normalAuth, {
        ...prefParams,
        value: stockDetailPreference('volume', 'macd'),
      })
      await saveUserPreference(request, secondaryAuth, {
        ...prefParams,
        value: stockDetailPreference('macd', 'volume'),
      })

      const contextOptions: BrowserContextOptions = {
        baseURL: testInfo.project.use.baseURL,
        viewport: testInfo.project.use.viewport,
      }
      normalContext = await browser.newContext(contextOptions)
      secondaryContext = await browser.newContext(contextOptions)
      const normalPage = await normalContext.newPage()
      const secondaryPage = await secondaryContext.newPage()
      const normalConsoleIssues = collectConsoleIssues(normalPage)
      const secondaryConsoleIssues = collectConsoleIssues(secondaryPage)
      await installAuthSnapshot(normalPage, normalAuth)
      await installAuthSnapshot(secondaryPage, secondaryAuth)

      await Promise.all([
        normalPage.goto(`/stocks/${sample.code}`),
        secondaryPage.goto(`/stocks/${sample.code}`),
      ])
      const normalWorkspace = normalPage.getByLabel('行情多图联动工作区')
      const secondaryWorkspace = secondaryPage.getByLabel('行情多图联动工作区')
      await expect(normalWorkspace.locator('[data-panel-key]')).toHaveCount(3)
      await expect(normalWorkspace.locator('[data-panel-key="slot2"]')).toContainText('量能')
      await expect(secondaryWorkspace.locator('[data-panel-key]')).toHaveCount(3)
      await expect(secondaryWorkspace.locator('[data-panel-key="slot2"]')).toContainText('MACD')

      await normalPage.getByTestId('page-settings-trigger').click()
      await normalPage.getByTestId('component-chart-stock-chart-slot3-hidden').click()
      await expect(normalWorkspace.locator('[data-panel-key]')).toHaveCount(2)
      await expect.poll(async () => {
        const value = await getStockChartLayoutPreference(request, normalAuth)
        return [value.slot2, value.slot3]
      }).toEqual(['volume', 'hidden'])
      const secondaryValue = await getStockChartLayoutPreference(request, secondaryAuth)
      expect([secondaryValue.slot2, secondaryValue.slot3]).toEqual(['macd', 'volume'])

      await Promise.all([normalPage.reload(), secondaryPage.reload()])
      await expect(normalWorkspace.locator('[data-panel-key]')).toHaveCount(2)
      await expect(normalWorkspace.locator('[data-panel-key="slot2"]')).toContainText('量能')
      await expect(secondaryWorkspace.locator('[data-panel-key]')).toHaveCount(3)
      await expect(secondaryWorkspace.locator('[data-panel-key="slot2"]')).toContainText('MACD')
      expect(normalConsoleIssues).toEqual([])
      expect(secondaryConsoleIssues).toEqual([])
    } finally {
      await normalContext?.close()
      await secondaryContext?.close()
      await destroyTemporaryE2EUsers(request, temporaryUsers)
    }
  })

  test('偏好接口 403 时使用本地 fallback 并继续保存当前用户调整', async ({
    page,
    request,
  }, testInfo) => {
    runInStandardViewport(testInfo)
    const consoleIssues = collectConsoleIssues(page, { allowedHttpStatuses: [403] })
    const auth = await loginAsDebugUser(page, request, 'debug_normal')
    const [sample] = await loadStockSamples(request, auth, 1)
    const localPreference = stockDetailPreference('macd', 'hidden')
    await page.addInitScript((value) => {
      window.localStorage.setItem('ai-stocks:page-settings:stock-detail', JSON.stringify(value))
    }, localPreference)
    let remoteWriteAttempts = 0
    await page.route('**/api/user-preferences*', async (route) => {
      if (route.request().method() !== 'GET') remoteWriteAttempts += 1
      await route.fulfill({
        status: 403,
        contentType: 'application/json',
        body: JSON.stringify({ code: 403, msg: 'E2E 偏好服务无权限', data: null }),
      })
    })
    await page.route('**/api/layout/effective/stock-detail*', async (route) => {
      await route.fulfill({
        status: 403,
        contentType: 'application/json',
        body: JSON.stringify({ code: 403, msg: 'E2E 布局服务无权限', data: null }),
      })
    })
    await page.route('**/api/layout/users/stock-detail*', async (route) => {
      remoteWriteAttempts += 1
      await route.fulfill({
        status: 403,
        contentType: 'application/json',
        body: JSON.stringify({ code: 403, msg: 'E2E 布局服务无权限', data: null }),
      })
    })

    await page.goto(`/stocks/${sample.code}`)
    const workspace = page.getByLabel('行情多图联动工作区')
    await expect(workspace.locator('[data-panel-key]')).toHaveCount(2)
    await expect(workspace.locator('[data-panel-key="slot2"]')).toContainText('MACD')

    await page.getByTestId('page-settings-trigger').click()
    await page.getByTestId('component-chart-stock-chart-slot3-volume').click()
    await expect(workspace.locator('[data-panel-key]')).toHaveCount(3)
    await expect.poll(() => page.evaluate(() => {
      const value = JSON.parse(
        window.localStorage.getItem('ai-stocks:layout-cc:stock-detail') || '{}',
      )
      const stockChart = value.values?.['slots.chart.config.stockChart']
      return [stockChart?.slot2, stockChart?.slot3]
    })).toEqual(['macd', 'volume'])
    await expect.poll(() => remoteWriteAttempts).toBeGreaterThan(0)
    expect(consoleIssues).toEqual([])
  })

  test('关键视口保持纵向三图、语义主题和 reduced-motion 契约', async ({
    page,
    request,
  }, testInfo) => {
    const consoleIssues = collectConsoleIssues(page)
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await page.addInitScript(() => {
      window.localStorage.setItem('ai-stocks-theme', 'light')
      window.localStorage.setItem('ai-stocks:layout-preset', 'balanced')
    })
    const { code } = await loadStocksOnlyContext(page, request)
    const { latestTradeDate, closesByDate, goldenSignal } = await installVisualChartEndpoints(page, code)
    await installPreferenceEndpoint(page, [{
      scope: 'page',
      pageKey: 'stock-detail',
      prefKey: 'settings',
      value: stockDetailPreference(),
      schemaVersion: 1,
    }])

    await page.goto(`/stocks/${code}`)
    const workspace = page.getByLabel('行情多图联动工作区')
    await expect(workspace.locator('[data-panel-key]')).toHaveCount(3)
    await assertThreeChartTitles(workspace)
    await expect(workspace.locator('.el-loading-mask')).toHaveCount(0)
    await expect(workspace.getByText('MACD 数据加载中', { exact: true })).toHaveCount(0)
    const shellTradeDate = page
      .getByLabel('交易日状态（无详情权限）')
      .getByText(latestTradeDate, { exact: true })
    await expect(shellTradeDate).toBeVisible()

    const geometry = await workspace.evaluate((element) => {
      const panels = [...element.querySelectorAll<HTMLElement>('[data-panel-key]')]
        .map((panel) => panel.getBoundingClientRect())
      const rect = element.getBoundingClientRect()
      const splitter = element.querySelector<HTMLElement>('[role="separator"]')
      const scrollRegion = element.closest<HTMLElement>('.v-scroll')
      return {
        workspaceHeight: rect.height,
        panelTops: panels.map((panel) => panel.top),
        splitterTransition: splitter ? getComputedStyle(splitter).transitionDuration : '',
      chartFitsItsPane: rect.bottom <= element.closest('[data-testid="stock-detail-chart-panel"]')!.getBoundingClientRect().bottom + 1,
        noHorizontalOverflow:
          document.documentElement.scrollWidth <= document.documentElement.clientWidth,
      }
    })
    expect(geometry.workspaceHeight).toBeGreaterThanOrEqual(stockChartWorkspaceMinHeight(['kline', 'volume', 'macd'], true))
    expect(geometry.panelTops[1]).toBeGreaterThan(geometry.panelTops[0])
    expect(geometry.panelTops[2]).toBeGreaterThan(geometry.panelTops[1])
    expect(geometry.splitterTransition).toBe('0s')
    expect(geometry.chartFitsItsPane).toBe(true)
    expect(geometry.noHorizontalOverflow).toBe(true)

    const panelDates = workspace.locator('.stock-chart-panel__date')
    const headerQuote = page.getByTestId('stock-latest-quote')
    const headerPrice = headerQuote.locator('.stock-quote-summary__hero dd')
    await expect(headerQuote).toBeVisible()
    await expect(headerPrice).toHaveText(closesByDate[latestTradeDate])
    await expect(panelDates).toHaveCount(1)
    const latestPanelDates = await panelDates.allTextContents()
    expect(latestPanelDates.map((value) => value.trim())).toEqual([latestTradeDate])
    const klineCanvas = workspace.getByLabel('K线（前复权）图表')
    await klineCanvas.scrollIntoViewIfNeeded()
    const klineRenderCanvas = klineCanvas.locator('svg').first()
    await expect(klineRenderCanvas).toBeVisible()
    const klineCanvasBox = await klineRenderCanvas.boundingBox()
    expect(klineCanvasBox).not.toBeNull()
    await page.mouse.move(1, 1)
    await page.mouse.move(
      klineCanvasBox!.x + klineCanvasBox!.width * 0.25,
      klineCanvasBox!.y + klineCanvasBox!.height * 0.5,
      { steps: 4 },
    )
    await expect.poll(async () => {
      const values = (await panelDates.allTextContents()).map((value) => value.trim())
      return values.length === 1 && values[0] !== latestTradeDate
    }).toBe(true)
    const hoveredDate = (await panelDates.first().innerText()).trim()
    expect(closesByDate[hoveredDate], '光标日期须对应确定性行情夹具').toBeDefined()
    await expect(headerPrice).toHaveText(closesByDate[hoveredDate])
    await expect(workspace.locator('.stock-chart-kline-tooltip')).toHaveCount(0)
    await testInfo.attach('stock-detail-linked-header-quote', {
      body: await page.screenshot(),
      contentType: 'image/png',
    })
    await page.mouse.move(1, 1)
    await expect(panelDates.first()).toHaveText(latestTradeDate)
    await expect(headerPrice).toHaveText(closesByDate[latestTradeDate])

    const lightBackground = await workspace.evaluate(
      (element) => getComputedStyle(element).backgroundColor,
    )
    await testInfo.attach('stock-detail-light', {
      body: await page.screenshot(),
      contentType: 'image/png',
    })
    await testInfo.attach('stock-detail-workspace-light', {
      body: await workspace.screenshot(),
      contentType: 'image/png',
    })
    const macdPanel = workspace.locator('[data-panel-key="slot3"]')
    await macdPanel.scrollIntoViewIfNeeded()
    await expect(macdPanel.locator('.stock-chart-panel__title')).toHaveText('MACD')
    const macdRenderCanvas = macdPanel.getByLabel('MACD（12,26,9·前复权）图表')
      .locator('svg')
      .first()
    const signalTooltip = workspace.locator('.stock-chart-macd-signal-tooltip')
    // SVG 暴露了实际信号文字，直接悬停首个金叉；不按旧画布高度猜测命中坐标。
    const firstGoldenLabel = macdRenderCanvas.locator('text').filter({ hasText: /^金叉$/ }).first()
    await expect(firstGoldenLabel).toBeVisible()
    await firstGoldenLabel.hover()
    await expect(signalTooltip).toBeVisible()
    await expect(signalTooltip).toContainText('金叉')
    await expect(signalTooltip).toContainText(`交易日：${goldenSignal.tradeDate}`)
    await testInfo.attach('stock-detail-macd-signal-tooltip', {
      body: await macdPanel.screenshot(),
      contentType: 'image/png',
    })
    await page.mouse.move(1, 1)
    await expect(signalTooltip).not.toBeVisible()
    await testInfo.attach('stock-detail-macd-light', {
      body: await macdPanel.screenshot(),
      contentType: 'image/png',
    })

    await page.getByRole('button', { name: '视觉环境' }).click()
    await page.getByTestId('appearance-theme-mode-dark').click()
    await expect(page.locator('html')).toHaveClass(/dark/)
    const darkBackground = await workspace.evaluate(
      (element) => getComputedStyle(element).backgroundColor,
    )
    expect(darkBackground).not.toBe(lightBackground)
    await expect(page.getByText('视觉预设', { exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: /澄空蓝/ })).toHaveCount(1)
    const closeAppearance = page.getByRole('button', { name: '关闭视觉环境' })
    await closeAppearance.click()
    await expect(closeAppearance).toBeHidden()
    await expect(shellTradeDate).toBeVisible()
    await testInfo.attach('stock-detail-dark-blue', {
      body: await page.screenshot(),
      contentType: 'image/png',
    })
    await testInfo.attach('stock-detail-workspace-dark-blue', {
      body: await workspace.screenshot(),
      contentType: 'image/png',
    })
    await macdPanel.scrollIntoViewIfNeeded()
    await testInfo.attach('stock-detail-macd-dark-blue', {
      body: await macdPanel.screenshot(),
      contentType: 'image/png',
    })

    const macdCanvas = workspace
      .getByLabel('MACD（12,26,9·前复权）图表')
      .locator('svg')
    await expect(macdCanvas).toHaveCount(1)
    await macdCanvas.scrollIntoViewIfNeeded()
    const macdCanvasBox = await macdCanvas.boundingBox()
    expect(macdCanvasBox).not.toBeNull()
    // 紧凑自适应面板可能隐藏缩放条，画布内滚轮缩放在所有目标视口仍可用。
    await page.mouse.move(macdCanvasBox!.x + macdCanvasBox!.width * 0.5, macdCanvasBox!.y + macdCanvasBox!.height * 0.5)
    for (let step = 0; step < 3; step += 1) {
      const previousStart = Number(await workspace.getAttribute('data-zoom-start'))
      await page.mouse.wheel(0, -600)
      await expect.poll(async () => Number(await workspace.getAttribute('data-zoom-start')))
        .toBeGreaterThan(previousStart)
    }
    await expect.poll(async () => Number(await workspace.getAttribute('data-zoom-start')))
      .toBeGreaterThan(10)

    expect(consoleIssues).toEqual([])
  })

  test('页面加载、空数据和 permission 状态保持正确图层', async (
    { page, request },
    testInfo,
  ) => {
    runInStandardViewport(testInfo)
    const consoleIssues = collectConsoleIssues(page, { allowedHttpStatuses: [403] })
    const { code } = await loadStocksOnlyContext(page, request)
    await installPreferenceEndpoint(page)

    let releaseBars!: () => void
    const barsGate = new Promise<void>((resolve) => { releaseBars = resolve })
    await page.route('**/api/stocks/*/bars*', async (route) => {
      const url = new URL(route.request().url())
      if (url.searchParams.get('lookback') === '1') {
        await route.continue()
        return
      }
      await barsGate
      await route.continue()
    })

    await page.goto(`/stocks/${code}`)
    await expect(page.getByText('正在加载个股行情…', { exact: true }).filter({ visible: true })).toHaveCount(1)
    await expect(page.getByLabel('行情多图联动工作区')).toBeHidden()
    releaseBars()
    const workspace = page.getByLabel('行情多图联动工作区')
    await expect(workspace.getByText('K线', { exact: true })).toBeVisible()

    await page.unroute('**/api/stocks/*/bars*')
    await page.route('**/api/stocks/*/bars*', async (route) => {
      const url = new URL(route.request().url())
      if (url.searchParams.get('lookback') === '1') {
        await route.continue()
        return
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          code: 0,
          msg: 'ok',
          data: { code, name: 'E2E 空行情', adjust: 'qfq', bars: [] },
        }),
      })
    })
    await page.reload()
    await expect(page.getByText('当前股票在所选范围内没有可用行情', { exact: true }))
      .toBeVisible()
    await expect(page.getByLabel('行情多图联动工作区')).toHaveCount(0)

    await page.unroute('**/api/stocks/*/bars*')
    await page.route('**/api/stocks/*/bars*', async (route) => {
      const url = new URL(route.request().url())
      if (url.searchParams.get('lookback') === '1') {
        await route.continue()
        return
      }
      await route.fulfill({
        status: 403,
        contentType: 'application/json',
        body: JSON.stringify({ code: 403, msg: 'E2E stocks:view 已撤销', data: null }),
      })
    })
    await page.reload()
    await expect(page.getByText('无权限查看个股详情', { exact: true })).toBeVisible()
    await expect(page.getByText('请联系系统管理员调整股票查看权限', { exact: true }))
      .toBeVisible()
    await expect(page.getByLabel('行情多图联动工作区')).toHaveCount(0)
    expect(consoleIssues).toEqual([])
  })
})
