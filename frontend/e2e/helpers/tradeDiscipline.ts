import { expect, type APIRequestContext } from '@playwright/test'

import { DEFAULT_E2E_API_URL } from './e2e-backend-health.mjs'

const API_URL = process.env.E2E_API_URL || DEFAULT_E2E_API_URL

export const TRADE_DISCIPLINE_FIXTURE = {
  idPrefix: 'e2e_td_',
  namePrefix: 'E2E纪律-',
  currentTradeDate: '2098-06-10',
  pendingTradeDate: '2098-06-11',
  operationTradeDate: '2098-06-05',
  stockCodes: ['998801.SZ', '998802.SZ', '998803.SZ'],
} as const

export interface SeededTradeDisciplineFixture {
  ruleId: string
  currentTradeDate: string
  pendingTradeDate: string
  checkinIds: string[]
}

interface ApiEnvelope<T> {
  code: number
  msg?: string
  data: T
}

async function fixtureGet<T>(
  request: APIRequestContext,
  accessToken: string,
  path: string,
  params?: Record<string, string | number>,
): Promise<T> {
  const response = await request.get(`${API_URL}${path}`, {
    headers: { authorization: `Bearer ${accessToken}` },
    params,
  })
  if (!response.ok()) {
    throw new Error(`交易纪律 E2E 夹具查询失败：${path} (${response.status()}) ${await response.text()}`)
  }
  const body = await response.json() as ApiEnvelope<T>
  expect(body.code, body.msg || `交易纪律 E2E 夹具接口返回非 0 code：${path}`).toBe(0)
  return body.data
}

/**
 * 从真实接口核验专属规则、四组合打卡和待生效版本，避免 T13 静默使用开发者真实数据。
 */
export async function requireTradeDisciplineFixture(
  request: APIRequestContext,
  accessToken: string,
  options: { verifyStockSearch?: boolean } = {},
): Promise<SeededTradeDisciplineFixture> {
  const rules = await fixtureGet<Array<Record<string, unknown>>>(
    request,
    accessToken,
    '/trade-discipline/rules',
    { trade_date: TRADE_DISCIPLINE_FIXTURE.currentTradeDate },
  )
  const seededRules = rules.filter((row) => (
    typeof row.id === 'string'
    && row.id.startsWith(TRADE_DISCIPLINE_FIXTURE.idPrefix)
    && typeof row.name === 'string'
    && row.name.startsWith(TRADE_DISCIPLINE_FIXTURE.namePrefix)
  ))
  expect(
    seededRules.length,
    '缺少唯一的交易纪律确定性规则；请使用 npm run test:e2e:trade-discipline',
  ).toBe(1)
  const rule = seededRules[0]
  expect(rule.latest_version_no).toBe(4)
  expect(rule.effective_event_seq).toBe(5)
  expect(rule.has_pending_management_action).toBe(true)
  expect((rule.effective_version as Record<string, unknown>)?.version_no).toBe(3)

  const history = await fixtureGet<{
    total: number
    list: Array<Record<string, unknown>>
  }>(request, accessToken, '/trade-discipline/checkins', {
    date_from: '2098-06-04',
    date_to: TRADE_DISCIPLINE_FIXTURE.currentTradeDate,
    rule_id: String(rule.id),
    page: 1,
    page_size: 20,
  })
  const seededHistory = history.list.filter((row) => (
    typeof row.id === 'string' && row.id.startsWith(TRADE_DISCIPLINE_FIXTURE.idPrefix)
  ))
  expect(seededHistory.length, '交易纪律夹具应包含四条专属历史').toBe(4)
  const combinations = new Set(seededHistory.map((row) => `${row.assessment}:${row.no_operation}`))
  expect(combinations).toEqual(new Set([
    'complied:true',
    'complied:false',
    'breached:true',
    'breached:false',
  ]))

  if (options.verifyStockSearch) {
    const stocks = await fixtureGet<{ list: Array<{ code: string }> }>(
      request,
      accessToken,
      '/trade-discipline/stock-options',
      { q: '9988', limit: 20 },
    )
    expect(stocks.list.map((row) => row.code)).toEqual(TRADE_DISCIPLINE_FIXTURE.stockCodes)
  }

  return {
    ruleId: String(rule.id),
    currentTradeDate: TRADE_DISCIPLINE_FIXTURE.currentTradeDate,
    pendingTradeDate: TRADE_DISCIPLINE_FIXTURE.pendingTradeDate,
    checkinIds: seededHistory.map((row) => String(row.id)),
  }
}
