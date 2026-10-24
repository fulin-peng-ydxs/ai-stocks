<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink, type RouteLocationRaw } from 'vue-router'
import { formatMarketPercent, marketValueClass } from '@/utils/marketValue'

const props = withDefaults(defineProps<{
  name: string
  pctChg?: number | null
  related?: boolean
  showRelatedLabel?: boolean
  to?: RouteLocationRaw
}>(), {
  pctChg: null,
  related: false,
  showRelatedLabel: true,
  to: undefined,
})

const pctText = computed(() => formatMarketPercent(props.pctChg))
const tagClass = computed(() => ({
  'is-related': props.related,
  'is-link': !!props.to,
  'is-up': marketValueClass(props.pctChg) === 'up',
  'is-down': marketValueClass(props.pctChg) === 'down',
}))
</script>

<template>
  <component
    :is="to ? RouterLink : 'span'"
    class="market-board-tag__link market-board-tag"
    :class="tagClass"
    :to="to"
  >
    <span v-if="related && showRelatedLabel" class="market-board-tag__badge">走势最相关</span>
    <span class="market-board-tag__name">{{ name }}</span>
    <span class="market-board-tag__pct">{{ pctText }}</span>
  </component>
</template>

<style scoped>
.market-board-tag {
  --board-direction: var(--el-text-color-secondary);
  position: relative;
  display: flex;
  box-sizing: border-box;
  min-width: 64px;
  max-width: 100%;
  min-height: 48px;
  flex: 0 0 auto;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0;
  padding: var(--app-space-2) var(--app-space-2) var(--app-space-1);
  border: 1px solid transparent;
  border-radius: var(--el-border-radius-base);
  background: color-mix(in srgb, var(--board-direction) 10%, var(--el-bg-color));
  color: var(--el-text-color-primary);
  text-align: center;
  text-decoration: none;
}
.market-board-tag.is-up { --board-direction: var(--market-up-color); }
.market-board-tag.is-down { --board-direction: var(--market-down-color); }
.market-board-tag.is-related { border-color: var(--board-direction); }
.market-board-tag.is-link:hover { border-color: var(--board-direction); }
.market-board-tag__link:focus-visible {
  outline: var(--app-focus-ring);
  outline-offset: 2px;
}
.market-board-tag__name {
  max-width: 100%;
  overflow-wrap: anywhere;
  font-size: var(--app-font-size-caption);
  line-height: var(--app-line-height-caption);
}
.market-board-tag__pct {
  color: var(--board-direction);
  font-size: var(--app-font-size-caption);
  font-weight: var(--app-font-weight-section);
  line-height: var(--app-line-height-caption);
  font-variant-numeric: tabular-nums;
}
.market-board-tag__badge {
  position: absolute;
  top: 0;
  right: 0;
  transform: translateY(-50%);
  padding: 0 var(--app-space-1);
  border-radius: var(--el-border-radius-small);
  background: var(--el-color-warning);
  color: var(--el-color-white);
  font-size: var(--app-font-size-micro);
  line-height: var(--app-line-height-caption);
  white-space: nowrap;
}
</style>
