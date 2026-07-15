// @vitest-environment jsdom
import type { AxiosAdapter, InternalAxiosRequestConfig } from 'axios'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ElMessage } from 'element-plus'

import http from '../client'
import { readAuth, writeAuth } from '../authToken'

vi.mock('element-plus', () => ({
  ElMessage: { error: vi.fn() },
}))

const ok = (config: InternalAxiosRequestConfig, data: unknown) => ({
  data: { code: 0, msg: '', data },
  status: 200,
  statusText: 'OK',
  headers: {},
  config,
})

function authHeader(config: InternalAxiosRequestConfig): string {
  const headers = config.headers
  if (typeof headers?.get === 'function') return String(headers.get('Authorization') || '')
  return String((headers as Record<string, string>)?.Authorization || '')
}

describe('api client silent refresh', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()
    vi.clearAllMocks()
    window.history.pushState({}, '', '/board')
    writeAuth({
      accessToken: 'old-access',
      refreshToken: 'refresh-token',
      user: null,
      tenant: null,
      role: '',
    })
  })

  it('single-flights concurrent 401 refresh and replays original requests', async () => {
    const seenAuth: string[] = []
    const fetchMock = vi.fn(async () => ({
      json: async () => ({
        code: 0,
        msg: '',
        data: { access_token: 'new-access', refresh_token: 'new-refresh' },
      }),
    }))
    vi.stubGlobal('fetch', fetchMock)

    const adapter: AxiosAdapter = async (config) => {
      const auth = authHeader(config)
      seenAuth.push(auth)
      if (auth === 'Bearer old-access') {
        return Promise.reject({
          config,
          response: { status: 401, data: { msg: 'expired' } },
        })
      }
      return ok(config, { auth })
    }
    http.defaults.adapter = adapter

    const [a, b] = await Promise.all([
      http.get<{ auth: string }>('/protected-a'),
      http.get<{ auth: string }>('/protected-b'),
    ]) as unknown as [{ auth: string }, { auth: string }]

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(a.auth).toBe('Bearer new-access')
    expect(b.auth).toBe('Bearer new-access')
    expect(seenAuth).toEqual([
      'Bearer old-access',
      'Bearer old-access',
      'Bearer new-access',
      'Bearer new-access',
    ])
    expect(readAuth().accessToken).toBe('new-access')
    expect(readAuth().refreshToken).toBe('new-refresh')
  })

  it('clears auth when refresh fails', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({
      json: async () => ({ code: 401, msg: 'refresh expired', data: null }),
    })))
    const adapter: AxiosAdapter = async (config) => Promise.reject({
      config,
      response: { status: 401, data: { msg: 'expired' } },
    })
    http.defaults.adapter = adapter

    await expect(http.get('/protected')).rejects.toBeTruthy()

    expect(readAuth().accessToken).toBe('')
    expect(readAuth().refreshToken).toBe('')
  })

  it('does not show login error toast for stale protected requests that finish on login page', async () => {
    window.history.pushState({}, '', '/login')
    writeAuth({
      accessToken: '',
      refreshToken: '',
      user: null,
      tenant: null,
      role: '',
    })
    const adapter: AxiosAdapter = async (config) => Promise.reject({
      config,
      response: { status: 401, data: { msg: '未登录' } },
    })
    http.defaults.adapter = adapter

    await expect(http.get('/layout/pages/config-score')).rejects.toBeTruthy()

    expect(ElMessage.error).not.toHaveBeenCalled()
  })
})
