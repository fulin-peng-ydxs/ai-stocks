<script setup lang="ts">
import { enumText } from '@/utils/displayText'
import { ArrowRight } from '@element-plus/icons-vue'
import AppScrollArea from '@/components/AppScrollArea.vue'
import AppAdvancedSearch from '@/components/AppAdvancedSearch.vue'
import { useMenuPageTitle } from '@/composables/useMenuPageTitle'
import AppTableColumn from '@/components/AppTableColumn.vue'
import AppHoverInfo from '@/components/AppHoverInfo'
import DataMetricCard from '@/components/data/DataMetricCard.vue'
import DataMetricDetails from '@/components/data/DataMetricDetails.vue'
import { overviewMetrics, intradayCoverageText, type OverviewAction } from './overviewMetrics'
import AppDataTable from '@/components/AppDataTable.vue'
import AppDetailField from '@/components/AppDetailField.vue'
import AppDetailFields from '@/components/AppDetailFields.vue'
import AppFilterSelect from '@/components/AppFilterSelect.vue'
import AppPagination from '@/components/AppPagination.vue'
import AppSearchInput from '@/components/AppSearchInput.vue'
import AppStatusNotice from '@/components/AppStatusNotice.vue'
import StockCodeMultiSelect from '@/components/data/StockCodeMultiSelect.vue'
import { onMounted, ref, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  getOverview, getCatalog, getDimensions, getStockQuality, LAYER_DESC, LAYER_ISSUE_SUMMARY,
  BOARD_ISSUE_ITEMS, ISSUE_TYPE_LABEL, ISSUE_LAYER, type Overview, type QualityLayer, type CatalogTable,
  type CatalogDatabaseSummary, type Dimension, type StockQuality,
} from '@/api/data'
import AppStateBlock from '@/components/AppStateBlock.vue'
import AppTabToolbar from '@/components/AppTabToolbar.vue'
import HelpHint from '@/components/HelpHint.vue'
import HelpTip from '@/components/HelpTip.vue'
import HelpTipItem from '@/components/HelpTipItem.vue'
import PageSegmented from '@/components/PageSegmented.vue'
import PageSettingSection from '@/components/PageSettingSection.vue'
import PageSettingItem from '@/components/PageSettingItem.vue'
import PageSettingsDrawer from '@/components/PageSettingsDrawer.vue'
import PageSettingsTrigger from '@/components/PageSettingsTrigger.vue'
import { usePageSettings } from '@/composables/usePageSettings'
import { useLegacyPageSettingsMigration } from '@/composables/useLegacyStockChartPreferenceMigration'
import { useDefaultedSessionValue } from '@/composables/useDefaultedSessionValue'
import { DEFAULT_PAGE_SIZE, PAGE_SIZE_OPTIONS } from '@/constants/pagination'
import LayoutHost from '@/layout/components/LayoutHost.vue'
import { getPageLayout } from '@/layout'
import { useRemoteLayoutConfig } from '@/composables/useRemoteLayoutConfig'
import { useComponentPageSizeSession } from '@/composables/useComponentPageSizeSession'
import { getErrorMessage } from '@/utils/error'
import { formatDateTimeSeconds } from '@/utils/dateTime'

const router = useRouter()
const settingsOpen = ref(false)
const overviewDefaults = {
  focusLayer: 'all' as 'all' | 'L12' | 'L34',
}
const {
  settings, isDirty, reset, save: savePageSettings,
  whenHydrated: whenPageSettingsHydrated, legacySnapshot,
} = usePageSettings('data-overview', overviewDefaults, { deferUnknownFieldCleanup: true })

// 布局声明统一取自 pageRegistry（单一事实源），不再页面内联手写 PageLayout。
const overviewLayout = getPageLayout('data-overview')
const defaultKpiItems = (
  overviewLayout.slots.find((slot) => slot.id === 'summary')?.config?.visibleItems as string[] | undefined
) ?? []
const validKpiItems = new Set(defaultKpiItems)
const {
  effective: overviewEffective,
  knobs: layoutKnobs,
  setKnob,
  valueOf,
  sourceOf,
  isDirty: layoutDirty,
  resetAll: resetLayout,
  componentValueOf,
  setComponentKnob,
  componentSourceOf,
  layerValuesOf,
  componentLayerValuesOf, componentAllowedLayers,
  whenRemoteHydrated, saveRemoteUserConfig, remoteSaveError,
} = useRemoteLayoutConfig(overviewLayout)

// 抽屉「布局 / 组件设置」由 PageSettingsDrawer 自动渲染；tabs 与表格字段按 registry 实例元数据继承。
const drawerConfig = { knobs: layoutKnobs, valueOf, sourceOf, setKnob, componentValueOf, setComponentKnob, componentSourceOf, layerValuesOf, componentLayerValuesOf, componentAllowedLayers, save: saveRemoteUserConfig }
useLegacyPageSettingsMigration({
  pageKey: 'data-overview',
  componentSourceOf, setComponentKnob, whenRemoteHydrated,
  whenPageSettingsHydrated, legacySnapshot, savePageSettings,
  saveRemoteUserConfig, remoteSaveFailed: () => remoteSaveError.value,
  legacyComponentMappings: [{
    legacyField: 'kpi',
    slotId: 'summary',
    componentField: 'visibleItems',
    transform: (value) => {
      if (!value || typeof value !== 'object' || Array.isArray(value)) return defaultKpiItems
      return Object.entries(value as Record<string, unknown>)
        .filter(([key, visible]) => validKpiItems.has(key) && visible !== false)
        .map(([key]) => key)
    },
  }],
})
// 工作区 tab 单向：组件配置层默认值（workspace.defaultActive）→ 会话 ref；切换不写回配置层。
const workspaceTabDefault = computed<'assets' | 'stocks' | 'board'>(() =>
  (componentValueOf('workspace', 'defaultActive') as 'assets' | 'stocks' | 'board') || 'assets',
)
const activeWorkspaceTab = useDefaultedSessionValue(workspaceTabDefault)
const visibleKpiItems = computed(() => new Set(
  (componentValueOf('summary', 'visibleItems') as string[] | undefined) ?? defaultKpiItems,
))
function kpiVisible(key: string): boolean {
  return visibleKpiItems.value.has(key)
}
function tableBorder(slotId: string): boolean {
  return componentValueOf(slotId, 'border') === true
}
const loading = ref(true)
const error = ref('')
const ov = ref<Overview | null>(null)
const tables = ref<CatalogTable[]>([])
const dims = ref<Dimension[]>([])
const catalogSummary = ref<Partial<Record<'duckdb' | 'postgres', CatalogDatabaseSummary>>>({})
const catalogLoading = ref(false)
const catalogError = ref('')

// 逐股质量
const sq = ref<StockQuality | null>(null)
const sqLoading = ref(true)
const sqError = ref('')
const sqSelected = ref<string[]>([])
const sqPage = ref(1)
const { pageSize: sqSize, changePageSize: changeSqSize } = useComponentPageSizeSession({
  resolveDefault: () => componentValueOf('stockTable', 'pageSize'),
  fallback: DEFAULT_PAGE_SIZE,
  shouldSync: () => sq.value != null,
  resetPage: () => { sqPage.value = 1 },
  reload: () => loadSq(),
})

const DIM_STATUS: Record<string, { label: string; type: 'success' | 'info' | 'warning' }> = {
  collected: { label: '已采集', type: 'success' },
  partial: { label: '部分覆盖', type: 'warning' },
  planned: { label: '规划中', type: 'info' },
}

type AssetMode = 'all' | 'duckdb' | 'postgres' | 'planned'
const assetMode = ref<AssetMode>('all')
const assetKeyword = ref('')
const assetCategory = ref('')
const showLegacyAssets = ref(false)
const exactLoading = ref<Record<string, boolean>>({})
const exactErrors = ref<Record<string, string>>({})

const assetHiddenColumns = computed<string[]>(() =>
  (componentValueOf('assetTable', 'hiddenColumns') as string[]) ?? [],
)
function assetColumnVisible(key: string): boolean {
  return !assetHiddenColumns.value.includes(key)
}

// 物理表目录与规划维度分场景展示；维度注册仍负责补充 DuckDB 采集来源。
const enrichedTables = computed(() => {
  const dimByTable: Record<string, Dimension> = {}
  for (const d of dims.value) for (const t of d.tables) dimByTable[t] = d
  return tables.value.map((t) => {
    const d = dimByTable[t.table]
    return { ...t, data_source: t.data_source === '—' ? d?.source ?? '—' : t.data_source }
  })
})

