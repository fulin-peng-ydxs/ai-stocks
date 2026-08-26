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
    expect(globalCss).toMatch(/\.page-head\s*\{[\s\S]*?align-items:\s*flex-start/)
    expect(globalCss).toContain('.app-page-title')
    expect(globalCss).toContain('.app-cluster-md')
    expect(design).toContain('### 3.2 Inline Information Unit Rules')
    expect(design).toContain('明显不是同一个连贯内容单位的信息不得直接相邻')
    expect(globalCss).toContain('.app-inline-info')
    expect(globalCss).toContain('.app-inline-info--nowrap')
  })

  it('独立行内信息使用全局信息组，标签不以页面私有固定边距修补', () => {
    const violations: string[] = []

    for (const file of sourceFiles(SRC_DIR)) {
      const rel = relative(SRC_DIR, file)
      for (const css of styleBlocks(file)) {
        for (const match of css.matchAll(/([^{}]+)\{([^{}]*?)\}/gs)) {
          const selector = match[1].trim()
          if (!/(tag|badge|chip)/i.test(selector)) continue
          for (const margin of match[2].matchAll(/margin-(left|right)\s*:\s*([^;\n]+)/g)) {
            const value = margin[2].trim()
            if (value === 'auto' || value === '0') continue
            violations.push(`${rel}:${lineOf(css, match.index ?? 0)} ${selector} -> margin-${margin[1]}: ${value}`)
          }
        }
      }
    }

    expect(violations).toEqual([])

    const schedule = read(join(SRC_DIR, 'views/data/ScheduleView.vue'))
    const stockSelect = read(join(SRC_DIR, 'views/trade-discipline/components/StockOptionSelect.vue'))
    expect(schedule).toContain('class="app-inline-info app-inline-info--nowrap"')
    expect(stockSelect).toContain('popper-class="stock-option-select-popper"')
    expect(stockSelect).toContain(':global(.stock-option-select-popper .el-select-dropdown__item)')
    expect(stockSelect).not.toContain('.el-select :deep(.el-select-dropdown__item)')
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
          // inherit 是合法继承语义（继承父级字号），不构成新增游离字号。
          if (value.startsWith('var(') || value === 'inherit') continue
          if (value.startsWith('clamp(') && allowedRawFontSizeFiles.has(rel)) continue
          if (!allowedRawFontSizeFiles.has(rel)) {
            violations.push(`${rel}:${lineOf(css, match.index ?? 0)} font-size: ${value}`)
          }
        }
        for (const match of css.matchAll(/line-height\s*:\s*([^;\n]+)/g)) {
          const value = match[1].trim()
          if (!value.startsWith('var(') && value !== 'inherit' && !allowedRawLineHeightFiles.has(rel)) {
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

  it('微字号（micro/tiny/ornament）不得通过宽泛后代选择器误传给嵌套元素', () => {
    // 事故复盘：.market-metric span { font-size: var(--app-font-size-micro) } 把 11px
    // 误传给 strong 内的数字 span。契约只检查「字号值是否来自 token」查不出这类问题——
    // 值虽是 var()，选择器却是无 > 限定的后代选择器，会命中本不该用小字号的嵌套元素。
    // 这里强制：微字号只允许作用在语义类、:global 或 > 限定的直接子级上。
    const violations: string[] = []
    const allowedRawFontSizeFiles = new Set([
      'components/BrandMark.vue',
      'views/LoginView.vue',
    ])
    const SMALL_FONT = /micro|tiny|ornament/
    // 裸标签（含 span/strong/div/p/b/em/i/a），用于识别「未限定直接子级」的后代选择器
    const LOOSE_TAG = /(?<![\w.-])(span|strong|div|td|p|b|em|i|a)(\s|,|:|\.|\[|$)/

    for (const file of sourceFiles(SRC_DIR)) {
      const rel = relative(SRC_DIR, file)
      if (allowedRawFontSizeFiles.has(rel)) continue
      for (const css of styleBlocks(file)) {
        for (const match of css.matchAll(/([^{}]+)\{([^}]*?)\}/gs)) {
          const selector = match[1].trim()
          if (selector.includes(':global') || selector.includes(':deep') || selector.includes('@keyframes')) continue
          if (selector.includes('>')) continue
          const body = match[2]
          const fontMatch = body.match(/font-size\s*:\s*([^;\n]+)/)
          if (!fontMatch) continue
          if (!SMALL_FONT.test(fontMatch[1])) continue
          if (LOOSE_TAG.test(selector)) {
            violations.push(`${rel}:${lineOf(css, match.index ?? 0)} ${selector} -> ${fontMatch[1].trim()}`)
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

  it('页面标题行间距由布局系统承载，禁止 .page-head 叠加私有 margin/padding-bottom', () => {
    // 事故复盘：QualityView/BoardView 的 .page-head { margin-bottom: 14px } 与 .lh-action 的
    // gap(12px) 叠加成 26px，造成页面间距不一致。间距一律由布局系统承载：
    //   - 操作区内块间距 = .lh-action gap(var(--app-space-3), 12px)
    //   - 页面级间距 = .v-page gap(--layout-page-gap, 预设 pageGap=14px)
    // 页面标题行(.page-head/.page-title-row/.title-row 等)禁止再声明 margin-bottom/padding-bottom。
    const violations: string[] = []
    for (const file of sourceFiles(SRC_DIR)) {
      const rel = relative(SRC_DIR, file)
      if (rel === 'styles/global.css') continue
      for (const css of styleBlocks(file)) {
        for (const match of css.matchAll(/([^{}]+)\{([^}]*?)\}/gs)) {
          const selector = match[1].trim()
          if (selector.includes(':global') || selector.includes(':deep') || selector.includes('@keyframes')) continue
          if (!/(\.page-head|\.page-title-row|\.title-row)(\s|,|:|\.|\{|$)/.test(selector)) continue
          const body = match[2]
          if (/margin-bottom\s*:\s*[^;}]+/.test(body) || /padding-bottom\s*:\s*[^;}]+/.test(body)) {
            violations.push(`${rel}:${lineOf(css, match.index ?? 0)} ${selector} -> ${body.trim().slice(0, 60)}`)
          }
        }
      }
    }

    expect(violations).toEqual([])
  })

  it('页头容器对齐钉标题顶：.page-head/.page-toolbar 禁止 flex-end/center，避免跨页抽屉按钮高度不一致', () => {
    // 事故复盘：各页把「标题+副标题」整块设为 .page-head，但 align-items 各自为政 —
    // flex-end 让动作区随副标题下沉、center 让动作区随文本块高度浮动，导致设置抽屉触发钮
    // 在不同页面高度不齐。统一钉标题顶：外层页头容器 align-items: flex-start。
    // 仅约束外层页头宿主（.page-head/.page-toolbar）；内嵌标题行 .page-title-row/.title-row
    // 负责标题与 HelpTip 居中（见 DESIGN §3），右侧子容器 .page-head-actions 对齐 32px 控件组，均不在此列。
    const violations: string[] = []
    for (const file of sourceFiles(SRC_DIR)) {
      const rel = relative(SRC_DIR, file)
      if (rel === 'styles/global.css') continue
      for (const css of styleBlocks(file)) {
        for (const match of css.matchAll(/([^{}]+)\{([^}]*?)\}/gs)) {
          const selector = match[1].trim()
          if (selector.includes(':global') || selector.includes(':deep') || selector.includes('@keyframes')) continue
          if (!/(\.page-head|\.page-toolbar|\.audit-head|\.dict-page-head)(\s|,|:|\.|\{|$)/.test(selector)) continue
          if (/(\.page-head-actions|\.page-title-row|\.title-row)/.test(selector)) continue
          const body = match[2]
          if (/(?:align-items|align-self)\s*:\s*(flex-end|center)/.test(body)) {
            violations.push(`${rel}:${lineOf(css, match.index ?? 0)} ${selector} -> ${body.trim().slice(0, 60)}`)
          }
        }
      }
    }

    expect(violations).toEqual([])
  })

  it('布局管理页统一消费全局页头结构，不再维护私有工具栏与副标题样式', () => {
    const layoutManagementPages = [
      'views/layout/LayoutPresetsView.vue',
      'views/layout/LayoutPagesView.vue',
      'views/layout/LayoutComponentsView.vue',
    ]

    for (const rel of layoutManagementPages) {
      const source = read(join(SRC_DIR, rel))
      expect(source, rel).toMatch(
        /<template #action>\s*<div class="lh-action">\s*<div class="page-head">/,
      )
      expect(source, rel).toMatch(/<h2 class="[^"]*\bapp-page-title\b[^"]*">/)
      expect(source, rel).toMatch(/<p class="page-subtitle">/)
      expect(source, rel).not.toContain('layout-toolbar')

      for (const css of styleBlocks(join(SRC_DIR, rel))) {
        expect(css, rel).not.toMatch(/\.page-subtitle\s*(?:,|\{)/)
      }
    }
  })

  it('新页面脚手架直接消费排版/间距事实源，并显式标记未完成占位', () => {
    const scaffold = read(join(FRONTEND_DIR, 'scripts/scaffold-page.mjs'))

    expect(scaffold).toContain('class="app-page-title"')
    expect(scaffold).toContain('gap: var(--app-space-3)')
    expect(scaffold).toContain('AppStateBlock')
    expect(scaffold).toContain('data-scaffold-placeholder')
    expect(scaffold).toContain('componentAllowedLayers,')
    expect(scaffold).toContain('componentLayerValuesOf, componentAllowedLayers }')
    expect(scaffold).not.toMatch(/\.page-toolbar h1\s*\{[\s\S]*?font-size\s*:/)
    expect(scaffold).not.toMatch(/\bgap\s*:\s*\d+px/)
  })
})
