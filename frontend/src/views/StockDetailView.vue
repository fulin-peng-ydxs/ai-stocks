<script setup lang="ts">
import {
  computed,
  onActivated,
  onBeforeUnmount,
  onDeactivated,
  onMounted,
  ref,
  watch,
} from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft, ArrowRight, Close, DArrowLeft, DArrowRight } from '@element-plus/icons-vue'
import {
  getBars,
  getIndicators,
  getStockBoardMembership,
  getStockQuoteSummary,
  getTradeEval,
  listStocks,
  type Bar,
  type IndicatorField,
  type IndicatorRow,
  type StockBoardMembership,
  type StockBasic,
  type StockQuoteSummary as StockQuoteSummaryData,
  type TradeEval,
} from '@/api/stocks'
import { addMembers, getGroup, listGroups, removeMembers, type GroupSummary } from '@/api/stockGroup'
import { browseTradeProfiles, copyTradeProfile, listTradeProfiles, type TradeProfileSummary } from '@/api/tradeProfile'
import AppIconButton from '@/components/AppIconButton.vue'
import AppDetailField from '@/components/AppDetailField.vue'
import AppDetailFields from '@/components/AppDetailFields.vue'
import AppWorkspacePane from '@/components/AppWorkspacePane.vue'
import AssetProfileSelect from '@/components/asset-search/AssetProfileSelect.vue'
import AppStateBlock from '@/components/AppStateBlock.vue'
import PageSegmented from '@/components/PageSegmented.vue'
import PageSettingSection from '@/components/PageSettingSection.vue'
import PageSettingItem from '@/components/PageSettingItem.vue'
import PageSettingsDrawer from '@/components/PageSettingsDrawer.vue'
import PageSettingsTrigger from '@/components/PageSettingsTrigger.vue'
import PageToggleRow from '@/components/PageToggleRow.vue'
import KlineRangeSelect from '@/components/KlineRangeSelect.vue'
import KlineSettingSection from '@/components/KlineSettingSection.vue'
import MarketDetailHero from '@/components/MarketDetailHero.vue'
import AppSplitWorkspace from '@/components/AppSplitWorkspace.vue'
import StockGroupFavoriteButton from '@/components/StockGroupFavoriteButton.vue'
import StockBoardMembershipPanel from '@/components/StockBoardMembershipPanel.vue'
import StockChartWorkspace from '@/components/stock-chart/StockChartWorkspace.vue'
import StockIntradayDialog from '@/components/stock-chart/StockIntradayDialog.vue'
import StockQuoteSummary from '@/components/stock-chart/StockQuoteSummary.vue'
import {
  formatAmount,
  formatChartNumber,
  formatShares,
  priceDirectionTone,
  stockVolumeRatioAt,
} from '@/components/stock-chart/chartUtils'
import type { StockQuoteSummaryModel, StockQuoteTone } from '@/components/stock-chart/stockQuoteSummary'
import type { MacdPanelState } from '@/components/stock-chart/workspaceOptions'
import { useStockSet } from '@/stores/stockSet'
import { useAuthStore } from '@/stores/auth'
import { hasPermission } from '@/utils/permission'
import { getErrorMessage, getErrorStatus } from '@/utils/error'
import { detailReturnLabel, trustedDetailReturnPath } from '@/utils/detailReturnNavigation'
import { formatCompactMoneyYuan } from '@/utils/money'
import { stockGroupTagStyle } from '@/utils/stockGroupPresentation'
import {
  APP_BOTTOM_FLOATING_FALLBACKS,
  APP_BOTTOM_FLOATING_PLACEMENT,
} from '@/utils/floatingPlacement'
import { usePageSettings } from '@/composables/usePageSettings'
import { useDefaultedSessionValue } from '@/composables/useDefaultedSessionValue'
import { useStockIntradayDrilldown } from '@/composables/useStockIntradayDrilldown'
import { useDebouncedQuery } from '@/composables/useDebouncedQuery'
import type { AssetBrowseParams, ProfileSummary } from '@/components/asset-search/types'
import { useKlinePrefs } from '@/composables/useKlinePrefs'
import {
  composeComponentRuntimeValueOf,
  useStockChartComponentConfig,
} from '@/composables/useStockChartComponentConfig'
import { useMarketMasterRatioRuntime } from '@/composables/useMarketMasterRatioRuntime'
import { useLegacyStockChartPreferenceMigration } from '@/composables/useLegacyStockChartPreferenceMigration'
import LayoutHost from '@/layout/components/LayoutHost.vue'
import { getPageLayout } from '@/layout'
import { MASTER_DETAIL_RATIO_DEFAULT } from '@/layout/masterDetailRatioProfiles'
import {
  MARKET_WORKSPACE_COMPACT_MIN_HEIGHT,
  MARKET_WORKSPACE_MIN_HEIGHT,
} from '@/layout/marketWorkspaceSizing'
import { useRemoteLayoutConfig } from '@/composables/useRemoteLayoutConfig'

const route = useRoute()
const router = useRouter()
// 工作标签按 path 缓存独立实例；代码固定为该实例创建时的路由，避免停用标签监听全局路由后被其他个股标签串改。
const code = ref(String(route.params.code))
const settingsOpen = ref(false)

// 布局声明统一取自 pageRegistry（单一事实源），不再页面内联手写 PageLayout。
const detailLayout = getPageLayout('stock-detail')
const detailWorkspaceDefaultRatio = Number(
  detailLayout.slots.find((slot) => slot.id === 'workspace')?.config?.masterRatio
    ?? MASTER_DETAIL_RATIO_DEFAULT,
)
const {
  effective: detailEffective,
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
  componentLayerValuesOf, componentAllowedLayers, remoteHydrated, whenRemoteHydrated,
  saveRemoteUserConfig, remoteSaveError,
} = useRemoteLayoutConfig(detailLayout)

// 抽屉的布局、分栏比例与图表组合由 PageSettingsDrawer 按 pageRegistry 元数据统一渲染。
const drawerConfig = { knobs: layoutKnobs, valueOf, sourceOf, setKnob, componentValueOf, setComponentKnob, componentSourceOf, layerValuesOf, componentLayerValuesOf, componentAllowedLayers, save: saveRemoteUserConfig }
const detailDefaults = {
  adjustMode: 'qfq' as '' | 'qfq' | 'hfq',
  klineOperationBarExpanded: false,
  klineMeasurementMode: 'latest' as 'latest' | 'range',
  showTradeCard: true,
  showIndicatorSnapshot: true,
  showRelatedBoards: true,
  showNav: true,
  indicators: {
    ma20: true,
    ma60: true,
    dist_to_high_2y: true,
    is_high_2y: true,
    is_bull_arrange: true,
    ma20_up: true,
    is_platform_breakout: true,
    is_vol_breakout: true,
  },
}
const { settings, isDirty, reset } = usePageSettings('stock-detail', detailDefaults)
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
const auxiliaryVisible = ref(true)
const klineOperationBarExpanded = useDefaultedSessionValue(computed(() => (
  Boolean(settings.klineOperationBarExpanded)
)))
const klineMeasurementMode = useDefaultedSessionValue(computed<'latest' | 'range'>(() => (
  settings.klineMeasurementMode === 'range' ? 'range' : 'latest'
)))
useLegacyStockChartPreferenceMigration({
  pageKey: 'stock-detail', componentSourceOf, setComponentKnob, whenRemoteHydrated,
  saveRemoteUserConfig, remoteSaveFailed: () => remoteSaveError.value,
})

function resetDetailSettings(): void {
  chartPreferences.cancelRatioDraft()
  reset()
  resetLayout()
}