const plannedAssets = computed(() => dims.value.filter((d) =>
  d.status === 'planned'
  && d.tables.every((table) => !tables.value.some((item) => item.table === table)),
))

const activeAssetCount = computed(() =>
  (catalogSummary.value.duckdb?.active_tables ?? 0)
  + (catalogSummary.value.postgres?.active_tables ?? 0),
)
const assetModeOptions = computed(() => [
  { label: `全部 ${activeAssetCount.value}`, value: 'all' },
  { label: `DuckDB ${catalogSummary.value.duckdb?.active_tables ?? 0}`, value: 'duckdb' },
  { label: `PG ${catalogSummary.value.postgres?.active_tables ?? 0}`, value: 'postgres' },
  { label: `规划中 ${plannedAssets.value.length}`, value: 'planned' },
])

const categoryOptions = computed(() => {
  const values = assetMode.value === 'planned'
    ? plannedAssets.value.map((item) => item.status)
    : enrichedTables.value
      .filter((item) => assetMode.value === 'all' || item.database === assetMode.value)
      .map((item) => item.category)
  return [...new Set(values)].sort().map((value) => ({
    value,
    label: assetMode.value === 'planned' ? DIM_STATUS[value]?.label ?? '状态未识别' : value,
  }))
})

const displayedAssets = computed(() => {
  const keyword = assetKeyword.value.trim().toLowerCase()
  if (assetMode.value === 'planned') {
    return plannedAssets.value.filter((item) => {
      if (assetCategory.value && item.status !== assetCategory.value) return false
      return !keyword
        || `${item.name_cn} ${item.dimension} ${item.descr} ${item.source}`.toLowerCase().includes(keyword)
    })
  }
  return enrichedTables.value.filter((item) => {
    if (assetMode.value !== 'all' && item.database !== assetMode.value) return false
    if (!showLegacyAssets.value && item.lifecycle === 'legacy_readonly') return false
    if (assetCategory.value && item.category !== assetCategory.value) return false
    return !keyword
      || `${item.name_cn} ${item.table} ${item.category} ${item.purpose}`.toLowerCase().includes(keyword)
  })
})

const hasAssetFilters = computed(() => (
  assetMode.value !== 'all'
  || assetCategory.value !== ''
  || assetKeyword.value.trim() !== ''
  || showLegacyAssets.value
))

watch(assetMode, () => { assetCategory.value = '' })

async function loadCatalog(includeLegacy = showLegacyAssets.value) {
  catalogLoading.value = true
  catalogError.value = ''
  try {
    const response = await getCatalog({ database: 'all', include_legacy: includeLegacy })
    tables.value = response.tables
    catalogSummary.value = response.summary
    return true
  } catch (e) {
    catalogError.value = getErrorMessage(e, '数据资产目录加载失败')
    return false
  } finally {
    catalogLoading.value = false
  }
}

async function toggleLegacyAssets(value: boolean) {
  const previous = showLegacyAssets.value
  showLegacyAssets.value = value
  if (!await loadCatalog(value)) showLegacyAssets.value = previous
}

async function resetAssetFilters() {
  if (!hasAssetFilters.value) return
  // 旧表开关改变目录请求范围；先确保默认目录加载成功，失败时完整保留当前筛选态。
  if (showLegacyAssets.value && !await loadCatalog(false)) return
  assetMode.value = 'all'
  assetCategory.value = ''
  assetKeyword.value = ''
  showLegacyAssets.value = false
}

async function loadExactCount(row: CatalogTable) {
  exactLoading.value = { ...exactLoading.value, [row.key]: true }
  const nextErrors = { ...exactErrors.value }
  delete nextErrors[row.key]
  exactErrors.value = nextErrors
  try {
    const response = await getCatalog({
      database: row.database,
      include_legacy: row.lifecycle === 'legacy_readonly',
      table: row.table,
      count_mode: 'exact',
    })
    const exact = response.tables[0]
    if (!exact) throw new Error('精确统计未返回目标表')
    tables.value = tables.value.map((item) => item.key === exact.key ? exact : item)
  } catch (e) {
    exactErrors.value = { ...exactErrors.value, [row.key]: getErrorMessage(e, '精确统计失败') }
  } finally {
    exactLoading.value = { ...exactLoading.value, [row.key]: false }
  }
}

function formatRowCount(row: CatalogTable): string {
  if (row.row_count == null) return '—'
  const value = row.row_count.toLocaleString('zh-CN')
  return row.row_count_mode === 'estimated' ? `约 ${value}` : value
}

function formatBytes(value: number | null): string {
  if (value == null) return '—'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let size = value
  let index = 0
  while (size >= 1024 && index < units.length - 1) { size /= 1024; index += 1 }
  return `${size.toLocaleString('zh-CN', { maximumFractionDigits: index === 0 ? 0 : 1 })} ${units[index]}`
}

const DB_LABEL = { duckdb: 'DuckDB', postgres: 'PostgreSQL' } as const
function databaseLabel(value: string): string {
  return DB_LABEL[value as keyof typeof DB_LABEL] ?? value
}
const SCOPE_LABEL: Record<string, string> = {
  market_global: '全市场共享',
  platform_global: '平台全局',
  tenant_user: '租户 + 用户',
  user: '单用户',
  runtime_global: '运行态全局',
}
const LIFECYCLE_LABEL: Record<string, string> = {
  active: '当前事实',
  legacy_readonly: '迁移旧表',
  unregistered: '待登记',
}
const METADATA_SOURCE_LABEL: Record<string, string> = {
  explicit: '表级注解',
  database_comment: '数据库注释',
  glossary: '公共词典',
  generated: '命名规则生成',
  fallback: '待补充',
}

function freshnessPolicyLabel(row: CatalogTable): string {
  const policy = row.freshness_policy
  if (!policy || policy.mode === 'not_applicable') return '不适用'
  if (policy.mode === 'snapshot_child') return '关联有效快照业务日'
  const comparison = policy.comparison === 'not_before' ? '不早于' : '等于'
  return `${policy.column || '业务日'} ${comparison} 全局最新交易日`
}

function qualityPolicyLabel(row: CatalogTable): string {
  const policy = row.quality_policy
  if (!policy || policy.mode === 'not_applicable') return '未纳入表级质检'
  if (policy.mode === 'all_issues') return '全部未解决质量问题'
  if (policy.mode === 'pending_outbox') return '待投递事件数'
  return `${policy.issue_types.length} 类质量规则`
}

function fieldMetadataSource(field: CatalogTable['fields'][number]): string {
  const name = METADATA_SOURCE_LABEL[field.name_source] ?? field.name_source
  const description = METADATA_SOURCE_LABEL[field.description_source]
    ?? field.description_source
  return `中文名：${name}；说明：${description}`
}

function formatQualityIssues(row: CatalogTable): string {
  if (row.open_issues == null) return '—'
  return row.open_issues > 0 ? `${row.open_issues} 待处理` : '0'
}

// 表级质量徽章：纳入鲜活度（最新时间空/滞后 → 不再误判"正常"）。
function tableFreshness(row: CatalogTable): { type: string; text: string } {
  if (row.lifecycle === 'legacy_readonly') return { type: 'info', text: '只读旧表' }
  if (row.fresh === false) return { type: 'danger', text: row.latest_time ? '数据滞后' : '无数据' }
  if (row.fresh == null) return { type: 'info', text: '不适用' }
  return { type: 'success', text: '鲜活' }
}

const metrics = computed(() => overviewMetrics(ov.value).filter((item) => kpiVisible(item.key)))

// 卡片外壳只展示，所有导航均由具名入口触发；页内定位与台账处理不混用。
function metricAction(action?: OverviewAction) {
  if (action === 'stocks') activeWorkspaceTab.value = 'stocks'
  else if (action === 'gaps') gotoQuality(undefined, 'history_data_gap,stale')
  else if (action === 'intraday-ingest') router.push({ path: '/data/ingest', query: { task_type: 'intraday_ingest' } })
  else if (action === 'st-refresh') gotoStRefresh()
  else if (action === 'board') activeWorkspaceTab.value = 'board'
  else if (action === 'quality') gotoQuality()
}
const intradayIssueTypes = 'intraday_gap,intraday_partial,intraday_invalid'
function gotoStockIntraday(code: string) {
  router.push({ path: '/data/quality', query: { code, issue_type: intradayIssueTypes } })
}

