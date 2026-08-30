<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Download, RefreshLeft } from '@element-plus/icons-vue'
import AppControlRow from '@/components/AppControlRow.vue'
import AppFilterSelect from '@/components/AppFilterSelect.vue'
import AppSearchInput from '@/components/AppSearchInput.vue'
import AppStateBlock from '@/components/AppStateBlock.vue'
import PageSegmented from '@/components/PageSegmented.vue'
import TradeDatePicker from '@/components/TradeDatePicker.vue'
import {
  DEFAULT_LIMIT_LADDER_FILTERS,
  type LimitLadderFilters,
  type LimitLadderHotspotType,
  type LimitLadderResult,
  type LimitLadderStock,
} from '@/api/limitLadder'
import LadderHotspots from './LadderHotspots.vue'
import LimitLadderCard from './LimitLadderCard.vue'

const props = defineProps<{
  result: LimitLadderResult | null
  filters: LimitLadderFilters
  tradeDate: string | null
  loading: boolean
  error: string
  exporting: boolean
  canViewSectors: boolean
}>()
const emit = defineEmits<{
  'update:filters': [filters: LimitLadderFilters]
  'update:tradeDate': [tradeDate: string | null]
  retry: []
  export: []
  select: [stock: LimitLadderStock]
}>()
const keywordDraft = ref(props.filters.keyword)
watch(() => props.filters.keyword, (value) => { keywordDraft.value = value })
const boardOptions = [
  { value: 'main', label: '主板' },
  { value: 'star', label: '科创板' },
  { value: 'gem', label: '创业板' },
]
const windowOptions = [10, 20, 31, 60].map((value) => ({ label: `${value} 日`, value }))
const ladderMeta = computed(() => props.result
  ? `${props.result.summary.stock_count} 只 · ${props.filters.window} 日口径`
  : '等待快照')
const hasApproximateSt = computed(() => Boolean(
  props.result?.snapshot?.has_approx_st
    || props.result?.layers.some((layer) => (
      layer.stocks.some((stock) => stock.st_quality === 'approximate')
    )),
))
const filteredEmpty = computed(() => props.result?.business_code === 'FILTER_EMPTY')
function ladderWidth(height: number): string {
  const highest = props.result?.summary.highest_board ?? height
  return `${Math.max(
    54,
    100 - Math.max(0, height - 1) * (46 / Math.max(1, highest - 1)),
  )}%`
}
function updateFilters(patch: Partial<LimitLadderFilters>): void {
  emit('update:filters', { ...props.filters, ...patch })
}
function updateBoards(value: string[] | string): void {
  const boards = (Array.isArray(value) ? value : [value]) as LimitLadderFilters['boards']
  updateFilters({
    boards: boards.length ? boards : [...DEFAULT_LIMIT_LADDER_FILTERS.boards],
  })
}
function searchKeyword(): void {
  updateFilters({ keyword: keywordDraft.value.trim() })
}
function toggleHotspot(type: LimitLadderHotspotType, key: string): void {
  const same = props.filters.hotspotType === type && props.filters.hotspotKey === key
  updateFilters({ hotspotType: same ? null : type, hotspotKey: same ? null : key })
}
function resetFilters(): void {
  keywordDraft.value = ''
  emit('update:filters', { ...DEFAULT_LIMIT_LADDER_FILTERS })
}
</script>

