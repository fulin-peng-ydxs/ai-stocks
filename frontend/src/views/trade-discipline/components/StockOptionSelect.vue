<script setup lang="ts">
import { onUnmounted, ref, watch } from 'vue'
import { searchTradeDisciplineStocks, type StockOption } from '@/api/tradeDiscipline'

const props = defineProps<{
  modelValue: StockOption | null
  disabled?: boolean
  clearable?: boolean
}>()
const emit = defineEmits<{ 'update:modelValue': [value: StockOption | null] }>()

const options = ref<StockOption[]>([])
const loading = ref(false)
let controller: AbortController | null = null
let requestSeq = 0
let debounceTimer: ReturnType<typeof setTimeout> | null = null

watch(() => props.modelValue, (value) => {
  if (value && !options.value.some((item) => item.code === value.code)) {
    options.value = [value, ...options.value]
  }
}, { immediate: true })

async function runSearch(normalized: string, seq: number): Promise<void> {
  controller = new AbortController()
  try {
    const result = await searchTradeDisciplineStocks(normalized, 20, controller.signal)
    if (seq !== requestSeq) return
    const selected = props.modelValue
    options.value = selected && !result.list.some((item) => item.code === selected.code)
      ? [selected, ...result.list]
      : result.list
  } catch {
    // 主动取消由请求层静默处理；其他错误已由统一请求层反馈。
  } finally {
    if (seq === requestSeq) loading.value = false
  }
}

function search(query: string): void {
  const normalized = query.trim()
  if (debounceTimer) clearTimeout(debounceTimer)
  controller?.abort()
  const seq = ++requestSeq
  if (!normalized) {
    options.value = props.modelValue ? [props.modelValue] : []
    loading.value = false
    return
  }
  loading.value = true
  debounceTimer = setTimeout(() => { void runSearch(normalized, seq) }, 250)
}

function select(code: string): void {
  emit('update:modelValue', options.value.find((item) => item.code === code) ?? null)
}

onUnmounted(() => {
  if (debounceTimer) clearTimeout(debounceTimer)
  controller?.abort()
})
</script>

<template>
  <el-select
    :model-value="modelValue?.code || ''"
    filterable
    remote
    reserve-keyword
    :remote-method="search"
    :loading="loading"
    :disabled="disabled"
    :clearable="clearable"
    placeholder="输入代码或名称搜索"
    no-data-text="没有匹配股票"
    @update:model-value="select"
  >
    <el-option v-for="item in options" :key="item.code" :label="`${item.code} ${item.name}`" :value="item.code">
      <span>{{ item.code }} · {{ item.name }}</span>
      <small v-if="item.industry">{{ item.industry }}</small>
    </el-option>
  </el-select>
</template>

<style scoped>
.el-select { width: 100%; }
.el-select :deep(.el-select-dropdown__item) { display: flex; justify-content: space-between; gap: var(--app-space-3); }
small { color: var(--el-text-color-secondary); }
</style>
