// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import RuleMasterList from '@/views/trade-discipline/components/RuleMasterList.vue'
import type { TradeDisciplineRule } from '@/api/tradeDiscipline'

const rules: TradeDisciplineRule[] = [
  {
    id: 'rule-1', name: '趋势突破', proposed_name: '趋势突破-草稿', status: 'active',
    latest_version_no: 2, draft_revision: 3, management_status: 'active',
    latest_management_event: null, has_pending_management_action: false,
    effective_status: 'active', effective_event_seq: 2,
    effective_from_trade_date: '2026-08-21',
    effective_version: { version_no: 2, name: '趋势突破', capital: '100000' },
  },
]

describe('RuleMasterList', () => {
  it('展示正式/草稿双状态并支持键盘选择', async () => {
    const wrapper = mount(RuleMasterList, {
      props: { rules, selectedId: '', canManage: true },
      global: { plugins: [ElementPlus], directives: { permission: {} } },
    })
    expect(wrapper.text()).toContain('当前 v2')
    expect(wrapper.text()).toContain('有编辑中草稿')
    await wrapper.get('[role="option"]').trigger('keydown.enter')
    expect(wrapper.emitted('select')?.[0]).toEqual(['rule-1'])
  })

  it('搜索无结果显示局部空态且新建命令保持可用', async () => {
    const wrapper = mount(RuleMasterList, {
      props: { rules, selectedId: 'rule-1', canManage: true },
      global: { plugins: [ElementPlus], directives: { permission: {} } },
    })
    await wrapper.get('input').setValue('不存在')
    await new Promise((resolve) => window.setTimeout(resolve, 320))
    expect(wrapper.text()).toContain('没有匹配的规则')
    await wrapper.get('[aria-label="新建规则"]').trigger('click')
    expect(wrapper.emitted('create')).toHaveLength(1)
  })
})
