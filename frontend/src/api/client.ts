// axios 请求层封装：统一 baseURL、注入鉴权头、解包 {code,msg,data}、错误提示（SDD §13.2 + stage2·T7）
import axios, { type AxiosInstance, type AxiosRequestConfig } from 'axios'
import { ElMessage } from 'element-plus'
import { clearAuth, getAccessToken, getRefreshToken, updateTokens } from './authToken'
import { businessMessage } from '@/utils/displayText'

export interface ApiResponse<T = unknown> {
  code: number
  msg: string
  data: T
}

// 调用方可传 skipGlobalError:true 关闭该请求的全局 toast（如登录/注册页改为字段内联报错）。
// 被跳过时错误仍会 reject，并在 error.uiMessage 上带回可读文案，交由调用方就地展示。
export interface AppRequestConfig extends AxiosRequestConfig {
  skipGlobalError?: boolean
}

// 把可读文案和统一响应的业务码挂到 error 上，便于调用方区分精确业务失败与网络故障。
function decorateError<E>(error: E, message: string, apiCode?: number): E {
  if (error && typeof error === 'object') {
    (error as { uiMessage?: string }).uiMessage = message
    if (apiCode !== undefined) (error as { apiCode?: number }).apiCode = apiCode
  }
  return error
}

// axios 超时：无 HTTP 响应，code=ECONNABORTED 且 message 含 timeout。注意与主动取消
// （isCancel/ERR_CANCELED）区分——取消在拦截器入口已单独拦截，不走到这里。
function isTimeoutError(error: unknown): boolean {
  const e = error as { code?: string; message?: string }
  return e?.code === 'ECONNABORTED' && typeof e.message === 'string' && e.message.includes('timeout')
}

const http: AxiosInstance = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

let refreshPromise: Promise<string> | null = null

interface RetryableConfig extends AppRequestConfig {
  _retry?: boolean
}

// 请求拦截：自动带上 access token（stage2·T7）；登录/注册等公开接口无 token 时不带即可
http.interceptors.request.use((config) => {
  const token = getAccessToken()
  if (token) {
    config.headers.set('Authorization', `Bearer ${token}`)
  }
  return config
})

// 未登录跳转：清本地态并带 redirect 回跳（用 location 避免与 router 循环依赖；整页重载可接受）
function redirectToLogin() {
  clearAuth()
  const { pathname, search, hash } = window.location
  if (pathname === '/login') return
  const redirect = encodeURIComponent(pathname + search + hash)
  if (import.meta.env.MODE === 'test') return
  window.location.assign(`/login?redirect=${redirect}`)
}

function isAuthRefreshExcluded(config: RetryableConfig | undefined): boolean {
  const url = String(config?.url || '')
  return url.includes('/auth/login')
    || url.includes('/auth/register')
    || url.includes('/auth/refresh')
}

function isLoginRequest(config: RetryableConfig | undefined): boolean {
  return String(config?.url || '').includes('/auth/login')
}

function applyBearer(config: RetryableConfig, token: string): void {
  const headers = config.headers as
    | { set?: (name: string, value: string) => void; Authorization?: string }
    | undefined
  if (typeof headers?.set === 'function') {
    headers.set('Authorization', `Bearer ${token}`)
    return
  }
  const { set: _set, ...plainHeaders } = headers || {}
  config.headers = { ...plainHeaders, Authorization: `Bearer ${token}` }
}

async function refreshAccessToken(): Promise<string> {
  if (!refreshPromise) {
    const refreshToken = getRefreshToken()
    if (!refreshToken) return Promise.reject(new Error('missing refresh token'))
    refreshPromise = fetch('/api/auth/refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
    })
      .then(async (resp) => {
        const body = await resp.json() as ApiResponse<{
          access_token: string
          refresh_token: string
        }>
        if (body.code !== 0 || !body.data?.access_token || !body.data?.refresh_token) {
          throw new Error(body.msg || '刷新登录态失败')
        }
        updateTokens(body.data.access_token, body.data.refresh_token)
        return body.data.access_token
      })
      .finally(() => {
        refreshPromise = null
      })
  }
  return refreshPromise
}

