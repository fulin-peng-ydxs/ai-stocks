<script setup lang="ts">
import AppSelect from '@/components/AppSelect.vue'
import { onUnmounted, ref, watch } from 'vue'
import { searchTradeDisciplineStocks, type StockOption } from '@/api/tradeDiscipline'
import StockStatusTag from '@/components/StockStatusTag.vue'

const props = defineProps<{
  modelValue: StockOption | null
  disabled?: boolean
  clearable?: boolean
  tradeDate?: string
}>()
const emit = defineEmits<{ 'update:modelValue': [value: StockOption | null] }>()

const options = ref<StockOption[]>([])
const loading = ref(false)
const searchError = ref(false)
let controller: AbortController | null = null
let requestSeq = 0
let debounceTimer: ReturnType<typeof setTimeout> | null = null

watch(() => props.modelValue, (value) => {
  if (value) {
    const index = options.value.findIndex((item) => item.code === value.code)
    if (index === -1) options.value = [value, ...options.value]
    else options.value[index] = value
  }
}, { immediate: true })

watch(() => props.tradeDate, () => {
  if (debounceTimer) clearTimeout(debounceTimer)
  controller?.abort()
  requestSeq += 1
  options.value = props.modelValue ? [props.modelValue] : []
  loading.value = false
  searchError.value = false
})

async function runSearch(normalized: string, seq: number): Promise<void> {
  const requestController = new AbortController()
  controller = requestController
  try {
    const result = await searchTradeDisciplineStocks(
      normalized,
      20,
      requestController.signal,
      props.tradeDate,
    )
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
    <AppSelect
      :model-value="modelValue?.code || ''"
      filterable
      remote
      reserve-keyword
      :remote-method="search"
      :loading="loading"
      :disabled="disabled"
      :clearable="clearable"
      popper-class="stock-option-select-popper"
      placeholder="输入代码或名称搜索"
      no-data-text="没有匹配股票"
      @update:model-value="select"
    >
      <el-option v-for="item in options" :key="item.code" :label="`${item.code} · ${item.name}`" :value="item.code">
        <span class="stock-option-select__primary app-inline-info app-inline-info--nowrap">
          <span>{{ item.code }} · {{ item.name }}</span>
          <StockStatusTag :is-st="item.is_st" :as-of-date="item.st_as_of_date" show-unknown />
        </span>
        <small v-if="item.industry || item.delist_date" class="stock-option-select__meta">
          {{ [item.industry, item.delist_date ? '已退市' : ''].filter(Boolean).join(' · ') }}
        </small>
      </el-option>
    </AppSelect>
    <StockStatusTag
      v-if="modelValue"
      :is-st="modelValue.is_st"
      :as-of-date="modelValue.st_as_of_date"
      show-unknown
    />
    <small v-if="searchError" class="stock-option-select__error" role="alert">
      搜索失败，请重新输入重试
    </small>
  </div>
</template>

<style scoped>
.stock-option-select { display: flex; flex-wrap: wrap; align-items: center; gap: var(--app-space-2); width: 100%; }
.el-select { flex: 1; min-width: 0; }
small { color: var(--el-text-color-secondary); }
.stock-option-select__error { flex-basis: 100%; display: block; color: var(--el-color-danger); }
:global(.stock-option-select-popper .el-select-dropdown__item) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-3);
}
:global(.stock-option-select-popper .stock-option-select__primary) {
  min-width: 0;
  flex: 1 1 auto;
  flex-wrap: wrap;
  white-space: normal;
}
:global(.stock-option-select-popper .stock-option-select__meta) {
  flex: 0 1 auto;
  min-width: 0;
  color: var(--el-text-color-secondary);
  white-space: normal;
}
</style>
