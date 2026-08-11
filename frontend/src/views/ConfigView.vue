<script setup lang="ts">
import AppTableColumn from '@/components/AppTableColumn.vue'
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Close, Plus, VideoPlay } from '@element-plus/icons-vue'
import {
  browseScoreProfiles,
  copyScoreProfile,
  deleteIndicatorDef,
  deleteScoreProfile,
  getIndicatorRegistry,
  getScoreProfile,
  getScoreProfileVersions,
  listScoreProfiles,
  runScoreProfile,
  saveIndicatorDef,
  saveScoreProfile,
  setScoreProfileVisibility,
  setIndicatorCategories,
  setIndicatorEnabled,
  type IndicatorDef,
  type IndicatorParam,
  type ScoreItem,
  type ScoreProfileSummary,
  type ScoreProfileVersion,
  type ScoreRunRow,
} from '@/api/scoreProfile'
import AssetVisibilityActions from '@/components/AssetVisibilityActions.vue'
import AssetProfileSelect from '@/components/asset-search/AssetProfileSelect.vue'
import AppDataTable from '@/components/AppDataTable.vue'
import AppStateBlock from '@/components/AppStateBlock.vue'
import AppIconButton from '@/components/AppIconButton.vue'
import AppRowActions from '@/components/AppRowActions.vue'
import HelpTip from '@/components/HelpTip.vue'
import SystemBuiltinTag from '@/components/SystemBuiltinTag.vue'
import TradeDatePicker from '@/components/TradeDatePicker.vue'
import { getErrorMessage } from '@/utils/error'
import PageSettingSection from '@/components/PageSettingSection.vue'
import PageSettingsDrawer from '@/components/PageSettingsDrawer.vue'
import PageSettingsTrigger from '@/components/PageSettingsTrigger.vue'
import PageToggleRow from '@/components/PageToggleRow.vue'
import ConfigGroupForm from '@/components/config/ConfigGroupForm.vue'
import { usePageSettings } from '@/composables/usePageSettings'
import { useTableSort } from '@/composables/useTableSort'
import { getSettingsView, resetSettings, saveSettings, type MailStatus, type SettingGroup } from '@/api/data'
import LayoutHost from '@/layout/components/LayoutHost.vue'
import { getPageLayout } from '@/layout'
import type { SlotConfigMeta } from '@/layout/pageRegistry'
import {
  CONFIG_SYSTEM_GROUP_TABS,
  configPanelCollapseSectionsOf,
  configPanelSectionsOf,
  type ConfigPanelBehavior,
} from '@/layout/configPanel'
import { useRemoteLayoutConfig } from '@/composables/useRemoteLayoutConfig'
import { useAuthStore } from '@/stores/auth'
import { hasPermission } from '@/utils/permission'
import { confirmProfileVisibilityReduction } from '@/utils/assetVisibility'
import type { AppRowAction } from '@/components/rowActions'
import type { AssetBrowseParams, ProfileSummary } from '@/components/asset-search/types'

const settingsOpen = ref(false)
const route = useRoute()
const auth = useAuthStore()
type ConfigTab = 'score' | 'tech' | 'trade' | 'system'
const forcedTab = computed<ConfigTab | null>(() => (route.meta.configTab as ConfigTab | undefined) ?? null)
const activeTab = computed<ConfigTab>(() => forcedTab.value || 'score')
function configPageKeyOf(tab: ConfigTab): string {
  return `config-${tab}`
}
const configPageKey = configPageKeyOf(activeTab.value)
const pageTitle = computed(() => {
  if (forcedTab.value === 'score') return '评分规则'
  if (forcedTab.value === 'trade') return '买卖指标'
  if (forcedTab.value === 'tech') return '技术指标'
  if (forcedTab.value === 'system') return '系统设置'
  return '配置管理'
})
const configDefaults = {
  previewExpanded: true,
}
const { settings, isDirty, reset } = usePageSettings(configPageKey, configDefaults)

// 布局声明统一取自 pageRegistry（单一事实源），不再页面内联手写 PageLayout。
const configLayout = getPageLayout(configPageKey)
const {
  effective: configEffective,
  knobs: layoutKnobs,
  setKnob,
  valueOf,
  sourceOf,
  isDirty: layoutDirty,
  resetAll: resetLayout,
  componentValueOf,
  setComponentKnob,
  componentSourceOf,
  layerValuesOf,
  componentLayerValuesOf,
} = useRemoteLayoutConfig(configLayout)

// 抽屉由 PageSettingsDrawer 按布局旋钮渲染；本页不再暴露 tabs 组件配置。
const drawerConfig = { knobs: layoutKnobs, valueOf, sourceOf, setKnob, componentValueOf, setComponentKnob, componentSourceOf, layerValuesOf, componentLayerValuesOf }

const TECH_SORT_FIELDS = ['catOrder', 'name_cn', 'typeLabel', 'srcLabel', 'hasParams'] as const
const {
  sortBy: techSortBy,
  sortOrder: techSortOrder,
  elementDefaultSort: techDefaultSort,
  onSortChange: onTechSortChange,
} = useTableSort<(typeof TECH_SORT_FIELDS)[number]>({
  slotId: 'techTable',
  defaultSort: 'catOrder:asc',
  componentValueOf,
  setComponentKnob,
  allowedFields: TECH_SORT_FIELDS,
  defaultOrder: 'asc',
})
function tableBorder(slotId: string): boolean {
  return componentValueOf(slotId, 'border') === true
}

// ── 系统设置（FR-DM-12：真实参数 Web 可编辑，写 app_config 覆盖层）──
const sysGroups = ref<SettingGroup[]>([])
const mailStatus = ref<MailStatus | null>(null)
const sysDraft = ref<Record<string, unknown>>({})
const sysLoading = ref(false)
const sysSaving = ref(false)
const sysSaveError = ref(false)
const activeSysTab = ref('access')
interface SystemGroupTab {
  key: string
  label: string
  groups: SettingGroup[]
}
const canManageSystemSettings = computed(() =>
  hasPermission(auth.role, auth.permissions, 'data-settings:manage'),
)
const configPanelBehavior = computed<ConfigPanelBehavior>(() => {
  const defaultCollapsed = componentValueOf('configPanel', 'defaultCollapsed')
  return {
    collapsibleSections: componentValueOf('configPanel', 'collapsibleSections') !== false,
    defaultCollapsed: Array.isArray(defaultCollapsed) ? (defaultCollapsed as string[]) : [],
    showGroupDescription: componentValueOf('configPanel', 'showGroupDescription') !== false,
    showSectionDescription: componentValueOf('configPanel', 'showSectionDescription') !== false,
  }
})
async function loadSystem() {
  if (!canManageSystemSettings.value) return
  sysLoading.value = true
  sysSaveError.value = false
  try {
    const { groups, mail_status } = await getSettingsView()
    sysGroups.value = groups
    mailStatus.value = mail_status ?? null
    const d: Record<string, unknown> = {}
    groups.forEach((g) => g.fields.forEach((f) => { d[f.path] = f.value }))
    sysDraft.value = d
  } finally { sysLoading.value = false }
}

// 只读能力就绪徽标：挂在「注册需邮箱验证码」开关下，提示底层真实发信是否就绪（部署级，页面不可改）。
// 这是「开关 + 能力就绪提示」的样板；后续新能力集成可复用同一 fieldStatus 机制（见开发留痕·可扩展）。
type FieldStatus = { tone: 'ok' | 'warn'; text: string }
const systemFieldStatus = computed<Record<string, FieldStatus>>(() => {
  const out: Record<string, FieldStatus> = {}
  const m = mailStatus.value
  if (!m) return out
  // 文案按 mode 精确对齐后端/mailer 真实分支：incomplete 会发码失败（非只写日志）。
  if (m.mode === 'ready') {
    out['auth.require_email_code'] = { tone: 'ok', text: `真实发信已就绪（${m.username_masked}）` }
  } else if (m.mode === 'incomplete') {
    out['auth.require_email_code'] = { tone: 'warn', text: '真实发信已开启但配置不完整，发码会失败（部署侧补全 AI_STOCKS_SMTP_*）' }
  } else {
    out['auth.require_email_code'] = { tone: 'warn', text: '真实发信未启用，验证码只写日志不真发（部署侧配 AI_STOCKS_SMTP_*）' }
  }
  return out
})
function updateSystemField(path: string, value: unknown) {
  sysDraft.value = { ...sysDraft.value, [path]: value }
}
const sysDirty = computed(() => {
  for (const g of sysGroups.value) for (const f of g.fields) {
    if (sysDraft.value[f.path] !== f.value) return true
  }
  return false
})
function systemFieldInvalid(field: SettingGroup['fields'][number], value: unknown): boolean {
  if (field.type === 'bool') return typeof value !== 'boolean'
  if (field.type === 'enum') return !(field.options ?? []).includes(String(value))
  // string/password：文本字段无数值范围校验，直接放行
  if (field.type === 'string' || field.type === 'password') return false
  const n = Number(value)
  if (!Number.isFinite(n)) return true
  if (field.type === 'int' && !Number.isInteger(n)) return true
  if (field.min != null && n < field.min) return true
  if (field.max != null && n > field.max) return true
  return false
}
const sysInvalidPaths = computed(() => {
  const invalid: string[] = []
  for (const group of sysGroups.value) {
    for (const field of group.fields) {
      if (systemFieldInvalid(field, sysDraft.value[field.path])) invalid.push(field.path)
    }
  }
  return invalid
})
const sysTabs = computed<SystemGroupTab[]>(() => {
  const groupsByKey = new Map(sysGroups.value.map((group) => [group.key, group]))
  const tabs = CONFIG_SYSTEM_GROUP_TABS.map((tab) => ({
    key: tab.key,
    label: tab.label,
    groups: tab.groupKeys.map((key) => groupsByKey.get(key)).filter((group): group is SettingGroup => !!group),
  })).filter((tab) => tab.groups.length)
  const used = new Set(CONFIG_SYSTEM_GROUP_TABS.flatMap((tab) => tab.groupKeys))
  const extra = sysGroups.value.filter((group) => !used.has(group.key))
  if (extra.length) tabs.push({ key: 'other', label: '其他', groups: extra })
  return tabs
})
const activeSysGroups = computed(() =>
  sysTabs.value.find((tab) => tab.key === activeSysTab.value)?.groups ?? [],
)
const configPanelMetaOverrides = computed<Record<string, SlotConfigMeta> | undefined>(() => {
  if (activeTab.value !== 'system') return undefined
  return {
    configPanel: {
      collapseSections: configPanelCollapseSectionsOf(activeSysGroups.value),
    },
  }
})
const activeSysPaths = computed(() =>
  activeSysGroups.value.flatMap((group) => group.fields.map((field) => field.path)),
)
async function saveSystem() {
  if (!canManageSystemSettings.value) return
  if (sysInvalidPaths.value.length) {
    ElMessage.warning('请修正超出范围的配置项')
    return
  }
  const updates: Record<string, unknown> = {}
  for (const g of sysGroups.value) for (const f of g.fields) {
    if (sysDraft.value[f.path] !== f.value) updates[f.path] = sysDraft.value[f.path]
  }
  if (!Object.keys(updates).length) { ElMessage.info('无修改'); return }
  sysSaving.value = true
  sysSaveError.value = false
  try {
    await saveSettings(updates)
    ElMessage.success('配置已更新')
    await loadSystem()
  } catch {
    sysSaveError.value = true
  } finally { sysSaving.value = false }
}
async function resetActiveSystemTab() {
  if (!canManageSystemSettings.value || !activeSysPaths.value.length) return
  const tabLabel = sysTabs.value.find((tab) => tab.key === activeSysTab.value)?.label || '当前配置'
  await ElMessageBox.confirm(
    `确认将「${tabLabel}」下所有配置恢复为默认值？未保存的编辑也会被丢弃。`,
    '重置配置',
    { type: 'warning' },
  )
  sysSaving.value = true
  sysSaveError.value = false
  try {
    await resetSettings(activeSysPaths.value)
    ElMessage.success('配置已重置')
    await loadSystem()
  } catch {
    sysSaveError.value = true
  } finally { sysSaving.value = false }
}
watch(() => sysTabs.value.map((tab) => tab.key).join('|'), () => {
  if (!sysTabs.value.some((tab) => tab.key === activeSysTab.value)) {
    activeSysTab.value = sysTabs.value[0]?.key || 'access'
  }
})
// ── 技术指标注册表（含内置 + 自定义）──
const registry = ref<IndicatorDef[]>([])
// 可作为评分项的指标（启用项）
const scorable = computed(() => registry.value.filter((d) => d.enabled))
function nameOf(key: string): string {
  return registry.value.find((d) => d.key === key)?.name_cn || key
}
function defOf(key: string): IndicatorDef | undefined {
  return registry.value.find((d) => d.key === key)
}
async function reloadRegistry() {
  registry.value = (await getIndicatorRegistry(true)).items
}

