<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ArrowLeft, DArrowLeft, DArrowRight, Star, StarFilled } from '@element-plus/icons-vue'
import { ElMessage, type Sort } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import type { Bar, IndicatorRow, KlinePeriod } from '@/api/stocks'
import {
  addSectorWatchlist,
  getSector,
  getSectorBars,
  getSectorMembers,
  listSectorWatchlist,
  removeSectorWatchlist,
  type SectorDetail,
  type SectorMember,
  type SectorMemberSortField,
} from '@/api/sectors'
import AppDataTable from '@/components/AppDataTable.vue'
import AppHoverInfo from '@/components/AppHoverInfo'
import AppAsyncRegion from '@/components/AppAsyncRegion.vue'
import AppControlRow from '@/components/AppControlRow.vue'
import AppRowActions from '@/components/AppRowActions.vue'
import AppIconButton from '@/components/AppIconButton.vue'
import AppSearchInput from '@/components/AppSearchInput.vue'
import AppSplitWorkspace from '@/components/AppSplitWorkspace.vue'
import AppStateBlock from '@/components/AppStateBlock.vue'
import AppTableColumn from '@/components/AppTableColumn.vue'
import AppWorkspacePane from '@/components/AppWorkspacePane.vue'
import StockStatusTag from '@/components/StockStatusTag.vue'
import KlineRangeSelect from '@/components/KlineRangeSelect.vue'
import MarketDetailHero from '@/components/MarketDetailHero.vue'
import PageSettingsDrawer from '@/components/PageSettingsDrawer.vue'
import PageSettingsTrigger from '@/components/PageSettingsTrigger.vue'
import StockChartWorkspace from '@/components/stock-chart/StockChartWorkspace.vue'
import TradeDatePicker from '@/components/TradeDatePicker.vue'
import {
  klineRangeQueryStart,
  trimKlineRange,
  useKlinePrefs,
} from '@/composables/useKlinePrefs'
import { useComponentPageSizeSession } from '@/composables/useComponentPageSizeSession'
import { useDefaultedSessionValue } from '@/composables/useDefaultedSessionValue'
import { useRemoteLayoutConfig } from '@/composables/useRemoteLayoutConfig'
import {
  composeComponentRuntimeValueOf,
  useStockChartComponentConfig,
} from '@/composables/useStockChartComponentConfig'
import { useMarketMasterRatioRuntime } from '@/composables/useMarketMasterRatioRuntime'
import { useLegacyStockChartPreferenceMigration } from '@/composables/useLegacyStockChartPreferenceMigration'
import { useTableSort } from '@/composables/useTableSort'
import { useTradeDates } from '@/composables/useTradeDates'
import { getPageLayout } from '@/layout'
import LayoutHost from '@/layout/components/LayoutHost.vue'
import { MASTER_DETAIL_RATIO_DEFAULT } from '@/layout/masterDetailRatioProfiles'
import {
  MARKET_WORKSPACE_COMPACT_MIN_HEIGHT,
  MARKET_WORKSPACE_MIN_HEIGHT,
} from '@/layout/marketWorkspaceSizing'
import { useAuthStore } from '@/stores/auth'
import { useSectorsSessionStore } from '@/stores/sectorsSession'
import { useStockSet } from '@/stores/stockSet'
import { getErrorMessage, getErrorStatus } from '@/utils/error'
import { hasPermission } from '@/utils/permission'
import { formatMoney } from '@/utils/money'
import { createLatestRequestGuard } from '@/utils/latestRequestGuard'
import {
  sectorDetailLocation,
  sectorListLocation,
  sectorReturnLabel,
  trustedSectorReturnPath,
} from '@/utils/sectorNavigation'
import {
  formatSectorInflow,
  formatSectorPercent,
  sectorValueClass,
  toBoardChartBars,
} from '@/utils/sectorCompare'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const sectorsSession = useSectorsSessionStore()
const stockSet = useStockSet()
const { dataMin, dataMax, ensureLoaded } = useTradeDates()
// 工作标签按 path 缓存独立实例；返回列表后全局 route.params 已无 code，详情实例仍须固定自身 code。
const code = ref(String(route.params.code || ''))
const sourceReturnPath = ref(trustedSectorReturnPath(route.query.return_to) ?? '')
const returnLocation = computed(() => sectorListLocation(sourceReturnPath.value))
const returnLabel = computed(() => sectorReturnLabel(sourceReturnPath.value))
const settingsOpen = ref(false)

