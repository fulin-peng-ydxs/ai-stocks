// @vitest-environment jsdom
import { defineComponent, nextTick } from 'vue'
import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createLayout, type PageLayout } from '@/layout'
import { useRemoteLayoutConfig } from '@/composables/useRemoteLayoutConfig'

const layoutApi = vi.hoisted(() => ({
  getLayoutPageConfig: vi.fn(),
  getLayoutUserConfig: vi.fn(),
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

describe('useRemoteLayoutConfig', () => {
  beforeEach(() => {
    vi.useRealTimers()
    vi.clearAllMocks()
    localStorage.clear()
    layoutApi.getLayoutPageConfig.mockResolvedValue({
      pageKey: 'remote-page',
      presetKey: null,
      config: { schemaVersion: 1, values: {} },
    })
    layoutApi.getLayoutUserConfig.mockResolvedValue({
      userId: 'u',
      pageKey: 'remote-page',
      config: { schemaVersion: 1, values: {} },
    })
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
    const userReq = deferred<{
      userId: string
      pageKey: string
      config: { schemaVersion: number; values: Record<string, unknown> }
    }>()
    layoutApi.getLayoutUserConfig.mockReturnValue(userReq.promise)
    const { config } = mountHarness(makeLayout())

    config.setKnob('density', 'comfortable')
    userReq.resolve({
      userId: 'u',
      pageKey: 'remote-page',
      config: { schemaVersion: 1, values: { density: 'compact' } },
    })
    await flushPromises()

    expect(config.valueOf('density')).toBe('comfortable')
    expect(layoutApi.saveLayoutUserConfig).toHaveBeenCalledWith('remote-page', expect.objectContaining({
      config: expect.objectContaining({
        values: expect.objectContaining({ density: 'comfortable' }),
      }),
    }))
  })
})
