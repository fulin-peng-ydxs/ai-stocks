<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import AppStateBlock from '@/components/AppStateBlock.vue'
import KlineSettingSection from '@/components/KlineSettingSection.vue'
import MarketMasterDetailWorkspace from '@/components/MarketMasterDetailWorkspace.vue'
import PageDrawer from '@/components/PageDrawer.vue'
import PageSegmented from '@/components/PageSegmented.vue'
import PageSettingSection from '@/components/PageSettingSection.vue'
import PageSettingsDrawer from '@/components/PageSettingsDrawer.vue'
import PageSettingsTrigger from '@/components/PageSettingsTrigger.vue'
import PageToggleRow from '@/components/PageToggleRow.vue'
import StockAnalysisPanel from '@/components/StockAnalysisPanel.vue'
import StockAnalysisDefaultFields from '@/components/StockAnalysisDefaultFields.vue'
import StockChartSettingSection from '@/components/StockChartSettingSection.vue'
import {
  exportLimitLadder,
  filtersFromRouteQuery,
  filtersToRouteQuery,
  getLimitLadder,
  listLimitLadderTradeDates,
  normalizeLimitLadderFilters,
  type LimitLadderFilters,
  type LimitLadderResult,
  type LimitLadderStock,
} from '@/api/limitLadder'
import { useRemoteLayoutConfig } from '@/composables/useRemoteLayoutConfig'
import { usePageSettings } from '@/composables/usePageSettings'
import { useKlinePrefs } from '@/composables/useKlinePrefs'
import { useMediaQuery } from '@/composables/useMediaQuery'
import { useStockAnalysisSelection } from '@/composables/useStockAnalysisSelection'
import { useStockAnalysisSession } from '@/composables/useStockAnalysisSession'
import {
  useStockChartPreferences,
  type AuxiliaryChartSlot,
} from '@/composables/useStockChartPreferences'
import { getPageLayout } from '@/layout'
import LayoutHost from '@/layout/components/LayoutHost.vue'
import { useAuthStore } from '@/stores/auth'
import { useStockSet } from '@/stores/stockSet'
import { hasPermission } from '@/utils/permission'
import {
  PRICE_COMPARE_METRIC_ORDER,
  type PriceCompareMetric,
} from '@/utils/marketCompare'
import LimitLadder from '@/views/limit-ladder/LimitLadder.vue'
import {
  LIMIT_LADDER_POLL_TIMEOUT_MS,
  limitLadderPollDecision,
  limitLadderPollDelay,
  limitLadderPollTaskKey,
} from '@/views/limit-ladder/polling'
import {
  DEFAULT_LIMIT_LADDER_PREFERENCE,
  filtersFromLimitLadderPreference,
  normalizeLimitLadderPreference,
  type LimitLadderPreferenceV1,
} from '@/views/limit-ladder/preferences'
import {
  DEFAULT_LIMIT_LADDER_CARD_SORT,
  DEFAULT_LIMIT_LADDER_CARD_SORT_ORDER,
  LIMIT_LADDER_CARD_SORT_OPTIONS,
  defaultLimitLadderCardSortOrder,
  normalizeLimitLadderCardSort,
  normalizeLimitLadderCardSortOrder,
  sortLimitLadderLayers,
  type LimitLadderCardSort,
  type LimitLadderCardSortOrder,
} from '@/views/limit-ladder/sorting'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const stockSet = useStockSet()
const settingsOpen = ref(false)
const ladderHost = ref<HTMLElement | null>(null)
const analysisDrawerOpen = ref(false)
const isNarrowViewport = useMediaQuery('(max-width: 768px)')
const isLowHeightViewport = useMediaQuery('(max-height: 700px)')
const tradeDate = ref<string | null>(
  typeof route.query.date === 'string' ? route.query.date : null,
)
const filters = ref<LimitLadderFilters>(filtersFromRouteQuery(route.query))
const cardSort = ref<LimitLadderCardSort>(normalizeLimitLadderCardSort(route.query.card_sort))
const cardSortOrder = ref<LimitLadderCardSortOrder>(
  normalizeLimitLadderCardSortOrder(
    route.query.card_order,
    defaultLimitLadderCardSortOrder(cardSort.value),
  ),
)
const result = ref<LimitLadderResult | null>(null)
// 首次请求前还要等待个人偏好和交易日列表，期间必须保持加载态，避免把 result=null
// 短暂渲染成“无可用快照”的业务失败态。
const loading = ref(true)
const error = ref('')
const forbidden = ref(false)
const exporting = ref(false)
let requestSequence = 0
let syncingRoute = false
let resultRefreshTimer: number | undefined
let resultRefreshDeadlineTimer: number | undefined
let resultRefreshAttempt = 0
let resultRefreshStartedAt = 0
let resultRefreshTaskKey = ''

