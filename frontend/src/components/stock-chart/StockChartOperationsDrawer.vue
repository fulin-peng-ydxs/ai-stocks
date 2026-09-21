<script setup lang="ts">
import PageDrawer from '@/components/PageDrawer.vue'

defineProps<{
  modelValue: boolean
  drawerId: string
}>()

defineEmits<{
  'update:modelValue': [value: boolean]
  closed: []
}>()
</script>

<template>
  <PageDrawer
    :id="drawerId"
    :model-value="modelValue"
    title="图表操作"
    size="sm"
    modal-class="stock-chart-operations-modal"
    destroy-on-close
    @update:model-value="$emit('update:modelValue', $event)"
    @closed="$emit('closed')"
  >
    <div class="stock-chart-operations-drawer" role="toolbar" aria-label="K线图表操作">
      <slot />
    </div>
  </PageDrawer>
</template>

<style scoped>
.stock-chart-operations-drawer {
  min-width: 0;
  display: grid;
  align-content: start;
  gap: var(--app-space-3);
}
</style>

<style>
.el-overlay.stock-chart-operations-modal {
  overflow: hidden;
  border-radius: inherit;
}

.stock-chart-operations-modal .el-drawer {
  max-width: 88%;
}

.stock-chart-operations-modal .el-drawer__header {
  margin-bottom: 0;
  padding-bottom: var(--app-space-3);
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.stock-chart-operations-modal .el-drawer__body {
  padding: var(--app-space-3);
}

.stock-chart-operations-modal .chart-operation-group {
  width: 100%;
  height: auto;
  min-height: var(--app-control-height-md);
  padding: var(--app-space-2);
  justify-content: space-between;
}
</style>
