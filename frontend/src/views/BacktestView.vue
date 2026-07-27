<script setup lang="ts">
import AppTableColumn from '@/components/AppTableColumn.vue'
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computeBoard, type BoardRow } from '@/api/board'
import {
  runBacktest, prepareBacktest, listRuns, getRun, deleteRun, runRobust, setRunVisibility,
  type StrategyResult, type Layers, type RunParams, type LayerCell,
  type TradeRow, type RunSummary, type ParamSweepResult, type InOutSampleResult,
} from '@/api/backtest'
import { listProfiles, getProfile, type Profile } from '@/api/screening'
import { listScoreProfiles, type ScoreProfileSummary } from '@/api/scoreProfile'
import { listTradeProfiles, type TradeProfileSummary } from '@/api/tradeProfile'
import { getBars, type Bar } from '@/api/stocks'
import EquityChart from '@/components/EquityChart.vue'
import CandleChart, { type TradeMarker } from '@/components/CandleChart.vue'
import AppControlItem from '@/components/AppControlItem.vue'
import AppControlRow from '@/components/AppControlRow.vue'
import AppDataTable from '@/components/AppDataTable.vue'
import AppStateBlock from '@/components/AppStateBlock.vue'
import TradeDatePicker from '@/components/TradeDatePicker.vue'
import HelpTip from '@/components/HelpTip.vue'
import PageSegmented from '@/components/PageSegmented.vue'
import PageSettingSection from '@/components/PageSettingSection.vue'
import PageSettingsDrawer from '@/components/PageSettingsDrawer.vue'
import PageSettingsTrigger from '@/components/PageSettingsTrigger.vue'
import PageToggleRow from '@/components/PageToggleRow.vue'
import AssetVisibilityActions from '@/components/AssetVisibilityActions.vue'
import AssetVisibilityTag from '@/components/AssetVisibilityTag.vue'
import AssetProfileLabel from '@/components/AssetProfileLabel.vue'
import { usePageSettings } from '@/composables/usePageSettings'
import { useUserPreference } from '@/composables/useUserPreference'
import { useTradeDates } from '@/composables/useTradeDates'
import LayoutHost from '@/layout/components/LayoutHost.vue'
import { getPageLayout } from '@/layout'
import { useRemoteLayoutConfig } from '@/composables/useRemoteLayoutConfig'
import { useAuthStore } from '@/stores/auth'
import { hasPermission } from '@/utils/permission'
import { getErrorMessage } from '@/utils/error'

const PARAMS_KEY = 'ai-stocks-backtest-params' // 表单参数持久化 fallback / 迁移源
type Visibility = 'private' | 'tenant' | 'public'
type HistorySource = 'all' | 'mine' | 'tenant' | 'public'
const auth = useAuthStore()
const settingsOpen = ref(false)
const backtestDefaults = {
  kind: 'strategy' as 'strategy' | 'score_check',
  topN: 10,
  initCap: 1_000_000,
  autoLoadHistory: true,
  robustExpanded: false,
}
const { settings, isDirty, reset } = usePageSettings('backtest', backtestDefaults)
type BacktestParamMemory = {
  kind: 'strategy' | 'score_check'
  dateStart: string
  dateEnd: string
  profileId: string
  scoreProfileId: string
  tradeProfileId: string
  topN: number
  initCap: number
  industryOn: boolean
  industryPct: number
}
const backtestParamDefaults: BacktestParamMemory = {
  kind: 'strategy',
  dateStart: '2024-01-01',
  dateEnd: '2024-12-31',
  profileId: '',
  scoreProfileId: '',
  tradeProfileId: '',
  topN: 10,
  initCap: 1_000_000,
  industryOn: false,
  industryPct: 20,
}
const { value: rememberedParams, hydrated: rememberedParamsHydrated } = useUserPreference({
  scope: 'feature',
  pageKey: 'backtest',
  prefKey: 'params',
  defaults: backtestParamDefaults,
  localStorageKey: PARAMS_KEY,
})

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
  isDirty: layoutDirty,
  resetAll: resetLayout,
} = useRemoteLayoutConfig(backtestLayout)

// 抽屉「布局」「组件设置」两段由 PageSettingsDrawer 按元数据自动渲染（见 pageRegistry.componentMeta）。
const drawerConfig = { knobs: layoutKnobs, valueOf, sourceOf, setKnob, componentValueOf, setComponentKnob, componentSourceOf, layerValuesOf, componentLayerValuesOf }

// 逐笔表排序/列显隐（组件配置层 trades slot）：抽屉写值由 ComponentAutoSettings 自动渲染；页面只读 getter。
type TradeSort = 'entry' | 'exit' | 'return' | 'hold'
const TRADE_SORT_PROPS: Record<string, TradeSort> = {
  entry_date: 'entry',
  exit_date: 'exit',
  return_pct: 'return',
  hold_days: 'hold',
}
const tradeSort = computed<TradeSort>(() => {
  const raw = componentValueOf('trades', 'defaultSort')
  return raw === 'exit' || raw === 'return' || raw === 'hold' ? raw : 'entry'
})
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
  setComponentKnob('trades', 'defaultSort', TRADE_SORT_PROPS[prop] ?? 'entry')
}

const kind = ref<'strategy' | 'score_check'>(settings.kind)
const dateStart = ref('2024-01-01')
const dateEnd = ref('2024-12-31')
const profileId = ref<string>('')      // 筛选方案（候选池），空=全市场候选
const scoreProfileId = ref<string>('') // 评分方案（排序/验证）
const tradeProfileId = ref<string>('') // 买卖方案（买/卖/兜底）
const topN = ref(Number(settings.topN))
const initCap = ref(Number(settings.initCap))
const industryOn = ref(false)
const industryPct = ref(20)            // 单行业持仓上限 %
const profiles = ref<Profile[]>([])
const scoreProfiles = ref<ScoreProfileSummary[]>([])
const tradeProfiles = ref<TradeProfileSummary[]>([])
const profileOptionsLoading = ref(true)
const profileOptionsError = ref('')
const nextRunSourceRef = ref('')

function screenProfileKey(p: Profile): string {
  return p.profile_ref || p.id
}

function normalizeScreenProfileKey(value?: string | null): string {
  if (!value) return ''
  const matched = profiles.value.find((p) => screenProfileKey(p) === value || p.id === value)
  return matched ? screenProfileKey(matched) : value
}
const selectedScreenProfile = computed(() =>
  profiles.value.find((p) => screenProfileKey(p) === profileId.value || p.id === profileId.value),
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
  scoreProfiles.value.find((p) => scoreProfileKey(p) === scoreProfileId.value || p.id === scoreProfileId.value),
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
  tradeProfiles.value.find((p) => tradeProfileKey(p) === tradeProfileId.value || p.id === tradeProfileId.value),
)

function tradeProfileName(value: string): string {
  return tradeProfiles.value.find((p) => tradeProfileKey(p) === value || p.id === value)?.name || ''
}

const loading = ref(false)
const resultError = ref('')
const resultErrorContext = ref<'run' | 'history'>('run')
const strat = ref<StrategyResult | null>(null)
const sig = ref<Layers | null>(null)
const runTime = ref('')          // 当前展示结果的回测运行时间（加载历史时显示；刚跑完为空）
const fromHistory = ref(false)   // 当前结果是否来自加载历史

const gradeTag: Record<string, '' | 'success' | 'warning' | 'info'> = {
  主升浪核心: 'success', 龙头候选: 'warning', 观察: 'info',
}
const robustPanels = ref<string[]>(settings.robustExpanded ? ['robust'] : [])
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
const historySource = ref<HistorySource>('all')
const runVisibilitySaving = ref(false)

// 切换"策略/信号"标签 → 清空下方结果（避免显示与当前模式不符的旧结果）
// loadingRun 期间由程序设置参数，不触发清空 / 不置脏
const loadingRun = ref(false)
watch(kind, () => {
  if (loadingRun.value) return
  strat.value = null; sig.value = null; selectedRun.value = ''
  loadHistory()  // 历史按 kind 分别加载，策略与评分验证不混展
})
watch(historySource, () => {
  selectedRun.value = ''
  strat.value = null
  sig.value = null
  loadHistory()
})

