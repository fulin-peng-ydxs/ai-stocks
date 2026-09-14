// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick, ref, type Ref } from 'vue'
import PageSettingsDrawer, { type DrawerConfig } from '@/components/PageSettingsDrawer.vue'
import { clearAuth, writeAuth } from '@/api/authToken'
import { resetDrawerPreferencesForTests } from '@/composables/useDrawerPreferences'

const prefApi = vi.hoisted(() => ({
  listUserPreferences: vi.fn(),
  saveUserPreference: vi.fn(),
}))

vi.mock('@/api/userPreferences', () => prefApi)

function login() {
  writeAuth({
    accessToken: 'token',
    refreshToken: 'refresh',
    user: { id: 'u', account: 'u' },
    tenant: { id: 't' },
    role: 'normal',
  })
}

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
    },
    slots: {
      business: '<div>业务内容</div>',
    },
    global: {
      stubs: {
        PageDrawer: {
          props: ['modelValue', 'size'],
          template: '<div v-if="modelValue" class="drawer" :data-size="size"><slot /></div>',
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
          name: 'ComponentAutoSettings',
          props: ['config', 'slotIds', 'componentMetaOverrides', 'showSlotTitle', 'runtimeValueOf'],
          template: `
            <div class="component-auto-settings" :data-slot-ids="slotIds?.join(',')" :data-show-slot-title="String(showSlotTitle)">
              <button class="set-drawer-size" @click="config.setComponentKnob('settings', 'size', 'lg')" />
              <button class="set-drawer-collapsed" @click="config.setComponentKnob('settings', 'defaultCollapsed', ['layout'])" />
            </div>
          `,
        },
        AppIconButton: { template: '<button type="button"><slot /></button>' },
        AppStateBlock: {
          props: ['state', 'title', 'description'],
          template: '<div class="state-block">{{ title }}{{ description }}</div>',
        },
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

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((r) => {
    resolve = r
  })
  return { promise, resolve }
}

async function flushPromises() {
  await Promise.resolve()
  await Promise.resolve()
  await nextTick()
}

describe('PageSettingsDrawer', () => {
  beforeEach(() => {
    vi.useRealTimers()
    vi.clearAllMocks()
    clearAuth()
    localStorage.clear()
    resetDrawerPreferencesForTests()
    prefApi.listUserPreferences.mockResolvedValue({ items: [] })
    prefApi.saveUserPreference.mockResolvedValue({})
  })

  it('提供业务插槽且未传 businessVisible 时默认显示业务选项', () => {
    const { wrapper } = mountDrawer(ref([]))

    expect(wrapper.find('.settings-group[data-title="业务选项"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('业务内容')
  })

  it('显式传入 businessVisible=false 时隐藏业务选项', async () => {
    const { wrapper } = mountDrawer(ref([]))

    await wrapper.setProps({ businessVisible: false })

    expect(wrapper.find('.settings-group[data-title="业务选项"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('业务内容')
  })

  it('点击折叠段只改变抽屉运行态，不写入默认折叠配置', async () => {
    const defaults = ref<string[]>([])
    const { wrapper, setComponentKnob } = mountDrawer(defaults)

    expect(groupOpen(wrapper, '布局')).toBe('true')
    await wrapper.find('.toggle[data-title="布局"]').trigger('click')

    expect(groupOpen(wrapper, '布局')).toBe('false')
    expect(setComponentKnob).not.toHaveBeenCalled()
  })

  it('把运行时 slot 与元数据过滤条件透传给组件设置', async () => {
    const defaults = ref<string[]>([])
    const { wrapper } = mountDrawer(defaults)
    const overrides = {
      table: {
        columns: [{ key: 'code', label: '代码' }],
      },
    }

    await wrapper.setProps({
      componentSlotIds: ['table'],
      componentMetaOverrides: overrides,
    })

    const autoSettings = wrapper.findComponent({ name: 'ComponentAutoSettings' })
    expect(autoSettings.props('slotIds')).toEqual(['table'])
    expect(autoSettings.props('componentMetaOverrides')).toEqual(overrides)
  })

  it('当前策略关闭全部个人组件字段时不渲染空组件段', async () => {
    const defaults = ref<string[]>([])
    const { wrapper } = mountDrawer(defaults)
    const current = wrapper.props('config')!

    await wrapper.setProps({
      config: {
        ...current,
        componentAllowedLayers: () => ['page'],
      },
    })

    expect(wrapper.find('.settings-group[data-title="组件设置"]').exists()).toBe(false)
  })

  it('策略关闭抽屉尺寸个人层后，已存全局偏好不再进入实际效果', async () => {
    login()
    prefApi.listUserPreferences.mockResolvedValueOnce({ items: [{ value: { size: 'lg' } }] })
    const defaults = ref<string[]>([])
    const { wrapper } = mountDrawer(defaults)
    const current = wrapper.props('config')!
    await flushPromises()
    expect(wrapper.find('.drawer').attributes('data-size')).toBe('lg')

    await wrapper.setProps({
      config: {
        ...current,
        componentAllowedLayers: (kind: string, field: string) =>
          kind === 'settings-drawer' && field === 'size' ? ['page'] : undefined,
      },
    })

    expect(wrapper.find('.drawer').attributes('data-size')).toBe('md')
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
    login()
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

  it('恢复默认同时清除抽屉自身偏好并继续触发页面重置', async () => {
    login()
    vi.useFakeTimers()
    const defaults = ref<string[]>([])
    const { wrapper, setComponentKnob } = mountDrawer(defaults)

    await wrapper.find('.set-drawer-size').trigger('click')
    await vi.advanceTimersByTimeAsync(350)
    prefApi.saveUserPreference.mockClear()

    await wrapper.find('.ps-reset').trigger('click')
    await vi.advanceTimersByTimeAsync(350)

    expect(setComponentKnob).not.toHaveBeenCalled()
    expect(wrapper.emitted('reset')).toHaveLength(1)
    expect(prefApi.saveUserPreference).toHaveBeenCalledWith(expect.objectContaining({
      scope: 'global',
      prefKey: 'settings-drawer',
      value: {},
    }))
    vi.useRealTimers()
  })

  it('抽屉偏好同步中和远端失败时给出轻量状态提示', async () => {
    login()
    const remote = deferred<{ items: unknown[] }>()
    prefApi.listUserPreferences.mockReturnValue(remote.promise)
    const { wrapper } = mountDrawer(ref([]))

    expect(wrapper.text()).toContain('正在同步抽屉偏好')

    remote.resolve({ items: [] })
    await vi.waitFor(() => {
      expect(wrapper.text()).not.toContain('正在同步抽屉偏好')
    })
    wrapper.unmount()

    resetDrawerPreferencesForTests()
    prefApi.listUserPreferences.mockReset()
    prefApi.listUserPreferences.mockRejectedValue(new Error('failed'))
    const { wrapper: failedWrapper } = mountDrawer(ref([]))

    await vi.waitFor(() => {
      expect(failedWrapper.text()).toContain('抽屉偏好暂用本地设置')
    })
  })
})