<template>
  <div class="limit-ladder" data-testid="limit-ladder-main">
    <section class="limit-ladder__toolbar" aria-label="连板天梯筛选">
      <AppControlRow align="center">
        <TradeDatePicker :model-value="tradeDate" placeholder="选择交易日" data-testid="limit-ladder-date" @update:model-value="$emit('update:tradeDate',$event)" />
        <PageSegmented :model-value="filters.window" :options="windowOptions" size="small" tone="primary" test-id="limit-ladder-window" aria-label="统计窗口" @update:model-value="updateFilters({window:Number($event) as LimitLadderFilters['window']})" />
        <AppFilterSelect class="limit-ladder__board-filter" :model-value="filters.boards" :options="boardOptions" placeholder="上市板块" :max-collapse-tags="2" data-testid="limit-ladder-boards" @change="updateBoards" />
        <el-checkbox :model-value="filters.ignoreSt" data-testid="limit-ladder-ignore-st" @update:model-value="updateFilters({ignoreSt:Boolean($event)})">忽略 ST</el-checkbox>
        <el-checkbox :model-value="filters.oneWordOnly" data-testid="limit-ladder-one-word" @update:model-value="updateFilters({oneWordOnly:Boolean($event)})">仅一字板</el-checkbox>
        <AppSearchInput v-model="keywordDraft" class="limit-ladder__search" placeholder="代码 / 名称" data-testid="limit-ladder-keyword" @search="searchKeyword" />
        <el-button :icon="RefreshLeft" @click="resetFilters">清除筛选</el-button>
        <el-button :icon="Download" :loading="exporting" :disabled="!result?.has_snapshot" data-testid="limit-ladder-export" @click="$emit('export')">导出 CSV</el-button>
      </AppControlRow>
    </section>
    <section v-if="result" class="limit-ladder__summary" aria-label="天梯摘要">
      <div><span>当前股票</span><strong data-testid="limit-ladder-summary-total">{{ result.summary.stock_count }}</strong><small>只</small></div>
      <div><span>最高板位</span><strong>{{ result.summary.highest_board ?? '—' }}</strong><small>板</small></div>
      <div><span>首板股票</span><strong>{{ result.summary.first_board_count }}</strong><small>只</small></div>
      <div class="limit-ladder__summary-meta"><span>{{ ladderMeta }}</span><el-tag v-if="hasApproximateSt" type="warning" effect="plain" size="small">历史 ST 含近似口径</el-tag></div>
    </section>
    <LadderHotspots v-if="result?.has_snapshot" :hotspots="result.hotspots" :active-type="filters.hotspotType" :active-key="filters.hotspotKey" @toggle="toggleHotspot" />
    <div class="limit-ladder__body">
      <AppStateBlock v-if="loading" state="loading" title="正在加载天梯快照" :skeleton-rows="6" />
      <AppStateBlock v-else-if="error" state="error" title="天梯加载失败" :description="error" retry @retry="$emit('retry')" />
      <AppStateBlock v-else-if="!result?.has_snapshot" state="empty"><div class="limit-ladder__empty-copy"><strong>当前交易日快照尚未就绪</strong><span>系统已受理或正在准备快照，可稍后重试。</span></div></AppStateBlock>
      <AppStateBlock v-else-if="filteredEmpty" state="empty">
        <div class="limit-ladder__empty-copy"><strong>当前筛选无匹配股票</strong><span>清除筛选后可恢复完整天梯。</span></div>
        <template #extra><el-button type="primary" @click="resetFilters">清除筛选</el-button></template>
      </AppStateBlock>
      <AppStateBlock v-else-if="!result.layers.length" state="empty"><div class="limit-ladder__empty-copy"><strong>当日无涨停股票</strong><span>这是合法的空快照，不代表加载失败。</span></div></AppStateBlock>
      <div v-else class="limit-ladder__layers" aria-label="连板天梯分层">
        <section v-for="layer in result.layers" :key="layer.consecutive_days" class="limit-ladder__layer" :style="{width:ladderWidth(layer.consecutive_days)}" :data-testid="`limit-ladder-layer-${layer.consecutive_days}`">
          <header class="limit-ladder__layer-head"><span>{{ layer.consecutive_days }}B</span><strong>{{ layer.consecutive_days===1?'首板':`${layer.consecutive_days} 连板` }}</strong><small>{{ layer.stock_count }} 只</small></header>
          <div class="limit-ladder__cards"><LimitLadderCard v-for="stock in layer.stocks" :key="stock.code" :stock="stock" :window="filters.window" :can-view-sectors="canViewSectors" @select="$emit('select',$event)" /></div>
        </section>
      </div>
    </div>
  </div>
</template>

<style scoped>
.limit-ladder {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  min-height: 0;
}
.limit-ladder__toolbar {
  flex: 0 0 auto;
  padding: var(--app-space-3) var(--app-space-4);
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.limit-ladder__board-filter { width: 210px; }
.limit-ladder__search { width: 180px; }
.limit-ladder__summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(96px, auto)) minmax(180px, 1fr);
  gap: var(--app-space-3);
  align-items: center;
  padding: var(--app-space-3) var(--app-space-4);
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.limit-ladder__summary > div:not(.limit-ladder__summary-meta) {
  display: grid;
  grid-template-columns: auto auto auto;
  align-items: baseline;
  justify-content: start;
  gap: var(--app-space-1);
}
.limit-ladder__summary span,
.limit-ladder__summary small {
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
}
.limit-ladder__summary strong {
  color: var(--el-text-color-primary);
  font-size: var(--app-font-size-title);
  font-variant-numeric: tabular-nums;
}
.limit-ladder__summary-meta {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: var(--app-space-2);
}
.limit-ladder__body {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
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
  min-width: 620px;
}
.limit-ladder__layer {
  min-width: 54%;
  border: 1px solid var(--el-border-color);
  border-radius: var(--layout-card-radius);
  background: color-mix(in srgb, var(--el-fill-color-light) 34%, var(--el-bg-color));
}
.limit-ladder__layer-head {
  display: flex;
  align-items: baseline;
  gap: var(--app-space-2);
  padding: var(--app-space-2) var(--app-space-3);
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.limit-ladder__layer-head > span {
  color: var(--app-market-up, var(--el-color-danger));
  font-weight: var(--app-font-weight-strong);
}
.limit-ladder__layer-head small {
  margin-left: auto;
  color: var(--el-text-color-secondary);
}
.limit-ladder__cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
  gap: var(--app-space-2);
  padding: var(--app-space-2);
}
@media (max-width: 900px) {
  .limit-ladder__summary { grid-template-columns: repeat(3, 1fr); }
  .limit-ladder__summary-meta { grid-column: 1 / -1; justify-content: flex-start; }
  .limit-ladder__body { padding: var(--app-space-3); }
  .limit-ladder__layers { min-width: 560px; align-items: stretch; }
  .limit-ladder__layer { width: 100% !important; }
}
</style>
