// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import MarketAnalysisHeader from '@/components/MarketAnalysisHeader.vue'

describe('MarketAnalysisHeader', () => {
  it('统一承载行情对象、详情入口、说明和响应式控制区', async () => {
    const wrapper = mount(MarketAnalysisHeader, {
      props: {
        title: '平安银行',
        code: '000001.SZ',
        detailVisible: true,
        titleTestId: 'analysis-title',
        detailTestId: 'analysis-detail',
      },
      slots: {
        description: '<span>区间走势说明</span>',
        controls: '<button class="test-control">切换模式</button>',
      },
      global: { plugins: [ElementPlus] },
    })

    expect(wrapper.get('[data-testid="analysis-title"]').text()).toBe('平安银行')
    expect(wrapper.text()).toContain('000001.SZ')
    expect(wrapper.get('.market-analysis-header__description').text()).toBe('区间走势说明')
    expect(wrapper.get('.market-analysis-header__controls').text()).toBe('切换模式')
    await wrapper.get('[data-testid="analysis-detail"]').trigger('click')
    expect(wrapper.emitted('openDetail')).toHaveLength(1)
  })
})
