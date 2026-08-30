<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import AppStateBlock from '@/components/AppStateBlock.vue'
import MarketMasterDetailWorkspace from '@/components/MarketMasterDetailWorkspace.vue'
import PageDrawer from '@/components/PageDrawer.vue'
import PageSegmented from '@/components/PageSegmented.vue'
import PageSettingSection from '@/components/PageSettingSection.vue'
import PageSettingsDrawer from '@/components/PageSettingsDrawer.vue'
import PageSettingsTrigger from '@/components/PageSettingsTrigger.vue'
import PageToggleRow from '@/components/PageToggleRow.vue'
import StockAnalysisPanel from '@/components/StockAnalysisPanel.vue'
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
import { useStockAnalysisSelection } from '@/composables/useStockAnalysisSelection'
import { useStockAnalysisSession } from '@/composables/useStockAnalysisSession'
import {
  createDefaultStockChartPreferences,
  useStockChartPreferences,
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
  DEFAULT_LIMIT_LADDER_PREFERENCE,
  filtersFromLimitLadderPreference,
  normalizeLimitLadderPreference,
  type LimitLadderPreferenceV1,
} from '@/views/limit-ladder/preferences'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const stockSet = useStockSet()
const settingsOpen = ref(false)
const ladderHost = ref<HTMLElement | null>(null)
const analysisDrawerOpen = ref(false)
const isNarrowViewport = ref(false)
const tradeDate = ref<string | null>(
  typeof route.query.date === 'string' ? route.query.date : null,
)
const filters = ref<LimitLadderFilters>(filtersFromRouteQuery(route.query))
const result = ref<LimitLadderResult | null>(null)
const loading = ref(false)
const error = ref('')
const exporting = ref(false)
let requestSequence = 0
let syncingRoute = false
let narrowMedia: MediaQueryList | null = null

const {
  settings: preference,
  isDirty: preferenceDirty,
  reset: resetPreference,
  whenHydrated: whenPreferenceHydrated,
  remoteError: preferenceRemoteError,
  saving: preferenceSaving,
  saveError: preferenceSaveError,
  save: savePreference,
} = usePageSettings('limit-ladder', DEFAULT_LIMIT_LADDER_PREFERENCE)
const preferenceDraft = reactive<LimitLadderPreferenceV1>(
  normalizeLimitLadderPreference(DEFAULT_LIMIT_LADDER_PREFERENCE),
)

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
const chartSettingsState = ref(createDefaultStockChartPreferences())
const chartSettings = computed({
  get: () => chartSettingsState.value,
  set: (value) => { chartSettingsState.value = value },
})
const chartPreferences = useStockChartPreferences(chartSettings, ref(true))

function effectivePreference(): LimitLadderPreferenceV1 {
  return preferenceRemoteError.value
    ? normalizeLimitLadderPreference(DEFAULT_LIMIT_LADDER_PREFERENCE)
    : normalizeLimitLadderPreference(preference)
}

function resetPreferenceDraft(): void {
  Object.assign(preferenceDraft, effectivePreference())
}