const layout = getPageLayout('sectors-detail')
const workspaceDefaultRatio = Number(
  layout.slots.find((slot) => slot.id === 'workspace')?.config?.masterRatio
    ?? MASTER_DETAIL_RATIO_DEFAULT,
)
const {
  effective,
  knobs: layoutKnobs,
  setKnob,
  valueOf,
  sourceOf,
  layerValuesOf,
  isDirty: layoutDirty,
  resetAll: resetLayout,
  componentValueOf,
  setComponentKnob,
  componentSourceOf,
  componentLayerValuesOf, componentAllowedLayers, remoteHydrated, whenRemoteHydrated,
  saveRemoteUserConfig, remoteSaveError,
} = useRemoteLayoutConfig(layout)
const drawerConfig = {
  knobs: layoutKnobs,
  setKnob,
  valueOf,
  sourceOf,
  layerValuesOf,
  componentValueOf,
  setComponentKnob,
  componentSourceOf,
  componentLayerValuesOf,
  componentAllowedLayers,
  save: saveRemoteUserConfig,
}

const chartPreferences = useStockChartComponentConfig({
  componentValueOf,
  setComponentKnob,
  hydrated: remoteHydrated,
})
const {
  setCurrentMasterRatioSample,
  componentRuntimeValueOf: masterRuntimeValueOf,
} = useMarketMasterRatioRuntime()
const componentRuntimeValueOf = composeComponentRuntimeValueOf(
  masterRuntimeValueOf,
  chartPreferences.componentRuntimeValueOf,
)
const splitWorkspaceRef = ref<InstanceType<typeof AppSplitWorkspace> | null>(null)
const splitCompact = ref(false)
const memberPanelVisible = ref(true)
useLegacyStockChartPreferenceMigration({
  pageKey: 'sectors-detail', componentSourceOf, setComponentKnob, whenRemoteHydrated,
  saveRemoteUserConfig, remoteSaveFailed: () => remoteSaveError.value,
})
const pageDirty = computed(() => layoutDirty.value)

const MEMBER_PAGE_SIZES = [10, 20, 30, 50]
const normalizeMemberPageSize = (value: unknown) => {
  const numeric = Number(value)
  return MEMBER_PAGE_SIZES.includes(numeric) ? numeric : 20
}
const MEMBER_SORT_FIELDS = ['pct', 'price', 'code'] as const
const { validDefault: defaultKlineRange } = useKlinePrefs()
// K 线范围单向：全局偏好默认范围 → 会话 ref；主区切换不写回全局默认。
const viewDays = useDefaultedSessionValue(defaultKlineRange)
const {
  sortBy,
  sortOrder,
  elementDefaultSort,
  onSortChange,
} = useTableSort<SectorMemberSortField>({
  slotId: 'memberTable',
  defaultSort: 'pct:desc',
  componentValueOf,
  allowedFields: MEMBER_SORT_FIELDS,
})
const hiddenColumns = computed<string[]>(() =>
  (componentValueOf('memberTable', 'hiddenColumns') as string[]) ?? [],
)
function colVisible(key: string): boolean {
  return !hiddenColumns.value.includes(key)
}
function tableBorder(slotId: string): boolean {
  return componentValueOf(slotId, 'border') === true
}