// 逐股四层列（DM-D15）：每列即一层，hover 出具体结果，点击进对应解决页。
// 列头短名（去掉 "Lx " 前缀）；层定义说明统一引用 data.ts 的权威 LAYER_DESC（单一出处）
const LAYER_CN: Record<string, string> = {
  L1: '入库闸门', L2: '字段契约', L3: '正确性', L4: '覆盖鲜活',
}
function layerCell(k: string, lay: any): { type: string; text: string; tip: string } {
  if (!lay) return { type: 'info', text: '—', tip: '' }
  if (lay.ok) {
    return { type: 'success', text: '达标', tip: `当前未发现问题。${LAYER_DESC[k] || ''}` }
  }
  const breakdown = (lay.breakdown || [])
    .map((item: { issue_type: string; count: number }) =>
      `${enumText(ISSUE_TYPE_LABEL, item.issue_type, '未识别问题类型')} ${item.count} 项`)
  if (k === 'L1') return {
    type: 'danger',
    text: `${lay.issues} 问题`,
    tip: `${breakdown.join(' · ') || `入库闸门有 ${lay.issues} 项待处理问题`} 查看台账可定位对应问题`,
  }
  if (k === 'L2') {
    const hasMissing = Boolean(lay.mv_detail)
    const hasInvalid = Number(lay.mv_invalid_days || 0) > 0
    const parts: string[] = []
    if (lay.capital_detail) parts.push(lay.capital_detail)
    if (hasMissing) parts.push(lay.mv_detail)
    if (hasInvalid) {
      const range = lay.mv_invalid_lo
        ? `（${lay.mv_invalid_lo}~${lay.mv_invalid_hi || lay.mv_invalid_lo}）`
        : ''
      parts.push(`市值数值异常：${lay.mv_invalid_detail || `${lay.mv_invalid_days} 天不符合字段契约`}${range}`)
    }
    const text = lay.capital_issues || (hasMissing && hasInvalid) ? '不达标' : hasInvalid ? '异常' : '缺'
    return {
      type: 'danger',
      text,
      tip: `${parts.join(' · ') || '市值字段契约不达标'} 查看台账可定位对应问题`,
    }
  }
  if (k === 'L3') return {
    type: 'danger',
    text: `${lay.issues} 问题`,
    tip: `${breakdown.join(' · ') || `正确性有 ${lay.issues} 项待处理问题`} 查看台账可定位对应问题`,
  }
  // L4
  const parts: string[] = []
  if (lay.history_gap_days) parts.push(`全历史缺口 ${lay.history_gap_days} 个交易日（含近端）`)
  if (lay.gap_days) parts.push(`缺口 ${lay.gap_days} 个交易日${lay.gap_lo ? `（${lay.gap_lo}~${lay.gap_hi}）` : ''}`)
  if (lay.stale_days) parts.push(`滞后 ${lay.stale_days} 个交易日`)
  return { type: 'danger', text: '不达标', tip: (parts.join(' · ') || '覆盖/鲜活不达标') + ' 查看台账定位历史缺口和滞后；台账由质检任务更新' }
}
function layerSummaryText(layer: QualityLayer): string {
  return LAYER_ISSUE_SUMMARY[layer.layer]?.(layer.issues) ?? `${layer.issues} 项`
}
function layerDetails(layer: QualityLayer) {
  return [
    { label: '达标股票', value: `${layer.pass_stocks.toLocaleString()} / ${layer.total.toLocaleString()} 只` },
    { label: '未达标股票', value: `${Math.max(layer.total - layer.pass_stocks, 0).toLocaleString()} 只` },
    { label: '问题统计', value: layerSummaryText(layer) },
  ]
}
function shouldShowLayer(k: string): boolean {
  if (settings.focusLayer === 'L12') return k === 'L1' || k === 'L2'
  if (settings.focusLayer === 'L34') return k === 'L3' || k === 'L4'
  return true
}
function goLayer(k: string, row: any) {
  const lay = row.layers[k]
  if (!lay || lay.ok) return
  // 覆盖帧是实时检查，台账由扫描更新；明确查看台账，不暗中切到采集参数页。
  const types = k === 'L4'
    ? ['history_data_gap', 'stale']
    : k === 'L2' ? ['capital_gap', 'capital_invalid', 'capital_mismatch', 'mv_missing', 'mv_invalid']
      : lay.breakdown?.length
        ? lay.breakdown.map((item: { issue_type: string }) => item.issue_type)
        : Object.keys(ISSUE_LAYER).filter((type) => ISSUE_LAYER[type] === k)
  router.push({ path: '/data/quality', query: { code: row.code, ...(types.length ? { issue_type: types.join(',') } : {}) } })
}

function gotoStRefresh() {
  router.push({ path: '/data/ingest', query: { task_type: 'stock_ingest', recipe: 'st_status_refresh' } })
}
async function load() {
  loading.value = true
  error.value = ''
  try {
    const [o, c, d] = await Promise.all([
      getOverview(),
      getCatalog({ database: 'all', include_legacy: false }),
      getDimensions(),
    ])
    ov.value = o
    tables.value = c.tables
    catalogSummary.value = c.summary
    dims.value = d.dimensions
    await loadSq()
  } catch (e) {
    error.value = getErrorMessage(e, '数据概览加载失败')
  } finally {
    loading.value = false
  }
}

async function loadSq() {
  sqLoading.value = true
  sqError.value = ''
  try {
    sq.value = await getStockQuality({
      codes: sqSelected.value.length ? sqSelected.value.join(',') : undefined,
      page: sqPage.value, size: sqSize.value,
    })
  } catch (error) {
    sqError.value = getErrorMessage(error, '逐股质量加载失败')
  } finally {
    sqLoading.value = false
  }
}
function onSqSelect() { sqPage.value = 1; loadSq() }

