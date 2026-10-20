// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { defineComponent, h, KeepAlive, nextTick, ref } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import AppHoverInfo from '@/components/AppHoverInfo'
import ElementPlus from 'element-plus'

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

afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks() })

describe('AppHoverInfo', () => {
  it.each(['tooltip', 'popover'] as const)('%s 在分阶段布局通知后保留仍命中的静止鼠标意图', async (kind) => {
    vi.useFakeTimers()
    const descriptor = Object.getOwnPropertyDescriptor(document, 'elementFromPoint')
    const hitTest = vi.fn()
    Object.defineProperty(document, 'elementFromPoint', { configurable: true, value: hitTest })
    const wrapper = mount(AppHoverInfo, {
      attachTo: document.body,
      props: { kind },
      slots: kind === 'popover'
        ? { reference: () => h('span', { class: 'reference' }, 'i'), default: () => h('div', '归档详情') }
        : { default: () => h('span', { class: 'reference' }, '?') },
      global: { stubs: { ElTooltip: ElTooltipStub, ElPopover: ElPopoverStub } },
    })
    try {
      const reference = wrapper.get('.reference')
      hitTest.mockReturnValue(reference.element)
      const visible = () => wrapper.get(`.${kind}-stub`).attributes('data-visible')
      await reference.trigger('mouseenter', { clientX: 120, clientY: 257 })
      await vi.advanceTimersByTimeAsync(120)
      window.dispatchEvent(new Event('resize'))
      await vi.advanceTimersByTimeAsync(420)
      // 屏幕稳定通知晚于首次悬浮门槛，鼠标没有再次移动。
      window.dispatchEvent(new Event('resize'))
      await nextTick()
      expect(visible()).toBe('false')
      await vi.advanceTimersByTimeAsync(300)
      expect(visible()).toBe('true')
      expect(hitTest).toHaveBeenLastCalledWith(120, 257)

      hitTest.mockReturnValue(document.body)
      window.dispatchEvent(new Event('resize'))
      await vi.advanceTimersByTimeAsync(300)
      expect(visible()).toBe('false')

      hitTest.mockReturnValue(reference.element)
      await reference.trigger('mouseenter', { clientX: 120, clientY: 257 })
      window.dispatchEvent(new Event('blur'))
      window.dispatchEvent(new Event('resize'))
      await vi.advanceTimersByTimeAsync(300)
      expect(visible()).toBe('false')
    } finally {
      wrapper.unmount()
      if (descriptor) Object.defineProperty(document, 'elementFromPoint', descriptor)
      else Reflect.deleteProperty(document, 'elementFromPoint')
    }
  })

  it.each(['tooltip', 'popover'] as const)('%s 共用四向回退和双轴边界约束', (kind) => {
    const wrapper = mount(AppHoverInfo, {
      props: { kind },
      slots: kind === 'popover'
        ? { reference: () => h('span', 'i'), default: () => h('div', '详情') }
        : { default: () => h('span', '?') },
      global: { stubs: { ElTooltip: ElTooltipStub, ElPopover: ElPopoverStub } },
    })
    try {
      const floating = wrapper.getComponent(kind === 'popover' ? ElPopoverStub : ElTooltipStub)
      expect(floating.vm.$attrs.popperOptions).toEqual({ modifiers: [
        { name: 'flip', options: { fallbackPlacements: ['top-start', 'bottom-start', 'left-start', 'right-start'], padding: 12 } },
        { name: 'preventOverflow', options: { altAxis: true, tether: false, padding: 12 } },
      ] })
    } finally { wrapper.unmount() }
  })

  it.each(['tooltip', 'popover'] as const)('真实库 %s 在反复切屏后重新打开，ARIA 与实际浮层同步', async (kind) => {
    vi.useFakeTimers()
    const wrapper = mount(AppHoverInfo, {
      attachTo: document.body,
      props: { kind }, attrs: { content: '静态说明', transition: '' },
      slots: kind === 'popover'
        ? { reference: () => h('span', { class: 'reference', tabindex: 0 }, 'i'), default: () => h('div', '归档统计') }
        : { default: () => h('span', { class: 'reference', tabindex: 0 }, '?') },
      global: { plugins: [ElementPlus] },
    })
    try {
      const reference = wrapper.get('.reference')
      for (let cycle = 0; cycle < 3; cycle++) {
        await reference.trigger('mousemove')
        await vi.advanceTimersByTimeAsync(300)
        const id = reference.attributes('aria-describedby')
        expect(id).toBeTruthy()
        const floating = document.getElementById(id!)!
        expect(floating).not.toBeNull()
        expect(floating.style.display).not.toBe('none')
        window.dispatchEvent(new Event('resize'))
        await nextTick()
        await vi.advanceTimersByTimeAsync(0)
        expect(reference.attributes('aria-describedby')).toBeUndefined()
        expect(floating.style.display).toBe('none')
      }
    } finally { wrapper.unmount() }
  })

  it('多个说明入口共用一个尺寸监听，最后卸载时释放', () => {
    const add = vi.spyOn(window, 'addEventListener')
    const remove = vi.spyOn(window, 'removeEventListener')
    const wrapper = mount(defineComponent({
      setup: () => () => h('div', Array.from({ length: 12 }, (_, index) =>
        h(AppHoverInfo, { content: String(index) }, { default: () => h('span', '?') }))),
    }), { global: { stubs: { ElTooltip: ElTooltipStub } } })
    expect(add.mock.calls.filter(([name]) => name === 'resize')).toHaveLength(1)
    wrapper.unmount()
    expect(remove.mock.calls.filter(([name]) => name === 'resize')).toHaveLength(1)
  })

  it.each(['tooltip', 'popover'] as const)('布局变化取消 %s 待显示状态，原位置再次移动后可恢复', async (kind) => {
    vi.useFakeTimers()
    const wrapper = mount(AppHoverInfo, {
      props: { kind },
      slots: kind === 'popover'
        ? { reference: () => h('span', { class: 'reference' }, 'i'), default: () => h('div', { class: 'content' }, '归档详情') }
        : { default: () => h('span', { class: 'reference' }, '?') },
      global: { stubs: { ElTooltip: ElTooltipStub, ElPopover: ElPopoverStub } },
    })
    try {
      const reference = wrapper.get('.reference')
      const floating = () => wrapper.get(`.${kind}-stub`).attributes('data-visible')
      await reference.trigger('mouseenter')
      vi.advanceTimersByTime(200)
      window.dispatchEvent(new Event('resize'))
      vi.advanceTimersByTime(300)
      await nextTick()
      expect(floating()).toBe('false')
      // 切屏后指针可能仍在原触发点内，不要求先移出、失焦或重新点击。
      await reference.trigger('mousemove')
      vi.advanceTimersByTime(300)
      await nextTick()
      expect(floating()).toBe('true')
      if (kind === 'popover') await wrapper.get('.content').trigger('mouseenter')
      window.dispatchEvent(new Event('resize'))
      await nextTick()
      expect(floating()).toBe('false')
      await reference.trigger('mouseenter')
      vi.advanceTimersByTime(300)
      await nextTick()
      expect(floating()).toBe('true')
    } finally { wrapper.unmount() }
  })

  it.each(['blur', 'hidden'])('窗口离开（%s）清理已显示和待显示提示，恢复焦点不自动显示', async (reason) => {
    vi.useFakeTimers()
    const wrapper = mount(AppHoverInfo, {
      slots: { default: () => h('button', { class: 'reference' }, '展开工作区') },
      global: { stubs: { ElTooltip: ElTooltipStub } },
    })
    const reference = wrapper.get('.reference')
    const leaveWindow = () => {
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', altKey: true, bubbles: true }))
      if (reason === 'blur') window.dispatchEvent(new Event('blur'))
      else {
        vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden')
        document.dispatchEvent(new Event('visibilitychange'))
      }
    }
    await reference.trigger('mouseenter')
    leaveWindow()
    vi.advanceTimersByTime(300)
    await reference.trigger('focusin')
    expect(wrapper.get('.tooltip-stub').attributes('data-visible')).toBe('false')

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }))
    await reference.trigger('focusin')
    expect(wrapper.get('.tooltip-stub').attributes('data-visible')).toBe('true')
    leaveWindow()
    await nextTick()
    expect(wrapper.get('.tooltip-stub').attributes('data-visible')).toBe('false')
    await reference.trigger('focusin')
    expect(wrapper.get('.tooltip-stub').attributes('data-visible')).toBe('false')
    await reference.trigger('mouseenter')
    vi.advanceTimersByTime(300)
    await nextTick()
    expect(wrapper.get('.tooltip-stub').attributes('data-visible')).toBe('true')
    wrapper.unmount()
  })

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
