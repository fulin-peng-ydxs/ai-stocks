// 认证接口封装（多租户 RBAC stage2·T7）——对应后端 /api/auth/*。
import http, { type AppRequestConfig } from './client'

// 登录页各请求统一关闭全局 toast，错误交由 LoginView 就地内联展示（错误态改进）。
const silent: AppRequestConfig = { skipGlobalError: true }

export interface AuthUser {
  id: string
  account: string
  email?: string | null
  status?: string
}

export interface LoginResult {
  access_token: string
  refresh_token: string
  user: AuthUser & { role: string; tenant_id: string }
}

export interface MeResult {
  user: AuthUser
  tenant: { id: string }
  role: string
  menus: unknown[]
  permissions: string[]
}

export interface PublicAuthConfig {
  require_email_code: boolean
  login_captcha_enabled: boolean
  captcha_after_fails: number
}

export interface CaptchaResult {
  captcha_id: string
  svg: string
}

export function login(payload: {
  account: string
  password: string
  captcha_id?: string
  captcha_code?: string
}): Promise<LoginResult> {
  return http.post('/auth/login', payload, silent)
}

export function register(payload: {
  account: string
  password: string
  email?: string
  email_code?: string
}): Promise<LoginResult> {
  return http.post('/auth/register', payload, silent)
}

export function refresh(refreshToken: string): Promise<LoginResult> {
  return http.post('/auth/refresh', { refresh_token: refreshToken })
}

export function logout(refreshToken?: string): Promise<null> {
  return http.post('/auth/logout', { refresh_token: refreshToken })
}

export function getMe(): Promise<MeResult> {
  return http.get('/auth/me')
}

export function getPublicConfig(): Promise<PublicAuthConfig> {
  return http.get('/auth/public-config', silent)
}

export function getCaptcha(): Promise<CaptchaResult> {
  return http.get('/auth/captcha', silent)
}

export function sendEmailCode(email: string): Promise<null> {
  return http.post('/auth/send-email-code', { email }, silent)
}
