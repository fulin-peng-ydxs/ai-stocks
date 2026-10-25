<script setup lang="ts">
import { useControlRowSizing, type ControlRowSize } from './controlRowSizing'

withDefaults(defineProps<{
  size?: ControlRowSize
  align?: 'center' | 'start' | 'end' | 'baseline'
  justify?: 'start' | 'end' | 'between'
  fill?: boolean
  /** 关联阈值与动作需作为一组换行时，在内层行关闭换行。 */
  wrap?: boolean
}>(), {
  align: 'center',
  justify: 'start',
  fill: false,
  wrap: true,
})
const row = useControlRowSizing()
</script>

<template>
  <div
    class="app-control-row app-control-row-scope"
    :style="row.style.value"
    :data-control-row="row.size.value"
    :class="[
      `is-align-${align}`,
      `is-justify-${justify}`,
      { 'is-fill': fill },
      { 'is-nowrap': !wrap },
    ]"
  >
    <slot />
  </div>
</template>

<style scoped>
.app-control-row {
  display: flex;
  flex-wrap: wrap;
  gap: var(--app-density-control-gap, var(--app-space-2));
  min-width: 0;
  min-height: var(--app-control-row-height);
}
.app-control-row.is-fill :deep(> *) {
  flex: 1 1 auto;
}
.app-control-row.is-nowrap { flex-wrap: nowrap; }
.is-align-center { align-items: center; }
.is-align-start { align-items: flex-start; }
.is-align-end { align-items: flex-end; }
.is-align-baseline { align-items: baseline; }
.is-justify-start { justify-content: flex-start; }
.is-justify-end { justify-content: flex-end; }
.is-justify-between { justify-content: space-between; }
.app-control-row :deep(> *) {
  max-width: 100%;
}
</style>