function gotoQuality(severity?: string, issueType?: string) {
  const q: Record<string, string> = {}
  if (severity) q.severity = severity
  if (issueType) q.issue_type = issueType
  router.push(Object.keys(q).length ? { path: '/data/quality', query: q } : '/data/quality')
}
function gotoBoard() {
  router.push({ path: '/data/ingest', query: { task_type: 'board', mode: 'update' } })
}
const boardCoverageItems = computed(() => {
  const board = ov.value?.board
  return [
    {
      key: 'member',
      label: '成分覆盖',
      desc: '板块字典已匹配成分股的覆盖进度',
      ready: board?.member_ready,
      target: board?.member_target,
    },
    {
      key: 'bar',
      label: '指数覆盖',
      desc: '板块指数行情可用于趋势对照的覆盖进度',
      ready: board?.bar_ready,
      target: board?.bar_target,
    },
    {
      key: 'fund',
      label: '资金流覆盖',
      desc: '资金流快照可用于板块热度跟踪的覆盖进度',
      ready: board?.fund_ready,
      target: board?.fund_target,
    },
  ].map((item) => {
    const key = item.key as 'member' | 'bar' | 'fund'
    const missing = Math.max((item.target ?? 0) - (item.ready ?? 0), 0)
    const ignored = Math.min(missing, Math.max(board?.coverage_handling?.[key]?.ignored ?? 0, 0))
    const pending = missing - ignored
    const confirmed = ignored > 0 && pending === 0
    return {
      ...item, ignored, pending, confirmed,
      pct: coveragePct(item.ready, item.target),
      status: confirmed ? undefined : coverageStatus(item.ready, item.target),
    }
  })
})
// 真实覆盖率不因人工确认而增加；补采状态只统计尚未确认的实际缺失。
const boardCoverageState = computed(() => {
  const items = boardCoverageItems.value
  if (items.some((item) => item.pending > 0)) return { label: '待补采', type: 'warning' as const }
  if ((ov.value?.board?.open_issues ?? 0) > 0) return { label: '待处理', type: 'warning' as const }
  if (items.some((item) => item.ignored > 0)) return { label: '缺失已人工确认', type: 'info' as const }
  if (!items.some((item) => item.target)) return { label: '尚无覆盖目标', type: 'info' as const }
  return { label: '已完成', type: 'success' as const }
})
const boardOverallCoverage = computed(() => {
  const totals = boardCoverageItems.value.reduce((acc, item) => ({
    ready: acc.ready + (item.ready ?? 0),
    target: acc.target + (item.target ?? 0),
  }), { ready: 0, target: 0 })
  return coveragePct(totals.ready, totals.target)
})
const boardIssueItems = computed(() => {
  const issues = ov.value?.board?.issues_by_type ?? {}
  const known = BOARD_ISSUE_ITEMS
    .map((item) => ({ ...item, count: issues[item.key] ?? 0 }))
    .filter((item) => item.count > 0)
  const knownKeys = new Set<string>(BOARD_ISSUE_ITEMS.map((item) => item.key))
  // 未登记展示名的类型也保留真实筛选键，不能把“其他板块问题”跳成全系统台账。
  const other = Object.entries(issues).filter(([key, count]) => count > 0 && !knownKeys.has(key))
    .map(([key, count]) => ({ key, count, label: enumText(ISSUE_TYPE_LABEL, key, '未识别问题类型'), hint: ISSUE_TYPE_LABEL[key] ? '前往对应质量台账查看' : '问题类型尚未登记' }))
  return [...known, ...other]
})
const boardFreshnessItems = computed(() => {
  const board = ov.value?.board
  const latest = ov.value?.latest_trade_date || ''
  return [
    { key: 'trade', label: '最新交易日', value: ov.value?.latest_trade_date, stale: false, confirmed: false, status: '基准' },
    {
      key: 'bar', label: '板块指数', value: board?.latest_bar_date,
      ...coverageFreshness(board?.latest_bar_date, latest, board?.bar_ready, board?.bar_target,
        boardCoverageItems.value.find((item) => item.key === 'bar')?.confirmed),
    },
    {
      key: 'fund', label: '资金流快照', value: board?.latest_fund_date,
      ...coverageFreshness(board?.latest_fund_date, latest, board?.fund_ready, board?.fund_target,
        boardCoverageItems.value.find((item) => item.key === 'fund')?.confirmed),
    },
  ]
})
function dateOnly(value?: string | null): string {
  return (value || '—').slice(0, 10)
}
function boardUpdateStatus(status?: string): { label: string; type: 'success' | 'danger' | 'warning' | 'info' } {
  if (status === 'success') return { label: '成功', type: 'success' }
  if (status === 'partial') return { label: '部分完成', type: 'warning' }
  if (status === 'checked') return { label: '已复查', type: 'success' }
  if (status === 'failed') return { label: '失败', type: 'danger' }
  if (status === 'running') return { label: '运行中', type: 'warning' }
  return { label: status ? '状态未识别' : '未记录', type: 'info' }
}
function coverageText(ready: number | undefined, total: number | undefined): string {
  return `${ready ?? 0}/${total ?? 0}`
}
function coveragePct(ready: number | undefined, total: number | undefined): number {
  if (!total) return 0
  return Math.round(((ready ?? 0) / total) * 1000) / 10
}
// 与分层质量模型同阈值的状态档：ready/total ≥ 99% 绿、≥ 90% 橙、其余红。
function coverageStatus(ready: number | undefined, total: number | undefined): 'success' | 'warning' | 'exception' {
  if (!total) return 'exception'
  const rate = (ready ?? 0) / total
  if (rate >= 0.99) return 'success'
  if (rate >= 0.9) return 'warning'
  return 'exception'
}
// 日期追平只代表至少一个板块有当日数据；完整覆盖后才能称为整体“同步”。
function coverageFreshness(
  value: string | null | undefined,
  latest: string,
  ready: number | undefined,
  target: number | undefined,
  confirmed = false,
): { stale: boolean; confirmed?: boolean; status: string } {
  if (confirmed) return { stale: false, confirmed: true, status: '缺失已人工确认' }
  if (!value) return { stale: true, status: '无数据' }
  if (!latest || value < latest) return { stale: true, status: '滞后' }
  if (!target || (ready ?? 0) < target) return { stale: true, status: '未齐' }
  return { stale: false, status: '同步' }
}

onMounted(load)
const menuPageTitle = useMenuPageTitle()
</script>