// 运行按钮状态机：dirty=true 蓝色可点；出结果/载入历史后置 false（灰、不可点）；改任一参数恢复
const dirty = ref(true)
watch(
  [kind, dateStart, dateEnd, profileId, scoreProfileId, tradeProfileId, topN, initCap, industryOn, industryPct],
  () => { if (!loadingRun.value) dirty.value = true },
)
watch(() => settings.kind, (value) => { kind.value = value })
watch(() => settings.topN, (value) => { topN.value = Number(value) })
watch(() => settings.initCap, (value) => { initCap.value = Number(value) })
watch(() => settings.robustExpanded, (value) => { robustPanels.value = value ? ['robust'] : [] })
watch(rememberedParamsHydrated, (ready) => {
  if (ready && !loadingRun.value) restoreParams()
})
// 程序化改参（运行/载入历史）后清脏：等参数 watcher 跑完再置 false
function clearDirtySoon() {
  nextTick(() => { dirty.value = false; loadingRun.value = false })
}

// 方案(版本) 文本：名字带版本号，空则占位
function nameVer(name?: string | null, ver?: number | null, fallback = ''): string {
  if (!name) return fallback
  return ver != null ? `${name}(v${ver})` : name
}

function runKey(r: RunSummary): string {
  return r.run_ref || r.asset_ref || r.id
}

const selectedRunSummary = computed(() =>
  runHistory.value.find((r) => runKey(r) === selectedRun.value || r.id === selectedRun.value),
)
const selectedRunReadonly = computed(() => !!selectedRunSummary.value?.readonly)
const historyEmptyText = computed(() => {
  if (historySource.value === 'mine') return '暂无回测记录'
  if (historySource.value === 'tenant') return '暂无租户公开记录'
  if (historySource.value === 'public') return '暂无全体公开记录'
  return ''
})
const canPublishTenant = computed(() =>
  hasPermission(auth.role, auth.permissions, 'backtest:publish-tenant'),
)
const canPublishPublic = computed(() =>
  hasPermission(auth.role, auth.permissions, 'backtest:publish-public'),
)
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
const runOptions = computed(() =>
  runHistory.value.map((r) => {
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
      color: ret == null ? '' : ret >= 0 ? 'var(--market-up-color)' : 'var(--market-down-color)',
      retTxt: ret == null ? '' : (ret >= 0 ? '+' : '') + (ret * 100).toFixed(1) + '%',
      source: r.source,
      ownerLabel: r.owner_label,
    }
  }),
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

// —— 表单参数持久化（localStorage）：下次进来沿用上次设置 ——
function saveParams() {
  rememberedParams.kind = kind.value
  rememberedParams.dateStart = dateStart.value
  rememberedParams.dateEnd = dateEnd.value
  rememberedParams.profileId = profileId.value
  rememberedParams.scoreProfileId = scoreProfileId.value
  rememberedParams.tradeProfileId = tradeProfileId.value
  rememberedParams.topN = topN.value
  rememberedParams.initCap = initCap.value
  rememberedParams.industryOn = industryOn.value
  rememberedParams.industryPct = industryPct.value
}
function restoreParams() {
  try {
    const p = rememberedParams
    const rawKind = (rememberedParams as unknown as { kind?: string }).kind
    kind.value = (rawKind === 'signal' ? 'score_check' : rawKind as 'strategy' | 'score_check' | undefined) ?? kind.value
    dateStart.value = p.dateStart ?? dateStart.value
    dateEnd.value = p.dateEnd ?? dateEnd.value
    profileId.value = normalizeScreenProfileKey(p.profileId ?? profileId.value)
    scoreProfileId.value = p.scoreProfileId ?? scoreProfileId.value
    tradeProfileId.value = normalizeTradeProfileKey(p.tradeProfileId ?? tradeProfileId.value)
    topN.value = p.topN ?? topN.value
    initCap.value = p.initCap ?? initCap.value
    industryOn.value = !!p.industryOn; industryPct.value = p.industryPct ?? industryPct.value
  } catch { /* ignore */ }
}

async function loadProfileOptions() {
  profileOptionsLoading.value = true
  profileOptionsError.value = ''
  const failures: string[] = []
  try {
    const [screenResult, scoreResult, tradeResult] = await Promise.allSettled([
      listProfiles(),
      listScoreProfiles(),
      listTradeProfiles(),
    ])
    if (screenResult.status === 'fulfilled') {
      profiles.value = screenResult.value
      profileId.value = normalizeScreenProfileKey(profileId.value)
    } else {
      failures.push(getErrorMessage(screenResult.reason, '选股方案加载失败'))
    }
    if (scoreResult.status === 'fulfilled') {
      scoreProfiles.value = scoreResult.value
      scoreProfileId.value = normalizeScoreProfileKey(scoreProfileId.value)
    } else {
      failures.push(getErrorMessage(scoreResult.reason, '评分方案加载失败'))
    }
    if (tradeResult.status === 'fulfilled') {
      tradeProfiles.value = tradeResult.value
      tradeProfileId.value = normalizeTradeProfileKey(tradeProfileId.value)
    } else {
      failures.push(getErrorMessage(tradeResult.reason, '买卖方案加载失败'))
    }
    profileOptionsError.value = failures.join('；')
  } finally {
    profileOptionsLoading.value = false
  }
}

async function loadHistory() {
  historyError.value = ''
  try {
    runHistory.value = (await listRuns(kind.value, historySource.value)).runs
  } catch (error) {
    historyError.value = getErrorMessage(error, '历史回测加载失败')
  }
}

function applyRunParams(run: RunSummary) {
  let p: any = {}
  try { p = JSON.parse((run as any).params || '{}') } catch { /* ignore */ }
  if (p.date_start) dateStart.value = ymd(p.date_start)
  if (p.date_end) dateEnd.value = ymd(p.date_end)
  profileId.value = normalizeScreenProfileKey(p.profile_id)
  scoreProfileId.value = normalizeScoreProfileKey(p.score_profile_id)
  tradeProfileId.value = normalizeTradeProfileKey(p.trade_profile_id)
  if (p.top_n) topN.value = p.top_n
  if (p.initial_capital) initCap.value = p.initial_capital
  industryOn.value = p.industry_max_pct != null; if (p.industry_max_pct != null) industryPct.value = Math.round(p.industry_max_pct * 100)
  return p
}

// 从历史重新载入某次回测结果（不重跑）
async function loadRun(id: string) {
  if (!id) return
  loading.value = true
  loadingRun.value = true
  nextRunSourceRef.value = ''
  resultError.value = ''
  try {
    const r = await getRun(id)
    const ca = (r.run as { created_at?: string }).created_at
    runTime.value = ca ? String(ca).slice(0, 19) : ''
    fromHistory.value = true
    if (r.run.kind === 'signal' || r.run.kind === 'score_check') {
      kind.value = 'score_check'
      strat.value = null
      sig.value = r.layers as Layers
    } else {
      kind.value = 'strategy'
      // 同步表单到该次回测的参数（方案/持仓/本金/卖出规则随之显示）
      const p = applyRunParams(r.run)
      const bench = p.benchmark || '000905.SH'
      const initCapV = r.equity.length ? r.equity[0].equity : initCap.value
      strat.value = {
        run_id: r.run.run_ref || id, metrics: r.metrics as any, layers: r.layers as Layers,
        trades: r.trades as TradeRow[], equity: r.equity, benchmark_code: bench,
        initial_capital: initCapV,
      }
      sig.value = null
    }
    clearDirtySoon()  // 载入成功 → 按钮置灰（loadingRun 保持到 nextTick，避免参数 watcher 误置脏）
  } catch (e) {
    resultErrorContext.value = 'history'
    resultError.value = getErrorMessage(e, '历史回测载入失败')
    ElMessage.error(resultError.value)
    loadingRun.value = false
  } finally {
    loading.value = false
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
    await ElMessageBox.confirm(`确认删除这次回测记录？\n${desc}`, '删除历史回测', {
      type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消',
    })
  } catch { return /* 取消 */ }
  try {
    await deleteRun(selectedRun.value)
    ElMessage.success('已删除')
    strat.value = null; sig.value = null
    await loadHistory()
    if (runHistory.value.length) {
      selectedRun.value = runKey(runHistory.value[0])
      await loadRun(selectedRun.value)
    } else {
      selectedRun.value = ''
    }
  } catch (e) {
    ElMessage.error((e as Error).message || '删除失败')
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
    const updated = await setRunVisibility(selectedRun.value, visibility)
    const idx = runHistory.value.findIndex((r) => r.id === updated.id || runKey(r) === selectedRun.value)
    if (idx >= 0) runHistory.value[idx] = { ...runHistory.value[idx], ...updated }
    ElMessage.success(visibility === 'private' ? '已设为私有' : '公开设置已更新')
    await loadHistory()
  } catch (e) {
    ElMessage.error((e as Error).message || '公开设置失败')
  } finally {
    runVisibilitySaving.value = false
  }
}

