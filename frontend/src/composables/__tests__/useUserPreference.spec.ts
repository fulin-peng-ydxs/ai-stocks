// @vitest-environment jsdom
import { computed, nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useUserPreference } from '@/composables/useUserPreference'
import { writeAuth } from '@/api/authToken'
import {
  createDefaultStockChartPreferences,
  useStockChartPreferences,
} from '@/composables/useStockChartPreferences'

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

describe('useUserPreference', () => {
  beforeEach(() => {
    vi.useRealTimers()
    vi.clearAllMocks()
    localStorage.clear()
    prefApi.listUserPreferences.mockResolvedValue({ items: [] })
    prefApi.saveUserPreference.mockResolvedValue({})
  })

  it('无登录态时只使用 localStorage fallback，不请求远端', async () => {
    localStorage.setItem('pref:test', JSON.stringify({ density: 'compact' }))
    const pref = useUserPreference({
      scope: 'page',
      pageKey: 'board',
      prefKey: 'settings',
      defaults: { density: 'standard' },
      localStorageKey: 'pref:test',
    })
    await flushPromises()

    expect(pref.value.density).toBe('compact')
    expect(pref.hydrated.value).toBe(true)
    expect(prefApi.listUserPreferences).not.toHaveBeenCalled()
  })

  it('登录后远端偏好覆盖本地 fallback', async () => {
    login()
    localStorage.setItem('pref:test', JSON.stringify({ density: 'compact' }))
    prefApi.listUserPreferences.mockResolvedValue({
      items: [{ value: { density: 'comfortable' } }],
    })

    const pref = useUserPreference({
      scope: 'page',
      pageKey: 'board',
      prefKey: 'settings',
      defaults: { density: 'standard' },
      localStorageKey: 'pref:test',
    })
    await flushPromises()

    expect(pref.value.density).toBe('comfortable')
    expect(JSON.parse(localStorage.getItem('pref:test') || '{}')).toEqual({ density: 'comfortable' })
  })

  it('whenHydrated 等待远端偏好完成后再放行页面初始化', async () => {
    login()
    const remote = deferred<{ items: Array<{ value: { density: string } }> }>()
    prefApi.listUserPreferences.mockReturnValue(remote.promise)
    const pref = useUserPreference({
      scope: 'page',
      pageKey: 'board',
      prefKey: 'settings',
      defaults: { density: 'standard' },
      localStorageKey: 'pref:test',
    })
    let released = false
    const waiting = pref.whenHydrated().then(() => { released = true })
    await flushPromises()
    expect(released).toBe(false)

    remote.resolve({ items: [{ value: { density: 'comfortable' } }] })
    await waiting
    expect(pref.value.density).toBe('comfortable')
    expect(released).toBe(true)
  })

  it('远端加载期间的本地编辑不会被覆盖，并会回写远端', async () => {
    login()
    const remote = deferred<{ items: Array<{ value: { density: string } }> }>()
    prefApi.listUserPreferences.mockReturnValue(remote.promise)

    const pref = useUserPreference({
      scope: 'page',
      pageKey: 'board',
      prefKey: 'settings',
      defaults: { density: 'standard' },
      localStorageKey: 'pref:test',
    })
    pref.value.density = 'comfortable'
    remote.resolve({ items: [{ value: { density: 'compact' } }] })
    await flushPromises()

    expect(pref.value.density).toBe('comfortable')
    expect(prefApi.saveUserPreference).toHaveBeenCalledWith(expect.objectContaining({
      scope: 'page',
      pageKey: 'board',
      prefKey: 'settings',
      value: { density: 'comfortable' },
    }))
  })

  it('远端读取失败后显式保存成功会清除降级错误态', async () => {
    login()
    prefApi.listUserPreferences.mockRejectedValueOnce(new Error('offline'))
    const pref = useUserPreference({
      scope: 'page',
      pageKey: 'limit-ladder',
      prefKey: 'settings',
      defaults: { window: 31 },
      localStorageKey: 'pref:limit-ladder',
    })
    await pref.whenHydrated()
    expect(pref.remoteError.value).toBe(true)

    pref.value.window = 20
    await pref.saveRemoteNow()

    expect(pref.saveError.value).toBe(false)
    expect(pref.remoteError.value).toBe(false)
  })

  it('图表组合在远端返回前被编辑时继续遵守 dirty-before-hydrate', async () => {
    login()
    const remote = deferred<{ items: Array<{ value: {
      charts: ReturnType<typeof createDefaultStockChartPreferences>
    } }> }>()
    prefApi.listUserPreferences.mockReturnValue(remote.promise)
    const defaults = { charts: createDefaultStockChartPreferences() }
    const pref = useUserPreference({
      scope: 'page',
      pageKey: 'stock-detail',
      prefKey: 'settings',
      defaults,
      localStorageKey: 'pref:stock-detail',
    })
    const charts = computed({
      get: () => pref.value.charts,
      set: (value) => {
        pref.value.charts = value
      },
    })
    const model = useStockChartPreferences(charts, pref.hydrated)

    model.setSlotType('slot2', 'hidden')
    const remoteCharts = createDefaultStockChartPreferences()
    remoteCharts.slot2 = 'macd'
    remoteCharts.slot3 = 'volume'
    remote.resolve({ items: [{ value: { charts: remoteCharts } }] })
    await flushPromises()

    expect(pref.value.charts.slot2).toBe('hidden')
    expect(prefApi.saveUserPreference).toHaveBeenCalledWith(expect.objectContaining({
      scope: 'page',
      pageKey: 'stock-detail',
      prefKey: 'settings',
      value: expect.objectContaining({
        charts: expect.objectContaining({ slot2: 'hidden', slot3: 'macd' }),
      }),
    }))
  })
})
