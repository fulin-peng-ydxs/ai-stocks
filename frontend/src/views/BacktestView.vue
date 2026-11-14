<script setup lang="ts">
import { formatReturn, formatPercent, formatPercentPoints, marketValueClass } from '@/utils/marketValue'
import { formatNumber, displayDirection, tinyValueHint } from '@/utils/numberFormat'
import { downloadCsv } from '@/utils/csv'
import AppForm from '@/components/AppForm.vue'
import AppSelect from '@/components/AppSelect.vue'
import AppScrollArea from '@/components/AppScrollArea.vue'
import AppHoverInfo from '@/components/AppHoverInfo'
import AppActionHint from '@/components/AppActionHint.vue'
import { useMenuPageTitle } from '@/composables/useMenuPageTitle'
import AppTableColumn from '@/components/AppTableColumn.vue'
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computeBoard, type BoardRow } from '@/api/board'
import {
  runBacktest, prepareBacktest, listRuns, getRun, deleteRun, runRobust, setRunVisibility, browseRuns,
  type StrategyResult, type Layers, type RunParams, type LayerCell,
  type TradeRow, type RunSummary, type ParamSweepResult, type InOutSampleResult,
} from '@/api/backtest'
import { listProfiles, getProfile, browseProfiles, copyProfile, type Profile } from '@/api/screening'
import { listScoreProfiles, browseScoreProfiles, copyScoreProfile, type ScoreProfileSummary } from '@/api/scoreProfile'
import { listTradeProfiles, browseTradeProfiles, copyTradeProfile, type TradeProfileSummary } from '@/api/tradeProfile'
import {
  getBars,
  getIndicators,
  type Bar,
  type IndicatorRow,
} from '@/api/stocks'
import { fetchBenchmarkEquity, type BenchmarkEquity } from '@/utils/benchmarkEquity'
import EquityChart from '@/components/EquityChart.vue'
import AppDialog from '@/components/AppDialog.vue'
import StockChartWorkspace from '@/components/stock-chart/StockChartWorkspace.vue'
import { MACD_INDICATOR_FIELDS } from '@/components/stock-chart/indicatorFields'
import type { MacdPanelState, TradeMarker } from '@/components/stock-chart/workspaceOptions'
import { Search } from '@element-plus/icons-vue'
import AppControlItem from '@/components/AppControlItem.vue'
import AppControlRow from '@/components/AppControlRow.vue'
import AppFilterSelect from '@/components/AppFilterSelect.vue'
import MarketBenchmarkSelect from '@/components/MarketBenchmarkSelect.vue'
import AppDataTable from '@/components/AppDataTable.vue'
import AppAsyncRegion from '@/components/AppAsyncRegion.vue'
import AppStateBlock from '@/components/AppStateBlock.vue'
import AppStatusNotice from '@/components/AppStatusNotice.vue'
import ScoreGradeTag from '@/components/ScoreGradeTag.vue'
import RankedStockResultTable from '@/components/ranked-stock/RankedStockResultTable.vue'
import { rankedStockColumns } from '@/components/ranked-stock/types'
import TradeDatePicker from '@/components/TradeDatePicker.vue'
import HelpTip from '@/components/HelpTip.vue'
import HelpHint from '@/components/HelpHint.vue'
import HelpTipItem from '@/components/HelpTipItem.vue'
import PageSegmented from '@/components/PageSegmented.vue'
import PageSettingSection from '@/components/PageSettingSection.vue'
import PageSettingItem from '@/components/PageSettingItem.vue'
import PageSettingsDrawer from '@/components/PageSettingsDrawer.vue'
import PageSettingsTrigger from '@/components/PageSettingsTrigger.vue'
import PageToggleRow from '@/components/PageToggleRow.vue'
import AssetVisibilityActions from '@/components/AssetVisibilityActions.vue'
import AssetVisibilityTag from '@/components/AssetVisibilityTag.vue'
import AssetProfileLabel from '@/components/AssetProfileLabel.vue'
import AppCloseButton from '@/components/AppCloseButton.vue'
import StockStatusTag from '@/components/StockStatusTag.vue'
import AssetProfileSelect from '@/components/asset-search/AssetProfileSelect.vue'
import AssetSearchDrawer from '@/components/asset-search/AssetSearchDrawer.vue'
import {
  assetItemKey,
  assetDisplaySource,
  type AssetBrowseItem,
  type AssetBrowseParams,
  type ProfileSummary,
  type BacktestRunSummary,
} from '@/components/asset-search/types'
import { usePageSettings } from '@/composables/usePageSettings'
import { useDefaultedSessionValue } from '@/composables/useDefaultedSessionValue'
import { useStockChartComponentConfig } from '@/composables/useStockChartComponentConfig'
import { useLegacyStockChartPreferenceMigration } from '@/composables/useLegacyStockChartPreferenceMigration'
import { useTradeDates } from '@/composables/useTradeDates'
import LayoutHost from '@/layout/components/LayoutHost.vue'
import { getPageLayout } from '@/layout'
import { useRemoteLayoutConfig } from '@/composables/useRemoteLayoutConfig'
import { useAuthStore } from '@/stores/auth'
import { hasPermission } from '@/utils/permission'
import type { AppRequestConfig } from '@/api/client'
import { getErrorMessage } from '@/utils/error'
import { formatDateTimeSeconds } from '@/utils/dateTime'
import {
  formatCompactMoneyYuan,
  formatMoney,
  formatMoneyInput,
  parseMoneyInput,
} from '@/utils/money'

type Visibility = 'private' | 'tenant' | 'public'
// 页面负责错误反馈；公开重跑回调继续使用 API 默认的拦截器反馈。
const pageErrorRequest: AppRequestConfig = { skipGlobalError: true }

const auth = useAuthStore()
const settingsOpen = ref(false)
const backtestDefaults = {
  kind: 'strategy' as 'strategy' | 'score_check',
  topN: 10,
  initCap: 1_000_000,
  robustExpanded: false,
  // 对比指数（净值图虚线基准）：业务选项层持久化，与板块行情 SectorsView 同款设置；默认中证 500（与板块行情默认一致）。
  benchmarkCode: '000905.SH',
}
const BACKTEST_KIND_OPTIONS = [
  { label: '策略回测', value: 'strategy' },
  { label: '评分验证', value: 'score_check' },
]
const { settings, isDirty, reset } = usePageSettings('backtest', backtestDefaults)

function resetBacktestSettings(): void {
  chartPreferences.cancelRatioDraft()
  reset()
  resetLayout()
}

// 布局声明统一取自 pageRegistry（单一事实源），不再页面内联手写 PageLayout。
const backtestLayout = getPageLayout('backtest')
const {
  effective: backtestEffective,
  knobs: layoutKnobs,
  setKnob,
  valueOf,
  sourceOf,
  componentValueOf,
  setComponentKnob,
  componentSourceOf,
  layerValuesOf,
  componentLayerValuesOf,
  componentAllowedLayers,
  isDirty: layoutDirty,
  resetAll: resetLayout,
  remoteHydrated,
  whenRemoteHydrated,
  saveRemoteUserConfig,
  remoteSaveError,
} = useRemoteLayoutConfig(backtestLayout)
const chartPreferences = useStockChartComponentConfig({
  componentValueOf,
  setComponentKnob,
  hydrated: remoteHydrated,
})
useLegacyStockChartPreferenceMigration({
  pageKey: 'backtest', componentSourceOf, setComponentKnob, whenRemoteHydrated,
  saveRemoteUserConfig, remoteSaveFailed: () => remoteSaveError.value,
})

// 抽屉「布局」「组件设置」两段由 PageSettingsDrawer 按元数据自动渲染（见 pageRegistry.componentMeta）。
const drawerConfig = { knobs: layoutKnobs, valueOf, sourceOf, setKnob, componentValueOf, setComponentKnob, componentSourceOf, layerValuesOf, componentLayerValuesOf, componentAllowedLayers, save: saveRemoteUserConfig }

// 逐笔表排序/列显隐（组件配置层 trades slot）：抽屉写值由 ComponentAutoSettings 自动渲染；页面只读 getter。
type TradeSort = 'entry' | 'exit' | 'return' | 'hold'
const TRADE_SORT_PROPS: Record<string, TradeSort> = {
  entry_date: 'entry',
  exit_date: 'exit',
  return_pct: 'return',
  hold_days: 'hold',
}
const tradeSortConfigured = computed<TradeSort>(() => {
  const raw = componentValueOf('trades', 'defaultSort')
  return raw === 'exit' || raw === 'return' || raw === 'hold' ? raw : 'entry'
})
// 排序单向：配置层默认值 → 会话覆盖；列头排序只写会话，不写回配置层。
const tradeSortSession = ref<TradeSort | null>(null)
watch(tradeSortConfigured, () => { tradeSortSession.value = null })
const tradeSort = computed<TradeSort>(() => tradeSortSession.value ?? tradeSortConfigured.value)
const tradeDefaultSort = computed(() => {
  if (tradeSort.value === 'exit') return { prop: 'exit_date', order: 'descending' }
  if (tradeSort.value === 'return') return { prop: 'return_pct', order: 'descending' }
  if (tradeSort.value === 'hold') return { prop: 'hold_days', order: 'descending' }
  return { prop: 'entry_date', order: 'descending' }
})
const tradeHidden = computed<string[]>(() => (componentValueOf('trades', 'hiddenColumns') as string[]) ?? [])
function tradeColVisible(key: string): boolean {
  return !tradeHidden.value.includes(key)
}
function tableBorder(slotId: string): boolean {
  return componentValueOf(slotId, 'border') === true
}
function onTradeSortChange({ prop }: { prop: string; order: string | null }): void {
  tradeSortSession.value = TRADE_SORT_PROPS[prop] ?? 'entry'
}

const kind = useDefaultedSessionValue(computed<'strategy' | 'score_check'>(() => (
  settings.kind === 'score_check' ? 'score_check' : 'strategy'
)))
const DEFAULT_DATE_START = '2024-01-01'
const DEFAULT_DATE_END = '2024-12-31'
const DEFAULT_INDUSTRY_PCT = 20
const dateStart = ref(DEFAULT_DATE_START)
const dateEnd = ref(DEFAULT_DATE_END)
const profileId = ref<string>('')      // 筛选方案（候选池），空=全市场候选
const scoreProfileId = ref<string>('') // 评分方案（排序/验证）
const tradeProfileId = ref<string>('') // 买卖方案（买/卖/兜底）
const topN = useDefaultedSessionValue(computed(() => Number(settings.topN)))
const initCap = useDefaultedSessionValue(computed(() => Number(settings.initCap)))
const industryOn = ref(false)
const industryPct = ref(DEFAULT_INDUSTRY_PCT) // 单行业持仓上限 %
// 基准指数选择（净值图虚线对比）：默认中证 500（与板块行情同款设置），可切换其它指数；fetch 结果注入 EquityChart。
// 单向：抽屉「默认对比指数」→ 会话 ref；主区改动只进会话态，不写回默认。
const benchChoice = useDefaultedSessionValue(computed(() => String(settings.benchmarkCode)))
const benchmarkEquity = ref<BenchmarkEquity | null>(null)
let benchRequestVersion = 0
async function loadBenchmarkEquity() {
  const code = benchChoice.value
  if (!code) { benchmarkEquity.value = null; return }
  if (!strat.value) return
  const version = ++benchRequestVersion
  const initCapV = strat.value.initial_capital ?? initCap.value
  const eq = await fetchBenchmarkEquity(code, dateStart.value, dateEnd.value, initCapV)
  if (version === benchRequestVersion) benchmarkEquity.value = eq
}
const profiles = ref<Profile[]>([])
const scoreProfiles = ref<ScoreProfileSummary[]>([])
const tradeProfiles = ref<TradeProfileSummary[]>([])
const nextRunSourceRef = ref('')

// 加载查看的临时只读项（2026-08-01 复审重裁：选择器外只读展示，DESIGN ElSelect 递归契约不破）。
// 组件保留会话候选，不把外部 ref 写入 mine 选值；选择器外 chip 显示本次运行方案的名称和版本；
// 不持久化、不自动运行。普通回测与稳健性测试都按 tempSelected 快照 > mine 选择器值 > 空取 ref。
// 用户选 mine 项 / 复制为我的即清；载入历史则按归属重新投影为 mine 选中、只读快照或失效态。
const tempSelected = ref<{
  screen: Profile | null
  score: ScoreProfileSummary | null
  trade: TradeProfileSummary | null
}>({ screen: null, score: null, trade: null })
type ProfileKind = 'screen' | 'score' | 'trade'
type HistoryProfileDisplay = {
  ref: string
  name?: string | null
  version?: number | null
  ownerLabel?: string | null
}
// 历史记录保存的是稳定 ref，方案不一定属于「我的」候选。这里单独保存历史展示信息：
// mine ref 投影回选择器，系统/公开 ref 投影为选择器外只读快照，失效 ref 明示并 fail-closed。
const historyProfileDisplays = ref<Record<ProfileKind, HistoryProfileDisplay | null>>({
  screen: null,
  score: null,
  trade: null,
})
const historyProfileUnavailable = ref<Record<ProfileKind, boolean>>({
  screen: false,
  score: false,
  trade: false,
})
// 三类 mine 列表就绪屏障：历史记录等程序化来源可能先写入 ref；列表 ready 后统一
// reconcileProfileRefs() 校验并清掉非 mine/非临时残留，避免 opaque ref 暴露给选择器。
const readyFlags = ref({ screen: false, score: false, trade: false })
const screenProfileSelectRef = ref<InstanceType<typeof AssetProfileSelect> | null>(null)
const scoreProfileSelectRef = ref<InstanceType<typeof AssetProfileSelect> | null>(null)
const tradeProfileSelectRef = ref<InstanceType<typeof AssetProfileSelect> | null>(null)

// mine 列表 ready 前只向选择器暴露空值，避免程序化加载的 opaque ref 短暂回显。
function guardedProfileModel(kind: ProfileKind, model: typeof profileId) {
  return computed({
    get: () => readyFlags.value[kind] ? model.value : '',
    set: (value: string) => { model.value = value },
  })
}
const guardedScreenProfileId = guardedProfileModel('screen', profileId)
const guardedScoreProfileId = guardedProfileModel('score', scoreProfileId)
const guardedTradeProfileId = guardedProfileModel('trade', tradeProfileId)

// 「复用参数重跑」从公开回测 params 复制字段的允许白名单（R6，P1-1）：含撮合参数（卖出 MA/止盈/止损/
// 最大持有/调仓）、基准与分层阈值——缺一即改变撮合与收益，非「以公开回测参数重跑」。剔除 source_run_ref。
const RERUN_BASE_FIELDS = [
  'date_start', 'date_end', 'profile_id', 'score_profile_id', 'trade_profile_id',
  'horizons', 'thresholds', 'benchmark',
] as const
const RERUN_STRATEGY_FIELDS = [
  'top_n', 'initial_capital', 'industry_max_pct',
  'sell_ma_period', 'take_profit', 'stop_loss', 'max_hold_days', 'rebalance_days',
] as const

// R3/R5/R7：三方案选择器统一走 AssetProfileSelect（select 形态）——下拉只加载「我的」source=mine 纯 owner，
// 「搜索」入口打开共享抽屉（系统内置/租户公开/全体公开）。「加载查看」走方案b：只记 tempSelected 快照、
// 选择器外 chip 展示（非 opaque ref），运行按快照优先（tempSelected > mine > 空），不写入 mine 选值、
// 不自动运行、不持久化；切换/复制/载入历史只清当前快照，会话候选保留。「复制为我的」并入候选并由组件选中。
// 组件为列表唯一事实源（onMounted fetchMine → emit ready），父页不再各自 list_visible，normalize 时序移 ready。
async function fetchMineScreenProfiles(): Promise<ProfileSummary[]> {
  if (!hasPermission(auth.role, auth.permissions, 'screen-profile:view')) return []
  return listProfiles('mine')
}
async function fetchMineScoreProfiles(): Promise<ProfileSummary[]> {
  if (!hasPermission(auth.role, auth.permissions, 'score-profile:view')) return []
  return listScoreProfiles('mine')
}
async function fetchMineTradeProfiles(): Promise<ProfileSummary[]> {
  if (!hasPermission(auth.role, auth.permissions, 'trade-profile:view')) return []
  return listTradeProfiles('mine')
}
function browseScreen(params: AssetBrowseParams) {
  return browseProfiles(params)
}
function browseScore(params: AssetBrowseParams) {
  return browseScoreProfiles(params)
}
function browseTrade(params: AssetBrowseParams) {
  return browseTradeProfiles(params)
}
function copyAnyScreenProfile(item: ProfileSummary) {
  return copyProfile(item.profile_ref || item.id)
}
function copyAnyScoreProfile(item: ProfileSummary) {
  return copyScoreProfile(item.profile_ref || item.id)
}
function copyAnyTradeProfile(item: ProfileSummary) {
  return copyTradeProfile(item.profile_ref || item.id)
}