async function reuseCurrentRunParams() {
  if (!selectedRun.value) return
  loading.value = true
  loadingRun.value = true
  try {
    const r = await getRun(selectedRun.value)
    if (r.run.kind === 'signal' || r.run.kind === 'score_check') {
      kind.value = 'score_check'
    } else {
      kind.value = 'strategy'
      applyRunParams(r.run)
      nextRunSourceRef.value = r.run.run_ref || selectedRun.value
    }
    strat.value = null
    sig.value = null
    fromHistory.value = false
    runTime.value = ''
    nextTick(() => { dirty.value = true; loadingRun.value = false })
    ElMessage.success('已复用参数')
  } catch (e) {
    ElMessage.error((e as Error).message || '复用参数失败')
    loadingRun.value = false
  } finally {
    loading.value = false
  }
}

// 导出当前回测的逐笔交易为 CSV（带 BOM，Excel 中文不乱码）
function exportTradesCsv() {
  if (!strat.value?.trades.length) return
  const headers = ['代码', '买入日', '买价', '卖出日', '卖价', '收益率', '盈亏(元)', '持有交易日', '卖出原因', '买入分档', '买入当日榜单排名']
  const lines = strat.value.trades.map((t) => {
    const tags = sellTags(t)
    const reason = tags.length ? tags.join('/') : t.exit_reason
    const buyGrade = t.grade || (t.entry_score != null ? `无评级(${t.entry_score.toFixed(0)})` : '')
    return [
      t.code, t.entry_date, t.entry_price, t.exit_date, t.exit_price,
      (t.return_pct * 100).toFixed(2) + '%', t.pnl, t.hold_days, reason, buyGrade,
      t.entry_rank ?? '',
    ].join(',')
  })
  const csv = '﻿' + [headers.join(','), ...lines].join('\n')
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `回测交易_${strat.value.run_id}.csv`
  a.click()
  URL.revokeObjectURL(url)
}

onMounted(async () => {
  restoreParams()
  kind.value = settings.kind
  topN.value = Number(settings.topN)
  initCap.value = Number(settings.initCap)
  robustPanels.value = settings.robustExpanded ? ['robust'] : []
  await loadProfileOptions()
  await loadHistory()
  // 默认载入最近一次回测结果，避免空屏、不用反复重跑
  if (settings.autoLoadHistory && runHistory.value.length) {
    selectedRun.value = runKey(runHistory.value[0])
    await loadRun(selectedRun.value)
  }
})

const HORIZONS = [10, 20]
const THRESHOLDS = [0.1, 0.2]

// —— 稳健性测试（即跑即看，不入历史）——
function buildStrategyParams(): Record<string, unknown> {
  const p: Record<string, unknown> = {
    date_start: dateStart.value, date_end: dateEnd.value,
    top_n: topN.value, initial_capital: initCap.value,
    profile_id: profileId.value || null,
  }
  if (scoreProfileId.value) p.score_profile_id = scoreProfileId.value
  if (tradeProfileId.value) p.trade_profile_id = tradeProfileId.value
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
      inOutRes.value = (await runRobust({ mode: 'in_out_sample', params: buildStrategyParams(), split_date: robustSplit.value })) as InOutSampleResult
    } else {
      const values = parseRobustValues()
      if (!values.length) { ElMessage.warning('请填写扫描取值'); return }
      sweepRes.value = (await runRobust({ mode: 'param_sweep', params: buildStrategyParams(), param: robustParam.value, values })) as ParamSweepResult
    }
  } catch (e) {
    ElMessage.error((e as Error).message || '稳健性测试失败')
  } finally {
    robustLoading.value = false
  }
}
const robustIsPct = computed(() =>
  ['industry_max_pct'].includes(robustParam.value))
function sweepValLabel(v: number): string {
  return robustIsPct.value ? (v * 100).toFixed(0) + '%' : String(v)
}

function buildBody(): RunParams {
  const body: RunParams = {
    kind: kind.value, date_start: dateStart.value, date_end: dateEnd.value,
    horizons: HORIZONS, thresholds: THRESHOLDS,
  }
  if (scoreProfileId.value) body.score_profile_id = scoreProfileId.value
  if (kind.value === 'strategy') {
    Object.assign(body, {
      top_n: topN.value, initial_capital: initCap.value,
      profile_id: profileId.value || null,
      trade_profile_id: tradeProfileId.value || null,
    })
    if (nextRunSourceRef.value) body.source_run_ref = nextRunSourceRef.value
    if (industryOn.value) body.industry_max_pct = industryPct.value / 100
  }
  return body
}

function validateRunSelection(): boolean {
  if (!scoreProfileId.value) {
    ElMessage.warning('请选择评分方案')
    return false
  }
  if (kind.value === 'strategy' && !tradeProfileId.value) {
    ElMessage.warning('请选择买卖方案')
    return false
  }
  return true
}

async function run() {
  if (!dateStart.value || !dateEnd.value) return ElMessage.warning('请选择回测区间')
  if (!validateRunSelection()) return
  const body = buildBody()
  // 查重：同条件（含方案版本）已有历史记录 → 询问加载历史 / 重新回测（覆盖）
  try {
    const pre = await prepareBacktest(body)
    if (pre.duplicate) {
      let choice: 'load' | 'rerun' | 'abort' = 'abort'
      try {
        await ElMessageBox.confirm(
          `已存在条件完全一致的历史记录（运行于 ${pre.duplicate.created_at.slice(0, 19)}）。\n可直接加载该结果，或重新回测覆盖它。`,
          '发现相同条件的历史回测',
          { confirmButtonText: '加载历史', cancelButtonText: '重新回测', distinguishCancelAndClose: true, type: 'info' },
        )
        choice = 'load'
      } catch (act) {
        choice = act === 'cancel' ? 'rerun' : 'abort' // cancel=重新回测；关闭/Esc=放弃
      }
      if (choice === 'abort') return
      if (choice === 'load') {
        selectedRun.value = pre.duplicate.run_id
        await loadRun(pre.duplicate.run_id)
        return
      }
      // rerun → 继续，runBacktest 落库时覆盖同签名旧记录
    }
  } catch { /* 查重失败不阻塞，直接回测 */ }
  await doRun(body)
}

async function doRun(body: RunParams) {
  saveParams()
  loading.value = true
  runTime.value = ''
  fromHistory.value = false
  resultError.value = ''
  resultErrorContext.value = 'run'
  try {
    if (body.kind === 'strategy') {
      strat.value = (await runBacktest(body)) as StrategyResult
      sig.value = null
      if (strat.value?.run_id) selectedRun.value = strat.value.run_id
    } else {
      sig.value = (await runBacktest(body)) as Layers
      strat.value = null
      // 评分验证也落库 → 用 run_id 选中历史
      const rid = (sig.value as unknown as { run_id?: string })?.run_id
      if (rid) selectedRun.value = rid
    }
    await loadHistory() // 新结果进历史列表
    nextRunSourceRef.value = ''
    dirty.value = false // 出结果 → 按钮置灰（参数未变时再点无意义）
  } catch (e) {
    resultErrorContext.value = 'run'
    resultError.value = getErrorMessage(e, '回测失败')
    ElMessage.error(resultError.value)
  } finally {
    loading.value = false
  }
}

