<script setup lang="ts">
import { ref, watch } from 'vue'
import { getStockQuality } from '@/api/data'
import { getErrorMessage } from '@/utils/error'

const props = withDefaults(defineProps<{
  modelValue: string[]
  testId?: string
  placeholder?: string
  ariaLabel?: string
}>(), {
  testId: undefined,
  placeholder: '输入代码或名称搜索',
  ariaLabel: '股票代码多选',
})

const emit = defineEmits<{
  'update:modelValue': [value: string[]]
  change: [value: string[]]
}>()

const options = ref<{ code: string; label: string }[]>([])
const loading = ref(false)
const error = ref('')
let searchSequence = 0

function normalizeCodes(values: string[]): string[] {
  return Array.from(new Set(values.map((value) => value.trim().toUpperCase()).filter(Boolean)))
}

function emitValue(values: string[]) {
  const normalized = normalizeCodes(values)
  emit('update:modelValue', normalized)
  emit('change', normalized)
}

function mergeWithSelected(items: Array<{ code: string; label: string }>) {
  const selected = new Set(normalizeCodes(props.modelValue))
  const merged = new Map<string, { code: string; label: string }>()
  for (const item of options.value) {
    if (selected.has(item.code)) merged.set(item.code, item)
  }
  for (const code of selected) {
    if (!merged.has(code)) merged.set(code, { code, label: code })
  }
  for (const item of items) merged.set(item.code, item)
  options.value = Array.from(merged.values())
}

async function search(keyword: string) {
  const query = keyword.trim()
  const sequence = ++searchSequence
  if (!query) {
    options.value = []
    error.value = ''
    loading.value = false
    return
  }
  loading.value = true
  error.value = ''
  try {
    const result = await getStockQuality({ keyword: query, size: 30 })
    if (sequence !== searchSequence) return
    mergeWithSelected(result.list.map((item) => ({
      code: item.code,
      label: `${item.code} ${item.name}`,
    })))
  } catch (reason) {
    if (sequence !== searchSequence) return
    mergeWithSelected([])
    error.value = getErrorMessage(reason, '股票候选加载失败')
  } finally {
    if (sequence === searchSequence) loading.value = false
  }
}

function handlePaste(event: ClipboardEvent) {
  const text = event.clipboardData?.getData('text') ?? ''
  if (!/[,，\s]/.test(text.trim())) return
  event.preventDefault()
  emitValue([...props.modelValue, ...text.split(/[,，\s]+/)])
}

watch(
  () => props.modelValue,
  (codes) => {
    for (const code of normalizeCodes(codes)) {
      if (!options.value.some((item) => item.code === code)) {
        options.value.push({ code, label: code })
      }
    }
  },
  { immediate: true },
)
</script>

<template>
  <div class="stock-code-multi-select" @paste="handlePaste">
    <el-select
      :model-value="modelValue"
      multiple
      filterable
      remote
      clearable
      collapse-tags
      allow-create
      default-first-option
      :remote-method="search"
      :loading="loading"
      :reserve-keyword="false"
      :no-data-text="error || '无匹配股票'"
      :placeholder="placeholder"
      :aria-label="ariaLabel"
      :data-testid="testId"
      style="width: 100%"
      @update:model-value="emitValue($event as string[])"
    >
      <el-option
        v-for="option in options"
        :key="option.code"
        :label="option.label"
        :value="option.code"
      />
    </el-select>
  </div>
</template>

<style scoped>
.stock-code-multi-select {
  width: 100%;
}
</style>
