import { execFileSync } from 'node:child_process'
import { copyFileSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const SCRIPT = fileURLToPath(new URL('../../../scripts/scaffold-page.mjs', import.meta.url))

describe('新页面脚手架响应式交付', () => {
  it('生成独立待验收标记、可换行操作栏，并同步布局、路由和 DESIGN 登记', () => {
    // 在独立仓库夹具中执行真实 CLI，防止脚手架测试改写当前工作区。
    const repo = mkdtempSync(join(tmpdir(), 'ai-stocks-scaffold-'))
    const frontend = join(repo, 'frontend')
    for (const dir of ['scripts', 'src/views', 'src/layout', 'src/router']) {
      mkdirSync(join(frontend, dir), { recursive: true })
    }
    copyFileSync(SCRIPT, join(frontend, 'scripts/scaffold-page.mjs'))
    writeFileSync(join(frontend, 'src/layout/pageRegistry.ts'), 'const entries = [\n]\n\n// P13 overlay\n')
    writeFileSync(join(frontend, 'src/router/index.ts'), 'const routes = [\n  // 兜底：未匹配路径\n]\n')
    writeFileSync(join(repo, 'DESIGN.md'), '<!-- page-registry:start -->\n<!-- page-registry:end -->\n')
    try {
      execFileSync(process.execPath, [join(frontend, 'scripts/scaffold-page.mjs'),
        '--pageKey', 'research', '--label', '研究页', '--archetype', 'list'], { cwd: frontend })
      const source = readFileSync(join(frontend, 'src/views/ResearchView.vue'), 'utf8')
      expect(source).toContain('responsive-review-pending')
      // 删除业务占位后响应式待验收标记仍存在，两个门禁互不替代。
      expect(source.replaceAll('data-scaffold-placeholder', '')).toContain('responsive-review-pending')
      expect(source).toContain('<LayoutHost :layout="effective">')
      expect(source).toContain('flex-wrap: wrap')
      expect(source).toContain('min-width: 0')
      const registry = readFileSync(join(frontend, 'src/layout/pageRegistry.ts'), 'utf8')
      expect(registry).toContain("responsiveProfile: 'single-column'")
      expect(registry).toContain('responsive: singleColumn()')
      expect(readFileSync(join(frontend, 'src/router/index.ts'), 'utf8')).toContain("name: 'research'")
      expect(readFileSync(join(repo, 'DESIGN.md'), 'utf8')).toContain('| `research` |')
    } finally {
      rmSync(repo, { recursive: true, force: true })
    }
  })
})
