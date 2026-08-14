<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ArrowLeft, Star, StarFilled } from '@element-plus/icons-vue'
import { ElMessage, type Sort } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import type { Bar, IndicatorRow } from '@/api/stocks'
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
import AppIconButton from '@/components/AppIconButton.vue'
import AppStateBlock from '@/components/AppStateBlock.vue'
import AppTableColumn from '@/components/AppTableColumn.vue'
import KlineSettingSection from '@/components/KlineSettingSection.vue'
import KlineRangeSelect from '@/components/KlineRangeSelect.vue'
import PageSettingsDrawer from '@/components/PageSettingsDrawer.vue'
import PageSettingsTrigger from '@/components/PageSettingsTrigger.vue'
import StockChartSettingSection from '@/components/StockChartSettingSection.vue'
import StockChartWorkspace from '@/components/stock-chart/StockChartWorkspace.vue'
import TradeDatePicker from '@/components/TradeDatePicker.vue'
import {
  klineRangeQueryStart,
  trimKlineRange,
  useKlinePrefs,
} from '@/composables/useKlinePrefs'
import { usePageSettings } from '@/composables/usePageSettings'
import { useRemoteLayoutConfig } from '@/composables/useRemoteLayoutConfig'
import {
  createDefaultStockChartPreferences,
  useStockChartPreferences,
  type AuxiliaryChartSlot,
} from '@/composables/useStockChartPreferences'
import { useTableSort } from '@/composables/useTableSort'
import { useTradeDates } from '@/composables/useTradeDates'
import { getPageLayout } from '@/layout'
import LayoutHost from '@/layout/components/LayoutHost.vue'
import { resolveComponentNumberValue } from '@/layout/componentConfig'
import { useAuthStore } from '@/stores/auth'
import { useStockSet } from '@/stores/stockSet'
import { getErrorMessage, getErrorStatus } from '@/utils/error'
import { hasPermission } from '@/utils/permission'
import {
  sanitizeSectorSourceQuery,
  sectorListLocation,
  toLocationQuery,
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
const stockSet = useStockSet()
const { dataMin, dataMax, ensureLoaded } = useTradeDates()
// 工作标签按 path 缓存独立实例；返回列表后全局 route.params 已无 code，详情实例仍须固定自身 code。
const code = ref(String(route.params.code || ''))
const sourceQuery = computed(() => sanitizeSectorSourceQuery(route.query))
const settingsOpen = ref(false)

const layout = getPageLayout('sectors-detail')
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
  componentLayerValuesOf,
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
}

const detailDefaults = { charts: createDefaultStockChartPreferences() }
const {
  settings,
  isDirty: settingsDirty,
  reset: resetPageSettings,
  hydrated,
} = usePageSettings('sectors-detail', detailDefaults)
const chartSettings = computed({
  get: () => settings.charts,
  set: (value) => {
    settings.charts = value
  },
})
const chartPreferences = useStockChartPreferences(chartSettings, hydrated)
const pageDirty = computed(() => layoutDirty.value || settingsDirty.value)

const MEMBER_PAGE_SIZES = [10, 20, 30, 50]
const MEMBER_SORT_FIELDS = ['pct', 'code'] as const
const { validDefault: defaultKlineRange } = useKlinePrefs()
const viewDays = ref(defaultKlineRange.value)
const {
  sortBy,
  sortOrder,
  elementDefaultSort,
  onSortChange,
} = useTableSort<SectorMemberSortField>({
  slotId: 'memberTable',
  defaultSort: 'pct:desc',
  componentValueOf,
  setComponentKnob,
  allowedFields: MEMBER_SORT_FIELDS,
})
const configuredPageSize = computed(() => {
  const value = Number(componentValueOf('memberTable', 'pageSize'))
  return MEMBER_PAGE_SIZES.includes(value) ? value : 20
})
const hiddenColumns = computed<string[]>(() =>
  (componentValueOf('memberTable', 'hiddenColumns') as string[]) ?? [],
)
const chartDefaultHeight = Number(
  layout.slots.find((slot) => slot.id === 'chart')?.config?.minHeight,
)
const configuredChartHeight = computed(() => resolveComponentNumberValue(
  'chart',
  'minHeight',
  componentValueOf('chart', 'minHeight'),
  chartDefaultHeight,
))
const chartWorkspaceMinHeight = computed(() => Math.max(384, configuredChartHeight.value - 80))
function colVisible(key: string): boolean {
  return !hiddenColumns.value.includes(key)
}
function tableBorder(slotId: string): boolean {
  return componentValueOf(slotId, 'border') === true
}

