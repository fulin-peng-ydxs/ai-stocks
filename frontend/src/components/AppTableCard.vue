<template>
  <!-- 外框归结果区域所有：切换表格、骨架或错误反馈时保留同一个边界。 -->
  <el-card shadow="never" class="app-table-card">
    <template v-if="$slots.header" #header><slot name="header" /></template>
    <slot />
  </el-card>
</template>

<style scoped>
.app-table-card {
  display: flex;
  flex-direction: column;
  flex: 1 1 auto;
  min-width: 0;
  min-height: 0;
}

.app-table-card > :deep(.el-card__body) {
  display: flex;
  flex-direction: column;
  flex: 1 1 auto;
  min-height: 0;
  padding: 0;
}

.app-table-card > :deep(.el-card__header) {
  flex: 0 0 auto;
}

.app-table-card > :deep(.el-card__body > .app-state-block) {
  flex: 1 1 auto;
  height: auto;
  margin: var(--layout-card-padding);
}

.app-table-card > :deep(.el-card__body > .app-data-table > .app-data-table__pager) {
  padding: var(--app-space-3) var(--layout-card-padding);
}
</style>
