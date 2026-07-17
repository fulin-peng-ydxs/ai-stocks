<script setup lang="ts">
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
import CandleChart from '@/components/CandleChart.vue'
import EquityChart from '@/components/EquityChart.vue'
import GrowthChart from '@/components/GrowthChart.vue'
import AppDataTable from '@/components/AppDataTable.vue'
import AppRowActions from '@/components/AppRowActions.vue'
import AppStateBlock from '@/components/AppStateBlock.vue'
import TradeDatePicker from '@/components/TradeDatePicker.vue'
import HelpTip from '@/components/HelpTip.vue'
import PageSegmented from '@/components/PageSegmented.vue'
import PageSettingSection from '@/components/PageSettingSection.vue'
import PageSettingsDrawer from '@/components/PageSettingsDrawer.vue'
import PageSettingsTrigger from '@/components/PageSettingsTrigger.vue'
import KlineRangeSelect from '@/components/KlineRangeSelect.vue'
import KlineSettingSection from '@/components/KlineSettingSection.vue'
import { usePageSettings } from '@/composables/usePageSettings'
import { useKlinePrefs } from '@/composables/useKlinePrefs'
import { useTableSort } from '@/composables/useTableSort'
import LayoutHost from '@/layout/components/LayoutHost.vue'
import { getPageLayout } from '@/layout'
import { useRemoteLayoutConfig } from '@/composables/useRemoteLayoutConfig'
import {
  startSession, getSession, listSessions, growth as fetchGrowth, revealNext,
  placeTrade, cancelIntent, settleRound, saveReview, deleteSession,
  type RunningView, type DetailView, type SessionRow, type GrowthPoint, type DetailRound,
} from '@/api/training'
import { getErrorMessage } from '@/utils/error'
import type { AppRowAction } from '@/components/rowActions'

// ── 页面阶段：config(未开局) / running(训练中) / result(结算回看) ──
const view = ref<(RunningView & Partial<DetailView>) | null>(null)
const loading = ref(false)
const phase = computed<'config' | 'running' | 'result'>(() => {
  if (!view.value) return 'config'
  return view.value.status === 'completed' ? 'result' : 'running'
})

// ── 页面设置（开局参数 + 快捷下单预设，均持久化）──
const { settings: cfg, isDirty, reset } = usePageSettings('training', {
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
})
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
  componentLayerValuesOf,
} = useRemoteLayoutConfig(trainingLayout)

// 抽屉「布局」段由 PageSettingsDrawer 按 config 自动渲染（本页无组件配置，仅布局段）。
const drawerConfig = { knobs: layoutKnobs, valueOf, sourceOf, setKnob, componentValueOf, setComponentKnob, componentSourceOf, layerValuesOf, componentLayerValuesOf }

// K 线显示范围：选项与默认值来自全局偏好（抽屉里可配，跨页同步）
const { validDefault: klineDefault } = useKlinePrefs()
const viewDays = ref(klineDefault.value)

// 预设解析
function parseList(s: string): number[] {
  return (s || '').split(/[,，\s]+/).map(Number).filter((n) => n > 0 && Number.isFinite(n))
}
const handsPresets = computed(() => parseList(cfg.handsPresetStr))
const amountPresets = computed(() => parseList(cfg.amountWanPresetStr).map((w) => w * 10000))

// ── 历史 & 成长 ──
const history = reactive({ list: [] as SessionRow[], total: 0, page: 1, size: 10, sort_by: 'created_at', sort_order: 'desc' })
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
  setComponentKnob,
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
      size: history.size,
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
const isAmount = computed(() => cfg.orderMode === 'amount')

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
function presetLabel(p: number): string { return isAmount.value ? `${p / 10000}万` : `${p}手` }
function buyPresetDisabled(p: number): boolean { const h = presetHands(p); return h < 1 || h > maxBuyHands.value }

