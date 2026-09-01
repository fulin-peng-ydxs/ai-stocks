<script setup lang="ts">
import AppTableColumn from '@/components/AppTableColumn.vue'
import {
  computed,
  onActivated,
  onBeforeUnmount,
  onDeactivated,
  onMounted,
  reactive,
  ref,
  watch,
} from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowRight } from '@element-plus/icons-vue'
import EquityChart from '@/components/EquityChart.vue'
import GrowthChart from '@/components/GrowthChart.vue'
import StockChartWorkspace from '@/components/stock-chart/StockChartWorkspace.vue'
import StockChartSettingSection from '@/components/StockChartSettingSection.vue'
import { useStatusColorPalette } from '@/components/chartTheme'
import AppDataTable from '@/components/AppDataTable.vue'
import AppRowActions from '@/components/AppRowActions.vue'
import AppStateBlock from '@/components/AppStateBlock.vue'
import TradeDatePicker from '@/components/TradeDatePicker.vue'
import HelpTip from '@/components/HelpTip.vue'
import HelpTipItem from '@/components/HelpTipItem.vue'
import PageSegmented from '@/components/PageSegmented.vue'
import PageSettingSection from '@/components/PageSettingSection.vue'
import PageSettingsDrawer from '@/components/PageSettingsDrawer.vue'
import PageSettingsTrigger from '@/components/PageSettingsTrigger.vue'
import KlineRangeSelect from '@/components/KlineRangeSelect.vue'
import KlineSettingSection from '@/components/KlineSettingSection.vue'
import {
  createDefaultStockChartPreferences,
  useStockChartPreferences,
  type AuxiliaryChartSlot,
  type StockChartPreferences,
} from '@/composables/useStockChartPreferences'
import { usePageSettings } from '@/composables/usePageSettings'
import { useComponentPageSizeSession } from '@/composables/useComponentPageSizeSession'
import { useKlinePrefs } from '@/composables/useKlinePrefs'
import { useTableSort } from '@/composables/useTableSort'
import LayoutHost from '@/layout/components/LayoutHost.vue'
import { getPageLayout, type PageLayout } from '@/layout'
import { resolveComponentNumberValue } from '@/layout/componentConfig'
import { PAGE_SIZE_OPTIONS } from '@/constants/pagination'
import { useRemoteLayoutConfig } from '@/composables/useRemoteLayoutConfig'
import {
  startSession, getSession, listSessions, growth as fetchGrowth, revealNext,
  placeTrade, cancelIntent, settleRound, saveReview, deleteSession,
  type RunningView, type DetailView, type SessionRow, type GrowthPoint, type DetailRound,
} from '@/api/training'
import type { Bar, IndicatorRow } from '@/api/stocks'
import { getErrorMessage } from '@/utils/error'
import { formatMoney, formatMoneyInput, parseMoneyInput } from '@/utils/money'
import type { AppRowAction } from '@/components/rowActions'

// ── 页面阶段：config(未开局) / running(训练中) / result(结算回看) ──
const view = ref<(RunningView & Partial<DetailView>) | null>(null)
const loading = ref(false)
const phase = computed<'config' | 'running' | 'result'>(() => {
  if (!view.value) return 'config'
  return view.value.status === 'completed' ? 'result' : 'running'
})

// ── 页面设置（开局参数 + 快捷下单预设，均持久化）──
const { settings: cfg, isDirty, reset, hydrated } = usePageSettings('training', {
  mode: 'single' as 'single' | 'multi',
  range_start: null as string | null,
  range_end: null as string | null,
  n_rounds: 5,
  window_days: 20,
  initial_capital: 100000,
  fee_enabled: true,
  exclude_st: true,
  boards: [] as string[],
  orderMode: 'hands' as 'hands' | 'amount',
  handsPresetStr: '1,10,20',
  amountWanPresetStr: '1,10,20',
  charts: createDefaultStockChartPreferences(),
})
// 主区只操作本次训练会话；cfg 仅承载设置抽屉里的长期默认，主区不反写。
const sessionConfig = reactive({
  mode: cfg.mode,
  range_start: cfg.range_start,
  range_end: cfg.range_end,
  boards: [...cfg.boards],
  orderMode: cfg.orderMode,
})
watch(
  () => [cfg.mode, cfg.range_start, cfg.range_end, cfg.boards, cfg.orderMode] as const,
  () => {
    sessionConfig.mode = cfg.mode
    sessionConfig.range_start = cfg.range_start
    sessionConfig.range_end = cfg.range_end
    sessionConfig.boards = [...cfg.boards]
    sessionConfig.orderMode = cfg.orderMode
  },
  { deep: true },
)
const chartSettings = computed({
  get: () => cfg.charts,
  set: (value: StockChartPreferences) => {
    cfg.charts = value
  },
})
const chartPreferences = useStockChartPreferences(chartSettings, hydrated)
function setAuxiliaryChart(slot: AuxiliaryChartSlot, value: string | number | boolean): void {
  chartPreferences.setSlotType(slot, value)
}
function handleRatioDraft(ratios: number[]): void {
  chartPreferences.updateRatioDraft(ratios)
}
function handleRatioCommit(ratios: number[]): void {
  chartPreferences.updateRatioDraft(ratios)
  chartPreferences.commitRatioDraft()
}
const settingsOpen = ref(false)

// 布局声明统一取自 pageRegistry（单一事实源），不再页面内联手写 PageLayout。
const trainingLayout = getPageLayout('training')
const {
  effective: trainingEffective,
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
} = useRemoteLayoutConfig(trainingLayout)

// 抽屉「布局 / 组件设置」由 PageSettingsDrawer 自动渲染；历史表与训练图表字段按 registry 自动继承。
const drawerConfig = { knobs: layoutKnobs, valueOf, sourceOf, setKnob, componentValueOf, setComponentKnob, componentSourceOf, layerValuesOf, componentLayerValuesOf, componentAllowedLayers }

// 三阶段共用同一布局：body 槽统一走默认成长区（grow 策略）。
// grow 容器是视口高 + overflow:auto——余量足够时由收尾块（历史表/成交明细/复盘卡）吃满剩余高度，
// 余量不足时整个主内容区滚动兜底，无需按阶段区分滚动归属（DESIGN §5.4）。
const mainLayout = computed<PageLayout>(() => trainingEffective.value)

const {
  pageSize: historyPageSize,
  changePageSize: changeHistoryPageSize,
} = useComponentPageSizeSession({
  resolveDefault: () => componentValueOf('history', 'pageSize'),
  resetPage: () => {
    history.page = 1
  },
  reload: loadHistory,
})

// 训练台/结算 K 线工作区高度：与个股详情一致，来自组件配置层（chart.minHeight）。
const chartDefaultHeight = Number(
  trainingLayout.slots.find((slot) => slot.id === 'chart')?.config?.minHeight,
)
const configuredChartHeight = computed(() => {
  return resolveComponentNumberValue(
    'chart',
    'minHeight',
    componentValueOf('chart', 'minHeight'),
    chartDefaultHeight,
  )
})

// K 线显示范围：选项与默认值来自全局偏好（抽屉里可配，跨页同步）；
// 单向：主区切换只进会话态，不写回全局默认范围。
const { validDefault: klineDefault } = useKlinePrefs()
const viewDays = ref(klineDefault.value)