const detail = ref<SectorDetail | null>(null)
const tradeDate = ref<string | null>('')
const detailLoading = ref(false)
const detailError = ref('')
const forbidden = ref(false)
const bars = ref<Bar[]>([])
const warmupBars = ref<Bar[]>([])
const indicators = ref<IndicatorRow[]>([])
const indicatorPeriod = ref<KlinePeriod>('day')
const chartLoading = ref(false)
const chartError = ref('')
const members = ref<SectorMember[]>([])
const memberTotal = ref(0)
const memberPage = ref(1)
const memberKeyword = ref('')
const { pageSize: memberSize, changePageSize: changeMemberSize } = useComponentPageSizeSession({
  resolveDefault: () => componentValueOf('memberTable', 'pageSize'),
  normalize: normalizeMemberPageSize,
  shouldSync: () => initialized,
  resetPage: () => {
    memberPage.value = 1
  },
  reload: loadMembers,
})
const memberTradeDate = ref<string | null>(null)
const memberLoading = ref(false)
const memberError = ref('')
const watchlisted = ref(false)
const watchlistBusy = ref(false)
let requestVersion = 0
let initialized = false

function persistDetailReturnState(): void {
  if (!initialized) return
  sectorsSession.saveDetailReturnState({
    boardCode: code.value,
    tradeDate: tradeDate.value,
    memberKeyword: memberKeyword.value.trim().slice(0, 50),
    memberPage: memberPage.value,
    memberSize: memberSize.value,
    memberSortBy: sortBy.value,
    memberSortOrder: sortOrder.value,
    viewDays: viewDays.value,
    returnPath: sourceReturnPath.value,
  })
}

async function cleanDetailUrl(): Promise<void> {
  const target = sectorDetailLocation(code.value, sourceReturnPath.value)
  if (router.resolve(target).fullPath !== route.fullPath) await router.replace(target)
}

const canViewStocks = computed(() => hasPermission(auth.role, auth.permissions, 'stocks:view'))
const canViewWatchlist = computed(() =>
  hasPermission(auth.role, auth.permissions, 'sector-watchlist:view'),
)
const canUpdateWatchlist = computed(() =>
  hasPermission(auth.role, auth.permissions, 'sector-watchlist:update'),
)

async function loadDetail(): Promise<void> {
  detailLoading.value = true
  detailError.value = ''
  forbidden.value = false
  detail.value = null
  try {
    detail.value = await getSector(code.value, tradeDate.value || undefined)
  } catch (error) {
    if (getErrorStatus(error) === 403) forbidden.value = true
    detailError.value = getErrorMessage(error, '板块详情加载失败')
  } finally {
    detailLoading.value = false
  }
}

async function loadChart(): Promise<void> {
  const end = tradeDate.value || detail.value?.trade_date || dataMax.value
  if (!end) return
  const version = ++requestVersion
  chartLoading.value = true
  chartError.value = ''
  try {
    const start = klineRangeQueryStart(end, viewDays.value, dataMin.value || '2024-01-01')
    const requestedPeriod = chartPreferences.klinePeriod.value
    const data = await getSectorBars(code.value, start, end, true, requestedPeriod)
    if (version !== requestVersion) return
    const mapped = toBoardChartBars(data.list)
    // 周期是数据与缩放的共同边界，不能在“近 N 日”下再缩放回周期外历史。
    bars.value = trimKlineRange(mapped, viewDays.value)
    warmupBars.value = mapped.slice(0, Math.max(0, mapped.length - bars.value.length))
    const visibleDates = new Set(bars.value.map((bar) => bar.date))
    indicators.value = (data.indicators ?? []).filter((row) => visibleDates.has(row.trade_date))
    indicatorPeriod.value = data.period ?? requestedPeriod
  } catch (error) {
    if (version !== requestVersion) return
    indicators.value = []
    chartError.value = getErrorMessage(error, '指数走势加载失败')
  } finally {
    if (version === requestVersion) chartLoading.value = false
  }
}

