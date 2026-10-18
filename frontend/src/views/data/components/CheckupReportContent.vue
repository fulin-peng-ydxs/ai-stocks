<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElLink, ElTag } from 'element-plus'
import AppDetailSection from '@/components/AppDetailSection.vue'
import AppSummaryDisclosureCard from '@/components/AppSummaryDisclosureCard.vue'
import AppDataTable from '@/components/AppDataTable.vue'
import AppTableColumn from '@/components/AppTableColumn.vue'
import AppStateBlock from '@/components/AppStateBlock.vue'
import type { CheckupCheck, CheckupIssueItem, CheckupReport } from '@/api/data'
import { checkupDetailGroups } from '../qualityReport'

const props = defineProps<{ report: CheckupReport }>()
const emit = defineEmits<{ locate: [item: CheckupIssueItem] }>()
const expanded = ref<string[]>([])
watch(() => props.report, () => { expanded.value = [] })
const status = (check: CheckupCheck) => check.status ?? (check.ok ? 'pass' : 'fail')
const labels = { pass: '通过', warn: '提醒', fail: '未通过' } as const
const colors = { pass: 'success', warn: 'warning', fail: 'danger' } as const
const warningCount = computed(() => props.report.warning_count
  ?? props.report.groups.flatMap(g => g.checks).filter(c => status(c) === 'warn').length)
const headerType = computed(() => !props.report.all_ok ? 'danger' : warningCount.value ? 'warning' : 'success')
const title = computed(() => !props.report.all_ok ? `${props.report.fails.length} 项未通过`
  : warningCount.value ? `体检通过，${warningCount.value} 项提醒` : '全部通过')
const keyOf = (group: string, check: CheckupCheck) => `${group}:${check.name}`
const groups = computed(() => props.report.groups.map(group => ({
  ...group,
  checks: group.checks.map(check => ({
    ...check, key: keyOf(group.group, check), details: checkupDetailGroups(check),
    // 提醒/失败始终可查看说明；通过项只有额外依据或明细时才增加展开操作。
    expandable: status(check) !== 'pass'
      || Boolean(check.items?.length || check.evidence?.length || check.help || check.detail.length > 100),
  })),
})))
function toggle(key: string) {
  expanded.value = expanded.value.includes(key)
    ? expanded.value.filter(value => value !== key) : [...expanded.value, key]
}
</script>

<template>
  <div class="checkup-report">
    <header class="report-head">
      <ElTag :type="headerType" effect="light">{{ title }}</ElTag>
      <span>{{ report.passed }} 通过 · {{ warningCount }} 提醒项 / {{ report.total }} 检查项</span>
    </header>
    <AppStateBlock v-if="!report.groups.length" state="empty" title="暂无体检明细" description="重新运行数据结构体检后查看结果" />
    <AppDetailSection v-for="group in groups" :key="group.group" :title="group.group">
      <AppSummaryDisclosureCard v-for="check in group.checks" :key="check.key"
        variant="compact" :panel-id="`checkup-${encodeURIComponent(check.key)}`"
        :title="check.name" :preview="check.detail" :collapsible="check.expandable"
        :expanded="expanded.includes(check.key)"
        :toggle-label="`${expanded.includes(check.key) ? '收起' : '展开'} ${check.name}`"
        @toggle="toggle(check.key)">
        <template #leading>
          <ElTag :type="colors[status(check)]" size="small" effect="plain">{{ labels[status(check)] }}</ElTag>
        </template>
        <div class="checkup-detail">
          <p v-if="check.detail.length > 100" class="checkup-description">
            {{ check.detail }}
          </p>
          <section v-for="(detail, detailIndex) in check.details" :key="detailIndex" class="checkup-detail-group">
            <p class="checkup-context">
              <span>{{ detail.label }} · 共 {{ detail.total }} 条<span v-if="detail.total > detail.rows.length">，展示 {{ detail.rows.length }} 条样例</span></span>
              <span v-if="detail.context">{{ detail.context }}</span>
            </p>
            <AppDataTable :data="detail.rows" embedded size="small" row-key="id"
              :aria-label="`${check.name} ${detail.label}`">
              <AppTableColumn v-for="column in detail.columns" :key="column.key"
                :prop="`values.${column.key}`" :label="column.label" :role="column.role">
                <template #default="{ row }">
                  <ElLink v-if="column.key === 'object' && row.issue" type="primary" underline="never"
                    :href="`/data/quality?code=${encodeURIComponent(row.issue.code)}&issue_type=${encodeURIComponent(row.issue.issue_type)}`"
                    @click.prevent="emit('locate', row.issue)">
                    {{ row.values[column.key] }}
                  </ElLink>
                  <ElTag v-else-if="column.key === 'status' && row.issue"
                    :type="row.issue.status === 'ignored' ? 'info' : 'warning'" size="small" effect="plain">
                    {{ row.values[column.key] }}
                  </ElTag>
                  <span v-else>{{ row.values[column.key] }}</span>
                </template>
              </AppTableColumn>
            </AppDataTable>
          </section>
          <p v-if="check.help" class="checkup-help"><strong>处理说明</strong> {{ check.help }}</p>
          <p v-if="status(check) !== 'pass' && !check.details.length" class="checkup-help">
            {{ check.evidence === undefined
              ? '该历史报告未保存逐条明细，请重新运行结构体检。'
              : '本项为整体状态检查，无逐条异常记录；请按检查说明处理。' }}
          </p>
        </div>
      </AppSummaryDisclosureCard>
    </AppDetailSection>
  </div>
</template>

<style scoped>
.checkup-report { display: grid; gap: var(--app-space-4); min-width: 0; }
.report-head { display: flex; align-items: center; flex-wrap: wrap; gap: var(--app-space-3); color: var(--el-text-color-secondary); font-size: var(--app-font-size-caption); }
.checkup-detail, .checkup-detail-group { display: grid; gap: var(--app-space-2); min-width: 0; }
.checkup-context { display: flex; flex-wrap: wrap; gap: var(--app-space-1) var(--app-space-3); }
.checkup-detail .checkup-context, .checkup-detail .checkup-description, .checkup-detail .checkup-help { margin: 0; color: var(--el-text-color-secondary); font-size: var(--app-font-size-caption); line-height: var(--app-line-height-comfy); overflow-wrap: anywhere; }
.checkup-help strong { color: var(--el-text-color-regular); font-weight: var(--app-font-weight-medium); }
</style>