// 预设解析
function parseList(s: string): number[] {
  return (s || '').split(/[,，\s]+/).map(Number).filter((n) => n > 0 && Number.isFinite(n))
}
const handsPresets = computed(() => parseList(cfg.handsPresetStr))
const amountPresets = computed(() => parseList(cfg.amountWanPresetStr).map((w) => w * 10000))

// ── 历史 & 成长 ──
const history = reactive({ list: [] as SessionRow[], total: 0, page: 1, sort_by: 'created_at', sort_order: 'desc' })
const historyError = ref('')
const HISTORY_SORT_FIELDS = ['created_at', 'completed_at', 'score', 'total_return', 'win_rate'] as const
const {
  sortBy: historySortBy,
  sortOrder: historySortOrder,
  elementDefaultSort: historyDefaultSort,
  onSortChange: onHistorySortChange,
} = useTableSort<(typeof HISTORY_SORT_FIELDS)[number]>({
  slotId: 'history',
  defaultSort: 'created_at:desc',
  componentValueOf,
  allowedFields: HISTORY_SORT_FIELDS,
  onChanged: () => {
    history.page = 1
    void loadHistory()
  },
})
function tableBorder(slotId: string): boolean {
  return componentValueOf(slotId, 'border') === true
}
const growthData = ref<GrowthPoint[]>([])
const growthError = ref('')
const historyLoading = ref(true)
const growthLoading = ref(true)

async function loadHistory() {
  historyLoading.value = true
  history.sort_by = historySortBy.value
  history.sort_order = historySortOrder.value
  historyError.value = ''
  try {
    const r = await listSessions({
      page: history.page,
      size: historyPageSize.value,
      sort_by: historySortBy.value,
      sort_order: historySortOrder.value,
    })
    history.list = r.list
    history.total = r.total
  } catch (error) {
    historyError.value = getErrorMessage(error, '训练历史加载失败')
  } finally {
    historyLoading.value = false
  }
}
async function loadGrowth() {
  growthLoading.value = true
  growthError.value = ''
  try {
    growthData.value = await fetchGrowth()
  } catch (error) {
    growthError.value = getErrorMessage(error, '成长曲线加载失败')
  } finally {
    growthLoading.value = false
  }
}

// ── 下单面板 ──
const order = reactive({ qty: 1, reason: '' })
const round = computed(() => view.value?.round)
const isLast = computed(() => !!round.value?.is_last_day)
const feeOn = computed(() => !!view.value?.fee_enabled)
const isAmount = computed(() => sessionConfig.orderMode === 'amount')

const pricePerHand = computed(() => (round.value ? round.value.cur_close * round.value.lot_size : 0))
// 买入总费率预判：滑点0.2%+佣金万2.5+过户≈0.226%，取略保守 0.25% 估「全仓上限」，
// 保证前端估出的手数后端按收盘价精确成交时必定买得起（买入 T+0 即时成交，无缩手数兜底）。
const buyRate = computed(() => (feeOn.value ? 0.0025 : 0))
const perHandCost = computed(() => pricePerHand.value * (1 + buyRate.value))
const cash = computed(() => round.value?.cash ?? 0)
const posHands = computed(() => round.value?.pos_hands ?? 0)
const posValue = computed(() => posHands.value * pricePerHand.value)

// 限制：可买上限（手）、全仓/半仓
const maxBuyHands = computed(() => (perHandCost.value > 0 ? Math.floor(cash.value / perHandCost.value) : 0))
const halfBuyHands = computed(() => Math.floor(maxBuyHands.value / 2))
const halfPosHands = computed(() => Math.floor(posHands.value / 2))

// 输入框限制（点 1：手数≤可买/持仓上限；金额≤可用资金/持仓市值）
const inputMin = computed(() => 0)
const inputMax = computed(() => isAmount.value
  ? Math.max(1, Math.round(Math.max(cash.value, posValue.value)))
  : Math.max(1, maxBuyHands.value, posHands.value))
const inputStep = computed(() => (isAmount.value ? 10000 : 1))

// 输入值 → 手数（金额模式按当前价折算）
function qtyToHands(qty: number): number {
  if (!isAmount.value) return Math.max(0, Math.floor(qty))
  return perHandCost.value > 0 ? Math.floor(qty / perHandCost.value) : 0
}
const orderHands = computed(() => qtyToHands(order.qty))
const estCost = computed(() => orderHands.value * perHandCost.value)

// 预设值 → 手数（手数模式 p=手；金额模式 p=元）
function presetHands(p: number): number {
  return isAmount.value ? (perHandCost.value > 0 ? Math.floor(p / perHandCost.value) : 0) : Math.floor(p)
}
const activePresets = computed(() => (isAmount.value ? amountPresets.value : handsPresets.value))
function presetLabel(p: number): string {
  return isAmount.value ? `${formatMoney(p, { digits: 0 })} 元` : `${p}手`
}
function buyPresetDisabled(p: number): boolean { const h = presetHands(p); return h < 1 || h > maxBuyHands.value }

// 一键填入输入框（点 4：点高亮数字即填满仓位）
function fillBuyMax() { order.qty = isAmount.value ? Math.round(cash.value) : maxBuyHands.value }
// 切换下单方式时复位输入量，避免“手数/金额”量纲串味（如 10 万元被当成 10 万手）
watch(() => sessionConfig.orderMode, () => { order.qty = isAmount.value ? 0 : 1 })

async function start() {
  loading.value = true
  try {
    const filters: Record<string, unknown> = { exclude_st: cfg.exclude_st }
    if (sessionConfig.boards.length) filters.boards = [...sessionConfig.boards]
    view.value = await startSession({
      mode: sessionConfig.mode, range_start: sessionConfig.range_start, range_end: sessionConfig.range_end,
      n_rounds: cfg.n_rounds, window_days: cfg.window_days,
      initial_capital: cfg.initial_capital, fee_enabled: cfg.fee_enabled, filters,
    })
  } catch (e) {
    ElMessage.error((e as Error).message || '开局失败')
  } finally {
    loading.value = false
  }
}

async function placeBuy(hands: number) {
  const h = Math.min(Math.floor(hands), maxBuyHands.value)
  if (h < 1) { ElMessage.warning('可用资金不足以买入 1 手'); return }
  view.value = await placeTrade(view.value!.id, 'buy', h, order.reason)
  order.reason = ''
}
async function placeSell(hands: number) {
  const h = Math.min(Math.floor(hands), posHands.value)
  if (h < 1) { ElMessage.warning('当前无持仓可卖'); return }
  view.value = await placeTrade(view.value!.id, 'sell', h, order.reason)
  order.reason = ''
}
// 自定义量（输入框）
const doBuy = () => placeBuy(orderHands.value)
const doSell = () => placeSell(qtyToHands(order.qty))
// 快捷买入：全仓 / 半仓 / 预设
const buyAll = () => placeBuy(maxBuyHands.value)
const buyHalf = () => placeBuy(halfBuyHands.value)
const buyPreset = (p: number) => placeBuy(presetHands(p))
// 快捷卖出：全部 / 半仓 / 预设
const sellAll = () => placeSell(posHands.value)
const sellHalf = () => placeSell(halfPosHands.value)
const sellPreset = (p: number) => placeSell(presetHands(p))
async function doCancel() { view.value = await cancelIntent(view.value!.id) }
async function nextDay() {
  const r = await revealNext(view.value!.id, round.value?.cursor_idx ?? null)
  view.value = r
  if (r.fill_msg) ElMessage.warning(r.fill_msg)
}
async function finishRound() {
  view.value = await settleRound(view.value!.id) as RunningView & DetailView
  if (view.value.status === 'completed') await Promise.all([loadHistory(), loadGrowth()])
}
async function backToConfig() {
  view.value = null
  await Promise.all([loadHistory(), loadGrowth()])
}
async function openSession(id: string) { view.value = await getSession(id) as RunningView & DetailView }
async function removeSession(id: string) {
  try { await ElMessageBox.confirm('确认删除该训练记录？', '提示', { type: 'warning' }) } catch { return }
  await deleteSession(id)
  await Promise.all([loadHistory(), loadGrowth()])
}

