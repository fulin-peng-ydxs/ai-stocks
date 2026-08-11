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
    if (pageKey === 'border-demo') {
      return {
        layout: {
          slots: [{ id: 'table', component: 'data-table', label: '列表' }],
        },
        consumedComponentFields: {
          table: ['border'],
        },
        componentMeta: {},
      }
    }
    if (pageKey === 'config-panel-demo') {
      return {
        layout: {
          slots: [{ id: 'configPanel', component: 'config-panel', label: '系统设置面板' }],
        },
        consumedComponentFields: {
          configPanel: ['defaultCollapsed'],
        },
        componentMeta: {
          configPanel: {
            collapseSections: [
              { key: 'auth', label: '认证与防滥用' },
              { key: 'auth.login', label: '登录保护' },
              { key: 'datasource', label: '数据源' },
            ],
          },
        },
      }
    }
    if (pageKey === 'chart-demo') {
      return {
        layout: {
          slots: [{ id: 'chart', component: 'chart', label: '板块指数' }],
        },
        consumedComponentFields: {
          chart: ['minHeight'],
        },
        componentMeta: {},
      }
    }
    return {
      layout: {
        slots: [{ id: 'settings', component: 'settings-drawer', label: '设置抽屉' }],
      },
      consumedComponentFields: {
        settings: ['bodyScroll', 'defaultCollapsed'],
      },
      componentMeta: {},
    }
  },
}))

vi.mock('@/layout/componentConfig', () => ({
  getComponentFieldDef: (_kind: string, field: string) => (
    field === 'minHeight'
      ? { key: 'minHeight', label: '图表区域高度', control: 'int', layers: ['page', 'user'], min: 480, max: 900, default: 560 }
      : field === 'border'
      ? { layers: ['page'] }
      : field === 'bodyScroll'
        ? { layers: ['preset', 'page'] }
        : { layers: ['user'] }
  ),
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
        ElButton: { template: '<button><slot /></button>' },
        ElSwitch: true,
        ElEmpty: true,
        ElSelect: { template: '<div><slot /></div>' },
        ElOption: { props: ['label'], template: '<span>{{ label }}</span>' },
        ElInputNumber: true,
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
        ElButton: { template: '<button><slot /></button>' },
        ElSwitch: true,
        ElEmpty: true,
        ElCheckboxGroup: { template: '<div><slot /></div>' },
        ElCheckbox: { props: ['value'], template: '<label><slot /></label>' },
        ElSelect: { props: ['modelValue'], template: '<div class="select-stub"><slot /></div>' },
        ElOption: { props: ['label'], template: '<span class="option-stub">{{ label }}</span>' },
        ElInputNumber: true,
      },
    },
  })
}

