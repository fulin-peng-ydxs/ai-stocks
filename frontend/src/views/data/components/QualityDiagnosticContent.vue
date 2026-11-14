<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { QualityIssue } from '@/api/data'
import { ISSUE_STATUS_LABEL } from '@/api/data'
import { enumText } from '@/utils/displayText'
import AppDetailSection from '@/components/AppDetailSection.vue'
import AppDetailFields from '@/components/AppDetailFields.vue'
import AppDetailField from '@/components/AppDetailField.vue'
import AppDataTable from '@/components/AppDataTable.vue'
import AppTableColumn from '@/components/AppTableColumn.vue'
import AppSummaryDisclosureCard from '@/components/AppSummaryDisclosureCard.vue'
import AppJsonViewer from '@/components/AppJsonViewer.vue'
import { qualityDiagnostic } from '../qualityDiagnostic'
import { qualityDetailText } from '../qualityReport'

const props = defineProps<{ issue: QualityIssue }>()
const diagnostic = computed(() => qualityDiagnostic(props.issue))
const rawOpen = ref(false)
watch(() => props.issue, () => { rawOpen.value = false })
</script>

<template>
  <div class="quality-diagnostic-content">
    <AppDetailSection title="检查结论" :bordered="false"
      :description="diagnostic.structured ? diagnostic.summary : qualityDetailText(issue.detail)">
      <AppDetailFields>
        <AppDetailField label="交易日" :value="diagnostic.day" />
        <AppDetailField label="台账状态" :value="enumText(ISSUE_STATUS_LABEL, issue.status, '未识别状态')" />
      </AppDetailFields>
    </AppDetailSection>
    <AppDetailSection v-if="diagnostic.coverageFields.length" title="分钟覆盖">
      <AppDetailFields>
        <AppDetailField v-for="field in diagnostic.coverageFields" :key="field.label"
          :label="field.label" :value="field.value" :span="field.label === '缺失时段' ? 'full' : 'normal'" />
      </AppDetailFields>
    </AppDetailSection>
    <AppDetailSection v-if="diagnostic.sources.length" title="来源核验" :description="diagnostic.availability">
      <AppDataTable :data="diagnostic.sources" embedded row-key="id" size="small" aria-label="来源核验记录">
        <AppTableColumn prop="name" label="来源" role="entity" />
        <AppTableColumn prop="decision" label="取源决策" role="status" />
        <AppTableColumn prop="reason" label="原因" role="description" />
        <AppTableColumn prop="points" label="目标日点数" role="number" />
        <AppTableColumn prop="range" label="最近有效响应范围" role="description" />
        <AppTableColumn prop="checkedAt" label="最近核验" role="datetime" />
      </AppDataTable>
    </AppDetailSection>
    <AppDetailSection v-if="diagnostic.repairFields.length" title="最近修复">
      <AppDetailFields>
        <AppDetailField v-for="field in diagnostic.repairFields" :key="field.label" :label="field.label" :value="field.value"
          :span="field.label === '失败原因' ? 'full' : 'normal'" />
      </AppDetailFields>
    </AppDetailSection>
    <AppSummaryDisclosureCard :panel-id="`quality-diagnostic-raw-${issue.id}`" title="技术详情"
      preview="问题标识与完整原始诊断" :expanded="rawOpen"
      :toggle-label="`${rawOpen ? '收起' : '展开'}技术详情`" @toggle="rawOpen = !rawOpen">
      <AppDetailFields>
        <AppDetailField label="问题记录" :value="issue.id" mono />
        <AppDetailField label="问题类型编码" :value="issue.issue_type" mono />
      </AppDetailFields>
      <AppJsonViewer :source="issue.detail" label="原始诊断" />
    </AppSummaryDisclosureCard>
  </div>
</template>

<style scoped>
.quality-diagnostic-content { display: grid; gap: var(--app-space-4); min-width: 0; }
</style>