function sessionRowActions(row: SessionRow): AppRowAction[] {
  return [
    {
      key: 'delete',
      label: '删除',
      type: 'danger',
      permission: 'training:delete',
      onClick: () => removeSession(row.id),
    },
  ]
}

// ── 复盘笔记 ──
const reviewNote = ref('')
async function persistReview() {
  if (!view.value) return
  await saveReview(view.value.id, reviewNote.value)
  ElMessage.success('复盘已保存')
}

// ── K 线范围选择：切片控制可见范围，warmupBars 仅参与 MA 计算不渲染 ──
const allRoundBars = computed(() => round.value?.bars ?? [])
const displayBars = computed(() => {
  const bs = allRoundBars.value
  return viewDays.value >= 99999 ? bs : bs.slice(-viewDays.value)
})
const warmupBars = computed(() => {
  const bs = allRoundBars.value
  return viewDays.value >= 99999 ? [] : bs.slice(0, -viewDays.value || undefined)
})
// 训练 MACD 由后端在 bars 内附带（防作弊不调 indicators 接口）；按 date 对齐成 IndicatorRow 供工作区消费。
function barsToIndicatorRows(bs: readonly Bar[]): IndicatorRow[] {
  return bs
    .filter((bar) => bar.macd_diff != null || bar.macd_dea != null || bar.macd_hist != null)
    .map((bar) => ({
      trade_date: bar.date,
      macd_diff: bar.macd_diff ?? null,
      macd_dea: bar.macd_dea ?? null,
      macd_hist: bar.macd_hist ?? null,
      macd_golden_cross: bar.macd_golden_cross ?? null,
      macd_dead_cross: bar.macd_dead_cross ?? null,
    }))
}
const indicatorRows = computed(() => barsToIndicatorRows(allRoundBars.value))

// ── 结算详情 ──
const detail = computed(() => view.value as unknown as DetailView | null)
function roundEquityPoints(rd: DetailRound, initCap: number) {
  const len = rd.equity_curve.length
  const winBars = len ? rd.bars.slice(-len) : []
  const firstOpen = winBars.length ? winBars[0].open : 0
  let peak = -Infinity
  return rd.equity_curve.map((eq, i) => {
    peak = Math.max(peak, eq)
    const bClose = winBars[i] ? winBars[i].close : firstOpen
    return {
      trade_date: winBars[i] ? winBars[i].date : `D${i}`,
      equity: eq, cash: 0, position_value: 0, n_positions: 0,
      benchmark_equity: firstOpen ? +(initCap * (bClose / firstOpen)).toFixed(2) : eq,
      drawdown: peak > 0 ? +(eq / peak - 1).toFixed(4) : 0,
    }
  })
}

// ── 格式化 ──
const pct = (v: number | null | undefined) => v == null ? '--' : (v >= 0 ? '+' : '') + (v * 100).toFixed(2) + '%'
const modeText = (m: string) => m === 'single' ? '单股' : '多股'
const gradePalette = useStatusColorPalette()
// 评级色统一消费语义色板：S=警示金、A=成功绿、B=主色蓝、C=中性灰、D=危险红。
const gradeColor = (g: string | null) => ({
  S: gradePalette.value.warning,
  A: gradePalette.value.success,
  B: gradePalette.value.primary,
  C: gradePalette.value.muted,
  D: gradePalette.value.danger,
} as Record<string, string>)[g || ''] || gradePalette.value.muted
// 评级阈值与后端 _grade_of 的 GRADE_BANDS 逐字对齐（D 为其余，即 <60）。
const gradeBands = [
  { g: 'S', text: 'S ≥ 90', thr: 90 },
  { g: 'A', text: 'A ≥ 80', thr: 80 },
  { g: 'B', text: 'B ≥ 70', thr: 70 },
  { g: 'C', text: 'C ≥ 60', thr: 60 },
  { g: 'D', text: 'D < 60', thr: 0 },
]

// ── 键盘快捷键 ──
function onKey(e: KeyboardEvent) {
  if (phase.value !== 'running') return
  const tag = (e.target as HTMLElement)?.tagName
  if (tag === 'INPUT' || tag === 'TEXTAREA') return
  if (e.key === 'ArrowRight') { isLast.value ? finishRound() : nextDay() }
  else if (e.key.toLowerCase() === 'b' && !isLast.value) doBuy()
  else if (e.key.toLowerCase() === 's' && (round.value?.pos_hands ?? 0) > 0) doSell()
}

let keyListening = false
function attachKeyboard() {
  if (keyListening) return
  window.addEventListener('keydown', onKey)
  keyListening = true
}
function detachKeyboard() {
  if (!keyListening) return
  window.removeEventListener('keydown', onKey)
  keyListening = false
}

onMounted(async () => {
  attachKeyboard()
  await Promise.all([loadHistory(), loadGrowth()])
})
onActivated(attachKeyboard)
onDeactivated(detachKeyboard)
onBeforeUnmount(detachKeyboard)
</script>

