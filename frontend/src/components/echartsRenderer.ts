import * as echarts from 'echarts'

/** 应用根允许非整数缩放；统一使用矢量渲染，避免 Canvas 位图被浏览器二次采样。 */
export function initVectorEChart(element: HTMLElement): echarts.ECharts {
  return echarts.init(element, undefined, { renderer: 'svg' })
}
