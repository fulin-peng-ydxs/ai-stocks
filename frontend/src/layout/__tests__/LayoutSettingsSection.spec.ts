// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import LayoutSettingsSection from '@/layout/components/LayoutSettingsSection.vue'
import SettingsGroup from '@/components/SettingsGroup.vue'

describe('LayoutSettingsSection', () => {
  it('按元数据把基础布局与模块显隐收拢为二级章节', () => {
    const wrapper = mount(LayoutSettingsSection, {
      props: {
        knobs: [
          {
            path: 'density',
            label: '信息密度',
            group: '基础布局',
            type: 'enum',
            options: ['standard'],
          },
          {
            path: 'slots.summary.visible',
            label: '显示摘要',
            group: '模块显示',
            type: 'bool',
          },
        ],
        valueOf: (path: string) => path === 'density' ? 'standard' : true,
        set: vi.fn(),
      },
      global: {
        stubs: {
          PageSegmented: true,
          PageToggleRow: true,
          SourceTag: true,
          ElIcon: true,
          ElInputNumber: true,
        },
      },
    })

    expect(wrapper.findAllComponents(SettingsGroup).map((group) => group.props('title')))
      .toEqual(['基础布局', '模块显示'])
    expect(wrapper.findAllComponents(SettingsGroup).every((group) => group.props('level') === 2))
      .toBe(true)
  })

  it('未显式分组的存量旋钮稳定归入基础布局', () => {
    const wrapper = mount(LayoutSettingsSection, {
      props: {
        knobs: [{ path: 'density', label: '信息密度', type: 'enum', options: ['standard'] }],
        valueOf: () => 'standard',
        set: vi.fn(),
      },
      global: {
        stubs: {
          PageSegmented: true,
          SourceTag: true,
          ElIcon: true,
          ElInputNumber: true,
        },
      },
    })

    expect(wrapper.getComponent(SettingsGroup).props('title')).toBe('基础布局')
  })
})
