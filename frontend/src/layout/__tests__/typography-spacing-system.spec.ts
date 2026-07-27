import { readFileSync, readdirSync } from 'node:fs'
import { dirname, extname, join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const TEST_DIR = dirname(fileURLToPath(import.meta.url))
const FRONTEND_DIR = join(TEST_DIR, '../../..')
const SRC_DIR = join(FRONTEND_DIR, 'src')
const PROJECT_DIR = join(FRONTEND_DIR, '..')

function read(path: string): string {
  return readFileSync(path, 'utf8')
}

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name)
    if (entry.isDirectory()) return sourceFiles(path)
    return ['.vue', '.css'].includes(extname(entry.name)) ? [path] : []
  })
}

function lineOf(source: string, index: number): number {
  return source.slice(0, index).split('\n').length
}

function styleBlocks(file: string): string[] {
  const source = read(file)
  if (extname(file) === '.css') return [source]
  return [...source.matchAll(/<style\b[^>]*>([\s\S]*?)<\/style>/g)].map((match) => match[1])
}

describe('字体与间距设计契约', () => {
  it('DESIGN、页面模板和全局样式声明同一套字体/间距事实源', () => {
    const design = read(join(PROJECT_DIR, 'DESIGN.md'))
    const pageTemplate = read(join(PROJECT_DIR, 'agent-works/configurable-layout-system/page-template.md'))
    const globalCss = read(join(SRC_DIR, 'styles/global.css'))

    expect(design).toContain('### 3.1 Spacing & Rhythm Rules')
    expect(design).toContain('--app-font-size-page-title')
    expect(design).toContain('--app-line-height-solid')
    expect(design).toContain('--app-space-1=4px')
    expect(design).toContain('禁止新增未登记的普通文字字号')
    expect(pageTemplate).toContain('### 字体与间距规范')
    expect(globalCss).toContain('--app-font-family-base')
    expect(globalCss).toContain("'Segoe UI Variable'")
    expect(globalCss).toContain("'Microsoft YaHei UI'")
    expect(globalCss).toContain('--app-font-size-body')
    expect(globalCss).toContain('--app-table-content-font-size')
    expect(globalCss).toContain('@media (max-resolution: 1.5dppx)')
    expect(globalCss).toContain('.lh-density-comfortable')
    expect(globalCss).toContain('--app-font-weight-section: 600')
    expect(globalCss).toContain('--app-line-height-solid')
    expect(globalCss).toContain('--app-space-control-gap')
    expect(globalCss).toContain('.app-page-title')
    expect(globalCss).toContain('.app-cluster-md')
  })

  it('登录页右侧光晕由当前预设强调色推导，避免单套预设漏覆盖', () => {
    const loginView = read(join(SRC_DIR, 'views/LoginView.vue'))

    expect(loginView).not.toContain('--login-auth-glow')
    expect(loginView).toContain('--login-accent: var(--el-color-primary, #1677ff)')
    expect(loginView).toContain('--login-accent-strong: var(--el-color-primary-dark-2, #1264d9)')
    expect(loginView).not.toContain('.login-shell.preset-daylight')
    expect(loginView).not.toContain('.login-shell.preset-nocturne')
    expect(loginView).not.toMatch(/#(?:b69254|876a3a|c5a466|d0ab68|9a7137)\b/i)
    expect(loginView).toContain(
      'grid-template-columns: minmax(0, 1.38fr) minmax(430px, 0.82fr)',
    )
    expect(loginView).toMatch(
      /radial-gradient\(\s*circle at 85% 0,\s*color-mix\(in srgb,\s*var\(--login-accent\)\s+12%,\s*transparent\),\s*transparent 28%\s*\)/,
    )
  })

  it('普通页面样式不新增游离 font-size、line-height、font-weight、gap 或 font-family', () => {
    const violations: string[] = []
    const allowedRawFontSizeFiles = new Set([
      'components/BrandMark.vue',
      'views/LoginView.vue',
    ])
    const allowedRawFontFamilyFiles = new Set(['views/LoginView.vue'])
    const allowedRawFontWeightFiles = new Set([
      'components/BrandMark.vue',
      'views/LoginView.vue',
    ])
    const allowedRawLineHeightFiles = new Set(['views/LoginView.vue'])

    for (const file of sourceFiles(SRC_DIR)) {
      const rel = relative(SRC_DIR, file)
      for (const css of styleBlocks(file)) {
        for (const match of css.matchAll(/font-size\s*:\s*([^;\n]+)/g)) {
          const value = match[1].trim()
          if (value.startsWith('var(')) continue
          if (value.startsWith('clamp(') && allowedRawFontSizeFiles.has(rel)) continue
          if (!allowedRawFontSizeFiles.has(rel)) {
            violations.push(`${rel}:${lineOf(css, match.index ?? 0)} font-size: ${value}`)
          }
        }
        for (const match of css.matchAll(/line-height\s*:\s*([^;\n]+)/g)) {
          const value = match[1].trim()
          if (!value.startsWith('var(') && !allowedRawLineHeightFiles.has(rel)) {
            violations.push(`${rel}:${lineOf(css, match.index ?? 0)} line-height: ${value}`)
          }
        }
        for (const match of css.matchAll(/font-weight\s*:\s*([^;\n]+)/g)) {
          const value = match[1].trim()
          if (!value.startsWith('var(') && !allowedRawFontWeightFiles.has(rel)) {
            violations.push(`${rel}:${lineOf(css, match.index ?? 0)} font-weight: ${value}`)
          }
        }
        for (const match of css.matchAll(/(^|[;{}\n]\s*)gap\s*:\s*([^;\n]+)/g)) {
          const value = match[2].trim()
          if (!value.startsWith('var(')) {
            violations.push(`${rel}:${lineOf(css, match.index ?? 0)} gap: ${value}`)
          }
        }
        for (const match of css.matchAll(/font-family\s*:\s*([^;\n]+)/g)) {
          const value = match[1].trim()
          if (!value.startsWith('var(') && !allowedRawFontFamilyFiles.has(rel)) {
            violations.push(`${rel}:${lineOf(css, match.index ?? 0)} font-family: ${value}`)
          }
        }
      }
    }

    expect(violations).toEqual([])
  })

  it('排版语义类必须有真实页面或组件消费，避免成为无人使用的平行事实源', () => {
    const semanticClasses = [
      'app-page-title',
      'app-section-title',
      'app-body-text',
      'app-caption-text',
      'app-micro-text',
      'app-data-text',
      'app-data-emphasis',
    ]
    const sources = sourceFiles(SRC_DIR)
      .filter((file) => relative(SRC_DIR, file) !== 'styles/global.css')
      .map((file) => read(file))
      .join('\n')

    expect(
      semanticClasses.filter((className) => !new RegExp(`class=["'][^"']*${className}\\b`).test(sources)),
    ).toEqual([])
  })

  it('新页面脚手架直接消费排版/间距事实源，并显式标记未完成占位', () => {
    const scaffold = read(join(FRONTEND_DIR, 'scripts/scaffold-page.mjs'))

    expect(scaffold).toContain('class="app-page-title"')
    expect(scaffold).toContain('gap: var(--app-space-3)')
    expect(scaffold).toContain('AppStateBlock')
    expect(scaffold).toContain('data-scaffold-placeholder')
    expect(scaffold).not.toMatch(/\.page-toolbar h1\s*\{[\s\S]*?font-size\s*:/)
    expect(scaffold).not.toMatch(/\bgap\s*:\s*\d+px/)
  })
})
