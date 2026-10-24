<script setup lang="ts">
import { ref } from 'vue'
import { ElForm, type FormInstance } from 'element-plus'

defineOptions({ inheritAttrs: false })

// 一级编辑表单统一使用大号；局部设置或行内编辑可显式回到页面密度。
withDefaults(defineProps<{ size?: 'large' | 'default' | 'small' }>(), { size: 'large' })
const form = ref<FormInstance>()
// 校验等能力保留由 Element Plus 承担，需要时通过 form 访问原生实例。
defineExpose({ form })
</script>

<template>
  <ElForm ref="form" v-bind="$attrs" :size="size">
    <template v-for="(_, name) in $slots" #[name]="scope">
      <slot :name="name" v-bind="scope || {}" />
    </template>
  </ElForm>
</template>
