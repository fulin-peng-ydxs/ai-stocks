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
    title-size="compact"
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
  display: flex;
  flex-direction: column;
  gap: var(--app-space-4);
}
</style>
