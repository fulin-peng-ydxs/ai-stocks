import { expect, type APIRequestContext } from '@playwright/test'

import { DEFAULT_E2E_API_URL } from './e2e-backend-health.mjs'

const API_URL = process.env.E2E_API_URL || DEFAULT_E2E_API_URL

export interface SeededSector {
  board_code: string
  name: string
}

/**
 * 读取受控 DuckDB 夹具并 fail-fast，避免板块工作台 E2E 悄悄依赖开发者本地真实行情。
 */
export async function requireSeededSectors(
  request: APIRequestContext,
  accessToken: string,
): Promise<SeededSector[]> {
  const response = await request.get(`${API_URL}/sectors`, {
    headers: { authorization: `Bearer ${accessToken}` },
    params: {
      keyword: 'E2E板块',
      page: 1,
      size: 50,
      sort_by: 'pct_today',
      order: 'desc',
    },
  })
  expect(response.ok(), '板块 E2E 夹具查询失败').toBe(true)
  const body = await response.json()
  expect(body.code, body.msg || '板块 E2E 夹具接口返回非 0 code').toBe(0)
  const boards = body.data.list as SeededSector[]
  expect(
    boards.length,
    '缺少板块 E2E 确定性数据；请使用 npm run test:e2e:sectors 或先执行 e2e-board-data seed',
  ).toBe(24)
  expect(boards.every((row) => row.board_code.startsWith('E2E9'))).toBe(true)
  return boards
}
