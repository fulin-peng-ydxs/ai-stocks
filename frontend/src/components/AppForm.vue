<script setup lang="ts">
import { ref } from 'vue'
import { ElForm, type FormInstance } from 'element-plus'
import { resetControlRowSizing } from './controlRowSizing'

defineOptions({ inheritAttrs: false })
resetControlRowSizing()

// 表单与页面共用常规密度；需要不同层级时由消费处显式声明尺寸。
withDefaults(defineProps<{ size?: 'large' | 'default' | 'small' }>(), { size: 'default' })
const form = ref<FormInstance>()
// 校验等能力保留由 Element Plus 承担，需要时通过 form 访问原生实例。
defineExpose({ form })
</script>

<template>
  <ElForm ref="form" v-bind="$attrs" class="app-control-row-boundary" :size="size">
    <template v-for="(_, name) in $slots" #[name]="scope">
      <slot :name="name" v-bind="scope || {}" />
    </template>
  </ElForm>
</template>