// 技术指标列表：搜索 + 排序 + 多分类
const techSearch = ref('')
// 分类默认排序：按预设角度顺序，自定义分类排其后(中文序)
const CATEGORY_ORDER = ['趋势', '动量', '量能', '位置', '均线', '突破', '估值', '换手', '形态', '强度', '新高', '事件', '筹码']
function sortCats(cats: string[]): string[] {
  return [...(cats ?? [])].sort((a, b) => {
    const ia = CATEGORY_ORDER.indexOf(a), ib = CATEGORY_ORDER.indexOf(b)
    if (ia !== -1 || ib !== -1) return (ia === -1 ? 999 : ia) - (ib === -1 ? 999 : ib)
    return a.localeCompare(b, 'zh')
  })
}
const allCategories = computed(() => {
  const s = new Set<string>()
  registry.value.forEach((d) => (d.categories ?? []).forEach((c) => s.add(c)))
  return sortCats([...s])
})
const techRows = computed(() => {
  const q = techSearch.value.trim().toLowerCase()
  const rows = registry.value.map((d) => {
    const cats = sortCats(d.categories ?? [])
    const idx = cats.length ? CATEGORY_ORDER.indexOf(cats[0]) : -1
    return {
      ...d,
      categories: cats,
      catOrder: cats.length ? (idx === -1 ? 900 : idx) : 999, // 按主分类的角度顺序排序
      srcLabel: d.is_builtin ? '系统内置' : '自定义',
      hasParams: (d.params?.length ?? 0) > 0,
      typeLabel: d.dtype === 'bool' ? '布尔' : '数值',
    }
  })
  const filtered = !q ? rows : rows.filter((d) =>
    [d.name_cn, d.key, d.desc, ...(d.categories ?? [])].join(' ').toLowerCase().includes(q),
  )
  const factor = techSortOrder.value === 'desc' ? -1 : 1
  filtered.sort((a, b) => {
    if (techSortBy.value === 'catOrder') return (a.catOrder - b.catOrder) * factor
    if (techSortBy.value === 'hasParams') return (Number(a.hasParams) - Number(b.hasParams)) * factor
    const av = String(a[techSortBy.value] ?? '')
    const bv = String(b[techSortBy.value] ?? '')
    return av.localeCompare(bv, 'zh') * factor
  })
  return filtered
})
async function onCategoriesChange(key: string, cats: string[]) {
  await setIndicatorCategories(key, cats)
  await reloadRegistry()
}

// 技术指标管理：启停 / 删除 / 新建自定义
async function toggleEnabled(row: IndicatorDef) {
  await setIndicatorEnabled(row.key, !row.enabled)
  await reloadRegistry()
}
async function removeDef(row: IndicatorDef) {
  await ElMessageBox.confirm(`确认删除自定义指标「${row.name_cn}」？`, '提示', { type: 'warning' })
  await deleteIndicatorDef(row.key)
  ElMessage.success('已删除')
  await reloadRegistry()
}

function indicatorDefRowActions(row: IndicatorDef): AppRowAction[] {
  if (row.is_builtin) return []
  return [
    {
      key: 'delete',
      label: '删除',
      type: 'danger',
      permission: 'indicator:def-manage',
      onClick: () => removeDef(row),
    },
  ]
}

const defDialog = ref(false)
const defForm = ref<{
  key: string; name_cn: string; dtype: 'bool' | 'number'; expression: string
  category: string; desc: string; params: IndicatorParam[]; categories: string[]
}>({ key: '', name_cn: '', dtype: 'bool', expression: '', category: '自定义', desc: '', params: [], categories: [] })

function openNewDef() {
  defForm.value = { key: '', name_cn: '', dtype: 'bool', expression: '', category: '自定义', desc: '', params: [], categories: [] }
  defDialog.value = true
}
function addDefParam() {
  defForm.value.params.push({ name: 'n', label: '参数', type: 'int', default: 5, min: null, max: null })
}
function removeDefParam(i: number) {
  defForm.value.params.splice(i, 1)
}
async function submitNewDef() {
  const f = defForm.value
  if (!f.key || !f.name_cn || !f.expression) {
    ElMessage.warning('请填写标识、名称、表达式')
    return
  }
  try {
    await saveIndicatorDef({
      key: f.key, name_cn: f.name_cn, dtype: f.dtype, expression: f.expression,
      params: f.params, category: f.category, desc: f.desc, categories: f.categories,
    })
    ElMessage.success('已保存')
    defDialog.value = false
    await reloadRegistry()
  } catch {
    /* 错误已由拦截器提示 */
  }
}

// ── 评分方案 ──
// R3/R5/R7：侧栏列表统一走 AssetProfileSelect（list 形态）——只加载「我的」（source=mine 纯 owner），
// 「搜索」入口打开共享搜索抽屉（系统内置/租户公开/全体公开），「加载查看」注入临时只读项、
// 「复制为我的」由后端生成唯一 id 并自动刷新选中；本页不再维护前端撞库/列表来源逻辑。
const profiles = ref<ScoreProfileSummary[]>([])
// 方案详情加载（选中→编辑器）独立状态：加载态/错误态/竞态守卫（P1-2）
const profileDetailLoading = ref(false)
const profileDetailError = ref('')
let scoreDetailSeq = 0
// 详情加载失败时的目标项（用于错误块重试——curRef 已回滚，需凭此重试用户真正想选的方案）
let scoreDetailAttempt = ''
// 最后一次成功载入编辑器的方案 ref（失败回滚的目标；不能用 curRef——onScoreSelect 已先写入新值）
let scoreLastAppliedRef = ''
const curRef = ref<string>('')
const curId = ref<string>('')
const curVersion = ref<number | null>(null)
const editId = ref('')
const editName = ref('')
const items = ref<ScoreItem[]>([])
const saving = ref(false)
const visibilitySaving = ref(false)
const isNew = ref(false)
const profileReadonly = ref(false)
const profileVisibility = ref<'private' | 'tenant' | 'public'>('private')
const canPublishTenant = computed(() =>
  hasPermission(auth.role, auth.permissions, 'score-profile:publish-tenant'),
)
const canPublishPublic = computed(() =>
  hasPermission(auth.role, auth.permissions, 'score-profile:publish-public'),
)
const canViewScoreProfiles = computed(() =>
  hasPermission(auth.role, auth.permissions, 'score-profile:view'),
)
const canSaveScoreProfiles = computed(() =>
  hasPermission(auth.role, auth.permissions, 'score-profile:save'),
)
const weightSum = computed(() =>
  Math.round(items.value.reduce((s, it) => s + (it.weight || 0), 0) * 100),
)

const scoreSelectRef = ref<InstanceType<typeof AssetProfileSelect> | null>(null)
async function fetchMineScoreProfiles(): Promise<ScoreProfileSummary[]> {
  // 无 score-profile:view 的角色不拉方案列表（避免 403 卡住页面主体）
  if (!canViewScoreProfiles.value) return []
  return listScoreProfiles('mine')
}
function browseScore(params: AssetBrowseParams) {
  return browseScoreProfiles(params)
}
function copyAnyScoreProfile(item: ProfileSummary) {
  return copyScoreProfile(item.profile_ref || item.id)
}

// 评分 mine 列表由选择器组件唯一拉取（onMounted 与 save/delete/publish/copy 后均只经组件 reload 一次），
// 回写经组件 ready 事件进入 onScoreReady → profiles.value；本页不再保留私有直连拉取（P2-1）。

// 供「加载查看」临时只读项回显：注入侧栏顶部，点击/选中后走统一 selectProfile 载入编辑器。
// P1-2：原子应用详情 + 失败回滚选中值 + seq 竞态守卫，保证「选中项 == 编辑器内容」不错位。
async function selectProfile(profileKey: string) {
  if (!profileKey) return
  const seq = ++scoreDetailSeq
  scoreDetailAttempt = profileKey
  profileDetailLoading.value = true
  profileDetailError.value = ''
  try {
    const p = await getScoreProfile(profileKey)
    if (seq !== scoreDetailSeq) return
    clearScoreRunResult()
    // 成功才整体写入编辑器（原子应用，不写一半）
    curRef.value = p.profile_ref || profileKey
    curId.value = p.id
    curVersion.value = p.version
    editId.value = p.id
    editName.value = p.name
    items.value = JSON.parse(JSON.stringify(p.items))
    items.value.forEach(ensureParams)
    profileReadonly.value = !!p.readonly
    profileVisibility.value = p.visibility || 'private'
    isNew.value = false
    scoreLastAppliedRef = curRef.value
  } catch (e) {
    if (seq !== scoreDetailSeq) return
    // 失败回滚到最后成功载入的项，编辑器保留旧内容，避免出现「选中新方案、保存到旧方案」
    curRef.value = scoreLastAppliedRef
    profileDetailError.value = getErrorMessage(e, '评分方案详情加载失败')
  } finally {
    if (seq === scoreDetailSeq) profileDetailLoading.value = false
  }
}
// 侧栏选择器选中变化（含「加载查看」注入的临时只读项）→ 载入编辑器；不自动试算。
// 选择器 v-model 同步 curRef 后即调用本函数作为唯一载入入口（含临时只读项）。
function onScoreSelect(key: string) {
  curRef.value = key
  if (!key) return
  void selectProfile(key)
}

// ── 评分方案历史版本（回看/载入；载入仅写入编辑器，保存后才生成新版本）──
const sVerVisible = ref(false)
const sVersions = ref<ScoreProfileVersion[]>([])
async function openScoreVersions() {
  if (!curRef.value) return
  sVersions.value = (await getScoreProfileVersions(curRef.value)).versions
  sVerVisible.value = true
}
function restoreScoreVersion(v: ScoreProfileVersion) {
  items.value = JSON.parse(JSON.stringify(v.items))
  items.value.forEach(ensureParams)
  sVerVisible.value = false
  ElMessage.success(`已载入 v${v.version} 到编辑器，确认后点「保存」生成新版本`)
}

function scoreVersionRowActions(v: ScoreProfileVersion): AppRowAction[] {
  if (!canSaveScoreProfiles.value) return []
  if (profileReadonly.value) {
    return [
      { key: 'copy', label: '复制此版本为我的', onClick: () => { void copyCurrentScoreProfile(v.version) } },
    ]
  }
  return [
    { key: 'restore', label: '载入此版本', onClick: () => restoreScoreVersion(v) },
  ]
}

