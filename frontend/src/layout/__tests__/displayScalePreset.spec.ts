// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import {
  initDisplayScale, resetDisplayScaleForTests, setCustomDisplayScalePercent,
  setAutoScaleResponsiveExponent, setDisplayScaleMode, useDisplayScale,
} from '@/composables/useDisplayScale'

describe('系统外观配置驱动自动缩放', () => {
  beforeEach(() => {
    localStorage.clear()
    resetDisplayScaleForTests()
    Object.defineProperty(window.screen, 'availWidth', { configurable: true, value: 1920 })
    Object.defineProperty(window.screen, 'availHeight', { configurable: true, value: 1080 })
    initDisplayScale()
  })
  afterEach(() => {
    resetDisplayScaleForTests()
    localStorage.clear()
  })

  it('系统配置变化会重算当前自动比例', () => {
    expect(useDisplayScale().effectivePercent.value).toBe(94)
    setAutoScaleResponsiveExponent(0)
    expect(useDisplayScale().effectivePercent.value).toBe(100)
    setAutoScaleResponsiveExponent(0.2)
    expect(useDisplayScale().effectivePercent.value).toBe(90)
    setAutoScaleResponsiveExponent(undefined)
    expect(useDisplayScale().effectivePercent.value).toBe(94)
  })

  it('系统策略不改变手动偏好，恢复自动时读取新策略', () => {
    setCustomDisplayScalePercent(123)
    setAutoScaleResponsiveExponent(0)
    expect(useDisplayScale().effectivePercent.value).toBe(123)
    setDisplayScaleMode('auto')
    expect(useDisplayScale().effectivePercent.value).toBe(100)
  })

  it('首屏从系统配置缓存恢复指数', () => {
    resetDisplayScaleForTests()
    localStorage.setItem('ai-stocks:auto-scale-exponent:v1', '0')
    initDisplayScale()
    expect(useDisplayScale().effectivePercent.value).toBe(100)
  })
})
