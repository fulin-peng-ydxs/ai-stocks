import { computed, ref } from 'vue'
import { createGlobalPreferenceSync } from './useGlobalPreferenceSync'

export type DisplayScaleMode = 'auto' | 'custom'

interface DisplayScalePreference {
  mode: DisplayScaleMode
  customPercent: number
}

export const DISPLAY_SCALE_MIN = 50
export const DISPLAY_SCALE_MAX = 150
export const DISPLAY_SCALE_DEFAULT = 100

const AUTO_SCALE_MIN = 82
const AUTO_SCALE_REFERENCE_AREA = 1920 * 1080
const AUTO_SCALE_DENSITY_EXPONENT = 0.15

export interface DisplayScaleArea {
  width: number
  height: number
}

const STORAGE_KEY = 'ai-stocks-display-scale'
const mode = ref<DisplayScaleMode>('auto')
const customPercent = ref(DISPLAY_SCALE_DEFAULT)
const autoPercent = ref(DISPLAY_SCALE_DEFAULT)
const effectivePercent = computed(() => (
  mode.value === 'auto' ? autoPercent.value : customPercent.value
))

let initialized = false
let resizeTimer: number | undefined

function clampPercent(value: unknown, fallback = DISPLAY_SCALE_DEFAULT): number {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return fallback
  return Math.min(DISPLAY_SCALE_MAX, Math.max(DISPLAY_SCALE_MIN, Math.round(numeric)))
}

function readAvailableScreenArea(): DisplayScaleArea {
  const screenWidth = Number(window.screen?.availWidth)
  const screenHeight = Number(window.screen?.availHeight)
  return {
    width: screenWidth > 0 ? screenWidth : window.innerWidth,
    height: screenHeight > 0 ? screenHeight : window.innerHeight,
  }
}

/**
 * 以操作系统已经折算后的屏幕可用 CSS 面积估算信息容量：常规桌面保持 100%，
 * 更大的工作屏连续提高信息密度，但采用低指数曲线并设置阅读下限，避免高分屏骤缩。
 * DPR、物理像素和浏览器页级缩放不参与目标比例计算。
 */
export function calculateAutoDisplayScalePercent(
  area: DisplayScaleArea = readAvailableScreenArea(),
): number {
  const width = Number(area.width)
  const height = Number(area.height)
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) {
    return DISPLAY_SCALE_DEFAULT
  }

  const availableArea = width * height
  if (availableArea <= AUTO_SCALE_REFERENCE_AREA) return DISPLAY_SCALE_DEFAULT

  const scale = Math.pow(AUTO_SCALE_REFERENCE_AREA / availableArea, AUTO_SCALE_DENSITY_EXPONENT)
  return Math.max(AUTO_SCALE_MIN, Math.min(DISPLAY_SCALE_DEFAULT, Math.round(scale * 100)))
}

function normalizePreference(value: unknown): DisplayScalePreference | undefined {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return undefined
  const raw = value as Record<string, unknown>
  if (raw.mode !== 'auto' && raw.mode !== 'custom') return undefined
  return {
    mode: raw.mode,
    customPercent: clampPercent(raw.customPercent),
  }
}

function readLocal(): DisplayScalePreference | undefined {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return normalizePreference(raw ? JSON.parse(raw) : undefined)
  } catch {
    return undefined
  }
}

function persistLocal(): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      mode: mode.value,
      customPercent: customPercent.value,
    } satisfies DisplayScalePreference))
  } catch {
    // 隐私模式或禁用站点存储时，显示比例仍应在当前会话生效。
  }
}

