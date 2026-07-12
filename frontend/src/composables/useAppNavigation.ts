import { ref } from 'vue'

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
}

export function useAppNavigation() {
  return {
    navigationMode,
    selectedPrimaryMenuIndex,
    setNavigationMode,
  }
}
