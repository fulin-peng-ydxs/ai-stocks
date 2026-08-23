<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ArrowDown, ArrowUp, Delete, Plus } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import AppIconButton from '@/components/AppIconButton.vue'
import AppStateBlock from '@/components/AppStateBlock.vue'
import { decimalToMinorUnits, formatMinorUnits } from '@/utils/fixedDecimal'
import FixedDecimalInput from '@/views/trade-discipline/components/FixedDecimalInput.vue'
import {
  archiveTradeDisciplineRule,
  copyTradeDisciplineRule,
  deleteTradeDisciplineRule,
  discardTradeDisciplineRuleDraft,
  getTradeDisciplineRule,
  openTradeDisciplineRuleDraft,
  publishTradeDisciplineRule,
  restoreTradeDisciplineRule,
  saveTradeDisciplineRuleDraft,
  type ActionSubtype,
  type ActionType,
  type DraftActionRule,
  type DraftStockRule,
  type RuleDraftPayload,
  type RuleVersionDetail,
  type TradeDisciplineRuleDetail,
} from '@/api/tradeDiscipline'

const props = defineProps<{
  ruleId: string
  tradeDate: string | null
  canManage: boolean
}>()

const emit = defineEmits<{
  changed: []
  deleted: []
  copied: [ruleId: string]
}>()

const detail = ref<TradeDisciplineRuleDetail | null>(null)
const loading = ref(false)
const loadError = ref(false)
const command = ref('')
const editing = ref(false)
const draftRevision = ref<number | null>(null)
const leaveDecisionVisible = ref(false)
const form = ref<RuleDraftPayload>(emptyPayload())
let baseline = ''
let resolveLeaveDecision: ((allowLeave: boolean) => void) | null = null
let loadRequest = 0

const dirty = computed(() => editing.value && fingerprint(form.value) !== baseline)
const enabledStockRules = computed(() => form.value.stock_rules.filter((item) => item.enabled))
const allocatedCapitalUnits = computed(() => enabledStockRules.value.reduce(
  (sum, item) => sum + (decimalToMinorUnits(item.max_capital) ?? 0n), 0n,
))
const totalCapitalUnits = computed(() => decimalToMinorUnits(form.value.capital) ?? 0n)
const remainingCapitalUnits = computed(() => totalCapitalUnits.value - allocatedCapitalUnits.value)
const allocatedCapitalText = computed(() => formatMinorUnits(allocatedCapitalUnits.value))
const remainingCapitalText = computed(() => formatMinorUnits(remainingCapitalUnits.value))
const capitalExceeded = computed(() => remainingCapitalUnits.value < 0n)
const hasSavedDraft = computed(() => Boolean(detail.value?.draft))
const isArchived = computed(() => detail.value?.management_status === 'archived')
const isUnpublished = computed(() => detail.value?.management_status === 'unpublished')
const canEditDetails = computed(() => props.canManage && editing.value && !isArchived.value)
const latestVersionLabel = computed(() => detail.value?.latest_version_no
  ? `当前正式 v${detail.value.latest_version_no}` : '尚无正式版本')

const subtypeOptions: Record<ActionType, Array<{ value: ActionSubtype; label: string }>> = {
  buy: [
    { value: 'open_position', label: '建仓' },
    { value: 'add_position', label: '加仓' },
  ],
  sell: [
    { value: 'liquidate', label: '清仓' },
    { value: 'do_t', label: '做 T' },
  ],
}

function emptyPayload(): RuleDraftPayload {
  return { name: null, capital: null, stock_rules: [], action_rules: [] }
}

function clonePayload(source: RuleDraftPayload | RuleVersionDetail | null): RuleDraftPayload {
  if (!source) return emptyPayload()
  return {
    name: source.name ?? null,
    capital: source.capital,
    stock_rules: source.stock_rules.map((item, index) => ({
      detail_id: item.detail_id ?? null,
      name: item.name ?? null,
      max_capital: item.max_capital,
      content: item.content ?? null,
      display_order: index + 1,
      enabled: Boolean(item.enabled),
    })),
    action_rules: source.action_rules.map((item, index) => ({
      detail_id: item.detail_id ?? null,
      name: item.name ?? null,
      action_type: item.action_type ?? null,
      action_subtype: item.action_subtype ?? null,
      content: item.content ?? null,
      display_order: index + 1,
      enabled: Boolean(item.enabled),
    })),
  }
}

