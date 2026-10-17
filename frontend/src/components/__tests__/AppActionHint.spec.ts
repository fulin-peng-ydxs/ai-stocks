// @vitest-environment jsdom
import { defineComponent, h, nextTick } from 'vue'
import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import AppActionHint from '../AppActionHint.vue'
const Tooltip = defineComponent({
  name: 'ElTooltip', props: ['visible', 'content'],
  setup: (props, { slots }) => () => h('div', { class: 'hint', 'data-visible': String(props.visible), 'data-content': props.content }, slots.default?.()),
})

describe('命令补充说明', () => {
  it('未声明文案时不生成提示与额外 Tab 入口', () => {
    const wrapper = mount(AppActionHint, { slots: { default: '<button>恢复</button>' }, global: { stubs: { ElTooltip: Tooltip } } })
    expect(wrapper.find('.hint').exists()).toBe(false)
    expect(wrapper.get('.app-action-hint').attributes('tabindex')).toBeUndefined()
    wrapper.unmount()
  })
  it('禁用原因可通过键盘阅读，外壳不执行被禁用的命令', async () => {
    const run = vi.fn()
    const wrapper = mount(AppActionHint, { props: { disabled: true, label: '恢复', text: '请先选择恢复范围' },
      slots: { default: () => h('button', { disabled: true, onClick: run }, '恢复') },
      global: { stubs: { ElTooltip: Tooltip } },
    })
    await nextTick()
    const shell = wrapper.get('.app-action-hint')
    expect(shell.attributes()).toMatchObject({ tabindex: '0', 'aria-label': '恢复' })
    await shell.trigger('focusin')
    expect(wrapper.get('.hint').attributes()).toMatchObject({ 'data-visible': 'true', 'data-content': '请先选择恢复范围' })
    await shell.trigger('keydown', { key: 'Enter' })
    ;(wrapper.get('button').element as HTMLButtonElement).click()
    expect(run).not.toHaveBeenCalled()
    await shell.trigger('keydown', { key: 'Escape' })
    expect(wrapper.get('.hint').attributes('data-visible')).toBe('false')
    wrapper.unmount()
  })
})
