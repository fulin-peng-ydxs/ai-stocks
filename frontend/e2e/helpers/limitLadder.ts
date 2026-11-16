import type { Page } from '@playwright/test'

export const limitLadderTradeDate = '2026-08-28'
export const limitLadderStock = {
  code: '000001.SZ', name: '平安银行', board: '主板', price_limit_pct: 0.1,
  is_st: false, st_quality: 'accurate', st_source: 'e2e', is_one_word: false,
  consecutive_days: 2, amount: 123000000, industry_name: '专属行业旧值',
  industry_board_code: 'I001', source_version: 'e2e-v1', window_limit_up_days: 3,
  window_return_pct: 12.34,
  window_start_date: '2026-08-20', actual_trade_days: 8,
  snapshot_concepts: [{ board_code: 'C001', board_name: '金融科技' }],
  latest_related_industry: {
    board_code: 'I900', board_name: '金融服务', as_of_date: limitLadderTradeDate,
  },
  latest_related_concept: {
    board_code: 'C001', board_name: '金融科技', as_of_date: limitLadderTradeDate,
  },
}

const firstBoardStock = {
  ...limitLadderStock,
  code: '000002.SZ', name: '万科A', consecutive_days: 1, window_limit_up_days: 1,
  window_return_pct: -2.5,
  industry_name: '房地产',
  latest_related_industry: {
    board_code: 'I901', board_name: '地产服务', as_of_date: limitLadderTradeDate,
  },
  latest_related_concept: {
    board_code: 'C002', board_name: '国企改革', as_of_date: limitLadderTradeDate,
  },
}

export const limitLadderFirstBoardStocks = Array.from({ length: 6 }, (_, index) => (
  index === 0
    ? firstBoardStock
    : {
        ...firstBoardStock,
        code: `00000${index + 2}.SZ`,
        name: `首板样本${index + 1}`,
      }
))

const bar = {
  date: limitLadderTradeDate, open: 10, high: 11, low: 9.8, close: 10.8, pre_close: 10,
  volume: 100000, amount: 1080000, turnover_rate: 1.2,
}

export type LimitLadderE2EResult = ReturnType<typeof makeLimitLadderResult>

export function makeLimitLadderResult(overrides: Record<string, unknown> = {}) {
  return {
    trade_date: limitLadderTradeDate,
    business_code: 'READY',
    snapshot_status: 'valid',
    stored_snapshot_status: 'valid',
    has_snapshot: true,
    filters: {},
    snapshot: {
      snapshot_id: 'e2e-snapshot',
      trade_date: limitLadderTradeDate,
      computed_at: `${limitLadderTradeDate}T18:00:00`,
      stock_count: 7,
      has_approx_st: false,
      coverage: {},
    },
    requested_window_start_date: '2026-07-17',
    requested_window_trade_days: 31,
    dynamic_window_status: 'ready',
    summary: { stock_count: 7, highest_board: 2, first_board_count: 6 },
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
      { consecutive_days: 2, stock_count: 1, stocks: [limitLadderStock] },
      { consecutive_days: 1, stock_count: 6, stocks: limitLadderFirstBoardStocks },
    ],
    ...overrides,
  }
}

export function makeUnavailableLadderResult(
  businessCode: string,
  overrides: Record<string, unknown> = {},
) {
  return makeLimitLadderResult({
    business_code: businessCode,
    snapshot_status: businessCode.toLowerCase(),
    stored_snapshot_status: 'missing',
    has_snapshot: false,
    snapshot: null,
    summary: { stock_count: 0, highest_board: null, first_board_count: 0 },
    hotspots: { industry: [], concept: [] },
    layers: [],
    ...overrides,
  })
}

export interface LimitLadderE2EController {
  recomputeCount: () => number
  queryUrls: () => string[]
  setResult: (result: LimitLadderE2EResult) => void
  queueResults: (...results: LimitLadderE2EResult[]) => void
  setHttpError: (status: number | null) => void
}

