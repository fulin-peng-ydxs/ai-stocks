// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { clearAuth, writeAuth } from '@/api/authToken'
import { resetWorkspaceTabPreferencesForTests, useWorkspaceTabPreferences } from '@/composables/useWorkspaceTabPreferences'

const api = vi.hoisted(() => ({ listUserPreferences: vi.fn(), saveUserPreference: vi.fn() }))
vi.mock('@/api/userPreferences', () => api)

function login(id: string) {
  writeAuth({ accessToken: id, refreshToken: id, user: { id, account: id }, tenant: { id: 't' }, role: 'normal' })
}
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(done => { resolve = done })
  return { promise, resolve }
}
async function settle() { for (let index = 0; index < 8; index += 1) await Promise.resolve() }

describe('工作页签折叠偏好', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.clearAllMocks()
    clearAuth()
    localStorage.clear()
    resetWorkspaceTabPreferencesForTests()
    api.listUserPreferences.mockResolvedValue({ items: [] })
    api.saveUserPreference.mockResolvedValue({})
  })
  afterEach(() => { resetWorkspaceTabPreferencesForTests(); vi.useRealTimers() })

  it('默认折叠，匿名刷新从本地恢复操作后的状态', () => {
    const pref = useWorkspaceTabPreferences()
    expect(pref.collapsed.value).toBe(true)
    pref.setCollapsed(false)
    resetWorkspaceTabPreferencesForTests()
    expect(useWorkspaceTabPreferences().collapsed.value).toBe(false)
    expect(api.listUserPreferences).not.toHaveBeenCalled()
  })

  it('恢复账号偏好并自动把切换写入既有 PG 偏好接口', async () => {
    login('a')
    api.listUserPreferences.mockResolvedValue({ items: [{ value: { collapsed: false } }] })
    const pref = useWorkspaceTabPreferences()
    await settle()
    expect(pref.collapsed.value).toBe(false)
    pref.setCollapsed(true)
    await vi.runOnlyPendingTimersAsync()
    expect(api.saveUserPreference).toHaveBeenLastCalledWith(expect.objectContaining({
      scope: 'global', prefKey: 'workspace-tabs', value: { collapsed: true },
    }))
  })

  it('加载期间手动展开不被晚到的折叠状态覆盖', async () => {
    login('a')
    const request = deferred<{ items: { value: { collapsed: boolean } }[] }>()
    api.listUserPreferences.mockReturnValue(request.promise)
    const pref = useWorkspaceTabPreferences()
    pref.setCollapsed(false)
    await settle()
    request.resolve({ items: [{ value: { collapsed: true } }] })
    await settle()
    await vi.runOnlyPendingTimersAsync()
    expect(pref.collapsed.value).toBe(false)
    expect(api.saveUserPreference).toHaveBeenLastCalledWith(expect.objectContaining({ value: { collapsed: false } }))
  })

  it('保存尚未完成就刷新，待同步意图优先于旧远端并重新保存', async () => {
    login('a')
    const saving = deferred<unknown>()
    api.saveUserPreference.mockReturnValueOnce(saving.promise)
    api.listUserPreferences.mockResolvedValue({ items: [{ value: { collapsed: true } }] })
    const pref = useWorkspaceTabPreferences()
    await settle()
    pref.setCollapsed(false)
    resetWorkspaceTabPreferencesForTests()
    const refreshed = useWorkspaceTabPreferences()
    await settle()
    expect(refreshed.collapsed.value).toBe(false)
    expect(api.saveUserPreference).toHaveBeenLastCalledWith(expect.objectContaining({ value: { collapsed: false } }))
    saving.resolve({})
    await settle()
  })

  it('连续切换按顺序保存，慢请求不能覆盖最后一次选择', async () => {
    login('a')
    const firstSave = deferred<unknown>()
    api.saveUserPreference.mockReturnValueOnce(firstSave.promise)
    const pref = useWorkspaceTabPreferences()
    await settle()
    pref.setCollapsed(false)
    await settle()
    pref.setCollapsed(true)
    await settle()
    expect(api.saveUserPreference).toHaveBeenCalledTimes(1)
    firstSave.resolve({})
    await settle()
    expect(api.saveUserPreference).toHaveBeenCalledTimes(2)
    expect(api.saveUserPreference).toHaveBeenLastCalledWith(expect.objectContaining({ value: { collapsed: true } }))
  })

  it('换账号后晚到的旧响应不得覆盖新账号，登出也不沿用上一账号', async () => {
    login('a')
    const oldRequest = deferred<{ items: { value: { collapsed: boolean } }[] }>()
    api.listUserPreferences.mockReturnValueOnce(oldRequest.promise)
    const pref = useWorkspaceTabPreferences()
    pref.setCollapsed(false)
    login('b')
    useWorkspaceTabPreferences()
    await settle()
    oldRequest.resolve({ items: [{ value: { collapsed: false } }] })
    await settle()
    expect(pref.collapsed.value).toBe(true)
    expect(JSON.parse(localStorage.getItem('ai-stocks:workspace-tabs:t:b') || '{}').collapsed).toBe(true)
    clearAuth()
    useWorkspaceTabPreferences()
    expect(pref.collapsed.value).toBe(true)
  })
})
