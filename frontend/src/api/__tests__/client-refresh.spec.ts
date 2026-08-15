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

  it('HTTP 500 且无 msg 时弹统一中文兜底文案而非 axios 英文', async () => {
    const adapter: AxiosAdapter = async (config) => Promise.reject({
      config,
      response: { status: 500, data: { detail: 'Internal Server Error' } },
    })
    http.defaults.adapter = adapter

    await expect(http.get('/sectors')).rejects.toMatchObject({
      uiMessage: '服务暂时不可用，请稍后重试',
    })

    expect(ElMessage.error).toHaveBeenCalledWith('服务暂时不可用，请稍后重试')
  })

  it('422 校验失败转软失败 {code:4000,msg:中文} 时弹 msg 而非空白', async () => {
    // 后端 RequestValidationError 处理器把 422 转成 HTTP 200 + {code:4000,msg:'参数 size 不合法'}。
    // 拦截器成功分支按业务 code !== 0 弹 msg；不得再出现空白 toast（数组 detail 已被后端消化）。
    const adapter: AxiosAdapter = async (config) => ({
      data: { code: 4000, msg: '参数 size 不合法', data: null },
      status: 200,
      statusText: 'OK',
      headers: {},
      config,
    })
    http.defaults.adapter = adapter

    await expect(http.get('/sectors?size=200')).rejects.toMatchObject({
      uiMessage: '参数 size 不合法',
    })

    expect(ElMessage.error).toHaveBeenCalledWith('参数 size 不合法')
  })

  it('HTTP 500 后端兜底已给中文 msg 时优先展示 msg', async () => {
    const adapter: AxiosAdapter = async (config) => Promise.reject({
      config,
      response: { status: 500, data: { code: 5000, msg: '服务内部错误，请稍后重试', data: null } },
    })
    http.defaults.adapter = adapter

    await expect(http.get('/sectors')).rejects.toMatchObject({
      uiMessage: '服务内部错误，请稍后重试',
    })

    expect(ElMessage.error).toHaveBeenCalledWith('服务内部错误，请稍后重试')
  })

  it('FastAPI 400 HTTPException 取 detail 中文文案而非 axios 英文', async () => {
    const adapter: AxiosAdapter = async (config) => Promise.reject({
      config,
      response: { status: 400, data: { detail: '不支持的指标字段: xxx' } },
    })
    http.defaults.adapter = adapter

    await expect(http.get('/stocks/bars')).rejects.toMatchObject({
      uiMessage: '不支持的指标字段: xxx',
    })

    expect(ElMessage.error).toHaveBeenCalledWith('不支持的指标字段: xxx')
  })

  it('axios 超时（无 HTTP 响应）弹中文超时文案而非英文 timeout', async () => {
    const adapter: AxiosAdapter = async (config) => Promise.reject({
      config,
      code: 'ECONNABORTED',
      message: 'timeout of 30000ms exceeded',
    })
    http.defaults.adapter = adapter

    await expect(http.get('/sectors')).rejects.toMatchObject({
      uiMessage: '请求超时，请稍后重试',
    })

    expect(ElMessage.error).toHaveBeenCalledWith('请求超时，请稍后重试')
  })

  it('断网（Network Error，无 HTTP 响应）弹中文网络错误而非英文', async () => {
    const adapter: AxiosAdapter = async (config) => Promise.reject({
      config,
      message: 'Network Error',
    })
    http.defaults.adapter = adapter

    await expect(http.get('/sectors')).rejects.toMatchObject({
      uiMessage: '网络错误，请检查网络后重试',
    })

    expect(ElMessage.error).toHaveBeenCalledWith('网络错误，请检查网络后重试')
  })
})
