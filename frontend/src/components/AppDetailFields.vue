<script setup lang="ts">
withDefaults(defineProps<{ columns?: 1 | 2 | 3 }>(), { columns: 2 })
</script>

<template>
  <dl class="app-detail-fields" :style="{ '--app-detail-columns': columns }">
    <slot />
  </dl>
</template>

<style scoped>
.app-detail-fields {
  display: grid;
  grid-template-columns: repeat(var(--app-detail-columns), minmax(0, 1fr));
  gap: 0;
  margin: 0;
  overflow: hidden;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: var(--app-radius-card);
}
@container app-viewport (max-width: 760px) {
  .app-detail-fields { grid-template-columns: 1fr; }
}
</style>
