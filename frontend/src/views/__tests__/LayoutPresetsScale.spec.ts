// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createPinia } from 'pinia'
import LayoutPresetsView from '../layout/LayoutPresetsView.vue'

const api = vi.hoisted(() => ({
  listLayoutPresets: vi.fn(), saveLayoutPreset: vi.fn(), deleteLayoutPreset: vi.fn(),
  getEffectiveLayoutConfig: vi.fn().mockResolvedValue({ layers: [], componentFieldPolicies: [] }),
}))
vi.mock('@/api/layout', async (importOriginal) => ({
  ...await importOriginal<object>(), ...api,
}))

describe('视觉预设字段边界', () => {
  afterEach(() => { localStorage.clear(); vi.clearAllMocks() })

  it('不再展示密度和自动缩放字段，仅保存视觉 token', async () => {
    api.listLayoutPresets.mockResolvedValue({ presets: [] })
    api.saveLayoutPreset.mockImplementation(async (value) => value)
    const wrapper = mount(LayoutPresetsView, {
      global: {
        plugins: [ElementPlus, createPinia()], directives: { permission: {} },
        stubs: {
          LayoutHost: { template: '<div><slot name="action"/><slot name="main"/><slot name="overlays"/></div>' },
          AppDetailDrawer: { props: ['modelValue'], template: '<div v-if="modelValue"><slot/><slot name="footer"/></div>' },
          AppDataTable: true,
        },
      },
    })
    try {
      await flushPromises()
      const button = (text: string) => wrapper.findAll('button').find((item) => item.text() === text)!
      await button('新增视觉预设').trigger('click')
      expect(wrapper.text()).not.toContain('自动缩放激进程度')
      expect(wrapper.text()).not.toContain('表格密度')
      expect(wrapper.find('.el-switch').exists()).toBe(false)
      const saveButton = button('保存')
      expect(saveButton.attributes('disabled')).toBeDefined()
      const nameInput = wrapper.findAll('input').find((input) => input.element.value === '自定义预设')!
      await nameInput.setValue('自定义预设 2')
      expect(saveButton.attributes('disabled')).toBeUndefined()
      await saveButton.trigger('click')
      await flushPromises()
      const values = api.saveLayoutPreset.mock.calls[0][0].config.values
      expect(Object.keys(values).every((path) => path.startsWith('tokens.'))).toBe(true)
      expect(values).toHaveProperty('tokens.shared.cardRadius')
    } finally { wrapper.unmount() }
  })

  it('保存后重新编辑读取最新 token，停用项保存仍保持停用', async () => {
    let record = {
      key: 'custom-status', name: '状态测试', description: '', enabled: false, is_builtin: false,
      schemaVersion: 1, config: { values: { 'tokens.shared.controlRadius': 6 } },
    }
    api.listLayoutPresets.mockImplementation(async () => ({ presets: [structuredClone(record)] }))
    api.saveLayoutPreset.mockImplementation(async (value) => {
      record = structuredClone(value)
      return record
    })
    const wrapper = mount(LayoutPresetsView, {
      global: {
        plugins: [ElementPlus, createPinia()], directives: { permission: {} },
        stubs: {
          LayoutHost: { template: '<div><slot name="action"/><slot name="main"/><slot name="overlays"/></div>' },
          AppDetailDrawer: { props: ['modelValue'], template: '<div v-if="modelValue"><slot/><slot name="footer"/></div>' },
        },
      },
    })
    try {
      await flushPromises()
      const button = (text: string) => wrapper.findAll('button').find((item) => item.text() === text)!
      await button('编辑').trigger('click')
      await flushPromises()
      const numberInputs = wrapper.findAll('input[role="spinbutton"]')
      await numberInputs[1].setValue('9')
      await numberInputs[1].trigger('change')
      await numberInputs[1].trigger('blur')
      await button('保存').trigger('click')
      await flushPromises()
      expect(api.saveLayoutPreset.mock.lastCall?.[0].enabled).toBe(false)
      expect(api.saveLayoutPreset.mock.lastCall?.[0].config.values['tokens.shared.controlRadius']).toBe(9)
      await button('编辑').trigger('click')
      await flushPromises()
      expect(wrapper.findAll<HTMLInputElement>('input[role="spinbutton"]')[1].element.value).toBe('9')
    } finally { wrapper.unmount() }
  })
})