const detail = ref<SectorDetail | null>(null)
const tradeDate = ref<string | null>(sourceQuery.value.date ?? '')
const detailLoading = ref(false)
const detailError = ref('')
const forbidden = ref(false)
const bars = ref<Bar[]>([])
const indicators = ref<IndicatorRow[]>([])
const chartLoading = ref(false)
const chartError = ref('')
const members = ref<SectorMember[]>([])
const memberTotal = ref(0)
const memberPage = ref(1)
const memberSize = ref(configuredPageSize.value)
const memberTradeDate = ref<string | null>(null)
const memberLoading = ref(false)
const memberError = ref('')
const watchlisted = ref(false)
const watchlistBusy = ref(false)
let requestVersion = 0
let initialized = false

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
    const data = await getSectorBars(code.value, start, end, true)
    if (version !== requestVersion) return
    const mapped = toBoardChartBars(data.list)
    // 周期是数据与缩放的共同边界，不能在“近 N 日”下再缩放回周期外历史。
    bars.value = trimKlineRange(mapped, viewDays.value)
    const visibleDates = new Set(bars.value.map((bar) => bar.date))
    indicators.value = (data.indicators ?? []).filter((row) => visibleDates.has(row.trade_date))
  } catch (error) {
    if (version !== requestVersion) return
    indicators.value = []
    chartError.value = getErrorMessage(error, '指数走势加载失败')
  } finally {
    if (version === requestVersion) chartLoading.value = false
  }
}

async function loadMembers(): Promise<void> {
  memberLoading.value = true
  memberError.value = ''
  try {
    const data = await getSectorMembers(code.value, {
      trade_date: tradeDate.value || undefined,
      page: memberPage.value,
      size: memberSize.value,
      sort_by: sortBy.value,
      order: sortOrder.value,
    })
    members.value = data.list
    memberTotal.value = data.total
    memberTradeDate.value = data.trade_date
    const maxPage = Math.max(1, Math.ceil(data.total / memberSize.value))
    if (memberPage.value > maxPage) {
      memberPage.value = maxPage
      await loadMembers()
    }
  } catch (error) {
    memberError.value = getErrorMessage(error, '成分股加载失败')
  } finally {
    memberLoading.value = false
  }
}

async function loadAll(): Promise<void> {
  await loadDetail()
  if (!detail.value || forbidden.value) return
  await Promise.all([loadChart(), loadMembers()])
}

function returnToList(): void {
  void router.replace(sectorListLocation(route.query))
}
function openStock(row: SectorMember): void {
  if (!canViewStocks.value) return
  const items = members.value.map((member) => ({ code: member.code, name: member.name }))
  stockSet.setSet('list', items, `${detail.value?.name || code.value}成分股`, '', {
    total: items.length,
    loadedPages: [1],
    pageSize: Math.max(items.length, 1),
    returnPath: route.fullPath,
  })
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
  return value === null || value === undefined ? '—' : value.toFixed(digits)
}
const fmtInflow = formatSectorInflow
const pctClass = sectorValueClass
function resetSettings(): void {
  chartPreferences.cancelRatioDraft()
  resetPageSettings()
  resetLayout()
}

function handleRatioDraft(ratios: number[]): void {
  chartPreferences.updateRatioDraft(ratios)
}

function handleRatioCommit(ratios: number[]): void {
  chartPreferences.updateRatioDraft(ratios)
  chartPreferences.commitRatioDraft()
}

function setAuxiliaryChart(slot: AuxiliaryChartSlot, value: string | number | boolean): void {
  chartPreferences.setSlotType(slot, value)
}

