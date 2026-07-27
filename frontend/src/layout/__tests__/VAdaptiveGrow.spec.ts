// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import VAdaptiveGrow from '@/layout/components/VAdaptiveGrow.vue'

describe('VAdaptiveGrow', () => {
  it('显式 minH 作为运行时最低高度', () => {
    const wrapper = mount(VAdaptiveGrow, {
      props: {
        slot: {
          id: 'table',
          component: 'data-table',
          region: 'main',
          growMain: true,
          minH: 360,
        },
      },
      slots: { default: '<div class="table">表格</div>' },
    })

    expect(wrapper.get('[data-testid="layout-grow-region"]').attributes('style'))
      .toContain('min-height: 360px')
  })

  it('未显式声明时消费组件目录最低高度', () => {
    const wrapper = mount(VAdaptiveGrow, {
      props: {
        slot: {
          id: 'table',
          component: 'data-table',
          region: 'main',
          growMain: true,
        },
      },
    })

    expect(wrapper.get('[data-testid="layout-grow-region"]').attributes('style'))
      .toContain('min-height: 300px')
  })
})
