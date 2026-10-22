<script setup lang="ts">
import { computed, ref } from 'vue'
import type { Placement, SelectInstance } from 'element-plus'
import {
  APP_BOTTOM_FLOATING_FALLBACKS,
  APP_BOTTOM_FLOATING_PLACEMENT,
} from '@/utils/floatingPlacement'

defineOptions({ inheritAttrs: false })

const props = withDefaults(defineProps<{
  /** 默认允许输入过滤候选；短枚举等场景可显式关闭，远程搜索仍由调用方提供。 */
  filterable?: boolean
  /** 普通控件使用语义容量；复合控件可由具名 class 承接自身布局。 */
  width?: 'compact' | 'short' | 'medium' | 'long' | 'wide' | 'fill'
  placement?: Placement
  fallbackPlacements?: Placement[]
  /** 长说明等明确场景可选择等宽；默认面板按内容扩展到共享上限。 */
  fitInputWidth?: boolean
  popperClass?: string
}>(), {
  filterable: true,
  width: undefined,
  placement: APP_BOTTOM_FLOATING_PLACEMENT,
  fallbackPlacements: () => [...APP_BOTTOM_FLOATING_FALLBACKS],
  fitInputWidth: false,
  popperClass: '',
})

const select = ref<SelectInstance>()
const panelClass = computed(() => [
  'app-select-popper',
  props.fitInputWidth ? 'app-select-popper--fit' : '',
  props.popperClass,
].filter(Boolean).join(' '))

// 保留选择器调用方使用的focus/blur API；业务值、事件及插槽直接交给底层组件。
defineExpose({
  focus: () => select.value?.focus(),
  blur: () => select.value?.blur(),
})
</script>

<template>
  <el-select
    ref="select"
    v-bind="$attrs"
    :filterable="filterable"
    class="app-select"
    :class="width ? `app-control-width-${width}` : undefined"
    :placement="placement"
    :fallback-placements="fallbackPlacements"
    :fit-input-width="fitInputWidth"
    :popper-class="panelClass"
  >
    <template v-for="(_, name) in $slots" #[name]="scope">
      <slot :name="name" v-bind="scope || {}" />
    </template>
  </el-select>
</template>
