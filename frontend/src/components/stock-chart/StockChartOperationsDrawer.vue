<script setup lang="ts">
import PageDrawer from '@/components/PageDrawer.vue'
import PageDrawerSurface from '@/components/PageDrawerSurface.vue'

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
    surface
    destroy-on-close
    @update:model-value="$emit('update:modelValue', $event)"
    @closed="$emit('closed')"
  >
    <PageDrawerSurface
      title="图表操作"
      title-size="compact"
      close-label="关闭图表操作"
      @close="$emit('update:modelValue', false)"
    >
      <div class="stock-chart-operations-drawer" role="toolbar" aria-label="K线图表操作">
        <slot />
      </div>
    </PageDrawerSurface>
  </PageDrawer>
</template>
