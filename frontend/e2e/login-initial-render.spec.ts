import { expect, test } from '@playwright/test'
import { collectConsoleIssues } from './helpers/console'
import { THEME_SURFACE_SPECS, rgbChannelsFromHex } from '../src/layout/themeSurfaces'

function expectedLoginSurfaces(mode: 'light' | 'dark') {
  const spec = THEME_SURFACE_SPECS[mode]
  const cssRgb = (hex: string) => `rgb(${rgbChannelsFromHex(hex)})`
  return {
    brand: cssRgb(spec.sidebarBg),
    auth: cssRgb(spec.pageBg),
    card: cssRgb(spec.surfaceBg),
  }
}

declare global {
  interface Window {
    __loginInitialRenderTrace?: {
      shellMounted: boolean
      loginMounted: boolean
    }
  }
}

test('刷新登录页时首帧不挂载工作台壳', async ({ page }) => {
  const consoleIssues = collectConsoleIssues(page)
  await page.addInitScript(() => {
    window.localStorage.setItem('ai-stocks-theme', 'light')
    const trace = { shellMounted: false, loginMounted: false }
    window.__loginInitialRenderTrace = trace
    const inspect = (node: Node) => {
      if (!(node instanceof Element)) return
      if (
        node.matches('[role="region"][aria-label="研究工作台"]')
        || node.querySelector('[role="region"][aria-label="研究工作台"]')
      ) trace.shellMounted = true
      if (
        node.matches('[role="region"][aria-label="登录页"]')
        || node.querySelector('[role="region"][aria-label="登录页"]')
      ) trace.loginMounted = true
    }
    new MutationObserver((records) => {
      records.forEach((record) => record.addedNodes.forEach(inspect))
    }).observe(document, { childList: true, subtree: true })
  })

  await page.goto('/login')
  await expect(page.getByRole('region', { name: '登录页' })).toBeVisible()
  const brandMark = page.getByRole('img', { name: '复盘啦' })
  await expect(brandMark).toHaveCSS('width', '184px')
  await expect(brandMark).toHaveCSS('height', '52px')
  await page.reload()
  await expect(page.getByRole('region', { name: '登录页' })).toBeVisible()

  await expect.poll(() => page.evaluate(() => window.__loginInitialRenderTrace)).toEqual({
    shellMounted: false,
    loginMounted: true,
  })

  const readLoginSurfaces = () => page.evaluate(() => {
    const read = (testId: string) => {
      const element = document.querySelector<HTMLElement>(`[data-testid="${testId}"]`)
      return element ? getComputedStyle(element).backgroundColor : ''
    }
    return {
      brand: read('login-brand-surface'),
      auth: read('login-auth-surface'),
      card: read('login-card-surface'),
    }
  })
  await expect.poll(readLoginSurfaces).toEqual(expectedLoginSurfaces('light'))

  await page.getByRole('button', { name: '切换主题' }).click()
  await expect(page.locator('html')).toHaveClass(/dark/)
  await expect.poll(readLoginSurfaces).toEqual(expectedLoginSurfaces('dark'))
  expect(consoleIssues).toEqual([])
})
