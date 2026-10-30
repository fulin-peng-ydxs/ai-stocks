<script setup lang="ts">
import AppScrollArea from '@/components/AppScrollArea.vue'
import { computed, ref } from 'vue'
import AppStateBlock from '@/components/AppStateBlock.vue'
import AppStatusNotice from '@/components/AppStatusNotice.vue'
import { formatDateTimeSeconds } from '@/utils/dateTime'
import { businessMessage } from '@/utils/displayText'
import {
  DEFAULT_LIMIT_LADDER_FILTERS,
  type LimitLadderFilters,
  type LimitLadderHotspotType,
  type LimitLadderResult,
  type LimitLadderStock,
} from '@/api/limitLadder'
import LadderHotspots from './LadderHotspots.vue'
import LimitLadderCard from './LimitLadderCard.vue'
import {
  DEFAULT_LIMIT_LADDER_CARD_SORT,
  DEFAULT_LIMIT_LADDER_CARD_SORT_ORDER,
  sortLimitLadderLayers,
  type LimitLadderCardSort,
  type LimitLadderCardSortOrder,
} from './sorting'

const props = withDefaults(defineProps<{
  result: LimitLadderResult | null
  tradeDate?: string | null
  filters: LimitLadderFilters
  loading: boolean
  error: string
  forbidden?: boolean
  canViewSectors: boolean
  canRecompute?: boolean
  canManageData?: boolean
  selectedCode?: string
  returnPath?: string
  cardSort?: LimitLadderCardSort
  cardSortOrder?: LimitLadderCardSortOrder
}>(), {
  cardSort: DEFAULT_LIMIT_LADDER_CARD_SORT,
  cardSortOrder: DEFAULT_LIMIT_LADDER_CARD_SORT_ORDER,
})
const emit = defineEmits<{
  'update:filters': [filters: LimitLadderFilters]
  retry: []
  openIngest: []
  select: [stock: LimitLadderStock]
}>()
const compactHotspotsOpen = ref(false)
const sortedLayers = computed(() => sortLimitLadderLayers(
  props.result?.layers ?? [],
  props.cardSort,
  props.cardSortOrder,
))
const hasApproximateSt = computed(() => Boolean(
  props.result?.snapshot?.has_approx_st
    || props.result?.layers.some((layer) => (
      layer.stocks.some((stock) => stock.st_quality === 'approximate')
    )),
))
const filteredEmpty = computed(() => props.result?.business_code === 'FILTER_EMPTY')
const stStatusBlocked = computed(() => props.result?.business_code === 'ST_STATUS_NOT_READY')
const staleSnapshot = computed(() => (
  props.result?.business_code === 'SNAPSHOT_STALE'
  || (stStatusBlocked.value && props.result?.has_snapshot)
))
const pendingSnapshot = computed(() => props.result?.business_code === 'SNAPSHOT_PENDING')
const failedSnapshot = computed(() => props.result?.business_code === 'SNAPSHOT_FAILED')
const coverageBlocked = computed(() => (
  String(props.result?.invalid_reason || '').includes('INGEST_PARTIAL')
  || (props.result?.coverage?.reason_codes as unknown[] | undefined)?.includes('INGEST_PARTIAL')
))
const retryText = computed(() => (
  failedSnapshot.value && props.canRecompute ? '重新计算' : '刷新状态'
))
const coverageReasonLabels: Record<string, string> = {
  NOT_TRADING_DAY: '所选日期不是交易日',
  POINT_IN_TIME_POOL_EMPTY: '当日点时股票池为空',
  INGEST_PARTIAL: '当日行情采集未完整成功',
  MISSING_BAR_OR_SUSPENSION: '部分股票缺少行情或停牌确认',
  INVALID_DAILY_BAR: '部分日行情字段无效',
  INVALID_OHLC: '开高低收价格无效',
  PRICE_NOT_NUMERIC: '收盘价或昨收缺失',
  PRICE_NOT_POSITIVE_FINITE: '收盘价或昨收不是有效正数',
  CLOSE_ABOVE_LIMIT_PRICE: '收盘价超过当前规则涨停价',
  LIMIT_PCT_MISSING: '缺少板块涨跌幅比例',
  LIMIT_PCT_INVALID: '板块涨跌幅比例无效',
  PRICE_LIMIT_APPLICABILITY_UNKNOWN: '无法确认当日涨跌幅规则',
  UNSUPPORTED_LIMIT_RULE: '部分股票无法可靠判断涨停规则',
  ST_STATUS_NOT_READY: 'ST 点时事实尚未发布',
}
function readableReason(value: string | null | undefined): string {
  if (!value) return ''
  return value.split(',').map((reason) => coverageReasonLabels[reason.trim()]
    || businessMessage(reason, '结果尚未通过检查，请到任务中心查看详情')).join('；')
}
const coverageReasons = computed(() => {
  const value = props.result?.coverage?.reason_codes
  return Array.isArray(value)
    ? value.map((reason) => coverageReasonLabels[String(reason)]
      || businessMessage(reason, '数据完整性尚未确认')).join('；')
    : ''
})
const unavailableTitle = computed(() => {
  if (props.result?.business_code === 'NOT_TRADING_DAY') return '所选日期不是交易日'
  if (stStatusBlocked.value) return 'ST 状态尚未就绪'
  if (props.result?.business_code === 'SNAPSHOT_FAILED') return '天梯快照计算失败'
  if (props.result?.business_code === 'SNAPSHOT_NOT_READY') return '行情数据尚未就绪'
  return '当前交易日尚无可用快照'
})
const unavailableDescription = computed(() => {
  if (props.result?.business_code === 'NOT_TRADING_DAY') {
    return props.result.nearest_previous_trade_date
      ? `请切换到交易日；最近交易日为 ${props.result.nearest_previous_trade_date}`
      : '请切换到有效交易日后重试'
  }
  if (stStatusBlocked.value) {
    return 'ST 状态刷新尚未完整发布，请等待刷新完成或重新运行“ST状态刷新”后重试'
  }
  const reason = readableReason(props.result?.failure_summary)
    || readableReason(props.result?.invalid_reason)
    || coverageReasons.value
  if (coverageBlocked.value) {
    const action = props.canManageData && props.canRecompute
      ? '请前往“数据采集”执行“日常同步”，完成后返回本页点击“重算当日”'
      : props.canManageData
        ? '请前往“数据采集”执行“日常同步”，完成后联系有重算权限的管理员'
      : '请联系有数据任务权限的管理员执行行情补采，完成后刷新状态'
    return `${reason || '当日行情采集未完整成功'}；${action}`
  }
  const diagnostics = props.result?.coverage?.diagnostics
  const detail = Array.isArray(diagnostics)
    ? diagnostics.slice(0, 10).map((item) => (
      `${item.code}：${coverageReasonLabels[item.reason] || businessMessage(item.reason, '完整性原因待核验')}`
    )).join('；')
    : ''
  return [detail ? (coverageReasons.value || reason) : (businessMessage(props.result?.task_error, '') || reason), detail]
    .filter(Boolean).join('；')
    || '系统尚未发布通过完整性校验的结果，请稍后重试'
})
const pendingDescription = computed(() => {
  const task = props.result?.task
  const progress = typeof task?.progress === 'number'
    ? `当前进度 ${Math.round(task.progress * 100)}%`
    : ''
  return [
    `天梯快照正在计算：${businessMessage(task?.message, '正在校验行情完整性并生成快照')}`,
    progress,
    '页面最多等待 2 分钟；失败后会停止等待并显示原因',
  ].filter(Boolean).join(' · ')
})
const staleDescription = computed(() => {
  if (stStatusBlocked.value) {
    const lastSuccess = props.result?.last_success_at || props.result?.snapshot?.computed_at
    return [
      'ST 状态刷新尚未完整发布，系统未把旧快照判定为有效结果',
      lastSuccess ? `下方仅保留 ${formatDateTimeSeconds(lastSuccess)} 生成的最后成功版本供核对` : '',
      '请在数据管理中查看 ST 刷新任务的进度与诊断',
    ].filter(Boolean).join(' · ')
  }
  const recalculating = props.result?.snapshot_status === 'recalculating'
  const status = recalculating ? '当前版本正在重算' : '新版本暂不可用'
  const lastSuccess = props.result?.last_success_at || props.result?.snapshot?.computed_at
  const failure = businessMessage(props.result?.task_error, '')
    || readableReason(props.result?.failure_summary)
    || readableReason(props.result?.invalid_reason)
  return [
    status,
    lastSuccess ? `当前展示 ${formatDateTimeSeconds(lastSuccess)} 生成的最后成功版本` : '',
    recalculating ? '计算完成后将自动刷新' : '',
    failure || '',
  ]
    .filter(Boolean)
    .join(' · ')
})
function updateFilters(patch: Partial<LimitLadderFilters>): void {
  emit('update:filters', { ...props.filters, ...patch })
}
function toggleHotspot(type: LimitLadderHotspotType, key: string): void {
  const same = props.filters.hotspotType === type && props.filters.hotspotKey === key
  updateFilters({ hotspotType: same ? null : type, hotspotKey: same ? null : key })
}
function resetFilters(): void {
  emit('update:filters', { ...DEFAULT_LIMIT_LADDER_FILTERS })
}
</script>

