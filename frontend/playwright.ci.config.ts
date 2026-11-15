import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { defineConfig } from '@playwright/test'
import base from './playwright.config'

// CI 专项范围只消费唯一登记，外部 grep/project 参数由 Python 总入口封闭。
const registry = JSON.parse(readFileSync(resolve('../config/ci-suites.json'), 'utf8'))
const name = process.env.AI_STOCKS_CI_SUITE
const suite = registry.suites[name || '']
const artifacts = process.env.AI_STOCKS_CI_ARTIFACT_DIR
if (suite?.kind !== 'e2e' || !artifacts) throw new Error('缺少登记的 CI E2E 专项或独立报告目录')
const port = Number(process.env.E2E_WEB_PORT || 5181)
if (!Number.isInteger(port) || port < 1024 || port > 65535) throw new Error('CI E2E 前端端口非法')
const baseURL = `http://127.0.0.1:${port}`
const files = Object.entries(registry.special_files)
  .filter(([, value]) => (value as { suite: string }).suite === name)
  .map(([file]) => `**/${file.replace(/^frontend\//, '')}`)
if (!files.length) throw new Error('CI E2E 专项没有登记用例')
const literal = (value: string) => new RegExp(value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))

export default defineConfig({
  ...base,
  forbidOnly: true,
  retries: 0,
  workers: 1,
  use: { ...base.use, baseURL },
  testMatch: files,
  outputDir: resolve(artifacts, 'e2e-results'),
  reporter: [
    ['list'],
    ['html', { outputFolder: resolve(artifacts, 'e2e-html'), open: 'never' }],
    ['json', { outputFile: resolve(artifacts, 'e2e-actual.json') }],
  ],
  projects: suite.e2e.projects.map((selection: { name: string; title?: string; exclude_title?: string }) => {
    const project = base.projects?.find((candidate) => candidate.name === selection.name)
    if (!project) throw new Error(`未知 Playwright 项目：${selection.name}`)
    return {
      ...project,
      ...(selection.title ? { grep: literal(selection.title) } : {}),
      ...(selection.exclude_title ? { grepInvert: literal(selection.exclude_title) } : {}),
    }
  }),
  webServer: {
    ...base.webServer,
    command: `npm run dev -- --host 127.0.0.1 --port ${port} --strictPort`,
    url: baseURL,
    reuseExistingServer: false,
  },
})
