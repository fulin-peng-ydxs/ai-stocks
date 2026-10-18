<script setup lang="ts">
import AppScrollArea from '@/components/AppScrollArea.vue'
/**
 * 响应式重排多列容器（规范 §5：兜底阶梯第 2 级「拿宽度换高度」）。
 * 按容器实际宽度（非视口，故支持侧栏伸缩）从 breakpoints 选列数，CSS Grid 等宽排布；
 * 仍放不下时容器整体内滚（兜底第 3 级），不裁切。窄屏自动回落单列。
 * 列数与「拆列后是否跌破组件最低宽」的合规性由 validator 在 schema 层把关，本组件只负责呈现。
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'
import type { ResponsiveBreakpoint, SlotSpec } from '../schema'

const props = defineProps<{ breakpoints: ResponsiveBreakpoint[]; slots: SlotSpec[] }>()

const scrollArea = ref<InstanceType<typeof AppScrollArea>>()
const columns = ref(1)
let ro: ResizeObserver | null = null

/** 按容器宽度取断点列数（断点已按 minWidth 升序，取最后一个满足的）。 */
function pickColumns(width: number): number {
  let cols = 1
  for (const bp of props.breakpoints) if (width >= bp.minWidth) cols = bp.columns
  return cols
}

onMounted(() => {
  if (!scrollArea.value?.viewport) return
  const apply = () => scrollArea.value?.viewport && (columns.value = pickColumns(scrollArea.value?.viewport.clientWidth))
  apply()
  ro = new ResizeObserver(apply)
  ro.observe(scrollArea.value?.viewport)
})
onBeforeUnmount(() => ro?.disconnect())
</script>

<template>
  <AppScrollArea ref="scrollArea" class="v-columns" :content-style="{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }">
    <template v-for="s in props.slots" :key="s.id">
      <div class="v-columns-cell"><slot :name="s.id" /></div>
    </template>
  </AppScrollArea>
</template>

<style scoped>
.v-columns {
  flex: 1 1 auto;
  min-height: 0;
  --app-scroll-display: grid;
  --app-scroll-gap: var(--app-space-3);
  --app-scroll-align-content: start;
}
.v-columns-cell {
  min-width: 0;
}
</style>
