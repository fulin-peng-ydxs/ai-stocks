// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, expect, it } from 'vitest'
import DataMetricCard from '../DataMetricCard.vue'
import DataMetricDetails from '../DataMetricDetails.vue'

describe('数据统计展示与操作分离', () => {
  it.each([
    { kind: 'help' as const, text: ' ' },
    { kind: 'details' as const, rows: [] },
  ])('没有有效说明时不生成空的悬浮入口（$kind）', (info) => {
    const wrapper = mount(DataMetricCard, {
      props: { label: '日线总行数', value: '0', info },
      global: { plugins: [ElementPlus] },
    })
    expect(wrapper.find('[role="button"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('卡片和详情入口不执行导航，只有具名操作触发事件', async () => {
    const wrapper = mount(DataMetricCard, {
      props: {
        label: '分时归档', value: '720', unit: '行', summary: '目标日完整 1 / 2 只',
        info: { kind: 'details', rows: [{ label: '累计缺失', value: '1 个股票交易日' }],
          notes: ['最新日期不代表全市场已采齐。'] }, actionLabel: '查看逐股覆盖',
      },
      global: { plugins: [ElementPlus] },
    })
    expect(wrapper.attributes('role')).toBeUndefined()
    expect(wrapper.text()).toContain('目标日完整 1 / 2 只')
    expect(wrapper.text()).not.toContain('累计缺失')
    await wrapper.trigger('click')
    const info = wrapper.get('[aria-label="分时归档统计详情"][tabindex="0"]')
    await info.trigger('click')
    expect(wrapper.emitted('action')).toBeUndefined()
    await wrapper.get('button').trigger('click')
    expect(wrapper.emitted('action')).toHaveLength(1)
    expect(wrapper.getComponent(DataMetricDetails).props('rows')).toEqual([{ label: '累计缺失', value: '1 个股票交易日' }])
    wrapper.unmount()
  })

  it('只读规模指标不生成空操作或整卡按钮', () => {
    const wrapper = mount(DataMetricCard, {
      props: { label: '日线总行数', value: '0', unit: '行', info: { kind: 'help', text: '已入库日线记录总数。' } },
      global: { plugins: [ElementPlus] },
    })
    expect(wrapper.find('button').exists()).toBe(false)
    expect(wrapper.text()).toContain('0')
    expect(wrapper.findComponent(DataMetricDetails).exists()).toBe(false)
    expect(wrapper.get('[aria-label="日线总行数口径说明"]').text()).toBe('?')
    wrapper.unmount()
  })
})
