// @vitest-environment jsdom
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { writeAuth } from '@/api/authToken'
import * as authApi from '@/api/auth'
import { writePageSession } from '@/utils/pageSessionStorage'
import { useAuthStore } from '../auth'
import { stockSetSessionStorageKey, useStockSet } from '../stockSet'

vi.mock('@/api/auth', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/auth')>()
  return {
    ...actual,
    logout: vi.fn(async () => null),
  }
})

describe('auth store', () => {
  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('已就绪的菜单后台刷新保留工作区就绪态，成功时整体替换权限快照', async () => {
    const auth = useAuthStore()
    auth.menusStatus = 'ready'
    let finish!: (value: authApi.MeResult) => void
    vi.spyOn(authApi, 'getMe').mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
    const pending = auth.fetchMe({ background: true })
    expect(auth.menusStatus).toBe('ready')
    const snapshot = {
      user: { id: 'user-1', account: 'test', email: null, status: 'active' }, tenant: { id: 'tenant-1' },
      role: 'system', menus: [{ index: '/system/menus', title: '菜单功能' }], permissions: ['menu:reorder'],
    } as authApi.MeResult
    finish(snapshot)
    await pending
    expect(auth.menusStatus).toBe('ready')
    expect(auth.menus).toEqual(snapshot.menus)
    expect(auth.permissions).toEqual(['menu:reorder'])
  })

  it('后台刷新失败仍 fail-closed；未就绪时后台选项不能绕过加载门禁', async () => {
    const auth = useAuthStore()
    auth.menusStatus = 'ready'
    vi.spyOn(authApi, 'getMe').mockRejectedValueOnce(new Error('failed'))
    await expect(auth.fetchMe({ background: true })).rejects.toThrow('failed')
    expect(auth.menusStatus).toBe('error')
    let fail!: (error: Error) => void
    vi.spyOn(authApi, 'getMe').mockReturnValueOnce(new Promise((_resolve, reject) => { fail = reject }))
    const pending = auth.fetchMe({ background: true })
    expect(auth.menusStatus).toBe('loading')
    fail(new Error('failed again'))
    await expect(pending).rejects.toThrow('failed again')
    expect(auth.menusStatus).toBe('error')
  })

  it('logout sends the latest persisted refresh token after silent refresh rotation', async () => {
    writeAuth({
      accessToken: 'new-access',
      refreshToken: 'new-refresh',
      user: null,
      tenant: null,
      role: '',
    })
    const auth = useAuthStore()
    auth.refreshToken = 'old-refresh'
    const stockSet = useStockSet()
    stockSet.setSet('list', [{ code: '000001.SZ' }], '查询结果')
    writePageSession('another-page', { keyword: '待清理' })
    expect(sessionStorage.getItem(stockSetSessionStorageKey())).not.toBeNull()

    await auth.logout()

    expect(authApi.logout).toHaveBeenCalledWith('new-refresh')
    expect(auth.refreshToken).toBe('')
    expect(stockSet.items).toEqual([])
    expect(Object.keys(sessionStorage).filter((key) => key.startsWith('ai-stocks:page-session:v1:'))).toEqual([])
  })
})