function mountBorderDemo(layer: 'page' | 'user') {
  return mount(ComponentAutoSettings as Component, {
    props: {
      pageKey: 'border-demo',
      layer,
      config: {
        componentValueOf: vi.fn(() => true),
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
        ElButton: { template: '<button><slot /></button>' },
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

function mountConfigPanelDemo() {
  const setComponentKnob = vi.fn()
  const wrapper = mount(ComponentAutoSettings as Component, {
    props: {
      pageKey: 'config-panel-demo',
      componentMetaOverrides: {
        configPanel: {
          collapseSections: [
            { key: 'auth', label: '认证与防滥用' },
            { key: 'auth.login', label: '登录保护' },
          ],
        },
      },
      config: {
        componentValueOf: vi.fn((slotId: string, field: string) => (
          slotId === 'configPanel' && field === 'defaultCollapsed'
            ? ['datasource', 'auth.login']
            : []
        )),
        setComponentKnob,
      },
    },
    global: {
      stubs: {
        SettingsGroup: {
          props: ['title'],
          template: '<section><h3 v-if="title">{{ title }}</h3><slot /></section>',
        },
        SourceTag: true,
        ElButton: { template: '<button><slot /></button>' },
        ElSwitch: true,
        ElEmpty: true,
        ElSelect: { template: '<div><slot /></div>' },
        ElOption: { props: ['label'], template: '<span>{{ label }}</span>' },
        ElCheckboxGroup: {
          props: ['modelValue'],
          emits: ['update:modelValue'],
          template: `
            <div class="checkbox-group" :data-model-value="modelValue.join('|')">
              <button class="emit-collapsed" @click="$emit('update:modelValue', ['auth'])" />
              <slot />
            </div>
          `,
        },
        ElCheckbox: { props: ['value'], template: '<label><slot /></label>' },
      },
    },
  })
  return { wrapper, setComponentKnob }
}

function mountChartDemo() {
  const setComponentKnob = vi.fn()
  const wrapper = mount(ComponentAutoSettings as Component, {
    props: {
      pageKey: 'chart-demo',
      config: {
        componentValueOf: vi.fn(() => 560),
        setComponentKnob,
      },
    },
    global: {
      stubs: {
        SettingsGroup: {
          props: ['title'],
          template: '<section><h3 v-if="title">{{ title }}</h3><slot /></section>',
        },
        SourceTag: true,
        AppRowActions: true,
        ElInputNumber: {
          props: ['modelValue', 'min', 'max'],
          emits: ['update:modelValue'],
          template: '<button class="number-stub" :data-value="modelValue" :data-min="min" :data-max="max" @click="$emit(\'update:modelValue\', 620)" />',
        },
        ElSelect: true,
        ElOption: true,
        ElSwitch: true,
        ElCheckboxGroup: true,
        ElCheckbox: true,
        ElEmpty: true,
      },
    },
  })
  return { wrapper, setComponentKnob }
}

describe('ComponentAutoSettings', () => {
  it('无业务设置 slot 时隐藏设置抽屉的业务折叠段选项', () => {
    const wrapper = mountAuto(false)
    expect(wrapper.text()).toContain('默认折叠段')
    expect(wrapper.text()).toContain('布局')
    expect(wrapper.text()).toContain('组件设置')
    expect(wrapper.text()).not.toContain('业务选项')
  })

  it('settings-drawer 内容区滚动不进入用户层设置抽屉', () => {
    const wrapper = mountAuto(false)
    expect(wrapper.text()).not.toContain('内容区滚动')
  })

  it('有业务设置 slot 时保留业务折叠段选项', () => {
    const wrapper = mountAuto(true)
    expect(wrapper.text()).toContain('业务选项')
  })

  it('排序字段候选超过三个时使用下拉，避免窄抽屉内分段按钮挤压', () => {
    const wrapper = mountSortDemo()
    expect(wrapper.find('.select-stub').exists()).toBe(true)
    expect(wrapper.find('.ca-select').exists()).toBe(true)
    expect(wrapper.find('.segmented-stub').exists()).toBe(true) // 排序方向仍使用分段控件
    expect(wrapper.text()).toContain('更新时间')
  })

  it('表格边框是 page 层组件能力，不进入用户设置层', () => {
    expect(mountBorderDemo('page').text()).toContain('显示表格边框')
    expect(mountBorderDemo('user').text()).not.toContain('显示表格边框')
  })

  it('数值型组件字段按统一元数据渲染并写回', async () => {
    const { wrapper, setComponentKnob } = mountChartDemo()
    expect(wrapper.text()).toContain('图表区域高度')
    expect(wrapper.find('.number-stub').attributes()).toMatchObject({
      'data-value': '560',
      'data-min': '480',
      'data-max': '900',
    })
    await wrapper.find('.number-stub').trigger('click')
    expect(setComponentKnob).toHaveBeenCalledWith('chart', 'minHeight', 620)
  })

  it('config-panel 默认折叠候选支持按当前业务覆盖并保留隐藏选中值', async () => {
    const { wrapper, setComponentKnob } = mountConfigPanelDemo()
    expect(wrapper.text()).toContain('默认折叠分区')
    expect(wrapper.text()).toContain('认证与防滥用')
    expect(wrapper.text()).toContain('登录保护')
    expect(wrapper.text()).not.toContain('数据源')
    expect(wrapper.find('.checkbox-group').attributes('data-model-value')).toBe('auth.login')

    await wrapper.find('.emit-collapsed').trigger('click')
    expect(setComponentKnob).toHaveBeenCalledWith('configPanel', 'defaultCollapsed', ['datasource', 'auth'])
  })
})
