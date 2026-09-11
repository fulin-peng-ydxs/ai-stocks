<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { getIntraday, type StockIntraday } from '@/api/stocks'
import AppStateBlock from '@/components/AppStateBlock.vue'
import AppStatusNotice from '@/components/AppStatusNotice.vue'
import { getErrorMessage } from '@/utils/error'
import { formatAmount, formatChartNumber } from './chartUtils'
import StockIntradayChart from './StockIntradayChart.vue'

const props = defineProps<{
  modelValue: boolean
  code: string
  name: string | null
  tradeDate: string
  requestKey?: number
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()

const loading = ref(false)
const error = ref('')
const data = ref<StockIntraday | null>(null)
let controller: AbortController | null = null
let requestVersion = 0

const title = computed(() => `${props.name || props.code} ${props.code} · ${props.tradeDate} · 分时`)
const rangeDescription = computed(() => {
  const start = data.value?.supported_start
  const end = data.value?.supported_end
  return start && end
    ? `免费分钟源当前仅支持本地最近交易日（${start} 至 ${end}）`
    : '免费分钟源当前仅支持本地最近 8 个交易日'
})
const summary = computed(() => {
  if (!data.value || !['ready', 'partial'].includes(data.value.status) || !data.value.points.length) {
    return null
  }
  const points = data.value.points
  const last = points.at(-1)!
  const high = Math.max(...points.map((point) => point.high))
  const low = Math.min(...points.map((point) => point.low))
  const amount = points.reduce((total, point) => total + point.amount, 0)
  const pct = data.value.pre_close && data.value.pre_close > 0
    ? ((last.close / data.value.pre_close) - 1) * 100
    : null
  return {
    close: formatChartNumber(last.close, 2),
    pct: pct == null ? '--' : `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`,
    tone: pct == null || pct === 0 ? 'flat' : pct > 0 ? 'up' : 'down',
    highLow: `${formatChartNumber(high, 2)} / ${formatChartNumber(low, 2)}`,
    amount: formatAmount(amount),
  }
})

function isCanceled(value: unknown): boolean {
  const candidate = value as { code?: string; name?: string }
  return candidate?.code === 'ERR_CANCELED' || candidate?.name === 'CanceledError'
}

async function load(): Promise<void> {
  controller?.abort()
  if (!props.modelValue || !props.code || !props.tradeDate) return
  const version = ++requestVersion
  const nextController = new AbortController()
  controller = nextController
  loading.value = true
  error.value = ''
  data.value = null
  try {
    const result = await getIntraday(props.code, props.tradeDate, nextController.signal)
    if (version === requestVersion && !nextController.signal.aborted) data.value = result
  } catch (reason) {
    if (version === requestVersion && !isCanceled(reason)) {
      error.value = getErrorMessage(reason, '分时行情加载失败，请稍后重试')
    }
  } finally {
    if (version === requestVersion) loading.value = false
  }
}

function close(): void {
  controller?.abort()
  requestVersion += 1
  emit('update:modelValue', false)
}

watch(
  [() => props.modelValue, () => props.code, () => props.tradeDate, () => props.requestKey],
  ([open]) => {
    if (open) void load()
    else controller?.abort()
  },
  { immediate: true },
)

onBeforeUnmount(() => controller?.abort())
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    :title="title"
    width="min(92vw, 1040px)"
    top="5vh"
    destroy-on-close
    data-testid="stock-intraday-dialog"
    @close="close"
  >
    <template #header>
      <div class="stock-intraday-dialog__header">
        <div class="stock-intraday-dialog__identity">
          <strong>{{ name || code }}</strong>
          <span>{{ code }} · {{ tradeDate }}</span>
        </div>
        <dl v-if="summary" class="stock-intraday-dialog__summary">
          <div>
            <dt>收盘</dt>
            <dd :class="`is-${summary.tone}`">{{ summary.close }}</dd>
          </div>
          <div>
            <dt>涨跌幅</dt>
            <dd :class="`is-${summary.tone}`">{{ summary.pct }}</dd>
          </div>
          <div>
            <dt>高 / 低</dt>
            <dd>{{ summary.highLow }}</dd>
          </div>
          <div>
            <dt>成交额</dt>
            <dd>{{ summary.amount }}</dd>
          </div>
        </dl>
      </div>
    </template>
    <AppStateBlock
      v-if="loading"
      state="loading"
      title="正在加载分时行情…"
      description="首次加载会访问免费分钟行情源，后续优先使用 12 小时缓存"
    />
    <AppStateBlock
      v-else-if="error"
      state="error"
      title="分时行情暂时不可用"
      :description="error"
      retry
      @retry="load"
    />
    <AppStateBlock
      v-else-if="data?.status === 'out_of_range'"
      state="empty"
      title="该日期超出免费源范围"
      :description="rangeDescription"
    />
    <AppStateBlock
      v-else-if="data?.status === 'no_data'"
      state="empty"
      title="该交易日暂无分时数据"
      description="可能为停牌、源端暂未覆盖或当日没有成交"
    />
    <template v-else-if="data && (data.status === 'ready' || data.status === 'partial')">
      <AppStatusNotice
        v-if="data.status === 'partial'"
        class="stock-intraday-dialog__notice"
        tone="warning"
        title="免费源返回的分钟点可能不完整，图中仅展示真实数据"
        description="可继续查看现有分时；缺失分钟不会补造价格或成交量"
      />
      <StockIntradayChart :points="data.points" :pre-close="data.pre_close" />
    </template>
  </el-dialog>
</template>

<style scoped>
.stock-intraday-dialog__notice {
  margin-bottom: var(--app-space-3);
}

.stock-intraday-dialog__header {
  display: flex;
  min-width: 0;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--app-space-5);
  padding-right: var(--app-space-5);
}

.stock-intraday-dialog__identity {
  display: flex;
  min-width: 0;
  align-items: baseline;
  gap: var(--app-space-2);
  white-space: nowrap;
}

.stock-intraday-dialog__identity strong {
  color: var(--el-text-color-primary);
  font-size: var(--app-font-size-page-title);
  font-weight: var(--app-font-weight-strong);
  line-height: var(--app-line-height-page-title);
}

.stock-intraday-dialog__identity span,
.stock-intraday-dialog__summary dt {
  color: var(--el-text-color-secondary);
}

.stock-intraday-dialog__summary {
  display: grid;
  flex: 0 1 560px;
  grid-template-columns: repeat(4, minmax(max-content, 1fr));
  gap: var(--app-space-5);
  margin: 0;
}

.stock-intraday-dialog__summary div {
  min-width: 0;
}

.stock-intraday-dialog__summary dt {
  margin-bottom: var(--app-space-1);
  font-size: var(--app-font-size-caption);
  font-weight: var(--app-font-weight-section);
}

.stock-intraday-dialog__summary dd {
  margin: 0;
  color: var(--el-text-color-primary);
  font-size: var(--app-font-size-data);
  font-weight: var(--app-font-weight-section);
  white-space: nowrap;
}

.stock-intraday-dialog__summary dd.is-up {
  color: var(--market-up-color);
}

.stock-intraday-dialog__summary dd.is-down {
  color: var(--market-down-color);
}

@media (max-width: 960px) {
  .stock-intraday-dialog__header {
    align-items: flex-start;
    flex-direction: column;
    gap: var(--app-space-2);
  }

  .stock-intraday-dialog__summary {
    width: 100%;
    flex-basis: auto;
    gap: var(--app-space-2);
  }
}
</style>
