<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { IndicatorDef, ScoreProfileVersion } from '@/api/scoreProfile'
import type { TradeProfileVersion } from '@/api/tradeProfile'
import AppDetailSection from '@/components/AppDetailSection.vue'
import AppDetailFields from '@/components/AppDetailFields.vue'
import AppDetailField from '@/components/AppDetailField.vue'
import AppDataTable from '@/components/AppDataTable.vue'
import AppTableColumn from '@/components/AppTableColumn.vue'
import AppSummaryDisclosureCard from '@/components/AppSummaryDisclosureCard.vue'
import AppJsonViewer from '@/components/AppJsonViewer.vue'
import { backstopFields, conditionRelation, conditionVersionRows, scoreVersionRows } from './profileVersionDetails'

const props = defineProps<{
  version: ScoreProfileVersion | TradeProfileVersion
  definitions: IndicatorDef[]
}>()
const rawOpen = ref(false)
watch(() => props.version, () => { rawOpen.value = false })
const groups = computed(() => 'items' in props.version
  ? [{ label: '评分规则', rows: scoreVersionRows(props.version, props.definitions), relation: '' }]
  : [{ label: '买入条件', tree: props.version.buy_tree }, { label: '卖出条件', tree: props.version.sell_tree }]
    .map(group => ({ label: group.label, rows: conditionVersionRows(group.tree, props.definitions),
      relation: conditionRelation(group.tree) })))
const score = computed(() => 'items' in props.version ? props.version : null)
const trade = computed(() => 'backstop' in props.version ? props.version : null)
</script>

<template>
  <div class="profile-version-content">
    <AppDetailFields v-if="score">
      <AppDetailField label="ST 股票" :value="typeof score.include_st === 'boolean' ? score.include_st ? '纳入' : '排除' : '未记录'" />
      <AppDetailField v-for="(value, grade) in score.grade_thresholds" :key="grade"
        :label="`${grade} 档阈值`" :value="Number.isFinite(value) ? value : '未记录'" />
    </AppDetailFields>
    <AppDetailSection v-for="group in groups" :key="group.label" :title="group.label">
      <p v-if="group.relation" class="profile-version-relation">{{ group.relation }}</p>
      <AppDataTable :data="group.rows" embedded row-key="id" size="small" :aria-label="group.label">
        <AppTableColumn prop="name" label="指标" role="entity" />
        <AppTableColumn prop="state" label="状态" role="status" />
        <AppTableColumn prop="params" label="保存的参数" role="description" />
        <AppTableColumn v-if="score" prop="weight" label="权重" role="number" />
        <AppTableColumn prop="rule" :label="score ? '评分方式' : '判断条件'" role="description" />
        <template #empty>该版本未设置{{ group.label }}</template>
      </AppDataTable>
    </AppDetailSection>
    <AppDetailSection v-if="trade" title="兜底退出规则">
      <AppDetailFields>
        <AppDetailField v-for="field in backstopFields(trade.backstop)" :key="field.label"
          :label="field.label" :value="field.value" />
      </AppDetailFields>
    </AppDetailSection>
    <AppSummaryDisclosureCard :panel-id="`profile-version-raw-${score ? 'score' : 'trade'}-${version.version}`" title="原始配置"
      preview="用于技术核对，展开查看保存的完整配置" :expanded="rawOpen"
      :toggle-label="`${rawOpen ? '收起' : '展开'}版本 ${version.version} 原始配置`"
      @toggle="rawOpen = !rawOpen">
      <AppJsonViewer :source="JSON.stringify(version)" label="原始配置" />
    </AppSummaryDisclosureCard>
  </div>
</template>

<style scoped>
.profile-version-content { display: grid; gap: var(--app-space-3); min-width: 0; }
.profile-version-relation { margin: 0 0 var(--app-space-2); color: var(--el-text-color-secondary); font-size: var(--app-font-size-caption); }
</style>
