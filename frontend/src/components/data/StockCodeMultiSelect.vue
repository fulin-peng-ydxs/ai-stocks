<script setup lang="ts">
import { computed } from 'vue'
import AppMultiSelect, { type AppMultiSelectOption } from '@/components/AppMultiSelect.vue'
import { getStockQuality } from '@/api/data'
import { isMarketBenchmarkCode, MARKET_BENCHMARKS } from '@/utils/marketBenchmarks'

const props = withDefaults(defineProps<{
  modelValue: string[]
  testId?: string
  placeholder?: string
  ariaLabel?: string
  assetType?: 'all' | 'stock' | 'index'
}>(), {
  testId: undefined,
  placeholder: '输入代码或名称搜索',
  ariaLabel: '股票代码多选',
  assetType: 'stock',
})
const emit = defineEmits<{
  'update:modelValue': [value: string[]]
  change: [value: string[]]
}>()
const indexOptions = computed<AppMultiSelectOption[]>(() => props.assetType === 'stock' ? []
  : MARKET_BENCHMARKS.map(item => ({ value: item.value, label: `${item.value} ${item.label}` })))
const codeSeparators = /[,，\s]+/
function normalizeCode(value: string): string { return value.trim().toUpperCase() }
async function searchStocks(keyword: string): Promise<AppMultiSelectOption[]> {
  if (props.assetType === 'index') return []
  const result = await getStockQuality({ keyword, size: 30 })
  return result.list.map(item => ({ value: item.code, label: `${item.code} ${item.name}` }))
}
/** 领域层仅负责存在性和类型判定；粘贴、去重、异步状态与错误展示由基础组件持有。 */
async function resolveCodes(codes: string[]): Promise<AppMultiSelectOption[]> {
  const indices = indexOptions.value.filter(item => codes.includes(item.value))
  const stockCodes: string[] = props.assetType === 'index' ? []
    : codes.filter(code => /^\d{6}\.(SH|SZ)$/.test(code) && !isMarketBenchmarkCode(code))
  if (!stockCodes.length) return indices
  const result = await getStockQuality({ codes: stockCodes.join(','), size: stockCodes.length })
  return [...indices, ...result.list.filter(item => stockCodes.includes(item.code))
    .map(item => ({ value: item.code, label: `${item.code} ${item.name}` }))]
}
function rejectedCodes(codes: string[]): string {
  return `未加入不存在或不适用于当前类型的标的：${codes.slice(0, 5).join('、')}${codes.length > 5 ? '等' : ''}`
}
</script>

<template>
  <div class="stock-code-multi-select">
    <AppMultiSelect
      :model-value="modelValue"
      :options="indexOptions"
      :load-options="searchStocks"
      :resolve-values="resolveCodes"
      :normalize-value="normalizeCode"
      :paste-separator="codeSeparators"
      :context-key="assetType"
      :rejected-message="rejectedCodes"
      load-error-message="股票候选加载失败"
      validation-error-message="标的校验失败，请重新粘贴"
      clearable
      collapse-tags
      default-first-option
      :reserve-keyword="false"
      :no-data-text="assetType === 'stock' ? '无匹配股票' : '无匹配个股或指数'"
      :placeholder="placeholder"
      :aria-label="ariaLabel"
      :data-testid="testId"
      width="fill"
      @update:model-value="emit('update:modelValue', $event)"
      @change="emit('change', $event)"
    />
  </div>
</template>

<style scoped>
.stock-code-multi-select { width: 100%; }
</style>
