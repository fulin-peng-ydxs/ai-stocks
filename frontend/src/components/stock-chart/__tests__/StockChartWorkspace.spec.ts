// @vitest-environment jsdom
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent, h, KeepAlive, nextTick, ref } from 'vue'
import type { Bar, IndicatorRow } from '@/api/stocks'
import StockChartWorkspace from '@/components/stock-chart/StockChartWorkspace.vue'
import {
  KLINE_MA_DEFINITIONS,
  VOLUME_MA_DEFINITIONS,
} from '@/components/stock-chart/chartUtils'
import { useTheme } from '@/composables/useTheme'
import { setLayoutPreset, setPresetOverrides } from '@/layout/useLayoutPreset'
import { WORKSPACE_RESIZE_ACTIVE } from '@/layout/workspaceResizeContext'

const echartsMock = vi.hoisted(() => {
  const instances: Array<Record<string, any>> = []
  return {
    instances,
    init: vi.fn((
      _element?: HTMLElement,
      _theme?: unknown,
      _options?: { renderer?: string },
    ) => {
      let disposed = false
      const listeners = new Map<string, Array<(event: unknown) => void>>()
      const rendererListeners = new Map<string, Array<(event: unknown) => void>>()
      const instance = {
        group: undefined as string | undefined,
        getDom: vi.fn(() => _element),
        setOption: vi.fn(),
        dispatchAction: vi.fn(),
        resize: vi.fn(),
        containPixel: vi.fn(() => true),
        dispose: vi.fn(() => { disposed = true }),
        isDisposed: vi.fn(() => disposed),
        on: vi.fn((name: string, handler: (event: unknown) => void) => {
          listeners.set(name, [...(listeners.get(name) ?? []), handler])
        }),
        getZr: vi.fn(() => ({
          on: (name: string, handler: (event: unknown) => void) => {
            rendererListeners.set(name, [...(rendererListeners.get(name) ?? []), handler])
          },
        })),
        emit(name: string, event: unknown) {
          listeners.get(name)?.forEach((handler) => handler(event))
        },
        emitRenderer(name: string, event: unknown = {}) {
          rendererListeners.get(name)?.forEach((handler) => handler(event))
        },
      }
      instances.push(instance)
      return instance
    }),
    connect: vi.fn(),
    disconnect: vi.fn(),
  }
})

vi.mock('echarts', () => ({
  init: echartsMock.init,
  connect: echartsMock.connect,
  disconnect: echartsMock.disconnect,
}))

class ResizeObserverMock {
  static instances: ResizeObserverMock[] = []

  observe = vi.fn()
  unobserve = vi.fn()
  disconnect = vi.fn()
  private readonly callback: ResizeObserverCallback

  constructor(callback: ResizeObserverCallback) {
    this.callback = callback
    ResizeObserverMock.instances.push(this)
  }

  trigger(): void {
    this.callback([], this as unknown as ResizeObserver)
  }
}

vi.stubGlobal('ResizeObserver', ResizeObserverMock)

const clientWidthDescriptor = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'clientWidth')
const clientHeightDescriptor = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'clientHeight')
let mockClientWidth = 640
let mockClientHeight = 800

beforeAll(() => {
  Object.defineProperty(HTMLElement.prototype, 'clientWidth', {
    configurable: true,
    get: () => mockClientWidth,
  })
  Object.defineProperty(HTMLElement.prototype, 'clientHeight', {
    configurable: true,
    get: () => mockClientHeight,
  })
})

afterAll(() => {
  if (clientWidthDescriptor) {
    Object.defineProperty(HTMLElement.prototype, 'clientWidth', clientWidthDescriptor)
  } else {
    Reflect.deleteProperty(HTMLElement.prototype, 'clientWidth')
  }
  if (clientHeightDescriptor) {
    Object.defineProperty(HTMLElement.prototype, 'clientHeight', clientHeightDescriptor)
  } else {
    Reflect.deleteProperty(HTMLElement.prototype, 'clientHeight')
  }
})

function bars(): Bar[] {
  return Array.from({ length: 40 }, (_, index) => ({
    date: `2026-06-${String(index + 1).padStart(2, '0')}`,
    open: 10 + index * 0.1,
    high: 10.5 + index * 0.1,
    low: 9.5 + index * 0.1,
    close: 10.2 + index * 0.1,
    pre_close: 10 + index * 0.1,
    volume: 100_000 + index * 1_000,
    amount: 1_000_000,
    turnover_rate: 1,
  }))
}

function indicators(source: Bar[]): IndicatorRow[] {
  return source.map((bar, index) => ({
    trade_date: bar.date,
    macd_diff: index / 100,
    macd_dea: index / 120,
    macd_hist: index / 80,
    macd_golden_cross: index === 20,
    macd_dead_cross: index === 30,
  }))
}

async function mountWorkspace(
  extraProps: Record<string, unknown> = {},
  slots: Record<string, string> = {},
  provided: Record<PropertyKey, unknown> = {},
) {
  const source = bars()
  const wrapper = mount(StockChartWorkspace, {
    props: {
      bars: source,
      indicators: indicators(source),
      ...extraProps,
    },
    slots,
    global: {
      provide: provided,
      directives: { loading: {} },
      stubs: {
        AppStateBlock: {
          props: ['state', 'title', 'description', 'retry'],
          emits: ['retry'],
          template: `
            <div class="state-stub" :data-state="state">
              {{ title }}{{ description }}
              <button v-if="retry" @click="$emit('retry')">重试 MACD</button>
            </div>
          `,
        },
        StockChartOperationsDrawer: {
          props: ['modelValue', 'drawerId'],
          emits: ['update:modelValue', 'closed'],
          template: `
            <aside v-if="modelValue" class="stock-chart-operations-drawer-stub" :id="drawerId">
              <slot />
              <button
                data-testid="close-chart-operations"
                @click="$emit('update:modelValue', false); $emit('closed')"
              >关闭</button>
            </aside>
          `,
        },
      },
    },
  })
  await nextTick()
  await nextTick()
  return wrapper
}

