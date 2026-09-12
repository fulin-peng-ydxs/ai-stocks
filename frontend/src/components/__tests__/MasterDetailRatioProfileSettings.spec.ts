// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ElementPlus from 'element-plus'
import MasterDetailRatioProfileSettings from '@/components/MasterDetailRatioProfileSettings.vue'

function mountSettings(props: Record<string, unknown>) {
  return mount(MasterDetailRatioProfileSettings, {
    props,
    global: { plugins: [ElementPlus] },
  })
}

describe('MasterDetailRatioProfileSettings', () => {
  it('只展示紧凑采用按钮并保存当前工作区比例', async () => {
    const wrapper = mountSettings({
      modelValue: { profiles: [{ width: 1280, ratio: 50 }, { width: 1920, ratio: 45 }] },
      currentSample: { width: 1840, ratio: 46 },
    })

    expect(wrapper.text()).toBe('使用页面当前比例')

    await wrapper.get('[data-testid="master-ratio-profile-save-current"]').trigger('click')
    expect(wrapper.emitted('apply')?.at(-1)).toEqual([{
      ratio: 46,
      profiles: {
        profiles: [{ width: 1280, ratio: 50 }, { width: 1840, ratio: 46 }],
      },
    }])
  })

  it('单区模式禁用采用按钮', () => {
    const wrapper = mountSettings({ modelValue: { profiles: [{ width: 1280, ratio: 50 }] } })

    expect(wrapper.get('[data-testid="master-ratio-profile-save-current"]').attributes('disabled')).toBeDefined()
  })
})
