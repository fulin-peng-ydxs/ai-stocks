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
    .replace(/{{[\s\S]*?}}/g, '')
    .replace(/<el-icon(?=[\s>/])[\s\S]*?<\/el-icon>/g, '')
    .replace(/<svg\b[\s\S]*?<\/svg>/g, '')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&nbsp;/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

describe('全站按钮与图标操作契约', () => {
  it('自定义直接点击入口必须同时提供键盘入口，纯事件容器不计入', () => {
    const violations: string[] = []
    for (const file of vueFiles(SRC_DIR)) {
      const source = read(file)
      for (const match of source.matchAll(/<(?:div|span|li|b|svg|path|strong|p|label|section|article|header|td|tr|el-tag)\b(?:"[^"]*"|'[^']*'|[^'">])*>/g)) {
        const tag = match[0]
        // 仅检查真实动作；@click.stop 等拦截冒泡的容器不承担点击命令。
        if (!/@click(?:\.[\w-]+)*="[^"\s][^"]*"/.test(tag)) continue
        if (!/tabindex=/.test(tag) || !/v-keyboard-activate/.test(tag)) {
          violations.push(`${relative(SRC_DIR, file)}:${lineOf(source, match.index ?? 0)}`)
        }
      }
    }
    expect(violations).toEqual([])
  })

  it('普通命令与纯图标操作有唯一公共实现和长期文档入口', () => {
    const design = read(join(PROJECT_DIR, 'DESIGN.md'))
    const pageTemplate = read(join(PROJECT_DIR, 'agent-works/configurable-layout-system/page-template.md'))
    const globalCss = read(join(SRC_DIR, 'styles/global.css'))

    expect(design).toContain('普通业务命令统一使用 Element Plus `<el-button>`')
    expect(design).toContain('纯图标操作统一使用 `AppIconButton`')
    expect(design).toContain('顶栏状态和工具按 `32px` 控件基线对齐')
    expect(design).toContain('文字 `13px / --app-font-weight-section`')
    expect(design).toContain('纯图标异步操作必须使用 `AppIconButton` 的 `loading`')
    expect(design).toContain('选择态勾选标记也使用 Element Plus 图标或项目 SVG')
    expect(design).toContain('控件宽度不按组件类型强制等宽')
    expect(design).toContain('新增或修改控件禁止匿名内联固定宽度')
    expect(pageTemplate).toContain('### 控件与操作规范')
    expect(pageTemplate).toContain('纯图标操作：使用 `AppIconButton`')
    expect(pageTemplate).toContain('异步纯图标操作使用 `:loading`')
    expect(pageTemplate).toContain('.app-control-width-compact/short/medium/long/wide/fill')
    expect(globalCss).toContain('--app-control-height-md: 32px')
    expect(globalCss).toContain('--app-control-width-compact: 96px')
    expect(globalCss).toContain('--app-control-width-wide: 300px')
    expect(globalCss).toMatch(/\.app-control-width-fill\s*\{[\s\S]*?--app-control-inline-width:\s*100%;[\s\S]*?min-width:\s*0;/)
    expect(globalCss).toContain('--app-button-font-weight: var(--app-font-weight-section)')

    for (const file of ['components/AppSearchInput.vue', 'components/AppFilterSelect.vue']) {
      expect(read(join(SRC_DIR, file)), file).toContain('width: var(--app-control-inline-width, 100%)')
    }

    const sectionFontWeight = globalCss.match(/--app-font-weight-section:\s*([^;]+);/)?.[1].trim()
    const frontMatterButtonFontWeight = design
      .match(/button-md:\n(?:    .+\n)*?    fontWeight:\s*([^\n]+)/)?.[1]
      .trim()

    expect(frontMatterButtonFontWeight).toBe(sectionFontWeight)
  })

  it('必须与禁止章节只保留系统级原则，组件实现细节由对应章节和清单承载', () => {
    const design = read(join(PROJECT_DIR, 'DESIGN.md'))
    const topLevelRules = design.match(/### 7\.1 必须遵守[\s\S]*?(?=### 7\.3 组件特性配置治理)/)?.[0] ?? ''

    expect(topLevelRules).not.toMatch(/AppFilterSelect|AppIconButton|HelpTip|HelpHint/)
    expect(topLevelRules).not.toMatch(/multiple=false|allowCreate|3 个标签|已选 N/)
    expect(design).toContain('默认多选、可搜索、可清空')
    expect(design).toContain('纯图标操作统一使用 `AppIconButton`')
    expect(design).toContain('单块纯文本说明优先进入 `HelpHint`')
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

  it('设置抽屉采用当前页面值统一复用主色朴素按钮', () => {
    const design = read(join(PROJECT_DIR, 'DESIGN.md'))
    const applyButton = read(join(SRC_DIR, 'components/PageSettingsApplyButton.vue'))
    const autoSettings = read(join(SRC_DIR, 'components/ComponentAutoSettings.vue'))

    expect(design).toContain('统一复用 `PageSettingsApplyButton`')
    expect(applyButton).toContain('type="primary"')
    expect(applyButton).toContain('plain')
    expect(applyButton).toContain(':loading="props.loading"')
    expect(applyButton).toContain('if (props.disabled || props.loading) return')
    expect(autoSettings).toContain("ElMessage.error('保存失败，请稍后重试')")
    expect(autoSettings).toContain('masterRatioChanged')
    expect(autoSettings).toContain('stockChartCurrentRatiosChanged')
    for (const file of [
      'components/MasterDetailRatioProfileSettings.vue',
      'components/StockChartSettingSection.vue',
    ]) {
      expect(read(join(SRC_DIR, file)), file).toContain('PageSettingsApplyButton')
    }
  })

  it('列表普通操作与禁用态使用不同文本层级', () => {
    const rowActions = read(join(SRC_DIR, 'components/AppRowActions.vue'))

    const states = read(join(SRC_DIR, 'styles/buttonStates.css'))
    expect(rowActions).not.toContain('--row-action-text:')
    expect(rowActions).not.toContain('--row-action-menu-bg:')
    expect(states).toContain('--app-button-neutral-text: var(--el-text-color-regular)')
    expect(states).toContain('--app-button-disabled-text: var(--el-disabled-text-color)')

  })

  it('命令状态接入全局样式，按下色不回退通用填充且默认行操作不匹配语义通配符', () => {
    const states = read(join(SRC_DIR, 'styles/buttonStates.css'))
    expect(read(join(SRC_DIR, 'styles/global.css'))).toContain("@import './buttonStates.css'")
    expect(states).not.toMatch(/var\(--el-fill-color(?:-dark)?\)/)
    expect(states).not.toContain("[class*='is-tone-']")
    for (const tone of ['primary', 'success', 'warning', 'danger', 'info']) {
      expect(states).toContain(`.el-button--${tone}`)
      expect(states).toContain(`.el-button.is-tone-${tone}`)
    }
    expect(states).toContain('.app-icon-button:not([data-close-size])')
    expect(states).toContain('@media (hover: none), (pointer: coarse)')
    expect(states).toContain('@media (prefers-reduced-motion: reduce)')
  })

  it('原生 button 只用于已声明的专用交互，不回流为页面私有命令按钮', () => {
    const allowedSpecializedClasses = /class="(?:topbar-status|appearance-mode-option|(?:navigation-option|theme-option)(?: app-interaction-target app-interaction-card)?|primary-entry(?: app-nav-context-entry)?(?: app-interaction-target app-interaction-nav)?|secondary-entry(?: app-nav-context-entry)?(?: app-interaction-target app-interaction-nav)?|seg-btn|pt-group-toggle|slot-box(?: [^"]*)?|app-icon-button|app-summary-disclosure-card__summary|login-[^"]+)"/
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

        const hasDynamicText = /{{[\s\S]*?}}/.test(content)
        if (hasIconOnlySignal && visibleButtonText(content) === '' && !hasDynamicText) {
          violations.push(
            `${relative(SRC_DIR, file)}:${lineOf(source, startIndex)} ${startTag.replace(/\s+/g, ' ')}`
          )
        }
      }
    }

    expect(violations).toEqual([])
  })

  it('交互按钮可见文案只允许中英文、数字和常用标点，图标必须走图标组件', () => {
    const violations: string[] = []
    const allowedButtonText = /^[\p{Script=Han}A-Za-z0-9\s.,;:!?'"()（）【】[\]《》<>、，。；：！？“”‘’·/\\\-–—+_=#%&@|~…]+$/u
    const elButton = /<el-button(?=[\s>/])(?:[^>"']|"[^"]*"|'[^']*')*>([\s\S]*?)<\/el-button>/g
    const nativeButton = /<button(?=[\s>/])(?:[^>"']|"[^"]*"|'[^']*')*>([\s\S]*?)<\/button>/g

    for (const file of vueFiles(SRC_DIR)) {
      const rel = relative(SRC_DIR, file)
      const source = read(file)
      for (const match of source.matchAll(elButton)) {
        const text = visibleButtonText(match[1])
        if (text && !allowedButtonText.test(text)) {
          violations.push(`${rel}:${lineOf(source, match.index ?? 0)} <el-button> ${text}`)
        }
      }
      for (const match of source.matchAll(nativeButton)) {
        const text = visibleButtonText(match[1])
        if (text && !allowedButtonText.test(text)) {
          violations.push(`${rel}:${lineOf(source, match.index ?? 0)} <button> ${text}`)
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

  it('选择态勾选标记使用图标组件，不保留 Unicode 勾作为交互控件图形', () => {
    const app = read(join(SRC_DIR, 'App.vue'))

    expect(app).not.toContain('class="theme-option-check" aria-hidden="true">✓')
    expect(app).toContain('<el-icon class="theme-option-check app-interaction-content" aria-hidden="true"><Select /></el-icon>')
  })
})
