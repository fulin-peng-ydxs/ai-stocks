// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import AppSummaryDisclosureCard from '@/components/AppSummaryDisclosureCard.vue'
import { findOverflowTooltipTarget } from '@/components/overflow/overflowTooltip'

describe('AppSummaryDisclosureCard', () => {
  it('展开入口不触发重复的长摘要悬浮提示', () => {
    const wrapper = mount(AppSummaryDisclosureCard, {
      props: {
        panelId: 'summary-panel',
        indexLabel: '01',
        title: '规则名称',
        preview: '点击当前摘要卡即可展开并查看完整内容',
        toggleLabel: '展开规则',
        expanded: false,
      },
    })

    expect(wrapper.get('.app-summary-disclosure-card__summary')
      .attributes('data-overflow-tooltip-disabled')).toBe('')

    const preview = wrapper.get<HTMLElement>('.app-summary-disclosure-card__preview').element
    Object.defineProperty(preview, 'clientWidth', { value: 80, configurable: true })
    Object.defineProperty(preview, 'scrollWidth', { value: 240, configurable: true })
    expect(findOverflowTooltipTarget(preview)).toBeNull()
  })
})
