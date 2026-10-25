import { readFileSync, readdirSync } from 'node:fs'
import { dirname, extname, join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import { baseParse, type ElementNode, type TemplateChildNode } from '@vue/compiler-dom'
import { parse as parseSfc } from '@vue/compiler-sfc'

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

const SIZE_MEDIA_QUERY = /@media[^{}]*\([^)]*\b(?:(?:min|max)-)?(?:width|height)\b/

/** 逐控件检查，避免同文件内只有一个下拉接入契约就掩盖其余遗漏。 */
function floatingContractViolations(source: string, file: string): string[] {
  const template = parseSfc(source).descriptor.template
  if (!template) return []
  const violations: string[] = []
  const tagOf = (node: ElementNode) => node.tag.replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`).replace(/^-/, '')
  const valueOf = (node: ElementNode, name: string): string | undefined => {
    const prop = node.props.find((p) => p.type === 6 ? p.name === name : p.arg?.type === 4 && p.arg.content === name)
    return prop?.type === 6 ? prop.value?.content : prop?.exp?.type === 4 ? prop.exp.content : undefined
  }
  const hasBound = (node: ElementNode, name: string, expression: string) => node.props.some(
    (p) => p.type === 7 && p.name === 'bind' && p.arg?.type === 4
      && p.arg.content === name && p.exp?.type === 4 && p.exp.content === expression,
  )
  const selects = new Set(['el-select', 'el-select-v2', 'el-cascader', 'el-tree-select'])
  const panels = new Set([...selects, 'el-date-picker', 'el-time-picker', 'el-time-select'])
  const menus = new Set(['el-dropdown', 'el-popover'])
  const optionTags = new Set(['el-option', 'el-option-group', 'el-dropdown-item', 'el-dropdown-menu'])
  const inspect = (node: TemplateChildNode, ancestors: ElementNode[]) => {
    if (node.type !== 1) return
    const tag = tagOf(node)
    const where = `${file}:${template.loc.start.line + node.loc.start.line - 1} ${tag}`
    if (tag === 'market-benchmark-select' && (valueOf(node, 'width') || valueOf(node, 'style'))) {
      violations.push(`${where}: benchmark width must be owned by shared selector`)
    }
    const selectRuntime = file === 'components/AppSelect.vue' && tag === 'el-select'
    if ((tag === 'el-select' || node.tag === 'select') && !selectRuntime) {
      violations.push(`${where}: use AppSelect instead of native select`)
    }
    if (tag === 'app-select' || selects.has(tag)) {
      const width = valueOf(node, 'width')
      if (width && !['compact', 'short', 'medium', 'long', 'wide', 'fill'].includes(width)) {
        violations.push(`${where}: semantic width`)
      }
      if (/(?:^|;)\s*(?:min-|max-)?width\s*:\s*[\d.]+(?:px|rem|em)\b/.test(valueOf(node, 'style') ?? '')) {
        violations.push(`${where}: inline fixed width`)
      }
    }
    if (panels.has(tag) || menus.has(tag)) {
      // 底层共享入口集中维护默认值，消费方不再重复配置。
      const dateRuntime = file === 'components/AppDatePicker.vue' && tag === 'el-date-picker'
      const placements = dateRuntime || selectRuntime ? ['placement']
        : ['APP_BOTTOM_FLOATING_PLACEMENT', 'APP_BOTTOM_END_FLOATING_PLACEMENT']
      if (!placements.some((placement) => hasBound(node, 'placement', placement))) violations.push(`${where}: placement`)
      const property = tag === 'el-dropdown' ? 'popper-options' : 'fallback-placements'
      const expression = tag === 'el-dropdown' ? 'APP_BOTTOM_FLOATING_POPPER_OPTIONS'
        : dateRuntime || selectRuntime ? 'fallbackPlacements' : 'APP_BOTTOM_FLOATING_FALLBACKS'
      if (!hasBound(node, property, expression)) violations.push(`${where}: ${property}`)
    }
    if (tag === 'el-option' || tag === 'el-dropdown-item') {
      const compound = node.children.some((child) => child.type === 1)
      const owner = [...ancestors].reverse().find((ancestor) => !optionTags.has(tagOf(ancestor))
        && (selects.has(tagOf(ancestor)) || ['app-select', 'el-dropdown'].includes(tagOf(ancestor))))
      if (compound && owner) {
        const boundary = (valueOf(owner, 'popper-class') ?? '').split(/\s+/)
          .filter((name) => name && name !== 'app-option-popper')
        if (!boundary.length) violations.push(`${where}: compound option popper-class`)
      }
    }
    for (const child of node.children) inspect(child, [...ancestors, node])
  }
  for (const node of baseParse(template.content).children) inspect(node, [])
  return violations
}

/** gap 可由一个或两个语义值组成；零与 token 组合不构成游离间距。 */
function isTokenGap(value: string): boolean {
  const parts = value.match(/var\((?:[^()]|\([^()]*\))*\)|\S+/g) ?? []
  return parts.length >= 1 && parts.length <= 2
    && parts.every(part => part === '0' || /^var\(--[\w-]+(?:,|\))/.test(part))
}

describe('字体与间距设计契约', () => {
  it('所有卡片圆角变量均有定义，外框不叠加白色顶部亮边', () => {
    const styles = sourceFiles(SRC_DIR).flatMap(file =>
      styleBlocks(file).map(source => ({ file, source })))
    const defined = new Set(styles.flatMap(({ source }) =>
      [...source.matchAll(/(--(?:app|layout)-[\w-]+)\s*:/g)].map(match => match[1])))
    const missing: string[] = []
    const highlights: string[] = []
    for (const { file, source } of styles) {
      for (const declaration of source.matchAll(/border(?:-[\w-]+)?radius\s*:\s*([^;{}]+)/g)) {
        for (const token of declaration[1].matchAll(/var\((--(?:app|layout)-[\w-]+)/g)) {
          if (!defined.has(token[1])) missing.push(`${relative(SRC_DIR, file)}: ${token[1]}`)
        }
      }
      if (/box-shadow\s*:[^;}]*inset\s+0\s+1px[^;}]*(?:\bwhite\b|rgba?\(255\s*,\s*255\s*,\s*255)/.test(source)) {
        highlights.push(relative(SRC_DIR, file))
      }
    }
    expect(missing).toEqual([])
    expect(highlights).toEqual([])
  })

  it('浮起只接入明确交互角色，视觉层不接管点击并提供禁用与减弱动效边界', () => {
    const css = read(join(SRC_DIR, 'styles/global.css'))
    for (const file of [
      'components/SideMenuItem.vue', 'components/TopNavigation.vue', 'components/WorkspaceTabs.vue',
      'components/MarketCompareMetricStrip.vue', 'views/limit-ladder/LimitLadderCard.vue',
      'views/ConfigView.vue', 'views/trade-discipline/components/RuleMasterList.vue',
      'App.vue',
    ]) {
      expect(read(join(SRC_DIR, file)), file).toContain('app-interaction-target')
    }
    // 统计卡是只读摘要；导航由具名动作承接，不以整卡浮起来暗示可点击。
    expect(read(join(SRC_DIR, 'views/data/OverviewView.vue'))).toContain('<DataMetricCard')
    const dataMetric = read(join(SRC_DIR, 'components/data/DataMetricCard.vue'))
    expect(dataMetric).not.toContain('app-interaction-target')
    expect(dataMetric).toContain('actionLabel')
    const shadowLayer = css.match(/::before\s*\{([^}]+)\}/)?.[1] ?? ''
    expect(shadowLayer).toContain('pointer-events: none')
    expect(shadowLayer).not.toMatch(/(?:^|;)\s*(?:border|background):/)
    expect(shadowLayer).not.toContain('--app-interaction-marker')
    // 卡片边框由唯一浮起表面负责，固定宿主不能再绘制第二套轮廓。
    const cardHost = css.match(/html\[data-layout-preset\] \.app-interaction-target\.app-interaction-card\s*\{([^}]+)\}/)?.[1] ?? ''
    expect(cardHost).toContain('border-color: transparent')
    expect(cardHost).toContain('background: transparent')
    expect(cardHost).toContain('box-shadow: none')
    expect(css).toMatch(/\.app-interaction-target\.app-interaction-card::before\s*\{[^}]*--app-interaction-card-background[^}]*--app-interaction-marker[^}]*transform: translateY/)

    const metrics = read(join(SRC_DIR, 'components/MarketCompareMetricStrip.vue'))
    expect(metrics).not.toContain('app-interaction-card')
    expect(metrics).toContain('.market-metric::before { content: none; }')
    expect(metrics).toContain('background: var(--app-interaction-selected-background)')
    expect(metrics).not.toMatch(/color-mix\([^;]*var\(--el-color-primary\)/)
    expect(css).toContain('@media (hover: hover) and (pointer: fine)')
    expect(css).toContain(':not(.app-interaction-delegated, :disabled, .is-disabled, .is-loading,')
    expect(css).toContain(':has(.app-interaction-trigger:not(:disabled')
    expect(css).toMatch(/\.app-interaction-delegated \.app-interaction-trigger:focus-visible\s*\{[^}]*outline: none/)
    expect(css).toMatch(/@media \(prefers-reduced-motion: reduce\)\s*\{[^}]*\.app-interaction-content[^}]*transform: none !important/)
    expect(css).not.toMatch(/\.el-card:hover|transition:\s*all\b/)
    const side = read(join(SRC_DIR, 'components/SideMenu.vue'))
    expect(side).toContain('class="menu-label section-heading"')
    expect(side).not.toContain('class="menu-label section-heading app-interaction')
  })

  it('菜单悬停与焦点共用中性表面入口，当前项通过角色变量保持定位色', () => {
    const css = read(join(SRC_DIR, 'styles/global.css'))
    const side = read(join(SRC_DIR, 'components/SideMenu.vue'))
    const top = read(join(SRC_DIR, 'components/TopNavigation.vue'))
    expect(css).toContain('--app-interaction-nav-hover-background: var(--chrome-bg-soft-hover)')
    expect(css).toMatch(/html\[data-layout-preset\] \.el-button\.app-interaction-target\s*\{[^}]*transition: var\(--app-interaction-color-transition\)/)
    // 键盘焦点不依赖指针能力，hover 只在精细指针设备启用。
    expect(css).toMatch(/:focus-visible[^{]*\{[^}]*background: var\(--app-interaction-nav-hover-background\)/)
    expect(css).toMatch(/@media \(hover: hover\) and \(pointer: fine\)\s*\{[^}]*:hover[^}]*background: var\(--app-interaction-nav-hover-background\)/)
    expect(side).not.toContain('background: var(--chrome-bg-soft)')
    expect(side).not.toMatch(/\.el-menu-item[^}]*:hover/)
    expect(side).toContain('--app-interaction-nav-hover-background: var(--chrome-nav-leaf-active-hover-bg)')
    expect(top).toContain('--app-interaction-nav-hover-background: transparent')
    expect(top).toContain('--app-interaction-nav-hover-color: var(--el-color-primary)')
  })

  it('侧栏与双排顶栏按相同导航角色消费字阶，辅助导航保留独立档位', () => {
    const css = read(join(SRC_DIR, 'styles/global.css'))
    const side = read(join(SRC_DIR, 'components/SideMenu.vue'))
    const top = read(join(SRC_DIR, 'components/TopNavigation.vue'))
    const tabs = read(join(SRC_DIR, 'components/WorkspaceTabs.vue'))
    const app = read(join(SRC_DIR, 'App.vue'))
    const rule = (source: string, selector: string) => {
      const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
      return source.match(new RegExp(`${escaped}\\s*\\{([^}]+)\\}`))?.[1] ?? ''
    }
    expect(css).toContain('--app-nav-font-size: var(--app-font-size-body)')
    expect(css).toContain('--app-nav-font-family: var(--app-font-family-base)')
    expect(css).toContain('--app-nav-meta-font-size: var(--app-font-size-caption)')
    for (const [source, selector] of [
      [side, '.menu :deep(.side-menu-node > .el-sub-menu__title)'],
      [top, '.primary-entry'], [top, '.secondary-entry'],
      [top, '.top-navigation-dropdown .el-dropdown-menu__item'],
      [app, '.shell-breadcrumb'],
    ]) {
      expect(rule(source, selector), selector).toContain('font-size: var(--app-nav-font-size)')
      expect(rule(source, selector), selector).toContain('line-height: var(--app-nav-line-height)')
      expect(rule(source, selector), selector).toContain('font-family: var(--app-nav-font-family)')
    }
    for (const selector of ['.primary-entry', '.secondary-entry']) {
      expect(rule(top, selector), selector).toContain('font-weight: var(--app-nav-weight-primary)')
    }
    expect(rule(top, '.primary-entry')).toContain('color: var(--chrome-text)')
    expect(rule(top, '.top-navigation-dropdown .el-dropdown-menu__item'))
      .toContain('font-weight: var(--app-nav-weight-regular)')
    expect(rule(top, '.secondary-entry.is-active')).toContain('font-weight: var(--app-nav-weight-active)')
    expect(rule(side, '.menu :deep(.is-root-menu-node > .el-sub-menu__title)'))
      .toContain('font-weight: var(--app-nav-weight-primary)')
    expect(rule(side, '.menu :deep(.el-sub-menu.is-active > .el-sub-menu__title)'))
      .toContain('font-weight: var(--app-nav-weight-active)')
    for (const [source, selector] of [
      [side, '.menu :deep(.menu-section > .el-menu-item-group__title)'],
      [top, '.secondary-context'],
    ]) {
      expect(rule(source, selector), selector).toContain('font-size: var(--app-nav-meta-font-size)')
      expect(rule(source, selector), selector).toContain('font-family: var(--app-nav-font-family)')
      expect(rule(source, selector), selector).toContain('line-height: var(--app-nav-meta-line-height)')
    }
    // 工作标签独立消费字号角色，避免调整标签时连带改变分区标题与辅助提示。
    expect(css).toContain('--app-nav-tab-font-size: var(--app-font-size-table)')
    expect(rule(tabs, '.workspace-tab')).toContain('font-size: var(--app-nav-tab-font-size)')
    expect(rule(tabs, '.workspace-tab')).toContain('font-family: var(--app-nav-font-family)')
    expect(rule(tabs, '.workspace-tab')).toContain('line-height: var(--app-nav-meta-line-height)')
  })

  it('横向导航共享尺寸和选中壳层，侧栏与下拉消费同一导航几何和叶子颜色', () => {
    const css = read(join(SRC_DIR, 'styles/global.css'))
    const side = read(join(SRC_DIR, 'components/SideMenu.vue'))
    const top = read(join(SRC_DIR, 'components/TopNavigation.vue'))
    const tabs = read(join(SRC_DIR, 'components/WorkspaceTabs.vue'))
    const app = read(join(SRC_DIR, 'App.vue'))
    // 一级保留图标框和栏底定位线，仅悬停表面紧凑；二级/标签复用选中壳层。
    expect(top).not.toContain('class="primary-entry app-nav-context-entry ')
    expect(top).toContain('.primary-entry.is-active::after')
    expect(top).toContain('.primary-entry.is-active .primary-entry-icon')
    expect(top).toContain('--app-interaction-inset: calc((100% - var(--app-nav-context-entry-height)) / 2)')
    expect(top.match(/class="secondary-entry app-nav-context-entry(?: [^"]+)?"/g)).toHaveLength(2)
    expect(tabs).toContain('class="workspace-tab app-nav-context-entry ')
    expect(css).toMatch(/\.app-nav-context-entry\s*\{[^}]*height: var\(--app-nav-context-entry-height\)/)
    expect(css).toMatch(/\.app-nav-context-entry\.is-active\s*\{[^}]*border-color: var\(--chrome-nav-entry-active-border\)[^}]*box-shadow:/)
    expect(css).toContain('--app-nav-context-entry-height: var(--app-control-height-md)')
    for (const source of [top, tabs, side]) {
      expect(source).not.toContain('border-radius: 8px')
    }
    for (const source of [top, tabs]) {
      expect(source).toContain('height: var(--app-nav-context-bar-height)')
      expect(source).not.toMatch(/border-color: color-mix\([^;]+var\(--shell-accent\)/)
    }
    for (const source of [side, top]) {
      expect(source).toContain('background: var(--chrome-nav-leaf-active-bg)')
      expect(source).toContain('var(--app-nav-icon-size)')
      expect(source).toContain('var(--app-nav-icon-size-nested)')
    }
    expect(side).toContain('height: var(--app-nav-side-primary-height)')
    expect(side).toContain('height: var(--app-nav-side-nested-height)')
    expect(app).toContain('grid-template-columns: var(--app-nav-sidebar-width)')
    expect(app).toContain('grid-template-rows: var(--app-nav-topbar-height)')
  })

  it('页面设置抽屉以稳定字体角色和结构线表达层级', () => {
    const globalCss = read(join(SRC_DIR, 'styles/global.css'))
    const drawer = read(join(SRC_DIR, 'components/PageSettingsDrawer.vue'))
    const drawerSurface = read(join(SRC_DIR, 'components/PageDrawerSurface.vue'))
    const detailDrawer = read(join(SRC_DIR, 'components/AppDetailDrawer.vue'))
    const appShell = read(join(SRC_DIR, 'App.vue'))
    const group = read(join(SRC_DIR, 'components/SettingsGroup.vue'))
    const section = read(join(SRC_DIR, 'components/PageSettingSection.vue'))
    const item = read(join(SRC_DIR, 'components/PageSettingItem.vue'))

    expect(globalCss).toContain('--app-font-size-drawer-title: 16px')
    expect(globalCss).toContain('--app-line-height-drawer-title: 24px')
    expect(globalCss).toMatch(/\.app-drawer-title\s*\{[\s\S]*?font-size: var\(--app-font-size-drawer-title\)[\s\S]*?font-weight: var\(--app-font-weight-section\)/)
    expect(globalCss).toMatch(/\.app-drawer-title--compact\s*\{[\s\S]*?font-size: var\(--app-font-size-section-title\)[\s\S]*?font-weight: var\(--app-font-weight-section\)/)
    expect(globalCss).toMatch(/\.app-drawer-subtitle\s*\{[\s\S]*?font-size: var\(--app-font-size-caption\)/)
    expect(drawer).not.toContain('<PageDrawerSurface')
    expect(drawer).toContain('<PageDrawer')
    expect(drawerSurface).toContain("'app-drawer-title--compact' : 'app-drawer-title'")
    expect(drawerSurface).toContain("'is-title-compact': titleSize === 'compact'")
    expect(drawerSurface).toMatch(/\.page-drawer-surface\.is-title-compact\s*\{[\s\S]*?--app-settings-group-level-one-font-size: var\(--app-font-size-body\)/)
    expect(drawerSurface).not.toMatch(/\.page-drawer-surface__title\s*\{[^}]*font-size:/)
    expect(appShell.match(/<PageDrawer\b/g)).toHaveLength(2)
    expect(appShell).not.toContain('<el-drawer')
    expect(appShell.match(/<SettingsGroup/g)).toHaveLength(4)
    expect(appShell).not.toContain('class="theme-card"')
    expect(appShell).not.toMatch(/\.theme-card\s*\{/)
    expect(appShell).not.toContain('class="drawer-card"')
    expect(appShell).not.toMatch(/\.drawer-card\s*\{/)
    expect(detailDrawer).toContain('<PageDrawer')
    expect(detailDrawer).toContain(':subtitle="subtitle"')
    expect(detailDrawer).not.toContain('<h2 class="app-drawer-title">')
    expect(detailDrawer).not.toMatch(/\.app-detail-drawer__heading h2\s*\{/)
    expect(appShell).toContain('title="视觉环境"')
    expect(appShell).toContain('subtitle="调整界面比例、页面密度、阅读光线与导航方式"')
    expect(group).toContain("'sg-nested': !transparent() && effectiveLevel > 1")
    expect(group).toMatch(/\.sg-l1 > \.sg-head \.sg-title\s*\{[\s\S]*?--app-settings-group-level-one-font-size[\s\S]*?var\(--app-font-size-section-title\)[\s\S]*?font-weight: var\(--app-font-weight-section\)/)
    expect(group).toContain('border-left: 1px solid var(--page-settings-section-border)')
    expect(group).toContain('font-size: var(--app-font-size-body)')
    expect(group).not.toContain('text-transform: uppercase')
    expect(group).not.toContain('text-decoration: underline dotted')
    expect(section).toContain('<SettingsGroup')
    expect(section).not.toContain('<style')
    expect(item).toContain('font-size: var(--app-font-size-table)')

    const duplicatedItemStyles = sourceFiles(SRC_DIR)
      .filter((file) => !file.endsWith('PageSettingItem.vue'))
      .filter((file) => /\.setting-(item|label)\s*\{/.test(read(file)))
      .map((file) => relative(SRC_DIR, file))
    expect(duplicatedItemStyles).toEqual([])
  })

  it('三档页面密度使用唯一语义变量矩阵', () => {
    const globalCss = read(join(SRC_DIR, 'styles/global.css'))
    const expected = {
      compact: [8, 8, 12, 6, 8, 28, 10, 6, 12, 8],
      standard: [12, 12, 16, 8, 12, 32, 12, 10, 16, 12],
      comfortable: [16, 16, 24, 12, 16, 36, 14, 14, 24, 16],
    }
    const variables = [
      'page-gap', 'section-gap', 'card-padding', 'control-gap', 'form-gap',
      'control-height', 'button-padding-x', 'table-cell-padding-y',
      'overlay-padding', 'overlay-group-gap',
    ]
    for (const [density, values] of Object.entries(expected)) {
      const block = globalCss.match(new RegExp(`\\.lh-density-${density} \\{([\\s\\S]*?)\\}`))?.[1] ?? ''
      variables.forEach((variable, index) => {
        expect(block).toContain(`--app-density-${variable}: ${values[index]}px`)
      })
      expect(block).toContain('--layout-page-gap: var(--app-density-page-gap)')
      expect(block).toContain('--layout-card-padding: var(--app-density-card-padding)')
      expect(block).toContain('--layout-table-cell-padding-y: var(--app-density-table-cell-padding-y)')
      expect(block).not.toContain('font-size')
    }
  })

  it('组件配置不得重新提供页面密度的平行入口', () => {
    const schemas = read(join(SRC_DIR, 'layout/componentSchemas.ts'))
    const catalog = read(join(SRC_DIR, 'layout/components.ts'))
    for (const deprecated of ['itemDensity', 'cardDensity']) {
      expect(schemas).not.toContain(deprecated)
      expect(catalog).not.toContain(deprecated)
    }
    expect(schemas).not.toMatch(/'page-shell':\s*\{[^}]*density/)
    expect(catalog).not.toMatch(/configCapabilities:\s*\[[^\]]*'density'/)
  })

  it('业务页和组件不得创建私有密度或平行表格密度规则', () => {
    const violations: string[] = []
    for (const file of sourceFiles(SRC_DIR)) {
      if (file.endsWith('styles/global.css') || file.endsWith('layout/components/LayoutHost.vue')) continue
      const source = read(file)
      if (/\.lh-density-|\.page-table-compact/.test(source)) {
        violations.push(relative(SRC_DIR, file))
      }
    }
    expect(violations).toEqual([])
  })

  it('DESIGN、页面模板和全局样式声明同一套字体/间距事实源', () => {
    const design = read(join(PROJECT_DIR, 'DESIGN.md'))
    const pageTemplate = read(join(PROJECT_DIR, 'agent-works/configurable-layout-system/page-template.md'))
    const globalCss = read(join(SRC_DIR, 'styles/global.css'))

    expect(design).toContain('### 3.1 间距与节奏规范')
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
    expect(globalCss).toMatch(/html\[data-layout-preset\] \.el-table \.cell\s*\{\s*line-height: var\(--app-table-content-line-height\)/)
    expect(globalCss).toContain('@media (max-resolution: 1.5dppx)')
    expect(globalCss).toContain('.lh-density-comfortable')
    expect(globalCss).toContain('--app-font-weight-section: 600')
    expect(globalCss).toContain('--app-line-height-solid')
    expect(globalCss).toContain('--app-space-control-gap')
    expect(globalCss).toContain('--app-display-scale')
    expect(globalCss).not.toContain('--app-display-scale-inverse')
    expect(globalCss).toContain('zoom: var(--app-display-scale')
    expect(globalCss).not.toContain('transform: scale(var(--app-display-scale')
    expect(globalCss).not.toContain("body > [id^='el-popper-container-'] > .el-popper")
    expect(globalCss).not.toMatch(/\.el-popper\s*\{\s*scale:\s*1;/)
    expect(read(join(SRC_DIR, 'utils/elementPlusPopperContainer.ts'))).toContain(
      'appRoot.append(container)',
    )
    expect(globalCss).toContain('max-width: min(360px, calc(100cqw - 24px))')
    expect(read(join(SRC_DIR, 'components/IconPicker.vue'))).toContain(
      'max-width: calc(100cqw - 32px)',
    )
    const packageJson = JSON.parse(read(join(FRONTEND_DIR, 'package.json')))
    expect(packageJson.dependencies['@popperjs/core']).toBe('npm:@sxzz/popperjs-es@2.11.8')
    const popperPatch = read(join(FRONTEND_DIR, 'patches/@popperjs+core+2.11.8.patch'))
    expect(popperPatch).toContain('function Qn(e,t)')
    expect(popperPatch).toContain('o=e.offsetWidth>0&&r.width/e.offsetWidth||1')
    expect(globalCss).toContain('container: app-viewport / size')
    expect(globalCss).toContain('--el-dialog-margin-top: 15cqh')
    expect(globalCss).toContain('max-width: calc(100% - 32px)')
    expect(design).toContain('自动界面比例先按当前屏幕有效逻辑面积连续确定整套 UI 的视觉尺度')
    expect(pageTemplate).toContain('| 全局界面比例 |')
    expect(globalCss).toMatch(/\.page-head\s*\{[\s\S]*?align-items:\s*flex-start/)
    expect(globalCss).toContain('.app-page-title')
    expect(globalCss).toContain('--app-font-size-kpi-xl')
    expect(design).toContain('同一行并列的对象识别块、摘要组、状态块等同层信息块')
    expect(design).toContain('行情摘要统一消费 `StockQuoteSummary`')
    expect(globalCss).toContain('.app-cluster-md')
    expect(design).toContain('### 3.2 行内信息单元规范')
    expect(design).toContain('明显不是同一个连贯内容单位的信息不得直接相邻')
    expect(globalCss).toContain('.app-inline-info')
    expect(globalCss).toContain('.app-inline-info--nowrap')
    expect(globalCss).toContain('--app-muted-text: var(--el-text-color-secondary)')
    expect(globalCss).not.toMatch(/--app-muted-text:\s*#[0-9a-f]{6}/i)
  })

  it('尺寸断点守卫覆盖范围语法，并允许主题与输入能力媒体查询', () => {
    for (const css of [
      '@media (max-width: 720px) {}',
      '@media screen and (min-height: 620px) {}',
      '@media (width <= 720px) {}',
      '@media (620px < height < 900px) {}',
    ]) expect(SIZE_MEDIA_QUERY.test(css), css).toBe(true)
    for (const css of [
      '@media (prefers-reduced-motion: reduce) {}',
      '@media (max-resolution: 1.5dppx) {}',
      '@media (hover: none) {}',
      '@container app-viewport (max-width: 720px) {}',
    ]) expect(SIZE_MEDIA_QUERY.test(css), css).toBe(false)
  })

  it('布局尺寸断点统一使用缩放后的容器，不混用原始视口媒体查询', () => {
    const violations: string[] = []
    for (const file of sourceFiles(SRC_DIR)) {
      for (const css of styleBlocks(file)) {
        if (SIZE_MEDIA_QUERY.test(css)) {
          violations.push(relative(SRC_DIR, file))
        }
      }
    }
    expect(violations).toEqual([])
  })

  it('独立行内信息使用全局信息组，标签不以页面私有固定边距修补', () => {
    const violations: string[] = []

    for (const file of sourceFiles(SRC_DIR)) {
      const rel = relative(SRC_DIR, file)
      const source = read(file)
      const inlineTagMargin = /<el-tag\b[^>]*\bstyle=["'][^"']*margin-(left|right)\s*:[^"']*["'][^>]*>/gs
      for (const match of source.matchAll(inlineTagMargin)) {
        const line = lineOf(source, match.index ?? 0)
        violations.push(`${rel}:${line} el-tag -> inline margin-${match[1]}`)
      }
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

  it('日期控件统一经过 AppDatePicker，默认浮层不得回退到页面上方', () => {
    const directDatePickers = sourceFiles(SRC_DIR)
      .filter((file) => relative(SRC_DIR, file) !== 'components/AppDatePicker.vue')
      .filter((file) => /<(?:el-date-picker|ElDatePicker)\b/.test(read(file)))
      .map((file) => relative(SRC_DIR, file))
    const appDatePicker = read(join(SRC_DIR, 'components/AppDatePicker.vue'))
    const tradeDatePicker = read(join(SRC_DIR, 'components/TradeDatePicker.vue'))
    const floatingPlacement = read(join(SRC_DIR, 'utils/floatingPlacement.ts'))

    expect(directDatePickers).toEqual([])
    expect(floatingPlacement).toContain("APP_BOTTOM_FLOATING_PLACEMENT: Placement = 'bottom-start'")
    expect(floatingPlacement).toContain("['bottom-start', 'bottom-end']")
    expect(appDatePicker).toContain('placement: APP_BOTTOM_FLOATING_PLACEMENT')
    expect(appDatePicker).toContain('fallbackPlacements: () => [...APP_BOTTOM_FLOATING_FALLBACKS]')
    expect(tradeDatePicker).toContain("import AppDatePicker from '@/components/AppDatePicker.vue'")
    expect(tradeDatePicker).toContain('<AppDatePicker')

    const duplicatedFallbacks = sourceFiles(SRC_DIR)
      .filter((file) => file.endsWith('.vue'))
      .filter((file) => /\[['"]bottom-start['"]\s*,\s*['"]bottom-end['"]\]/.test(read(file)))
      .map((file) => relative(SRC_DIR, file))
    expect(duplicatedFallbacks).toEqual([])
  })

  it('全站逐控件检查下拉定位、复合选项浮层边界与语义宽度', () => {
    const violations = sourceFiles(SRC_DIR).filter((file) => file.endsWith('.vue'))
      .flatMap((file) => floatingContractViolations(read(file), relative(SRC_DIR, file)))
    expect(violations).toEqual([])
  })

  it('逐控件禁止原生入口、固定宽度和无边界复合选项，合法共享入口不误报', () => {
    const source = `<template>
      <AppSelect width="short" /><el-icon><Select /></el-icon>
      <AppSelect style="width: 170px" width="170px">
        <el-option><span>名称</span><small>状态</small></el-option>
      </AppSelect>
      <ElSelect :placement="APP_BOTTOM_FLOATING_PLACEMENT" :fallback-placements="APP_BOTTOM_FLOATING_FALLBACKS" />
      <select><option>原生选项</option></select>
    </template>`
    const violations = floatingContractViolations(source, 'example.vue')
    expect(violations).toHaveLength(5)
    expect(violations.filter((item) => item.endsWith(': use AppSelect instead of native select'))).toHaveLength(2)
    expect(violations.some((item) => item.endsWith(': semantic width'))).toBe(true)
    expect(violations.some((item) => item.endsWith(': inline fixed width'))).toBe(true)
    expect(violations.some((item) => item.endsWith(': compound option popper-class'))).toBe(true)
  })

  it('指数单选复用 AppSelect 与语义容量，宽度由业务组件持有', () => {
    const benchmark = read(join(SRC_DIR, 'components/MarketBenchmarkSelect.vue'))
    expect(benchmark).not.toContain('AppFilterSelect')
    expect(benchmark).toContain('<AppSelect')
    expect(benchmark).toContain('width="short"')
    expect(floatingContractViolations('<template><MarketBenchmarkSelect width="120px" /></template>', 'example.vue'))
      .toEqual(['example.vue:1 market-benchmark-select: benchmark width must be owned by shared selector'])
  })

  it('不使用英文装饰性 eyebrow、kicker 或工作区标题', () => {
    const forbidden = [
      'STOCK INTELLIGENCE',
      'SECTOR INTELLIGENCE',
      'LIMIT LADDER',
      'MARKET INTELLIGENCE',
      'PRIVATE ACCESS',
      'SYSTEM ONLINE',
      '>WORKSPACE<',
    ]
    const source = sourceFiles(SRC_DIR)
      .filter((file) => file.endsWith('.vue'))
      .map((file) => read(file))
      .join('\n')

    for (const text of forbidden) expect(source).not.toContain(text)
  })

  it('所属板块卡片的背景与涨跌幅共用金融色，名称保持中性文字', () => {
    const source = read(join(SRC_DIR, 'components/MarketBoardTag.vue'))
    expect(source).toContain('--board-direction: var(--market-up-color)')
    expect(source).toContain('--board-direction: var(--market-down-color)')
    expect(source).toContain('background: color-mix(in srgb, var(--board-direction) 10%, var(--el-bg-color))')
    expect(source).toContain('color: var(--el-text-color-primary)')
    expect(source).toContain('color: var(--board-direction)')
  })

  it('登录页右侧光晕由当前预设强调色推导，避免单套预设漏覆盖', () => {
    const loginView = read(join(SRC_DIR, 'views/LoginView.vue'))

    expect(loginView).not.toContain('--login-auth-glow')
    expect(loginView).toContain('--login-accent: var(--el-color-primary)')
    expect(loginView).toContain('--login-accent-strong: var(--el-color-primary-dark-2, #1264d9)')
    expect(loginView).not.toContain('.login-shell.preset-daylight')
    expect(loginView).not.toContain('.login-shell.preset-nocturne')
    expect(loginView).not.toMatch(/#(?:b69254|876a3a|c5a466|d0ab68|9a7137)\b/i)
    expect(loginView).toContain(
      'grid-template-columns: minmax(0, 1.2fr) minmax(430px, 1fr)',
    )
    expect(loginView).toMatch(
      /radial-gradient\(\s*circle at 85% 0,\s*color-mix\(in srgb,\s*var\(--login-accent\)\s+12%,\s*transparent\),\s*transparent 28%\s*\)/,
    )
  })

  it('间距校验按语义值识别单双轴组合，避免误报零间距或漏报第二轴', () => {
    for (const value of ['0', 'var(--app-space-3)', '0 var(--app-space-3)',
      'var(--app-space-2) 0', 'var(--app-space-2, var(--app-space-3))']) {
      expect(isTokenGap(value), value).toBe(true)
    }
    for (const value of ['1px', '0 13px', 'var(--app-space-2) 13px', 'var(--app-space-2) 0 0']) {
      expect(isTokenGap(value), value).toBe(false)
    }
  })

  it('普通页面样式不新增游离 gap', () => {
    const violations: string[] = []
    for (const file of sourceFiles(SRC_DIR)) {
      for (const css of styleBlocks(file)) {
        for (const match of css.matchAll(/(^|[;{}\n]\s*)gap\s*:\s*([^;\n]+)/g)) {
          const value = match[2].trim()
          if (!isTokenGap(value)) {
            violations.push(`${relative(SRC_DIR, file)}:${lineOf(css, match.index ?? 0)} gap: ${value}`)
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
    const SMALL_FONT = /micro|tiny|ornament/
    // 裸标签（含 span/strong/div/p/b/em/i/a），用于识别「未限定直接子级」的后代选择器
    const LOOSE_TAG = /(?<![\w.-])(span|strong|div|td|p|b|em|i|a)(\s|,|:|\.|\[|$)/

    for (const file of sourceFiles(SRC_DIR)) {
      const rel = relative(SRC_DIR, file)
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

  it('数据采集与任务调度表单的辅助说明统一消费共享组件及 caption 字阶', () => {
    const targets = [
      'components/data/BoardTaskScopeFields.vue',
      'components/data/StockIngestScopeFields.vue',
      'components/data/CurrentDayFallbackField.vue',
      'components/data/ResultMaintenanceTaskFields.vue',
      'views/data/IngestView.vue',
      'views/data/ScheduleView.vue',
    ]

    for (const target of targets) {
      const source = read(join(SRC_DIR, target))
      expect(source, target).toContain('AppFormHelp')
      expect(source, target).not.toContain('class="hint')
      expect(source, target).not.toMatch(/\.hint\s*\{/)
    }
    expect(read(join(SRC_DIR, 'components/AppFormHelp.vue'))).toContain('app-caption-text')

    const globalCss = read(join(SRC_DIR, 'styles/global.css'))
    expect(globalCss).toContain('.app-inline-info--fill { width: 100%; }')
  })

  it('页面标题行间距由布局系统承载，禁止 .page-head 叠加私有 margin/padding-bottom', () => {
    // 事故复盘：QualityView/BoardView 的 .page-head { margin-bottom: 14px } 与 .lh-action 的
    // gap(12px) 叠加成 26px，造成页面间距不一致。间距一律由布局系统承载：
    //   - 操作区内块间距 = .lh-action gap(--app-density-section-gap)
    //   - 页面级间距 = .v-page gap(--app-density-page-gap)，标准档为 12px
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

  it('所有可导航页面标题统一跟随菜单名称，阶段后缀不复制基础标题', () => {
    const pagesWithTitle = sourceFiles(join(SRC_DIR, 'views'))
      .filter((file) => read(file).includes('app-page-title'))

    for (const file of pagesWithTitle) {
      const source = read(file)
      expect(source, relative(SRC_DIR, file)).toContain('useMenuPageTitle')
    }

    const training = read(join(SRC_DIR, 'views/TrainingView.vue'))
    expect(training).toContain("useMenuPageTitle({ suffix: '进行中' })")
    expect(training).toContain("useMenuPageTitle({ suffix: '结算' })")
    expect(training).not.toContain('盘感训练 · 进行中')
    expect(training).not.toContain('训练结算')

    const menuManagement = read(join(SRC_DIR, 'views/system/MenuResourceView.vue'))
    expect(menuManagement).toMatch(/await updateMenu\([\s\S]*await auth\.fetchMe\((?:\{\s*background:\s*true\s*\})?\)/)
  })

  it('新页面脚手架直接消费排版/间距事实源，并显式标记未完成占位', () => {
    const scaffold = read(join(FRONTEND_DIR, 'scripts/scaffold-page.mjs'))

    expect(scaffold).toContain('class="app-page-title"')
    expect(scaffold).toContain("import { useMenuPageTitle } from '@/composables/useMenuPageTitle'")
    expect(scaffold).toContain("const menuPageTitle = useMenuPageTitle({ fallback: '${label}' })")
    expect(scaffold).toContain('{{ menuPageTitle }}')
    expect(scaffold).toContain('gap: var(--app-space-3)')
    expect(scaffold).toContain('AppStateBlock')
    expect(scaffold).toContain('data-scaffold-placeholder')
    expect(scaffold).toContain('responsive-review-pending')
    expect(scaffold).toContain('flex-wrap: wrap')
    expect(scaffold).toContain('componentAllowedLayers,')
    expect(scaffold).toContain('componentLayerValuesOf, componentAllowedLayers }')
    expect(scaffold).not.toMatch(/\.page-toolbar h1\s*\{[\s\S]*?font-size\s*:/)
    expect(scaffold).not.toMatch(/\bgap\s*:\s*\d+px/)
  })
})