<template>
  <!-- ══════════ 阶段一：未开局（配置 + 历史主表 + 成长）══════════ -->
  <LayoutHost v-if="phase === 'config'" :layout="mainLayout">
    <template #action>
    <div class="page-head">
        <div>
          <h2 class="app-page-title page-title-row">
            盘感训练
            <HelpTip title="盘感训练是什么？" :width="440">
              <HelpTipItem question="训练如何进行">
                <ul>
                  <li>系统在指定历史区间内随机抽取个股和起点，隐藏股名、代码与真实日期，逐日揭示 K 线，由你负责买卖。</li>
                </ul>
              </HelpTipItem>
              <HelpTipItem question="买卖如何成交">
                <ul>
                  <li>买入当日按收盘价成交（T+0），卖出次日按开盘价成交（T+1）；同时执行涨跌停不可成交、停牌顺延等真实约束，并可选择计入交易成本。</li>
                </ul>
              </HelpTipItem>
              <HelpTipItem question="一局结束后得到什么">
                <ul>
                  <li>一局可训练单只或多只股票；结束后揭晓身份，给出收益、胜率、回撤与综合评级，并沉淀到训练历史和成长曲线。</li>
                </ul>
              </HelpTipItem>
            </HelpTip>
          </h2>
          <p class="page-subtitle">盲测 · 逐日揭示 · 买 T+0 / 卖 T+1 · 回溯思路与成长</p>
        </div>
        <PageSettingsTrigger :dirty="isDirty" @click="settingsOpen = true" />
      </div>
    </template>

    <template #main>
    <div class="cfg-body">
        <el-card shadow="never" class="cfg-card">
          <div class="cfg-grid">
            <div class="cfg-item">
              <label>训练模式</label>
              <PageSegmented
                v-model="sessionConfig.mode"
                tone="primary"
                aria-label="训练模式"
                :options="[
                  { label: '单只随机', value: 'single' },
                  { label: '多只一轮', value: 'multi' },
                ]"
              />
            </div>
            <div class="cfg-item wide">
              <label>随机交易日范围</label>
              <div class="range">
                <TradeDatePicker v-model="sessionConfig.range_start" placeholder="开始日" clearable />
                <span>至</span>
                <TradeDatePicker v-model="sessionConfig.range_end" placeholder="结束日" clearable />
                <span class="hint">留空 = 全部历史</span>
              </div>
            </div>
            <div class="cfg-item">
              <label>板块</label>
              <el-select v-model="sessionConfig.boards" placeholder="不限（全部板块）" multiple clearable
                         collapse-tags collapse-tags-tooltip :max-collapse-tags="2" style="width:220px">
                <el-option label="主板" value="主板" />
                <el-option label="创业板" value="创业板" />
                <el-option label="科创板" value="科创板" />
              </el-select>
            </div>
          </div>
          <div class="cfg-actions">
            <el-button v-permission="'training:start'" type="primary" size="large" :loading="loading" @click="start">开始训练</el-button>
            <span class="cfg-hint">回合数、连续交易日、初始资金等默认值可在右上角
              <b class="hl" @click="settingsOpen = true">设置</b> 中调整</span>
          </div>
        </el-card>

        <el-card v-if="growthLoading || growthData.length || growthError" shadow="never" class="growth-card">
          <template #header>
            <span class="card-title">成长曲线</span><span class="card-sub">历次评分 / 收益</span>
            <HelpTip title="成长曲线是什么？" :width="380">
              <HelpTipItem question="坐标表示什么">
                <ul>
                  <li>横轴为完成局序，纵轴左侧为历次综合评分（0~100），右侧为整局收益。</li>
                </ul>
              </HelpTipItem>
              <HelpTipItem question="曲线如何解读">
                <ul>
                  <li>用于观察盘感是否稳定进步；评分趋势向上说明买卖时机与纪律在改善，收益为负时会绘制在 0 下方。每次结算一局后自动沉淀一个点。</li>
                </ul>
              </HelpTipItem>
            </HelpTip>
          </template>
          <AppStateBlock
            v-if="growthLoading && !growthData.length"
            state="loading"
            title="正在加载成长曲线…"
          />
          <AppStateBlock
            v-else-if="growthError"
            state="error"
            :title="growthData.length ? '成长曲线刷新失败' : '成长曲线加载失败'"
            :description="growthError"
            retry
            @retry="loadGrowth"
          />
          <div v-else v-loading="growthLoading">
            <GrowthChart :data="growthData" />
          </div>
        </el-card>

        <el-card shadow="never" class="hist-card">
          <template #header><span class="card-title">训练历史</span><span class="card-sub">共 {{ history.total }} 局，点行回看</span></template>
          <AppStateBlock
            v-if="historyLoading && !history.list.length"
            state="loading"
            title="正在加载训练历史…"
          />
          <AppStateBlock
            v-else-if="historyError"
            state="error"
            :title="history.list.length ? '训练历史刷新失败' : '训练历史加载失败'"
            :description="historyError"
            retry
            @retry="loadHistory"
          />
          <AppDataTable
            v-else
            :data="history.list"
            :loading="historyLoading"
            size="small"
            table-class="hist-table"
            :border="tableBorder('history')"
            clickable
            :default-sort="historyDefaultSort"
            :pagination="{ currentPage: history.page, pageSize: historyPageSize, total: history.total, pageSizes: PAGE_SIZE_OPTIONS, small: true }"
            @sort-change="onHistorySortChange"
            @page-change="(p: number) => { history.page = p; loadHistory() }"
            @size-change="changeHistoryPageSize"
            @row-click="(r:SessionRow)=>openSession(r.id)">
            <AppTableColumn label="模式">
              <template #default="{ row }">{{ modeText(row.mode) }}·{{ row.n_rounds }}</template>
            </AppTableColumn>
            <AppTableColumn label="评级">
              <template #default="{ row }">
                <span v-if="row.grade" class="grade-chip" :style="{ background: gradeColor(row.grade) }">{{ row.grade }}</span>
                <span v-else class="muted">进行中</span>
              </template>
            </AppTableColumn>
            <AppTableColumn label="评分" prop="score" sortable="custom">
              <template #default="{ row }">{{ row.score != null ? row.score.toFixed(1) : '--' }}</template>
            </AppTableColumn>
            <AppTableColumn label="收益" prop="total_return" sortable="custom">
              <template #default="{ row }"><span :class="(row.total_return ?? 0) >= 0 ? 'up' : 'down'">{{ pct(row.total_return) }}</span></template>
            </AppTableColumn>
            <AppTableColumn label="胜率" prop="win_rate" sortable="custom">
              <template #default="{ row }">{{ row.win_rate != null ? (row.win_rate * 100).toFixed(0) + '%' : '--' }}</template>
            </AppTableColumn>
            <AppTableColumn label="开始时间" prop="created_at" sortable="custom">
              <template #default="{ row }">{{ row.created_at?.slice(0, 16) }}</template>
            </AppTableColumn>
            <AppTableColumn label="结束时间" prop="completed_at" sortable="custom">
              <template #default="{ row }">{{ row.completed_at?.slice(0, 16) ?? '--' }}</template>
            </AppTableColumn>
            <AppTableColumn label="操作" role="action-compact">
              <template #default="{ row }">
                <AppRowActions :actions="sessionRowActions(row)" :inline-limit="1" />
              </template>
            </AppTableColumn>
          </AppDataTable>
        </el-card>
    </div>
    </template>
  </LayoutHost>

  <!-- ══════════ 阶段二：训练中（混合成长区）══════════ -->
  <LayoutHost v-else-if="phase === 'running' && round" :layout="mainLayout">
    <template #action>
    <div class="page-head">
        <div>
          <h2 class="app-page-title title-row">
            盘感训练 · 进行中
            <HelpTip title="训练规则" :width="380">
              <HelpTipItem question="盲测隐藏什么">
                <ul>
                  <li>隐藏个股身份与真实日期，横轴使用相对日（D±n）。</li>
                </ul>
              </HelpTipItem>
              <HelpTipItem question="买卖何时成交">
                <ul>
                  <li>买入当日按收盘价即时成交，收盘封涨停时不可买入；卖出登记后于次日开盘成交，开盘跌停时不可卖出，停牌时顺延。窗口末日仍持仓则按收盘价强制清算。</li>
                </ul>
              </HelpTipItem>
            </HelpTip>
          </h2>
          <p class="page-subtitle app-inline-info">
            <span>回合 {{ view!.cur_round + 1 }}/{{ view!.n_rounds }} · 第 {{ round.cursor_idx + 1 }}/{{ round.window_days }} 个交易日 · 盲测中</span>
            <el-tag v-if="round.board" size="small" effect="plain">{{ round.board }}</el-tag>
          </p>
        </div>
        <div class="page-head-actions">
          <div class="ops">
            <KlineRangeSelect v-model="viewDays" />
          </div>
          <el-button @click="backToConfig">退出训练</el-button>
          <PageSettingsTrigger :dirty="isDirty" @click="settingsOpen = true" />
        </div>
      </div>
    </template>

    <template #main>
    <div class="run-body">
        <div class="chart-block">
          <StockChartWorkspace
            :data-configured-height="configuredChartHeight"
            :style="{ flexBasis: `${configuredChartHeight}px` }"
            :bars="displayBars"
            :warmup-bars="warmupBars"
            :indicators="indicatorRows"
            :markers="round.markers"
            :slot2="chartPreferences.preferences.value.slot2"
            :slot3="chartPreferences.preferences.value.slot3"
            :height-ratios="chartPreferences.currentRatios.value"
            :zoom-start="0"
            :zoom-end="100"
            :min-height="configuredChartHeight"
            :aria-label="'训练 K 线（盲测）工作区'"
            @ratio-draft="handleRatioDraft"
            @ratio-commit="handleRatioCommit"
          />
        </div>

        <div v-permission="'training:trade'" class="action-panel">
          <div class="acct">
            <div class="acct-item"><label>可用资金（可买上限）</label><b class="lim">{{ formatMoney(round.cash, { digits: 0, empty: '--' }) }}</b></div>
            <div class="acct-item"><label>持仓（可卖上限）</label><b class="lim">{{ round.pos_hands }} 手</b><span class="muted">@{{ formatMoney(round.pos_avg_price) }}</span></div>
            <div class="acct-item"><label>浮动盈亏</label><b :class="round.unrealized_pnl >= 0 ? 'up' : 'down'">{{ formatMoney(round.unrealized_pnl, { digits: 0, empty: '--' }) }}</b></div>
            <div class="acct-item"><label>总资产</label><b>{{ formatMoney(round.equity, { digits: 0, empty: '--' }) }}</b><span :class="(round.equity - view!.initial_capital) >= 0 ? 'up' : 'down'">{{ pct((round.equity - view!.initial_capital) / view!.initial_capital) }}</span></div>
            <div class="acct-item"><label>当前价</label><b>{{ formatMoney(round.cur_close) }}</b></div>
          </div>

          <div v-if="round.pending" class="pending">
            <span>待成交（次日开盘）：<b :class="round.pending.side === 'buy' ? 'up' : 'down'">{{ round.pending.side === 'buy' ? '买入' : '卖出' }} {{ round.pending.hands }} 手</b></span>
            <el-button link type="info" size="small" @click="doCancel">撤单</el-button>
          </div>

          <template v-if="!isLast">
            <div class="ops order-input">
              <PageSegmented v-model="sessionConfig.orderMode" tone="primary" size="small" aria-label="本轮下单方式" :options="[{ label: '按手数', value: 'hands' }, { label: '按金额', value: 'amount' }]" />
              <el-input-number
                v-model="order.qty"
                :min="inputMin"
                :max="inputMax"
                :step="inputStep"
                :formatter="isAmount ? formatMoneyInput : undefined"
                :parser="isAmount ? parseMoneyInput : undefined"
                controls-position="right"
                style="width:160px"
              />
              <span class="unit">{{ isAmount ? '元' : '手' }}</span>
              <span class="hint" v-if="!isAmount">
                约需 ¥{{ formatMoney(estCost, { digits: 0, empty: '--' }) }} · 最多可买
                <b class="hl" title="点击填入全仓" @click="fillBuyMax">{{ maxBuyHands }}</b> 手
              </span>
              <span class="hint" v-else>
                可用资金 <b class="hl" title="点击全额填入" @click="fillBuyMax">¥{{ formatMoney(cash, { digits: 0, empty: '--' }) }}</b> · 本单 ≈ {{ orderHands }} 手
              </span>
            </div>

            <div class="trade-row">
              <span class="side-tag buy">买入</span>
              <el-button size="small" type="danger" plain :disabled="maxBuyHands < 1" @click="buyAll">全仓</el-button>
              <el-button size="small" type="danger" plain :disabled="halfBuyHands < 1" @click="buyHalf">半仓</el-button>
              <el-button v-for="p in activePresets" :key="'b' + p" size="small" plain :disabled="buyPresetDisabled(p)" @click="buyPreset(p)">{{ presetLabel(p) }}</el-button>
              <el-button type="danger" :disabled="orderHands < 1" @click="doBuy">买入当前量 (B)</el-button>
            </div>

            <div class="trade-row" :class="{ disabled: posHands < 1 }">
              <span class="side-tag sell">卖出</span>
              <el-button size="small" type="success" plain :disabled="posHands < 1" @click="sellAll">全部</el-button>
              <el-button size="small" type="success" plain :disabled="halfPosHands < 1" @click="sellHalf">半仓</el-button>
              <el-button v-for="p in activePresets" :key="'s' + p" size="small" plain :disabled="posHands < 1" @click="sellPreset(p)">{{ presetLabel(p) }}</el-button>
              <el-button type="success" :disabled="posHands < 1" @click="doSell">卖出当前量 (S)</el-button>
            </div>

            <div class="ops">
              <el-input v-model="order.reason" placeholder="操作理由（选填，记录买卖思路）" size="default" style="width:280px" />
              <el-button type="primary" plain @click="nextDay">
                下一交易日
                <el-icon class="el-icon--right"><ArrowRight /></el-icon>
              </el-button>
            </div>
          </template>
          <div class="ops" v-else>
            <span class="last-tip">已到窗口末日，结算后揭晓个股身份与得分</span>
            <el-button type="warning" @click="finishRound">结算本回合</el-button>
          </div>
        </div>

        <el-card class="trades-card" shadow="never">
          <AppDataTable :data="round.trades" height="100%" size="small" empty-text="尚无成交">
            <AppTableColumn label="相对日"><template #default="{ row }">D{{ row.rel_day }}</template></AppTableColumn>
            <AppTableColumn label="方向"><template #default="{ row }"><span :class="row.side === 'buy' ? 'up' : 'down'">{{ row.side === 'buy' ? '买入' : '卖出' }}</span></template></AppTableColumn>
            <AppTableColumn label="成交价"><template #default="{ row }">{{ formatMoney(row.price) }}</template></AppTableColumn>
            <AppTableColumn label="手数"><template #default="{ row }">{{ row.hands }}</template></AppTableColumn>
            <AppTableColumn label="盈亏"><template #default="{ row }"><span v-if="row.pnl != null" :class="row.pnl >= 0 ? 'up' : 'down'">{{ formatMoney(row.pnl, { digits: 0, empty: '--' }) }}</span><span v-else class="muted">—</span></template></AppTableColumn>
            <AppTableColumn label="收益率"><template #default="{ row }"><span v-if="row.return_pct != null" :class="row.return_pct >= 0 ? 'up' : 'down'">{{ pct(row.return_pct) }}</span><span v-else class="muted">—</span></template></AppTableColumn>
            <AppTableColumn label="理由"><template #default="{ row }">{{ row.reason || (row.auto_close ? '到期清算' : '') }}</template></AppTableColumn>
          </AppDataTable>
        </el-card>
    </div>
    </template>
  </LayoutHost>

  <!-- ══════════ 阶段三：结算回看 ══════════ -->
  <LayoutHost v-else-if="phase === 'result' && detail" :layout="mainLayout">
    <template #action>
    <div class="page-head">
        <div>
          <h2 class="app-page-title title-row">
            训练结算
            <span class="grade-big app-data-emphasis" :style="{ color: gradeColor(detail.grade) }">{{ detail.grade }}</span>
            <span class="score-tip">综合评分 {{ detail.score?.toFixed(1) }}</span>
          </h2>
          <p class="page-subtitle">{{ modeText(detail.mode) }} · {{ detail.n_rounds }} 回合 · {{ detail.created_at?.slice(0, 16) }}</p>
        </div>
        <div class="page-head-actions">
          <div class="ops">
            <KlineRangeSelect v-model="viewDays" />
          </div>
          <el-button @click="backToConfig">返回</el-button>
          <PageSettingsTrigger :dirty="isDirty" @click="settingsOpen = true" />
        </div>
      </div>
    </template>

    <template #main>
    <div class="result-body">
        <div class="kpi-row">
          <div class="kpi"><label>平均收益</label><b :class="(detail.total_return ?? 0) >= 0 ? 'up' : 'down'">{{ pct(detail.total_return) }}</b></div>
          <div class="kpi"><label>胜率</label><b>{{ detail.win_rate != null ? (detail.win_rate * 100).toFixed(0) + '%' : '--' }}</b></div>
          <div class="kpi"><label>最大回撤</label><b class="down">{{ pct(detail.max_drawdown) }}</b></div>
          <div class="kpi"><label>成交笔数</label><b>{{ detail.n_trades }}</b></div>
          <div class="kpi"><label>回合数</label><b>{{ detail.n_rounds }}</b></div>
        </div>

        <el-card shadow="never" class="score-rule-card">
          <template #header>
            <span class="card-title">评分规则</span>
            <HelpTip title="综合评分怎么算？" :width="420">
              <HelpTipItem question="综合评分如何加权">
                <ul>
                  <li>四项维度分数加权为 0~100 分：超额收益×40% + 绝对收益×25% + 回撤控制×20% + 胜率×15%。</li>
                </ul>
              </HelpTipItem>
              <HelpTipItem question="各维度如何计算">
                <ul>
                  <li>超额 =（总收益 − 同期满仓持有收益 + 10%）÷ 20%。</li>
                  <li>绝对 =（总收益 + 20%）÷ 40%。</li>
                  <li>回撤控制 =（最大回撤 + 25%）÷ 25%；以上三项均截断到 0~1。</li>
                  <li>胜率 = 盈利卖出笔数 ÷ 卖出总笔数。</li>
                </ul>
              </HelpTipItem>
              <HelpTipItem question="评级如何划分">
                <ul>
                  <li>S ≥ 90，A ≥ 80，B ≥ 70，C ≥ 60，其余为 D。</li>
                </ul>
              </HelpTipItem>
            </HelpTip>
          </template>
          <div class="score-rule-grid">
            <div class="rule-item"><span class="rule-key">综合评分</span><b class="rule-val">超额×40% + 绝对×25% + 回撤×20% + 胜率×15%</b></div>
            <div class="rule-item"><span class="rule-key">超额收益</span><span class="rule-val">(总收益 − 基准 + 10%) ÷ 20%，截断 0~1</span></div>
            <div class="rule-item"><span class="rule-key">绝对收益</span><span class="rule-val">(总收益 + 20%) ÷ 40%，截断 0~1</span></div>
            <div class="rule-item"><span class="rule-key">回撤控制</span><span class="rule-val">(最大回撤 + 25%) ÷ 25%，截断 0~1</span></div>
            <div class="rule-item"><span class="rule-key">胜率</span><span class="rule-val">盈利卖出笔 ÷ 卖出总笔</span></div>
            <div class="rule-item"><span class="rule-key">评级阈值</span><span class="rule-val"><span v-for="(item, i) in gradeBands" :key="item.g" :class="{ 'grade-dot': true, 'grade-dot--last': i === gradeBands.length - 1 }" :style="{ color: gradeColor(item.g) }">{{ item.text }}</span></span></div>
          </div>
        </el-card>

        <el-card v-for="rd in detail.rounds" :key="rd.seq" shadow="never" class="round-card">
          <template #header>
            <div class="round-head">
              <span class="rname app-inline-info"><span>回合 {{ rd.seq + 1 }} · {{ rd.name }} <span class="muted">{{ rd.code }}</span></span>
                <el-tag v-if="rd.board" size="small" effect="plain">{{ rd.board }}</el-tag>
              </span>
              <span class="muted">{{ rd.start_date }} ~ {{ rd.end_date }}</span>
              <span class="round-ret">你 <b :class="(rd.round_return ?? 0) >= 0 ? 'up' : 'down'">{{ pct(rd.round_return) }}</b> · 满仓持有 <b :class="(rd.benchmark_return ?? 0) >= 0 ? 'up' : 'down'">{{ pct(rd.benchmark_return) }}</b> · 回撤 <b class="down">{{ pct(rd.max_drawdown) }}</b></span>
            </div>
          </template>
          <div class="round-grid">
            <div class="round-chart"><StockChartWorkspace
              :data-configured-height="configuredChartHeight"
              :style="{ flexBasis: `${configuredChartHeight}px` }"
              :bars="viewDays >= 99999 ? rd.bars : rd.bars.slice(-viewDays)"
              :warmup-bars="viewDays >= 99999 ? [] : rd.bars.slice(0, -viewDays || undefined)"
              :indicators="barsToIndicatorRows(rd.bars)"
              :markers="rd.markers"
              :slot2="chartPreferences.preferences.value.slot2"
              :slot3="chartPreferences.preferences.value.slot3"
              :height-ratios="chartPreferences.currentRatios.value"
              :zoom-start="0"
              :zoom-end="100"
              :min-height="configuredChartHeight"
              :aria-label="'结算回看 K 线工作区'"
              @ratio-draft="handleRatioDraft"
              @ratio-commit="handleRatioCommit"
            /></div>
            <div class="round-equity"><EquityChart :points="roundEquityPoints(rd, detail.initial_capital)" benchmark-code="满仓持有" fill /></div>
          </div>
          <AppDataTable :data="rd.trades" size="small" class="round-trades" empty-text="本回合无成交" embedded max-height="240">
            <AppTableColumn label="决策日"><template #default="{ row }">{{ row.decide_date }}</template></AppTableColumn>
            <AppTableColumn label="成交日"><template #default="{ row }">{{ row.fill_date }}</template></AppTableColumn>
            <AppTableColumn label="方向"><template #default="{ row }"><span :class="row.side === 'buy' ? 'up' : 'down'">{{ row.side === 'buy' ? '买入' : '卖出' }}</span></template></AppTableColumn>
            <AppTableColumn label="成交价"><template #default="{ row }">{{ formatMoney(row.price) }}</template></AppTableColumn>
            <AppTableColumn label="手数"><template #default="{ row }">{{ row.hands }}</template></AppTableColumn>
            <AppTableColumn label="盈亏"><template #default="{ row }"><span v-if="row.pnl != null" :class="row.pnl >= 0 ? 'up' : 'down'">{{ formatMoney(row.pnl, { digits: 0, empty: '--' }) }}</span><span v-else class="muted">—</span></template></AppTableColumn>
            <AppTableColumn label="收益率"><template #default="{ row }"><span v-if="row.return_pct != null" :class="row.return_pct >= 0 ? 'up' : 'down'">{{ pct(row.return_pct) }}</span><span v-else class="muted">—</span></template></AppTableColumn>
            <AppTableColumn label="理由"><template #default="{ row }">{{ row.reason || (row.auto_close ? '到期清算' : '') }}</template></AppTableColumn>
          </AppDataTable>
        </el-card>

        <el-card shadow="never" class="review-card">
          <template #header><span class="card-title">整局复盘</span></template>
          <el-input v-model="reviewNote" type="textarea" :rows="4" placeholder="记录本局思路、复盘总结、改进点……" />
          <div class="review-actions"><el-button v-permission="'training:review'" type="primary" @click="persistReview">保存复盘</el-button></div>
        </el-card>
    </div>
    </template>
  </LayoutHost>

  <!-- 设置抽屉：开局默认/选股范围/快捷下单三阶段共享；图表与 K 线属性仅在训练台/回看（有图）时展示。
       组件设置（图表区域高度等）通过 component-slot-ids 按阶段放行，config 阶段只留训练历史排序。 -->
  <PageSettingsDrawer
    v-model="settingsOpen"
    title="盘感训练"
    :dirty="isDirty || layoutDirty"
    page-key="training"
    :config="drawerConfig"
    :component-slot-ids="phase === 'config' ? ['history'] : ['chart']"
    @reset="reset(); chartPreferences.cancelRatioDraft(); resetLayout()"
  >
      <template #business>
      <PageSettingSection title="开局默认" desc="每次开局沿用的默认参数，开局前可临时改。">
        <div class="setting-item">
          <div class="setting-label">训练模式</div>
          <PageSegmented
            v-model="cfg.mode"
            aria-label="训练模式"
            :options="[
              { label: '单只随机', value: 'single' },
              { label: '多只一轮', value: 'multi' },
            ]"
          />
        </div>
        <div class="setting-item">
          <div class="setting-label">板块</div>
          <el-select v-model="cfg.boards" placeholder="不限（全部板块）" multiple clearable
                     collapse-tags collapse-tags-tooltip :max-collapse-tags="2" style="width:220px">
            <el-option label="主板" value="主板" />
            <el-option label="创业板" value="创业板" />
            <el-option label="科创板" value="科创板" />
          </el-select>
        </div>
        <div v-if="cfg.mode === 'multi'" class="setting-item">
          <div class="setting-label">回合数（只）</div>
          <el-input-number v-model="cfg.n_rounds" :min="1" :max="20" size="small" style="width:140px" />
        </div>
        <div class="setting-item">
          <div class="setting-label">每回合连续交易日</div>
          <el-input-number v-model="cfg.window_days" :min="5" :max="60" size="small" style="width:140px" />
        </div>
        <div class="setting-item">
          <div class="setting-label">初始资金（元）</div>
          <el-input-number
            v-model="cfg.initial_capital"
            :min="10000"
            :step="10000"
            :formatter="formatMoneyInput"
            :parser="parseMoneyInput"
            size="small"
            style="width:160px"
          />
        </div>
      </PageSettingSection>
      <template v-if="phase !== 'config'">
        <KlineSettingSection />
        <StockChartSettingSection
          :slot2="chartPreferences.preferences.value.slot2"
          :slot3="chartPreferences.preferences.value.slot3"
            :chart-types="chartPreferences.visibleTypes.value"
            :default-ratios="chartPreferences.defaultRatios.value"
            :current-ratios="chartPreferences.currentRatios.value"
          test-id-prefix="training-chart"
          @change="setAuxiliaryChart"
            @save-default-ratios="chartPreferences.setDefaultHeightRatios"
        />
      </template>
      <PageSettingSection title="选股范围" desc="控制随机选股时的股票池过滤条件。">
        <div class="setting-item">
          <div class="setting-label">排除 ST</div>
          <el-switch v-model="cfg.exclude_st" />
        </div>
        <div class="setting-item">
          <div class="setting-label">
            计入交易成本
            <HelpTip title="交易成本" :width="280">
              <HelpTipItem question="关闭后如何计算">
                <ul>
                  <li>按“零摩擦”计算，不计佣金、印花税、过户费和滑点，用于专注训练买卖时机。</li>
                </ul>
              </HelpTipItem>
            </HelpTip>
          </div>
          <el-switch v-model="cfg.fee_enabled" />
        </div>
      </PageSettingSection>
      <PageSettingSection title="快捷下单" desc="配置下单方式与一键预设，训练时直接点选快速买卖。">
        <div class="setting-item">
          <div class="setting-label">默认下单方式</div>
          <PageSegmented v-model="cfg.orderMode" aria-label="默认下单方式" :options="[{ label: '按手数', value: 'hands' }, { label: '按金额', value: 'amount' }]" />
        </div>
        <div class="setting-item col">
          <div class="setting-label">手数预设（逗号分隔）</div>
          <el-input v-model="cfg.handsPresetStr" placeholder="1,10,20" />
        </div>
        <div class="setting-item col">
          <div class="setting-label">金额预设（万，逗号分隔）</div>
          <el-input v-model="cfg.amountWanPresetStr" placeholder="1,10,20" />
        </div>
      </PageSettingSection>
      </template>
    </PageSettingsDrawer>
