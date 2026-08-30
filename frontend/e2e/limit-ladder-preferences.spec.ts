import { expect, test, type Page, type TestInfo } from '@playwright/test'
import {
  getUserPreference,
  loginAsDebugUser,
  saveUserPreference,
  type E2EAuthSnapshot,
} from './helpers/auth'
import { collectConsoleIssues } from './helpers/console'

const defaultPreference = {
  schemaVersion: 1,
  window: 31,
  ignoreSt: true,
  boards: ['main', 'star', 'gem'],
  showAnalysisPanel: false,
}

async function openBusinessSettings(page: Page): Promise<void> {
  await page.getByTestId('page-settings-trigger').click()
  const save = page.getByTestId('limit-ladder-default-save')
  if (!await save.isVisible()) {
    await page.getByText('业务选项', { exact: true }).click()
  }
  await expect(save).toBeVisible()
}

async function readPreference(
  request: Parameters<typeof getUserPreference>[0],
  auth: E2EAuthSnapshot,
): Promise<unknown> {
  return getUserPreference(request, auth, {
    scope: 'page',
    pageKey: 'limit-ladder',
    prefKey: 'settings',
  })
}

test('个人默认支持取消、保存、URL 覆盖和恢复默认', async ({ page, request }, testInfo: TestInfo) => {
  test.setTimeout(90_000)
  test.skip(
    testInfo.project.name !== 'chromium-standard',
    '偏好写入链路只在标准视口串行执行',
  )
  const consoleIssues = collectConsoleIssues(page, { allowedHttpStatuses: [503] })
  const auth = await loginAsDebugUser(page, request, 'debug_system')
  const originalPreference = await readPreference(request, auth)
  await saveUserPreference(request, auth, {
    scope: 'page',
    pageKey: 'limit-ladder',
    prefKey: 'settings',
    value: defaultPreference,
  })

  try {
    await page.goto('/limit-ladder')
    await expect(page.getByTestId('limit-ladder-main')).toBeVisible()
    await expect(page).toHaveURL(/window=31/)

    await openBusinessSettings(page)
    await page.getByTestId('limit-ladder-default-window-20').click()
    await page.getByTestId('limit-ladder-default-cancel').click()
    await expect(page.getByTestId('page-settings-drawer')).toBeHidden()
    expect(await readPreference(request, auth)).toEqual(defaultPreference)

    await openBusinessSettings(page)
    await page.getByTestId('limit-ladder-default-window-20').click()
    await page.route('**/api/user-preferences', async (route) => {
      if (route.request().method() !== 'POST') {
        await route.continue()
        return
      }
      await route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({ code: 5000, msg: '偏好服务暂不可用', data: null }),
      })
    })
    await page.getByTestId('limit-ladder-default-save').click()
    await expect(page.getByText('默认偏好保存失败，请检查网络后重试')).toBeVisible()
    await expect(page.getByTestId('page-settings-drawer')).toBeVisible()
    expect(await readPreference(request, auth)).toEqual(defaultPreference)
    await page.getByTestId('limit-ladder-default-cancel').click()
    await page.unroute('**/api/user-preferences')

    await openBusinessSettings(page)
    await page.getByTestId('limit-ladder-default-window-20').click()
    await page.getByTestId('limit-ladder-default-boards')
      .getByText('科创板', { exact: true })
      .click()
    await page.getByTestId('limit-ladder-default-ignore-st-switch').click()
    await page.getByTestId('limit-ladder-default-analysis-switch').click()
    await expect(page.getByTestId('limit-ladder-default-window-20'))
      .toHaveAttribute('aria-pressed', 'true')
    await expect(page.getByTestId('limit-ladder-default-boards')
      .getByRole('checkbox', { name: '科创板' }))
      .not.toBeChecked()
    await expect(page.getByTestId('limit-ladder-default-ignore-st-switch'))
      .not.toHaveClass(/is-checked/)
    await expect(page.getByTestId('limit-ladder-default-analysis-switch'))
      .toHaveClass(/is-checked/)

    const screenshotPath = testInfo.outputPath('limit-ladder-preference-draft.png')
    await page.screenshot({ path: screenshotPath, fullPage: true })
    await testInfo.attach('limit-ladder-preference-draft', {
      path: screenshotPath,
      contentType: 'image/png',
    })

    await page.getByTestId('limit-ladder-default-save').click()
    await expect(page.getByText('已保存连板天梯默认偏好')).toBeVisible()
    await expect.poll(() => readPreference(request, auth)).toEqual({
      schemaVersion: 1,
      window: 20,
      ignoreSt: false,
      boards: ['main', 'gem'],
      showAnalysisPanel: true,
    })

    await page.goto('/limit-ladder')
    await expect(page).toHaveURL(/window=20/)
    await expect(page).toHaveURL(/boards=main,gem/)
    await expect(page).toHaveURL(/ignore_st=0/)
    await expect(page.getByTestId('market-hide-analysis')).toBeVisible()

    await page.goto('/limit-ladder?window=60&boards=star&ignore_st=1')
    await expect(page.getByTestId('limit-ladder-window-60')).toHaveAttribute('aria-pressed', 'true')
    await expect(page.getByTestId('limit-ladder-ignore-st')).toBeChecked()

    await openBusinessSettings(page)
    await page.getByTestId('page-settings-reset').click()
    await expect(page).toHaveURL(/window=31/)
    await expect(page).not.toHaveURL(/boards=/)
    await expect(page).not.toHaveURL(/ignore_st=/)
    await expect(page.getByTestId('market-show-analysis')).toBeVisible()
    await expect.poll(() => readPreference(request, auth)).toEqual(defaultPreference)
    expect(consoleIssues).toEqual([])
  } finally {
    await saveUserPreference(request, auth, {
      scope: 'page',
      pageKey: 'limit-ladder',
      prefKey: 'settings',
      value: originalPreference ?? defaultPreference,
    })
  }
})
