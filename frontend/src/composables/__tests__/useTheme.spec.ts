// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { clearAuth, writeAuth } from '@/api/authToken'
import {
  carryCurrentThemeIntoSession,
  initTheme,
  syncThemePreference,
  toggleTheme,
  useTheme,
} from '@/composables/useTheme'

const prefApi = vi.hoisted(() => ({
  listUserPreferences: vi.fn(),
  saveUserPreference: vi.fn(),
}))

vi.mock('@/api/userPreferences', () => prefApi)

function login(token: string) {
  writeAuth({
    accessToken: token,
    refreshToken: `refresh-${token}`,
    user: { id: `user-${token}`, account: `user-${token}` },
    tenant: { id: 'tenant-a' },
    role: 'normal',
  })
}

describe('登录前后主题连续性', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    clearAuth()
    document.documentElement.classList.remove('dark')
    prefApi.listUserPreferences.mockResolvedValue({ items: [] })
    prefApi.saveUserPreference.mockResolvedValue({})
    initTheme()
  })

  it('登录页当前显示模式优先写回账号，不被旧远端主题覆盖', async () => {
    expect(useTheme().isDark.value).toBe(false)
    carryCurrentThemeIntoSession()
    expect(localStorage.getItem('ai-stocks-theme-pending-sync')).toBe('1')

    login('theme-local-wins')
    prefApi.listUserPreferences.mockResolvedValue({
      items: [{ value: { mode: 'dark' } }],
    })
    await syncThemePreference()

    expect(prefApi.listUserPreferences).not.toHaveBeenCalled()
    expect(prefApi.saveUserPreference).toHaveBeenCalledWith(expect.objectContaining({
      prefKey: 'theme',
      value: { mode: 'light' },
    }))
    expect(localStorage.getItem('ai-stocks-theme-pending-sync')).toBeNull()
    expect(document.documentElement.classList.contains('dark')).toBe(false)
  })

  it('登录页没有新选择时沿用账号已保存主题', async () => {
    login('theme-remote-wins')
    prefApi.listUserPreferences.mockResolvedValue({
      items: [{ value: { mode: 'dark' } }],
    })

    await syncThemePreference()

    expect(useTheme().isDark.value).toBe(true)
    expect(localStorage.getItem('ai-stocks-theme')).toBe('dark')
    expect(document.documentElement.classList.contains('dark')).toBe(true)
  })

  it('写回失败时保持登录页选择并留待下次重试', async () => {
    toggleTheme()
    login('theme-save-retry')
    prefApi.saveUserPreference.mockRejectedValue(new Error('offline'))

    await syncThemePreference()

    expect(prefApi.listUserPreferences).not.toHaveBeenCalled()
    expect(localStorage.getItem('ai-stocks-theme-pending-sync')).toBe('1')
    expect(useTheme().isDark.value).toBe(true)
  })
})
