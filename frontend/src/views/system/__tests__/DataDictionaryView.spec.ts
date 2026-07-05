// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'
import { computed, defineComponent, h, inject, provide, ref, type Component, type ComputedRef } from 'vue'
import { useAuthStore } from '@/stores/auth'
import DataDictionaryView from '@/views/system/DataDictionaryView.vue'

vi.mock('@/api/dict', () => ({
  listDictTypes: vi.fn(),
  listDictItems: vi.fn(),
  createDictType: vi.fn(),
  updateDictType: vi.fn(),
  deleteDictType: vi.fn(),
  createDictItem: vi.fn(),
  updateDictItem: vi.fn(),
  deleteDictItem: vi.fn(),
}))
vi.mock('@/composables/useRemoteLayoutConfig', () => ({
  useRemoteLayoutConfig: () => ({
    effective: {},
    knobs: [],
    setKnob: vi.fn(),
    valueOf: vi.fn(),
    sourceOf: vi.fn(),
    isDirty: ref(false),
    resetAll: vi.fn(),
    componentValueOf: vi.fn((_slot: string, field: string) => (field === 'pageSize' ? 50 : [])),
    setComponentKnob: vi.fn(),
    componentSourceOf: vi.fn(),
    layerValuesOf: vi.fn(),
    componentLayerValuesOf: vi.fn(),
  }),
}))

import * as dictApi from '@/api/dict'

const typeRows = [
  {
    id: 't1',
    code: 'user_status',
    name: '用户状态',
    enabled: true,
    sort: 10,
    remark: '账号状态',
    item_count: 1,
    updated_at: '2026-07-05T10:00:00+00:00',
  },
  {
    id: 't2',
    code: 'audit_result',
    name: '审计结果',
    enabled: true,
    sort: 20,
    remark: null,
    item_count: 0,
    updated_at: '2026-07-05T10:00:00+00:00',
  },
]

const itemRows = [
  {
    id: 'i1',
    type_code: 'user_status',
    code: 'active',
    label: '启用',
    enabled: true,
    sort: 10,
    remark: '可登录',
    updated_at: '2026-07-05T10:00:00+00:00',
  },
]

const tableRowsKey = Symbol('tableRows')

const ElTableStub = defineComponent({
  name: 'ElTable',
  props: {
    data: { type: Array, default: () => [] },
  },
  setup(props, { slots }) {
    provide(tableRowsKey, computed(() => props.data))
    return () => h('div', { class: 'el-table' }, [
      slots.default?.(),
      props.data.length === 0 ? slots.empty?.() : null,
    ])
  },
})

const ElTableColumnStub = defineComponent({
  name: 'ElTableColumn',
  props: {
    prop: { type: String, default: '' },
  },
  setup(props, { slots }) {
    const rows = inject<ComputedRef<Record<string, unknown>[]>>(tableRowsKey, computed(() => []))
    return () => h('div', { class: 'el-table-column' }, rows.value.map((row) => (
      h('div', { class: 'el-table-cell' }, slots.default ? slots.default({ row }) : String(row[props.prop] ?? ''))
    )))
  },
})

const ElSelectStub = defineComponent({
  name: 'ElSelect',
  props: {
    modelValue: { type: [String, Number, Boolean], default: '' },
  },
  emits: ['update:modelValue', 'change'],
  setup(props, { emit, slots }) {
    return () => h('select', {
      class: 'el-select',
      value: props.modelValue as string,
      onChange: (event: Event) => {
        const value = (event.target as HTMLSelectElement).value
        emit('update:modelValue', value)
        emit('change', value)
      },
    }, slots.default?.())
  },
})

const ElOptionStub = defineComponent({
  name: 'ElOption',
  props: {
    label: { type: String, required: true },
    value: { type: String, required: true },
  },
  setup(props) {
    return () => h('option', { value: props.value }, props.label)
  },
})

const stubs = {
  LayoutHost: {
    template: '<div><slot name="action"/><slot name="main"/><slot name="overlays"/></div>',
  },
  PageSettingsDrawer: true,
  PageSettingsTrigger: true,
  HelpTip: { template: '<span><slot/></span>' },
  ElTable: ElTableStub,
  ElTableColumn: ElTableColumnStub,
  ElSelect: ElSelectStub,
  ElOption: ElOptionStub,
  teleport: true,
}

function mockHappyApis() {
  ;(dictApi.listDictTypes as ReturnType<typeof vi.fn>).mockResolvedValue({
    list: typeRows,
    total: typeRows.length,
    page: 1,
    size: 200,
  })
  ;(dictApi.listDictItems as ReturnType<typeof vi.fn>).mockResolvedValue({
    list: itemRows,
    total: itemRows.length,
    page: 1,
    size: 50,
  })
  ;(dictApi.createDictType as ReturnType<typeof vi.fn>).mockResolvedValue(typeRows[0])
  ;(dictApi.updateDictType as ReturnType<typeof vi.fn>).mockResolvedValue(typeRows[0])
  ;(dictApi.deleteDictType as ReturnType<typeof vi.fn>).mockResolvedValue(undefined)
  ;(dictApi.createDictItem as ReturnType<typeof vi.fn>).mockResolvedValue(itemRows[0])
  ;(dictApi.updateDictItem as ReturnType<typeof vi.fn>).mockResolvedValue(itemRows[0])
  ;(dictApi.deleteDictItem as ReturnType<typeof vi.fn>).mockResolvedValue(undefined)
}

