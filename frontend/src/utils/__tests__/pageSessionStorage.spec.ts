// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from 'vitest'
import { writeAuth } from '@/api/authToken'
import {
  clearAllPageSessions,
  pageSessionStorageKey,
  readPageSession,
  removePageSession,
  writePageSession,
} from '@/utils/pageSessionStorage'

describe('pageSessionStorage', () => {
  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
    writeAuth({
      accessToken: 'token', refreshToken: 'refresh',
      user: { id: 'user-a', account: 'a' }, tenant: { id: 'tenant-a' }, role: 'normal',
    })
  })

  it('按命名空间、租户和用户隔离当前 Tab 会话', () => {
    writePageSession('stocks', { view: 'group' })
    expect(pageSessionStorageKey('stocks')).toBe(
      'ai-stocks:page-session:v1:stocks:tenant-a:user-a',
    )
    expect(readPageSession('stocks')).toEqual({ view: 'group' })
    expect(readPageSession('board')).toBeNull()
  })

  it('支持精确清理和退出时前缀清理，不影响无关状态', () => {
    writePageSession('stocks', { view: 'group' })
    writePageSession('board', { date: '2026-09-12' })
    sessionStorage.setItem('unrelated', 'keep')

    removePageSession('stocks')
    expect(readPageSession('stocks')).toBeNull()
    expect(readPageSession('board')).toEqual({ date: '2026-09-12' })

    clearAllPageSessions()
    expect(readPageSession('board')).toBeNull()
    expect(sessionStorage.getItem('unrelated')).toBe('keep')
  })

  it('读取时迁移调用方声明的旧会话键', () => {
    sessionStorage.setItem('legacy:stocks', JSON.stringify({ view: 'list' }))

    expect(readPageSession('stocks', ['legacy:stocks'])).toEqual({ view: 'list' })
    expect(sessionStorage.getItem('legacy:stocks')).toBeNull()
    expect(readPageSession('stocks')).toEqual({ view: 'list' })
  })
})