// 一键填入输入框（点 4：点高亮数字即填满仓位）
function fillBuyMax() { order.qty = isAmount.value ? Math.round(cash.value) : maxBuyHands.value }
// 切换下单方式时复位输入量，避免“手数/金额”量纲串味（如 10 万元被当成 10 万手）
watch(() => cfg.orderMode, () => { order.qty = isAmount.value ? 0 : 1 })

async function start() {
  loading.value = true
  try {
    const filters: Record<string, unknown> = { exclude_st: cfg.exclude_st }
    if (cfg.boards.length) filters.boards = [...cfg.boards]
    view.value = await startSession({
      mode: cfg.mode, range_start: cfg.range_start, range_end: cfg.range_end,
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
const money = (v: number | null | undefined) => v == null ? '--' : Math.round(v).toLocaleString('zh-CN')
const modeText = (m: string) => m === 'single' ? '单股' : '多股'
const gradeColor = (g: string | null) => ({ S: '#e6a23c', A: '#67c23a', B: '#409eff', C: '#909399', D: '#f56c6c' } as Record<string, string>)[g || ''] || '#909399'

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
  <LayoutHost v-if="phase === 'config'" :layout="trainingEffective">
    <template #action>
    <div class="page-head">
        <div>
          <h2 class="title-row">
            🎮 盘感训练
            <HelpTip title="盘感训练是什么？" :width="440">
              <p><b>针对个股的买卖手感训练</b>：系统在你指定的历史区间里随机抽一只个股、随机一个起点，<b>盲测</b>（隐藏股名/代码/真实日期）下逐日揭示 K 线，你负责买卖。</p>
              <p style="margin:6px 0 2px"><b>买入当日按收盘价成交（T+0）</b>，<b>卖出次日开盘价成交（T+1）</b>；套用收盘/开盘涨跌停买不到、跌停卖不出、停牌顺延等真实约束；可选计入交易成本。</p>
              <p style="margin:6px 0 0">一局可练单只或多只（每只一个回合），结束后揭晓身份、给出收益/胜率/回撤与综合评级，并沉淀到训练历史与成长曲线。</p>
            </HelpTip>
          </h2>
          <span class="sub">盲测 · 逐日揭示 · 买 T+0 / 卖 T+1 · 回溯思路与成长</span>
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
              <el-radio-group v-model="cfg.mode">
                <el-radio-button value="single">单只随机</el-radio-button>
                <el-radio-button value="multi">多只一轮</el-radio-button>
              </el-radio-group>
            </div>
            <div class="cfg-item wide">
              <label>随机交易日范围</label>
              <div class="range">
                <TradeDatePicker v-model="cfg.range_start" placeholder="开始日" clearable />
                <span>至</span>
                <TradeDatePicker v-model="cfg.range_end" placeholder="结束日" clearable />
                <span class="hint">留空 = 全部历史</span>
              </div>
            </div>
            <div class="cfg-item">
              <label>板块</label>
              <el-select v-model="cfg.boards" placeholder="不限（全部板块）" multiple clearable
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
          <template #header><span class="card-title">成长曲线</span><span class="card-sub">历次评分 / 收益</span></template>
          <AppStateBlock
            v-if="growthLoading && !growthData.length"
            state="loading"
            title="正在加载成长曲线…"
          />
          <AppStateBlock
            v-else-if="growthError && !growthData.length"
            state="error"
            title="成长曲线加载失败"
            :description="growthError"
            retry
            @retry="loadGrowth"
          />
          <template v-else>
          <AppStateBlock
            v-if="growthError"
            state="error"
            size="compact"
            title="成长曲线刷新失败"
            :description="growthError"
            retry
            @retry="loadGrowth"
          />
          <div v-loading="growthLoading">
            <GrowthChart :data="growthData" />
          </div>
          </template>
        </el-card>

        <el-card shadow="never" class="hist-card">
          <template #header><span class="card-title">训练历史</span><span class="card-sub">共 {{ history.total }} 局，点行回看</span></template>
          <AppStateBlock
            v-if="historyLoading && !history.list.length"
            state="loading"
            title="正在加载训练历史…"
          />
          <AppStateBlock
            v-else-if="historyError && !history.list.length"
            state="error"
            title="训练历史加载失败"
            :description="historyError"
            retry
            @retry="loadHistory"
          />
          <template v-else>
          <AppStateBlock
            v-if="historyError"
            state="error"
            size="compact"
            title="训练历史刷新失败"
            :description="historyError"
            retry
            @retry="loadHistory"
          />
          <AppDataTable
            :data="history.list"
            :loading="historyLoading"
            size="small"
            table-class="hist-table"
            :border="tableBorder('history')"
            clickable
            :default-sort="historyDefaultSort"
            @sort-change="onHistorySortChange"
            @row-click="(r:SessionRow)=>openSession(r.id)">
            <el-table-column label="模式" width="90">
              <template #default="{ row }">{{ modeText(row.mode) }}·{{ row.n_rounds }}</template>
            </el-table-column>
            <el-table-column label="评级" width="70">
              <template #default="{ row }">
                <span v-if="row.grade" class="grade-chip" :style="{ background: gradeColor(row.grade) }">{{ row.grade }}</span>
                <span v-else class="muted">进行中</span>
              </template>
            </el-table-column>
            <el-table-column label="评分" prop="score" width="70" sortable="custom">
              <template #default="{ row }">{{ row.score != null ? row.score.toFixed(1) : '--' }}</template>
            </el-table-column>
            <el-table-column label="收益" prop="total_return" width="90" sortable="custom">
              <template #default="{ row }"><span :class="(row.total_return ?? 0) >= 0 ? 'up' : 'down'">{{ pct(row.total_return) }}</span></template>
            </el-table-column>
            <el-table-column label="胜率" prop="win_rate" width="80" sortable="custom">
              <template #default="{ row }">{{ row.win_rate != null ? (row.win_rate * 100).toFixed(0) + '%' : '--' }}</template>
            </el-table-column>
            <el-table-column label="开始时间" prop="created_at" min-width="140" sortable="custom">
              <template #default="{ row }">{{ row.created_at?.slice(0, 16) }}</template>
            </el-table-column>
            <el-table-column label="结束时间" prop="completed_at" min-width="140" sortable="custom">
              <template #default="{ row }">{{ row.completed_at?.slice(0, 16) ?? '--' }}</template>
            </el-table-column>
            <el-table-column label="操作" width="72">
              <template #default="{ row }">
                <AppRowActions :actions="sessionRowActions(row)" :inline-limit="1" />
              </template>
            </el-table-column>
          </AppDataTable>
          </template>
          <el-pagination v-if="history.total > history.size" small layout="prev, pager, next"
            :total="history.total" :page-size="history.size" :current-page="history.page"
            @current-change="(p:number)=>{ history.page=p; loadHistory() }" class="pager" />
        </el-card>
    </div>
    </template>
  </LayoutHost>

  <!-- ══════════ 阶段二：训练中（混合成长区）══════════ -->
  <LayoutHost v-else-if="phase === 'running' && round" :layout="trainingEffective">
    <template #action>
    <div class="page-head">
        <div>
          <h2 class="title-row">
            🎮 盘感训练 · 进行中
            <HelpTip title="训练规则" :width="380">
              <p><b>盲测</b>：隐藏个股身份与真实日期，横轴用相对日（D±n）。</p>
              <p style="margin:6px 0 0"><b>买 T+0</b>：买入当日按收盘价即时成交（收盘封涨停买不到）。<b>卖 T+1</b>：卖出登记后次日开盘成交（开盘跌停卖不出、停牌顺延）。窗口末日仍持仓将按收盘价强制清算。</p>
            </HelpTip>
          </h2>
          <span class="sub">回合 {{ view!.cur_round + 1 }}/{{ view!.n_rounds }} · 第 {{ round.cursor_idx + 1 }}/{{ round.window_days }} 个交易日 · 盲测中</span>
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
          <CandleChart :bars="displayBars" :warmup-bars="warmupBars" :markers="round.markers" :zoom-start="0" :zoom-end="100" />
        </div>

        <div v-permission="'training:trade'" class="action-panel">
          <div class="acct">
            <div class="acct-item"><label>可用资金（可买上限）</label><b class="lim">{{ money(round.cash) }}</b></div>
            <div class="acct-item"><label>持仓（可卖上限）</label><b class="lim">{{ round.pos_hands }} 手</b><span class="muted">@{{ round.pos_avg_price.toFixed(2) }}</span></div>
            <div class="acct-item"><label>浮动盈亏</label><b :class="round.unrealized_pnl >= 0 ? 'up' : 'down'">{{ money(round.unrealized_pnl) }}</b></div>
            <div class="acct-item"><label>总资产</label><b>{{ money(round.equity) }}</b><span :class="(round.equity - view!.initial_capital) >= 0 ? 'up' : 'down'">{{ pct((round.equity - view!.initial_capital) / view!.initial_capital) }}</span></div>
            <div class="acct-item"><label>当前价</label><b>{{ round.cur_close.toFixed(2) }}</b></div>
          </div>

          <div v-if="round.pending" class="pending">
            <span>待成交（次日开盘）：<b :class="round.pending.side === 'buy' ? 'up' : 'down'">{{ round.pending.side === 'buy' ? '买入' : '卖出' }} {{ round.pending.hands }} 手</b></span>
            <el-button link type="info" size="small" @click="doCancel">撤单</el-button>
          </div>

          <template v-if="!isLast">
            <div class="ops order-input">
              <PageSegmented v-model="cfg.orderMode" :options="[{ label: '按手数', value: 'hands' }, { label: '按金额', value: 'amount' }]" />
              <el-input-number v-model="order.qty" :min="inputMin" :max="inputMax" :step="inputStep" controls-position="right" style="width:160px" />
              <span class="unit">{{ isAmount ? '元' : '手' }}</span>
              <span class="hint" v-if="!isAmount">
                约需 ¥{{ money(estCost) }} · 最多可买
                <b class="hl" title="点击填入全仓" @click="fillBuyMax">{{ maxBuyHands }}</b> 手
              </span>
              <span class="hint" v-else>
                可用资金 <b class="hl" title="点击全额填入" @click="fillBuyMax">¥{{ money(cash) }}</b> · 本单 ≈ {{ orderHands }} 手
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
          <el-table :data="round.trades" height="100%" size="small" empty-text="尚无成交">
            <el-table-column label="相对日" width="80"><template #default="{ row }">D{{ row.rel_day }}</template></el-table-column>
            <el-table-column label="方向" width="70"><template #default="{ row }"><span :class="row.side === 'buy' ? 'up' : 'down'">{{ row.side === 'buy' ? '买入' : '卖出' }}</span></template></el-table-column>
            <el-table-column label="成交价" width="90"><template #default="{ row }">{{ row.price.toFixed(2) }}</template></el-table-column>
            <el-table-column label="手数" width="70"><template #default="{ row }">{{ row.hands }}</template></el-table-column>
            <el-table-column label="盈亏" width="100"><template #default="{ row }"><span v-if="row.pnl != null" :class="row.pnl >= 0 ? 'up' : 'down'">{{ money(row.pnl) }}</span><span v-else class="muted">—</span></template></el-table-column>
            <el-table-column label="收益率" width="90"><template #default="{ row }"><span v-if="row.return_pct != null" :class="row.return_pct >= 0 ? 'up' : 'down'">{{ pct(row.return_pct) }}</span><span v-else class="muted">—</span></template></el-table-column>
            <el-table-column label="理由" min-width="120"><template #default="{ row }">{{ row.reason || (row.auto_close ? '到期清算' : '') }}</template></el-table-column>
          </el-table>
        </el-card>
    </div>
    </template>
  </LayoutHost>

  <!-- ══════════ 阶段三：结算回看 ══════════ -->
  <LayoutHost v-else-if="phase === 'result' && detail" :layout="trainingEffective">
    <template #action>
    <div class="page-head">
        <div>
          <h2 class="title-row">
            🎮 训练结算
            <span class="grade-big app-data-emphasis" :style="{ color: gradeColor(detail.grade) }">{{ detail.grade }}</span>
            <span class="score-tip">综合评分 {{ detail.score?.toFixed(1) }}</span>
          </h2>
          <span class="sub">{{ modeText(detail.mode) }} · {{ detail.n_rounds }} 回合 · {{ detail.created_at?.slice(0, 16) }}</span>
        </div>
        <el-button @click="backToConfig">返回</el-button>
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

        <el-card v-for="rd in detail.rounds" :key="rd.seq" shadow="never" class="round-card">
          <template #header>
            <div class="round-head">
              <span class="rname">回合 {{ rd.seq + 1 }} · {{ rd.name }} <span class="muted">{{ rd.code }}</span></span>
              <span class="muted">{{ rd.start_date }} ~ {{ rd.end_date }}</span>
              <span class="round-ret">你 <b :class="(rd.round_return ?? 0) >= 0 ? 'up' : 'down'">{{ pct(rd.round_return) }}</b> · 满仓持有 <b :class="(rd.benchmark_return ?? 0) >= 0 ? 'up' : 'down'">{{ pct(rd.benchmark_return) }}</b> · 回撤 <b class="down">{{ pct(rd.max_drawdown) }}</b></span>
            </div>
          </template>
          <div class="round-grid">
            <div class="round-chart"><CandleChart
              :bars="viewDays >= 99999 ? rd.bars : rd.bars.slice(-viewDays)"
              :warmup-bars="viewDays >= 99999 ? [] : rd.bars.slice(0, -viewDays || undefined)"
              :markers="rd.markers" :zoom-start="0" :zoom-end="100"
            /></div>
            <div class="round-equity"><EquityChart :points="roundEquityPoints(rd, detail.initial_capital)" benchmark-code="满仓持有" /></div>
          </div>
          <el-table :data="rd.trades" size="small" class="round-trades" empty-text="本回合无成交">
            <el-table-column label="决策日" width="110"><template #default="{ row }">{{ row.decide_date }}</template></el-table-column>
            <el-table-column label="成交日" width="110"><template #default="{ row }">{{ row.fill_date }}</template></el-table-column>
            <el-table-column label="方向" width="70"><template #default="{ row }"><span :class="row.side === 'buy' ? 'up' : 'down'">{{ row.side === 'buy' ? '买入' : '卖出' }}</span></template></el-table-column>
            <el-table-column label="成交价" width="90"><template #default="{ row }">{{ row.price.toFixed(2) }}</template></el-table-column>
            <el-table-column label="手数" width="70"><template #default="{ row }">{{ row.hands }}</template></el-table-column>
            <el-table-column label="盈亏" width="100"><template #default="{ row }"><span v-if="row.pnl != null" :class="row.pnl >= 0 ? 'up' : 'down'">{{ money(row.pnl) }}</span><span v-else class="muted">—</span></template></el-table-column>
            <el-table-column label="收益率" width="90"><template #default="{ row }"><span v-if="row.return_pct != null" :class="row.return_pct >= 0 ? 'up' : 'down'">{{ pct(row.return_pct) }}</span><span v-else class="muted">—</span></template></el-table-column>
            <el-table-column label="理由" min-width="120"><template #default="{ row }">{{ row.reason || (row.auto_close ? '到期清算' : '') }}</template></el-table-column>
          </el-table>
        </el-card>

        <el-card shadow="never" class="review-card">
          <template #header><span class="card-title">整局复盘</span></template>
          <el-input v-model="reviewNote" type="textarea" :rows="4" placeholder="记录本局思路、复盘总结、改进点……" />
          <div class="review-actions"><el-button v-permission="'training:review'" type="primary" @click="persistReview">保存复盘</el-button></div>
        </el-card>
    </div>
    </template>
  </LayoutHost>

  <!-- 设置抽屉：快捷下单预设（三阶段共享，作为根级兄弟，teleport 到 body）-->
  <PageSettingsDrawer
    v-model="settingsOpen"
    title="盘感训练"
    :dirty="isDirty || layoutDirty"
    page-key="training"
    :config="drawerConfig"
    @reset="reset(); resetLayout()"
  >
      <template #business>
      <PageSettingSection title="开局默认" desc="每次开局沿用的默认参数，开局前可临时改。">
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
          <el-input-number v-model="cfg.initial_capital" :min="10000" :step="10000" size="small" style="width:160px" />
        </div>
      </PageSettingSection>
      <KlineSettingSection />
      <PageSettingSection title="选股范围" desc="控制随机选股时的股票池过滤条件。">
        <div class="setting-item">
          <div class="setting-label">排除 ST</div>
          <el-switch v-model="cfg.exclude_st" />
        </div>
        <div class="setting-item">
          <div class="setting-label">
            计入交易成本
            <HelpTip title="交易成本" :width="280">关闭则为「零摩擦」，不计佣金/印花税/过户费/滑点，用于专注练买卖时机。</HelpTip>
          </div>
          <el-switch v-model="cfg.fee_enabled" />
        </div>
      </PageSettingSection>
      <PageSettingSection title="快捷下单" desc="配置下单方式与一键预设，训练时直接点选快速买卖。">
        <div class="setting-item">
          <div class="setting-label">默认下单方式</div>
          <PageSegmented v-model="cfg.orderMode" :options="[{ label: '按手数', value: 'hands' }, { label: '按金额', value: 'amount' }]" />
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
.page-head { display: flex; justify-content: space-between; align-items: flex-end; flex-wrap: wrap; gap: var(--app-space-2); padding-bottom: 4px; }
.page-head .title-row { margin: 0; font-size: var(--app-font-size-page-title-sm); display: flex; align-items: center; gap: var(--app-space-control-gap); }
.page-head .sub { color: var(--el-text-color-secondary); font-size: var(--app-font-size-table); }
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
.pager { margin-top: 8px; }
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

/* 结算：纯长内容流 → 整体内滚 */
.result-body { flex: 1 1 auto; min-height: 0; overflow: auto; display: flex; flex-direction: column; gap: var(--app-space-3); padding-right: 2px; }
.kpi-row { display: flex; gap: var(--app-space-3); flex-wrap: wrap; }
.kpi { flex: 1 1 120px; background: var(--el-fill-color-light); border-radius: 8px; padding: 10px 14px; display: flex; flex-direction: column; gap: var(--app-space-1); }
.kpi label { font-size: var(--app-font-size-caption); color: var(--el-text-color-secondary); }
.kpi b { font-size: var(--app-font-size-page-title-sm); font-variant-numeric: tabular-nums; }
.round-head { display: flex; align-items: baseline; gap: var(--app-space-4); flex-wrap: wrap; }
.round-head .rname { font-weight: var(--app-font-weight-section); }
.round-head .round-ret { margin-left: auto; font-size: var(--app-font-size-table); }
.round-grid { display: grid; grid-template-columns: 1.4fr 1fr; gap: var(--app-space-3); }
.round-equity { min-width: 0; }
.round-trades { margin-top: 10px; }
.review-actions { margin-top: 10px; text-align: right; }

.up { color: var(--el-color-danger); }
.down { color: var(--el-color-success); }
.muted { color: var(--el-text-color-placeholder); }
@media (max-width: 1100px) { .round-grid { grid-template-columns: 1fr; } }
</style>
