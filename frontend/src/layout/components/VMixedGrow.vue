<script setup lang="ts">
/**
 * 混合成长区（规范 §8 / §4-F）：固定分析块（flex:0 0 auto 自然高）+ 一张主表/主图（flex:1 + 业务最低高 + 内部内滚）。
 * 容器 overflow:auto 兜底：放得下→主表 grow 填满内滚；放不下→容器整体滚动不裁切。
 * 由 LayoutHost 在「多组件 + 恰一个 growMain」时选用，slot 内容按 slots[].id 具名传入。
 */
import { COMPONENT_CATALOG } from '../components'
import type { SlotSpec } from '../schema'

const props = defineProps<{ slots: SlotSpec[] }>()

const minHeightOf = (s: SlotSpec): number => s.minH ?? COMPONENT_CATALOG[s.component]?.minH ?? 0
</script>

<template>
  <div class="v-mixed">
    <template v-for="s in props.slots" :key="s.id">
      <div
        :class="s.growMain ? 'v-mixed-main' : 'v-mixed-fixed'"
        :style="s.growMain ? { minHeight: minHeightOf(s) + 'px' } : undefined"
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
  overflow: auto;
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
