// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ElementPlus from 'element-plus'
import StockGroupBatchActions from '@/components/StockGroupBatchActions.vue'

describe('StockGroupBatchActions', () => {
  it('共享展示选择结果，并支持逐个查看、移除单项和清空', async () => {
    const wrapper = mount(StockGroupBatchActions, {
      props: {
        modelValue: [
          { code: '000001.SZ', name: '平安银行' },
          { code: '000002.SZ', name: '万科A' },
        ],
        groups: [],
        'onUpdate:modelValue': (value) => wrapper.setProps({ modelValue: value }),
      },
      global: {
        plugins: [ElementPlus],
        directives: { permission: () => undefined },
      },
    })

    expect(wrapper.text()).toContain('已选 2 只')
    await wrapper.findAll('button').find(button => button.text() === '逐个查看')!.trigger('click')
    expect(wrapper.emitted('view')).toHaveLength(1)

    await wrapper.get('.el-tag__close').trigger('click')
    expect(wrapper.props('modelValue')).toHaveLength(1)
    await wrapper.get('.stock-batch-ops .is-text').trigger('click')
    expect(wrapper.props('modelValue')).toEqual([])
  })
})
