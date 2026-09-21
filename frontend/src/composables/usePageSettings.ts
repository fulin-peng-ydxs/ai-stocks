import { useUserPreference } from './useUserPreference'

export function usePageSettings<T extends Record<string, unknown>>(
  pageKey: string,
  defaults: T,
  options: { deferUnknownFieldCleanup?: boolean } = {},
) {
  const pref = useUserPreference({
    scope: 'page',
    pageKey,
    prefKey: 'settings',
    defaults,
    localStorageKey: `ai-stocks:page-settings:${pageKey}`,
    deferUnknownFieldCleanup: options.deferUnknownFieldCleanup,
  })

  return {
    settings: pref.value,
    isDirty: pref.isDirty,
    reset: pref.reset,
    hydrated: pref.hydrated,
    whenHydrated: pref.whenHydrated,
    remoteError: pref.remoteError,
    saving: pref.saving,
    saveError: pref.saveError,
    save: pref.saveRemoteNow,
    legacySnapshot: pref.legacySnapshot,
  }
}
