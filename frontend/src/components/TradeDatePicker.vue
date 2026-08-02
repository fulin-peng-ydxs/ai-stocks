<script setup lang="ts">
// 全站统一的交易日日期选择器：中文格式 + 只能选真实交易日 + 交易日高亮（trade-cal 样式见 global.css）
import { onMounted, watch } from 'vue'
import { useTradeDates } from '@/composables/useTradeDates'

const props = defineProps<{
  modelValue: string | null
  placeholder?: string
  clearable?: boolean
  /** 默认落到行情数据的最新交易日；仅用于“默认最新、仍可回看历史”的业务控件。 */
  defaultLatest?: boolean
}>()
const emit = defineEmits<{ 'update:modelValue': [v: string | null] }>()

const { dataMax, disabledTradeDate, ensureLoaded } = useTradeDates()

function applyLatestDate() {
  if (props.defaultLatest && !props.modelValue && dataMax.value) {
    emit('update:modelValue', dataMax.value)
  }
}

async function ensureLatestLoaded() {
  try {
    await ensureLoaded()
    applyLatestDate()
  } catch {
    // 共享层当前会吞掉加载异常；这里仍防御未来实现抛错，展开日期面板时可再次重试。
  }
}

function onVisibleChange(visible: boolean) {
  // 首次日历请求失败时，用户再次展开控件即可重试；共享 dataMax 后续恢复也由 watch 自动补值。
  if (visible && !dataMax.value) void ensureLatestLoaded()
}

watch([() => props.defaultLatest, () => props.modelValue, dataMax], applyLatestDate, { immediate: true })
onMounted(() => { void ensureLatestLoaded() })
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
    @visible-change="onVisibleChange"
  />
</template>
