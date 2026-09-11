// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import LayoutPresetsView from '../layout/LayoutPresetsView.vue'

const api = vi.hoisted(() => ({ listLayoutPresets: vi.fn(), saveLayoutPreset: vi.fn(), deleteLayoutPreset: vi.fn() }))
vi.mock('@/api/layout', async (importOriginal) => ({
  ...await importOriginal<object>(), ...api,
}))

describe('预设管理缩放字段', () => {
  afterEach(() => { localStorage.clear(); vi.clearAllMocks() })

  it('新增默认显示 0.10，用户输入的零值随预设保存', async () => {
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
      await button('新增预设').trigger('click')
      const input = wrapper.get('input[aria-label="自动缩放激进程度"]')
      expect((input.element as HTMLInputElement).value).toBe('0.10')
      await input.setValue('0')
      await input.trigger('blur')
      await button('保存').trigger('click')
      await flushPromises()
      expect(api.saveLayoutPreset).toHaveBeenCalledWith(expect.objectContaining({
        config: { values: expect.objectContaining({ 'responsiveDefaults.autoScaleResponsiveExponent': 0 }) },
      }))
    } finally { wrapper.unmount() }
  })
})