function retryResult() {
  if (resultErrorContext.value === 'history' && selectedRun.value) {
    void loadRun(selectedRun.value)
    return
  }
  void run()
}

// —— 展示辅助 ——
const pct = (v: number | null | undefined, d = 1) =>
  v == null ? '—' : (v >= 0 ? '+' : '') + (v * 100).toFixed(d) + '%'
const num = (v: number | null | undefined, d = 2) => (v == null ? '—' : v.toFixed(d))

const metricCards = computed(() => {
  const m = strat.value?.metrics
  if (!m) return []
  return [
    { label: '累计收益', val: pct(m.total_return), good: m.total_return >= 0 },
    { label: '超额(vs基准)', val: pct(m.excess_return), good: m.excess_return >= 0 },
    { label: '年化收益', val: pct(m.annual_return), good: m.annual_return >= 0, hint: '短区间年化会被放大，仅长周期可信' },
    { label: '最大回撤', val: pct(m.max_drawdown), good: false },
    { label: '夏普', val: num(m.sharpe), good: m.sharpe >= 0 },
    { label: '卡玛', val: num(m.calmar), good: m.calmar >= 0 },
    { label: '胜率', val: pct(m.win_rate, 0), good: m.win_rate >= 0.5 },
    { label: '盈亏比', val: m.profit_factor == null ? '∞' : num(m.profit_factor), good: (m.profit_factor ?? 99) >= 1 },
    { label: '交易数', val: String(m.n_trades), good: true, neutral: true },
    { label: '平均持有(日)', val: num(m.avg_hold_days, 1), good: true, neutral: true },
  ]
})

