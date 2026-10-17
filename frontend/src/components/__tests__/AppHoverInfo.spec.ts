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
    expect(wrapper.find('.tooltip-stub').exists()).toBe(false)
    vi.advanceTimersByTime(300)
    expect(wrapper.find('.tooltip-stub').exists()).toBe(false)
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
  it('虚拟锚点复用同一停留与焦点规则，替换锚点和卸载时释放监听', async () => {
    vi.useFakeTimers()
    const first = document.createElement('button')
    const second = document.createElement('button')
    document.body.append(first, second)
    const remove = vi.spyOn(first, 'removeEventListener')
    const wrapper = mount(AppHoverInfo, {
      props: { reference: first },
      attrs: { content: '页面设置' },
      global: { stubs: { ElTooltip: ElTooltipStub } },
    })
    first.dispatchEvent(new MouseEvent('mouseenter'))
    vi.advanceTimersByTime(300)
    await nextTick()
    expect(wrapper.get('.tooltip-stub').attributes('data-visible')).toBe('true')
    first.dispatchEvent(new Event('pointerdown'))
    first.dispatchEvent(new FocusEvent('focusin'))
    await nextTick()
    expect(wrapper.get('.tooltip-stub').attributes('data-visible')).toBe('false')
    first.dispatchEvent(new MouseEvent('click'))
    first.dispatchEvent(new FocusEvent('focusout'))
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }))
    first.dispatchEvent(new FocusEvent('focusin'))
    await nextTick()
    expect(wrapper.get('.tooltip-stub').attributes('data-visible')).toBe('true')
    first.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await nextTick()
    expect(wrapper.get('.tooltip-stub').attributes('data-visible')).toBe('false')
    await wrapper.setProps({ reference: second })
    expect(remove).toHaveBeenCalledTimes(8)
    first.dispatchEvent(new MouseEvent('mouseenter'))
    vi.advanceTimersByTime(300)
    await nextTick()
    expect(wrapper.get('.tooltip-stub').attributes('data-visible')).toBe('false')
    second.dispatchEvent(new MouseEvent('mouseenter'))
    wrapper.unmount()
    vi.advanceTimersByTime(300)
    first.remove()
    second.remove()
  })

  it('鼠标操作其他入口后归还焦点不锁定提示，Tab 焦点仍立即显示', async () => {
    const anchor = document.createElement('button')
    const close = document.createElement('button')
    document.body.append(anchor, close)
    const wrapper = mount(AppHoverInfo, { props: { reference: anchor }, attrs: { content: '页面设置' }, global: { stubs: { ElTooltip: ElTooltipStub } } })
    close.dispatchEvent(new Event('pointerdown', { bubbles: true }))
    anchor.dispatchEvent(new FocusEvent('focusin'))
    await nextTick()
    expect(wrapper.get('.tooltip-stub').attributes('data-visible')).toBe('false')
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }))
    anchor.dispatchEvent(new FocusEvent('focusin'))
    await nextTick()
    expect(wrapper.get('.tooltip-stub').attributes('data-visible')).toBe('true')
    wrapper.unmount()
    anchor.remove()
    close.remove()
  })

})
