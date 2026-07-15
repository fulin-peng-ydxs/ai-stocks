// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { ref, type Ref } from 'vue'
import PageSettingsDrawer, { type DrawerConfig } from '@/components/PageSettingsDrawer.vue'

const prefApi = vi.hoisted(() => ({
  listUserPreferences: vi.fn(),
  saveUserPreference: vi.fn(),
}))

vi.mock('@/api/userPreferences', () => prefApi)

function makeConfig(defaultCollapsedRef: Ref<string[]>) {
  const setComponentKnob = vi.fn()
  const config: DrawerConfig = {
    knobs: [{ path: 'density', label: '信息密度', type: 'enum', options: ['standard'] }],
    valueOf: vi.fn(),
    sourceOf: vi.fn(() => 'default'),
    setKnob: vi.fn(),
    componentValueOf: vi.fn((slotId: string, field: string) => {
      if (slotId !== 'settings') return undefined
      if (field === 'defaultCollapsed') return defaultCollapsedRef.value
      if (field === 'collapsibleSections') return true
      if (field === 'bodyScroll') return true
      if (field === 'size') return 'md'
      return undefined
    }),
    setComponentKnob,
  }
  return { config, setComponentKnob }
}

function mountDrawer(defaultCollapsedRef: Ref<string[]>) {
  const { config, setComponentKnob } = makeConfig(defaultCollapsedRef)
  const wrapper = mount(PageSettingsDrawer, {
    props: {
      modelValue: true,
      config,
      pageKey: 'board',
      businessVisible: true,
    },
    slots: {
      business: '<div>业务内容</div>',
    },
    global: {
      stubs: {
        PageDrawer: {
          props: ['modelValue'],
          template: '<div v-if="modelValue" class="drawer"><slot /></div>',
        },
        SettingsGroup: {
          props: ['title', 'modelValue'],
          emits: ['update:modelValue'],
          template: `
            <section class="settings-group" :data-title="title" :data-open="String(modelValue)">
              <button class="toggle" :data-title="title" @click="$emit('update:modelValue', !modelValue)">
                {{ title }}
              </button>
              <div v-show="modelValue"><slot /></div>
            </section>
          `,
        },
        LayoutSettingsSection: true,
        ComponentAutoSettings: {
          props: ['config'],
          template: `
            <div>
              <button class="set-drawer-size" @click="config.setComponentKnob('settings', 'size', 'lg')" />
              <button class="set-drawer-collapsed" @click="config.setComponentKnob('settings', 'defaultCollapsed', ['layout'])" />
            </div>
          `,
        },
        AppIconButton: { template: '<button type="button"><slot /></button>' },
        ElButton: { template: '<button type="button"><slot /></button>' },
        ElIcon: { template: '<span><slot /></span>' },
      },
    },
  })
  return { wrapper, setComponentKnob }
}

function groupOpen(wrapper: ReturnType<typeof mount>, title: string): string | undefined {
  return wrapper.find(`.settings-group[data-title="${title}"]`).attributes('data-open')
}

describe('PageSettingsDrawer', () => {
  beforeEach(() => {
    prefApi.listUserPreferences.mockResolvedValue({ items: [] })
    prefApi.saveUserPreference.mockResolvedValue({})
  })

  it('点击折叠段只改变抽屉运行态，不写入默认折叠配置', async () => {
    const defaults = ref<string[]>([])
    const { wrapper, setComponentKnob } = mountDrawer(defaults)

    expect(groupOpen(wrapper, '布局')).toBe('true')
    await wrapper.find('.toggle[data-title="布局"]').trigger('click')

    expect(groupOpen(wrapper, '布局')).toBe('false')
    expect(setComponentKnob).not.toHaveBeenCalled()
  })

  it('每次打开抽屉时从当前默认折叠配置重新初始化运行态', async () => {
    const defaults = ref<string[]>(['layout'])
    const { wrapper, setComponentKnob } = mountDrawer(defaults)

    expect(groupOpen(wrapper, '布局')).toBe('false')
    await wrapper.find('.toggle[data-title="布局"]').trigger('click')
    expect(groupOpen(wrapper, '布局')).toBe('true')

    await wrapper.setProps({ modelValue: false })
    defaults.value = ['business']
    await wrapper.setProps({ modelValue: true })

    expect(groupOpen(wrapper, '布局')).toBe('true')
    expect(groupOpen(wrapper, '业务选项')).toBe('false')
    expect(setComponentKnob).not.toHaveBeenCalled()
  })

  it('抽屉自身偏好写入全局 user_preference，不写页面组件配置', async () => {
    vi.useFakeTimers()
    const defaults = ref<string[]>([])
    const { wrapper, setComponentKnob } = mountDrawer(defaults)

    await wrapper.find('.set-drawer-size').trigger('click')
    await vi.advanceTimersByTimeAsync(350)

    expect(setComponentKnob).not.toHaveBeenCalled()
    expect(prefApi.saveUserPreference).toHaveBeenCalledWith(expect.objectContaining({
      scope: 'global',
      prefKey: 'settings-drawer',
      value: expect.objectContaining({ size: 'lg' }),
    }))
    vi.useRealTimers()
  })
})