function screenProfileKey(p: Profile): string {
  return p.profile_ref || p.id
}

function normalizeScreenProfileKey(value?: string | null): string {
  if (!value) return ''
  const matched = profiles.value.find((p) => screenProfileKey(p) === value || p.id === value)
  return matched ? screenProfileKey(matched) : value
}
const selectedScreenProfile = computed(() =>
  profiles.value.find((p) => screenProfileKey(p) === profileId.value || p.id === profileId.value)
  ?? (tempSelected.value.screen && screenProfileKey(tempSelected.value.screen) === profileId.value
    ? tempSelected.value.screen : null),
)

function scoreProfileKey(p: ScoreProfileSummary): string {
  return p.profile_ref || p.id
}

function normalizeScoreProfileKey(value?: string | null): string {
  if (!value) return ''
  const matched = scoreProfiles.value.find((p) => scoreProfileKey(p) === value || p.id === value)
  return matched ? scoreProfileKey(matched) : value
}
const selectedScoreProfile = computed(() =>
  scoreProfiles.value.find((p) => scoreProfileKey(p) === scoreProfileId.value || p.id === scoreProfileId.value)
  ?? (tempSelected.value.score && scoreProfileKey(tempSelected.value.score) === scoreProfileId.value
    ? tempSelected.value.score : null),
)

function tradeProfileKey(p: TradeProfileSummary): string {
  return p.profile_ref || p.id
}

function normalizeTradeProfileKey(value?: string | null): string {
  if (!value) return ''
  const matched = tradeProfiles.value.find((p) => tradeProfileKey(p) === value || p.id === value)
  return matched ? tradeProfileKey(matched) : value
}
const selectedTradeProfile = computed(() =>
  tradeProfiles.value.find((p) => tradeProfileKey(p) === tradeProfileId.value || p.id === tradeProfileId.value)
  ?? (tempSelected.value.trade && tradeProfileKey(tempSelected.value.trade) === tradeProfileId.value
    ? tempSelected.value.trade : null),
)
const loading = ref(false)
const resultError = ref('')
const resultErrorContext = ref<'run' | 'history'>('run')
const strat = ref<StrategyResult | null>(null)
const sig = ref<Layers | null>(null)
const runTime = ref('')          // 当前展示结果的回测运行时间（加载历史时显示；刚跑完为空）
const fromHistory = ref(false)   // 当前结果是否来自加载历史

// 稳健性测试展开态单向：抽屉默认值 → 会话 ref；折叠面板点击只进会话态，不写回默认。
const robustPanels = useDefaultedSessionValue(computed<string[]>(() => (
  settings.robustExpanded ? ['robust'] : []
)))
const tradeRows = computed(() => {
  const list = [...(strat.value?.trades ?? [])]
  if (tradeSort.value === 'return') list.sort((a, b) => b.return_pct - a.return_pct)
  else if (tradeSort.value === 'hold') list.sort((a, b) => b.hold_days - a.hold_days)
  else if (tradeSort.value === 'exit') list.sort((a, b) => b.exit_date.localeCompare(a.exit_date))
  else list.sort((a, b) => b.entry_date.localeCompare(a.entry_date))
  return list
})

// 交易日历（全站共享，数据范围用于提示行）
const { dataMin, dataMax, prevTradeDate } = useTradeDates()

// 历史回测（已落库，可重新载入，不必反复重跑）
const runHistory = ref<RunSummary[]>([])
const historyError = ref('')
const selectedRun = ref<string>('')
type HistoryRetryTarget =
  | { kind: 'load'; id: string; summary?: RunSummary }
  | { kind: 'mine-switch'; id: string }
const historyRetryTarget = ref<HistoryRetryTarget | null>(null)
// 公开抽屉「加载查看」只保存当前只读快照，不写入 mine-only runHistory，也不把 opaque ref 写入 ElSelect。
const externalRunSummary = ref<RunSummary | null>(null)
// 当前结果实际使用的评分方案 ref（P1-2）：doRun 用冻结 body、loadRun 用该 run params 写入；
// 「查看买入当日榜单」以此为准（与回测口径一致），不用 mine 选择器值——避免加载公开/历史后选择器为空或仍 mine-A 时下钻错口径。
const resultScoreRef = ref('')
const runVisibilitySaving = ref(false)
type RunViewSnapshot = {
  dateStart: string
  dateEnd: string
  profileId: string
  scoreProfileId: string
  tradeProfileId: string
  topN: number
  initCap: number
  industryOn: boolean
  industryPct: number
  tempSelected: typeof tempSelected.value
  historyProfileDisplays: typeof historyProfileDisplays.value
  historyProfileUnavailable: typeof historyProfileUnavailable.value
  selectedRun: string
  resultScoreRef: string
  strat: StrategyResult | null
  sig: Layers | null
  runTime: string
  fromHistory: boolean
  dirty: boolean
  nextRunSourceRef: string
}
let beforeExternalRun: RunViewSnapshot | null = null
let runLoadSequence = 0
let historyLoadSequence = 0
type RunViewOperationKind = 'run' | 'load'
const activeRunOperation = ref<{ sequence: number; kind: RunViewOperationKind } | null>(null)
const runningRun = computed(() => activeRunOperation.value?.kind === 'run')

function beginRunViewOperation(kind: RunViewOperationKind): number {
  const sequence = ++runLoadSequence
  activeRunOperation.value = { sequence, kind }
  return sequence
}

function invalidateRunViewOperation(): void {
  runLoadSequence += 1
  activeRunOperation.value = null
  loading.value = false
}

function finishRunViewOperation(sequence?: number): void {
  if (sequence === undefined) {
    loading.value = false
    return
  }
  if (activeRunOperation.value?.sequence !== sequence) return
  activeRunOperation.value = null
  loading.value = false
}

function snapshotRunView(): RunViewSnapshot {
  return {
    dateStart: dateStart.value,
    dateEnd: dateEnd.value,
    profileId: profileId.value,
    scoreProfileId: scoreProfileId.value,
    tradeProfileId: tradeProfileId.value,
    topN: topN.value,
    initCap: initCap.value,
    industryOn: industryOn.value,
    industryPct: industryPct.value,
    tempSelected: { ...tempSelected.value },
    historyProfileDisplays: { ...historyProfileDisplays.value },
    historyProfileUnavailable: { ...historyProfileUnavailable.value },
    selectedRun: selectedRun.value,
    resultScoreRef: resultScoreRef.value,
    strat: strat.value,
    sig: sig.value,
    runTime: runTime.value,
    fromHistory: fromHistory.value,
    dirty: dirty.value,
    nextRunSourceRef: nextRunSourceRef.value,
  }
}

function restoreRunView(snapshot: RunViewSnapshot) {
  loadingRun.value = true
  dateStart.value = snapshot.dateStart
  dateEnd.value = snapshot.dateEnd
  profileId.value = snapshot.profileId
  scoreProfileId.value = snapshot.scoreProfileId
  tradeProfileId.value = snapshot.tradeProfileId
  topN.value = snapshot.topN
  initCap.value = snapshot.initCap
  industryOn.value = snapshot.industryOn
  industryPct.value = snapshot.industryPct
  tempSelected.value = { ...snapshot.tempSelected }
  historyProfileDisplays.value = { ...snapshot.historyProfileDisplays }
  historyProfileUnavailable.value = { ...snapshot.historyProfileUnavailable }
  selectedRun.value = snapshot.selectedRun
  resultScoreRef.value = snapshot.resultScoreRef
  strat.value = snapshot.strat
  sig.value = snapshot.sig
  runTime.value = snapshot.runTime
  fromHistory.value = snapshot.fromHistory
  nextRunSourceRef.value = snapshot.nextRunSourceRef
  nextTick(() => {
    dirty.value = snapshot.dirty
    loadingRun.value = false
  })
}

const loadingRun = ref(false)
const dirty = ref(true)

/** 当前输入上下文变化后，旧结果及其历史归属必须一起失效。 */
function clearDisplayedRunResult() {
  strat.value = null
  sig.value = null
  selectedRun.value = ''
  externalRunSummary.value = null
  resultScoreRef.value = ''
  runTime.value = ''
  fromHistory.value = false
  resultError.value = ''
}

const hasResettableRunParams = computed(() => Boolean(
  dateStart.value !== DEFAULT_DATE_START
  || dateEnd.value !== DEFAULT_DATE_END
  || profileId.value
  || scoreProfileId.value
  || tradeProfileId.value
  || topN.value !== Number(settings.topN)
  || initCap.value !== Number(settings.initCap)
  || industryOn.value
  || industryPct.value !== DEFAULT_INDUSTRY_PCT
  || selectedRun.value
  || externalRunSummary.value
  || nextRunSourceRef.value
  || strat.value
  || sig.value
  || resultError.value
  || Object.values(tempSelected.value).some(Boolean)
  || Object.values(historyProfileDisplays.value).some(Boolean)
  || Object.values(historyProfileUnavailable.value).some(Boolean)
))

/** 恢复当前回测模式的初始参数，并彻底退出历史/公开记录投影。 */
function resetRunParams() {
  if (!hasResettableRunParams.value) return
  invalidateRunViewOperation()
  beforeExternalRun = null
  historyRetryTarget.value = null
  loadingRun.value = true
  dateStart.value = DEFAULT_DATE_START
  dateEnd.value = DEFAULT_DATE_END
  profileId.value = ''
  scoreProfileId.value = ''
  tradeProfileId.value = ''
  topN.value = Number(settings.topN)
  initCap.value = Number(settings.initCap)
  industryOn.value = false
  industryPct.value = DEFAULT_INDUSTRY_PCT
  tempSelected.value = { screen: null, score: null, trade: null }
  historyProfileDisplays.value = { screen: null, score: null, trade: null }
  historyProfileUnavailable.value = { screen: false, score: false, trade: false }
  screenProfileSelectRef.value?.clearTransient?.()
  scoreProfileSelectRef.value?.clearTransient?.()
  tradeProfileSelectRef.value?.clearTransient?.()
  nextRunSourceRef.value = ''
  clearDisplayedRunResult()
  nextTick(() => {
    dirty.value = true
    loadingRun.value = false
  })
}

// 切换"策略/信号"标签 → 清空下方结果（避免显示与当前模式不符的旧结果）
// loadingRun 期间由程序设置参数，不触发清空 / 不置脏
// loadingRun 只保护同步的程序化参数应用；网络等待由 activeRunOperation 持有。
// 用户改任一影响 buildBody 的参数时取消当前 operation 并释放其 loading，旧响应只能静默落库，不能回写页面。
watch(kind, () => {
  if (loadingRun.value) return
  invalidateRunViewOperation()
  beforeExternalRun = null
  clearDisplayedRunResult()
  dirty.value = true
  loadHistory()  // 历史按 kind 分别加载，策略与评分验证不混展
}, { flush: 'sync' })

// 运行按钮状态机：dirty=true 蓝色可点；出结果/载入历史后置 false（灰、不可点）；改任一参数恢复
watch(
  [
    dateStart, dateEnd, profileId, scoreProfileId, tradeProfileId, topN, initCap, industryOn, industryPct,
    () => effectiveProfileRefs().screen,
    () => effectiveProfileRefs().score,
    () => effectiveProfileRefs().trade,
  ],
  () => {
    if (loadingRun.value) return // 程序化恢复参数：不置脏、不使 token 失效
    dirty.value = true
    if (activeRunOperation.value) invalidateRunViewOperation()
    clearDisplayedRunResult()
    beforeExternalRun = null
  },
  { flush: 'sync' },
)
// 基准选择切换 → 重新拉指数曲线；无有效对比（不对比/无结果）时置空回退默认实线。
watch(benchChoice, () => { benchmarkEquity.value = null; loadBenchmarkEquity() })
// 新回测结果出现（日期区间可能变化）→ 按当前区间重拉基准曲线；不覆盖用户的选择。
watch(strat, (s) => {
  if (s) loadBenchmarkEquity()
  else benchmarkEquity.value = null
})
// 程序化改参（运行/载入历史）后清脏：等参数 watcher 跑完再置 false
function clearDirtySoon() {
  nextTick(() => { dirty.value = false; loadingRun.value = false })
}

// 切换/清空选择即丢弃对应临时只读项（P1-2）：当前 key 不等于临时项 key 立即清除，
// 避免「加载公开方案→切到自己的方案」后仍把有效选择当作临时项。
watch(profileId, (v) => {
  if (loadingRun.value) return
  if (historyProfileDisplays.value.screen) return
  if (tempSelected.value.screen && screenProfileKey(tempSelected.value.screen) !== v) tempSelected.value.screen = null
}, { flush: 'sync' })
watch(scoreProfileId, (v) => {
  if (loadingRun.value) return
  if (historyProfileDisplays.value.score) return
  if (tempSelected.value.score && scoreProfileKey(tempSelected.value.score) !== v) tempSelected.value.score = null
}, { flush: 'sync' })
watch(tradeProfileId, (v) => {
  if (loadingRun.value) return
  if (historyProfileDisplays.value.trade) return
  if (tempSelected.value.trade && tradeProfileKey(tempSelected.value.trade) !== v) tempSelected.value.trade = null
}, { flush: 'sync' })

// 方案(版本) 文本：名字带版本号，空则占位
function nameVer(name?: string | null, ver?: number | null, fallback = ''): string {
  if (!name) return fallback
  return ver != null ? `${name}(v${ver})` : name
}

function runKey(r: RunSummary): string {
  return r.run_ref || r.asset_ref || r.id
}

const selectedMineRunSummary = computed(() =>
  runHistory.value.find((r) => runKey(r) === selectedRun.value || r.id === selectedRun.value),
)
const selectedRunSummary = computed(() => externalRunSummary.value ?? selectedMineRunSummary.value)
const activeRunRef = computed(() =>
  externalRunSummary.value ? runKey(externalRunSummary.value) : selectedRun.value,
)
// fail-closed（P1-4 + 复审 P2-1）：有摘要按 readonly；无摘要但存在选中值时一律只读（不启用删除/公开编辑）——
// 加载查看注入的公开行或选中后摘要暂缺（含非 loading 场景），默认可写会让「删除」对他人记录错误可点。
const selectedRunReadonly = computed(() =>
  selectedRunSummary.value ? !!selectedRunSummary.value.readonly : !!activeRunRef.value,
)
const canPublishTenant = computed(() =>
  hasPermission(auth.role, auth.permissions, 'backtest:publish-tenant'),
)
const canPublishPublic = computed(() =>
  hasPermission(auth.role, auth.permissions, 'backtest:publish-public'),
)
// R5/R6：顶部记录只加载 mine；租户/全体公开记录统一走搜索抽屉，避免来源下拉与公开浏览形成重复入口。
// 抽屉负责表格化浏览、加载查看和复用参数重跑（不弹确认，组件行内 loading，决策2）。
const canViewBacktest = computed(() =>
  hasPermission(auth.role, auth.permissions, 'backtest:view'),
)
const runBrowseOpen = ref(false)
// 卖出原因命中的具体指标（卖树部分命中时）：解析 exit_detail(JSON 数组)；全命中/非卖树返回空
function sellTags(row: TradeRow): string[] {
  if (!row.exit_detail) return []
  try {
    const arr = JSON.parse(row.exit_detail)
    return Array.isArray(arr) ? arr : []
  } catch { return [] }
}
// 卖出原因文本：部分命中 → 命中的具体指标；否则原因类别（卖出信号/止盈/止损/到期…）
function exitText(t: TradeRow): string {
  const tags = sellTags(t)
  return tags.length ? tags.join(' / ') : t.exit_reason
}
// 历史下拉项：名称=评分方案(版本)-筛选方案(版本)-买卖方案(版本)·年份；评分验证只含评分方案
function toRunOption(r: RunSummary) {
  const y1 = (r.date_start || '').slice(0, 4)
  const y2 = (r.date_end || '').slice(0, 4)
  const year = y1 === y2 ? y1 : `${y1}~${y2}`
  const score = nameVer(r.score_profile_name, r.score_profile_version, '—')
  let who: string
  if (r.kind === 'strategy') {
    const screen = nameVer(r.profile_name, r.profile_version, '—')
    const trade = nameVer(r.trade_profile_name, r.trade_profile_version, '—')
    who = `${score}-${screen}-${trade}`
  } else {
    who = score
  }
  const ret = r.total_return
  return {
    id: runKey(r), label: `${who}·${year}`,
    range: `${(r.date_start || '').slice(0, 10)} ~ ${(r.date_end || '').slice(0, 10)}`,
    color: marketValueClass(ret, { input: 'ratio' }) === 'up' ? 'var(--market-up-color)' : marketValueClass(ret, { input: 'ratio' }) === 'down' ? 'var(--market-down-color)' : '',
    retTxt: formatReturn(ret),
    displaySource: assetDisplaySource(r.source),
    ownerLabel: r.owner_label,
  }
}
const runOptions = computed(() => runHistory.value.map(toRunOption))
const historyPlaceholder = computed(() => runOptions.value.length ? '请选择回测记录（可选）' : '暂无我的回测')
const externalRunOption = computed(() =>
  externalRunSummary.value ? toRunOption(externalRunSummary.value) : null,
)

