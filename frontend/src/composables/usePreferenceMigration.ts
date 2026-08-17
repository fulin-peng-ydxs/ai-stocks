import { getAccessToken } from '@/api/authToken'
import {
  LAYOUT_CONFIG_SCHEMA_VERSION,
  saveLayoutUserConfig,
  type LayoutOverlayValues,
} from '@/api/layout'
import { saveUserPreferencesBulk, type SaveUserPreferencePayload } from '@/api/userPreferences'
import {
  getPageLayout,
  knobMap,
  readStoredComponentOverlay,
  readStoredOverlay,
  type PageLayout,
} from '@/layout'

export const CONFIG_STORAGE_MIGRATION_MARKER = 'ai-stocks:migration:config-storage-pg:v1'
export const CONFIG_STORAGE_MIGRATION_SOURCE = 'config-storage-pg-v1'

type DrawerSize = 'sm' | 'md' | 'lg'
type NavigationMode = 'sidebar-tabs' | 'dual-topbar'

export interface PreferenceMigrationResult {
  skipped: boolean
  migrated: boolean
  layoutCount: number
  preferenceCount: number
  failed: boolean
}

const DRAWER_SIZE_KEYS: DrawerSize[] = ['sm', 'md', 'lg']
const NAVIGATION_MODES: NavigationMode[] = ['sidebar-tabs', 'dual-topbar']
const PREFERENCE_BULK_CHUNK_SIZE = 100
let runningMigration: Promise<PreferenceMigrationResult> | null = null

function emptyResult(skipped: boolean): PreferenceMigrationResult {
  return {
    skipped,
    migrated: false,
    layoutCount: 0,
    preferenceCount: 0,
    failed: false,
  }
}

function storageKeys(prefix: string): string[] {
  const keys: string[] = []
  for (let i = 0; i < localStorage.length; i += 1) {
    const key = localStorage.key(i)
    if (key?.startsWith(prefix)) keys.push(key)
  }
  return keys.sort()
}

function readJsonObject(key: string): Record<string, unknown> | null {
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
      ? parsed as Record<string, unknown>
      : null
  } catch {
    return null
  }
}

function readLegacyLayoutOverride(key: string): { schemaVersion?: number; values?: Record<string, unknown> } | null {
  const parsed = readJsonObject(key)
  if (!parsed) return null
  if ('values' in parsed) {
    return {
      schemaVersion: typeof parsed.schemaVersion === 'number' ? parsed.schemaVersion : undefined,
      values: readObjectValue(parsed.values),
    }
  }
  return { schemaVersion: LAYOUT_CONFIG_SCHEMA_VERSION, values: parsed }
}

function readObjectValue(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : undefined
}

function readLegacyDrawerSize(key: string): DrawerSize | undefined {
  const parsed = readLegacyLayoutOverride(key)
  if (parsed?.schemaVersion && parsed.schemaVersion !== LAYOUT_CONFIG_SCHEMA_VERSION) return undefined
  const size = parsed?.values?.['slots.settings.config.size']
  return DRAWER_SIZE_KEYS.includes(size as DrawerSize) ? size as DrawerSize : undefined
}

function readThemePreference(): SaveUserPreferencePayload | null {
  const mode = localStorage.getItem('ai-stocks-theme')
  if (mode !== 'dark' && mode !== 'light' && mode !== 'system') return null
  return {
    scope: 'global',
    prefKey: 'theme',
    value: { mode },
    schemaVersion: 1,
  }
}

function readNavigationPreference(): SaveUserPreferencePayload | null {
  const mode = localStorage.getItem('ai-stocks-navigation-mode')
  if (!NAVIGATION_MODES.includes(mode as NavigationMode)) return null
  return {
    scope: 'global',
    prefKey: 'navigation',
    value: { mode },
    schemaVersion: 1,
  }
}

function readKlinePreference(): SaveUserPreferencePayload | null {
  const value = readJsonObject('ai-stocks:kline-prefs')
  if (!value) return null
  return {
    scope: 'global',
    prefKey: 'kline-prefs',
    value,
    schemaVersion: 1,
  }
}