function fingerprint(payload: RuleDraftPayload): string {
  return JSON.stringify(payload)
}

function setEditorSource(source: RuleDraftPayload | RuleVersionDetail | null, revision: number | null) {
  form.value = clonePayload(source)
  draftRevision.value = revision
  baseline = fingerprint(form.value)
  editing.value = revision !== null
}

async function load(): Promise<void> {
  if (!props.ruleId) return
  const request = ++loadRequest
  loading.value = true
  loadError.value = false
  try {
    const result = await getTradeDisciplineRule(props.ruleId, props.tradeDate)
    if (request !== loadRequest) return
    detail.value = result
    if (result.draft) setEditorSource(result.draft, result.draft.draft_revision)
    else setEditorSource(result.latest_version, null)
  } catch {
    if (request === loadRequest) loadError.value = true
  } finally {
    if (request === loadRequest) loading.value = false
  }
}

async function beginEdit(): Promise<void> {
  if (!detail.value || isArchived.value) return
  command.value = 'open'
  try {
    const draft = await openTradeDisciplineRuleDraft(detail.value.id)
    detail.value.draft = draft
    setEditorSource(draft, draft.draft_revision)
    emit('changed')
  } finally {
    command.value = ''
  }
}

function normalizedPayload(): RuleDraftPayload {
  return {
    name: form.value.name?.trim() || null,
    capital: form.value.capital === '' ? null : form.value.capital,
    stock_rules: form.value.stock_rules.map((item, index) => ({
      ...item,
      name: item.name?.trim() || null,
      content: item.content ?? null,
      max_capital: item.max_capital === '' ? null : item.max_capital,
      display_order: index + 1,
    })),
    action_rules: form.value.action_rules.map((item, index) => ({
      ...item,
      name: item.name?.trim() || null,
      content: item.content ?? null,
      display_order: index + 1,
    })),
  }
}

async function saveDraft(showMessage = true): Promise<boolean> {
  if (!detail.value || draftRevision.value === null) return false
  command.value = 'save'
  try {
    const saved = await saveTradeDisciplineRuleDraft(detail.value.id, {
      ...normalizedPayload(),
      expected_revision: draftRevision.value,
    })
    detail.value.draft = saved
    setEditorSource(saved, saved.draft_revision)
    if (showMessage) ElMessage.success('草稿已保存，当前正式版本未改变')
    emit('changed')
    return true
  } catch {
    return false
  } finally {
    command.value = ''
  }
}

function restoreBaseline(): void {
  const source = detail.value?.draft ?? detail.value?.latest_version ?? null
  setEditorSource(source, detail.value?.draft?.draft_revision ?? null)
}

function finishLeaveDecision(allowLeave: boolean): void {
  leaveDecisionVisible.value = false
  resolveLeaveDecision?.(allowLeave)
  resolveLeaveDecision = null
}

async function saveAndLeave(): Promise<void> {
  if (await saveDraft(false)) finishLeaveDecision(true)
}

function discardAndLeave(): void {
  restoreBaseline()
  finishLeaveDecision(true)
}

function continueEditing(): void {
  finishLeaveDecision(false)
}

function requestLeave(): Promise<boolean> {
  if (!dirty.value) return Promise.resolve(true)
  if (leaveDecisionVisible.value) return Promise.resolve(false)
  leaveDecisionVisible.value = true
  return new Promise((resolve) => { resolveLeaveDecision = resolve })
}