function pointerEvent(type: string, pointerId: number, clientY: number): Event {
  const event = new Event(type)
  Object.defineProperties(event, {
    pointerId: { value: pointerId },
    clientY: { value: clientY },
  })
  return event
}

describe('StockChartWorkspace', () => {
  it('紧凑双图高度仍保留 K 线和量能，并对过小请求执行安全下限', async () => {
    mockClientHeight = 480
    const compact = await mountWorkspace({
      slot2: 'volume',
      slot3: 'hidden',
      minHeight: 480,
    })
    expect(compact.attributes('data-min-height')).toBe('480')
    expect(compact.findAll('.stock-chart-panel')).toHaveLength(2)
    expect(compact.find('.stock-chart-panel--volume').exists()).toBe(true)
    const compactSplitter = compact.find('[role="separator"]')
    expect(compactSplitter.attributes('aria-valuenow')).toBe('73')
    expect(compactSplitter.attributes('aria-valuemax')).toBe('73')
    compact.unmount()

    const clamped = await mountWorkspace({
      slot2: 'volume',
      slot3: 'hidden',
      minHeight: 100,
    })
    expect(clamped.attributes('data-min-height')).toBe('412')
    clamped.unmount()
  })

  it('视口填充模式使用紧凑面板下限，低高度工作台不再被固定详情高度顶出', async () => {
    mockClientHeight = 300
    const wrapper = await mountWorkspace({
      slot2: 'volume',
      slot3: 'hidden',
      fitAvailableHeight: true,
    })

    expect(wrapper.attributes('data-min-height')).toBe('262')
    expect(wrapper.find('.stock-chart-panel--kline').attributes('style')).toContain('min-height: 178px')
    expect(wrapper.find('.stock-chart-panel--volume').attributes('style')).toContain('min-height: 76px')
    wrapper.unmount()
  })

  const { isDark } = useTheme()

  beforeEach(() => {
    isDark.value = false
    setPresetOverrides({})
    setLayoutPreset('balanced')
    echartsMock.instances.length = 0
    echartsMock.init.mockClear()
    echartsMock.connect.mockClear()
    echartsMock.disconnect.mockClear()
    ResizeObserverMock.instances.length = 0
    mockClientWidth = 640
    mockClientHeight = 800
    document.documentElement.style.removeProperty('--app-display-scale')
  })

  it('使用 SVG 保持非整数页面缩放下的矢量清晰度，并响应比例变化', async () => {
    const wrapper = await mountWorkspace()

    expect(echartsMock.init).toHaveBeenCalledTimes(3)
    expect(echartsMock.init.mock.calls[0]?.[2]).toMatchObject({ renderer: 'svg' })

    document.documentElement.style.setProperty('--app-display-scale', '0.91')
    window.dispatchEvent(new Event('resize'))
    await nextTick()
    await nextTick()

    expect(echartsMock.init).toHaveBeenCalledTimes(3)
    expect(echartsMock.instances.slice(0, 3).every(
      (instance) => instance.resize.mock.calls.length > 0,
    )).toBe(true)
    const updatedKlineOption = echartsMock.instances[0].setOption.mock.calls.at(-1)?.[0]
    expect(updatedKlineOption.series[0].barWidth).toBe('65.52%')

    wrapper.unmount()
  })

  it('默认创建三幅独立图、唯一联动 group，并把日期轴 slider 放在底图', async () => {
    const wrapper = await mountWorkspace()

    expect(wrapper.findAll('.stock-chart-panel')).toHaveLength(3)
    expect(wrapper.text()).toContain('K线（前复权）')
    expect(wrapper.text()).toContain('量能')
    expect(wrapper.text()).toContain('MACD（12,26,9·前复权）')

    await wrapper.setProps({ adjustLabel: '原始连续指数' })
    expect(wrapper.text()).toContain('K线（原始连续指数）')
    expect(wrapper.text()).toContain('MACD（12,26,9·原始连续指数）')

    await wrapper.setProps({ adjustLabel: '后复权', macdAdjustLabel: '前复权' })
    expect(wrapper.text()).toContain('K线（后复权）')
    expect(wrapper.text()).toContain('MACD（12,26,9·前复权）')
    expect(wrapper.findAll('.stock-chart-panel__date')).toHaveLength(1)
    expect(wrapper.find('.stock-chart-panel--kline .stock-chart-panel__date').exists()).toBe(true)
    expect(wrapper.find('.stock-chart-panel--volume .stock-chart-panel__date').exists()).toBe(false)
    expect(wrapper.find('.stock-chart-panel--macd .stock-chart-panel__date').exists()).toBe(false)
    expect(wrapper.find('[aria-live]').exists()).toBe(false)
    expect(echartsMock.init).toHaveBeenCalledTimes(3)
    expect(new Set(echartsMock.instances.map((instance) => instance.group)).size).toBe(1)
    expect(echartsMock.connect).toHaveBeenCalledTimes(1)

    const latestOptions = echartsMock.instances.map((instance) =>
      instance.setOption.mock.calls.at(-1)?.[0] as { dataZoom?: unknown[] },
    )
    expect(latestOptions[0].dataZoom).toHaveLength(1)
    expect(latestOptions[1].dataZoom).toHaveLength(1)
    expect(latestOptions[2].dataZoom).toHaveLength(2)
  })

  it('周期请求完成前不把旧周期指标错配到新 K 线', async () => {
    const source: Bar[] = [
      { ...bars()[0]!, date: '2026-09-14' },
      { ...bars()[1]!, date: '2026-09-15' },
      { ...bars()[2]!, date: '2026-09-18' },
    ]
    const periodIndicators: IndicatorRow[] = [{
      trade_date: '2026-09-18',
      macd_diff: 0.3,
      macd_dea: 0.2,
      macd_hist: 0.2,
    }]
    const wrapper = await mountWorkspace({
      bars: source,
      indicators: periodIndicators,
      enableKlinePeriodSwitch: true,
      klinePeriod: 'week',
      indicatorsPeriod: 'day',
    })
    const macd = echartsMock.instances[2]

    expect(macd.setOption.mock.calls.at(-1)?.[0].series[0].data)
      .toEqual([{ value: null, itemStyle: expect.any(Object) }])

    await wrapper.setProps({ indicatorsPeriod: 'week' })
    await nextTick()

    expect(macd.setOption.mock.calls.at(-1)?.[0].series[0].data)
      .toEqual([{ value: 0.2, itemStyle: expect.any(Object) }])
    wrapper.unmount()
  })

  it('向消费页报告当前光标 K 线，离开图表后恢复最新行情', async () => {
    const source = bars()
    const wrapper = await mountWorkspace()
    const kline = echartsMock.instances[0]

    kline.emit('updateAxisPointer', { seriesDataIndices: [{ dataIndex: 6 }] })
    await nextTick()
    expect(wrapper.emitted('activeBarChange')?.at(-1)?.[0]).toEqual(source[6])

    kline.emit('globalout', {})
    await nextTick()
    expect(wrapper.emitted('activeBarChange')?.at(-1)?.[0]).toBeNull()
    wrapper.unmount()
  })

  it('挂载与尺寸变化时向统一偏好层报告图表工作区实际宽高', async () => {
    const wrapper = await mountWorkspace()
    expect(wrapper.emitted('workspaceResize')?.at(-1)?.[0]).toEqual(expect.objectContaining({
      width: 640,
      height: 800,
      ratios: [0.6, 0.2, 0.2],
      minimumRatios: expect.any(Array),
    }))

    mockClientWidth = 1280
    mockClientHeight = 720
    ResizeObserverMock.instances[0]?.trigger()
    await nextTick()
    expect(wrapper.emitted('workspaceResize')?.at(-1)?.[0]).toEqual(expect.objectContaining({
      width: 1280,
      height: 720,
      ratios: [0.6, 0.2, 0.2],
      minimumRatios: expect.any(Array),
    }))
    wrapper.unmount()
    expect(wrapper.emitted('workspaceResize')?.at(-1)?.[0]).toBeUndefined()
  })

  it('低高度触发安全约束时上报页面实际显示比例而非原始配置比例', async () => {
    mockClientHeight = 300
    const wrapper = await mountWorkspace({ fitAvailableHeight: true })
    const sample = wrapper.emitted('workspaceResize')?.at(-1)?.[0] as {
      ratios: number[]
    }
    const separators = wrapper.findAll('[role="separator"]')

    expect(sample.ratios).not.toEqual([0.6, 0.2, 0.2])
    expect(Math.round(sample.ratios[0] * 100))
      .toBe(Number(separators[0].attributes('aria-valuenow')))
    expect(Math.round((sample.ratios[0] + sample.ratios[1]) * 100))
      .toBe(Number(separators[1].attributes('aria-valuenow')))
    wrapper.unmount()
  })

  it('所有消费页面都按底部画布真实高度统一收展可视滑动条', async () => {
    mockClientHeight = 60
    const wrapper = await mountWorkspace({ fitAvailableHeight: true })
    const bottomChart = echartsMock.instances[2]

    expect(bottomChart.setOption.mock.calls.at(-1)?.[0].dataZoom).toHaveLength(1)

    mockClientHeight = 120
    ResizeObserverMock.instances[0]?.trigger()
    await nextTick()
    await nextTick()

    expect(bottomChart.setOption.mock.calls.at(-1)?.[0].dataZoom).toHaveLength(2)
    wrapper.unmount()
  })

  it('只在 K 线标题尾部承载调用方提供的工作区操作', async () => {
    const wrapper = await mountWorkspace({}, {
      'header-actions': '<button data-testid="header-action">收起辅助信息</button>',
    })

    expect(wrapper.findAll('[data-testid="header-action"]')).toHaveLength(1)
    expect(wrapper.find('.stock-chart-panel--kline [data-testid="header-action"]').exists())
      .toBe(true)
    wrapper.unmount()
  })

  it('仅在显式启用后响应日K蜡烛单击，并忽略均线与辅助图', async () => {
    const disabled = await mountWorkspace()
    echartsMock.instances[0].emit('click', { seriesType: 'candlestick', dataIndex: 2 })
    expect(disabled.emitted('barClick')).toBeUndefined()
    disabled.unmount()
    echartsMock.instances.length = 0

    const enabled = await mountWorkspace({ enableIntradayDrilldown: true })
    const [kline, volume] = echartsMock.instances
    kline.emit('click', { seriesType: 'line', dataIndex: 2 })
    volume.emit('click', { seriesType: 'bar', dataIndex: 2 })
    expect(enabled.emitted('barClick')).toBeUndefined()

    kline.emit('click', { seriesType: 'candlestick', dataIndex: 2 })
    expect(enabled.emitted('barClick')).toEqual([['2026-06-03']])
    const option = kline.setOption.mock.calls.at(-1)?.[0]
    expect(option.series[0].cursor).toBe('pointer')
  })

  it('按需显示至最新涨跌，并在自选区间模式接管两次 K 线点击', async () => {
    const wrapper = await mountWorkspace({
      enableReturnMeasurement: true,
      enableIntradayDrilldown: true,
    })
    const kline = echartsMock.instances[0]

    expect(wrapper.find('.stock-chart-measurement__hint').exists()).toBe(false)
    expect(wrapper.find('.stock-chart-operations-drawer-stub').exists()).toBe(false)
    expect(wrapper.get('[data-testid="stock-chart-toggle-operations"]').attributes('aria-expanded'))
      .toBe('false')
    await wrapper.get('[data-testid="stock-chart-toggle-operations"]').trigger('click')
    expect(wrapper.find('.stock-chart-operations-drawer-stub').exists()).toBe(true)
    expect(wrapper.get('.chart-operation-group').text()).toContain('涨跌测算')
    expect(wrapper.get('[data-testid="stock-chart-measurement-mode-latest"]').text()).toBe('截止')
    expect(wrapper.get('[data-testid="stock-chart-measurement-mode-range"]').text()).toBe('区间')
    expect(wrapper.find('[data-testid="stock-chart-measurement-mode"]').exists()).toBe(true)
    expect(wrapper.get('[data-testid="stock-chart-measurement-mode"]').classes())
      .not.toContain('page-segmented--primary')
    expect(wrapper.find('.stock-chart-panel__date').text()).toBe('2026-06-40')
    await wrapper.get('.stock-chart-panel--kline .stock-chart-panel__canvas')
      .trigger('pointerenter')
    expect(wrapper.find('[data-testid="stock-chart-measurement-mode"]').exists()).toBe(true)
    kline.emit('updateAxisPointer', { seriesDataIndices: [{ dataIndex: 6 }] })
    await nextTick()
    expect(wrapper.find('.stock-chart-measurement__hint').exists()).toBe(false)
    expect(wrapper.emitted('measurementSummaryChange')?.at(-1)?.[0]).toEqual({
      label: '截止 2026-06-40',
      value: '+30.56%',
      tone: 'up',
      details: [{ label: '交易日', value: '33个交易日' }],
    })
    const latestOption = kline.setOption.mock.calls.at(-1)?.[0]
    const tooltipHtml = latestOption.tooltip.formatter([{ dataIndex: 6 }])
    expect(tooltipHtml).toContain('截止 2026-06-40')
    expect(tooltipHtml).toContain('+30.56%')
    expect(tooltipHtml).toContain('33个交易日')

    await wrapper.get('[data-testid="close-chart-operations"]').trigger('click')
    expect(wrapper.find('.stock-chart-operations-drawer-stub').exists()).toBe(false)
    expect(wrapper.find('[data-testid="stock-chart-measurement-mode"]').exists()).toBe(false)
    expect(wrapper.find('.stock-chart-measurement__hint').exists()).toBe(false)
    expect(wrapper.find('.stock-chart-panel__date').text()).toBe('2026-06-07')
    await wrapper.get('[data-testid="stock-chart-toggle-operations"]').trigger('click')
    expect(wrapper.find('.stock-chart-operations-drawer-stub').exists()).toBe(true)

    expect(latestOption.series[0].markArea).toBeUndefined()

    kline.emit('globalout', {})
    await nextTick()
    expect(wrapper.find('.stock-chart-measurement__hint').exists()).toBe(false)
    expect(wrapper.emitted('measurementSummaryChange')?.at(-1)?.[0]).toBeNull()
    await wrapper.get('.stock-chart-panel--kline').trigger('pointerleave')
    expect(wrapper.find('[data-testid="stock-chart-measurement-mode"]').exists()).toBe(true)

    await wrapper.get('.stock-chart-panel--kline .stock-chart-panel__canvas')
      .trigger('pointerenter')
    await wrapper.get('[data-testid="stock-chart-measurement-mode-range"]').trigger('click')
    expect(wrapper.emitted('update:returnMeasurementMode')).toEqual([['range']])
    expect(wrapper.text()).toContain('点击 K 线选择起点')
    await wrapper.get('.stock-chart-panel--kline').trigger('pointerleave')
    expect(wrapper.find('[data-testid="stock-chart-measurement-mode"]').exists()).toBe(true)
    expect(wrapper.find('.stock-chart-measurement__hint').exists()).toBe(false)

    await wrapper.get('.stock-chart-panel--kline .stock-chart-panel__canvas')
      .trigger('pointerenter')
    expect(wrapper.find('[data-testid="stock-chart-measurement-mode"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('点击 K 线选择起点')
    expect(wrapper.get('.stock-chart-measurement__hint').attributes('style'))
      .toContain('top: 8px; right: 64px; max-width: calc(100% - 128px)')

    kline.containPixel.mockReturnValueOnce(false)
    kline.emit('updateAxisPointer', { seriesDataIndices: [{ dataIndex: 1 }] })
    kline.emitRenderer('click', { offsetX: 12, offsetY: 320 })
    expect(wrapper.text()).toContain('点击 K 线选择起点')

    kline.emit('updateAxisPointer', { seriesDataIndices: [{ dataIndex: 2 }] })
    kline.emitRenderer('click', { offsetX: 120, offsetY: 80 })
    kline.emit('updateAxisPointer', { seriesDataIndices: [{ dataIndex: 6 }] })
    await nextTick()
    expect(wrapper.text()).toContain('2026-06-03起')
    expect(wrapper.text()).toContain('移动到终点后再次点击')
    expect(wrapper.emitted('measurementSummaryChange')?.at(-1)?.[0]).toEqual({
      label: '区间涨跌',
      value: '+3.85%',
      tone: 'up',
      details: [
        { label: '区间', value: '2026-06-03 → 2026-06-07' },
        { label: '交易日', value: '4个交易日' },
      ],
    })

    kline.emitRenderer('click', { offsetX: 180, offsetY: 70 })
    await nextTick()
    expect(wrapper.text()).toContain('2026-06-03 → 2026-06-07')
    expect(wrapper.text()).toContain('点击 K 线重新选择起点')
    expect(wrapper.emitted('barClick')).toBeUndefined()
    const option = kline.setOption.mock.calls.at(-1)?.[0]
    expect(option.series[0].markArea.data).toEqual([[{ xAxis: 2 }, { xAxis: 6 }]])

    wrapper.unmount()
  })

  it('未启用涨跌测算时保持原有紧凑日期标题', async () => {
    const wrapper = await mountWorkspace()

    expect(wrapper.find('[data-testid="stock-chart-measurement-mode"]').exists()).toBe(false)
    expect(wrapper.find('.stock-chart-panel__date').text()).toBe('2026-06-40')
    wrapper.unmount()
  })

  it('按外部默认值初始化 K 线周期与测算模式，并响应后续默认值变更', async () => {
    const wrapper = await mountWorkspace({
      enableReturnMeasurement: true,
      enableKlinePeriodSwitch: true,
      klinePeriod: 'week',
      returnMeasurementMode: 'range',
    })

    expect(wrapper.find('.stock-chart-operations-drawer-stub').exists()).toBe(false)
    expect(wrapper.get('[data-testid="stock-chart-toggle-operations"]').attributes('aria-expanded'))
      .toBe('false')
    expect(wrapper.get('[data-testid="stock-chart-kline-period-week"]').attributes('aria-pressed'))
      .toBe('true')
    expect(wrapper.text()).toContain('K线（前复权）')

    await wrapper.get('[data-testid="stock-chart-toggle-operations"]').trigger('click')
    expect(wrapper.get('[data-testid="stock-chart-measurement-mode-range"]')
      .attributes('aria-pressed')).toBe('true')

    await wrapper.setProps({ klinePeriod: 'month', returnMeasurementMode: 'latest' })
    expect(wrapper.get('[data-testid="stock-chart-kline-period-month"]').attributes('aria-pressed'))
      .toBe('true')
    expect(wrapper.text()).toContain('K线（前复权）')
    expect(wrapper.get('[data-testid="stock-chart-measurement-mode-latest"]')
      .attributes('aria-pressed')).toBe('true')
    wrapper.unmount()
  })

  it('复权口径作为抽屉内临时操作并更新标题', async () => {
    const wrapper = await mountWorkspace({
      enableAdjustModeSwitch: true,
      adjustMode: 'qfq',
    })

    await wrapper.get('[data-testid="stock-chart-toggle-operations"]').trigger('click')
    expect(wrapper.get('[data-testid="stock-chart-adjust-mode-qfq"]')
      .attributes('aria-pressed')).toBe('true')
    expect(wrapper.get('[data-testid="stock-chart-adjust-mode"]').classes())
      .not.toContain('page-segmented--primary')
    expect(wrapper.get('.chart-operation-group').text()).toContain('复权口径')

    await wrapper.get('[data-testid="stock-chart-adjust-mode-hfq"]').trigger('click')
    expect(wrapper.emitted('update:adjustMode')).toEqual([['hfq']])
    expect(wrapper.text()).toContain('K线（后复权）')
    wrapper.unmount()
  })

  it('切换周期会重置光标和缩放，且非日 K 不触发分时下钻', async () => {
    const wrapper = await mountWorkspace({
      enableKlinePeriodSwitch: true,
      enableIntradayDrilldown: true,
    })
    const kline = echartsMock.instances[0]

    kline.emit('updateAxisPointer', { seriesDataIndices: [{ dataIndex: 6 }] })
    kline.emit('datazoom', { batch: [{ start: 20, end: 70 }] })
    await wrapper.get('[data-testid="stock-chart-kline-period-week"]').trigger('click')
    await nextTick()
    await nextTick()

    expect(wrapper.emitted('update:klinePeriod')).toEqual([['week']])
    expect(wrapper.emitted('activeBarChange')?.at(-1)?.[0]).toBeNull()
    expect(wrapper.text()).toContain('K线（前复权）')
    expect(kline.setOption.mock.calls.at(-1)?.[0].dataZoom[0]).toMatchObject({
      start: 0,
      end: 100,
    })

    kline.emit('click', { seriesType: 'candlestick', dataIndex: 1 })
    expect(wrapper.emitted('barClick')).toBeUndefined()
    wrapper.unmount()
  })

  it('空数据标题仍从共享 MA/VMA 定义生成', async () => {
    const wrapper = await mountWorkspace({ bars: [], indicators: [] })
    const labels = (selector: string) => wrapper.findAll(selector).map((label) => label.text())

    expect(labels('.stock-chart-panel--kline .stock-chart-legend__label'))
      .toEqual(KLINE_MA_DEFINITIONS.map(({ label }) => label))
    expect(labels('.stock-chart-panel--volume .stock-chart-legend__label'))
      .toEqual(['总量', ...VOLUME_MA_DEFINITIONS.map(({ label }) => label)])

    expect(wrapper.classes()).toContain('app-stock-chart-frame')
    expect(wrapper.findAll('.stock-chart-legend__marker').length).toBeGreaterThan(0)

    wrapper.unmount()
  })

  it('同时挂载两个工作区时使用不同 group，互不连接或断开', async () => {
    const first = await mountWorkspace()
    const firstGroup = echartsMock.instances[0].group
    expect(new Set(echartsMock.instances.slice(0, 3).map((instance) => instance.group)).size)
      .toBe(1)

    const second = await mountWorkspace()
    const secondGroup = echartsMock.instances[3].group
    expect(new Set(echartsMock.instances.slice(3, 6).map((instance) => instance.group)).size)
      .toBe(1)
    expect(secondGroup).not.toBe(firstGroup)

    const secondDisconnectsBefore = echartsMock.disconnect.mock.calls.filter(
      ([group]) => group === secondGroup,
    ).length
    first.unmount()
    expect(echartsMock.disconnect).toHaveBeenCalledWith(firstGroup)
    expect(echartsMock.disconnect.mock.calls.filter(
      ([group]) => group === secondGroup,
    )).toHaveLength(secondDisconnectsBefore)

    second.unmount()
    expect(echartsMock.disconnect).toHaveBeenCalledWith(secondGroup)
  })

  it('任意图缩放后显式同步全部兄弟图，并在重绘后保留共享窗口', async () => {
    const wrapper = await mountWorkspace()
    const [kline, volume, macd] = echartsMock.instances

    macd.emit('datazoom', { batch: [{ start: 24, end: 82 }] })
    await nextTick()

    expect(kline.dispatchAction).toHaveBeenCalledWith({
      type: 'dataZoom',
      start: 24,
      end: 82,
    })
    expect(volume.dispatchAction).toHaveBeenCalledWith({
      type: 'dataZoom',
      start: 24,
      end: 82,
    })
    expect(macd.dispatchAction).not.toHaveBeenCalled()

    await wrapper.setProps({ macdState: 'loading' })
    await nextTick()

    echartsMock.instances.forEach((instance) => {
      const option = instance.setOption.mock.calls.at(-1)?.[0] as {
        dataZoom: Array<{ start: number; end: number }>
      }
      expect(option.dataZoom[0]).toMatchObject({ start: 24, end: 82 })
    })

    kline.emit('datazoom', { start: 35, end: 70 })
    expect(volume.dispatchAction).toHaveBeenLastCalledWith({
      type: 'dataZoom',
      start: 35,
      end: 70,
    })
    expect(macd.dispatchAction).toHaveBeenLastCalledWith({
      type: 'dataZoom',
      start: 35,
      end: 70,
    })
  })

  it('切换明暗模式时重新读取默认主题 token 并重绘全部画布', async () => {
    const wrapper = await mountWorkspace()
    const callsBefore = echartsMock.instances.map((instance) => instance.setOption.mock.calls.length)
    const backgroundBefore = echartsMock.instances[0].setOption.mock.calls.at(-1)?.[0]
      ?.backgroundColor

    isDark.value = true
    setLayoutPreset('balanced')
    await nextTick()
    await nextTick()

    echartsMock.instances.forEach((instance, index) => {
      expect(instance.setOption.mock.calls.length).toBeGreaterThan(callsBefore[index])
    })
    const backgroundAfter = echartsMock.instances[0].setOption.mock.calls.at(-1)?.[0]
      ?.backgroundColor
    expect(backgroundAfter).not.toBe(backgroundBefore)

    wrapper.unmount()
  })

  it('当前预设更新后重绘全部画布但忽略基础表面覆盖', async () => {
    const wrapper = await mountWorkspace()
    const callsBefore = echartsMock.instances.map((instance) => instance.setOption.mock.calls.length)

    setPresetOverrides({
      balanced: {
        'tokens.light.surfaceBg': '#f2f5f8',
        'tokens.light.border': '#a8b4c2',
        'tokens.light.primary': '#2457d6',
      },
    })
    await nextTick()
    await nextTick()

    echartsMock.instances.forEach((instance, index) => {
      expect(instance.setOption.mock.calls.length).toBeGreaterThan(callsBefore[index])
      expect(instance.setOption.mock.calls.at(-1)?.[0]?.backgroundColor).toBe('#ffffff')
    })

    wrapper.unmount()
  })

  it('隐藏辅助图时销毁实例和无效分隔线，剩余底图接管日期轴', async () => {
    const wrapper = await mountWorkspace()
    const removed = echartsMock.instances[2]

    await wrapper.setProps({ slot3: 'hidden', heightRatios: [0.75, 0.25] })
    await nextTick()

    expect(wrapper.findAll('.stock-chart-panel')).toHaveLength(2)
    expect(wrapper.findAll('[role="separator"]')).toHaveLength(1)
    expect(removed.dispose).toHaveBeenCalledTimes(1)
    const volumeOption = echartsMock.instances[1].setOption.mock.calls.at(-1)?.[0] as {
      dataZoom?: unknown[]
    }
    expect(volumeOption.dataZoom).toHaveLength(2)
  })

  it('局部 MACD 加载、历史不足和错误状态均保留图名与稳定面板', async () => {
    const wrapper = await mountWorkspace({ macdState: 'loading' })
    let macdPanel = wrapper.find('.stock-chart-panel--macd')

    expect(macdPanel.text()).toContain('MACD（12,26,9·前复权）')
    expect(macdPanel.text()).toContain('MACD 数据加载中')
    expect(macdPanel.find('button').exists()).toBe(false)
    expect(macdPanel.attributes('style')).toContain('min-height: 126px')

    await wrapper.setProps({ macdState: 'insufficient' })
    await nextTick()
    macdPanel = wrapper.find('.stock-chart-panel--macd')
    expect(macdPanel.text()).toContain('历史数据不足')
    expect(macdPanel.find('button').exists()).toBe(false)

    await wrapper.setProps({
      macdState: 'error',
      macdError: 'MACD 暂不可用，K线与量能不受影响',
    })
    await nextTick()
    macdPanel = wrapper.find('.stock-chart-panel--macd')
    expect(macdPanel.text()).toContain('MACD 加载失败')

    await macdPanel.find('button').trigger('click')
    expect(wrapper.emitted('retryMacd')).toHaveLength(1)
  })

  it('分隔线具备完整 ARIA，键盘按 2% 调整并提交一次', async () => {
    const wrapper = await mountWorkspace()
    const separator = wrapper.find('[role="separator"]')

    expect(separator.attributes('aria-orientation')).toBe('horizontal')
    expect(Number(separator.attributes('aria-valuemin'))).toBeGreaterThan(0)
    expect(Number(separator.attributes('aria-valuemax'))).toBeGreaterThan(
      Number(separator.attributes('aria-valuemin')),
    )
    expect(separator.attributes('aria-valuenow')).toBe('60')

    await separator.trigger('keydown', { key: 'ArrowUp' })

    const draft = wrapper.emitted('ratioDraft')?.at(-1)?.[0] as number[]
    const committed = wrapper.emitted('ratioCommit')?.at(-1)?.[0] as number[]
    expect(draft[0]).toBeCloseTo(0.58)
    expect(draft[1]).toBeCloseTo(0.22)
    expect(draft[2]).toBeCloseTo(0.2)
    expect(committed).toEqual(draft)
  })

  it('成长型紧凑外壳按实际高度释放拖动空间，仅在真实最低高度锁定', async () => {
    mockClientHeight = 900
    const wrapper = await mountWorkspace({ minHeight: 384 })
    const separator = wrapper.find('[role="separator"]')

    expect(wrapper.attributes('data-min-height')).toBe('546')
    expect(separator.attributes('aria-valuenow')).toBe('60')
    expect(Number(separator.attributes('aria-valuemax'))).toBeGreaterThan(60)

    await separator.trigger('pointerdown', { pointerId: 17, clientY: 100 })
    window.dispatchEvent(pointerEvent('pointermove', 17, 160))
    window.dispatchEvent(pointerEvent('pointerup', 17, 160))
    await nextTick()

    const committed = wrapper.emitted('ratioCommit')?.at(-1)?.[0] as number[]
    expect(committed[0]).toBeGreaterThan(0.6)

    mockClientHeight = 546
    ResizeObserverMock.instances[0]?.trigger()
    await nextTick()

    expect(separator.attributes('aria-valuenow')).toBe('52')
    expect(separator.attributes('aria-valuemax')).toBe('53')
  })

  it('同帧 pointermove 只应用最新草稿，拖动中仅刷新相邻图并在结束后全量校准', async () => {
    const wrapper = await mountWorkspace()
    const separator = wrapper.find('[role="separator"]')
    let frameCallback: FrameRequestCallback | undefined
    const requestFrame = vi.spyOn(globalThis, 'requestAnimationFrame').mockImplementation((callback) => {
      frameCallback = callback
      return 7
    })
    const cancelFrame = vi.spyOn(globalThis, 'cancelAnimationFrame').mockImplementation(() => {})
    await nextTick()
    echartsMock.instances.forEach((instance) => instance.resize.mockClear())

    await separator.trigger('pointerdown', { pointerId: 7, clientY: 100 })
    window.dispatchEvent(pointerEvent('pointermove', 7, 115))
    window.dispatchEvent(pointerEvent('pointermove', 7, 130))
    expect(requestFrame).toHaveBeenCalledTimes(1)
    expect(wrapper.emitted('ratioDraft')).toBeUndefined()

    frameCallback?.(0)
    await nextTick()

    expect(wrapper.emitted('ratioDraft')).toHaveLength(1)
    expect(wrapper.emitted('ratioCommit')).toBeUndefined()
    const resizeCounts = echartsMock.instances.map((instance) => instance.resize.mock.calls.length)
    expect(resizeCounts).toEqual([1, 1, 0])

    ResizeObserverMock.instances[0]?.trigger()
    await nextTick()
    echartsMock.instances.forEach((instance, index) => {
      expect(instance.resize.mock.calls.length).toBe(resizeCounts[index])
    })

    window.dispatchEvent(pointerEvent('pointercancel', 7, 130))
    window.dispatchEvent(pointerEvent('pointerup', 7, 130))
    await nextTick()
    await nextTick()

    expect(wrapper.emitted('ratioCommit')).toHaveLength(1)
    echartsMock.instances.forEach((instance, index) => {
      expect(instance.resize.mock.calls.length).toBe(resizeCounts[index] + 1)
    })
    requestFrame.mockRestore()
    cancelFrame.mockRestore()
  })

  it('父级左右分栏拖动期间延后图表 resize，结束后只按最终尺寸刷新', async () => {
    const ancestorResizing = ref(true)
    const wrapper = await mountWorkspace({}, {}, {
      [WORKSPACE_RESIZE_ACTIVE as symbol]: ancestorResizing,
    })
    echartsMock.instances.forEach((instance) => instance.resize.mockClear())

    mockClientWidth = 720
    ResizeObserverMock.instances[0]?.trigger()
    await nextTick()
    await nextTick()
    echartsMock.instances.forEach((instance) => {
      expect(instance.resize).not.toHaveBeenCalled()
    })

    ancestorResizing.value = false
    await nextTick()
    await nextTick()
    await nextTick()
    echartsMock.instances.forEach((instance) => {
      expect(instance.resize).toHaveBeenCalledTimes(1)
    })
    expect(wrapper.emitted('workspaceResize')?.at(-1)?.[0]).toEqual(expect.objectContaining({
      width: 720,
    }))
    wrapper.unmount()
  })

  it('卸载时断开 group、销毁全部实例且不残留拖动监听状态', async () => {
    const wrapper = await mountWorkspace()
    await wrapper.find('[role="separator"]').trigger('pointerdown', {
      pointerId: 9,
      clientY: 100,
    })

    wrapper.unmount()

    expect(document.body.classList.contains('stock-chart-is-resizing')).toBe(false)
    expect(echartsMock.disconnect).toHaveBeenCalled()
    expect(echartsMock.instances.every((instance) => instance.dispose.mock.calls.length === 1))
      .toBe(true)
  })

  it('KeepAlive 停用释放实例，恢复页先绘制后只重建一组实例和监听', async () => {
    const visible = ref(true)
    const source = bars()
    const Host = defineComponent({
      setup: () => () => h(KeepAlive, null, {
        default: () => visible.value
          ? h(StockChartWorkspace, {
              bars: source,
              indicators: indicators(source),
            })
          : h('div', 'inactive'),
      }),
    })
    const wrapper = mount(Host, {
      global: {
        directives: { loading: {} },
        stubs: {
          AppStateBlock: true,
        },
      },
    })
    await nextTick()
    await nextTick()
    expect(echartsMock.init).toHaveBeenCalledTimes(3)
    expect(ResizeObserverMock.instances).toHaveLength(1)
    expect(ResizeObserverMock.instances[0].observe).toHaveBeenCalledTimes(4)

    visible.value = false
    await nextTick()
    expect(echartsMock.instances.slice(0, 3).every(
      (instance) => instance.dispose.mock.calls.length === 1,
    )).toBe(true)
    expect(ResizeObserverMock.instances[0].disconnect).toHaveBeenCalledTimes(1)

    visible.value = true
    await nextTick()
    expect(echartsMock.init).toHaveBeenCalledTimes(3)
    expect(wrapper.find('.stock-chart-workspace').attributes('aria-busy')).toBe('true')
    await new Promise((resolve) => window.setTimeout(resolve, 0))
    await new Promise((resolve) => window.setTimeout(resolve, 0))
    expect(wrapper.find('.stock-chart-workspace').attributes('aria-busy')).toBe('false')
    await nextTick()
    expect(echartsMock.init).toHaveBeenCalledTimes(6)
    expect(echartsMock.instances.slice(3).every(
      (instance) => instance.dispose.mock.calls.length === 0,
    )).toBe(true)
    expect(ResizeObserverMock.instances).toHaveLength(2)
    expect(ResizeObserverMock.instances[0].disconnect).toHaveBeenCalledTimes(1)
    expect(ResizeObserverMock.instances[1].observe).toHaveBeenCalledTimes(4)

    wrapper.unmount()
    expect(ResizeObserverMock.instances[1].disconnect).toHaveBeenCalledTimes(1)
  })

  it('图表在缓存页面激活后才挂载时，第一次菜单恢复仍会重建画布', async () => {
    const pageVisible = ref(true)
    const chartVisible = ref(false)
    const source = bars()
    const CachedPage = defineComponent({
      name: 'LateChartCachedPage',
      setup: () => () => h('div', chartVisible.value
        ? [h(StockChartWorkspace, {
            bars: source,
            indicators: indicators(source),
          })]
        : []),
    })
    const Host = defineComponent({
      setup: () => () => h(KeepAlive, null, {
        default: () => pageVisible.value ? h(CachedPage) : h('div', 'inactive'),
      }),
    })
    const wrapper = mount(Host, {
      global: {
        directives: { loading: {} },
        stubs: { AppStateBlock: true },
      },
    })
    await nextTick()
    chartVisible.value = true
    await nextTick()
    await nextTick()
    expect(echartsMock.init).toHaveBeenCalledTimes(3)

    pageVisible.value = false
    await nextTick()
    expect(echartsMock.instances.slice(0, 3).every(
      (instance) => instance.dispose.mock.calls.length === 1,
    )).toBe(true)

    pageVisible.value = true
    await nextTick()
    expect(wrapper.find('.stock-chart-workspace').attributes('aria-busy')).toBe('true')
    await new Promise((resolve) => window.setTimeout(resolve, 0))
    await new Promise((resolve) => window.setTimeout(resolve, 0))
    await nextTick()

    expect(echartsMock.init).toHaveBeenCalledTimes(6)
    expect(wrapper.find('.stock-chart-workspace').attributes('aria-busy')).toBe('false')
    wrapper.unmount()
  })

  it('容器为 0×0 时延迟初始化，尺寸恢复后由 ResizeObserver 补建图表', async () => {
    mockClientWidth = 0
    mockClientHeight = 0
    const wrapper = await mountWorkspace()

    expect(echartsMock.init).not.toHaveBeenCalled()
    expect(ResizeObserverMock.instances).toHaveLength(1)

    mockClientWidth = 640
    mockClientHeight = 800
    ResizeObserverMock.instances[0].trigger()
    await nextTick()

    expect(echartsMock.init).toHaveBeenCalledTimes(3)
    wrapper.unmount()
  })

  it('KeepAlive 恢复瞬间仍为 0×0 时跨帧补建，不依赖 ResizeObserver 恰好通知', async () => {
    const visible = ref(true)
    const source = bars()
    const Host = defineComponent({
      setup: () => () => h(KeepAlive, null, {
        default: () => visible.value
          ? h(StockChartWorkspace, {
              bars: source,
              indicators: indicators(source),
            })
          : h('div', 'inactive'),
      }),
    })
    const wrapper = mount(Host, {
      global: {
        directives: { loading: {} },
        stubs: { AppStateBlock: true },
      },
    })
    await nextTick()
    await nextTick()
    expect(echartsMock.init).toHaveBeenCalledTimes(3)

    visible.value = false
    await nextTick()
    mockClientWidth = 0
    mockClientHeight = 0
    visible.value = true
    await nextTick()
    await new Promise((resolve) => window.setTimeout(resolve, 0))
    expect(echartsMock.init).toHaveBeenCalledTimes(3)

    mockClientWidth = 640
    mockClientHeight = 800
    await new Promise((resolve) => window.setTimeout(resolve, 25))
    await nextTick()

    expect(echartsMock.init).toHaveBeenCalledTimes(6)
    expect(wrapper.find('.stock-chart-workspace').attributes('aria-busy')).toBe('false')
    wrapper.unmount()
  })

  it('传入 markers 时在 K 线 markPoint 渲染买卖点，买蓝▲/卖橙▼置于蜡烛外', async () => {
    const source = bars()
    const wrapper = await mountWorkspace({
      markers: [
        { date: source[10].date, kind: 'buy', label: '买入\n12.20' },
        { date: source[20].date, kind: 'sell', label: '卖出\n14.20' },
      ],
    })
    const klineInstance = echartsMock.instances[0]
    const option = klineInstance.setOption.mock.calls.at(-1)?.[0]
    const klineSeries = (option.series as Array<Record<string, unknown>>)
      .find((series) => series.type === 'candlestick')
    const points = (klineSeries?.markPoint as { data?: unknown[] })?.data ?? []

    expect(points).toHaveLength(2)
    const buy = (points as Array<Record<string, unknown>>)
      .find((point) => point.kind === 'buy')
    const sell = (points as Array<Record<string, unknown>>)
      .find((point) => point.kind === 'sell')
    const buyCoord = buy?.coord as [number, number]
    const sellCoord = sell?.coord as [number, number]
    expect(buyCoord[0]).toBe(10)
    expect(sellCoord[0]).toBe(20)
    // 买点钉在最低价下方、卖点钉在最高价上方。
    expect(buyCoord[1]).toBeCloseTo(source[10].low * 0.985)
    expect(sellCoord[1]).toBeCloseTo(source[20].high * 1.015)
    expect((buy?.itemStyle as { color?: string }).color).toBeTruthy()
    expect((sell?.itemStyle as { color?: string }).color).toBeTruthy()
    expect((buy?.label as { formatter?: string }).formatter).toBe('买入\n12.20')
    expect((sell?.label as { formatter?: string }).formatter).toBe('卖出\n14.20')
    wrapper.unmount()
  })

  it('未传 markers 时 K 线 markPoint 为空，不影响个股详情等既有页面', async () => {
    const wrapper = await mountWorkspace()
    const klineInstance = echartsMock.instances[0]
    const option = klineInstance.setOption.mock.calls.at(-1)?.[0]
    const klineSeries = (option.series as Array<Record<string, unknown>>)
      .find((series) => series.type === 'candlestick')
    expect((klineSeries?.markPoint as { data?: unknown[] }).data ?? []).toEqual([])
    wrapper.unmount()
  })
})
