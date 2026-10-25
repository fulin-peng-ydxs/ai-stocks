// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import PageDensitySyncSettings from '../PageDensitySyncSettings.vue'

const api = vi.hoisted(() => ({ syncLayoutUserDensity: vi.fn() }))
vi.mock('@/api/layout', async (original) => ({ ...await original<object>(), ...api }))
afterEach(() => { vi.clearAllMocks(); localStorage.clear() })

describe('一键统一密度入口', () => {
  it('仅点击应用才同步，失败保留选择并支持重试，成功说明结果', async () => {
    api.syncLayoutUserDensity.mockRejectedValueOnce(new Error('同步失败'))
      .mockImplementation(async (payload) => payload)
    const wrapper = mount(PageDensitySyncSettings, {
      global: { plugins: [ElementPlus], directives: { permission: {} } },
    })
    try {
      await wrapper.get('button[aria-pressed="false"]').trigger('click')
      expect(api.syncLayoutUserDensity).not.toHaveBeenCalled()
      const apply = wrapper.findAll('button').find((button) => button.text() === '统一应用')!
      await apply.trigger('click')
      await flushPromises()
      expect(wrapper.get('[role="alert"]').text()).toContain('同步失败')
      expect(wrapper.get('button[aria-pressed="true"]').text()).toBe('紧凑')
      await wrapper.findAll('button').find((button) => button.text() === '重试')!.trigger('click')
      await flushPromises()
      expect(api.syncLayoutUserDensity).toHaveBeenCalledTimes(2)
      expect(wrapper.get('[role="status"]').text()).toContain('统一为紧凑密度')
      expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    } finally { wrapper.unmount() }
  })
})
