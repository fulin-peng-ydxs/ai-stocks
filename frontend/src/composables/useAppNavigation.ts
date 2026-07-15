import { ref } from 'vue'
import { getAccessToken } from '@/api/authToken'
import { listUserPreferences, saveUserPreference } from '@/api/userPreferences'

export type NavigationMode = 'sidebar-tabs' | 'dual-topbar'

const STORAGE_KEY = 'ai-stocks-navigation-mode'
const navigationMode = ref<NavigationMode>('sidebar-tabs')
const selectedPrimaryMenuIndex = ref('')
let syncedToken = ''

function isNavigationMode(value: string | null): value is NavigationMode {
  return value === 'sidebar-tabs' || value === 'dual-topbar'
}

export function initAppNavigation() {
  const saved = localStorage.getItem(STORAGE_KEY)
  navigationMode.value = isNavigationMode(saved) ? saved : 'sidebar-tabs'
}

export function setNavigationMode(mode: NavigationMode) {
  navigationMode.value = mode
  localStorage.setItem(STORAGE_KEY, mode)
  void saveNavigationPreference()
}

async function saveNavigationPreference() {
  if (!getAccessToken()) return
  try {
    await saveUserPreference({
      scope: 'global',
      prefKey: 'navigation',
      value: { mode: navigationMode.value },
      schemaVersion: 1,
    })
  } catch {
    /* 远端偏好失败不影响本地导航模式 */
  }
}

export async function syncNavigationPreference() {
  const token = getAccessToken()
  if (!token || syncedToken === token) return
  syncedToken = token
  try {
    const res = await listUserPreferences({ scope: 'global', prefKey: 'navigation' })
    const mode = (res.items[0]?.value as { mode?: unknown } | undefined)?.mode
    const normalized = typeof mode === 'string' && isNavigationMode(mode) ? mode : null
    if (normalized) {
      navigationMode.value = normalized
      localStorage.setItem(STORAGE_KEY, normalized)
      return
    }
    await saveNavigationPreference()
  } catch {
    /* 登录后偏好同步失败时继续使用 localStorage 导航模式 */
  }
}

export function useAppNavigation() {
  return {
    navigationMode,
    selectedPrimaryMenuIndex,
    setNavigationMode,
    syncNavigationPreference,
  }
}
