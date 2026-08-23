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
const searchError = ref(false)
let controller: AbortController | null = null
let requestSeq = 0
let debounceTimer: ReturnType<typeof setTimeout> | null = null

watch(() => props.modelValue, (value) => {
  if (value && !options.value.some((item) => item.code === value.code)) {
    options.value = [value, ...options.value]
  }
}, { immediate: true })

async function runSearch(normalized: string, seq: number): Promise<void> {
  const requestController = new AbortController()
  controller = requestController
  try {
    const result = await searchTradeDisciplineStocks(normalized, 20, requestController.signal)
    if (seq !== requestSeq) return
    searchError.value = false
    const selected = props.modelValue
    options.value = selected && !result.list.some((item) => item.code === selected.code)
      ? [selected, ...result.list]
      : result.list
  } catch {
    if (seq !== requestSeq || requestController.signal.aborted) return
    options.value = props.modelValue ? [props.modelValue] : []
    searchError.value = true
  } finally {
    if (seq === requestSeq) loading.value = false
  }
}

function search(query: string): void {
  const normalized = query.trim()
  if (debounceTimer) clearTimeout(debounceTimer)
  controller?.abort()
  const seq = ++requestSeq
  searchError.value = false
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
  <div class="stock-option-select">
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
    <small v-if="searchError" class="stock-option-select__error" role="alert">
      搜索失败，请重新输入重试
    </small>
  </div>
</template>

<style scoped>
.stock-option-select, .el-select { width: 100%; }
.el-select :deep(.el-select-dropdown__item) { display: flex; justify-content: space-between; gap: var(--app-space-3); }
small { color: var(--el-text-color-secondary); }
.stock-option-select__error { display: block; margin-top: var(--app-space-1); color: var(--el-color-danger); }
</style>
