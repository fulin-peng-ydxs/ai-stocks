<script setup lang="ts">
import AppControlRow from '@/components/AppControlRow.vue'

withDefaults(defineProps<{
  label?: string
}>(), {
  label: '图表操作',
})
</script>

<template>
  <section class="chart-operation-bar" role="toolbar" :aria-label="label">
    <AppControlRow justify="start" class="chart-operation-bar__actions">
      <slot />
    </AppControlRow>
  </section>
</template>

<style scoped>
.chart-operation-bar {
  flex: 0 0 auto;
  padding: var(--app-space-1) var(--app-space-3);
  border-bottom: 1px solid var(--el-border-color-lighter);
  background: var(--el-bg-color);
}

.chart-operation-bar__actions {
  width: 100%;
}

.chart-operation-bar :deep(.page-segmented) {
  flex: 0 0 auto;
  height: var(--app-control-height-xs);
  padding: 1px;
}

.chart-operation-bar :deep(.page-segmented .seg-btn) {
  padding-inline: var(--app-space-control-gap);
}
</style>
