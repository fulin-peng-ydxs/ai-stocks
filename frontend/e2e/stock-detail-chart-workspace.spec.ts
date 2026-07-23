import { expect, test } from '@playwright/test'
import { loginAsDebugUser } from './helpers/auth'

const API_URL = process.env.E2E_API_URL || 'http://127.0.0.1:8000/api'

test.describe('个股详情三图工作区', () => {
  test('MACD 局部失败不阻断行情，重试与范围刷新使用独立指标请求', async ({ page, request }) => {
    const consoleIssues: string[] = []
    page.on('console', (message) => {
      const text = message.text()
      const expectedInjectedFailure = text.includes('status of 503')
      if (['error', 'warning'].includes(message.type()) && !expectedInjectedFailure) {
        consoleIssues.push(text)
      }
    })

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

    const stocksResponse = await request.get(`${API_URL}/stocks?page=1&size=1`, { headers })
    expect(stocksResponse.ok()).toBe(true)
    const stocksBody = await stocksResponse.json()
    expect(stocksBody.code, stocksBody.msg || '读取验收股票失败').toBe(0)
    const code = stocksBody.data.list[0]?.code as string | undefined
    expect(code, '本地行情库没有可用于个股详情验收的股票').toBeTruthy()

    let failNextIndicatorRequest = true
    let indicatorRequests = 0
    let unauthorizedSecondaryRequests = 0
    page.on('request', (pageRequest) => {
      const url = pageRequest.url()
      if (url.includes('/api/stock-groups') || url.includes('/api/trade-profiles')) {
        unauthorizedSecondaryRequests += 1
      }
    })
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

    await page.goto(`/stocks/${code}`)

    await expect(page.getByText('K线（日线·前复权）', { exact: true })).toBeVisible()
    await expect(page.getByText('量能', { exact: true })).toBeVisible()
    await expect(page.getByText('MACD（12,26,9·前复权）', { exact: true })).toBeVisible()
    const workspace = page.getByLabel('个股多图联动工作区')
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
    expect(unauthorizedSecondaryRequests).toBe(0)
    expect(consoleIssues).toEqual([])
  })
})