<template>
  <LayoutHost :component-value-of="componentValueOf" :layout="overviewEffective">
    <template #action>
    <div class="page-head">
      <div>
      <h2 class="app-page-title">
        {{ menuPageTitle }}
        <HelpTip title="数据概览看什么？" :width="420">
          <HelpTipItem question="页面提供什么">
            <ul>
              <li>展示核心 KPI、按数据维度归并的数据资产表、四层质量达标率和逐股分层体检。</li>
            </ul>
          </HelpTipItem>
          <HelpTipItem question="问题如何处理">
            <ul>
              <li>统计详情通过指标旁的信息入口查看；具名链接定位覆盖或质量台账，采集按钮进入任务参数页。</li>
            </ul>
          </HelpTipItem>
        </HelpTip>
      </h2>
      <p class="page-subtitle">查看数据规模、覆盖与质量；通过具名入口定位明细和处理问题。</p>
      </div>
      <div class="page-head-actions">
        <el-button :loading="loading" type="primary" @click="load">刷新</el-button>
        <PageSettingsTrigger :dirty="isDirty" @click="settingsOpen = true" />
      </div>
    </div>
    </template>

    <template #summary>
      <div v-if="!error" class="overview-summary" data-testid="overview-summary">
        <AppStateBlock
          v-if="loading && !ov"
          state="loading"
          title="正在加载数据概览…"
        />
        <AppScrollArea v-else class="metric-scroll" axis="x" aria-label="核心数据指标">
          <div class="stat-grid" data-testid="overview-kpi-grid" v-loading="loading && !!ov">
            <DataMetricCard
              v-for="metric in metrics" :key="metric.key"
              :data-testid="metric.testId"
              :label="metric.label" :value="metric.value" :unit="metric.unit"
              :summary="metric.summary" :tone="metric.tone"
              :info="metric.info" :action-label="metric.actionLabel"
              @action="metricAction(metric.action)"
            />
          </div>
        </AppScrollArea>
      </div>
    </template>

    <template #quality>
      <el-card
        v-if="!error && ov?.quality.by_layer?.length"
        shadow="never"
        class="quality-summary"
        data-testid="overview-quality-summary"
      >
          <template #header>
            <div class="quality-heading">
              <span>日线四层质量</span>
              <span class="hint">最近质检：{{ formatDateTimeSeconds(ov.last_scan_at, '尚未质检') }}
                <HelpHint label="最近质检时间说明" text="质量台账由立即质检或定时质检更新；逐股覆盖实时检查，可能与尚未刷新或已忽略的台账不同。" />
              </span>
            </div>
          </template>
          <div class="quality-layer-grid">
            <div v-for="l in ov.quality.by_layer" :key="l.layer" class="layer-card">
              <div class="layer-name">
                <span>{{ l.layer }} · {{ l.name_cn }}</span>
                <DataMetricDetails :label="`${l.layer} · ${l.name_cn}`" :rows="layerDetails(l)" :notes="[l.desc]" />
              </div>
              <template v-if="l.total">
                <div class="layer-progress">
                  <el-progress :percentage="coveragePct(l.pass_stocks, l.total)" :show-text="false"
                    :status="l.pass_rate >= 0.99 ? 'success' : l.pass_rate >= 0.9 ? 'warning' : 'exception'" />
                  <span>{{ coveragePct(l.pass_stocks, l.total) }}%</span>
                </div>
                <div class="layer-foot">{{ l.pass_stocks.toLocaleString() }} / {{ l.total.toLocaleString() }} 只达标</div>
              </template>
              <span v-else class="hint">尚无可检查股票</span>
            </div>
          </div>
      </el-card>
    </template>

    <template #workspace>
      <AppStateBlock
        v-if="loading && !ov && !error"
        state="loading"
        title="正在加载数据工作区…"
      />
      <AppStateBlock
        v-else-if="error"
        state="error"
        :title="ov ? '数据概览刷新失败' : '数据概览加载失败'"
        :description="error"
        retry
        @retry="load"
      />
      <el-card
        v-else
        shadow="never"
        class="app-workspace-card overview-workspace-card"
        data-testid="overview-workspace"
      >
        <el-tabs v-model="activeWorkspaceTab" class="app-workspace-tabs overview-tabs">
          <el-tab-pane label="数据资产" name="assets">
            <div class="app-workspace-panel overview-panel">
              <AppTabToolbar label="数据资产操作栏" data-testid="overview-assets-toolbar">
                <template #actions><AppAdvancedSearch
                  group="assets"
                  :states="{
                    category: { value: assetCategory, options: categoryOptions, clear: () => assetCategory = '' },
                    legacy: { selfLabelled: true, value: showLegacyAssets, active: !showLegacyAssets, summary: !showLegacyAssets ? '不包含迁移旧表' : '', available: assetMode === 'all' || assetMode === 'duckdb', clear: () => toggleLegacyAssets(true) },
                    keyword: { value: assetKeyword, clear: () => assetKeyword = '' }
                  }"
                >
                  <template #context>
                    <PageSegmented
                      v-model="assetMode"
                      :options="assetModeOptions"
                      aria-label="数据资产数据库场景"
                      test-id="overview-asset-mode"
                      size="small"
                      tone="primary"
                    />
                  </template>
                  <template #category>
                    <AppFilterSelect
                      v-model="assetCategory"
                      class="asset-category"
                      :options="categoryOptions"
                      :multiple="false"
                      placeholder="业务分类"
                      aria-label="数据资产业务分类"
                      data-testid="overview-asset-category"
                    />
                  </template>
                  <template #legacy>
                    <label v-if="assetMode === 'all' || assetMode === 'duckdb'" class="asset-legacy-toggle">
                      <span>查看迁移旧表</span>
                      <el-switch
                        :model-value="showLegacyAssets"
                        :loading="catalogLoading"
                        data-testid="overview-asset-legacy"
                        @change="toggleLegacyAssets(Boolean($event))"
                      />
                    </label>
                  </template>
                  <template #keyword>
                    <AppSearchInput
                      v-model="assetKeyword"
                      class="asset-search"
                      placeholder="搜索中文名、表名或用途"
                      :debounce-ms="150"
                      data-testid="overview-asset-search"
                    />
                  </template>
                  <template #commands>
                    <el-button
                      :disabled="!hasAssetFilters"
                      data-testid="overview-asset-reset-filters"
                      @click="resetAssetFilters"
                    >
                      重置筛选
                    </el-button>
                  </template>
                </AppAdvancedSearch></template>
                <template #description>
                  {{ assetMode === 'planned'
                    ? '规划维度不参与物理表统计'
                    : `当前显示 ${displayedAssets.length} 张；展开可查看真实字段并按需精确统计` }}
                </template>
              </AppTabToolbar>

              <AppStatusNotice
                v-if="catalogError && tables.length"
                class="asset-local-error"
                title="目录切换失败，已保留原筛选结果"
                :description="catalogError"
                tone="error"
                size="compact"
                action-text="重试"
                @action="loadCatalog()"
              />

              <AppStateBlock
                v-if="catalogError && !tables.length"
                state="error"
                title="数据资产目录加载失败"
                :description="catalogError"
                retry
                @retry="loadCatalog()"
              />

              <AppDataTable
                v-else-if="assetMode === 'planned'"
                :data="displayedAssets"
                size="small"
                height="100%"
                aria-label="规划中数据资产表"
                data-testid="overview-planned-asset-table"
                :border="tableBorder('assetTable')"
                row-key="dimension"
              >
                <AppTableColumn label="维度" prop="name_cn" />
                <AppTableColumn label="状态" role="status">
                  <template #default="{ row }">
                    <el-tag :type="DIM_STATUS[row.status]?.type ?? 'info'" size="small" effect="plain">
                      {{ DIM_STATUS[row.status]?.label ?? '状态未识别' }}
                    </el-tag>
                  </template>
                </AppTableColumn>
                <AppTableColumn label="预期来源" prop="source" />
                <AppTableColumn label="说明" prop="descr" />
              </AppDataTable>

              <AppDataTable
                v-else
                :data="displayedAssets"
                size="small"
                height="100%"
                aria-label="数据资产表"
                data-testid="overview-asset-table"
                :border="tableBorder('assetTable')"
                :loading="loading || catalogLoading"
                row-key="key"
              >
                <AppTableColumn type="expand">
                  <template #default="{ row }">
                    <div class="expand">
                      <AppDetailFields :columns="2">
                        <AppDetailField label="用途" :value="row.purpose" />
                        <AppDetailField label="事实源" :value="databaseLabel(row.source_of_truth)" />
                        <AppDetailField label="生命周期" :value="LIFECYCLE_LABEL[row.lifecycle]" />
                        <AppDetailField label="关联关系" :value="row.relations?.join('；')" />
                        <AppDetailField label="鲜活度策略" :value="freshnessPolicyLabel(row)" />
                        <AppDetailField label="质量策略" :value="qualityPolicyLabel(row)" />
                      </AppDetailFields>
                      <AppStatusNotice
                        v-if="row.metadata_issues?.length"
                        class="asset-local-error"
                        title="业务元数据尚未完成登记"
                        :description="row.metadata_issues.join('；')"
                        tone="warning"
                        size="compact"
                      />
                      <div class="asset-count-action">
                        <el-button
                          size="small"
                          :loading="exactLoading[row.key]"
                          data-testid="overview-asset-exact-count"
                          @click="loadExactCount(row)"
                        >精确统计行数</el-button>
                        <div
                          v-if="(row.row_count_mode === 'exact' && row.measured_at) || exactErrors[row.key]"
                          class="asset-count-status"
                        >
                          <span v-if="row.row_count_mode === 'exact' && row.measured_at" class="hint">
                            统计于 {{ formatDateTimeSeconds(row.measured_at) }}
                          </span>
                          <span v-if="exactErrors[row.key]" class="asset-count-error" role="alert">
                            {{ exactErrors[row.key] }}；已保留原统计结果
                          </span>
                        </div>
                      </div>
                      <AppDataTable v-if="row.fields?.length" :data="row.fields" size="small" class="fld-tbl" embedded>
                        <AppTableColumn label="字段" prop="name" />
                        <AppTableColumn label="中文名" prop="name_cn" />
                        <AppTableColumn label="原生类型" prop="type" />
                        <AppTableColumn label="可空" role="status">
                          <template #default="scope">{{ scope.row.nullable ? '是' : '否' }}</template>
                        </AppTableColumn>
                        <AppTableColumn label="默认值">
                          <template #default="scope"><span class="mono">{{ scope.row.default ?? '—' }}</span></template>
                        </AppTableColumn>
                        <AppTableColumn label="主键" role="status">
                          <template #default="scope">{{ scope.row.primary_key ? '是' : '—' }}</template>
                        </AppTableColumn>
                        <AppTableColumn label="外键" prop="references" />
                        <AppTableColumn label="元数据来源">
                          <template #default="scope">{{ fieldMetadataSource(scope.row) }}</template>
                        </AppTableColumn>
                        <AppTableColumn label="说明" prop="desc" />
                      </AppDataTable>
                    </div>
                  </template>
                </AppTableColumn>
                <AppTableColumn v-if="assetMode === 'all' && assetColumnVisible('database')" label="数据库" role="status">
                  <template #default="{ row }">
                    <el-tag type="info" size="small" effect="plain">{{ databaseLabel(row.database) }}</el-tag>
                  </template>
                </AppTableColumn>
                <AppTableColumn v-if="assetColumnVisible('name')" label="中文名" prop="name_cn" />
                <AppTableColumn v-if="assetColumnVisible('table')" label="物理表" prop="table">
                  <template #default="{ row }"><span class="mono">{{ row.table }}</span></template>
                </AppTableColumn>
                <AppTableColumn v-if="assetColumnVisible('category')" label="业务分类" prop="category" />
                <AppTableColumn v-if="assetColumnVisible('lifecycle')" label="生命周期" role="status">
                  <template #default="{ row }">
                    <el-tag
                      :type="row.lifecycle === 'active' ? 'success' : row.lifecycle === 'unregistered' ? 'warning' : 'info'"
                      size="small"
                      effect="plain"
                    >
                      {{ LIFECYCLE_LABEL[row.lifecycle] }}
                    </el-tag>
                    <span v-if="row.lifecycle === 'legacy_readonly'" class="asset-fact-source">PG 事实源</span>
                  </template>
                </AppTableColumn>
                <AppTableColumn v-if="assetColumnVisible('rowCount')" label="行数" role="number">
                  <template #default="{ row }">{{ formatRowCount(row) }}</template>
                </AppTableColumn>

                <AppTableColumn
                  v-if="assetMode === 'duckdb' && assetColumnVisible('dataSource')"
                  label="数据源"
                  prop="data_source"
                />
                <AppTableColumn
                  v-if="assetMode === 'duckdb' && assetColumnVisible('latestTime')"
                  label="最新业务日"
                >
                  <template #default="{ row }">{{ formatDateTimeSeconds(row.latest_time) }}</template>
                </AppTableColumn>
                <AppTableColumn
                  v-if="assetMode === 'duckdb' && assetColumnVisible('freshness')"
                  label="鲜活度"
                  role="status"
                >
                  <template #header>
                    <span>鲜活度</span>
                    <HelpTip title="表级鲜活度怎么判定？" :width="440">
                      <HelpTipItem question="时序表如何判定">
                        <ul>
                          <li>日线行情、市值指标和指数的最新数据时间须不早于全局最新交易日才算鲜活；为空或滞后时显示「无数据 / 数据滞后」，表级鲜活度与质量问题分列显示，不能用最大业务日证明全市场覆盖完整。</li>
                        </ul>
                      </HelpTipItem>
                      <HelpTipItem question="基础与台账表如何判定">
                        <ul>
                          <li>基础与台账表不套用行情鲜活度。失效 outbox 单独展示最后更新时间和待处理数。</li>
                        </ul>
                      </HelpTipItem>
                      <HelpTipItem question="连板天梯如何判定">
                        <ul>
                          <li>快照子表通过有效 snapshot_id 关联主表取得最新业务日，鲜活度以最新有效状态和全局交易日比较。</li>
                        </ul>
                      </HelpTipItem>
                    </HelpTip>
                  </template>
                  <template #default="{ row }">
                    <el-tag :type="tableFreshness(row).type as any" size="small" effect="plain">{{ tableFreshness(row).text }}</el-tag>
                  </template>
                </AppTableColumn>
                <AppTableColumn
                  v-if="assetMode === 'duckdb' && assetColumnVisible('qualityIssues')"
                  label="质量问题"
                  role="number"
                >
                  <template #header>
                    <span>质量问题</span>
                    <HelpHint label="表级质量问题口径说明" text="0 表示已纳入质量规则且没有待处理问题；— 表示不适用或尚未纳入表级质检，不能解释为质量正常。" />
                  </template>
                  <template #default="{ row }">
                    <span :class="{ 'txt-warn': row.open_issues != null && row.open_issues > 0 }">
                      {{ formatQualityIssues(row) }}
                    </span>
                  </template>
                </AppTableColumn>

                <AppTableColumn
                  v-if="assetMode === 'postgres' && assetColumnVisible('ownershipScope')"
                  label="归属范围"
                >
                  <template #default="{ row }">{{ enumText(SCOPE_LABEL, row.ownership_scope, '归属待核验') }}</template>
                </AppTableColumn>
                <AppTableColumn
                  v-if="assetMode === 'postgres' && assetColumnVisible('storageBytes')"
                  label="表及索引空间"
                  role="number"
                >
                  <template #default="{ row }">{{ formatBytes(row.storage_bytes) }}</template>
                </AppTableColumn>
              </AppDataTable>
            </div>
          </el-tab-pane>

          <el-tab-pane label="逐股分层体检" name="stocks" lazy>
            <div class="app-workspace-panel overview-panel">
              <AppTabToolbar label="逐股分层体检操作栏" data-testid="overview-stocks-toolbar">
                <template #actions>
                  <StockCodeMultiSelect
                    v-model="sqSelected"
                    class="overview-stock-filter"
                    test-id="overview-stock-codes"
                    aria-label="逐股体检股票范围"
                    @change="onSqSelect"
                  />
                </template>
                <template #description>
                  异常入口查看对应台账 · 最新交易日 {{ (sq?.latest_trade_date || '—').slice(0, 10) }}
                </template>
              </AppTabToolbar>
              <AppStateBlock
                v-if="sqLoading && !sq"
                state="loading"
                title="正在加载逐股质量…"
              />
              <AppStateBlock
                v-else-if="sqError"
                state="error"
                :title="sq ? '逐股质量刷新失败' : '逐股质量加载失败'"
                :description="sqError"
                retry
                @retry="loadSq"
              />
              <template v-else>
                <AppDataTable
                  :data="sq?.list ?? []"
                  size="small"
                  height="100%"
                  aria-label="逐股分层体检表"
                  data-testid="overview-stock-table"
                  :border="tableBorder('stockTable')"
                  :loading="sqLoading"
                  row-key="code"
                >
                  <AppTableColumn label="代码" prop="code" />
                  <AppTableColumn label="名称" prop="name" />
                  <AppTableColumn label="最新数据">
                    <template #default="{ row }">{{ (row.latest_date || '—').slice(0, 10) }}</template>
                  </AppTableColumn>
                  <AppTableColumn label="分时覆盖" role="text" control-width="medium">
                    <template #default="{ row }">
                      <div v-if="row.intraday" class="stock-intraday-cell">
                        <el-button v-if="row.intraday.partial_days || row.intraday.missing_days" link type="primary" size="small"
                          :aria-label="`${row.code} 分时${intradayCoverageText(row.intraday)}，查看台账`"
                          @click="gotoStockIntraday(row.code)">{{ intradayCoverageText(row.intraday) }} · 查看台账</el-button>
                        <span v-else>{{ intradayCoverageText(row.intraday) }}</span>
                        <DataMetricDetails label="分时覆盖" :rows="[
                          { label: '完整归档', value: row.intraday.complete_days + ' 个股票交易日' },
                          { label: '部分覆盖', value: row.intraday.partial_days + ' 个股票交易日' },
                          { label: '整日缺失', value: row.intraday.missing_days + ' 个股票交易日' },
                          { label: '监控起点', value: dateOnly(row.intraday.monitoring_start) },
                          { label: '目标交易日', value: dateOnly(row.intraday.target_end) },
                          { label: '最新归档日', value: dateOnly(row.intraday.archive_end) },
                        ]" :notes="['覆盖数量单位为股票交易日；完整仅表示必需分钟已覆盖。缺失、部分和数据非法属于独立分时台账，不计入日线四层评分。']" />
                      </div>
                      <span v-else class="app-caption-text">未监控</span>
                    </template>
                  </AppTableColumn>
                  <AppTableColumn v-for="k in ['L1', 'L2', 'L3', 'L4'].filter(shouldShowLayer)" :key="k" :label="LAYER_CN[k]" role="status">
                    <template #header>
                      <span>{{ LAYER_CN[k] }} <HelpHint :text="LAYER_DESC[k]" :label="`${LAYER_CN[k]}口径说明`" /></span>
                    </template>
                    <template #default="{ row }">
                      <AppHoverInfo :content="layerCell(k, row.layers[k]).tip" placement="top">
                        <el-button v-if="row.layers[k] && !row.layers[k].ok" link type="danger" size="small"
                          :aria-label="`${row.code} ${LAYER_CN[k]}：${layerCell(k, row.layers[k]).text}，查看质量台账`" @click="goLayer(k, row)">
                          {{ layerCell(k, row.layers[k]).text }} · 查看台账
                        </el-button>
                        <el-tag v-else :type="layerCell(k, row.layers[k]).type as any" size="small" effect="plain">
                          {{ layerCell(k, row.layers[k]).text }}
                        </el-tag>
                      </AppHoverInfo>
                    </template>
                  </AppTableColumn>
                </AppDataTable>
                <div class="pager">
                  <AppPagination
                    :total="sq?.total ?? 0"
                    :current-page="sqPage"
                    :page-size="sqSize"
                    :page-sizes="PAGE_SIZE_OPTIONS"
                    @current-change="(p: number) => { sqPage = p; loadSq() }"
                    @size-change="changeSqSize"
                  />
                </div>
              </template>
            </div>
          </el-tab-pane>

          <el-tab-pane label="板块数据" name="board" lazy class="board-pane">
          <AppScrollArea class="board-pane-scroll">
            <div class="app-workspace-panel overview-panel" v-if="ov?.board">
              <div class="board-hero">
                <div class="board-hero-main">
                  <span class="board-eyebrow">同花顺板块源</span>
                  <div class="board-title-line">
                    <span class="board-total">{{ ov.board.board_dict }}</span>
                    <span class="board-title-text">个概念 / 行业板块</span>
                  </div>
                  <div class="board-type-row" aria-label="板块类型分布">
                    <span>概念 <b>{{ ov.board.concept_count }}</b></span>
                    <span>行业 <b>{{ ov.board.industry_count }}</b></span>
                    <span>综合覆盖 <b>{{ boardOverallCoverage }}%</b></span>
                  </div>
                </div>
                <div class="board-hero-status" :class="{ 'is-warning': ov.board.open_issues > 0 }">
                  <span class="board-status-label">质量台账待处理</span>
                  <strong>{{ ov.board.open_issues }} 项</strong>
                  <span>覆盖与鲜活度单独检查</span>
                </div>
              </div>

              <div class="board-layout">
                <div class="board-main">
                  <div class="board-section-head">
                    <div>
                      <span class="panel-title">覆盖进度</span>
                      <HelpHint label="板块覆盖统计口径说明" text="覆盖率和日期显示真实入库数据；当前有效的人工确认单独列示，不计入待补采，也不计为已采齐。资金流覆盖指基准交易日的即时快照。" />
                    </div>
                    <div class="board-section-actions">
                      <el-tag
                        size="small"
                        effect="plain"
                        class="board-coverage-tag"
                        :type="boardCoverageState.type"
                      >
                        {{ boardCoverageState.label }}
                      </el-tag>
                      <el-button data-testid="overview-board-ingest" size="small" type="primary" @click="gotoBoard()">
                        去采集板块
                      </el-button>
                    </div>
                  </div>
                  <div class="board-coverage-grid">
                    <div v-for="item in boardCoverageItems" :key="item.key" class="cov-card">
                      <div class="cov-card-top">
                        <div>
                          <div class="cov-label">{{ item.label }}
                            <HelpHint :text="item.desc" :label="`${item.label}口径说明`" />
                          </div>
                        </div>
                        <div class="cov-pct" :class="[item.confirmed ? 'confirmed' : item.status === 'success' ? 'done' : item.status]">{{ item.target ? item.pct + '%' : '—' }}</div>
                      </div>
                      <el-progress
                        v-if="item.target"
                        :percentage="item.pct"
                        :status="item.status"
                        :stroke-width="9"
                        :show-text="false"
                      />
                      <div class="cov-foot">
                        <span>{{ item.target ? coverageText(item.ready, item.target) + ' 个板块' : '尚无覆盖目标' }}</span>
                      </div>
                      <div v-if="item.ignored" class="app-caption-text">
                        缺失已人工确认 {{ item.ignored }} 个<span v-if="item.pending">，待补采 {{ item.pending }} 个</span>
                      </div>
                    </div>
                  </div>

                  <div class="board-freshness-strip">
                    <div v-for="item in boardFreshnessItems" :key="item.key" class="fresh-cell" :class="{ stale: item.stale, confirmed: item.confirmed }">
                      <span class="fresh-label">{{ item.label }}</span>
                      <strong>{{ dateOnly(item.value) }}</strong>
                      <span>{{ item.status }}</span>
                    </div>
                  </div>
                </div>

                <div class="board-side">
                  <div class="board-side-block issue-panel">
                    <div class="board-side-title">
                      <span>质量问题</span>
                      <HelpHint label="板块台账说明" text="显示已记录的未解决问题；零问题不等于覆盖完整，需结合覆盖进度和最近质检时间。" />
                    </div>
                    <div v-if="boardIssueItems.length" class="board-issue-list">
                      <div v-for="item in boardIssueItems" :key="item.key" class="issue-card">
                        <span class="issue-copy">
                          <span class="issue-tag">{{ item.label }}</span>
                          <span class="issue-hint">{{ item.hint }}</span>
                        </span>
                        <el-button v-if="ISSUE_TYPE_LABEL[item.key]" link type="primary" @click="gotoQuality(undefined, item.key)">查看 {{ item.count }} 项<el-icon class="el-icon--right"><ArrowRight /></el-icon></el-button>
                        <span v-else class="hint">{{ item.count }} 项</span>
                      </div>
                    </div>
                    <div v-else class="issue-ok-card">
                      <span class="issue-ok-dot"></span>
                      <span>无待处理板块问题</span>
                    </div>
                  </div>

                  <div class="board-side-block" v-if="ov.board.last_update">
                    <div class="board-side-title">
                      <span class="app-inline-info app-inline-info--nowrap">
                        <span>最近采集</span>
                        <DataMetricDetails label="最近板块采集" :rows="[{ label: '物理表', value: ov.board.last_update.table_name }]" :notes="ov.board.last_update.detail ? [ov.board.last_update.detail] : []" />
                      </span>
                      <el-tag size="small" effect="plain" :type="boardUpdateStatus(ov.board.last_update.status).type">
                        {{ boardUpdateStatus(ov.board.last_update.status).label }}
                      </el-tag>
                    </div>
                    <div class="board-update-card">
                      <span>{{ tables.find((table) => table.table === ov?.board?.last_update?.table_name)?.name_cn || ov.board.last_update.table_name }}</span>
                      <strong>{{ formatDateTimeSeconds(ov.board.last_update.updated_at, '') }}</strong>
                    </div>
                  </div>
                </div>
              </div>
            </div>
            <AppStateBlock
              v-else
              state="empty"
              title="暂无板块数据"
              description="请先在数据采集页运行板块采集"
            >
              <template #extra>
                <el-button data-testid="overview-board-ingest" size="small" type="primary" @click="gotoBoard()">
                  去采集板块
                </el-button>
              </template>
            </AppStateBlock>
          </AppScrollArea>
          </el-tab-pane>
        </el-tabs>
      </el-card>
    </template>

    <template #overlays>
    <PageSettingsDrawer
      v-model="settingsOpen"
      title="数据概览"
      :dirty="isDirty || layoutDirty"
      page-key="data-overview"
      :config="drawerConfig"
      @reset="reset(); resetLayout()"
    >
      <template #business>
        <PageSettingSection section-key="stock-check" title="逐股体检">
          <PageSettingItem label="默认关注层">
            <PageSegmented v-model="settings.focusLayer" aria-label="默认关注层" :options="[
              { label: '全部', value: 'all' },
              { label: 'L1-L2', value: 'L12' },
              { label: 'L3-L4', value: 'L34' },
            ]" />
          </PageSettingItem>
        </PageSettingSection>
      </template>
    </PageSettingsDrawer>
    </template>
  </LayoutHost>
