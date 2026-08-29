import { execFile } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { createServer } from 'node:http'
import type { AddressInfo } from 'node:net'
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

async function startHealthServer(body: unknown): Promise<{
  apiUrl: string
  close: () => Promise<void>
}> {
  const server = createServer((_request, response) => {
    response.writeHead(200, { 'Content-Type': 'application/json' })
    response.end(JSON.stringify(body))
  })
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
  const address = server.address() as AddressInfo

  return {
    apiUrl: `http://127.0.0.1:${address.port}/api`,
    close: () => new Promise<void>((resolve, reject) => {
      server.close((error) => {
        if (error) reject(error)
        else resolve()
      })
    }),
  }
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

  it('后端不可访问时给出带写模式的重启指引', async () => {
    const closedServer = await startHealthServer({ code: 0 })
    const apiUrl = closedServer.apiUrl
    await closedServer.close()

    const failure = await failedCheck({
      ...validEnvironment,
      E2E_API_URL: apiUrl,
    })

    expect(failure.code).toBe(1)
    expect(failure.stderr).toContain('无法访问后端 E2E 健康检查')
    expect(failure.stderr).toContain(
      'AI_STOCKS_ENV=test AI_STOCKS_E2E_WRITE=1 ./start.sh restart',
    )
  })

  it('运行中的后端未启用 E2E 写模式时根据业务码提前失败', async () => {
    const server = await startHealthServer({
      code: 403,
      msg: 'E2E 写环境未启用',
      data: null,
    })

    try {
      const failure = await failedCheck({
        ...validEnvironment,
        E2E_API_URL: server.apiUrl,
      })

      expect(failure.code).toBe(1)
      expect(failure.stderr).toContain('后端未按 E2E 写模式启动')
      expect(failure.stderr).toContain('E2E 写环境未启用')
    } finally {
      await server.close()
    }
  })

  it('后端返回 code 0 和合法 PG 指纹时通过', async () => {
    const server = await startHealthServer({
      code: 0,
      msg: 'ok',
      data: {
        environment: 'test',
        pgFingerprint: 'a'.repeat(64),
      },
    })

    try {
      const result = await runCheck({
        ...validEnvironment,
        E2E_API_URL: server.apiUrl,
      })

      expect(result.stderr).toBe('')
      expect(result.stdout).toContain('设计验收环境检查通过')
      expect(result.stdout).toContain(`${server.apiUrl}/health/e2e`)
    } finally {
      await server.close()
    }
  })
})
