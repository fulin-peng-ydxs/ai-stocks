// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import StockCodeMultiSelect from '../StockCodeMultiSelect.vue'
import { getStockQuality } from '@/api/data'

vi.mock('@/api/data', () => ({ getStockQuality: vi.fn() }))

const ElSelectStub = defineComponent({
  name: 'ElSelect',
  inheritAttrs: false,
  props: [
    'modelValue', 'remoteMethod', 'loading', 'noDataText', 'placeholder',
    'ariaLabel', 'dataTestid',
  ],
  emits: ['update:modelValue'],
  setup(props, { attrs, slots }) {
    return () => h('div', {
      ...attrs,
      class: 'select-stub',
      'data-no-data-text': props.noDataText,
      'data-loading': String(props.loading),
    }, slots.default?.())
  },
})

const ElOptionStub = defineComponent({
  name: 'ElOption',
  props: ['label', 'value'],
  setup(props) {
    return () => h('span', { class: 'option-stub', 'data-value': props.value }, props.label)
  },
})

function mountSelect(modelValue: string[] = []) {
  return mount(StockCodeMultiSelect, {
    props: { modelValue, testId: 'stock-codes' },
    global: { stubs: { ElSelect: ElSelectStub, ElOption: ElOptionStub } },
  })
}

describe('StockCodeMultiSelect', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('远程搜索展示代码名称并保留已选代码', async () => {
    vi.mocked(getStockQuality).mockResolvedValue({
      list: [{ code: '000001.SZ', name: '平安银行' }],
      total: 1,
    } as never)
    const wrapper = mountSelect(['600000.SH'])
    const select = wrapper.findComponent(ElSelectStub)

    await select.props('remoteMethod')('平安')
    await wrapper.vm.$nextTick()

    expect(getStockQuality).toHaveBeenCalledWith({ keyword: '平安', size: 30 })
    expect(wrapper.text()).toContain('600000.SH')
    expect(wrapper.text()).toContain('000001.SZ 平安银行')
  })

  it('选择和批量粘贴统一转大写、去空并稳定去重', async () => {
    const wrapper = mountSelect(['600000.SH'])
    const select = wrapper.findComponent(ElSelectStub)
    select.vm.$emit('update:modelValue', ['600000.sh', ' 000001.sz ', '600000.SH'])
    await wrapper.vm.$nextTick()
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual([['600000.SH', '000001.SZ']])

    const pasteEvent = new Event('paste', { bubbles: true, cancelable: true })
    Object.defineProperty(pasteEvent, 'clipboardData', {
      value: { getData: () => '000001.sz， 300001.SZ\n600000.sh' },
    })
    const preventDefault = vi.spyOn(pasteEvent, 'preventDefault')
    wrapper.find('.stock-code-multi-select').element.dispatchEvent(pasteEvent)
    await wrapper.vm.$nextTick()
    expect(preventDefault).toHaveBeenCalled()
    expect(wrapper.emitted('update:modelValue')?.[1]).toEqual([
      ['600000.SH', '000001.SZ', '300001.SZ'],
    ])
    expect(wrapper.emitted('change')?.[1]).toEqual([
      ['600000.SH', '000001.SZ', '300001.SZ'],
    ])
  })

  it('搜索失败保留控件并显示明确候选错误', async () => {
    vi.mocked(getStockQuality).mockRejectedValue(new Error('network down'))
    const wrapper = mountSelect(['600000.SH'])
    const select = wrapper.findComponent(ElSelectStub)

    await select.props('remoteMethod')('银行')
    await wrapper.vm.$nextTick()

    expect(wrapper.find('.select-stub').attributes('data-no-data-text')).toContain('network down')
    expect(wrapper.text()).toContain('600000.SH')
  })
})
