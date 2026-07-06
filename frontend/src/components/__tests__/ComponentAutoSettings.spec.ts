// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import type { Component } from 'vue'
import ComponentAutoSettings from '@/components/ComponentAutoSettings.vue'

vi.mock('@/layout/pageRegistry', () => ({
  getPageEntry: (pageKey: string) => {
    if (pageKey === 'sort-demo') {
      return {
        layout: {
          slots: [{ id: 'table', component: 'data-table', label: '列表' }],
        },
        consumedComponentFields: {
          table: ['defaultSort'],
        },
        componentMeta: {
          table: {
            sortFields: [
              { key: 'sort', label: '排序' },
              { key: 'code', label: 'code' },
              { key: 'name', label: '名称' },
              { key: 'updated_at', label: '更新时间' },
            ],
          },
        },
      }
    }
    return {
      layout: {
        slots: [{ id: 'settings', component: 'settings-drawer', label: '设置抽屉' }],
      },
      consumedComponentFields: {
        settings: ['defaultCollapsed'],
      },
      componentMeta: {},
    }
  },
}))

vi.mock('@/layout/componentConfig', () => ({
  getComponentFieldDef: () => ({ layers: ['user'] }),
}))

function mountAuto(drawerBusinessVisible: boolean) {
  return mount(ComponentAutoSettings as Component, {
    props: {
      pageKey: 'system-config',
      drawerBusinessVisible,
      config: {
        componentValueOf: vi.fn(() => []),
        setComponentKnob: vi.fn(),
      },
    },
    global: {
      stubs: {
        SettingsGroup: {
          props: ['title'],
          template: '<section><h3 v-if="title">{{ title }}</h3><slot /></section>',
        },
        SourceTag: true,
        ElSwitch: true,
        ElEmpty: true,
        ElSelect: { template: '<div><slot /></div>' },
        ElOption: { props: ['label'], template: '<span>{{ label }}</span>' },
        ElCheckboxGroup: { template: '<div><slot /></div>' },
        ElCheckbox: { props: ['value'], template: '<label><slot /></label>' },
      },
    },
  })
}

function mountSortDemo() {
  return mount(ComponentAutoSettings as Component, {
    props: {
      pageKey: 'sort-demo',
      config: {
        componentValueOf: vi.fn(() => 'updated_at:desc'),
        setComponentKnob: vi.fn(),
      },
    },
    global: {
      stubs: {
        SettingsGroup: {
          props: ['title'],
          template: '<section><h3 v-if="title">{{ title }}</h3><slot /></section>',
        },
        SourceTag: true,
        PageSegmented: { template: '<div class="segmented-stub" />' },
        ElSwitch: true,
        ElEmpty: true,
        ElCheckboxGroup: { template: '<div><slot /></div>' },
        ElCheckbox: { props: ['value'], template: '<label><slot /></label>' },
        ElSelect: { props: ['modelValue'], template: '<div class="select-stub"><slot /></div>' },
        ElOption: { props: ['label'], template: '<span class="option-stub">{{ label }}</span>' },
      },
    },
  })
}

describe('ComponentAutoSettings', () => {
  it('无业务设置 slot 时隐藏设置抽屉的业务折叠段选项', () => {
    const wrapper = mountAuto(false)
    expect(wrapper.text()).toContain('默认折叠段')
    expect(wrapper.text()).toContain('布局')
    expect(wrapper.text()).toContain('组件设置')
    expect(wrapper.text()).not.toContain('业务选项')
  })

  it('有业务设置 slot 时保留业务折叠段选项', () => {
    const wrapper = mountAuto(true)
    expect(wrapper.text()).toContain('业务选项')
  })

  it('排序字段候选超过三个时使用下拉，避免窄抽屉内分段按钮挤压', () => {
    const wrapper = mountSortDemo()
    expect(wrapper.find('.select-stub').exists()).toBe(true)
    expect(wrapper.find('.segmented-stub').exists()).toBe(true) // 排序方向仍使用分段控件
    expect(wrapper.text()).toContain('更新时间')
  })
})