</template>

<style scoped>
.training { gap: var(--app-space-2); }
.page-head { display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: var(--app-space-2); }
.page-head .title-row { margin: 0; display: flex; align-items: center; gap: var(--app-space-control-gap); }
.page-title-row { display: flex; align-items: center; }
.page-head .grade-big { font-size: var(--app-font-size-kpi-lg); font-weight: var(--app-font-weight-strong); margin-left: 4px; }
.page-head .score-tip { font-size: var(--app-font-size-body); color: var(--el-text-color-secondary); margin-left: 6px; }
.page-head-actions { display: flex; align-items: center; gap: var(--app-space-2); }

/* 配置：固定块 + 历史主表 → 混合成长区 */
.cfg-body { flex: 1 1 auto; min-height: 0; display: flex; flex-direction: column; gap: var(--app-space-3); overflow: auto; padding-right: 2px; }
.cfg-card, .growth-card { flex: 0 0 auto; }
.cfg-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: var(--app-space-4); }
.cfg-item { display: flex; flex-direction: column; gap: var(--app-space-control-gap); }
.cfg-item.wide { grid-column: span 2; }
.cfg-item label { font-size: var(--app-font-size-table); color: var(--el-text-color-secondary); }
.cfg-item .lbl-tip { display: flex; align-items: center; }
.cfg-item .range { display: flex; align-items: center; gap: var(--app-space-2); flex-wrap: wrap; }
.cfg-item .hint { font-size: var(--app-font-size-caption); color: var(--el-text-color-placeholder); }
.cfg-actions { margin-top: 18px; text-align: center; display: flex; flex-direction: column; align-items: center; gap: var(--app-space-2); }
.cfg-hint { font-size: var(--app-font-size-caption); color: var(--el-text-color-secondary); }
.cfg-hint .hl { cursor: pointer; }
.card-title { font-weight: var(--app-font-weight-section); }
.card-sub { color: var(--el-text-color-secondary); font-size: var(--app-font-size-caption); margin-left: 8px; }
.hist-card { flex: 1 1 auto; min-height: 300px; display: flex; flex-direction: column; }
.hist-card :deep(.el-card__body) { flex: 1; min-height: 0; display: flex; flex-direction: column; padding: 8px 12px; }
.hist-table { cursor: pointer; flex: 1; }
.grade-chip { color: #fff; padding: 1px 8px; border-radius: 10px; font-weight: var(--app-font-weight-strong); font-size: var(--app-font-size-caption); }
.setting-item { display: flex; align-items: center; justify-content: space-between; gap: var(--app-space-3); padding: 6px 0; }
.setting-item.col { flex-direction: column; align-items: stretch; }
.setting-label { font-size: var(--app-font-size-table); color: var(--el-text-color-regular); }

/* 训练中：固定块（图+面板）+ 主表 → 混合成长区 */
.run-body { flex: 1 1 auto; min-height: 0; display: flex; flex-direction: column; gap: var(--app-space-2); overflow: auto; padding-right: 2px; }
.chart-block { flex: 0 0 auto; }
.action-panel { flex: 0 0 auto; background: var(--el-fill-color-light); border-radius: 8px; padding: 10px 14px; display: flex; flex-direction: column; gap: var(--app-space-2); }
.acct { display: flex; gap: var(--app-space-5); flex-wrap: wrap; }
.acct-item { display: flex; flex-direction: column; }
.acct-item label { font-size: var(--app-font-size-caption); color: var(--el-text-color-secondary); }
.acct-item b { font-size: var(--app-font-size-data); font-variant-numeric: tabular-nums; }
.acct-item b.lim { color: var(--el-color-primary); }
.acct-item .muted { font-size: var(--app-font-size-caption); }
.pending { display: flex; align-items: center; gap: var(--app-space-2); background: var(--el-color-warning-light-9); padding: 4px 10px; border-radius: 6px; font-size: var(--app-font-size-table); }
.ops { display: flex; align-items: center; gap: var(--app-space-2); flex-wrap: wrap; }
.ops .unit { color: var(--el-text-color-secondary); margin-left: -4px; }
.ops .hint { font-size: var(--app-font-size-caption); color: var(--el-text-color-secondary); font-variant-numeric: tabular-nums; }
.ops .last-tip { color: var(--el-color-warning); font-size: var(--app-font-size-table); }
/* 预判高亮数字（可点填入） */
.hl { color: var(--el-color-primary); font-weight: var(--app-font-weight-strong); font-size: var(--app-font-size-section-title); padding: 0 3px; border-radius: 4px; cursor: pointer; transition: background .15s; }
.hl:hover { background: var(--el-color-primary-light-9); text-decoration: underline; }
/* 买入/卖出快捷行 */
.trade-row { display: flex; align-items: center; gap: var(--app-space-2); flex-wrap: wrap; }
.trade-row.disabled { opacity: .55; }
.side-tag { font-size: var(--app-font-size-table); font-weight: var(--app-font-weight-strong); width: 40px; }
.side-tag.buy { color: var(--el-color-danger); }
.side-tag.sell { color: var(--el-color-success); }
.trades-card { flex: 1 1 auto; min-height: 160px; display: flex; flex-direction: column; }
.trades-card :deep(.el-card__body) { flex: 1; min-height: 0; padding: 8px; }

/* 结算：固定块（KPI/评分规则/回合卡）自然高，整局复盘卡吃满剩余高度；余量不足时整区滚动兜底 */
.result-body { flex: 1 1 auto; min-height: 0; overflow: auto; display: flex; flex-direction: column; gap: var(--app-space-3); padding-right: 2px; }
.kpi-row { display: flex; gap: var(--app-space-3); flex-wrap: wrap; }
.kpi { flex: 1 1 120px; background: var(--el-fill-color-light); border-radius: 8px; padding: 10px 14px; display: flex; flex-direction: column; gap: var(--app-space-1); }
.kpi label { font-size: var(--app-font-size-caption); color: var(--el-text-color-secondary); }
.kpi b { font-size: var(--app-font-size-page-title-sm); font-variant-numeric: tabular-nums; }
.score-rule-card { flex: 0 0 auto; }
.score-rule-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: var(--app-space-2) var(--app-space-4); }
.rule-item { display: flex; align-items: baseline; gap: var(--app-space-2); font-size: var(--app-font-size-table); }
.rule-key { flex: 0 0 auto; color: var(--el-text-color-secondary); }
.rule-val { color: var(--el-text-color-regular); font-variant-numeric: tabular-nums; }
.grade-dot { margin-right: var(--app-space-3); font-weight: var(--app-font-weight-strong); }
.grade-dot--last { margin-right: 0; }
.round-head { display: flex; align-items: baseline; gap: var(--app-space-4); flex-wrap: wrap; }
.round-head .rname { font-weight: var(--app-font-weight-section); }
.round-head .round-ret { margin-left: auto; font-size: var(--app-font-size-table); }
/* 回合卡：不被 result-body 压缩（flex-shrink:0），长内容由整页滚动承载；el-card 默认 overflow 需放行给子内容。 */
.round-card { flex: 0 0 auto; }
.round-card :deep(.el-card__body) { overflow: visible; }
.round-grid { display: grid; grid-template-columns: 1.4fr 1fr; gap: var(--app-space-3); }
.round-chart { min-width: 0; display: flex; flex-direction: column; }
.round-equity { min-width: 0; display: flex; flex-direction: column; }
/* 成交明细：长列表走内部滚动（上限 240px，AppDataTable max-height prop），避免撑爆整页；低于上限时随内容自适应高度。 */
.round-trades { margin-top: 10px; }
/* 整局复盘：收尾块吃富余空间（视口剩余 > 内容自然高时填满复盘卡，不再固定矮）；
   余量不足时靠 min-height 保住可用区，由 result-body 整区滚动兜底（DESIGN §5.4 阶梯）。 */
.review-card { flex: 1 1 auto; min-height: 200px; display: flex; flex-direction: column; }
.review-card :deep(.el-card__body) { flex: 1; min-height: 0; display: flex; flex-direction: column; }
.review-card :deep(.el-textarea) { flex: 1 1 auto; min-height: 96px; }
.review-card :deep(.el-textarea__inner) { height: 100%; resize: vertical; }
.review-actions { margin-top: 10px; text-align: right; flex: 0 0 auto; }

.up { color: var(--el-color-danger); }
.down { color: var(--el-color-success); }
@media (max-width: 1100px) { .round-grid { grid-template-columns: 1fr; } }
</style>
