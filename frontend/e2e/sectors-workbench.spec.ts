import { expect, test } from '@playwright/test'

import { loginAsDebugUser } from './helpers/auth'
import { collectConsoleIssues } from './helpers/console'
import { DEFAULT_E2E_API_URL } from './helpers/e2e-backend-health.mjs'
import { openPageAndWaitForHeading } from './helpers/navigation'

const API_URL = process.env.E2E_API_URL || DEFAULT_E2E_API_URL

test.describe('板块行情工作台', () => {
  test('首屏加载排行与走势，并支持自选、行选中、对比和 K 线联动', async ({ page, request }, testInfo) => {
    test.setTimeout(90_000)
    const consoleIssues = collectConsoleIssues(page)
    const sectorApi404s: string[] = []
    page.on('response', (response) => {
      if (response.status() === 404 && response.url().includes('/api/sectors/')) {
        sectorApi404s.push(response.url())
      }
    })
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
    const projectIndex = ['chromium-compact', 'chromium-standard', 'chromium-default']
      .indexOf(testInfo.project.name)
    const watchlistBoard = boards[Math.max(projectIndex, 0)]!
    await request.delete(`${API_URL}/sectors/watchlist/${watchlistBoard.board_code}`, {
      headers: { authorization: `Bearer ${auth.accessToken}` },
    })

    try {
      await openPageAndWaitForHeading(page, '/sectors', '板块行情')
      await expect(page.getByTestId('sectors-workspace')).toBeVisible({ timeout: 20_000 })
      await expect(page.getByTestId('sectors-chart-title')).toHaveText(boards[0]!.name)
      const compareChart = page.getByTestId('sectors-compare-chart')
      await expect(compareChart).toBeVisible()
      await expect(page.getByTestId('sectors-compare-rail').getByRole('button')).toHaveCount(1)
      await expect(compareChart).toHaveAttribute('data-benchmark-code', '000905.SH')
      await expect.poll(async () => Number(
        await compareChart.getAttribute('data-benchmark-point-count'),
      )).toBeGreaterThan(0)
      await page.getByTestId('sectors-benchmark').click()
      await page.getByRole('option', { name: '不对比指数' }).click()
      await expect(compareChart).toHaveAttribute('data-benchmark-code', '')
      await page.getByTestId('sectors-benchmark').click()
      await page.getByRole('option', { name: '中证 500' }).click()
      await expect(compareChart).toHaveAttribute('data-benchmark-code', '000905.SH')
      const pointCount = async () => Number(await compareChart.getAttribute('data-point-count'))
      await expect.poll(pointCount).toBeGreaterThan(0)
      const defaultPointCount = await pointCount()
      expect(defaultPointCount).toBeLessThanOrEqual(120)
      await page.getByTestId('sectors-range').click()
      await page.getByRole('option', { name: '全部' }).click()
      await expect.poll(pointCount).toBeGreaterThan(defaultPointCount)
      await page.getByTestId('sectors-range').click()
      await page.getByRole('option', { name: '近 60 日' }).click()
      await expect.poll(pointCount).toBeLessThanOrEqual(60)
      expect(await pointCount()).toBeGreaterThan(0)
      await page.getByTestId('sectors-range').click()
      await page.getByRole('option', { name: '近 120 日' }).click()
      await expect.poll(pointCount).toBe(defaultPointCount)
      await expect(page.getByText('区间首日统一记为 0%；虚线为中证 500', { exact: false }))
        .toBeVisible()

      const watchlistButton = page.getByTestId(`sectors-watchlist-${watchlistBoard.board_code}`)
      await watchlistButton.click()
      await expect(watchlistButton).toHaveAccessibleName(
        `移出板块自选：${watchlistBoard.name}`,
        { timeout: 15_000 },
      )
      await page.getByTestId('sectors-list-scope-watchlist').click()
      await expect(page.getByTestId(`sectors-row-${watchlistBoard.board_code}`)).toBeVisible()
      await watchlistButton.click()
      await expect(page.getByTestId(`sectors-row-${watchlistBoard.board_code}`)).toHaveCount(0)

      await page.getByTestId('sectors-list-scope-all').click()
      await page.getByTestId(`sectors-row-${boards[3]!.board_code}`).click()
      await expect(page.getByTestId('sectors-chart-title')).toHaveText(boards[3]!.name)

      await page.getByTestId(`sectors-pin-${boards[0]!.board_code}`).click()
      await expect(page.getByTestId(`sectors-compare-${boards[0]!.board_code}`)).toBeVisible()
      await page.getByTestId(`sectors-remove-${boards[0]!.board_code}`).click()
      await expect(page.getByTestId(`sectors-compare-${boards[0]!.board_code}`)).toHaveCount(0)

      await page.getByTestId('sectors-chart-mode-kline').click()
      await expect(page.getByTestId('sectors-chart-mode-kline')).toHaveAttribute('aria-pressed', 'true')
      await expect(page.getByTestId('sectors-chart')).toBeVisible()

      await page.getByTestId('page-settings-trigger').click()
      const listDrawer = page.getByTestId('page-settings-drawer')
      await expect(listDrawer).toBeVisible()
      const listDefaultMode = listDrawer.getByTestId('sectors-default-chart-mode')
      if (!await listDefaultMode.isVisible()) {
        await listDrawer.getByRole('button', { name: '业务选项', exact: true }).click()
      }
      await expect(listDrawer.getByTestId('sectors-default-scope')).toBeVisible()
      await expect(listDefaultMode).toBeVisible()
      await expect(listDrawer.getByTestId('kline-setting-section')).toBeVisible()
      await listDrawer.getByRole('button', { name: '关闭页面设置' }).click()

      await page.getByTestId('sectors-open-detail').click()
      await expect(page).toHaveURL(new RegExp(`/sectors/${boards[3]!.board_code}`))
      await expect(page.getByTestId('sector-detail-page')).toBeVisible({ timeout: 20_000 })
      await expect(page.getByRole('heading', { name: boards[3]!.name })).toBeVisible({
        timeout: 20_000,
      })
      await expect(page.getByTestId('sector-detail-range')).toContainText('近 120 日')
      const chartSection = page.getByTestId('sector-detail-chart-section')
      const memberSection = page.getByTestId('sector-detail-member-section')
      await expect(chartSection).toBeVisible()
      await expect(memberSection).toBeVisible()
      const configuredChartHeight = Number(await chartSection.getAttribute('data-configured-height'))
      expect(configuredChartHeight).toBeGreaterThanOrEqual(480)
      expect(configuredChartHeight).toBeLessThanOrEqual(900)
      expect(Math.abs(((await chartSection.boundingBox())?.height ?? 0) - configuredChartHeight))
        .toBeLessThanOrEqual(1)
      expect((await memberSection.boundingBox())?.height).toBeGreaterThanOrEqual(420)
      const volumePanel = chartSection.locator('[data-panel-key="slot2"]')
      await expect(volumePanel).toBeVisible()
      const chartBounds = await chartSection.boundingBox()
      const volumeBounds = await volumePanel.boundingBox()
      expect(volumeBounds?.height).toBeGreaterThan(120)
      expect((volumeBounds?.y ?? 0) + (volumeBounds?.height ?? 0))
        .toBeLessThanOrEqual((chartBounds?.y ?? 0) + (chartBounds?.height ?? 0))

      await page.getByTestId('page-settings-trigger').click()
      const detailDrawer = page.getByTestId('page-settings-drawer')
      await expect(detailDrawer).toBeVisible()
      const chartHeightControl = detailDrawer.getByTestId('component-chart-minHeight')
      if (!await chartHeightControl.isVisible()) {
        await detailDrawer.getByRole('button', { name: '组件设置', exact: true }).click()
      }
      await expect(chartHeightControl).toBeVisible()
      const detailKlineSettings = detailDrawer.getByTestId('kline-setting-section')
      if (!await detailKlineSettings.isVisible()) {
        await detailDrawer.getByRole('button', { name: '业务选项', exact: true }).click()
      }
      await expect(detailKlineSettings).toBeVisible()
      await detailDrawer.getByRole('button', { name: '关闭页面设置' }).click()

      await page.locator('.menu').getByRole('menuitem', { name: '每日榜单', exact: true }).click()
      await expect(page).toHaveURL(/\/board$/)
      await page.locator('.menu').getByRole('menuitem', { name: '板块行情', exact: true }).click()
      await expect(page).toHaveURL(new RegExp(`/sectors/${boards[3]!.board_code}`))
      await expect(page.getByTestId('sector-detail-page')).toBeVisible()

      const chartSplitter = page.getByRole('separator', {
        name: '调整K线（日线·板块指数）与下一幅图高度',
      })
      await expect(chartSplitter).toBeVisible()
      const ratioBefore = Number(await chartSplitter.getAttribute('aria-valuenow'))
      const ratioMin = Number(await chartSplitter.getAttribute('aria-valuemin'))
      const ratioMax = Number(await chartSplitter.getAttribute('aria-valuemax'))
      const growKline = ratioBefore < ratioMax
      await chartSplitter.focus()
      await chartSplitter.press(growKline ? 'ArrowDown' : 'ArrowUp')
      const expectedRatio = growKline
        ? Math.min(ratioMax, ratioBefore + 2)
        : Math.max(ratioMin, ratioBefore - 2)
      await expect(chartSplitter).toHaveAttribute('aria-valuenow', String(expectedRatio))

      const firstMember = page.locator('[data-testid^="sector-member-"]').first()
      await firstMember.scrollIntoViewIfNeeded()
      await expect(firstMember).toBeVisible()
      const memberCode = (await firstMember.textContent())?.trim()
      expect(memberCode).toBeTruthy()
      await firstMember.click()
      await expect(page).toHaveURL(new RegExp(`/stocks/${memberCode}`))
      await page.getByRole('button', { name: '返回', exact: true }).click()
      await expect(page).toHaveURL(new RegExp(`/sectors/${boards[3]!.board_code}`))
      await expect(page.getByTestId('sector-detail-page')).toBeVisible()

      await page.getByTestId('sector-detail-back').click()
      await expect(page).toHaveURL(/\/sectors(?:\?|$)/)
      await expect(page.getByTestId('sectors-workspace')).toBeVisible()
      await page.waitForTimeout(300)
      expect(sectorApi404s).toEqual([])
      expect(consoleIssues).toEqual([])
    } finally {
      await request.delete(`${API_URL}/sectors/watchlist/${watchlistBoard.board_code}`, {
        headers: { authorization: `Bearer ${auth.accessToken}` },
      })
    }
  })

  test('板块最小权限可用，自选写按钮受控且成分股跳转 fail-closed', async ({
    page,
    request,
  }, testInfo) => {
    test.skip(testInfo.project.name !== 'chromium-standard', '权限矩阵仅在标准视口执行')
    const consoleIssues = collectConsoleIssues(page)
    const auth = await loginAsDebugUser(page, request, 'debug_sectors_only')
    const meResponse = await request.get(`${API_URL}/auth/me`, {
      headers: { authorization: `Bearer ${auth.accessToken}` },
    })
    expect(meResponse.ok()).toBe(true)
    const me = (await meResponse.json()).data as {
      permissions: string[]
    }
    expect(me.permissions).toEqual(expect.arrayContaining([
      'sectors:view',
      'sector-watchlist:view',
      'sector-watchlist:update',
    ]))
    expect(me.permissions).not.toContain('stocks:view')

    const sectorResponse = await request.get(`${API_URL}/sectors`, {
      headers: { authorization: `Bearer ${auth.accessToken}` },
      params: { page: 1, size: 1, sort_by: 'pct_today', order: 'desc' },
    })
    expect(sectorResponse.ok()).toBe(true)
    const sample = (await sectorResponse.json()).data.list[0] as {
      board_code: string
      name: string
    }

    await openPageAndWaitForHeading(page, '/sectors', '板块行情')
    await expect(page.getByTestId('sectors-workspace')).toBeVisible({ timeout: 20_000 })
    const nextPage = page.getByRole('button', { name: '下一页' })
    await expect(nextPage).toBeEnabled()
    await nextPage.click()
    await expect(page).toHaveURL(/[?&]page=2(?:&|$)/)

    await page.getByRole('columnheader', { name: /5日/ }).click()
    await expect(page).toHaveURL(/[?&]sort=pct_5d(?:&|$)/)
    await page.getByTestId('sectors-keyword').fill(sample.name)
    await page.getByTestId('sectors-keyword').press('Enter')
    await expect(page.getByTestId(`sectors-row-${sample.board_code}`)).toBeVisible()
    await expect(page).toHaveURL(new RegExp(`keyword=${encodeURIComponent(sample.name)}`))
    await page.getByTestId('sectors-keyword').fill('')
    await page.getByTestId('sectors-keyword').press('Enter')

    await page.getByTestId('page-settings-trigger').click()
    const settingsDrawer = page.getByTestId('page-settings-drawer')
    const netInflowVisibility = settingsDrawer.getByTestId(
      'component-table-hiddenColumns-net_inflow',
    )
    if (!await netInflowVisibility.isVisible()) {
      await settingsDrawer.getByRole('button', { name: '组件设置', exact: true }).click()
    }
    await settingsDrawer.getByTestId('component-table-hiddenColumns-net_inflow-switch').click()
    await settingsDrawer.getByRole('button', { name: '关闭页面设置' }).click()
    await expect(page.getByRole('columnheader', { name: /净流入/ })).toHaveCount(0)
    await page.getByTestId('page-settings-trigger').click()
    await settingsDrawer.getByTestId('page-settings-reset').click()
    await settingsDrawer.getByRole('button', { name: '关闭页面设置' }).click()
    await expect(page.getByRole('columnheader', { name: /净流入/ })).toBeVisible()

    const firstSectorRow = page.locator('[data-testid^="sectors-row-"]').first()
    await expect(firstSectorRow).toBeVisible({ timeout: 20_000 })
    await expect(firstSectorRow.getByRole('button', { name: /板块自选/ })).toBeVisible()
    await firstSectorRow.click()
    await page.getByTestId('sectors-open-detail').click()
    await expect(page).toHaveURL(/\/sectors\/[^/?]+/)
    await expect(page.getByText('当前账号无个股行情查看权限', { exact: true })).toBeVisible()

    const firstMember = page.locator('[data-testid^="sector-member-"]').first()
    await firstMember.scrollIntoViewIfNeeded()
    await expect(firstMember).toHaveClass(/stock-disabled/)
    const detailUrl = page.url()
    await firstMember.click()
    await expect(page).toHaveURL(detailUrl)

    await page.goto('/stocks/600000.SH')
    await expect(page).toHaveURL(/\/sectors(?:\/[^/?]+)?(?:\?|$)/)
    expect(consoleIssues).toEqual([])
  })
})
