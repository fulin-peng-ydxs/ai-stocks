// @vitest-environment jsdom

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import BoardTaskScopeFields from '@/components/data/BoardTaskScopeFields.vue'
import type { BoardIngestStage } from '@/api/data'

const baseProps = {
  mode: 'update' as const,
  boardType: '' as const,
  stages: ['bar', 'fund'] as BoardIngestStage[],
  forceMembers: false,
  forceCurrentDay: false,
  testIdPrefix: 'board',
}

describe('BoardTaskScopeFields', () => {
  it('only shows force-current-day for date-sensitive incremental stages', async () => {
    const wrapper = mount(BoardTaskScopeFields, {
      props: baseProps,
      global: {
        stubs: {
          'el-checkbox': { template: '<button><slot /></button>' },
          'el-checkbox-group': { template: '<div><slot /></div>' },
          'el-form-item': { template: '<div><slot /></div>' },
        },
      },
    })

    expect(wrapper.find('[data-testid="board-force-current-day"]').exists()).toBe(true)
    expect(wrapper.findAll('.app-form-help')).toHaveLength(3)
    expect(wrapper.findAll('.app-form-help__marker')).toHaveLength(3)

    await wrapper.setProps({ mode: 'backfill' })
    expect(wrapper.find('[data-testid="board-force-current-day"]').exists()).toBe(false)

    await wrapper.setProps({ mode: 'update', stages: ['members'] })
    expect(wrapper.find('[data-testid="board-force-current-day"]').exists()).toBe(false)
  })

  it('shows the reusable manual index range only when enabled for incremental bars', async () => {
    const wrapper = mount(BoardTaskScopeFields, {
      props: { ...baseProps, allowDateRange: true },
      global: {
        stubs: {
          TradeDatePicker: { props: ['modelValue'], template: '<input />' },
          'el-checkbox': { template: '<button><slot /></button>' },
          'el-checkbox-group': { template: '<div><slot /></div>' },
          'el-form-item': { template: '<div><slot /></div>' },
        },
      },
    })

    expect(wrapper.find('[data-testid="board-date-start"]').exists()).toBe(true)
    await wrapper.setProps({ stages: ['fund'] })
    expect(wrapper.find('[data-testid="board-date-start"]').exists()).toBe(false)
  })
})
