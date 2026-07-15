import { computed, reactive } from 'vue'
import { listUserPreferences, saveUserPreference } from '@/api/userPreferences'

export type DrawerSectionKey = 'layout' | 'components' | 'business'
export type DrawerSize = 'sm' | 'md' | 'lg'

export interface DrawerPreferenceValue {
  size?: DrawerSize
  defaultCollapsed?: DrawerSectionKey[]
}

const SECTION_KEYS: DrawerSectionKey[] = ['layout', 'components', 'business']
const SIZE_KEYS: DrawerSize[] = ['sm', 'md', 'lg']

const state = reactive({
  hydrated: false,
  loading: false,
  failed: false,
  dirty: new Set<keyof DrawerPreferenceValue>(),
  value: {} as DrawerPreferenceValue,
})

let loadPromise: Promise<void> | null = null
let saveTimer: number | undefined

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

function scheduleSave(): void {
  if (saveTimer) window.clearTimeout(saveTimer)
  saveTimer = window.setTimeout(async () => {
    saveTimer = undefined
    try {
      await saveUserPreference<DrawerPreferenceValue>({
        scope: 'global',
        pageKey: '',
        prefKey: 'settings-drawer',
        value: { ...state.value },
        schemaVersion: 1,
      })
      state.failed = false
    } catch {
      state.failed = true
    }
  }, 300)
}

async function load(): Promise<void> {
  if (state.hydrated || loadPromise) return loadPromise ?? Promise.resolve()
  state.loading = true
  loadPromise = listUserPreferences({ scope: 'global', prefKey: 'settings-drawer' })
    .then((res) => {
      const remote = normalizePreference(res.items[0]?.value)
      if (!state.dirty.has('size')) state.value.size = remote.size
      if (!state.dirty.has('defaultCollapsed')) state.value.defaultCollapsed = remote.defaultCollapsed
      state.hydrated = true
      state.failed = false
      if (state.dirty.size) scheduleSave()
    })
    .catch(() => {
      state.hydrated = true
      state.failed = true
    })
    .finally(() => {
      state.loading = false
      loadPromise = null
    })
  return loadPromise
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
    failed: computed(() => state.failed),
    size,
    defaultCollapsed,
    setSize,
    setDefaultCollapsed,
  }
}
