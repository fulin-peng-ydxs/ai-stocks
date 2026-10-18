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

  it('紧凑模式复用原生展开入口，支持状态前缀且不强加序号', async () => {
    const wrapper = mount(AppSummaryDisclosureCard, {
      props: {
        panelId: 'check-detail', title: '检查项', toggleLabel: '展开检查项',
        expanded: false, variant: 'compact',
      },
      slots: { leading: '<span>提醒</span>', default: '<p>对象明细</p>' },
    })
    const trigger = wrapper.get('button')
    expect(trigger.attributes('aria-controls')).toBe('check-detail')
    expect(trigger.attributes('aria-expanded')).toBe('false')
    expect(wrapper.find('.app-summary-disclosure-card__index').exists()).toBe(false)
    expect(wrapper.find('#check-detail').exists()).toBe(false)
    await trigger.trigger('click')
    expect(wrapper.emitted('toggle')).toHaveLength(1)
    await wrapper.setProps({ expanded: true })
    expect(wrapper.get('#check-detail').text()).toBe('对象明细')
  })

  it.each([true, false])('紧凑行保留完整摘要并允许真实截断提示，collapsible=%s', (collapsible) => {
    const previewText = '全历史异常 0 行；近90交易日台账范围 0 行'
    const wrapper = mount(AppSummaryDisclosureCard, {
      props: {
        panelId: 'compact-summary', title: '市值关系', preview: previewText,
        toggleLabel: '展开市值关系', expanded: false, variant: 'compact', collapsible,
      },
    })
    expect(wrapper.get('.app-summary-disclosure-card__summary').attributes('data-overflow-tooltip-disabled')).toBeUndefined()
    const preview = wrapper.get<HTMLElement>('.app-summary-disclosure-card__preview').element
    expect(preview.textContent?.trim()).toBe(previewText)
    preview.style.textOverflow = 'ellipsis'
    Object.defineProperty(preview, 'clientWidth', { value: 100, configurable: true })
    Object.defineProperty(preview, 'scrollWidth', { value: 300, configurable: true })
    expect(findOverflowTooltipTarget(preview)).toBe(preview)
    Object.defineProperty(preview, 'clientWidth', { value: 400, configurable: true })
    expect(findOverflowTooltipTarget(preview)).toBeNull()
  })

  it('无需明细的静态行保留同一摘要结构，不提供无效按钮或切换事件', async () => {
    const wrapper = mount(AppSummaryDisclosureCard, {
      props: {
        panelId: 'static-check', title: '已通过', toggleLabel: '已通过',
        expanded: false, variant: 'compact', collapsible: false,
      },
    })
    expect(wrapper.find('button').exists()).toBe(false)
    const summary = wrapper.get('.app-summary-disclosure-card__summary')
    expect(summary.attributes('aria-controls')).toBeUndefined()
    await summary.trigger('click')
    expect(wrapper.emitted('toggle')).toBeUndefined()
  })
})
