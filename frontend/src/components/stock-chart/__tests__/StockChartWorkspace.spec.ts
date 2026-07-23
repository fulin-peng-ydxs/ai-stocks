// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent, h, KeepAlive, nextTick, ref } from 'vue'
import type { Bar, IndicatorRow } from '@/api/stocks'
import StockChartWorkspace from '@/components/stock-chart/StockChartWorkspace.vue'

const echartsMock = vi.hoisted(() => {
  const instances: Array<Record<string, any>> = []
  return {
    instances,
    init: vi.fn(() => {
      let disposed = false
      const instance = {
        group: undefined as string | undefined,
        setOption: vi.fn(),
        resize: vi.fn(),
        dispose: vi.fn(() => { disposed = true }),
        isDisposed: vi.fn(() => disposed),
        on: vi.fn(),
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
  observe = vi.fn()
  disconnect = vi.fn()
}

vi.stubGlobal('ResizeObserver', ResizeObserverMock)

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
  beforeEach(() => {
    echartsMock.instances.length = 0
    echartsMock.init.mockClear()
    echartsMock.connect.mockClear()
    echartsMock.disconnect.mockClear()
  })

  it('默认创建三幅独立图、唯一联动 group，并把日期轴 slider 放在底图', async () => {
    const wrapper = await mountWorkspace()

    expect(wrapper.findAll('.stock-chart-panel')).toHaveLength(3)
    expect(wrapper.text()).toContain('K线（日线·前复权）')
    expect(wrapper.text()).toContain('量能')
    expect(wrapper.text()).toContain('MACD（12,26,9·前复权）')
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

  it('局部 MACD 状态保留图名与稳定面板，错误态只发出局部重试', async () => {
    const wrapper = await mountWorkspace({
      macdState: 'error',
      macdError: 'MACD 暂不可用，K线与量能不受影响',
    })

    const macdPanel = wrapper.find('.stock-chart-panel--macd')
    expect(macdPanel.text()).toContain('MACD（12,26,9·前复权）')
    expect(macdPanel.text()).toContain('MACD 加载失败')
    expect(macdPanel.attributes('style')).toContain('min-height: 126px')

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

    visible.value = false
    await nextTick()
    expect(echartsMock.instances.slice(0, 3).every(
      (instance) => instance.dispose.mock.calls.length === 1,
    )).toBe(true)

    visible.value = true
    await nextTick()
    await nextTick()
    expect(echartsMock.init).toHaveBeenCalledTimes(6)
    expect(echartsMock.instances.slice(3).every(
      (instance) => instance.dispose.mock.calls.length === 0,
    )).toBe(true)

    wrapper.unmount()
  })
})
