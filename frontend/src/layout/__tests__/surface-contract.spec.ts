import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { auditSurfaces, auditSurfaceTree } from '../../../scripts/check-surfaces.mjs'
import { LAYOUT_PRESETS } from '../presets'
import { themeSurfaceVariables, THEME_SURFACE_SPECS } from '../themeSurfaces'
import type { ThemeMode } from '../schema'

const audit = (source: string, file = 'views/Fixture.vue') => auditSurfaces([{ file, source }]).violations

describe('统一表面与边界契约', () => {
  it('扫描全站生产源码的 CSS、Vue 模板和脚本样式对象', () => {
    const result = auditSurfaceTree()
    expect(result.files).toBeGreaterThan(300)
    expect(result.violations).toEqual([])
  })

  it.each([
    '<template><div style="background:#191919" /></template>',
    '<template><div :style="{borderColor: `#fff`}" /></template>',
    '<template><div style="background:white" /></template>',
    '<script setup>const style = {["backgroundColor"]: "#fff"}</script>',
    '<script setup>el.style.backgroundColor = "#fff"</script>',
    '<script setup>el.style.setProperty("background", "#fff")</script>',
    '<script setup>const style = {backgroundColor: "rgb(0,0,0)"}</script>',
    '<template><div /></template><style>.card {background:color-mix(in srgb,var(--el-bg-color) 50%,white)}</style>',
    '<template><div /></template><style>.card {border:1px solid var(--el-border-color,#ddd)}</style>',
    '<template><div /></template><style>.card {--app-surface-container:var(--local-bg)}</style>',
  ])('拒绝局部色值、混色和私自定义共享角色: %s', source => {
    expect(audit(source).length).toBeGreaterThan(0)
  })

  it('允许透明面、标准角色和业务文字，不把普通字段当成 CSS', () => {
    expect(audit('<template><div style="background:transparent;border:1px solid var(--app-border-default)" /></template><script setup>const name = "#fff"</script>')).toEqual([])
  })

  it('拼错的共享角色不能静默回退', () => {
    expect(audit('<template><div style="background:var(--app-surface-missing)" /></template>').join()).toContain('未定义')
  })

  it('品牌装饰只允许登记的具体选择器、属性及原值', () => {
    const source = '<template><div /></template><style>.market-orbit {border:1px solid color-mix(in srgb, var(--login-accent) 10%, transparent)}</style>'
    expect(audit(source, 'views/LoginView.vue')).toEqual([])
    expect(audit(source.replace('10%', '50%'), 'views/LoginView.vue')).toHaveLength(1)
    expect(audit(source.replace('.market-orbit', '.login-field'), 'views/LoginView.vue')).toHaveLength(1)
  })

  it('明暗所有预设都从同一入口映射内容、控件、浮层及组件库边界', () => {
    for (const preset of Object.values(LAYOUT_PRESETS)) {
      for (const mode of ['light', 'dark'] as ThemeMode[]) {
        const tokens = preset.tokens[mode]
        const roles = themeSurfaceVariables(tokens, mode)
        expect(roles['--app-surface-canvas']).toBe(THEME_SURFACE_SPECS[mode].pageBg)
        for (const key of ['--app-surface-container', '--app-surface-control', '--app-surface-overlay', '--el-disabled-bg-color']) {
          expect(roles[key]).toBe(THEME_SURFACE_SPECS[mode].surfaceBg)
        }
        for (const key of ['--app-border-default', '--el-border-color', '--el-border-color-light', '--el-border-color-lighter', '--el-border-color-extra-light']) {
          expect(roles[key]).toBe(tokens.border)
        }
      }
    }
  })

  it('规则摘要及配置容器保留内容面，内部编辑区不得因嵌套自动刷灰', () => {
    const read = (file: string) => readFileSync(resolve(__dirname, '../../', file), 'utf8')
    const summary = read('components/AppSummaryDisclosureCard.vue')
    const config = read('components/config/ConfigPanelSection.vue')
    expect(summary).not.toContain('--app-surface-section')
    expect(config).not.toContain('--app-surface-section')
    expect(summary).toMatch(/\.app-summary-disclosure-card\s*\{[^}]*background: var\(--app-surface-container\)/)
    expect(summary).toMatch(/\.app-summary-disclosure-card__editor\s*\{[^}]*background: var\(--app-surface-container\)/)
  })
})