// ── 通用导航：当前集合（分组成员 / 列表勾选 / 查询结果）上一个·下一个·直选 ──
const stockSet = useStockSet()
const auth = useAuthStore()
const canViewGroups = computed(() => hasPermission(auth.role, auth.permissions, 'stock-group:view'))
const canUpdateGroups = computed(() => (
  canViewGroups.value
  && hasPermission(auth.role, auth.permissions, 'stock-group:member-update')
))
const canViewTradeProfiles = computed(() => (
  hasPermission(auth.role, auth.permissions, 'trade-profile:view')
))
const canEvaluateTrades = computed(() => (
  hasPermission(auth.role, auth.permissions, 'stocks:trade-eval')
))
const canViewSectors = computed(() => hasPermission(auth.role, auth.permissions, 'sectors:view'))
const canUseTradeEvaluation = computed(() => (
  canViewTradeProfiles.value && canEvaluateTrades.value
))
const hasAuxiliaryContent = computed(() => (
  settings.showRelatedBoards
  || settings.showIndicatorSnapshot
  || (settings.showTradeCard && canUseTradeEvaluation.value)
))
const showAuxiliary = computed(() => auxiliaryVisible.value && hasAuxiliaryContent.value)

function toggleAuxiliaryPanel(): void {
  if (splitWorkspaceRef.value?.openCompactSecondary()) {
    auxiliaryVisible.value = true
    return
  }
  auxiliaryVisible.value = !auxiliaryVisible.value
}
const setIndex = computed(() => stockSet.indexOf(code.value))
const inSet = computed(() => setIndex.value >= 0)
const prevCode = computed(() => stockSet.neighbor(code.value, -1))
const nextCode = computed(() => stockSet.neighbor(code.value, 1))
function neighborLabel(target: string | null, direction: '上一只' | '下一只'): string {
  if (!target) return direction
  const item = stockSet.items.find((candidate) => candidate.code === target)
  return `${direction} · ${item?.name || target}`
}
const prevLabel = computed(() => neighborLabel(prevCode.value, '上一只'))
const nextLabel = computed(() => neighborLabel(nextCode.value, '下一只'))
function gotoCode(c: string | null) {
  if (c && c !== '__more__' && c !== code.value) router.push(`/stocks/${c}`)
}
const returnLocation = computed(() => (
  inSet.value
    ? (trustedDetailReturnPath(stockSet.returnPath) || '/stocks?restore=1')
    : '/stocks?restore=1'
))
const returnLabel = computed(() => detailReturnLabel(returnLocation.value, '返回个股查询'))
function returnToCollection() {
  // returnPath 由来源页（榜单/板块等）进详情时写入，仅在当前 code 仍属于该集合时可信；
  // 直接从菜单/标签/链接进入（code 不在集合中）时用残留 returnPath 会错回旧来源页，统一归位列表。
  router.push(returnLocation.value)
}
const collectionTotal = computed(() => stockSet.total || stockSet.items.length)
const collectionTotalPages = computed(() => Math.max(1, Math.ceil(collectionTotal.value / Math.max(stockSet.pageSize || 20, 1))))
const minLoadedPage = computed(() => stockSet.loadedPages.length ? Math.min(...stockSet.loadedPages) : 1)
const maxLoadedPage = computed(() => stockSet.loadedPages.length ? Math.max(...stockSet.loadedPages) : 1)
const canUseCollectionQuery = computed(() => !stockSet.query || stockSet.query.kind !== 'group' || canViewGroups.value)
const canLoadPrev = computed(() => !!stockSet.query && canUseCollectionQuery.value && minLoadedPage.value > 1)
const canLoadNext = computed(() => !!stockSet.query && canUseCollectionQuery.value && maxLoadedPage.value < collectionTotalPages.value)
const setLoading = ref(false)
function clearUnauthorizedGroupSet() {
  if (canViewGroups.value) return
  stockSet.clearGroupContext()
}
async function loadSetPage(page: number) {
  if (!stockSet.query || stockSet.loadedPages.includes(page)) return
  if (stockSet.query.kind === 'group' && !canViewGroups.value) {
    stockSet.clearGroupContext()
    return
  }
  setLoading.value = true
  try {
    if (stockSet.query.kind === 'group') {
      const data = await getGroup(stockSet.query.groupId, { ...stockSet.query.params, page, size: stockSet.pageSize })
      stockSet.appendPage(data.members.list.map((r) => ({ code: r.code, name: r.name })), page)
      stockSet.setTotal(data.members.total)
    } else {
      const data = await listStocks({ ...stockSet.query.params, page, size: stockSet.pageSize })
      stockSet.appendPage(data.list.map((r) => ({ code: r.code, name: r.name })), page)
      stockSet.setTotal(data.total)
    }
  } finally {
    setLoading.value = false
  }
}
async function gotoNeighbor(dir: -1 | 1) {
  const c = stockSet.neighbor(code.value, dir)
  if (c) return gotoCode(c)
  if (dir < 0 && canLoadPrev.value) {
    await loadSetPage(minLoadedPage.value - 1)
    return gotoCode(stockSet.neighbor(code.value, dir))
  }
  if (dir > 0 && canLoadNext.value) {
    await loadSetPage(maxLoadedPage.value + 1)
    return gotoCode(stockSet.neighbor(code.value, dir))
  }
}
const barsLoading = ref(true)
const barsError = ref('')
const barsPermissionDenied = ref(false)
const indicatorLoading = ref(true)
const indicatorError = ref('')
const indicatorRows = ref<IndicatorRow[]>([])
const quoteLoading = ref(true)
const membershipLoading = ref(true)
const membershipError = ref('')
// 显示范围（缩放）单向：全局 K 线偏好默认范围 → 会话 ref；主区切换不写回全局默认。
// 数据始终全量加载，可自由拖动看全部
const { validDefault: klineDefault } = useKlinePrefs()
const viewDays = useDefaultedSessionValue(klineDefault)
const bars = ref<Bar[]>([])
const name = ref('')
const {
  intradayOpen,
  intradayTradeDate,
  intradayRequestKey,
  openIntraday,
} = useStockIntradayDrilldown(code)
const quoteSummaryData = ref<StockQuoteSummaryData | null>(null)
const chartActiveBar = ref<Bar | null>(null)
const boardMembership = ref<StockBoardMembership | null>(null)
const latest = ref<IndicatorRow | null>(null)
const analysisDate = computed(() => (
  quoteSummaryData.value?.trade_date
  ?? latest.value?.trade_date
  ?? bars.value.at(-1)?.date
  ?? '最新交易日'
))