// 确保评分项的 params 含该指标全部参数（补默认值），供参数输入框绑定
function ensureParams(item: ScoreItem) {
  if (!item.params) item.params = {}
  const def = defOf(item.indicator)
  for (const p of def?.params ?? []) {
    if (item.params[p.name] === undefined) item.params[p.name] = p.default
  }
}

function newProfile() {
  scoreDetailSeq += 1
  curRef.value = ''
  curId.value = ''
  curVersion.value = null
  editId.value = ''
  editName.value = ''
  items.value = []
  profileReadonly.value = false
  profileVisibility.value = 'private'
  isNew.value = true
  // 新建态同步清空「最后成功项」，避免后续详情失败回滚到已废弃的旧方案
  scoreLastAppliedRef = ''
  scoreDetailAttempt = ''
  profileDetailError.value = ''
  clearScoreRunResult()
}

// 新增评分项（默认 bool / 平均分配权重）
function addItem() {
  const used = new Set(items.value.map((i) => i.indicator))
  const cand = scorable.value.find((d) => !used.has(d.key))
  if (!cand) {
    ElMessage.warning('没有更多可添加的指标')
    return
  }
  const def: ScoreItem = {
    indicator: cand.key,
    params: defaultParams(cand),
    weight: 0,
    scoring: cand.dtype === 'bool' ? { type: 'bool' } : { type: 'linear', min: 0, max: 100 },
  }
  items.value.push(def)
  rebalanceEqual()
}

function defaultParams(def: IndicatorDef): Record<string, number> {
  const p: Record<string, number> = {}
  for (const param of def.params) p[param.name] = param.default
  return p
}

function removeItem(idx: number) {
  items.value.splice(idx, 1)
  rebalanceEqual()
}

function scoreItemRowActions(idx: number): AppRowAction[] {
  return [
    {
      key: 'delete',
      label: '删除',
      type: 'danger',
      disabled: profileReadonly.value,
      onClick: () => removeItem(idx),
    },
  ]
}

// 当指标类型切换为 bool 时，scoring 自动切 bool；数值默认 linear
function onIndicatorChange(item: ScoreItem) {
  const def = defOf(item.indicator)
  item.params = def ? defaultParams(def) : {}
  if (def?.dtype === 'bool') item.scoring = { type: 'bool' }
  else if (item.scoring.type === 'bool') item.scoring = { type: 'linear', min: 0, max: 100 }
}

function onScoringTypeChange(item: ScoreItem, type: string) {
  if (type === 'bool') item.scoring = { type: 'bool' }
  else if (type === 'linear') item.scoring = { type: 'linear', min: 0, max: 100 }
  else item.scoring = { type: 'band', bands: [[80, 101, 100], [0, 80, 0]] }
}

// 权重平均分配（增删项后）
function rebalanceEqual() {
  const n = items.value.length
  if (!n) return
  const w = Math.floor((100 / n)) / 100
  items.value.forEach((it, i) => {
    it.weight = i === n - 1 ? +(1 - w * (n - 1)).toFixed(2) : w
  })
}

// 拖动某项权重 → 其余按比例自动重分配，保持总和 100%
function onWeightChange(idx: number, pct: number) {
  const v = Math.min(100, Math.max(0, pct)) / 100
  const others = items.value.filter((_, i) => i !== idx)
  const otherSum = others.reduce((s, it) => s + it.weight, 0)
  const remain = 1 - v
  items.value[idx].weight = +v.toFixed(4)
  if (others.length === 0) return
  if (otherSum <= 1e-9) {
    const each = remain / others.length
    others.forEach((it) => (it.weight = +each.toFixed(4)))
  } else {
    others.forEach((it) => (it.weight = +((it.weight / otherSum) * remain).toFixed(4)))
  }
}

function addBand(item: ScoreItem) {
  if (item.scoring.type === 'band') item.scoring.bands.push([0, 0, 0])
}
function removeBand(item: ScoreItem, i: number) {
  if (item.scoring.type === 'band') item.scoring.bands.splice(i, 1)
}

async function save() {
  if (profileReadonly.value) {
    ElMessage.warning('公开方案为只读，请先复制为自己的方案')
    return
  }
  if (!editName.value) {
    ElMessage.warning('请填写方案名称')
    return
  }
  if (!items.value.length) {
    ElMessage.warning('请至少添加一个指标项')
    return
  }
  if (weightSum.value !== 100) {
    ElMessage.warning(`权重合计需为 100%（当前 ${weightSum.value}%）`)
    return
  }
  saving.value = true
  try {
    const r = await saveScoreProfile({
      id: editId.value || null,
      name: editName.value,
      items: items.value,
    })
    curVersion.value = r.version
    ElMessage.success(`已保存（v${r.version}）`)
    isNew.value = false
    editId.value = r.id
    curId.value = r.id
    // 组件为列表唯一事实源（P2-1）：只经组件 reload 拉一次 mine 并回写 profiles.value（内部已 emit ready），
    // 不再并行调 loadProfiles() 直连 API（避免 save 后产生双份 source=mine 请求）。
    const list = await scoreSelectRef.value?.reload()
    const saved = (list as ScoreProfileSummary[] | undefined)?.find((p) => p.id === r.id)
    curRef.value = saved ? (saved.profile_ref || saved.id) : r.id
  } finally {
    saving.value = false
  }
}

async function remove() {
  if (!curRef.value || profileReadonly.value) return
  await ElMessageBox.confirm(`确认删除方案「${editName.value}」？`, '提示', { type: 'warning' })
  await deleteScoreProfile(curRef.value)
  ElMessage.success('已删除')
  newProfile()
  // 删除后只经组件 reload 刷新 mine 列表并回写（内部 emit ready → onScoreReady → profiles.value），不再并行 loadProfiles()。
  await scoreSelectRef.value?.reload()
}

async function publishScoreProfile(visibility: 'private' | 'tenant' | 'public') {
  if (!curRef.value || profileReadonly.value || visibilitySaving.value) return
  if (visibility === profileVisibility.value) return
  if (visibility === 'tenant' && !canPublishTenant.value) {
    ElMessage.warning('无权公开到租户')
    return
  }
  if (visibility === 'public' && !canPublishPublic.value) {
    ElMessage.warning('无权公开到全体用户')
    return
  }
  if (!await confirmProfileVisibilityReduction(
    editName.value || '当前方案',
    profileVisibility.value,
    visibility,
  )) return
  visibilitySaving.value = true
  try {
    const p = await setScoreProfileVisibility(curRef.value, visibility)
    profileVisibility.value = p.visibility || visibility
    const affected = p.affected_run_count || 0
    ElMessage.success(affected
      ? `可见性已更新，并同步收窄 ${affected} 条关联回测`
      : visibility === 'private' ? '已设为私有' : '公开设置已更新')
    // 发布后只经组件 reload 刷新 mine 列表并回写，不再并行 loadProfiles()。
    await scoreSelectRef.value?.reload()
  } finally {
    visibilitySaving.value = false
  }
}

// C8：复制由后端生成唯一 id、名称默认「原名 副本」，返回新标识供选中
async function copyCurrentScoreProfile(version?: number) {
  if (!curRef.value) return
  const r = await copyScoreProfile(curRef.value, version ? { version } : undefined)
  ElMessage.success(version ? `已将 v${version} 复制为我的方案` : '已复制为我的方案')
  sVerVisible.value = false
  // 复制后只经组件 reload 刷新 mine 列表并回写，不再并行 loadProfiles()。
  const list = await scoreSelectRef.value?.reload()
  const copied = (list as ScoreProfileSummary[] | undefined)?.find((p) => p.id === r.id)
  curRef.value = copied ? (copied.profile_ref || copied.id) : (r.profile_ref || r.id)
}

// ── 试算 ──
const runDate = ref<string>('')
const runRows = ref<ScoreRunRow[]>([])
const running = ref(false)
const runError = ref('')
function clearScoreRunResult() {
  runRows.value = []
  runError.value = ''
}
const subKeys = computed(() => items.value.map((i) => i.indicator))

function scoreLevel(v: number | undefined): string {
  const n = v ?? 0
  return n >= 80 ? 'hi' : n >= 50 ? 'mid' : 'lo'
}

function gradeType(g: string): string {
  return g === '主升浪核心' ? 'danger' : g === '龙头候选' ? 'warning' : g === '观察' ? 'success' : 'info'
}

async function tryRun() {
  if (!items.value.length || weightSum.value !== 100) {
    ElMessage.warning('请先配置好指标与权重（合计 100%）')
    return
  }
  running.value = true
  runError.value = ''
  try {
    const res = await runScoreProfile({
      items: items.value,
      run_date: runDate.value || undefined,
      top: 30,
    })
    runRows.value = res.list
    runDate.value = res.run_date
    if (!res.list.length) ElMessage.info('无结果（可能该日无数据）')
  } catch (e) {
    runError.value = getErrorMessage(e, '试算运行失败')
    ElMessage.error(runError.value)
  } finally {
    running.value = false
  }
}

// ════════════ 买卖指标方案 ════════════
import {
  browseTradeProfiles,
  copyTradeProfile,
  deleteTradeProfile,
  getTradeProfile,
  getTradeProfileVersions,
  listTradeProfiles,
  previewConditions,
  saveTradeProfile,
  setTradeProfileVisibility,
  type CondTree,
  type TradeCond,
  type TradeProfileSummary,
  type TradeProfileVersion,
} from '@/api/tradeProfile'

const tProfiles = ref<TradeProfileSummary[]>([])
// 买卖方案详情加载（选中→编辑器）独立状态：加载态/错误态/竞态守卫（P1-2）
const tDetailLoading = ref(false)
const tDetailError = ref('')
let tradeDetailSeq = 0
// 详情加载失败时的目标项（用于错误块重试）
let tradeDetailAttempt = ''
// 最后一次成功载入编辑器的方案 ref（失败回滚的目标）
let tradeLastAppliedRef = ''
const tCurRef = ref('')
const tCurId = ref('')
const tCurVersion = ref<number | null>(null)
const tEditId = ref('')
const tEditName = ref('')
const tIsNew = ref(false)
const tReadonly = ref(false)
const tVisibility = ref<'private' | 'tenant' | 'public'>('private')
const tVisibilitySaving = ref(false)
const buyLogic = ref<'AND' | 'OR'>('AND')
const sellLogic = ref<'AND' | 'OR'>('OR')
const buyConds = ref<TradeCond[]>([])
const sellConds = ref<TradeCond[]>([])
const backstop = ref<{ tp: number | null; sl: number | null; hold: number | null }>({ tp: null, sl: null, hold: null })
const tSaving = ref(false)
const NUM_CMP = [
  { v: '>=', t: '≥' }, { v: '<=', t: '≤' }, { v: '>', t: '>' },
  { v: '<', t: '<' }, { v: 'between', t: '区间' },
]
const canTradePublishTenant = computed(() =>
  hasPermission(auth.role, auth.permissions, 'trade-profile:publish-tenant'),
)
const canTradePublishPublic = computed(() =>
  hasPermission(auth.role, auth.permissions, 'trade-profile:publish-public'),
)
const canViewTradeProfiles = computed(() =>
  hasPermission(auth.role, auth.permissions, 'trade-profile:view'),
)
const canSaveTradeProfiles = computed(() =>
  hasPermission(auth.role, auth.permissions, 'trade-profile:save'),
)
function tradeProfileKey(p: TradeProfileSummary): string {
  return p.profile_ref || p.id
}
const tradeSelectRef = ref<InstanceType<typeof AssetProfileSelect> | null>(null)
async function fetchMineTradeProfiles(): Promise<TradeProfileSummary[]> {
  if (!canViewTradeProfiles.value) return []
  return listTradeProfiles('mine')
}
function browseTrade(params: AssetBrowseParams) {
  return browseTradeProfiles(params)
}
function copyAnyTradeProfile(item: ProfileSummary) {
  return copyTradeProfile(item.profile_ref || item.id)
}
// 买卖 mine 列表由选择器组件唯一拉取（onMounted 与 save/delete/publish/copy 后均只经组件 reload 一次），
// 回写经组件 ready 事件进入 onTradeReady → tProfiles.value；本页不再保留私有直连拉取（P2-1）。
function condListOf(side: 'buy' | 'sell') {
  return side === 'buy' ? buyConds : sellConds
}
function newCond(): TradeCond {
  const used = new Set([...buyConds.value, ...sellConds.value].map((c) => c.indicator))
  const cand = scorable.value.find((d) => !used.has(d.key)) || scorable.value[0]
  return condForIndicator(cand?.key ?? 'rs_pct')
}
function condForIndicator(key: string): TradeCond {
  const def = defOf(key)
  const params = def ? defaultParams(def) : {}
  if (def?.dtype === 'bool') return { indicator: key, params, cmp: '==', value: true }
  return { indicator: key, params, cmp: '>=', value: 0 }
}
function onCondIndicator(cond: TradeCond) {
  Object.assign(cond, condForIndicator(cond.indicator))
}
function onCmpChange(cond: TradeCond, cmp: string) {
  cond.cmp = cmp
  cond.value = cmp === 'between' ? [0, 0] : 0
}
function addCond(side: 'buy' | 'sell') {
  condListOf(side).value.push(newCond())
}
function removeCond(side: 'buy' | 'sell', i: number) {
  condListOf(side).value.splice(i, 1)
}

