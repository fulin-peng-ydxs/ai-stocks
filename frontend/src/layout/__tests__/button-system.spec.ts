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

function vueFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name)
    if (entry.isDirectory()) return vueFiles(path)
    return extname(entry.name) === '.vue' ? [path] : []
  })
}

function lineOf(source: string, index: number): number {
  return source.slice(0, index).split('\n').length
}

function visibleButtonText(content: string): string {
  return content
    .replace(/<!--[\s\S]*?-->/g, '')
    .replace(/<el-icon(?=[\s>/])[\s\S]*?<\/el-icon>/g, '')
    .replace(/<svg\b[\s\S]*?<\/svg>/g, '')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&nbsp;/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

describe('全站按钮与图标操作契约', () => {
  it('普通命令与纯图标操作有唯一公共实现和长期文档入口', () => {
    const design = read(join(PROJECT_DIR, 'DESIGN.md'))
    const pageTemplate = read(join(PROJECT_DIR, 'agent-works/configurable-layout-system/page-template.md'))
    const globalCss = read(join(SRC_DIR, 'styles/global.css'))

    expect(design).toContain('普通业务命令统一使用 Element Plus `<el-button>`')
    expect(design).toContain('纯图标操作统一使用 `AppIconButton`')
    expect(design).toContain('顶栏状态和工具按 `32px` 控件基线对齐')
    expect(design).toContain('文字 `13px / --app-font-weight-section`')
    expect(design).toContain('纯图标异步操作必须使用 `AppIconButton` 的 `loading`')
    expect(design).toContain('Unicode 禁令针对交互图标、操作按钮和纯图标控件')
    expect(pageTemplate).toContain('### 控件与操作规范')
    expect(pageTemplate).toContain('纯图标操作：使用 `AppIconButton`')
    expect(pageTemplate).toContain('异步纯图标操作使用 `:loading`')
    expect(globalCss).toContain('--app-control-height-md: 32px')
    expect(globalCss).toContain('--app-button-font-weight: var(--app-font-weight-section)')

    const sectionFontWeight = globalCss.match(/--app-font-weight-section:\s*([^;]+);/)?.[1].trim()
    const frontMatterButtonFontWeight = design
      .match(/button-md:\n(?:    .+\n)*?    fontWeight:\s*([^\n]+)/)?.[1]
      .trim()

    expect(frontMatterButtonFontWeight).toBe(sectionFontWeight)
  })

  it('应用外壳、页面设置和配置编辑器共同消费 AppIconButton', () => {
    const consumers = [
      'App.vue',
      'components/PageSettingsTrigger.vue',
      'components/PageSettingsDrawer.vue',
      'views/ConfigView.vue',
    ]

    for (const file of consumers) {
      expect(read(join(SRC_DIR, file)), file).toContain('AppIconButton')
    }
  })

  it('原生 button 只用于已声明的专用交互，不回流为页面私有命令按钮', () => {
    const allowedSpecializedClasses = /class="(?:topbar-status|appearance-mode-option|navigation-option|theme-option|workspace-tab-close|primary-entry|secondary-entry|seg-btn|slot-box(?: [^"]*)?|app-icon-button|login-[^"]+)"/
    const violations: string[] = []

    for (const file of vueFiles(SRC_DIR)) {
      const source = read(file)
      for (const match of source.matchAll(/<button\b(?:"[^"]*"|'[^']*'|[^'">])*>/g)) {
        if (!allowedSpecializedClasses.test(match[0])) {
          violations.push(`${relative(SRC_DIR, file)}: ${match[0].replace(/\s+/g, ' ')}`)
        }
      }
    }

    expect(violations).toEqual([])
  })

  it('纯图标 el-button 必须迁移到 AppIconButton', () => {
    const violations: string[] = []
    const elButtonStart = /<el-button(?=[\s>/])(?:[^>"']|"[^"]*"|'[^']*')*(?:\/>|>)/g

    for (const file of vueFiles(SRC_DIR)) {
      if (relative(SRC_DIR, file) === 'components/AppIconButton.vue') continue

      const source = read(file)
      for (const match of source.matchAll(elButtonStart)) {
        const startTag = match[0]
        const startIndex = match.index ?? 0
        const selfClosing = startTag.endsWith('/>')
        const contentStart = startIndex + startTag.length
        const closeIndex = selfClosing ? contentStart : source.indexOf('</el-button>', contentStart)
        const content = closeIndex >= 0 ? source.slice(contentStart, closeIndex) : ''
        const hasIconOnlySignal =
          /\bcircle(?:[\s=>/]|$)/.test(startTag) ||
          /\b:?icon\s*=/.test(startTag) ||
          /<el-icon(?=[\s>/])/.test(content)

        if (hasIconOnlySignal && visibleButtonText(content) === '') {
          violations.push(
            `${relative(SRC_DIR, file)}:${lineOf(source, startIndex)} ${startTag.replace(/\s+/g, ' ')}`
          )
        }
      }
    }

    expect(violations).toEqual([])
  })

  it('el-button 文案不使用 Unicode 字符冒充图标', () => {
    const violations: string[] = []
    const pseudoIconChars = /[＋▶‹›→]/u
    const elButton = /<el-button(?=[\s>/])(?:[^>"']|"[^"]*"|'[^']*')*>([\s\S]*?)<\/el-button>/g

    for (const file of vueFiles(SRC_DIR)) {
      const source = read(file)
      for (const match of source.matchAll(elButton)) {
        const text = visibleButtonText(match[1])
        if (pseudoIconChars.test(text)) {
          violations.push(`${relative(SRC_DIR, file)}:${lineOf(source, match.index ?? 0)} ${text}`)
        }
      }
    }

    expect(violations).toEqual([])
  })

  it('界面源码不使用 Unicode 字符冒充设置或关闭图标', () => {
    const violations = vueFiles(SRC_DIR)
      .filter((file) => /[⚙✕]/u.test(read(file)))
      .map((file) => relative(SRC_DIR, file))

    expect(violations).toEqual([])
  })

  it('选择态装饰勾允许保留为 aria-hidden 文案标记，不扩大为操作图标', () => {
    const app = read(join(SRC_DIR, 'App.vue'))
    const checkMarkers = [...app.matchAll(/<span class="theme-option-check" aria-hidden="true">✓<\/span>/g)]

    expect(checkMarkers).toHaveLength(2)
  })
})
