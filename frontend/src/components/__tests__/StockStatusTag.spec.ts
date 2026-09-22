// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import StockStatusTag from '@/components/StockStatusTag.vue'

describe('StockStatusTag', () => {
  it('仅为明确 ST 状态显示带日期说明的危险标签', () => {
    const wrapper = mount(StockStatusTag, {
      props: { isSt: true, asOfDate: '2026-09-22' },
      global: { plugins: [ElementPlus] },
    })

    expect(wrapper.text()).toBe('ST')
    expect(wrapper.get('.el-tag').classes()).toContain('el-tag--danger')
    expect(wrapper.get('.stock-status-tag-shell').attributes('title')).toBe('截至 2026-09-22，该股票处于 ST 状态')
  })

  it('非 ST 不显示，未知仅在调用方明确允许降级时显示', async () => {
    const wrapper = mount(StockStatusTag, {
      props: { isSt: false },
      global: { plugins: [ElementPlus] },
    })
    expect(wrapper.find('.el-tag').exists()).toBe(false)

    await wrapper.setProps({ isSt: null, showUnknown: true, contextLabel: '买入日', asOfDate: '2026-08-01' })
    expect(wrapper.text()).toBe('ST状态未知')
    expect(wrapper.get('.stock-status-tag-shell').attributes('title')).toBe('买入日 2026-08-01，该股票的 ST 状态未知')
  })

  it('上层上下文已经明确为纯 ST 集合时隐藏重复标签，离开后恢复', async () => {
    const wrapper = mount(StockStatusTag, {
      props: { isSt: true, stOnlyContext: true },
      global: { plugins: [ElementPlus] },
    })

    expect(wrapper.find('.el-tag').exists()).toBe(false)

    await wrapper.setProps({ stOnlyContext: false })
    expect(wrapper.text()).toBe('ST')
  })
})
