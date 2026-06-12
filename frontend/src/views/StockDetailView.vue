<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getBars, getIndicators, getTradeEval, type Bar, type TradeEval } from '@/api/stocks'
import { listTradeProfiles, type TradeProfileSummary } from '@/api/tradeProfile'
import { useStockSet } from '@/stores/stockSet'
import CandleChart from '@/components/CandleChart.vue'

const route = useRoute()
const router = useRouter()
const code = ref(String(route.params.code))

// ── 通用导航：当前集合（分组成员 / 列表勾选 / 查询结果）上一个·下一个·直选 ──
const stockSet = useStockSet()
const setIndex = computed(() => stockSet.indexOf(code.value))
const inSet = computed(() => setIndex.value >= 0)
const prevCode = computed(() => stockSet.neighbor(code.value, -1))
const nextCode = computed(() => stockSet.neighbor(code.value, 1))
function gotoCode(c: string | null) {
  if (c && c !== code.value) router.push(`/stocks/${c}`)
}
const loading = ref(false)
const error = ref('')
const adjust = ref('qfq')
const viewDays = ref(250)   // 显示范围（缩放），数据始终全量加载，可自由拖动看全部
const bars = ref<Bar[]>([])
const name = ref('')
const latest = ref<Record<string, unknown> | null>(null)

// 同花顺式：全量数据 + dataZoom 缩放。viewDays 控制默认显示最近 N 日，可拖动看更早
const zoomStart = computed(() => {
  const n = bars.value.length
  if (!n || viewDays.value >= n) return 0
  return ((n - viewDays.value) / n) * 100
})

// 个股详情页展示的关键指标（取最新一日）
const INDICATOR_FIELDS: { key: string; label: string }[] = [
  { key: 'ma20', label: 'MA20' },
  { key: 'ma60', label: 'MA60' },
  { key: 'dist_to_high_2y', label: '距两年高(比)' },
  { key: 'is_high_2y', label: '两年新高' },
  { key: 'is_bull_arrange', label: '多头排列' },
  { key: 'ma20_up', label: 'MA20 向上' },
  { key: 'is_platform_breakout', label: '平台突破' },
  { key: 'is_vol_breakout', label: '放量突破' },
]

function fmt(v: unknown): string {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'boolean') return v ? '是' : '否'
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : v.toFixed(2)
  return String(v)
}

// ── 买卖指标方案评估（v2.0：替代固定买点引擎）──
const tradeProfiles = ref<TradeProfileSummary[]>([])
const tradeId = ref('')
const tradeEval = ref<TradeEval | null>(null)
const tradeLoading = ref(false)

// 快速点上/下一个会产生重叠请求：用 AbortController 取消在途 + 防抖只发最终一次
let reqCtrl: AbortController | null = null
let navTimer: ReturnType<typeof setTimeout> | null = null
function isAbort(e: unknown): boolean {
  const c = e as { code?: string; name?: string }
  return c?.code === 'ERR_CANCELED' || c?.name === 'CanceledError'
}

async function evalTrade(signal?: AbortSignal) {
  if (!tradeId.value) return
  tradeLoading.value = true
  try {
    const r = await getTradeEval(code.value, tradeId.value, undefined, signal)
    if (!signal?.aborted) tradeEval.value = r
  } catch (e) {
    if (!isAbort(e)) tradeEval.value = null
  } finally {
    if (!signal?.aborted) tradeLoading.value = false
  }
}

async function load() {
  reqCtrl?.abort()                      // 取消上一次在途请求
  const ctrl = new AbortController()
  reqCtrl = ctrl
  loading.value = true
  error.value = ''
  try {
    const [b, ind] = await Promise.all([
      getBars(code.value, { adjust: adjust.value, lookback: 6000 }, ctrl.signal),
      getIndicators(code.value, { lookback: 1 }, ctrl.signal),
    ])
    if (ctrl.signal.aborted) return
    bars.value = b.bars
    name.value = b.name || ''
    latest.value = ind.indicators.length ? ind.indicators[ind.indicators.length - 1] : null
    if (tradeId.value) evalTrade(ctrl.signal)  // 不阻塞主图
  } catch (e) {
    if (isAbort(e)) return
    error.value = (e as Error).message
  } finally {
    if (reqCtrl === ctrl) loading.value = false  // 仅最新一次负责收尾
  }
}

// 上/下一个连点防抖：路由变了立即换页，但数据加载合并到最后一次
function scheduleLoad() {
  if (navTimer) clearTimeout(navTimer)
  navTimer = setTimeout(() => { navTimer = null; load() }, 140)
}

watch(
  () => route.params.code,
  (c) => {
    if (c) {
      code.value = String(c)
      tradeEval.value = null
      scheduleLoad()
    }
  },
)

onMounted(async () => {
  try {
    tradeProfiles.value = await listTradeProfiles()
    if (tradeProfiles.value.length) tradeId.value = tradeProfiles.value[0].id
  } catch {
    /* 方案列表失败不阻塞 */
  }
  load()
})
</script>