// 始终至少加载 5 年数据保证 MA60/MA120 有足够热身窗口，displayBars 控制图表可见范围
const MIN_HISTORY_DAYS = 1250
const chartLookback = computed(() => viewDays.value >= 99999 ? 6000 : Math.max(viewDays.value, MIN_HISTORY_DAYS))
// 展示用：按选项切末尾 N 根；热身用：剩余部分仅参与 MA 计算不渲染
const displayBars = computed(() => viewDays.value >= 99999 ? bars.value : bars.value.slice(-viewDays.value))
const warmupBars = computed(() => viewDays.value >= 99999 ? [] : bars.value.slice(0, -viewDays.value || undefined))
const latestPct = computed(() => {
  const b = chartActiveBar.value ?? quoteSummaryData.value
  if (b?.close == null || !b.pre_close || b.pre_close <= 0) return null
  return ((b.close / b.pre_close) - 1) * 100
})
const latestChange = computed(() => {
  const b = chartActiveBar.value ?? quoteSummaryData.value
  if (b?.close == null || b.pre_close == null) return null
  return b.close - b.pre_close
})
const quoteTone = computed<StockQuoteTone>(() => (
  latestPct.value == null || latestPct.value === 0 ? 'neutral' : latestPct.value > 0 ? 'up' : 'down'
))
const headerSummary = computed<StockQuoteSummaryModel | null>(() => {
  const quote = quoteSummaryData.value
  if (!quote) return null
  const bar = chartActiveBar.value
  const close = bar?.close ?? quote.close
  const preClose = bar?.pre_close ?? quote.pre_close
  const volumeRatio = bar ? stockVolumeRatioAt(bars.value, bar.date) : quote.volume_ratio
  return {
    hero: {
      label: '',
      value: formatChartNumber(close, 2, '—'),
      tone: quoteTone.value,
      details: [
        {
          label: '涨跌额',
          value: latestChange.value == null
            ? '—'
            : `${latestChange.value > 0 ? '+' : ''}${latestChange.value.toFixed(2)}`,
          tone: quoteTone.value,
        },
        { label: '涨跌幅', value: fmtPct(latestPct.value), tone: quoteTone.value },
      ],
    },
    rowsPerColumn: 4,
    metrics: [
      {
        label: '开盘',
        value: formatChartNumber(bar?.open ?? quote.open, 2, '—'),
        tone: priceDirectionTone(bar?.open ?? quote.open, preClose),
      },
      {
        label: '最高',
        value: formatChartNumber(bar?.high ?? quote.high, 2, '—'),
        tone: priceDirectionTone(bar?.high ?? quote.high, preClose),
      },
      {
        label: '最低',
        value: formatChartNumber(bar?.low ?? quote.low, 2, '—'),
        tone: priceDirectionTone(bar?.low ?? quote.low, preClose),
      },
      { label: '量比', value: volumeRatio == null ? '—' : volumeRatio.toFixed(2) },
      { label: '总市值', value: formatCompactMoneyYuan(quote.total_mv) },
      { label: '流通市值', value: formatCompactMoneyYuan(quote.float_mv) },
      { label: '市盈率', value: '—' },
      {
        label: '换手率',
        value: (bar?.turnover_rate ?? quote.turnover_rate) == null
          ? '—'
          : `${(bar?.turnover_rate ?? quote.turnover_rate)!.toFixed(2)}%`,
      },
      { label: '成交额', value: formatAmount(bar?.amount ?? quote.amount, '—') },
      { label: '流通股', value: formatShares(quote.float_share, '—') },
      { label: '总股本', value: formatShares(quote.total_share, '—') },
    ],
  }
})

// 个股详情页展示的关键指标（取最新一日）
const INDICATOR_FIELDS = [
  { key: 'ma20', label: 'MA20' },
  { key: 'ma60', label: 'MA60' },
  { key: 'dist_to_high_2y', label: '距两年高(比)' },
  { key: 'is_high_2y', label: '两年新高' },
  { key: 'is_bull_arrange', label: '多头排列' },
  { key: 'ma20_up', label: 'MA20 向上' },
  { key: 'is_platform_breakout', label: '平台突破' },
  { key: 'is_vol_breakout', label: '放量突破' },
] as const
const MACD_FIELDS = [
  'macd_diff',
  'macd_dea',
  'macd_hist',
  'macd_golden_cross',
  'macd_dead_cross',
] as const satisfies readonly IndicatorField[]
const DETAIL_INDICATOR_FIELDS = [
  ...INDICATOR_FIELDS.map((field) => field.key),
  ...MACD_FIELDS,
] as readonly IndicatorField[]
const visibleIndicatorFields = computed(() => INDICATOR_FIELDS.filter((f) => settings.indicators[f.key as keyof typeof settings.indicators]))
const adjustLabel = computed(() => {
  if (settings.adjustMode === 'qfq') return '前复权'
  if (settings.adjustMode === 'hfq') return '后复权'
  return '不复权'
})
const hasCompleteMacd = computed(() => indicatorRows.value.some((row) => (
  typeof row.macd_diff === 'number'
  && typeof row.macd_dea === 'number'
  && typeof row.macd_hist === 'number'
)))
const macdState = computed<MacdPanelState>(() => {
  if (indicatorLoading.value) return 'loading'
  if (indicatorError.value) return 'error'
  return hasCompleteMacd.value ? 'ready' : 'insufficient'
})

function fmt(v: unknown): string {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'boolean') return v ? '是' : '否'
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : v.toFixed(2)
  return String(v)
}
function fmtPct(v: number | null | undefined): string {
  if (v === null || v === undefined) return '--'
  return (v > 0 ? '+' : '') + v.toFixed(2) + '%'
}
// ── 买卖指标方案评估（v2.0：替代固定买点引擎）──
// R3/R5/R7/R10：方案选择统一走 AssetProfileSelect——下拉只加载「我的」source=mine 纯 owner，
// 「搜索」入口打开共享搜索抽屉（系统内置/租户公开/全体公开）；「加载查看」注入临时只读项
// 并按现状由用户显式触发评估，不自动重评；「复制为我的」后端生成 id 并刷新选中。
const tradeProfiles = ref<TradeProfileSummary[]>([])
const tradeId = ref('')
const tradeEval = ref<TradeEval | null>(null)
const tradeLoading = ref(false)
const tradeError = ref('')

function tradeProfileKey(profile: TradeProfileSummary): string {
  return profile.profile_ref || profile.id
}
const tradeSelectRef = ref<InstanceType<typeof AssetProfileSelect> | null>(null)
async function fetchMineTradeProfiles(): Promise<TradeProfileSummary[]> {
  if (!canViewTradeProfiles.value) return []
  return listTradeProfiles('mine')
}
function browseTrade(params: AssetBrowseParams) {
  return browseTradeProfiles(params)
}
function copyAnyTradeProfile(item: ProfileSummary) {
  return copyTradeProfile(item.profile_ref || item.id)
}
// 主下拉「主动切换」→ 显式评估（沿用现状 @change 习惯，用户明确操作）
function onTradeSelect(key: string) {
  tradeId.value = key
  void evalTrade()
}
// 「加载查看」临时只读项由选择器组件持有，mine 列表保持纯净；页面只保存有效 ref，不自动评估。
function onTradeLoaded(item: ProfileSummary) {
  const summary = item as TradeProfileSummary
  tradeId.value = tradeProfileKey(summary)
  cancelRequest(tradeRequest)
  tradeEval.value = null
  tradeError.value = ''
}

interface RequestChannel {
  controller: AbortController | null
  sequence: number
}

function createRequestChannel(): RequestChannel {
  return { controller: null, sequence: 0 }
}

const barsRequest = createRequestChannel()
const indicatorRequest = createRequestChannel()
const quoteRequest = createRequestChannel()
const membershipRequest = createRequestChannel()
const tradeRequest = createRequestChannel()

function beginRequest(channel: RequestChannel) {
  channel.controller?.abort()
  const controller = new AbortController()
  const sequence = ++channel.sequence
  channel.controller = controller
  return { controller, sequence }
}

function isCurrentRequest(
  channel: RequestChannel,
  controller: AbortController,
  sequence: number,
): boolean {
  return channel.sequence === sequence && !controller.signal.aborted
}

function cancelRequest(channel: RequestChannel): void {
  channel.sequence += 1
  channel.controller?.abort()
  channel.controller = null
}

function cancelDetailRequests(): void {
  cancelRequest(barsRequest)
  cancelRequest(indicatorRequest)
  cancelRequest(quoteRequest)
  cancelRequest(membershipRequest)
  cancelRequest(tradeRequest)
}

let resumeBarsRequest = false
let resumeIndicatorRequest = false
let resumeQuoteRequest = false
let resumeMembershipRequest = false
let resumeTradeRequest = false

function isAbort(e: unknown): boolean {
  const c = e as { code?: string; name?: string }
  return c?.code === 'ERR_CANCELED' || c?.name === 'CanceledError'
}

