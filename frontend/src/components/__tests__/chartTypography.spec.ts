// @vitest-environment jsdom
import { afterEach, describe, expect, it } from 'vitest'
import { chartTypography, echartsTheme } from '@/components/chartTheme'

const root = document.documentElement
const changed = ['--app-font-family-base', '--app-font-size-tiny', '--app-font-size-caption', '--app-font-weight-section']
afterEach(() => changed.forEach(name => root.style.removeProperty(name)))

describe('图表字体适配器', () => {
  it('主题快照从 CSS 字体和字阶读取，消费端没有第二套数值', () => {
    root.style.setProperty('--app-font-family-base', 'Fixture UI, sans-serif')
    root.style.setProperty('--app-font-size-tiny', '10.5px')
    root.style.setProperty('--app-font-size-caption', '12.5px')
    root.style.setProperty('--app-font-weight-section', '610')
    expect(echartsTheme(false).typography).toMatchObject({
      fontFamily: 'Fixture UI, sans-serif', axis: 10.5, body: 12.5, section: 610,
    })
  })

  it('CSS 尚未加载或值损坏时仍提供可渲染的文本', () => {
    root.style.setProperty('--app-font-size-tiny', 'invalid')
    expect(chartTypography().axis).toBeGreaterThan(0)
    expect(chartTypography().fontFamily).toContain('system-ui')
  })
})
