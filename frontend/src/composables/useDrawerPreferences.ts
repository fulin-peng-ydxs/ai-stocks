import { computed, reactive } from 'vue'
import { getAccessToken, readAuth } from '@/api/authToken'
import { createGlobalPreferenceSync } from './useGlobalPreferenceSync'

export type DrawerSectionKey = 'layout' | 'components' | 'business'
export type DrawerSize = 'sm' | 'md' | 'lg'

export interface DrawerPreferenceValue {
  size?: DrawerSize
  defaultCollapsed?: DrawerSectionKey[]
}

const SECTION_KEYS: DrawerSectionKey[] = ['layout', 'components', 'business']
const SIZE_KEYS: DrawerSize[] = ['sm', 'md', 'lg']
const STORAGE_PREFIX = 'ai-stocks:drawer-preferences'

const state = reactive({
  hydrated: false,
  loading: false,
  failed: false,
  dirty: new Set<keyof DrawerPreferenceValue>(),
  value: {} as DrawerPreferenceValue,
})

let activeStorageKey = ''

function storageKeyForCurrentIdentity(): string {
  const auth = readAuth()
  if (auth.accessToken && auth.user?.id) {
    return `${STORAGE_PREFIX}:${auth.tenant?.id || 'default'}:${auth.user.id}`
  }
  return `${STORAGE_PREFIX}:anonymous`
}

function cleanSize(value: unknown): DrawerSize | undefined {
  return SIZE_KEYS.includes(value as DrawerSize) ? value as DrawerSize : undefined
}

function cleanCollapsed(value: unknown): DrawerSectionKey[] | undefined {
  if (!Array.isArray(value)) return undefined
  return value.filter((item): item is DrawerSectionKey => SECTION_KEYS.includes(item as DrawerSectionKey))
}

function normalizePreference(value: unknown): DrawerPreferenceValue {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {}
  const raw = value as Record<string, unknown>
  const next: DrawerPreferenceValue = {}
  const size = cleanSize(raw.size)
  const collapsed = cleanCollapsed(raw.defaultCollapsed)
  if (size) next.size = size
  if (collapsed) next.defaultCollapsed = collapsed
  return next
}

function readLocal(): DrawerPreferenceValue {
  try {
    const raw = localStorage.getItem(activeStorageKey || storageKeyForCurrentIdentity())
    return normalizePreference(raw ? JSON.parse(raw) : undefined)
  } catch {
    return {}
  }
}

function persistLocal(): void {
  try {
    localStorage.setItem(activeStorageKey || storageKeyForCurrentIdentity(), JSON.stringify(state.value))
  } catch {
    /* 本地 fallback 失败不影响页面渲染 */
  }
}

function replaceStateValue(value: DrawerPreferenceValue): void {
  state.value.size = value.size
  state.value.defaultCollapsed = value.defaultCollapsed
}

const drawerPreferenceSync = createGlobalPreferenceSync<DrawerPreferenceValue>({
  prefKey: 'settings-drawer',
  identityKey: storageKeyForCurrentIdentity,
  isHydrated: () => state.hydrated,
  snapshot: () => ({ ...state.value }),
  normalize: normalizePreference,
  applyRemote(remote) {
    if (!state.dirty.has('size')) state.value.size = remote.size
    if (!state.dirty.has('defaultCollapsed')) state.value.defaultCollapsed = remote.defaultCollapsed
  },
  persistLocal,
  onIdentityChange({ identityKey }) {
    activeStorageKey = identityKey
    state.hydrated = false
    state.loading = false
    state.failed = false
    state.dirty.clear()
    replaceStateValue(readLocal())
  },
  onNoToken() {
    state.hydrated = true
    state.failed = false
  },
  onLoadStart() {
    state.loading = true
  },
  onLoadSuccess() {
    state.hydrated = true
    state.failed = false
  },
  onLoadError() {
    state.hydrated = true
    state.failed = true
  },
  onLoadFinally() {
    state.loading = false
  },
  onSaveSuccess() {
    state.failed = false
  },
  onSaveError() {
    state.failed = true
  },
  afterRemoteApplied() {
    if (state.dirty.size) drawerPreferenceSync.scheduleSave()
  },
})

function scheduleSave(): void {
  drawerPreferenceSync.scheduleSave()
}

function resetPreference(): void {
  drawerPreferenceSync.ensureIdentity()
  replaceStateValue({})
  state.dirty.add('size')
  state.dirty.add('defaultCollapsed')
  scheduleSave()
}

async function load(): Promise<void> {
  return drawerPreferenceSync.syncOnce()
}

export function syncDrawerPreferences(): Promise<void> {
  return load()
}

export function resetDrawerPreferencesForTests(): void {
  drawerPreferenceSync.resetForTests()
  activeStorageKey = ''
  state.hydrated = false
  state.loading = false
  state.failed = false
  state.dirty.clear()
  replaceStateValue({})
}

export function useDrawerPreferences() {
  void load()

  const size = computed(() => state.value.size)
  const defaultCollapsed = computed(() => state.value.defaultCollapsed)

  function setSize(value: unknown): void {
    const next = cleanSize(value)
    if (!next) return
    state.value.size = next
    state.dirty.add('size')
    scheduleSave()
  }

  function setDefaultCollapsed(value: unknown): void {
    const next = cleanCollapsed(value)
    if (!next) return
    state.value.defaultCollapsed = next
    state.dirty.add('defaultCollapsed')
    scheduleSave()
  }

  return {
    hydrated: computed(() => state.hydrated),
    loading: computed(() => state.loading),
    failed: computed(() => state.failed),
    size,
    defaultCollapsed,
    setSize,
    setDefaultCollapsed,
    reset: resetPreference,
  }
}
