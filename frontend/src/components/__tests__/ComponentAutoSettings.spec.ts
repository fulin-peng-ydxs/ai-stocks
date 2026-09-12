// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import type { Component } from 'vue'
import ComponentAutoSettings from '@/components/ComponentAutoSettings.vue'

vi.mock('@/layout/pageRegistry', () => ({
  componentMetaForSlot: (entry: any, slot: any) => entry.componentMeta?.[slot.id] ?? {},
  applicableComponentFields: (entry: any, slotId: string, layer: 'page' | 'user') => {
    const fieldsByPage: Record<string, { key: string; layers: string[] }[]> = {
      'sort-demo': [{ key: 'defaultSort', layers: ['page', 'user'] }],
      'border-demo': [{ key: 'border', layers: ['page'] }],
      'config-panel-demo': [{ key: 'defaultCollapsed', layers: ['page', 'user'] }],
      'chart-demo': [
        { key: 'minHeight', layers: ['page', 'user'] },
        { key: 'stockChart', layers: ['page', 'user'] },
      ],
      'master-demo': [
        { key: 'masterRatio', layers: ['preset', 'page', 'user'] },
        { key: 'masterRatioProfiles', layers: ['user'] },
      ],
      'system-config': [
        { key: 'bodyScroll', layers: ['preset', 'page'] },
        { key: 'defaultCollapsed', layers: ['preset', 'page', 'user'] },
      ],
    }
    return (fieldsByPage[entry.pageKey] ?? []).filter((field) => field.layers.includes(layer))
  },
  getPageEntry: (pageKey: string) => {
    if (pageKey === 'sort-demo') {
      return {
        pageKey,
        supportsComponentConfig: true,
        layout: {
          slots: [{ id: 'table', component: 'data-table', label: '列表' }],
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
        pageKey,
        supportsComponentConfig: true,
        layout: {
          slots: [{ id: 'table', component: 'data-table', label: '列表' }],
        },
        componentMeta: {},
      }
    }
    if (pageKey === 'config-panel-demo') {
      return {
        pageKey,
        supportsComponentConfig: true,
        layout: {
          slots: [{ id: 'configPanel', component: 'config-panel', label: '系统设置面板' }],
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
        pageKey,
        supportsComponentConfig: true,
        layout: {
          slots: [{ id: 'chart', component: 'chart', label: '板块指数' }],
        },
        componentMeta: {},
      }
    }
    if (pageKey === 'master-demo') {
      return {
        pageKey,
        supportsComponentConfig: true,
        layout: { slots: [{ id: 'workspace', component: 'master-detail', label: '行情工作台' }] },
        componentMeta: {},
      }
    }
    return {
      pageKey,
      supportsComponentConfig: true,
      layout: {
        slots: [{ id: 'settings', component: 'settings-drawer', label: '设置抽屉' }],
      },
      componentMeta: {},
    }
  },
}))

vi.mock('@/layout/componentConfig', () => {
  const fieldDef = (_kind: string, field: string) => (
    field === 'stockChart'
      ? { key: 'stockChart', label: '图表组合与内部比例', control: 'object', layers: ['page', 'user'] }
      : field === 'minHeight'
      ? { key: 'minHeight', label: '图表区域高度', control: 'int', layers: ['page', 'user'], min: 480, max: 900, default: 560 }
      : field === 'masterRatio'
        ? { key: 'masterRatio', label: '列表默认占比', control: 'int', layers: ['preset', 'page', 'user'], min: 30, max: 70, default: 45 }
      : field === 'masterRatioProfiles'
        ? { key: 'masterRatioProfiles', label: '尺寸比例档案', control: 'object', layers: ['user'], default: { profiles: [] } }
      : field === 'border'
      ? { key: 'border', label: '显示表格边框', control: 'bool', layers: ['page'], default: false }
      : field === 'bodyScroll'
        ? { key: 'bodyScroll', label: '内容区滚动', control: 'bool', layers: ['preset', 'page'], default: true }
        : { key: field, label: field, control: 'string[]', layers: ['user'] }
  )
  return {
    getComponentFieldDef: fieldDef,
    getApplicableComponentFieldDefs: (kind: string, meta: any, layer: string) => {
      const fields = kind === 'chart'
        ? ['minHeight', 'stockChart']
        : kind === 'master-detail'
          ? ['masterRatio', 'masterRatioProfiles']
        : kind === 'config-panel'
          ? ['defaultCollapsed']
          : kind === 'settings-drawer'
            ? ['bodyScroll', 'defaultCollapsed']
            : meta.sortFields?.length
              ? ['defaultSort']
              : ['border']
      return fields.map((field) => fieldDef(kind, field)).filter((def) => def.layers.includes(layer))
    },
  }
})

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
        componentValueOf: vi.fn((_slotId: string, field: string) => (
          field === 'stockChart'
            ? {
                slot2: 'volume',
                slot3: 'macd',
                heightRatios: {
                  kline: [1],
                  'kline|volume': [0.75, 0.25],
                  'kline|macd': [0.75, 0.25],
                  'kline|volume|macd': [0.6, 0.2, 0.2],
                  'kline|macd|volume': [0.6, 0.2, 0.2],
                },
              }
            : 560
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
        AppRowActions: true,
        ElInputNumber: {
          props: ['modelValue', 'min', 'max'],
          emits: ['update:modelValue'],
          template: '<button class="number-stub" :data-value="modelValue" :data-min="min" :data-max="max" @click="$emit(\'update:modelValue\', 620)" />',
        },
        ElButton: { template: '<button><slot /></button>' },
        ElSelect: true,
        ElOption: true,
        ElSwitch: true,
        ElCheckboxGroup: true,
        ElCheckbox: true,
        ElEmpty: true,
        StockChartSettingSection: {
          props: ['slot2', 'slot3', 'defaultRatios', 'currentRatios'],
          emits: ['change', 'saveDefaultRatios'],
          template: '<div><button class="stock-chart-stub" @click="$emit(\'change\', \'slot2\', \'macd\')">chart</button><button class="stock-chart-current-stub" @click="$emit(\'change\', \'slot2\', \'volume\')">current</button></div>',
        },
      },
    },
  })
  return { wrapper, setComponentKnob }
}