/** 共享天梯 E2E 数据入口，避免分析、状态和筛选用例维护多套契约。 */
export async function installDeterministicLimitLadder(
  page: Page,
): Promise<LimitLadderE2EController> {
  let current = makeLimitLadderResult()
  let queued: LimitLadderE2EResult[] = []
  let httpError: number | null = null
  let recomputeRequests = 0
  const requestedUrls: string[] = []

  await page.route('**/api/limit-ladder/trade-dates', (route) => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({
      code: 0,
      msg: 'ok',
      data: {
        dates: [limitLadderTradeDate],
        latest_candidate_date: limitLadderTradeDate,
        latest_complete_date: limitLadderTradeDate,
        latest_candidate_coverage: {},
        latest_candidate_ready: true,
      },
    }),
  }))
  await page.route(`**/api/limit-ladder/${limitLadderTradeDate}/recompute`, (route) => {
    recomputeRequests += 1
    queued = [
      makeLimitLadderResult({
        business_code: 'SNAPSHOT_STALE',
        snapshot_status: 'recalculating',
        last_success_at: `${limitLadderTradeDate}T18:00:00`,
      }),
      current,
    ]
    return route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        code: 0,
        msg: 'ok',
        data: {
          command_id: 'e2e-command', task_id: 'e2e-task', status: 'requested', reused: false,
        },
      }),
    })
  })
  await page.route(`**/api/limit-ladder/${limitLadderTradeDate}/export?**`, (route) => route.fulfill({
    contentType: 'text/csv; charset=utf-8',
    headers: {
      'content-disposition': `attachment; filename*=UTF-8''limit-ladder-${limitLadderTradeDate}-20d.csv`,
    },
    body: '\uFEFF代码,名称,窗口涨停次数,窗口累计涨幅\n000001.SZ,平安银行,3,12.34\n',
  }))
  await page.route(new RegExp(`/api/limit-ladder/${limitLadderTradeDate}(?:\\?.*)?$`), (route) => {
    requestedUrls.push(route.request().url())
    if (httpError !== null) {
      return route.fulfill({
        status: httpError,
        contentType: 'application/json',
        body: JSON.stringify({ code: 4030, msg: '无权查看连板天梯', data: null }),
      })
    }
    const result = queued.shift() ?? current
    return route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({ code: 0, msg: 'ok', data: result }),
    })
  })
  await page.route('**/api/stocks/benchmarks/*/bars?**', (route) => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({
      code: 0, msg: 'ok', data: { code: '000905.SH', name: '中证500', bars: [bar] },
    }),
  }))
  await page.route(`**/api/stocks/${limitLadderStock.code}/bars?**`, (route) => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({
      code: 0,
      msg: 'ok',
      data: {
        code: limitLadderStock.code,
        name: limitLadderStock.name,
        adjust: 'qfq',
        bars: [bar],
      },
    }),
  }))
  await page.route(`**/api/stocks/${limitLadderStock.code}/indicators?**`, (route) => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({
      code: 0,
      msg: 'ok',
      data: {
        code: limitLadderStock.code,
        indicators: [{
          trade_date: limitLadderTradeDate,
          macd_diff: 1,
          macd_dea: 0.8,
          macd_hist: 0.2,
        }],
      },
    }),
  }))
  // 详情常驻报价与图表使用同一固定截面，避免读取开发库或空库的其它日期。
  await page.route(`**/api/stocks/${limitLadderStock.code}/quote-summary*`, (route) => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({ code: 0, msg: 'ok', data: {
      ...bar, trade_date: limitLadderTradeDate, code: limitLadderStock.code,
      name: limitLadderStock.name, board: '主板', is_st: false,
    } }),
  }))

  return {
    recomputeCount: () => recomputeRequests,
    queryUrls: () => [...requestedUrls],
    setResult: (result) => {
      current = result
      queued = []
    },
    queueResults: (...results) => { queued = [...results] },
    setHttpError: (status) => { httpError = status },
  }
}