async function discardSavedDraft(): Promise<void> {
  if (!detail.value?.draft) return
  try {
    await ElMessageBox.confirm(
      `放弃编辑中草稿并恢复${latestVersionLabel.value}？`,
      '放弃工作草稿',
      { type: 'warning', confirmButtonText: '放弃草稿', confirmButtonClass: 'el-button--danger' },
    )
  } catch { return }
  command.value = 'discard'
  try {
    await discardTradeDisciplineRuleDraft(detail.value.id)
    await load()
    ElMessage.success('工作草稿已放弃，正式版本未改变')
    emit('changed')
  } finally {
    command.value = ''
  }
}

function validateForPublish(): boolean {
  if (!form.value.name?.trim()) return warn('发布前请填写规则名称')
  if (totalCapitalUnits.value <= 0n) return warn('发布前请填写大于 0 的总本金')
  if (!enabledStockRules.value.length) return warn('发布前至少启用一条选股规则')
  if (capitalExceeded.value) return warn(`启用选股规则合计超出本金 ${formatMinorUnits(-remainingCapitalUnits.value)} 元`)
  if (!enabledStockRules.value.every((item) => (decimalToMinorUnits(item.max_capital) ?? 0n) > 0n)) {
    return warn('启用的选股规则必须填写大于 0 的资金上限')
  }
  const actions = form.value.action_rules.filter((item) => item.enabled)
  if (!actions.some((item) => item.action_type === 'buy')) return warn('发布前至少启用一条买入规则')
  if (!actions.some((item) => item.action_type === 'sell')) return warn('发布前至少启用一条卖出规则')
  return true
}

function warn(message: string): false {
  ElMessage.warning(message)
  return false
}

async function publish(): Promise<void> {
  if (!detail.value || draftRevision.value === null || !validateForPublish()) return
  if (dirty.value && !(await saveDraft(false))) return
  command.value = 'publish'
  try {
    const result = await publishTradeDisciplineRule(detail.value.id, draftRevision.value!)
    ElMessage.success(result.changed
      ? `已发布 v${result.version_no}，从 ${result.effective_from_trade_date} 生效`
      : `草稿与 v${result.version_no} 一致，未生成新版本`)
    await load()
    emit('changed')
  } finally {
    command.value = ''
  }
}

async function copyRule(): Promise<void> {
  if (!detail.value) return
  if (dirty.value && !(await requestLeave())) return
  let source: 'published' | 'draft' = detail.value.draft ? 'draft' : 'published'
  if (detail.value.draft && detail.value.latest_version) {
    try {
      await ElMessageBox.confirm(
        '该规则同时存在正式版本和编辑中草稿，请选择复制来源。',
        '复制规则',
        {
          confirmButtonText: '复制草稿',
          cancelButtonText: '复制正式版本',
          distinguishCancelAndClose: true,
        },
      )
    } catch (action) {
      if (action === 'cancel') source = 'published'
      else return
    }
  }
  command.value = 'copy'
  try {
    const copied = await copyTradeDisciplineRule(detail.value.id, source)
    ElMessage.success('已复制为草稿（未发布）')
    emit('copied', copied.id)
  } finally {
    command.value = ''
  }
}

async function archiveOrRestore(): Promise<void> {
  if (!detail.value) return
  if (detail.value.draft) {
    ElMessage.warning('归档前请先发布或放弃工作草稿')
    return
  }
  const restoring = isArchived.value
  try {
    await ElMessageBox.confirm(
      restoring ? '恢复后将从下一真实交易日重新生效。' : '归档后将从下一真实交易日起停止生效。',
      restoring ? '恢复规则' : '归档规则',
      { type: 'warning', confirmButtonText: restoring ? '恢复' : '归档' },
    )
  } catch { return }
  command.value = restoring ? 'restore' : 'archive'
  try {
    const result = restoring
      ? await restoreTradeDisciplineRule(detail.value.id)
      : await archiveTradeDisciplineRule(detail.value.id)
    ElMessage.success(`${restoring ? '恢复' : '归档'}动作已提交，从 ${result.effective_from_trade_date} 生效`)
    await load()
    emit('changed')
  } finally {
    command.value = ''
  }
}

