<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink, type RouteLocationRaw } from 'vue-router'

const props = withDefaults(defineProps<{
  name: string
  pctChg?: number | null
  related?: boolean
  to?: RouteLocationRaw
}>(), {
  pctChg: null,
  related: false,
  to: undefined,
})

const pctText = computed(() => {
  const value = props.pctChg
  if (value == null || !Number.isFinite(value)) return '—'
  return `${value > 0 ? '+' : ''}${value.toFixed(2)}%`
})

const tagClass = computed(() => ({
  'is-related': props.related,
  'is-link': !!props.to,
  'is-up': props.pctChg != null && props.pctChg > 0,
  'is-down': props.pctChg != null && props.pctChg < 0,
}))
</script>

<template>
  <component
    :is="to ? RouterLink : 'span'"
    class="market-board-tag__link"
    :to="to"
  >
    <el-tag size="default" effect="plain" class="market-board-tag" :class="tagClass">
      <span class="market-board-tag__name">{{ name }}</span>
      <span class="market-board-tag__pct">{{ pctText }}</span>
      <span v-if="related" class="market-board-tag__badge">最相关</span>
    </el-tag>
  </component>
</template>

<style scoped>
.market-board-tag__link {
  display: inline-flex;
  max-width: 100%;
  min-width: 0;
  text-decoration: none;
}

.market-board-tag {
  max-width: 100%;
  --el-tag-text-color: var(--el-text-color-regular);
}

.market-board-tag :deep(.el-tag__content) {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: var(--app-space-control-gap);
}

.market-board-tag.is-related {
  --el-tag-border-color: var(--el-color-primary);
}

.market-board-tag.is-link:hover {
  --el-tag-bg-color: var(--el-color-primary-light-9);
}

.market-board-tag__link:focus-visible {
  border-radius: var(--el-border-radius-small);
  outline: 2px solid var(--el-color-primary);
  outline-offset: 2px;
}

.market-board-tag__name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.market-board-tag__pct {
  flex: 0 0 auto;
  font-variant-numeric: tabular-nums;
}

.market-board-tag.is-up .market-board-tag__pct {
  color: var(--market-up-color);
}

.market-board-tag.is-down .market-board-tag__pct {
  color: var(--market-down-color);
}

.market-board-tag__badge {
  flex: 0 0 auto;
  color: var(--el-color-primary);
  font-size: var(--app-font-size-micro);
}
</style>
