// axios 请求层封装：统一 baseURL、注入鉴权头、解包 {code,msg,data}、错误提示（SDD §13.2 + stage2·T7）
import axios, { type AxiosInstance, type AxiosRequestConfig } from 'axios'
import { ElMessage } from 'element-plus'
import { clearAuth, getAccessToken, getRefreshToken, updateTokens } from './authToken'

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

// 把可读文案挂到 error 上，便于跳过全局 toast 的调用方统一读取 error.uiMessage。
function decorateError<E>(error: E, message: string): E {
  if (error && typeof error === 'object') {
    (error as { uiMessage?: string }).uiMessage = message
  }
  return error
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
      const message = body.msg || '请求失败'
      const skip = (resp.config as RetryableConfig | undefined)?.skipGlobalError
      if (!skip) ElMessage.error(message)
      return Promise.reject(decorateError(new Error(message), message))
    }
    return body.data as unknown as never
  },
  async (error) => {
    if (axios.isCancel(error)) return Promise.reject(error) // 主动取消（导航切换）不弹错
    // stage2·T7：按 HTTP 状态分流——401 清态跳登录、403 无权、429 限流、503 依赖不可用
    const status = error?.response?.status
    const msg = error?.response?.data?.msg
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
    } else {
      message = msg || error?.message || '网络错误'
    }
    decorateError(error, message)
    if (!skip) ElMessage.error(message)
    return Promise.reject(error)
  },
)

export default http
