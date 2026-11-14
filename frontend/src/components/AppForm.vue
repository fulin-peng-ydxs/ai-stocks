<script setup lang="ts">
import { ref } from 'vue'
import { ElForm, type FormInstance } from 'element-plus'
import { resetControlRowSizing } from './controlRowSizing'

defineOptions({ inheritAttrs: false })
resetControlRowSizing()

// 横向标签默认原生左对齐，使标签列与整表说明自然共用起点；显式位置继续透传。
withDefaults(defineProps<{
  size?: 'large' | 'default' | 'small'
  labelPosition?: 'left' | 'right' | 'top'
}>(), { size: 'default', labelPosition: 'left' })
const form = ref<FormInstance>()
// 校验等能力保留由 Element Plus 承担，需要时通过 form 访问原生实例。
defineExpose({ form })
</script>

<template>
  <ElForm ref="form" v-bind="$attrs" class="app-control-row-boundary" :size="size" :label-position="labelPosition">
    <template v-for="(_, name) in $slots" #[name]="scope">
      <slot :name="name" v-bind="scope || {}" />
    </template>
  </ElForm>
</template>
