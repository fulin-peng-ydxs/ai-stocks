// @vitest-environment jsdom
import { defineComponent, nextTick } from 'vue'
import { flushPromises as flushAllPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createLayout, type PageLayout } from '@/layout'
import { useRemoteLayoutConfig } from '@/composables/useRemoteLayoutConfig'
import { pageDensitySyncing, unifyPageDensity } from '@/composables/pageDensitySync'

const layoutApi = vi.hoisted(() => ({
  getEffectiveLayoutConfig: vi.fn(),
  saveLayoutUserConfig: vi.fn(),
  syncLayoutUserDensity: vi.fn(),
}))

vi.mock('@/api/layout', () => layoutApi)
const cleanups: Array<() => void> = []
afterEach(() => cleanups.splice(0).forEach((cleanup) => cleanup()))

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
  cleanups.push(() => wrapper.unmount())
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
    layoutApi.syncLayoutUserDensity.mockImplementation(async (payload) => payload)
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

  it('显式保存会接管已排队的防抖写入，避免同值重复请求', async () => {
    vi.useFakeTimers()
    const { config } = mountHarness(makeLayout())
    await flushPromises()

    config.setComponentKnob('table', 'pageSize', 50)
    await nextTick()
    await config.saveRemoteUserConfig()
    await vi.advanceTimersByTimeAsync(350)

    expect(layoutApi.saveLayoutUserConfig).toHaveBeenCalledTimes(1)
  })

  it('连续保存串行执行并让后发配置最终落库', async () => {
    const firstSave = deferred<unknown>()
    layoutApi.saveLayoutUserConfig
      .mockReturnValueOnce(firstSave.promise)
      .mockResolvedValueOnce({})
    const { config } = mountHarness(makeLayout())
    await flushPromises()

    config.setComponentKnob('table', 'pageSize', 50)
    await nextTick()
    const first = config.saveRemoteUserConfig()
    await flushPromises()
    expect(layoutApi.saveLayoutUserConfig).toHaveBeenCalledTimes(1)

    config.setComponentKnob('table', 'pageSize', 100)
    await nextTick()
    const second = config.saveRemoteUserConfig()
    await flushPromises()
    expect(layoutApi.saveLayoutUserConfig).toHaveBeenCalledTimes(1)

    firstSave.resolve({})
    await Promise.all([first, second])
    expect(layoutApi.saveLayoutUserConfig).toHaveBeenCalledTimes(2)
    expect(layoutApi.saveLayoutUserConfig).toHaveBeenLastCalledWith(
      'remote-page',
      expect.objectContaining({
        config: expect.objectContaining({
          values: expect.objectContaining({ 'slots.table.config.pageSize': 100 }),
        }),
      }),
    )
  })

  it('显式保存失败返回失败结果并保留错误态', async () => {
    layoutApi.saveLayoutUserConfig.mockRejectedValueOnce(new Error('failed'))
    const { config } = mountHarness(makeLayout())
    await flushPromises()

    config.setComponentKnob('table', 'pageSize', 50)
    await nextTick()
    const saved = await config.saveRemoteUserConfig()

    expect(saved).toBe(false)
    expect(config.remoteSaveError.value).toBe(true)
    expect(config.remoteSaving.value).toBe(false)
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

  it('whenRemoteHydrated 在页面/用户生效配置与字段策略都处理完成后才解除等待', async () => {
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

  it('一键同步更新已打开与缓存页面，保留其它配置且仍可逐页调整', async () => {
    vi.useFakeTimers()
    const first = mountHarness(makeLayout('board')).config
    const second = mountHarness(makeLayout('stocks')).config
    await flushAllPromises()
    first.setComponentKnob('table', 'pageSize', 50)
    await unifyPageDensity('compact')
    expect(first.valueOf('density')).toBe('compact')
    expect(second.valueOf('density')).toBe('compact')
    expect(first.componentValueOf('table', 'pageSize')).toBe(50)
    expect(layoutApi.saveLayoutUserConfig).toHaveBeenCalledTimes(1)
    expect(layoutApi.syncLayoutUserDensity).toHaveBeenCalledWith({
      density: 'compact', pageKeys: expect.arrayContaining(['board', 'stocks', 'layout-pages']),
    })
    expect(JSON.parse(localStorage.getItem('ai-stocks:layout:backtest')!).values.density).toBe('compact')
    first.setKnob('density', 'comfortable')
    await vi.advanceTimersByTimeAsync(350)
    expect(first.valueOf('density')).toBe('comfortable')
    expect(second.valueOf('density')).toBe('compact')
    expect(layoutApi.saveLayoutUserConfig).toHaveBeenLastCalledWith('board', expect.objectContaining({
      config: expect.objectContaining({ values: expect.objectContaining({ density: 'comfortable' }) }),
    }))
  })

  it('批量期间的新编辑等到事务完成再保存，写入包含已同步密度', async () => {
    const batch = deferred<{ pageKeys: string[]; density: string }>()
    layoutApi.syncLayoutUserDensity.mockReturnValueOnce(batch.promise)
    const { config } = mountHarness(makeLayout('board'))
    await flushAllPromises()
    const sync = unifyPageDensity('compact')
    await flushAllPromises()
    expect(pageDensitySyncing.value).toBe(true)
    config.setComponentKnob('table', 'pageSize', 100)
    const save = config.saveRemoteUserConfig()
    await flushAllPromises()
    expect(layoutApi.saveLayoutUserConfig).not.toHaveBeenCalled()
    batch.resolve({ density: 'compact', pageKeys: ['board'] })
    await sync
    await save
    expect(layoutApi.saveLayoutUserConfig).toHaveBeenCalledWith('board', expect.objectContaining({
      config: expect.objectContaining({ values: expect.objectContaining({ density: 'compact', 'slots.table.config.pageSize': 100 }) }),
    }))
  })

  it('整批失败不修改页面密度，释放保存屏障并允许重试', async () => {
    const { config } = mountHarness(makeLayout('board'))
    await flushAllPromises()
    layoutApi.syncLayoutUserDensity.mockRejectedValueOnce(new Error('offline'))
    await expect(unifyPageDensity('compact')).rejects.toThrow('offline')
    expect(config.valueOf('density')).toBe('standard')
    expect(pageDensitySyncing.value).toBe(false)
    await unifyPageDensity('compact')
    expect(config.valueOf('density')).toBe('compact')
  })

  it('批量发出之后的新逐页密度选择优先，不被较早操作的响应反向覆盖', async () => {
    const batch = deferred<{ pageKeys: string[]; density: string }>()
    layoutApi.syncLayoutUserDensity.mockReturnValueOnce(batch.promise)
    const { config } = mountHarness(makeLayout('board'))
    await flushAllPromises()
    const sync = unifyPageDensity('compact')
    await flushAllPromises()
    config.setKnob('density', 'comfortable')
    const save = config.saveRemoteUserConfig()
    batch.resolve({ density: 'compact', pageKeys: ['board'] })
    await sync
    await save
    expect(config.valueOf('density')).toBe('comfortable')
    expect(JSON.parse(localStorage.getItem('ai-stocks:layout:board')!).values.density).toBe('comfortable')
    expect(layoutApi.saveLayoutUserConfig).toHaveBeenLastCalledWith('board', expect.objectContaining({
      config: expect.objectContaining({ values: expect.objectContaining({ density: 'comfortable' }) }),
    }))
  })

  it('同步等待旧的加载请求，不让旧响应覆盖同步结果', async () => {
    const remote = deferred<ReturnType<typeof effectiveConfig>>()
    layoutApi.getEffectiveLayoutConfig.mockReturnValueOnce(remote.promise)
    const { config } = mountHarness(makeLayout('board'))
    const sync = unifyPageDensity('compact')
    await flushAllPromises()
    expect(layoutApi.syncLayoutUserDensity).not.toHaveBeenCalled()
    remote.resolve(effectiveConfig({}, { density: 'comfortable' }))
    await sync
    expect(config.valueOf('density')).toBe('compact')
  })

  it('关闭标签时仍会保存防抖窗口内的编辑', async () => {
    vi.useFakeTimers()
    const { config, wrapper } = mountHarness(makeLayout())
    await flushAllPromises()
    config.setKnob('density', 'compact')
    wrapper.unmount()
    await flushAllPromises()
    expect(layoutApi.saveLayoutUserConfig).toHaveBeenCalledWith('remote-page', expect.objectContaining({
      config: expect.objectContaining({ values: expect.objectContaining({ density: 'compact' }) }),
    }))
  })

  it('批量期间再次选择原密度也视为较晚的明确选择', async () => {
    const batch = deferred<{ pageKeys: string[]; density: string }>()
    layoutApi.syncLayoutUserDensity.mockReturnValueOnce(batch.promise)
    const { config } = mountHarness(makeLayout('board'))
    await flushAllPromises()
    const sync = unifyPageDensity('compact')
    await flushAllPromises()
    config.setKnob('density', 'standard')
    const save = config.saveRemoteUserConfig()
    batch.resolve({ density: 'compact', pageKeys: ['board'] })
    await sync
    await save
    expect(config.valueOf('density')).toBe('standard')
  })

  it('卸载后不再等待该页面，账号变化不回填旧账号同步结果', async () => {
    const first = mountHarness(makeLayout('board'))
    await flushAllPromises()
    first.wrapper.unmount()
    const batch = deferred<{ pageKeys: string[]; density: string }>()
    layoutApi.syncLayoutUserDensity.mockReturnValueOnce(batch.promise)
    const sync = unifyPageDensity('compact')
    await flushAllPromises()
    localStorage.setItem('ai-stocks-auth', JSON.stringify({ user: { id: 'other' }, tenant: { id: 'new' } }))
    batch.resolve({ density: 'compact', pageKeys: ['board'] })
    await expect(sync).rejects.toThrow('登录账号已变化')
    expect(first.config.valueOf('density')).toBe('standard')
    expect(pageDensitySyncing.value).toBe(false)
  })
})
