<script setup lang="ts">
withDefaults(defineProps<{
  interactive?: boolean
}>(), {
  interactive: false,
})
</script>

<template>
  <div class="stock-chart-splitter" :class="{ 'is-interactive': interactive }">
    <span v-if="interactive" aria-hidden="true" />
  </div>
</template>

<style scoped>
.stock-chart-splitter {
  position: relative;
  z-index: 2;
  flex: 0 0 8px;
  height: 8px;
  box-sizing: border-box;
  background: var(--el-bg-color);
  border-top: 1px solid var(--el-border-color-lighter);
  border-bottom: 1px solid var(--el-border-color-lighter);
  outline: none;
}

.stock-chart-splitter.is-interactive {
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: row-resize;
  touch-action: none;
}

.stock-chart-splitter > span {
  width: 42px;
  height: 2px;
  border-radius: 1px;
  background: var(--el-border-color);
}

.stock-chart-splitter.is-interactive:hover,
.stock-chart-splitter.is-interactive:focus-visible {
  background: var(--el-color-primary-light-9);
}

.stock-chart-splitter.is-interactive:focus-visible {
  box-shadow: inset 0 0 0 2px var(--el-color-primary);
}

.stock-chart-splitter.is-interactive:hover > span,
.stock-chart-splitter.is-interactive:focus-visible > span {
  background: var(--el-color-primary);
}

@media (prefers-reduced-motion: reduce) {
  .stock-chart-splitter,
  .stock-chart-splitter > span {
    transition: none;
  }
}
</style>
