export type DisplayScaleAxis = 'x' | 'y'

const FALLBACK_SCALE = 1

function finitePositive(value: number): number | undefined {
  return Number.isFinite(value) && value > 0 ? value : undefined
}

/**
 * 返回元素从布局坐标到浏览器视口坐标的实际比例。
 * 优先使用元素自身尺寸，兼容未来在应用根之外增加其他 transform 的场景。
 */
export function elementVisualScale(
  element: HTMLElement | null | undefined,
  axis: DisplayScaleAxis,
): number {
  if (element) {
    const rect = element.getBoundingClientRect()
    const layoutSize = axis === 'x' ? element.offsetWidth : element.offsetHeight
    const visualSize = axis === 'x' ? rect.width : rect.height
    const measured = layoutSize > 0 && visualSize > 0 ? visualSize / layoutSize : undefined
    const validMeasured = finitePositive(measured ?? 0)
    if (validMeasured) return validMeasured
  }

  const raw = globalThis.document
    ?.documentElement
    ?.style
    ?.getPropertyValue('--app-display-scale')
  return finitePositive(Number(raw)) ?? FALLBACK_SCALE
}

/** 把 PointerEvent/getBoundingClientRect 的视口像素差换算为元素内部的 CSS 布局像素。 */
export function viewportDeltaToLayoutPixels(
  delta: number,
  element: HTMLElement | null | undefined,
  axis: DisplayScaleAxis,
): number {
  const numeric = Number(delta)
  if (!Number.isFinite(numeric)) return 0
  return numeric / elementVisualScale(element, axis)
}
