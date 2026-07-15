import { ref } from 'vue'
import { createGlobalPreferenceSync } from './useGlobalPreferenceSync'

export type NavigationMode = 'sidebar-tabs' | 'dual-topbar'

const STORAGE_KEY = 'ai-stocks-navigation-mode'
const navigationMode = ref<NavigationMode>('sidebar-tabs')
const selectedPrimaryMenuIndex = ref('')

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
  void navigationPreferenceSync.saveNow()
}

const navigationPreferenceSync = createGlobalPreferenceSync<{ mode: NavigationMode }>({
  prefKey: 'navigation',
  snapshot: () => ({ mode: navigationMode.value }),
  normalize(value) {
    const mode = (value as { mode?: unknown } | undefined)?.mode
    return typeof mode === 'string' && isNavigationMode(mode) ? { mode } : undefined
  },
  applyRemote(value) {
    navigationMode.value = value.mode
    localStorage.setItem(STORAGE_KEY, value.mode)
  },
})

export async function syncNavigationPreference() {
  await navigationPreferenceSync.syncOnce()
}

export function useAppNavigation() {
  return {
    navigationMode,
    selectedPrimaryMenuIndex,
    setNavigationMode,
    syncNavigationPreference,
  }
}
