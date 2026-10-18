// @vitest-environment jsdom
import { flushPromises } from '@vue/test-utils'
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
    pref.setCollapsedSections(['layout'])
    await flushPromises()

    expect(pref.size.value).toBe('lg')
    expect(pref.collapsedSections.value).toEqual(['layout'])
    expect(prefApi.listUserPreferences).not.toHaveBeenCalled()
    expect(prefApi.saveUserPreference).not.toHaveBeenCalled()
    expect(JSON.parse(localStorage.getItem('ai-stocks:drawer-preferences:anonymous') || '{}'))
      .toEqual({ size: 'lg', collapsedSections: ['layout'] })
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

  it('reset 清空抽屉自身偏好并保存空对象', async () => {
    vi.useFakeTimers()
    login('user-a')
    prefApi.listUserPreferences.mockResolvedValueOnce({ items: [{ value: { size: 'lg', defaultCollapsed: ['layout'] } }] })

    const pref = useDrawerPreferences()
    await flushPromises()
    expect(pref.size.value).toBe('lg')

    pref.reset()
    await vi.runOnlyPendingTimersAsync()

    expect(pref.size.value).toBeUndefined()
    expect(pref.collapsedSections.value).toBeUndefined()
    expect(JSON.parse(localStorage.getItem('ai-stocks:drawer-preferences:tenant-a:user-a') || '{}'))
      .toEqual({})
    expect(prefApi.saveUserPreference).toHaveBeenCalledWith(expect.objectContaining({
      scope: 'global',
      prefKey: 'settings-drawer',
      value: {},
    }))
  })

  it('读取旧 defaultCollapsed 偏好但新写入统一改为 collapsedSections', async () => {
    vi.useFakeTimers()
    login('user-a')
    prefApi.listUserPreferences.mockResolvedValueOnce({ items: [{ value: { defaultCollapsed: ['business'] } }] })

    const pref = useDrawerPreferences()
    await flushPromises()
    expect(pref.collapsedSections.value).toEqual(['business'])

    pref.setCollapsedSections(['layout', 'business'])
    await vi.runOnlyPendingTimersAsync()

    expect(prefApi.saveUserPreference).toHaveBeenCalledWith(expect.objectContaining({
      value: { collapsedSections: ['layout', 'business'] },
    }))
  })

  it('子节点按页面隔离并持久化，恢复当前页默认不清除其他页面记忆', async () => {
    login('user-a')
    const pref = useDrawerPreferences()
    await flushPromises()
    pref.setGroupOpen('board', 'component:table', false)
    pref.setGroupOpen('stocks', 'component:table', false)
    await flushPromises()
    expect(pref.groupOpen('board', 'component:table')).toBe(false)
    expect(pref.groupOpen('quality', 'component:table')).toBeUndefined()

    pref.reset('board')
    await flushPromises()
    expect(pref.groupOpen('board', 'component:table')).toBe(true)
    expect(pref.groupOpen('stocks', 'component:table')).toBe(false)
    expect(prefApi.saveUserPreference).toHaveBeenLastCalledWith(expect.objectContaining({
      value: { collapsedGroups: { board: [], stocks: ['component:table'] } },
    }))
  })

  it('立即刷新保留待同步操作，旧远端值不覆盖，同时合并未编辑页面', async () => {
    login('user-a')
    localStorage.setItem('ai-stocks:drawer-preferences:tenant-a:user-a', JSON.stringify({
      collapsedSections: ['layout'],
      collapsedGroups: { board: ['component:table'] },
      pending: { fields: ['collapsedSections'], pages: ['board'] },
    }))
    prefApi.listUserPreferences.mockResolvedValueOnce({ items: [{ value: {
      size: 'lg', collapsedSections: [],
      collapsedGroups: { board: [], stocks: ['layout:base'] },
    } }] })
    const pref = useDrawerPreferences()
    await flushPromises()
    expect(pref.collapsedSections.value).toEqual(['layout'])
    expect(pref.groupOpen('board', 'component:table')).toBe(false)
    expect(pref.groupOpen('stocks', 'layout:base')).toBe(false)
    expect(pref.size.value).toBe('lg')
    expect(prefApi.saveUserPreference).toHaveBeenLastCalledWith(expect.objectContaining({
      value: { size: 'lg', collapsedSections: ['layout'], collapsedGroups: {
        board: ['component:table'], stocks: ['layout:base'],
      } },
    }))
    await flushPromises()
    expect(JSON.parse(localStorage.getItem('ai-stocks:drawer-preferences:tenant-a:user-a')!)).not.toHaveProperty('pending')
  })

  it('水合期间的操作等待远端合并后保存，不提前覆盖未读取的其他页面', async () => {
    login('user-a')
    const remote = deferred<{ items: Array<{ value: unknown }> }>()
    prefApi.listUserPreferences.mockReturnValueOnce(remote.promise)
    const pref = useDrawerPreferences()
    pref.setGroupOpen('board', 'layout:base', false)
    await flushPromises()
    expect(prefApi.saveUserPreference).not.toHaveBeenCalled()
    remote.resolve({ items: [{ value: { collapsedGroups: { stocks: ['component:table'] } } }] })
    await flushPromises()
    expect(prefApi.saveUserPreference).toHaveBeenCalledWith(expect.objectContaining({
      value: { collapsedGroups: { stocks: ['component:table'], board: ['layout:base'] } },
    }))
  })

  it('连续选择串行落库，慢请求完成后仍保存最后的选择', async () => {
    login('user-a')
    const pref = useDrawerPreferences()
    await flushPromises()
    const slow = deferred<unknown>()
    prefApi.saveUserPreference.mockReturnValueOnce(slow.promise)
    pref.setGroupOpen('board', 'layout:base', false)
    await flushPromises()
    pref.setGroupOpen('board', 'layout:base', true)
    pref.setGroupOpen('board', 'component:table', false)
    await flushPromises()
    expect(prefApi.saveUserPreference).toHaveBeenCalledTimes(1)
    slow.resolve({})
    await flushPromises()
    await flushPromises()
    expect(prefApi.saveUserPreference).toHaveBeenCalledTimes(2)
    expect(prefApi.saveUserPreference).toHaveBeenLastCalledWith(expect.objectContaining({
      value: { collapsedGroups: { board: ['component:table'] } },
    }))
  })

  it('旧账号的保存失败不污染新账号，页面记忆也按身份隔离', async () => {
    login('user-a')
    const pref = useDrawerPreferences()
    await flushPromises()
    const slow = deferred<unknown>()
    prefApi.saveUserPreference.mockReturnValueOnce(slow.promise)
    pref.setGroupOpen('board', 'layout:base', false)
    await flushPromises()
    login('user-b')
    await syncDrawerPreferences()
    expect(pref.groupOpen('board', 'layout:base')).toBeUndefined()
    slow.resolve(Promise.reject(new Error('旧账号失败')))
    await flushPromises()
    expect(pref.failed.value).toBe(false)
  })

  it('保存失败保留待同步意图，刷新重试时不会被旧云端记录反向覆盖', async () => {
    login('user-a')
    const pref = useDrawerPreferences()
    await flushPromises()
    prefApi.saveUserPreference.mockRejectedValueOnce(new Error('离线'))
    pref.setGroupOpen('board', 'layout:base', false)
    await flushPromises()
    expect(pref.failed.value).toBe(true)
    expect(JSON.parse(localStorage.getItem('ai-stocks:drawer-preferences:tenant-a:user-a')!))
      .toHaveProperty('pending.pages', ['board'])
    resetDrawerPreferencesForTests()
    prefApi.listUserPreferences.mockResolvedValueOnce({ items: [{ value: { collapsedGroups: { board: [] } } }] })
    const restored = useDrawerPreferences()
    await flushPromises()
    expect(restored.groupOpen('board', 'layout:base')).toBe(false)
    expect(restored.failed.value).toBe(false)
    expect(prefApi.saveUserPreference).toHaveBeenLastCalledWith(expect.objectContaining({
      value: { collapsedGroups: { board: ['layout:base'] } },
    }))
  })

  it('已挂载页面中登录 token 更新后，下一次操作会重新水合并继续保存', async () => {
    login('user-a')
    const pref = useDrawerPreferences()
    await flushPromises()
    login('user-a', 'refreshed-token')
    pref.setGroupOpen('board', 'layout:base', false)
    await flushPromises()
    expect(pref.hydrated.value).toBe(true)
    expect(prefApi.listUserPreferences).toHaveBeenCalledTimes(2)
    expect(prefApi.saveUserPreference).toHaveBeenLastCalledWith(expect.objectContaining({
      value: { collapsedGroups: { board: ['layout:base'] } },
    }))
  })
})
