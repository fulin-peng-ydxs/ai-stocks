import { spawnSync } from 'node:child_process'
import { mkdirSync, mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const frontend = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const action = process.argv[2]
if (!['run', 'test'].includes(action) || process.argv.length !== 3) {
  throw new Error('CI 入口仅接受 run/test，不透传测试筛选参数')
}
const parent = process.env.AI_STOCKS_CI_ARTIFACT_DIR
  || resolve(frontend, '../.local/tmp/ai-agent')
mkdirSync(parent, { recursive: true })
const artifacts = mkdtempSync(resolve(parent, 'ci-frontend-'))
const build = resolve(artifacts, 'dist')
const report = resolve(artifacts, 'ci-frontend.json')
const coverage = resolve(artifacts, 'coverage')
console.log(`前端 CI 临时产物：${artifacts}`)

function run(command, args) {
  const result = spawnSync(command, args, {
    cwd: frontend,
    env: { ...process.env, CI: '1' },
    stdio: 'inherit',
    timeout: 1_500_000,
  })
  if (result.error) throw result.error
  if (result.status !== 0) throw new Error(`CI 子命令失败：${command}，状态 ${result.status}`)
}

try {
  // 正式 build 已包含静态与类型检查；产物放本轮独立目录，不覆盖日常 frontend/dist。
  if (action === 'run') run('npm', ['run', 'build', '--', '--outDir', build])
  run(process.execPath, [
    'node_modules/vitest/vitest.mjs', 'run', '--config', 'vitest.ci.config.ts',
    '--reporter=default', '--reporter=json', `--outputFile=${report}`,
    '--coverage.enabled', `--coverage.reportsDirectory=${coverage}`,
  ])
  const result = JSON.parse(readFileSync(report, 'utf8'))
  const assertions = result.testResults.flatMap(file => file.assertionResults)
  if (result.success !== true || !assertions.length
    || result.numTotalTests !== assertions.length
    || result.numPassedTests !== assertions.length
    || assertions.some(test => test.status !== 'passed')) {
    throw new Error('前端 CI 存在失败、skip/todo、空集合或不完整报告，拒绝通过')
  }
  console.log(`前端 CI 完整执行：${assertions.length} 项通过，0 项跳过`)
  const summary = JSON.parse(readFileSync(resolve(coverage, 'coverage-summary.json'), 'utf8'))
  const measured = JSON.parse(readFileSync(resolve(coverage, 'coverage-final.json'), 'utf8'))
  if (!Number.isFinite(summary.total?.lines?.total) || summary.total.lines.total <= 0
    || !Object.keys(measured).length
    || !readFileSync(resolve(coverage, 'lcov.info'), 'utf8').includes('SF:')) {
    throw new Error('前端覆盖率报告测量集合为空')
  }
  console.log(`前端覆盖率报告：${coverage}`)
} finally {
  // 生产构建只用于本轮门禁，报告继续保留供失败诊断与 GitHub 归档。
  rmSync(build, { recursive: true, force: true })
}
