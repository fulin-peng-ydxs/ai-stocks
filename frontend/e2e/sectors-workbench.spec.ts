import { expect, test } from '@playwright/test'

import { loginAsDebugUser } from './helpers/auth'
import { collectConsoleIssues } from './helpers/console'
import { DEFAULT_E2E_API_URL } from './helpers/e2e-backend-health.mjs'
import { openPageAndWaitForHeading } from './helpers/navigation'

const API_URL = process.env.E2E_API_URL || DEFAULT_E2E_API_URL

test.describe('板块行情工作台', () => {
  test('首屏加载排行与走势，并支持行选中、对比和 K 线联动', async ({ page, request }) => {
    const consoleIssues = collectConsoleIssues(page)
    const auth = await loginAsDebugUser(page, request, 'debug_system')
    const response = await request.get(`${API_URL}/sectors`, {
      headers: { authorization: `Bearer ${auth.accessToken}` },
      params: { page: 1, size: 4, sort_by: 'pct_today', order: 'desc' },
    })
    expect(response.ok()).toBe(true)
    const body = await response.json()
    expect(body.code, body.msg || '板块列表接口返回非 0 code').toBe(0)
    const boards = body.data.list as Array<{ board_code: string; name: string }>
    expect(boards.length).toBeGreaterThanOrEqual(4)

    await openPageAndWaitForHeading(page, '/sectors', '板块行情')
    await expect(page.getByTestId('sectors-workspace')).toBeVisible({ timeout: 20_000 })
    await expect(page.getByTestId('sectors-chart-title')).toHaveText(boards[0]!.name)

    await page.getByTestId(`sectors-row-${boards[3]!.board_code}`).click()
    await expect(page.getByTestId('sectors-chart-title')).toHaveText(boards[3]!.name)

    await page.getByTestId(`sectors-pin-${boards[0]!.board_code}`).click()
    await expect(page.getByTestId(`sectors-compare-${boards[0]!.board_code}`)).toBeVisible()
    await page.getByTestId(`sectors-remove-${boards[0]!.board_code}`).click()
    await expect(page.getByTestId(`sectors-compare-${boards[0]!.board_code}`)).toHaveCount(0)

    await page.getByTestId('sectors-chart-mode-kline').click()
    await expect(page.getByTestId('sectors-chart-mode-kline')).toHaveAttribute('aria-pressed', 'true')
    await expect(page.getByTestId('sectors-chart')).toBeVisible()
    expect(consoleIssues).toEqual([])
  })
})