</template>

<style scoped>
.page-head { display: flex; justify-content: space-between; align-items: flex-start; }
.overview-summary { min-width: 0; }
.panel-title {
  color: var(--el-text-color-primary);
  font-size: var(--app-font-size-table);
  font-weight: var(--app-font-weight-section);
}
.overview-panel > .el-table {
  flex: 1 1 auto;
  min-height: 0;
}
.metric-scroll { flex: 0 0 auto; }
.stat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: var(--app-space-3); }
.quality-heading { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: var(--app-space-2); line-height: var(--app-line-height-table); }
.quality-layer-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: var(--app-space-3); }
.stock-intraday-cell { display: flex; align-items: center; gap: var(--app-space-2); }
.hint { color: var(--el-text-color-secondary); margin-left: 6px; }
.hint { font-size: var(--app-font-size-caption); color: var(--el-text-color-secondary); }
.mono { font-family: var(--app-font-family-mono); font-size: var(--app-font-size-caption); }
.expand { padding: 6px 14px; }
.exp-line { font-size: var(--app-font-size-table); margin-bottom: 6px; color: var(--el-text-color-regular); }
.fld-tbl { margin-top: 8px; }
.asset-search { width: 280px; max-width: 100%; }
.asset-category { width: 190px; max-width: 100%; }
.asset-legacy-toggle {
  display: inline-flex;
  align-items: center;
  gap: var(--app-space-2);
  white-space: nowrap;
  color: var(--el-text-color-regular);
  font-size: var(--app-font-size-table);
}
.asset-local-error {
  flex: 0 0 auto;
  margin-bottom: var(--app-space-2);
}
.asset-count-action {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--app-space-2);
  margin-top: var(--app-space-3);
  margin-bottom: var(--app-space-3);
}
.asset-count-status {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: var(--app-space-2);
  min-width: 0;
  margin-left: auto;
  text-align: right;
}
.asset-count-error { color: var(--el-color-danger); font-size: var(--app-font-size-caption); }
.asset-fact-source {
  display: block;
  margin-top: 2px;
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
}
.layer-card { padding: 8px 10px; border: 1px solid var(--el-border-color-lighter); border-radius: var(--layout-card-radius); }
.layer-name { display: flex; align-items: center; gap: var(--app-space-1); font-size: var(--app-font-size-table); line-height: var(--app-line-height-table); font-weight: var(--app-font-weight-section); margin-bottom: 6px; }
.layer-foot { font-size: var(--app-font-size-caption); line-height: var(--app-line-height-caption); color: var(--el-text-color-secondary); margin-top: 4px; }
.layer-progress { display: flex; align-items: center; gap: var(--app-space-2); }
.layer-progress .el-progress { flex: 1; min-width: 0; }
.layer-progress > span { font-size: var(--app-font-size-caption); line-height: var(--app-line-height-caption); color: var(--el-text-color-primary); }
.quality-summary :deep(.el-card__header) { padding: 9px 12px; }
.quality-summary :deep(.el-card__body) { padding: 10px 12px; }

