// @vitest-environment jsdom
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { writeAuth } from '@/api/authToken'
import * as authApi from '@/api/auth'
import { useAuthStore } from '../auth'

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
    setActivePinia(createPinia())
    vi.clearAllMocks()
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

    await auth.logout()

    expect(authApi.logout).toHaveBeenCalledWith('new-refresh')
    expect(auth.refreshToken).toBe('')
  })
})
