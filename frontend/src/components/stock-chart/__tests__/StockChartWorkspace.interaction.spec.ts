// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, type VueWrapper } from '@vue/test-utils'
import { nextTick } from 'vue'
import * as echarts from 'echarts'
import type { Bar } from '@/api/stocks'
import StockChartWorkspace from '../StockChartWorkspace.vue'
import { STOCK_CHART_GRID_SIDE } from '../chartUtils'

const bars: Bar[] = Array.from({ length: 100 }, (_, index) => ({
  date: `2026-${String(Math.floor(index / 28) + 4).padStart(2, '0')}-${String(index % 28 + 1).padStart(2, '0')}`,
  open: 10 + index / 10,
  close: 10.1 + index / 10,
  high: 10.3 + index / 10,
  low: 9.8 + index / 10,
  pre_close: 10 + index / 10,
  volume: 100_000 + index * 100,
  amount: 1_000_000,
  turnover_rate: 1,
}))

let wrapper: VueWrapper | undefined

async function mountCharts(extraProps: Record<string, unknown> = {}) {
  wrapper = mount(StockChartWorkspace, {
    attachTo: document.body,
    props: { bars, zoomStart: 25, zoomEnd: 75, ...extraProps },
    global: { directives: { loading: {} } },
  })
  await nextTick()
  await nextTick()
  return wrapper.findAll('.stock-chart-panel__canvas').map((canvas) => (
    echarts.getInstanceByDom(canvas.element as HTMLElement)!
  ))
}

/** 经过真实 ZRender 的漫游监听，不用假的 datazoom 事件代替按住/移动/松手。 */
function emitPointer(chart: echarts.ECharts, type: string, x: number) {
  chart.getZr().trigger(type, {
    offsetX: x,
    offsetY: 50,
    event: new MouseEvent(type, { button: 0 }),
  })
}

async function dragChart(chart: echarts.ECharts) {
  emitPointer(chart, 'mousedown', 300)
  for (const x of [350, 400, 450]) {
    emitPointer(chart, 'mousemove', x)
    // 等待 dataZoom 自带节流提交，检验同一次按住中的后续移动仍被处理。
    await new Promise((resolve) => setTimeout(resolve, 60))
  }
  emitPointer(chart, 'mouseup', 450)
}

function zoomRange(chart: echarts.ECharts) {
  return (chart.getOption().dataZoom as Array<{ start: number; end: number }>)[0]!
}

beforeEach(() => {
  vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(800)
  vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(240)
  // SVG 图表仍通过 Canvas 测量文字；这里只替代字宽，保留真实 ECharts 交互控制器。
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({
    measureText: (text: string) => ({ width: text.length * 7 }),
  } as CanvasRenderingContext2D)
  vi.stubGlobal('ResizeObserver', class {
    observe() {}
    unobserve() {}
    disconnect() {}
  })
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = undefined
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('股票工作区真实 ECharts 拖动', () => {
  it.each(['kline', 'slot2', 'slot3'])('从 %s 按住连续移动时保持平移和三图同窗', async (key) => {
    const charts = await mountCharts()
    expect(charts).toHaveLength(3)
    const chart = echarts.getInstanceByDom(wrapper!.get(
      `[data-panel-key="${key}"] .stock-chart-panel__canvas`,
    ).element as HTMLElement)!
    await dragChart(chart)

    const ranges = charts.map(zoomRange)
    expect(ranges[0]!.start).toBeCloseTo(25 - 50 * 150 / (800 - 2 * STOCK_CHART_GRID_SIDE), 3)
    ranges.forEach((range) => {
      expect(range.start).toBeCloseTo(ranges[0]!.start, 5)
      expect(range.end - range.start).toBeCloseTo(50, 5)
    })
  })

  it('自选区间预览刷新不打断平移，退出区间模式后清除旧底色与端点', async () => {
    const [chart] = await mountCharts({ enableReturnMeasurement: true, returnMeasurementMode: 'range' })
    chart!.dispatchAction({ type: 'updateAxisPointer', x: 300, y: 50 })
    emitPointer(chart!, 'click', 300)
    const series = () => (chart!.getOption().series as Array<{
      markArea: { data: unknown[] }
      markLine: { data: unknown[] }
    }>)[0]!
    expect(series().markArea.data).toHaveLength(1)

    await dragChart(chart!)
    expect(zoomRange(chart!).start).toBeLessThan(15)
    expect(series().markArea.data).toHaveLength(1)

    await wrapper!.setProps({ returnMeasurementMode: 'latest' })
    expect(series().markArea.data).toEqual([])
    expect(series().markLine.data).toEqual([])
  })

  it('全日期范围时平移保持边界，不改变缩放宽度', async () => {
    const charts = await mountCharts({ zoomStart: 0, zoomEnd: 100 })
    await dragChart(charts[0]!)
    charts.forEach((chart) => expect(zoomRange(chart)).toMatchObject({ start: 0, end: 100 }))
  })
})
