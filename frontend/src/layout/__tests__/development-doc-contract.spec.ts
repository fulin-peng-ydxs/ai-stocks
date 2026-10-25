import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { auditComponentEntries } from '../../../scripts/design-source.mjs'

const read = (path: string) => readFileSync(new URL(`../../../../${path}`, import.meta.url), 'utf8')
const blocks = (markdown: string, language: string) => [...markdown.matchAll(
  new RegExp('```' + language + '\\s*\\n([\\s\\S]*?)```', 'g'),
)].map(match => match[1]!)

// 文档示例也消费生产检查器；说明文字中的禁止项不作为可执行组件检查。
function componentViolations(markdown: string) {
  return auditComponentEntries(blocks(markdown, 'vue').map((source, index) => ({
    file: `docs/Example${index}.vue`, source,
  })))
}

function unsafeBrowserCommands(markdown: string) {
  return blocks(markdown, 'bash').flatMap(block => block.split('\n')).filter(line => {
    if (line.trim().startsWith('#') || !/\bnpm run test:e2e(?:\s|$)/.test(line)) return false
    // 物理夹具由专用 runner 管理；普通路径至少明确 spec 或正向 grep，排除式过滤不够。
    if (/(?:board-data-management|sector-quality-recovery|sectors-workbench|stock-board-correlation|trade-discipline|backtest-public-runs)\.spec\.ts/.test(line)) return true
    return !/(?:e2e\/[\w-]+\.spec\.ts|--grep(?:=|\s))/.test(line)
  })
}

describe('开发规范中的可执行示例', () => {
  it('共享组件入口门禁同时拒绝违规示例，允许正确封装', () => {
    expect(componentViolations('```vue\n<template><el-drawer/></template>\n```')).not.toEqual([])
    expect(componentViolations('```vue\n<template><PageDrawer boundary="app"/></template>\n```')).toEqual([])
    expect(componentViolations(read('agent-works/configurable-layout-system/page-template.md'))).toEqual([])
  })

  it.each([
    'npm run test:e2e',
    'npm run test:e2e -- --grep-invert public',
    'npm run test:e2e -- e2e/trade-discipline.spec.ts',
  ])('拒绝绕过夹具编排或无正向范围的示例：%s', command => {
    expect(unsafeBrowserCommands(`\`\`\`bash\n${command}\n\`\`\``)).toEqual([command])
  })

  it('允许普通定向路径和专用 runner，已发布文档不含旧全量操作', () => {
    const commands = 'npm run test:e2e -- e2e/login-initial-render.spec.ts --project=chromium-standard\n'
      + 'npm run test:e2e:sectors -- --grep=probe\n'
      + 'npm run test:design'
    expect(unsafeBrowserCommands(`\`\`\`bash\n${commands}\n\`\`\``)).toEqual([])
    for (const path of ['AGENTS.md', 'README.md', 'agent-works/configurable-layout-system/page-template.md', 'agent-works/e2e-automation/guide.md']) {
      expect(unsafeBrowserCommands(read(path)), path).toEqual([])
    }
  })
})