// 选中方案 → 拉取其条件并渲染为可读介绍
const selectedProfile = ref<Profile | null>(null)
watch(profileId, async (id) => {
  selectedProfile.value = id ? await getProfile(id).catch(() => null) : null
})
const CMP_TXT: Record<string, string> = {
  '==': '=', '!=': '≠', '>': '>', '>=': '≥', '<': '<', '<=': '≤', between: '介于',
}
const FIELD_TXT: Record<string, string> = {
  is_bull_arrange: '多头排列', ma20_up: 'MA20向上', is_high_2y: '两年新高',
  is_vol_breakout: '放量突破', is_platform_breakout: '平台突破',
  is_turnover_healthy: '换手健康', rs_pct: 'RS强度', float_mv: '流通市值',
  above_ma250: '站上年线',
}
function astToText(node: any): string {
  if (!node) return ''
  if (node.op) {
    const join = node.op === 'AND' ? ' 且 ' : node.op === 'OR' ? ' 或 ' : ''
    const inner = (node.children || []).map(astToText).filter(Boolean).join(join)
    return node.op === 'NOT' ? `非(${inner})` : inner ? `(${inner})` : ''
  }
  if (node.type === 'expr') return node.expr
  if (node.type === 'col') {
    const f = FIELD_TXT[node.field] || node.field
    const cmp = CMP_TXT[node.cmp] || node.cmp
    if (node.cmp === 'between') return `${f} 介于 ${node.value?.[0]}~${node.value?.[1]}`
    if (node.value === true) return f
    if (node.value === false) return `非${f}`
    return `${f} ${cmp} ${node.value}`
  }
  return ''
}
const profileDesc = computed(() =>
  selectedProfile.value ? astToText(selectedProfile.value.expression) : '',
)

// 统一归属校验：列表 ready 后校验程序化加载的历史方案引用，清掉既不在 mine 列表、
// 也不是本次会话临时只读项的残留（R3 下拉仅 mine）。
const staleProfileNoticeKeys = new Set<string>()
const pendingStaleProfileKinds = new Set<string>()
function queueStaleProfileNotice(kind: string, refValue: string) {
  const key = `${kind}:${refValue}`
  if (!staleProfileNoticeKeys.has(key)) {
    staleProfileNoticeKeys.add(key)
    pendingStaleProfileKinds.add(kind)
  }
}
function flushStaleProfileNotice() {
  if (!Object.values(readyFlags.value).every(Boolean) || !pendingStaleProfileKinds.size) return
  ElMessage.warning(`原${[...pendingStaleProfileKinds].join('/')}方案已不可用（非「我的」方案），请重新选择`)
  pendingStaleProfileKinds.clear()
}
function reconcileProfileRefs() {
  if (readyFlags.value.screen && profileId.value
    && !profiles.value.some((p) => screenProfileKey(p) === profileId.value)
    && !(tempSelected.value.screen && screenProfileKey(tempSelected.value.screen) === profileId.value)) {
    queueStaleProfileNotice('选股', profileId.value); profileId.value = ''
  }
  if (readyFlags.value.score && scoreProfileId.value
    && !scoreProfiles.value.some((p) => scoreProfileKey(p) === scoreProfileId.value)
    && !(tempSelected.value.score && scoreProfileKey(tempSelected.value.score) === scoreProfileId.value)) {
    queueStaleProfileNotice('评分', scoreProfileId.value); scoreProfileId.value = ''
  }
  if (readyFlags.value.trade && tradeProfileId.value
    && !tradeProfiles.value.some((p) => tradeProfileKey(p) === tradeProfileId.value)
    && !(tempSelected.value.trade && tradeProfileKey(tempSelected.value.trade) === tradeProfileId.value)) {
    queueStaleProfileNotice('买卖', tradeProfileId.value); tradeProfileId.value = ''
  }
  flushStaleProfileNotice()
}

// 组件 ready：列表落地后置就绪标记、规范化引用，再统一校验程序化加载的历史方案。
function onScreenReady(items: ProfileSummary[]) {
  profiles.value = items as Profile[]
  readyFlags.value.screen = true
  profileId.value = normalizeScreenProfileKey(profileId.value)
  projectHistoryProfile('screen')
  reconcileProfileRefs()
}
function onScoreReady(items: ProfileSummary[]) {
  scoreProfiles.value = items as ScoreProfileSummary[]
  readyFlags.value.score = true
  scoreProfileId.value = normalizeScoreProfileKey(scoreProfileId.value)
  projectHistoryProfile('score')
  reconcileProfileRefs()
}
function onTradeReady(items: ProfileSummary[]) {
  tradeProfiles.value = items as TradeProfileSummary[]
  readyFlags.value.trade = true
  tradeProfileId.value = normalizeTradeProfileKey(tradeProfileId.value)
  projectHistoryProfile('trade')
  reconcileProfileRefs()
}
// 「加载查看」：组件保留会话候选，页面记快照供选择器外 chip 展示 + 运行时按快照取 ref，
// 不设为选择器选中；切换只释放当前运行快照，组件会话候选保留，可再次选择加载。
function onScreenLoaded(item: ProfileSummary) {
  historyProfileDisplays.value.screen = null
  historyProfileUnavailable.value.screen = false
  tempSelected.value.screen = item as Profile
}
function onScoreLoaded(item: ProfileSummary) {
  historyProfileDisplays.value.score = null
  historyProfileUnavailable.value.score = false
  tempSelected.value.score = item as ScoreProfileSummary
}
function onTradeLoaded(item: ProfileSummary) {
  historyProfileDisplays.value.trade = null
  historyProfileUnavailable.value.trade = false
  tempSelected.value.trade = item as TradeProfileSummary
}
// 复制成功（P1-2 修复：不复用 onXLoaded）：组件已把新资产并入其 mine 列表并选中、经 ready 喂页面列表、
// copiedItem 回写完整 summary。复制结果归「我的」，不是临时项——清空对应 tempSelected（避免误当临时剔除），
// 选中交给组件的 update:modelValue。
function onScreenCopied(_item: ProfileSummary) {
  clearTemp('screen', false)
}
function onScoreCopied(_item: ProfileSummary) {
  clearTemp('score', false)
}
function onTradeCopied(_item: ProfileSummary) {
  clearTemp('trade', false)
}
function clearTemp(kind: 'screen' | 'score' | 'trade', remove = true) {
  const current = tempSelected.value[kind]
  tempSelected.value[kind] = null
  historyProfileDisplays.value[kind] = null
  historyProfileUnavailable.value[kind] = false
  const selector = {
    screen: screenProfileSelectRef,
    score: scoreProfileSelectRef,
    trade: tradeProfileSelectRef,
  }[kind]
  if (remove && current) selector.value?.clearTransient?.(current.profile_ref || current.id)
}
// 用户在选择器里做出选择（含重选同一值）即丢弃对应临时只读快照：watch(profileId) 只在值变化时触发，
// 覆盖不了「已选 mine-A → 加载公开 → 重选同一 mine-A」这一边界；故在 update:modelValue 回调里无条件清。
// 不改组件选中逻辑（组件会话候选由组件自管，运行取的是页面 tempSelected 快照，组件残留不影响口径）。
function onScoreSelect() { clearTemp('score', false) }
function onScreenSelect() { clearTemp('screen', false) }
function onTradeSelect() { clearTemp('trade', false) }

// external 模式的当前项由页面快照确定，不能按 mine 选择器的 modelValue 判断。
function onLoadedRemoved(kind: 'screen' | 'score' | 'trade', item: ProfileSummary) {
  const current = tempSelected.value[kind]
  if (current && (current.profile_ref || current.id) === (item.profile_ref || item.id)) {
    clearTemp(kind, false)
  }
}

async function loadHistory(sequence?: number): Promise<boolean> {
  const requestSequence = ++historyLoadSequence
  const requestedKind = kind.value
  historyError.value = ''
  try {
    const runs = (await listRuns(requestedKind, 'mine', undefined, pageErrorRequest)).runs
    if (
      requestSequence !== historyLoadSequence
      || requestedKind !== kind.value
      || (sequence !== undefined && sequence !== runLoadSequence)
    ) return false
    runHistory.value = runs
    return true
  } catch (error) {
    if (
      requestSequence !== historyLoadSequence
      || requestedKind !== kind.value
      || (sequence !== undefined && sequence !== runLoadSequence)
    ) return false
    historyError.value = getErrorMessage(error, '历史回测加载失败')
    return false
  }
}

function projectHistoryProfile(kind: ProfileKind) {
  const display = historyProfileDisplays.value[kind]
  if (!display) return
  const config = {
    screen: {
      ready: readyFlags.value.screen,
      items: profiles.value as ProfileSummary[],
      getKey: (item: ProfileSummary) => screenProfileKey(item as Profile),
      setModel: (value: string) => { profileId.value = value },
      setTemp: (item: ProfileSummary | null) => { tempSelected.value.screen = item as Profile | null },
    },
    score: {
      ready: readyFlags.value.score,
      items: scoreProfiles.value as ProfileSummary[],
      getKey: (item: ProfileSummary) => scoreProfileKey(item as ScoreProfileSummary),
      setModel: (value: string) => { scoreProfileId.value = value },
      setTemp: (item: ProfileSummary | null) => { tempSelected.value.score = item as ScoreProfileSummary | null },
    },
    trade: {
      ready: readyFlags.value.trade,
      items: tradeProfiles.value as ProfileSummary[],
      getKey: (item: ProfileSummary) => tradeProfileKey(item as TradeProfileSummary),
      setModel: (value: string) => { tradeProfileId.value = value },
      setTemp: (item: ProfileSummary | null) => { tempSelected.value.trade = item as TradeProfileSummary | null },
    },
  }[kind]
  const mine = config.items.find((item) => config.getKey(item) === display.ref || item.id === display.ref)
  if (mine) {
    config.setTemp(null)
    historyProfileUnavailable.value[kind] = false
    historyProfileDisplays.value[kind] = null
    config.setModel(config.getKey(mine))
    return
  }

  // 列表未 ready 时也绝不把 raw ref 写入 ElSelect；先展示后端随历史摘要返回的名称，ready 后再判归属。
  config.setModel('')
  if (display.name) {
    config.setTemp({
      id: display.ref,
      profile_ref: display.ref,
      name: display.name,
      version: display.version ?? 0,
      is_preset: false,
      readonly: true,
      owner_label: display.ownerLabel ?? undefined,
    })
    historyProfileUnavailable.value[kind] = false
  } else {
    config.setTemp(null)
    historyProfileUnavailable.value[kind] = config.ready
  }
}

function applyRunParams(run: RunSummary, summary?: RunSummary) {
  let p: any = {}
  try { p = JSON.parse(run.params || '{}') } catch { /* ignore */ }
  const display = summary ?? run
  // 载入历史为权威参数来源。方案 ref 不直接写入 mine-only 选择器，统一投影为 mine 选中、只读名称或失效态。
  tempSelected.value = { screen: null, score: null, trade: null }
  historyProfileDisplays.value = {
    screen: p.profile_id ? {
      ref: p.profile_id,
      name: display.profile_name,
      version: display.profile_version,
      ownerLabel: display.owner_label,
    } : null,
    score: p.score_profile_id ? {
      ref: p.score_profile_id,
      name: display.score_profile_name,
      version: display.score_profile_version,
      ownerLabel: display.owner_label,
    } : null,
    trade: p.trade_profile_id ? {
      ref: p.trade_profile_id,
      name: display.trade_profile_name,
      version: display.trade_profile_version,
      ownerLabel: display.owner_label,
    } : null,
  }
  historyProfileUnavailable.value = { screen: false, score: false, trade: false }
  if (p.date_start) dateStart.value = ymd(p.date_start)
  if (p.date_end) dateEnd.value = ymd(p.date_end)
  if (!p.profile_id) profileId.value = ''
  if (!p.score_profile_id) scoreProfileId.value = ''
  if (!p.trade_profile_id) tradeProfileId.value = ''
  projectHistoryProfile('screen')
  projectHistoryProfile('score')
  projectHistoryProfile('trade')
  if (p.top_n) topN.value = p.top_n
  if (p.initial_capital) initCap.value = p.initial_capital
  industryOn.value = p.industry_max_pct != null; if (p.industry_max_pct != null) industryPct.value = Math.round(p.industry_max_pct * 100)
  return p
}

// 从历史重新载入某次回测结果（不重跑）
// 从历史重新载入某次回测结果（不重跑）
// P1-1（五次复审）拆为「获取详情」+「应用详情」两段：fetch 只发请求、不碰任何页面状态；
// apply 才写表单/结果/resultScoreRef。调用方可在「获取成功」后原子执行 应用详情+commitMineRun，
// 避免详情加载失败时已永久清掉公开摘要与进入前快照（用户既看不到新结果也无法恢复原现场）。
async function fetchRunDetail(id: string) {
  const r = await getRun(id, pageErrorRequest)
  if (!r?.run) throw new Error('历史回测载入失败')
  return r
}

// 应用已获取的详情到页面状态（同步、不再发请求）。返回该 run 实际评分口径供 resultScoreRef 冻结。
function applyRunDetail(id: string, r: Awaited<ReturnType<typeof fetchRunDetail>>, summary?: RunSummary) {
  const ca = (r.run as { created_at?: string }).created_at
  runTime.value = ca ? formatDateTimeSeconds(String(ca), '') : ''
  fromHistory.value = true
  const p = applyRunParams(r.run, summary ?? selectedRunSummary.value)
  resultScoreRef.value = p.score_profile_id || '' // 冻结该历史 run 实际评分口径（下钻榜单用）
  if (r.run.kind === 'signal' || r.run.kind === 'score_check') {
    kind.value = 'score_check'
    strat.value = null
    sig.value = r.layers as Layers
  } else {
    kind.value = 'strategy'
    // 同步表单到该次回测的参数（方案/持仓/本金/卖出规则随之显示）
    const bench = p.benchmark || '000905.SH'
    const initCapV = r.equity.length ? r.equity[0].equity : initCap.value
    strat.value = {
      run_id: r.run.run_ref || id, metrics: r.metrics as any, layers: r.layers as Layers,
      trades: r.trades as TradeRow[], equity: r.equity, benchmark_code: bench,
      initial_capital: initCapV,
    }
    sig.value = null
  }
}

async function loadRun(id: string, summary?: RunSummary) {
  if (!id) return
  historyRetryTarget.value = { kind: 'load', id, summary }
  const sequence = beginRunViewOperation('load')
  loading.value = true
  nextRunSourceRef.value = ''
  resultError.value = ''
  strat.value = null
  sig.value = null
  fromHistory.value = false
  runTime.value = ''
  try {
    const r = await fetchRunDetail(id)
    if (sequence !== runLoadSequence) return
    loadingRun.value = true
    applyRunDetail(id, r, summary)
    historyRetryTarget.value = null
    clearDirtySoon()  // 载入成功 → 按钮置灰（loadingRun 保持到 nextTick，避免参数 watcher 误置脏）
  } catch (e) {
    if (sequence !== runLoadSequence) return
    resultErrorContext.value = 'history'
    resultError.value = getErrorMessage(e, '历史回测载入失败')
    ElMessage.error(resultError.value)
    loadingRun.value = false
  } finally {
    finishRunViewOperation(sequence)
  }
}

