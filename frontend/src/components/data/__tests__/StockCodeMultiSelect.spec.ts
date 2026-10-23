// @vitest-environment jsdom
import { flushPromises, mount } from '@vue/test-utils'
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
    'ariaLabel', 'dataTestid', 'allowCreate',
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

function paste(wrapper: ReturnType<typeof mountSelect>, text: string) {
  const event = new Event('paste', { bubbles: true, cancelable: true })
  Object.defineProperty(event, 'clipboardData', { value: { getData: () => text } })
  wrapper.get('.select-stub').element.dispatchEvent(event)
  expect(event.defaultPrevented).toBe(true)
}

describe('StockCodeMultiSelect', () => {
  beforeEach(() => { vi.resetAllMocks() })
  it('仅指数搜索使用共享指数注册表，不请求股票候选', async () => {
    const wrapper = mountSelect()
    await wrapper.setProps({ assetType: 'index' })
    await wrapper.findComponent(ElSelectStub).props('remoteMethod')('上证')
    await wrapper.vm.$nextTick()
    expect(getStockQuality).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('000001.SH 上证指数')
  })

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

  it('搜索文本不能创建选项，只接受已有候选并支持清空', async () => {
    const wrapper = mountSelect(['600000.SH'])
    await wrapper.setProps({ assetType: 'all' })
    vi.mocked(getStockQuality).mockResolvedValue({ list: [] } as never)
    const select = wrapper.findComponent(ElSelectStub)
    await select.props('remoteMethod')('上')
    expect(select.props('allowCreate')).toBeFalsy()
    select.vm.$emit('update:modelValue', ['600000.sh', '上', ' 000001.sh ', '999999.SH'])
    await wrapper.vm.$nextTick()
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual([['600000.SH', '000001.SH']])
    select.vm.$emit('update:modelValue', [])
    expect(wrapper.emitted('change')?.[1]).toEqual([[]])
  })

  it('批量粘贴精确校验、规范大小写、去重并拒绝不存在的代码', async () => {
    vi.mocked(getStockQuality).mockResolvedValue({
      list: [{ code: '000001.SZ', name: '平安银行' }, { code: '300001.SZ', name: '特锐德' }],
    } as never)
    const wrapper = mountSelect(['600000.SH'])
    paste(wrapper, '000001.sz， 300001.SZ\n000001.SZ 999999.SH 上')
    await flushPromises()
    expect(getStockQuality).toHaveBeenCalledWith({
      codes: '000001.SZ,300001.SZ,999999.SH', size: 3,
    })
    expect(wrapper.emitted('change')?.[0]).toEqual([
      ['600000.SH', '000001.SZ', '300001.SZ'],
    ])
    expect(wrapper.get('[role="alert"]').text()).toContain('999999.SH、上')
    expect(wrapper.findComponent(ElSelectStub).props('loading')).toBe(false)
  })

  it('仅指数粘贴拒绝股票及未知指数，使用注册表而不查询股票接口', async () => {
    const wrapper = mountSelect()
    await wrapper.setProps({ assetType: 'index' })
    paste(wrapper, '000001.sh 000001.SZ 999999.SH')
    await flushPromises()
    expect(getStockQuality).not.toHaveBeenCalled()
    expect(wrapper.emitted('change')?.[0]).toEqual([['000001.SH']])
    // Element Plus 在更新已选值后会清空搜索，不能顺带抹掉无效粘贴提示。
    await wrapper.findComponent(ElSelectStub).props('remoteMethod')('')
    await wrapper.vm.$nextTick()
    expect(wrapper.get('[role="alert"]').text()).toContain('000001.SZ、999999.SH')
  })

  it('混合粘贴分别核实股票和指数，股票模式拒绝指数', async () => {
    vi.mocked(getStockQuality).mockResolvedValue({
      list: [{ code: '000001.SZ', name: '平安银行' }],
    } as never)
    const wrapper = mountSelect()
    await wrapper.setProps({ assetType: 'all' })
    paste(wrapper, '000001.SH,000001.SZ')
    await flushPromises()
    expect(wrapper.emitted('change')?.[0]).toEqual([['000001.SH', '000001.SZ']])
    await wrapper.setProps({ assetType: 'stock' })
    paste(wrapper, '000001.SH,000001.SZ')
    await flushPromises()
    expect(wrapper.emitted('change')?.[1]).toEqual([['000001.SZ']])
    expect(wrapper.get('[role="alert"]').text()).toContain('000001.SH')
  })

  it('校验失败不加入粘贴项且保留已选标的', async () => {
    vi.mocked(getStockQuality).mockRejectedValue(new Error('network down'))
    const wrapper = mountSelect(['600000.SH'])
    paste(wrapper, '000001.SZ,300001.SZ')
    await flushPromises()
    expect(wrapper.emitted('change')).toBeUndefined()
    expect(wrapper.text()).toContain('600000.SH')
    expect(wrapper.get('[role="alert"]').text()).toBe('标的校验失败，请重新粘贴')
    expect(wrapper.findComponent(ElSelectStub).props('loading')).toBe(false)
  })

  it.each(['clear', 'assetType', 'unmount', 'newPaste'])('旧粘贴响应在 %s 后失效', async (action) => {
    let resolve!: (value: never) => void
    vi.mocked(getStockQuality).mockReturnValueOnce(new Promise(r => { resolve = r }))
    const wrapper = mountSelect(['600000.SH'])
    paste(wrapper, '000001.SZ,300001.SZ')
    await wrapper.vm.$nextTick()
    expect(wrapper.findComponent(ElSelectStub).props('loading')).toBe(true)
    if (action === 'clear') await wrapper.setProps({ modelValue: [] })
    if (action === 'assetType') await wrapper.setProps({ assetType: 'index' })
    if (action === 'unmount') wrapper.unmount()
    if (action === 'newPaste') paste(wrapper, '无效,输入')
    resolve({ list: [{ code: '000001.SZ', name: '平安银行' }] } as never)
    await flushPromises()
    expect(wrapper.emitted('change')).toBeUndefined()
  })

  it('混合搜索的股票接口失败仍保留本地指数候选', async () => {
    vi.mocked(getStockQuality).mockRejectedValue(new Error('network down'))
    const wrapper = mountSelect()
    await wrapper.setProps({ assetType: 'all' })
    await wrapper.findComponent(ElSelectStub).props('remoteMethod')('上')
    expect(wrapper.text()).toContain('000001.SH 上证指数')
  })

  it('搜索失败保留控件并显示明确候选错误', async () => {
    vi.mocked(getStockQuality).mockRejectedValue(new Error('network down'))
    const wrapper = mountSelect(['600000.SH'])
    const select = wrapper.findComponent(ElSelectStub)

    await select.props('remoteMethod')('银行')
    await wrapper.vm.$nextTick()

    expect(wrapper.find('.select-stub').attributes('data-no-data-text')).toBe('股票候选加载失败')
    expect(wrapper.text()).toContain('600000.SH')
  })
})