async function removeUnpublished(): Promise<void> {
  if (!detail.value || !isUnpublished.value) return
  try {
    await ElMessageBox.confirm(
      `删除未发布规则「${form.value.name || '未命名规则'}」？`,
      '删除未发布规则',
      { type: 'warning', confirmButtonText: '删除', confirmButtonClass: 'el-button--danger' },
    )
  } catch { return }
  command.value = 'delete'
  try {
    await deleteTradeDisciplineRule(detail.value.id)
    ElMessage.success('未发布规则已删除')
    emit('deleted')
  } finally {
    command.value = ''
  }
}

function addStockRule(): void {
  if (!canEditDetails.value) return
  form.value.stock_rules.push({
    detail_id: null, name: null, max_capital: null, content: null,
    display_order: form.value.stock_rules.length + 1, enabled: true,
  })
}

function addActionRule(): void {
  if (!canEditDetails.value) return
  form.value.action_rules.push({
    detail_id: null, name: null, action_type: 'buy', action_subtype: 'open_position',
    content: null, display_order: form.value.action_rules.length + 1, enabled: true,
  })
}

function move<T>(items: T[], index: number, offset: -1 | 1): void {
  if (!canEditDetails.value) return
  const target = index + offset
  if (target < 0 || target >= items.length) return
  const current = items[index]
  items[index] = items[target]
  items[target] = current
}

function removeStock(index: number): void {
  if (canEditDetails.value) form.value.stock_rules.splice(index, 1)
}
function removeAction(index: number): void {
  if (canEditDetails.value) form.value.action_rules.splice(index, 1)
}

function changeActionType(item: DraftActionRule): void {
  if (!item.action_type) { item.action_subtype = null; return }
  const available = subtypeOptions[item.action_type]
  if (!available.some((option) => option.value === item.action_subtype)) {
    item.action_subtype = available[0].value
  }
}

function managementText(): string {
  const event = detail.value?.latest_management_event
  if (!event) return isUnpublished.value ? '草稿（未发布）' : latestVersionLabel.value
  const verb = event.event_type === 'archive' ? '归档' : event.event_type === 'restore' ? '恢复' : `发布 v${event.version_no}`
  return detail.value?.has_pending_management_action
    ? `${verb}，待 ${event.effective_from_trade_date} 生效`
    : `${verb}已生效`
}

function effectiveText(): string {
  if (detail.value?.effective_status === 'active') return `当前按 v${detail.value.effective_version?.version_no ?? '—'} 履约`
  return detail.value?.effective_status === 'archived' ? '当前已归档' : '当前尚未生效'
}

watch(() => [props.ruleId, props.tradeDate], load, { immediate: true })

defineExpose({ isDirty: () => dirty.value, requestLeave, saveDraft })
</script>

