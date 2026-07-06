// axios 请求层封装：统一 baseURL、注入鉴权头、解包 {code,msg,data}、错误提示（SDD §13.2 + stage2·T7）
import axios, { type AxiosInstance, type AxiosRequestConfig } from 'axios'
import { ElMessage } from 'element-plus'
import { clearAuth, getAccessToken, getRefreshToken, updateTokens } from './authToken'

export interface ApiResponse<T = unknown> {
  code: number
  msg: string
  data: T
}

const http: AxiosInstance = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

let refreshPromise: Promise<string> | null = null

interface RetryableConfig extends AxiosRequestConfig {
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
      ElMessage.error(body.msg || '请求失败')
      return Promise.reject(new Error(body.msg))
    }
    return body.data as unknown as never
  },
  async (error) => {
    if (axios.isCancel(error)) return Promise.reject(error) // 主动取消（导航切换）不弹错
    // stage2·T7：按 HTTP 状态分流——401 清态跳登录、403 无权、429 限流、503 依赖不可用
    const status = error?.response?.status
    const msg = error?.response?.data?.msg
    if (status === 401) {
      // 已在登录页时的 401 是登录动作本身失败（账密错/图形码错/锁定），此处弹后端提示；
      // 其余页面的 401 是会话失效，清态跳登录（redirectToLogin 内已判重不重复跳）。
      if (window.location.pathname === '/login') {
        ElMessage.error(msg || '账号或密码错误')
      } else {
        const config = error?.config as RetryableConfig | undefined
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
    if (status === 403) {
      ElMessage.error(msg || '无权限执行此操作')
    } else if (status === 429) {
      ElMessage.error(msg || '请求过于频繁，请稍后再试')
    } else if (status === 503) {
      ElMessage.error(msg || '服务暂时不可用，请稍后重试')
    } else {
      ElMessage.error(msg || error?.message || '网络错误')
    }
    return Promise.reject(error)
  },
)

export default http
