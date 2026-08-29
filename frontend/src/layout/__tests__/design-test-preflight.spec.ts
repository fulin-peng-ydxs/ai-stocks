import { execFile } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const FRONTEND_ROOT = fileURLToPath(new URL('../../../', import.meta.url))
const CHECK_SCRIPT = fileURLToPath(
  new URL('../../../scripts/check-design-test-env.mjs', import.meta.url),
)
const DESIGN_E2E_SCRIPT = fileURLToPath(
  new URL('../../../../scripts/run-design-e2e.sh', import.meta.url),
)

interface CheckResult {
  stdout: string
  stderr: string
}

interface CheckFailure extends Error, CheckResult {
  code: number
}

function runCheck(
  overrides: Record<string, string | undefined> = {},
): Promise<CheckResult> {
  const env = { ...process.env, ...overrides }
  for (const [key, value] of Object.entries(env)) {
    if (value === undefined) delete env[key]
  }

  return new Promise((resolve, reject) => {
    execFile(
      process.execPath,
      [CHECK_SCRIPT],
      { cwd: FRONTEND_ROOT, env },
      (error, stdout, stderr) => {
        const result = { stdout, stderr }
        if (error) {
          reject(Object.assign(error, result))
          return
        }
        resolve(result)
      },
    )
  })
}

async function failedCheck(
  overrides: Record<string, string | undefined>,
): Promise<CheckFailure> {
  try {
    await runCheck(overrides)
  } catch (error) {
    return error as CheckFailure
  }
  throw new Error('环境前置检查应当失败')
}

const validEnvironment = {
  AI_STOCKS_ENV: 'test',
  AI_STOCKS_E2E_WRITE: '1',
}

describe('完整设计验收环境前置检查', () => {
  it('完整设计验收在运行其他门禁前执行环境前置检查', () => {
    const packageJson = JSON.parse(
      readFileSync(new URL('../../../package.json', import.meta.url), 'utf8'),
    ) as { scripts: Record<string, string> }

    expect(packageJson.scripts['test:design']).toMatch(
      /^node scripts\/check-design-test-env\.mjs && /,
    )
  })

  it('Playwright 按互斥夹具和 DuckDB 模式分组编排', () => {
    const script = readFileSync(DESIGN_E2E_SCRIPT, 'utf8')

    expect(script).toContain('run-sector-e2e.sh')
    expect(script).toContain('run-stock-board-correlation-e2e.sh')
    expect(script).toContain('run-trade-discipline-e2e.sh')
    expect(script).toContain('e2e/backtest-public-runs.spec.ts')
    expect(script).toContain('stop_and_start_backend 1')
    expect(script).toContain('stock-board-correlation|trade-discipline')
  })

  it('调用方未显式启用安全环境时在访问后端前失败', async () => {
    const failure = await failedCheck({
      AI_STOCKS_ENV: undefined,
      AI_STOCKS_E2E_WRITE: undefined,
      E2E_API_URL: 'http://127.0.0.1:1/api',
    })

    expect(failure.code).toBe(1)
    expect(failure.stderr).toContain('完整设计验收要求显式设置本地测试环境')
  })

  it('后端初始停止时由 runner 管理生命周期，前置检查仍通过', async () => {
    const result = await runCheck({
      ...validEnvironment,
      E2E_API_URL: undefined,
    })

    expect(result.stderr).toBe('')
    expect(result.stdout).toContain('后端运行态由 E2E runner 受控管理')
  })

  it('拒绝由完整验收 runner 管理范围外的 API 地址', async () => {
    const failure = await failedCheck({
      ...validEnvironment,
      E2E_API_URL: 'http://127.0.0.1:8765/api',
    })

    expect(failure.code).toBe(1)
    expect(failure.stderr).toContain('仅允许 E2E_API_URL=http://127.0.0.1:8000/api')
  })

  it('显式本地 API 地址时通过', async () => {
    const result = await runCheck({
      ...validEnvironment,
      E2E_API_URL: 'http://127.0.0.1:8000/api/',
    })

    expect(result.stderr).toBe('')
    expect(result.stdout).toContain('设计验收安全环境检查通过')
  })
})