function requestBearerToken(error: unknown): string {
  const headers = (error as any)?.config?.headers
  const raw = typeof headers?.get === 'function'
    ? headers.get('Authorization')
    : headers?.Authorization || headers?.authorization || ''
  const value = String(raw || '')
  return value.startsWith('Bearer ') ? value.slice(7) : ''
}

// 响应拦截：业务 code !== 0 统一提示并抛错；成功直接返回 data
http.interceptors.response.use(
  (resp) => {
    const body = resp.data as ApiResponse
    if (body.code !== 0) {
      const message = businessMessage(body.msg, '请求失败，请稍后重试')
      const skip = (resp.config as RetryableConfig | undefined)?.skipGlobalError
      if (!skip) ElMessage.error(message)
      return Promise.reject(decorateError(new Error(message), message, body.code))
    }
    return body.data as unknown as never
  },
  async (error) => {
    if (axios.isCancel(error)) return Promise.reject(error) // 主动取消（导航切换）不弹错
    // stage2·T7：按 HTTP 状态分流——401 清态跳登录、403 无权、429 限流、503 依赖不可用
    const status = error?.response?.status
    const msg = error?.response?.data?.msg
    // FastAPI 未捕获异常返回 {"detail":"Internal Server Error"}，msg 缺失；detail 作为补充信息。
    const detailMsg = error?.response?.data?.detail
    // skipGlobalError：调用方（如登录/注册页）要求关闭全局 toast，改由页面就地展示
    const skip = (error?.config as RetryableConfig | undefined)?.skipGlobalError
    if (status === 401) {
      // 只有登录接口自身的 401 才是账密/验证码等登录失败；其他接口即便响应晚到登录页，
      // 也只是旧页面尾随请求的会话失效，必须静默清态，避免退出后连续弹错。
      const config = error?.config as RetryableConfig | undefined
      if (isLoginRequest(config)) {
        const message = msg || '账号或密码错误'
        decorateError(error, message)
        if (!skip) ElMessage.error(message)
      } else {
        if (config && !config._retry && !isAuthRefreshExcluded(config) && getRefreshToken()) {
          config._retry = true
          try {
            const token = await refreshAccessToken()
            applyBearer(config, token)
            return http.request(config)
          } catch {
            redirectToLogin()
            return Promise.reject(error)
          }
        }
        const currentToken = getAccessToken()
        const failedToken = requestBearerToken(error)
        if (currentToken && failedToken !== currentToken) {
          return Promise.reject(error)
        }
        redirectToLogin()
      }
      return Promise.reject(error)
    }
    let message: string
    if (status === 403) {
      message = msg || '无权限执行此操作'
    } else if (status === 429) {
      message = msg || '请求过于频繁，请稍后再试'
    } else if (status === 503) {
      message = msg || '服务暂时不可用，请稍后重试'
    } else if (status && status >= 500) {
      // 5xx（未捕获异常 500 / 网关 502/504 等）：后端兜底 handler 保证返回 {code:5000,msg:中文}；
      // 旧后端/网关可能返回 {"detail":"Internal Server Error"} 或 HTML，msg 缺失时统一中文兜底，
      // 不把英文系统文本直接弹给用户。
      message = msg || '服务暂时不可用，请稍后重试'
    } else if (status === undefined) {
      // 网络层错误（无 HTTP 响应）：axios 超时（timeout of 30000ms exceeded / ECONNABORTED）、
      // 断网（Network Error）等只有英文 error.message，统一转中文，不直接展示系统文本。
      message = isTimeoutError(error) ? '请求超时，请稍后重试' : '网络错误，请检查网络后重试'
    } else {
      // 4xx/其它：后端部分端点用 FastAPI HTTPException（detail 承载中文业务文案），msg 缺失时取 detail。
      message = msg || detailMsg || error?.message || '网络错误'
    }
    message = businessMessage(message, '请求失败，请稍后重试')
    decorateError(error, message)
    if (!skip) ElMessage.error(message)
    return Promise.reject(error)
  },
)

export default http
