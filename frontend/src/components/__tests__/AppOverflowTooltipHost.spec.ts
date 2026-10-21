// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { defineComponent, h, nextTick } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import AppOverflowTooltipHost from '@/components/AppOverflowTooltipHost.vue'
import AppSummaryDisclosureCard from '@/components/AppSummaryDisclosureCard.vue'

const ElTooltipStub = defineComponent({
  name: 'ElTooltip',
  props: ['visible', 'content', 'virtualRef', 'popperClass'],
  setup(props, { slots }) {
    return () => h('div', {
      class: 'tooltip-host',
      'data-visible': String(props.visible),
      'data-content': props.content,
      'data-target': props.virtualRef?.id,
      'data-popper-class': props.popperClass,
    }, slots.content?.())
  },
})

function appendOverflowTarget(id: string, title = '完整内容'): HTMLElement {
  const target = document.createElement('span')
  target.id = id
  target.dataset.overflowTooltipContent = title
  target.textContent = title
  target.style.textOverflow = 'ellipsis'
  target.style.overflow = 'hidden'
  Object.defineProperty(target, 'clientWidth', { value: 40 })
  Object.defineProperty(target, 'scrollWidth', { value: 100 })
  document.body.append(target)
  return target
}

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
  document.body.innerHTML = ''
})

