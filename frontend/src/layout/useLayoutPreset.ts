import { computed, ref, watch } from 'vue'
import { DEFAULT_LAYOUT_PRESET, getLayoutPreset, LAYOUT_PRESETS } from './presets'
import type { LayoutPresetKey, StyleTokenConfig } from './schema'
import { useTheme } from '@/composables/useTheme'

const STORAGE_KEY = 'ai-stocks:layout-preset'
const activePresetKey = ref<LayoutPresetKey>(DEFAULT_LAYOUT_PRESET)
const { isDark } = useTheme()

/**
 * 后端预设覆盖（P11：让"预设管理页编辑"真正驱动运行时外观）。
 * 形如 { [presetKey]: { 'tokens.light.primary': '#...', 'tokens.shared.cardRadius': 8, ... } }，
 * 由 main.ts 挂载后异步拉取注入；缺省（离线/未拉取）则只用前端内置 presets.ts（首屏不闪烁）。
 */
const presetOverrides = ref<Record<string, Record<string, string | number>>>({})

function setCssVar(tokens: StyleTokenConfig, key: keyof StyleTokenConfig, cssName: string, unit = '') {
  document.documentElement.style.setProperty(cssName, `${tokens[key]}${unit}`)
}

function hexToRgba(hex: string, alpha: number): string {
  const m = /^#([0-9a-f]{6})$/i.exec(hex.trim())
  if (!m) return hex
  const n = parseInt(m[1], 16)
  const r = (n >> 16) & 255
  const g = (n >> 8) & 255
  const b = n & 255
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

/** 内置 token（按模式）叠加后端覆盖：颜色/阴影取 `tokens.<mode>.*`，形态/密度取 `tokens.shared.*`。 */
function mergeTokens(base: StyleTokenConfig, ov: Record<string, string | number>, mode: 'light' | 'dark'): StyleTokenConfig {
  const m = { ...base } as Record<string, string | number>
  const modePrefix = `tokens.${mode}.`
  const sharedPrefix = 'tokens.shared.'
  for (const [path, val] of Object.entries(ov)) {
    if (path.startsWith(modePrefix)) m[path.slice(modePrefix.length)] = val
    else if (path.startsWith(sharedPrefix)) m[path.slice(sharedPrefix.length)] = val
  }
  return m as unknown as StyleTokenConfig
}

function applyPreset(key: LayoutPresetKey) {
  const preset = getLayoutPreset(key)
  const root = document.documentElement
  // 按当前白天/夜间模式取对应 token 集（M9：预设 × 明暗二维）
  const mode = isDark.value ? 'dark' : 'light'
  // 内置 token 叠加后端预设覆盖（P11 运行时打通）
  const t = mergeTokens(preset.tokens[mode], presetOverrides.value[preset.key] ?? {}, mode)
  root.dataset.layoutPreset = preset.key
  root.dataset.layoutMode = mode
  const chromeBg = mode === 'dark' ? t.submenuBg : t.surfaceBg

  root.style.setProperty('--el-color-primary', t.primary)
  root.style.setProperty('--el-color-success', t.success)
  root.style.setProperty('--el-color-warning', t.warning)
  root.style.setProperty('--el-color-danger', t.danger)
  root.style.setProperty('--el-bg-color-page', t.pageBg)
  root.style.setProperty('--el-bg-color', t.surfaceBg)
  root.style.setProperty('--el-bg-color-overlay', t.surfaceBg)
  root.style.setProperty('--el-fill-color-blank', t.surfaceBg)
  root.style.setProperty('--el-fill-color-light', t.surfaceHover)
  root.style.setProperty('--el-fill-color-lighter', hexToRgba(t.border, mode === 'dark' ? 0.46 : 0.34))
  root.style.setProperty('--el-fill-color-extra-light', hexToRgba(t.surfaceHover, mode === 'dark' ? 0.72 : 0.58))
  root.style.setProperty('--el-disabled-bg-color', t.surfaceHover)
  root.style.setProperty('--el-border-color', t.border)
  root.style.setProperty('--el-border-color-light', t.border)
  root.style.setProperty('--el-border-color-lighter', t.border)
  root.style.setProperty('--el-border-color-dark', t.borderStrong)
  root.style.setProperty('--el-border-color-darker', t.borderStrong)
  root.style.setProperty('--el-text-color-primary', t.textStrong)
  root.style.setProperty('--el-text-color-regular', t.text)
  root.style.setProperty('--el-text-color-secondary', t.textMuted)
  root.style.setProperty('--el-text-color-placeholder', t.textMuted)
  root.style.setProperty('--el-text-color-disabled', t.textMuted)

  root.style.setProperty('--chrome-bg', chromeBg)
  root.style.setProperty('--chrome-bg-soft', t.surfaceBg)
  root.style.setProperty('--chrome-bg-soft-hover', t.surfaceHover)
  root.style.setProperty('--chrome-border', t.border)
  root.style.setProperty('--chrome-border-strong', t.borderStrong)
  root.style.setProperty('--chrome-border-hover', t.primary)
  root.style.setProperty('--chrome-text', t.text)
  root.style.setProperty('--chrome-text-strong', t.textStrong)
  root.style.setProperty('--chrome-text-muted', t.textMuted)
  root.style.setProperty('--chrome-submenu-bg', t.submenuBg)
  root.style.setProperty('--chrome-active-bg', t.activeBg)
  root.style.setProperty('--chrome-menu-icon-active-bg', hexToRgba(t.primary, mode === 'dark' ? 0.22 : 0.14))
  root.style.setProperty('--chrome-menu-icon-active-border', hexToRgba(t.primary, mode === 'dark' ? 0.42 : 0.26))
  root.style.setProperty('--chrome-menu-icon-active-color', t.primary)
  root.style.setProperty('--shell-accent', t.primary)
  root.style.setProperty('--shell-accent-strong', t.danger)
  root.style.setProperty('--shell-accent-soft', hexToRgba(t.primary, mode === 'dark' ? 0.22 : 0.12))
  root.style.setProperty('--shell-accent-faint', hexToRgba(t.primary, mode === 'dark' ? 0.14 : 0.07))
  root.style.setProperty('--shell-accent-line', hexToRgba(t.primary, mode === 'dark' ? 0.42 : 0.22))
  root.style.setProperty('--shell-danger-line', hexToRgba(t.danger, mode === 'dark' ? 0.18 : 0.10))
  root.style.setProperty('--shell-canvas-glow', hexToRgba(t.primary, mode === 'dark' ? 0.12 : 0.08))
  root.style.setProperty('--shell-surface-shadow', t.shadow)
  root.style.setProperty('--shell-control-mark', mode === 'dark' ? '#f7fbfc' : '#ffffff')
  root.style.setProperty('--brand-icon-start', t.primary)
  root.style.setProperty('--brand-icon-end', t.danger)
  root.style.setProperty('--brand-signal', hexToRgba(t.danger, mode === 'dark' ? 0.58 : 0.42))
  root.style.setProperty('--brand-word', t.textStrong)
  root.style.setProperty('--brand-word-stroke', hexToRgba(mode === 'dark' ? t.pageBg : t.surfaceBg, mode === 'dark' ? 0.58 : 0.68))
  root.style.setProperty('--drawer-bg', t.pageBg)
  root.style.setProperty('--drawer-card-bg', t.surfaceBg)
  root.style.setProperty('--drawer-border', t.border)
  root.style.setProperty('--drawer-text', t.text)
  root.style.setProperty('--drawer-text-muted', t.textMuted)
  root.style.setProperty('--page-settings-bg', t.surfaceBg)
  root.style.setProperty('--page-settings-border', t.border)
  root.style.setProperty('--page-settings-shadow', t.shadow)
  root.style.setProperty('--page-settings-section-bg', t.surfaceHover)
  root.style.setProperty('--page-settings-section-border', t.border)
  root.style.setProperty('--page-settings-divider', t.border)
  root.style.setProperty('--page-settings-text', t.textStrong)
  root.style.setProperty('--page-settings-text-subtle', t.text)
  root.style.setProperty('--page-settings-text-muted', t.textMuted)
  root.style.setProperty('--page-settings-accent', t.primary)
  root.style.setProperty('--page-settings-dot-ring', t.surfaceBg)
  root.style.setProperty('--page-settings-trigger-text', t.textMuted)
  root.style.setProperty('--page-settings-trigger-hover-text', t.textStrong)
  root.style.setProperty('--page-settings-trigger-hover-bg', t.surfaceHover)
  root.style.setProperty('--page-settings-seg-bg', t.pageBg)
  root.style.setProperty('--page-settings-seg-hover-bg', t.surfaceHover)
  root.style.setProperty('--page-settings-seg-active-bg', t.activeBg)
  root.style.setProperty('--page-settings-seg-active-border', t.borderStrong)
  root.style.setProperty('--page-settings-switch-off', t.borderStrong)
  root.style.setProperty('--page-settings-tip-border', t.borderStrong)
  root.style.setProperty('--page-settings-footer-btn-bg', t.surfaceHover)
  root.style.setProperty('--page-settings-footer-btn-hover-bg', t.activeBg)

  setCssVar(t, 'cardRadius', '--layout-card-radius', 'px')
  setCssVar(t, 'controlRadius', '--layout-control-radius', 'px')
  setCssVar(t, 'pageGap', '--layout-page-gap', 'px')
  setCssVar(t, 'cardPadding', '--layout-card-padding', 'px')
  setCssVar(t, 'tableCellPaddingY', '--layout-table-cell-padding-y', 'px')
}

export function initLayoutPreset() {
  const saved = localStorage.getItem(STORAGE_KEY) as LayoutPresetKey | null
  activePresetKey.value = getLayoutPreset(saved).key
  applyPreset(activePresetKey.value)
  // 白天/夜间切换（useTheme.toggleTheme 改 isDark）时，按当前预设重刷对应模式 token
  watch(isDark, () => applyPreset(activePresetKey.value))
}

export function setLayoutPreset(key: LayoutPresetKey) {
  activePresetKey.value = getLayoutPreset(key).key
  localStorage.setItem(STORAGE_KEY, activePresetKey.value)
  applyPreset(activePresetKey.value)
}

/** 注入后端预设覆盖并立即重刷当前预设外观（P11：预设编辑驱动运行时）。 */
export function setPresetOverrides(map: Record<string, Record<string, string | number>>) {
  presetOverrides.value = map
  applyPreset(activePresetKey.value)
}

/** 取某预设某模式下「内置 + 后端覆盖」的有效 token（供预设管理页回显当前生效值）。 */
export function effectivePresetTokens(key: string, mode: 'light' | 'dark'): StyleTokenConfig {
  const preset = getLayoutPreset(key)
  return mergeTokens(preset.tokens[mode], presetOverrides.value[preset.key] ?? {}, mode)
}

const CFD_RE = /^componentFieldDefaults\.([^.]+)\.([^.]+)$/

/**
 * 取某预设的「预设×组件默认」：{ 组件种类 -> { 字段 -> 值 } }（来自后端覆盖 componentFieldDefaults.*）。
 * 供 useLayoutConfig 把预设组件默认展开成各 slot 的 preset 层组件配置覆盖（P11）。
 */
export function presetComponentDefaults(key: string): Record<string, Record<string, string | number | boolean>> {
  const ov = presetOverrides.value[getLayoutPreset(key).key] ?? {}
  const out: Record<string, Record<string, string | number | boolean>> = {}
  for (const [path, val] of Object.entries(ov)) {
    const m = CFD_RE.exec(path)
    if (m) (out[m[1]] ??= {})[m[2]] = val
  }
  return out
}

export function useLayoutPreset() {
  const activePreset = computed(() => getLayoutPreset(activePresetKey.value))
  const options = computed(() => Object.values(LAYOUT_PRESETS).map((p) => ({
    label: p.name,
    value: p.key,
    description: p.description,
  })))
  return { activePresetKey, activePreset, options, setLayoutPreset }
}
