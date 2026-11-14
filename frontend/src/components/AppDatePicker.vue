<script setup lang="ts">
import { useAttrs } from 'vue'
import type { Placement } from 'element-plus'
import {
  APP_BOTTOM_FLOATING_FALLBACKS,
  APP_BOTTOM_FLOATING_PLACEMENT,
} from '@/utils/floatingPlacement'

defineOptions({ inheritAttrs: false })
const attrs = useAttrs()

withDefaults(defineProps<{
  /** 日期浮层默认固定在触发器下方；仅有明确交互理由时才允许消费侧覆盖。 */
  placement?: Placement
  /** 只在下方左右对齐间回退，避免空间计算把日期面板翻到页面上方。 */
  fallbackPlacements?: Placement[]
}>(), {
  placement: APP_BOTTOM_FLOATING_PLACEMENT,
  fallbackPlacements: () => [...APP_BOTTOM_FLOATING_FALLBACKS],
})
</script>

<template>
  <el-date-picker
    v-bind="$attrs"
    class="app-date-picker"
    :class="{
      'app-date-picker--range': attrs.type === 'daterange' || attrs.type === 'monthrange',
      'app-date-picker--datetime-range': attrs.type === 'datetimerange',
    }"
    :placement="placement"
    :fallback-placements="fallbackPlacements"
  >
    <template v-for="(_, name) in $slots" #[name]="scope">
      <slot :name="name" v-bind="scope || {}" />
    </template>
  </el-date-picker>
</template>

<style scoped>
/* 日期库组件的多根渲染不承接包装器 scope id，以唯一共享 class 精确命中真实输入根。 */
:global(.app-date-picker.el-date-editor) {
  width: var(--app-control-inline-width, var(--app-control-width-long));
  max-width: 100%;
  min-width: 0;
}
:global(.app-date-picker.el-date-editor.app-date-picker--range) {
  width: var(--app-control-inline-width, var(--app-control-width-wide));
}
/* 两端完整日期时间各占普通选择容量，另给分隔符和图标留白；窄容器由最大宽度收缩。
 * 该复合几何只在日期适配器持有，页面不复制 400px 等组件库默认值。 */
:global(.app-date-picker.el-date-editor.app-date-picker--datetime-range) {
  width: calc(var(--app-control-width-medium) * 2 + var(--app-space-6));
}
</style>
