<script setup lang="ts">
import { computed } from 'vue'
import {
  BOARD_STAGE_OPTIONS,
  BOARD_TYPE_OPTIONS,
  type BoardIngestStage,
  type BoardTypeScope,
} from '@/api/data'
import PageSegmented from '@/components/PageSegmented.vue'
import TradeDatePicker from '@/components/TradeDatePicker.vue'
import CurrentDayFallbackField from '@/components/data/CurrentDayFallbackField.vue'

const props = withDefaults(defineProps<{
  mode: 'update' | 'backfill'
  boardType: BoardTypeScope
  stages: BoardIngestStage[]
  forceMembers: boolean
  forceCurrentDay: boolean
  testIdPrefix: string
  allowDateRange?: boolean
  dateStart?: string
  dateEnd?: string
}>(), {
  allowDateRange: false,
  dateStart: '',
  dateEnd: '',
})

const emit = defineEmits<{
  'update:mode': [value: 'update' | 'backfill']
  'update:boardType': [value: BoardTypeScope]
  'update:stages': [value: BoardIngestStage[]]
  'update:forceMembers': [value: boolean]
  'update:forceCurrentDay': [value: boolean]
  'update:dateStart': [value: string]
  'update:dateEnd': [value: string]
}>()

const includesMembers = computed(() => props.stages.includes('members'))
</script>

<template>
  <el-form-item label="采集模式">
    <div class="app-inline-info">
      <PageSegmented
        :model-value="mode"
        :test-id="`${testIdPrefix}-mode`"
        :options="[
          { label: '增量', value: 'update' },
          { label: '全量回填', value: 'backfill' },
        ]"
        aria-label="板块采集模式"
        @update:model-value="$emit('update:mode', $event as 'update' | 'backfill')"
      />
      <span class="app-caption-text">增量按各板块最新指数日期续采，全量回填扩展指数历史；两种模式都刷新资金流五个周期</span>
    </div>
  </el-form-item>
  <el-form-item label="板块类型">
    <PageSegmented
      :model-value="boardType"
      :test-id="`${testIdPrefix}-type`"
      :options="BOARD_TYPE_OPTIONS"
      aria-label="板块类型"
      @update:model-value="$emit('update:boardType', $event as BoardTypeScope)"
    />
  </el-form-item>
  <el-form-item label="采集内容">
    <div class="app-inline-info">
      <el-checkbox-group
        :model-value="stages"
        :data-testid="`${testIdPrefix}-stages`"
        @update:model-value="$emit('update:stages', $event as BoardIngestStage[])"
      >
        <el-checkbox v-for="stage in BOARD_STAGE_OPTIONS" :key="stage.value" :value="stage.value">
          {{ stage.label }}
        </el-checkbox>
      </el-checkbox-group>
      <span class="app-caption-text">可按需组合；质检恢复会自动选择与问题类型对应的最小采集内容</span>
    </div>
  </el-form-item>
  <el-form-item v-if="includesMembers" label="成分刷新">
    <el-checkbox
      :model-value="forceMembers"
      :data-testid="`${testIdPrefix}-force-members`"
      @update:model-value="$emit('update:forceMembers', Boolean($event))"
    >
      强制刷新成分快照（绕过间隔）
    </el-checkbox>
  </el-form-item>
  <CurrentDayFallbackField
    v-if="mode === 'update' && (stages.includes('bar') || stages.includes('fund'))"
    :model-value="forceCurrentDay"
    :test-id="`${testIdPrefix}-force-current-day`"
    @update:model-value="$emit('update:forceCurrentDay', $event)"
  />
  <template v-if="allowDateRange && mode === 'update' && stages.includes('bar')">
    <el-form-item label="指数开始日">
      <TradeDatePicker
        :model-value="dateStart"
        :data-testid="`${testIdPrefix}-date-start`"
        placeholder="留空=按各板块最新日期续采"
        clearable
        @update:model-value="$emit('update:dateStart', $event || '')"
      />
    </el-form-item>
    <el-form-item label="指数结束日">
      <div class="app-inline-info">
        <TradeDatePicker
          :model-value="dateEnd"
          :data-testid="`${testIdPrefix}-date-end`"
          placeholder="留空=仅开始日"
          clearable
          @update:model-value="$emit('update:dateEnd', $event || '')"
        />
        <span class="app-caption-text">仅作用于板块指数；开始日留空时使用自动增量，指定区间时不执行当日就绪回退</span>
      </div>
    </el-form-item>
  </template>
</template>
