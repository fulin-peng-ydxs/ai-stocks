import { expect, type APIRequestContext } from '@playwright/test'

import type { StockBasic } from '../../src/api/stocks'
import { DEFAULT_E2E_API_URL } from './e2e-backend-health.mjs'

const API_URL = process.env.E2E_API_URL || DEFAULT_E2E_API_URL

export interface SeededCorrelationStocks {
  targetDate: string
  stocks: StockBasic[]
}

/**
 * 从真实个股接口读取受控关联板块夹具并 fail-fast，页面断言不依赖开发库中的偶然行情。
 */
export async function requireSeededCorrelationStocks(
  request: APIRequestContext,
  accessToken: string,
): Promise<SeededCorrelationStocks> {
  const response = await request.get(`${API_URL}/stocks`, {
    headers: { authorization: `Bearer ${accessToken}` },
    params: { q: 'E2E相关-股票', page: 1, size: 20 },
  })
  expect(response.ok(), '关联板块 E2E 夹具查询失败').toBe(true)
  const body = await response.json()
  expect(body.code, body.msg || '关联板块 E2E 夹具接口返回非 0 code').toBe(0)
  const stocks = body.data.list as StockBasic[]
  expect(
    stocks.length,
    '缺少关联板块 E2E 确定性数据；请使用 npm run test:e2e:stock-board-correlation',
  ).toBe(4)
  expect(stocks.every((row) => row.code.startsWith('9977'))).toBe(true)
  expect(stocks.every((row) => row.related_boards?.industry?.name === 'E2E相关-行业冠军'))
    .toBe(true)
  expect(stocks.every((row) => row.related_boards?.concept?.name === 'E2E相关-概念冠军'))
    .toBe(true)
  return { targetDate: body.data.trade_date as string, stocks }
}
