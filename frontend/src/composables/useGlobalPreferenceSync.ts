import { getAccessToken } from '@/api/authToken'
import { listUserPreferences, saveUserPreference } from '@/api/userPreferences'

interface IdentityContext {
  token: string
  identityKey: string
}

export interface GlobalPreferenceSyncOptions<T> {
  prefKey: string
  schemaVersion?: number
  pageKey?: string
  debounceMs?: number
  identityKey?: () => string
  isHydrated?: () => boolean
  snapshot: () => T
  normalize: (value: unknown) => T | undefined
  applyRemote: (value: T) => void | Promise<void>
  persistLocal?: () => void
  onIdentityChange?: (ctx: IdentityContext) => void
  onNoToken?: () => void
  onLoadStart?: () => void
  onLoadSuccess?: () => void
  onLoadError?: () => void
  onLoadFinally?: () => void
  onSaveSuccess?: () => void
  onSaveError?: () => void
  afterRemoteApplied?: () => void
}

/** 全局用户偏好同步内核：只封装 token/身份守卫、PG 读写、debounce 和失败回调。 */
export function createGlobalPreferenceSync<T>(options: GlobalPreferenceSyncOptions<T>) {
  let activeIdentity = ''
  let loadPromise: Promise<void> | null = null
  let saveTimer: number | undefined

  function identityKey(): string {
    return options.identityKey?.() ?? ''
  }

  function clearSaveTimer(): void {
    if (saveTimer) window.clearTimeout(saveTimer)
    saveTimer = undefined
  }

  function ensureIdentity(): IdentityContext & { changed: boolean } {
    const token = getAccessToken()
    const key = identityKey()
    const identity = `${token || ''}:${key}`
    const changed = identity !== activeIdentity
    if (changed) {
      clearSaveTimer()
      loadPromise = null
      activeIdentity = identity
      options.onIdentityChange?.({ token, identityKey: key })
    }
    return { token, identityKey: key, changed }
  }

  async function saveNow(value: T = options.snapshot()): Promise<boolean> {
    const { token } = ensureIdentity()
    if (!token) return false
    try {
      await saveUserPreference<T>({
        scope: 'global',
        pageKey: options.pageKey ?? '',
        prefKey: options.prefKey,
        value,
        schemaVersion: options.schemaVersion ?? 1,
      })
      options.onSaveSuccess?.()
      return true
    } catch {
      options.onSaveError?.()
      return false
    }
  }

  function scheduleSave(): void {
    const { token } = ensureIdentity()
    options.persistLocal?.()
    if (!token) return
    clearSaveTimer()
    saveTimer = window.setTimeout(() => {
      saveTimer = undefined
      void saveNow()
    }, options.debounceMs ?? 300)
  }

  async function syncOnce(): Promise<void> {
    const { token, changed } = ensureIdentity()
    if (!token) {
      options.onNoToken?.()
      return
    }
    if (loadPromise) return loadPromise
    if (!changed && options.isHydrated?.()) return
    if (!changed && !options.isHydrated) return

    options.onLoadStart?.()
    loadPromise = listUserPreferences({ scope: 'global', prefKey: options.prefKey })
      .then(async (res) => {
        const remote = options.normalize(res.items[0]?.value)
        if (remote !== undefined) {
          await options.applyRemote(remote)
          options.persistLocal?.()
          options.afterRemoteApplied?.()
        } else {
          await saveNow()
        }
        options.onLoadSuccess?.()
      })
      .catch(() => {
        options.onLoadError?.()
      })
      .finally(() => {
        options.onLoadFinally?.()
        loadPromise = null
      })
    return loadPromise
  }

  function resetForTests(): void {
    clearSaveTimer()
    activeIdentity = ''
    loadPromise = null
  }

  return {
    ensureIdentity,
    saveNow,
    scheduleSave,
    syncOnce,
    resetForTests,
  }
}