<template>
  <section class="rule-editor" aria-label="规则编辑工作区">
    <AppStateBlock v-if="loading" state="loading" title="正在加载规则…" />
    <AppStateBlock v-else-if="loadError" state="error" title="规则详情加载失败" retry @retry="load" />
    <template v-else-if="detail">
      <header class="rule-editor__head">
        <div>
          <div class="detail-kicker">{{ latestVersionLabel }}</div>
          <h3 class="app-section-title">{{ form.name || detail.name || '未命名规则' }}</h3>
        </div>
        <div v-if="canManage" class="rule-editor__commands">
          <el-button v-permission="'trade-discipline:rule-manage'" :loading="command === 'copy'" @click="copyRule">复制</el-button>
          <el-button
            v-if="!isUnpublished"
            v-permission="'trade-discipline:rule-manage'"
            :type="isArchived ? 'primary' : 'danger'"
            plain
            :loading="command === 'archive' || command === 'restore'"
            @click="archiveOrRestore"
          >{{ isArchived ? '恢复' : '归档' }}</el-button>
          <el-button v-else v-permission="'trade-discipline:rule-manage'" type="danger" plain :loading="command === 'delete'" @click="removeUnpublished">删除</el-button>
        </div>
      </header>

      <div class="rule-state-track" aria-label="规则双状态">
        <div><span>当前有效</span><strong>{{ effectiveText() }}</strong></div>
        <div><span>管理动作</span><strong>{{ managementText() }}</strong></div>
        <div><span>编辑现场</span><strong>{{ hasSavedDraft ? `草稿 r${draftRevision}` : '无工作草稿' }}</strong></div>
      </div>

      <div v-if="!canManage" class="readonly-banner">当前账号只有查看权限。</div>
      <div v-else-if="isArchived" class="readonly-banner">归档规则不可编辑；恢复后可重新创建工作草稿。</div>
      <div v-else-if="!editing" class="readonly-banner">
        当前展示最新正式版本。创建工作草稿后再修改，正式版本不会被覆盖。
        <el-button v-permission="'trade-discipline:rule-manage'" type="primary" size="small" :loading="command === 'open'" @click="beginEdit">编辑规则</el-button>
      </div>

      <el-form class="rule-editor__form" label-position="top" :disabled="!editing || !canManage">
        <div class="rule-editor__base">
          <el-form-item label="规则名称">
            <el-input v-model="form.name" maxlength="80" placeholder="例如：趋势突破纪律" />
          </el-form-item>
          <el-form-item label="总本金（元）">
            <FixedDecimalInput v-model="form.capital" />
          </el-form-item>
          <div class="capital-meter" :class="{ danger: capitalExceeded }">
            <span>启用规则已分配 {{ allocatedCapitalText }}</span>
            <strong>剩余 {{ remainingCapitalText }}</strong>
          </div>
        </div>

        <section class="detail-group">
          <header><div><h4>选股规则</h4><p>仅启用项参与发布校验和资金汇总</p></div><el-button v-if="canEditDetails" v-permission="'trade-discipline:rule-manage'" :icon="Plus" @click="addStockRule">添加选股规则</el-button></header>
          <AppStateBlock v-if="!form.stock_rules.length" state="empty" size="tiny" title="尚未添加选股规则" />
          <article v-for="(item, index) in form.stock_rules" :key="item.detail_id || `stock-${index}`" class="detail-card">
            <div class="detail-card__head">
              <el-switch v-model="item.enabled" :disabled="!canEditDetails" active-text="启用" inactive-text="停用" />
              <div v-if="canEditDetails" class="detail-card__moves">
                <AppIconButton v-permission="'trade-discipline:rule-manage'" label="上移选股规则" size="sm" :disabled="index === 0" @click="move(form.stock_rules, index, -1)"><ArrowUp /></AppIconButton>
                <AppIconButton v-permission="'trade-discipline:rule-manage'" label="下移选股规则" size="sm" :disabled="index === form.stock_rules.length - 1" @click="move(form.stock_rules, index, 1)"><ArrowDown /></AppIconButton>
                <AppIconButton v-permission="'trade-discipline:rule-manage'" label="删除选股规则" size="sm" tone="danger" @click="removeStock(index)"><Delete /></AppIconButton>
              </div>
            </div>
            <div class="detail-card__grid">
              <el-form-item label="规则名称"><el-input v-model="item.name" maxlength="80" /></el-form-item>
              <el-form-item label="资金上限（元）"><FixedDecimalInput v-model="item.max_capital" /></el-form-item>
            </div>
            <el-form-item label="规则内容"><el-input v-model="item.content" type="textarea" :autosize="{ minRows: 3, maxRows: 10 }" resize="vertical" /></el-form-item>
          </article>
        </section>

        <section class="detail-group">
          <header><div><h4>买卖规则</h4><p>正式发布至少启用一条买入和一条卖出规则</p></div><el-button v-if="canEditDetails" v-permission="'trade-discipline:rule-manage'" :icon="Plus" @click="addActionRule">添加买卖规则</el-button></header>
          <AppStateBlock v-if="!form.action_rules.length" state="empty" size="tiny" title="尚未添加买卖规则" />
          <article v-for="(item, index) in form.action_rules" :key="item.detail_id || `action-${index}`" class="detail-card">
            <div class="detail-card__head">
              <el-switch v-model="item.enabled" :disabled="!canEditDetails" active-text="启用" inactive-text="停用" />
              <div v-if="canEditDetails" class="detail-card__moves">
                <AppIconButton v-permission="'trade-discipline:rule-manage'" label="上移买卖规则" size="sm" :disabled="index === 0" @click="move(form.action_rules, index, -1)"><ArrowUp /></AppIconButton>
                <AppIconButton v-permission="'trade-discipline:rule-manage'" label="下移买卖规则" size="sm" :disabled="index === form.action_rules.length - 1" @click="move(form.action_rules, index, 1)"><ArrowDown /></AppIconButton>
                <AppIconButton v-permission="'trade-discipline:rule-manage'" label="删除买卖规则" size="sm" tone="danger" @click="removeAction(index)"><Delete /></AppIconButton>
              </div>
            </div>
            <div class="detail-card__grid detail-card__grid--actions">
              <el-form-item label="规则名称"><el-input v-model="item.name" maxlength="80" /></el-form-item>
              <el-form-item label="方向"><el-select v-model="item.action_type" @change="changeActionType(item)"><el-option label="买入" value="buy" /><el-option label="卖出" value="sell" /></el-select></el-form-item>
              <el-form-item label="类型"><el-select v-model="item.action_subtype"><el-option v-for="option in item.action_type ? subtypeOptions[item.action_type] : []" :key="option.value" :label="option.label" :value="option.value" /></el-select></el-form-item>
            </div>
            <el-form-item label="规则内容"><el-input v-model="item.content" type="textarea" :autosize="{ minRows: 3, maxRows: 10 }" resize="vertical" /></el-form-item>
          </article>
        </section>
      </el-form>

      <footer v-if="canManage && editing" class="rule-editor__footer">
        <span v-if="dirty" class="dirty-copy">有未保存修改</span>
        <el-button v-permission="'trade-discipline:rule-manage'" @click="restoreBaseline">取消未保存修改</el-button>
        <el-button v-if="hasSavedDraft && !isUnpublished" v-permission="'trade-discipline:rule-manage'" type="danger" plain :loading="command === 'discard'" @click="discardSavedDraft">放弃草稿</el-button>
        <el-button v-permission="'trade-discipline:rule-manage'" :loading="command === 'save'" @click="saveDraft()">保存草稿</el-button>
        <el-button v-permission="'trade-discipline:rule-manage'" type="primary" :loading="command === 'publish'" @click="publish">保存并启用</el-button>
      </footer>

      <el-dialog
        v-model="leaveDecisionVisible"
        title="未保存的规则修改"
        width="460px"
        :show-close="false"
        :close-on-click-modal="false"
        :close-on-press-escape="false"
        :teleported="false"
      >
        <p class="leave-decision-copy">当前规则有未保存修改。请选择如何处理后再离开。</p>
        <template #footer>
          <el-button @click="continueEditing">继续编辑</el-button>
          <el-button v-permission="'trade-discipline:rule-manage'" type="danger" plain @click="discardAndLeave">放弃修改</el-button>
          <el-button v-permission="'trade-discipline:rule-manage'" type="primary" :loading="command === 'save'" @click="saveAndLeave">保存草稿</el-button>
        </template>
      </el-dialog>
    </template>
  </section>
