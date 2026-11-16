import { expect, type APIRequestContext, type Page } from '@playwright/test'
import type { LedgerContext, LedgerHistoryRow, LedgerSnapshot } from '../../src/api/tradeLedger'
import { DEFAULT_E2E_API_URL } from './e2e-backend-health.mjs'

export const TRADE_DISCIPLINE_API = process.env.E2E_API_URL || DEFAULT_E2E_API_URL
export const TRADE_DISCIPLINE_FIXTURE = {
  idPrefix: 'e2e_td_', namePrefix: 'E2E纪律-',
  openingTradeDate: '2098-06-02', currentTradeDate: '2098-06-10', pendingTradeDate: '2098-06-11',
  operationTradeDate: '2098-06-05', latestSeededTradeDate: '2098-06-09',
  ledgerDates: ['2098-06-04', '2098-06-05', '2098-06-06', '2098-06-09'],
  stockCodes: ['998801.SZ', '998802.SZ', '998803.SZ'],
} as const

/** 界面接线用完整账户结构；不能把此固定材料当成真实记账执行证据。 */
export function makeLedgerSnapshot(overrides: Partial<LedgerSnapshot> = {}): LedgerSnapshot {
  return {
    trade_date: '2026-08-21', revision_no: 1, events: [], positions: [], opening_positions: [],
    omissions: [], rules: [], assessment: 'complied', complete: true, peak_positions: 0,
    buy_amount: '0.00', sell_amount: '0.00', fee: '0.00', net_outflow: '0.00',
    cash: '100000.00', realized_pnl: '0.00', review_note: null, evaluations: [],
    ...overrides,
  }
}

export function makeLedgerContext(snapshot: LedgerSnapshot | null,
  overrides: Partial<LedgerContext> = {}): LedgerContext {
  return {
    trade_date: snapshot?.trade_date ?? '2026-08-21', account_revision: 3,
    initialized_on: '2026-08-20', can_edit: true,
    latest_trade_date: snapshot?.trade_date ?? null, current_revision_no: snapshot?.revision_no ?? 0,
    snapshot, rules: snapshot?.rules ?? [], opening_positions: [], opening_cash: '100000.00',
    positions: snapshot?.positions ?? [], cash: snapshot?.cash ?? '100000.00', ...overrides,
  }
}

/** 外壳只在已知市场交易日后加载纪律摘要，界面材料必须同时提供该前置。 */
export async function installLedgerUiCalendar(page: Page, tradeDate = '2026-08-21') {
  await page.route('**/api/data/trade-dates*', route => route.fulfill({
    contentType: 'application/json', body: JSON.stringify({ code: 0, msg: 'ok',
      data: { dates: [tradeDate], min: tradeDate, max: tradeDate, count: 1 } }),
  }))
}

export async function tradeFixtureGet<T>(
  request: APIRequestContext, accessToken: string, path: string,
  params?: Record<string, string | number | boolean>,
): Promise<T> {
  const response = await request.get(`${TRADE_DISCIPLINE_API}/trade-discipline${path}`, {
    headers: { authorization: `Bearer ${accessToken}` }, params,
  })
  expect(response.ok(), `交易纪律夹具接口失败 ${path}: ${response.status()}`).toBe(true)
  const body = await response.json()
  expect(body.code, body.msg).toBe(0)
  return body.data as T
}

export function ledgerContext(request: APIRequestContext, accessToken: string, tradeDate = TRADE_DISCIPLINE_FIXTURE.currentTradeDate) {
  return tradeFixtureGet<LedgerContext>(request, accessToken, '/ledger', { trade_date: tradeDate })
}

/** 通过当前账户接口核验正式日结，旧逐规则 checkin 不再作为页面夹具。 */
export async function requireTradeDisciplineFixture(
  request: APIRequestContext, accessToken: string,
  options: { verifyStockSearch?: boolean; initialized?: boolean } = {},
) {
  const fixed = TRADE_DISCIPLINE_FIXTURE
  const rules = await tradeFixtureGet<Array<{
    id: string; name: string; latest_version_no: number; effective_event_seq: number;
    has_pending_management_action: boolean; effective_version: { version_no: number };
  }>>(request, accessToken, '/rules', { trade_date: fixed.currentTradeDate })
  const seeded = rules.filter(r => r.id.startsWith(fixed.idPrefix) && r.name.startsWith(fixed.namePrefix))
  expect(seeded, '应存在唯一的专属规则；通过 run e2e-trade 准备夹具').toHaveLength(1)
  const rule = seeded[0]!
  expect(rule).toMatchObject({ latest_version_no: 4, effective_event_seq: 5,
    has_pending_management_action: true, effective_version: { version_no: 3 } })
  const context = await ledgerContext(request, accessToken)
  if (options.initialized === false) {
    expect(context.initialized_on).toBeNull()
    expect(context.account_revision).toBe(0)
  } else {
    expect(context.initialized_on).toBe(fixed.openingTradeDate)
    const history = await tradeFixtureGet<{ total: number; list: LedgerHistoryRow[] }>(request, accessToken, '/ledger/history', {
      date_from: fixed.ledgerDates[0], date_to: fixed.latestSeededTradeDate, sort_order: 'asc',
    })
    expect(history.total).toBe(4)
    expect(history.list.map(row => [row.snapshot.assessment, row.snapshot.operation_count === 0])).toEqual([
      ['complied', true], ['complied', false], ['breached', true], ['breached', false],
    ])
    expect(history.list.map(row => row.current_revision_no)).toEqual([1, 1, 1, 2])
  }
  if (options.verifyStockSearch) {
    const stocks = await tradeFixtureGet<{ list: { code: string }[] }>(request, accessToken, '/stock-options', { q: '9988', limit: 20 })
    expect(stocks.list.map(row => row.code)).toEqual(fixed.stockCodes)
  }
  return { ruleId: rule.id, currentTradeDate: fixed.currentTradeDate, pendingTradeDate: fixed.pendingTradeDate }
}
