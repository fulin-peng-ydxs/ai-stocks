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

const echartsMock = vi.hoisted(() => {
  const instances: Array<Record<string, any>> = []
  return {
    instances,
    init: vi.fn(() => {
      let disposed = false
      const listeners = new Map<string, Array<(event: unknown) => void>>()
      const instance = {
        group: undefined as string | undefined,
        setOption: vi.fn(),
        dispatchAction: vi.fn(),
        resize: vi.fn(),
        dispose: vi.fn(() => { disposed = true }),
        isDisposed: vi.fn(() => disposed),
        on: vi.fn((name: string, handler: (event: unknown) => void) => {
          listeners.set(name, [...(listeners.get(name) ?? []), handler])
        }),
        emit(name: string, event: unknown) {
          listeners.get(name)?.forEach((handler) => handler(event))
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
let mockClientHeight = 240

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

async function mountWorkspace(extraProps: Record<string, unknown> = {}) {
  const source = bars()
  const wrapper = mount(StockChartWorkspace, {
    props: {
      bars: source,
      indicators: indicators(source),
      ...extraProps,
    },
    global: {
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
    expect(clamped.attributes('data-min-height')).toBe('384')
    clamped.unmount()
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
    mockClientHeight = 240
  })

  it('默认创建三幅独立图、唯一联动 group，并把日期轴 slider 放在底图', async () => {
    const wrapper = await mountWorkspace()

    expect(wrapper.findAll('.stock-chart-panel')).toHaveLength(3)
    expect(wrapper.text()).toContain('K线（日线·前复权）')
    expect(wrapper.text()).toContain('量能')
    expect(wrapper.text()).toContain('MACD（12,26,9·前复权）')

    await wrapper.setProps({ adjustLabel: '原始连续指数' })
    expect(wrapper.text()).toContain('K线（日线·原始连续指数）')
    expect(wrapper.text()).toContain('MACD（12,26,9·原始连续指数）')
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

  it('空数据标题仍从共享 MA/VMA 定义生成', async () => {
    const wrapper = await mountWorkspace({ bars: [], indicators: [] })
    const labels = (selector: string) => wrapper.findAll(selector).map(
      (metric) => metric.text().replace(/\s+--$/, ''),
    )

    expect(labels('.stock-chart-panel--kline .stock-chart-panel__metric'))
      .toEqual(KLINE_MA_DEFINITIONS.map(({ label }) => label))
    expect(labels('.stock-chart-panel--volume .stock-chart-panel__metric'))
      .toEqual(['总量', ...VOLUME_MA_DEFINITIONS.map(({ label }) => label)])

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

  it('pointermove 只发草稿，pointercancel 作为终态仅提交一次并触发 resize', async () => {
    const wrapper = await mountWorkspace()
    const separator = wrapper.find('[role="separator"]')

    await separator.trigger('pointerdown', { pointerId: 7, clientY: 100 })
    window.dispatchEvent(pointerEvent('pointermove', 7, 130))
    await nextTick()

    expect(wrapper.emitted('ratioDraft')).toHaveLength(1)
    expect(wrapper.emitted('ratioCommit')).toBeUndefined()
    expect(echartsMock.instances.some((instance) => instance.resize.mock.calls.length > 0)).toBe(true)

    window.dispatchEvent(pointerEvent('pointercancel', 7, 130))
    window.dispatchEvent(pointerEvent('pointerup', 7, 130))
    await nextTick()

    expect(wrapper.emitted('ratioCommit')).toHaveLength(1)
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

  it('KeepAlive 停用释放实例，恢复时只重建一组实例和监听', async () => {
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
        stubs: {
          AppStateBlock: true,
        },
      },
    })
    await nextTick()
    await nextTick()
    expect(echartsMock.init).toHaveBeenCalledTimes(3)
    expect(ResizeObserverMock.instances).toHaveLength(1)
    expect(ResizeObserverMock.instances[0].observe).toHaveBeenCalledTimes(1)

    visible.value = false
    await nextTick()
    expect(echartsMock.instances.slice(0, 3).every(
      (instance) => instance.dispose.mock.calls.length === 1,
    )).toBe(true)
    expect(ResizeObserverMock.instances[0].disconnect).toHaveBeenCalledTimes(1)

    visible.value = true
    await nextTick()
    await nextTick()
    expect(echartsMock.init).toHaveBeenCalledTimes(6)
    expect(echartsMock.instances.slice(3).every(
      (instance) => instance.dispose.mock.calls.length === 0,
    )).toBe(true)
    expect(ResizeObserverMock.instances).toHaveLength(2)
    expect(ResizeObserverMock.instances[0].disconnect).toHaveBeenCalledTimes(1)
    expect(ResizeObserverMock.instances[1].observe).toHaveBeenCalledTimes(1)

    wrapper.unmount()
    expect(ResizeObserverMock.instances[1].disconnect).toHaveBeenCalledTimes(1)
  })

  it('容器为 0×0 时延迟初始化，尺寸恢复后由 ResizeObserver 补建图表', async () => {
    mockClientWidth = 0
    mockClientHeight = 0
    const wrapper = await mountWorkspace()

    expect(echartsMock.init).not.toHaveBeenCalled()
    expect(ResizeObserverMock.instances).toHaveLength(1)

    mockClientWidth = 640
    mockClientHeight = 240
    ResizeObserverMock.instances[0].trigger()
    await nextTick()

    expect(echartsMock.init).toHaveBeenCalledTimes(3)
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
