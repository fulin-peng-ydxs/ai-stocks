<script setup lang="ts">
import AppSelect from '@/components/AppSelect.vue'
import { computed } from 'vue'
import PageSegmented from '@/components/PageSegmented.vue'
import TradeDatePicker from '@/components/TradeDatePicker.vue'
import StockCodeMultiSelect from '@/components/data/StockCodeMultiSelect.vue'
import CurrentDayFallbackField from '@/components/data/CurrentDayFallbackField.vue'
import {
  STOCK_INGEST_RECIPE_OPTIONS,
  isHeavyStockIngestRecipe,
  stockIngestSummary,
  stockIngestSupportsCodes,
  stockIngestSupportsConcurrency,
  stockIngestSupportsYears,
  type StockIngestFormValue,
  type StockIngestRecipe,
  type StockIngestScope,
} from '@/utils/stockIngest'

const props = defineProps<{
  modelValue: StockIngestFormValue
  testIdPrefix: string
}>()

const emit = defineEmits<{ 'update:modelValue': [value: StockIngestFormValue] }>()

const supportsCodes = computed(() => stockIngestSupportsCodes(props.modelValue.recipe))
const supportsYears = computed(() => stockIngestSupportsYears(props.modelValue.recipe))
const supportsConcurrency = computed(() => stockIngestSupportsConcurrency(props.modelValue.recipe))
const isHeavy = computed(() => isHeavyStockIngestRecipe(props.modelValue.recipe))
const summary = computed(() => stockIngestSummary(props.modelValue))

function patch(value: Partial<StockIngestFormValue>) {
  emit('update:modelValue', { ...props.modelValue, ...value })
}

function changeRecipe(recipe: StockIngestRecipe) {
  patch({
    recipe,
    scope: stockIngestSupportsCodes(recipe) ? props.modelValue.scope : 'all',
    codes: stockIngestSupportsCodes(recipe) ? props.modelValue.codes : [],
    date_start: ['range_refetch', 'st_status_refresh'].includes(recipe) ? props.modelValue.date_start : '',
    date_end: ['range_refetch', 'st_status_refresh'].includes(recipe) ? props.modelValue.date_end : '',
    years: stockIngestSupportsYears(recipe) ? props.modelValue.years : null,
    concurrency: stockIngestSupportsConcurrency(recipe) ? props.modelValue.concurrency : null,
    force_current_day: recipe === 'daily_update' ? props.modelValue.force_current_day : false,
  })
}

</script>

<template>
  <el-form-item label="采集方案" required>
    <AppSelect
      :model-value="modelValue.recipe"
      :data-testid="`${testIdPrefix}-recipe`"
      aria-label="采集方案"
      fit-input-width
      popper-class="stock-ingest-recipe-popper"
      @update:model-value="changeRecipe($event as StockIngestRecipe)"
      width="fill"
    >
      <el-option
        v-for="option in STOCK_INGEST_RECIPE_OPTIONS"
        :key="option.value"
        :label="option.label"
        :value="option.value"
      >
        <span>{{ option.label }}</span>
        <span class="app-caption-text">{{ option.description }}</span>
      </el-option>
    </AppSelect>
  </el-form-item>

  <el-form-item v-if="supportsCodes" label="股票范围" required>
    <PageSegmented
      :model-value="modelValue.scope"
      :options="[{ label: '全市场', value: 'all' }, { label: '指定股票', value: 'selected' }]"
      :test-id="`${testIdPrefix}-scope`"
      tone="primary"
      aria-label="个股采集范围"
      @update:model-value="patch({ scope: $event as StockIngestScope })"
    />
  </el-form-item>

  <el-form-item v-if="supportsCodes && modelValue.scope === 'selected'" label="指定股票" required>
    <StockCodeMultiSelect
      :model-value="modelValue.codes"
      :test-id="`${testIdPrefix}-codes`"
      placeholder="输入股票代码或名称搜索"
      @update:model-value="patch({ codes: $event as string[] })"
    />
  </el-form-item>

  <template v-if="modelValue.recipe === 'range_refetch' || modelValue.recipe === 'st_status_refresh'">
    <el-form-item label="起始日期" :required="modelValue.recipe === 'range_refetch'">
      <TradeDatePicker
        :model-value="modelValue.date_start"
        :placeholder="modelValue.recipe === 'st_status_refresh' ? '留空=全部已有历史' : '必填，仅可选交易日'"
        :clearable="modelValue.recipe === 'st_status_refresh'"
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

  <el-form-item v-if="supportsYears" label="历史年数">
    <el-input-number
      :model-value="modelValue.years"
      :min="1"
      :max="30"
      placeholder="留空=默认"
      @update:model-value="patch({ years: $event as number | null })"
    />
  </el-form-item>

  <el-form-item v-if="supportsConcurrency" label="采集并发数">
    <div class="app-inline-info">
      <el-input-number
        :model-value="modelValue.concurrency"
        :min="1"
        :max="16"
        placeholder="默认"
        @update:model-value="patch({ concurrency: $event as number | null })"
      />
      <span class="app-caption-text">留空沿用全局配置；提高并发会增加免费数据源封禁风险</span>
    </div>
  </el-form-item>

  <CurrentDayFallbackField
    v-if="modelValue.recipe === 'daily_update'"
    :model-value="modelValue.force_current_day"
    :test-id="`${testIdPrefix}-force-current-day`"
    @update:model-value="patch({ force_current_day: $event })"
  />

  <el-alert
    v-if="isHeavy"
    type="warning"
    :closable="false"
    title="该方案可能运行较久；可离开页面，之后从任务中心查看进度或继续任务。"
  />
  <el-alert
    class="stock-ingest-summary"
    type="info"
    :closable="false"
    :title="`将执行：${summary}`"
    :data-testid="`${testIdPrefix}-summary`"
  />
</template>

<style scoped>
/* 下拉与触发器等宽，选项按实际说明高度排版，避免长文撑宽并触发侧向定位。 */
:global(.stock-ingest-recipe-popper .el-select-dropdown__item) {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--app-space-1);
  height: auto;
  padding-block: var(--app-density-control-gap);
  line-height: var(--app-line-height-comfy);
  white-space: normal;
  overflow-wrap: anywhere;
}
:global(.stock-ingest-recipe-popper .app-caption-text) {
  font-weight: var(--app-font-weight-regular);
}

.stock-ingest-summary {
  margin: var(--app-space-2) 0 var(--app-space-4);
}
</style>