async function mountView(role = 'system'): Promise<VueWrapper> {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.role = role
  auth.permissions = role === 'system' ? ['dict:type-manage', 'dict:item-manage'] : []
  auth.menusStatus = 'ready'
  auth.tenant = { id: 'tenant-a' }
  const wrapper = mount(DataDictionaryView as Component, {
    attachTo: document.body,
    global: {
      plugins: [pinia, ElementPlus],
      stubs,
      directives: { permission: {} },
    },
  })
  await flushPromises()
  await wrapper.vm.$nextTick()
  return wrapper
}

function buttonByText(wrapper: VueWrapper, text: string) {
  const button = wrapper.findAll('button').find((node) => node.text() === text)
  expect(button, `未找到按钮：${text}`).toBeTruthy()
  return button!
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  document.body.innerHTML = ''
  mockHappyApis()
})

afterEach(() => {
  document.body.innerHTML = ''
})

describe('DataDictionaryView', () => {
  it('加载字典类型和当前类型的字典项', async () => {
    const wrapper = await mountView()
    expect(wrapper.text()).toContain('数据字典')
    expect(wrapper.text()).toContain('用户状态')
    expect(wrapper.text()).toContain('active')
    expect(dictApi.listDictItems).toHaveBeenCalledWith(expect.objectContaining({
      type_code: 'user_status',
      page: 1,
      size: 50,
    }))
  })

  it('切换左侧类型后按新类型加载字典项', async () => {
    const wrapper = await mountView()
    const typeButton = wrapper.findAll('button').find((node) => node.text().includes('audit_result'))
    expect(typeButton).toBeTruthy()
    await typeButton!.trigger('click')
    await flushPromises()
    expect(dictApi.listDictItems).toHaveBeenLastCalledWith(expect.objectContaining({
      type_code: 'audit_result',
    }))
  })

  it('查询字典项时透传关键字和启用状态', async () => {
    localStorage.setItem(
      'ai-stocks:page-settings:data-dictionary',
      JSON.stringify({
        selectedTypeCode: '',
        typeKeyword: '',
        itemKeyword: '',
        itemEnabled: 'false',
      }),
    )
    const wrapper = await mountView()
    await wrapper.find('input[placeholder="搜索字典项 code / 名称"]').setValue('active')
    await wrapper.find('.dict-item-filters button').trigger('click')
    await flushPromises()
    expect(dictApi.listDictItems).toHaveBeenLastCalledWith(expect.objectContaining({
      q: 'active',
      enabled: false,
    }))
  })

  it('新建类型提交 code，编辑类型不提交 code', async () => {
    const wrapper = await mountView()
    await buttonByText(wrapper, '新建类型').trigger('click')
    await flushPromises()
    await wrapper.find('input[placeholder="如 user_status"]').setValue('tenant_state')
    await wrapper.find('input[placeholder="如 用户状态"]').setValue('租户状态')
    await buttonByText(wrapper, '保存').trigger('click')
    await flushPromises()
    expect(dictApi.createDictType).toHaveBeenCalledWith(expect.objectContaining({
      code: 'tenant_state',
      name: '租户状态',
    }))

    await buttonByText(wrapper, '编辑类型').trigger('click')
    await flushPromises()
    const codeInput = wrapper.find('input[placeholder="如 user_status"]')
    expect(codeInput.attributes('disabled')).toBeDefined()
    await codeInput.setValue('changed_code')
    await wrapper.find('input[placeholder="如 用户状态"]').setValue('用户状态编辑')
    await buttonByText(wrapper, '保存').trigger('click')
    await flushPromises()
    const updateBody = (dictApi.updateDictType as ReturnType<typeof vi.fn>).mock.calls.at(-1)?.[1]
    expect(dictApi.updateDictType).toHaveBeenLastCalledWith('user_status', expect.any(Object))
    expect(updateBody).not.toHaveProperty('code')
  })

  it('编辑字典项时禁用 type/code，保存不提交 type_code/code', async () => {
    const wrapper = await mountView()
    const edit = wrapper.findAll('button').find((node) => node.text() === '编辑')
    expect(edit).toBeTruthy()
    await edit!.trigger('click')
    await flushPromises()
    const disabledInputs = wrapper.findAll('input').filter((input) => (
      (input.element as HTMLInputElement).disabled
    ))
    expect(disabledInputs.length).toBeGreaterThanOrEqual(2)
    await wrapper.find('input[placeholder="如 启用"]').setValue('启用编辑')
    await buttonByText(wrapper, '保存').trigger('click')
    await flushPromises()
    const updateBody = (dictApi.updateDictItem as ReturnType<typeof vi.fn>).mock.calls.at(-1)?.[2]
    expect(dictApi.updateDictItem).toHaveBeenLastCalledWith('user_status', 'active', expect.any(Object))
    expect(updateBody).not.toHaveProperty('type_code')
    expect(updateBody).not.toHaveProperty('code')
  })

  it('类型加载失败显示错误态，重试后恢复', async () => {
    ;(dictApi.listDictTypes as ReturnType<typeof vi.fn>)
      .mockRejectedValueOnce(new Error('boom'))
      .mockResolvedValueOnce({ list: typeRows, total: typeRows.length, page: 1, size: 200 })
    const wrapper = await mountView()
    expect(wrapper.text()).toContain('类型加载失败')
    await buttonByText(wrapper, '重试').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('用户状态')
  })

  it('非 system 角色显示权限态且不请求字典接口', async () => {
    const wrapper = await mountView('tenant_admin')
    expect(wrapper.text()).toContain('无权限维护数据字典')
    expect(dictApi.listDictTypes).not.toHaveBeenCalled()
    expect(dictApi.listDictItems).not.toHaveBeenCalled()
  })
})
