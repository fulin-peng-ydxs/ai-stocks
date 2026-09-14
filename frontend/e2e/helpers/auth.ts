import { execFile } from 'node:child_process'
import { resolve } from 'node:path'
import { promisify } from 'node:util'
import type { APIRequestContext, Page } from '@playwright/test'
import { expect } from '@playwright/test'
import {
  DEFAULT_E2E_API_URL,
  e2eBackendHealthUrl,
  requireE2EBackendHealth,
} from './e2e-backend-health.mjs'

const API_URL = process.env.E2E_API_URL || DEFAULT_E2E_API_URL
const AUTH_STORAGE_KEY = 'ai-stocks-auth'
const DISPLAY_SCALE_STORAGE_KEY = 'ai-stocks-display-scale'
const debugAuthCache = new Map<string, E2EAuthSnapshot>()
const execFileAsync = promisify(execFile)

export interface E2EAuthSnapshot {
  accessToken: string
  refreshToken: string
  user: { id: string; account: string; email?: string | null; status?: string | null }
  tenant: { id: string }
  role: string
}

export interface TemporaryE2EUser {
  userId: string
  account: string
  tenantId: string
  role: 'normal'
  pgFingerprint: string
}

function debugPassword(): string {
  return process.env.AI_STOCKS_TEST_USER_PASSWORD || 'Test@12345'
}

async function runTemporaryUserFixture(args: string[]): Promise<Record<string, unknown>> {
  const repositoryRoot = resolve(process.cwd(), '..')
  const { stdout } = await execFileAsync(
    resolve(repositoryRoot, 'start.sh'),
    ['e2e-user', ...args],
    {
      cwd: repositoryRoot,
      env: process.env,
      maxBuffer: 1024 * 1024,
      timeout: 15_000,
    },
  )
  const line = stdout.trim().split(/\r?\n/).at(-1)
  if (!line) throw new Error('临时 E2E 用户夹具未返回结果')
  return JSON.parse(line) as Record<string, unknown>
}

async function backendE2ETarget(request: APIRequestContext): Promise<string> {
  const resp = await request.get(e2eBackendHealthUrl(API_URL))
  expect(resp.ok(), '后端 E2E 环境检查请求失败').toBe(true)
  const body = await resp.json()
  return requireE2EBackendHealth(body)
}

export async function createTemporaryE2EUser(
  request: APIRequestContext,
  role: TemporaryE2EUser['role'],
): Promise<TemporaryE2EUser> {
  const pgFingerprint = await backendE2ETarget(request)
  const result = await runTemporaryUserFixture([
    'create',
    '--role',
    role,
    '--expected-pg-fingerprint',
    pgFingerprint,
  ])
  if (
    typeof result.userId !== 'string'
    || typeof result.account !== 'string'
    || typeof result.tenantId !== 'string'
    || result.role !== role
  ) {
    throw new Error('临时 E2E 用户夹具返回结构非法')
  }
  return { ...result, pgFingerprint } as unknown as TemporaryE2EUser
}

export async function destroyTemporaryE2EUser(
  request: APIRequestContext,
  user: TemporaryE2EUser,
): Promise<void> {
  try {
    const currentPgFingerprint = await backendE2ETarget(request)
    if (currentPgFingerprint !== user.pgFingerprint) {
      throw new Error('被测后端 PostgreSQL 在用例执行期间发生变化，拒绝清理')
    }
    const result = await runTemporaryUserFixture([
      'destroy',
      '--user-id',
      user.userId,
      '--tenant-id',
      user.tenantId,
      '--account',
      user.account,
      '--expected-pg-fingerprint',
      user.pgFingerprint,
    ])
    if (result.userRows !== 1) {
      throw new Error(`临时 E2E 用户清理数量异常：${String(result.userRows)}`)
    }
  } finally {
    debugAuthCache.delete(user.account)
  }
}

export async function destroyTemporaryE2EUsers(
  request: APIRequestContext,
  users: TemporaryE2EUser[],
): Promise<void> {
  const errors: unknown[] = []
  for (const user of [...users].reverse()) {
    try {
      await destroyTemporaryE2EUser(request, user)
    } catch (error) {
      errors.push(error)
    }
  }
  if (errors.length > 0) {
    throw new AggregateError(errors, '一个或多个临时 E2E 用户清理失败')
  }
}

export async function installAuthSnapshot(
  page: Page,
  snapshot: E2EAuthSnapshot,
): Promise<void> {
  await page.addInitScript(([key, value]) => {
    window.localStorage.setItem(key, JSON.stringify(value))
  }, [AUTH_STORAGE_KEY, snapshot] as const)
  // 页面布局 E2E 固定 100% 显示比例，避免系统自动比例与视口矩阵叠加后污染 CSS 几何断言。
  // 自动比例策略由独立单测与 display-scale fixture 验证。
  await page.addInitScript((key) => {
    // Playwright 的虚拟 screen 默认小于设计参考屏；固定参考面积后，远端同步回 auto 模式
    // 仍保持 100%，不会把布局像素断言整体缩成 90%。
    Object.defineProperty(window.screen, 'availWidth', { configurable: true, value: 2560 })
    Object.defineProperty(window.screen, 'availHeight', { configurable: true, value: 1440 })
    window.localStorage.setItem(key, JSON.stringify({
      mode: 'custom',
      customPercent: 100,
      customProfiles: [],
    }))
  }, DISPLAY_SCALE_STORAGE_KEY)
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
  expect(resp.ok(), `调试账号 ${account} 登录失败；先执行 ./start.sh dev-users 校准账号`).toBe(true)
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