const memberRequest = createLatestRequestGuard()
async function loadMembers(): Promise<void> {
  const requestId = memberRequest.begin()
  persistDetailReturnState()
  memberLoading.value = true
  memberError.value = ''
  try {
    const data = await getSectorMembers(code.value, {
      trade_date: tradeDate.value || undefined,
      keyword: memberKeyword.value.trim() || undefined,
      page: memberPage.value,
      size: memberSize.value,
      sort_by: sortBy.value,
      order: sortOrder.value,
    })
    if (!memberRequest.isCurrent(requestId)) return
    members.value = data.list
    memberTotal.value = data.total
    memberTradeDate.value = data.trade_date
    const maxPage = Math.max(1, Math.ceil(data.total / memberSize.value))
    if (memberPage.value > maxPage) {
      memberPage.value = maxPage
      await loadMembers()
    }
  } catch (error) {
    if (!memberRequest.isCurrent(requestId)) return
    memberError.value = getErrorMessage(error, '成分股加载失败')
  } finally {
    if (memberRequest.isCurrent(requestId)) memberLoading.value = false
  }
}

function searchMembers(): void {
  memberPage.value = 1
  void loadMembers()
}

async function loadAll(): Promise<void> {
  await loadDetail()
  if (!detail.value || forbidden.value) return
  await Promise.all([loadChart(), loadMembers()])
}

async function refreshSectorDetail(): Promise<void> {
  await Promise.all([loadAll(), loadWatchlistState()])
}

function returnToSource(): void {
  // 与个股详情一致：进入详情时固化可信来源，显式返回使用 push 恢复来源现场。
  void router.push(returnLocation.value)
}
function openStock(row: SectorMember): void {
  if (!canViewStocks.value) return
  persistDetailReturnState()
  const items = members.value.map((member) => ({ code: member.code, name: member.name }))
  stockSet.setResultSet(
    items,
    `${detail.value?.name || code.value}成分股`,
    `/sectors/${encodeURIComponent(code.value)}?restore=1`,
  )
  void router.push(`/stocks/${encodeURIComponent(row.code)}`)
}

async function loadWatchlistState(): Promise<void> {
  if (!canViewWatchlist.value) return
  try {
    const data = await listSectorWatchlist()
    watchlisted.value = data.list.some((row) => row.board_code === code.value)
  } catch (error) {
    ElMessage.error(getErrorMessage(error, '板块自选状态加载失败'))
  }
}
async function toggleWatchlist(): Promise<void> {
  if (!canUpdateWatchlist.value || watchlistBusy.value) return
  watchlistBusy.value = true
  try {
    if (watchlisted.value) await removeSectorWatchlist(code.value)
    else await addSectorWatchlist(code.value)
    watchlisted.value = !watchlisted.value
    ElMessage.success(watchlisted.value ? '已加入板块自选' : '已移出板块自选')
  } catch (error) {
    ElMessage.error(getErrorMessage(error, '板块自选更新失败'))
  } finally {
    watchlistBusy.value = false
  }
}

const fmtPct = formatSectorPercent
function fmtNumber(value: number | null | undefined, digits = 2): string {
  return formatMoney(value, { digits })
}
const fmtInflow = formatSectorInflow
const pctClass = sectorValueClass
function resetSettings(): void {
  chartPreferences.cancelRatioDraft()
  resetLayout()
}

function toggleMemberPanel(): void {
  if (splitCompact.value) {
    splitWorkspaceRef.value?.openCompactSecondary()
    return
  }
  memberPanelVisible.value = !memberPanelVisible.value
}

watch([sortBy, sortOrder], () => {
  if (!initialized) return
  memberPage.value = 1
  persistDetailReturnState()
  void loadMembers()
})
watch(viewDays, () => {
  if (!initialized) return
  persistDetailReturnState()
  void loadChart()
})
watch(() => chartPreferences.klinePeriod.value, () => {
  if (!initialized) return
  void loadChart()
})
watch(tradeDate, () => {
  if (!initialized) return
  memberPage.value = 1
  persistDetailReturnState()
  void loadAll()
})

