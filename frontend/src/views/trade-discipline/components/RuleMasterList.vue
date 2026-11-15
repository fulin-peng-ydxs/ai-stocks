<script setup lang="ts">
import { formatDateOnly } from '@/utils/dateTime'
import AppControlRow from '@/components/AppControlRow.vue'
import AppScrollArea from '@/components/AppScrollArea.vue'
import { vKeyboardActivate } from '@/directives/keyboardActivate'
import { computed, ref } from 'vue'
import { Plus } from '@element-plus/icons-vue'
import AppSearchInput from '@/components/AppSearchInput.vue'
import AppAsyncRegion from '@/components/AppAsyncRegion.vue'
import AppStateBlock from '@/components/AppStateBlock.vue'
import type { CheckinSummaryRule, TradeDisciplineRule } from '@/api/tradeDiscipline'
import {
  checkinAssessmentLabel,
  checkinAssessmentTagType,
} from '@/utils/tradeDisciplineAssessment'

const props = withDefaults(defineProps<{
  rules: TradeDisciplineRule[]
  selectedId: string
  loading?: boolean
  error?: boolean
  canManage: boolean
  showCreate?: boolean
  checkinStates?: CheckinSummaryRule[] | null
}>(), {
  showCreate: true,
  loading: false,
  error: false,
})

const emit = defineEmits<{
  select: [ruleId: string]
  create: []
  retry: []
}>()

const query = ref('')
const filteredRules = computed(() => {
  const normalized = query.value.trim().toLocaleLowerCase('zh-CN')
  if (!normalized) return props.rules
  return props.rules.filter((rule) =>
    (rule.proposed_name || rule.name || '').toLocaleLowerCase('zh-CN').includes(normalized))
})
const checkinByRule = computed(() => new Map(
  (props.checkinStates ?? []).map((item) => [item.rule_id, item]),
))

function effectiveLabel(rule: TradeDisciplineRule): string {
  if (rule.effective_status === 'active') {
    return rule.effective_version?.version_no ? `当前 v${rule.effective_version.version_no}` : '当前生效'
  }
  return rule.effective_status === 'archived' ? '当前已归档' : '当前未生效'
}

function managementLabel(rule: TradeDisciplineRule): string {
  const checkin = checkinByRule.value.get(rule.id)
  if (checkin) {
    if (!checkin.checkin_id) return '待打卡'
    return `${checkinAssessmentLabel(checkin.assessment!)} · r${checkin.current_revision_no}`
  }
  const event = rule.latest_management_event
  if (rule.has_pending_management_action && event) {
    const action = event.event_type === 'archive'
      ? '归档'
      : event.event_type === 'restore' ? '恢复' : `发布 v${event.version_no}`
    return `${action}待 ${formatDateOnly(event.effective_from_trade_date)}`
  }
  if (rule.draft_revision) return '有编辑中草稿'
  if (rule.management_status === 'active') return `最新 v${rule.latest_version_no ?? '—'}`
  return rule.management_status === 'archived' ? '管理状态已归档' : '草稿（未发布）'
}

function managementTone(rule: TradeDisciplineRule): 'success' | 'danger' | 'warning' | 'secondary' {
  const checkin = checkinByRule.value.get(rule.id)
  if (checkin) {
    if (!checkin.checkin_id) return 'warning'
    return checkinAssessmentTagType(checkin.assessment!)
  }
  if (rule.has_pending_management_action || rule.draft_revision) return 'warning'
  if (rule.management_status === 'unpublished') return 'warning'
  return 'secondary'
}
</script>

