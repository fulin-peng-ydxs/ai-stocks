import { expect, test } from '@playwright/test'
import { loginAsDebugUser } from './helpers/auth'

test.describe('系统组件四态预览', () => {
  test('四态共用稳定容器，非 ready 态消费统一状态组件', async ({ page, request }) => {
    const consoleIssues: string[] = []
    page.on('console', (msg) => {
      if (['error', 'warning'].includes(msg.type())) consoleIssues.push(msg.text())
    })

    await loginAsDebugUser(page, request, 'debug_system')
    await page.goto('/system/layout/components')
    await page.getByTestId('component-catalog-data-table-preview').click()

    const drawer = page.getByTestId('component-preview-drawer')
    const preview = page.getByTestId('component-state-preview')
    await expect(drawer).toBeVisible()
    await expect(drawer).toContainText('业务页面仍需接入真实数据并单独通过四态测试')
    await expect(preview).toHaveAttribute('data-state', 'ready')

    const readyBox = await preview.boundingBox()
    expect(readyBox).not.toBeNull()
    const readyOverflow = await preview.evaluate((element) => ({
      clientHeight: element.clientHeight,
      scrollHeight: element.scrollHeight,
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
    }))
    expect(readyOverflow.scrollHeight, 'ready 预览内容不应被纵向裁切').toBeLessThanOrEqual(readyOverflow.clientHeight)
    expect(readyOverflow.scrollWidth, 'ready 预览内容不应被横向裁切').toBeLessThanOrEqual(readyOverflow.clientWidth)

    for (const state of ['loading', 'empty', 'error'] as const) {
      await page.getByTestId(`component-state-${state}`).click()
      await expect(preview).toHaveAttribute('data-state', state)
      await expect(preview.locator(`.app-state-block--${state}`)).toHaveCount(1)
      const box = await preview.boundingBox()
      expect(box).not.toBeNull()
      expect(box?.width).toBeCloseTo(readyBox?.width ?? 0, 1)
      expect(box?.height).toBeCloseTo(readyBox?.height ?? 0, 1)
      const overflow = await preview.evaluate((element) => ({
        clientHeight: element.clientHeight,
        scrollHeight: element.scrollHeight,
        clientWidth: element.clientWidth,
        scrollWidth: element.scrollWidth,
      }))
      expect(overflow.scrollHeight, `${state} 预览内容不应被纵向裁切`).toBeLessThanOrEqual(overflow.clientHeight)
      expect(overflow.scrollWidth, `${state} 预览内容不应被横向裁切`).toBeLessThanOrEqual(overflow.clientWidth)
    }

    expect(consoleIssues).toEqual([])
  })
})