async function evalTrade() {
  const profileId = tradeId.value
  if (!profileId) {
    cancelRequest(tradeRequest)
    tradeEval.value = null
    tradeLoading.value = false
    return
  }
  const { controller, sequence } = beginRequest(tradeRequest)
  tradeLoading.value = true
  tradeError.value = ''
  try {
    const result = await getTradeEval(code.value, profileId, undefined, controller.signal)
    if (isCurrentRequest(tradeRequest, controller, sequence) && tradeId.value === profileId) {
      tradeEval.value = result
    }
  } catch (e) {
    if (!isAbort(e) && isCurrentRequest(tradeRequest, controller, sequence)) {
      tradeEval.value = null
      tradeError.value = getErrorMessage(e, '买卖信号加载失败')
    }
  } finally {
    if (isCurrentRequest(tradeRequest, controller, sequence)) {
      tradeLoading.value = false
      tradeRequest.controller = null
    }
  }
}

async function loadBars() {
  const { controller, sequence } = beginRequest(barsRequest)
  barsLoading.value = true
  barsError.value = ''
  try {
    const result = await getBars(
      code.value,
      { adjust: settings.adjustMode || '', lookback: chartLookback.value },
      controller.signal,
    )
    if (!isCurrentRequest(barsRequest, controller, sequence)) return
    // 权限态必须持续到受保护行情成功返回，不能在新请求 pending 时短暂回显旧数据。
    barsPermissionDenied.value = false
    bars.value = result.bars
    name.value = result.name || ''
  } catch (e) {
    if (isAbort(e) || !isCurrentRequest(barsRequest, controller, sequence)) return
    if (getErrorStatus(e) === 403) {
      barsPermissionDenied.value = true
      // stocks:view 已被拒绝后立即清除全部详情派生数据，并终止并发通道，保持 fail-closed。
      // 后续普通失败也不解除权限态；只有新的行情成功响应才能恢复展示。
      bars.value = []
      name.value = ''
      indicatorRows.value = []
      latest.value = null
      quoteSummaryData.value = null
      boardMembership.value = null
      tradeEval.value = null
      indicatorError.value = ''
      tradeError.value = ''
      cancelRequest(indicatorRequest)
      cancelRequest(quoteRequest)
      cancelRequest(membershipRequest)
      cancelRequest(tradeRequest)
      indicatorLoading.value = false
      quoteLoading.value = false
      membershipLoading.value = false
      tradeLoading.value = false
    }
    barsError.value = getErrorMessage(e, '个股行情加载失败')
  } finally {
    if (isCurrentRequest(barsRequest, controller, sequence)) {
      barsLoading.value = false
      barsRequest.controller = null
    }
  }
}

async function loadIndicators() {
  const { controller, sequence } = beginRequest(indicatorRequest)
  indicatorLoading.value = true
  indicatorError.value = ''
  try {
    const result = await getIndicators(
      code.value,
      { lookback: chartLookback.value, fields: DETAIL_INDICATOR_FIELDS },
      controller.signal,
    )
    if (!isCurrentRequest(indicatorRequest, controller, sequence)) return
    indicatorRows.value = result.indicators
    latest.value = result.indicators.at(-1) ?? null
  } catch (e) {
    if (isAbort(e) || !isCurrentRequest(indicatorRequest, controller, sequence)) return
    indicatorError.value = getErrorStatus(e) === 403
      ? '无权限查看 MACD 指标，请联系系统管理员调整权限'
      : getErrorMessage(e, 'MACD 指标加载失败，K线与量能不受影响')
  } finally {
    if (isCurrentRequest(indicatorRequest, controller, sequence)) {
      indicatorLoading.value = false
      indicatorRequest.controller = null
    }
  }
}

async function loadLatestQuote(): Promise<string | null | undefined> {
  const requestedCode = code.value
  const { controller, sequence } = beginRequest(quoteRequest)
  quoteLoading.value = true
  try {
    const result = await getStockQuoteSummary(requestedCode, controller.signal)
    if (!isCurrentRequest(quoteRequest, controller, sequence)) return undefined
    quoteSummaryData.value = result
    if (result.name) name.value = result.name
    return result.trade_date
  } catch (e) {
    if (!isAbort(e) && isCurrentRequest(quoteRequest, controller, sequence)) {
      quoteSummaryData.value = null
      return null
    }
    return undefined
  } finally {
    if (isCurrentRequest(quoteRequest, controller, sequence)) {
      quoteLoading.value = false
      quoteRequest.controller = null
    }
  }
}

async function loadBoardMembership(
  businessDate = quoteSummaryData.value?.trade_date ?? undefined,
): Promise<void> {
  const requestedCode = code.value
  const { controller, sequence } = beginRequest(membershipRequest)
  membershipLoading.value = true
  membershipError.value = ''
  try {
    const result = await getStockBoardMembership(
      requestedCode,
      businessDate ?? undefined,
      controller.signal,
    )
    if (isCurrentRequest(membershipRequest, controller, sequence)) {
      boardMembership.value = result
    }
  } catch (e) {
    if (!isAbort(e) && isCurrentRequest(membershipRequest, controller, sequence)) {
      boardMembership.value = null
      membershipError.value = getErrorMessage(e, '所属板块加载失败')
    }
  } finally {
    if (isCurrentRequest(membershipRequest, controller, sequence)) {
      membershipLoading.value = false
      membershipRequest.controller = null
    }
  }
}

async function loadQuoteContext(): Promise<void> {
  const businessDate = await loadLatestQuote()
  if (businessDate !== undefined && !barsPermissionDenied.value) {
    await loadBoardMembership(businessDate ?? undefined)
  }
}

async function reloadRangeData() {
  await Promise.all([loadBars(), loadIndicators()])
}

async function refreshStockDetail(): Promise<void> {
  await Promise.all([
    reloadRangeData(),
    loadQuoteContext(),
    loadGroups(),
    loadStockGroups(),
    tradeId.value ? evalTrade() : Promise.resolve(),
  ])
}

watch(viewDays, () => {
  void reloadRangeData()
})
watch(() => settings.adjustMode, () => {
  void loadBars()
})

// 组件为列表唯一事实源（P2-1）：经 ready 接收「我的」列表，不再重复 fetch；首项自动选中并评估
async function onTradeReady(list: ProfileSummary[]) {
  tradeProfiles.value = list as TradeProfileSummary[]
  if (tradeProfiles.value.length && !tradeId.value && !barsPermissionDenied.value) {
    tradeId.value = tradeProfileKey(tradeProfiles.value[0])
    await evalTrade()
  }
}
// 复制成功（P2-2）：组件回写完整 summary，并入 tradeProfiles 供选中回显
function onTradeCopied(item: ProfileSummary) {
  const summary = item as TradeProfileSummary
  if (!tradeProfiles.value.some((p) => tradeProfileKey(p) === tradeProfileKey(summary))) {
    tradeProfiles.value = [summary, ...tradeProfiles.value]
  }
}

onMounted(async () => {
  await auth.ensureLoaded().catch(() => undefined)
  clearUnauthorizedGroupSet()
  await Promise.all([
    reloadRangeData(),
    loadQuoteContext(),
    loadGroups(),
    loadStockGroups(),
  ])
})

