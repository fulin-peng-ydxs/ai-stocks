// 全局主题（白天/夜间）：模块级单例状态，首屏读 localStorage，登录后同步 PG 用户偏好。
import { ref } from 'vue'
import { createGlobalPreferenceSync } from './useGlobalPreferenceSync'

const STORAGE_KEY = 'ai-stocks-theme'
const isDark = ref(false)
type ThemePreference = { mode: 'dark' | 'light' }

function apply(v: boolean) {
  document.documentElement.classList.toggle('dark', v)
}

function persistLocal() {
  localStorage.setItem(STORAGE_KEY, isDark.value ? 'dark' : 'light')
}

const themePreferenceSync = createGlobalPreferenceSync<ThemePreference>({
  prefKey: 'theme',
  snapshot: () => ({ mode: isDark.value ? 'dark' : 'light' }),
  normalize(value) {
    const mode = (value as { mode?: unknown } | undefined)?.mode
    return mode === 'dark' || mode === 'light' ? { mode } : undefined
  },
  applyRemote(value) {
    isDark.value = value.mode === 'dark'
    persistLocal()
    apply(isDark.value)
  },
})

export function initTheme() {
  const saved = localStorage.getItem(STORAGE_KEY)
  if (saved) {
    isDark.value = saved === 'dark'
  } else {
    isDark.value = window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false
  }
  apply(isDark.value)
}

export function toggleTheme() {
  isDark.value = !isDark.value
  persistLocal()
  apply(isDark.value)
  void themePreferenceSync.saveNow()
}

export async function syncThemePreference() {
  await themePreferenceSync.syncOnce()
}

export function useTheme() {
  return { isDark, toggleTheme, syncThemePreference }
}