</template>

<style scoped>
.rule-editor { min-width: 520px; min-height: 0; overflow: auto; flex: 1 1 auto; padding: var(--app-space-5); border: 1px solid var(--el-border-color); border-radius: 8px; background: var(--el-bg-color-overlay); }
.rule-editor__head, .rule-editor__commands, .detail-group > header, .detail-card__head, .detail-card__moves, .rule-editor__footer { display: flex; align-items: center; }
.rule-editor__head { justify-content: space-between; gap: var(--app-space-3); }
.rule-editor__head .app-section-title { margin: var(--app-space-1) 0 0; }
.rule-editor__commands, .detail-card__moves { gap: var(--app-space-1); }
.rule-state-track { margin: var(--app-space-4) 0; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); border: 1px solid var(--el-border-color-lighter); border-radius: 7px; overflow: hidden; }
.rule-state-track > div { padding: var(--app-space-3); background: var(--el-fill-color-extra-light); }
.rule-state-track > div + div { border-left: 1px solid var(--el-border-color-lighter); }
.rule-state-track span { display: block; color: var(--el-text-color-secondary); font-size: var(--app-font-size-caption); }
.rule-state-track strong { display: block; margin-top: var(--app-space-1); color: var(--el-text-color-primary); font-size: var(--app-font-size-table); }
.readonly-banner { margin-bottom: var(--app-space-4); padding: var(--app-space-3); border-left: 3px solid var(--el-color-warning); background: var(--el-color-warning-light-9); color: var(--el-text-color-secondary); display: flex; align-items: center; justify-content: space-between; gap: var(--app-space-3); }
.rule-editor__base { display: grid; grid-template-columns: minmax(220px, 1fr) minmax(180px, 0.7fr) minmax(200px, 0.8fr); gap: var(--app-space-3); align-items: end; }
.rule-editor__base :deep(.el-input) { width: 100%; }
.capital-meter { min-height: var(--app-control-height-md); margin-bottom: 18px; padding: 0 var(--app-space-3); border-radius: 6px; background: var(--el-color-success-light-9); color: var(--el-color-success-dark-2); display: flex; align-items: center; justify-content: space-between; gap: var(--app-space-2); font-size: var(--app-font-size-caption); }
.capital-meter.danger { background: var(--el-color-danger-light-9); color: var(--el-color-danger); }
.detail-group { margin-top: var(--app-space-5); }
.detail-group > header { justify-content: space-between; gap: var(--app-space-3); margin-bottom: var(--app-space-2); }
.detail-group h4 { margin: 0; font-size: var(--app-font-size-section); }
.detail-group p { margin: var(--app-space-1) 0 0; color: var(--el-text-color-secondary); font-size: var(--app-font-size-caption); }
.detail-card { padding: var(--app-space-3); border: 1px solid var(--el-border-color-lighter); border-radius: 7px; background: var(--el-bg-color); }
.detail-card + .detail-card { margin-top: var(--app-space-2); }
.detail-card__head { justify-content: space-between; margin-bottom: var(--app-space-2); }
.detail-card__grid { display: grid; grid-template-columns: minmax(220px, 1fr) minmax(180px, 0.65fr); gap: var(--app-space-3); }
.detail-card__grid--actions { grid-template-columns: minmax(220px, 1fr) 120px 140px; }
.rule-editor__footer { position: sticky; bottom: calc(var(--app-space-5) * -1); z-index: 2; justify-content: flex-end; gap: var(--app-space-2); margin: var(--app-space-5) calc(var(--app-space-5) * -1) calc(var(--app-space-5) * -1); padding: var(--app-space-3) var(--app-space-5); border-top: 1px solid var(--el-border-color); background: var(--el-bg-color-overlay); }
.dirty-copy { margin-right: auto; color: var(--el-color-warning); font-size: var(--app-font-size-caption); }
.leave-decision-copy { margin: 0; color: var(--el-text-color-regular); line-height: var(--app-line-height-longform); }
@media (max-width: 1100px) {
  .rule-editor { min-width: 0; overflow: visible; }
  .rule-state-track, .rule-editor__base { grid-template-columns: 1fr; }
  .rule-state-track > div + div { border-left: 0; border-top: 1px solid var(--el-border-color-lighter); }
  .capital-meter { margin-bottom: 0; }
}
@media (max-width: 760px) {
  .rule-editor__head, .detail-group > header { align-items: stretch; flex-direction: column; }
  .rule-editor__commands { flex-wrap: wrap; }
  .detail-card__grid, .detail-card__grid--actions { grid-template-columns: 1fr; }
  .rule-editor__footer { flex-wrap: wrap; }
}
</style>