const {
  settings: preference,
  isDirty: preferenceDirty,
  reset: resetPreference,
  hydrated: preferenceHydrated,
  whenHydrated: whenPreferenceHydrated,
  remoteError: preferenceRemoteError,
  saveError: preferenceSaveError,
  save: savePreference,
} = usePageSettings('limit-ladder', DEFAULT_LIMIT_LADDER_PREFERENCE)

const analysisDefaults = reactive({
  defaultChartMode: 'compare' as 'compare' | 'kline',
  showAnalysisPanel: DEFAULT_LIMIT_LADDER_PREFERENCE.showAnalysisPanel,
  compareRange: 60,
  benchmarkCode: '000905.SH',
  compareMetrics: [...PRICE_COMPARE_METRIC_ORDER] as PriceCompareMetric[],
  defaultCompareMetric: 'cum' as PriceCompareMetric,
  adjustMode: 'qfq' as '' | 'qfq' | 'hfq',
})
const { validDefault: klineDefaultRange } = useKlinePrefs()
const {
  analysisPanelVisible,
  chartMode,
  compareRange,
  compareMetric,
  benchmarkCode,
  adjustMode,
  visibleCompareMetrics,
  klineRange,
} = useStockAnalysisSession(analysisDefaults, klineDefaultRange)
const chartSettings = computed({
  get: () => preference.charts,
  set: (value) => { preference.charts = value },
})
const chartPreferences = useStockChartPreferences(chartSettings, preferenceHydrated)

function effectivePreference(): LimitLadderPreferenceV1 {
  return preferenceRemoteError.value
    ? normalizeLimitLadderPreference(DEFAULT_LIMIT_LADDER_PREFERENCE)
    : normalizeLimitLadderPreference(preference)
}

function applyAnalysisDefaults(value: LimitLadderPreferenceV1): void {
  analysisDefaults.defaultChartMode = value.defaultChartMode
  analysisDefaults.showAnalysisPanel = value.showAnalysisPanel
  analysisDefaults.compareRange = value.compareRange
  analysisDefaults.benchmarkCode = value.benchmarkCode
  analysisDefaults.compareMetrics = [...value.compareMetrics]
  analysisDefaults.defaultCompareMetric = value.defaultCompareMetric
  analysisDefaults.adjustMode = value.adjustMode
}

const canViewSectors = computed(() => (
  hasPermission(auth.role, auth.permissions, 'sectors:view')
))
const canViewStockDetail = computed(() => (
  hasPermission(auth.role, auth.permissions, 'stocks:view')
))
const canManageData = computed(() => (
  hasPermission(auth.role, auth.permissions, 'data-task:manage')
))
const analysisSourceItems = computed(() => (
  sortLimitLadderLayers(result.value?.layers ?? [], cardSort.value, cardSortOrder.value)
    .flatMap((layer) => layer.stocks)
))
const {
  activeCode: activeAnalysisCode,
  activeItem: activeAnalysisItem,
  items: analysisItems,
  select: selectAnalysisItem,
  activate: activateAnalysisCode,
  remove: removeAnalysisCode,
  clear: clearAnalysisSelection,
} = useStockAnalysisSelection(analysisSourceItems, {
  autoSelectFirst: false,
  onLimitReached: (limit) => ElMessage.warning(`最多对比${limit}只股票`),
})
const workspaceMeta = computed(() => result.value?.has_snapshot
  ? `${result.value.summary.stock_count} 只 · ${filters.value.window} 日口径`
  : '等待快照')
