import { computed, reactive, ref, watch } from 'vue'
import { getAccessToken } from '@/api/authToken'
import { listUserPreferences, saveUserPreference } from '@/api/userPreferences'

export type UserPreferenceScope = 'global' | 'page' | 'feature'

export interface UseUserPreferenceOptions<T extends object> {
  scope: UserPreferenceScope
  pageKey?: string
  prefKey: string
  defaults: T
  localStorageKey: string
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

function isObject(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}

export function mergePreferenceDefaults<T>(defaults: T, saved: unknown): T {
  if (Array.isArray(defaults)) return Array.isArray(saved) ? (saved as T) : clone(defaults)
  if (isObject(defaults)) {
    const out: Record<string, unknown> = {}
    const src = isObject(saved) ? saved : {}
    for (const [key, value] of Object.entries(defaults)) {
      out[key] = mergePreferenceDefaults(value, src[key])
    }
    return out as T
  }
  return (saved === undefined ? defaults : saved) as T
}

export function replaceReactive<T extends Record<string, unknown>>(target: T, source: T): void {
  for (const key of Object.keys(target)) delete target[key]
  Object.assign(target, source)
}

function readLocal<T>(key: string, defaults: T): T {
  try {
    const raw = localStorage.getItem(key)
    return mergePreferenceDefaults(defaults, raw ? JSON.parse(raw) : undefined)
  } catch {
    return clone(defaults)
  }
}

export function useUserPreference<T extends object>(options: UseUserPreferenceOptions<T>) {
  const value = reactive(readLocal(options.localStorageKey, options.defaults)) as T
  const hydrated = ref(false)
  const remoteError = ref(false)
  const saving = ref(false)
  const saveError = ref(false)
  let applyingRemote = false
  let dirtyBeforeHydrate = false
  let saveTimer: number | undefined

  function persistLocal(): void {
    try {
      localStorage.setItem(options.localStorageKey, JSON.stringify(value))
    } catch {
      /* ignore */
    }
  }

  async function saveRemoteNow(): Promise<void> {
    if (!getAccessToken()) return
    saving.value = true
    try {
      await saveUserPreference<T>({
        scope: options.scope,
        pageKey: options.pageKey ?? '',
        prefKey: options.prefKey,
        value: clone(value),
        schemaVersion: 1,
      })
      saveError.value = false
    } catch {
      saveError.value = true
    } finally {
      saving.value = false
    }
  }

  function scheduleRemoteSave(): void {
    if (!getAccessToken()) return
    if (saveTimer) window.clearTimeout(saveTimer)
    saveTimer = window.setTimeout(() => {
      saveTimer = undefined
      void saveRemoteNow()
    }, 300)
  }

  async function loadRemote(): Promise<void> {
    if (!getAccessToken()) {
      hydrated.value = true
      return
    }
    try {
      const res = await listUserPreferences({
        scope: options.scope,
        pageKey: options.pageKey ?? '',
        prefKey: options.prefKey,
      })
      const remote = res.items[0]?.value
      if (!dirtyBeforeHydrate && remote !== undefined) {
        applyingRemote = true
        replaceReactive(value as Record<string, unknown>, mergePreferenceDefaults(options.defaults, remote) as Record<string, unknown>)
        applyingRemote = false
      } else if (dirtyBeforeHydrate) {
        await saveRemoteNow()
      }
      remoteError.value = false
    } catch {
      remoteError.value = true
    } finally {
      hydrated.value = true
    }
  }

  async function whenHydrated(): Promise<void> {
    if (hydrated.value) return
    await new Promise<void>((resolve) => {
      const stop = watch(hydrated, (ready) => {
        if (!ready) return
        stop()
        resolve()
      })
    })
  }

  watch(
    value,
    () => {
      persistLocal()
      if (!hydrated.value) dirtyBeforeHydrate = true
      if (!applyingRemote && hydrated.value) scheduleRemoteSave()
    },
    { deep: true },
  )

  const isDirty = computed(() => JSON.stringify(value) !== JSON.stringify(options.defaults))

  function reset(): void {
    replaceReactive(value as Record<string, unknown>, clone(options.defaults) as Record<string, unknown>)
  }

  void loadRemote()

  return {
    value,
    hydrated,
    remoteError,
    saving,
    saveError,
    isDirty,
    reset,
    loadRemote,
    whenHydrated,
    saveRemoteNow,
  }
}
