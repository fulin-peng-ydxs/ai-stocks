// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ElementPlus from 'element-plus'
import MarketMasterDetailWorkspace from '@/components/MarketMasterDetailWorkspace.vue'

describe('MarketMasterDetailWorkspace', () => {
  it('compact 模式只渲染列表并隐藏无效的分析收展入口', () => {
    const wrapper = mount(MarketMasterDetailWorkspace, {
      props: {
        analysisVisible: true,
        compact: true,
        eyebrow: 'TEST',
        title: '测试列表',
      },
      slots: {
        list: '<div data-testid="list-slot">列表</div>',
        analysis: '<div data-testid="analysis-slot">分析</div>',
      },
      global: { plugins: [ElementPlus] },
    })

    expect(wrapper.get('[data-testid="list-slot"]').text()).toBe('列表')
    expect(wrapper.find('[data-testid="analysis-slot"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="market-hide-analysis"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="market-show-analysis"]').exists()).toBe(false)
    expect(wrapper.classes()).toContain('market-master-detail--list-only')
  })
})
