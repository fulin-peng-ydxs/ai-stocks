import { expect, test, type Locator } from '@playwright/test'
import { collectConsoleIssues } from './helpers/console'

type Geometry = {
  left: number
  right: number
  top: number
  bottom: number
  width: number
  layoutWidth: number
}

async function geometry(locator: Locator): Promise<Geometry> {
  return locator.evaluate((element) => {
    const html = element as HTMLElement
    const rect = html.getBoundingClientRect()
    return {
      left: rect.left,
      right: rect.right,
      top: rect.top,
      bottom: rect.bottom,
      width: rect.width,
      layoutWidth: html.offsetWidth,
    }
  })
}

function expectPopperAligned(trigger: Geometry, popper: Geometry, placement: string | null, scale: number) {
  const [side, variation] = (placement ?? '').split('-')
  const tolerance = 2
  expect(['top', 'bottom', 'left', 'right']).toContain(side)
  if (side === 'top' || side === 'bottom') {
    if (variation === 'start') expect(Math.abs(popper.left - trigger.left)).toBeLessThanOrEqual(tolerance)
    else if (variation === 'end') expect(Math.abs(popper.right - trigger.right)).toBeLessThanOrEqual(tolerance)
    else {
      const triggerCenter = (trigger.left + trigger.right) / 2
      const popperCenter = (popper.left + popper.right) / 2
      expect(Math.abs(popperCenter - triggerCenter)).toBeLessThanOrEqual(tolerance)
    }
    if (side === 'bottom') {
      expect(popper.top).toBeGreaterThanOrEqual(trigger.bottom)
      expect(popper.top - trigger.bottom).toBeLessThanOrEqual(16 * scale)
    } else {
      expect(popper.bottom).toBeLessThanOrEqual(trigger.top)
      expect(trigger.top - popper.bottom).toBeLessThanOrEqual(16 * scale)
    }
  } else if (side === 'left' || side === 'right') {
    if (variation === 'start') expect(Math.abs(popper.top - trigger.top)).toBeLessThanOrEqual(tolerance)
    else if (variation === 'end') expect(Math.abs(popper.bottom - trigger.bottom)).toBeLessThanOrEqual(tolerance)
    else {
      const triggerCenter = (trigger.top + trigger.bottom) / 2
      const popperCenter = (popper.top + popper.bottom) / 2
      expect(Math.abs(popperCenter - triggerCenter)).toBeLessThanOrEqual(tolerance)
    }
    if (side === 'right') {
      expect(popper.left).toBeGreaterThanOrEqual(trigger.right)
      expect(popper.left - trigger.right).toBeLessThanOrEqual(16 * scale)
    } else {
      expect(popper.right).toBeLessThanOrEqual(trigger.left)
      expect(trigger.left - popper.right).toBeLessThanOrEqual(16 * scale)
    }
  }
}

