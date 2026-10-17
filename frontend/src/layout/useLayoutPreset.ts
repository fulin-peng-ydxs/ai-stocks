import { computed, ref, watch } from 'vue'
import { DEFAULT_LAYOUT_PRESET, getLayoutPreset, LAYOUT_PRESETS } from './presets'
import {
  blendHex,
  getLoginSurfaceSpec,
  hasDistinctTextHierarchy,
  isHexColor,
  rgbChannelsFromHex,
  rgbaFromHex,
} from './themeSurfaces'
import type { LayoutPreset, StyleTokenConfig } from './schema'
import { useTheme } from '@/composables/useTheme'

const STORAGE_KEY = 'ai-stocks:layout-preset'
const RUNTIME_PRESET_CACHE_KEY = 'ai-stocks:layout-preset-catalog:v1'
const activePresetKey = ref<string>(DEFAULT_LAYOUT_PRESET)
let preferredPresetKey = DEFAULT_LAYOUT_PRESET as string
/**
 * 运行时主题 token 的提交版本。预设 key、明暗模式或后端覆盖任一来源完成 CSS 变量写入后递增，
 * 供 ECharts 等不会自动响应 CSS 变量的画布消费者重新取色。
 */
const themeRevision = ref(0)
const { isDark } = useTheme()

/**
 * 后端预设覆盖（P11：让“视觉预设”页编辑真正驱动运行时外观）。
 * 形如 { [presetKey]: { 'tokens.light.primary': '#...', 'tokens.shared.cardRadius': 8, ... } }，
 * 由 main.ts 挂载后异步拉取注入；缺省（离线/未拉取）则只用前端内置 presets.ts（首屏不闪烁）。
 */
type RuntimePresetValue = string | number | boolean
const presetOverrides = ref<Record<string, Record<string, RuntimePresetValue>>>({})
export interface RuntimePresetDefinition {
  key: string
  name: string
  description: string
}
export interface RuntimePresetSource extends RuntimePresetDefinition {
  config?: {
    values?: Record<string, unknown>
  }
}

const presetCatalog = ref<RuntimePresetDefinition[]>(
  Object.values(LAYOUT_PRESETS).map(({ key, name, description }) => ({ key, name, description })),
)
const PRESET_COLOR_KEYS = new Set<keyof StyleTokenConfig>([
  'primary',
  'success',
  'warning',
  'danger',
  'marketUp',
  'marketDown',
  'border',
  'borderStrong',
])
const PRESET_TEXT_KEYS = new Set<keyof StyleTokenConfig>(['shadow'])
const PRESET_SHAPE_KEYS = new Set<keyof StyleTokenConfig>(['cardRadius', 'controlRadius'])

function setCssVar(tokens: StyleTokenConfig, key: keyof StyleTokenConfig, cssName: string, unit = '') {
  document.documentElement.style.setProperty(cssName, `${tokens[key]}${unit}`)
}

const ELEMENT_COLOR_LIGHT_LEVELS = [3, 5, 7, 8, 9] as const
type ElementSemanticColor = 'primary' | 'success' | 'warning' | 'danger' | 'error'

function applyElementColorScale(
  root: HTMLElement,
  name: ElementSemanticColor,
  color: string,
  mode: 'light' | 'dark',
  surfaceBg: string,
) {
  const safeColor = isHexColor(color) ? color : '#000000'
  const safeSurfaceBg = isHexColor(surfaceBg) ? surfaceBg : safeColor
  root.style.setProperty(`--el-color-${name}`, safeColor)
  root.style.setProperty(`--el-color-${name}-rgb`, rgbChannelsFromHex(safeColor))

  // Element Plus 的 light-* 在暗色模式实际表示向表面色收敛，不能继续沿用组件库默认色阶。
  const quietTarget = mode === 'dark' ? safeSurfaceBg : '#ffffff'
  for (const level of ELEMENT_COLOR_LIGHT_LEVELS) {
    root.style.setProperty(
      `--el-color-${name}-light-${level}`,
      blendHex(safeColor, quietTarget, 1 - level / 10),
    )
  }
  const activeTarget = mode === 'dark' ? '#ffffff' : '#000000'
  root.style.setProperty(`--el-color-${name}-dark-2`, blendHex(safeColor, activeTarget, 0.8))
}

/**
 * 内置 token 叠加后端预设。
 * 基础表面由明暗模式固定；预设只改变语义色、边框、阴影和共享圆角，
 * 不参与页面密度或布局策略。
 */
