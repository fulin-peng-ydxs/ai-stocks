// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, h } from 'vue'
import { afterEach, describe, expect, it } from 'vitest'
import RelatedBoardCell from '../RelatedBoardCell.vue'
import { useAuthStore } from '@/stores/auth'
import type {
  RelatedBoardConfidence,
  RelatedBoardWinner,
  StockRelatedBoards,
} from '@/types/relatedBoards'

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

const ElTagStub = defineComponent({
  name: 'ElTag',
  props: ['size', 'effect'],
  setup(props, { slots }) {
    return () => h('span', {
      class: 'tag-stub',
      'data-size': props.size,
      'data-effect': props.effect,
    }, slots.default?.())
  },
})

const RouterLinkStub = defineComponent({
  name: 'RouterLink',
  props: ['to'],
  setup(props, { slots, attrs }) {
    return () => h('a', {
      ...attrs,
      href: props.to,
      onClick: (event: MouseEvent) => {
        event.preventDefault()
        const listener = attrs.onClick
        if (Array.isArray(listener)) listener.forEach((item) => (item as (e: MouseEvent) => void)(event))
        else if (typeof listener === 'function') listener(event)
      },
    }, slots.default?.())
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

function summary(
  confidence: RelatedBoardConfidence,
  overrides: Partial<RelatedBoardWinner> = {},
): StockRelatedBoards {
  return {
    as_of_date: '2026-08-28',
    benchmark: { code: '000001.SH', name: '上证指数', fallback: false },
    industry: winner(confidence, overrides),
    concept: null,
  }
}

function mountCell(
  props: { summary?: StockRelatedBoards | null; boardType: 'industry' | 'concept'; testId?: string },
  role = 'normal',
  permissions: string[] = [],
) {
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
        ElTag: ElTagStub,
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
    const wrapper = mountCell({ summary: summary(confidence), boardType: 'industry' })

    expect(wrapper.text()).toContain('银行')
    expect(wrapper.text()).toContain('综合相关度0.8235')
    expect(wrapper.text()).toContain('20 日相关度0.8667')
    expect(wrapper.text()).toContain('60 日相关度0.7589')
    expect(wrapper.text()).toContain('20 日有效样本20')
    expect(wrapper.text()).toContain('60 日有效样本58')
    expect(wrapper.text()).not.toContain('有效样本指股票、板块与基准三方同日均有可计算收益')
    expect(wrapper.text()).toContain('数据截止日2026-08-28')
    expect(wrapper.text()).not.toContain('相关性较弱')
    expect(wrapper.getComponent(ElTagStub).props()).toMatchObject({
      size: 'small',
      effect: 'plain',
    })
    expect(wrapper.getComponent(ElPopoverStub).props('trigger')).toEqual(['hover', 'focus'])
    const reference = wrapper.get('.related-board-cell__name')
    expect(reference.attributes('tabindex')).toBe('0')
    ;(reference.element as HTMLElement).focus()
    expect(document.activeElement).toBe(reference.element)
  })

  it('低可信结果明确标记相关性较弱并安全处理非有限数', () => {
    const wrapper = mountCell({
      summary: { ...summary('low', { score: -0.123456, corr_20: Number.NaN }), as_of_date: '' },
      boardType: 'industry',
    })

    expect(wrapper.text()).toContain('相关性较弱')
    expect(wrapper.text()).toContain('综合相关度-0.1235')
    expect(wrapper.text()).toContain('20 日相关度—')
    expect(wrapper.text()).toContain('数据截止日—')
  })

  it('有 sectors:view 时渲染编码后的详情链接，system 角色也放行', () => {
    const allowed = mountCell(
      {
        summary: summary('high', { board_code: '概念/AI' }),
        boardType: 'industry',
        testId: 'related-board',
      },
      'normal',
      ['sectors:view'],
    )
    expect(allowed.get('a').attributes('href')).toBe('/sectors/%E6%A6%82%E5%BF%B5%2FAI')

    const system = mountCell({ summary: summary('medium'), boardType: 'industry' }, 'system')
    expect(system.find('a').exists()).toBe(true)
  })

  it('无 sectors:view 时只渲染可聚焦文本，不产生链接或权限错误入口', () => {
    const wrapper = mountCell(
      { summary: summary('high'), boardType: 'industry' },
      'normal',
      ['stocks:view'],
    )

    expect(wrapper.find('a').exists()).toBe(false)
    expect(wrapper.get('.related-board-cell__name').attributes('tabindex')).toBe('0')
    expect(wrapper.text()).toContain('银行')
  })

  it('无冠军显示普通破折号且不虚构说明', () => {
    const wrapper = mountCell({ summary: null, boardType: 'concept', testId: 'empty-related-board' })

    expect(wrapper.text()).toBe('—')
    expect(wrapper.find('.tooltip-stub').exists()).toBe(false)
    expect(wrapper.get('[data-testid="empty-related-board"]').attributes('aria-label')).toBe('暂无走势板块')
  })

  it('日期无结果与合法空结果统一只显示破折号', () => {
    const wrapper = mountCell({
      summary: { ...summary('high'), industry: null, unavailable_reason: 'as_of_mismatch' },
      boardType: 'industry',
    })

    expect(wrapper.text()).toBe('—')
    expect(wrapper.find('.tooltip-stub').exists()).toBe(false)
    expect(wrapper.get('.related-board-cell__empty').attributes('aria-label')).toBe('暂无走势板块')
  })

  it('首次计算任务创建后显示明确的计算中状态', () => {
    const wrapper = mountCell({
      summary: {
        ...summary('high'),
        as_of_date: null,
        industry: null,
        unavailable_reason: 'first_load_pending',
      },
      boardType: 'industry',
    })

    expect(wrapper.text()).toBe('计算中')
    expect(wrapper.get('.tooltip-stub').attributes('data-content')).toBe('首次计算正在等待或执行，完成后将自动刷新')
    expect(wrapper.get('.related-board-cell__empty').attributes('aria-label')).toBe('走势相关首次计算中')
  })

  it('点击板块链接不冒泡触发表格行点击', async () => {
    const wrapper = mountCell(
      { summary: summary('high'), boardType: 'industry' },
      'normal',
      ['sectors:view'],
    )
    let bubbled = 0
    wrapper.element.parentElement?.addEventListener('click', () => { bubbled += 1 })

    await wrapper.get('a').trigger('click')

    expect(bubbled).toBe(0)
  })
})
