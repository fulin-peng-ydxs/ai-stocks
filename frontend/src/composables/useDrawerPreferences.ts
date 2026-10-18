import { computed, reactive } from 'vue'
import { getAccessToken, readAuth } from '@/api/authToken'
import { createGlobalPreferenceSync } from './useGlobalPreferenceSync'

export type DrawerSectionKey = 'layout' | 'components' | 'business'
export type DrawerSize = 'sm' | 'md' | 'lg'

export interface DrawerPreferenceValue {
  size?: DrawerSize
  collapsedSections?: DrawerSectionKey[]
  /** 页面内稳定节点的关闭清单，和三个全局一级分组分开。 */
  collapsedGroups?: Record<string, string[]>
}

const SECTION_KEYS: DrawerSectionKey[] = ['layout', 'components', 'business']
const SIZE_KEYS: DrawerSize[] = ['sm', 'md', 'lg']
const STORAGE_PREFIX = 'ai-stocks:drawer-preferences'

const state = reactive({
  hydrated: false,
  loading: false,
  failed: false,
  editedFields: new Set<'size' | 'collapsedSections'>(),
  editedPages: new Set<string>(),
  pending: false,
  value: {} as DrawerPreferenceValue,
})

let activeStorageKey = ''
let revision = 0
let saveChain = Promise.resolve()

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
  // 兼容旧偏好字段；新写入只保留“当前折叠态”语义，避免再被理解为可配置默认值。
  const collapsed = cleanCollapsed(raw.collapsedSections ?? raw.defaultCollapsed)
  if (size) next.size = size
  if (collapsed) next.collapsedSections = collapsed
  if (raw.collapsedGroups && typeof raw.collapsedGroups === 'object' && !Array.isArray(raw.collapsedGroups)) {
    next.collapsedGroups = Object.fromEntries(Object.entries(raw.collapsedGroups)
      .filter(([page, keys]) => page && Array.isArray(keys))
      .map(([page, keys]) => [page, [...new Set((keys as unknown[])
        .filter((key): key is string => typeof key === 'string' && !!key))]]))
  }
  return next
}

function readLocal(): DrawerPreferenceValue {
  try {
    const raw = localStorage.getItem(activeStorageKey || storageKeyForCurrentIdentity())
    const saved = raw ? JSON.parse(raw) : undefined
    if (saved?.pending && typeof saved.pending === 'object') {
      const fields: unknown[] = Array.isArray(saved.pending.fields) ? saved.pending.fields : []
      fields.forEach(field => {
        if (field === 'size' || field === 'collapsedSections') state.editedFields.add(field)
      })
      const pages: unknown[] = Array.isArray(saved.pending.pages) ? saved.pending.pages : []
      pages.forEach(page => {
        if (typeof page === 'string' && page) state.editedPages.add(page)
      })
      state.pending = state.editedFields.size > 0 || state.editedPages.size > 0
    }
    return normalizePreference(saved)
  } catch {
    return {}
  }
}

function persistLocal(): void {
  try {
    const value = {
      ...state.value,
      ...(state.pending ? {
        pending: { fields: [...state.editedFields], pages: [...state.editedPages] },
      } : {}),
    }
    localStorage.setItem(activeStorageKey || storageKeyForCurrentIdentity(), JSON.stringify(value))
  } catch {
    /* 本地 fallback 失败不影响页面渲染 */
  }
}

function replaceStateValue(value: DrawerPreferenceValue): void {
  state.value.size = value.size
  state.value.collapsedSections = value.collapsedSections
  state.value.collapsedGroups = value.collapsedGroups
}

