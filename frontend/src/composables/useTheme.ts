// 全局主题（白天/夜间）：模块级单例状态，首屏读 localStorage，登录后同步 PG 用户偏好。
import { ref } from 'vue'
import { getAccessToken } from '@/api/authToken'
import { listUserPreferences, saveUserPreference } from '@/api/userPreferences'

const STORAGE_KEY = 'ai-stocks-theme'
const isDark = ref(false)
let syncedToken = ''

function apply(v: boolean) {
  document.documentElement.classList.toggle('dark', v)
}

function persistLocal() {
  localStorage.setItem(STORAGE_KEY, isDark.value ? 'dark' : 'light')
}

async function saveThemePreference() {
  if (!getAccessToken()) return
  try {
    await saveUserPreference({
      scope: 'global',
      prefKey: 'theme',
      value: { mode: isDark.value ? 'dark' : 'light' },
      schemaVersion: 1,
    })
  } catch {
    /* 远端偏好失败不影响主题切换 */
  }
}

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
  void saveThemePreference()
}

export async function syncThemePreference() {
  const token = getAccessToken()
  if (!token || syncedToken === token) return
  syncedToken = token
  try {
    const res = await listUserPreferences({ scope: 'global', prefKey: 'theme' })
    const mode = (res.items[0]?.value as { mode?: unknown } | undefined)?.mode
    if (mode === 'dark' || mode === 'light') {
      isDark.value = mode === 'dark'
      persistLocal()
      apply(isDark.value)
      return
    }
    await saveThemePreference()
  } catch {
    /* 登录后偏好同步失败时继续使用 localStorage 主题 */
  }
}

export function useTheme() {
  return { isDark, toggleTheme, syncThemePreference }
}