<template>
  <aside class="rule-master app-surface" aria-label="规则管理列表">
    <AppControlRow class="rule-master__tools">
      <el-button
        v-if="canManage && showCreate"
        v-permission="'trade-discipline:rule-manage'"
        type="primary"
        plain
        :icon="Plus"
        class="rule-master__create"
        aria-label="新建规则"
        :disabled="loading || error"
        @click="emit('create')"
      >
        新建规则
      </el-button>
      <AppSearchInput v-model="query" placeholder="搜索规则" />
    </AppControlRow>

    <AppAsyncRegion
      class="rule-master__region"
      :loading="loading"
      :has-content="rules.length > 0"
      :error="error ? '右侧内容已保留，重试后同步列表' : ''"
      :state-size="!loading && !error && !rules.length ? 'inline' : 'tiny'"
      error-title="规则列表刷新失败"
      :empty-title="query ? '没有匹配的规则' : '暂无交易规则'"
      retry
      @retry="emit('retry')"
    >
      <AppStateBlock
        v-if="!filteredRules.length"
        state="empty"
        size="inline"
        :title="query ? '没有匹配的规则' : '暂无交易规则'"
      />
      <AppScrollArea
        v-else
        class="rule-master__list app-scroll-paint-space"
        :content-style="{ gridAutoRows: 'max-content' }"
        role="group"
        aria-label="选择交易规则"
      >
        <div
          v-for="rule in filteredRules"
          :key="rule.id"
          class="rule-master__item app-interaction-target app-interaction-card app-interaction-card--inset"
          :class="{ active: selectedId === rule.id, 'is-selected': selectedId === rule.id }"
          role="button"
          tabindex="0"
          :aria-pressed="selectedId === rule.id"
          @click="emit('select', rule.id)"
          v-keyboard-activate
        >
          <div class="rule-master__name app-interaction-content">
            <span>{{ rule.proposed_name || rule.name || '未命名规则' }}</span>
            <el-tag v-if="rule.draft_revision" size="small" type="warning" effect="plain">草稿</el-tag>
          </div>
          <div class="rule-master__states app-interaction-content">
            <span>{{ checkinByRule.get(rule.id) ? `履约版本 v${checkinByRule.get(rule.id)?.version_no}` : effectiveLabel(rule) }}</span>
            <small
              class="rule-master__management"
              :class="`is-${managementTone(rule)}`"
            >{{ managementLabel(rule) }}</small>
          </div>
        </div>
      </AppScrollArea>
    </AppAsyncRegion>
  </aside>
</template>

<style scoped>
.rule-master {
  width: 100%;
  min-height: 0;
  overflow: hidden;
  padding: var(--app-space-2);
  display: flex;
  flex-direction: column;
  gap: var(--app-space-2);
}
.rule-master__tools { display: grid; grid-template-columns: minmax(0, 1fr); flex: none; }
.rule-master__create { width: 100%; }
.rule-master__region { min-height: 0; flex: 1 1 auto; display: flex; flex-direction: column; }
.rule-master__list {
  min-height: 0;
  flex: 1 1 auto;
  --app-scroll-display: grid;
  --app-scroll-align-content: start;
  --app-scroll-gap: var(--app-space-1);
  /* 四向绘制空间复用共享规则，借用外壳内距保持条目原始占位。 */
}
.rule-master__item {
  min-height: min-content;
  padding: var(--app-space-2) var(--app-space-3);
  cursor: pointer;
}
.rule-master__name { display: flex; align-items: center; justify-content: space-between; gap: var(--app-space-2); font-weight: var(--app-font-weight-section); }
.rule-master__name > span { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rule-master__states { margin-top: var(--app-space-1); display: flex; align-items: baseline; flex-wrap: wrap; gap: var(--app-space-1) var(--app-space-2); color: var(--el-text-color-secondary); font-size: var(--app-font-size-caption); line-height: var(--app-line-height-caption); }
.rule-master__management { text-align: left; color: var(--el-text-color-secondary); overflow-wrap: anywhere; }
.rule-master__management.is-success { color: var(--el-color-success); }
.rule-master__management.is-danger { color: var(--app-danger-text); }
.rule-master__management.is-warning { color: var(--app-warning-text); }
@container app-viewport (max-width: 1100px) {
  .rule-master { width: 100%; max-height: 210px; }
}
</style>
