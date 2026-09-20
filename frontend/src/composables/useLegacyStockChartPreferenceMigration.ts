import { onMounted } from 'vue'
import { getAccessToken } from '@/api/authToken'
import {
  listUserPreferences,
  saveUserPreference,
  type UserPreferenceRecord,
} from '@/api/userPreferences'
import { normalizeStockChartPreferences } from '@/composables/useStockChartPreferences'

interface LegacyStockChartPreferenceMigrationAccess {
  pageKey: string
  slotId?: string
  componentSourceOf: (slotId: string, field: string) => unknown
  setComponentKnob: (slotId: string, field: string, value: unknown) => void
  whenRemoteHydrated: () => Promise<void>
  saveRemoteUserConfig: () => Promise<boolean | void>
  remoteSaveFailed: () => boolean
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : undefined
}

function readLocalRecord(pageKey: string): Record<string, unknown> | undefined {
  try {
    return asRecord(JSON.parse(localStorage.getItem(`ai-stocks:page-settings:${pageKey}`) || 'null'))
  } catch {
    return undefined
  }
}

function removeLocalLegacyField(pageKey: string, record: Record<string, unknown> | undefined): void {
  if (!record || !Object.prototype.hasOwnProperty.call(record, 'charts')) return
  const next = { ...record }
  delete next.charts
  localStorage.setItem(`ai-stocks:page-settings:${pageKey}`, JSON.stringify(next))
}

/**
 * 一次性兼容旧版页面偏好中的 charts 字段：先迁入 page+slot 的用户组件配置，
 * 确认组件配置已保存后再删除旧字段。已有组件用户配置始终优先，避免回迁覆盖新值。
 */
export function useLegacyStockChartPreferenceMigration(
  access: LegacyStockChartPreferenceMigrationAccess,
): void {
  onMounted(async () => {
    // 兼容只实现最小布局访问器的嵌入壳/页面测试；生产 useRemoteLayoutConfig 会提供完整接口。
    if (
      typeof access.whenRemoteHydrated !== 'function'
      || typeof access.componentSourceOf !== 'function'
      || typeof access.setComponentKnob !== 'function'
    ) return
    const slotId = access.slotId ?? 'chart'
    const localRecord = readLocalRecord(access.pageKey)

    await access.whenRemoteHydrated()
    if (access.componentSourceOf(slotId, 'stockChart') === 'user') {
      removeLocalLegacyField(access.pageKey, localRecord)
      return
    }

    let remoteRecord: UserPreferenceRecord | undefined

    if (getAccessToken()) {
      try {
        const response = await listUserPreferences({
          scope: 'page',
          pageKey: access.pageKey,
          prefKey: 'settings',
        })
        remoteRecord = response.items[0]
      } catch {
        // 远端不可用时保留远端旧字段；本地来源仍可迁移，后续会由布局同步补齐。
      }
    }

    const remoteValue = asRecord(remoteRecord?.value)
    const legacyCharts = remoteValue?.charts ?? localRecord?.charts
    let componentReady = false

    if (!componentReady && legacyCharts !== undefined) {
      access.setComponentKnob(slotId, 'stockChart', normalizeStockChartPreferences(legacyCharts))
      if (typeof access.saveRemoteUserConfig === 'function') await access.saveRemoteUserConfig()
      componentReady = !getAccessToken()
        || typeof access.remoteSaveFailed !== 'function'
        || !access.remoteSaveFailed()
    }

    if (!componentReady) return
    removeLocalLegacyField(access.pageKey, localRecord)

    if (remoteRecord && remoteValue && Object.prototype.hasOwnProperty.call(remoteValue, 'charts')) {
      const next = { ...remoteValue }
      delete next.charts
      try {
        await saveUserPreference({
          scope: 'page',
          pageKey: access.pageKey,
          prefKey: 'settings',
          value: next,
          schemaVersion: remoteRecord.schemaVersion,
        })
      } catch {
        // 组件配置已经生效；仅保留无害的旧字段，待下次迁移重试清理。
      }
    }
  })
}
