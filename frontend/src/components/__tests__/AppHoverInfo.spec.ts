// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { defineComponent, h, KeepAlive, nextTick, ref } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import AppHoverInfo from '@/components/AppHoverInfo'

const ElTooltipStub = defineComponent({
  name: 'ElTooltip',
  props: ['visible', 'content'],
  setup(props, { slots }) {
    return () => h('div', {
      class: 'tooltip-stub',
      'data-visible': String(props.visible),
    }, slots.default?.())
  },
})

const ElPopoverStub = defineComponent({
  name: 'ElPopover',
  props: ['visible'],
  setup(props, { slots }) {
    return () => h('div', {
      class: 'popover-stub',
      'data-visible': String(props.visible),
    }, [slots.reference?.(), slots.default?.()])
  },
})

afterEach(() => { vi.useRealTimers() })

describe('AppHoverInfo', () => {
  it('鼠标在目标内移动会重置计时，显示后移动会收起；键盘焦点立即显示', async () => {
    vi.useFakeTimers()
    const wrapper = mount(AppHoverInfo, {
      slots: { default: () => h('button', { class: 'reference' }, '说明') },
      global: { stubs: { ElTooltip: ElTooltipStub } },
    })
    const reference = wrapper.get('.reference')
    await reference.trigger('mouseenter')
    vi.advanceTimersByTime(200)
    await reference.trigger('mousemove')
    vi.advanceTimersByTime(299)
    await nextTick()
    expect(wrapper.get('.tooltip-stub').attributes('data-visible')).toBe('false')
    vi.advanceTimersByTime(1)
    await nextTick()
    expect(wrapper.get('.tooltip-stub').attributes('data-visible')).toBe('true')

    await reference.trigger('mousemove')
    expect(wrapper.get('.tooltip-stub').attributes('data-visible')).toBe('false')
    await reference.trigger('mouseleave')
    vi.advanceTimersByTime(300)
    await reference.trigger('focusin')
    expect(wrapper.get('.tooltip-stub').attributes('data-visible')).toBe('true')
    await reference.trigger('focusout')
    expect(wrapper.get('.tooltip-stub').attributes('data-visible')).toBe('false')
    wrapper.unmount()
  })

  it('富内容浮层允许鼠标从触发目标移入内容阅读', async () => {
    vi.useFakeTimers()
    const wrapper = mount(AppHoverInfo, {
      props: { kind: 'popover' },
      slots: {
        reference: () => h('button', { class: 'reference' }, '说明'),
        default: () => h('div', { class: 'content' }, '详细说明'),
      },
      global: { stubs: { ElPopover: ElPopoverStub } },
    })
    await wrapper.get('.reference').trigger('mouseenter')
    vi.advanceTimersByTime(300)
    await nextTick()
    expect(wrapper.get('.popover-stub').attributes('data-visible')).toBe('true')

    await wrapper.get('.reference').trigger('mouseleave')
    vi.advanceTimersByTime(100)
    await wrapper.get('.content').trigger('mouseenter')
    vi.advanceTimersByTime(180)
    await nextTick()
    expect(wrapper.get('.popover-stub').attributes('data-visible')).toBe('true')
    await wrapper.get('.content').trigger('mouseleave')
    expect(wrapper.get('.popover-stub').attributes('data-visible')).toBe('false')
    wrapper.unmount()
  })

  it('子链接阻止冒泡时也在点击阶段收起浮层', async () => {
    const wrapper = mount(AppHoverInfo, {
      props: { kind: 'popover' },
      slots: {
        reference: () => h('span', { class: 'reference' }, [
          h('a', {
            class: 'board-link',
            href: '/sectors/881001',
            onClick: (event: MouseEvent) => {
              event.preventDefault()
              event.stopPropagation()
            },
          }, '行业走势'),
        ]),
        default: () => h('div', '相关性说明'),
      },
      global: { stubs: { ElPopover: ElPopoverStub } },
    })

    await wrapper.get('.board-link').trigger('focusin')
    expect(wrapper.get('.popover-stub').attributes('data-visible')).toBe('true')
    await wrapper.get('.board-link').trigger('click')
    expect(wrapper.get('.popover-stub').attributes('data-visible')).toBe('false')
    wrapper.unmount()
  })

  it('禁用时取消待显示计时并收起已有提示', async () => {
    vi.useFakeTimers()
    const wrapper = mount(AppHoverInfo, {
      props: { disabled: false },
      slots: { default: () => h('span', { class: 'reference' }, '状态') },
      global: { stubs: { ElTooltip: ElTooltipStub } },
    })
    await wrapper.get('.reference').trigger('mouseenter')
    vi.advanceTimersByTime(300)
    await nextTick()
    expect(wrapper.get('.tooltip-stub').attributes('data-visible')).toBe('true')

    await wrapper.setProps({ disabled: true })
    expect(wrapper.get('.tooltip-stub').attributes('data-visible')).toBe('false')
    vi.advanceTimersByTime(300)
    expect(wrapper.get('.tooltip-stub').attributes('data-visible')).toBe('false')
    wrapper.unmount()
  })

  it('缓存页面切走再返回时收起已显示的浮层', async () => {
    const active = ref(true)
    const InfoPage = defineComponent({
      name: 'InfoPage',
      setup: () => () => h(AppHoverInfo, { kind: 'popover' }, {
        reference: () => h('a', { class: 'reference', href: '/sectors/881001' }, '行业走势'),
        default: () => h('div', '相关性说明'),
      }),
    })
    const OtherPage = defineComponent({ name: 'OtherPage', render: () => h('div', '板块详情') })
    const wrapper = mount(defineComponent({
      setup: () => () => h(KeepAlive, null, {
        default: () => active.value ? h(InfoPage) : h(OtherPage),
      }),
    }), { global: { stubs: { ElPopover: ElPopoverStub } } })

    await wrapper.get('.reference').trigger('focusin')
    expect(wrapper.get('.popover-stub').attributes('data-visible')).toBe('true')
    active.value = false
    await nextTick()
    active.value = true
    await nextTick()
    expect(wrapper.get('.popover-stub').attributes('data-visible')).toBe('false')
    wrapper.unmount()
  })
})
