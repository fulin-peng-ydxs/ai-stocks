<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import type { LimitLadderStock, LimitLadderWindow } from '@/api/limitLadder'

const props = defineProps<{
  stock: LimitLadderStock
  window: LimitLadderWindow
  canViewSectors: boolean
  selected?: boolean
}>()

const emit = defineEmits<{ select: [stock: LimitLadderStock] }>()

const relatedPath = computed(() => (
  `/sectors/${encodeURIComponent(props.stock.latest_related_concept?.board_code ?? '')}`
))
const shortHistory = computed(() => (
  props.stock.actual_trade_days != null && props.stock.actual_trade_days < props.window
))
const amountText = computed(() => {
  const value = Number(props.stock.amount)
  if (!Number.isFinite(value)) return '—'
  if (value >= 1e8) return `${(value / 1e8).toFixed(2)} 亿`
  if (value >= 1e4) return `${(value / 1e4).toFixed(0)} 万`
  return value.toLocaleString('zh-CN')
})
const limitText = computed(() => `${(Number(props.stock.price_limit_pct) * 100).toFixed(0)}%`)

function selectCard(): void {
  emit('select', props.stock)
}
</script>

<template>
  <article
    class="limit-ladder-card"
    :class="{ 'limit-ladder-card--selected': selected }"
    tabindex="0"
    :aria-current="selected ? 'true' : undefined"
    :aria-label="`选择${stock.name}查看走势`"
    :data-testid="`limit-ladder-card-${stock.code}`"
    :data-stock-code="stock.code"
    @click="selectCard"
    @keydown.enter.prevent="selectCard"
    @keydown.space.prevent="selectCard"
  >
    <header class="limit-ladder-card__head">
      <div class="limit-ladder-card__identity">
        <strong>{{ stock.name }}</strong>
        <span>{{ stock.code }}</span>
      </div>
      <span class="limit-ladder-card__limit">+{{ limitText }}</span>
    </header>

    <div class="limit-ladder-card__metrics">
      <strong>{{ stock.consecutive_days === 1 ? '首板' : `${stock.consecutive_days} 连板` }}</strong>
      <span>{{ window }} 日 {{ stock.window_limit_up_days ?? '—' }} 板</span>
      <el-tag v-if="stock.is_st" size="small" type="danger" effect="plain">ST</el-tag>
      <el-tag v-if="stock.is_one_word" size="small" type="warning" effect="plain">一字</el-tag>
    </div>

    <p v-if="shortHistory" class="limit-ladder-card__history" data-testid="limit-ladder-short-history">
      上市历史不足 {{ window }} 个交易日，实际自 {{ stock.window_start_date || '—' }} 起（{{ stock.actual_trade_days }} 日）
    </p>

    <footer class="limit-ladder-card__foot">
      <div>
        <span>{{ stock.board }} · {{ stock.industry_name || '未分类' }}</span>
        <small>成交额 {{ amountText }}</small>
      </div>
      <div v-if="stock.latest_related_concept" class="limit-ladder-card__concept">
        <RouterLink
          v-if="canViewSectors"
          :to="relatedPath"
          :aria-label="`进入${stock.latest_related_concept.board_name}板块行情`"
          :data-testid="`limit-ladder-related-${stock.code}`"
          @click.stop
        >{{ stock.latest_related_concept.board_name }} ↗</RouterLink>
        <span v-else tabindex="0">{{ stock.latest_related_concept.board_name }}</span>
        <small>截至 {{ stock.latest_related_concept.as_of_date }}</small>
      </div>
      <span v-else class="limit-ladder-card__empty">暂无相关概念</span>
    </footer>
  </article>
</template>

<style scoped>
.limit-ladder-card {
  min-width: 0;
  padding: var(--app-space-3);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: var(--layout-card-radius);
  background: var(--el-bg-color);
  box-shadow: var(--el-box-shadow-lighter);
  cursor: pointer;
  transition: border-color .15s ease, box-shadow .15s ease, transform .15s ease;
}
.limit-ladder-card:hover {
  border-color: var(--el-color-primary-light-5);
  box-shadow: var(--el-box-shadow-light);
  transform: translateY(-1px);
}
.limit-ladder-card--selected {
  border-color: var(--el-color-primary);
  box-shadow: inset 3px 0 0 var(--el-color-primary), var(--el-box-shadow-light);
}
.limit-ladder-card:focus-visible {
  outline: 2px solid var(--el-color-primary);
  outline-offset: 2px;
}
.limit-ladder-card__head,
.limit-ladder-card__metrics,
.limit-ladder-card__foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-2);
}
.limit-ladder-card__identity {
  min-width: 0;
}
.limit-ladder-card__identity strong,
.limit-ladder-card__identity span {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.limit-ladder-card__identity span,
.limit-ladder-card__foot small,
.limit-ladder-card__history {
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
}
.limit-ladder-card__limit {
  color: var(--app-market-up, var(--el-color-danger));
  font-weight: var(--app-font-weight-strong);
  font-variant-numeric: tabular-nums;
}
.limit-ladder-card__metrics {
  justify-content: flex-start;
  margin-top: var(--app-space-2);
  color: var(--el-text-color-regular);
  font-size: var(--app-font-size-table);
}
.limit-ladder-card__metrics strong {
  color: var(--app-market-up, var(--el-color-danger));
}
.limit-ladder-card__history {
  margin: var(--app-space-2) 0 0;
  color: var(--app-warning-text);
  line-height: var(--app-line-height-comfy);
}
.limit-ladder-card__foot {
  align-items: flex-end;
  margin-top: var(--app-space-3);
  padding-top: var(--app-space-2);
  border-top: 1px solid var(--el-border-color-extra-light);
  font-size: var(--app-font-size-caption);
}
.limit-ladder-card__foot > div:first-child,
.limit-ladder-card__concept {
  display: grid;
  min-width: 0;
  gap: var(--app-space-1);
}
.limit-ladder-card__concept {
  justify-items: end;
  text-align: right;
}
.limit-ladder-card__concept a {
  color: var(--el-color-primary);
  text-decoration: none;
}
.limit-ladder-card__concept a:hover { text-decoration: underline; }
.limit-ladder-card__empty { color: var(--app-placeholder-text); }
@media (max-width: 720px) {
  .limit-ladder-card__foot { align-items: flex-start; flex-direction: column; }
  .limit-ladder-card__concept { justify-items: start; text-align: left; }
}
</style>