const ladderReturnPath = computed(() => route.fullPath)
const compactHotspots = computed(() => (
  isLowHeightViewport.value && analysisPanelVisible.value && !isNarrowViewport.value
))

const baseLayout = getPageLayout('limit-ladder')
const {
  effective,
  knobs,
  setKnob,
  valueOf,
  sourceOf,
  layerValuesOf,
  isDirty,
  resetAll,
  componentValueOf,
  setComponentKnob,
  componentSourceOf,
  componentLayerValuesOf,
  componentAllowedLayers,
} = useRemoteLayoutConfig(baseLayout)
const drawerConfig = {
  knobs,
  setKnob,
  valueOf,
  sourceOf,
  layerValuesOf,
  componentValueOf,
  setComponentKnob,
  componentSourceOf,
  componentLayerValuesOf,
  componentAllowedLayers,
}

async function applySystemDefaults(): Promise<void> {
  filters.value = filtersFromLimitLadderPreference(DEFAULT_LIMIT_LADDER_PREFERENCE)
  cardSort.value = DEFAULT_LIMIT_LADDER_CARD_SORT
  cardSortOrder.value = DEFAULT_LIMIT_LADDER_CARD_SORT_ORDER
  applyAnalysisDefaults(DEFAULT_LIMIT_LADDER_PREFERENCE)
  await syncUrl()
  await loadLadder()
}

async function resetAllSettings(): Promise<void> {
  resetPreference()
  resetAll()
  await savePreference()
  await applySystemDefaults()
  if (preferenceSaveError.value) {
    ElMessage.error('默认偏好已在本机恢复，远端保存失败，请稍后重试')
    return
  }
  ElMessage.success('已恢复并应用系统默认设置')
}

function errorMessage(value: unknown, fallback: string): string {
  return String(
    (value as { uiMessage?: string; message?: string })?.uiMessage
      || (value as { message?: string })?.message
      || fallback,
  )
}

function isPermissionError(value: unknown): boolean {
  return (value as { response?: { status?: number } })?.response?.status === 403
}

async function syncUrl(): Promise<void> {
  syncingRoute = true
  try {
    await router.replace({
      query: {
        ...filtersToRouteQuery(filters.value),
        ...(tradeDate.value ? { date: tradeDate.value } : {}),
        ...(activeAnalysisCode.value ? { selected: activeAnalysisCode.value } : {}),
        ...(activeAnalysisCode.value ? { anchor: activeAnalysisCode.value } : {}),
        card_sort: cardSort.value,
        card_order: cardSortOrder.value,
      },
    })
  } finally {
    syncingRoute = false
  }
}

