import { spawnSync } from 'node:child_process'
import { copyFileSync, mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { expect, it } from 'vitest'

// 使用真实 CI 脚本和配置，夹具只含探针，避免递归执行本测试或请求在线后端。
it('完整前端 CI 自动收集业务目录，并拒绝失败、skip/todo、only、空集合和筛选参数', () => {
  const frontend = resolve(dirname(fileURLToPath(import.meta.url)), '../../..')
  const parent = resolve(frontend, '../.local/tmp/ai-agent')
  mkdirSync(parent, { recursive: true })
  const fixture = mkdtempSync(resolve(parent, 'frontend-ci-probe-'))
  const write = (path: string, contents: string) => {
    const file = resolve(fixture, path)
    mkdirSync(dirname(file), { recursive: true })
    writeFileSync(file, contents)
  }
  try {
    for (const name of ['vitest.config.ts', 'vitest.ci.config.ts']) {
      copyFileSync(resolve(frontend, name), resolve(fixture, name))
    }
    write('scripts/run-ci.mjs', readFileSync(resolve(frontend, 'scripts/run-ci.mjs'), 'utf8'))
    symlinkSync(resolve(frontend, 'node_modules'), resolve(fixture, 'node_modules'), 'dir')
    const scripts = JSON.parse(readFileSync(resolve(frontend, 'package.json'), 'utf8')).scripts
    write('package.json', JSON.stringify({ type: 'module', scripts: { 'test:ci': scripts['test:ci'] } }))
    const paths = ['layout', 'components', 'directives', 'views', 'api', 'stores', 'router', 'utils', 'composables', 'constants']
      .map(folder => `src/${folder}/nested/added.test.ts`)
    const pass = 'import {it,expect} from "vitest";it("probe",()=>expect(true).toBe(true))'
    paths.forEach(path => write(path, pass))
    // 未被导入的业务文件也必须进入覆盖率分母；纯测试文件不能充当覆盖率材料。
    write('src/utils/uncovered.ts', 'export const uncovered = (value: number) => value + 1')
    const artifacts = resolve(fixture, 'artifacts')
    const run = (extra: string[] = []) => spawnSync('npm', ['run', 'test:ci', '--', ...extra], {
      cwd: fixture, encoding: 'utf8', timeout: 30000,
      env: { ...process.env, AI_STOCKS_CI_ARTIFACT_DIR: artifacts },
    })
    const first = run()
    expect(first.status, first.stdout + first.stderr).toBe(0)
    const directory = first.stdout.match(/前端 CI 临时产物：([^\n]+)/)![1]!.trim()
    const report = JSON.parse(readFileSync(resolve(directory, 'ci-frontend.json'), 'utf8'))
    expect(report.testResults.map((file: { name: string }) => file.name.replace(fixture + '/', '')).sort())
      .toEqual([...paths].sort())
    expect(report.numPassedTests).toBe(paths.length)
    const measured = JSON.parse(readFileSync(resolve(directory, 'coverage/coverage-final.json'), 'utf8'))
    expect(Object.keys(measured).map(path => path.replace(fixture + '/', '')))
      .toEqual(['src/utils/uncovered.ts'])
    for (const source of [
      pass.replace('toBe(true)', 'toBe(false)'),
      pass.replace('it(', 'it.skip('),
      'import {it} from "vitest";it.todo("not implemented")',
      pass.replace('it(', 'it.only('),
    ]) {
      write(paths[0], source)
      const result = run()
      expect(result.status, result.stdout + result.stderr).toBe(1)
    }
    write(paths[0], pass)
    expect(run(['--testNamePattern=probe']).status).toBe(1)
    for (const path of paths) rmSync(resolve(fixture, path))
    expect(run().status).toBe(1)
  } finally {
    rmSync(fixture, { recursive: true, force: true })
  }
}, 120000)
