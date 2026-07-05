// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import type { Component } from 'vue'
import ComponentAutoSettings from '@/components/ComponentAutoSettings.vue'

vi.mock('@/layout/pageRegistry', () => ({
  getPageEntry: () => ({
    layout: {
      slots: [{ id: 'settings', component: 'settings-drawer', label: '设置抽屉' }],
    },
    consumedComponentFields: {
      settings: ['defaultCollapsed'],
    },
    componentMeta: {},
  }),
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
        ElCheckboxGroup: { template: '<div><slot /></div>' },
        ElCheckbox: { props: ['value'], template: '<label><slot /></label>' },
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
})
