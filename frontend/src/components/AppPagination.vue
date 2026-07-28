<script setup lang="ts">
import { PAGE_SIZE_OPTIONS } from '@/constants/pagination'

withDefaults(defineProps<{
  currentPage: number
  pageSize: number
  total: number
  pageSizes?: number[]
  small?: boolean
}>(), {
  pageSizes: () => PAGE_SIZE_OPTIONS,
  small: false,
})

const emit = defineEmits<{
  'update:currentPage': [value: number]
  'update:pageSize': [value: number]
  'current-change': [value: number]
  'size-change': [value: number]
}>()

function onCurrentChange(value: number) {
  emit('update:currentPage', value)
  emit('current-change', value)
}

function onSizeChange(value: number) {
  emit('update:pageSize', value)
  emit('size-change', value)
}
</script>

<template>
  <el-pagination
    :current-page="currentPage"
    :page-size="pageSize"
    :page-sizes="pageSizes"
    :total="total"
    :size="small ? 'small' : 'default'"
    layout="total, sizes, prev, pager, next"
    background
    @current-change="onCurrentChange"
    @size-change="onSizeChange"
  />
</template>
