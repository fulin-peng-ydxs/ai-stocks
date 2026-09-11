// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import {
  initDisplayScale, resetDisplayScaleForTests, setCustomDisplayScalePercent,
  setDisplayScaleMode, useDisplayScale,
} from '@/composables/useDisplayScale'
import { initLayoutPreset, setLayoutPreset, setRuntimePresetSources } from '../useLayoutPreset'

const path = 'responsiveDefaults.autoScaleResponsiveExponent'
const preset = (value?: number) => ({
  key: 'scale-test', name: '缩放测试', description: '',
  config: { values: value === undefined ? {} : { [path]: value } },
})

describe('预设驱动自动缩放', () => {
  beforeEach(() => {
    localStorage.clear()
    resetDisplayScaleForTests()
    Object.defineProperty(window.screen, 'availWidth', { configurable: true, value: 1920 })
    Object.defineProperty(window.screen, 'availHeight', { configurable: true, value: 1080 })
    setRuntimePresetSources([])
    setLayoutPreset('balanced')
    initDisplayScale()
  })
  afterEach(() => {
    resetDisplayScaleForTests()
    setLayoutPreset('balanced')
    setRuntimePresetSources([])
    localStorage.clear()
  })

  it('切换、同 key 保存、停用与历史缺项均重算当前自动比例', () => {
    setRuntimePresetSources([preset(0)])
    expect(useDisplayScale().effectivePercent.value).toBe(94)
    setLayoutPreset('scale-test')
    expect(useDisplayScale().effectivePercent.value).toBe(100)
    setRuntimePresetSources([preset(0.2)])
    expect(useDisplayScale().effectivePercent.value).toBe(90)
    setRuntimePresetSources([preset()])
    expect(useDisplayScale().effectivePercent.value).toBe(94)
    setRuntimePresetSources([preset(0)])
    setRuntimePresetSources([])
    expect(useDisplayScale().effectivePercent.value).toBe(94)
  })

  it('预设切换不改变手动偏好，恢复自动时读取新策略', () => {
    setCustomDisplayScalePercent(123)
    setRuntimePresetSources([preset(0)])
    setLayoutPreset('scale-test')
    expect(useDisplayScale().effectivePercent.value).toBe(123)
    setDisplayScaleMode('auto')
    expect(useDisplayScale().effectivePercent.value).toBe(100)
  })

  it('首屏从预设缓存恢复指数，再初始化缩放时不会恢复为硬编码默认值', () => {
    resetDisplayScaleForTests()
    localStorage.setItem('ai-stocks:layout-preset', 'scale-test')
    localStorage.setItem('ai-stocks:layout-preset-catalog:v1', JSON.stringify([preset(0)]))
    initLayoutPreset()
    initDisplayScale()
    expect(useDisplayScale().effectivePercent.value).toBe(100)
  })
})
