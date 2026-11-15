// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import type { Component } from 'vue'
import HelpHint from '@/components/HelpHint.vue'

describe('HelpHint', () => {
  it('说明提示支持鼠标悬浮和键盘焦点触达', () => {
    const wrapper = mount(HelpHint as Component, {
      props: { text: '默认值：3；允许范围：1 - 10' },
      global: {
        stubs: {
          ElTooltip: {
            props: ['content', 'trigger', 'popperClass'],
            template: `
              <div
                class="tooltip"
                :data-content="content"
                :data-trigger="trigger.join('|')"
                :data-popper-class="popperClass"
              >
                <slot />
              </div>
            `,
          },
        },
      },
    })

    expect(wrapper.find('.tooltip').attributes('data-content')).toBe('默认值：3；允许范围：1 - 10')
    expect(wrapper.find('.tooltip').attributes('data-trigger')).toBe('hover|focus')
    expect(wrapper.find('.tooltip').attributes('data-popper-class'))
      .toBe('app-wrapping-popper app-hover-info--tooltip help-hint-popper')
    expect(wrapper.find('.help-hint').attributes('tabindex')).toBe('0')
    expect(wrapper.find('.help-hint').attributes('role')).toBe('button')
  })
})