function tradeCondRowActions(side: 'buy' | 'sell', i: number): AppRowAction[] {
  return [
    {
      key: 'delete',
      label: '删除',
      type: 'danger',
      disabled: tReadonly.value,
      onClick: () => removeCond(side, i),
    },
  ]
}

function toTree(logic: 'AND' | 'OR', conds: TradeCond[]): CondTree {
  return {
    op: logic,
    children: conds.map((c) => {
      const leaf: TradeCond = { indicator: c.indicator, cmp: c.cmp, value: c.value }
      if (c.params && Object.keys(c.params).length) leaf.params = c.params
      return leaf
    }),
  }
}
function fromTree(tree: CondTree | Record<string, never> | undefined): { logic: 'AND' | 'OR'; conds: TradeCond[] } {
  const t = tree as CondTree
  if (!t || !t.children) return { logic: 'AND', conds: [] }
  const conds = t.children.map((l) => ({
    indicator: l.indicator, params: l.params ?? {}, cmp: l.cmp, value: l.value,
  }))
  conds.forEach((c) => {
    const def = defOf(c.indicator)
    for (const p of def?.params ?? []) if (c.params![p.name] === undefined) c.params![p.name] = p.default
  })
  return { logic: t.op ?? 'AND', conds }
}

// P1-2：原子应用详情 + 失败回滚选中值 + seq 竞态守卫，保证「选中项 == 编辑器内容」不错位。
async function selectTradeProfile(pid: string) {
  if (!pid) return
  const seq = ++tradeDetailSeq
  tradeDetailAttempt = pid
  tDetailLoading.value = true
  tDetailError.value = ''
  try {
    const p = await getTradeProfile(pid)
    if (seq !== tradeDetailSeq) return
    clearTradePreview()
    tCurRef.value = p.profile_ref || pid
    tCurId.value = p.id; tCurVersion.value = p.version; tEditId.value = p.id; tEditName.value = p.name; tIsNew.value = false
    tReadonly.value = !!p.readonly
    tVisibility.value = p.visibility || 'private'
    const b = fromTree(p.buy_tree); buyLogic.value = b.logic; buyConds.value = b.conds
    const s = fromTree(p.sell_tree); sellLogic.value = s.logic; sellConds.value = s.conds
    backstop.value = {
      tp: p.backstop?.take_profit != null ? Math.round(p.backstop.take_profit * 100) : null,
      sl: p.backstop?.stop_loss != null ? Math.round(p.backstop.stop_loss * 100) : null,
      hold: p.backstop?.max_hold_days ?? null,
    }
    tradeLastAppliedRef = tCurRef.value
  } catch (e) {
    if (seq !== tradeDetailSeq) return
    // 失败回滚到最后成功载入的项，编辑器保留旧内容
    tCurRef.value = tradeLastAppliedRef
    tDetailError.value = getErrorMessage(e, '买卖方案详情加载失败')
  } finally {
    if (seq === tradeDetailSeq) tDetailLoading.value = false
  }
}
// 侧栏选择器选中变化（含「加载查看」注入的临时只读项）→ 载入编辑器；不自动试算
function onTradeSelect(key: string) {
  tCurRef.value = key
  if (!key) return
  void selectTradeProfile(key)
}
function newTradeProfile() {
  tradeDetailSeq += 1
  tCurRef.value = ''
  tCurId.value = ''; tCurVersion.value = null; tEditId.value = ''; tEditName.value = ''; tIsNew.value = true
  tReadonly.value = false
  tVisibility.value = 'private'
  buyLogic.value = 'AND'; buyConds.value = []
  sellLogic.value = 'OR'; sellConds.value = []
  backstop.value = { tp: null, sl: null, hold: null }
  tradeLastAppliedRef = ''
  tradeDetailAttempt = ''
  tDetailError.value = ''
  clearTradePreview()
}

// ── 买卖方案历史版本（回看/载入；载入仅写入编辑器，保存后才生成新版本）──
const tVerVisible = ref(false)
const tVersions = ref<TradeProfileVersion[]>([])
async function openTradeVersions() {
  if (!tCurRef.value) return
  tVersions.value = (await getTradeProfileVersions(tCurRef.value)).versions
  tVerVisible.value = true
}
function restoreTradeVersion(v: TradeProfileVersion) {
  const b = fromTree(v.buy_tree); buyLogic.value = b.logic; buyConds.value = b.conds
  const s = fromTree(v.sell_tree); sellLogic.value = s.logic; sellConds.value = s.conds
  backstop.value = {
    tp: v.backstop?.take_profit != null ? Math.round(v.backstop.take_profit * 100) : null,
    sl: v.backstop?.stop_loss != null ? Math.round(v.backstop.stop_loss * 100) : null,
    hold: v.backstop?.max_hold_days ?? null,
  }
  tVerVisible.value = false
  ElMessage.success(`已载入 v${v.version} 到编辑器，确认后点「保存」生成新版本`)
}

function tradeVersionRowActions(v: TradeProfileVersion): AppRowAction[] {
  if (!canSaveTradeProfiles.value) return []
  if (tReadonly.value) {
    return [
      { key: 'copy', label: '复制此版本为我的', onClick: () => { void copyCurrentTradeProfile(v.version) } },
    ]
  }
  return [
    { key: 'restore', label: '载入此版本', onClick: () => restoreTradeVersion(v) },
  ]
}
async function saveTrade() {
  if (tReadonly.value) { ElMessage.warning('公开方案为只读，请先复制为自己的方案'); return }
  if (!tEditName.value) { ElMessage.warning('请填写方案名称'); return }
  if (!buyConds.value.length) { ElMessage.warning('请至少配置一个买入条件'); return }
  const bs = {
    take_profit: backstop.value.tp != null ? backstop.value.tp / 100 : null,
    stop_loss: backstop.value.sl != null ? backstop.value.sl / 100 : null,
    max_hold_days: backstop.value.hold ?? null,
  }
  tSaving.value = true
  try {
    const r = await saveTradeProfile({
      id: tEditId.value || null,
      name: tEditName.value,
      buy_tree: toTree(buyLogic.value, buyConds.value),
      sell_tree: toTree(sellLogic.value, sellConds.value),
      backstop: bs,
    })
    tCurVersion.value = r.version
    ElMessage.success(`已保存（v${r.version}）`)
    tIsNew.value = false
    tEditId.value = r.id
    tCurId.value = r.id
    // 组件为列表唯一事实源（P2-1）：只经组件 reload 拉一次 mine 并回写 tProfiles.value（内部已 emit ready），
    // 不再并行调 loadTradeProfiles() 直连 API。
    const list = await tradeSelectRef.value?.reload()
    const saved = (list as TradeProfileSummary[] | undefined)?.find((p) => p.id === r.id)
    tCurRef.value = saved ? tradeProfileKey(saved) : r.id
  } catch { /* 拦截器已提示 */ } finally { tSaving.value = false }
}
async function removeTrade() {
  if (!tCurRef.value || tReadonly.value) return
  await ElMessageBox.confirm(`确认删除买卖方案「${tEditName.value}」？`, '提示', { type: 'warning' })
  await deleteTradeProfile(tCurRef.value)
  ElMessage.success('已删除'); newTradeProfile()
  // 删除后只经组件 reload 刷新 mine 列表并回写（内部 emit ready → onTradeReady → tProfiles.value），不再并行 loadTradeProfiles()。
  await tradeSelectRef.value?.reload()
}

async function publishTradeProfile(visibility: 'private' | 'tenant' | 'public') {
  if (!tCurRef.value || tReadonly.value || tVisibilitySaving.value) return
  if (visibility === tVisibility.value) return
  if (visibility === 'tenant' && !canTradePublishTenant.value) {
    ElMessage.warning('无权公开到租户')
    return
  }
  if (visibility === 'public' && !canTradePublishPublic.value) {
    ElMessage.warning('无权公开到全体用户')
    return
  }
  if (!await confirmProfileVisibilityReduction(
    tEditName.value || '当前方案',
    tVisibility.value,
    visibility,
  )) return
  tVisibilitySaving.value = true
  try {
    const p = await setTradeProfileVisibility(tCurRef.value, visibility)
    tVisibility.value = p.visibility || visibility
    const affected = p.affected_run_count || 0
    ElMessage.success(affected
      ? `可见性已更新，并同步收窄 ${affected} 条关联回测`
      : visibility === 'private' ? '已设为私有' : '公开设置已更新')
    // 发布后只经组件 reload 刷新 mine 列表并回写，不再并行 loadTradeProfiles()。
    await tradeSelectRef.value?.reload()
  } finally {
    tVisibilitySaving.value = false
  }
}
// C8：复制由后端生成唯一 id、名称默认「原名 副本」，返回新标识供选中
async function copyCurrentTradeProfile(version?: number) {
  if (!tCurRef.value) return
  const r = await copyTradeProfile(tCurRef.value, version ? { version } : undefined)
  ElMessage.success(version ? `已将 v${version} 复制为我的方案` : '已复制为我的方案')
  tVerVisible.value = false
  // 复制后只经组件 reload 刷新 mine 列表并回写，不再并行 loadTradeProfiles()。
  const list = await tradeSelectRef.value?.reload()
  const copied = (list as TradeProfileSummary[] | undefined)?.find((p) => p.id === r.id)
  tCurRef.value = copied ? tradeProfileKey(copied) : (r.profile_ref || r.id)
}

