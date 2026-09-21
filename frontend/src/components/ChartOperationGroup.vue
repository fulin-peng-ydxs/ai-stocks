<script setup lang="ts">
import AppControlItem from '@/components/AppControlItem.vue'

defineProps<{
  label: string
}>()
</script>

<template>
  <AppControlItem :label="label" class="chart-operation-group">
    <slot />
  </AppControlItem>
</template>

<style scoped>
.chart-operation-group {
  box-sizing: border-box;
  height: var(--app-control-height-sm);
  padding: 1px 1px 1px var(--app-space-2);
  border: 1px solid var(--el-border-color);
  border-radius: var(--layout-control-radius);
  background: var(--app-section-bg);
}

.chart-operation-group :deep(.app-control-item__label) {
  font-size: var(--app-font-size-caption);
  line-height: var(--app-line-height-caption);
}
</style>
