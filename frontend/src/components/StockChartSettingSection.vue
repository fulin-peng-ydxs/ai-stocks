<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import PageSegmented from '@/components/PageSegmented.vue'
import PageSettingSection from '@/components/PageSettingSection.vue'
import type {
  AuxiliaryChartSlot,
  AuxiliaryChartType,
  ChartType,
} from '@/composables/useStockChartPreferences'

const props = defineProps<{
  slot2: AuxiliaryChartType
  slot3: AuxiliaryChartType
  chartTypes: ChartType[]
  defaultRatios: number[]
  testIdPrefix?: string
}>()

const emit = defineEmits<{
  change: [slot: AuxiliaryChartSlot, value: string | number | boolean]
  saveDefaultRatios: [ratios: number[]]
  saveCurrentAsDefault: []
}>()

const auxiliaryChartOptions = [
  { label: '成交量', value: 'volume' },
  { label: 'MACD', value: 'macd' },
  { label: '隐藏', value: 'hidden' },
]

const chartTypeLabels: Record<ChartType, string> = {
  kline: 'K线',
  volume: '成交量',
  macd: 'MACD',
}
const ratioDraft = ref<number[]>([])
const ratioTotal = computed(() => ratioDraft.value.reduce((sum, value) => sum + Number(value || 0), 0))
const ratioValid = computed(() => (
  ratioDraft.value.length === props.chartTypes.length
  && ratioDraft.value.every((value) => Number.isFinite(value) && value > 0)
  && ratioTotal.value === 100
))

function toPercentages(ratios: number[]): number[] {
  if (!ratios.length) return []
  const result = ratios.map((value) => Math.max(1, Math.floor(value * 100)))
  let remainder = 100 - result.reduce((sum, value) => sum + value, 0)
  const order = ratios
    .map((value, index) => ({ index, fraction: value * 100 - Math.floor(value * 100) }))
    .sort((left, right) => remainder >= 0
      ? right.fraction - left.fraction
      : result[right.index] - result[left.index])
  let cursor = 0
  while (remainder !== 0 && order.length) {
    const index = order[cursor % order.length].index
    if (remainder > 0) {
      result[index] += 1
      remainder -= 1
    } else if (result[index] > 1) {
      result[index] -= 1
      remainder += 1
    }
    cursor += 1
  }
  return result
}

function saveDraftAsDefault(): void {
  if (!ratioValid.value) return
  emit('saveDefaultRatios', ratioDraft.value.map((value) => value / 100))
}

function saveCurrentAsDefault(): void {
  emit('saveCurrentAsDefault')
}

watch(
  () => props.defaultRatios,
  (ratios) => { ratioDraft.value = toPercentages(ratios) },
  { immediate: true, deep: true },
)
</script>

<template>
  <PageSettingSection title="图表设置" desc="图表类型和默认高度在新会话中生效；主页面拖动只调整当前会话。">
    <slot name="before" />
    <div class="setting-item">
      <div class="setting-label">图表一</div>
      <div class="fixed-chart-value" :data-testid="`${testIdPrefix || 'chart'}-slot1-kline`">K线（固定，不可隐藏）</div>
    </div>
    <div class="setting-item">
      <div class="setting-label">图表二</div>
      <PageSegmented
        :model-value="slot2"
        :options="auxiliaryChartOptions"
        aria-label="图表二类型"
        :test-id="`${testIdPrefix || 'chart'}-slot2`"
        @update:model-value="emit('change', 'slot2', $event)"
      />
    </div>
    <div class="setting-item">
      <div class="setting-label">图表三</div>
      <PageSegmented
        :model-value="slot3"
        :options="auxiliaryChartOptions"
        aria-label="图表三类型"
        :test-id="`${testIdPrefix || 'chart'}-slot3`"
        @update:model-value="emit('change', 'slot3', $event)"
      />
    </div>
    <div class="ratio-setting">
      <div class="setting-label">默认高度比例</div>
      <div class="ratio-composition">当前组合：{{ chartTypes.map((type) => chartTypeLabels[type]).join(' / ') }}</div>
      <div v-if="chartTypes.length === 1" class="fixed-chart-value">K线 100%（单图无需配置）</div>
      <template v-else>
        <div class="ratio-inputs">
          <label v-for="(type, index) in chartTypes" :key="type" class="ratio-input">
            <span>{{ chartTypeLabels[type] }}</span>
            <el-input-number
              v-model="ratioDraft[index]"
              :min="1"
              :max="99"
              :step="1"
              :precision="0"
              controls-position="right"
              :aria-label="`${chartTypeLabels[type]}默认高度百分比`"
            />
            <span>%</span>
          </label>
        </div>
        <div class="ratio-summary" :class="{ invalid: !ratioValid }">合计 {{ ratioTotal }}%</div>
        <div class="ratio-actions">
          <el-button
            :disabled="!ratioValid"
            :data-testid="`${testIdPrefix || 'chart'}-save-default-ratios`"
            @click="saveDraftAsDefault"
          >保存默认比例</el-button>
          <el-button
            type="primary"
            plain
            :data-testid="`${testIdPrefix || 'chart'}-save-current-ratios`"
            @click="saveCurrentAsDefault"
          >当前比例设为默认</el-button>
        </div>
      </template>
    </div>
  </PageSettingSection>
</template>

<style scoped>
.setting-item {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-2);
}
.setting-label {
  color: var(--page-settings-text-subtle);
  font-size: var(--app-font-size-body);
}
.fixed-chart-value {
  min-height: 38px;
  display: flex;
  align-items: center;
  padding: 0 10px;
  border: 1px solid var(--page-settings-seg-active-border);
  border-radius: 10px;
  background: var(--page-settings-seg-active-bg);
  color: var(--page-settings-text);
  font-size: var(--app-font-size-table);
  font-weight: var(--app-font-weight-section);
}
.ratio-setting {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-2);
  padding-top: var(--app-space-2);
  border-top: 1px solid var(--page-settings-seg-active-border);
}
.ratio-composition,
.ratio-summary {
  color: var(--page-settings-text-subtle);
  font-size: var(--app-font-size-table);
}
.ratio-summary.invalid {
  color: var(--el-color-danger);
}
.ratio-inputs {
  display: grid;
  gap: var(--app-space-2);
}
.ratio-input {
  display: grid;
  grid-template-columns: minmax(52px, 1fr) 116px 14px;
  align-items: center;
  gap: var(--app-space-2);
  color: var(--page-settings-text);
  font-size: var(--app-font-size-table);
}
.ratio-actions {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1.35fr);
  gap: var(--app-space-2);
}

.ratio-actions :deep(.el-button) {
  width: 100%;
  min-width: 0;
  margin-left: 0;
}
</style>