watch(
  () => [route.path, route.query.restore] as const,
  ([path, restore]) => {
    if (!initialized || !path.startsWith('/sectors/') || String(route.params.code || '') !== code.value || restore !== '1') return
    const restored = sectorsSession.consumeDetailReturnState(code.value)
    if (restored?.returnPath) sourceReturnPath.value = restored.returnPath
    void cleanDetailUrl()
  },
)

onMounted(async () => {
  await ensureLoaded().catch(() => undefined)
  // 只有从个股显式返回才恢复一次性详情现场；普通进入或刷新按页面默认值初始化。
  const restored = route.query.restore === '1'
    ? sectorsSession.consumeDetailReturnState(code.value)
    : null
  if (restored) {
    tradeDate.value = typeof restored.tradeDate === 'string' ? restored.tradeDate : dataMax.value || ''
    memberKeyword.value = typeof restored.memberKeyword === 'string'
      ? restored.memberKeyword.slice(0, 50)
      : ''
    memberPage.value = Number.isInteger(restored.memberPage) && restored.memberPage > 0
      ? restored.memberPage
      : 1
    memberSize.value = normalizeMemberPageSize(restored.memberSize)
    if ((MEMBER_SORT_FIELDS as readonly string[]).includes(restored.memberSortBy)) {
      onSortChange({
        prop: restored.memberSortBy,
        order: restored.memberSortOrder === 'asc' ? 'ascending' : 'descending',
      })
    }
    viewDays.value = Number.isFinite(restored.viewDays) && restored.viewDays > 0
      ? restored.viewDays
      : defaultKlineRange.value
    sourceReturnPath.value = trustedSectorReturnPath(route.query.return_to)
      ?? trustedSectorReturnPath(restored.returnPath)
      ?? ''
  } else {
    tradeDate.value = dataMax.value || ''
  }
  initialized = true
  await cleanDetailUrl()
  await Promise.all([loadAll(), loadWatchlistState()])
})
</script>

