<script setup lang="ts">
withDefaults(defineProps<{
  align?: 'center' | 'start' | 'end' | 'baseline'
  justify?: 'start' | 'end' | 'between'
  fill?: boolean
}>(), {
  align: 'center',
  justify: 'start',
  fill: false,
})
</script>

<template>
  <div
    class="app-control-row"
    :class="[
      `is-align-${align}`,
      `is-justify-${justify}`,
      { 'is-fill': fill },
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
}
.app-control-row.is-fill :deep(> *) {
  flex: 1 1 auto;
}
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
