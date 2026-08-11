<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  grade: string
  size?: 'small' | 'default' | 'large'
}>(), {
  size: 'default',
})

const type = computed(() => {
  if (props.grade === '主升浪核心') return 'danger'
  if (props.grade === '龙头候选') return 'warning'
  if (props.grade === '观察') return 'success'
  return 'info'
})
</script>

<template>
  <el-tag :type="type" :size="size" effect="light">{{ grade }}</el-tag>
</template>