describe('AppOverflowTooltipHost', () => {
  it('没有裁切的内容不会在停留或键盘聚焦时弹出，真实裁切后恢复提示', async () => {
    vi.useFakeTimers()
    const wrapper = mount(AppOverflowTooltipHost, {
      attachTo: document.body,
      global: { stubs: { ElTooltip: ElTooltipStub } },
    })
    const target = appendOverflowTarget('visible-overflow', '完整可见的文字')
    target.style.overflow = 'visible'
    target.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }))
    await vi.advanceTimersByTimeAsync(300)
    target.dispatchEvent(new FocusEvent('focusin', { bubbles: true }))
    await nextTick()
    expect(wrapper.find('.tooltip-host').exists()).toBe(false)

    target.style.overflow = 'hidden'
    target.dispatchEvent(new MouseEvent('mousemove', { bubbles: true }))
    await vi.advanceTimersByTimeAsync(300)
    expect(wrapper.get('.tooltip-host').attributes('data-content')).toBe('完整可见的文字')
    wrapper.unmount()
  })

  it('分阶段布局后静止鼠标仍能显示；截断消失或失焦后不恢复', async () => {
    vi.useFakeTimers()
    const descriptor = Object.getOwnPropertyDescriptor(document, 'elementFromPoint')
    const hitTest = vi.fn()
    Object.defineProperty(document, 'elementFromPoint', { configurable: true, value: hitTest })
    const wrapper = mount(AppOverflowTooltipHost, {
      attachTo: document.body, global: { stubs: { ElTooltip: ElTooltipStub } },
    })
    const target = appendOverflowTarget('layout-hover')
    hitTest.mockReturnValue(target)
    try {
      target.dispatchEvent(new MouseEvent('mousemove', { bubbles: true, clientX: 80, clientY: 100 }))
      await vi.advanceTimersByTimeAsync(120)
      window.dispatchEvent(new Event('resize'))
      await vi.advanceTimersByTimeAsync(420)
      window.dispatchEvent(new Event('resize'))
      await vi.advanceTimersByTimeAsync(300)
      expect(wrapper.get('.tooltip-host').attributes('data-visible')).toBe('true')
      hitTest.mockReturnValue(document.body)
      window.dispatchEvent(new Event('resize'))
      await vi.advanceTimersByTimeAsync(300)
      expect(wrapper.find('.tooltip-host').exists()).toBe(false)
      hitTest.mockReturnValue(target)
      target.dispatchEvent(new MouseEvent('mousemove', { bubbles: true }))
      window.dispatchEvent(new Event('blur'))
      window.dispatchEvent(new Event('resize'))
      await vi.advanceTimersByTimeAsync(300)
      expect(wrapper.find('.tooltip-host').exists()).toBe(false)
    } finally {
      wrapper.unmount()
      if (descriptor) Object.defineProperty(document, 'elementFromPoint', descriptor)
      else Reflect.deleteProperty(document, 'elementFromPoint')
    }
  })

  it.each(['首次移动', '点击', '窗口失焦', 'Escape'])('%s 后无需移出文字再移入也能重新悬浮', async (action) => {
    vi.useFakeTimers()
    const wrapper = mount(AppOverflowTooltipHost, {
      attachTo: document.body,
      global: { stubs: { ElTooltip: ElTooltipStub } },
    })
    const target = appendOverflowTarget('resume-hover', '有标记无数据 0 / 有数据无标记 0')
    if (action !== '首次移动') {
      target.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }))
      vi.advanceTimersByTime(300)
      await nextTick()
      expect(wrapper.get('.tooltip-host').attributes('data-visible')).toBe('true')
      if (action === '点击') target.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      if (action === '窗口失焦') {
        window.dispatchEvent(new Event('blur'))
        window.dispatchEvent(new Event('focus'))
      }
      if (action === 'Escape') document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
      await nextTick()
      expect(wrapper.find('.tooltip-host').exists()).toBe(false)
    }
    // 鼠标一直位于同一文字节点内时只产生 mousemove，不会再产生 mouseover。
    target.dispatchEvent(new MouseEvent('mousemove', { bubbles: true }))
    vi.advanceTimersByTime(299)
    await nextTick()
    expect(wrapper.find('.tooltip-host').exists()).toBe(false)
    vi.advanceTimersByTime(1)
    await nextTick()
    expect(wrapper.get('.tooltip-host').attributes('data-content')).toBe(target.textContent)
    wrapper.unmount()
  })

  it.each([true, false])('紧凑检查行按截断文字分别提示，留白不触发，collapsible=%s', async (collapsible) => {
    vi.useFakeTimers()
    const wrapper = mount(defineComponent({
      setup: () => () => h('div', [
        h(AppOverflowTooltipHost),
        h(AppSummaryDisclosureCard, {
          panelId: 'check-detail', title: '完整检查名称', toggleLabel: '展开检查',
          preview: '有标记无数据 0 / 有数据无标记 0',
          variant: 'compact', expanded: false, collapsible,
        }),
      ]),
    }), {
      attachTo: document.body,
      global: { stubs: { ElTooltip: ElTooltipStub } },
    })
    const host = wrapper.getComponent(AppOverflowTooltipHost)
    const card = wrapper.getComponent(AppSummaryDisclosureCard)
    const summary = card.get('.app-summary-disclosure-card__summary')
    const title = card.get<HTMLElement>('strong')
    const preview = card.get<HTMLElement>('.app-summary-disclosure-card__preview')
    // 标题与摘要是独立阅读目标，不能把整行留白代理成任意一段文字。
    for (const target of [title.element, preview.element]) {
      target.style.textOverflow = 'ellipsis'
      target.style.overflow = 'hidden'
      Object.defineProperty(target, 'clientWidth', { value: 40, configurable: true })
      Object.defineProperty(target, 'scrollWidth', { value: 200 })
    }
    await summary.trigger('mouseover')
    vi.advanceTimersByTime(300)
    await nextTick()
    expect(host.find('.tooltip-host').exists()).toBe(false)
    await preview.trigger('mousemove')
    vi.advanceTimersByTime(300)
    await nextTick()
    expect(host.get('.tooltip-host').attributes('data-content')).toBe('有标记无数据 0 / 有数据无标记 0')
    await preview.trigger('click')
    await preview.trigger('mousemove')
    vi.advanceTimersByTime(300)
    await nextTick()
    expect(host.get('.tooltip-host').attributes('data-content')).toBe('有标记无数据 0 / 有数据无标记 0')
    await preview.trigger('mouseout')
    await title.trigger('mouseover')
    vi.advanceTimersByTime(300)
    await nextTick()
    expect(host.get('.tooltip-host').attributes('data-content')).toBe('完整检查名称')
    await title.trigger('mouseout')
    Object.defineProperty(preview.element, 'clientWidth', { value: 240 })
    await preview.trigger('mousemove')
    vi.advanceTimersByTime(300)
    await nextTick()
    expect(host.find('.tooltip-host').exists()).toBe(false)
    await summary.trigger('mousemove')
    vi.advanceTimersByTime(300)
    await nextTick()
    expect(host.find('.tooltip-host').exists()).toBe(false)
    wrapper.unmount()
  })

  it('窗口失焦清理省略提示及计时，恢复焦点不弹出，重新 Tab 阅读正常', async () => {
    vi.useFakeTimers()
    const wrapper = mount(AppOverflowTooltipHost, {
      attachTo: document.body,
      global: { stubs: { ElTooltip: ElTooltipStub } },
    })
    const target = appendOverflowTarget('window-return')
    target.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }))
    window.dispatchEvent(new Event('blur'))
    vi.advanceTimersByTime(300)
    target.dispatchEvent(new FocusEvent('focusin', { bubbles: true }))
    await nextTick()
    expect(wrapper.find('.tooltip-host').exists()).toBe(false)
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }))
    target.dispatchEvent(new FocusEvent('focusin', { bubbles: true }))
    await nextTick()
    expect(wrapper.get('.tooltip-host').attributes('data-visible')).toBe('true')
    window.dispatchEvent(new Event('blur'))
    await nextTick()
    expect(wrapper.find('.tooltip-host').exists()).toBe(false)
    wrapper.unmount()
  })

  it('点击产生的焦点不锁定提示，阻止冒泡也能清理，Tab 焦点仍显示', async () => {
    vi.useFakeTimers()
    const wrapper = mount(AppOverflowTooltipHost, {
      attachTo: document.body,
      global: { stubs: { ElTooltip: ElTooltipStub } },
    })
    const button = document.createElement('button')
    button.textContent = '用户列表：收起下级分组'
    button.style.textOverflow = 'ellipsis'
    button.style.overflow = 'hidden'
    Object.defineProperty(button, 'clientWidth', { value: 40 })
    Object.defineProperty(button, 'scrollWidth', { value: 100 })
    document.body.append(button)
    button.addEventListener('pointerdown', (event) => event.stopPropagation())
    button.addEventListener('click', (event) => event.stopPropagation())

    button.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }))
    vi.advanceTimersByTime(300)
    await nextTick()
    expect(wrapper.get('.tooltip-host').attributes('data-visible')).toBe('true')

    button.dispatchEvent(new Event('pointerdown', { bubbles: true }))
    button.focus()
    button.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    button.dispatchEvent(new MouseEvent('mouseout', { bubbles: true }))
    vi.advanceTimersByTime(300)
    await nextTick()
    expect(document.activeElement).toBe(button)
    expect(wrapper.find('.tooltip-host').exists()).toBe(false)
    expect(button.textContent).toBe('用户列表：收起下级分组')

    // 再次悬停仍按停留门槛显示，点击焦点不阻止鼠标移开后的清理。
    button.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }))
    vi.advanceTimersByTime(300)
    await nextTick()
    expect(wrapper.get('.tooltip-host').attributes('data-visible')).toBe('true')
    button.dispatchEvent(new MouseEvent('mouseout', { bubbles: true }))
    await nextTick()
    expect(wrapper.find('.tooltip-host').exists()).toBe(false)

    button.blur()
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }))
    button.focus()
    await nextTick()
    expect(wrapper.get('.tooltip-host').attributes('data-visible')).toBe('true')
    button.dispatchEvent(new MouseEvent('mouseout', { bubbles: true }))
    await nextTick()
    expect(wrapper.get('.tooltip-host').attributes('data-visible')).toBe('true')
    button.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await nextTick()
    expect(wrapper.find('.tooltip-host').exists()).toBe(false)
    wrapper.unmount()
  })

  it('长文本使用共享宽度上限，实际超过八行时显示截断提示', async () => {
    vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockImplementation(function (this: HTMLElement) {
      return this.classList.contains('app-overflow-tooltip-content__text') ? 160 : 0
    })
    vi.spyOn(HTMLElement.prototype, 'scrollHeight', 'get').mockImplementation(function (this: HTMLElement) {
      return this.classList.contains('app-overflow-tooltip-content__text') ? 200 : 0
    })
    const wrapper = mount(AppOverflowTooltipHost, {
      attachTo: document.body,
      global: { stubs: { ElTooltip: ElTooltipStub } },
    })
    const target = appendOverflowTarget('long-label', '很长的内容'.repeat(100))

    target.dispatchEvent(new FocusEvent('focusin', { bubbles: true }))
    await nextTick()
    await nextTick()
    expect(wrapper.get('.tooltip-host').attributes('data-popper-class'))
      .toBe('app-wrapping-popper app-overflow-tooltip-popper')
    expect(wrapper.get('.app-overflow-tooltip-content__text').text()).toBe(target.textContent)
    expect(wrapper.get('.app-overflow-tooltip-content__notice').text()).toBe('… 内容已截断')

    target.dispatchEvent(new FocusEvent('focusout', { bubbles: true }))
    await nextTick()
    wrapper.unmount()
  })

  it('鼠标停留后才显示真实省略内容，持续移动会重置等待', async () => {
    vi.useFakeTimers()
    const wrapper = mount(AppOverflowTooltipHost, {
      attachTo: document.body,
      global: { stubs: { ElTooltip: ElTooltipStub } },
    })
    const target = appendOverflowTarget('truncated-label', '完整标签')

    target.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }))
    await nextTick()
    expect(wrapper.find('.tooltip-host').exists()).toBe(false)
    vi.advanceTimersByTime(200)
    target.dispatchEvent(new MouseEvent('mousemove', { bubbles: true }))
    vi.advanceTimersByTime(299)
    await nextTick()
    expect(wrapper.find('.tooltip-host').exists()).toBe(false)
    vi.advanceTimersByTime(1)
    await nextTick()
    expect(wrapper.get('.tooltip-host').attributes()).toMatchObject({
      'data-visible': 'true',
      'data-content': '完整标签',
      'data-target': 'truncated-label',
    })
    expect(wrapper.find('.app-overflow-tooltip-content__notice').exists()).toBe(false)
    expect(target.hasAttribute('title')).toBe(false)

    target.dispatchEvent(new MouseEvent('mousemove', { bubbles: true }))
    await nextTick()
    expect(wrapper.find('.tooltip-host').exists()).toBe(false)
    vi.advanceTimersByTime(300)
    await nextTick()
    expect(wrapper.get('.tooltip-host').attributes('data-visible')).toBe('true')

    target.dispatchEvent(new MouseEvent('mouseout', { bubbles: true }))
    await nextTick()
    expect(wrapper.find('.tooltip-host').exists()).toBe(false)
    expect(target.dataset.overflowTooltipContent).toBe('完整标签')
    wrapper.unmount()
  })

  it('短暂经过时取消待显示提示，键盘焦点仍立即展示', async () => {
    vi.useFakeTimers()
    const wrapper = mount(AppOverflowTooltipHost, {
      attachTo: document.body,
      global: { stubs: { ElTooltip: ElTooltipStub } },
    })
    const target = appendOverflowTarget('short-hover')

    target.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }))
    vi.advanceTimersByTime(100)
    target.dispatchEvent(new MouseEvent('mouseout', { bubbles: true }))
    vi.advanceTimersByTime(300)
    await nextTick()
    expect(wrapper.find('.tooltip-host').exists()).toBe(false)
    expect(target.dataset.overflowTooltipContent).toBe('完整内容')

    target.dispatchEvent(new FocusEvent('focusin', { bubbles: true }))
    await nextTick()
    expect(wrapper.get('.tooltip-host').attributes('data-visible')).toBe('true')
    target.dispatchEvent(new FocusEvent('focusout', { bubbles: true }))
    await nextTick()
    expect(wrapper.find('.tooltip-host').exists()).toBe(false)
    wrapper.unmount()
  })

  it('切换目标或卸载时取消上一目标的待显示计时', async () => {
    vi.useFakeTimers()
    const wrapper = mount(AppOverflowTooltipHost, {
      attachTo: document.body,
      global: { stubs: { ElTooltip: ElTooltipStub } },
    })
    const first = appendOverflowTarget('first', '第一项完整内容')
    const second = appendOverflowTarget('second', '第二项完整内容')

    first.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }))
    vi.advanceTimersByTime(200)
    second.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }))
    vi.advanceTimersByTime(299)
    await nextTick()
    expect(wrapper.find('.tooltip-host').exists()).toBe(false)
    vi.advanceTimersByTime(1)
    await nextTick()
    expect(wrapper.get('.tooltip-host').attributes('data-target')).toBe('second')

    second.dispatchEvent(new MouseEvent('mouseout', { bubbles: true }))
    first.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }))
    wrapper.unmount()
    vi.advanceTimersByTime(300)
    expect(first.dataset.overflowTooltipContent).toBe('第一项完整内容')
  })

  it('按钮内省略文字由外层代理时，移动和离开仍能正确取消提示', async () => {
    vi.useFakeTimers()
    const wrapper = mount(AppOverflowTooltipHost, {
      attachTo: document.body,
      global: { stubs: { ElTooltip: ElTooltipStub } },
    })
    const button = document.createElement('button')
    button.dataset.overflowTooltipDelegate = ''
    const label = document.createElement('span')
    label.dataset.overflowTooltipTarget = ''
    label.textContent = '较长的选项名称'
    label.style.textOverflow = 'ellipsis'
    label.style.overflow = 'hidden'
    Object.defineProperty(label, 'clientWidth', { value: 40 })
    Object.defineProperty(label, 'scrollWidth', { value: 100 })
    button.append(label)
    document.body.append(button)

    button.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }))
    vi.advanceTimersByTime(200)
    button.dispatchEvent(new MouseEvent('mousemove', { bubbles: true }))
    vi.advanceTimersByTime(200)
    button.dispatchEvent(new MouseEvent('mouseout', { bubbles: true }))
    vi.advanceTimersByTime(300)
    await nextTick()
    expect(wrapper.find('.tooltip-host').exists()).toBe(false)
    wrapper.unmount()
  })

  it('完整可见内容和原生 title 不会触发全局提示，也不修改 DOM 属性', async () => {
    vi.useFakeTimers()
    const wrapper = mount(AppOverflowTooltipHost, {
      attachTo: document.body,
      global: { stubs: { ElTooltip: ElTooltipStub } },
    })
    const button = document.createElement('button')
    button.title = '关闭页面设置'
    button.setAttribute('aria-label', '关闭页面设置')
    button.textContent = '关闭'
    document.body.append(button)
    button.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }))
    vi.advanceTimersByTime(300)
    await nextTick()
    expect(wrapper.find('.tooltip-host').exists()).toBe(false)
    button.dispatchEvent(new FocusEvent('focusin', { bubbles: true }))
    await nextTick()
    expect(wrapper.find('.tooltip-host').exists()).toBe(false)
    expect(button.title).toBe('关闭页面设置')
    expect(button.getAttribute('aria-label')).toBe('关闭页面设置')
    wrapper.unmount()
  })
})
