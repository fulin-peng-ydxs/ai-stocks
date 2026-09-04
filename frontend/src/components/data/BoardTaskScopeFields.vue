<script setup lang="ts">
import { computed } from 'vue'
import {
  BOARD_STAGE_OPTIONS,
  BOARD_TYPE_OPTIONS,
  type BoardIngestStage,
  type BoardTypeScope,
} from '@/api/data'
import PageSegmented from '@/components/PageSegmented.vue'
import CurrentDayFallbackField from '@/components/data/CurrentDayFallbackField.vue'

const props = defineProps<{
  mode: 'update' | 'backfill'
  boardType: BoardTypeScope
  stages: BoardIngestStage[]
  forceMembers: boolean
  forceCurrentDay: boolean
  testIdPrefix: string
}>()

const emit = defineEmits<{
  'update:mode': [value: 'update' | 'backfill']
  'update:boardType': [value: BoardTypeScope]
  'update:stages': [value: BoardIngestStage[]]
  'update:forceMembers': [value: boolean]
  'update:forceCurrentDay': [value: boolean]
}>()

const includesMembers = computed(() => props.stages.includes('members'))
</script>

<template>
  <el-form-item label="采集模式">
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
    <span class="hint">增量补近期指数，全量回填扩展指数历史；两种模式都刷新资金流五个周期</span>
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
    <el-checkbox-group
      :model-value="stages"
      :data-testid="`${testIdPrefix}-stages`"
      @update:model-value="$emit('update:stages', $event as BoardIngestStage[])"
    >
      <el-checkbox v-for="stage in BOARD_STAGE_OPTIONS" :key="stage.value" :value="stage.value">
        {{ stage.label }}
      </el-checkbox>
    </el-checkbox-group>
    <span class="hint">可按需组合；质检恢复会自动选择与问题类型对应的最小采集内容</span>
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
</template>
