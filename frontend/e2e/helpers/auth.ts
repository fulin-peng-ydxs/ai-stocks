import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import type { APIRequestContext, Page } from '@playwright/test'
import { expect } from '@playwright/test'

const API_URL = process.env.E2E_API_URL || 'http://127.0.0.1:8000/api'
const AUTH_STORAGE_KEY = 'ai-stocks-auth'
const debugAuthCache = new Map<string, E2EAuthSnapshot>()

export interface E2EAuthSnapshot {
  accessToken: string
  refreshToken: string
  user: { id: string; account: string; email?: string | null; status?: string | null }
  tenant: { id: string }
  role: string
}

function readLocalEnv(name: string): string {
  const envPath = resolve(process.cwd(), '..', '.env.local')
  if (!existsSync(envPath)) return ''
  const line = readFileSync(envPath, 'utf8')
    .split(/\r?\n/)
    .map((entry) => entry.trim())
    .find((entry) => entry && !entry.startsWith('#') && entry.startsWith(`${name}=`))
  if (!line) return ''
  return line.slice(name.length + 1).replace(/^['"]|['"]$/g, '')
}

function debugPassword(): string {
  return process.env.AI_STOCKS_TEST_USER_PASSWORD
    || readLocalEnv('AI_STOCKS_TEST_USER_PASSWORD')
    || 'Test@12345'
}

export async function installAuthSnapshot(
  page: Page,
  snapshot: E2EAuthSnapshot,
): Promise<void> {
  await page.addInitScript(([key, value]) => {
    window.localStorage.setItem(key, JSON.stringify(value))
  }, [AUTH_STORAGE_KEY, snapshot] as const)
}

export async function expectBackendHealthy(request: APIRequestContext): Promise<void> {
  const resp = await request.get(`${API_URL}/health`)
  expect(resp.ok(), '后端 8000 未就绪；先执行 ./start.sh 并确认 /api/health=200').toBe(true)
}

export async function authenticateDebugUser(
  request: APIRequestContext,
  account = process.env.E2E_ACCOUNT || 'debug_normal',
): Promise<E2EAuthSnapshot> {
  const cached = debugAuthCache.get(account)
  if (cached) return cached
  await expectBackendHealthy(request)
  const resp = await request.post(`${API_URL}/auth/login`, {
    data: { account, password: debugPassword() },
  })
  expect(resp.ok(), `调试账号 ${account} 登录失败；先执行 python -m backend.cli dev-users 校准账号`).toBe(true)
  const body = await resp.json()
  expect(body.code, body.msg || '登录接口返回非 0 code').toBe(0)
  const data = body.data
  const snapshot: E2EAuthSnapshot = {
    accessToken: data.access_token,
    refreshToken: data.refresh_token,
    user: {
      id: data.user.id,
      account: data.user.account,
      email: data.user.email ?? null,
      status: data.user.status ?? null,
    },
    tenant: { id: data.user.tenant_id },
    role: data.user.role,
  }
  debugAuthCache.set(account, snapshot)
  return snapshot
}

export async function loginAsDebugUser(
  page: Page,
  request: APIRequestContext,
  account = process.env.E2E_ACCOUNT || 'debug_normal',
): Promise<E2EAuthSnapshot> {
  const snapshot = await authenticateDebugUser(request, account)
  await installAuthSnapshot(page, snapshot)
  return snapshot
}

export async function saveUserPreference(
  request: APIRequestContext,
  auth: E2EAuthSnapshot,
  payload: { scope: string; prefKey: string; value: unknown; pageKey?: string; schemaVersion?: number },
): Promise<void> {
  const resp = await request.post(`${API_URL}/user-preferences`, {
    headers: { authorization: `Bearer ${auth.accessToken}` },
    data: { schemaVersion: 1, ...payload },
  })
  expect(resp.ok(), '保存用户偏好失败').toBe(true)
  const body = await resp.json()
  expect(body.code, body.msg || '保存用户偏好返回非 0 code').toBe(0)
}

export async function getUserPreference(
  request: APIRequestContext,
  auth: E2EAuthSnapshot,
  params: { scope: string; prefKey: string; pageKey?: string },
): Promise<unknown> {
  const search = new URLSearchParams({ scope: params.scope, prefKey: params.prefKey })
  if (params.pageKey) search.set('pageKey', params.pageKey)
  const resp = await request.get(`${API_URL}/user-preferences?${search.toString()}`, {
    headers: { authorization: `Bearer ${auth.accessToken}` },
  })
  expect(resp.ok(), '读取用户偏好失败').toBe(true)
  const body = await resp.json()
  expect(body.code, body.msg || '读取用户偏好返回非 0 code').toBe(0)
  return body.data?.items?.[0]?.value
}