.overview-stock-filter { width: min(460px, 100%); }
.txt-warn { color: var(--app-warning-text); font-weight: var(--app-font-weight-section); }
.pager { display: flex; justify-content: flex-end; margin-top: 12px; }


/* ── 板块数据 tab ── */
/* el-tabs 内容区 overflow:hidden 会裁超高内容，板块面板须自行承接滚动。 */
.board-pane-scroll { height: 100%; }
.board-pane-scroll :deep(> .app-scroll-area__renderer > .el-scrollbar__wrap > .app-scroll-area__content) > .overview-panel {
  height: auto;
  min-height: 100%;
}
.board-hero {
  flex: 0 0 auto;
  display: grid;
  grid-template-columns: minmax(260px, 1fr) minmax(150px, auto);
  align-items: stretch;
  gap: var(--app-space-3);
  margin-bottom: var(--app-space-3);
}
.board-hero-main,
.board-hero-status,
.board-side-block,
.cov-card,
.fresh-cell {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: var(--layout-card-radius);
  background: var(--el-bg-color);
}
.board-hero-main {
  position: relative;
  min-width: 0;
  padding: var(--app-space-4);
  overflow: hidden;
}
.board-eyebrow {
  display: block;
  font-size: var(--app-font-size-caption);
  color: var(--el-text-color-secondary);
  line-height: var(--app-line-height-caption);
}
.board-title-line {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: var(--app-space-2);
  margin-top: var(--app-space-1);
}
.board-total {
  font-size: var(--app-font-size-kpi-lg);
  line-height: var(--app-line-height-compact);
  font-weight: var(--app-font-weight-strong);
  color: var(--el-text-color-primary);
}
.board-title-text {
  font-size: var(--app-font-size-body);
  color: var(--el-text-color-regular);
}
.board-type-row {
  display: flex;
  flex-wrap: wrap;
  gap: var(--app-space-2) var(--app-space-4);
  margin-top: var(--app-space-3);
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-table);
}
.board-type-row b {
  color: var(--el-text-color-primary);
  font-size: var(--app-font-size-data);
  line-height: var(--app-line-height-data);
  font-weight: var(--app-font-weight-section);
}
.board-hero-status {
  min-width: 150px;
  padding: var(--app-space-3);
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: var(--app-space-1);
  border-color: var(--el-border-color-lighter);
}
.board-hero-status.is-warning {
  border-color: var(--el-color-warning-light-5);
  background: var(--el-color-warning-light-9);
}
.board-status-label,
.fresh-label,
.issue-hint {
  font-size: var(--app-font-size-caption);
  color: var(--el-text-color-secondary);
}
.board-hero-status strong {
  font-size: var(--app-font-size-data);
  font-weight: var(--app-font-weight-section);
  line-height: var(--app-line-height-data);
  color: var(--el-text-color-primary);
}
.board-hero-status span:last-child {
  font-size: var(--app-font-size-caption);
  color: var(--el-text-color-regular);
}
.board-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(260px, 0.65fr);
  gap: var(--app-space-3);
  align-items: stretch;
  flex: 1 1 auto;
  min-height: 0;
}
.board-main,
.board-side {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--app-space-3);
  min-height: 0;
}
.board-section-head,
.board-side-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-2);
}
.board-section-head {
  flex: 0 0 auto;
}
.board-section-head .hint,
.board-side-title .hint {
  margin-left: var(--app-space-2);
}
.board-section-actions {
  display: inline-flex;
  align-items: center;
  gap: var(--app-space-2);
}
.board-coverage-tag {
  cursor: default;
}
.board-coverage-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--app-space-3);
}
.cov-card {
  min-width: 0;
  padding: var(--app-space-3);
  display: flex;
  flex-direction: column;
  gap: var(--app-space-2);
}
.cov-card-top,
.cov-foot {
  display: flex;
  justify-content: space-between;
  gap: var(--app-space-2);
}
.cov-card-top {
  align-items: flex-start;
}
.cov-label {
  font-size: var(--app-font-size-table);
  font-weight: var(--app-font-weight-section);
  color: var(--el-text-color-primary);
}
.cov-pct {
  flex: 0 0 auto;
  font-size: var(--app-font-size-data);
  line-height: var(--app-line-height-data);
  font-weight: var(--app-font-weight-section);
  color: var(--app-warning-text);
}
.cov-pct.done {
  color: var(--el-color-success);
}
.cov-pct.exception {
  color: var(--app-danger-text);
}
.cov-pct.confirmed {
  color: var(--el-text-color-secondary);
}
.cov-foot {
  align-items: center;
  font-size: var(--app-font-size-caption);
  color: var(--el-text-color-secondary);
}
.cov-foot span:first-child {
  color: var(--el-text-color-primary);
  font-weight: var(--app-font-weight-section);
}
.board-freshness-strip {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--app-space-3);
}
.fresh-cell {
  min-width: 0;
  padding: var(--app-space-3);
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: var(--app-space-1) var(--app-space-2);
  align-items: baseline;
}
.fresh-cell strong {
  font-size: var(--app-font-size-table);
  color: var(--el-text-color-primary);
}
.fresh-cell span:last-child {
  justify-self: end;
  font-size: var(--app-font-size-caption);
  color: var(--el-color-success);
}
.fresh-cell.stale {
  border-color: var(--el-color-warning-light-5);
}
.fresh-cell.stale span:last-child,
.fresh-cell.stale strong {
  color: var(--app-warning-text);
}
.fresh-cell.confirmed span:last-child {
  color: var(--el-text-color-secondary);
}
.board-side-block {
  padding: var(--app-space-3);
}
.issue-panel {
  flex: 1 1 auto;
}
.board-side-title {
  margin-bottom: var(--app-space-2);
  font-size: var(--app-font-size-table);
  font-weight: var(--app-font-weight-section);
  color: var(--el-text-color-primary);
}
.board-issue-list {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-2);
}
.issue-card {
  width: 100%;
  min-height: 54px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-3);
  padding: var(--app-space-2) var(--app-space-3);
  border: 1px solid var(--app-border-notice-warning);
  border-radius: var(--layout-card-radius);
  background: var(--el-color-warning-light-9);
  color: inherit;
  text-align: left;
}
.issue-copy {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--app-space-1);
}
.issue-tag {
  font-size: var(--app-font-size-table);
  font-weight: var(--app-font-weight-section);
  color: var(--el-text-color-primary);
}
.issue-ok-card {
  min-height: 54px;
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
  padding: var(--app-space-3);
  border: 1px solid var(--app-border-notice-success);
  border-radius: var(--layout-card-radius);
  color: var(--el-color-success);
  font-size: var(--app-font-size-table);
}
.issue-ok-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--el-color-success);
}
.board-update-card {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-1);
}
.board-update-card strong {
  color: var(--el-text-color-primary);
  font-size: var(--app-font-size-table);
}

@container app-viewport (max-height: 700px) {
  .stat-grid { grid-template-columns: none; grid-auto-flow: column; grid-auto-columns: minmax(180px, 1fr); gap: var(--app-space-2); }
  .quality-summary :deep(.el-card__header) { padding: 5px 10px; }
  .quality-summary :deep(.el-card__body) { padding: 5px 10px; }
  .layer-card { padding: 3px 7px; }
  .layer-name { margin-bottom: 2px; font-size: var(--app-font-size-caption); }

  .overview-workspace-card :deep(.el-card__body) { padding: 6px 10px 8px; }
  .overview-tabs :deep(.el-tabs__header) { margin-bottom: 5px; }
}

@container app-viewport (max-width: 1100px) {
  .board-hero {
    grid-template-columns: 1fr;
  }
  .board-layout {
    grid-template-columns: 1fr;
  }
  .board-coverage-grid,
  .board-freshness-strip {
    grid-template-columns: 1fr;
  }
}
</style>