// 删除当前选中的历史回测
async function removeCurrentRun() {
  if (!selectedRun.value) return
  const cur = selectedRunSummary.value
  if (cur?.readonly) {
    ElMessage.warning('公开回测记录为只读，不能删除')
    return
  }
  const desc = cur ? `${cur.kind === 'strategy' ? '策略' : '评分验证'} ${cur.date_start?.slice(0, 10)}~${cur.date_end?.slice(0, 10)}` : selectedRun.value
  try {
    await ElMessageBox.confirm(`确认删除这次回测记录？\n${desc}\n删除后保留当前参数，便于重新运行。`, '删除历史回测', {
      confirmButtonType: 'danger',
      type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消',
    })
  } catch { return /* 取消 */ }
  try {
    const deletedRef = selectedRun.value
    await deleteRun(deletedRef, pageErrorRequest)
    invalidateRunViewOperation()
    clearDisplayedRunResult()
    nextRunSourceRef.value = ''
    dirty.value = true
    runHistory.value = runHistory.value.filter((r) => runKey(r) !== deletedRef && r.id !== deletedRef)
    if (!(await loadHistory())) {
      ElMessage.warning('记录已删除，但列表刷新失败，请稍后重试')
      return
    }
    selectedRun.value = ''
    ElMessage.success('记录已删除，参数已保留，可重新运行或选择其他记录')
  } catch (e) {
    ElMessage.error(getErrorMessage(e, '删除失败'))
  }
}

async function publishRunVisibility(visibility: Visibility) {
  if (!selectedRun.value || selectedRunReadonly.value || runVisibilitySaving.value) return
  if (visibility === selectedRunSummary.value?.visibility) return
  if (visibility === 'tenant' && !canPublishTenant.value) {
    ElMessage.warning('无权公开到租户')
    return
  }
  if (visibility === 'public' && !canPublishPublic.value) {
    ElMessage.warning('无权公开到全体用户')
    return
  }
  runVisibilitySaving.value = true
  try {
    const updated = await setRunVisibility(selectedRun.value, visibility, pageErrorRequest)
    const idx = runHistory.value.findIndex((r) => r.id === updated.id || runKey(r) === selectedRun.value)
    if (idx >= 0) runHistory.value[idx] = { ...runHistory.value[idx], ...updated }
    ElMessage.success(visibility === 'private' ? '已设为私有' : '公开设置已更新')
    await loadHistory()
  } catch (e) {
    ElMessage.error(getErrorMessage(e, '公开设置失败'))
  } finally {
    runVisibilitySaving.value = false
  }
}

async function reuseCurrentRunParams() {
  const runRef = activeRunRef.value
  if (!runRef) return
  const sequence = beginRunViewOperation('load')
  loading.value = true
  try {
    const r = await getRun(runRef, pageErrorRequest)
    if (sequence !== runLoadSequence) return
    loadingRun.value = true
    applyRunParams(r.run, selectedRunSummary.value)
    nextRunSourceRef.value = r.run.run_ref || runRef
    if (r.run.kind === 'signal' || r.run.kind === 'score_check') {
      kind.value = 'score_check'
    } else {
      kind.value = 'strategy'
    }
    strat.value = null
    sig.value = null
    fromHistory.value = false
    runTime.value = ''
    nextTick(() => { dirty.value = true; loadingRun.value = false })
    ElMessage.success('已复用参数')
  } catch (e) {
    if (sequence !== runLoadSequence) return
    ElMessage.error(getErrorMessage(e, '复用参数失败'))
    loadingRun.value = false
  } finally {
    finishRunViewOperation(sequence)
  }
}

// —— 历史区「浏览公开回测」抽屉（R5/R6）——
// 「加载查看」载入该回测结果（不重跑）：公开摘要只放独立只读快照，不污染 mine-only 顶部候选，
// 也不把 opaque ref 写入 ElSelect；selectedRunSummary/activeRunRef 仍承接只读、复用参数和来源展示。
function onRunLoaded(item: AssetBrowseItem) {
  const key = assetItemKey(item)
  if (!key) return
  const summary = { ...(item as unknown as RunSummary), readonly: true }
  if (!externalRunSummary.value && !beforeExternalRun) beforeExternalRun = snapshotRunView()
  externalRunSummary.value = summary
  selectedRun.value = ''
  void loadRun(key, summary)
}

async function onMineRunSelected(id: string) {
  if (!id) return
  // 普通 mine→mine 切换沿用既有 loadRun；从公开查看态退出必须先成功取得详情，
  // 否则网络失败会提前销毁公开摘要和进入公开态前的可恢复快照。
  if (!externalRunSummary.value) {
    void loadRun(id)
    return
  }
  const sequence = beginRunViewOperation('load')
  historyRetryTarget.value = { kind: 'mine-switch', id }
  loading.value = true
  resultError.value = ''
  try {
    const detail = await fetchRunDetail(id)
    if (sequence !== runLoadSequence) return
    loadingRun.value = true
    commitMineRun()
    selectedRun.value = id
    applyRunDetail(id, detail)
    historyRetryTarget.value = null
    clearDirtySoon()
  } catch (error) {
    if (sequence !== runLoadSequence) return
    selectedRun.value = ''
    resultErrorContext.value = 'history'
    resultError.value = getErrorMessage(error, '历史回测载入失败')
    ElMessage.error(resultError.value)
    loadingRun.value = false
  } finally {
    finishRunViewOperation(sequence)
  }
}

// 统一状态转换（P1-1）：mine 新结果成为当前结果时，同时退出「公开查看态」——
// 清掉公开摘要与「进入公开查看前的快照」，避免之后误把新 mine 结果恢复成进入前的旧状态、
// 或再次加载公开记录时恢复到更早的陈旧快照。覆盖：页面运行、抽屉直接重跑、查重后加载 mine 三条路径。
function commitMineRun() {
  externalRunSummary.value = null
  beforeExternalRun = null
}

function clearExternalRun() {
  invalidateRunViewOperation()
  loadingRun.value = false
  externalRunSummary.value = null
  resultError.value = ''
  const snapshot = beforeExternalRun
  beforeExternalRun = null
  if (snapshot) restoreRunView(snapshot)
  else {
    strat.value = null
    sig.value = null
    fromHistory.value = false
    runTime.value = ''
    dirty.value = true
  }
}

// 解析历史 run.params JSON → RunParams（与 applyRunParams 同口径解析，但**不写回表单、不置脏**）。
// 按白名单完整复制回测参数（R6，P1-1）：含撮合参数（卖出 MA/止盈/止损/最大持有/调仓）、基准与
// 分层阈值——缺一即改变撮合与收益结果；剔除 source_run_ref，由 rerunPublicRun 另行附加新引用。
function buildBodyFromRun(run: RunSummary): RunParams {
  let p: Record<string, any> = {}
  try { p = JSON.parse((run as { params?: string }).params || '{}') } catch { /* ignore */ }
  const rawKind = (run.kind || p.kind || 'strategy') as string
  const k = rawKind === 'signal' ? 'score_check' : (rawKind as 'strategy' | 'score_check')
  const body: RunParams = { kind: k, date_start: '', date_end: '' }
  const copy = (field: string) => {
    const v = p[field]
    if (v !== undefined && v !== null) (body as unknown as Record<string, unknown>)[field] = v
  }
  RERUN_BASE_FIELDS.forEach(copy)
  body.date_start = ymd(body.date_start || run.date_start || '')
  body.date_end = ymd(body.date_end || run.date_end || '')
  if (!Array.isArray(body.horizons)) body.horizons = HORIZONS
  if (!Array.isArray(body.thresholds)) body.thresholds = THRESHOLDS
  if (k === 'strategy') RERUN_STRATEGY_FIELDS.forEach(copy)
  return body
}

// 「复用参数重跑」（决策2：不弹确认，立即同步重跑，组件行内 loading；不写回表单、不置脏、不影响当前选中）。
// 新 run 归当前 owner、private，审计含 source_run_ref；不复制他人结果快照（C7）。
async function rerunPublicRun(item: AssetBrowseItem): Promise<unknown> {
  const ref = assetItemKey(item)
  const detail = await getRun(ref)
  const body = buildBodyFromRun(detail.run)
  body.source_run_ref = detail.run.run_ref || ref
  return runBacktest(body)
}

// 重跑成功（P2-5 + 复审 P2-2）：新 run 归「我的」，只加载一次 mine 列表并按返回 run_id 精确选中。
async function onRunRerunDone(result: unknown) {
  ElMessage.success('已按该回测参数重跑，新记录归「我的」')
  const rid = (result as { run_id?: string } | null)?.run_id || null
  if (!(await loadHistory())) {
    ElMessage.warning('重跑已完成，但我的记录刷新失败，请稍后重试')
    return
  }
  if (!rid) {
    ElMessage.warning('重跑已完成，但接口未返回新记录标识，请手动选择记录')
    return
  }
  const target = runHistory.value.find((r) => r.id === rid || runKey(r) === rid)
  if (!target) {
    ElMessage.warning('重跑已完成，但新记录尚未出现在列表中，请稍后刷新')
    return
  }
  // P1-1（五次复审）：先成功获取新 mine 详情，再原子执行「应用详情 + 退出公开查看态 + 选中」。
  // 详情加载失败时不动 externalRunSummary/beforeExternalRun，用户仍可关闭公开查看恢复原现场。
  const key = runKey(target)
  const sequence = beginRunViewOperation('load')
  loading.value = true
  try {
    const detail = await fetchRunDetail(key)
    if (sequence !== runLoadSequence) return
    loadingRun.value = true
    commitMineRun() // 详情已取到 → 原子提交：清公开摘要+进入前快照，再应用新结果
    selectedRun.value = key
    applyRunDetail(key, detail, target)
    clearDirtySoon()
  } catch (e) {
    if (sequence !== runLoadSequence) return
    ElMessage.error(getErrorMessage(e, '重跑结果载入失败，请稍后从历史记录选择'))
    loadingRun.value = false
  } finally {
    finishRunViewOperation(sequence)
  }
}

// 导出当前回测的逐笔交易为 CSV（带 BOM，Excel 中文不乱码）
function exportTradesCsv() {
  if (!strat.value?.trades.length) return
  const headers = ['代码', '买入日', '买价(元)', '卖出日', '卖价(元)', '收益率(比例)', '盈亏(元)', '持有交易日', '卖出原因', '买入分档', '买入当日榜单排名']
  const rows = strat.value.trades.map((t) => {
    const tags = sellTags(t)
    const reason = tags.length ? tags.join('/') : t.exit_reason
    const buyGrade = t.grade || (t.entry_score != null ? `无评级(${t.entry_score})` : '')
    return [
      t.code, t.entry_date, t.entry_price, t.exit_date, t.exit_price,
      t.return_pct, t.pnl, t.hold_days, reason, buyGrade,
      t.entry_rank ?? '',
    ]
  })
  downloadCsv(`回测交易_${strat.value.run_id}.csv`, headers, rows)
}

onMounted(async () => {
  kind.value = settings.kind
  topN.value = Number(settings.topN)
  initCap.value = Number(settings.initCap)
  await loadHistory()
})

const HORIZONS = [10, 20]
const THRESHOLDS = [0.1, 0.2]

// —— 稳健性测试（即跑即看，不入历史）——
function effectiveProfileRefs() {
  return {
    screen: tempSelected.value.screen ? screenProfileKey(tempSelected.value.screen) : profileId.value,
    score: tempSelected.value.score ? scoreProfileKey(tempSelected.value.score) : scoreProfileId.value,
    trade: tempSelected.value.trade ? tradeProfileKey(tempSelected.value.trade) : tradeProfileId.value,
  }
}

function buildStrategyParams(): Record<string, unknown> {
  const refs = effectiveProfileRefs()
  const p: Record<string, unknown> = {
    date_start: dateStart.value, date_end: dateEnd.value,
    top_n: topN.value, initial_capital: initCap.value,
    profile_id: refs.screen || null,
  }
  if (refs.score) p.score_profile_id = refs.score
  if (refs.trade) p.trade_profile_id = refs.trade
  if (industryOn.value) p.industry_max_pct = industryPct.value / 100
  return p
}
const ROBUST_PARAM_OPTS = [
  { v: 'top_n', t: '持仓数 TopN' },
  { v: 'rebalance_days', t: '调仓周期(交易日)' }, { v: 'industry_max_pct', t: '行业上限 %' },
]
const robustMode = ref<'param_sweep' | 'in_out_sample'>('param_sweep')
const robustParam = ref('top_n')
const robustValuesText = ref('5, 10, 15, 20')
const robustSplit = ref('')
const robustLoading = ref(false)
const sweepRes = ref<ParamSweepResult | null>(null)
const inOutRes = ref<InOutSampleResult | null>(null)

function parseRobustValues(): number[] {
  const pct = robustParam.value === 'industry_max_pct'
  return robustValuesText.value.split(/[,，\s]+/).map((s) => Number(s)).filter((n) => !Number.isNaN(n))
    .map((n) => (pct ? n / 100 : n))
}
async function runRobustTest() {
  if (kind.value !== 'strategy') return
  if (!validateRunSelection()) return
  robustLoading.value = true
  sweepRes.value = null; inOutRes.value = null
  try {
    if (robustMode.value === 'in_out_sample') {
      if (!robustSplit.value) { ElMessage.warning('请选择样本切分日'); return }
      inOutRes.value = (await runRobust({ mode: 'in_out_sample', params: buildStrategyParams(), split_date: robustSplit.value }, pageErrorRequest)) as InOutSampleResult
    } else {
      const values = parseRobustValues()
      if (!values.length) { ElMessage.warning('请填写扫描取值'); return }
      sweepRes.value = (await runRobust({ mode: 'param_sweep', params: buildStrategyParams(), param: robustParam.value, values }, pageErrorRequest)) as ParamSweepResult
    }
  } catch (e) {
    ElMessage.error(getErrorMessage(e, '稳健性测试失败'))
  } finally {
    robustLoading.value = false
  }
}
const robustIsPct = computed(() =>
  ['industry_max_pct'].includes(robustParam.value))
function sweepValLabel(v: number): string {
  return robustIsPct.value ? formatPercent(v, { input: 'ratio' }) : formatNumber(v, 'parameter')
}

function buildBody(): RunParams {
  const body: RunParams = {
    kind: kind.value, date_start: dateStart.value, date_end: dateEnd.value,
    horizons: HORIZONS, thresholds: THRESHOLDS,
  }
  // 运行取 ref 优先级统一为:tempSelected 临时快照 > mine 选择器值 > 空(2026-08-01 三次复审拍板)。
  // 「加载查看」是用户最后一次明确操作,chip 即本次运行口径;不修改选择器值与持久偏好。
  // 清除 chip / 改选 mine / 复制为我的会清掉临时快照；历史载入另按历史 ref 重新投影。
  const refs = effectiveProfileRefs()
  if (refs.score) body.score_profile_id = refs.score
  if (nextRunSourceRef.value) body.source_run_ref = nextRunSourceRef.value
  if (kind.value === 'strategy') {
    Object.assign(body, {
      top_n: topN.value, initial_capital: initCap.value,
      profile_id: refs.screen || null,
      trade_profile_id: refs.trade || null,
    })
    if (industryOn.value) body.industry_max_pct = industryPct.value / 100
  }
  return body
}

function validateRunSelection(): boolean {
  const unavailable = (Object.entries(historyProfileUnavailable.value) as [ProfileKind, boolean][])
    .filter(([, value]) => value)
    .map(([key]) => ({ screen: '选股', score: '评分', trade: '买卖' })[key])
  if (unavailable.length) {
    ElMessage.warning(`历史${unavailable.join('/')}方案已不可用，请重新选择`)
    return false
  }
  const refs = effectiveProfileRefs()
  if (!refs.score) {
    ElMessage.warning('请选择评分方案')
    return false
  }
  if (kind.value === 'strategy' && !refs.trade) {
    ElMessage.warning('请选择买卖方案')
    return false
  }
  return true
}

