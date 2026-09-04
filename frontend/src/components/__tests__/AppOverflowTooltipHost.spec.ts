// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { defineComponent, h, nextTick } from 'vue'
import { afterEach, describe, expect, it } from 'vitest'
import AppOverflowTooltipHost from '@/components/AppOverflowTooltipHost.vue'

const ElTooltipStub = defineComponent({
  name: 'ElTooltip',
  props: ['visible', 'content', 'virtualRef'],
  setup(props) {
    return () => h('div', {
      class: 'tooltip-host',
      'data-visible': String(props.visible),
      'data-content': props.content,
      'data-target': props.virtualRef?.id,
    })
  },
})

afterEach(() => {
  document.body.innerHTML = ''
})

describe('AppOverflowTooltipHost', () => {
  it('悬浮真实省略目标时统一显示完整内容，离开后收起并恢复原 title', async () => {
    const wrapper = mount(AppOverflowTooltipHost, {
      attachTo: document.body,
      global: { stubs: { ElTooltip: ElTooltipStub } },
    })
    const target = document.createElement('span')
    target.id = 'truncated-label'
    target.title = '完整标签'
    target.textContent = '完整标签'
    target.style.textOverflow = 'ellipsis'
    Object.defineProperty(target, 'clientWidth', { value: 40 })
    Object.defineProperty(target, 'scrollWidth', { value: 100 })
    document.body.append(target)

    target.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }))
    await nextTick()
    expect(wrapper.get('.tooltip-host').attributes()).toMatchObject({
      'data-visible': 'true',
      'data-content': '完整标签',
      'data-target': 'truncated-label',
    })
    expect(target.title).toBe('')

    target.dispatchEvent(new MouseEvent('mouseout', { bubbles: true }))
    await nextTick()
    expect(wrapper.find('.tooltip-host').exists()).toBe(false)
    expect(target.title).toBe('完整标签')
    wrapper.unmount()
  })
})
