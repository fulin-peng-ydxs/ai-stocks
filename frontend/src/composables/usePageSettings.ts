import { useUserPreference } from './useUserPreference'

export function usePageSettings<T extends Record<string, unknown>>(pageKey: string, defaults: T) {
  const pref = useUserPreference({
    scope: 'page',
    pageKey,
    prefKey: 'settings',
    defaults,
    localStorageKey: `ai-stocks:page-settings:${pageKey}`,
  })

  return {
    settings: pref.value,
    isDirty: pref.isDirty,
    reset: pref.reset,
    hydrated: pref.hydrated,
    remoteError: pref.remoteError,
  }
}