// ── 分组编辑 ──
const groups = ref<GroupSummary[]>([])
const stockGroups = ref<StockBasic['groups']>([])
const groupOpsLoading = ref(false)
const selectedGroupIds = ref<string[]>([])
const defaultGroup = computed(() => groups.value.find((group) => group.is_default))
const isDefaultFavorite = computed(() => {
  const group = defaultGroup.value
  return Boolean(group && selectedGroupIds.value.includes(group.id))
})
const selectedGroups = computed(() => selectedGroupIds.value.map((id) => {
  const fromAll = groups.value.find((g) => g.id === id)
  const fromStock = stockGroups.value.find((g) => g.id === id)
  return fromAll ?? fromStock ?? null
}).filter((g): g is GroupSummary | StockBasic['groups'][number] => !!g))
const visibleSelectedGroups = computed(() => selectedGroups.value.slice(0, 2))
const hiddenSelectedGroupCount = computed(() => Math.max(0, selectedGroups.value.length - visibleSelectedGroups.value.length))
let syncingGroupSelect = false
async function loadGroups() {
  // 次级加载按自身 view 码优雅降级：无 stock-group:view 的部分授权角色不拉分组、也不因此 403 卡住详情页主体
  // （K 线/指标/交易评估仍可用）。默认业务角色含该码不受影响。与 StocksView.reloadGroups 同口径。
  if (!canViewGroups.value) {
    groups.value = []
    return
  }
  groups.value = await listGroups()
}
async function loadStockGroups() {
  if (!canViewGroups.value) {
    stockGroups.value = []
    selectedGroupIds.value = []
    return
  }
  const data = await listStocks({ q: code.value, page: 1, size: 1 })
  stockGroups.value = data.list.find((r) => r.code === code.value)?.groups ?? []
  syncingGroupSelect = true
  selectedGroupIds.value = stockGroups.value.map((g) => g.id)
  syncingGroupSelect = false
}
async function onGroupsChange(value: unknown) {
  if (syncingGroupSelect) return
  if (!canViewGroups.value) return
  const nextIds = Array.isArray(value) ? value.map(String) : []
  const prev = new Set(stockGroups.value.map((g) => g.id))
  const next = new Set(nextIds)
  const add = nextIds.filter((id) => !prev.has(id))
  const remove = [...prev].filter((id) => !next.has(id))
  if (!add.length && !remove.length) return
  groupOpsLoading.value = true
  try {
    await Promise.all([
      ...add.map((gid) => addMembers(gid, [code.value])),
      ...remove.map((gid) => removeMembers(gid, [code.value])),
    ])
    await Promise.all([loadGroups(), loadStockGroups()])
    ElMessage.success('分组已同步')
  } finally {
    groupOpsLoading.value = false
  }
}
async function removeSelectedGroup(gid: string) {
  if (groupOpsLoading.value) return
  const next = selectedGroupIds.value.filter((id) => id !== gid)
  selectedGroupIds.value = next
  await onGroupsChange(next)
}

function updateDefaultFavorite(active: boolean): void {
  const group = defaultGroup.value
  if (!group) return
  const otherGroups = stockGroups.value.filter((item) => item.id !== group.id)
  stockGroups.value = active
    ? [{ id: group.id, name: group.name, color: group.color, is_default: true }, ...otherGroups]
    : otherGroups
  selectedGroupIds.value = stockGroups.value.map((item) => item.id)
  group.member_count = Math.max(0, group.member_count + (active ? 1 : -1))
}

// ── 集合下拉：保留全量集合语义，候选项按 100 条懒加载，搜索合并在同一个下拉里 ──
const DROPDOWN_PAGE_SIZE = 100
// 首屏直接消费共享集合，否则当前股票会在下拉候选加载前被临时补成第 1 项。
const dropdownItems = ref<{ code: string; name?: string | null }[]>([...stockSet.items])
const dropdownPage = ref(stockSet.loadedPages.length ? Math.max(...stockSet.loadedPages) : 1)
const dropdownTotal = ref(collectionTotal.value)
const dropdownKeyword = ref('')
const dropdownLoading = ref(false)
const dropdownLoadedPages = ref<number[]>(
  stockSet.loadedPages.length ? [...stockSet.loadedPages] : (stockSet.items.length ? [1] : []),
)
let dropdownRequestSeq = 0
const collectionKeyword = ref('')
const collectionSearch = useDebouncedQuery(() => resetDropdown(collectionKeyword.value.trim()), 180)

const dropdownHasMore = computed(() => dropdownItems.value.length < dropdownTotal.value)
const currentDropdownItem = computed(() => {
  const fromSet = stockSet.items.find((it) => it.code === code.value)
  return fromSet ?? { code: code.value, name: name.value || null }
})
const dropdownOptions = computed(() => {
  const current = currentDropdownItem.value
  if (!current.code || dropdownItems.value.some((it) => it.code === current.code)) return dropdownItems.value
  return [current, ...dropdownItems.value]
})

function mergeItems(base: { code: string; name?: string | null }[], incoming: { code: string; name?: string | null }[]) {
  const seen = new Set(base.map((it) => it.code))
  return [...base, ...incoming.filter((it) => !seen.has(it.code))]
}

async function fetchDropdownPage(page: number, keyword: string) {
  if (stockSet.query) {
    if (stockSet.query.kind === 'group') {
      if (!canViewGroups.value) {
        stockSet.clearGroupContext()
        return { total: 0, items: [] }
      }
      const data = await getGroup(stockSet.query.groupId, {
        ...stockSet.query.params,
        q: keyword || stockSet.query.params.q,
        page,
        size: DROPDOWN_PAGE_SIZE,
      })
      return {
        total: data.members.total,
        items: data.members.list.map((r) => ({ code: r.code, name: r.name })),
      }
    }
    const data = await listStocks({
      ...stockSet.query.params,
      q: keyword || stockSet.query.params.q,
      page,
      size: DROPDOWN_PAGE_SIZE,
    })
    return {
      total: data.total,
      items: data.list.map((r) => ({ code: r.code, name: r.name })),
    }
  }

  const q = keyword.trim().toLowerCase()
  const source = q
    ? stockSet.items.filter((it) => it.code.toLowerCase().includes(q) || (it.name || '').toLowerCase().includes(q))
    : stockSet.items
  const start = (page - 1) * DROPDOWN_PAGE_SIZE
  return {
    total: source.length,
    items: source.slice(start, start + DROPDOWN_PAGE_SIZE),
  }
}

async function loadDropdownPage(page: number, replace = false) {
  if (dropdownLoading.value || (!replace && dropdownLoadedPages.value.includes(page))) return
  dropdownLoading.value = true
  const seq = ++dropdownRequestSeq
  try {
    const keyword = dropdownKeyword.value.trim()
    const data = await fetchDropdownPage(page, keyword)
    if (seq !== dropdownRequestSeq || keyword !== dropdownKeyword.value.trim()) return
    dropdownTotal.value = data.total
    dropdownPage.value = page
    dropdownLoadedPages.value = replace ? [page] : [...dropdownLoadedPages.value, page]
    dropdownItems.value = replace ? data.items : mergeItems(dropdownItems.value, data.items)

    if (!keyword) {
      stockSet.setTotal(data.total)
      stockSet.appendPage(data.items, page)
    }
  } finally {
    dropdownLoading.value = false
  }
}

async function resetDropdown(keyword = '') {
  dropdownRequestSeq += 1
  dropdownKeyword.value = keyword
  dropdownTotal.value = 0
  dropdownLoadedPages.value = []
  dropdownItems.value = []

  if (!keyword) {
    dropdownItems.value = stockSet.items
    dropdownTotal.value = collectionTotal.value
    dropdownLoadedPages.value = stockSet.loadedPages.length ? [...stockSet.loadedPages] : [1]
    dropdownPage.value = dropdownLoadedPages.value.length ? Math.max(...dropdownLoadedPages.value) : 1
    return
  }

  dropdownPage.value = 1
  await loadDropdownPage(1, true)
}

function onCollectionSearch(query: string) {
  collectionKeyword.value = query
  collectionSearch.schedule()
}

function onCollectionSelect(c: string | null) {
  if (!c || c === '__more__') return
  if (stockSet.indexOf(c) < 0) {
    stockSet.mergeItemsNear(dropdownItems.value, code.value)
  }
  gotoCode(c)
}

async function onCollectionVisibleChange(visible: boolean) {
  if (!visible) return
  if (!dropdownItems.value.length || dropdownKeyword.value) await resetDropdown('')
}

function onCollectionEndReached(direction: string) {
  if (direction !== 'bottom' || dropdownLoading.value || !dropdownHasMore.value) return
  const nextPage = dropdownLoadedPages.value.length
    ? Math.max(...dropdownLoadedPages.value) + 1
    : dropdownPage.value + 1
  void loadDropdownPage(nextPage)
}

