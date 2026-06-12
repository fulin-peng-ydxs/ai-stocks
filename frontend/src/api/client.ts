// axios 请求层封装：统一 baseURL、解包 {code,msg,data}、错误提示（SDD §13.2）
import axios, { type AxiosInstance } from 'axios'
import { ElMessage } from 'element-plus'

export interface ApiResponse<T = unknown> {
  code: number
  msg: string
  data: T
}

const http: AxiosInstance = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

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
    ElMessage.error(error?.message || '网络错误')
    return Promise.reject(error)
  },
)

export default http
