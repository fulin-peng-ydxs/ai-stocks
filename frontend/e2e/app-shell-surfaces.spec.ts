import { expect, test } from '@playwright/test'
import { loginAsDebugUser } from './helpers/auth'
import { collectConsoleIssues } from './helpers/console'

test('工作台边栏与主区使用原型固定底色且不受视觉预设影响', async ({ page, request }) => {
  const consoleIssues = collectConsoleIssues(page)
  await page.addInitScript(() => {
    window.localStorage.setItem('ai-stocks-theme', 'light')
    // 模拟用户在登录页明确选择白天：登录后必须写回账号，不能被旧远端夜间偏好覆盖。
    window.localStorage.setItem('ai-stocks-theme-pending-sync', '1')
    window.localStorage.setItem('ai-stocks:layout-preset', 'balanced')
  })
  await loginAsDebugUser(page, request, 'debug_normal')
  await page.goto('/board')

  const aside = page.getByTestId('app-sidebar-surface')
  const workspace = page.getByTestId('app-workspace-surface')
  const topbar = page.getByTestId('app-topbar-surface')
  const brandMark = page.getByRole('img', { name: '复盘啦' })
  await expect(brandMark).toHaveCSS('width', '184px')
  await expect(brandMark).toHaveCSS('height', '52px')
  await expect(aside).toHaveCSS('background-color', 'rgb(252, 252, 252)')
  await expect(workspace).toHaveCSS('background-color', 'rgb(255, 255, 255)')
  await expect(topbar).toHaveCSS('background-color', 'rgb(252, 252, 252)')

  await page.getByRole('button', { name: '视觉环境' }).click()
  await page.getByRole('button', { name: '夜间' }).click()
  await expect(page.locator('html')).toHaveClass(/dark/)
  await expect(aside).toHaveCSS('background-color', 'rgb(31, 31, 31)')
  await expect(workspace).toHaveCSS('background-color', 'rgb(23, 23, 23)')
  await expect(topbar).toHaveCSS('background-color', 'rgb(31, 31, 31)')

  expect(consoleIssues).toEqual([])
})
