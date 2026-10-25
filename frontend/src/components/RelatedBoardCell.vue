<script setup lang="ts">
import { computed } from 'vue'
import { getActivePinia } from 'pinia'
import { useAuthStore } from '@/stores/auth'
import { hasPermission } from '@/utils/permission'
import { sectorDetailLocation } from '@/utils/sectorNavigation'
import type { RelatedBoardWinner, StockRelatedBoards } from '@/types/relatedBoards'
import RelatedBoardEmptyValue from '@/components/RelatedBoardEmptyValue.vue'
import RelatedBoardHistoryHint from '@/components/RelatedBoardHistoryHint.vue'
import AppHoverInfo from '@/components/AppHoverInfo'
import MarketBoardTag from '@/components/MarketBoardTag.vue'

const props = withDefaults(defineProps<{
  summary?: StockRelatedBoards | null
  boardType: 'industry' | 'concept'
  testId?: string
  returnPath?: string
}>(), {
  summary: null,
})

const auth = getActivePinia() ? useAuthStore() : null
const board = computed<RelatedBoardWinner | null>(() => {
  if (props.summary?.unavailable_reason) return null
  return props.summary?.[props.boardType] ?? null
})
const asOfDate = computed(() => board.value?.history?.as_of_date ?? props.summary?.as_of_date ?? null)
const benchmark = computed(() => board.value?.history?.benchmark ?? props.summary?.benchmark)
const unavailableReason = computed(() => props.summary?.unavailable_reason ?? null)
const emptyReason = computed(() => {
  if (unavailableReason.value) return null
  return props.boardType === 'industry'
    ? props.summary?.industry_empty_reason ?? null
    : props.summary?.concept_empty_reason ?? null
})
const canNavigate = computed(() => Boolean(
  board.value
  && auth
  && hasPermission(auth.role, auth.permissions, 'sectors:view'),
))
const sectorLocation = computed(() => sectorDetailLocation(
  board.value?.board_code ?? '',
  props.returnPath,
))

function formatCorrelation(value: number): string {
  if (!Number.isFinite(value)) return '—'
  return value.toLocaleString('zh-CN', { minimumFractionDigits: 0, maximumFractionDigits: 4 })
}
</script>

<template>
  <AppHoverInfo
    v-if="board"
    kind="popover"
    placement="bottom-start"
    :width="280"
  >
    <template #reference>
      <span class="related-board-cell__tag">
        <MarketBoardTag
          variant="tag"
          :name="board.name"
          :pct-chg="board.pct_chg"
          :to="canNavigate ? sectorLocation : undefined"
          :tabindex="canNavigate ? undefined : 0"
          :data-testid="testId"
          @click.stop
        />
        <RelatedBoardHistoryHint :history="board.history" :explain="false" />
      </span>
    </template>

    <div class="related-board-cell__popover" :aria-label="`${board.name}相关性说明`">
      <div class="related-board-cell__title">{{ board.name }}</div>
      <div v-if="board.history" class="related-board-cell__warning">
        当日共同有效样本不足，沿用 {{ board.history.as_of_date }} 的最近有效结果
      </div>
      <div v-if="board.confidence === 'low'" class="related-board-cell__warning">相关性较弱</div>
      <dl class="related-board-cell__metrics">
        <div><dt>综合相关度</dt><dd>{{ formatCorrelation(board.score) }}</dd></div>
        <div><dt>20 日相关度</dt><dd>{{ formatCorrelation(board.corr_20) }}</dd></div>
        <div><dt>60 日相关度</dt><dd>{{ formatCorrelation(board.corr_60) }}</dd></div>
        <div><dt>20 日有效样本</dt><dd>{{ board.sample_20 }}</dd></div>
        <div><dt>60 日有效样本</dt><dd>{{ board.sample_60 }}</dd></div>
        <div><dt>数据截止日</dt><dd>{{ asOfDate || '—' }}</dd></div>
        <div v-if="board.history"><dt>计算基准</dt><dd>{{ benchmark?.name || benchmark?.code || '—' }}</dd></div>
      </dl>
    </div>
  </AppHoverInfo>

  <AppHoverInfo
    v-else-if="unavailableReason === 'first_load_pending'"
    content="首次计算正在等待或执行，完成后将自动刷新"
    placement="top"
  >
    <span
      class="related-board-cell__empty related-board-cell__empty--pending"
      tabindex="0"
      aria-label="走势相关首次计算中"
      :data-testid="testId"
    >计算中</span>
  </AppHoverInfo>

  <RelatedBoardEmptyValue
    v-else
    :reason="emptyReason"
    :aria-label="`暂无${boardType === 'industry' ? '行业' : '概念'}走势`"
    :test-id="testId"
  />
</template>

<style scoped>
.related-board-cell__tag {
  display: inline-flex;
  max-width: 100%;
  min-width: 0;
  align-items: center;
  gap: var(--app-space-control-gap);
  vertical-align: middle;
}

.related-board-cell__tag > .market-board-tag {
  flex-shrink: 1;
  min-width: 0;
}

.related-board-cell__empty {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  vertical-align: middle;
  white-space: nowrap;
  line-height: var(--app-line-height-table);
  color: var(--app-placeholder-text);
}

.related-board-cell__empty--pending {
  color: var(--el-color-primary);
}

.related-board-cell__popover {
  color: var(--el-text-color-regular);
  font-size: var(--app-font-size-caption);
  line-height: var(--app-line-height-comfy);
}

.related-board-cell__title {
  color: var(--el-text-color-primary);
  font-weight: var(--app-font-weight-section);
}

.related-board-cell__warning {
  margin-top: var(--app-space-1);
  color: var(--app-warning-text);
  font-weight: var(--app-font-weight-strong);
}

.related-board-cell__metrics {
  display: grid;
  gap: var(--app-space-1);
  margin: var(--app-space-2) 0 0;
}

.related-board-cell__metrics > div {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: var(--app-space-3);
}

.related-board-cell__metrics dt,
.related-board-cell__metrics dd {
  margin: 0;
}

.related-board-cell__metrics dt {
  color: var(--el-text-color-secondary);
}

.related-board-cell__metrics dd {
  color: var(--el-text-color-primary);
  font-variant-numeric: tabular-nums;
}

</style>
