// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, expect, it } from 'vitest'
import MarketCompareMetricStrip from '@/components/MarketCompareMetricStrip.vue'

// CSS 紧凑态由真实浏览器验证；这里检查收起数值后的信息恢复及切换契约。
describe('MarketCompareMetricStrip', () => {
  it('辅助值提供完整提示，复合值保留原有分隔，选中态仍由消费方控制', async () => {
    const wrapper = mount(MarketCompareMetricStrip, {
      props: {
        items: [
          { key: 'growth', label: '5日涨幅', value: '+2.66%' },
          { key: 'members', label: '成员涨/跌', value: '50 / 2', parts: [
            { text: '50', tone: 'up' }, { text: '/', tone: 'muted' }, { text: '2', tone: 'down' },
          ] },
        ],
        activeKey: 'growth', ariaLabel: '板块对比指标', testIdPrefix: 'metrics',
      },
      global: { plugins: [ElementPlus] },
    })
    const growth = wrapper.get('[data-testid="metrics-growth"]')
    const members = wrapper.get('[data-testid="metrics-members"]')
    expect(growth.attributes('title')).toBe('5日涨幅：+2.66%')
    expect(members.attributes('title')).toBe('成员涨/跌：50 / 2')
    await members.trigger('mouseenter')
    expect(wrapper.emitted('select')).toBeUndefined()
    const memberButton = members.element as HTMLButtonElement
    memberButton.disabled = true
    await members.trigger('click')
    expect(wrapper.emitted('select')).toBeUndefined()
    memberButton.disabled = false
    await members.trigger('click')
    expect(wrapper.emitted('select')).toEqual([['members']])
    expect(growth.attributes('aria-pressed')).toBe('true')
    await wrapper.setProps({ activeKey: 'members' })
    expect(members.attributes('aria-pressed')).toBe('true')
    expect(members.classes()).toContain('is-selected')
    wrapper.unmount()
  })
})