function mergeTokens(base: StyleTokenConfig, ov: Record<string, RuntimePresetValue>, mode: 'light' | 'dark'): StyleTokenConfig {
  const m = { ...base } as Record<string, string | number>
  const modePrefix = `tokens.${mode}.`
  const sharedPrefix = 'tokens.shared.'
  for (const [path, val] of Object.entries(ov)) {
    if (path.startsWith(modePrefix)) {
      const key = path.slice(modePrefix.length)
      if (!PRESET_COLOR_KEYS.has(key as keyof StyleTokenConfig)
        && !PRESET_TEXT_KEYS.has(key as keyof StyleTokenConfig)) continue
      // 防御历史脏数据：颜色覆盖不合法时保留内置 token，禁止生成 NaN CSS 变量。
      if (typeof val !== 'string' || (PRESET_COLOR_KEYS.has(key as keyof StyleTokenConfig) && !isHexColor(val))) continue
      m[key] = val
    }
    else if (path.startsWith(sharedPrefix) && typeof val === 'number' && Number.isFinite(val)) {
      const key = path.slice(sharedPrefix.length)
      if (PRESET_SHAPE_KEYS.has(key as keyof StyleTokenConfig)) m[key] = val
    }
  }
  if (!hasDistinctTextHierarchy(String(m.text), String(m.textMuted))) {
    m.text = base.text
    m.textMuted = base.textMuted
  }
  return m as unknown as StyleTokenConfig
}

function resolvePresetKey(key: string | null | undefined): string {
  const candidate = key || DEFAULT_LAYOUT_PRESET
  return presetCatalog.value.some((preset) => preset.key === candidate)
    ? candidate
    : DEFAULT_LAYOUT_PRESET
}

