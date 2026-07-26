import { expect, test } from '@playwright/test'
import { collectConsoleIssues } from './helpers/console'

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
      if (node.matches('.app') || node.querySelector('.app')) trace.shellMounted = true
      if (node.matches('.login-shell') || node.querySelector('.login-shell')) trace.loginMounted = true
    }
    new MutationObserver((records) => {
      records.forEach((record) => record.addedNodes.forEach(inspect))
    }).observe(document, { childList: true, subtree: true })
  })

  await page.goto('/login')
  await expect(page.locator('.login-shell')).toBeVisible()
  const brandMark = page.getByRole('img', { name: '复盘啦' })
  await expect(brandMark).toHaveCSS('width', '184px')
  await expect(brandMark).toHaveCSS('height', '52px')
  await page.reload()
  await expect(page.locator('.login-shell')).toBeVisible()

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
  await expect.poll(readLoginSurfaces).toEqual({
    brand: 'rgb(252, 252, 252)',
    auth: 'rgb(255, 255, 255)',
    card: 'rgb(255, 255, 255)',
  })

  await page.getByRole('button', { name: '切换主题' }).click()
  await expect(page.locator('html')).toHaveClass(/dark/)
  await expect.poll(readLoginSurfaces).toEqual({
    brand: 'rgb(31, 31, 31)',
    auth: 'rgb(23, 23, 23)',
    card: 'rgb(31, 31, 31)',
  })
  expect(consoleIssues).toEqual([])
})