onDeactivated(() => {
  resumeBarsRequest = barsLoading.value
  resumeIndicatorRequest = indicatorLoading.value
  resumeQuoteRequest = quoteLoading.value
  resumeMembershipRequest = membershipLoading.value
  resumeTradeRequest = tradeLoading.value
  cancelDetailRequests()
  barsLoading.value = false
  indicatorLoading.value = false
  quoteLoading.value = false
  membershipLoading.value = false
  tradeLoading.value = false
})

onActivated(() => {
  if (resumeBarsRequest) void loadBars()
  if (resumeIndicatorRequest) void loadIndicators()
  if (resumeQuoteRequest || resumeMembershipRequest) void loadQuoteContext()
  if (resumeTradeRequest) void evalTrade()
  resumeBarsRequest = false
  resumeIndicatorRequest = false
  resumeQuoteRequest = false
  resumeMembershipRequest = false
  resumeTradeRequest = false
})

onBeforeUnmount(() => {
  cancelDetailRequests()
})
</script>

<template>
  <LayoutHost :layout="detailEffective">
    <template #action>
    <div class="lh-action detail-action">
      <div class="detail-nav">
        <el-button
          text
          :aria-label="returnLabel"
          data-testid="stock-detail-back"
          @click="returnToCollection"
        >
          <template #icon><el-icon><ArrowLeft /></el-icon></template>
          {{ returnLabel }}
        </el-button>
        <div class="page-head-actions detail-actions">
          <el-button
            data-testid="stock-detail-refresh"
            :loading="barsLoading || indicatorLoading || quoteLoading || membershipLoading || tradeLoading"
            @click="refreshStockDetail"
          >刷新</el-button>
          <PageSettingsTrigger :dirty="isDirty" @click="settingsOpen = true" />
        </div>
      </div>
    </div>
    </template>

    <template #main>
    <div class="stock-detail-main">
    <AppStateBlock
      v-if="barsPermissionDenied || barsError"
      state="error"
      :variant="barsPermissionDenied ? 'permission' : undefined"
      :title="barsPermissionDenied ? '无权限查看个股详情' : (bars.length ? '个股详情刷新失败' : '个股详情加载失败')"
      :description="barsPermissionDenied ? '请联系系统管理员调整股票查看权限' : barsError"
      :retry="!barsPermissionDenied"
      @retry="loadBars"
    />

    <AppStateBlock
      v-else-if="!barsLoading && !bars.length"
      state="empty"
      title="暂无个股行情"
      description="当前股票在所选范围内没有可用行情"
    />

    <template v-else>
      <MarketDetailHero
        class="stock-detail-hero"
        :title="name || quoteSummaryData?.name || code"
        :code="code"
        subtitle="价格趋势、技术状态与所属板块联动观察"
        aside-align="start"
      >
        <template #badges>
          <span v-if="quoteSummaryData?.board" class="stock-type">{{ quoteSummaryData.board }}</span>
          <span v-if="quoteSummaryData?.is_st" class="stock-type stock-type--risk">ST</span>
        </template>
        <template #actions>
          <StockGroupFavoriteButton
            v-if="canUpdateGroups && defaultGroup && !barsPermissionDenied"
            :group-id="defaultGroup.id"
            :code="code"
            :name="name || quoteSummaryData?.name || code"
            :active="isDefaultFavorite"
            :default-date="quoteSummaryData?.trade_date || ''"
            data-testid="stock-detail-favorite"
            @changed="updateDefaultFavorite"
          />
        </template>
        <template #summary>
          <StockQuoteSummary
            v-if="headerSummary"
            :summary="headerSummary"
            column-gap="relaxed"
            data-testid="stock-latest-quote"
          />
          <span v-else class="app-caption-text">
            {{ quoteLoading ? '行情摘要加载中…' : '行情摘要暂不可用' }}
          </span>
        </template>
        <template v-if="(settings.showNav && stockSet.has) || (canUpdateGroups && !barsPermissionDenied)" #footer>
          <div
            v-if="settings.showNav && stockSet.has"
            class="stock-context__collection"
            data-testid="stock-set-navigation"
          >
            <span class="nav-label">
              {{ stockSet.label }}
              <span v-if="inSet" class="nav-pos">{{ setIndex + 1 }}/{{ collectionTotal }}</span>
              <span v-else class="nav-pos muted">不在集合内 · 共 {{ collectionTotal }} 只</span>
            </span>
            <el-button-group class="nav-btns">
              <el-button size="small" :loading="setLoading" :disabled="!prevCode && !canLoadPrev" @click="gotoNeighbor(-1)">
                <template #icon><el-icon><ArrowLeft /></el-icon></template>
                {{ prevLabel }}
              </el-button>
              <el-button size="small" :loading="setLoading" :disabled="!nextCode && !canLoadNext" @click="gotoNeighbor(1)">
                {{ nextLabel }}
                <el-icon class="el-icon--right"><ArrowRight /></el-icon>
              </el-button>
            </el-button-group>
            <el-select
              data-testid="stock-set-select"
              :model-value="code"
              placeholder="从集合中选择"
              filterable
              remote
              clearable
              reserve-keyword
              size="small"
              class="stock-context__select"
              :remote-method="onCollectionSearch"
              :loading="dropdownLoading"
              @change="onCollectionSelect"
              @visible-change="onCollectionVisibleChange"
              @end-reached="onCollectionEndReached"
            >
              <el-option
                v-for="(it, i) in dropdownOptions"
                :key="it.code"
                :value="it.code"
                :label="`${i + 1}. ${it.name || ''} ${it.code}`"
              />
              <el-option
                v-if="dropdownHasMore"
                key="__more__"
                value="__more__"
                disabled
                :label="dropdownLoading ? '加载中...' : '向下滚动加载更多'"
              />
            </el-select>
            <AppIconButton label="退出集合" size="sm" tone="default" @click="stockSet.clear()">
              <el-icon><Close /></el-icon>
            </AppIconButton>
          </div>
          <div v-if="canUpdateGroups && !barsPermissionDenied" class="stock-context__groups">
            <span class="stock-context__label">所属分组</span>
            <el-select
              v-model="selectedGroupIds"
              v-permission="'stock-group:member-update'"
              data-testid="stock-group-select"
              multiple
              filterable
              collapse-tags
              collapse-tags-tooltip
              :max-collapse-tags="2"
              size="small"
              :placement="APP_BOTTOM_FLOATING_PLACEMENT"
              :fallback-placements="APP_BOTTOM_FLOATING_FALLBACKS"
              class="stock-context__group-select"
              placeholder="选择分组"
              :loading="groupOpsLoading"
              @change="onGroupsChange"
            >
              <template #tag>
                <el-tag
                  v-for="g in visibleSelectedGroups"
                  :key="g.id"
                  class="group-select-tag"
                  size="small"
                  closable
                  :disable-transitions="true"
                  :style="stockGroupTagStyle(g.color)"
                  @close.stop="removeSelectedGroup(g.id)"
                >{{ g.name }}</el-tag>
                <el-tag v-if="hiddenSelectedGroupCount" class="group-select-tag more" size="small">
                  +{{ hiddenSelectedGroupCount }}
                </el-tag>
              </template>
              <el-option v-for="g in groups" :key="g.id" :value="g.id" :label="g.name">
                <span class="group-option">
                  <span class="color-dot" :style="{ backgroundColor: g.color }" />
                  <span>{{ g.name }}（{{ g.member_count }}）</span>
                </span>
              </el-option>
            </el-select>
          </div>
        </template>
      </MarketDetailHero>
      <AppStateBlock
        v-if="barsLoading && !bars.length"
        state="loading"
        title="正在加载个股行情…"
      />
      <div v-show="!barsLoading || bars.length" class="stock-detail-ready">
        <AppSplitWorkspace
          ref="splitWorkspaceRef"
          class="stock-detail-workspace"
          data-testid="stock-detail-workspace"
          :secondary-visible="showAuxiliary"
          :default-primary-ratio="Number(componentValueOf('workspace', 'masterRatio') ?? detailWorkspaceDefaultRatio)"
          :primary-ratio-profiles="componentValueOf('workspace', 'masterRatioProfiles')"
          :min-height="MARKET_WORKSPACE_MIN_HEIGHT"
          :compact-min-height="MARKET_WORKSPACE_COMPACT_MIN_HEIGHT"
          secondary-drawer-title="个股辅助信息"
          separator-label="调整图表与辅助信息宽度"
          test-id-prefix="stock-detail"
          @update:secondary-visible="auxiliaryVisible = $event"
          @primary-ratio-sample-change="setCurrentMasterRatioSample"
          @compact-change="splitCompact = $event"
        >
          <template #primary>
          <AppWorkspacePane
            title="行情走势"
            aria-label="个股行情走势"
            primary
            data-testid="stock-detail-chart-panel"
          >
            <template #actions>
              <KlineRangeSelect
                v-model="viewDays"
                width="112px"
                test-id="stock-detail-range"
              />
              <AppIconButton
                v-if="hasAuxiliaryContent"
                :label="splitCompact ? '查看辅助信息' : (showAuxiliary ? '收起辅助信息，仅看图表' : '显示辅助信息')"
                data-testid="stock-detail-toggle-auxiliary"
                size="sm"
                :native-title="false"
                @click="toggleAuxiliaryPanel"
              >
                <el-icon>
                  <DArrowRight v-if="showAuxiliary && !splitCompact" />
                  <DArrowLeft v-else />
                </el-icon>
              </AppIconButton>
            </template>
            <StockChartWorkspace
              class="detail-chart-workspace"
              v-loading="barsLoading && bars.length > 0"
              :bars="displayBars"
              :warmup-bars="warmupBars"
              :indicators="indicatorRows"
              :slot2="chartPreferences.preferences.value.slot2"
              :slot3="chartPreferences.preferences.value.slot3"
              :height-ratios="chartPreferences.currentRatios.value"
              :adjust-label="adjustLabel"
              macd-adjust-label="前复权"
              :macd-state="macdState"
              :macd-error="indicatorError"
              :zoom-start="0"
              :zoom-end="100"
              fit-available-height
              enable-intraday-drilldown
              enable-return-measurement
              v-model:return-measurement-mode="klineMeasurementMode"
              v-model:measurement-operations-expanded="klineOperationBarExpanded"
              :show-kline-tooltip="false"
              @ratio-draft="chartPreferences.handleRatioDraft"
              @ratio-commit="chartPreferences.handleRatioCommit"
              @workspace-resize="chartPreferences.handleWorkspaceResize"
              @retry-macd="loadIndicators"
              @bar-click="openIntraday"
              @active-bar-change="chartActiveBar = $event"
            />
          </AppWorkspacePane>
          </template>

          <template #secondary>
          <AppWorkspacePane
            :title="analysisDate"
            eyebrow="分析概览"
            aria-label="个股分析概览"
            :header-visible="!splitCompact"
            data-testid="stock-detail-auxiliary-panel"
          >
          <aside class="stock-detail-auxiliary">
            <StockBoardMembershipPanel
              v-if="settings.showRelatedBoards"
              :membership="boardMembership"
              :loading="membershipLoading"
              :error="membershipError"
              :can-navigate="canViewSectors"
              :return-path="route.fullPath"
              @retry="loadBoardMembership"
            />
            <el-card
              v-if="settings.showIndicatorSnapshot"
              data-testid="stock-indicator-snapshot-card"
              shadow="never"
              class="ind-card"
              header="最新指标快照"
            >
              <AppDetailFields :columns="2">
                <AppDetailField
                  v-for="f in visibleIndicatorFields"
                  :key="f.key"
                  :label="f.label"
                  :value="latest ? fmt(latest[f.key]) : null"
                />
              </AppDetailFields>
              <p class="note">注：RS 相对强度为全市场横截面指标，个股单独查询不计算；请在策略筛选/每日榜单中查看。</p>
            </el-card>

            <!-- 买卖指标方案评估 -->
            <el-card
              v-if="settings.showTradeCard && canUseTradeEvaluation"
              data-testid="stock-trade-eval-card"
              shadow="never"
              class="trade-card"
            >
        <template #header>
          <div class="trade-head">
            <span>买卖信号评估</span>
            <AssetProfileSelect
              ref="tradeSelectRef"
              :model-value="tradeId"
              asset-label="买卖方案"
              :fetch-mine="fetchMineTradeProfiles"
              :browse="browseTrade"
              :copy-item="copyAnyTradeProfile"
              copy-permission="trade-profile:save"
              view-permission="trade-profile:view"
              placeholder="选我的买卖方案（可选）"
              test-id="stock-trade-select"
              class="trade-profile-select"
              @update:model-value="onTradeSelect"
              @loaded="onTradeLoaded"
              @ready="onTradeReady"
              @copied-item="onTradeCopied"
            />
            <el-button
              type="primary"
              size="small"
              :disabled="!tradeId"
              :loading="tradeLoading"
              data-testid="stock-trade-eval-run"
              @click="evalTrade()"
            >
              评估
            </el-button>
            <span class="hint" v-if="tradeEval">交易日 {{ tradeEval.date }} · v{{ tradeEval.version }}</span>
          </div>
        </template>
        <div v-loading="tradeLoading && !!tradeEval">
          <AppStateBlock
            v-if="tradeError"
            state="error"
            size="compact"
            title="买卖信号加载失败"
            :description="tradeError"
            retry
            @retry="evalTrade()"
          />
          <AppStateBlock
            v-else-if="tradeLoading && !tradeEval"
            state="loading"
            size="compact"
            title="正在加载买卖信号…"
          />
          <el-empty v-else-if="!tradeEval" class="app-empty app-empty--compact" description="选择买卖方案以评估当日信号" />
          <div v-else class="trade-body">
            <div class="signal-row">
              <el-tag :type="tradeEval.buy_signal ? 'danger' : 'info'" effect="dark" size="large">
                {{ tradeEval.buy_signal ? '✓ 触发买入' : '买入未触发' }}
              </el-tag>
              <el-tag :type="tradeEval.sell_signal ? 'warning' : 'info'" effect="dark" size="large">
                {{ tradeEval.sell_signal ? '✓ 触发卖出' : '卖出未触发' }}
              </el-tag>
            </div>
            <div class="cond-cols">
              <div class="cond-col">
                <div class="cond-title">买入条件（{{ tradeEval.buy.op === 'AND' ? '需全部满足' : '满足任一' }}）</div>
                <div v-for="(cc, i) in tradeEval.buy.conds" :key="i" class="cond-line">
                  <el-tag :type="cc.met ? 'success' : 'info'" size="small" effect="plain">
                    {{ cc.met ? '✓' : '✗' }}
                  </el-tag>
                  <span>{{ cc.label }}</span>
                </div>
              </div>
              <div class="cond-col">
                <div class="cond-title">卖出条件（{{ tradeEval.sell.op === 'AND' ? '需全部满足' : '满足任一' }}）</div>
                <el-empty v-if="!tradeEval.sell.conds.length" class="app-empty app-empty--tiny" description="无卖出条件" />
                <div v-for="(cc, i) in tradeEval.sell.conds" :key="i" class="cond-line">
                  <el-tag :type="cc.met ? 'success' : 'info'" size="small" effect="plain">
                    {{ cc.met ? '✓' : '✗' }}
                  </el-tag>
                  <span>{{ cc.label }}</span>
                </div>
                <div v-if="tradeEval.backstop && (tradeEval.backstop.take_profit || tradeEval.backstop.stop_loss || tradeEval.backstop.max_hold_days)" class="backstop">
                  兜底：
                  <span v-if="tradeEval.backstop.take_profit">止盈 {{ (tradeEval.backstop.take_profit * 100).toFixed(0) }}%</span>
                  <span v-if="tradeEval.backstop.stop_loss"> · 止损 {{ (tradeEval.backstop.stop_loss * 100).toFixed(0) }}%</span>
                  <span v-if="tradeEval.backstop.max_hold_days"> · 最多持 {{ tradeEval.backstop.max_hold_days }} 日</span>
                </div>
              </div>
            </div>
            <p class="note">点时安全：仅用 ≤ 当日数据求值。兜底止盈止损需结合持仓成本，在回测验证中生效。</p>
          </div>
        </div>
            </el-card>
          </aside>
          </AppWorkspacePane>
          </template>
        </AppSplitWorkspace>
      </div>
    </template>
    </div>
    </template>

    <template #overlays>
    <PageSettingsDrawer
      v-model="settingsOpen"
      title="个股详情"
      :dirty="isDirty || layoutDirty"
      page-key="stock-detail"
      :config="drawerConfig"
      :business-visible="true"
      :component-runtime-value-of="componentRuntimeValueOf"
      @reset="resetDetailSettings"
    >
      <template #business>
        <PageSettingSection title="行情口径">
          <PageSettingItem label="复权模式">
            <PageSegmented v-model="settings.adjustMode" aria-label="复权模式" :options="[
              { label: '不复权', value: '' },
              { label: '前复权', value: 'qfq' },
              { label: '后复权', value: 'hfq' },
            ]" />
          </PageSettingItem>
        </PageSettingSection>

        <KlineSettingSection />

        <PageSettingSection title="图表操作">
          <PageToggleRow
            v-model="settings.klineOperationBarExpanded"
            label="默认展开图表操作栏"
            test-id="stock-detail-default-operation-bar"
          />
          <PageSettingItem label="默认区间测算模式">
            <PageSegmented
              v-model="settings.klineMeasurementMode"
              aria-label="默认区间测算模式"
              test-id="stock-detail-default-measurement-mode"
              :options="[
                { label: '截止', value: 'latest' },
                { label: '区间', value: 'range' },
              ]"
            />
          </PageSettingItem>
        </PageSettingSection>

        <PageSettingSection title="指标快照">
          <PageToggleRow v-model="settings.indicators.ma20" label="MA20" />
          <PageToggleRow v-model="settings.indicators.ma60" label="MA60" />
          <PageToggleRow v-model="settings.indicators.dist_to_high_2y" label="距两年高(比)" />
          <PageToggleRow v-model="settings.indicators.is_high_2y" label="两年新高" />
          <PageToggleRow v-model="settings.indicators.is_bull_arrange" label="多头排列" />
          <PageToggleRow v-model="settings.indicators.ma20_up" label="MA20 向上" />
          <PageToggleRow v-model="settings.indicators.is_platform_breakout" label="平台突破" />
          <PageToggleRow v-model="settings.indicators.is_vol_breakout" label="放量突破" />
        </PageSettingSection>

        <PageSettingSection title="辅助模块">
          <PageToggleRow v-model="settings.showNav" label="显示集合导航条" />
          <PageToggleRow
            v-model="settings.showRelatedBoards"
            label="显示所属板块"
            test-id="stock-detail-toggle-related-boards"
          />
          <PageToggleRow
            v-model="settings.showIndicatorSnapshot"
            label="显示最新指标快照"
            test-id="stock-detail-toggle-indicator-snapshot"
          />
          <PageToggleRow
            v-if="canUseTradeEvaluation"
            v-model="settings.showTradeCard"
            label="显示买卖信号评估卡"
            test-id="stock-detail-toggle-trade-card"
          />
        </PageSettingSection>
      </template>
    </PageSettingsDrawer>
    <StockIntradayDialog
      v-model="intradayOpen"
      :code="code"
      :name="name"
      :trade-date="intradayTradeDate"
      :request-key="intradayRequestKey"
    />
    </template>
  </LayoutHost>