function normalizeRuntimePresetSources(definitions: RuntimePresetSource[]) {
  const catalog: RuntimePresetDefinition[] = []
  const overrides: Record<string, Record<string, RuntimePresetValue>> = {}
  const seen = new Set<string>()
  for (const preset of definitions) {
    const key = preset.key?.trim()
    if (!key || seen.has(key)) continue
    seen.add(key)
    catalog.push({
      key,
      name: preset.name || key,
      description: preset.description || '',
    })
    const values = preset.config?.values
    if (!values) continue
    const primitiveValues = Object.fromEntries(
      Object.entries(values).filter(([, value]) =>
        typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean'),
    ) as Record<string, RuntimePresetValue>
    if (Object.keys(primitiveValues).length) overrides[key] = primitiveValues
  }
  return { catalog, overrides }
}

function installRuntimePresetSources(definitions: RuntimePresetSource[], persist: boolean) {
  const { catalog, overrides } = normalizeRuntimePresetSources(definitions)
  const builtIn = LAYOUT_PRESETS[DEFAULT_LAYOUT_PRESET]
  if (!catalog.some((preset) => preset.key === DEFAULT_LAYOUT_PRESET)) {
    catalog.unshift({
      key: builtIn.key,
      name: builtIn.name,
      description: builtIn.description,
    })
  }
  presetCatalog.value = catalog
  presetOverrides.value = overrides
  activePresetKey.value = resolvePresetKey(preferredPresetKey)
  localStorage.setItem(STORAGE_KEY, activePresetKey.value)
  if (persist) {
    localStorage.setItem(RUNTIME_PRESET_CACHE_KEY, JSON.stringify(definitions))
  }
  applyPreset(activePresetKey.value)
}

function restoreRuntimePresetCache() {
  const raw = localStorage.getItem(RUNTIME_PRESET_CACHE_KEY)
  if (!raw) return
  try {
    const parsed = JSON.parse(raw)
    if (Array.isArray(parsed)) installRuntimePresetSources(parsed, false)
  } catch {
    localStorage.removeItem(RUNTIME_PRESET_CACHE_KEY)
  }
}

/** 将后端预设转换为真实可消费的运行时预设；自定义项以默认中性表面为基础。 */
export function getRuntimeLayoutPreset(key: string | null | undefined): LayoutPreset {
  const resolvedKey = resolvePresetKey(key)
  const base = getLayoutPreset(resolvedKey)
  const meta = presetCatalog.value.find((preset) => preset.key === resolvedKey)
  const overrides = presetOverrides.value[resolvedKey] ?? {}
  return {
    ...base,
    key: resolvedKey,
    name: meta?.name ?? base.name,
    description: meta?.description ?? base.description,
    tokens: {
      light: mergeTokens(base.tokens.light, overrides, 'light'),
      dark: mergeTokens(base.tokens.dark, overrides, 'dark'),
    },
  }
}

function applyPreset(key: string) {
  const preset = getRuntimeLayoutPreset(key)
  const root = document.documentElement
  // 按当前白天/夜间模式取对应 token 集（M9：预设 × 明暗二维）
  const mode = isDark.value ? 'dark' : 'light'
  // 内置 token 叠加后端预设覆盖（P11 运行时打通）
  const t = preset.tokens[mode]
  root.dataset.layoutPreset = preset.key
  root.dataset.layoutMode = mode
  const chromeBg = t.submenuBg
  const surfaces = getLoginSurfaceSpec(mode)

  applyElementColorScale(root, 'primary', t.primary, mode, t.surfaceBg)
  applyElementColorScale(root, 'success', t.success, mode, t.surfaceBg)
  applyElementColorScale(root, 'warning', t.warning, mode, t.surfaceBg)
  applyElementColorScale(root, 'danger', t.danger, mode, t.surfaceBg)
  applyElementColorScale(root, 'error', t.danger, mode, t.surfaceBg)
  root.style.setProperty('--el-bg-color-page', t.pageBg)
  root.style.setProperty('--el-bg-color', t.surfaceBg)
  root.style.setProperty('--el-bg-color-overlay', t.surfaceBg)
  root.style.setProperty('--el-fill-color-blank', t.surfaceBg)
  root.style.setProperty('--app-section-bg', surfaces.sectionBg)
  root.style.setProperty('--el-fill-color-light', t.surfaceHover)
  root.style.setProperty('--el-fill-color-lighter', rgbaFromHex(t.border, mode === 'dark' ? 0.46 : 0.34))
  root.style.setProperty('--el-fill-color-extra-light', rgbaFromHex(t.surfaceHover, mode === 'dark' ? 0.72 : 0.58))
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
  root.style.setProperty('--app-muted-text', t.textMuted)

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
  root.style.setProperty('--chrome-menu-icon-active-bg', rgbaFromHex(t.primary, mode === 'dark' ? 0.22 : 0.14))
  root.style.setProperty('--chrome-menu-icon-active-border', rgbaFromHex(t.primary, mode === 'dark' ? 0.42 : 0.26))
  root.style.setProperty('--chrome-menu-icon-active-color', t.primary)
  root.style.setProperty('--shell-accent', t.primary)
  root.style.setProperty('--shell-accent-strong', t.danger)
  root.style.setProperty('--shell-accent-soft', rgbaFromHex(t.primary, mode === 'dark' ? 0.22 : 0.12))
  root.style.setProperty('--shell-accent-faint', rgbaFromHex(t.primary, mode === 'dark' ? 0.14 : 0.07))
  root.style.setProperty('--shell-accent-line', rgbaFromHex(t.primary, mode === 'dark' ? 0.42 : 0.22))
  root.style.setProperty('--shell-danger-line', rgbaFromHex(t.danger, mode === 'dark' ? 0.18 : 0.10))
  root.style.setProperty('--shell-canvas-glow', rgbaFromHex(t.primary, mode === 'dark' ? 0.12 : 0.08))
  root.style.setProperty('--shell-surface-shadow', t.shadow)
  root.style.setProperty('--shell-control-mark', mode === 'dark' ? '#f7fbfc' : '#ffffff')
  // 品牌字标只消费运行时主色：登录页与工作台不得再各自组合第二套 Logo 色板。
  root.style.setProperty('--brand-icon-start', blendHex(t.primary, '#ffffff', 0.62))
  root.style.setProperty('--brand-icon-end', blendHex(t.primary, mode === 'dark' ? '#ffffff' : '#000000', 0.8))
  root.style.setProperty('--brand-signal', rgbaFromHex(t.danger, mode === 'dark' ? 0.58 : 0.42))
  root.style.setProperty('--brand-word', t.textStrong)
  root.style.setProperty('--brand-word-stroke', rgbaFromHex(mode === 'dark' ? t.pageBg : t.surfaceBg, mode === 'dark' ? 0.58 : 0.68))
  root.style.setProperty('--drawer-bg', t.surfaceBg)
  root.style.setProperty('--drawer-card-bg', t.surfaceBg)
  root.style.setProperty('--drawer-border', t.border)
  root.style.setProperty('--drawer-text', t.text)
  root.style.setProperty('--drawer-text-muted', t.textMuted)
  root.style.setProperty('--page-settings-bg', t.surfaceBg)
  root.style.setProperty('--page-settings-border', t.border)
  root.style.setProperty('--page-settings-shadow', t.shadow)
  root.style.setProperty('--page-settings-section-bg', surfaces.sectionBg)
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
  root.style.setProperty('--page-settings-seg-bg', t.surfaceHover)
  root.style.setProperty('--page-settings-seg-hover-bg', t.activeBg)
  root.style.setProperty(
    '--page-settings-seg-active-bg',
    mode === 'dark' ? blendHex(t.activeBg, t.textStrong, 0.88) : t.surfaceBg,
  )
  root.style.setProperty('--page-settings-seg-active-border', t.borderStrong)
  root.style.setProperty('--page-settings-switch-off', t.borderStrong)
  root.style.setProperty('--page-settings-tip-border', t.borderStrong)
  root.style.setProperty('--page-settings-footer-btn-bg', t.surfaceHover)
  root.style.setProperty('--page-settings-footer-btn-hover-bg', t.activeBg)

  // 金融涨跌色（涨红/跌绿）：感知亮度恒高于同名主体信号色一档，由预设统一提供并随明暗/预设联动。
  const marketUp = isHexColor(t.marketUp) ? t.marketUp : t.danger
  const marketDown = isHexColor(t.marketDown) ? t.marketDown : t.success
  root.style.setProperty('--market-up-color', marketUp)
  root.style.setProperty('--market-down-color', marketDown)

  // 状态文本/评分档色统一消费预设语义主色（统一：同一语义同一值，不再 dark-2 压暗或 blend 提彩的第二套派生）。
  // 防御非法后端覆盖：非 #RRGGBB 时回落到预设主色，避免 blendHex 静默落黑。
  const ok = (c: string, fb: string) => (isHexColor(c) ? c : fb)
  const warn = ok(t.warning, '#f58a07')
  const dgr = ok(t.danger, '#f04438')
  const okc = ok(t.success, '#0ea968')
  root.style.setProperty('--app-warning-text', warn)
  root.style.setProperty('--app-danger-text', dgr)
  root.style.setProperty('--score-high-text', okc)
  root.style.setProperty('--score-high-bg', rgbaFromHex(okc, mode === 'dark' ? 0.18 : 0.14))
  root.style.setProperty('--score-mid-text', warn)
  root.style.setProperty('--score-mid-bg', rgbaFromHex(warn, mode === 'dark' ? 0.2 : 0.16))

  setCssVar(t, 'cardRadius', '--layout-card-radius', 'px')
  setCssVar(t, 'controlRadius', '--layout-control-radius', 'px')
  // 必须在全部 CSS 变量写入后发布，避免画布消费者读到新版本号与旧 token 的中间态。
  themeRevision.value += 1
}

export function initLayoutPreset() {
  const saved = localStorage.getItem(STORAGE_KEY)
  preferredPresetKey = saved || DEFAULT_LAYOUT_PRESET
  // 登录前无法使用受保护的布局接口，先恢复最近一次公开外观目录，保证自定义预设首屏可用。
  restoreRuntimePresetCache()
  activePresetKey.value = resolvePresetKey(preferredPresetKey)
  applyPreset(activePresetKey.value)
  // 白天/夜间切换（useTheme.toggleTheme 改 isDark）时，按当前预设重刷对应模式 token
  watch(isDark, () => applyPreset(activePresetKey.value))
}

/**
 * 同一入口接收登录页公开外观配置和登录后完整预设列表。
 * 登录页与系统页由此共享同一目录、同一强调色覆盖与同一首屏缓存。
 */
export function setRuntimePresetSources(definitions: RuntimePresetSource[]) {
  installRuntimePresetSources(definitions, true)
}

export function setLayoutPreset(key: string) {
  preferredPresetKey = key
  activePresetKey.value = resolvePresetKey(key)
  localStorage.setItem(STORAGE_KEY, activePresetKey.value)
  applyPreset(activePresetKey.value)
}

/** 注入后端启用预设目录；当前只有一套也保留选择入口，新增项无需再改外观抽屉。 */
export function setPresetCatalog(definitions: RuntimePresetDefinition[]) {
  const byKey = new Map<string, RuntimePresetDefinition>()
  for (const preset of definitions) {
    if (preset.key) byKey.set(preset.key, preset)
  }
  const builtIn = LAYOUT_PRESETS[DEFAULT_LAYOUT_PRESET]
  if (!byKey.has(DEFAULT_LAYOUT_PRESET)) {
    byKey.set(DEFAULT_LAYOUT_PRESET, {
      key: builtIn.key,
      name: builtIn.name,
      description: builtIn.description,
    })
  }
  presetCatalog.value = [...byKey.values()]
  activePresetKey.value = resolvePresetKey(preferredPresetKey)
  localStorage.setItem(STORAGE_KEY, activePresetKey.value)
  applyPreset(activePresetKey.value)
}

/** 注入后端预设覆盖并立即重刷当前预设外观（P11：预设编辑驱动运行时）。 */
export function setPresetOverrides(map: Record<string, Record<string, RuntimePresetValue>>) {
  presetOverrides.value = map
  applyPreset(activePresetKey.value)
}

/** 取某预设某模式下「内置 + 后端覆盖」的有效 token（供视觉预设页回显当前生效值）。 */
export function effectivePresetTokens(key: string, mode: 'light' | 'dark'): StyleTokenConfig {
  return getRuntimeLayoutPreset(key).tokens[mode]
}

export function useLayoutPreset() {
  const activePreset = computed(() => getRuntimeLayoutPreset(activePresetKey.value))
  const options = computed(() => presetCatalog.value.map((preset) => ({
    label: preset.name,
    value: preset.key,
    description: preset.description,
  })))
  return { activePresetKey, activePreset, themeRevision, options, setLayoutPreset }
}
