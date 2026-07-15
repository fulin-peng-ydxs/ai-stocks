// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { writeAuth } from '@/api/authToken'
import {
  CONFIG_STORAGE_MIGRATION_MARKER,
  migrateLocalPreferencesToRemote,
} from '@/composables/usePreferenceMigration'

const layoutApi = vi.hoisted(() => ({
  saveLayoutUserConfig: vi.fn(),
}))

const prefApi = vi.hoisted(() => ({
  saveUserPreferencesBulk: vi.fn(),
}))

vi.mock('@/api/layout', () => ({
  LAYOUT_CONFIG_SCHEMA_VERSION: 1,
  saveLayoutUserConfig: layoutApi.saveLayoutUserConfig,
}))

vi.mock('@/api/userPreferences', () => ({
  saveUserPreferencesBulk: prefApi.saveUserPreferencesBulk,
}))

function login() {
  writeAuth({
    accessToken: 'token',
    refreshToken: 'refresh',
    user: { id: 'u', account: 'u' },
    tenant: { id: 't' },
    role: 'normal',
  })
}

function seedLegacyPreferences() {
  localStorage.setItem('ai-stocks:layout:board', JSON.stringify({
    schemaVersion: 1,
    values: { density: 'compact', unknown: 'drop-me' },
  }))
  localStorage.setItem('ai-stocks:layout-cc:board', JSON.stringify({
    schemaVersion: 1,
    values: {
      'slots.table.config.hiddenColumns': ['score'],
      'slots.settings.config.size': 'lg',
      'slots.settings.config.defaultCollapsed': ['layout'],
      'slots.settings.config.bodyScroll': false,
    },
  }))
  localStorage.setItem('ai-stocks:page-settings:data-dictionary', JSON.stringify({ onlyChanged: true }))
  localStorage.setItem('ai-stocks-theme', 'dark')
  localStorage.setItem('ai-stocks-navigation-mode', 'dual-topbar')
  localStorage.setItem('ai-stocks:kline-prefs', JSON.stringify({
    periods: [30, 90],
    includeAll: false,
    defaultPeriod: 90,
  }))
  localStorage.setItem('ai-stocks-backtest-params', JSON.stringify({
    kind: 'signal',
    limit: 20,
  }))
}

describe('usePreferenceMigration', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    layoutApi.saveLayoutUserConfig.mockResolvedValue({})
    prefApi.saveUserPreferencesBulk.mockResolvedValue({ items: [] })
  })

  it('未登录时不迁移也不写 marker', async () => {
    seedLegacyPreferences()

    const result = await migrateLocalPreferencesToRemote()

    expect(result.skipped).toBe(true)
    expect(layoutApi.saveLayoutUserConfig).not.toHaveBeenCalled()
    expect(prefApi.saveUserPreferencesBulk).not.toHaveBeenCalled()
    expect(localStorage.getItem(CONFIG_STORAGE_MIGRATION_MARKER)).toBeNull()
  })

  it('登录后拆分迁移 layout_user_config、全局抽屉和业务偏好', async () => {
    login()
    seedLegacyPreferences()

    const result = await migrateLocalPreferencesToRemote()

    expect(result.failed).toBe(false)
    expect(result.layoutCount).toBe(1)
    expect(layoutApi.saveLayoutUserConfig).toHaveBeenCalledWith(
      'board',
      expect.objectContaining({
        config: {
          schemaVersion: 1,
          values: {
            density: 'compact',
            'slots.table.config.hiddenColumns': ['score'],
          },
        },
        layout: expect.objectContaining({ pageKey: 'board' }),
      }),
    )

    const bulkItems = prefApi.saveUserPreferencesBulk.mock.calls[0][0]
    expect(bulkItems).toEqual(expect.arrayContaining([
      expect.objectContaining({
        scope: 'page',
        pageKey: 'data-dictionary',
        prefKey: 'settings',
        value: { onlyChanged: true },
      }),
      expect.objectContaining({
        scope: 'global',
        prefKey: 'settings-drawer',
        value: { size: 'lg' },
      }),
      expect.objectContaining({ scope: 'global', prefKey: 'theme', value: { mode: 'dark' } }),
      expect.objectContaining({ scope: 'global', prefKey: 'navigation', value: { mode: 'dual-topbar' } }),
      expect.objectContaining({
        scope: 'global',
        prefKey: 'kline-prefs',
        value: { periods: [30, 90], includeAll: false, defaultPeriod: 90 },
      }),
      expect.objectContaining({
        scope: 'feature',
        pageKey: 'backtest',
        prefKey: 'params',
        value: { kind: 'signal', limit: 20 },
      }),
    ]))
    expect(bulkItems.find((item: { prefKey: string }) => item.prefKey === 'settings-drawer').value)
      .not.toHaveProperty('defaultCollapsed')
    expect(localStorage.getItem(CONFIG_STORAGE_MIGRATION_MARKER)).toBeTruthy()
  })

  it('marker 存在时跳过重复迁移', async () => {
    login()
    seedLegacyPreferences()
    localStorage.setItem(CONFIG_STORAGE_MIGRATION_MARKER, 'done')

    const result = await migrateLocalPreferencesToRemote()

    expect(result.skipped).toBe(true)
    expect(layoutApi.saveLayoutUserConfig).not.toHaveBeenCalled()
    expect(prefApi.saveUserPreferencesBulk).not.toHaveBeenCalled()
  })

  it('迁移失败时不写 marker，便于下次重试', async () => {
    login()
    seedLegacyPreferences()
    layoutApi.saveLayoutUserConfig.mockRejectedValueOnce(new Error('failed'))
    vi.spyOn(console, 'warn').mockImplementation(() => undefined)

    const result = await migrateLocalPreferencesToRemote()

    expect(result.failed).toBe(true)
    expect(prefApi.saveUserPreferencesBulk).toHaveBeenCalled()
    expect(localStorage.getItem(CONFIG_STORAGE_MIGRATION_MARKER)).toBeNull()
  })
})