async function run() {
  if (!dateStart.value || !dateEnd.value) return ElMessage.warning('请选择回测区间')
  if (!validateRunSelection()) return
  const body = buildBody()
  // P1-1（七次复审）：整个 run() 作为一次统一 operation token——发起 prepareBacktest 前即建立序列。
  // prepare 请求/查重确认框 pending 期间，用户关闭公开查看或切换历史会递增 runLoadSequence；
  // 之后每个写状态/发请求的节点都校验，旧操作晚到即弃，不得覆盖新页面状态（含不得用旧参数 doRun 落库）。
  const sequence = beginRunViewOperation('run')
  const frozen = buildBody()
  try {
    const pre = await prepareBacktest(body, pageErrorRequest)
    if (sequence !== runLoadSequence) return // prepare 晚到：页面已切换，丢弃本次操作
    if (pre.duplicate) {
      let choice: 'load' | 'rerun' | 'abort' = 'abort'
      try {
        await ElMessageBox.confirm(
          `已存在条件完全一致的历史记录（运行于 ${formatDateTimeSeconds(pre.duplicate.created_at)}）。\n可直接加载该结果，或重新回测覆盖它。`,
          '发现相同条件的历史回测',
          { confirmButtonType: 'info', cancelButtonType: 'warning', confirmButtonText: '加载历史', cancelButtonText: '重新回测', distinguishCancelAndClose: true, type: 'info' },
        )
        choice = 'load'
      } catch (act) {
        choice = act === 'cancel' ? 'rerun' : 'abort' // cancel=重新回测；关闭/Esc=放弃
      }
      if (sequence !== runLoadSequence) return // 确认框等待期间页面已切换，丢弃本次操作
      if (choice === 'abort') { finishRunViewOperation(sequence); return }
      if (choice === 'load') {
        // P1-1（五次复审）：先成功获取该 mine 历史详情，再原子执行「应用详情 + 退出公开查看态」。
        // P1-1（六次复审）：沿用 run() 的 operation token——详情请求 pending 期间页面切换会递增序列，
        // 晚到响应在成功/异常/finally 写状态前校验，过期即弃，不覆盖当前页面。
        const did = pre.duplicate.run_id
        loading.value = true
        try {
          const detail = await fetchRunDetail(did)
          if (sequence !== runLoadSequence) return
          loadingRun.value = true
          commitMineRun() // 详情已取到 → 原子提交：清公开摘要+进入前快照
          // P1-2（六次复审）：选中 key 用 opaque run_ref（与历史下拉 option value 一致），
          // 不写后端内部 id——否则 selectedRun 匹配不到 option，下拉显示 bt_.../内部 ID。
          const key = (detail.run as { run_ref?: string }).run_ref || did
          // 经 runHistory 归一化：优先用列表里同 run_ref 的 option value，确保与 option 完全一致
          const inHistory = runHistory.value.find((r) => runKey(r) === key || r.id === did)
          selectedRun.value = inHistory ? runKey(inHistory) : key
          applyRunDetail(selectedRun.value, detail)
          clearDirtySoon()
        } catch (e) {
          if (sequence !== runLoadSequence) return
          ElMessage.error(getErrorMessage(e, '历史回测载入失败'))
        } finally {
          if (sequence === runLoadSequence) {
            nextTick(() => { loadingRun.value = false })
          }
          finishRunViewOperation(sequence)
        }
        return
      }
      // rerun → 继续，runBacktest 落库时覆盖同签名旧记录
    }
  } catch {
    if (sequence !== runLoadSequence) return // 查重失败但页面已切换：不得因 catch 路径继续 doRun
    /* 查重失败不阻塞，直接回测 */
  }
  if (sequence !== runLoadSequence) return // 进入 doRun 前再校验：页面已切换则不得用旧参数落库
  await doRun(frozen, sequence) // 用冻结口径跑；doRun 末尾按 token 是否失效决定是否清脏
}

// P1-1（八次复审）：doRun 消费 operation token——runBacktest 结果先入局部变量，校验未过期才写响应式状态；
// 响应返回后/loadHistory 前后/异常/finally 写 loading 前分别检查。过期则丢弃页面写回（后台记录可能已落库，
// 静默保留在历史列表，下次主动刷新再出现），不得覆盖当前结果、选中项、公开快照，也不显示旧请求错误。
// P1-2（八次复审）：选中 key 用 opaque run_ref（与历史下拉 option 一致），不写后端内部 run_id——
// 列表刷新后按 id 找到新记录取 runKey；刷新失败或暂缺新项时保持未选中并提示，不把内部 ID 填进下拉。
async function doRun(body: RunParams, sequence?: number) {
  const stale = () => sequence !== undefined && sequence !== runLoadSequence
  // 参数已在 run() 保存并冻结；activeRunOperation 从 prepare 起持续持有，直到历史刷新结束或用户取消。
  loading.value = true
  runTime.value = ''
  fromHistory.value = false
  resultError.value = ''
  resultErrorContext.value = 'run'
  try {
    const res = (await runBacktest(body, pageErrorRequest)) as StrategyResult | Layers
    if (stale()) return // 回测请求 pending 期间页面已切换：丢弃本次写回（后台记录仍落库，留待刷新）
    // 先取内部 id 局部持有，loadHistory 后按 id 归一化为 run_ref 再选中
    const internalId = body.kind === 'strategy'
      ? (res as StrategyResult).run_id
      : (res as unknown as { run_id?: string }).run_id
    if (body.kind === 'strategy') {
      strat.value = res as StrategyResult
      sig.value = null
    } else {
      sig.value = res as Layers
      strat.value = null
    }
    const refreshed = await loadHistory(sequence) // 新结果进历史列表；过期列表响应也不得覆盖当前 kind
    if (stale()) return // loadHistory 期间页面又切换：不选中、不清公开快照
    commitMineRun() // mine 新结果成为当前结果 → 退出公开查看态（清公开摘要+进入前快照）
    // 选中用 run_ref（下拉 option value），不写内部 id
    const target = internalId ? runHistory.value.find((r) => r.id === internalId) : undefined
    if (target) {
      selectedRun.value = runKey(target)
    } else if (internalId) {
      // 列表里找不到新记录：保持未选中，不把内部 id 填进下拉；无论刷新失败还是新项暂缺都提示（P2-1 九次复审）
      selectedRun.value = ''
      if (!refreshed) ElMessage.warning('回测已完成，但我的记录刷新失败，请稍后从历史记录选择')
      else ElMessage.warning('回测已完成，但新记录尚未出现在列表中，请稍后刷新')
    }
    resultScoreRef.value = body.score_profile_id || '' // 冻结本次结果实际评分口径（下钻榜单用）
    nextRunSourceRef.value = ''
    // 出结果 → 按钮置灰；但若用户运行期间改过参数（token 已失效），保持 dirty=true，不误标「未修改」
    if (sequence === undefined || sequence === runLoadSequence) dirty.value = false
  } catch (e) {
    if (stale()) return // 旧请求失败：不在当前页面显示过期错误
    resultErrorContext.value = 'run'
    resultError.value = getErrorMessage(e, '回测失败')
    ElMessage.error(resultError.value)
  } finally {
    finishRunViewOperation(sequence)
  }
}

function retryResult() {
  if (resultErrorContext.value === 'history' && historyRetryTarget.value) {
    const target = historyRetryTarget.value
    if (target.kind === 'mine-switch') void onMineRunSelected(target.id)
    else void loadRun(target.id, target.summary)
    return
  }
  void run()
}

// —— 展示辅助 ——
const pct = formatReturn
const num = (v: number | null | undefined) => formatNumber(v, 'ratio')

const metricCards = computed(() => {
  const m = strat.value?.metrics
  if (!m) return []
  return [
    { label: '累计收益', val: pct(m.total_return), hint: tinyValueHint(m.total_return, '%', 2, 2), neutral: displayDirection(m.total_return, 2, 2) === 0, good: m.total_return >= 0 },
    { label: '超额(vs基准)', val: formatPercentPoints(m.excess_return, 'ratio'), hint: tinyValueHint(m.excess_return, ' 个百分点', 2, 2), neutral: displayDirection(m.excess_return, 2, 2) === 0, good: m.excess_return >= 0 },
    { label: '年化收益', val: pct(m.annual_return), neutral: displayDirection(m.annual_return, 2, 2) === 0, good: m.annual_return >= 0, hint: '短区间年化会被放大，仅长周期可信' },
    { label: '最大回撤', val: pct(m.max_drawdown), hint: tinyValueHint(m.max_drawdown, '%', 2, 2), neutral: displayDirection(m.max_drawdown, 2, 2) === 0, good: false },
    { label: '夏普', val: num(m.sharpe), neutral: !displayDirection(m.sharpe), good: m.sharpe >= 0 },
    { label: '卡玛', val: num(m.calmar), neutral: !displayDirection(m.calmar), good: m.calmar >= 0 },
    { label: '胜率', val: formatPercent(m.win_rate, { input: 'ratio' }), neutral: !displayDirection(m.win_rate, 2, 2), good: m.win_rate >= 0.5 },
    // 后端以 null 表示有盈利且无亏损的无限盈亏比；旧结果未提供字段才是缺失。
    { label: '盈亏比', val: m.profit_factor === null ? '∞' : num(m.profit_factor), neutral: m.profit_factor !== null && !displayDirection(m.profit_factor), good: (m.profit_factor ?? 99) >= 1 },
    { label: '交易数', val: formatNumber(m.n_trades, 'count'), good: true, neutral: true },
    { label: '平均持有(日)', val: formatNumber(m.avg_hold_days), good: true, neutral: true },
  ]
})

// 分层命中率表：行=各档+base rate，列=N×X
const layerKeys = computed(() => {
  const out: { key: string; label: string }[] = []
  for (const n of HORIZONS) for (const x of THRESHOLDS)
    out.push({ key: `N${n}_X${Math.round(x * 100)}`, label: `${n}日≥${formatPercent(x, { input: 'ratio' })}` })
  return out
})
const layersData = computed(() => strat.value?.layers ?? sig.value)
const layerRows = computed(() => {
  const L = layersData.value
  if (!L) return []
  const rows: { name: string; isBase: boolean; cells: Record<string, LayerCell> }[] = []
  for (const g of L.grades_order) {
    const e = L.by_grade[g] as Record<string, LayerCell | number>
    const cells: Record<string, LayerCell> = {}
    for (const lk of layerKeys.value) cells[lk.key] = e[lk.key] as LayerCell
    rows.push({ name: `${g} (n=${formatNumber(e.n_signals as number | undefined, 'count')})`, isBase: false, cells })
  }
  rows.push({ name: '全市场基线 (base rate)', isBase: true, cells: L.base_rate })
  return rows
})
const hasTradeRows = computed(() => Boolean(strat.value?.trades?.length))

// —— 交易明细 → 内嵌 K 线（买卖点标注 + 卖出后表现），不跳转个股详情 ——
interface DlgTrade extends TradeRow {
  fwd10: number | null
  fwd30: number | null
  fwd120: number | null
}
const chartDlg = ref(false)
const dlgCode = ref('')
const dlgName = ref<string | null>(null)
const dlgBars = ref<Bar[]>([])
const dlgIndicators = ref<IndicatorRow[]>([])
const dlgIndicatorLoading = ref(false)
const dlgIndicatorError = ref('')
const dlgMarkers = ref<TradeMarker[]>([])
const dlgTrades = ref<DlgTrade[]>([])
const dlgClicked = ref<TradeRow | null>(null)
const dlgLoading = ref(false)
const dlgZoom = ref<{ start: number; end: number }>({ start: 55, end: 100 })
const dlgMacdState = computed<MacdPanelState>(() => {
  if (dlgIndicatorLoading.value) return 'loading'
  if (dlgIndicatorError.value) return 'error'
  const hasCompleteMacd = dlgIndicators.value.some((row) => (
    typeof row.macd_diff === 'number'
    && typeof row.macd_dea === 'number'
    && typeof row.macd_hist === 'number'
  ))
  return hasCompleteMacd ? 'ready' : 'insufficient'
})

const ymd = (s: string) => (s || '').slice(0, 10) // 容错：去掉可能的 " 00:00:00"

async function loadDialogIndicators(): Promise<void> {
  if (!dlgCode.value) return
  dlgIndicatorLoading.value = true
  dlgIndicatorError.value = ''
  try {
    const data = await getIndicators(dlgCode.value, {
      lookback: 6000,
      fields: MACD_INDICATOR_FIELDS,
    })
    dlgIndicators.value = data.indicators
  } catch (error) {
    dlgIndicators.value = []
    dlgIndicatorError.value = getErrorMessage(error, 'MACD 指标载入失败')
  } finally {
    dlgIndicatorLoading.value = false
  }
}

// 点击交易的本笔摘要（左上角）：收益率 / 买入金额 / 卖出金额 / 股数
const dlgSummary = computed(() => {
  const t = dlgClicked.value
  if (!t) return null
  const buyAmt = t.return_pct !== 0 ? t.pnl / t.return_pct : t.entry_price * t.shares
  return {
    ret: t.return_pct, buyAmt, sellAmt: buyAmt + t.pnl, shares: t.shares, pnl: t.pnl,
    rank: t.entry_rank, pickRank: t.entry_pick_rank, pool: t.entry_pool, grade: t.grade,
    entry: t.entry_date, exit: t.exit_date, reason: exitText(t),
  }
})

// 查看买入当日榜单（按需计算该日全市场 Top N，高亮本笔买入的票）
const boardDlg = ref(false)
const boardDate = ref('')
const boardRows = ref<BoardRow[]>([])
const backtestBoardColumns = rankedStockColumns(['rank', 'code', 'name', 'board', 'score', 'grade'])
const boardLoading = ref(false)
const boardHighlight = ref<Set<string>>(new Set())
const boardMissing = ref(false)  // 高亮票不在 Top50（名次太靠后）
const boardRowClass = (o: { row: BoardRow }) => (boardHighlight.value.has(o.row.code) ? 'bd-hit' : '')
async function openDayBoard(buyDate: string, highlightCode: string) {
  // 排名是按"信号日(买入日的前一交易日)"的榜单决定的，故取前一交易日，与 entry_rank 一致
  const sigDate = prevTradeDate(ymd(buyDate))
  boardDate.value = sigDate
  boardHighlight.value = new Set([highlightCode])
  boardRows.value = []
  boardMissing.value = false
  boardLoading.value = true
  boardDlg.value = true
  try {
    boardRows.value = (await computeBoard(sigDate, 50, resultScoreRef.value || undefined, pageErrorRequest)).list
    boardMissing.value = !boardRows.value.some((r) => r.code === highlightCode)
    // 自动滚动高亮行到可视区
    nextTick(() => {
      const el = document.querySelector('.board-dlg .bd-hit') as HTMLElement | null
      el?.scrollIntoView({ block: 'center', behavior: 'smooth' })
    })
  } catch (e) {
    ElMessage.error(getErrorMessage(e, '榜单计算失败'))
  } finally {
    boardLoading.value = false
  }
}

function addCalDays(s: string, days: number): string {
  const d = new Date(ymd(s) + 'T00:00:00')
  d.setDate(d.getDate() + days)
  const m = `${d.getMonth() + 1}`.padStart(2, '0')
  const dd = `${d.getDate()}`.padStart(2, '0')
  return `${d.getFullYear()}-${m}-${dd}`
}

async function openTradeChart(row: TradeRow) {
  if (!strat.value) return
  const code = row.code
  const ts = strat.value.trades.filter((t) => t.code === code)
    .sort((a, b) => a.entry_date.localeCompare(b.entry_date))
  dlgCode.value = code
  dlgClicked.value = row
  dlgTrades.value = ts.map((t) => ({ ...t, fwd10: null, fwd30: null, fwd120: null }))
  dlgLoading.value = true
  chartDlg.value = true
  dlgBars.value = []
  dlgIndicators.value = []
  dlgIndicatorError.value = ''
  dlgMarkers.value = []
  const indicatorRequest = loadDialogIndicators()
  try {
    const firstEntry = ymd(ts[0].entry_date)
    const lastExit = ymd(ts[ts.length - 1].exit_date)
    // 同花顺式：加载该股全部历史（含卖出后），默认缩放到交易区间，可自由缩放看全部
    const data = await getBars(code, { adjust: 'qfq', lookback: 6000 }, undefined, pageErrorRequest)
    dlgName.value = data.name
    dlgBars.value = data.bars
    // 买卖点标记
    const marks: TradeMarker[] = []
    for (const t of ts) {
      marks.push({ date: ymd(t.entry_date), kind: 'buy', label: `买${t.grade ? '·' + t.grade : ''}` })
      const ret = formatReturn(t.return_pct)
      marks.push({ date: ymd(t.exit_date), kind: 'sell', label: `卖·${exitText(t)}\n${ret}` })
    }
    dlgMarkers.value = marks
    // 默认缩放：定位到交易区间（首买前 ~30 日 ~ 末卖后 ~30 日），让买卖点一进来就可见
    const idxByDate = new Map(data.bars.map((b, i) => [b.date, i]))
    const n = data.bars.length
    const iEntry = idxByDate.get(firstEntry) ?? 0
    const iExit = idxByDate.get(lastExit) ?? n - 1
    const pad = 30
    dlgZoom.value = {
      start: Math.max(0, ((iEntry - pad) / Math.max(n - 1, 1)) * 100),
      end: Math.min(100, ((iExit + pad) / Math.max(n - 1, 1)) * 100),
    }
    // 卖出后 10/30/120(半年) 交易日涨跌幅（从已加载 K 线按交易日偏移计算）
    const fwd = (exit: string, off: number): number | null => {
      const i = idxByDate.get(ymd(exit))
      if (i == null) return null
      const base = data.bars[i].close
      const j = data.bars[i + off]
      return j && base ? j.close / base - 1 : null
    }
    dlgTrades.value = ts.map((t) => ({
      ...t, fwd10: fwd(t.exit_date, 10), fwd30: fwd(t.exit_date, 30), fwd120: fwd(t.exit_date, 120),
    }))
  } catch (e) {
    ElMessage.error(getErrorMessage(e, 'K线载入失败'))
  } finally {
    await indicatorRequest
    dlgLoading.value = false
  }
}
const menuPageTitle = useMenuPageTitle()
</script>

