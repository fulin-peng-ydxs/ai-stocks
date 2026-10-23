<script setup lang="ts">
import AppFormHelp from '@/components/AppFormHelp.vue'
import PageSegmented from '@/components/PageSegmented.vue'
import TradeDatePicker from '@/components/TradeDatePicker.vue'
import StockCodeMultiSelect from '@/components/data/StockCodeMultiSelect.vue'
import type { IntradayIngestForm } from '@/utils/intradayIngest'
import { isMarketBenchmarkCode } from '@/utils/marketBenchmarks'

const props = defineProps<{ modelValue: IntradayIngestForm; testIdPrefix: string }>()
const emit = defineEmits<{ 'update:modelValue': [value: IntradayIngestForm] }>()
function patch(value: Partial<IntradayIngestForm>) {
  if (value.asset_type && value.asset_type !== props.modelValue.asset_type) {
    value.codes = props.modelValue.codes.filter(code => value.asset_type === 'all'
      || isMarketBenchmarkCode(code) === (value.asset_type === 'index'))
  }
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
    <AppFormHelp>采集范围与模式独立。全市场采集可能运行数小时，可在任务中心查看进度、终止或续跑。</AppFormHelp>
  </el-form-item>
  <el-form-item label="采集对象" required>
    <PageSegmented :model-value="modelValue.asset_type"
      :test-id="testIdPrefix + '-asset-type'" aria-label="分时采集对象"
      :options="[{ label: '个股＋指数', value: 'all' }, { label: '仅个股', value: 'stock' }, { label: '仅指数', value: 'index' }]"
      @update:model-value="patch({ asset_type: $event as IntradayIngestForm['asset_type'] })" />
  </el-form-item>
  <el-form-item label="标的范围" required>
    <PageSegmented
      :model-value="modelValue.scope"
      :test-id="testIdPrefix + '-scope'"
      :options="[{ label: '全部', value: 'all' }, { label: '指定标的', value: 'selected' }]"
      aria-label="分时标的范围"
      @update:model-value="patch({ scope: $event as IntradayIngestForm['scope'] })"
    />
  </el-form-item>
  <el-form-item v-if="modelValue.scope === 'selected'" label="指定标的" required>
    <StockCodeMultiSelect
      :model-value="modelValue.codes"
      :asset-type="modelValue.asset_type"
      aria-label="分时个股或指数多选"
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
    title="个股与指数共用采集和质检；首次从全局监控起点采集。成功补采更早数据会自动前移全部标的质检起点，数据丢失不会使起点后移；当天须已收盘且对应日线就绪。"
  />
</template>
