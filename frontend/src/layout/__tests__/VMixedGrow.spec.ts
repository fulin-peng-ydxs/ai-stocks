// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import VMixedGrow from '@/layout/components/VMixedGrow.vue'
import type { SlotSpec } from '@/layout/schema'

describe('VMixedGrow 低视口收缩契约', () => {
  it('业务 minH 只参与校验，不以内联高度撑开真实成长区', () => {
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
    expect(grow.attributes('style')).toBeUndefined()
    expect(grow.classes()).toContain('v-mixed-main')
  })
})
