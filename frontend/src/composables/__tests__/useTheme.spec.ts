// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { clearAuth, writeAuth } from '@/api/authToken'
import {
  carryCurrentThemeIntoSession,
  initTheme,
  setThemeMode,
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
    setThemeMode('light') // 登录页本次明确选了白天
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

  it('setThemeMode 持久化三态意图并写回账号', async () => {
    login('theme-set-mode')

    setThemeMode('system')

    expect(useTheme().themeMode.value).toBe('system')
    expect(localStorage.getItem('ai-stocks-theme')).toBe('system')
    await Promise.resolve()
    expect(prefApi.saveUserPreference).toHaveBeenCalledWith(expect.objectContaining({
      prefKey: 'theme',
      value: { mode: 'system' },
    }))

    setThemeMode('dark')
    expect(useTheme().isDark.value).toBe(true)
    expect(document.documentElement.classList.contains('dark')).toBe(true)
  })

  it('toggleTheme 落到当前可见的反色显式意图', () => {
    setThemeMode('system')
    expect(useTheme().isDark.value).toBe(false) // jsdom 无 matchMedia,系统态兜底白天

    toggleTheme()

    expect(useTheme().themeMode.value).toBe('dark')
    expect(useTheme().isDark.value).toBe(true)
    expect(localStorage.getItem('ai-stocks-theme')).toBe('dark')
  })

  it('远端 system 意图下发后跟随系统兜底并挂载监听', async () => {
    login('theme-remote-system')
    prefApi.listUserPreferences.mockResolvedValue({
      items: [{ value: { mode: 'system' } }],
    })

    await syncThemePreference()

    expect(useTheme().themeMode.value).toBe('system')
    expect(useTheme().isDark.value).toBe(false)
    expect(localStorage.getItem('ai-stocks-theme')).toBe('system')
  })

  it('initTheme 读取本地 system 意图', () => {
    localStorage.setItem('ai-stocks-theme', 'system')

    initTheme()

    expect(useTheme().themeMode.value).toBe('system')
    expect(useTheme().isDark.value).toBe(false)
  })

  it('system 态监听 prefers-color-scheme 变化实时切换', () => {
    const listeners: Array<() => void> = []
    let matches = false
    const mql = {
      get matches() { return matches },
      addEventListener: (_event: string, cb: () => void) => { listeners.push(cb) },
      removeEventListener: (_event: string, cb: () => void) => {
        const idx = listeners.indexOf(cb)
        if (idx >= 0) listeners.splice(idx, 1)
      },
    }
    const originalMatchMedia = window.matchMedia
    // @ts-expect-error 注入最小可用的 matchMedia 实现
    window.matchMedia = () => mql

    try {
      setThemeMode('system')
      expect(useTheme().isDark.value).toBe(false)

      matches = true
      listeners.forEach((cb) => cb())
      expect(useTheme().isDark.value).toBe(true)
      expect(document.documentElement.classList.contains('dark')).toBe(true)

      // 切回显式意图后卸载监听,系统变化不再影响
      setThemeMode('light')
      expect(listeners).toHaveLength(0)
    } finally {
      window.matchMedia = originalMatchMedia
    }
  })
})
