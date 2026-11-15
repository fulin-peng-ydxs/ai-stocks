// @vitest-environment jsdom
import type { AxiosAdapter, InternalAxiosRequestConfig } from 'axios'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ElMessage } from 'element-plus'

import http, { type AppRequestConfig, withRequestParams } from '../client'
import { readAuth, writeAuth } from '../authToken'
import { startSession, revealNext, placeTrade, cancelIntent, settleRound } from '../training'
import { deleteRun, getRun, setRunVisibility, runBacktest, prepareBacktest, runRobust, listRuns } from '../backtest'
import { computeBoard, runBoardProfile } from '../board'
import { getBars } from '../stocks'
import { runScreen, rankScreen } from '../screening'
import { runScoreProfile } from '../scoreProfile'
import { previewConditions } from '../tradeProfile'
import { listSectorWatchlist, addSectorWatchlist, removeSectorWatchlist } from '../sectors'
import { listScheduleOptions } from '../data'
import { saveFieldPolicy, validateLayoutConfig, saveLayoutPageConfig, saveLayoutPreset } from '../layout'
import { getMe } from '../auth'

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
  it('查询配置合并保留取消与序列化选项，API 参数优先且不改写调用方', () => {
    const controller = new AbortController()
    const serialize = vi.fn(() => 'encoded=query')
    const config: AppRequestConfig = {
      signal: controller.signal, skipGlobalError: true,
      params: { previous: 1 }, paramsSerializer: { serialize },
    }
    const merged = withRequestParams(config, { q: 'stock', limit: 50 })
    expect(merged).toEqual({ ...config, params: { q: 'stock', limit: 50 } })
    expect(merged.signal).toBe(controller.signal)
    expect(merged.paramsSerializer).toBe(config.paramsSerializer)
    expect(config.params).toEqual({ previous: 1 })
  })
  it('HTTP 200 软失败不会把 SQL 原文带入提示，业务码继续保留', async () => {
    http.defaults.adapter = async config => ({ ...ok(config, null),
      data: { code: 5003, msg: '查询失败: Binder Error\nSQL: SELECT secret FROM private_table', data: null } })
    await expect(http.get('/storage-failure')).rejects.toMatchObject({
      apiCode: 5003, uiMessage: '请求失败，请稍后重试',
    })
    expect(ElMessage.error).toHaveBeenCalledWith('请求失败，请稍后重试')
  })
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

  it.each([
    ['查询失败 SQL: SELECT secret FROM users', '账号或密码错误'],
    ['认证失败 https://upstream.invalid/login', '账号或密码错误'],
    ['账号或密码不正确', '账号或密码不正确'],
  ])('登录 401 复用业务消息转换且保留原始响应：%s', async (msg, expected) => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    http.defaults.adapter = async config => Promise.reject({
      config, response: { status: 401, data: { msg } },
    })
    await expect(http.post('/auth/login', {})).rejects.toMatchObject({
      uiMessage: expected, response: { status: 401, data: { msg } },
    })
    expect(ElMessage.error).toHaveBeenCalledWith(expected)
    vi.mocked(ElMessage.error).mockClear()
    const silent: AppRequestConfig = { skipGlobalError: true }
    await expect(http.post('/auth/login', {}, silent)).rejects.toMatchObject({ uiMessage: expected })
    expect(ElMessage.error).not.toHaveBeenCalled()
    expect(fetchMock).not.toHaveBeenCalled()
    expect(readAuth().accessToken).toBe('old-access')
  })

  it.each([
    { name: '筛选运行', call: (config?: AppRequestConfig) => runScreen({ score_profile_id: 'score' }, config), timeout: 30000 },
    { name: '筛选重排', call: (config?: AppRequestConfig) => rankScreen({ run_date: '2026-11-13', score_profile_id: 'score', codes: [] }, config), timeout: 30000 },
    { name: '评分试算', call: (config?: AppRequestConfig) => runScoreProfile({ items: [] }, config), timeout: 30000 },
    { name: '买卖试算', call: (config?: AppRequestConfig) => previewConditions({ tree: { op: 'AND', children: [] } }, config), timeout: 30000 },
    { name: '板块自选读取', call: (config?: AppRequestConfig) => listSectorWatchlist(config), timeout: 30000 },
    { name: '板块加入自选', call: (config?: AppRequestConfig) => addSectorWatchlist('board', config), timeout: 30000 },
    { name: '板块移出自选', call: (config?: AppRequestConfig) => removeSectorWatchlist('board', config), timeout: 30000 },
    { name: '上游候选', call: (config?: AppRequestConfig) => listScheduleOptions('任务', undefined, config), timeout: 30000 },
    { name: '布局字段策略', call: (config?: AppRequestConfig) => saveFieldPolicy({ componentKind: 'table', field: 'border', allowedLayers: ['user'] }, config), timeout: 30000 },
    { name: '布局校验', call: (config?: AppRequestConfig) => validateLayoutConfig({ config: { values: {} } }, config), timeout: 30000 },
    { name: '页面布局导入', call: (config?: AppRequestConfig) => saveLayoutPageConfig('board', { config: { values: {} } }, config), timeout: 30000 },
    { name: '视觉预设导入', call: (config?: AppRequestConfig) => saveLayoutPreset({ key: 'test', name: '测试' }, config), timeout: 30000 },
    { name: '回测历史刷新', call: (config?: AppRequestConfig) => listRuns('strategy', 'mine', undefined, config), timeout: 30000 },
    { name: '菜单权限刷新', call: (config?: AppRequestConfig) => getMe(config), timeout: 30000 },
    { name: '训练开局', call: (config?: AppRequestConfig) => startSession({ mode: 'single' }, config), timeout: 30000 },
    { name: '下一交易日', call: (config?: AppRequestConfig) => revealNext('session', 0, config), timeout: 30000 },
    { name: '训练下单', call: (config?: AppRequestConfig) => placeTrade('session', 'buy', 1, '', config), timeout: 30000 },
    { name: '撤销意向', call: (config?: AppRequestConfig) => cancelIntent('session', config), timeout: 30000 },
    { name: '训练结算', call: (config?: AppRequestConfig) => settleRound('session', config), timeout: 30000 },
    { name: '删除回测', call: (config?: AppRequestConfig) => deleteRun('run', config), timeout: 30000 },
    { name: '加载回测', call: (config?: AppRequestConfig) => getRun('run', config), timeout: 30000 },
    { name: '公开设置', call: (config?: AppRequestConfig) => setRunVisibility('run', 'private', config), timeout: 30000 },
    { name: '运行回测', call: (config?: AppRequestConfig) => runBacktest({ kind: 'strategy', date_start: '2026-01-01', date_end: '2026-01-02' }, config), timeout: 300000 },
    { name: '回测查重', call: (config?: AppRequestConfig) => prepareBacktest({ kind: 'strategy', date_start: '2026-01-01', date_end: '2026-01-02' }, config), timeout: 30000 },
    { name: '稳健性测试', call: (config?: AppRequestConfig) => runRobust({ mode: 'param_sweep', params: {} }, config), timeout: 600000 },
    { name: '榜单导出', call: (config?: AppRequestConfig) => runBoardProfile({ export_all: true }, config), timeout: 30000 },
    { name: '回测 K 线', call: (config?: AppRequestConfig) => getBars('000001.SZ', { lookback: 6000 }, undefined, config), timeout: 30000 },
    { name: '回测榜单', call: (config?: AppRequestConfig) => computeBoard('2026-01-01', 50, undefined, config), timeout: 30000 },
  ])('$name：页面接管时无全局重复提示，默认调用仍由拦截器提示且保留超时', async ({ call, timeout }) => {
    const seen: InternalAxiosRequestConfig[] = []
    http.defaults.adapter = async config => {
      seen.push(config)
      return { ...ok(config, null), data: { code: 400, msg: '来源维护中，请稍后重试', data: null } }
    }
    await expect(call({ skipGlobalError: true })).rejects.toMatchObject({ uiMessage: '来源维护中，请稍后重试' })
    expect(ElMessage.error).not.toHaveBeenCalled()
    await expect(call()).rejects.toMatchObject({ uiMessage: '来源维护中，请稍后重试' })
    expect(ElMessage.error).toHaveBeenCalledTimes(1)
    expect(ElMessage.error).toHaveBeenCalledWith('来源维护中，请稍后重试')
    expect(seen.map(config => config.timeout)).toEqual([timeout, timeout])
    expect(seen[0].data).toEqual(seen[1].data)
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

  it('保留 HTTP 200 统一响应中的业务错误码', async () => {
    const adapter: AxiosAdapter = async (config) => ({
      data: { code: 404, msg: '方案不存在', data: null },
      status: 200,
      statusText: 'OK',
      headers: {},
      config,
    })
    http.defaults.adapter = adapter

    await expect(http.post('/board/run')).rejects.toMatchObject({
      apiCode: 404,
      uiMessage: '方案不存在',
    })
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
