<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import type { LimitLadderStock, LimitLadderWindow } from '@/api/limitLadder'
import { formatMarketPercent, marketValueClass } from '@/utils/marketValue'

const props = defineProps<{
  stock: LimitLadderStock
  window: LimitLadderWindow
  canViewSectors: boolean
  selected?: boolean
  returnPath?: string
}>()

const emit = defineEmits<{ select: [stock: LimitLadderStock] }>()

const relatedLocation = computed(() => ({
  path: `/sectors/${encodeURIComponent(props.stock.latest_related_concept?.board_code ?? '')}`,
  query: props.returnPath ? { return_to: props.returnPath } : undefined,
}))
const shortHistory = computed(() => (
  props.stock.actual_trade_days != null && props.stock.actual_trade_days < props.window
))
const windowLimitUpDays = computed(() => props.stock.window_limit_up_days)
const usesConsecutiveStreak = computed(() => props.stock.consecutive_days > 1)
const displayDays = computed(() => (
  usesConsecutiveStreak.value ? props.stock.consecutive_days : props.window
))
const displayLimitUpDays = computed(() => (
  usesConsecutiveStreak.value ? props.stock.consecutive_days : windowLimitUpDays.value
))
const relatedIndustryName = computed(() => (
  props.stock.latest_related_industry?.board_name || '未分类'
))

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
      </div>
      <div class="limit-ladder-card__return">
        <span>{{ window }} 日累计</span>
        <strong :class="marketValueClass(stock.window_return_pct)">
          {{ formatMarketPercent(stock.window_return_pct) }}
        </strong>
      </div>
    </header>

    <div class="limit-ladder-card__metrics">
      <span
        class="limit-ladder-card__window-stat"
        :class="{ 'is-streak': usesConsecutiveStreak }"
      >
        {{ displayDays }} 日
        <b :class="{ 'is-multiple': !usesConsecutiveStreak && (displayLimitUpDays ?? 0) > 1 }">
          {{ displayLimitUpDays ?? '—' }}
        </b>
        板
      </span>
      <el-tag v-if="stock.is_st" size="small" type="danger" effect="plain">ST</el-tag>
      <el-tag v-if="stock.is_one_word" size="small" type="warning" effect="plain">一字</el-tag>
    </div>

    <p v-if="shortHistory" class="limit-ladder-card__history" data-testid="limit-ladder-short-history">
      窗口仅 {{ stock.actual_trade_days }} 日 · 自 {{ stock.window_start_date || '—' }} 起
    </p>

    <footer class="limit-ladder-card__foot">
      <span>{{ stock.board }}</span>
      <span aria-hidden="true">·</span>
      <span class="limit-ladder-card__industry" data-testid="limit-ladder-related-industry">
        {{ relatedIndustryName }}
      </span>
      <span aria-hidden="true">·</span>
      <span v-if="stock.latest_related_concept" class="limit-ladder-card__concept">
        <RouterLink
          v-if="canViewSectors"
          :to="relatedLocation"
          :aria-label="`进入${stock.latest_related_concept.board_name}板块行情`"
          :data-testid="`limit-ladder-related-${stock.code}`"
          @click.stop
        >{{ stock.latest_related_concept.board_name }} ↗</RouterLink>
        <span v-else tabindex="0">{{ stock.latest_related_concept.board_name }}</span>
      </span>
      <span v-else class="limit-ladder-card__empty">暂无相关概念</span>
    </footer>
  </article>
</template>

<style scoped>
.limit-ladder-card {
  min-width: 0;
  padding: var(--app-space-2);
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
.limit-ladder-card__metrics,
.limit-ladder-card__head,
.limit-ladder-card__foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-2);
}
.limit-ladder-card__identity {
  flex: 1 1 auto;
  min-width: 0;
}
.limit-ladder-card__identity strong {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.limit-ladder-card__foot small,
.limit-ladder-card__history {
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
}
.limit-ladder-card__return {
  display: grid;
  flex: none;
  justify-items: end;
  font-variant-numeric: tabular-nums;
}
.limit-ladder-card__return span {
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
}
.limit-ladder-card__return strong {
  font-size: var(--app-font-size-table);
  font-weight: var(--app-font-weight-strong);
}
.limit-ladder-card__metrics {
  justify-content: flex-start;
  flex-wrap: wrap;
  margin-top: var(--app-space-1);
  color: var(--el-text-color-regular);
  font-size: var(--app-font-size-table);
}
.limit-ladder-card__window-stat b {
  color: inherit;
  font-weight: var(--app-font-weight-strong);
  font-variant-numeric: tabular-nums;
}
.limit-ladder-card__window-stat b.is-multiple {
  color: var(--market-up-color);
}
.limit-ladder-card__window-stat.is-streak,
.limit-ladder-card__window-stat.is-streak b {
  color: var(--market-up-color);
  font-weight: var(--app-font-weight-strong);
}
.limit-ladder-card__history {
  margin: var(--app-space-1) 0 0;
  color: var(--app-warning-text);
  line-height: var(--app-line-height-comfy);
}
.limit-ladder-card__foot {
  display: flex;
  width: 100%;
  overflow: hidden;
  gap: var(--app-space-control-gap);
  align-items: center;
  justify-content: flex-start;
  margin-top: var(--app-space-2);
  padding-top: var(--app-space-1);
  border-top: 1px solid var(--el-border-color-extra-light);
  color: var(--el-text-color-regular);
  font-size: var(--app-font-size-caption);
}
.limit-ladder-card__foot > span:first-child,
.limit-ladder-card__foot > span:nth-child(2),
.limit-ladder-card__foot > span:nth-child(4) {
  flex: none;
}
.limit-ladder-card__industry,
.limit-ladder-card__concept {
  flex: 1 1 auto;
  text-align: left;
}
.limit-ladder-card__foot span,
.limit-ladder-card__foot a,
.limit-ladder-card__foot small {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.limit-ladder-card__concept a {
  display: inline;
  color: var(--el-color-primary);
  text-decoration: none;
}
.limit-ladder-card__concept a:hover { text-decoration: underline; }
.limit-ladder-card__empty { color: var(--app-placeholder-text); }
</style>