const drawerPreferenceSync = createGlobalPreferenceSync<DrawerPreferenceValue>({
  prefKey: 'settings-drawer',
  identityKey: storageKeyForCurrentIdentity,
  isHydrated: () => state.hydrated,
  snapshot: () => JSON.parse(JSON.stringify(state.value)) as DrawerPreferenceValue,
  normalize: normalizePreference,
  applyRemote(remote) {
    if (!state.editedFields.has('size')) state.value.size = remote.size
    if (!state.editedFields.has('collapsedSections')) state.value.collapsedSections = remote.collapsedSections
    const groups = { ...remote.collapsedGroups }
    for (const page of state.editedPages) groups[page] = state.value.collapsedGroups?.[page] ?? []
    state.value.collapsedGroups = Object.keys(groups).length ? groups : undefined
  },
  persistLocal,
  onIdentityChange({ identityKey }) {
    activeStorageKey = identityKey
    state.hydrated = false
    state.loading = false
    state.failed = false
    state.editedFields.clear()
    state.editedPages.clear()
    state.pending = false
    revision += 1
    saveChain = Promise.resolve()
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
    if (state.pending) void saveCurrent()
  },
  onLoadError() {
    state.hydrated = true
    state.failed = true
  },
  onLoadFinally() {
    state.loading = false
  },
})

/** 串行保存最终选择；本地先保留待同步意图，刷新和旧响应都不能反向覆盖用户操作。 */
function saveCurrent(): Promise<void> {
  if (!state.hydrated || !getAccessToken()) return Promise.resolve()
  const requestKey = activeStorageKey
  const requestRevision = revision
  const token = getAccessToken()
  const value = JSON.parse(JSON.stringify(state.value)) as DrawerPreferenceValue
  const isCurrent = () => requestKey === activeStorageKey
    && requestKey === storageKeyForCurrentIdentity() && token === getAccessToken()
    && requestRevision === revision
  saveChain = saveChain.then(async () => {
    if (!isCurrent()) return
    const saved = await drawerPreferenceSync.saveNow(value)
    if (!isCurrent()) return
    state.failed = !saved
    if (saved) {
      state.pending = false
      state.editedFields.clear()
      state.editedPages.clear()
      persistLocal()
    }
  })
  return saveChain
}

function scheduleSave(): void {
  revision += 1
  state.pending = !!getAccessToken()
  persistLocal()
  if (!state.hydrated) void load()
  else void saveCurrent()
}

function resetPreference(pageKey?: string): void {
  drawerPreferenceSync.ensureIdentity()
  state.value.size = undefined
  state.value.collapsedSections = undefined
  state.editedFields.add('size')
  state.editedFields.add('collapsedSections')
  if (pageKey) {
    state.value.collapsedGroups = { ...state.value.collapsedGroups, [pageKey]: [] }
    state.editedPages.add(pageKey)
  }
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
  state.editedFields.clear()
  state.editedPages.clear()
  state.pending = false
  revision += 1
  saveChain = Promise.resolve()
  replaceStateValue({})
}

export function useDrawerPreferences() {
  void load()

  const size = computed(() => state.value.size)
  const collapsedSections = computed(() => state.value.collapsedSections)

  function setSize(value: unknown): void {
    const next = cleanSize(value)
    if (!next) return
    drawerPreferenceSync.ensureIdentity()
    state.value.size = next
    state.editedFields.add('size')
    scheduleSave()
  }

  function setCollapsedSections(value: unknown): void {
    const next = cleanCollapsed(value)
    if (!next) return
    drawerPreferenceSync.ensureIdentity()
    state.value.collapsedSections = next
    state.editedFields.add('collapsedSections')
    scheduleSave()
  }

  function groupOpen(pageKey: string, key: string): boolean | undefined {
    const closed = state.value.collapsedGroups?.[pageKey]
    return Array.isArray(closed) ? !closed.includes(key) : undefined
  }

  function setGroupOpen(pageKey: string, key: string, open: boolean): void {
    if (!pageKey || !key) return
    drawerPreferenceSync.ensureIdentity()
    const closed = new Set(state.value.collapsedGroups?.[pageKey] ?? [])
    if (open) closed.delete(key)
    else closed.add(key)
    state.value.collapsedGroups = { ...state.value.collapsedGroups, [pageKey]: [...closed] }
    state.editedPages.add(pageKey)
    scheduleSave()
  }

  return {
    groupOpen,
    setGroupOpen,
    hydrated: computed(() => state.hydrated),
    loading: computed(() => state.loading),
    failed: computed(() => state.failed),
    size,
    collapsedSections,
    setSize,
    setCollapsedSections,
    reset: resetPreference,
  }
}
