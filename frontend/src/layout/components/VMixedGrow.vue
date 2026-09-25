<script setup lang="ts">
/**
 * 混合成长区（规范 §8 / §4-F）：固定分析块 + 一张主表/主图（flex:1 + 内部内滚）。
 * 固定块声明 idealH 时，可在空间不足时从理想高度收缩到 minH；未声明时保持自然高且不收缩。
 * growMain 的业务 minH 同时参与运行时：余量足够时主组件内滚，余量不足时
 * 整个主内容区滚动兜底，避免把表格/标签工作区压到不可用。
 * 由 LayoutHost 在「多组件 + 恰一个 growMain」时选用，slot 内容按 slots[].id 具名传入。
 */
import type { SlotSpec } from '../schema'
import { COMPONENT_CATALOG } from '../components'

const props = defineProps<{ slots: SlotSpec[] }>()

function minHeight(slot: SlotSpec): string | undefined {
  if (!slot.growMain && slot.idealH == null) return undefined
  return `${slot.minH ?? COMPONENT_CATALOG[slot.component]?.minH ?? 0}px`
}

function slotStyle(slot: SlotSpec): Record<string, string> | undefined {
  if (slot.growMain) return { minHeight: minHeight(slot)! }
  if (slot.idealH == null) return undefined
  return {
    minHeight: minHeight(slot)!,
    maxHeight: `${slot.idealH}px`,
  }
}
</script>

<template>
  <div class="v-mixed" data-testid="layout-mixed-region">
    <template v-for="s in props.slots" :key="s.id">
      <div
        :class="[
          s.growMain ? 'v-mixed-main' : 'v-mixed-fixed',
          { 'v-mixed-fixed--shrinkable': !s.growMain && s.idealH != null },
        ]"
        :data-testid="s.growMain ? 'layout-grow-region' : undefined"
        :style="slotStyle(s)"
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
.v-mixed-fixed--shrinkable {
  flex: 0 1 auto;
  min-height: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.v-mixed-fixed--shrinkable > :deep(.el-card) {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.v-mixed-fixed--shrinkable > :deep(.el-card > .el-card__body) {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.v-mixed-fixed--shrinkable :deep(.app-data-table--embedded) {
  flex: 1 1 auto;
  min-height: 0;
}
.v-mixed-fixed--shrinkable :deep(.el-table) {
  max-height: 100% !important;
}
/* 主表/主图：吃富余空间且内部内滚；不足 minH 时由外层主内容区滚动兜底。 */
.v-mixed-main {
  flex: 1 1 auto;
  display: flex;
  flex-direction: column;
}
.v-mixed-main > :deep(.el-card) {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.v-mixed-main > :deep(.el-card > .el-card__body) {
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
