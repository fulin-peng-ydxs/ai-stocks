<script setup lang="ts">
// 全站统一的交易日日期选择器：中文格式 + 只能选真实交易日 + 交易日高亮（trade-cal 样式见 global.css）
import { useTradeDates } from '@/composables/useTradeDates'

defineProps<{
  modelValue: string | null
  placeholder?: string
  clearable?: boolean
}>()
const emit = defineEmits<{ 'update:modelValue': [v: string | null] }>()

const { disabledTradeDate } = useTradeDates()
</script>

<template>
  <el-date-picker
    :model-value="modelValue"
    type="date"
    value-format="YYYY-MM-DD"
    format="YYYY年MM月DD日"
    :placeholder="placeholder"
    :clearable="clearable ?? false"
    :disabled-date="disabledTradeDate"
    popper-class="trade-cal"
    @update:model-value="(v: string | null) => emit('update:modelValue', v)"
  />
</template>
