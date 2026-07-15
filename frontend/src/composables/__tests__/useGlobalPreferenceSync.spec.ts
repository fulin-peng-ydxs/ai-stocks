// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { clearAuth, writeAuth } from '@/api/authToken'
import { createGlobalPreferenceSync } from '@/composables/useGlobalPreferenceSync'

const prefApi = vi.hoisted(() => ({
  listUserPreferences: vi.fn(),
  saveUserPreference: vi.fn(),
}))

vi.mock('@/api/userPreferences', () => prefApi)

function login(token = 'token-a') {
  writeAuth({
    accessToken: token,
    refreshToken: `refresh-${token}`,
    user: { id: `user-${token}`, account: `user-${token}` },
    tenant: { id: 'tenant-a' },
    role: 'normal',
  })
}

describe('createGlobalPreferenceSync', () => {
  beforeEach(() => {
    vi.useRealTimers()
    vi.clearAllMocks()
    localStorage.clear()
    clearAuth()
    prefApi.listUserPreferences.mockResolvedValue({ items: [] })
    prefApi.saveUserPreference.mockResolvedValue({})
  })

  it('按 token 守卫全局偏好同步，同一登录态只拉取一次', async () => {
    login('token-a')
    const applied: unknown[] = []
    prefApi.listUserPreferences.mockResolvedValueOnce({ items: [{ value: { mode: 'dark' } }] })

    const sync = createGlobalPreferenceSync({
      prefKey: 'theme',
      snapshot: () => ({ mode: 'light' }),
      normalize: (value) => value as { mode: string } | undefined,
      applyRemote: (value) => {
        applied.push(value)
      },
    })

    await sync.syncOnce()
    await sync.syncOnce()

    expect(prefApi.listUserPreferences).toHaveBeenCalledTimes(1)
    expect(applied).toEqual([{ mode: 'dark' }])
  })

  it('远端缺失时保存当前本地快照，登录身份变化后重新同步', async () => {
    login('token-a')
    let current = 'dual-topbar'
    const sync = createGlobalPreferenceSync({
      prefKey: 'navigation',
      snapshot: () => ({ mode: current }),
      normalize: (value) => {
        const mode = (value as { mode?: unknown } | undefined)?.mode
        return typeof mode === 'string' ? { mode } : undefined
      },
      applyRemote: (value) => { current = value.mode },
    })

    await sync.syncOnce()
    expect(prefApi.saveUserPreference).toHaveBeenCalledWith(expect.objectContaining({
      scope: 'global',
      prefKey: 'navigation',
      value: { mode: 'dual-topbar' },
    }))

    prefApi.listUserPreferences.mockResolvedValueOnce({ items: [{ value: { mode: 'sidebar-tabs' } }] })
    login('token-b')
    await sync.syncOnce()

    expect(current).toBe('sidebar-tabs')
    expect(prefApi.listUserPreferences).toHaveBeenCalledTimes(2)
  })

  it('debounce 保存远端偏好，未登录时只执行本地持久化回调', async () => {
    vi.useFakeTimers()
    const persistLocal = vi.fn()
    let value = 'light'
    const sync = createGlobalPreferenceSync({
      prefKey: 'theme',
      snapshot: () => ({ mode: value }),
      normalize: (remote) => remote as { mode: string } | undefined,
      applyRemote: vi.fn(),
      persistLocal,
    })

    sync.scheduleSave()
    await vi.advanceTimersByTimeAsync(350)
    expect(persistLocal).toHaveBeenCalledTimes(1)
    expect(prefApi.saveUserPreference).not.toHaveBeenCalled()

    login()
    value = 'dark'
    sync.scheduleSave()
    value = 'light'
    sync.scheduleSave()
    await vi.advanceTimersByTimeAsync(350)

    expect(prefApi.saveUserPreference).toHaveBeenCalledTimes(1)
    expect(prefApi.saveUserPreference).toHaveBeenCalledWith(expect.objectContaining({
      prefKey: 'theme',
      value: { mode: 'light' },
    }))
    vi.useRealTimers()
  })
})
