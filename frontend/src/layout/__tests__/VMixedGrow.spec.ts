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
})