function mountMasterDemo(runtimeRatio?: number) {
  const setComponentKnob = vi.fn()
  const wrapper = mount(ComponentAutoSettings as Component, {
    props: {
      pageKey: 'master-demo',
      runtimeValueOf: vi.fn((_slotId: string, field: string) => (
        field === 'masterRatioProfiles' && runtimeRatio
          ? { width: 1920, ratio: runtimeRatio }
          : runtimeRatio
      )),
      config: {
        componentValueOf: vi.fn((_slotId: string, field: string) => (
          field === 'masterRatioProfiles' ? { profiles: [] } : 45
        )),
        setComponentKnob,
      },
    },
    global: {
      stubs: {
        SettingsGroup: { template: '<section><slot /></section>' },
        SourceTag: true,
        AppRowActions: true,
        MasterDetailRatioProfileSettings: {
          props: ['modelValue', 'currentSample'],
          emits: ['update:modelValue'],
          template: '<button data-testid="master-ratio-profile-save-current" :disabled="!currentSample" @click="$emit(\'update:modelValue\', { profiles: [currentSample] })">使用页面当前比例</button>',
        },
        ElInputNumber: true,
        ElButton: {
          props: ['disabled'],
          template: '<button :disabled="disabled"><slot /></button>',
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

  it('股票多图组合在组件设置中按 slot 写回统一 stockChart 字段', async () => {
    const { wrapper, setComponentKnob } = mountChartDemo()
    expect(wrapper.text()).toContain('图表组合与内部比例')
    await wrapper.find('.stock-chart-stub').trigger('click')
    expect(setComponentKnob).toHaveBeenCalledWith(
      'chart',
      'stockChart',
      expect.objectContaining({ slot2: 'macd', slot3: 'volume' }),
    )
  })

  it('股票多图组合重复选择当前类型时不写入组件配置', async () => {
    const { wrapper, setComponentKnob } = mountChartDemo()
    await wrapper.find('.stock-chart-current-stub').trigger('click')
    expect(setComponentKnob).not.toHaveBeenCalled()
  })

  it('行情工作台可把页面当前宽度与比例保存为尺寸档案', async () => {
    const { wrapper, setComponentKnob } = mountMasterDemo(48)

    await wrapper.get('[data-testid="master-ratio-profile-save-current"]').trigger('click')

    expect(setComponentKnob).toHaveBeenCalledWith('workspace', 'masterRatioProfiles', {
      profiles: [{ width: 1920, ratio: 48 }],
    })
  })

  it('页面当前比例尚未上报时禁用采用入口', () => {
    const { wrapper } = mountMasterDemo()
    expect(wrapper.get('[data-testid="master-ratio-profile-save-current"]').attributes('disabled'))
      .toBeDefined()
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
