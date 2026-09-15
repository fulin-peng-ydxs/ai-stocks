// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import LayoutPresetsView from '../layout/LayoutPresetsView.vue'

const api = vi.hoisted(() => ({ listLayoutPresets: vi.fn(), saveLayoutPreset: vi.fn(), deleteLayoutPreset: vi.fn() }))
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
        plugins: [ElementPlus], directives: { permission: {} },
        stubs: {
          LayoutHost: { template: '<div><slot name="action"/><slot name="main"/><slot name="overlays"/></div>' },
          ElDialog: { props: ['modelValue'], template: '<div v-if="modelValue"><slot/><slot name="footer"/></div>' },
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
      await button('保存').trigger('click')
      await flushPromises()
      const values = api.saveLayoutPreset.mock.calls[0][0].config.values
      expect(Object.keys(values).every((path) => path.startsWith('tokens.'))).toBe(true)
      expect(values).toHaveProperty('tokens.shared.cardRadius')
    } finally { wrapper.unmount() }
  })
})