function applyScale(): void {
  const percent = effectivePercent.value
  const scale = percent / 100
  const root = document.documentElement
  const resolution = (window.devicePixelRatio || 1) * scale <= 1.5 ? 'low' : 'high'
  const changed = root.style.getPropertyValue('--app-display-scale') !== String(scale)
    || root.dataset.displayScaleMode !== mode.value
    || root.dataset.displayResolution !== resolution
  root.style.setProperty('--app-display-scale', String(scale))
  root.style.setProperty('--app-display-scale-inverse', String(1 / scale))
  root.dataset.displayScaleMode = mode.value
  root.dataset.displayScalePercent = String(percent)
  root.dataset.displayResolution = resolution

  // Canvas 与依赖窗口尺寸的第三方组件需要在缩放后的布局稳定后重新测量。
  if (changed) window.requestAnimationFrame?.(() => window.dispatchEvent(new Event('resize')))
}

function refreshAutoPercent(): void {
  autoPercent.value = calculateAutoDisplayScalePercent()
  // 自定义模式跨显示器时，清晰度分级也需要重新计算。
  applyScale()
}

const preferenceSync = createGlobalPreferenceSync<DisplayScalePreference>({
  prefKey: 'display-scale',
  debounceMs: 250,
  snapshot: () => ({ mode: mode.value, customPercent: customPercent.value }),
  normalize: normalizePreference,
  applyRemote(value) {
    mode.value = value.mode
    customPercent.value = value.customPercent
    refreshAutoPercent()
  },
  persistLocal,
})

function schedulePersist(): void {
  preferenceSync.scheduleSave()
}

function onViewportChange(): void {
  if (resizeTimer) window.clearTimeout(resizeTimer)
  resizeTimer = window.setTimeout(() => {
    resizeTimer = undefined
    refreshAutoPercent()
  }, 120)
}

function onVisibilityChange(): void {
  if (!document.hidden) onViewportChange()
}

export function initDisplayScale(): void {
  const saved = readLocal()
  mode.value = saved?.mode ?? 'auto'
  customPercent.value = saved?.customPercent ?? DISPLAY_SCALE_DEFAULT
  refreshAutoPercent()
  if (!initialized) {
    window.addEventListener('resize', onViewportChange)
    window.addEventListener('focus', onViewportChange)
    window.addEventListener('pageshow', onViewportChange)
    document.addEventListener('visibilitychange', onVisibilityChange)
    initialized = true
  }
}

export function setDisplayScaleMode(value: DisplayScaleMode): void {
  if (value !== 'auto' && value !== 'custom') return
  if (value === 'custom' && mode.value === 'auto') {
    customPercent.value = autoPercent.value
  }
  mode.value = value
  refreshAutoPercent()
  schedulePersist()
}

export function setCustomDisplayScalePercent(value: unknown): void {
  customPercent.value = clampPercent(value, customPercent.value)
  mode.value = 'custom'
  applyScale()
  schedulePersist()
}

export function resetDisplayScale(): void {
  setCustomDisplayScalePercent(DISPLAY_SCALE_DEFAULT)
}

export async function syncDisplayScalePreference(): Promise<void> {
  await preferenceSync.syncOnce()
}

export function resetDisplayScaleForTests(): void {
  if (resizeTimer) window.clearTimeout(resizeTimer)
  resizeTimer = undefined
  if (initialized) {
    window.removeEventListener('resize', onViewportChange)
    window.removeEventListener('focus', onViewportChange)
    window.removeEventListener('pageshow', onViewportChange)
    document.removeEventListener('visibilitychange', onVisibilityChange)
  }
  initialized = false
  preferenceSync.resetForTests()
  mode.value = 'auto'
  customPercent.value = DISPLAY_SCALE_DEFAULT
  autoPercent.value = DISPLAY_SCALE_DEFAULT
  document.documentElement.style.removeProperty('--app-display-scale')
  document.documentElement.style.removeProperty('--app-display-scale-inverse')
  delete document.documentElement.dataset.displayScaleMode
  delete document.documentElement.dataset.displayScalePercent
  delete document.documentElement.dataset.displayResolution
}

export function useDisplayScale() {
  return {
    mode,
    customPercent,
    autoPercent,
    effectivePercent,
    setMode: setDisplayScaleMode,
    setCustomPercent: setCustomDisplayScalePercent,
    reset: resetDisplayScale,
    syncPreference: syncDisplayScalePreference,
  }
}
