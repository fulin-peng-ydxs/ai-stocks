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

describe('全站按钮与图标操作契约', () => {
  it('普通命令与纯图标操作有唯一公共实现和长期文档入口', () => {
    const design = read(join(PROJECT_DIR, 'DESIGN.md'))
    const pageTemplate = read(join(PROJECT_DIR, 'agent-works/configurable-layout-system/page-template.md'))
    const globalCss = read(join(SRC_DIR, 'styles/global.css'))

    expect(design).toContain('普通业务命令统一使用 Element Plus `<el-button>`')
    expect(design).toContain('纯图标操作统一使用 `AppIconButton`')
    expect(design).toContain('顶栏状态和工具按 `32px` 控件基线对齐')
    expect(pageTemplate).toContain('### 控件与操作规范')
    expect(pageTemplate).toContain('纯图标操作：使用 `AppIconButton`')
    expect(globalCss).toContain('--app-control-height-md: 32px')
    expect(globalCss).toContain('--app-button-font-weight: 600')
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

  it('界面源码不使用 Unicode 字符冒充设置或关闭图标', () => {
    const violations = vueFiles(SRC_DIR)
      .filter((file) => /[⚙✕]/u.test(read(file)))
      .map((file) => relative(SRC_DIR, file))

    expect(violations).toEqual([])
  })
})