watch([sortBy, sortOrder], () => {
  if (!initialized) return
  memberPage.value = 1
  void loadMembers()
})
watch(configuredPageSize, (value) => {
  memberSize.value = value
  if (!initialized) return
  memberPage.value = 1
  void loadMembers()
})
watch(viewDays, () => {
  if (!initialized) return
  void loadChart()
})
watch(tradeDate, (value) => {
  if (!initialized) return
  const next = { ...sourceQuery.value, ...(value ? { date: value } : {}) }
  void router.replace({ path: route.path, query: toLocationQuery(next) })
  memberPage.value = 1
  void loadAll()
})
onMounted(async () => {
  await ensureLoaded().catch(() => undefined)
  if (!tradeDate.value) tradeDate.value = dataMax.value || ''
  initialized = true
  await Promise.all([loadAll(), loadWatchlistState()])
})
</script>

<template>
  <LayoutHost :layout="effective">
    <template #action>
      <div class="lh-action detail-action">
        <div class="detail-nav">
          <el-button :icon="ArrowLeft" text data-testid="sector-detail-back" @click="returnToList">
            返回板块行情
          </el-button>
          <div class="detail-actions">
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
      <AppStateBlock
        v-else-if="detailError && !detail"
        state="error"
        title="板块不存在或加载失败"
        :description="detailError"
        retry
        @retry="loadAll"
      />
      <div v-else class="sector-detail" v-loading="detailLoading" data-testid="sector-detail-page">
        <section class="hero-panel">
          <div class="hero-copy">
            <div class="hero-kicker">SECTOR INTELLIGENCE</div>
            <div class="hero-title-row">
              <h2 class="app-page-title">{{ detail?.name || code }}</h2>
              <span v-if="detail" class="sector-type">
                {{ detail.board_type === 'concept' ? '概念板块' : '行业板块' }}
              </span>
              <span class="sector-code">{{ code }}</span>
              <AppIconButton
                v-if="canUpdateWatchlist"
                v-permission="'sector-watchlist:update'"
                :label="watchlisted ? '移出板块自选' : '加入板块自选'"
                :loading="watchlistBusy"
                :class="{ 'watchlist-active': watchlisted }"
                @click="toggleWatchlist"
              >
                <el-icon><StarFilled v-if="watchlisted" /><Star v-else /></el-icon>
              </AppIconButton>
            </div>
            <p>指数趋势与历史累计成员强弱联动观察</p>
          </div>
          <div class="hero-date app-caption-text">
            行情 {{ detail?.trade_date || '—' }} · 资金 {{ detail?.fund_flow_date || '—' }}
          </div>
        </section>

        <section class="metric-strip" aria-label="板块关键指标">
          <div class="metric metric--primary">
            <span>今日涨幅</span>
            <strong :class="pctClass(detail?.pct_today)">{{ fmtPct(detail?.pct_today) }}</strong>
          </div>
          <div class="metric"><span>5 日</span><strong :class="pctClass(detail?.pct_5d)">{{ fmtPct(detail?.pct_5d) }}</strong></div>
          <div class="metric"><span>20 日</span><strong :class="pctClass(detail?.pct_20d)">{{ fmtPct(detail?.pct_20d) }}</strong></div>
          <div class="metric"><span>即时净流入</span><strong :class="pctClass(detail?.net_inflow)">{{ fmtInflow(detail?.net_inflow) }}</strong></div>
          <div class="metric"><span>累计成员涨 / 跌</span><strong><i class="up">{{ detail?.up_count ?? '—' }}</i> / <i class="down">{{ detail?.down_count ?? '—' }}</i></strong></div>
          <div class="metric"><span>最近快照返回</span><strong>{{ detail?.member_count ?? '—' }} <small>只</small></strong></div>
          <div class="metric metric--leader"><span>累计成员领涨</span><strong>{{ detail?.leader_stock || '—' }} <em :class="pctClass(detail?.leader_pct)">{{ fmtPct(detail?.leader_pct) }}</em></strong></div>
        </section>

        <section
          class="content-panel chart-section"
          data-testid="sector-detail-chart-section"
          :data-configured-height="configuredChartHeight"
          :style="{ flexBasis: `${configuredChartHeight}px` }"
        >
          <header class="section-head">
            <div>
              <h3 class="app-section-title">板块指数</h3>
              <p class="app-caption-text">原始连续指数 · 开高低收与量能</p>
            </div>
            <KlineRangeSelect v-model="viewDays" width="112px" test-id="sector-detail-range" />
          </header>
          <div class="chart-stage" v-loading="chartLoading">
            <AppStateBlock v-if="chartError" state="error" size="compact" title="指数走势加载失败" :description="chartError" retry @retry="loadChart" />
            <AppStateBlock v-else-if="!chartLoading && !bars.length" state="empty" size="compact" title="暂无指数走势" description="请先运行板块指数采集，或切换交易日期" />
            <StockChartWorkspace
              v-else
              class="sector-chart-workspace"
              :bars="bars"
              :indicators="indicators"
              :slot2="chartPreferences.preferences.value.slot2"
              :slot3="chartPreferences.preferences.value.slot3"
              :height-ratios="chartPreferences.currentRatios.value"
              adjust-label="原始连续指数"
              :min-height="chartWorkspaceMinHeight"
              :zoom-start="0"
              :zoom-end="100"
              aria-label="板块指数 K 线与量能联动工作区"
              @ratio-draft="handleRatioDraft"
              @ratio-commit="handleRatioCommit"
            />
          </div>
        </section>

        <section class="content-panel member-section" data-testid="sector-detail-member-section">
          <header class="section-head">
            <div>
              <h3 class="app-section-title">历史累计成分股</h3>
              <p class="app-caption-text">{{ memberTradeDate || detail?.trade_date || '最新交易日' }} · {{ memberTotal }} 条累计关系</p>
            </div>
            <span class="permission-hint">{{ canViewStocks ? '点击成分股进入个股行情' : '当前账号无个股行情查看权限' }}</span>
          </header>
          <AppStateBlock v-if="memberError" state="error" size="compact" title="成分股加载失败" :description="memberError" retry @retry="loadMembers" />
          <AppDataTable
            v-else
            :data="members"
            :loading="memberLoading"
            row-key="code"
            :default-sort="elementDefaultSort"
            :border="tableBorder('memberTable')"
            :clickable="canViewStocks"
            aria-label="板块历史累计成分股"
            :pagination="{ currentPage: memberPage, pageSize: memberSize, total: memberTotal, pageSizes: MEMBER_PAGE_SIZES, small: true }"
            @row-click="openStock"
            @sort-change="(value: Sort) => onSortChange(value)"
            @page-change="(value: number) => { memberPage = value; void loadMembers() }"
            @size-change="(value: number) => { memberSize = value; memberPage = 1; void loadMembers() }"
          >
            <AppTableColumn v-if="colVisible('code')" label="代码" prop="code" role="code" sortable="custom">
              <template #default="{ row }">
                <el-tooltip :disabled="canViewStocks" content="无个股行情查看权限" placement="top">
                  <span
                    :class="{ 'stock-link': canViewStocks, 'stock-disabled': !canViewStocks }"
                    :data-testid="row?.code ? `sector-member-${row.code}` : undefined"
                  >{{ row.code }}</span>
                </el-tooltip>
              </template>
            </AppTableColumn>
            <AppTableColumn v-if="colVisible('name')" label="名称" prop="name" role="name">
              <template #default="{ row }">
                <el-tooltip :disabled="canViewStocks" content="无个股行情查看权限" placement="top">
                  <strong :class="{ 'stock-link': canViewStocks, 'stock-disabled': !canViewStocks }">{{ row.name || '—' }}</strong>
                </el-tooltip>
              </template>
            </AppTableColumn>
            <AppTableColumn v-if="colVisible('price')" label="现价" prop="close" role="number" align="right">
              <template #default="{ row }"><span class="app-data-text">{{ fmtNumber(row.close) }}</span></template>
            </AppTableColumn>
            <AppTableColumn v-if="colVisible('pct')" label="涨跌幅" prop="pct" role="number" align="right" sortable="custom">
              <template #default="{ row }"><strong class="app-data-text" :class="pctClass(row.pct_chg)">{{ fmtPct(row.pct_chg) }}</strong></template>
            </AppTableColumn>
            <AppTableColumn v-if="colVisible('turnover')" label="换手率" prop="turnover_rate" role="number" align="right">
              <template #default="{ row }"><span class="app-data-text">{{ fmtPct(row.turnover_rate) }}</span></template>
            </AppTableColumn>
            <template #empty>暂无成分股数据，请先运行板块成分采集</template>
          </AppDataTable>
        </section>
      </div>
    </template>

    <template #overlays>
      <PageSettingsDrawer
        v-model="settingsOpen"
        title="板块详情"
        page-key="sectors-detail"
        :dirty="pageDirty"
        :config="drawerConfig"
        @reset="resetSettings"
      >
        <template #business>
          <StockChartSettingSection
            :slot2="chartPreferences.preferences.value.slot2"
            :slot3="chartPreferences.preferences.value.slot3"
            test-id-prefix="sector-detail-chart"
            @change="setAuxiliaryChart"
          />
          <KlineSettingSection />
        </template>
      </PageSettingsDrawer>
    </template>
  </LayoutHost>