<template>
  <div class="limit-ladder" data-testid="limit-ladder-main">
    <AppStatusNotice
      v-if="staleSnapshot && !loading && !error"
      class="limit-ladder__status-notice"
      data-testid="limit-ladder-stale-notice"
      tone="warning"
      :title="stStatusBlocked ? 'ST 状态尚未就绪' : '结果已过期'"
      :description="staleDescription"
    />
    <div v-if="result?.has_snapshot && !error && !forbidden && (!loading || tradeDate === result.trade_date)" class="limit-ladder__overview" :aria-busy="loading">
      <span v-if="loading" role="status" class="muted">正在更新，热点数量暂为上次结果</span>
      <section v-if="!loading" class="limit-ladder__summary" aria-label="天梯摘要">
        <div><span>当前股票</span><strong class="is-total" data-testid="limit-ladder-summary-total">{{ result.summary.stock_count }}</strong><small>只</small></div>
        <div><span>最高板位</span><strong class="is-highest">{{ result.summary.highest_board ?? '—' }}</strong><small>板</small></div>
        <div><span>首板股票</span><strong class="is-first">{{ result.summary.first_board_count }}</strong><small>只</small></div>
        <div v-if="hasApproximateSt" class="limit-ladder__summary-meta"><el-tag type="warning" effect="plain" size="small">历史 ST 含近似口径</el-tag></div>
        <el-button
          class="limit-ladder__hotspots-toggle"
          text
          :aria-expanded="compactHotspotsOpen"
          aria-controls="limit-ladder-hotspots"
          @click="compactHotspotsOpen = !compactHotspotsOpen"
        >{{ compactHotspotsOpen ? '收起热点' : '展开热点' }}</el-button>
      </section>
      <AppScrollArea id="limit-ladder-hotspots" class="limit-ladder__hotspots" :class="{ 'is-expanded': compactHotspotsOpen }">
        <LadderHotspots
          :hotspots="result.hotspots"
          :active-type="filters.hotspotType"
          :active-key="filters.hotspotKey"
          @toggle="toggleHotspot"
        />
      </AppScrollArea>
    </div>
    <AppScrollArea class="limit-ladder__content" data-testid="limit-ladder-scroll-region">
      <div class="limit-ladder__body">
        <AppStateBlock v-if="loading" data-testid="limit-ladder-state" state="loading" title="正在加载天梯快照" :skeleton-rows="6" />
        <AppStateBlock
          v-else-if="forbidden"
          data-testid="limit-ladder-state"
          state="error"
          variant="permission"
          title="无权限查看连板天梯"
          description="请联系系统管理员调整权限"
        />
        <AppStateBlock v-else-if="error" data-testid="limit-ladder-state" state="error" title="天梯加载失败" :description="error" retry @retry="$emit('retry')" />
        <AppStateBlock v-else-if="pendingSnapshot" data-testid="limit-ladder-state" state="loading" title="天梯快照正在计算" :description="pendingDescription" :skeleton-rows="6" />
        <AppStateBlock
          v-else-if="!result?.has_snapshot"
          data-testid="limit-ladder-state"
          :state="result?.business_code === 'NOT_TRADING_DAY' ? 'empty' : 'error'"
        >
          <div class="limit-ladder__empty-copy">
            <strong>{{ unavailableTitle }}</strong>
            <span>{{ unavailableDescription }}</span>
          </div>
          <template v-if="result?.business_code !== 'NOT_TRADING_DAY'" #extra>
            <el-button
              v-if="coverageBlocked && canManageData"
              type="primary"
              plain
              @click="$emit('openIngest')"
            >去补采行情</el-button>
            <el-button type="primary" @click="$emit('retry')">{{ retryText }}</el-button>
          </template>
        </AppStateBlock>
        <AppStateBlock v-else-if="filteredEmpty" data-testid="limit-ladder-state" state="empty">
          <div class="limit-ladder__empty-copy"><strong>当前筛选无匹配股票</strong><span>重置筛选后可恢复完整天梯。</span></div>
          <template #extra><el-button type="primary" data-filter-reset-empty @click="resetFilters">重置筛选</el-button></template>
        </AppStateBlock>
        <AppStateBlock v-else-if="!result.layers.length" data-testid="limit-ladder-state" state="empty"><div class="limit-ladder__empty-copy"><strong>当日无涨停股票</strong><span>这是合法的空快照，不代表加载失败。</span></div></AppStateBlock>
        <div v-else class="limit-ladder__layers" aria-label="连板天梯分层">
          <section v-for="layer in sortedLayers" :key="layer.consecutive_days" class="limit-ladder__layer" :data-testid="`limit-ladder-layer-${layer.consecutive_days}`">
            <header class="limit-ladder__layer-head"><span>{{ layer.consecutive_days }}B</span><strong>{{ layer.consecutive_days===1?'首板':`${layer.consecutive_days} 连板` }}</strong><small>{{ layer.stock_count }} 只</small></header>
            <div class="limit-ladder__cards"><LimitLadderCard v-for="stock in layer.stocks" :key="stock.code" :stock="stock" :window="filters.window" :can-view-sectors="canViewSectors" :selected="stock.code === selectedCode" :return-path="returnPath" @select="$emit('select',$event)" /></div>
          </section>
        </div>
      </div>
    </AppScrollArea>
  </div>
