// axios 请求层封装：统一 baseURL、注入鉴权头、解包 {code,msg,data}、错误提示（SDD §13.2 + stage2·T7）
import axios, { type AxiosInstance } from 'axios'
import { ElMessage } from 'element-plus'
import { clearAuth, getAccessToken } from './authToken'

export interface ApiResponse<T = unknown> {
  code: number
  msg: string
  data: T
}

const http: AxiosInstance = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

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
  window.location.assign(`/login?redirect=${redirect}`)
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
  (error) => {
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
