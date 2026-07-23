import { expect, test } from '@playwright/test'
import { loginAsDebugUser } from './helpers/auth'

const API_URL = process.env.E2E_API_URL || 'http://127.0.0.1:8000/api'

test.describe('个股详情三图工作区', () => {
  test('MACD 局部失败隔离，图表组合和高度偏好可自动保存与重置', async ({ page, request }) => {
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

    type PreferencePayload = {
      scope: string
      pageKey?: string
      prefKey: string
      value: unknown
      schemaVersion?: number
    }
    const preferenceKey = (item: Pick<PreferencePayload, 'scope' | 'pageKey' | 'prefKey'>) => (
      `${item.scope}|${item.pageKey || ''}|${item.prefKey}`
    )
    const preferenceStore = new Map<string, PreferencePayload>()
    const stocksPreferenceKey = preferenceKey({
      scope: 'page',
      pageKey: 'stocks',
      prefKey: 'settings',
    })
    const stockDetailPreferenceKey = preferenceKey({
      scope: 'page',
      pageKey: 'stock-detail',
      prefKey: 'settings',
    })
    preferenceStore.set(stocksPreferenceKey, {
      scope: 'page',
      pageKey: 'stocks',
      prefKey: 'settings',
      value: { defaultView: 'group', excludeSt: true },
      schemaVersion: 1,
    })
    let stocksPreferenceWrites = 0
    // 最小权限账号不能用真实 PG helper 写偏好；用例内存端点同时隔离共享账号历史状态和写入。
    await page.route('**/api/user-preferences*', async (route) => {
      const request = route.request()
      const url = new URL(request.url())
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
        preferenceStore.set(key, normalized)
        if (key === stocksPreferenceKey) stocksPreferenceWrites += 1
        return normalized
      }

      if (request.method() === 'GET') {
        const scope = url.searchParams.get('scope')
        const pageKey = url.searchParams.get('pageKey')
        const prefKey = url.searchParams.get('prefKey')
        const items = [...preferenceStore.values()].filter((item) => (
          (scope === null || item.scope === scope)
          && (pageKey === null || (item.pageKey || '') === pageKey)
          && (prefKey === null || item.prefKey === prefKey)
        ))
        await respond({ items })
        return
      }

      const body = request.postDataJSON() as PreferencePayload | {
        items: PreferencePayload[]
      }
      if (url.pathname.endsWith('/bulk')) {
        const items = body && 'items' in body ? body.items.map(save) : []
        await respond({ items }, '用户偏好已批量保存')
        return
      }
      await respond(save(body as PreferencePayload), '用户偏好已保存')
    })

    const stocksResponse = await request.get(`${API_URL}/stocks?page=1&size=1`, { headers })
    expect(stocksResponse.ok()).toBe(true)
    const stocksBody = await stocksResponse.json()
    expect(stocksBody.code, stocksBody.msg || '读取验收股票失败').toBe(0)
    const code = stocksBody.data.list[0]?.code as string | undefined
    expect(code, '本地行情库没有可用于个股详情验收的股票').toBeTruthy()
    expect(stocksBody.data.list[0]?.groups).toEqual([])

    let failNextIndicatorRequest = true
    let indicatorRequests = 0
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
      (preferenceStore.get(stocksPreferenceKey)?.value as { defaultView?: string }).defaultView
    )).toBe('group')
    const writesBeforeListClick = stocksPreferenceWrites
    await settingsDrawer.getByTestId('stocks-default-view-list').click()
    // 远端自动保存有 300ms 防抖；跨过窗口后确认这次无效点击没有触发新写入。
    await page.waitForTimeout(400)
    await expect.poll(() => page.evaluate(() => (
      JSON.parse(window.localStorage.getItem('ai-stocks:page-settings:stocks') || '{}').defaultView
    ))).toBe('group')
    expect(
      (preferenceStore.get(stocksPreferenceKey)?.value as { defaultView?: string }).defaultView,
    ).toBe('group')
    expect(stocksPreferenceWrites).toBe(writesBeforeListClick)
    await settingsDrawer.getByRole('button', { name: '关闭页面设置' }).click()

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

    const indicatorRequestsBeforeSettings = indicatorRequests
    await page.getByTestId('page-settings-trigger').click()
    const detailSettingsDrawer = page.getByTestId('page-settings-drawer')
    await expect(detailSettingsDrawer).toBeVisible()
    await expect(detailSettingsDrawer.getByTestId('stock-detail-chart-slot1-kline')).toContainText(
      '固定，不可隐藏',
    )

    // 目标类型已被另一槽使用时自动交换，不产生新的行情或指标请求。
    await detailSettingsDrawer.getByTestId('stock-detail-chart-slot2-macd').click()
    await expect(workspace.locator('[data-panel-key="slot2"]')).toContainText('MACD')
    await expect(workspace.locator('[data-panel-key="slot3"]')).toContainText('量能')

    await detailSettingsDrawer.getByTestId('stock-detail-chart-slot3-hidden').click()
    await expect(page.locator('[data-panel-key]')).toHaveCount(2)
    await expect(workspace.getByRole('separator')).toHaveCount(1)
    await expect.poll(() => {
      const value = preferenceStore.get(stockDetailPreferenceKey)?.value as {
        charts?: { slot2?: string; slot3?: string }
      } | undefined
      return [value?.charts?.slot2, value?.charts?.slot3]
    }).toEqual(['macd', 'hidden'])
    expect(indicatorRequests).toBe(indicatorRequestsBeforeSettings)

    await detailSettingsDrawer.getByRole('button', { name: '关闭页面设置' }).click()
    await expect(page.locator('[data-panel-key]')).toHaveCount(2)

    // 重新加载后由隔离远端偏好恢复组合，不依赖共享调试账号 PG 历史值。
    await page.reload()
    await expect(page.locator('[data-panel-key]')).toHaveCount(2)
    await expect(workspace.locator('[data-panel-key="slot2"]')).toContainText('MACD')
    await expect(workspace.locator('[data-panel-key="slot3"]')).toHaveCount(0)
    const indicatorRequestsAfterReload = indicatorRequests

    const firstSeparator = workspace.getByRole('separator').first()
    const ratioBeforeKeyboard = await firstSeparator.getAttribute('aria-valuenow')
    await firstSeparator.press('ArrowDown')
    await expect(firstSeparator).not.toHaveAttribute('aria-valuenow', ratioBeforeKeyboard || '')
    await expect.poll(() => {
      const value = preferenceStore.get(stockDetailPreferenceKey)?.value as {
        charts?: { heightRatios?: Record<string, number[]> }
      } | undefined
      return value?.charts?.heightRatios?.['kline|macd']
    }).not.toEqual([0.75, 0.25])

    await page.getByTestId('page-settings-trigger').click()
    const resetDrawer = page.getByTestId('page-settings-drawer')
    await resetDrawer.getByTestId('page-settings-reset').click()
    await expect(page.locator('[data-panel-key]')).toHaveCount(3)
    await expect(resetDrawer.getByTestId('stock-detail-chart-slot2-volume')).toHaveClass(/active/)
    await expect(resetDrawer.getByTestId('stock-detail-chart-slot3-macd')).toHaveClass(/active/)
    await expect(workspace.getByRole('separator').first()).toHaveAttribute('aria-valuenow', '60')
    await expect.poll(() => {
      const value = preferenceStore.get(stockDetailPreferenceKey)?.value as {
        charts?: {
          slot2?: string
          slot3?: string
          heightRatios?: Record<string, number[]>
        }
      } | undefined
      return {
        slot2: value?.charts?.slot2,
        slot3: value?.charts?.slot3,
        ratios: value?.charts?.heightRatios?.['kline|volume|macd'],
      }
    }).toEqual({ slot2: 'volume', slot3: 'macd', ratios: [0.6, 0.2, 0.2] })
    expect(indicatorRequests).toBe(indicatorRequestsAfterReload)

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
})
