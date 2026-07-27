import { expect, test } from '@playwright/test'
import { loginAsDebugUser } from './helpers/auth'
import { collectConsoleIssues } from './helpers/console'

async function openPresets(page: import('@playwright/test').Page) {
  await page.goto('/system/layout/presets')
  await expect(page.getByText('预设管理', { exact: true }).first()).toBeVisible({ timeout: 20_000 })
  await expect(page.getByTestId('preset-table')).toBeVisible()
}

async function scrollGeometry(page: import('@playwright/test').Page) {
  return page.evaluate(() => {
    const adaptive = document.querySelector<HTMLElement>('[data-testid="layout-adaptive-region"]')
    const grow = document.querySelector<HTMLElement>('[data-testid="layout-grow-region"]')
    const main = document.querySelector<HTMLElement>('[data-testid="app-main-surface"]')
    const table = document.querySelector<HTMLElement>('[data-testid="preset-table"]')
    if (!adaptive || !grow || !main || !table) throw new Error('预设页滚动契约节点不完整')
    return {
      adaptiveClientHeight: adaptive.clientHeight,
      adaptiveScrollHeight: adaptive.scrollHeight,
      growHeight: grow.getBoundingClientRect().height,
      mainScrollTop: main.scrollTop,
      tableHeight: table.getBoundingClientRect().height,
      mainBottom: main.getBoundingClientRect().bottom,
      viewportHeight: window.innerHeight,
    }
  })
}

test('主表余量达到 minH 时由表体滚动，应用外壳与主内容区不滚动', async ({ page, request }) => {
  const consoleIssues = collectConsoleIssues(page)
  await loginAsDebugUser(page, request, 'debug_system')
  await page.setViewportSize({ width: 1440, height: 900 })
  await openPresets(page)

  const geometry = await scrollGeometry(page)
  expect(geometry.growHeight).toBeGreaterThanOrEqual(360)
  expect(geometry.adaptiveScrollHeight).toBeLessThanOrEqual(geometry.adaptiveClientHeight + 1)
  expect(geometry.tableHeight).toBeGreaterThan(200)
  expect(geometry.mainScrollTop).toBe(0)
  expect(geometry.mainBottom).toBeLessThanOrEqual(geometry.viewportHeight + 1)
  expect(consoleIssues).toEqual([])
})

test('主表余量低于 minH 时只启用主内容区滚动兜底', async ({ page, request }) => {
  const consoleIssues = collectConsoleIssues(page)
  await loginAsDebugUser(page, request, 'debug_system')
  await page.setViewportSize({ width: 1100, height: 420 })
  await openPresets(page)

  const geometry = await scrollGeometry(page)
  expect(geometry.growHeight).toBeGreaterThanOrEqual(360)
  expect(geometry.adaptiveScrollHeight).toBeGreaterThan(geometry.adaptiveClientHeight + 1)
  expect(geometry.mainScrollTop).toBe(0)
  expect(geometry.mainBottom).toBeLessThanOrEqual(geometry.viewportHeight + 1)
  expect(consoleIssues).toEqual([])
})
