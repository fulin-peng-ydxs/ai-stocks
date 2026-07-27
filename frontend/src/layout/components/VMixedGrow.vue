<script setup lang="ts">
/**
 * 混合成长区（规范 §8 / §4-F）：固定分析块（flex:0 0 auto 自然高）+ 一张主表/主图（flex:1 + 内部内滚）。
 * 组件目录的 minH 用于布局校验和设计预览；真实低视口中成长区必须允许收缩，
 * 把有限空间交给表体滚动，不能反向撑高容器并切掉固定分析块。
 * 由 LayoutHost 在「多组件 + 恰一个 growMain」时选用，slot 内容按 slots[].id 具名传入。
 */
import type { SlotSpec } from '../schema'

const props = defineProps<{ slots: SlotSpec[] }>()
</script>

<template>
  <div class="v-mixed" data-testid="layout-mixed-region">
    <template v-for="s in props.slots" :key="s.id">
      <div
        :class="s.growMain ? 'v-mixed-main' : 'v-mixed-fixed'"
        :data-testid="s.growMain ? 'layout-grow-region' : undefined"
      >
        <slot :name="s.id" />
      </div>
    </template>
  </div>
</template>

<style scoped>
.v-mixed {
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  gap: var(--app-space-3);
}
.v-mixed-fixed {
  flex: 0 0 auto;
}
/* 主表/主图：吃富余空间且内部内滚，写法对齐 global.css 的 .v-grow */
.v-mixed-main {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.v-mixed-main :deep(.el-card) {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.v-mixed-main :deep(.el-card > .el-card__body) {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.v-mixed-main :deep(.el-table) {
  flex: 1 1 auto;
  min-height: 0;
}
</style>
