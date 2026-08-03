import { execFile } from 'node:child_process'
import { existsSync, mkdirSync, openSync, closeSync, rmSync, writeFileSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { resolve } from 'node:path'
import { promisify } from 'node:util'
import type { APIRequestContext } from '@playwright/test'
import { expect } from '@playwright/test'
import {
  DEFAULT_E2E_API_URL,
  e2eBackendHealthUrl,
  requireE2EBackendHealth,
} from './e2e-backend-health.mjs'

const API_URL = process.env.E2E_API_URL || DEFAULT_E2E_API_URL
const execFileAsync = promisify(execFile)
const SEED_LOCK = resolve(tmpdir(), 'ai-stocks-e2e-backtest-seed.lock')
const SEED_STATE = resolve(tmpdir(), 'ai-stocks-e2e-backtest-seed.json')

export interface SeededBacktestRun {
  runId: string
  runRef: string
  ownerAccount: string
  tenantId: string
  visibility: string
  dateStart: string
  dateEnd: string
  pgFingerprint: string
}

/** 跨 worker 文件锁：三视口并发 seed 同 owner/同 signature 会触发 advisory lock，串行化避免。 */
async function withFileLock<T>(fn: () => Promise<T>): Promise<T> {
  mkdirSync(tmpdir(), { recursive: true })
  for (let attempt = 0; attempt < 120; attempt += 1) {
    try {
      const fd = openSync(SEED_LOCK, 'wx')
      try {
        return await fn()
      } finally {
        closeSync(fd)
        rmSync(SEED_LOCK, { force: true })
      }
    } catch (e) {
      if ((e as NodeJS.ErrnoException).code !== 'EEXIST') throw e
      await new Promise((r) => setTimeout(r, 500))
    }
  }
  throw new Error('公开回测夹具跨 worker 锁等待超时')
}

export interface SeededBacktestRun {
  runId: string
  runRef: string
  ownerAccount: string
  tenantId: string
  visibility: string
  dateStart: string
  dateEnd: string
  pgFingerprint: string
}

async function runFixture(args: string[]): Promise<Record<string, unknown>> {
  const repositoryRoot = resolve(process.cwd(), '..')
  const { stdout } = await execFileAsync(
    resolve(repositoryRoot, 'start.sh'),
    ['e2e-backtest-run', ...args],
    { cwd: repositoryRoot, env: process.env, maxBuffer: 1024 * 1024, timeout: 120_000 },
  )
  const line = stdout.trim().split(/\r?\n/).at(-1)
  if (!line) throw new Error('公开回测夹具未返回结果')
  return JSON.parse(line) as Record<string, unknown>
}

async function backendE2ETarget(request: APIRequestContext): Promise<string> {
  const resp = await request.get(e2eBackendHealthUrl(API_URL))
  expect(resp.ok(), '后端 E2E 环境检查请求失败').toBe(true)
  const body = await resp.json()
  return requireE2EBackendHealth(body)
}

/** 三视口共享一条公开回测：首个 worker 持锁真实 seed，其余 worker 复用同一 run（文件态）。 */
export async function seedPublicBacktestRun(
  request: APIRequestContext,
  options: { ownerAccount?: string; visibility?: 'tenant' | 'public' } = {},
): Promise<SeededBacktestRun> {
  const pgFingerprint = await backendE2ETarget(request)
  return withFileLock(async () => {
    if (existsSync(SEED_STATE)) {
      try {
        const cached = JSON.parse(readFileSync(SEED_STATE, 'utf8')) as SeededBacktestRun
        if (cached.pgFingerprint === pgFingerprint && cached.runRef) return cached
      } catch { /* 状态损坏则重 seed */ }
    }
    const result = await runFixture([
      'seed',
      '--owner-account', options.ownerAccount ?? 'debug_normal',
      '--visibility', options.visibility ?? 'public',
      '--expected-pg-fingerprint', pgFingerprint,
    ])
    if (typeof result.runId !== 'string' || typeof result.runRef !== 'string') {
      throw new Error('公开回测夹具返回结构非法')
    }
    const seeded = { ...result, pgFingerprint } as unknown as SeededBacktestRun
    writeFileSync(SEED_STATE, JSON.stringify(seeded))
    return seeded
  })
}

/** 精确删除本夹具生成的全部公开回测；跨 worker 去重，仅首个清理者真正执行。 */
export async function cleanupPublicBacktestRuns(
  request: APIRequestContext,
  pgFingerprint: string,
): Promise<void> {
  const current = await backendE2ETarget(request)
  if (current !== pgFingerprint) {
    throw new Error('被测后端 PostgreSQL 在用例执行期间发生变化，拒绝清理')
  }
  await withFileLock(async () => {
    if (!existsSync(SEED_STATE)) return // 已被其他 worker 清理
    await runFixture(['cleanup', '--expected-pg-fingerprint', pgFingerprint])
    rmSync(SEED_STATE, { force: true })
  })
}