</template>

<style scoped>
.detail-action,
.detail-nav,
.detail-actions,
.hero-title-row,
.section-head {
  display: flex;
  align-items: center;
}
.detail-nav,
.section-head {
  justify-content: space-between;
  gap: var(--app-space-3);
  width: 100%;
}
.detail-actions,
.hero-title-row {
  gap: var(--app-space-2);
}
.detail-date {
  width: 164px;
}
.sector-detail {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-3);
  min-width: 860px;
  min-height: 0;
  height: 100%;
  overflow: auto;
}
.hero-panel,
.metric-strip,
.content-panel {
  border: 1px solid var(--el-border-color);
  border-radius: var(--layout-card-radius);
  background: var(--el-bg-color);
}
.hero-panel {
  flex: 0 0 auto;
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--app-space-4);
  padding: var(--app-space-3) var(--app-space-4);
  background: linear-gradient(115deg, color-mix(in srgb, var(--el-color-primary-light-9) 72%, var(--el-bg-color)), var(--el-bg-color) 62%);
}
.hero-kicker {
  color: var(--el-color-primary);
  font-size: var(--app-font-size-micro);
  font-weight: var(--app-font-weight-strong);
  letter-spacing: 0.14em;
}
.hero-title-row {
  margin-top: var(--app-space-1);
}
.hero-copy p,
.section-head p {
  margin: var(--app-space-1) 0 0;
  color: var(--el-text-color-secondary);
}
.sector-type {
  padding: 3px 8px;
  border-radius: 999px;
  color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
  font-size: var(--app-font-size-caption);
  font-weight: var(--app-font-weight-strong);
}
.sector-code {
  color: var(--el-text-color-secondary);
  font-family: var(--app-font-family-mono);
  font-size: var(--app-font-size-caption);
}
.watchlist-active {
  color: var(--el-color-warning);
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
.metric span {
  display: block;
  margin-bottom: var(--app-space-1);
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
}
.metric strong {
  white-space: nowrap;
  font-size: var(--app-font-size-subtitle);
  font-weight: var(--app-font-weight-strong);
}
.metric--primary {
  background: color-mix(in srgb, var(--el-color-primary-light-9) 52%, transparent);
}
.metric--leader {
  min-width: 154px;
}
.metric small,
.metric em {
  font-size: var(--app-font-size-caption);
  font-style: normal;
}
.content-panel {
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}
.chart-section {
  flex: 0 0 560px;
}
.member-section {
  flex: 1 0 420px;
}
.section-head {
  flex: 0 0 auto;
  padding: var(--app-space-3) var(--app-space-4);
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.chart-stage {
  flex: 1;
  min-height: 0;
}
.sector-chart-workspace {
  height: 100%;
  border: 0;
  border-radius: 0;
}
.permission-hint {
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
}
.stock-link {
  color: var(--el-color-primary);
}
.stock-disabled {
  color: var(--el-text-color-secondary);
  cursor: not-allowed;
}
.up { color: var(--market-up-color); }
.down { color: var(--market-down-color); }
.muted { color: var(--el-text-color-secondary); }
@media (max-width: 1120px) {
  .metric-strip { grid-template-columns: repeat(4, minmax(132px, 1fr)); }
}
</style>
