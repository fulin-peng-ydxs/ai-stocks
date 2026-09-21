import { onMounted, type Ref } from 'vue'
import { getAccessToken } from '@/api/authToken'
import {
  listUserPreferences,
  saveUserPreference,
  type UserPreferenceRecord,
} from '@/api/userPreferences'
import { normalizeStockChartPreferences } from '@/composables/useStockChartPreferences'
import { normalizeStockAnalysisPreferences } from '@/composables/useStockAnalysisSession'
import { normalizeSectorAnalysisPreferences } from '@/composables/useSectorAnalysisPreferences'

const LEGACY_STOCK_ANALYSIS_FIELDS = [
  'defaultChartMode',
  'showAnalysisPanel',
  'compareRange',
  'benchmarkCode',
  'compareMetrics',
  'defaultCompareMetric',
] as const

const LEGACY_SECTOR_ANALYSIS_FIELDS = [
  'defaultChartMode',
  'showAnalysisPanel',
  'benchmarkCode',
  'compareMetrics',
  'defaultCompareMetric',
  'compareWindow',
] as const

interface LegacyPageSettingsMigrationAccess {
  pageKey: string
  slotId?: string
  analysisType?: 'stock' | 'sector' | 'none'
  componentSourceOf: (slotId: string, field: string) => unknown
  setComponentKnob: (slotId: string, field: string, value: unknown) => void
  sourceOf?: (path: string) => unknown
  setKnob?: (path: string, value: unknown) => void
  whenRemoteHydrated: () => Promise<void>
  whenPageSettingsHydrated?: () => Promise<void>
  legacySnapshot?: Ref<unknown>
  savePageSettings?: () => Promise<void>
  saveRemoteUserConfig: () => Promise<boolean | void>
  remoteSaveFailed: () => boolean
  legacyComponentMappings?: Array<{
    legacyField: string
    slotId: string
    componentField: string
    transform?: (value: unknown) => unknown
  }>
  legacyLayoutMappings?: Array<{
    legacyField: string
    path: string
    transform?: (value: unknown) => unknown
  }>
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

function removeLocalLegacyFields(
  pageKey: string,
  record: Record<string, unknown> | undefined,
  fields: readonly string[],
): void {
  if (!record || !fields.some((field) => Object.prototype.hasOwnProperty.call(record, field))) return
  const next = { ...record }
  for (const field of fields) delete next[field]
  localStorage.setItem(`ai-stocks:page-settings:${pageKey}`, JSON.stringify(next))
}

function analysisFrom(
  record: Record<string, unknown>,
  fields: readonly string[],
): Record<string, unknown> | undefined {
  const entries = fields
    .filter((field) => Object.prototype.hasOwnProperty.call(record, field))
    .map((field) => [field, record[field]])
  return entries.length ? Object.fromEntries(entries) : undefined
}

/**
 * 一次性兼容旧版页面偏好：结构属性迁入布局用户层，组件内部能力迁入 page+slot 组件配置，
 * 确认布局配置已保存后再删除旧字段。已有用户层配置始终优先，避免回迁覆盖新值。
 */
export function useLegacyPageSettingsMigration(
  access: LegacyPageSettingsMigrationAccess,
): void {
  onMounted(async () => {
    // 兼容只实现最小布局访问器的嵌入壳/页面测试；生产 useRemoteLayoutConfig 会提供完整接口。
    if (
      typeof access.whenRemoteHydrated !== 'function'
      || typeof access.componentSourceOf !== 'function'
      || typeof access.setComponentKnob !== 'function'
    ) return
    const slotId = access.slotId ?? 'chart'
    await Promise.all([
      access.whenRemoteHydrated(),
      access.whenPageSettingsHydrated?.() ?? Promise.resolve(),
    ])
    const snapshot = asRecord(access.legacySnapshot?.value)
    const localRecord = snapshot ?? readLocalRecord(access.pageKey)

    let remoteRecord: UserPreferenceRecord | undefined

    if (!snapshot && getAccessToken()) {
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
    const legacyValue = snapshot ?? remoteValue ?? localRecord
    if (!legacyValue) return
    const legacyCharts = legacyValue.charts
    const analysisType = access.analysisType ?? 'none'
    const analysisFields = analysisType === 'sector'
      ? LEGACY_SECTOR_ANALYSIS_FIELDS
      : analysisType === 'stock'
        ? LEGACY_STOCK_ANALYSIS_FIELDS
        : []
    const legacyAnalysis = analysisFrom(legacyValue, analysisFields)
    const componentAnalysisField = analysisType === 'sector' ? 'sectorAnalysis' : 'stockAnalysis'
    const migratedFields: string[] = []
    let changed = false

    for (const mapping of access.legacyLayoutMappings ?? []) {
      if (!Object.prototype.hasOwnProperty.call(legacyValue, mapping.legacyField)) continue
      migratedFields.push(mapping.legacyField)
      if (access.sourceOf?.(mapping.path) === 'user') continue
      if (typeof access.setKnob !== 'function') continue
      access.setKnob(
        mapping.path,
        mapping.transform
          ? mapping.transform(legacyValue[mapping.legacyField])
          : legacyValue[mapping.legacyField],
      )
      changed = true
    }

    for (const mapping of access.legacyComponentMappings ?? []) {
      if (!Object.prototype.hasOwnProperty.call(legacyValue, mapping.legacyField)) continue
      migratedFields.push(mapping.legacyField)
      if (access.componentSourceOf(mapping.slotId, mapping.componentField) === 'user') continue
      access.setComponentKnob(
        mapping.slotId,
        mapping.componentField,
        mapping.transform
          ? mapping.transform(legacyValue[mapping.legacyField])
          : legacyValue[mapping.legacyField],
      )
      changed = true
    }

    if (legacyCharts !== undefined) {
      migratedFields.push('charts')
    }
    if (legacyCharts !== undefined && access.componentSourceOf(slotId, 'stockChart') !== 'user') {
      access.setComponentKnob(slotId, 'stockChart', normalizeStockChartPreferences(legacyCharts))
      changed = true
    }
    if (legacyAnalysis) {
      migratedFields.push(...analysisFields.filter((field) => (
        Object.prototype.hasOwnProperty.call(legacyValue, field)
      )))
      if (access.componentSourceOf(slotId, componentAnalysisField) !== 'user') {
        access.setComponentKnob(
          slotId,
          componentAnalysisField,
          analysisType === 'sector'
            ? normalizeSectorAnalysisPreferences(legacyAnalysis)
            : normalizeStockAnalysisPreferences(legacyAnalysis),
        )
        changed = true
      }
    }

    if (!migratedFields.length) return
    if (changed && typeof access.saveRemoteUserConfig === 'function') {
      await access.saveRemoteUserConfig()
    }
    const componentReady = !changed
      || !getAccessToken()
      || typeof access.remoteSaveFailed !== 'function'
      || !access.remoteSaveFailed()
    if (!componentReady) return
    // 页面偏好在 hydration 时会按新 schema 规范化；清理必须基于此刻的最新值，
    // 不能把迁移前快照写回去覆盖用户刚刚修改的仍有效字段。
    removeLocalLegacyFields(access.pageKey, readLocalRecord(access.pageKey), migratedFields)

    // usePageSettings 在这几页延迟清理未知字段；只有组件配置已安全落库后，
    // 才显式保存当前页面 schema，从 PG 删除旧字段。
    if (access.savePageSettings && getAccessToken()) {
      await access.savePageSettings()
      return
    }

    if (remoteRecord && remoteValue) {
      const next = { ...remoteValue }
      for (const field of migratedFields) delete next[field]
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

/** 行情页面保留原入口；通用旧页面偏好迁移与其它页面共用同一实现。 */
export const useLegacyStockChartPreferenceMigration = useLegacyPageSettingsMigration
