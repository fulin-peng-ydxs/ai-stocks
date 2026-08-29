// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, h } from 'vue'
import { afterEach, describe, expect, it } from 'vitest'
import RelatedBoardCell from '../RelatedBoardCell.vue'
import { useAuthStore } from '@/stores/auth'
import type { RelatedBoardConfidence, RelatedBoardWinner } from '@/types/relatedBoards'

const ElPopoverStub = defineComponent({
  name: 'ElPopover',
  props: ['trigger', 'placement', 'width'],
  setup(_props, { slots }) {
    return () => h('div', { class: 'popover-stub' }, [
      h('div', { class: 'popover-reference' }, slots.reference?.()),
      h('div', { class: 'popover-content' }, slots.default?.()),
    ])
  },
})

const ElTooltipStub = defineComponent({
  name: 'ElTooltip',
  props: ['content', 'trigger', 'placement'],
  setup(props, { slots }) {
    return () => h('div', { class: 'tooltip-stub', 'data-content': props.content }, slots.default?.())
  },
})

const RouterLinkStub = defineComponent({
  name: 'RouterLink',
  props: ['to'],
  setup(props, { slots, attrs }) {
    return () => h('a', { ...attrs, href: props.to }, slots.default?.())
  },
})

const wrappers: Array<{ unmount: () => void }> = []

function winner(confidence: RelatedBoardConfidence, overrides: Partial<RelatedBoardWinner> = {}): RelatedBoardWinner {
  return {
    board_code: '881001',
    name: '银行',
    score: 0.823456,
    corr_20: 0.866666,
    corr_60: 0.758888,
    sample_20: 20,
    sample_60: 58,
    confidence,
    ...overrides,
  }
}

function mountCell(props: Record<string, unknown>, role = 'normal', permissions: string[] = []) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.role = role
  auth.permissions = permissions
  const wrapper = mount(RelatedBoardCell, {
    props,
    global: {
      plugins: [pinia],
      stubs: {
        ElPopover: ElPopoverStub,
        ElTooltip: ElTooltipStub,
        RouterLink: RouterLinkStub,
      },
    },
    attachTo: document.body,
  })
  wrappers.push(wrapper)
  return wrapper
}

describe('RelatedBoardCell', () => {
  afterEach(() => {
    for (const wrapper of wrappers.splice(0)) wrapper.unmount()
    document.body.innerHTML = ''
  })

  it.each(['high', 'medium'] as const)('%s 可信结果展示完整指标且不误标低可信', (confidence) => {
    const wrapper = mountCell({ board: winner(confidence), asOfDate: '2026-08-28' })

    expect(wrapper.text()).toContain('银行')
    expect(wrapper.text()).toContain('综合相关度0.8235')
    expect(wrapper.text()).toContain('20 日相关度0.8667')
    expect(wrapper.text()).toContain('60 日相关度0.7589')
    expect(wrapper.text()).toContain('20 日样本20')
    expect(wrapper.text()).toContain('60 日样本58')
    expect(wrapper.text()).toContain('数据截止日2026-08-28')
    expect(wrapper.text()).not.toContain('相关性较弱')
    expect(wrapper.getComponent(ElPopoverStub).props('trigger')).toEqual(['hover', 'focus'])
    const reference = wrapper.get('.related-board-cell__name')
    expect(reference.attributes('tabindex')).toBe('0')
    ;(reference.element as HTMLElement).focus()
    expect(document.activeElement).toBe(reference.element)
  })

  it('低可信结果明确标记相关性较弱并安全处理非有限数', () => {
    const wrapper = mountCell({
      board: winner('low', { score: -0.123456, corr_20: Number.NaN }),
      asOfDate: null,
    })

    expect(wrapper.text()).toContain('相关性较弱')
    expect(wrapper.text()).toContain('综合相关度-0.1235')
    expect(wrapper.text()).toContain('20 日相关度—')
    expect(wrapper.text()).toContain('数据截止日—')
  })

  it('有 sectors:view 时渲染编码后的详情链接，system 角色也放行', () => {
    const allowed = mountCell(
      { board: winner('high', { board_code: '概念/AI' }), testId: 'related-board' },
      'normal',
      ['sectors:view'],
    )
    expect(allowed.get('a').attributes('href')).toBe('/sectors/%E6%A6%82%E5%BF%B5%2FAI')

    const system = mountCell({ board: winner('medium') }, 'system')
    expect(system.find('a').exists()).toBe(true)
  })

  it('无 sectors:view 时只渲染可聚焦文本，不产生链接或权限错误入口', () => {
    const wrapper = mountCell({ board: winner('high') }, 'normal', ['stocks:view'])

    expect(wrapper.find('a').exists()).toBe(false)
    expect(wrapper.get('.related-board-cell__name').attributes('tabindex')).toBe('0')
    expect(wrapper.text()).toContain('银行')
  })

  it('无冠军显示普通破折号且不虚构说明', () => {
    const wrapper = mountCell({ board: null, testId: 'empty-related-board' })

    expect(wrapper.text()).toBe('—')
    expect(wrapper.find('.tooltip-stub').exists()).toBe(false)
    expect(wrapper.get('[data-testid="empty-related-board"]').attributes('aria-label')).toBe('暂无走势板块')
  })

  it('历史日期不匹配仍显示破折号，但提供可聚焦的固定说明', () => {
    const wrapper = mountCell({ board: null, unavailableReason: 'as_of_mismatch' })

    expect(wrapper.text()).toBe('—')
    expect(wrapper.get('.tooltip-stub').attributes('data-content')).toBe('未保留该历史日期的相关性结果')
    expect(wrapper.get('.related-board-cell__empty').attributes('tabindex')).toBe('0')
    expect(wrapper.getComponent(ElTooltipStub).props('trigger')).toEqual(['hover', 'focus'])
    ;(wrapper.get('.related-board-cell__empty').element as HTMLElement).focus()
    expect(document.activeElement).toBe(wrapper.get('.related-board-cell__empty').element)
  })
})