<template>
  <LayoutHost :layout="backtestEffective">
    <template #action>
    <div class="page-head">
      <div>
        <h2 class="app-page-title page-title-row">
          {{ menuPageTitle }}
          <HelpTip title="回测在验证什么？" :width="460">
            <HelpTipItem question="策略回测验证什么">
              <ul>
                <li>逐日按“先卖后买”事件驱动撮合：T 日选股、T+1 开盘成交，跌破 MA 卖出；计入交易成本、涨跌停或停牌不可成交、退市强平，并计算真实资金曲线。</li>
              </ul>
            </HelpTipItem>
            <HelpTipItem question="信号质量验证什么">
              <ul>
                <li>统计分数越高时，N 日内触及 X% 涨幅的概率是否越高，并减去全市场基线得到超额，用于判断评分的真实能力。</li>
              </ul>
            </HelpTipItem>
            <HelpTipItem warning>
              <ul>
                <li>未来 N 日只用于评估，不是未来函数。</li>
                <li>短区间的年化和卡玛会被放大，应观察长周期。</li>
                <li>样本量小的分档不可信。</li>
              </ul>
            </HelpTipItem>
          </HelpTip>
        </h2>
        <p class="page-subtitle">用策略/评分方案做 T+1 开盘撮合回测，查看收益、交易与当日榜单。</p>
      </div>
      <AppControlRow class="page-head-actions">
        <div class="hist">
          <span class="lbl">回测记录</span>
          <AppStatusNotice
            v-if="historyError"
            tone="warning"
            size="inline"
            title="历史回测加载失败"
            :description="historyError"
            action-text="重新加载"
            @action="loadHistory"
          />
          <template v-else>
          <AppSelect
            v-model="selectedRun"
            class="history-run-select"
            @change="onMineRunSelected(selectedRun)"

            :placeholder="historyPlaceholder"
            popper-class="app-option-popper backtest-run-select-popper"
            width="wide"
          >
            <el-option v-for="o in runOptions" :key="o.id" :value="o.id" :label="o.label">
              <span class="app-inline-info app-inline-info--fill app-inline-info--nowrap app-inline-info--md">
                <span class="app-option-label" :style="{ color: o.color }">{{ o.label }}</span>
                <AssetVisibilityTag
                  v-if="o.displaySource"
                  mode="source"
                  :source="o.displaySource"
                  :owner-label="o.ownerLabel"
                />
                <span class="app-option-meta">{{ o.range }} <b :style="{ color: o.color }">{{ o.retTxt }}</b></span>
              </span>
            </el-option>
          </AppSelect>
          <HelpHint text="历史记录显示最近 100 条我的回测，可通过公开回测入口浏览共享记录。" />
          <span
            v-if="externalRunOption"
            class="temp-readonly-chip app-surface app-surface--inset app-surface--dashed app-surface--section"
            data-testid="backtest-external-run"
          >
            <span class="temp-readonly-chip-prefix">正在查看：</span>
            <span>{{ externalRunOption.label }}</span>
            <AssetVisibilityTag
              v-if="externalRunOption.displaySource"
              mode="source"
              :source="externalRunOption.displaySource"
              :owner-label="externalRunOption.ownerLabel"
            />
            <AppCloseButton label="关闭公开回测查看" size="compact" @click="clearExternalRun" />
          </span>
          <AssetVisibilityActions
            :show-visibility="!!selectedRunSummary"
            :visibility="selectedRunSummary?.visibility || 'private'"
            :readonly="selectedRunReadonly"
            :can-publish-tenant="canPublishTenant"
            :can-publish-public="canPublishPublic"
            :saving="runVisibilitySaving"
            :reuse-visible="selectedRunReadonly"
            reuse-permission="backtest:run"
            :reuse-disabled="!activeRunRef"
            @publish="publishRunVisibility"
            @reuse="reuseCurrentRunParams"
          />
          <el-button v-permission="'backtest:delete'" v-if="!selectedRunReadonly" type="danger" plain :disabled="!selectedRun" @click="removeCurrentRun">删除</el-button>
          <!-- 浏览公开回测（R5/R6）：表格化浏览 tenant/public 回测 + 加载查看 + 复用参数重跑 -->
          <AppActionHint v-if="canViewBacktest" text="浏览租户/全体公开的历史回测，可加载查看或复用参数重跑" label="浏览公开回测">
            <el-button
              :icon="Search"
              data-testid="backtest-browse-open"
              @click="runBrowseOpen = true"
            >浏览公开回测</el-button>
          </AppActionHint>
          </template>
        </div>
        <PageSettingsTrigger :dirty="isDirty" @click="settingsOpen = true" />
      </AppControlRow>
    </div>
    </template>

    <template #main>
    <div class="backtest-body">
    <div class="backtest-mode-rail">
      <PageSegmented
        v-model="kind"
        :options="BACKTEST_KIND_OPTIONS"
        tone="primary"
        test-id="backtest-kind-tabs"
        aria-label="回测验证模式"
      />
    </div>
    <el-card
      shadow="never"
      class="form-card app-card-compact"
    >
      <AppForm label-position="top" class="backtest-params" :class="{ 'is-score-check': kind === 'score_check' }">
        <div class="form-row parameter-grid">
          <el-form-item class="date-field" label="回测区间">
            <div class="date-range">
              <TradeDatePicker v-model="dateStart" aria-label="回测开始日期" placeholder="开始日期" />
              <span class="date-range-separator">—</span>
              <TradeDatePicker v-model="dateEnd" aria-label="回测结束日期" placeholder="结束日期" />
            </div>
          </el-form-item>
          <template v-if="kind === 'strategy'">
            <el-form-item class="holding-field">
              <template #label>
                持仓数量
                <HelpTip title="持仓数" :width="300">
                  <HelpTipItem question="持仓数如何生效">
                    <ul>
                      <li>每个调仓日在候选中按综合分取前 N 只等权买入，并限制同时最多持有的股票数量。</li>
                    </ul>
                  </HelpTipItem>
                </HelpTip>
              </template>
              <el-input-number v-model="topN" aria-label="持仓数量" :min="1" :max="50" controls-position="right" />
            </el-form-item>
            <el-form-item class="capital-field" label="初始本金（元）">
              <el-input-number
                v-model="initCap"
                aria-label="初始本金（元）"
                :min="100000"
                :step="100000"
                :formatter="formatMoneyInput"
                :parser="parseMoneyInput"
                controls-position="right"
              />
            </el-form-item>
            <el-form-item class="industry-field" label="行业上限">
              <div class="industry-controls">
                <el-checkbox v-model="industryOn" aria-label="启用行业上限">启用</el-checkbox>
                <el-input-number v-model="industryPct" aria-label="行业上限百分比" :disabled="!industryOn" :min="1" :max="100" controls-position="right" />
                <span class="unit" :class="{ off: !industryOn }">%</span>
              </div>
            </el-form-item>
          </template>
        </div>
        <AppControlRow class="scheme-grid" align="start">
          <el-form-item class="scheme-field">
            <template #label>
              评分方案 <span class="required-mark" aria-hidden="true">*</span>
              <HelpTip title="评分方案" :width="340">
                <HelpTipItem question="方案用于什么">
                  <ul>
                    <li>策略回测中用于在候选超过持仓数时按分排序截断；评分验证中用于分档检验高分组是否更易上涨。</li>
                  </ul>
                </HelpTipItem>
                <HelpTipItem question="在哪里定义">
                  <ul>
                    <li>前往「配置管理 → 评分规则」定义。</li>
                  </ul>
                </HelpTipItem>
              </HelpTip>
            </template>
            <AssetProfileSelect
              ref="scoreProfileSelectRef"
              v-model="guardedScoreProfileId"
              asset-label="评分方案"
              :fetch-mine="fetchMineScoreProfiles"
              :browse="browseScore"
              :copy-item="copyAnyScoreProfile"
              loaded-mode="external"
              copy-permission="score-profile:save"
              view-permission="score-profile:view"
              placeholder="请选择评分方案"
              search-button="icon"
              test-id="backtest-score-select"
              @ready="onScoreReady"
              @loaded="onScoreLoaded"
              @temp-removed="onLoadedRemoved('score', $event)"
              @copied-item="onScoreCopied"
              @update:model-value="onScoreSelect"
            />
            <!-- 加载查看的临时只读项：选择器外展示（方案b，不破组件递归契约），显示名称非 opaque ref；本次运行口径（快照优先于 mine 选择器值） -->
            <span
              v-if="tempSelected.score || historyProfileUnavailable.score"
              class="temp-readonly-chip app-surface app-surface--inset app-surface--dashed app-surface--section"
              :data-testid="`${'backtest-score-select'}-temp`"
            >
              <template v-if="tempSelected.score">
                <span class="temp-readonly-chip-prefix">本次运行：</span>
                <AssetProfileLabel
                  :name="tempSelected.score.name"
                  :version="tempSelected.score.version || null"
                  :source="tempSelected.score.is_preset ? 'preset' : tempSelected.score.source"
                  :is-preset="tempSelected.score.is_preset"
                  :owner-label="tempSelected.score.owner_label"
                  readonly
                />
              </template>
              <span v-else class="temp-readonly-chip-prefix">历史评分方案已不可用，请重新选择</span>
              <AppCloseButton label="清除临时只读方案" size="compact" @click="clearTemp('score')" />
            </span>
          </el-form-item>
          <template v-if="kind === 'strategy'">
            <el-form-item class="scheme-field">
              <template #label>
                选股方案
                <HelpTip title="选股方案 = 自定义策略入口" :width="360">
                  <HelpTipItem question="方案如何限制范围">
                    <ul>
                      <li>选择方案后，只在命中该方案的股票中按评分取前 N 只；不选择时不额外限制范围，但仍排除 ST，并继续执行评分和买入条件。</li>
                    </ul>
                  </HelpTipItem>
                  <HelpTipItem question="如何自定义方案">
                    <ul>
                      <li>前往「策略筛选」页编写规则并保存，之后即可在此选择。</li>
                    </ul>
                  </HelpTipItem>
                </HelpTip>
                <HelpHint v-if="profileDesc" :text="`方案说明：${profileDesc}`" />
              </template>
              <AssetProfileSelect
                ref="screenProfileSelectRef"
                v-model="guardedScreenProfileId"
                asset-label="选股方案"
                :fetch-mine="fetchMineScreenProfiles"
                :browse="browseScreen"
                :copy-item="copyAnyScreenProfile"
                loaded-mode="external"
                copy-permission="screen-profile:save"
                view-permission="screen-profile:view"
                placeholder="不使用选股方案"
                search-button="icon"
                test-id="backtest-screen-select"
                @ready="onScreenReady"
                @loaded="onScreenLoaded"
                @temp-removed="onLoadedRemoved('screen', $event)"
                @copied-item="onScreenCopied"
                @update:model-value="onScreenSelect"
              />
              <!-- 加载查看的临时只读项：选择器外展示（方案b）；本次运行口径（快照优先于 mine 选择器值） -->
              <span
                v-if="tempSelected.screen || historyProfileUnavailable.screen"
                class="temp-readonly-chip app-surface app-surface--inset app-surface--dashed app-surface--section"
                data-testid="backtest-screen-select-temp"
              >
                <template v-if="tempSelected.screen">
                  <span class="temp-readonly-chip-prefix">本次运行：</span>
                  <AssetProfileLabel
                    :name="tempSelected.screen.name"
                    :version="tempSelected.screen.version || null"
                    :source="tempSelected.screen.is_preset ? 'preset' : tempSelected.screen.source"
                    :is-preset="tempSelected.screen.is_preset"
                    :owner-label="tempSelected.screen.owner_label"
                    readonly
                  />
                </template>
                <span v-else class="temp-readonly-chip-prefix">历史选股方案已不可用，请重新选择或清除</span>
                <AppCloseButton label="清除临时只读方案" size="compact" @click="clearTemp('screen')" />
              </span>
            </el-form-item>
            <el-form-item class="scheme-field">
              <template #label>
                买卖方案 <span class="required-mark" aria-hidden="true">*</span>
                <HelpTip title="买卖方案 = 买/卖/兜底" :width="380">
                  <HelpTipItem question="方案如何决定买卖">
                    <ul>
                      <li>买入必须同时满足筛选命中和买入条件；卖出执行方案的卖出条件以及止盈、止损、最大持有等兜底。</li>
                    </ul>
                  </HelpTipItem>
                  <HelpTipItem question="在哪里定义">
                    <ul>
                      <li>前往「配置管理 → 买卖指标」定义。</li>
                    </ul>
                  </HelpTipItem>
                </HelpTip>
              </template>
              <AssetProfileSelect
                ref="tradeProfileSelectRef"
                v-model="guardedTradeProfileId"
                asset-label="买卖方案"
                :fetch-mine="fetchMineTradeProfiles"
                :browse="browseTrade"
                :copy-item="copyAnyTradeProfile"
                loaded-mode="external"
                copy-permission="trade-profile:save"
                view-permission="trade-profile:view"
                placeholder="请选择买卖方案"
                search-button="icon"
                test-id="backtest-trade-select"
                @ready="onTradeReady"
                @loaded="onTradeLoaded"
                @temp-removed="onLoadedRemoved('trade', $event)"
                @copied-item="onTradeCopied"
                @update:model-value="onTradeSelect"
              />
              <!-- 加载查看的临时只读项：选择器外展示（方案b）；本次运行口径（快照优先于 mine 选择器值） -->
              <span
                v-if="tempSelected.trade || historyProfileUnavailable.trade"
                class="temp-readonly-chip app-surface app-surface--inset app-surface--dashed app-surface--section"
                data-testid="backtest-trade-select-temp"
              >
                <template v-if="tempSelected.trade">
                  <span class="temp-readonly-chip-prefix">本次运行：</span>
                  <AssetProfileLabel
                    :name="tempSelected.trade.name"
                    :version="tempSelected.trade.version || null"
                    :source="tempSelected.trade.is_preset ? 'preset' : tempSelected.trade.source"
                    :is-preset="tempSelected.trade.is_preset"
                    :owner-label="tempSelected.trade.owner_label"
                    readonly
                  />
                </template>
                <span v-else class="temp-readonly-chip-prefix">历史买卖方案已不可用，请重新选择</span>
                <AppCloseButton label="清除临时只读方案" size="compact" @click="clearTemp('trade')" />
              </span>
            </el-form-item>
          </template>
        </AppControlRow>
        <div class="parameter-footer">
          <div class="parameter-status">
            <span v-if="dataMin">可用数据：{{ dataMin }} ～ {{ dataMax }}</span>
            <HelpHint :text="kind === 'strategy'
              ? '本地同步执行，区间数月约 10 秒级。'
              : '信号质量分析覆盖全市场，耗时稍长。'" />
          </div>
          <AppControlRow class="run-row">
            <el-button
              data-testid="backtest-reset-params"
              :disabled="!hasResettableRunParams"
              @click="resetRunParams"
            >重置参数</el-button>
            <el-button v-permission="'backtest:run'" :type="dirty ? 'primary' : 'info'" :loading="loading || runningRun"
                       :disabled="!dirty" @click="run">
              {{ dirty ? '运行回测' : '已是最新结果' }}
            </el-button>
          </AppControlRow>
        </div>
      </AppForm>
    </el-card>

    <AppScrollArea :as="AppAsyncRegion"
      class="results"
      :loading="loading"
      :has-content="Boolean(strat || sig)"
      :error="resultError"
      loading-title="正在加载回测结果…"
      :error-title="resultErrorContext === 'history' ? '历史回测载入失败' : ((strat || sig) ? '回测结果刷新失败' : '回测运行失败')"
      empty-title="设置参数后点「运行回测」"
      retry
      @retry="retryResult"
    >
      <div class="results-top">
      <!-- 加载历史时：显示这次回测的运行时间 -->
      <AppStatusNotice
        v-if="fromHistory && runTime && (strat || sig)"
        class="run-time-notice"
        title="已载入历史记录"
        :description="`回测于 ${runTime} 运行`"
      />
      <!-- 策略：绩效卡 + 资金曲线 -->
      <template v-if="strat">
        <el-card shadow="never" class="block">
          <div class="metrics">
            <div v-for="c in metricCards" :key="c.label" class="metric"
                 :class="{ good: c.good && !c.neutral, bad: !c.good && !c.neutral }">
              <div class="m-label">{{ c.label }}<HelpHint v-if="c.hint" :text="c.hint" /></div>
              <div class="m-val">{{ c.val }}</div>
            </div>
          </div>
        </el-card>
        <el-card shadow="never" class="block">
          <div class="block-title">资金曲线（组合 vs 基准 + 回撤）
            <span class="bench-choice">
              <span class="bench-choice-label">对比指数</span>
              <MarketBenchmarkSelect
                v-model="benchChoice"
                test-id="backtest-benchmark"
              />
            </span>
          </div>
          <EquityChart :points="strat.equity" :benchmark-code="strat.benchmark_code || '000905.SH'"
            :extra-benchmark="benchmarkEquity" :show-benchmark="benchChoice !== ''" />
        </el-card>

        <!-- 稳健性测试（即跑即看，不入历史）：用当前表单参数为基准 -->
        <el-card shadow="never" class="block">
          <el-collapse v-model="robustPanels">
            <el-collapse-item name="robust">
              <template #title>
                <span class="block-title" style="margin:0">稳健性测试
                  <HelpTip title="结果是否稳健 / 过拟合？" :width="380">
                    <HelpTipItem question="参数敏感性怎么看">
                      <ul>
                        <li>固定其他参数，扫描一个参数的多个取值，观察绩效是否平滑，而不是只依赖某个特殊取值。</li>
                      </ul>
                    </HelpTipItem>
                    <HelpTipItem question="样本内外怎么看">
                      <ul>
                        <li>按某日把区间分为两部分分别回测，样本外仍成立才更可信；基准参数取上方表单当前设置。</li>
                      </ul>
                    </HelpTipItem>
                  </HelpTip>
                </span>
              </template>
              <AppControlRow class="form-row robust-row">
                <el-radio-group v-model="robustMode">
                  <el-radio-button value="param_sweep">参数敏感性</el-radio-button>
                  <el-radio-button value="in_out_sample">样本内外</el-radio-button>
                </el-radio-group>
                <template v-if="robustMode === 'param_sweep'">
                  <AppControlItem label="扫描参数">
                    <AppSelect
                      v-model="robustParam"

                      width="medium"
                    >
                      <el-option v-for="o in ROBUST_PARAM_OPTS" :key="o.v" :value="o.v" :label="o.t" />
                    </AppSelect>
                  </AppControlItem>
                  <AppControlItem label="取值">
                    <el-input v-model="robustValuesText" class="app-control-width-long" placeholder="逗号分隔，如 5,10,15,20" />
                  </AppControlItem>
                </template>
                <template v-else>
                  <AppControlItem label="样本切分日">
                    <TradeDatePicker v-model="robustSplit" placeholder="区间内某交易日" class="app-control-width-long" />
                  </AppControlItem>
                </template>
                <el-button v-permission="'backtest:robust'" type="primary" plain :loading="robustLoading" @click="runRobustTest">运行</el-button>
                <span class="tip-inline">逐组完整回测，较慢</span>
              </AppControlRow>

              <!-- 参数敏感性结果 -->
              <AppDataTable v-if="sweepRes" :data="sweepRes.rows" size="small" border embedded>
                <AppTableColumn :label="ROBUST_PARAM_OPTS.find(o => o.v === sweepRes!.param)?.t || sweepRes.param" role="number">
                  <template #default="{ row }"><b>{{ sweepValLabel(row.value) }}</b></template>
                </AppTableColumn>
                <AppTableColumn label="累计收益" role="number">
                  <template #default="{ row }"><span :class="marketValueClass(row.total_return, { input: 'ratio' })">{{ pct(row.total_return) }}</span></template>
                </AppTableColumn>
                <AppTableColumn label="超额" role="number">
                  <template #default="{ row }"><span :class="marketValueClass(row.excess_return, { input: 'ratio' })">{{ formatPercentPoints(row.excess_return, 'ratio') }}</span></template>
                </AppTableColumn>
                <AppTableColumn label="最大回撤" role="number">
                  <template #default="{ row }">{{ pct(row.max_drawdown) }}</template>
                </AppTableColumn>
                <AppTableColumn label="夏普" role="number">
                  <template #default="{ row }">{{ num(row.sharpe) }}</template>
                </AppTableColumn>
                <AppTableColumn label="胜率" role="number">
                  <template #default="{ row }">{{ formatPercent(row.win_rate, { input: 'ratio' }) }}</template>
                </AppTableColumn>
                <AppTableColumn label="交易数" role="number">
                  <template #default="{ row }">{{ formatNumber(row.n_trades, 'count') }}</template>
                </AppTableColumn>
              </AppDataTable>

              <!-- 样本内外结果 -->
              <AppDataTable v-if="inOutRes" :data="[
                { seg: '样本内', ...inOutRes.in_sample },
                { seg: '样本外', ...inOutRes.out_sample },
              ]" size="small" border embedded>
                <AppTableColumn label="样本" role="description">
                  <template #default="{ row }"><b>{{ row.seg }}</b><span class="opt-range">{{ row.range[0] }}~{{ row.range[1] }}</span></template>
                </AppTableColumn>
                <AppTableColumn label="累计收益" role="number">
                  <template #default="{ row }"><span :class="marketValueClass(row.total_return, { input: 'ratio' })">{{ pct(row.total_return) }}</span></template>
                </AppTableColumn>
                <AppTableColumn label="超额" role="number">
                  <template #default="{ row }"><span :class="marketValueClass(row.excess_return, { input: 'ratio' })">{{ formatPercentPoints(row.excess_return, 'ratio') }}</span></template>
                </AppTableColumn>
                <AppTableColumn label="最大回撤" role="number">
                  <template #default="{ row }">{{ pct(row.max_drawdown) }}</template>
                </AppTableColumn>
                <AppTableColumn label="夏普" role="number">
                  <template #default="{ row }">{{ num(row.sharpe) }}</template>
                </AppTableColumn>
                <AppTableColumn label="胜率" role="number">
                  <template #default="{ row }">{{ formatPercent(row.win_rate, { input: 'ratio' }) }}</template>
                </AppTableColumn>
              </AppDataTable>
            </el-collapse-item>
          </el-collapse>
        </el-card>
      </template>

      <!-- 分层命中率（策略与信号共用）—— 核心概率口径 -->
      <el-card v-if="layersData" shadow="never" class="block">
        <div class="block-title">
          分层命中率 vs 全市场基线（超额）
          <span class="sub">区间 {{ layersData.date_start }} ~ {{ layersData.date_end }}，总信号 {{ formatNumber(layersData.total_signals, 'count') }}</span>
        </div>
        <AppDataTable :data="layerRows" size="small" embedded>
          <AppTableColumn label="分档">
            <template #default="{ row }">
              <b :class="{ base: row.isBase }">{{ row.name }}</b>
            </template>
          </AppTableColumn>
          <AppTableColumn v-for="lk in layerKeys" :key="lk.key" :label="lk.label" role="comparison-number">
            <template #default="{ row }">
              <template v-if="row.cells[lk.key] && row.cells[lk.key].hit_rate != null">
                <span class="hit">{{ formatPercent(row.cells[lk.key].hit_rate, { input: 'ratio' }) }}</span>
                <span v-if="!row.isBase && row.cells[lk.key].excess != null"
                      class="excess" :class="marketValueClass(row.cells[lk.key].excess, { input: 'ratio' })">
                  {{ formatPercentPoints(row.cells[lk.key].excess, 'ratio') }}
                </span>
                <AppHoverInfo v-if="!row.isBase && row.cells[lk.key].reliable === false" content="样本量过小，不采信">
                  <span tabindex="0" class="unreliable">·样本少</span>
                </AppHoverInfo>
              </template>
              <span v-else class="muted">—</span>
            </template>
          </AppTableColumn>
        </AppDataTable>
        <div class="legend-line">
          每格上为命中率，下为<b>超额</b>（命中率−基线）。超额为正说明该档比"随便买"更可能摸到目标涨幅。
        </div>
      </el-card>
      </div>

      <!-- 逐笔交易（策略）-->
      <el-card v-if="hasTradeRows" shadow="never" class="block trade-block app-card-body-fill">
        <AppControlRow class="block-title">
          逐笔交易（{{ formatNumber(strat!.trades.length, 'count') }} 笔）
          <span class="sub">点任一行 → 在 K 线上看该股的买卖点与原因（不跳转）</span>
          <el-button class="export-btn" @click="exportTradesCsv">导出 CSV</el-button>
        </AppControlRow>
        <div class="trade-table-wrap">
        <AppDataTable :data="tradeRows" size="small" clickable
                  :border="tableBorder('trades')"
                  :default-sort="tradeDefaultSort" @sort-change="onTradeSortChange"
                  @row-click="(r:any) => openTradeChart(r)">
          <AppTableColumn label="代码" prop="code">
            <template #default="{ row }">
              <span class="app-inline-info app-inline-info--nowrap">
                <el-button data-button-kind="navigation" link type="primary" class="app-table-field-link" :aria-label="`查看 ${row.code} 交易回放`" @click.stop="openTradeChart(row)">{{ row.code }}</el-button>
                <StockStatusTag
                  :is-st="row.entry_is_st"
                  :as-of-date="row.st_as_of_date || row.entry_date"
                  context-label="买入日"
                />
              </span>
            </template>
          </AppTableColumn>
          <AppTableColumn label="买入" prop="entry_date" sortable :sort-by="(r:any)=>r.entry_date" />
          <AppTableColumn label="买价" header-meta="元"><template #default="{ row }">{{ formatMoney(row.entry_price) }}</template></AppTableColumn>
          <AppTableColumn label="卖出" prop="exit_date" sortable :sort-by="(r:any)=>r.exit_date" />
          <AppTableColumn label="卖价" header-meta="元"><template #default="{ row }">{{ formatMoney(row.exit_price) }}</template></AppTableColumn>
          <AppTableColumn v-if="tradeColVisible('ret')" label="收益" prop="return_pct" sortable :sort-by="(r:any)=>r.return_pct">
            <template #default="{ row }">
              <span :class="marketValueClass(row.return_pct, { input: 'ratio' })">{{ pct(row.return_pct) }}</span>
            </template>
          </AppTableColumn>
          <AppTableColumn v-if="tradeColVisible('hold')" label="持有" header-meta="日" prop="hold_days" sortable :sort-by="(r:any)=>r.hold_days"><template #default="{ row }">{{ formatNumber(row.hold_days, 'count') }}</template></AppTableColumn>
          <AppTableColumn v-if="tradeColVisible('reason')" label="卖出原因">
            <template #default="{ row }">
              <template v-if="sellTags(row).length">
                <el-tag v-for="t in sellTags(row)" :key="t" type="warning" size="small" effect="light" class="sell-tag">{{ t }}</el-tag>
              </template>
              <span v-else>{{ row.exit_reason }}</span>
            </template>
          </AppTableColumn>
          <AppTableColumn v-if="tradeColVisible('grade')" label="买入档">
            <template #default="{ row }">
              <ScoreGradeTag v-if="row.grade" :grade="row.grade" />
              <AppHoverInfo v-else-if="row.entry_score != null" content="综合分未达「观察」档阈值，但因候选池内排名靠前而买入">
                <span tabindex="0" class="muted">无评级·{{ formatNumber(row.entry_score, 'score') }}分</span>
              </AppHoverInfo>
              <span v-else class="muted">—</span>
            </template>
          </AppTableColumn>
          <AppTableColumn v-if="tradeColVisible('rank')" label="榜单排名">
            <template #default="{ row }">{{ row.entry_rank ? '#' + row.entry_rank : '—' }}</template>
          </AppTableColumn>
        </AppDataTable>
        </div>
      </el-card>

    </AppScrollArea>
    </div>
    </template>

    <template #overlays>
    <!-- 交易明细 → 内嵌 K 线（买卖点标注，蓝▲买/橙▼卖），不跳转 -->
    <AppDialog v-model="chartDlg" :title="`${dlgName || ''} ${dlgCode}　交易回放`" size="workspace" top="5cqh">
      <div v-loading="dlgLoading">
        <!-- 左上角：本笔交易摘要（收益率/买入金额/卖出金额/股数）-->
        <div v-if="dlgSummary" class="dlg-summary">
          <div class="ds-item"><span class="ds-k">本笔收益</span>
            <span class="ds-v" :class="marketValueClass(dlgSummary.ret, { input: 'ratio' })">{{ pct(dlgSummary.ret) }}</span></div>
          <div class="ds-item"><span class="ds-k">买入金额</span><span class="ds-v">{{ formatCompactMoneyYuan(dlgSummary.buyAmt) }}</span></div>
          <div class="ds-item"><span class="ds-k">卖出金额</span><span class="ds-v">{{ formatCompactMoneyYuan(dlgSummary.sellAmt) }}</span></div>
          <div class="ds-item"><span class="ds-k">股数</span><span class="ds-v">{{ formatNumber(dlgSummary.shares, 'quantity') }}</span></div>
          <div class="ds-item"><span class="ds-k">盈亏</span>
            <span class="ds-v" :class="marketValueClass(dlgSummary.pnl)">{{ formatCompactMoneyYuan(dlgSummary.pnl, { forceSign: true }) }}</span></div>
          <div class="ds-item">
            <span class="ds-k">买入优先级
              <HelpTip title="为什么买它？" :width="340">
                <HelpTipItem question="方案内排名是什么">
                  <ul>
                    <li>当天选股方案命中的股票按评分排序后的优先级，买入按此顺序执行。</li>
                  </ul>
                </HelpTipItem>
                <HelpTipItem question="全市场榜单名次是什么">
                  <ul>
                    <li>该股票在当日每日榜单的全市场评分排序名次；方案命中的股票不一定处于榜单前列。</li>
                  </ul>
                </HelpTipItem>
              </HelpTip>
            </span>
            <span class="ds-v ds-rank">
              方案内第 {{ dlgSummary.pickRank || '—' }}<span class="ds-sub"> / 命中 {{ dlgSummary.pool || '—' }} 只</span>
            </span>
            <span class="ds-rank2">
              全市场榜单 <b>#{{ dlgSummary.rank || '—' }}</b> ·
              <ScoreGradeTag v-if="dlgSummary.grade" :grade="dlgSummary.grade" />
              <span v-else>—</span>
              <el-button data-button-kind="navigation" link type="primary" size="small" @click="openDayBoard(dlgSummary.entry, dlgCode)">查看当日榜单</el-button>
            </span>
          </div>
          <div class="ds-item ds-span"><span class="ds-k">{{ dlgSummary.entry }} 买 → {{ dlgSummary.exit }} 卖（{{ dlgSummary.reason }}）</span></div>
        </div>
        <div class="dlg-legend">
          <span class="lg buy">▲ 买入（买入分档）</span>
          <span class="lg sell">▼ 卖出（卖出原因 + 该笔收益）</span>
          <span class="dlg-hint">买卖点按成交日标注</span>
        </div>
        <StockChartWorkspace
          v-if="dlgBars.length"
          class="backtest-trade-chart"
          :bars="dlgBars"
          :indicators="dlgIndicators"
          :markers="dlgMarkers"
          :slot2="chartPreferences.preferences.value.slot2"
          :slot3="chartPreferences.preferences.value.slot3"
          :height-ratios="chartPreferences.currentRatios.value"
          adjust-label="前复权"
          :zoom-start="dlgZoom.start"
          :zoom-end="dlgZoom.end"
          :min-height="480"
          :macd-state="dlgMacdState"
          :macd-error="dlgIndicatorError"
          aria-label="回测交易 K 线多图联动工作区"
          @ratio-draft="chartPreferences.handleRatioDraft"
          @ratio-commit="chartPreferences.handleRatioCommit"
          @workspace-resize="chartPreferences.handleWorkspaceResize"
          @retry-macd="loadDialogIndicators"
        />
        <div class="dlg-tbl-title">本股交易明细 + 卖出后表现（看卖得对不对）</div>
        <AppDataTable :data="dlgTrades" size="small" class="dlg-trades" embedded>
          <AppTableColumn label="买入" prop="entry_date" />
          <AppTableColumn label="卖出" prop="exit_date" />
          <AppTableColumn label="收益">
            <template #default="{ row }">
              <span :class="marketValueClass(row.return_pct, { input: 'ratio' })">{{ pct(row.return_pct) }}</span>
            </template>
          </AppTableColumn>
          <AppTableColumn label="持有" header-meta="日" prop="hold_days"><template #default="{ row }">{{ formatNumber(row.hold_days, 'count') }}</template></AppTableColumn>
          <AppTableColumn label="卖出原因">
            <template #default="{ row }">
              <template v-if="sellTags(row).length">
                <el-tag v-for="t in sellTags(row)" :key="t" type="warning" size="small" effect="light" class="sell-tag">{{ t }}</el-tag>
              </template>
              <span v-else>{{ row.exit_reason }}</span>
            </template>
          </AppTableColumn>
          <AppTableColumn label="买入档">
            <template #default="{ row }">
              <ScoreGradeTag v-if="row.grade" :grade="row.grade" />
              <span v-else-if="row.entry_score != null" class="muted">无评级·{{ formatNumber(row.entry_score, 'score') }}分</span>
              <span v-else class="muted">—</span>
            </template>
          </AppTableColumn>
          <AppTableColumn label="榜单排名">
            <template #default="{ row }">{{ row.entry_rank ? '#' + row.entry_rank : '—' }}</template>
          </AppTableColumn>
          <AppTableColumn label="卖后10日">
            <template #default="{ row }"><span :class="row.fwd10 == null ? '' : marketValueClass(row.fwd10, { input: 'ratio' })">{{ pct(row.fwd10) }}</span></template>
          </AppTableColumn>
          <AppTableColumn label="卖后30日">
            <template #default="{ row }"><span :class="row.fwd30 == null ? '' : marketValueClass(row.fwd30, { input: 'ratio' })">{{ pct(row.fwd30) }}</span></template>
          </AppTableColumn>
          <AppTableColumn label="卖后半年">
            <template #default="{ row }"><span :class="row.fwd120 == null ? '' : marketValueClass(row.fwd120, { input: 'ratio' })">{{ pct(row.fwd120) }}</span></template>
          </AppTableColumn>
        </AppDataTable>
        <div class="dlg-hint" style="margin-top:6px">
          「卖后涨跌」是卖出后该股继续涨/跌的幅度：卖后大涨=卖早了，卖后续跌=卖对了。
        </div>
      </div>
    </AppDialog>

    <!-- 查看买入当日的每日榜单（全市场评分 Top 50，高亮本笔买入的票）-->
    <AppDialog v-model="boardDlg" class="board-dlg" :title="`${boardDate} 每日榜单 · 全市场评分 Top 50`" size="max" top="6cqh">
      <template #header>
        <span class="el-dialog__title app-inline-info">
          <span>{{ boardDate }} 每日榜单 · 全市场评分 Top 50</span>
          <HelpHint text="日期为选股信号日，即买入日的前一交易日；榜单展示当日全市场评分前 50 名。" />
        </span>
      </template>
      <div>
        <div class="dlg-hint" style="margin-bottom:8px">
          这是<b>选股信号日</b>（买入日的前一交易日）全市场按评分排序的榜单；<b class="bd-hit-legend">高亮行</b>=本笔买入的票，能看清它在大盘里的相对位置。
        </div>
        <AppStatusNotice
          v-if="boardMissing && boardRows.length"
          class="board-missing-notice"
          tone="warning"
          title="本笔买入股票不在 Top 50 内"
          description="该股票因选股方案命中且方案内排名靠前而被买入，并非综合分靠前"
        />
        <RankedStockResultTable
          :rows="boardRows"
          :columns="backtestBoardColumns"
          :loading="boardLoading"
          :analysis-pins="false"
          :st-as-of-date="boardDate"
          :row-class="(row) => boardRowClass({ row })"
          height="460"
        />
      </div>
    </AppDialog>

    <!-- 浏览公开回测抽屉（R5/R6）：kind='backtest'，tenant/public 段、无系统内置、默认全体公开 -->
    <AssetSearchDrawer
      v-model="runBrowseOpen"
      asset-label="回测"
      kind="backtest"
      :browse="(p) => browseRuns({ ...p, kind })"
      :rerun-item="rerunPublicRun"
      rerun-permission="backtest:run"
      :can-browse="canViewBacktest"
      test-id="backtest-run-drawer"
      @load="onRunLoaded"
      @rerun-done="onRunRerunDone"
    />

    <PageSettingsDrawer
      v-model="settingsOpen"
      title="策略回测"
      :dirty="isDirty || layoutDirty"
      page-key="backtest"
      :config="drawerConfig"
      :component-runtime-value-of="chartPreferences.componentRuntimeValueOf"
      @reset="resetBacktestSettings"
    >
      <template #business>
        <PageSettingSection section-key="default-parameters" title="默认参数">
          <PageSettingItem label="默认模式">
            <PageSegmented
              v-model="settings.kind"
              aria-label="默认模式"
              :options="BACKTEST_KIND_OPTIONS"
            />
          </PageSettingItem>
          <PageSettingItem label="Top N">
            <PageSegmented v-model="settings.topN" aria-label="Top N" :options="[
              { label: '5', value: 5 },
              { label: '10', value: 10 },
              { label: '20', value: 20 },
            ]" />
          </PageSettingItem>
          <PageSettingItem label="初始资金">
            <PageSegmented v-model="settings.initCap" aria-label="初始资金" :options="[
              { label: '500,000 元', value: 500000 },
              { label: '1,000,000 元', value: 1000000 },
              { label: '3,000,000 元', value: 3000000 },
            ]" />
          </PageSettingItem>
          <PageToggleRow v-model="settings.robustExpanded" label="默认展开稳健性测试" />
          <PageSettingItem label="默认对比指数">
            <MarketBenchmarkSelect
              v-model="settings.benchmarkCode"
              test-id="backtest-default-benchmark"
            />
          </PageSettingItem>
        </PageSettingSection>
      </template>
    </PageSettingsDrawer>
    </template>
  </LayoutHost>
