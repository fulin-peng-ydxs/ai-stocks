// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { nextTick, reactive, type Component } from 'vue'
import { ElCheckbox, ElCheckboxGroup, ElMessage } from 'element-plus'
import ComponentAutoSettings from '@/components/ComponentAutoSettings.vue'
import HelpHint from '@/components/HelpHint.vue'
import { SETTINGS_FOLD_PREFERENCES, type SettingsFoldPreferences } from '@/composables/settingsFoldPreferences'
import { createDefaultStockChartPreferences } from '@/composables/useStockChartPreferences'

vi.mock('@/layout/pageRegistry', () => ({
  componentMetaForSlot: (entry: any, slot: any) => entry.componentMeta?.[slot.id] ?? {},
  applicableComponentFields: (entry: any, slotId: string, layer: 'page' | 'user') => {
    const fieldsByPage: Record<string, { key: string; layers: string[] }[]> = {
      'sort-demo': [{ key: 'defaultSort', layers: ['page', 'user'] }],
      'border-demo': [{ key: 'border', layers: ['page'] }],
      'config-panel-demo': [{ key: 'defaultCollapsed', layers: ['page', 'user'] }],
      'chart-demo': [
        { key: 'klineRangePreferences', layers: ['user'] },
        { key: 'minHeight', layers: ['page', 'user'] },
        { key: 'stockChart', layers: ['page', 'user'] },
      ],
      'master-demo': [
        { key: 'masterRatio', layers: ['preset', 'page', 'user'] },
        { key: 'masterRatioProfiles', layers: ['user'] },
      ],
      'system-config': [
        { key: 'bodyScroll', layers: ['preset', 'page'] },
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
            hint: '规则管理、今日打卡和历史详情共用默认值。',
            collapseSections: [
              { key: 'auth', label: '认证与防滥用' },
              { key: 'auth.login', label: '登录保护', parentKey: 'auth' },
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
    field === 'klineRangePreferences'
      ? { key: 'klineRangePreferences', label: 'K 线范围', control: 'object', layers: ['user'], help: '所有 K 线图共用的快捷范围与默认范围。' }
      : field === 'stockChart'
      ? { key: 'stockChart', label: '图表组合与内部比例', control: 'object', layers: ['page', 'user'] }
      : field === 'minHeight'
      ? { key: 'minHeight', label: '图表区域高度', control: 'int', layers: ['page', 'user'], min: 480, max: 900, default: 560, help: '这是一段需要收进统一帮助提示而不是常驻铺开的较长说明。' }
      : field === 'masterRatio'
        ? { key: 'masterRatio', label: '列表默认占比', control: 'int', layers: ['preset', 'page', 'user'], min: 30, max: 70, default: 45 }
      : field === 'masterRatioProfiles'
        ? { key: 'masterRatioProfiles', label: '尺寸比例档案', control: 'object', layers: ['user'], default: { profiles: [] } }
      : field === 'border'
      ? { key: 'border', label: '显示列分隔线', control: 'bool', layers: ['page'], default: false }
      : field === 'bodyScroll'
        ? { key: 'bodyScroll', label: '内容区滚动', control: 'bool', layers: ['preset', 'page'], default: true }
        : { key: field, label: field, control: 'string[]', layers: field === 'defaultCollapsed' ? ['page', 'user'] : ['user'] }
  )
  return {
    getComponentFieldDef: fieldDef,
    getApplicableComponentFieldDefs: (kind: string, meta: any, layer: string) => {
      const fields = kind === 'chart'
        ? ['klineRangePreferences', 'minHeight', 'stockChart']
        : kind === 'master-detail'
          ? ['masterRatio', 'masterRatioProfiles']
        : kind === 'config-panel'
          ? ['defaultCollapsed']
          : kind === 'settings-drawer'
            ? ['bodyScroll']
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

function mountConfigPanelDemo(layer: 'page' | 'user' = 'user', preferences?: SettingsFoldPreferences) {
  const state = reactive({ collapsed: ['datasource', 'auth.login'] })
  const setComponentKnob = vi.fn((_slot: string, _field: string, values: string[]) => {
    state.collapsed = values
  })
  const wrapper = mount(ComponentAutoSettings as Component, {
    props: {
      pageKey: 'config-panel-demo',
      layer,
      componentMetaOverrides: {
        configPanel: {
          collapseSections: [
            { key: 'auth', label: '认证与防滥用' },
            { key: 'auth.login', label: '登录保护', parentKey: 'auth' },
          ],
        },
      },
      config: {
        componentValueOf: vi.fn((slotId: string, field: string) => (
          slotId === 'configPanel' && field === 'defaultCollapsed'
            ? state.collapsed
            : []
        )),
        setComponentKnob,
      },
    },
    global: {
      components: { ElCheckboxGroup, ElCheckbox },
      provide: preferences ? { [SETTINGS_FOLD_PREFERENCES as symbol]: preferences } : {},
      stubs: {
        SettingsGroup: false,
        ElIcon: true,
        ElCollapseTransition: { template: '<slot />' },
        SourceTag: true,
        ElButton: { template: '<button><slot /></button>' },
        ElSwitch: true,
        ElEmpty: true,
        ElSelect: { template: '<div><slot /></div>' },
        ElOption: { props: ['label'], template: '<span>{{ label }}</span>' },
        ElCheckboxGroup: false,
        ElCheckbox: false,
      },
    },
  })
  return { wrapper, setComponentKnob, state }
}

function mountChartDemo(withRuntime = false) {
  const setComponentKnob = vi.fn()
  const wrapper = mount(ComponentAutoSettings as Component, {
    props: {
      pageKey: 'chart-demo',
      runtimeValueOf: withRuntime
        ? vi.fn((_slotId: string, field: string) => {
            if (field === 'stockChartRatioSample') {
              return { width: 1280, height: 720, ratios: [0.5, 0.3, 0.2] }
            }
            if (field === 'stockChartConfigured') {
              return createDefaultStockChartPreferences()
            }
            if (field !== 'stockChart') return undefined
            return {
              ...createDefaultStockChartPreferences(),
              heightRatios: {
                ...createDefaultStockChartPreferences().heightRatios,
                'kline|volume|macd': [0.5, 0.3, 0.2],
              },
              heightRatioProfiles: {
                ...createDefaultStockChartPreferences().heightRatioProfiles,
                'kline|volume|macd': [{
                  width: 1280,
                  height: 720,
                  ratios: [0.5, 0.3, 0.2],
                }],
              },
            }
          })
        : undefined,
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
        ElTooltip: { template: '<span><slot /></span>' },
        ElSwitch: true,
        ElCheckboxGroup: true,
        ElCheckbox: true,
        ElEmpty: true,
        StockChartSettingSection: {
          props: ['slot2', 'slot3', 'defaultRatios', 'currentRatios', 'canApplyCurrentRatios', 'currentRatiosChanged', 'disableCurrentRatios'],
          emits: ['change', 'saveDefaultRatios', 'applyCurrentRatios'],
          template: '<div><button class="stock-chart-stub" :data-current-ratios="currentRatios.join(\'|\')" @click="$emit(\'change\', \'slot2\', \'macd\')">chart</button><button class="stock-chart-current-stub" @click="$emit(\'change\', \'slot2\', \'volume\')">current</button><button class="stock-chart-ratio-stub" @click="$emit(\'saveDefaultRatios\', [0.52, 0.28, 0.2])">ratio</button><button class="stock-chart-apply-stub" :disabled="!canApplyCurrentRatios || !currentRatiosChanged || disableCurrentRatios" @click="$emit(\'applyCurrentRatios\')">apply</button></div>',
        },
        KlineSettingSection: {
          template: '<div data-testid="kline-setting-section" />',
        },
      },
    },
  })
  return { wrapper, setComponentKnob }
}

function mountMasterDemo(runtimeRatio?: number, save?: () => Promise<boolean | void>) {
  const values = reactive<Record<string, unknown>>({
    masterRatio: 45,
    masterRatioProfiles: {
      profiles: runtimeRatio ? [{ width: 1920, ratio: runtimeRatio }] : [],
    },
  })
  const setComponentKnob = vi.fn((_slotId: string, field: string, value: unknown) => {
    values[field] = value
  })
  const wrapper = mount(ComponentAutoSettings as Component, {
    props: {
      pageKey: 'master-demo',
      runtimeValueOf: vi.fn((_slotId: string, field: string) => (
        field === 'masterRatioProfiles' && runtimeRatio
          ? { width: 1920, ratio: runtimeRatio }
          : runtimeRatio
      )),
      config: {
        componentValueOf: vi.fn((_slotId: string, field: string) => values[field]),
        setComponentKnob,
        save,
      },
    },
    global: {
      stubs: {
        SettingsGroup: { template: '<section><slot /></section>' },
        SourceTag: true,
        AppRowActions: true,
        MasterDetailRatioProfileSettings: {
          props: ['modelValue', 'currentSample', 'disabled', 'saving'],
          emits: ['apply'],
          template: '<button data-testid="master-ratio-profile-save-current" :data-saving="String(Boolean(saving))" :disabled="disabled || !currentSample || saving" @click="$emit(\'apply\', { ratio: currentSample.ratio, profiles: { profiles: [currentSample] } })">使用页面当前比例</button>',
        },
        ElInputNumber: {
          props: ['modelValue'],
          emits: ['update:modelValue'],
          template: '<button class="number-stub" :data-value="modelValue" @click="$emit(\'update:modelValue\', 50)" />',
        },
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
  it('settings-drawer 折叠策略不进入组件设置', () => {
    const wrapper = mountAuto(false)
    expect(wrapper.text()).not.toContain('默认折叠段')
    expect(wrapper.text()).not.toContain('允许折叠分组')
  })

  it('settings-drawer 内容区滚动不进入用户层设置抽屉', () => {
    const wrapper = mountAuto(false)
    expect(wrapper.text()).not.toContain('内容区滚动')
  })

  it('排序字段候选超过三个时使用下拉，避免窄抽屉内分段按钮挤压', () => {
    const wrapper = mountSortDemo()
    expect(wrapper.find('.select-stub').exists()).toBe(true)
    expect(wrapper.find('.ca-select').exists()).toBe(true)
    expect(wrapper.find('.segmented-stub').exists()).toBe(true) // 排序方向仍使用分段控件
    expect(wrapper.text()).toContain('更新时间')
  })

  it('表格边框是 page 层组件能力，不进入用户设置层', () => {
    expect(mountBorderDemo('page').text()).toContain('显示列分隔线')
    expect(mountBorderDemo('user').text()).not.toContain('显示列分隔线')
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

  it('组件组说明与标题共同显示，隐藏组标题时不留下独立问号', async () => {
    const { wrapper } = mountConfigPanelDemo()
    const text = '规则管理、今日打卡和历史详情共用默认值。'
    const hint = () => wrapper.findAllComponents(HelpHint).find(item => item.props('text') === text)!
    const header = wrapper.get('[data-cc-slot="configPanel"] > .sg-head')
    expect(header.text()).toContain('系统设置面板')
    expect(header.text()).not.toContain(text)
    const expanded = header.attributes('aria-expanded')
    await hint().trigger('click')
    await hint().trigger('keydown', { key: 'Enter' })
    await hint().trigger('keydown', { key: ' ' })
    expect(header.attributes('aria-expanded')).toBe(expanded)
    await wrapper.setProps({ showSlotTitle: false })
    expect(hint()).toBeUndefined()
    wrapper.unmount()
  })

  it('较长字段说明统一收进 HelpHint，不在抽屉正文常驻铺开', () => {
    const { wrapper } = mountChartDemo()
    const hint = wrapper.findAllComponents(HelpHint).find((item) => (
      item.props('text') === '这是一段需要收进统一帮助提示而不是常驻铺开的较长说明。'
    ))

    expect(hint).toBeTruthy()
    expect(wrapper.text()).not.toContain('这是一段需要收进统一帮助提示而不是常驻铺开的较长说明。')
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

  it('K 线范围作为图表组件设置渲染，不走页面业务插槽', () => {
    const { wrapper } = mountChartDemo()
    expect(wrapper.find('[data-testid="kline-setting-section"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('K 线范围')
  })

  it('股票多图组合重复选择当前类型时不写入组件配置', async () => {
    const { wrapper, setComponentKnob } = mountChartDemo()
    await wrapper.find('.stock-chart-current-stub').trigger('click')
    expect(setComponentKnob).not.toHaveBeenCalled()
  })

  it('采用页面当前图表比例时原子写回默认比例与当前尺寸档案', async () => {
    const { wrapper, setComponentKnob } = mountChartDemo(true)
    await wrapper.find('.stock-chart-apply-stub').trigger('click')

    expect(setComponentKnob).toHaveBeenCalledWith(
      'chart',
      'stockChart',
      expect.objectContaining({
        heightRatios: expect.objectContaining({
          'kline|volume|macd': [0.5, 0.3, 0.2],
        }),
        heightRatioProfiles: expect.objectContaining({
          'kline|volume|macd': [{
            width: 1280,
            height: 720,
            ratios: [0.5, 0.3, 0.2],
          }],
        }),
      }),
    )
  })

  it('图表会话拖动后抽屉仍回显已配置基线，采用按钮继续读取拖动值', () => {
    const { wrapper } = mountChartDemo(true)

    expect(wrapper.find('.stock-chart-stub').attributes('data-current-ratios'))
      .toBe('0.6|0.2|0.2')
  })

  it('直接编辑图表比例时同步更新当前工作区尺寸档案', async () => {
    const { wrapper, setComponentKnob } = mountChartDemo(true)
    await wrapper.find('.stock-chart-ratio-stub').trigger('click')

    expect(setComponentKnob).toHaveBeenCalledWith(
      'chart',
      'stockChart',
      expect.objectContaining({
        heightRatios: expect.objectContaining({
          'kline|volume|macd': [0.52, 0.28, 0.2],
        }),
        heightRatioProfiles: expect.objectContaining({
          'kline|volume|macd': [{
            width: 1280,
            height: 720,
            ratios: [0.52, 0.28, 0.2],
          }],
        }),
      }),
    )
  })

  it('行情工作台采用页面当前比例时同步更新默认占比与尺寸档案', async () => {
    const { wrapper, setComponentKnob } = mountMasterDemo(48)
    expect(wrapper.get('.number-stub').attributes('data-value')).toBe('48')

    await wrapper.get('[data-testid="master-ratio-profile-save-current"]').trigger('click')
    await nextTick()

    expect(setComponentKnob).toHaveBeenNthCalledWith(1, 'workspace', 'masterRatio', 48)
    expect(setComponentKnob).toHaveBeenNthCalledWith(2, 'workspace', 'masterRatioProfiles', {
      profiles: [{ width: 1920, ratio: 48 }],
    })
    expect(wrapper.get('.number-stub').attributes('data-value')).toBe('48')
  })

  it('采用页面当前比例时锁定按钮直到显式持久化完成', async () => {
    let resolveSave!: () => void
    const save = vi.fn(() => new Promise<void>((resolve) => { resolveSave = resolve }))
    const { wrapper, setComponentKnob } = mountMasterDemo(48, save)
    const button = wrapper.get('[data-testid="master-ratio-profile-save-current"]')

    await button.trigger('click')
    await nextTick()
    expect(button.attributes('data-saving')).toBe('true')
    expect(save).toHaveBeenCalledOnce()
    expect(setComponentKnob).toHaveBeenCalledTimes(2)

    await button.trigger('click')
    expect(setComponentKnob).toHaveBeenCalledTimes(2)

    resolveSave()
    await flushPromises()
    await nextTick()
    expect(button.attributes('data-saving')).toBe('false')
    expect(button.attributes('disabled')).toBeDefined()

    await button.trigger('click')
    expect(save).toHaveBeenCalledOnce()
    expect(setComponentKnob).toHaveBeenCalledTimes(2)
  })

  it('采用页面当前比例保存失败时提示错误并释放按钮供重试', async () => {
    const error = vi.spyOn(ElMessage, 'error').mockReturnValue({} as ReturnType<typeof ElMessage.error>)
    const { wrapper } = mountMasterDemo(48, vi.fn().mockResolvedValue(false))
    const button = wrapper.get('[data-testid="master-ratio-profile-save-current"]')

    await button.trigger('click')
    await flushPromises()
    await nextTick()

    expect(error).toHaveBeenCalledWith('保存失败，请稍后重试')
    expect(button.attributes('data-saving')).toBe('false')
    expect(button.attributes('disabled')).toBeUndefined()

    await button.trigger('click')
    await flushPromises()
    expect(error).toHaveBeenCalledTimes(2)
    error.mockRestore()
  })

  it('保存函数抛出异常时同样提示错误并释放按钮', async () => {
    const error = vi.spyOn(ElMessage, 'error').mockReturnValue({} as ReturnType<typeof ElMessage.error>)
    const { wrapper } = mountMasterDemo(48, vi.fn().mockRejectedValue(new Error('failed')))
    const button = wrapper.get('[data-testid="master-ratio-profile-save-current"]')

    await button.trigger('click')
    await flushPromises()
    await nextTick()

    expect(error).toHaveBeenCalledWith('保存失败，请稍后重试')
    expect(button.attributes('data-saving')).toBe('false')
    error.mockRestore()
  })

  it('行情工作台按尺寸档案或安全边界调整后回显页面实际比例', () => {
    const { wrapper } = mountMasterDemo(43)

    expect(wrapper.get('.number-stub').attributes('data-value')).toBe('43')
  })

  it('直接编辑列表占比时同步更新当前宽度档案，避免旧档案覆盖新值', async () => {
    const { wrapper, setComponentKnob } = mountMasterDemo(48)
    await wrapper.get('.number-stub').trigger('click')

    expect(setComponentKnob).toHaveBeenNthCalledWith(1, 'workspace', 'masterRatio', 50)
    expect(setComponentKnob).toHaveBeenNthCalledWith(2, 'workspace', 'masterRatioProfiles', {
      profiles: [{ width: 1920, ratio: 50 }],
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
    expect(wrapper.findComponent(ElCheckboxGroup).props('modelValue')).toEqual(['auth.login'])

    await wrapper.findComponent(ElCheckboxGroup).vm.$emit('update:modelValue', ['auth'])
    expect(setComponentKnob).toHaveBeenCalledWith('configPanel', 'defaultCollapsed', ['datasource', 'auth'])
  })

  it.each(['page', 'user'] as const)('config-panel 在 %s 层按父组显示子项，父子选值独立', async (layer) => {
    const { wrapper, state } = mountConfigPanelDemo(layer)
    const branch = wrapper.find('[data-collapse-group="auth"]')
    const children = branch.find('[role="group"]')
    expect(children.attributes('aria-label')).toBe('认证与防滥用下级分区')
    expect(children.text()).toBe('登录保护')
    const parent = branch.findComponent(ElCheckbox)
    const child = children.findComponent(ElCheckbox)
    expect(parent.props('value')).toBe('auth')
    expect(child.find<HTMLInputElement>('input').element.checked).toBe(true)
    await parent.find('input').setValue(true)
    expect(state.collapsed).toEqual(['datasource', 'auth.login', 'auth'])
    await child.find('input').setValue(false)
    expect(state.collapsed).toEqual(['datasource', 'auth'])
    await parent.find('input').setValue(false)
    expect(state.collapsed).toEqual(['datasource'])
  })

  it('切换候选范围后保留已选值，缺失父组的候选仍可访问', async () => {
    const { wrapper, state } = mountConfigPanelDemo()
    await wrapper.setProps({ componentMetaOverrides: {
      configPanel: { collapseSections: [{ key: 'datasource', label: '数据源' }] },
    } })
    await wrapper.findComponent(ElCheckbox).find('input').setValue(false)
    expect(state.collapsed).toEqual(['auth.login'])
    await wrapper.setProps({ componentMetaOverrides: {
      configPanel: { collapseSections: [{ key: 'auth.login', label: '登录保护', parentKey: 'auth' }] },
    } })
    expect(wrapper.find('[data-collapse-group="auth.login"]').exists()).toBe(true)
    expect(wrapper.find('[data-collapse-group="auth.login"] .sg-head').exists()).toBe(false)
    expect(wrapper.findComponent(ElCheckbox).find<HTMLInputElement>('input').element.checked).toBe(true)
  })

  it.each(['page', 'user'] as const)('默认折叠清单在 %s 层整体与父组可折叠，折叠和选值互不影响', async (layer) => {
    const { wrapper, state, setComponentKnob } = mountConfigPanelDemo(layer)
    const list = wrapper.get('[data-settings-group-title="默认折叠分区"]')
    const branch = wrapper.get('[data-collapse-group="auth"]')
    const header = branch.get('.sg-head')
    const childInput = branch.get('[role="group"]').get<HTMLInputElement>('input')

    await header.get('.el-checkbox').trigger('click')
    expect(header.attributes('aria-expanded')).toBe('true')
    // 键盘操作复选框同样不能冒泡成为分组展开操作。
    await header.get('input').trigger('keydown', { key: ' ' })
    expect(header.attributes('aria-expanded')).toBe('true')
    const selected = [...state.collapsed]
    setComponentKnob.mockClear()

    await header.trigger('click')
    expect(header.attributes('aria-expanded')).toBe('false')
    expect(branch.get('.sg-body').attributes('style')).toContain('display: none')
    expect(childInput.element.checked).toBe(selected.includes('auth.login'))
    await list.get('.sg-head').trigger('click')
    expect(list.get('.sg-body').attributes('style')).toContain('display: none')
    await list.get('.sg-head').trigger('click')
    expect(header.attributes('aria-expanded')).toBe('false')
    await header.trigger('keydown', { key: 'Enter' })
    expect(header.attributes('aria-expanded')).toBe('true')
    expect(branch.get('.sg-body').attributes('style')).not.toContain('display: none')
    expect(state.collapsed).toEqual(selected)
    expect(setComponentKnob).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('清单与父组通过共享折叠偏好恢复状态，批量收展不写业务默认值', async () => {
    const open = reactive<Record<string, boolean>>({
      'component:configPanel:defaultCollapsed:auth': false,
    })
    const setOpen = vi.fn((key: string, value: boolean) => { open[key] = value })
    const { wrapper, setComponentKnob } = mountConfigPanelDemo('user', {
      enabled: () => true, isOpen: key => open[key], setOpen,
    })
    await nextTick()
    const list = wrapper.get('[data-settings-group-title="默认折叠分区"]')
    expect(list.get('[data-collapse-group="auth"] .sg-head').attributes('aria-expanded')).toBe('false')
    await list.get('button[aria-label="默认折叠分区：展开下级分组"]').trigger('click')
    expect(setOpen).toHaveBeenLastCalledWith('component:configPanel:defaultCollapsed:auth', true)
    await list.get('.sg-head').trigger('click')
    expect(setOpen).toHaveBeenLastCalledWith('component:configPanel:defaultCollapsed', false)
    expect(setComponentKnob).not.toHaveBeenCalled()
    wrapper.unmount()
  })

})