</template>

<style scoped>
.limit-ladder {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  container-name: limit-ladder;
  container-type: inline-size;
}
.limit-ladder__content {
  --app-scroll-display: flex;
  flex: 1 1 auto;
  --app-scroll-direction: column;
  min-height: 0;
  overscroll-behavior: contain;
}
/* 概览与股票滚动区分离，展开热点也不能占满工作区。 */
.limit-ladder__overview {
  flex: 0 0 auto;
  min-width: 0;
  background: var(--el-bg-color);
}
.limit-ladder__hotspots {
  max-height: min(calc(6 * var(--app-control-height-sm) + 8 * var(--app-space-2)), 24cqh);
  overscroll-behavior: contain;
}
.limit-ladder__hotspots-toggle { display: none; }
.limit-ladder__summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(96px, auto)) minmax(180px, 1fr);
  gap: var(--app-space-3);
  align-items: center;
  padding: var(--app-space-3) var(--app-space-4);
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.limit-ladder__status-notice {
  flex: 0 0 auto;
  border-width: 0 0 1px;
  border-radius: 0;
  padding-inline: var(--app-space-4);
}
.limit-ladder__summary > div:not(.limit-ladder__summary-meta) {
  display: grid;
  grid-template-columns: auto auto auto;
  align-items: baseline;
  justify-content: center;
  gap: var(--app-space-1);
}
.limit-ladder__summary span,
.limit-ladder__summary small {
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
}
.limit-ladder__summary strong {
  color: var(--el-text-color-primary);
  font-size: var(--app-font-size-data);
  font-weight: var(--app-font-weight-section);
  line-height: var(--app-line-height-data);
  font-variant-numeric: tabular-nums;
}
.limit-ladder__summary strong.is-total { color: var(--el-color-primary); }
.limit-ladder__summary strong.is-highest { color: var(--market-up-color); }
.limit-ladder__summary strong.is-first { color: var(--app-warning-text); }
.limit-ladder__summary-meta {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: var(--app-space-2);
}
.limit-ladder__body {
  display: flex;
  width: 100%;
  min-width: 0;
  flex: 1 0 auto;
  flex-direction: column;
  padding: var(--app-space-4);
}
.limit-ladder__empty-copy {
  display: grid;
  gap: var(--app-space-1);
  color: var(--el-text-color-secondary);
  line-height: var(--app-line-height-comfy);
}
.limit-ladder__empty-copy strong { color: var(--el-text-color-primary); }
.limit-ladder__layers {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-3);
  align-items: center;
  min-width: 0;
}
.limit-ladder__layer {
  width: 100%;
  min-width: min(100%, 220px);
  border: 1px solid var(--el-border-color);
  border-radius: var(--layout-card-radius);
  background: color-mix(in srgb, var(--app-section-bg) 34%, var(--el-bg-color));
}
.limit-ladder__layer-head {
  display: flex;
  align-items: baseline;
  gap: var(--app-space-2);
  padding: var(--app-space-2) var(--app-space-3);
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.limit-ladder__layer-head > span {
  color: var(--market-up-color);
  font-weight: var(--app-font-weight-strong);
}
.limit-ladder__layer-head small {
  margin-left: auto;
  color: var(--el-text-color-secondary);
}
.limit-ladder__cards {
  display: flex;
  flex-wrap: wrap;
  gap: var(--app-space-2);
  justify-content: flex-start;
  padding: var(--app-space-2);
}
.limit-ladder__cards > * {
  flex: 0 0 220px;
  width: 220px;
  max-width: 100%;
}
@container limit-ladder (max-width: 700px) {
  .limit-ladder__summary { grid-template-columns: repeat(3, 1fr); }
  .limit-ladder__summary-meta { grid-column: 1 / -1; justify-content: flex-start; }
  .limit-ladder__body { padding: var(--app-space-3); }
  .limit-ladder__layers { align-items: stretch; }
}
@container app-viewport (max-width: 720px) {
  .limit-ladder__hotspots-toggle { display: inline-flex; grid-column: 1 / -1; justify-self: start; }
  .limit-ladder__hotspots:not(.is-expanded) { display: none; }
}
@container app-viewport (max-height: 620px) {
  .limit-ladder__hotspots-toggle { display: inline-flex; grid-column: 1 / -1; justify-self: start; }
  .limit-ladder__hotspots:not(.is-expanded) { display: none; }
}
</style>
