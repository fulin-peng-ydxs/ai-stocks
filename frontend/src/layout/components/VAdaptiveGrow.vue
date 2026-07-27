<script setup lang="ts">
/**
 * 条件成长区：
 * - 可用高度达到主组件最低高度时，主组件吃满余量并自行内滚。
 * - 可用高度不足时，主内容区才出现整体滚动，以保护组件最低可用高度。
 */
import { computed } from 'vue'
import { COMPONENT_CATALOG } from '../components'
import type { SlotSpec } from '../schema'

const props = defineProps<{
  slot: SlotSpec
}>()

const minHeight = computed(() =>
  props.slot.minH ?? COMPONENT_CATALOG[props.slot.component]?.minH ?? 0)
</script>

<template>
  <div class="v-adaptive-grow" data-testid="layout-adaptive-region">
    <div
      class="v-adaptive-grow__main"
      data-testid="layout-grow-region"
      :style="{ minHeight: `${minHeight}px` }"
    >
      <slot />
    </div>
  </div>
</template>

<style scoped>
.v-adaptive-grow {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  display: flex;
  flex-direction: column;
}

.v-adaptive-grow__main {
  flex: 1 1 auto;
  display: flex;
  flex-direction: column;
}

.v-adaptive-grow__main > :deep(.el-card) {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.v-adaptive-grow__main > :deep(.el-card > .el-card__body) {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
</style>
