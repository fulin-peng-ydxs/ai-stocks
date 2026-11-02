<script setup lang="ts">
import { formatNumber } from '@/utils/numberFormat'
import { PAGE_SIZE_OPTIONS } from '@/constants/pagination'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = withDefaults(defineProps<{
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

const FULL_LAYOUT_MIN_WIDTH = 640
const SUMMARY_LAYOUT_MIN_WIDTH = 420
const rootRef = ref<HTMLElement | null>(null)
const layoutTier = ref<0 | 1 | 2>(0)
let resizeObserver: ResizeObserver | null = null
let measureVersion = 0

const paginationLayout = computed(() => {
  if (layoutTier.value === 2) {
    return 'slot, sizes, prev, pager, next'
  }
  if (layoutTier.value === 1) {
    return 'slot, prev, pager, next'
  }
  return 'prev, pager, next'
})
const pagerCount = computed(() => layoutTier.value === 2 ? 7 : 5)
const effectiveSmall = computed(() => props.small || layoutTier.value < 2)

function preferredTier(width: number): 0 | 1 | 2 {
  if (width >= FULL_LAYOUT_MIN_WIDTH) return 2
  if (width >= SUMMARY_LAYOUT_MIN_WIDTH) return 1
  return 0
}

async function measure(): Promise<void> {
  const root = rootRef.value
  if (!root) return
  const version = ++measureVersion
  let tier = preferredTier(root.clientWidth)
  while (tier > 0) {
    layoutTier.value = tier as 1 | 2
    await nextTick()
    if (version !== measureVersion || root !== rootRef.value) return
    const pagination = root.querySelector<HTMLElement>('.el-pagination')
    if (!pagination || pagination.scrollWidth <= root.clientWidth + 1) return
    tier -= 1
  }
  layoutTier.value = 0
}

onMounted(() => {
  void measure()
  if (typeof ResizeObserver !== 'undefined' && rootRef.value) {
    resizeObserver = new ResizeObserver(() => { void measure() })
    resizeObserver.observe(rootRef.value)
  }
})

onBeforeUnmount(() => {
  measureVersion += 1
  resizeObserver?.disconnect()
  resizeObserver = null
})

watch(
  () => [props.currentPage, props.pageSize, props.pageSizes, props.total, props.small],
  () => { void measure() },
  { deep: true },
)

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
  <div ref="rootRef" class="app-pagination">
    <el-pagination
      :current-page="currentPage"
      :page-size="pageSize"
      :page-sizes="pageSizes"
      :pager-count="pagerCount"
      :total="total"
      :size="effectiveSmall ? 'small' : 'default'"
      :layout="paginationLayout"
      background
      @current-change="onCurrentChange"
      @size-change="onSizeChange"
    >
      <span class="el-pagination__total" role="status">共 {{ formatNumber(total, 'count') }} 条</span>
    </el-pagination>
  </div>
</template>

<style scoped>
.app-pagination {
  display: flex;
  flex: 1 1 auto;
  justify-content: flex-end;
  min-width: 0;
  max-width: 100%;
}
.app-pagination :deep(.el-pagination) {
  max-width: 100%;
}
</style>
