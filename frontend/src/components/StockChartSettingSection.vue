<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import PageSegmented from '@/components/PageSegmented.vue'
import PageSettingItem from '@/components/PageSettingItem.vue'
import PageSettingsApplyButton from '@/components/PageSettingsApplyButton.vue'
import SettingsGroup from '@/components/SettingsGroup.vue'
import AppControlRow from '@/components/AppControlRow.vue'
import type {
  AuxiliaryChartSlot,
  AuxiliaryChartType,
  ChartType,
} from '@/composables/useStockChartPreferences'

const props = withDefaults(defineProps<{
  slot2: AuxiliaryChartType
  slot3: AuxiliaryChartType
  chartTypes: ChartType[]
  defaultRatios: number[]
  currentRatios: number[]
  canApplyCurrentRatios?: boolean
  currentRatiosChanged?: boolean
  disableCurrentRatios?: boolean
  savingCurrentRatios?: boolean
  testIdPrefix?: string
  /** 折叠偏好的稳定业务路径，与标题和图表数量无关。 */
  foldKeyPrefix?: string
}>(), {
  canApplyCurrentRatios: true,
  currentRatiosChanged: true,
})

const emit = defineEmits<{
  change: [slot: AuxiliaryChartSlot, value: string | number | boolean]
  saveDefaultRatios: [ratios: number[]]
  applyCurrentRatios: []
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

function redistributePercentages(editedIndex: number, rawValue: number | undefined): number[] {
  const count = props.chartTypes.length
  if (count <= 1) return [100]

  const maxEdited = 100 - (count - 1)
  const editedValue = Math.min(maxEdited, Math.max(1, Math.round(Number(rawValue) || 1)))
  const otherCount = count - 1
  const remaining = 100 - editedValue
  const baseValue = Math.floor(remaining / otherCount)
  let extra = remaining - baseValue * otherCount

  return props.chartTypes.map((_, index) => {
    if (index === editedIndex) return editedValue
    const value = baseValue + (extra > 0 ? 1 : 0)
    extra = Math.max(0, extra - 1)
    return value
  })
}

function persistRatios(ratios: number[]): void {
  ratioDraft.value = ratios
  emit('saveDefaultRatios', ratios.map((value) => value / 100))
}

function updateRatio(index: number, value: number | undefined): void {
  if (value != null && !Number.isInteger(value)) {
    ElMessage.warning('高度百分比需为整数')
    return
  }
  persistRatios(redistributePercentages(index, value))
}

function useCurrentRatios(): void {
  if (!props.currentRatiosChanged || props.disableCurrentRatios || props.savingCurrentRatios) return
  ratioDraft.value = toPercentages(props.currentRatios)
  emit('applyCurrentRatios')
}

watch(
  [
    () => props.defaultRatios,
    () => props.currentRatios,
    () => props.chartTypes,
    () => props.canApplyCurrentRatios,
  ],
  () => {
    const currentAvailable = props.canApplyCurrentRatios !== false
      && props.currentRatios.length === props.chartTypes.length
    ratioDraft.value = toPercentages(currentAvailable ? props.currentRatios : props.defaultRatios)
  },
  { immediate: true, deep: true },
)
</script>

<template>
  <div class="stock-chart-settings">
    <slot name="before" />
    <PageSettingItem label="图表一">
      <div class="fixed-chart-value" :data-testid="`${testIdPrefix || 'chart'}-slot1-kline`">K线（固定，不可隐藏）</div>
    </PageSettingItem>
    <PageSettingItem label="图表二">
      <PageSegmented
        :model-value="slot2"
        :options="auxiliaryChartOptions"
        aria-label="图表二类型"
        :test-id="`${testIdPrefix || 'chart'}-slot2`"
        @update:model-value="emit('change', 'slot2', $event)"
      />
    </PageSettingItem>
    <PageSettingItem label="图表三">
      <PageSegmented
        :model-value="slot3"
        :options="auxiliaryChartOptions"
        aria-label="图表三类型"
        :test-id="`${testIdPrefix || 'chart'}-slot3`"
        @update:model-value="emit('change', 'slot3', $event)"
      />
    </PageSettingItem>
    <PageSettingItem v-if="chartTypes.length === 1" :label="canApplyCurrentRatios === false ? '默认高度比例' : '已配置高度比例'">
      <div class="fixed-chart-value">K线 100%（单图无需配置）</div>
    </PageSettingItem>
    <SettingsGroup
      v-else
      :title="canApplyCurrentRatios === false ? '默认高度比例' : '已配置高度比例'"
      :fold-key="foldKeyPrefix ? `${foldKeyPrefix}:heightRatios` : undefined"
    >
      <div class="ratio-composition">当前组合：{{ chartTypes.map((type) => chartTypeLabels[type]).join(' / ') }}</div>
      <PageSettingItem v-for="(type, index) in chartTypes" :key="type" :label="chartTypeLabels[type]" layout="inline">
        <AppControlRow>
          <el-input-number
            :model-value="ratioDraft[index]"
            :min="1"
            :max="100 - (chartTypes.length - 1)"
            :step="1"
            controls-position="right"
            :aria-label="`${chartTypeLabels[type]}${canApplyCurrentRatios === false ? '默认' : '已配置'}高度百分比`"
            @update:model-value="updateRatio(index, $event)"
          />
          <span>%</span>
        </AppControlRow>
      </PageSettingItem>
      <div class="ratio-summary">合计 {{ ratioTotal }}%</div>
      <div class="ratio-actions">
        <PageSettingsApplyButton
          label="使用页面当前比例"
          :disabled="canApplyCurrentRatios === false || currentRatiosChanged === false || disableCurrentRatios"
          :loading="savingCurrentRatios"
          :test-id="`${testIdPrefix || 'chart'}-save-current-ratios`"
          @click="useCurrentRatios"
        />
      </div>
    </SettingsGroup>
  </div>
</template>

<style scoped>
.stock-chart-settings {
  display: grid;
  gap: var(--app-space-3);
}
.settings-help {
  margin: 0;
  color: var(--page-settings-text-subtle);
  font-size: var(--app-font-size-table);
  line-height: var(--app-line-height-comfy);
}
.fixed-chart-value {
  min-height: 38px;
  display: flex;
  align-items: center;
  padding: 0 10px;
  border: 1px solid var(--page-settings-seg-active-border);
  border-radius: var(--layout-control-radius);
  background: var(--page-settings-seg-active-bg);
  color: var(--page-settings-text);
  font-size: var(--app-font-size-table);
  font-weight: var(--app-font-weight-section);
}
.ratio-composition,
.ratio-summary {
  color: var(--page-settings-text-subtle);
  font-size: var(--app-font-size-table);
}
.ratio-actions {
  display: flex;
}

</style>