</template>

<style scoped>
.page-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: var(--app-space-2);
  min-width: 0;
}
.page-title-row { display: flex; align-items: center; }
.page-head-actions { min-width: 0; max-width: 100%; }
.hist {
  display: flex;
  align-items: center;
  gap: var(--app-space-control-gap);
  flex-wrap: wrap;
  justify-content: flex-end;
  min-width: 0;
  max-width: 100%;
}
.history-run-select { flex: 1 1 var(--app-control-width-wide); min-width: 0; }
/* 样本名称与完整日期范围分两层展示，列容量由 description 角色承接。 */
.opt-range { display: block; white-space: nowrap; color: var(--el-text-color-secondary); font-size: var(--app-font-size-caption); }
.dlg-legend { display: flex; align-items: center; gap: var(--app-space-4); margin-bottom: 8px; font-size: var(--app-font-size-caption); }
.dlg-legend .lg.buy { color: var(--el-color-primary); font-weight: var(--app-font-weight-section); }
.dlg-legend .lg.sell { color: var(--el-color-warning); font-weight: var(--app-font-weight-section); }
.dlg-legend .dlg-hint { color: var(--el-text-color-secondary); }
.dlg-trades { margin-top: 8px; }
.dlg-summary {
  display: flex; flex-wrap: wrap; gap: var(--app-space-2) var(--app-space-5); align-items: center;
  padding: 10px 14px; margin-bottom: 10px; border-radius: var(--layout-card-radius);
  background: var(--app-section-bg);
}
.ds-item { display: flex; flex-direction: column; }
.ds-item.ds-span { margin-left: auto; }
.ds-k { font-size: var(--app-font-size-caption); color: var(--el-text-color-secondary); }
.ds-v { font-size: var(--app-font-size-data); line-height: var(--app-line-height-data); font-weight: var(--app-font-weight-section); font-variant-numeric: tabular-nums; }
.ds-rank { font-size: var(--app-font-size-section-title); }
.ds-rank .ds-sub { font-size: var(--app-font-size-caption); font-weight: var(--app-font-weight-regular); color: var(--el-text-color-secondary); }
.ds-rank2 { font-size: var(--app-font-size-caption); color: var(--el-text-color-regular); margin-top: 2px; }
:deep(.bd-hit) {
  background: var(--el-color-primary-light-8) !important; font-weight: var(--app-font-weight-strong);
  box-shadow: inset 4px 0 0 0 var(--el-color-primary);
}
:deep(.bd-hit td) { color: var(--el-color-primary); }
.bd-hit-legend {
  background: var(--el-color-primary-light-8); color: var(--el-color-primary);
  padding: 0 4px; border-radius: var(--app-radius-mark); box-shadow: inset 3px 0 0 0 var(--el-color-primary);
}
.run-time-notice { margin-bottom: var(--app-space-3); }
.board-missing-notice { margin-bottom: var(--app-space-2); }
.backtest-body {
  flex: 1 1 auto;          /* 填满 LayoutHost 的条件成长区 */
  /* 固定参数与结果最低高度共同撑开主区，低高度交给 LayoutHost 滚动。 */
  min-height: min-content;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.backtest-mode-rail {
  display: flex;
  align-items: center;
  flex: 0 0 auto;
  margin-bottom: var(--app-space-3);
}
.sell-tag { margin: 1px 2px 1px 0; }
.dlg-tbl-title { margin: 14px 0 6px; font-weight: var(--app-font-weight-section); font-size: var(--app-font-size-table); }
.form-card { margin-bottom: var(--app-space-3); flex: 0 0 auto; }
.backtest-params {
  display: grid;
  gap: var(--app-space-4);
}
.parameter-grid {
  display: grid;
  grid-template-columns: minmax(350px, 1.4fr) minmax(100px, 0.6fr) minmax(160px, 0.8fr) minmax(190px, 0.8fr);
  gap: var(--app-space-4);
}
.scheme-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 240px), 1fr));
  gap: var(--app-space-4);
}
.backtest-params :deep(.el-form-item) {
  margin-bottom: 0;
  min-width: 0;
}
.backtest-params :deep(.el-form-item__label) {
  display: flex;
  align-items: center;
  gap: var(--app-space-1);
}
.backtest-params :deep(.el-form-item__content) {
  min-width: 0;
  gap: var(--app-space-2);
}
.backtest-params :deep(.asset-profile-select),
.backtest-params :deep(.el-input-number) {
  width: 100%;
}
.date-range {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
  align-items: center;
  gap: var(--app-space-2);
  width: 100%;
  min-width: 0;
}
.date-range :deep(.el-date-editor) { width: 100%; min-width: 0; }
.date-range-separator { color: var(--el-text-color-secondary); }
.industry-controls {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
  width: 100%;
}
.industry-controls :deep(.el-checkbox) { margin-right: 0; }
.industry-controls :deep(.el-input-number) { flex: 1; min-width: 0; }
.required-mark { color: var(--el-color-danger); }
.parameter-footer {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-3);
  padding-top: var(--app-space-3);
  border-top: 1px solid var(--app-border-divider);
}
.parameter-status {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--app-space-1);
  min-width: 0;
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
}
.backtest-params .temp-readonly-chip {
  flex-wrap: wrap;
  min-width: 0;
  max-width: 100%;
  white-space: normal;
}
.is-score-check { grid-template-columns: minmax(320px, 1fr) minmax(0, 1fr); }
.is-score-check .parameter-grid,
.is-score-check .scheme-grid { grid-template-columns: minmax(0, 1fr); }
.is-score-check .parameter-footer { grid-column: 1 / -1; }
.results {
  flex: 1 1 240px;
  --app-scroll-display: flex;
  --app-scroll-direction: column;
  min-height: 240px;
  /* 第二原则：各块最低高宽放不下时，整个结果区滚动兜底（够放时不出滚动条）*/
  --app-scroll-gap: var(--app-space-3);
  --app-scroll-padding-right: 2px;
}
.results-top {
  flex: 0 0 auto;  /* 绩效卡/资金曲线/稳健性/分层表：按内容取自然高 */
}
.lbl { color: var(--el-text-color-secondary); font-size: var(--app-font-size-table); margin-left: 6px; display: inline-flex; align-items: center; gap: var(--app-space-1); }
.robust-row { margin-bottom: 10px; }
.run-row { margin-left: auto; }
.unit { font-size: var(--app-font-size-caption); color: var(--el-text-color-secondary); margin-right: 4px; }
.unit.off { opacity: 0.4; }
.tip-inline { color: var(--el-text-color-secondary); font-size: var(--app-font-size-caption); }
.prof-desc {
  margin-top: 12px; padding: 8px 12px; border-radius: var(--layout-control-radius);
  background: var(--el-color-primary-light-9); font-size: var(--app-font-size-table);
  display: flex; align-items: baseline; gap: var(--app-space-2);
}
.prof-desc .pd-tag { font-weight: var(--app-font-weight-section); color: var(--el-color-primary); white-space: nowrap; }
.prof-desc .pd-body { color: var(--el-text-color-regular); }
.block { margin-bottom: 14px; }
.results-top > .block:last-child {
  margin-bottom: 0;
}
.trade-block {
  /* 第一原则：交易表填满剩余高度并表体内滚（表头吸顶）；
     空间不足时退到约 6–8 行的最低高度，由结果区整体滚动兜底 */
  flex: 1 1 auto;
  min-height: 300px;
  overflow: hidden;
  margin-bottom: 0;
  display: flex;
  flex-direction: column;
}
.trade-table-wrap {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.block-title { font-weight: var(--app-font-weight-section); margin-bottom: 10px; display: flex; align-items: baseline; gap: var(--app-density-control-gap, var(--app-space-2)); }
.block-title .sub { font-weight: var(--app-font-weight-regular); font-size: var(--app-font-size-caption); color: var(--el-text-color-secondary); }
.bench-choice { margin-left: auto; display: flex; align-items: center; gap: var(--app-space-2); font-weight: var(--app-font-weight-regular); font-size: var(--app-font-size-caption); color: var(--el-text-color-secondary); }
.export-btn { margin-left: auto; }
.metrics { display: grid; grid-template-columns: repeat(5, 1fr); gap: var(--app-space-3); }
.metric { background: var(--app-section-bg); border-radius: var(--layout-card-radius); padding: 12px 14px; }
.m-label { font-size: var(--app-font-size-caption); color: var(--el-text-color-secondary); }
.m-val { font-size: var(--app-font-size-page-title-sm); font-weight: var(--app-font-weight-strong); font-variant-numeric: tabular-nums; margin-top: 4px; }
.metric.good .m-val { color: var(--market-up-color); }
.metric.bad .m-val { color: var(--market-down-color); }
.hit { font-weight: var(--app-font-weight-section); font-variant-numeric: tabular-nums; }
.excess { display: block; font-size: var(--app-font-size-caption); }
.unreliable { display: block; font-size: var(--app-font-size-caption); color: var(--app-warning-text); }
.base { color: var(--el-text-color-secondary); }
.legend-line { font-size: var(--app-font-size-caption); color: var(--el-text-color-secondary); margin-top: 8px; }
.clickable :deep(.el-table__row) { cursor: pointer; }

@container app-viewport (max-width: 1180px) {
  .parameter-grid { grid-template-columns: repeat(auto-fit, minmax(min(100%, 350px), 1fr)); }
}

@container app-viewport (max-width: 720px) {
  .scheme-grid,
  .is-score-check { grid-template-columns: minmax(0, 1fr); }
  .date-field { grid-column: 1 / -1; }
  .page-head {
    align-items: flex-start;
    flex-direction: column;
  }
  .page-head-actions,
  .hist {
    width: 100%;
    justify-content: flex-start;
  }
  .hist .lbl {
    margin-left: 0;
  }
  .history-run-select {
    flex: 1 1 100%;
    width: 100% !important;
    max-width: 100%;
  }
}

@container app-viewport (max-width: 480px) {
  .parameter-grid,
  .date-range { grid-template-columns: minmax(0, 1fr); }
  .date-range-separator { display: none; }
  .parameter-footer { align-items: flex-start; }
  .parameter-status { width: 100%; }
}

/* 方案只读预览保留在对应字段内，长名称可换行，关闭入口仍可达。 */
.temp-readonly-chip {
  display: inline-flex;
  align-items: center;
  gap: var(--app-space-control-gap);
  padding: 2px 6px;
  white-space: nowrap;
}
.temp-readonly-chip-prefix {
  color: var(--el-text-color-secondary);
}
</style>
