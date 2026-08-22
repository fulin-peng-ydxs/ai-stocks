<script setup lang="ts">
import { computed, ref } from 'vue'
import { Plus } from '@element-plus/icons-vue'
import AppSearchInput from '@/components/AppSearchInput.vue'
import AppStateBlock from '@/components/AppStateBlock.vue'
import type { CheckinSummaryRule, TradeDisciplineRule } from '@/api/tradeDiscipline'

const props = defineProps<{
  rules: TradeDisciplineRule[]
  selectedId: string
  loading?: boolean
  canManage: boolean
  checkinStates?: CheckinSummaryRule[] | null
}>()

const emit = defineEmits<{
  select: [ruleId: string]
  create: []
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
    return checkin.assessment === 'complied'
      ? `已履约 · r${checkin.current_revision_no}`
      : `未履约 · r${checkin.current_revision_no}`
  }
  const event = rule.latest_management_event
  if (rule.has_pending_management_action && event) {
    const action = event.event_type === 'archive'
      ? '归档'
      : event.event_type === 'restore' ? '恢复' : `发布 v${event.version_no}`
    return `${action}待 ${event.effective_from_trade_date}`
  }
  if (rule.draft_revision) return '有编辑中草稿'
  if (rule.management_status === 'active') return `最新 v${rule.latest_version_no ?? '—'}`
  return rule.management_status === 'archived' ? '管理状态已归档' : '草稿（未发布）'
}
</script>

<template>
  <aside class="rule-master" aria-label="规则管理列表">
    <div class="rule-master__tools">
      <AppSearchInput v-model="query" size="small" placeholder="搜索规则" />
      <el-button
        v-if="canManage"
        v-permission="'trade-discipline:rule-manage'"
        type="primary"
        :icon="Plus"
        size="small"
        aria-label="新建规则"
        @click="emit('create')"
      >
        新建
      </el-button>
    </div>

    <AppStateBlock v-if="loading" state="loading" size="tiny" />
    <AppStateBlock
      v-else-if="!filteredRules.length"
      state="empty"
      size="compact"
      :title="query ? '没有匹配的规则' : '暂无交易规则'"
    />
    <div v-else class="rule-master__list" role="listbox" aria-label="选择交易规则">
      <div
        v-for="rule in filteredRules"
        :key="rule.id"
        class="rule-master__item"
        :class="{ active: selectedId === rule.id }"
        role="option"
        tabindex="0"
        :aria-selected="selectedId === rule.id"
        @click="emit('select', rule.id)"
        @keydown.enter="emit('select', rule.id)"
        @keydown.space.prevent="emit('select', rule.id)"
      >
        <div class="rule-master__name">
          <span>{{ rule.proposed_name || rule.name || '未命名规则' }}</span>
          <el-tag v-if="rule.draft_revision" size="small" type="warning" effect="plain">草稿</el-tag>
        </div>
        <div class="rule-master__states">
          <span>{{ checkinByRule.get(rule.id) ? `履约版本 v${checkinByRule.get(rule.id)?.version_no}` : effectiveLabel(rule) }}</span>
          <small>{{ managementLabel(rule) }}</small>
        </div>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.rule-master {
  width: 304px;
  flex: none;
  min-height: 0;
  overflow: hidden;
  padding: var(--app-space-2);
  border: 1px solid var(--el-border-color);
  border-radius: 8px;
  background: var(--el-bg-color-overlay);
  display: flex;
  flex-direction: column;
  gap: var(--app-space-2);
}
.rule-master__tools { display: flex; gap: var(--app-space-2); flex: none; }
.rule-master__list { min-height: 0; overflow: auto; display: grid; align-content: start; gap: var(--app-space-1); }
.rule-master__item {
  min-height: 70px;
  padding: var(--app-space-2) var(--app-space-3);
  border: 1px solid transparent;
  border-radius: 7px;
  cursor: pointer;
}
.rule-master__item:hover { background: var(--el-fill-color-light); }
.rule-master__item:focus-visible { outline: 2px solid var(--el-color-primary-light-3); outline-offset: 1px; }
.rule-master__item.active { border-color: var(--el-color-primary-light-5); background: var(--el-color-primary-light-9); }
.rule-master__name { display: flex; align-items: center; justify-content: space-between; gap: var(--app-space-2); font-weight: var(--app-font-weight-section); }
.rule-master__name > span { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rule-master__states { margin-top: var(--app-space-1); display: flex; justify-content: space-between; gap: var(--app-space-2); color: var(--el-text-color-secondary); font-size: var(--app-font-size-caption); }
.rule-master__states small { text-align: right; color: var(--el-color-warning); }
@media (max-width: 1100px) {
  .rule-master { width: 100%; max-height: 210px; }
}
</style>
