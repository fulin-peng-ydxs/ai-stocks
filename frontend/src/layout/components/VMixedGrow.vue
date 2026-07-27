<script setup lang="ts">
/**
 * 混合成长区（规范 §8 / §4-F）：固定分析块（flex:0 0 auto 自然高）+ 一张主表/主图（flex:1 + 内部内滚）。
 * growMain 的业务 minH 同时参与运行时：余量足够时主组件内滚，余量不足时
 * 整个主内容区滚动兜底，避免把表格/标签工作区压到不可用。
 * 由 LayoutHost 在「多组件 + 恰一个 growMain」时选用，slot 内容按 slots[].id 具名传入。
 */
import type { SlotSpec } from '../schema'
import { COMPONENT_CATALOG } from '../components'

const props = defineProps<{ slots: SlotSpec[] }>()

function minHeight(slot: SlotSpec): string | undefined {
  if (!slot.growMain) return undefined
  return `${slot.minH ?? COMPONENT_CATALOG[slot.component]?.minH ?? 0}px`
}
</script>

<template>
  <div class="v-mixed" data-testid="layout-mixed-region">
    <template v-for="s in props.slots" :key="s.id">
      <div
        :class="s.growMain ? 'v-mixed-main' : 'v-mixed-fixed'"
        :data-testid="s.growMain ? 'layout-grow-region' : undefined"
        :style="s.growMain ? { minHeight: minHeight(s) } : undefined"
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
