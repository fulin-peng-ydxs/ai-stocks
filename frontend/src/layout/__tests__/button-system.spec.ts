import { FULL_SOURCE_AUDIT_TIMEOUT_MS } from './helpers/fullSourceAudit'
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
  }, FULL_SOURCE_AUDIT_TIMEOUT_MS)

  it('普通命令与纯图标操作消费共享尺寸和字重契约', () => {
    const design = read(join(PROJECT_DIR, 'DESIGN.md'))
    const globalCss = read(join(SRC_DIR, 'styles/global.css'))

    expect(globalCss).toContain('--app-control-height-md: 32px')
    expect(globalCss).toContain('--app-control-width-compact: 96px')
    expect(globalCss).toContain('--app-control-width-wide: 300px')
    expect(globalCss).toMatch(/\.app-control-width-fill\s*\{[\s\S]*?--app-control-inline-width:\s*100%;[\s\S]*?min-width:\s*0;/)
    expect(globalCss).toContain('--app-button-font-weight: var(--app-font-weight-medium)')
    expect(globalCss).toMatch(/\.el-button\s*\{[^}]*font-weight: var\(--app-button-font-weight\)/)
    expect(globalCss).toMatch(/\.app-command-menu-popper \.el-dropdown-menu__item\s*\{[^}]*font-weight: var\(--app-button-font-weight\)/)
    expect(read(join(SRC_DIR, 'views/LoginView.vue')))
      .toMatch(/\.login-primary\s*\{[^}]*font-weight: var\(--app-button-font-weight\)/)

    for (const file of ['components/AppSearchInput.vue', 'components/AppFilterSelect.vue']) {
      expect(read(join(SRC_DIR, file)), file).toContain('width: var(--app-control-inline-width, 100%)')
    }

    const commandFontWeight = globalCss.match(/--app-font-weight-medium:\s*([^;]+);/)?.[1].trim()
    const frontMatterButtonFontWeight = design
      .match(/button-md:\n(?:    .+\n)*?    fontWeight:\s*([^\n]+)/)?.[1]
      .trim()

    expect(commandFontWeight).toBe('500')
    expect(frontMatterButtonFontWeight).toBe(commandFontWeight)
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
    const applyButton = read(join(SRC_DIR, 'components/PageSettingsApplyButton.vue'))
    const autoSettings = read(join(SRC_DIR, 'components/ComponentAutoSettings.vue'))

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
    expect(states).not.toMatch(/\bfont(?:-weight)?\s*:/)
    expect(rowActions).not.toContain('--row-action-text:')
    expect(rowActions).not.toContain('--row-action-menu-bg:')
    expect(states).toContain('--app-button-neutral-text: var(--el-text-color-regular)')
    expect(states).toContain('--app-button-disabled-text: var(--el-disabled-text-color)')
    // 普通 info 与行操作 info 的常态文字共用中性角色，交互反馈按外形处理。
    expect(states).toContain(':where(.el-button--info, .is-tone-info)')

  })

  it('训练买卖命令不借用危险/成功色表达交易方向', () => {
    const training = read(join(SRC_DIR, 'views/TrainingView.vue'))
    for (const command of ['doBuy', 'doSell']) {
      const tag = training.match(new RegExp(`<el-button[^>]+@click="${command}"[^>]*>`))?.[0]
      expect(tag).toContain('type="primary"')
      expect(tag).toContain('plain')
    }
    expect(training).not.toMatch(/<el-button[^>]*type="(?:danger|success)"/)
  })

  it('命令状态接入全局样式，按下色不回退通用填充且默认行操作不匹配语义通配符', () => {
    const states = read(join(SRC_DIR, 'styles/buttonStates.css'))
    expect(read(join(SRC_DIR, 'styles/global.css'))).toContain("@import './buttonStates.css'")
    expect(states).not.toMatch(/var\(--el-fill-color(?:-dark)?\)/)
    expect(states).not.toContain("[class*='is-tone-']")
    // 常态文字/实体背景消费主题原色，不能再次引入自动对比度调色。
    expect(states).toContain('--app-button-rest-text: var(--app-button-tone)')
    expect(states).toContain('--app-button-rest-bg: var(--app-button-tone)')
    expect(states).not.toContain('--app-button-tone-text')
    for (const tone of ['primary', 'success', 'warning', 'danger', 'info']) {
      expect(states).toContain(`.el-button--${tone}`)
      expect(states).toContain(`.el-button.is-tone-${tone}`)
    }
    expect(states).toContain('.app-icon-button:not([data-close-size])')
    expect(states).toContain('@media (hover: none), (pointer: coarse)')
    expect(states).toContain('@media (prefers-reduced-motion: reduce)')
  })

  it('原生 button 只用于已声明的专用交互，不回流为页面私有命令按钮', () => {
    // 允许项绑定到真实文件和控件角色，不能凭 login-* 等页面前缀绕过组件契约。
    const allowedSpecializedClasses: Record<string, string[]> = {
      'App.vue': ['topbar-status', 'theme-option', 'navigation-option'],
      'components/TopNavigation.vue': ['primary-entry', 'secondary-entry'],
      'components/PageSegmented.vue': ['seg-btn'],
      'components/AppIconButton.vue': ['app-icon-button'],
      'layout/components/LayoutPagePreview.vue': ['slot-box'],
      'views/system/PermissionTree.vue': ['pt-group-toggle'],
      'views/LoginView.vue': ['login-primary', 'login-tab'],
    }
    const violations: string[] = []

    for (const file of vueFiles(SRC_DIR)) {
      const source = read(file)
      for (const match of source.matchAll(/<button\b(?:"[^"]*"|'[^']*'|[^'">])*>/g)) {
        const baseClass = match[0].match(/\bclass="([^"]+)"/)?.[1].split(/\s+/)[0]
        if (!baseClass || !allowedSpecializedClasses[relative(SRC_DIR, file)]?.includes(baseClass)) {
          violations.push(`${relative(SRC_DIR, file)}: ${match[0].replace(/\s+/g, ' ')}`)
        }
      }
    }

    expect(violations).toEqual([])
  }, FULL_SOURCE_AUDIT_TIMEOUT_MS)

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
  }, FULL_SOURCE_AUDIT_TIMEOUT_MS)

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
  }, FULL_SOURCE_AUDIT_TIMEOUT_MS)

  it('界面源码不使用 Unicode 字符冒充设置或关闭图标', () => {
    const violations = vueFiles(SRC_DIR)
      .filter((file) => /[⚙✕]/u.test(read(file)))
      .map((file) => relative(SRC_DIR, file))

    expect(violations).toEqual([])
  }, FULL_SOURCE_AUDIT_TIMEOUT_MS)

  it('选择态勾选标记使用图标组件，不保留 Unicode 勾作为交互控件图形', () => {
    const app = read(join(SRC_DIR, 'App.vue'))

    expect(app).not.toContain('class="theme-option-check" aria-hidden="true">✓')
    expect(app).toContain('<el-icon class="theme-option-check app-interaction-content" aria-hidden="true"><Select /></el-icon>')
  })
})
