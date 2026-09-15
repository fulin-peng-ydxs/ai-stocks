// @vitest-environment jsdom
import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import StockIntradayDialog from '@/components/stock-chart/StockIntradayDialog.vue'
import { getIntraday } from '@/api/stocks'

vi.mock('@/api/stocks', () => ({ getIntraday: vi.fn() }))

const ready = {
  code: '002251.SZ',
  name: '步步高',
  trade_date: '2026-09-10',
  frequency: '1m' as const,
  status: 'ready' as const,
  source: 'sina' as const,
  fetched_at: '2026-09-11T00:00:00Z',
  supported_start: '2026-09-01',
  supported_end: '2026-09-10',
  pre_close: 3.55,
  turnover_rate: 6.8,
  points: [{
    time: '09:31', open: 3.6, high: 3.62, low: 3.59, close: 3.61,
    volume: 10, amount: 3610, average_price: 3.61,
  }],
}

const DialogStub = defineComponent({
  name: 'AppDialog',
  props: ['modelValue', 'title'],
  emits: ['close'],
  template: '<section v-if="modelValue" class="dialog-stub"><slot name="header"><h2>{{ title }}</h2></slot><slot /></section>',
})
const StateStub = defineComponent({
  props: {
    state: String,
    title: String,
    description: String,
    retry: Boolean,
  },
  emits: ['retry'],
  template: '<div class="state-stub">{{ title }} {{ description }}<button v-if="retry" @click="$emit(\'retry\')">重试</button></div>',
})
const ChartStub = defineComponent({
  name: 'StockIntradayChart',
  props: ['points', 'preClose'],
  template: '<div class="chart-stub" />',
})
const NoticeStub = defineComponent({
  name: 'AppStatusNotice',
  props: ['title', 'description', 'tone'],
  template: '<div class="notice-stub">{{ title }} {{ description }}</div>',
})

function mountDialog() {
  return mount(StockIntradayDialog, {
    props: {
      modelValue: true,
      code: '002251.SZ',
      name: '步步高',
      tradeDate: '2026-09-10',
    },
    global: {
      stubs: {
        AppDialog: DialogStub,
        AppStatusNotice: NoticeStub,
        AppStateBlock: StateStub,
        StockIntradayChart: ChartStub,
      },
    },
  })
}

describe('StockIntradayDialog', () => {
  beforeEach(() => {
    vi.mocked(getIntraday).mockReset()
  })

  it('打开后才加载，成功时向共享双图传入数据', async () => {
    vi.mocked(getIntraday).mockResolvedValue(ready)
    const wrapper = mountDialog()
    await flushPromises()

    expect(getIntraday).toHaveBeenCalledWith('002251.SZ', '2026-09-10', expect.any(AbortSignal))
    expect(wrapper.findComponent(DialogStub).props('title'))
      .toBe('步步高 002251.SZ · 2026-09-10 · 分时')
    expect(wrapper.text()).toContain('步步高002251.SZ · 2026-09-10')
    const chart = wrapper.findComponent(ChartStub)
    expect(chart.props('points')).toEqual(ready.points)
    expect(chart.props('preClose')).toBe(3.55)
    expect(wrapper.find('.stock-quote-summary__hero dd').text()).toBe('3.61')
    expect(wrapper.text()).not.toContain('收盘')
    expect(wrapper.find('.stock-quote-summary__hero dd').classes()).toContain('is-up')
    expect(wrapper.findAll('.stock-quote-summary__column')).toHaveLength(4)
    expect(wrapper.text()).toContain('开盘3.60最高3.62')
    expect(wrapper.text()).toContain('最低3.59涨幅+1.69%')
    expect(wrapper.text()).toContain('振幅0.85%换手率6.80%')
    expect(wrapper.text()).toContain('成交量10手')
    expect(wrapper.text()).toContain('成交额3,610')
  })

  it('超范围显示免费源日期说明，不渲染图表', async () => {
    vi.mocked(getIntraday).mockResolvedValue({ ...ready, status: 'out_of_range', points: [] })
    const wrapper = mountDialog()
    await flushPromises()

    expect(wrapper.text()).toContain('该日期超出免费源范围')
    expect(wrapper.text()).toContain('2026-09-01 至 2026-09-10')
    expect(wrapper.findComponent(ChartStub).exists()).toBe(false)
  })

  it('部分分钟点保留图表并给出不完整提示', async () => {
    vi.mocked(getIntraday).mockResolvedValue({ ...ready, status: 'partial' })
    const wrapper = mountDialog()
    await flushPromises()

    expect(wrapper.findComponent(ChartStub).exists()).toBe(true)
    expect(wrapper.findComponent(NoticeStub).props('tone')).toBe('info')
    expect(wrapper.html()).toContain('免费源返回的分钟点可能不完整')
  })

  it('无成交数据显示就地空态', async () => {
    vi.mocked(getIntraday).mockResolvedValue({ ...ready, status: 'no_data', points: [] })
    const wrapper = mountDialog()
    await flushPromises()

    expect(wrapper.text()).toContain('该交易日暂无分时数据')
    expect(wrapper.findComponent(ChartStub).exists()).toBe(false)
  })

  it('切换日期会取消旧请求，旧响应不能覆盖新结果', async () => {
    let resolveFirst!: (value: typeof ready) => void
    const first = new Promise<typeof ready>((resolve) => { resolveFirst = resolve })
    vi.mocked(getIntraday)
      .mockReturnValueOnce(first)
      .mockResolvedValueOnce({ ...ready, trade_date: '2026-09-09', pre_close: 3.4 })
    const wrapper = mountDialog()
    const firstSignal = vi.mocked(getIntraday).mock.calls[0][2]!

    await wrapper.setProps({ tradeDate: '2026-09-09' })
    await flushPromises()
    expect(firstSignal.aborted).toBe(true)
    expect(wrapper.findComponent(ChartStub).props('preClose')).toBe(3.4)

    resolveFirst(ready)
    await flushPromises()
    expect(wrapper.findComponent(ChartStub).props('preClose')).toBe(3.4)
  })

  it('重复点击同一日期会用 requestKey 触发新请求', async () => {
    vi.mocked(getIntraday).mockResolvedValue(ready)
    const wrapper = mountDialog()
    await flushPromises()

    await wrapper.setProps({ requestKey: 1 })
    await flushPromises()

    expect(getIntraday).toHaveBeenCalledTimes(2)
    expect(getIntraday).toHaveBeenLastCalledWith(
      '002251.SZ',
      '2026-09-10',
      expect.any(AbortSignal),
    )
  })

  it('关闭弹窗会取消在途请求', async () => {
    vi.mocked(getIntraday).mockReturnValue(new Promise(() => {}))
    const wrapper = mountDialog()
    const signal = vi.mocked(getIntraday).mock.calls[0][2]!

    wrapper.findComponent(DialogStub).vm.$emit('close')
    await flushPromises()

    expect(signal.aborted).toBe(true)
    expect(wrapper.emitted('update:modelValue')).toEqual([[false]])
  })

  it('503 使用弹窗内错误态并支持重试', async () => {
    vi.mocked(getIntraday)
      .mockRejectedValueOnce(new Error('免费分时源暂时不可用'))
      .mockResolvedValueOnce(ready)
    const wrapper = mountDialog()
    await flushPromises()

    expect(wrapper.text()).toContain('分时行情暂时不可用')
    await wrapper.get('button').trigger('click')
    await flushPromises()
    expect(getIntraday).toHaveBeenCalledTimes(2)
    expect(wrapper.findComponent(ChartStub).exists()).toBe(true)
  })
})