// 记录实际试算的交易日：previewConditions 不传 run_date 时后端回落最新交易日（非必然「今日」），文案需展示真实口径
const previewHit = ref<{ buy: number | null; sell: number | null }>({ buy: null, sell: null })
const previewDate = ref<{ buy: string | null; sell: string | null }>({ buy: null, sell: null })
const previewing = ref('')
function clearTradePreview() {
  previewHit.value = { buy: null, sell: null }
  previewDate.value = { buy: null, sell: null }
}
async function previewSide(side: 'buy' | 'sell') {
  const conds = condListOf(side).value
  if (!conds.length) { ElMessage.warning('该侧无条件'); return }
  previewing.value = side
  previewHit.value[side] = null
  previewDate.value[side] = null
  try {
    const logic = side === 'buy' ? buyLogic.value : sellLogic.value
    const res = await previewConditions({ tree: toTree(logic, conds), top: 10 })
    previewHit.value[side] = res.hit
    previewDate.value[side] = res.run_date
    ElMessage.success(`${side === 'buy' ? '买入' : '卖出'}条件命中 ${res.hit} 只（${res.run_date}）`)
  } catch (e) {
    ElMessage.error(getErrorMessage(e, `${side === 'buy' ? '买入' : '卖出'}条件试算失败`))
  } finally { previewing.value = '' }
}

const pageReady = ref(false)
const pageInitError = ref(false)
const baseReady = ref(false)
let initSeq = 0

function sleep(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
}

async function withInitialRetry<T>(task: () => Promise<T>): Promise<T> {
  try {
    return await task()
  } catch (first) {
    await auth.ensureLoaded()
    await sleep(250)
    try {
      return await task()
    } catch {
      throw first
    }
  }
}

// 组件为列表唯一事实源（P2-1）：经 ready 接收「我的」列表并决定初始选中，不再在 init 直接 fetch。
// init 仅做权限/菜单就绪重试（withInitialRetry），列表拉取交给选择器组件（onMounted 拉一次后 emit ready）。
function onScoreReady(list: ProfileSummary[]) {
  profiles.value = list as ScoreProfileSummary[]
  if (profiles.value.length && !curRef.value) onScoreSelect(profiles.value[0].profile_ref || profiles.value[0].id)
  else if (!profiles.value.length && !curRef.value) newProfile()
}
// 复制成功（P2-2）：组件回写完整 summary，并入 profiles 供侧栏/编辑器一致
function onScoreCopied(item: ProfileSummary) {
  const summary = item as ScoreProfileSummary
  if (!profiles.value.some((p) => (p.profile_ref || p.id) === (summary.profile_ref || summary.id))) {
    profiles.value = [summary, ...profiles.value]
  }
}
// 「加载查看」（R5/§7.0）：载入编辑器只读展示（页面级状态，不污染 mine 列表，也不经组件选中态——
// 组件刻意不把临时项设为选中，规避 el-select 把 selectedItem 锁到非持久 tempItem 的更新循环）。
// 复用 onScoreSelect（seq 守卫 + 失败回滚），只读由 profileReadonly 控制、不自动试算。
function onScoreLoaded(item: ProfileSummary) {
  const summary = item as ScoreProfileSummary
  onScoreSelect(summary.profile_ref || summary.id)
}
// 行内「×」只移除「加载查看」临时预览项，不删除资产；组件只会为当前 tempItem 发出此事件。
// 不用 readonly 推断临时项：平台内置资产对其物理 owner 可能是 readonly=false，仍须完整清理页面状态。
async function onScoreTempRemoved(item: ProfileSummary) {
  const summary = item as ScoreProfileSummary
  ElMessage.info(`已移除预览的方案「${summary.name}」`)
  // 先同步清空外部身份、参数和试算，再刷新 mine；刷新失败也不会留下“来源已移除、参数仍可编辑”的假新建态。
  newProfile()
  await scoreSelectRef.value?.reload()
}
function onTradeReady(list: ProfileSummary[]) {
  tProfiles.value = list as TradeProfileSummary[]
  if (tProfiles.value.length && !tCurRef.value) onTradeSelect(tradeProfileKey(tProfiles.value[0]))
  else if (!tProfiles.value.length && !tCurRef.value) newTradeProfile()
}
function onTradeCopied(item: ProfileSummary) {
  const summary = item as TradeProfileSummary
  if (!tProfiles.value.some((p) => tradeProfileKey(p) === tradeProfileKey(summary))) {
    tProfiles.value = [summary, ...tProfiles.value]
  }
}
// 「加载查看」（R5/§7.0）：载入编辑器只读展示（同 onScoreLoaded，页面级状态不污染 mine 列表）。
function onTradeLoaded(item: ProfileSummary) {
  const summary = item as TradeProfileSummary
  onTradeSelect(tradeProfileKey(summary))
}
// 行内「×」只移除「加载查看」临时预览项，不删除资产；清理契约与评分方案一致。
async function onTradeTempRemoved(item: ProfileSummary) {
  const summary = item as TradeProfileSummary
  ElMessage.info(`已移除预览的方案「${summary.name}」`)
  // 与评分方案一致：移除即同步丢弃外部参数；mine 刷新失败时仍保持干净的新建态。
  newTradeProfile()
  await tradeSelectRef.value?.reload()
}

async function initScorePage() {
  await withInitialRetry(async () => {
    // 选择器组件挂载后自行拉取并经 ready 回推列表/首项选中；此处仅确保权限与菜单就绪。
    await auth.ensureLoaded()
  })
}

async function initTradePage() {
  await withInitialRetry(async () => {
    await auth.ensureLoaded()
  })
}

// 列表加载失败兜底：选择器组件内部已显示可重试错误态并保留旧列表（P1-3 契约）；父级仅需确保权限就绪，
// 不再维护「组件失败 → 页面自己直连重试」的旁路（避免与组件双份拉取）。
function onScoreLoadFailed() {
  void auth.ensureLoaded().catch((e) => console.error('[config] 评分方案加载失败兜底', e))
}

function onTradeLoadFailed() {
  void auth.ensureLoaded().catch((e) => console.error('[config] 买卖方案加载失败兜底', e))
}

async function ensureBaseReady() {
  if (baseReady.value) return
  await auth.ensureLoaded()
  await withInitialRetry(reloadRegistry)
  baseReady.value = true
}

async function initActivePage(tab: ConfigTab = activeTab.value) {
  const seq = ++initSeq
  pageReady.value = false
  pageInitError.value = false
  try {
    if (tab === 'system') {
      await auth.ensureLoaded()
      if (seq !== initSeq) return
      if (canManageSystemSettings.value) await withInitialRetry(loadSystem)
      if (seq === initSeq) pageReady.value = true
      return
    }
    await ensureBaseReady()
    if (seq !== initSeq) return
    if (tab === 'score') await initScorePage()
    else if (tab === 'trade') await initTradePage()
    if (seq === initSeq) pageReady.value = true
  } catch (e) {
    if (seq === initSeq) pageInitError.value = true
    console.error(`[config] ${tab} 初始化失败`, e)
  }
}

onMounted(() => { initActivePage() })
watch(activeTab, (tab) => { initActivePage(tab) })
</script>