function collectPageSettingsPreferences(): SaveUserPreferencePayload[] {
  const prefix = 'ai-stocks:page-settings:'
  const items: SaveUserPreferencePayload[] = []
  for (const key of storageKeys(prefix)) {
    const pageKey = key.slice(prefix.length)
    const value = readJsonObject(key)
    if (!pageKey || !value) continue
    items.push({
      scope: 'page',
      pageKey,
      prefKey: 'settings',
      value,
      schemaVersion: 1,
    })
  }
  return items
}

function slotKindMap(layout: PageLayout): Map<string, string> {
  return new Map(layout.slots.map((slot) => [slot.id, slot.component as string]))
}

function collectLayoutUserConfigs(): Array<{ pageKey: string; layout: PageLayout; values: LayoutOverlayValues }> {
  const prefix = 'ai-stocks:layout:'
  const componentPrefix = 'ai-stocks:layout-cc:'
  const pageKeys = new Set<string>()
  for (const key of storageKeys(prefix)) pageKeys.add(key.slice(prefix.length))
  for (const key of storageKeys(componentPrefix)) pageKeys.add(key.slice(componentPrefix.length))

  const configs: Array<{ pageKey: string; layout: PageLayout; values: LayoutOverlayValues }> = []
  for (const pageKey of [...pageKeys].sort()) {
    let layout: PageLayout
    try {
      layout = getPageLayout(pageKey)
    } catch {
      continue
    }
    const values = {
      ...readStoredOverlay(`${prefix}${pageKey}`, knobMap(layout)),
      ...readStoredComponentOverlay(`${componentPrefix}${pageKey}`, slotKindMap(layout)),
    }
    if (Object.keys(values).length) configs.push({ pageKey, layout, values })
  }
  return configs
}

function collectUserPreferences(): SaveUserPreferencePayload[] {
  const items: SaveUserPreferencePayload[] = []
  for (const item of collectPageSettingsPreferences()) items.push(item)

  const drawerSize = storageKeys('ai-stocks:layout-cc:')
    .map(readLegacyDrawerSize)
    .find((size): size is DrawerSize => !!size)
  if (drawerSize) {
    items.push({
      scope: 'global',
      pageKey: '',
      prefKey: 'settings-drawer',
      value: { size: drawerSize },
      schemaVersion: 1,
    })
  }

  for (const item of [
    readThemePreference(),
    readNavigationPreference(),
    readKlinePreference(),
  ]) {
    if (item) items.push(item)
  }
  return items
}

async function runMigration(): Promise<PreferenceMigrationResult> {
  if (!getAccessToken()) return emptyResult(true)
  if (localStorage.getItem(CONFIG_STORAGE_MIGRATION_MARKER)) return emptyResult(true)

  const result = emptyResult(false)
  const layoutConfigs = collectLayoutUserConfigs()
  const preferences = collectUserPreferences()

  for (const item of layoutConfigs) {
    try {
      await saveLayoutUserConfig(item.pageKey, {
        config: { schemaVersion: LAYOUT_CONFIG_SCHEMA_VERSION, values: item.values },
        schemaVersion: LAYOUT_CONFIG_SCHEMA_VERSION,
        layout: item.layout as unknown as Record<string, unknown>,
      })
      result.layoutCount += 1
    } catch {
      result.failed = true
    }
  }

  for (let i = 0; i < preferences.length; i += PREFERENCE_BULK_CHUNK_SIZE) {
    const chunk = preferences.slice(i, i + PREFERENCE_BULK_CHUNK_SIZE)
    if (!chunk.length) continue
    try {
      await saveUserPreferencesBulk(chunk, { migrationSource: CONFIG_STORAGE_MIGRATION_SOURCE })
      result.preferenceCount += chunk.length
    } catch {
      result.failed = true
    }
  }

  result.migrated = result.layoutCount > 0 || result.preferenceCount > 0
  if (!result.failed) {
    localStorage.setItem(CONFIG_STORAGE_MIGRATION_MARKER, new Date().toISOString())
  } else {
    console.warn('[preference-migration] 旧本地偏好迁移失败，将继续使用本地 fallback 并在下次登录后重试。')
  }
  return result
}

export function migrateLocalPreferencesToRemote(): Promise<PreferenceMigrationResult> {
  if (!runningMigration) {
    runningMigration = runMigration().finally(() => {
      runningMigration = null
    })
  }
  return runningMigration
}
