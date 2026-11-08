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
  gap: var(--el-border-width);
  margin: 0;
  /* 间隙只容纳一条接缝；外沿由此容器绘制并裁去子项向外投影。 */
  overflow: hidden;
  background: var(--el-bg-color);
  border: 1px solid var(--app-border-subtle);
  border-radius: var(--layout-card-radius);
}
@container app-viewport (max-width: 760px) {
  .app-detail-fields { grid-template-columns: 1fr; }
}
</style>
