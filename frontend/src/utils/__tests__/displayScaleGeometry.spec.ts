// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { elementVisualScale, viewportDeltaToLayoutPixels } from '@/utils/displayScaleGeometry'

describe('displayScaleGeometry', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    document.documentElement.style.removeProperty('--app-display-scale')
  })

  it('优先根据元素布局尺寸与视口矩形识别实际缩放', () => {
    const element = document.createElement('div')
    Object.defineProperty(element, 'offsetWidth', { configurable: true, value: 1000 })
    vi.spyOn(element, 'getBoundingClientRect').mockReturnValue({ width: 850 } as DOMRect)

    expect(elementVisualScale(element, 'x')).toBeCloseTo(0.85)
    expect(viewportDeltaToLayoutPixels(85, element, 'x')).toBeCloseTo(100)
  })

  it('元素尚未完成布局时回退到应用根比例', () => {
    document.documentElement.style.setProperty('--app-display-scale', '1.25')

    expect(elementVisualScale(null, 'y')).toBe(1.25)
    expect(viewportDeltaToLayoutPixels(125, null, 'y')).toBe(100)
    expect(viewportDeltaToLayoutPixels(Number.NaN, null, 'y')).toBe(0)
  })

})
