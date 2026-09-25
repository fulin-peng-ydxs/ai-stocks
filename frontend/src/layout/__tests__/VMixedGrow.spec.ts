// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import VMixedGrow from '@/layout/components/VMixedGrow.vue'
import type { SlotSpec } from '@/layout/schema'

describe('VMixedGrow 条件成长契约', () => {
  it('把 growMain 的业务 minH 应用到真实成长区，余量不足时由外层滚动兜底', () => {
    const slots: SlotSpec[] = [
      { id: 'summary', component: 'kpi-grid', region: 'main', order: 1 },
      { id: 'workspace', component: 'tabs', region: 'main', growMain: true, minH: 420, order: 2 },
    ]
    const wrapper = mount(VMixedGrow, {
      props: { slots },
      slots: {
        summary: '<div>摘要</div>',
        workspace: '<div>工作区</div>',
      },
    })

    const grow = wrapper.get('[data-testid="layout-grow-region"]')
    expect(grow.attributes('style')).toContain('min-height: 420px')
    expect(grow.classes()).toContain('v-mixed-main')
  })

  it('仅让声明 idealH 的前置区域在理想高度与业务下限之间受控收缩', () => {
    const wrapper = mount(VMixedGrow, {
      props: {
        slots: [
          { id: 'summary', component: 'section', region: 'main', order: 1 },
          { id: 'leading', component: 'data-table', region: 'main', minH: 520, idealH: 960, order: 2 },
          { id: 'workspace', component: 'section', region: 'main', growMain: true, minH: 200, order: 3 },
        ],
      },
      slots: {
        summary: '<div>摘要</div>',
        leading: '<div>前置表</div>',
        workspace: '<div>成长区</div>',
      },
    })

    const fixed = wrapper.findAll('.v-mixed-fixed')
    expect(fixed[0]!.classes()).not.toContain('v-mixed-fixed--shrinkable')
    expect(fixed[1]!.classes()).toContain('v-mixed-fixed--shrinkable')
    expect(fixed[1]!.attributes('style')).toContain('min-height: 520px')
    expect(fixed[1]!.attributes('style')).toContain('max-height: 960px')
    expect(wrapper.find('.v-mixed-main').attributes('style')).toContain('min-height: 200px')
  })
})