<template>
  <LayoutHost :layout="configEffective">
    <template #action>
    <div class="page-head">
      <h2 class="page-title app-page-title">{{ pageTitle }}</h2>
      <div class="page-head-actions">
        <PageSettingsTrigger :dirty="isDirty || layoutDirty" @click="settingsOpen = true" />
      </div>
    </div>
    </template>

    <template #main>
    <div class="config-body">
    <AppStateBlock
      v-if="pageInitError"
      state="error"
      title="配置数据加载失败"
      description="权限、菜单或指标目录尚未就绪，请重试"
      class="config-error"
      retry
      @retry="initActivePage()"
    />
    <AppStateBlock v-else-if="!pageReady" state="loading" title="正在加载配置数据…" class="config-error" />
    <template v-else>
      <!-- ============ 评分规则 ============ -->
      <template v-if="activeTab === 'score'">
        <div class="score-layout pane-fill">
          <!-- 方案列表（R3/R5/R7：统一选择器 list 形态，仅我的 + 搜索系统内置/租户/全体公开） -->
          <aside class="prof-list">
            <el-button type="primary" plain size="small" style="width: 100%" @click="newProfile">
              <template #icon><el-icon><Plus /></el-icon></template>
              新建方案
            </el-button>
            <AssetProfileSelect
              ref="scoreSelectRef"
              mode="list"
              :model-value="curRef"
              asset-label="评分方案"
              :fetch-mine="fetchMineScoreProfiles"
              :browse="browseScore"
              :copy-item="copyAnyScoreProfile"
              copy-permission="score-profile:save"
              view-permission="score-profile:view"
              test-id="score-profile-select"
              @update:model-value="onScoreSelect"
              @loaded="onScoreLoaded"
              @ready="onScoreReady"
              @copied-item="onScoreCopied"
              @load-failed="onScoreLoadFailed"
              @temp-removed="onScoreTempRemoved"
            />
          </aside>

          <!-- 编辑器 -->
          <section class="editor editor-score">
            <div class="ed-head">
              <el-input v-model="editName" :disabled="profileReadonly" placeholder="方案名称" style="width: 200px" />
              <span v-if="editId && !isNew" class="id-badge mono">{{ editId }}</span>
              <span v-if="curVersion && !isNew" class="ver-badge" title="点击查看历史版本" @click="openScoreVersions">v{{ curVersion }}</span>
              <AssetVisibilityActions
                v-if="!isNew"
                :visibility="profileVisibility"
                :readonly="profileReadonly"
                :can-publish-tenant="canPublishTenant"
                :can-publish-public="canPublishPublic"
                :saving="visibilitySaving"
                :copy-visible="profileReadonly"
                copy-permission="score-profile:save"
                @publish="publishScoreProfile"
                @copy="copyCurrentScoreProfile"
              />
              <span class="wsum" :class="{ bad: weightSum !== 100 }">权重合计 {{ weightSum }}%</span>
              <div class="spacer" />
              <el-button v-permission="'score-profile:save'" :disabled="profileReadonly" :loading="saving" type="primary" @click="save">保存</el-button>
              <el-button v-permission="'score-profile:delete'" v-if="curId && !isNew && !profileReadonly" type="danger" plain @click="remove">删除</el-button>
            </div>

            <!-- 详情加载态/失败态（P1-2）：失败已回滚选中值，编辑器保留旧内容 -->
            <AppStateBlock
              v-if="profileDetailError"
              state="error"
              size="compact"
              title="评分方案详情加载失败"
              :description="profileDetailError"
              retry
              @retry="onScoreSelect(scoreDetailAttempt || curRef)"
            />
            <AppStateBlock
              v-else-if="profileDetailLoading"
              state="loading"
              size="compact"
              title="正在加载方案详情…"
            />

            <p class="hint">
              每个指标产出 0~100 达标分（布尔=满足100/否0；数值按阈值映射），按权重百分比加权 →
              综合分。调一个权重，其余自动按比例重分配保持 100%。
            </p>

            <AppDataTable :data="items" size="small" border class="item-table" embedded>
              <AppTableColumn label="指标">
                <template #default="{ row }">
                  <el-select v-model="row.indicator" size="small" filterable :disabled="profileReadonly" @change="onIndicatorChange(row)">
                    <el-option v-for="d in scorable" :key="d.key" :label="d.name_cn" :value="d.key" />
                  </el-select>
                  <!-- 动态参数（如 连续上涨N天 的 N）-->
                  <div v-if="defOf(row.indicator)?.params?.length" class="param-row">
                    <span v-for="p in defOf(row.indicator)!.params" :key="p.name" class="param-item">
                      <label>{{ p.label }}</label>
                      <el-input-number
                        v-model="row.params![p.name]"
                        size="small"
                        :controls="false"
                        :disabled="profileReadonly"
                        :min="p.min ?? undefined"
                        :max="p.max ?? undefined"
                        style="width: 64px"
                      />
                    </span>
                  </div>
                </template>
              </AppTableColumn>

              <AppTableColumn label="打分方式">
                <template #default="{ row }">
                  <div class="scoring-cell">
                    <el-radio-group
                      :model-value="row.scoring.type"
                      size="small"
                      @change="(v: string) => onScoringTypeChange(row, v)"
                    >
                      <el-radio-button value="bool" :disabled="profileReadonly || defOf(row.indicator)?.dtype === 'number'">
                        布尔
                      </el-radio-button>
                      <el-radio-button value="linear" :disabled="profileReadonly || defOf(row.indicator)?.dtype === 'bool'">
                        线性
                      </el-radio-button>
                      <el-radio-button value="band" :disabled="profileReadonly || defOf(row.indicator)?.dtype === 'bool'">
                        分段
                      </el-radio-button>
                    </el-radio-group>

                    <!-- bool -->
                    <span v-if="row.scoring.type === 'bool'" class="tip">满足=100 / 否=0</span>
                    <!-- linear -->
                    <div v-else-if="row.scoring.type === 'linear'" class="linear-row">
                      <span>0分→</span>
                      <el-input-number v-model="row.scoring.min" size="small" :controls="false" :disabled="profileReadonly" style="width: 78px" />
                      <span>100分→</span>
                      <el-input-number v-model="row.scoring.max" size="small" :controls="false" :disabled="profileReadonly" style="width: 78px" />
                    </div>
                    <!-- band -->
                    <div v-else class="band-box">
                      <div v-for="(b, bi) in row.scoring.bands" :key="bi" class="band-row">
                        <el-input-number v-model="b[0]" size="small" :controls="false" :disabled="profileReadonly" style="width: 64px" />
                        <span>~</span>
                        <el-input-number v-model="b[1]" size="small" :controls="false" :disabled="profileReadonly" style="width: 64px" />
                        <span>→</span>
                        <el-input-number v-model="b[2]" size="small" :controls="false" :disabled="profileReadonly" :min="0" :max="100" style="width: 64px" />
                        <span>分</span>
                        <AppIconButton label="删除分段" size="xs" tone="danger" :disabled="profileReadonly" @click="removeBand(row, bi)">
                          <el-icon><Close /></el-icon>
                        </AppIconButton>
                      </div>
                      <el-button link type="primary" size="small" :disabled="profileReadonly" @click="addBand(row)">
                        <template #icon><el-icon><Plus /></el-icon></template>
                        段
                      </el-button>
                    </div>
                  </div>
                </template>
              </AppTableColumn>

              <AppTableColumn label="权重">
                <template #default="{ row, $index }">
                  <div class="weight-cell">
                    <el-slider
                      :model-value="Math.round(row.weight * 100)"
                      :min="0"
                      :max="100"
                      :disabled="profileReadonly"
                      @input="(v: number) => onWeightChange($index, v)"
                    />
                    <span class="wval">{{ Math.round(row.weight * 100) }}%</span>
                  </div>
                </template>
              </AppTableColumn>

              <!-- 操作列：单删除动作，用紧凑操作列 role；structural(48px) 会放不下「更多」按钮测量层造成横向滚动 -->
              <AppTableColumn label="操作" role="action-compact">
                <template #default="{ $index }">
                  <AppRowActions :actions="scoreItemRowActions($index)" :inline-limit="1" />
                </template>
              </AppTableColumn>
            </AppDataTable>

            <el-button size="small" plain style="margin-top: 8px" :disabled="profileReadonly" @click="addItem">
              <template #icon><el-icon><Plus /></el-icon></template>
              添加指标
            </el-button>

            <!-- 试算 -->
            <div class="run-head">
              <span class="run-title">试算榜单</span>
              <el-tag v-if="runRows.length" type="info" size="small" round>共 {{ runRows.length }} 只</el-tag>
              <TradeDatePicker v-model="runDate" placeholder="默认最新交易日" default-latest />
              <el-button v-permission="'score:run'" :loading="running" type="primary" @click="tryRun">
                <template #icon><el-icon><VideoPlay /></el-icon></template>
                用当前配置试算
              </el-button>
            </div>
            <AppStateBlock
              v-if="runError"
              state="error"
              size="compact"
              title="试算运行失败"
              :description="runError"
              retry
              @retry="tryRun"
            />
            <div v-if="settings.previewExpanded && runRows.length" class="run-table-wrap">
            <AppDataTable :data="runRows" size="small" border height="100%" class="run-table">
              <AppTableColumn label="#">
                <template #default="{ row }">{{ row.rank }}</template>
              </AppTableColumn>
              <AppTableColumn prop="code" label="代码" />
              <AppTableColumn prop="name" label="名称" />
              <AppTableColumn label="综合分">
                <template #default="{ row }"><b style="color: var(--el-color-danger)">{{ row.total_score }}</b></template>
              </AppTableColumn>
              <AppTableColumn label="评级">
                <template #default="{ row }">
                  <el-tag v-if="row.grade" :type="gradeType(row.grade)" size="small" effect="light">
                    {{ row.grade }}
                  </el-tag>
                  <span v-else>—</span>
                </template>
              </AppTableColumn>
              <AppTableColumn label="分项达标分">
                <template #default="{ row }">
                  <div class="subchips">
                    <span
                      v-for="k in subKeys"
                      :key="k"
                      class="subchip score"
                      :class="scoreLevel(row.sub_scores?.[k])"
                    >
                      <i>{{ nameOf(k) }}</i><b>{{ Math.round(row.sub_scores?.[k] ?? 0) }}</b>
                    </span>
                  </div>
                </template>
              </AppTableColumn>
            </AppDataTable>
            </div>
          </section>
        </div>
      </template>

      <!-- ============ 技术指标 ============ -->
      <template v-else-if="activeTab === 'tech'">
        <div class="pane-fill tech-pane">
        <div class="tech-head">
          <p class="hint" style="margin: 0">
            <HelpTip title="技术指标说明" :width="420">
              <p style="margin:0">系统内置不可删除，仅可启停；自定义 = 一段带参数的表达式，供评分/筛选/买卖引用。</p>
              <p style="margin:8px 0 0">表达式函数：MA / HHV / LLV / REF / COUNT / SUM / ABS；变量：C / O / H / L / V / TURN。</p>
              <p style="margin:8px 0 0">分类可多选/自定义命名（直接输入新名回车即可）。</p>
            </HelpTip>
          </p>
          <div class="tech-actions">
            <el-input v-model="techSearch" placeholder="搜索名称/标识/说明/分类" clearable size="small" style="width: 220px" />
            <el-button v-permission="'indicator:def-manage'" type="primary" plain size="small" @click="openNewDef">
              <template #icon><el-icon><Plus /></el-icon></template>
              新建自定义指标
            </el-button>
          </div>
        </div>
        <div class="tech-table-wrap">
        <AppDataTable :data="techRows" size="small" :border="tableBorder('techTable')"
                  :default-sort="techDefaultSort" @sort-change="onTechSortChange">
          <AppTableColumn prop="name_cn" label="名称" sortable="custom" />
          <AppTableColumn prop="key" label="标识" show-overflow-tooltip>
            <template #default="{ row }">
              <span class="mono">{{ row.key }}</span>
            </template>
          </AppTableColumn>
          <AppTableColumn prop="catOrder" label="分类" sortable="custom">
            <template #default="{ row }">
              <el-select
                :model-value="row.categories"
                multiple filterable allow-create default-first-option
                collapse-tags collapse-tags-tooltip :max-collapse-tags="3"
                size="small" placeholder="加分类" style="width: 264px"
                @change="(v: string[]) => onCategoriesChange(row.key, v)"
              >
                <el-option v-for="cat in allCategories" :key="cat" :label="cat" :value="cat" />
              </el-select>
            </template>
          </AppTableColumn>
          <AppTableColumn prop="typeLabel" label="类型" sortable="custom" />
          <AppTableColumn prop="srcLabel" label="来源" sortable="custom">
            <template #default="{ row }">
              <SystemBuiltinTag v-if="row.is_builtin" />
              <el-tag v-else type="warning" size="small" effect="plain">自定义</el-tag>
            </template>
          </AppTableColumn>
          <AppTableColumn prop="hasParams" label="有无参数" sortable="custom">
            <template #default="{ row }">
              <span v-if="!row.params.length" class="tip">无</span>
              <span v-else>
                <span v-for="p in row.params" :key="p.name" class="subchip">{{ p.label }}({{ p.default }})</span>
              </span>
            </template>
          </AppTableColumn>
          <AppTableColumn label="计算 / 表达式">
            <template #default="{ row }">
              <code v-if="row.expression" class="expr">{{ row.expression }}</code>
              <span v-else class="tip">系统内置·代码向量化计算（无 DSL 表达式）</span>
            </template>
          </AppTableColumn>
          <AppTableColumn label="说明 / 用法">
            <template #default="{ row }">
              <span class="usage">{{ row.desc || '—' }}</span>
            </template>
          </AppTableColumn>
          <AppTableColumn label="启用">
            <template #default="{ row }">
              <el-switch v-permission="'indicator:def-manage'" :model-value="row.enabled" size="small" @change="toggleEnabled(row)" />
            </template>
          </AppTableColumn>
          <AppTableColumn label="操作">
            <template #default="{ row }">
              <AppRowActions :actions="indicatorDefRowActions(row)" :inline-limit="1" />
            </template>
          </AppTableColumn>
        </AppDataTable>
        </div>

        <!-- 新建自定义指标 -->
        <el-dialog v-model="defDialog" title="新建自定义指标" width="560px">
          <el-form label-width="92px" size="small">
            <el-form-item label="标识(英文)">
              <el-input v-model="defForm.key" placeholder="如 consec_up3" />
            </el-form-item>
            <el-form-item label="中文名">
              <el-input v-model="defForm.name_cn" placeholder="如 连续上涨" />
            </el-form-item>
            <el-form-item label="类型">
              <el-radio-group v-model="defForm.dtype">
                <el-radio-button value="bool">布尔</el-radio-button>
                <el-radio-button value="number">数值</el-radio-button>
              </el-radio-group>
            </el-form-item>
            <el-form-item label="表达式">
              <el-input
                v-model="defForm.expression"
                type="textarea"
                :rows="2"
                placeholder="如 COUNT(C > REF(C,1), {n}) == {n}（用 {参数名} 占位）"
              />
            </el-form-item>
            <el-form-item label="说明/用法">
              <el-input
                v-model="defForm.desc"
                type="textarea"
                :rows="2"
                placeholder="这个指标是什么、口径、怎么用（会显示在指标列表，供选用时参考）"
              />
            </el-form-item>
            <el-form-item label="分类">
              <el-select
                v-model="defForm.categories"
                multiple filterable allow-create default-first-option
                placeholder="选择或输入新分类（可多个）" style="width: 100%"
              >
                <el-option v-for="cat in allCategories" :key="cat" :label="cat" :value="cat" />
              </el-select>
            </el-form-item>
            <el-form-item label="参数">
              <div class="def-params">
                <div v-for="(p, i) in defForm.params" :key="i" class="def-param-row">
                  <el-input v-model="p.name" size="small" placeholder="名(同{占位})" style="width: 110px" />
                  <el-input v-model="p.label" size="small" placeholder="中文标签" style="width: 100px" />
                  <el-input-number v-model="p.default" size="small" :controls="false" placeholder="默认" style="width: 80px" />
                  <AppIconButton label="删除参数" size="xs" tone="danger" @click="removeDefParam(i)">
                    <el-icon><Close /></el-icon>
                  </AppIconButton>
                </div>
                <el-button link type="primary" size="small" @click="addDefParam">
                  <template #icon><el-icon><Plus /></el-icon></template>
                  参数
                </el-button>
              </div>
            </el-form-item>
          </el-form>
          <template #footer>
            <el-button @click="defDialog = false">取消</el-button>
            <el-button v-permission="'indicator:def-manage'" type="primary" @click="submitNewDef">保存</el-button>
          </template>
        </el-dialog>
        </div>
      </template>

      <!-- ============ 买卖指标 ============ -->
      <template v-else-if="activeTab === 'trade'">
        <div class="score-layout pane-fill">
          <aside class="prof-list">
            <el-button type="primary" plain size="small" style="width: 100%" @click="newTradeProfile">
              <template #icon><el-icon><Plus /></el-icon></template>
              新建方案
            </el-button>
            <AssetProfileSelect
              ref="tradeSelectRef"
              mode="list"
              :model-value="tCurRef"
              asset-label="买卖方案"
              :fetch-mine="fetchMineTradeProfiles"
              :browse="browseTrade"
              :copy-item="copyAnyTradeProfile"
              copy-permission="trade-profile:save"
              view-permission="trade-profile:view"
              test-id="trade-profile-select"
              @update:model-value="onTradeSelect"
              @loaded="onTradeLoaded"
              @ready="onTradeReady"
              @copied-item="onTradeCopied"
              @load-failed="onTradeLoadFailed"
              @temp-removed="onTradeTempRemoved"
            />
          </aside>

          <section class="editor">
            <div class="ed-head">
              <el-input v-model="tEditName" :disabled="tReadonly" placeholder="方案名称" style="width: 190px" />
              <span v-if="tEditId && !tIsNew" class="id-badge mono">{{ tEditId }}</span>
              <span v-if="tCurVersion && !tIsNew" class="ver-badge" title="点击查看历史版本" @click="openTradeVersions">v{{ tCurVersion }}</span>
              <AssetVisibilityActions
                v-if="!tIsNew"
                :visibility="tVisibility"
                :readonly="tReadonly"
                :can-publish-tenant="canTradePublishTenant"
                :can-publish-public="canTradePublishPublic"
                :saving="tVisibilitySaving"
                :copy-visible="tReadonly"
                copy-permission="trade-profile:save"
                @publish="publishTradeProfile"
                @copy="copyCurrentTradeProfile"
              />
              <div class="spacer" />
              <el-button v-permission="'trade-profile:save'" :disabled="tReadonly" :loading="tSaving" type="primary" @click="saveTrade">保存</el-button>
              <el-button v-permission="'trade-profile:delete'" v-if="tCurId && !tIsNew && !tReadonly" type="danger" plain @click="removeTrade">删除</el-button>
            </div>

            <!-- 详情加载态/失败态（P1-2）：失败已回滚选中值，编辑器保留旧内容 -->
            <AppStateBlock
              v-if="tDetailError"
              state="error"
              size="compact"
              title="买卖方案详情加载失败"
              :description="tDetailError"
              retry
              @retry="onTradeSelect(tradeDetailAttempt || tCurRef)"
            />
            <AppStateBlock
              v-else-if="tDetailLoading"
              state="loading"
              size="compact"
              title="正在加载方案详情…"
            />
            <p class="hint">买入/卖出各是一组技术指标条件(且/或)。卖出以指标命中为主,止盈/止损/最大持仓为可选兜底,先到先卖。</p>

            <!-- 买入条件 -->
            <div class="cond-block">
              <div class="cond-head">
                <span class="cond-title buy">买入条件</span>
                <el-radio-group v-model="buyLogic" size="small" :disabled="tReadonly">
                  <el-radio-button value="AND">且(全满足)</el-radio-button>
                  <el-radio-button value="OR">或(任一)</el-radio-button>
                </el-radio-group>
                <el-button v-permission="'trade-profile:preview'" size="small" :loading="previewing === 'buy'" @click="previewSide('buy')">
                  <template #icon><el-icon><VideoPlay /></el-icon></template>
                  试算
                </el-button>
                <el-tag v-if="previewHit.buy !== null" type="success" size="small" round>命中 {{ previewHit.buy }} 只{{ previewDate.buy ? ` · ${previewDate.buy}` : '' }}</el-tag>
              </div>
              <div v-for="(c, i) in buyConds" :key="'b' + i" class="cond-row">
                <el-select v-model="c.indicator" size="small" filterable style="width: 150px" :disabled="tReadonly" @change="onCondIndicator(c)">
                  <el-option v-for="d in scorable" :key="d.key" :label="d.name_cn" :value="d.key" />
                </el-select>
                <span v-for="p in defOf(c.indicator)?.params ?? []" :key="p.name" class="param-item">
                  <label>{{ p.label }}</label>
                  <el-input-number v-model="c.params![p.name]" size="small" :disabled="tReadonly" :controls="false" style="width: 58px" />
                </span>
                <template v-if="defOf(c.indicator)?.dtype === 'bool'">
                  <el-select :model-value="c.value" size="small" style="width: 96px" :disabled="tReadonly" @change="(v: boolean) => (c.value = v)">
                    <el-option :value="true" label="满足" />
                    <el-option :value="false" label="不满足" />
                  </el-select>
                </template>
                <template v-else>
                  <el-select :model-value="c.cmp" size="small" style="width: 86px" :disabled="tReadonly" @change="(v: string) => onCmpChange(c, v)">
                    <el-option v-for="o in NUM_CMP" :key="o.v" :value="o.v" :label="o.t" />
                  </el-select>
                  <template v-if="c.cmp === 'between'">
                    <el-input-number :model-value="(c.value as number[])[0]" size="small" :disabled="tReadonly" :controls="false" style="width: 78px"
                                     @update:model-value="(v: number) => (c.value = [v, (c.value as number[])[1]])" />
                    <span>~</span>
                    <el-input-number :model-value="(c.value as number[])[1]" size="small" :disabled="tReadonly" :controls="false" style="width: 78px"
                                     @update:model-value="(v: number) => (c.value = [(c.value as number[])[0], v])" />
                  </template>
                  <el-input-number v-else :model-value="(c.value as number)" size="small" :disabled="tReadonly" :controls="false" style="width: 96px"
                                   @update:model-value="(v: number) => (c.value = v)" />
                </template>
                <AppRowActions :actions="tradeCondRowActions('buy', i)" :inline-limit="1" />
              </div>
              <el-button size="small" plain :disabled="tReadonly" @click="addCond('buy')">
                <template #icon><el-icon><Plus /></el-icon></template>
                买入条件
              </el-button>
            </div>

            <!-- 卖出条件 -->
            <div class="cond-block">
              <div class="cond-head">
                <span class="cond-title sell">卖出条件</span>
                <el-radio-group v-model="sellLogic" size="small" :disabled="tReadonly">
                  <el-radio-button value="AND">且(全满足)</el-radio-button>
                  <el-radio-button value="OR">或(任一)</el-radio-button>
                </el-radio-group>
                <el-button v-permission="'trade-profile:preview'" size="small" :loading="previewing === 'sell'" @click="previewSide('sell')">
                  <template #icon><el-icon><VideoPlay /></el-icon></template>
                  试算
                </el-button>
                <el-tag v-if="previewHit.sell !== null" type="warning" size="small" round>命中 {{ previewHit.sell }} 只{{ previewDate.sell ? ` · ${previewDate.sell}` : '' }}</el-tag>
              </div>
              <div v-for="(c, i) in sellConds" :key="'s' + i" class="cond-row">
                <el-select v-model="c.indicator" size="small" filterable style="width: 150px" :disabled="tReadonly" @change="onCondIndicator(c)">
                  <el-option v-for="d in scorable" :key="d.key" :label="d.name_cn" :value="d.key" />
                </el-select>
                <span v-for="p in defOf(c.indicator)?.params ?? []" :key="p.name" class="param-item">
                  <label>{{ p.label }}</label>
                  <el-input-number v-model="c.params![p.name]" size="small" :disabled="tReadonly" :controls="false" style="width: 58px" />
                </span>
                <template v-if="defOf(c.indicator)?.dtype === 'bool'">
                  <el-select :model-value="c.value" size="small" style="width: 96px" :disabled="tReadonly" @change="(v: boolean) => (c.value = v)">
                    <el-option :value="true" label="满足" />
                    <el-option :value="false" label="不满足" />
                  </el-select>
                </template>
                <template v-else>
                  <el-select :model-value="c.cmp" size="small" style="width: 86px" :disabled="tReadonly" @change="(v: string) => onCmpChange(c, v)">
                    <el-option v-for="o in NUM_CMP" :key="o.v" :value="o.v" :label="o.t" />
                  </el-select>
                  <template v-if="c.cmp === 'between'">
                    <el-input-number :model-value="(c.value as number[])[0]" size="small" :disabled="tReadonly" :controls="false" style="width: 78px"
                                     @update:model-value="(v: number) => (c.value = [v, (c.value as number[])[1]])" />
                    <span>~</span>
                    <el-input-number :model-value="(c.value as number[])[1]" size="small" :disabled="tReadonly" :controls="false" style="width: 78px"
                                     @update:model-value="(v: number) => (c.value = [(c.value as number[])[0], v])" />
                  </template>
                  <el-input-number v-else :model-value="(c.value as number)" size="small" :disabled="tReadonly" :controls="false" style="width: 96px"
                                   @update:model-value="(v: number) => (c.value = v)" />
                </template>
                <AppRowActions :actions="tradeCondRowActions('sell', i)" :inline-limit="1" />
              </div>
              <el-button size="small" plain :disabled="tReadonly" @click="addCond('sell')">
                <template #icon><el-icon><Plus /></el-icon></template>
                卖出条件
              </el-button>
            </div>

            <!-- 兜底 -->
            <div class="cond-block">
              <span class="cond-title">兜底(可选,卖出安全网)</span>
              <div class="backstop-row">
                <span class="bs-item"><label>止盈</label><el-input-number v-model="backstop.tp" size="small" :disabled="tReadonly" :controls="false" :min="0" style="width: 80px" /><i>%</i></span>
                <span class="bs-item"><label>止损</label><el-input-number v-model="backstop.sl" size="small" :disabled="tReadonly" :controls="false" :min="0" style="width: 80px" /><i>%</i></span>
                <span class="bs-item"><label>最大持仓</label><el-input-number v-model="backstop.hold" size="small" :disabled="tReadonly" :controls="false" :min="1" style="width: 80px" /><i>天</i></span>
              </div>
            </div>
          </section>
        </div>
      </template>

      <!-- ============ 系统设置（FR-DM-12）============ -->
      <template v-else-if="activeTab === 'system'">
        <AppStateBlock
          v-if="!canManageSystemSettings"
          state="error"
          variant="permission"
          title="无权限维护系统设置"
          description="系统设置仅系统管理员可编辑"
          class="config-error"
        />
        <div v-else class="sys-wrap" v-loading="sysLoading">
          <div class="sys-head">
            <div class="sys-summary">
              <span>保存后即时影响访问安全、数据采集、审计留存和研究运行参数。</span>
            </div>
            <div class="sys-actions">
              <el-alert
                v-if="sysSaveError"
                type="error"
                title="保存失败，已保留当前编辑值"
                :closable="false"
                show-icon
              />
              <el-alert
                v-else-if="sysInvalidPaths.length"
                type="warning"
                title="存在超出允许范围的配置项"
                :closable="false"
                show-icon
              />
              <el-button
                v-permission="'data-settings:manage'"
                :loading="sysSaving"
                :disabled="!activeSysPaths.length"
                @click="resetActiveSystemTab"
              >
                重置配置
              </el-button>
              <el-button
                v-permission="'data-settings:manage'"
                type="primary"
                :loading="sysSaving"
                :disabled="!sysDirty || !!sysInvalidPaths.length"
                @click="saveSystem"
              >
                保存并生效
              </el-button>
            </div>
          </div>

          <el-empty
            v-if="!sysLoading && !sysGroups.length"
            class="app-empty"
            description="暂无可维护配置"
          />
          <el-tabs v-else v-model="activeSysTab" class="sys-tabs">
            <el-tab-pane
              v-for="tab in sysTabs"
              :key="tab.key"
              :name="tab.key"
              :label="tab.label"
            >
              <div class="sys-grid">
                <ConfigGroupForm
                  v-for="group in tab.groups"
                  :key="group.key"
                  :group="group"
                  :sections="configPanelSectionsOf(group.key)"
                  :panel-behavior="configPanelBehavior"
                  :model-value="sysDraft"
                  :disabled="sysSaving"
                  :invalid-paths="sysInvalidPaths"
                  :field-status="systemFieldStatus"
                  @update-field="updateSystemField"
                />
              </div>
            </el-tab-pane>
          </el-tabs>
        </div>
      </template>
    </template>
    </div>
    </template>

    <template #overlays>
    <!-- 评分方案历史版本 -->
    <el-dialog v-model="sVerVisible" :title="`历史版本 · ${editName || ''}`" width="560px">
      <el-empty v-if="!sVersions.length" class="app-empty app-empty--compact" description="暂无历史版本" />
      <div v-for="v in sVersions" :key="v.version" class="ver-item">
        <div class="ver-head">
          <b>v{{ v.version }}</b>
          <span class="hint">{{ v.saved_at?.slice(0, 16) }}</span>
          <span class="hint">{{ v.items.length }} 项指标</span>
          <div class="spacer" />
          <AppRowActions :actions="scoreVersionRowActions(v)" :inline-limit="1" />
        </div>
        <pre class="ast">{{ JSON.stringify(v.items, null, 2) }}</pre>
      </div>
    </el-dialog>

    <!-- 买卖方案历史版本 -->
    <el-dialog v-model="tVerVisible" :title="`历史版本 · ${tEditName || ''}`" width="560px">
      <el-empty v-if="!tVersions.length" class="app-empty app-empty--compact" description="暂无历史版本" />
      <div v-for="v in tVersions" :key="v.version" class="ver-item">
        <div class="ver-head">
          <b>v{{ v.version }}</b>
          <span class="hint">{{ v.saved_at?.slice(0, 16) }}</span>
          <div class="spacer" />
          <AppRowActions :actions="tradeVersionRowActions(v)" :inline-limit="1" />
        </div>
        <pre class="ast">买入 {{ JSON.stringify(v.buy_tree, null, 2) }}