function queryText(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

async function restoreScrollAnchor(code: string): Promise<void> {
  if (!code) return
  await nextTick()
  await new Promise<void>((resolve) => {
    window.requestAnimationFrame(() => window.requestAnimationFrame(() => resolve()))
  })
  const card = Array.from(ladderHost.value?.querySelectorAll<HTMLElement>('[data-stock-code]') ?? [])
    .find((node) => node.dataset.stockCode === code)
  const scrollRegion = card?.closest<HTMLElement>('.limit-ladder__content')
  if (!card || !scrollRegion) return
  const cardRect = card.getBoundingClientRect()
  const regionRect = scrollRegion.getBoundingClientRect()
  const centeredOffset = Math.max((scrollRegion.clientHeight - cardRect.height) / 2, 0)
  scrollRegion.scrollTop += cardRect.top - regionRect.top - centeredOffset
}

async function reconcileAnalysisContext(): Promise<void> {
  await nextTick()
  const requestedCode = queryText(route.query.selected)
  const requestedItem = analysisSourceItems.value.find((item) => item.code === requestedCode)
  if (requestedItem) selectAnalysisItem(requestedItem)

  if (!analysisSourceItems.value.length) {
    clearAnalysisSelection()
    analysisDrawerOpen.value = false
  }
  const anchor = queryText(route.query.anchor)
  if (anchor && analysisSourceItems.value.some((item) => item.code === anchor)) {
    await restoreScrollAnchor(anchor)
  }
}

function clearResultRefresh(resetTracking = true): void {
  if (resultRefreshTimer !== undefined) window.clearTimeout(resultRefreshTimer)
  resultRefreshTimer = undefined
  if (resetTracking) {
    if (resultRefreshDeadlineTimer !== undefined) {
      window.clearTimeout(resultRefreshDeadlineTimer)
    }
    resultRefreshDeadlineTimer = undefined
    resultRefreshAttempt = 0
    resultRefreshStartedAt = 0
    resultRefreshTaskKey = ''
  }
}

function needsResultRefresh(data: LimitLadderResult | null): boolean {
  return data?.business_code === 'SNAPSHOT_PENDING'
    || data?.snapshot_status === 'calculating'
    || data?.snapshot_status === 'recalculating'
}

function stopResultRefreshAtTimeout(): void {
  if (!result.value || !needsResultRefresh(result.value)) {
    clearResultRefresh()
    return
  }
  const timeoutMessage = '计算任务等待超时，请重试；系统会重新检查并恢复孤儿任务'
  requestSequence += 1
  clearResultRefresh()
  if (result.value.has_snapshot) {
    result.value = {
      ...result.value,
      snapshot_status: 'failed',
      task_error: timeoutMessage,
    }
  } else {
    error.value = timeoutMessage
  }
}

function scheduleResultRefresh(): void {
  clearResultRefresh(false)
  if (!result.value || !needsResultRefresh(result.value)) {
    clearResultRefresh()
    return
  }
  const taskKey = limitLadderPollTaskKey(result.value)
  if (taskKey !== resultRefreshTaskKey) {
    if (resultRefreshDeadlineTimer !== undefined) {
      window.clearTimeout(resultRefreshDeadlineTimer)
    }
    resultRefreshTaskKey = taskKey
    resultRefreshAttempt = 0
    resultRefreshStartedAt = performance.now()
    resultRefreshDeadlineTimer = window.setTimeout(() => {
      resultRefreshDeadlineTimer = undefined
      stopResultRefreshAtTimeout()
    }, LIMIT_LADDER_POLL_TIMEOUT_MS)
  }
  const decision = limitLadderPollDecision(
    resultRefreshAttempt,
    performance.now() - resultRefreshStartedAt,
  )
  if (decision.timedOut) {
    stopResultRefreshAtTimeout()
    return
  }
  const delay = decision.delayMs ?? LIMIT_LADDER_POLL_TIMEOUT_MS
  resultRefreshAttempt += 1
  resultRefreshTimer = window.setTimeout(() => {
    resultRefreshTimer = undefined
    void requestLadder(true)
  }, delay)
}

async function requestLadder(background: boolean): Promise<void> {
  if (!tradeDate.value) return
  const sequence = ++requestSequence
  if (!background) {
    loading.value = true
    error.value = ''
  }
  forbidden.value = false
  try {
    const data = await getLimitLadder(tradeDate.value, filters.value)
    if (sequence !== requestSequence) return
    result.value = data
    forbidden.value = false
    if (background) error.value = ''
    if (!background) loading.value = false
    await reconcileAnalysisContext()
    if (sequence !== requestSequence) return
    if (activeAnalysisCode.value !== queryText(route.query.selected)) await syncUrl()
  } catch (value) {
    if (sequence !== requestSequence) return
    if (isPermissionError(value)) {
      result.value = null
      error.value = ''
      forbidden.value = true
    } else if (!background) {
      error.value = errorMessage(value, '天梯加载失败，请稍后重试')
    }
  } finally {
    if (sequence === requestSequence) {
      if (!background) loading.value = false
      scheduleResultRefresh()
    }
  }
}

async function loadLadder(): Promise<void> {
  clearResultRefresh()
  await requestLadder(false)
}

async function retryLadder(): Promise<void> {
  await loadLadder()
}

async function openLadderMaintenance(): Promise<void> {
  await router.push({
    path: '/data/ingest',
    query: {
      task_type: 'limit_ladder_invalidate',
      ...(tradeDate.value ? { trade_date: tradeDate.value } : {}),
    },
  })
}

async function setFilters(next: LimitLadderFilters): Promise<void> {
  filters.value = normalizeLimitLadderFilters(next)
  await syncUrl()
  await loadLadder()
}

async function setTradeDate(next: string | null): Promise<void> {
  if (!next || next === tradeDate.value) return
  tradeDate.value = next
  filters.value = { ...filters.value, hotspotType: null, hotspotKey: null }
  result.value = null
  clearAnalysisSelection()
  analysisDrawerOpen.value = false
  await syncUrl()
  await loadLadder()
}

async function setCardSort(next: LimitLadderCardSort): Promise<void> {
  cardSort.value = normalizeLimitLadderCardSort(next)
  await syncUrl()
}

async function exportCsv(): Promise<void> {
  if (!tradeDate.value || exporting.value) return
  exporting.value = true
  try {
    const { blob, filename } = await exportLimitLadder(tradeDate.value, filters.value)
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = filename
    anchor.click()
    URL.revokeObjectURL(url)
    ElMessage.success(`已按当前 ${filters.value.window} 日筛选口径导出`)
  } catch (value) {
    ElMessage.error(errorMessage(value, '导出失败，请稍后重试'))
  } finally {
    exporting.value = false
  }
}

async function selectStock(stock: LimitLadderStock): Promise<void> {
  selectAnalysisItem(stock)
  if (isNarrowViewport.value) analysisDrawerOpen.value = true
  else analysisPanelVisible.value = true
  await syncUrl()
}

async function activateAnalysisItem(code: string): Promise<void> {
  activateAnalysisCode(code)
  await syncUrl()
}

async function removeAnalysisItem(code: string): Promise<void> {
  removeAnalysisCode(code)
  await syncUrl()
}

async function openActiveAnalysisDetail(): Promise<void> {
  const active = activeAnalysisItem.value
  if (!canViewStockDetail.value || !active) return
  const items = analysisSourceItems.value.map((item) => ({ code: item.code, name: item.name }))
  await syncUrl()
  stockSet.setSet('list', items, '连板天梯', '', {
    total: items.length,
    loadedPages: items.length ? [1] : [],
    pageSize: Math.max(items.length, 1),
    returnPath: route.fullPath,
  })
  await router.push(`/stocks/${active.code}`)
}

function handleRatioDraft(ratios: number[]): void {
  chartPreferences.updateRatioDraft(ratios)
}

function setAuxiliaryChart(slot: AuxiliaryChartSlot, value: string | number | boolean): void {
  chartPreferences.setSlotType(slot, value)
}

function handleRatioCommit(ratios: number[]): void {
  chartPreferences.updateRatioDraft(ratios)
  chartPreferences.commitRatioDraft()
}

watch(preference, () => applyAnalysisDefaults(normalizeLimitLadderPreference(preference)), { deep: true })

watch(isNarrowViewport, (narrow) => {
  if (!narrow) analysisDrawerOpen.value = false
})

watch(analysisDrawerOpen, (open) => {
  if (!open) void restoreScrollAnchor(activeAnalysisCode.value)
})

watch(
  () => route.query,
  (query) => {
    if (syncingRoute) return
    const nextDate = typeof query.date === 'string' ? query.date : tradeDate.value
    const nextFilters = filtersFromRouteQuery(
      query,
      filtersFromLimitLadderPreference(effectivePreference()),
    )
    const changed = nextDate !== tradeDate.value
      || JSON.stringify(nextFilters) !== JSON.stringify(filters.value)
    cardSort.value = normalizeLimitLadderCardSort(query.card_sort ?? cardSort.value)
    cardSortOrder.value = normalizeLimitLadderCardSortOrder(
      query.card_order,
      query.card_sort === undefined
        ? cardSortOrder.value
        : defaultLimitLadderCardSortOrder(cardSort.value),
    )
    if (!changed) {
      void reconcileAnalysisContext()
      return
    }
    tradeDate.value = nextDate
    filters.value = nextFilters
    void loadLadder()
  },
)

onMounted(async () => {
  try {
    await whenPreferenceHydrated()
    const savedPreference = effectivePreference()
    applyAnalysisDefaults(savedPreference)
    cardSort.value = normalizeLimitLadderCardSort(route.query.card_sort ?? savedPreference.cardSort)
    cardSortOrder.value = normalizeLimitLadderCardSortOrder(
      route.query.card_order,
      route.query.card_sort === undefined
        ? savedPreference.cardSortOrder
        : defaultLimitLadderCardSortOrder(cardSort.value),
    )
    filters.value = filtersFromRouteQuery(
      route.query,
      filtersFromLimitLadderPreference(savedPreference),
    )
    analysisDefaults.showAnalysisPanel = savedPreference.showAnalysisPanel
    const dates = await listLimitLadderTradeDates()
    if (!tradeDate.value) {
      tradeDate.value = dates.latest_complete_date
        || dates.latest_candidate_date
        || dates.dates[0]
        || null
    }
    if (!tradeDate.value) {
      error.value = '暂无可用交易日'
      loading.value = false
      return
    }
    await syncUrl()
    await loadLadder()
  } catch (value) {
    if (isPermissionError(value)) {
      result.value = null
      error.value = ''
      forbidden.value = true
    } else {
      error.value = errorMessage(value, '交易日加载失败，请稍后重试')
    }
    loading.value = false
  }
})

onBeforeUnmount(() => {
  requestSequence += 1
  clearResultRefresh()
})
</script>

<template>
  <LayoutHost :layout="effective" data-testid="limit-ladder-page">
    <template #action>
      <div class="lh-action">
        <div class="page-head">
          <div>
            <h2 class="app-page-title">连板天梯</h2>
            <p class="page-subtitle">按交易日观察涨停梯队，筛选、热点与导出共享同一快照口径。</p>
          </div>
          <div class="page-head-actions">
            <el-button
              v-if="canManageData"
              data-testid="limit-ladder-maintenance"
              @click="openLadderMaintenance"
            >结果维护</el-button>
            <el-button
              :loading="exporting"
              :disabled="!result?.has_snapshot"
              data-testid="limit-ladder-export"
              @click="exportCsv"
            >导出 CSV</el-button>
            <PageSettingsTrigger :dirty="isDirty || preferenceDirty" @click="settingsOpen = true" />
          </div>
        </div>
      </div>
    </template>

    <template #main>
      <MarketMasterDetailWorkspace
        v-model:analysis-visible="analysisPanelVisible"
        :compact="isNarrowViewport"
        eyebrow="LIMIT LADDER"
        title="涨停梯队"
        :meta="workspaceMeta"
        list-aria-label="连板天梯分层"
        data-testid="limit-ladder-workspace"
      >
        <template #list>
          <div ref="ladderHost" class="limit-ladder-host">
            <LimitLadder
              :result="result"
              :filters="filters"
              :trade-date="tradeDate"
              :loading="loading"
              :error="error"
              :forbidden="forbidden"
              :can-view-sectors="canViewSectors"
              :can-manage-data="canManageData"
              :compact-hotspots="compactHotspots"
              :selected-code="activeAnalysisCode"
              :return-path="ladderReturnPath"
              :card-sort="cardSort"
              :card-sort-order="cardSortOrder"
              @update:filters="setFilters"
              @update:trade-date="setTradeDate"
              @update:card-sort="setCardSort"
              @retry="retryLadder"
              @open-maintenance="openLadderMaintenance"
              @open-ingest="router.push('/data/ingest')"
              @select="selectStock"
            />
          </div>
        </template>
        <template #analysis>
          <StockAnalysisPanel
            v-model:mode="chartMode"
            v-model:compare-range="compareRange"
            v-model:compare-metric="compareMetric"
            v-model:benchmark-code="benchmarkCode"
            v-model:kline-range="klineRange"
            :active="activeAnalysisItem"
            :items="analysisItems"
            :compare-metrics="visibleCompareMetrics"
            :adjust-mode="adjustMode"
            :end-date="tradeDate"
            :slot2="chartPreferences.preferences.value.slot2"
            :slot3="chartPreferences.preferences.value.slot3"
            :height-ratios="chartPreferences.currentRatios.value"
            :can-open-detail="canViewStockDetail"
            @activate="activateAnalysisItem"
            @remove="removeAnalysisItem"
            @open-detail="openActiveAnalysisDetail"
            @ratio-draft="handleRatioDraft"
            @ratio-commit="handleRatioCommit"
          />
        </template>
      </MarketMasterDetailWorkspace>
    </template>

    <template #overlays>
      <PageDrawer
        v-if="isNarrowViewport"
        v-model="analysisDrawerOpen"
        title="股票走势分析"
        size="full"
        modal-class="limit-ladder-analysis-drawer"
        data-testid="limit-ladder-analysis-drawer"
      >
        <StockAnalysisPanel
          v-model:mode="chartMode"
          v-model:compare-range="compareRange"
          v-model:compare-metric="compareMetric"
          v-model:benchmark-code="benchmarkCode"
          v-model:kline-range="klineRange"
          :active="activeAnalysisItem"
          :items="analysisItems"
          :compare-metrics="visibleCompareMetrics"
          :adjust-mode="adjustMode"
          :end-date="tradeDate"
          :slot2="chartPreferences.preferences.value.slot2"
          :slot3="chartPreferences.preferences.value.slot3"
          :height-ratios="chartPreferences.currentRatios.value"
          :can-open-detail="canViewStockDetail"
          @activate="activateAnalysisItem"
          @remove="removeAnalysisItem"
          @open-detail="openActiveAnalysisDetail"
          @ratio-draft="handleRatioDraft"
          @ratio-commit="handleRatioCommit"
        />
      </PageDrawer>
      <PageSettingsDrawer
        v-model="settingsOpen"
        title="连板天梯"
        :dirty="isDirty || preferenceDirty"
        page-key="limit-ladder"
        :config="drawerConfig"
        :business-visible="true"
        @reset="resetAllSettings"
      >
        <template #business>
          <AppStateBlock
            v-if="preferenceRemoteError"
            state="error"
            size="inline"
            title="个人偏好读取失败"
            description="当前使用系统默认，修改后会继续尝试同步"
          />
          <AppStateBlock
            v-else-if="preferenceSaveError"
            state="error"
            size="inline"
            title="默认偏好远端同步失败"
            description="当前修改已保存在本机，网络恢复后再次修改即可重试"
          />
          <StockChartSettingSection
            :slot2="chartPreferences.preferences.value.slot2"
            :slot3="chartPreferences.preferences.value.slot3"
            :chart-types="chartPreferences.visibleTypes.value"
            :default-ratios="chartPreferences.defaultRatios.value"
            test-id-prefix="limit-ladder-chart"
            @change="setAuxiliaryChart"
            @save-default-ratios="chartPreferences.setDefaultHeightRatios"
            @save-current-as-default="chartPreferences.saveCurrentRatiosAsDefault"
          >
            <template #before>
              <div class="setting-item">
                <div class="setting-label">复权模式</div>
                <PageSegmented
                  v-model="preference.adjustMode"
                  aria-label="复权模式"
                  :options="[
                    { label: '不复权', value: '' },
                    { label: '前复权', value: 'qfq' },
                    { label: '后复权', value: 'hfq' },
                  ]"
                />
              </div>
            </template>
          </StockChartSettingSection>
          <PageSettingSection title="默认查询">
            <div class="setting-item">
              <div class="setting-label">统计窗口</div>
              <PageSegmented
                v-model="preference.window"
                :options="[
                  { label: '10 日', value: 10 },
                  { label: '20 日', value: 20 },
                  { label: '31 日', value: 31 },
                  { label: '60 日', value: 60 },
                ]"
                aria-label="默认统计窗口"
                test-id="limit-ladder-default-window"
              />
            </div>
            <div class="setting-item">
              <div class="setting-label">纳入板块</div>
              <el-checkbox-group
                v-model="preference.boards"
                class="board-preference-options"
                aria-label="默认纳入板块"
                data-testid="limit-ladder-default-boards"
              >
                <el-checkbox value="main">主板</el-checkbox>
                <el-checkbox value="star">科创板</el-checkbox>
                <el-checkbox value="gem">创业板</el-checkbox>
              </el-checkbox-group>
            </div>
            <PageToggleRow
              v-model="preference.ignoreSt"
              label="默认忽略 ST"
              test-id="limit-ladder-default-ignore-st"
            />
            <div class="setting-item">
              <div class="setting-label">卡片层内排序</div>
              <el-select
                v-model="preference.cardSort"
                data-testid="limit-ladder-default-card-sort"
              >
                <el-option
                  v-for="option in LIMIT_LADDER_CARD_SORT_OPTIONS"
                  :key="option.value"
                  :label="option.label"
                  :value="option.value"
                />
              </el-select>
            </div>
            <div class="setting-item">
              <div class="setting-label">排序方向</div>
              <PageSegmented
                v-model="preference.cardSortOrder"
                :options="[
                  { label: '升序', value: 'asc' },
                  { label: '降序', value: 'desc' },
                ]"
                aria-label="默认卡片排序方向"
                test-id="limit-ladder-default-card-sort-order"
              />
            </div>
            <StockAnalysisDefaultFields
              v-model:default-chart-mode="preference.defaultChartMode"
              v-model:compare-range="preference.compareRange"
              v-model:benchmark-code="preference.benchmarkCode"
              v-model:compare-metrics="preference.compareMetrics"
              v-model:default-compare-metric="preference.defaultCompareMetric"
              v-model:show-analysis-panel="preference.showAnalysisPanel"
            />
          </PageSettingSection>
          <KlineSettingSection />
        </template>
      </PageSettingsDrawer>
    </template>
  </LayoutHost>
</template>

<style scoped>
.limit-ladder-host {
  display: flex;
  flex: 1 1 auto;
  min-height: 0;
}
.setting-item {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-2);
}
.setting-label {
  color: var(--page-settings-text);
  font-size: var(--app-font-size-body);
}
.board-preference-options {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--app-space-1);
}
</style>

<style>
.limit-ladder-analysis-drawer .el-drawer__body {
  display: flex;
  min-height: 0;
  padding: var(--app-space-3);
}
.limit-ladder-analysis-drawer .stock-analysis-panel {
  flex: 1 1 auto;
}
</style>
