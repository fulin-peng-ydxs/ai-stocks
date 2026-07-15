// @vitest-environment jsdom
import { nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { clearAuth, writeAuth } from '@/api/authToken'
import {
  resetDrawerPreferencesForTests,
  syncDrawerPreferences,
  useDrawerPreferences,
} from '@/composables/useDrawerPreferences'

const prefApi = vi.hoisted(() => ({
  listUserPreferences: vi.fn(),
  saveUserPreference: vi.fn(),
}))

vi.mock('@/api/userPreferences', () => prefApi)

function login(userId: string, token = `token-${userId}`) {
  writeAuth({
    accessToken: token,
    refreshToken: `refresh-${userId}`,
    user: { id: userId, account: userId },
    tenant: { id: 'tenant-a' },
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

describe('useDrawerPreferences', () => {
  beforeEach(() => {
    vi.useRealTimers()
    clearAuth()
    localStorage.clear()
    resetDrawerPreferencesForTests()
    vi.clearAllMocks()
    prefApi.listUserPreferences.mockResolvedValue({ items: [] })
    prefApi.saveUserPreference.mockResolvedValue({})
  })

  it('未登录时使用匿名 localStorage fallback，不请求远端', async () => {
    localStorage.setItem('ai-stocks:drawer-preferences:anonymous', JSON.stringify({ size: 'lg' }))

    const pref = useDrawerPreferences()
    await flushPromises()
    pref.setDefaultCollapsed(['layout'])
    await flushPromises()

    expect(pref.size.value).toBe('lg')
    expect(pref.defaultCollapsed.value).toEqual(['layout'])
    expect(prefApi.listUserPreferences).not.toHaveBeenCalled()
    expect(prefApi.saveUserPreference).not.toHaveBeenCalled()
    expect(JSON.parse(localStorage.getItem('ai-stocks:drawer-preferences:anonymous') || '{}'))
      .toEqual({ size: 'lg', defaultCollapsed: ['layout'] })
  })

  it('同标签页换用户后重新按新 token 拉取，避免沿用上一用户抽屉偏好', async () => {
    login('user-a')
    prefApi.listUserPreferences.mockResolvedValueOnce({ items: [{ value: { size: 'lg' } }] })

    const pref = useDrawerPreferences()
    await flushPromises()
    expect(pref.size.value).toBe('lg')

    login('user-b')
    prefApi.listUserPreferences.mockResolvedValueOnce({ items: [{ value: { size: 'sm' } }] })
    await syncDrawerPreferences()
    await flushPromises()

    expect(pref.size.value).toBe('sm')
    expect(prefApi.listUserPreferences).toHaveBeenCalledTimes(2)
  })

  it('不同登录用户使用独立本地 fallback key', async () => {
    login('user-a')
    prefApi.listUserPreferences.mockResolvedValueOnce({ items: [{ value: { size: 'lg' } }] })
    const pref = useDrawerPreferences()
    await flushPromises()
    expect(pref.size.value).toBe('lg')
    expect(JSON.parse(localStorage.getItem('ai-stocks:drawer-preferences:tenant-a:user-a') || '{}'))
      .toEqual({ size: 'lg' })

    login('user-b')
    prefApi.listUserPreferences.mockResolvedValueOnce({ items: [] })
    await syncDrawerPreferences()
    await flushPromises()

    expect(pref.size.value).toBeUndefined()
    expect(localStorage.getItem('ai-stocks:drawer-preferences:tenant-a:user-b')).toBe('{}')
  })

  it('远端加载期间的本地编辑不被旧响应覆盖，并回写当前用户远端', async () => {
    vi.useFakeTimers()
    login('user-a')
    const remote = deferred<{ items: Array<{ value: { size: string } }> }>()
    prefApi.listUserPreferences.mockReturnValue(remote.promise)

    const pref = useDrawerPreferences()
    pref.setSize('sm')
    remote.resolve({ items: [{ value: { size: 'lg' } }] })
    await flushPromises()
    await vi.runOnlyPendingTimersAsync()

    expect(pref.size.value).toBe('sm')
    expect(prefApi.saveUserPreference).toHaveBeenCalledWith(expect.objectContaining({
      scope: 'global',
      pageKey: '',
      prefKey: 'settings-drawer',
      value: { size: 'sm' },
    }))
  })
})
