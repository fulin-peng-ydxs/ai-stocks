import * as echarts from 'echarts'
import { viewportDeltaToLayoutPixels } from '@/utils/displayScaleGeometry'

type ZRenderPointerEvent = Event & {
  clientX?: number
  clientY?: number
  zrX?: number
  zrY?: number
}

const coordinateNormalizedElements = new WeakSet<HTMLElement>()
const POINTER_EVENT_TYPES = [
  'pointerdown',
  'pointermove',
  'pointerup',
  'pointerout',
  'mousedown',
  'mousemove',
  'mouseup',
  'mouseout',
  'click',
  'dblclick',
  'contextmenu',
] as const

function installPointerCoordinateNormalization(element: HTMLElement): void {
  if (coordinateNormalizedElements.has(element)) return

  const normalize = (rawEvent: Event) => {
    const event = rawEvent as ZRenderPointerEvent
    if (!Number.isFinite(event.clientX) || !Number.isFinite(event.clientY)) return

    const rect = element.getBoundingClientRect()
    event.zrX = viewportDeltaToLayoutPixels(event.clientX! - rect.left, element, 'x')
    event.zrY = viewportDeltaToLayoutPixels(event.clientY! - rect.top, element, 'y')
  }

  // ZRender 优先消费 zrX/zrY。捕获阶段先把视口坐标换回图表布局坐标，
  // 避免祖先 zoom 下浏览器 offsetX/offsetY 与 SVG 布局尺寸不一致。
  POINTER_EVENT_TYPES.forEach(type => element.addEventListener(type, normalize, true))
  coordinateNormalizedElements.add(element)
}

/** 应用根允许非整数缩放；统一使用矢量渲染和同一套指针坐标换算。 */
export function initVectorEChart(element: HTMLElement): echarts.ECharts {
  installPointerCoordinateNormalization(element)
  return echarts.init(element, undefined, { renderer: 'svg' })
}
