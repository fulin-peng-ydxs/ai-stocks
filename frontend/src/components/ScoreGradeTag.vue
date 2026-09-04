<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  grade: string
}>()

const type = computed(() => {
  if (props.grade === '主升浪核心') return 'danger'
  if (props.grade === '龙头候选') return 'warning'
  if (props.grade === '观察') return 'success'
  return 'info'
})
</script>

<template>
  <span class="app-table-tag-shell">
    <el-tag :type="type" size="small" effect="light">{{ grade }}</el-tag>
  </span>
</template>