const canViewSectors = computed(() => (
  hasPermission(auth.role, auth.permissions, 'sectors:view')
))
const canViewStockDetail = computed(() => (
  hasPermission(auth.role, auth.permissions, 'stocks:view')
))
const analysisSourceItems = computed(() => (
  result.value?.layers.flatMap((layer) => layer.stocks) ?? []
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
  analysisDefaults.showAnalysisPanel = DEFAULT_LIMIT_LADDER_PREFERENCE.showAnalysisPanel
  await syncUrl()
  await loadLadder()
}

async function savePreferenceDefaults(): Promise<void> {
  const previous = effectivePreference()
  const normalized = normalizeLimitLadderPreference(preferenceDraft)
  Object.assign(preference, normalized)
  await savePreference()
  if (preferenceSaveError.value) {
    Object.assign(preference, previous)
    ElMessage.error('默认偏好保存失败，请检查网络后重试')
    return
  }
  Object.assign(preferenceDraft, normalized)
  settingsOpen.value = false
  ElMessage.success('已保存连板天梯默认偏好')
}

function cancelPreferenceDraft(): void {
  resetPreferenceDraft()
  settingsOpen.value = false
}

async function resetAllSettings(): Promise<void> {
  resetPreference()
  resetAll()
  resetPreferenceDraft()
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

async function syncUrl(): Promise<void> {
  syncingRoute = true
  try {
    await router.replace({
      query: {
        ...filtersToRouteQuery(filters.value),
        ...(tradeDate.value ? { date: tradeDate.value } : {}),
        ...(activeAnalysisCode.value ? { selected: activeAnalysisCode.value } : {}),
        ...(activeAnalysisCode.value ? { anchor: activeAnalysisCode.value } : {}),
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
  const card = Array.from(ladderHost.value?.querySelectorAll<HTMLElement>('[data-stock-code]') ?? [])
    .find((node) => node.dataset.stockCode === code)
  card?.scrollIntoView({ block: 'center', inline: 'nearest' })
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

async function loadLadder(): Promise<void> {
  if (!tradeDate.value) return
  const sequence = ++requestSequence
  loading.value = true
  error.value = ''
  try {
    const data = await getLimitLadder(tradeDate.value, filters.value)
    if (sequence !== requestSequence) return
    result.value = data
    await reconcileAnalysisContext()
    if (sequence !== requestSequence) return
    if (activeAnalysisCode.value !== queryText(route.query.selected)) await syncUrl()
  } catch (value) {
    if (sequence !== requestSequence) return
    error.value = errorMessage(value, '天梯加载失败，请稍后重试')
  } finally {
    if (sequence === requestSequence) loading.value = false
  }
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

function handleRatioCommit(ratios: number[]): void {
  chartPreferences.updateRatioDraft(ratios)
  chartPreferences.commitRatioDraft()
}

function updateNarrowViewport(event?: MediaQueryListEvent): void {
  isNarrowViewport.value = event?.matches ?? narrowMedia?.matches ?? false
  if (!isNarrowViewport.value) analysisDrawerOpen.value = false
}

watch(
  settingsOpen,
  () => resetPreferenceDraft(),
)

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
    if (!changed) return
    tradeDate.value = nextDate
    filters.value = nextFilters
    void loadLadder()
  },
)

onMounted(async () => {
  narrowMedia = window.matchMedia('(max-width: 768px)')
  updateNarrowViewport()
  narrowMedia.addEventListener('change', updateNarrowViewport)
  try {
    await whenPreferenceHydrated()
    const savedPreference = effectivePreference()
    Object.assign(preferenceDraft, savedPreference)
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
      return
    }
    await syncUrl()
    await loadLadder()
  } catch (value) {
    error.value = errorMessage(value, '交易日加载失败，请稍后重试')
  }
})

onBeforeUnmount(() => {
  requestSequence += 1
  narrowMedia?.removeEventListener('change', updateNarrowViewport)
  narrowMedia = null
})
</script>

<template>
  <LayoutHost :layout="effective" data-testid="limit-ladder-page">
    <template #action>
      <div class="lh-action">
        <div class="page-head">
          <div>
            <div class="page-title-line">
              <h2 class="app-page-title">连板天梯</h2>
              <el-tag size="small" type="success" effect="plain">完整工作台</el-tag>
            </div>
            <p class="page-subtitle">按交易日观察涨停梯队，筛选、热点与导出共享同一快照口径。</p>
          </div>
          <PageSettingsTrigger :dirty="isDirty" @click="settingsOpen = true" />
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
              :exporting="exporting"
              :can-view-sectors="canViewSectors"
              :selected-code="activeAnalysisCode"
              @update:filters="setFilters"
              @update:trade-date="setTradeDate"
              @retry="loadLadder"
              @export="exportCsv"
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
            description="当前使用系统默认，可重新保存后再试"
          />
          <PageSettingSection title="默认筛选">
            <div class="setting-item">
              <div class="setting-label">统计窗口</div>
              <PageSegmented
                v-model="preferenceDraft.window"
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
                v-model="preferenceDraft.boards"
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
              v-model="preferenceDraft.ignoreSt"
              label="默认忽略 ST"
              test-id="limit-ladder-default-ignore-st"
            />
            <PageToggleRow
              v-model="preferenceDraft.showAnalysisPanel"
              label="默认展开走势分析"
              test-id="limit-ladder-default-analysis"
            />
          </PageSettingSection>
          <div class="preference-actions">
            <el-button data-testid="limit-ladder-default-cancel" @click="cancelPreferenceDraft">
              取消
            </el-button>
            <el-button
              type="primary"
              :loading="preferenceSaving"
              data-testid="limit-ladder-default-save"
              @click="savePreferenceDefaults"
            >
              保存为默认
            </el-button>
          </div>
        </template>
      </PageSettingsDrawer>
    </template>
  </LayoutHost>
</template>

<style scoped>
.page-title-line {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
}
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
.preference-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--app-space-2);
  padding-top: var(--app-space-2);
}
@media (max-width: 720px) {
  .page-title-line { align-items: flex-start; flex-direction: column; }
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