</template>

<style scoped>
.stock-detail-main {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: var(--app-space-3);
  overflow: hidden;
}

.stock-detail-ready {
  min-height: 0;
  flex: 1 1 auto;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.stock-detail-workspace {
  flex: 1 1 auto;
  min-height: 0;
}

.detail-chart-workspace {
  flex: 1 1 auto;
  width: 100%;
  min-height: 0;
}

.stock-detail-auxiliary {
  box-sizing: border-box;
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  gap: var(--app-space-3);
  width: 100%;
  min-width: 0;
  min-height: 0;
  padding: var(--app-space-3);
  overflow-y: auto;
  overscroll-behavior: contain;
}

.detail-action,
.detail-nav,
.detail-actions,
.stock-context__collection,
.stock-context__groups {
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

.stock-type {
  padding: 3px 8px;
  border-radius: 999px;
  color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
  font-size: var(--app-font-size-caption);
  font-weight: var(--app-font-weight-strong);
}

.stock-type--risk {
  color: var(--market-up-color);
  background: color-mix(in srgb, var(--market-up-color) 10%, transparent);
}
.group-option {
  display: inline-flex;
  align-items: center;
  gap: var(--app-space-control-gap);
}
.group-select-tag {
  margin: 2px 4px 2px 0;
  border-radius: 4px;
  border-style: solid;
  font-weight: var(--app-font-weight-section);
}
.group-select-tag.more {
  color: var(--el-text-color-secondary);
  border-color: var(--el-border-color);
  background: var(--app-section-bg);
}
.color-dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  flex: 0 0 auto;
}
.stock-context__collection {
  min-width: 0;
  flex: 1 1 620px;
  gap: var(--app-space-3);
  flex-wrap: wrap;
}
.nav-label {
  font-size: var(--app-font-size-table);
  font-weight: var(--app-font-weight-section);
  color: var(--el-text-color-regular);
  flex: 0 0 auto;
}
.stock-context__select {
  width: min(240px, 30cqw);
}
.stock-context__groups {
  min-width: 0;
  flex: 1 1 300px;
  justify-content: flex-end;
  gap: var(--app-space-2);
}
.stock-context__label {
  flex: 0 0 auto;
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
}
.stock-context__group-select {
  width: min(260px, 32cqw);
}
.nav-pos {
  font-weight: var(--app-font-weight-regular);
  margin-left: var(--app-space-control-gap);
  color: var(--el-text-color-secondary);
  font-variant-numeric: tabular-nums;
}
.ind-card,
.trade-card {
  flex: 0 0 auto;
  margin: 0;
}
.note {
  margin: 10px 0 0;
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
}
.trade-head {
  display: flex;
  align-items: center;
  gap: var(--app-space-3);
  flex-wrap: wrap;
}
.trade-profile-select {
  flex: 1 1 240px;
  min-width: 0;
}
.hint {
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
}
.signal-row {
  display: flex;
  gap: var(--app-space-3);
  margin-bottom: 16px;
}
.cond-cols {
  display: flex;
  gap: var(--app-space-6);
  flex-direction: column;
}
.cond-col {
  min-width: 0;
}
.cond-title {
  font-weight: var(--app-font-weight-section);
  font-size: var(--app-font-size-table);
  margin-bottom: 8px;
  color: var(--el-text-color-regular);
}
.cond-line {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
  margin-bottom: 6px;
  font-size: var(--app-font-size-table);
}
.backstop {
  margin-top: 10px;
  font-size: var(--app-font-size-caption);
  color: var(--el-text-color-secondary);
}

@container app-viewport (max-width: 980px) {
  .stock-context__groups {
    justify-content: flex-start;
  }

  .stock-context__select,
  .stock-context__group-select {
    width: min(100%, 320px);
  }
}
</style>
