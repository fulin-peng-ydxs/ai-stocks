<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import type { LimitLadderStock, LimitLadderWindow } from '@/api/limitLadder'
import { formatMarketPercent, marketValueClass } from '@/utils/marketValue'
import { sectorDetailLocation } from '@/utils/sectorNavigation'
import RelatedBoardEmptyValue from '@/components/RelatedBoardEmptyValue.vue'

const props = defineProps<{
  stock: LimitLadderStock
  window: LimitLadderWindow
  canViewSectors: boolean
  selected?: boolean
  returnPath?: string
}>()

const emit = defineEmits<{ select: [stock: LimitLadderStock] }>()

const relatedLocation = computed(() => sectorDetailLocation(
  props.stock.latest_related_concept?.board_code ?? '',
  props.returnPath,
))
const shortHistory = computed(() => (
  props.stock.actual_trade_days != null && props.stock.actual_trade_days < props.window
))
const windowLimitUpDays = computed(() => props.stock.window_limit_up_days)
const hasMultipleLimitUps = computed(() => (windowLimitUpDays.value ?? 0) > 1)
const relatedIndustryName = computed(() => (
  props.stock.latest_related_industry?.board_name || ''
))

function selectCard(): void {
  emit('select', props.stock)
}
</script>

<template>
  <article
    class="limit-ladder-card"
    :class="{ 'limit-ladder-card--selected': selected }"
    :aria-current="selected ? 'true' : undefined"
    :data-testid="`limit-ladder-card-${stock.code}`"
    :data-stock-code="stock.code"
  >
    <el-button
      native-type="button"
      class="limit-ladder-card__select"
      :aria-current="selected ? 'true' : undefined"
      :aria-label="`选择${stock.name}查看走势`"
      :data-testid="`limit-ladder-card-select-${stock.code}`"
      @click="selectCard"
    >
      <span class="limit-ladder-card__head">
        <span class="limit-ladder-card__identity">
          <strong :title="stock.name">{{ stock.name }}</strong>
          <span>{{ stock.code }}</span>
        </span>
        <span class="limit-ladder-card__return">
          <span>累计涨幅</span>
          <strong :class="marketValueClass(stock.window_return_pct)">
            {{ formatMarketPercent(stock.window_return_pct) }}
          </strong>
        </span>
      </span>

      <span class="limit-ladder-card__metrics">
        <span class="limit-ladder-card__window-stat">
          {{ window }} 日
          <b :class="{ 'is-multiple': hasMultipleLimitUps }">
            {{ windowLimitUpDays ?? '—' }}
          </b>
          板
        </span>
        <el-tag v-if="stock.is_st" size="small" type="danger" effect="plain">ST</el-tag>
        <el-tag v-if="stock.is_one_word" size="small" type="warning" effect="plain">一字</el-tag>
      </span>

      <span v-if="shortHistory" class="limit-ladder-card__history" data-testid="limit-ladder-short-history">
        窗口仅 {{ stock.actual_trade_days }} 日 · 自 {{ stock.window_start_date || '—' }} 起
      </span>
    </el-button>

    <footer class="limit-ladder-card__foot">
      <span>{{ stock.board }}</span>
      <span aria-hidden="true">·</span>
      <span class="limit-ladder-card__industry" :title="relatedIndustryName || undefined" data-testid="limit-ladder-related-industry">
        <template v-if="relatedIndustryName">{{ relatedIndustryName }}</template>
        <RelatedBoardEmptyValue
          v-else
          :reason="stock.latest_related_industry_empty_reason"
          aria-label="暂无行业走势"
        />
      </span>
      <span aria-hidden="true">·</span>
      <span v-if="stock.latest_related_concept" class="limit-ladder-card__concept">
        <RouterLink
          v-if="canViewSectors"
          :to="relatedLocation"
          :title="stock.latest_related_concept.board_name"
          :aria-label="`进入${stock.latest_related_concept.board_name}板块行情`"
          :data-testid="`limit-ladder-related-${stock.code}`"
          @click.stop
        >{{ stock.latest_related_concept.board_name }} ↗</RouterLink>
        <span v-else :title="stock.latest_related_concept.board_name">{{ stock.latest_related_concept.board_name }}</span>
      </span>
      <RelatedBoardEmptyValue
        v-else
        :reason="stock.latest_related_concept_empty_reason"
        aria-label="暂无概念走势"
      />
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
  transition: border-color .15s ease, box-shadow .15s ease, transform .15s ease;
}
.limit-ladder-card:has(.limit-ladder-card__select:hover) {
  border-color: var(--el-color-primary-light-5);
  box-shadow: var(--el-box-shadow-light);
  transform: translateY(-1px);
}
.limit-ladder-card--selected {
  border-color: var(--el-color-primary);
  box-shadow: inset 3px 0 0 var(--el-color-primary), var(--el-box-shadow-light);
}
.limit-ladder-card__select.el-button:focus-visible {
  outline: 2px solid var(--el-color-primary);
  outline-offset: 2px;
}
.limit-ladder-card .limit-ladder-card__select.el-button {
  --el-button-text-color: inherit;
  --el-button-bg-color: transparent;
  --el-button-border-color: transparent;
  --el-button-hover-text-color: inherit;
  --el-button-hover-bg-color: transparent;
  --el-button-hover-border-color: transparent;
  --el-button-active-text-color: inherit;
  --el-button-active-bg-color: transparent;
  --el-button-active-border-color: transparent;
  display: block;
  width: 100%;
  height: auto;
  min-height: 0;
  margin: 0;
  padding: 0;
  border: 0;
  background: transparent;
  color: inherit;
  cursor: pointer;
  font: inherit;
  line-height: var(--app-line-height-table);
  text-align: left;
  white-space: normal;
}
.limit-ladder-card .limit-ladder-card__select.el-button > :deep(span) {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  width: 100%;
}
.limit-ladder-card__metrics,
.limit-ladder-card__foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-2);
}
.limit-ladder-card__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--app-space-2);
}
.limit-ladder-card__identity {
  display: flex;
  flex-direction: column;
  flex: 1 1 auto;
  align-items: flex-start;
  gap: 0;
  min-width: 0;
}
.limit-ladder-card__identity strong,
.limit-ladder-card__identity span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.limit-ladder-card__identity strong {
  width: 100%;
}
.limit-ladder-card__identity span {
  width: 100%;
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
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
.limit-ladder-card__history {
  display: block;
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