// 分层命中率表：行=各档+base rate，列=N×X
const layerKeys = computed(() => {
  const out: { key: string; label: string }[] = []
  for (const n of HORIZONS) for (const x of THRESHOLDS)
    out.push({ key: `N${n}_X${Math.round(x * 100)}`, label: `${n}日≥${Math.round(x * 100)}%` })
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
    rows.push({ name: `${g} (n=${e.n_signals})`, isBase: false, cells })
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
const dlgMarkers = ref<TradeMarker[]>([])
const dlgTrades = ref<DlgTrade[]>([])
const dlgClicked = ref<TradeRow | null>(null)
const dlgLoading = ref(false)
const dlgZoom = ref<{ start: number; end: number }>({ start: 55, end: 100 })

const ymd = (s: string) => (s || '').slice(0, 10) // 容错：去掉可能的 " 00:00:00"
const wan = (yuan: number) => (yuan / 1e4).toFixed(1) + '万' // 金额→万元

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
    boardRows.value = (await computeBoard(sigDate, 50, scoreProfileId.value || undefined)).list
    boardMissing.value = !boardRows.value.some((r) => r.code === highlightCode)
    // 自动滚动高亮行到可视区
    nextTick(() => {
      const el = document.querySelector('.board-dlg .bd-hit') as HTMLElement | null
      el?.scrollIntoView({ block: 'center', behavior: 'smooth' })
    })
  } catch (e) {
    ElMessage.error((e as Error).message || '榜单计算失败')
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
  dlgMarkers.value = []
  try {
    const firstEntry = ymd(ts[0].entry_date)
    const lastExit = ymd(ts[ts.length - 1].exit_date)
    // 同花顺式：加载该股全部历史（含卖出后），默认缩放到交易区间，可自由缩放看全部
    const data = await getBars(code, { adjust: 'qfq', lookback: 6000 })
    dlgName.value = data.name
    dlgBars.value = data.bars
    // 买卖点标记
    const marks: TradeMarker[] = []
    for (const t of ts) {
      marks.push({ date: ymd(t.entry_date), kind: 'buy', label: `买${t.grade ? '·' + t.grade : ''}` })
      const ret = (t.return_pct >= 0 ? '+' : '') + (t.return_pct * 100).toFixed(1) + '%'
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
      return j && base ? +(j.close / base - 1).toFixed(4) : null
    }
    dlgTrades.value = ts.map((t) => ({
      ...t, fwd10: fwd(t.exit_date, 10), fwd30: fwd(t.exit_date, 30), fwd120: fwd(t.exit_date, 120),
    }))
  } catch (e) {
    ElMessage.error((e as Error).message || 'K线载入失败')
  } finally {
    dlgLoading.value = false
  }
}
</script>

<template>
  <LayoutHost :layout="backtestEffective">
    <template #action>
    <div class="page-head">
      <h2 class="title-row">
        回测
        <HelpTip title="回测在验证什么？" :width="460">
          <p><b>两种模式</b>：</p>
          <ul style="margin:0;padding-left:18px">
            <li><b>策略回测</b>：逐日「先卖后买」事件驱动撮合——T 日选股、<b>T+1 开盘成交</b>，跌破 MA 卖出；含交易成本、涨跌停/停牌不可成交、退市强平。算真实资金曲线。</li>
            <li><b>信号质量</b>：纯统计「分越高，N 日内摸到 X% 涨幅的概率是否越高」，并<b>减去全市场基线(base rate)</b>得超额——这才是评分的真实能力。</li>
          </ul>
          <p style="margin:6px 0 0;color:var(--app-warning-text)"><b>⚠️ 防坑</b>：① 用未来 N 日是「评估」非未来函数；② 短区间「年化/卡玛」会被放大，只看长周期；③ 样本量小(n小)的分档不可信。</p>
        </HelpTip>
      </h2>
      <div class="page-head-actions">
        <div class="hist">
          <span class="lbl">历史回测</span>
          <el-select v-model="historySource" class="history-source-select" style="width: 112px" size="default">
            <el-option value="all" label="全部" />
            <el-option value="mine" label="我的" />
            <el-option value="tenant" label="租户公开" />
            <el-option value="public" label="全体公开" />
          </el-select>
          <el-select
            v-model="selectedRun"
            class="history-run-select"
            style="width: 340px"
            @change="loadRun(selectedRun)"
            size="default"
          >
            <el-option v-for="o in runOptions" :key="o.id" :value="o.id" :label="o.label">
              <span :style="{ color: o.color, fontWeight: 600 }">{{ o.label }}</span>
              <AssetVisibilityTag
                mode="source"
                :source="o.source"
                :owner-label="o.ownerLabel"
                style="margin-left: 8px"
              />
              <span class="opt-range">{{ o.range }} <b :style="{ color: o.color }">{{ o.retTxt }}</b></span>
            </el-option>
          </el-select>
          <AssetVisibilityActions
            :show-visibility="!!selectedRunSummary"
            :visibility="selectedRunSummary?.visibility || 'private'"
            :readonly="selectedRunReadonly"
            :can-publish-tenant="canPublishTenant"
            :can-publish-public="canPublishPublic"
            :saving="runVisibilitySaving"
            :reuse-visible="selectedRunReadonly"
            reuse-permission="backtest:run"
            :reuse-disabled="!selectedRun"
            @publish="publishRunVisibility"
            @reuse="reuseCurrentRunParams"
          />
          <el-button v-permission="'backtest:delete'" v-if="!selectedRunReadonly" :disabled="!selectedRun" @click="removeCurrentRun" title="删除当前选中的历史回测">删除</el-button>
          <span v-if="!runHistory.length && historySource !== 'all'" class="hist-empty">{{ historyEmptyText }}</span>
        </div>
        <PageSettingsTrigger :dirty="isDirty" @click="settingsOpen = true" />
      </div>
    </div>
    </template>

    <template #main>
    <div class="backtest-body">
    <el-card
      v-loading="profileOptionsLoading"
      element-loading-text="正在加载回测方案…"
      shadow="never"
      class="form-card"
    >
      <AppStateBlock
        v-if="profileOptionsError"
        state="error"
        size="inline"
        title="回测方案加载不完整"
        :description="profileOptionsError"
        retry
        @retry="loadProfileOptions"
      />
      <AppControlRow class="form-row" dense>
        <el-radio-group v-model="kind">
          <el-radio-button value="strategy">策略回测</el-radio-button>
          <el-radio-button value="score_check">评分验证</el-radio-button>
        </el-radio-group>
        <AppControlItem label="区间">
          <TradeDatePicker v-model="dateStart" placeholder="开始" style="width: 160px" />
        </AppControlItem>
        <AppControlItem label="~">
          <TradeDatePicker v-model="dateEnd" placeholder="结束" style="width: 160px" />
        </AppControlItem>
        <AppControlItem>
          <template #label>
            评分方案
            <HelpTip title="评分方案" :width="340">
              <p>策略回测里用于<b>候选超过持仓数时按分排序截断</b>；评分验证里用于<b>分档检验高分组是否更易涨</b>。去「配置管理 → 评分规则」定义。</p>
            </HelpTip>
          </template>
          <el-select v-model="scoreProfileId" :loading="profileOptionsLoading" placeholder="请选择评分方案" no-data-text="暂无可用评分方案" style="width: 190px">
            <template v-if="selectedScoreProfile" #label>
              <AssetProfileLabel
                :name="selectedScoreProfile.name"
                :version="selectedScoreProfile.version"
                :source="selectedScoreProfile.source"
                :is-preset="selectedScoreProfile.is_preset"
                :owner-label="selectedScoreProfile.owner_label"
                :readonly="selectedScoreProfile.readonly"
              />
            </template>
            <el-option v-for="p in scoreProfiles" :key="scoreProfileKey(p)" :value="scoreProfileKey(p)" :label="p.name">
              <AssetProfileLabel
                :name="p.name"
                :version="p.version"
                :source="p.source"
                :is-preset="p.is_preset"
                :owner-label="p.owner_label"
                :readonly="p.readonly"
              />
            </el-option>
          </el-select>
        </AppControlItem>
        <template v-if="kind === 'strategy'">
          <AppControlItem>
            <template #label>
              选股方案
              <HelpTip title="选股方案 = 自定义策略入口" :width="360">
                <p>决定<b>每天从哪些股票里挑</b>：选某方案 → 只在该方案命中的股票里按评分排序取前 N 只；不选则使用全市场候选。</p>
                <p style="margin:6px 0 0">想自定义策略？去<b>「策略筛选」页</b>写规则并「保存为方案」，这里就会出现可选。</p>
              </HelpTip>
            </template>
            <!-- 悬浮显示方案具体选股条件 -->
            <el-tooltip placement="bottom" :disabled="!profileDesc" effect="dark">
              <template #content>
                <div style="max-width:360px;line-height:1.6">
                  <b>方案说明：</b> <br>{{ profileDesc }}
                </div>
              </template>
              <el-select v-model="profileId" :loading="profileOptionsLoading" clearable placeholder="请选择选股方案" no-data-text="暂无可用选股方案" style="width: 190px">
                <template v-if="selectedScreenProfile" #label>
                  <AssetProfileLabel
                    :name="selectedScreenProfile.name"
                    :version="selectedScreenProfile.version"
                    :source="selectedScreenProfile.source"
                    :is-preset="selectedScreenProfile.is_preset"
                    :owner-label="selectedScreenProfile.owner_label"
                    :readonly="selectedScreenProfile.readonly"
                  />
                </template>
                <el-option v-for="p in profiles" :key="screenProfileKey(p)" :value="screenProfileKey(p)" :label="p.name">
                  <AssetProfileLabel
                    :name="p.name"
                    :version="p.version"
                    :source="p.source"
                    :is-preset="p.is_preset"
                    :owner-label="p.owner_label"
                    :readonly="p.readonly"
                  />
                </el-option>
              </el-select>
            </el-tooltip>
          </AppControlItem>
          <AppControlItem>
            <template #label>
              持仓数
              <HelpTip title="持仓数（Top N）" :width="300">
                <p>同时最多持有几只：每个调仓日在候选里按综合分取<b>前 N 只</b>等权买入。</p>
              </HelpTip>
            </template>
            <el-input-number v-model="topN" :min="1" :max="50" controls-position="right" style="width: 100px" />
          </AppControlItem>
          <AppControlItem label="本金">
            <el-input-number v-model="initCap" :min="100000" :step="100000" controls-position="right" style="width: 140px" />
          </AppControlItem>
          <AppControlItem>
            <template #label>
              买卖方案
              <HelpTip title="买卖方案 = 买/卖/兜底" :width="380">
                <p>选某买卖方案 → 买入须<b>筛选命中且买入条件成立</b>，卖出走方案的<b>卖出条件 + 兜底(止盈/止损/最大持有)</b>。去「配置管理 → 买卖指标」定义。</p>
              </HelpTip>
            </template>
            <el-select v-model="tradeProfileId" :loading="profileOptionsLoading" placeholder="请选择买卖方案" no-data-text="暂无可用买卖方案" style="width: 190px">
              <template v-if="selectedTradeProfile" #label>
                <AssetProfileLabel
                  :name="selectedTradeProfile.name"
                  :version="selectedTradeProfile.version"
                  :source="selectedTradeProfile.source"
                  :is-preset="selectedTradeProfile.is_preset"
                  :owner-label="selectedTradeProfile.owner_label"
                  :readonly="selectedTradeProfile.readonly"
                />
              </template>
              <el-option v-for="p in tradeProfiles" :key="tradeProfileKey(p)" :value="tradeProfileKey(p)" :label="p.name">
                <AssetProfileLabel
                  :name="p.name"
                  :version="p.version"
                  :source="p.source"
                  :is-preset="p.is_preset"
                  :owner-label="p.owner_label"
                  :readonly="p.readonly"
                />
              </el-option>
            </el-select>
          </AppControlItem>
          <AppControlItem>
            <el-checkbox v-model="industryOn">行业上限</el-checkbox>
            <el-input-number v-model="industryPct" :disabled="!industryOn" :min="1" :max="100" controls-position="right" style="width: 92px" />
            <span class="unit" :class="{ off: !industryOn }">%</span>
          </AppControlItem>
        </template>
      </AppControlRow>

      <AppControlRow v-if="kind === 'strategy' && tradeProfileId" class="form-row sell-row" dense>
        <AppControlItem label="卖出规则">
          <span class="tip-inline">由买卖方案「{{ tradeProfileName(tradeProfileId) }}」的卖出条件 + 兜底接管</span>
        </AppControlItem>
      </AppControlRow>

      <!-- 运行按钮 + 紧贴其下的执行说明。dirty=蓝可点；出结果/载入历史后置灰；改参恢复 -->
      <div class="run-row">
        <el-button v-permission="'backtest:run'" :type="dirty ? 'primary' : 'info'" size="large" :loading="loading"
                   :disabled="!dirty" @click="run">
          {{ dirty ? '运行回测' : '已是最新结果' }}
        </el-button>
      </div>
      <div class="tip-line">
        本地同步执行，区间数月约 10 秒级；信号质量分析覆盖全市场（耗时稍长）。
        <span v-if="dataMin">数据可用范围 {{ dataMin }} ~ {{ dataMax }}。</span>
      </div>
    </el-card>

    <div v-loading="loading" class="results">
      <AppStateBlock
        v-if="historyError"
        state="error"
        size="compact"
        title="历史回测加载失败"
        :description="historyError"
        retry
        @retry="loadHistory"
      />
      <AppStateBlock
        v-if="resultError && !strat && !sig"
        state="error"
        :title="resultErrorContext === 'history' ? '历史回测载入失败' : '回测运行失败'"
        :description="resultError"
        retry
        @retry="retryResult"
      />
      <template v-else>
      <AppStateBlock
        v-if="resultError"
        state="error"
        size="compact"
        :title="resultErrorContext === 'history' ? '历史回测载入失败' : '回测结果刷新失败'"
        :description="resultError"
        retry
        @retry="retryResult"
      />
      <div class="results-top">
      <!-- 加载历史时：显示这次回测的运行时间 -->
      <div v-if="fromHistory && runTime && (strat || sig)" class="run-time-banner">
        📂 加载的历史记录 · 回测于 <b>{{ runTime }}</b> 运行
      </div>
      <!-- 策略：绩效卡 + 资金曲线 -->
      <template v-if="strat">
        <el-card shadow="never" class="block">
          <div class="metrics">
            <div v-for="c in metricCards" :key="c.label" class="metric"
                 :class="{ good: c.good && !c.neutral, bad: !c.good && !c.neutral }">
              <div class="m-label">{{ c.label }}<span v-if="c.hint" class="m-hint" :title="c.hint">ⓘ</span></div>
              <div class="m-val">{{ c.val }}</div>
            </div>
          </div>
        </el-card>
        <el-card shadow="never" class="block">
          <div class="block-title">资金曲线（组合 vs 基准 + 回撤）</div>
          <EquityChart :points="strat.equity" :benchmark-code="strat.benchmark_code" />
        </el-card>

        <!-- 稳健性测试（即跑即看，不入历史）：用当前表单参数为基准 -->
        <el-card shadow="never" class="block">
          <el-collapse v-model="robustPanels">
            <el-collapse-item name="robust">
              <template #title>
                <span class="block-title" style="margin:0">稳健性测试
                  <HelpTip title="结果是否稳健 / 过拟合？" :width="380">
                    <p><b>参数敏感性</b>：固定其它参数、扫一个参数的多个取值，看绩效是否平滑（而非靠某个魔法值）。</p>
                    <p style="margin:6px 0 0"><b>样本内外</b>：把区间按某日一分为二分别回测，样本外仍成立才可信。基准参数=上方表单当前设置。</p>
                  </HelpTip>
                </span>
              </template>
              <AppControlRow class="form-row robust-row" dense>
                <el-radio-group v-model="robustMode" size="small">
                  <el-radio-button value="param_sweep">参数敏感性</el-radio-button>
                  <el-radio-button value="in_out_sample">样本内外</el-radio-button>
                </el-radio-group>
                <template v-if="robustMode === 'param_sweep'">
                  <AppControlItem label="扫描参数">
                    <el-select v-model="robustParam" style="width: 170px" size="small">
                      <el-option v-for="o in ROBUST_PARAM_OPTS" :key="o.v" :value="o.v" :label="o.t" />
                    </el-select>
                  </AppControlItem>
                  <AppControlItem label="取值">
                    <el-input v-model="robustValuesText" size="small" style="width: 220px" placeholder="逗号分隔，如 5,10,15,20" />
                  </AppControlItem>
                </template>
                <template v-else>
                  <AppControlItem label="样本切分日">
                    <TradeDatePicker v-model="robustSplit" placeholder="区间内某交易日" style="width: 160px" />
                  </AppControlItem>
                </template>
                <el-button v-permission="'backtest:robust'" type="primary" plain size="small" :loading="robustLoading" @click="runRobustTest">运行</el-button>
                <span class="tip-inline">逐组完整回测，较慢</span>
              </AppControlRow>

              <!-- 参数敏感性结果 -->
              <AppDataTable v-if="sweepRes" :data="sweepRes.rows" size="small" border :fill="false">
                <AppTableColumn :label="ROBUST_PARAM_OPTS.find(o => o.v === sweepRes!.param)?.t || sweepRes.param" role="number">
                  <template #default="{ row }"><b>{{ sweepValLabel(row.value) }}</b></template>
                </AppTableColumn>
                <AppTableColumn label="累计收益" align="right">
                  <template #default="{ row }"><span :class="row.total_return >= 0 ? 'up' : 'down'">{{ pct(row.total_return) }}</span></template>
                </AppTableColumn>
                <AppTableColumn label="超额" align="right">
                  <template #default="{ row }"><span :class="row.excess_return >= 0 ? 'up' : 'down'">{{ pct(row.excess_return) }}</span></template>
                </AppTableColumn>
                <AppTableColumn label="最大回撤" align="right">
                  <template #default="{ row }">{{ pct(row.max_drawdown) }}</template>
                </AppTableColumn>
                <AppTableColumn label="夏普" align="right">
                  <template #default="{ row }">{{ num(row.sharpe) }}</template>
                </AppTableColumn>
                <AppTableColumn label="胜率" align="right">
                  <template #default="{ row }">{{ pct(row.win_rate) }}</template>
                </AppTableColumn>
                <AppTableColumn label="交易数" align="right">
                  <template #default="{ row }">{{ row.n_trades ?? '—' }}</template>
                </AppTableColumn>
              </AppDataTable>

              <!-- 样本内外结果 -->
              <AppDataTable v-if="inOutRes" :data="[
                { seg: '样本内', ...inOutRes.in_sample },
                { seg: '样本外', ...inOutRes.out_sample },
              ]" size="small" border :fill="false">
                <AppTableColumn label="样本">
                  <template #default="{ row }"><b>{{ row.seg }}</b><span class="opt-range">{{ row.range[0] }}~{{ row.range[1] }}</span></template>
                </AppTableColumn>
                <AppTableColumn label="累计收益" align="right">
                  <template #default="{ row }"><span :class="row.total_return >= 0 ? 'up' : 'down'">{{ pct(row.total_return) }}</span></template>
                </AppTableColumn>
                <AppTableColumn label="超额" align="right">
                  <template #default="{ row }"><span :class="row.excess_return >= 0 ? 'up' : 'down'">{{ pct(row.excess_return) }}</span></template>
                </AppTableColumn>
                <AppTableColumn label="最大回撤" align="right">
                  <template #default="{ row }">{{ pct(row.max_drawdown) }}</template>
                </AppTableColumn>
                <AppTableColumn label="夏普" align="right">
                  <template #default="{ row }">{{ num(row.sharpe) }}</template>
                </AppTableColumn>
                <AppTableColumn label="胜率" align="right">
                  <template #default="{ row }">{{ pct(row.win_rate) }}</template>
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
          <span class="sub">区间 {{ layersData.date_start }} ~ {{ layersData.date_end }}，总信号 {{ layersData.total_signals }}</span>
        </div>
        <AppDataTable :data="layerRows" size="small" :fill="false">
          <AppTableColumn label="分档">
            <template #default="{ row }">
              <b :class="{ base: row.isBase }">{{ row.name }}</b>
            </template>
          </AppTableColumn>
          <AppTableColumn v-for="lk in layerKeys" :key="lk.key" :label="lk.label" role="number" align="center">
            <template #default="{ row }">
              <template v-if="row.cells[lk.key] && row.cells[lk.key].hit_rate != null">
                <span class="hit">{{ (row.cells[lk.key].hit_rate * 100).toFixed(1) }}%</span>
                <span v-if="!row.isBase && row.cells[lk.key].excess != null"
                      class="excess" :class="{ pos: row.cells[lk.key].excess >= 0 }">
                  {{ pct(row.cells[lk.key].excess, 1) }}
                </span>
                <span v-if="!row.isBase && row.cells[lk.key].reliable === false" class="unreliable" title="样本量过小，不采信">·样本少</span>
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
      <el-card v-if="hasTradeRows" shadow="never" class="block trade-block">
        <div class="block-title">
          逐笔交易（{{ strat!.trades.length }} 笔）
          <span class="sub">点任一行 → 在 K 线上看该股的买卖点与原因（不跳转）</span>
          <el-button size="small" class="export-btn" @click="exportTradesCsv">导出 CSV</el-button>
        </div>
        <div class="trade-table-wrap">
        <AppDataTable :data="tradeRows" size="small" clickable
                  :border="tableBorder('trades')"
                  :default-sort="tradeDefaultSort" @sort-change="onTradeSortChange"
                  @row-click="(r:any) => openTradeChart(r)">
          <AppTableColumn label="代码" prop="code" />
          <AppTableColumn label="买入" prop="entry_date" sortable :sort-by="(r:any)=>r.entry_date" />
          <AppTableColumn label="买价"><template #default="{ row }">{{ num(row.entry_price) }}</template></AppTableColumn>
          <AppTableColumn label="卖出" prop="exit_date" sortable :sort-by="(r:any)=>r.exit_date" />
          <AppTableColumn label="卖价"><template #default="{ row }">{{ num(row.exit_price) }}</template></AppTableColumn>
          <AppTableColumn v-if="tradeColVisible('ret')" label="收益" prop="return_pct" sortable :sort-by="(r:any)=>r.return_pct">
            <template #default="{ row }">
              <span :class="row.return_pct >= 0 ? 'up' : 'down'">{{ pct(row.return_pct, 2) }}</span>
            </template>
          </AppTableColumn>
          <AppTableColumn v-if="tradeColVisible('hold')" label="持有(日)" prop="hold_days" sortable :sort-by="(r:any)=>r.hold_days" />
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
              <el-tag v-if="row.grade" :type="gradeTag[row.grade] ?? 'info'" size="small" effect="light">{{ row.grade }}</el-tag>
              <span v-else-if="row.entry_score != null" class="muted" title="综合分未达「观察」档阈值，但因候选池内排名靠前而买入">无评级·{{ row.entry_score.toFixed(0) }}分</span>
              <span v-else class="muted">—</span>
            </template>
          </AppTableColumn>
          <AppTableColumn v-if="tradeColVisible('rank')" label="榜单排名">
            <template #default="{ row }">{{ row.entry_rank ? '#' + row.entry_rank : '—' }}</template>
          </AppTableColumn>
        </AppDataTable>
        </div>
      </el-card>

      <el-empty v-if="!loading && !strat && !sig" class="app-empty" description="设置参数后点「运行回测」" />
      </template>
    </div>
    </div>
    </template>

    <template #overlays>
    <!-- 交易明细 → 内嵌 K 线（买卖点标注，蓝▲买/橙▼卖），不跳转 -->
    <el-dialog v-model="chartDlg" :title="`${dlgName || ''} ${dlgCode}　交易回放`" width="90%" top="5vh">
      <div v-loading="dlgLoading">
        <!-- 左上角：本笔交易摘要（收益率/买入金额/卖出金额/股数）-->
        <div v-if="dlgSummary" class="dlg-summary">
          <div class="ds-item"><span class="ds-k">本笔收益</span>
            <span class="ds-v" :class="dlgSummary.ret >= 0 ? 'up' : 'down'">{{ pct(dlgSummary.ret, 2) }}</span></div>
          <div class="ds-item"><span class="ds-k">买入金额</span><span class="ds-v">{{ wan(dlgSummary.buyAmt) }}</span></div>
          <div class="ds-item"><span class="ds-k">卖出金额</span><span class="ds-v">{{ wan(dlgSummary.sellAmt) }}</span></div>
          <div class="ds-item"><span class="ds-k">股数</span><span class="ds-v">{{ dlgSummary.shares.toLocaleString() }}</span></div>
          <div class="ds-item"><span class="ds-k">盈亏</span>
            <span class="ds-v" :class="dlgSummary.pnl >= 0 ? 'up' : 'down'">{{ wan(dlgSummary.pnl) }}</span></div>
          <div class="ds-item">
            <span class="ds-k">买入优先级
              <HelpTip title="为什么买它？" :width="340">
                <p><b>方案内排名</b>=当天选股方案命中的票按评分排序后的优先级（买入就按这个顺序）。</p>
                <p style="margin:6px 0 0"><b>全市场榜单 #</b>=它在当日<b>每日榜单</b>（全市场评分排序）里的名次——方案命中票不一定是榜单靠前的票。</p>
              </HelpTip>
            </span>
            <span class="ds-v ds-rank">
              方案内第 {{ dlgSummary.pickRank || '—' }}<span class="ds-sub"> / 命中 {{ dlgSummary.pool || '—' }} 只</span>
            </span>
            <span class="ds-rank2">
              全市场榜单 <b>#{{ dlgSummary.rank || '—' }}</b> · {{ dlgSummary.grade || '—' }}
              <el-button link type="primary" size="small" @click="openDayBoard(dlgSummary.entry, dlgCode)">查看当日榜单</el-button>
            </span>
          </div>
          <div class="ds-item ds-span"><span class="ds-k">{{ dlgSummary.entry }} 买 → {{ dlgSummary.exit }} 卖（{{ dlgSummary.reason }}）</span></div>
        </div>
        <div class="dlg-legend">
          <span class="lg buy">▲ 买入（买入分档）</span>
          <span class="lg sell">▼ 卖出（卖出原因 + 该笔收益）</span>
          <span class="dlg-hint">买卖点按成交日标注</span>
        </div>
        <CandleChart v-if="dlgBars.length" :bars="dlgBars" :markers="dlgMarkers"
                     :zoom-start="dlgZoom.start" :zoom-end="dlgZoom.end" />
        <div class="dlg-tbl-title">本股交易明细 + 卖出后表现（看卖得对不对）</div>
        <AppDataTable :data="dlgTrades" size="small" class="dlg-trades" :fill="false">
          <AppTableColumn label="买入" prop="entry_date" />
          <AppTableColumn label="卖出" prop="exit_date" />
          <AppTableColumn label="收益">
            <template #default="{ row }">
              <span :class="row.return_pct >= 0 ? 'up' : 'down'">{{ pct(row.return_pct, 2) }}</span>
            </template>
          </AppTableColumn>
          <AppTableColumn label="持有(日)" prop="hold_days" />
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
              <span v-if="row.grade">{{ row.grade }}</span>
              <span v-else-if="row.entry_score != null" class="muted">无评级·{{ row.entry_score.toFixed(0) }}分</span>
              <span v-else class="muted">—</span>
            </template>
          </AppTableColumn>
          <AppTableColumn label="榜单排名">
            <template #default="{ row }">{{ row.entry_rank ? '#' + row.entry_rank : '—' }}</template>
          </AppTableColumn>
          <AppTableColumn label="卖后10日">
            <template #default="{ row }"><span :class="row.fwd10 == null ? '' : row.fwd10 >= 0 ? 'up' : 'down'">{{ pct(row.fwd10, 1) }}</span></template>
          </AppTableColumn>
          <AppTableColumn label="卖后30日">
            <template #default="{ row }"><span :class="row.fwd30 == null ? '' : row.fwd30 >= 0 ? 'up' : 'down'">{{ pct(row.fwd30, 1) }}</span></template>
          </AppTableColumn>
          <AppTableColumn label="卖后半年">
            <template #default="{ row }"><span :class="row.fwd120 == null ? '' : row.fwd120 >= 0 ? 'up' : 'down'">{{ pct(row.fwd120, 1) }}</span></template>
          </AppTableColumn>
        </AppDataTable>
        <div class="dlg-hint" style="margin-top:6px">
          「卖后涨跌」是卖出后该股继续涨/跌的幅度：卖后大涨=卖早了，卖后续跌=卖对了。
        </div>
      </div>
    </el-dialog>

    <!-- 查看买入当日的每日榜单（全市场评分 Top 50，高亮本笔买入的票）-->
    <el-dialog v-model="boardDlg" class="board-dlg" :title="`${boardDate}（选股信号日）每日榜单 · 全市场评分 Top 50`" width="640px" top="6vh">
      <div v-loading="boardLoading">
        <div class="dlg-hint" style="margin-bottom:8px">
          这是<b>选股信号日</b>（买入日的前一交易日）全市场按评分排序的榜单；<b class="bd-hit-legend">高亮行</b>=本笔买入的票，能看清它在大盘里的相对位置。
        </div>
        <el-alert v-if="boardMissing && boardRows.length" type="warning" :closable="false" show-icon style="margin-bottom:8px"
                  title="本笔买入的票不在 Top 50 内（榜单名次更靠后）——它因选股方案命中且方案内排名靠前而被买入，并非综合分靠前。" />
        <AppDataTable :data="boardRows" size="small" height="460" :row-class-name="boardRowClass" :fill="false">
          <AppTableColumn label="#" prop="rank" />
          <AppTableColumn label="代码" prop="code" />
          <AppTableColumn label="名称" prop="name">
            <template #default="{ row }">{{ row.name || '—' }}</template>
          </AppTableColumn>
          <AppTableColumn label="综合分" prop="total_score" />
          <AppTableColumn label="评级" prop="grade" />
        </AppDataTable>
      </div>
    </el-dialog>

    <PageSettingsDrawer
      v-model="settingsOpen"
      title="策略回测"
      :dirty="isDirty || layoutDirty"
      page-key="backtest"
      :config="drawerConfig"
      @reset="reset(); resetLayout()"
    >
      <template #business>
        <PageSettingSection title="默认参数">
          <div class="setting-item">
            <div class="setting-label">默认模式</div>
            <PageSegmented v-model="settings.kind" aria-label="默认模式" :options="[
              { label: '策略回测', value: 'strategy' },
              { label: '评分验证', value: 'score_check' },
            ]" />
          </div>
          <div class="setting-item">
            <div class="setting-label">Top N</div>
            <PageSegmented v-model="settings.topN" aria-label="Top N" :options="[
              { label: '5', value: 5 },
              { label: '10', value: 10 },
              { label: '20', value: 20 },
            ]" />
          </div>
          <div class="setting-item">
            <div class="setting-label">初始资金</div>
            <PageSegmented v-model="settings.initCap" aria-label="初始资金" :options="[
              { label: '50万', value: 500000 },
              { label: '100万', value: 1000000 },
              { label: '300万', value: 3000000 },
            ]" />
          </div>
          <PageToggleRow v-model="settings.autoLoadHistory" label="自动加载最近历史回测" />
          <PageToggleRow v-model="settings.robustExpanded" label="默认展开稳健性测试" />
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
  align-items: flex-end;
  gap: var(--app-space-2);
  min-width: 0;
}
.page-head h2 { margin: 0; font-size: var(--app-font-size-page-title-sm); }
.page-head-actions { min-width: 0; max-width: 100%; }
.setting-item { display: flex; flex-direction: column; gap: var(--app-space-2); }
.setting-label { font-size: var(--app-font-size-body); color: var(--page-settings-text-subtle); }
.hist {
  display: flex;
  align-items: center;
  gap: var(--app-space-control-gap);
  flex-wrap: wrap;
  justify-content: flex-end;
  min-width: 0;
  max-width: 100%;
}
.history-source-select { flex: 0 0 112px; }
.history-run-select { flex: 1 1 260px; min-width: 0; max-width: 340px; }
.opt-range { float: right; color: var(--el-text-color-secondary); font-size: var(--app-font-size-caption); margin-left: 18px; }
.hist-empty { color: var(--el-text-color-secondary); font-size: var(--app-font-size-caption); white-space: nowrap; }
.dlg-legend { display: flex; align-items: center; gap: var(--app-space-4); margin-bottom: 8px; font-size: var(--app-font-size-caption); }
.dlg-legend .lg.buy { color: #3b82f6; font-weight: var(--app-font-weight-section); }
.dlg-legend .lg.sell { color: #f5a623; font-weight: var(--app-font-weight-section); }
.dlg-legend .dlg-hint { color: var(--el-text-color-secondary); }
.dlg-trades { margin-top: 8px; }
.dlg-summary {
  display: flex; flex-wrap: wrap; gap: var(--app-space-2) var(--app-space-5); align-items: center;
  padding: 10px 14px; margin-bottom: 10px; border-radius: 8px;
  background: var(--el-fill-color-light);
}
.ds-item { display: flex; flex-direction: column; }
.ds-item.ds-span { margin-left: auto; }
.ds-k { font-size: var(--app-font-size-micro); color: var(--el-text-color-secondary); }
.ds-v { font-size: var(--app-font-size-data); font-weight: var(--app-font-weight-strong); font-variant-numeric: tabular-nums; }
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
  padding: 0 4px; border-radius: 3px; box-shadow: inset 3px 0 0 0 var(--el-color-primary);
}
.run-time-banner {
  margin-bottom: 12px; padding: 7px 12px; border-radius: 6px; font-size: var(--app-font-size-table);
  background: var(--el-color-info-light-9); color: var(--el-text-color-regular);
  border: 1px solid var(--el-color-info-light-7);
}
.backtest-body {
  flex: 1 1 auto;          /* 填满 LayoutHost 的 .v-grow */
  min-height: 0;
  overflow: hidden;        /* 自身不滚：固定表单卡 + 内部 .results 区滚动 */
  display: flex;
  flex-direction: column;
}
.sell-tag { margin: 1px 2px 1px 0; }
.dlg-tbl-title { margin: 14px 0 6px; font-weight: var(--app-font-weight-section); font-size: var(--app-font-size-table); }
.title-row { display: flex; align-items: center; }
.form-card { margin-bottom: 14px; flex: 0 0 auto; }  /* 操作区固定高，不被结果挤压（第一层级）*/
.results {
  flex: 1 1 auto;
  display: flex;
  flex-direction: column;
  min-height: 0;
  /* 第二原则：各块最低高宽放不下时，整个结果区滚动兜底（够放时不出滚动条）*/
  overflow: auto;
  gap: var(--app-space-3);
  padding-right: 2px;
}
.results-top {
  flex: 0 0 auto;  /* 绩效卡/资金曲线/稳健性/分层表：按内容取自然高 */
}
.lbl { color: var(--el-text-color-secondary); font-size: var(--app-font-size-table); margin-left: 6px; display: inline-flex; align-items: center; gap: var(--app-space-1); }
.sell-row { margin-top: 12px; padding-top: 12px; border-top: 1px dashed var(--el-border-color); }
.robust-row { margin-bottom: 10px; }
.run-row { margin-top: 14px; }
.unit { font-size: var(--app-font-size-caption); color: var(--el-text-color-secondary); margin-right: 4px; }
.unit.off { opacity: 0.4; }
.tip-line { color: var(--el-text-color-secondary); font-size: var(--app-font-size-caption); margin-top: 8px; }
.tip-inline { color: var(--el-text-color-secondary); font-size: var(--app-font-size-caption); }
.prof-desc {
  margin-top: 12px; padding: 8px 12px; border-radius: 6px;
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
}
.trade-block :deep(.el-card__body) {
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.trade-table-wrap {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.block-title { font-weight: var(--app-font-weight-section); margin-bottom: 10px; display: flex; align-items: baseline; gap: var(--app-space-2); }
.block-title .sub { font-weight: var(--app-font-weight-regular); font-size: var(--app-font-size-caption); color: var(--el-text-color-secondary); }
.export-btn { margin-left: auto; }
.metrics { display: grid; grid-template-columns: repeat(5, 1fr); gap: var(--app-space-3); }
.metric { background: var(--el-fill-color-light); border-radius: 8px; padding: 12px 14px; }
.m-label { font-size: var(--app-font-size-caption); color: var(--el-text-color-secondary); }
.m-hint { margin-left: 3px; cursor: help; }
.m-val { font-size: var(--app-font-size-page-title-sm); font-weight: var(--app-font-weight-strong); font-variant-numeric: tabular-nums; margin-top: 4px; }
.metric.good .m-val { color: var(--market-up-color); }
.metric.bad .m-val { color: var(--market-down-color); }
.hit { font-weight: var(--app-font-weight-section); font-variant-numeric: tabular-nums; }
.excess { display: block; font-size: var(--app-font-size-micro); color: var(--market-down-color); }
.excess.pos { color: var(--market-up-color); }
.unreliable { display: block; font-size: var(--app-font-size-tiny); color: var(--app-warning-text); }
.base { color: var(--el-text-color-secondary); }
.legend-line { font-size: var(--app-font-size-caption); color: var(--el-text-color-secondary); margin-top: 8px; }
.up { color: var(--market-up-color); } .down { color: var(--market-down-color); }
.muted { color: var(--el-text-color-placeholder); }
.clickable :deep(.el-table__row) { cursor: pointer; }

@media (max-width: 720px) {
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
  .history-source-select {
    flex: 0 1 128px;
    min-width: 104px;
    max-width: 128px;
  }
  .history-run-select {
    flex: 1 1 100%;
    width: 100% !important;
    max-width: 100%;
  }
}

@media (max-width: 480px) {
  .form-card :deep(.el-card__body) {
    padding: 12px;
  }
  .form-row {
    gap: var(--app-space-2) var(--app-space-control-gap);
  }
  .form-row .lbl {
    margin-left: 0;
  }
}
</style>
