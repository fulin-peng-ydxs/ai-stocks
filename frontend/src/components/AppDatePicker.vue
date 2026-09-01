<script setup lang="ts">
import type { Placement } from 'element-plus'

defineOptions({ inheritAttrs: false })

withDefaults(defineProps<{
  /** 日期浮层默认固定在触发器下方；仅有明确交互理由时才允许消费侧覆盖。 */
  placement?: Placement
  /** 只在下方左右对齐间回退，避免空间计算把日期面板翻到页面上方。 */
  fallbackPlacements?: Placement[]
}>(), {
  placement: 'bottom-start',
  fallbackPlacements: () => ['bottom-start', 'bottom-end'],
})
</script>

<template>
  <el-date-picker
    v-bind="$attrs"
    :placement="placement"
    :fallback-placements="fallbackPlacements"
  >
    <template v-for="(_, name) in $slots" #[name]="scope">
      <slot :name="name" v-bind="scope || {}" />
    </template>
  </el-date-picker>
</template>
