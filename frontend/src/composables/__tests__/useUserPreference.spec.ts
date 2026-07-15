// @vitest-environment jsdom
import { nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useUserPreference } from '@/composables/useUserPreference'
import { writeAuth } from '@/api/authToken'

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
})
