<script setup lang="ts">
import AppFormHelp from '@/components/AppFormHelp.vue'
import PageSegmented from '@/components/PageSegmented.vue'
import TradeDatePicker from '@/components/TradeDatePicker.vue'
import StockCodeMultiSelect from '@/components/data/StockCodeMultiSelect.vue'
import type { IntradayIngestForm } from '@/utils/intradayIngest'

const props = defineProps<{ modelValue: IntradayIngestForm; testIdPrefix: string }>()
const emit = defineEmits<{ 'update:modelValue': [value: IntradayIngestForm] }>()
function patch(value: Partial<IntradayIngestForm>) {
  emit('update:modelValue', { ...props.modelValue, ...value })
}
</script>

<template>
  <el-form-item label="采集模式" required>
    <div class="app-inline-info">
      <PageSegmented
        :model-value="modelValue.mode"
        :test-id="testIdPrefix + '-mode'"
        :options="[{ label: '近期增量补采', value: 'update' }, { label: '日期区间重采', value: 'refetch' }]"
        aria-label="分时采集模式"
        @update:model-value="patch({ mode: $event as IntradayIngestForm['mode'] })"
      />
    </div>
    <AppFormHelp>{{ modelValue.mode === 'update'
      ? '补采缺失、不完整和新增日期，已有完整归档会跳过。'
      : '指定区间重新取源，完整日期也会刷新；较差、空或失败结果不会覆盖已有较好数据。' }}</AppFormHelp>
  </el-form-item>
  <el-form-item>
    <AppFormHelp>股票范围与采集模式独立。全市场采集可能运行数小时，可离开页面后从任务中心查看进度、终止或续跑。</AppFormHelp>
  </el-form-item>
  <el-form-item label="股票范围" required>
    <PageSegmented
      :model-value="modelValue.scope"
      :test-id="testIdPrefix + '-scope'"
      :options="[{ label: '全市场', value: 'all' }, { label: '指定股票', value: 'selected' }]"
      aria-label="分时股票范围"
      @update:model-value="patch({ scope: $event as IntradayIngestForm['scope'] })"
    />
  </el-form-item>
  <el-form-item v-if="modelValue.scope === 'selected'" label="指定股票" required>
    <StockCodeMultiSelect
      :model-value="modelValue.codes"
      :test-id="testIdPrefix + '-codes'"
      @update:model-value="patch({ codes: $event as string[] })"
    />
  </el-form-item>
  <template v-if="modelValue.mode === 'refetch'">
    <el-form-item label="起始日期" required>
      <TradeDatePicker
        :model-value="modelValue.date_start"
        placeholder="选择交易日"
        @update:model-value="patch({ date_start: $event || '' })"
      />
    </el-form-item>
    <el-form-item label="结束日期">
      <TradeDatePicker
        :model-value="modelValue.date_end"
        placeholder="留空=仅起始日"
        clearable
        @update:model-value="patch({ date_end: $event || '' })"
      />
    </el-form-item>
  </template>
  <el-alert
    type="info" :closable="false"
    title="仅归档已收盘的1分钟分时，长期保留。近期源无法补齐任意历史；超出窗口的缺口保留待处理。"
  />
</template>
