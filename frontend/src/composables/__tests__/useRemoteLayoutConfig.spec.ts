// @vitest-environment jsdom
import { defineComponent, nextTick } from 'vue'
import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createLayout, type PageLayout } from '@/layout'
import { useRemoteLayoutConfig } from '@/composables/useRemoteLayoutConfig'

const layoutApi = vi.hoisted(() => ({
  getEffectiveLayoutConfig: vi.fn(),
  saveLayoutUserConfig: vi.fn(),
}))

vi.mock('@/api/layout', () => layoutApi)

function makeLayout(pageKey = 'remote-page'): PageLayout {
  const layout = createLayout('list', pageKey)
  layout.slots.push({ id: 'settings', component: 'settings-drawer', region: 'overlay', order: 99 })
  return layout
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((r) => {
    resolve = r
  })
  return { promise, resolve }
}

async function flushPromises(): Promise<void> {
  await Promise.resolve()
  await Promise.resolve()
  await nextTick()
}

function mountHarness(layout: PageLayout) {
  let config!: ReturnType<typeof useRemoteLayoutConfig>
  const Harness = defineComponent({
    setup() {
      config = useRemoteLayoutConfig(layout)
      return {}
    },
    template: '<div />',
  })
  const wrapper = mount(Harness)
  return { wrapper, get config() { return config } }
}

function effectiveConfig(
  pageValues: Record<string, unknown> = {},
  userValues: Record<string, unknown> = {},
) {
  return {
    pageKey: 'remote-page',
    userId: 'u',
    presetKey: null,
    schemaVersion: 1,
    values: { ...pageValues, ...userValues },
    source: {},
    layers: [
      { layer: 'page', config: { schemaVersion: 1, values: pageValues } },
      { layer: 'user', config: { schemaVersion: 1, values: userValues } },
    ],
    componentFieldPolicies: [],
  }
}

describe('useRemoteLayoutConfig', () => {
  beforeEach(() => {
    vi.useRealTimers()
    vi.clearAllMocks()
    localStorage.clear()
    layoutApi.getEffectiveLayoutConfig.mockResolvedValue(effectiveConfig())
    layoutApi.saveLayoutUserConfig.mockResolvedValue({
      userId: 'u',
      pageKey: 'remote-page',
      config: { schemaVersion: 1, values: {} },
    })
  })

  it('用户修改组件配置后 debounce 保存，并携带真实 PageLayout 做后端归属校验', async () => {
    vi.useFakeTimers()
    const layout = makeLayout()
    const { config } = mountHarness(layout)
    await flushPromises()

    config.setComponentKnob('table', 'pageSize', 50)
    await vi.advanceTimersByTimeAsync(350)

    expect(layoutApi.saveLayoutUserConfig).toHaveBeenCalledTimes(1)
    expect(layoutApi.saveLayoutUserConfig).toHaveBeenCalledWith('remote-page', expect.objectContaining({
      config: expect.objectContaining({
        values: expect.objectContaining({ 'slots.table.config.pageSize': 50 }),
      }),
      layout: expect.objectContaining({
        pageKey: 'remote-page',
        slots: expect.arrayContaining([expect.objectContaining({ id: 'table', component: 'data-table' })]),
      }),
    }))
  })

  it('远端用户层返回时保留加载期间的本地编辑并回写 PG', async () => {
    vi.useFakeTimers()
    const effectiveReq = deferred<ReturnType<typeof effectiveConfig>>()
    layoutApi.getEffectiveLayoutConfig.mockReturnValue(effectiveReq.promise)
    const { config } = mountHarness(makeLayout())

    config.setKnob('density', 'comfortable')
    effectiveReq.resolve(effectiveConfig({}, { density: 'compact' }))
    await flushPromises()

    expect(config.valueOf('density')).toBe('comfortable')
    expect(layoutApi.saveLayoutUserConfig).toHaveBeenCalledWith('remote-page', expect.objectContaining({
      config: expect.objectContaining({
        values: expect.objectContaining({ density: 'comfortable' }),
      }),
    }))
  })

  it('whenRemoteHydrated 在四层生效配置与字段策略都处理完成后才解除等待', async () => {
    const effectiveReq = deferred<ReturnType<typeof effectiveConfig>>()
    layoutApi.getEffectiveLayoutConfig.mockReturnValue(effectiveReq.promise)
    const { config } = mountHarness(makeLayout())
    let completed = false
    void config.whenRemoteHydrated().then(() => { completed = true })
    await flushPromises()
    expect(completed).toBe(false)

    effectiveReq.resolve(effectiveConfig())
    await config.whenRemoteHydrated()
    expect(config.remoteHydrated.value).toBe(true)
    expect(completed).toBe(true)
  })

  it('管理员收紧字段策略后，历史用户值不再进入实际效果且写入入口同步拒绝', async () => {
    layoutApi.getEffectiveLayoutConfig.mockResolvedValue({
      ...effectiveConfig({}, { 'slots.table.config.pageSize': 100 }),
      componentFieldPolicies: [{
        componentKind: 'data-table',
        field: 'pageSize',
        maxLayers: ['preset', 'page', 'user'],
        allowedLayers: ['preset', 'page'],
        overridden: true,
      }],
    })
    const { config } = mountHarness(makeLayout())
    await config.whenRemoteHydrated()

    expect(config.componentValueOf('table', 'pageSize')).toBe(20)
    expect(() => config.setComponentKnob('table', 'pageSize', 50)).toThrow('当前字段策略不允许用户层修改')
    expect(config.exportUserConfig().values).not.toHaveProperty('slots.table.config.pageSize')
  })
})