<template>
  <LayoutHost :layout="effective">
    <template #action>
      <div class="lh-action detail-action">
        <div class="detail-nav">
          <el-button :icon="ArrowLeft" text data-testid="sector-detail-back" @click="returnToSource">
            {{ returnLabel }}
          </el-button>
          <div class="detail-actions">
            <el-button
              data-testid="sector-detail-refresh"
              :loading="detailLoading || chartLoading || memberLoading"
              @click="refreshSectorDetail"
            >刷新</el-button>
            <TradeDatePicker v-model="tradeDate" default-latest class="detail-date" />
            <PageSettingsTrigger :dirty="pageDirty" @click="settingsOpen = true" />
          </div>
        </div>
      </div>
    </template>

    <template #main>
      <AppStateBlock
        v-if="forbidden"
        state="error"
        variant="permission"
        title="无权限查看板块详情"
        description="请联系系统管理员调整权限"
      />
      <AppAsyncRegion
        v-else
        class="sector-detail"
        data-testid="sector-detail-page"
        :loading="detailLoading"
        :has-content="Boolean(detail)"
        :error="detailError"
        loading-title="正在加载板块详情…"
        error-title="板块不存在或加载失败"
        empty-title="暂无板块详情"
        retry
        @retry="loadAll"
      >
        <MarketDetailHero
          :title="detail?.name || code"
          :code="code"
          subtitle="指数趋势与历史成员强弱联动观察"
        >
          <template #badges>
            <span v-if="detail" class="sector-type">
              {{ detail.board_type === 'concept' ? '概念板块' : '行业板块' }}
            </span>
          </template>
          <template #actions>
            <AppIconButton
              v-if="canUpdateWatchlist"
              v-permission="'sector-watchlist:update'"
              :label="watchlisted ? '移出板块自选' : '加入板块自选'"
              :tooltip="watchlisted ? '移出板块自选' : '加入板块自选'"
              :loading="watchlistBusy"
              :class="{ 'watchlist-active': watchlisted }"
              @click="toggleWatchlist"
            >
              <el-icon><StarFilled v-if="watchlisted" /><Star v-else /></el-icon>
            </AppIconButton>
          </template>
        </MarketDetailHero>

        <section class="metric-strip" aria-label="板块关键指标">
          <div class="metric">
            <span>今日涨幅</span>
            <strong :class="pctClass(detail?.pct_today)">{{ fmtPct(detail?.pct_today) }}</strong>
          </div>
          <div class="metric"><span>5 日涨幅</span><strong :class="pctClass(detail?.pct_5d)">{{ fmtPct(detail?.pct_5d) }}</strong></div>
          <div class="metric"><span>20 日涨幅</span><strong :class="pctClass(detail?.pct_20d)">{{ fmtPct(detail?.pct_20d) }}</strong></div>
          <div class="metric"><span>即时净流入</span><strong :class="pctClass(detail?.net_inflow)">{{ fmtInflow(detail?.net_inflow) }}</strong></div>
          <div class="metric"><span>成员涨 / 跌</span><strong><span class="up">{{ detail?.up_count ?? '—' }}</span> / <span class="down">{{ detail?.down_count ?? '—' }}</span></strong></div>
          <div class="metric"><span>最近快照返回</span><strong>{{ detail?.member_count ?? '—' }} <small>只</small></strong></div>
          <div class="metric metric--leader"><span>成员领涨</span><strong>{{ detail?.leader_stock || '—' }} <em :class="pctClass(detail?.leader_pct)">{{ fmtPct(detail?.leader_pct) }}</em></strong></div>
        </section>

        <AppSplitWorkspace
          ref="splitWorkspaceRef"
          class="sector-detail-workspace"
          data-testid="sector-detail-workspace"
          :secondary-visible="memberPanelVisible"
          :default-primary-ratio="Number(componentValueOf('workspace', 'masterRatio') ?? workspaceDefaultRatio)"
          :primary-ratio-profiles="componentValueOf('workspace', 'masterRatioProfiles')"
          :min-height="MARKET_WORKSPACE_MIN_HEIGHT"
          :compact-min-height="MARKET_WORKSPACE_COMPACT_MIN_HEIGHT"
          secondary-drawer-title="板块成分股"
          separator-label="调整板块走势与成分股宽度"
          test-id-prefix="sector-detail"
          @update:secondary-visible="memberPanelVisible = $event"
          @primary-ratio-sample-change="setCurrentMasterRatioSample"
          @compact-change="splitCompact = $event"
        >
          <template #primary>
            <AppWorkspacePane
              title="板块走势"
              aria-label="板块指数走势"
              data-testid="sector-detail-chart-section"
            >
              <template #actions>
                <KlineRangeSelect v-model="viewDays" width="112px" test-id="sector-detail-range" />
                <AppIconButton
                  :label="splitCompact ? '查看成分股' : (memberPanelVisible ? '收起成分股，仅看走势' : '显示成分股')"
                  data-testid="sector-detail-toggle-members"
                  size="sm"
                  @click="toggleMemberPanel"
                >
                  <el-icon>
                    <DArrowRight v-if="memberPanelVisible && !splitCompact" />
                    <DArrowLeft v-else />
                  </el-icon>
                </AppIconButton>
              </template>
              <AppAsyncRegion
                class="chart-stage"
                :loading="chartLoading"
                :has-content="bars.length > 0"
                :error="chartError"
                loading-title="正在加载指数走势…"
                error-title="指数走势加载失败"
                empty-title="暂无指数走势"
                empty-description="请先运行板块指数采集，或切换交易日期"
                state-size="compact"
                retry
                @retry="loadChart"
              >
                <StockChartWorkspace
                  class="sector-chart-workspace"
                  :bars="bars"
                  :warmup-bars="warmupBars"
                  :indicators="indicators"
                  :indicators-period="indicatorPeriod"
                  :slot2="chartPreferences.preferences.value.slot2"
                  :slot3="chartPreferences.preferences.value.slot3"
                  :height-ratios="chartPreferences.currentRatios.value"
                  adjust-label="原始连续指数"
                  :zoom-start="0"
                  :zoom-end="100"
                  fit-available-height
                  aria-label="板块指数 K 线与量能联动工作区"
                  enable-return-measurement
                  enable-kline-period-switch
                  v-model:return-measurement-mode="chartPreferences.returnMeasurementMode.value"
                  v-model:kline-period="chartPreferences.klinePeriod.value"
                  @ratio-draft="chartPreferences.handleRatioDraft"
                  @ratio-commit="chartPreferences.handleRatioCommit"
                  @workspace-resize="chartPreferences.handleWorkspaceResize"
                />
              </AppAsyncRegion>
            </AppWorkspacePane>
          </template>
          <template #secondary>
            <AppWorkspacePane
              :title="memberTradeDate || detail?.trade_date || '最新交易日'"
              eyebrow="成分股"
              aria-label="板块成分股"
              :header-visible="!splitCompact"
              data-testid="sector-detail-member-section"
            >
              <template #actions>
                <span class="permission-hint">
                  {{ memberTotal }} 条 · {{ canViewStocks ? '点击查看行情' : '无个股查看权限' }}
                </span>
              </template>
              <AppControlRow class="member-filter-row" aria-label="成分股筛选">
                <AppSearchInput
                  v-model="memberKeyword"
                  class="app-control-width-long"
                  placeholder="代码 / 名称"
                  maxlength="50"
                  data-testid="sector-member-keyword"
                  @search="searchMembers"
                />
              </AppControlRow>
              <AppStateBlock v-if="memberError" state="error" size="compact" title="成分股加载失败" :description="memberError" retry @retry="loadMembers" />
              <AppDataTable
                v-else
                :data="members"
                :loading="memberLoading"
                row-key="code"
                :default-sort="elementDefaultSort"
                :border="tableBorder('memberTable')"
                :clickable="canViewStocks"
                aria-label="板块历史成分股"
                :pagination="{ currentPage: memberPage, pageSize: memberSize, total: memberTotal, pageSizes: MEMBER_PAGE_SIZES, small: true }"
                @row-click="openStock"
                @sort-change="(value: Sort) => onSortChange(value)"
                @page-change="(value: number) => { memberPage = value; void loadMembers() }"
                @size-change="changeMemberSize"
              >
                <AppTableColumn v-if="colVisible('code')" label="代码" prop="code" role="code" sortable="custom">
                  <template #default="{ row }">
                    <AppHoverInfo :disabled="canViewStocks" content="无个股行情查看权限" placement="top">
                      <span
                        :class="{ 'stock-disabled': !canViewStocks }"
                        :data-testid="row?.code ? `sector-member-${row.code}` : undefined"
                      >
                        <span class="app-inline-info app-inline-info--nowrap">
                          <span>{{ row.code }}</span>
                          <StockStatusTag v-if="!colVisible('name')" :is-st="row.is_st" :as-of-date="row.st_as_of_date" />
                        </span>
                      </span>
                    </AppHoverInfo>
                  </template>
                </AppTableColumn>
                <AppTableColumn v-if="colVisible('name')" label="名称" prop="name" role="name">
                  <template #default="{ row }">
                    <AppHoverInfo :disabled="canViewStocks" content="无个股行情查看权限" placement="top">
                      <span class="app-inline-info app-inline-info--nowrap">
                        <strong :class="{ 'stock-disabled': !canViewStocks }">{{ row.name || '—' }}</strong>
                        <StockStatusTag :is-st="row.is_st" :as-of-date="row.st_as_of_date" />
                      </span>
                    </AppHoverInfo>
                  </template>
                </AppTableColumn>
                <AppTableColumn v-if="colVisible('price')" label="现价" prop="price" role="number" sortable="custom">
                  <template #default="{ row }"><span class="app-data-text">{{ fmtNumber(row.close) }}</span></template>
                </AppTableColumn>
                <AppTableColumn v-if="colVisible('pct')" label="涨跌幅" prop="pct" role="number" sortable="custom">
                  <template #default="{ row }"><strong class="app-data-text" :class="pctClass(row.pct_chg)">{{ fmtPct(row.pct_chg) }}</strong></template>
                </AppTableColumn>
                <AppTableColumn v-if="colVisible('turnover')" label="换手率" prop="turnover_rate" role="number">
                  <template #default="{ row }"><span class="app-data-text">{{ fmtPct(row.turnover_rate) }}</span></template>
                </AppTableColumn>
                <AppTableColumn v-if="canViewStocks" label="操作" role="action-compact">
                  <template #default="{ row }">
                    <AppRowActions :aria-label="`${row.name || row.code} 行操作`" :actions="[{ key: 'view', label: '查看行情', onClick: () => openStock(row) }]" />
                  </template>
                </AppTableColumn>
                <template #empty>
                  {{ memberKeyword.trim() ? '没有匹配的成分股，请更换代码或名称' : '暂无成分股数据，请先运行板块成分采集' }}
                </template>
              </AppDataTable>
            </AppWorkspacePane>
          </template>
        </AppSplitWorkspace>
      </AppAsyncRegion>
    </template>

    <template #overlays>
      <PageSettingsDrawer
        v-model="settingsOpen"
        title="板块详情"
        page-key="sectors-detail"
        :dirty="pageDirty"
        :config="drawerConfig"
        :business-visible="true"
        :component-runtime-value-of="componentRuntimeValueOf"
        @reset="resetSettings"
      >
      </PageSettingsDrawer>
    </template>
  </LayoutHost>
