// @vitest-environment jsdom
import { mount, flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick, ref } from 'vue'
import TradeDatePicker from '@/components/TradeDatePicker.vue'

const ensureLoaded = vi.fn().mockResolvedValue(undefined)
const dataMax = ref<string | null>('2026-07-31')
vi.mock('@/composables/useTradeDates', () => ({
  useTradeDates: () => ({
    dataMax,
    disabledTradeDate: vi.fn(() => false),
    ensureLoaded,
  }),
}))

function mountPicker(defaultLatest = false, extraProps: Record<string, unknown> = {}) {
  return mount(TradeDatePicker, {
    props: { modelValue: '', defaultLatest, ...extraProps },
    global: {
      stubs: {
        ElDatePicker: {
          name: 'ElDatePicker',
          props: ['modelValue', 'placement', 'fallbackPlacements'],
          template: '<input :value="modelValue" />',
        },
      },
    },
  })
}

describe('TradeDatePicker', () => {
  beforeEach(() => {
    ensureLoaded.mockReset().mockResolvedValue(undefined)
    dataMax.value = '2026-07-31'
  })

  it('按需把空值初始化为数据最新交易日', async () => {
    const wrapper = mountPicker(true)
    await flushPromises()
    expect(ensureLoaded).toHaveBeenCalled()
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['2026-07-31'])
  })

  it('未开启默认最新时保留空值，避免改写显式日期范围页面', async () => {
    const wrapper = mountPicker(false)
    await flushPromises()
    expect(wrapper.emitted('update:modelValue')).toBeFalsy()
  })

  it('首次加载失败后可在共享交易日恢复时自动补值，并允许展开控件重试', async () => {
    dataMax.value = null
    ensureLoaded.mockRejectedValueOnce(new Error('network')).mockResolvedValue(undefined)
    const wrapper = mountPicker(true)
    await flushPromises()
    expect(wrapper.emitted('update:modelValue')).toBeFalsy()

    ;(wrapper.vm as unknown as { onVisibleChange: (visible: boolean) => void }).onVisibleChange(true)
    await flushPromises()
    expect(ensureLoaded).toHaveBeenCalledTimes(2)

    dataMax.value = '2026-08-01'
    await nextTick()
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['2026-08-01'])
  })

  it('把业务页面指定的浮层位置与回退位置透传给统一日期控件', () => {
    const wrapper = mountPicker(false, {
      placement: 'bottom-start',
      fallbackPlacements: ['bottom-start'],
    })
    const picker = wrapper.findComponent({ name: 'ElDatePicker' })
    expect(picker.props('placement')).toBe('bottom-start')
    expect(picker.props('fallbackPlacements')).toEqual(['bottom-start'])
  })
})