卖出 {{ JSON.stringify(v.sell_tree, null, 2) }}
兜底 {{ JSON.stringify(v.backstop, null, 2) }}</pre>
      </div>
    </el-dialog>

    <PageSettingsDrawer
      v-model="settingsOpen"
      :title="pageTitle"
      :dirty="isDirty || layoutDirty"
      :page-key="configPageKey"
      :config="drawerConfig"
      :business-visible="activeTab === 'tech'"
      :component-meta-overrides="configPanelMetaOverrides"
      @reset="reset(); resetLayout()"
    >
      <template #business>
        <PageSettingSection title="界面默认项">
          <PageToggleRow v-model="settings.previewExpanded" label="默认显示试算结果区" />
        </PageSettingSection>
      </template>
    </PageSettingsDrawer>
    </template>
  </LayoutHost>
</template>

<style scoped>
.sys-wrap {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: var(--app-space-2);
}
.sys-head {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-4);
  padding: 0;
}
.sys-summary {
  min-width: 0;
}
.sys-summary strong,
.sys-summary span {
  display: block;
}
.sys-summary strong {
  font-size: var(--app-font-size-data);
  line-height: var(--app-line-height-compact);
}
.sys-summary span {
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
}
.sys-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--app-space-2);
  flex-wrap: wrap;
}
.sys-actions :deep(.el-alert) {
  width: 260px;
  padding: 4px 8px;
}
.sys-tabs {
  min-width: 0;
}
.sys-tabs :deep(.el-tabs__content) {
  overflow: visible;
}
.sys-grid {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-3);
  min-width: 0;
}
.page-head { display: flex; justify-content: space-between; align-items: center; }
.config-body {
  flex: 1 1 auto;   /* 填满 LayoutHost 的条件成长区，页面内容在本区域内滚动 */
  min-height: 0;
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: auto;
}
.pane-fill {
  height: 100%;
  display: flex;
}
.config-error {
  height: 100%;
}
.config-loading {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-body);
}
.setting-item { display: flex; flex-direction: column; gap: var(--app-space-2); }
.setting-label { font-size: var(--app-font-size-body); color: var(--page-settings-text-subtle); }
.page-title {
  margin: 0;
  font-size: var(--app-font-size-page-title-sm);
}
.hint {
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-table);
  margin: 4px 0 12px;
}
.score-layout {
  display: flex;
  gap: var(--app-space-4);
  min-height: 0;  /* 评分/买卖工作区作为成长列容器，需可被钳定，editor 的 flex:1 才能正确分高 */
}
.prof-list {
  width: 190px;
  flex-shrink: 0;
}
.prof-list ul {
  list-style: none;
  padding: 0;
  margin: 10px 0 0;
}
.prof-list li {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 9px 11px;
  border-radius: 7px;
  cursor: pointer;
  font-size: var(--app-font-size-body);
  margin-bottom: 4px;
}
.prof-list li:hover {
  background: var(--el-fill-color-light);
}
.prof-list li.active {
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
  font-weight: var(--app-font-weight-section);
}
.editor {
  flex: 1;
  min-width: 0;
}
.editor-score {
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.ed-head {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
}
.spacer {
  flex: 1;
}
.ver-badge {
  font-size: var(--app-font-size-caption);
  color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
  border-radius: 10px;
  padding: 1px 8px;
  font-weight: var(--app-font-weight-section);
  cursor: pointer;
  user-select: none;
}
.ver-badge:hover {
  background: var(--el-color-primary-light-7);
}
.id-badge {
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--el-text-color-secondary);
  background: var(--el-fill-color-light);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
  padding: 1px 8px;
  font-size: var(--app-font-size-caption);
}
.mono {
  font-family: var(--app-font-family-mono);
}
.ver-item {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  padding: 8px 10px;
  margin-bottom: 10px;
}
.ver-head {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
}
.ast {
  margin: 8px 0 0;
  padding: 10px 12px;
  background: var(--el-fill-color-light);
  border-radius: 6px;
  font-size: var(--app-font-size-caption);
  color: var(--el-text-color-regular);
  max-height: 200px;
  overflow: auto;
  white-space: pre-wrap;
}
.wsum {
  font-size: var(--app-font-size-table);
  color: var(--el-color-success);
  font-weight: var(--app-font-weight-section);
}
.wsum.bad {
  color: var(--el-color-danger);
}
.scoring-cell {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-control-gap);
}
.tip {
  font-size: var(--app-font-size-caption);
  color: var(--el-text-color-secondary);
}
.linear-row,
.band-row {
  display: flex;
  align-items: center;
  gap: var(--app-space-control-gap);
  font-size: var(--app-font-size-caption);
}
.band-box {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-1);
}
.band-box > .el-button.is-link,
.def-params > .el-button.is-link {
  align-self: flex-start;
  width: fit-content;
}
.weight-cell {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
}
.wval {
  width: 42px;
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.run-head {
  display: flex;
  align-items: center;
  gap: var(--app-space-3);
  margin: 22px 0 10px;
}
.run-table-wrap {
  flex: 1 1 auto;
  min-height: 240px;
  display: flex;
  flex-direction: column;
}
.run-title {
  font-weight: var(--app-font-weight-section);
  font-size: var(--app-font-size-section-title);
}
.subchip {
  display: inline-block;
  background: var(--el-fill-color-light);
  border-radius: 4px;
  padding: 1px 6px;
  margin: 0 4px 2px 0;
  font-size: var(--app-font-size-caption);
}
.param-row {
  display: flex;
  flex-wrap: wrap;
  gap: var(--app-space-control-gap);
  margin-top: 5px;
}
.param-item {
  display: inline-flex;
  align-items: center;
  gap: var(--app-space-1);
  font-size: var(--app-font-size-caption);
  color: var(--el-text-color-secondary);
}
.tech-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--app-space-4);
  margin-bottom: 12px;
  flex: none;
}
.tech-actions {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
  flex-shrink: 0;
}
.tech-pane {
  flex-direction: column;
  gap: var(--app-space-3);
  min-height: 0;
}
/* 技术指标表承接复合面板内部的成长与表体滚动。 */
.tech-table-wrap {
  flex: 1 1 auto;
  min-height: 360px;
  display: flex;
  flex-direction: column;
}
.tech-table-wrap .el-table {
  flex: 1 1 auto;
  min-height: 0;
}
.expr {
  font-family: var(--app-font-family-mono);
  background: var(--el-fill-color-light);
  border-radius: 4px;
  padding: 1px 6px;
  font-size: var(--app-font-size-caption);
}
.usage {
  display: block;
  font-size: var(--app-font-size-caption);
  line-height: var(--app-line-height-reading);
  color: var(--el-text-color-regular);
  white-space: normal;
  word-break: break-word;
}
.def-params {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-control-gap);
  width: 100%;
}
.def-param-row {
  display: flex;
  align-items: center;
  gap: var(--app-space-control-gap);
}
.cond-block {
  margin: 14px 0;
  padding: 12px 14px;
  border: 1px solid var(--el-border-color-light);
  border-radius: 8px;
  background: var(--el-fill-color-blank);
}
.cond-head {
  display: flex;
  align-items: center;
  gap: var(--app-space-3);
  margin-bottom: 10px;
}
.cond-title {
  font-weight: var(--app-font-weight-section);
  font-size: var(--app-font-size-body);
}
.cond-title.buy {
  color: var(--el-color-danger);
}
.cond-title.sell {
  color: var(--el-color-success);
}
.cond-row {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
  margin-bottom: 7px;
  flex-wrap: wrap;
}
.backstop-row {
  display: flex;
  gap: var(--app-space-5);
  margin-top: 8px;
}
.bs-item {
  display: inline-flex;
  align-items: center;
  gap: var(--app-space-control-gap);
  font-size: var(--app-font-size-table);
  color: var(--el-text-color-regular);
}
.bs-item i {
  font-style: normal;
  color: var(--el-text-color-secondary);
}
/* 试算结果分项达标分：彩色徽章，按分值高低着色 */
.subchips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--app-space-control-gap);
}
.subchip.score {
  display: inline-flex;
  align-items: center;
  gap: var(--app-space-control-gap);
  white-space: nowrap;
  margin: 0;
  padding: 2px 7px;
  border-radius: 11px;
  line-height: var(--app-line-height-comfy);
}
.subchip.score i {
  font-style: normal;
  color: var(--el-text-color-secondary);
}
.subchip.score b {
  font-variant-numeric: tabular-nums;
}
.subchip.score.hi {
  background: var(--score-high-bg);
}
.subchip.score.hi b {
  color: var(--score-high-text);
}
.subchip.score.mid {
  background: var(--score-mid-bg);
}
.subchip.score.mid b {
  color: var(--score-mid-text);
}
.subchip.score.lo {
  background: var(--el-fill-color);
}
.subchip.score.lo b {
  color: var(--el-text-color-secondary);
}
@media (max-width: 980px) {
  .sys-head {
    flex-direction: column;
    align-items: stretch;
  }
  .sys-actions {
    justify-content: flex-start;
  }
  .sys-actions :deep(.el-alert) {
    width: 100%;
  }
  .sys-grid {
    grid-template-columns: 1fr;
  }
}
</style>