</template>

<style scoped>
.detail-action,
.detail-nav,
.detail-actions {
  display: flex;
  align-items: center;
}
.detail-nav {
  justify-content: space-between;
  gap: var(--app-space-3);
  width: 100%;
}
.detail-actions {
  gap: var(--app-space-2);
}
.detail-date {
  width: 164px;
}
.sector-detail {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-3);
  min-width: 0;
  min-height: 0;
  height: 100%;
  overflow: hidden;
}
.metric-strip {
  border: 1px solid var(--el-border-color);
  border-radius: var(--layout-card-radius);
  background: var(--el-bg-color);
}
.sector-type {
  padding: 3px 8px;
  border-radius: 999px;
  color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
  font-size: var(--app-font-size-caption);
  font-weight: var(--app-font-weight-strong);
}
.watchlist-active {
  color: var(--el-color-primary);
}
.metric-strip {
  flex: 0 0 auto;
  display: grid;
  grid-template-columns: repeat(7, minmax(104px, 1fr));
  overflow-x: auto;
}
.metric {
  min-width: 104px;
  padding: var(--app-space-3);
  border-right: 1px solid var(--el-border-color-lighter);
}
.metric:last-child {
  border-right: 0;
}
.metric > span {
  display: block;
  margin-bottom: var(--app-space-1);
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
}
.metric strong {
  white-space: nowrap;
  font-size: var(--app-font-size-data);
  font-weight: var(--app-font-weight-section);
  line-height: var(--app-line-height-data);
}
.metric--leader {
  min-width: 154px;
}
.metric small,
.metric em {
  font-size: var(--app-font-size-caption);
  font-style: normal;
}
.sector-detail-workspace {
  flex: 1 1 auto;
  min-height: 0;
}
.chart-stage {
  display: flex;
  flex: 1 1 auto;
  height: 100%;
  min-height: 0;
}
.sector-chart-workspace {
  flex: 1 1 auto;
  width: 100%;
  min-height: 0;
  border: 0;
  border-radius: 0;
}
.permission-hint {
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
}
.member-filter-row {
  flex: 0 0 auto;
  padding: var(--app-space-3) var(--app-space-4);
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.stock-disabled {
  color: var(--el-text-color-secondary);
  cursor: not-allowed;
}
.metric strong .up {
  display: inline;
  font-style: normal;
}
.metric strong .down {
  display: inline;
  font-style: normal;
}
@container app-viewport (max-width: 1120px) {
  .metric-strip { grid-template-columns: repeat(4, minmax(132px, 1fr)); }
}
</style>