<template>
  <div class="v-page">
    <div class="page-head">
      <div class="title">
        <el-button text @click="router.push('/stocks')">‹ 返回</el-button>
        <h2>{{ name || '—' }}</h2>
        <span class="code-sub">{{ code }}</span>
      </div>
      <div class="ops">
        <el-radio-group v-model="adjust" @change="load">
          <el-radio-button value="qfq">前复权</el-radio-button>
          <el-radio-button value="">不复权</el-radio-button>
        </el-radio-group>
        <el-select v-model="viewDays" style="width: 130px">
          <el-option :value="120" label="近 120 日" />
          <el-option :value="250" label="近 250 日" />
          <el-option :value="500" label="近 500 日" />
          <el-option :value="99999" label="全部" />
        </el-select>
      </div>
    </div>

    <div class="v-scroll">
    <!-- 通用集合导航条 -->
    <div v-if="stockSet.has" class="nav-bar">
      <span class="nav-label">
        {{ stockSet.label }}
        <span v-if="inSet" class="nav-pos">{{ setIndex + 1 }}/{{ stockSet.items.length }}</span>
        <span v-else class="nav-pos muted">不在集合内 · 共 {{ stockSet.items.length }} 只</span>
      </span>
      <el-button-group class="nav-btns">
        <el-button size="small" :disabled="!prevCode" @click="gotoCode(prevCode)">‹ 上一个</el-button>
        <el-button size="small" :disabled="!nextCode" @click="gotoCode(nextCode)">下一个 ›</el-button>
      </el-button-group>
      <el-select
        :model-value="inSet ? code : undefined"
        placeholder="从集合中选择"
        filterable
        size="small"
        style="width: 220px"
        @change="gotoCode"
      >
        <el-option
          v-for="(it, i) in stockSet.items"
          :key="it.code"
          :value="it.code"
          :label="`${i + 1}. ${it.name || ''} ${it.code}`"
        />
      </el-select>
      <el-button size="small" text @click="stockSet.clear()">退出集合</el-button>
    </div>

    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />

    <template v-else>
      <el-card shadow="never" v-loading="loading" :body-style="{ padding: '0' }">
        <CandleChart :bars="bars" :zoom-start="zoomStart" :zoom-end="100" />
      </el-card>

      <el-card shadow="never" class="ind-card" header="最新指标快照">
        <el-descriptions :column="4" border size="small">
          <el-descriptions-item v-for="f in INDICATOR_FIELDS" :key="f.key" :label="f.label">
            {{ latest ? fmt(latest[f.key]) : '—' }}
          </el-descriptions-item>
        </el-descriptions>
        <p class="note">注：RS 相对强度为全市场横截面指标，个股单独查询不计算；请在策略筛选/每日榜单中查看。</p>
      </el-card>

      <!-- 买卖指标方案评估 -->
      <el-card shadow="never" class="trade-card">
        <template #header>
          <div class="trade-head">
            <span>买卖信号评估</span>
            <el-select v-model="tradeId" size="small" style="width: 220px" @change="() => evalTrade()">
              <el-option v-for="p in tradeProfiles" :key="p.id" :value="p.id"
                :label="p.name + (p.is_preset ? '（预设）' : '')" />
            </el-select>
            <span class="hint" v-if="tradeEval">交易日 {{ tradeEval.date }} · v{{ tradeEval.version }}</span>
          </div>
        </template>
        <div v-loading="tradeLoading">
          <el-empty v-if="!tradeEval" description="选择买卖方案以评估当日信号" :image-size="60" />
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
                <el-empty v-if="!tradeEval.sell.conds.length" description="无卖出条件" :image-size="40" />
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
    </template>
    </div>
  </div>
</template>

<style scoped>
.page-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 14px;
}
.title {
  display: flex;
  align-items: center;
  gap: 8px;
}
.title h2 {
  margin: 0;
  font-size: 20px;
}
.code-sub {
  color: #909399;
  font-size: 14px;
  font-variant-numeric: tabular-nums;
}
.ops {
  display: flex;
  gap: 10px;
}
.nav-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 12px;
  margin-bottom: 14px;
  background: var(--el-fill-color-light);
  border-radius: 8px;
  flex-wrap: wrap;
}
.nav-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-regular);
  flex: 1;
}
.nav-pos {
  font-weight: 400;
  margin-left: 6px;
  color: var(--el-text-color-secondary);
  font-variant-numeric: tabular-nums;
}
.ind-card,
.trade-card {
  margin-top: 16px;
}
.note {
  margin: 10px 0 0;
  color: #909399;
  font-size: 12px;
}
.trade-head {
  display: flex;
  align-items: center;
  gap: 12px;
}
.hint {
  color: #909399;
  font-size: 12px;
}
.signal-row {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}
.cond-cols {
  display: flex;
  gap: 32px;
  flex-wrap: wrap;
}
.cond-col {
  flex: 1;
  min-width: 240px;
}
.cond-title {
  font-weight: 600;
  font-size: 13px;
  margin-bottom: 8px;
  color: var(--el-text-color-regular);
}
.cond-line {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
  font-size: 13px;
}
.backstop {
  margin-top: 10px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
</style>