test('锚点浮层在 50%～150% 下同比缩放且点击、悬浮定位不漂移', async ({ page }) => {
  const consoleIssues = collectConsoleIssues(page)
  await page.goto('/e2e/fixtures/display-scale-popper-preview.html')

  for (const scale of [0.5, 1, 1.5]) {
    await page.getByTestId(`scale-${scale}`).click()

    const select = page.getByTestId('scale-select')
    await select.click()
    const selectPopper = page.locator('.el-select__popper:visible')
    await expect(selectPopper).toBeVisible()
    await expect(selectPopper.locator('xpath=..')).toHaveAttribute('id', /^el-popper-container-/)
    expect(await selectPopper.locator('xpath=../..').getAttribute('id')).toBe('app')

    const selectTriggerGeometry = await geometry(select)
    const selectPopperGeometry = await geometry(selectPopper)
    expect(selectPopperGeometry.width / selectPopperGeometry.layoutWidth).toBeCloseTo(scale, 1)
    expectPopperAligned(
      selectTriggerGeometry,
      selectPopperGeometry,
      await selectPopper.getAttribute('data-popper-placement'),
      scale,
    )
    await page.getByRole('option', { name: scale === 1 ? '选项 Alpha' : '选项 Beta' }).click()
    await expect(page.getByTestId('select-value')).toHaveText(scale === 1 ? 'alpha' : 'beta')
    await expect(selectPopper).toBeHidden()

    const date = page.locator('.el-date-editor:not(.edge-date)')
    await date.click()
    const datePopper = page.locator('.el-picker__popper:visible')
    await expect(datePopper).toBeVisible()
    const dateTriggerGeometry = await geometry(date)
    const datePopperGeometry = await geometry(datePopper)
    expect(datePopperGeometry.width / datePopperGeometry.layoutWidth).toBeCloseTo(scale, 1)
    expectPopperAligned(
      dateTriggerGeometry,
      datePopperGeometry,
      await datePopper.getAttribute('data-popper-placement'),
      scale,
    )
    await datePopper.locator('.el-date-table td.available').first().click()
    await expect(datePopper).toBeHidden()

    const hoverTarget = page.getByTestId('hover-target')
    await hoverTarget.hover()
    const tooltipPopper = page.getByRole('tooltip', { name: '缩放悬浮提示' })
    await expect(tooltipPopper).toBeVisible()
    await tooltipPopper.hover()
    expectPopperAligned(
      await geometry(hoverTarget),
      await geometry(tooltipPopper),
      await tooltipPopper.getAttribute('data-popper-placement'),
      scale,
    )
    await page.mouse.move(0, 0)
    await expect(tooltipPopper).toBeHidden()

    const edgeSelect = page.getByTestId('edge-select')
    await edgeSelect.click()
    const edgeSelectPopper = page.locator('.el-select__popper:visible')
    await expect(edgeSelectPopper).toBeVisible()
    const edgeSelectGeometry = await geometry(edgeSelectPopper)
    expect(edgeSelectGeometry.left).toBeGreaterThanOrEqual(0)
    expect(edgeSelectGeometry.right).toBeLessThanOrEqual(page.viewportSize()!.width + 2)
    await page.getByRole('option', { name: '边缘选项 Beta' }).click()
    await expect(edgeSelectPopper).toBeHidden()

    const edgeDate = page.locator('.edge-date')
    await edgeDate.click()
    const edgeDatePopper = page.locator('.el-picker__popper:visible')
    await expect(edgeDatePopper).toBeVisible()
    const edgeDateGeometry = await geometry(edgeDatePopper)
    expect(edgeDateGeometry.top).toBeGreaterThanOrEqual(0)
    expect(edgeDateGeometry.left).toBeGreaterThanOrEqual(0)
    expect(edgeDateGeometry.right).toBeLessThanOrEqual(page.viewportSize()!.width + 2)
    expect(edgeDateGeometry.bottom).toBeLessThanOrEqual(page.viewportSize()!.height + 2)
    await edgeDatePopper.locator('.el-date-table td.available').first().click()
    await expect(edgeDatePopper).toBeHidden()

    const bottomSelect = page.getByTestId('bottom-select')
    await bottomSelect.click()
    const bottomSelectPopper = page.locator('.el-select__popper:visible')
    await expect(bottomSelectPopper).toBeVisible()
    const bottomSelectGeometry = await geometry(bottomSelectPopper)
    expect(bottomSelectGeometry.top).toBeGreaterThanOrEqual(0)
    expect(bottomSelectGeometry.bottom).toBeLessThanOrEqual(page.viewportSize()!.height + 2)
    expect(await bottomSelectPopper.getAttribute('data-popper-placement')).toMatch(/^top/)
    await page.getByRole('option', { name: '底部选项 Beta' }).click()
    await expect(bottomSelectPopper).toBeHidden()
  }

  expect(consoleIssues).toEqual([])
})
