<script setup lang="ts">
import { vKeyboardActivate } from '@/directives/keyboardActivate'
import AppHoverInfo from '@/components/AppHoverInfo'
import AppAdvancedSearch from '@/components/AppAdvancedSearch.vue'
import { useMenuPageTitle } from '@/composables/useMenuPageTitle'
import AppTableColumn from '@/components/AppTableColumn.vue'
import AppFilterSelect from '@/components/AppFilterSelect.vue'
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Close, Plus, VideoPlay } from '@element-plus/icons-vue'
import {
  browseScoreProfiles,
  copyScoreProfile,
  deleteIndicatorDef,
  getIndicatorReferences,
  deleteScoreProfile,
  getIndicatorRegistry,
  getScoreProfile,
  getScoreProfileVersions,
  listScoreProfiles,
  runScoreProfile,
  previewIndicatorDef,
  saveIndicatorDef,
  updateIndicatorDef,
  saveScoreProfile,
  setScoreProfileVisibility,
  setIndicatorCategories,
  setIndicatorEnabled,
  type IndicatorDef,
  type IndicatorParam,
  type IndicatorPreviewResult,
  type IndicatorReferenceSummary,
  type IndicatorTemplate,
  type ScoreItem,
  type ScoreProfileSummary,
  type ScoreProfileVersion,
  type ScoreRunRow,
} from '@/api/scoreProfile'
import {
  KLINE_PERIOD_OPTIONS,
  type KlinePeriod,
} from '@/components/stock-chart/klinePeriod'
import AssetVisibilityActions from '@/components/AssetVisibilityActions.vue'
import AssetProfileSelect from '@/components/asset-search/AssetProfileSelect.vue'
import AppDataTable from '@/components/AppDataTable.vue'
import AppAsyncRegion from '@/components/AppAsyncRegion.vue'
import AppDetailDrawer from '@/components/AppDetailDrawer.vue'
import AppStateBlock from '@/components/AppStateBlock.vue'
import AppStatusNotice from '@/components/AppStatusNotice.vue'
import RankedStockWorkbench from '@/components/ranked-stock/RankedStockWorkbench.vue'
import type { RankedStockColumnKey } from '@/components/ranked-stock/types'
import AppIconButton from '@/components/AppIconButton.vue'
import AppSearchInput from '@/components/AppSearchInput.vue'
import AppRowActions from '@/components/AppRowActions.vue'
import HelpHint from '@/components/HelpHint.vue'
import HelpTip from '@/components/HelpTip.vue'
import HelpTipItem from '@/components/HelpTipItem.vue'
import PageSegmented from '@/components/PageSegmented.vue'
import PageSettingItem from '@/components/PageSettingItem.vue'
import PageSettingSection from '@/components/PageSettingSection.vue'
import SystemBuiltinTag from '@/components/SystemBuiltinTag.vue'
import TradeDatePicker from '@/components/TradeDatePicker.vue'
import IndicatorParamFields from '@/components/indicator/IndicatorParamFields.vue'
import IndicatorParamSchemaEditor from '@/components/indicator/IndicatorParamSchemaEditor.vue'
import IndicatorSelect from '@/components/indicator/IndicatorSelect.vue'
import StrategyItemEnabledSwitch from '@/components/strategy/StrategyItemEnabledSwitch.vue'
import { getErrorMessage } from '@/utils/error'
import { formatDateTimeMinutes } from '@/utils/dateTime'
import PageSettingsDrawer from '@/components/PageSettingsDrawer.vue'
import PageSettingsTrigger from '@/components/PageSettingsTrigger.vue'
import ConfigGroupForm from '@/components/config/ConfigGroupForm.vue'
import { usePageSettings } from '@/composables/usePageSettings'
import { useDefaultedSessionValue } from '@/composables/useDefaultedSessionValue'
import { useTableSort } from '@/composables/useTableSort'
import { useFormChangeTracker } from '@/composables/useFormChangeTracker'
import { useMarketMasterRatioRuntime } from '@/composables/useMarketMasterRatioRuntime'
import {
  composeComponentRuntimeValueOf,
  useStockChartComponentConfig,
} from '@/composables/useStockChartComponentConfig'
import { useRankedStockResultView } from '@/composables/useRankedStockResultView'
import {
  useStockAdjustModeSession,
  type StockAdjustMode,
} from '@/composables/useStockAnalysisSession'
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
const canManageIndicators = computed(() =>
  hasPermission(auth.role, auth.permissions, 'indicator:def-manage'),
)
type ConfigTab = 'score' | 'tech' | 'trade' | 'system'
const forcedTab = computed<ConfigTab | null>(() => (route.meta.configTab as ConfigTab | undefined) ?? null)
const activeTab = computed<ConfigTab>(() => forcedTab.value || 'score')
function configPageKeyOf(tab: ConfigTab): string {
  return `config-${tab}`
}
const configPageKey = configPageKeyOf(activeTab.value)
const pageTitle = useMenuPageTitle({ fallback: '配置管理' })
const pageSubtitle = computed(() => {
  if (forcedTab.value === 'score') return '按权重组合技术指标打分排序，权重自动归一到 100%。'
  if (forcedTab.value === 'trade') return '买入/卖出各一组技术指标条件（且/或），止盈/止损/持仓为可选兜底。'
  if (forcedTab.value === 'tech') return '系统内置指标不可删除仅可启停；自定义指标为一段带参数的表达式，供评分/筛选/买卖引用。'
  if (forcedTab.value === 'system') return '保存后即时影响访问安全、数据采集、审计留存和研究运行参数。'
  return ''
})
type ConfigPageSettings = Record<string, unknown> & {
  adjustMode?: StockAdjustMode
}
const configDefaults: ConfigPageSettings = activeTab.value === 'score'
  ? { adjustMode: 'qfq' }
  : {}
const { settings, isDirty, reset } = usePageSettings(configPageKey, configDefaults)
const adjustMode = useStockAdjustModeSession(settings)
const settingsAdjustMode = computed<StockAdjustMode>({
  get: () => settings.adjustMode ?? 'qfq',
  set: (value) => { settings.adjustMode = value },
})

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
  componentLayerValuesOf, componentAllowedLayers,
  remoteHydrated,
  saveRemoteUserConfig,
} = useRemoteLayoutConfig(configLayout)

// 抽屉由 PageSettingsDrawer 按布局旋钮渲染；本页不再暴露 tabs 组件配置。
const drawerConfig = { knobs: layoutKnobs, valueOf, sourceOf, setKnob, componentValueOf, setComponentKnob, componentSourceOf, layerValuesOf, componentLayerValuesOf, componentAllowedLayers, save: saveRemoteUserConfig }
const {
  setCurrentMasterRatioSample,
  componentRuntimeValueOf: masterRuntimeValueOf,
} = useMarketMasterRatioRuntime()
const chartPreferences = useStockChartComponentConfig({
  slotId: 'analysis',
  componentValueOf,
  setComponentKnob,
  hydrated: remoteHydrated,
})
const componentRuntimeValueOf = composeComponentRuntimeValueOf(
  masterRuntimeValueOf,
  chartPreferences.componentRuntimeValueOf,
)

const TECH_SORT_FIELDS = ['catOrder', 'name_cn', 'layerLabel', 'typeLabel', 'srcLabel', 'hasParams'] as const
const {
  sortBy: techSortBy,
  sortOrder: techSortOrder,
  elementDefaultSort: techDefaultSort,
  onSortChange: onTechSortChange,
} = useTableSort<(typeof TECH_SORT_FIELDS)[number]>({
  slotId: 'techTable',
  defaultSort: 'catOrder:asc',
  componentValueOf,
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
// 系统设置分组页签单向：组件配置层默认值（sysTabs.defaultActive）→ 会话 ref；页面切换不写回配置层。
const sysTabDefault = computed<string>(() => (componentValueOf('sysTabs', 'defaultActive') as string) || 'access')
const activeSysTab = useDefaultedSessionValue(sysTabDefault)
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
  if (m) {
    // 文案按 mode 精确对齐后端/mailer 真实分支：incomplete 会发码失败（非只写日志）。
    if (m.mode === 'ready') {
      out['auth.require_email_code'] = { tone: 'ok', text: `真实发信已就绪（${m.username_masked}）` }
    } else if (m.mode === 'incomplete') {
      out['auth.require_email_code'] = { tone: 'warn', text: '真实发信已开启但配置不完整，发码会失败（部署侧补全 AI_STOCKS_SMTP_*）' }
    } else {
      out['auth.require_email_code'] = { tone: 'warn', text: '真实发信未启用，验证码只写日志不真发（部署侧配 AI_STOCKS_SMTP_*）' }
    }
  }
  for (const group of sysGroups.value) {
    for (const field of group.fields) {
      if (field.secret_status === 'unavailable') {
        out[field.path] = {
          tone: 'warn',
          text: '已存密文无法解密，请检查主密钥或输入新值后保存',
        }
      } else if (field.path === 'ths_board.login_cookie' && field.credential) {
        const labels: Record<string, string> = {
          pending: 'Cookie 已保存，等待“测试连通”真实校验',
          valid: 'Cookie 登录态有效',
          expiring: `Cookie 即将到期（剩余 ${field.credential.remaining_days ?? 0} 天）`,
          expired: 'Cookie 已超过默认有效期，请重新校验或更换',
          invalid: 'Cookie 登录态已失效，请更换',
          unknown: 'Cookie 来自部署配置，尚未真实校验',
          check_failed: 'Cookie 最近一次真实校验失败，请检查网络后重试',
        }
        const text = labels[field.credential.status]
        if (text) out[field.path] = {
          tone: field.credential.status === 'valid' ? 'ok' : 'warn',
          text,
        }
      }
    }
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
    '恢复默认',
    { type: 'warning' },
  )
  sysSaving.value = true
  sysSaveError.value = false
  try {
    await resetSettings(activeSysPaths.value)
    ElMessage.success('配置已恢复默认')
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
const indicatorTemplates = ref<IndicatorTemplate[]>([])
const indicatorDefaultPeriod = ref<KlinePeriod>('day')
function klinePeriodLabel(period: KlinePeriod | null | undefined): string {
  if (!period) return ''
  return KLINE_PERIOD_OPTIONS.find(({ value }) => value === period)?.label ?? period
}
// 可作为评分项的指标（启用项）
const scorable = computed(() => registry.value.filter((d) => d.enabled))
function nameOf(key: string): string {
  return registry.value.find((d) => d.key === key)?.name_cn || key
}
function defOf(key: string): IndicatorDef | undefined {
  return registry.value.find((d) => d.key === key)
}
async function reloadRegistry() {
  const result = await getIndicatorRegistry(true)
  registry.value = result.items
  indicatorTemplates.value = result.templates ?? []
  indicatorDefaultPeriod.value = result.calculation_context?.default_period ?? 'day'
}

// 技术指标列表：搜索 + 排序 + 多分类
const techSearch = ref('')
const techLayer = ref('')
const techSource = ref('')
const techDtype = ref('')
const techStatus = ref('')
const showPresets = ref(false)
const hasTechFilters = computed(() => Boolean(
  techSearch.value.trim() || techLayer.value || techSource.value
  || techDtype.value || techStatus.value || showPresets.value,
))
function resetTechFilters(): void {
  techSearch.value = ''
  techLayer.value = ''
  techSource.value = ''
  techDtype.value = ''
  techStatus.value = ''
  showPresets.value = false
}
const LAYER_LABELS: Record<string, string> = {
  field: '基础字段', metric: '数值指标', signal: '布尔信号', preset: '参数预设',
}
// 分类默认排序：按预设角度顺序，自定义分类排其后(中文序)
const CATEGORY_ORDER = ['价格', '趋势', '动量', '量能', '位置', '均线', '突破', '估值', '换手', '形态', '强度', '新高', '事件', '筹码']
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
const categoryOptions = computed(() => allCategories.value.map((category) => ({
  value: category,
  label: category,
})))
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
      calculationPeriodLabel: klinePeriodLabel(d.calculation_period),
      layerLabel: d.layer ? LAYER_LABELS[d.layer] ?? d.layer : '未分层',
      parentName: d.parent_key ? nameOf(d.parent_key) : '',
    }
  })
  const searched = !q ? rows : rows.filter((d) =>
    [d.name_cn, d.key, d.desc, ...(d.categories ?? [])].join(' ').toLowerCase().includes(q),
  )
  const filtered = searched.filter((d) =>
    (!techLayer.value || d.layer === techLayer.value)
    && (!techSource.value || (techSource.value === 'builtin') === d.is_builtin)
    && (!techDtype.value || d.dtype === techDtype.value)
    && (!techStatus.value || (techStatus.value === 'enabled') === d.enabled)
    && (showPresets.value || !!q || techLayer.value === 'preset' || d.layer !== 'preset'),
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
function onCategorySelectChange(key: string, value: string[] | string) {
  return onCategoriesChange(key, Array.isArray(value) ? value : [value].filter(Boolean))
}
function formatPresetParams(params: Record<string, number | string> | undefined): string {
  return Object.entries(params ?? {}).map(([key, value]) => `${key}=${value}`).join('，')
}

// 技术指标管理：启停 / 删除 / 新建自定义
async function toggleEnabled(row: IndicatorDef) {
  await setIndicatorEnabled(row.key, !row.enabled)
  await reloadRegistry()
}
async function removeDef(row: IndicatorDef) {
  const refs = await getIndicatorReferences(row.key)
  if (refs.count) {
    ElMessage.warning(`该指标被 ${refs.count} 个方案版本引用，并关联 ${refs.backtest_count} 条回测，不能删除`)
    return
  }
  await ElMessageBox.confirm(`确认删除自定义指标「${row.name_cn}」？`, '提示', { type: 'warning' })
  await deleteIndicatorDef(row.key)
  ElMessage.success('已删除')
  await reloadRegistry()
}

function indicatorDefRowActions(row: IndicatorDef): AppRowAction[] {
  if (row.is_builtin) return []
  return [
    {
      key: 'edit',
      label: '编辑',
      permission: 'indicator:def-manage',
      onClick: () => openEditDef(row),
    },
    {
      key: 'delete',
      label: '删除',
      type: 'danger',
      permission: 'indicator:def-manage',
      onClick: () => removeDef(row),
    },
  ]
}

const defDrawer = ref(false)
const defMode = ref<'template' | 'dsl'>('template')
const selectedTemplate = ref('')
const editingKey = ref('')
const indicatorDefinitionPeriod = ref<KlinePeriod>('day')
const indicatorDefinitionPeriodLabel = computed(() => klinePeriodLabel(indicatorDefinitionPeriod.value))
const defSaving = ref(false)
const defPreviewing = ref(false)
const defPreview = ref<IndicatorPreviewResult | null>(null)
const defReferences = ref<IndicatorReferenceSummary | null>(null)
const defReferencesLoading = ref(false)
const defReferencesError = ref(false)
const previewCode = ref('')
const defPreviewDate = ref('')
const previewValues = ref<Record<string, number>>({})
const defForm = ref<{
  key: string; name_cn: string; dtype: 'bool' | 'number'; expression: string
  category: string; desc: string; params: IndicatorParam[]; categories: string[]
}>({ key: '', name_cn: '', dtype: 'number', expression: '', category: '自定义', desc: '', params: [], categories: [] })
const indicatorSubmitPayload = () => ({
  key: defForm.value.key.trim(),
  name_cn: defForm.value.name_cn.trim(),
  dtype: defForm.value.dtype,
  expression: defForm.value.expression.trim(),
  params: defForm.value.params,
  category: defForm.value.category,
  desc: defForm.value.desc.trim(),
  categories: [...defForm.value.categories].sort(),
})
const {
  hasChanges: indicatorFormChanged,
  captureBaseline: captureIndicatorBaseline,
} = useFormChangeTracker(indicatorSubmitPayload)

const semanticLocked = computed(() => !!editingKey.value && (
  defReferencesLoading.value || defReferencesError.value || !!defReferences.value?.count
))

function resetPreviewValues(): void {
  previewValues.value = Object.fromEntries(defForm.value.params.map((p) => [p.name, p.default]))
  defPreview.value = null
}

function openNewDef() {
  editingKey.value = ''
  indicatorDefinitionPeriod.value = indicatorDefaultPeriod.value
  defReferences.value = null
  defReferencesError.value = false
  defMode.value = 'template'
  selectedTemplate.value = ''
  previewCode.value = ''
  defPreviewDate.value = ''
  defForm.value = { key: '', name_cn: '', dtype: 'number', expression: '', category: '自定义', desc: '', params: [], categories: [] }
  resetPreviewValues()
  captureIndicatorBaseline()
  defDrawer.value = true
}
async function openEditDef(row: IndicatorDef) {
  editingKey.value = row.key
  indicatorDefinitionPeriod.value = row.calculation_period ?? indicatorDefaultPeriod.value
  defReferencesLoading.value = true
  defReferencesError.value = false
  defMode.value = 'dsl'
  selectedTemplate.value = ''
  previewCode.value = ''
  defPreviewDate.value = ''
  defForm.value = {
    key: row.key, name_cn: row.name_cn, dtype: row.dtype, expression: row.expression ?? '',
    category: row.category, desc: row.desc, params: row.params.map((p) => ({ ...p })),
    categories: [...row.categories],
  }
  resetPreviewValues()
  captureIndicatorBaseline()
  defDrawer.value = true
  try {
    defReferences.value = await getIndicatorReferences(row.key)
  } catch {
    defReferencesError.value = true
  } finally {
    defReferencesLoading.value = false
  }
}
function applyTemplate(key: string) {
  const template = indicatorTemplates.value.find((item) => item.key === key)
  if (!template) return
  defForm.value.dtype = template.dtype
  defForm.value.expression = template.expression
  defForm.value.params = template.params.map((param) => ({ ...param }))
  if (!defForm.value.name_cn) defForm.value.name_cn = template.name
  resetPreviewValues()
}
function templateSummary(key: string): string {
  return ({
    range_position: '判断收盘价处于一段价格区间的什么位置',
    distance_to_high: '计算当前价格距离一段时间最高点有多远',
    ma_spread: '衡量快线与慢线之间的距离和趋势强弱',
  } as Record<string, string>)[key] ?? '从预设公式开始，只需调整参数'
}
async function runDefPreview() {
  if (!previewCode.value.trim()) {
    ElMessage.warning('请填写代表性股票代码后试算')
    return
  }
  defPreviewing.value = true
  try {
    defPreview.value = await previewIndicatorDef({
      dtype: defForm.value.dtype, expression: defForm.value.expression,
      params: defForm.value.params, values: previewValues.value,
      code: previewCode.value.trim(), trade_date: defPreviewDate.value || undefined,
    })
  } finally {
    defPreviewing.value = false
  }
}
async function submitNewDef() {
  if (!indicatorFormChanged.value) return
  const f = defForm.value
  if (!f.key || !f.name_cn || !f.expression) {
    ElMessage.warning('请填写标识、名称、表达式')
    return
  }
  if (!semanticLocked.value && defPreview.value?.status !== 'ok') {
    ElMessage.warning('请先完成一次有效试算')
    return
  }
  defSaving.value = true
  try {
    const body = {
      key: f.key, name_cn: f.name_cn, dtype: f.dtype, expression: f.expression,
      params: f.params, category: f.category, desc: f.desc, categories: f.categories,
    }
    if (editingKey.value) await updateIndicatorDef(editingKey.value, body)
    else await saveIndicatorDef(body)
    ElMessage.success('已保存')
    defDrawer.value = false
    await reloadRegistry()
  } catch {
    /* 错误已由拦截器提示 */
  } finally {
    defSaving.value = false
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
const includeSt = ref(true)
const saving = ref(false)
const visibilitySaving = ref(false)
const isNew = ref(false)
const profileReadonly = ref(false)
const profileVisibility = ref<'private' | 'tenant' | 'public'>('private')
const scoreSubmitPayload = () => ({
  name: editName.value.trim(),
  items: items.value,
  include_st: includeSt.value,
})
const {
  hasChanges: scoreFormChanged,
  captureBaseline: captureScoreBaseline,
} = useFormChangeTracker(scoreSubmitPayload)
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
function itemEnabled(item: { enabled?: boolean }): boolean {
  return item.enabled !== false
}
const activeScoreItems = computed(() => items.value.filter(itemEnabled))
const weightSum = computed(() =>
  Math.round(activeScoreItems.value.reduce((s, it) => s + (it.weight || 0), 0) * 100),
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
    includeSt.value = p.include_st !== false
    items.value.forEach(ensureParams)
    profileReadonly.value = !!p.readonly
    profileVisibility.value = p.visibility || 'private'
    isNew.value = false
    scoreLastAppliedRef = curRef.value
    captureScoreBaseline()
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
  includeSt.value = v.include_st !== false
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
  if (item.enabled === undefined) item.enabled = true
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
  includeSt.value = true
  profileReadonly.value = false
  profileVisibility.value = 'private'
  isNew.value = true
  // 新建态同步清空「最后成功项」，避免后续详情失败回滚到已废弃的旧方案
  scoreLastAppliedRef = ''
  scoreDetailAttempt = ''
  profileDetailError.value = ''
  clearScoreRunResult()
  captureScoreBaseline()
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
    enabled: true,
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
  const active = activeScoreItems.value
  const n = active.length
  if (!n) return
  const w = Math.floor((100 / n)) / 100
  active.forEach((it, i) => {
    it.weight = i === n - 1 ? +(1 - w * (n - 1)).toFixed(2) : w
  })
}

function onScoreEnabledChange() {
  rebalanceEqual()
  clearScoreRunResult()
}

// 拖动某项权重 → 其余按比例自动重分配，保持总和 100%
function onWeightChange(idx: number, pct: number) {
  if (!itemEnabled(items.value[idx])) return
  const v = Math.min(100, Math.max(0, pct)) / 100
  const others = items.value.filter((item, i) => i !== idx && itemEnabled(item))
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
  if (!scoreFormChanged.value) return
  if (profileReadonly.value) {
    ElMessage.warning('公开方案为只读，请先复制为自己的方案')
    return
  }
  if (!editName.value) {
    ElMessage.warning('请填写方案名称')
    return
  }
  if (!activeScoreItems.value.length) {
    ElMessage.warning('请至少启用一个指标项')
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
      include_st: includeSt.value,
    })
    curVersion.value = r.version
    ElMessage.success(`已保存（v${r.version}）`)
    isNew.value = false
    editId.value = r.id
    curId.value = r.id
    captureScoreBaseline()
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
const scoreRunCompleted = ref(false)
function clearScoreRunResult() {
  runRows.value = []
  runError.value = ''
  scoreRunCompleted.value = false
}
const subKeys = computed(() => activeScoreItems.value.map((i) => i.indicator))
const scoreRunColumnKeys = computed<RankedStockColumnKey[]>(() => [
  'rank', 'code', 'name', 'board', 'score', 'grade', 'subScores',
])
const {
  rows: displayRunRows,
  columns: scoreRunColumns,
  onSortChange: onScoreRunSortChange,
} = useRankedStockResultView({
  rows: runRows,
  columnKeys: scoreRunColumnKeys,
  componentValueOf,
})

async function tryRun() {
  if (!activeScoreItems.value.length || weightSum.value !== 100) {
    ElMessage.warning('请至少启用一个指标，并确保启用项权重合计 100%')
    return
  }
  running.value = true
  runError.value = ''
  try {
    const res = await runScoreProfile({
      ...(editId.value && !scoreFormChanged.value
        ? { profile_id: curRef.value }
        : { items: items.value, include_st: includeSt.value }),
      run_date: runDate.value || undefined,
      top: 30,
    })
    runRows.value = res.list
    scoreRunCompleted.value = true
    runDate.value = res.run_date
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
const tradeSubmitPayload = () => ({
  name: tEditName.value.trim(),
  buy_tree: toTree(buyLogic.value, buyConds.value),
  sell_tree: toTree(sellLogic.value, sellConds.value),
  backstop: {
    take_profit: backstop.value.tp != null ? backstop.value.tp / 100 : null,
    stop_loss: backstop.value.sl != null ? backstop.value.sl / 100 : null,
    max_hold_days: backstop.value.hold ?? null,
  },
})
const {
  hasChanges: tradeFormChanged,
  captureBaseline: captureTradeBaseline,
} = useFormChangeTracker(tradeSubmitPayload)
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
  if (def?.dtype === 'bool') return { indicator: key, enabled: true, params, cmp: '==', value: true }
  return { indicator: key, enabled: true, params, cmp: '>=', value: 0 }
}
function onCondIndicator(cond: TradeCond) {
  const enabled = itemEnabled(cond)
  Object.assign(cond, condForIndicator(cond.indicator), { enabled })
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
      leaf.enabled = itemEnabled(c)
      if (c.params && Object.keys(c.params).length) leaf.params = c.params
      return leaf
    }),
  }
}
function fromTree(tree: CondTree | Record<string, never> | undefined): { logic: 'AND' | 'OR'; conds: TradeCond[] } {
  const t = tree as CondTree
  if (!t || !t.children) return { logic: 'AND', conds: [] }
  const conds = t.children.map((l) => ({
    indicator: l.indicator, enabled: itemEnabled(l), params: l.params ?? {}, cmp: l.cmp, value: l.value,
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
    captureTradeBaseline()
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
  captureTradeBaseline()
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
  if (!tradeFormChanged.value) return
  if (tReadonly.value) { ElMessage.warning('公开方案为只读，请先复制为自己的方案'); return }
  if (!tEditName.value) { ElMessage.warning('请填写方案名称'); return }
  if (!buyConds.value.some(itemEnabled)) { ElMessage.warning('请至少启用一个买入条件'); return }
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
    captureTradeBaseline()
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
  if (!conds.some(itemEnabled)) { ElMessage.warning('该侧没有已启用的条件'); return }
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
  <LayoutHost :component-value-of="componentValueOf" :layout="configEffective">
    <template #action>
    <div class="page-head">
      <div>
        <h2 class="page-title app-page-title">
          {{ pageTitle }}
          <HelpTip v-if="activeTab === 'score'" title="评分规则说明" :width="420">
            <HelpTipItem question="指标如何打分">
              <ul>
                <li>每个指标产出 0~100 达标分（布尔=满足100/否0；数值按阈值映射），按权重百分比加权得到综合分。</li>
              </ul>
            </HelpTipItem>
            <HelpTipItem question="权重如何调整">
              <ul>
                <li>调一个权重，其余自动按比例重分配，合计始终保持 100%。</li>
              </ul>
            </HelpTipItem>
            <HelpTipItem question="方案如何管理">
              <ul>
                <li>系统内置方案只读，可复制为我的方案后编辑；「用当前配置试算」按所选交易日预览评分结果。</li>
              </ul>
            </HelpTipItem>
          </HelpTip>
          <HelpTip v-else-if="activeTab === 'tech'" title="技术指标说明" :width="420" test-id="config-tech-help-tip">
            <HelpTipItem question="指标如何维护">
              <ul>
                <li>系统内置不可删除，仅可启停；自定义指标是一段带参数的表达式，供评分、筛选和买卖引用。</li>
              </ul>
            </HelpTipItem>
            <HelpTipItem question="表达式支持什么">
              <ul>
                <li>函数支持 MA / HHV / LLV / REF / COUNT / SUM / ABS。</li>
                <li>变量支持 C / O / H / L / V / TURN。</li>
              </ul>
            </HelpTipItem>
            <HelpTipItem question="分类如何维护">
              <ul>
                <li>分类可多选，也可直接输入新名称后回车创建。</li>
              </ul>
            </HelpTipItem>
          </HelpTip>
          <HelpTip v-else-if="activeTab === 'trade'" title="买卖指标说明" :width="420">
            <HelpTipItem question="条件如何组成">
              <ul>
                <li>买入/卖出各是一组技术指标条件，支持「且（全满足）」和「或（任一）」组合。</li>
              </ul>
            </HelpTipItem>
            <HelpTipItem question="卖出如何成交">
              <ul>
                <li>卖出以指标命中为主，止盈/止损/最大持仓为可选兜底，先到先卖。</li>
              </ul>
            </HelpTipItem>
            <HelpTipItem question="方案如何管理">
              <ul>
                <li>系统内置方案只读，可复制为我的方案后编辑；买入、卖出可分别「试算」命中只数。</li>
              </ul>
            </HelpTipItem>
          </HelpTip>
          <HelpTip v-else-if="activeTab === 'system'" title="系统设置说明" :width="420">
            <HelpTipItem question="这里管什么">
              <ul>
                <li>访问安全、数据采集、审计留存和研究运行参数，按分组页签维护。</li>
              </ul>
            </HelpTipItem>
            <HelpTipItem question="保存何时生效">
              <ul>
                <li>「保存并生效」写入后立即影响全站运行；存在超出允许范围的配置项时无法保存。</li>
              </ul>
            </HelpTipItem>
            <HelpTipItem question="恢复默认做什么">
              <ul>
                <li>「恢复默认」将当前分组页签下所有配置恢复为默认值，未保存的编辑一并丢弃。</li>
              </ul>
            </HelpTipItem>
          </HelpTip>
        </h2>
        <p class="page-subtitle">{{ pageSubtitle }}</p>
      </div>
      <div class="page-head-actions">
        <el-button
          v-if="activeTab === 'tech'"
          v-permission="'indicator:def-manage'"
          type="primary"
          @click="openNewDef"
        >
          <template #icon><el-icon><Plus /></el-icon></template>
          新建自定义指标
        </el-button>
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
            <div class="ed-head app-cluster-md">
              <el-input v-model="editName" :disabled="profileReadonly" placeholder="方案名称" style="width: 200px" />
              <AppHoverInfo v-if="curVersion && !isNew" content="点击查看历史版本">
                <span tabindex="0" class="ver-badge" role="button" @click="openScoreVersions" v-keyboard-activate>v{{ curVersion }}</span>
              </AppHoverInfo>
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
              <el-button v-permission="'score-profile:save'" :disabled="profileReadonly || !scoreFormChanged" :loading="saving" type="primary" @click="save">保存</el-button>
              <el-button v-permission="'score-profile:delete'" v-if="curId && !isNew && !profileReadonly" type="danger" plain @click="remove">删除</el-button>
            </div>

            <div class="score-profile-options">
              <span class="score-profile-option-label">
                ST 股票参与评分排名
                <HelpHint text="决定 ST 是否进入该方案的评分母集和全市场排名；参与评分不会自动加分或扣分。" />
              </span>
              <PageSegmented
                :model-value="includeSt"
                :options="[
                  { label: '参与', value: true },
                  { label: '不参与', value: false },
                ]"
                size="small"
                aria-label="ST 股票参与评分排名"
                :disabled="profileReadonly"
                test-id="score-include-st"
                @update:model-value="includeSt = Boolean($event)"
              />
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

            <AppDataTable
              :data="items"
              size="small"
              :border="tableBorder('scoreItems')"
              class="item-table"
              embedded
            >
              <AppTableColumn label="启用" role="structural">
                <template #default="{ row }">
                  <StrategyItemEnabledSwitch
                    v-model="row.enabled"
                    :disabled="profileReadonly"
                    label="是否启用评分指标"
                    @change="onScoreEnabledChange"
                  />
                </template>
              </AppTableColumn>
              <AppTableColumn label="指标">
                <template #default="{ row }">
                  <IndicatorSelect
                    v-model="row.indicator"
                    :definitions="registry"
                    :disabled="profileReadonly"
                    @change="onIndicatorChange(row)"
                  />
                  <!-- 动态参数（如 连续上涨N天 的 N）-->
                  <div v-if="defOf(row.indicator)?.params?.length" class="param-row">
                    <IndicatorParamFields
                      v-model="row.params!"
                      :params="defOf(row.indicator)!.params"
                      :disabled="profileReadonly"
                    />
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
                        <AppIconButton label="删除分段" tooltip="删除分段" size="xs" tone="danger" :disabled="profileReadonly" @click="removeBand(row, bi)">
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
                      :disabled="profileReadonly || !itemEnabled(row)"
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
            <AppStateBlock v-if="running && !runRows.length" state="loading" title="正在试算评分结果…" />
            <AppStateBlock
              v-else-if="runError"
              state="error"
              :title="runRows.length ? '试算结果刷新失败' : '试算运行失败'"
              :description="runError"
              retry
              @retry="tryRun"
            />
            <div v-else-if="runRows.length" class="run-table-wrap">
            <RankedStockWorkbench
              registry-page-key="config-score"
              :adjust-mode="adjustMode"
              :analysis-defaults="chartPreferences.stockAnalysis.value"
              :rows="displayRunRows"
              :columns="scoreRunColumns"
              :title="runDate || '最新交易日'"
              :meta="`${runRows.length} 只`"
              :run-date="runDate"
              :loading="running"
              :score-keys="subKeys"
              :label-of="nameOf"
              :return-path="route.fullPath"
              collection-label="评分试算"
              :border="tableBorder('result')"
              :default-master-ratio="Number(componentValueOf('workspace', 'masterRatio') ?? 45)"
              :master-ratio-profiles="componentValueOf('workspace', 'masterRatioProfiles')"
              :slot2="chartPreferences.preferences.value.slot2"
              :slot3="chartPreferences.preferences.value.slot3"
              :height-ratios="chartPreferences.currentRatios.value"
              v-model:return-measurement-mode="chartPreferences.returnMeasurementMode.value"
              v-model:kline-period="chartPreferences.klinePeriod.value"
              @sort-change="onScoreRunSortChange"
              @master-ratio-sample-change="setCurrentMasterRatioSample"
              @ratio-draft="chartPreferences.handleRatioDraft"
              @ratio-commit="chartPreferences.handleRatioCommit"
              @workspace-resize="chartPreferences.handleWorkspaceResize"
            />
            </div>
            <AppStateBlock
              v-else-if="scoreRunCompleted"
              state="empty"
              title="当前配置在该交易日暂无评分结果"
            />
            <AppStateBlock v-else state="empty" title="配置评分规则后点「用当前配置试算」" />
          </section>
        </div>
      </template>

      <!-- ============ 技术指标 ============ -->
      <template v-else-if="activeTab === 'tech'">
        <div class="pane-fill tech-pane">
        <el-card shadow="never" class="filter-card tech-filter-card">
          <AppAdvancedSearch
            group="indicators"
            :states="{
              layer: { value: techLayer, options: [{value:'field',label:'基础字段'},{value:'metric',label:'数值指标'},{value:'signal',label:'布尔信号'},{value:'preset',label:'参数预设'}], clear: () => techLayer = '' },
              source: { value: techSource, options: [{value:'builtin',label:'系统内置'},{value:'custom',label:'自定义'}], clear: () => techSource = '' },
              dtype: { value: techDtype, options: [{value:'number',label:'数值'},{value:'bool',label:'布尔'}], clear: () => techDtype = '' },
              status: { value: techStatus, options: [{value:'enabled',label:'已启用'},{value:'disabled',label:'已停用'}], clear: () => techStatus = '' },
              presets: { selfLabelled: true, value: showPresets, active: !showPresets && !techSearch.trim() && techLayer !== 'preset', summary: !showPresets ? '不包含快捷预设' : '', clear: () => showPresets = true },
              keyword: { value: techSearch, clear: () => techSearch = '' }
            }"
          >
            <template #layer>
              <el-select v-model="techLayer" clearable placeholder="业务层级" class="app-control-width-short">
                <el-option value="field" label="基础字段" />
                <el-option value="metric" label="数值指标" />
                <el-option value="signal" label="布尔信号" />
                <el-option value="preset" label="参数预设" />
              </el-select>
            </template>
            <template #source>
              <el-select v-model="techSource" clearable placeholder="来源" class="app-control-width-short">
                <el-option value="builtin" label="系统内置" />
                <el-option value="custom" label="自定义" />
              </el-select>
            </template>
            <template #dtype>
              <el-select v-model="techDtype" clearable placeholder="输出类型" class="app-control-width-short">
                <el-option value="number" label="数值" />
                <el-option value="bool" label="布尔" />
              </el-select>
            </template>
            <template #status>
              <el-select v-model="techStatus" clearable placeholder="状态" class="app-control-width-short">
                <el-option value="enabled" label="已启用" />
                <el-option value="disabled" label="已停用" />
              </el-select>
            </template>
            <template #presets>
              <el-checkbox v-model="showPresets">展开快捷预设</el-checkbox>
            </template>
            <template #keyword>
              <AppSearchInput v-model="techSearch" placeholder="搜索名称/标识/说明/分类" :debounce-ms="0" class="app-control-width-long" />
            </template>
            <template #commands>
                <el-button :disabled="!hasTechFilters" @click="resetTechFilters">重置筛选</el-button>
              </template>
            </AppAdvancedSearch>
        </el-card>
        <div class="tech-table-wrap">
        <AppDataTable :data="techRows" size="small" :border="tableBorder('techTable')"
                  :default-sort="techDefaultSort" @sort-change="onTechSortChange">
          <AppTableColumn prop="name_cn" label="名称" sortable="custom" />
          <AppTableColumn prop="key" label="标识">
            <template #default="{ row }">
              <span class="mono">{{ row.key }}</span>
            </template>
          </AppTableColumn>
          <AppTableColumn prop="layerLabel" label="业务层级" sortable="custom">
            <template #default="{ row }">
              <el-tag size="small" effect="plain">{{ row.layerLabel }}</el-tag>
              <div v-if="row.parent_key" class="tip">属于 {{ row.parentName }} · {{ formatPresetParams(row.preset_params) }}</div>
            </template>
          </AppTableColumn>
          <AppTableColumn
            prop="catOrder"
            label="分类"
            sortable="custom"
            :filter-select-visible-tag-count="2"
          >
            <template #default="{ row }">
              <AppFilterSelect
                :model-value="row.categories"
                :options="categoryOptions"
                :clearable="false"
                :visible-tag-count="2"
                allow-create
                default-first-option
                size="small"
                placeholder="加分类"
                aria-label="维护指标分类"
                :disabled="!canManageIndicators"
                @change="(value) => onCategorySelectChange(row.key, value)"
              />
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
          <AppTableColumn label="计算周期">
            <template #default="{ row }">
              <el-tag
                v-if="row.calculationPeriodLabel"
                size="small"
                effect="plain"
                data-testid="indicator-calculation-period"
              >{{ row.calculationPeriodLabel }}</el-tag>
              <span v-else class="tip">—</span>
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
          <AppTableColumn label="操作" role="action-compact">
            <template #default="{ row }">
              <AppRowActions :actions="indicatorDefRowActions(row)" :inline-limit="1" />
            </template>
          </AppTableColumn>
        </AppDataTable>
        </div>

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
            <div class="ed-head app-cluster-md">
              <el-input v-model="tEditName" :disabled="tReadonly" placeholder="方案名称" style="width: 190px" />
              <AppHoverInfo v-if="tCurVersion && !tIsNew" content="点击查看历史版本">
                <span tabindex="0" class="ver-badge" role="button" @click="openTradeVersions" v-keyboard-activate>v{{ tCurVersion }}</span>
              </AppHoverInfo>
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
              <el-button v-permission="'trade-profile:save'" :disabled="tReadonly || !tradeFormChanged" :loading="tSaving" type="primary" @click="saveTrade">保存</el-button>
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
                <StrategyItemEnabledSwitch v-model="c.enabled" :disabled="tReadonly" label="是否启用买入条件" />
                <IndicatorSelect v-model="c.indicator" :definitions="registry" :disabled="tReadonly" @change="onCondIndicator(c)" />
                <IndicatorParamFields v-model="c.params!" :params="defOf(c.indicator)?.params ?? []" :disabled="tReadonly" />
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
                <StrategyItemEnabledSwitch v-model="c.enabled" :disabled="tReadonly" label="是否启用卖出条件" />
                <IndicatorSelect v-model="c.indicator" :definitions="registry" :disabled="tReadonly" @change="onCondIndicator(c)" />
                <IndicatorParamFields v-model="c.params!" :params="defOf(c.indicator)?.params ?? []" :disabled="tReadonly" />
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
        <AppAsyncRegion
          v-else
          class="sys-wrap"
          :loading="sysLoading"
          :has-content="sysGroups.length > 0"
          loading-title="正在加载系统设置…"
          empty-title="暂无可维护配置"
        >
          <el-tabs v-model="activeSysTab" class="sys-tabs">
            <el-tab-pane
              v-for="tab in sysTabs"
              :key="tab.key"
              :name="tab.key"
              :label="tab.label"
            >
              <div v-if="tab.key === activeSysTab" class="sys-tab-toolbar">
                <div v-if="sysSaveError || sysInvalidPaths.length" class="sys-alerts">
                  <AppStatusNotice
                    v-if="sysSaveError"
                    tone="error"
                    title="保存失败，已保留当前编辑值"
                  />
                  <AppStatusNotice
                    v-else-if="sysInvalidPaths.length"
                    tone="warning"
                    title="存在超出允许范围的配置项"
                  />
                </div>
                <div class="sys-actions">
                  <el-button
                    v-permission="'data-settings:manage'"
                    :loading="sysSaving"
                    :disabled="!activeSysPaths.length"
                    @click="resetActiveSystemTab"
                  >
                    恢复默认
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
        </AppAsyncRegion>
      </template>
    </template>
    </div>
    </template>

    <template #overlays>
    <!-- 评分方案历史版本 -->
    <AppDetailDrawer v-model="sVerVisible" :title="`历史版本 · ${editName || ''}`" size="xl">
      <el-empty v-if="!sVersions.length" class="app-empty app-empty--compact" description="暂无历史版本" />
      <div v-for="v in sVersions" :key="v.version" class="ver-item">
        <div class="ver-head">
          <b>v{{ v.version }}</b>
          <span class="hint">{{ formatDateTimeMinutes(v.saved_at) }}</span>
          <span class="hint">{{ v.items.length }} 项指标</span>
          <div class="spacer" />
          <AppRowActions :actions="scoreVersionRowActions(v)" :inline-limit="1" />
        </div>
        <pre class="ast">{{ JSON.stringify(v.items, null, 2) }}</pre>
      </div>
    </AppDetailDrawer>

    <!-- 买卖方案历史版本 -->
    <AppDetailDrawer v-model="tVerVisible" :title="`历史版本 · ${tEditName || ''}`" size="xl">
      <el-empty v-if="!tVersions.length" class="app-empty app-empty--compact" description="暂无历史版本" />
      <div v-for="v in tVersions" :key="v.version" class="ver-item">
        <div class="ver-head">
          <b>v{{ v.version }}</b>
          <span class="hint">{{ formatDateTimeMinutes(v.saved_at) }}</span>
          <div class="spacer" />
          <AppRowActions :actions="tradeVersionRowActions(v)" :inline-limit="1" />
        </div>
        <pre class="ast">买入 {{ JSON.stringify(v.buy_tree, null, 2) }}
卖出 {{ JSON.stringify(v.sell_tree, null, 2) }}
兜底 {{ JSON.stringify(v.backstop, null, 2) }}</pre>
      </div>
    </AppDetailDrawer>

    <AppDetailDrawer
      v-model="defDrawer"
      :title="editingKey ? `编辑 · ${defForm.name_cn}` : '创建自定义指标'"
      subtitle="定义一个可被筛选、评分和买卖方案共同复用的计算能力。"
      size="xxl"
      class="indicator-definition-drawer"
      destroy-on-close
    >
      <AppStatusNotice
        v-if="defReferencesError"
        title="引用关系加载失败，计算语义已按安全策略锁定；可修改名称、说明和分类后保存。"
        tone="warning"
      />
      <AppStatusNotice
        v-else-if="semanticLocked && !defReferencesLoading"
        title="该指标已被方案引用，计算类型、表达式和参数结构已锁定；如需修改口径，请另存为新指标。"
      />
      <el-form label-position="top" size="small" class="indicator-definition-form">
        <section v-if="!editingKey" class="indicator-editor-section">
          <header class="indicator-editor-section__head">
            <span>01</span>
            <div><h3>选择创建方式</h3><p>第一次创建建议从模板开始，公式创建适合熟悉指标计算的人。</p></div>
          </header>
          <el-radio-group v-model="defMode" class="indicator-create-mode">
            <el-radio-button value="template">
              <b>模板创建</b><small>选择常用计算，修改周期即可</small>
            </el-radio-button>
            <el-radio-button value="dsl">
              <b>公式创建</b><small>使用受限制的安全指标公式</small>
            </el-radio-button>
          </el-radio-group>
          <div v-if="defMode === 'template'" class="indicator-template-grid">
            <el-button
              v-for="item in indicatorTemplates"
              :key="item.key"
              class="app-interaction-target app-interaction-card"
              :class="{ 'is-selected': selectedTemplate === item.key }"
              :aria-pressed="selectedTemplate === item.key"
              @click="selectedTemplate = item.key; applyTemplate(item.key)"
            >
              <b class="app-interaction-content">{{ item.name }}</b>
              <span class="app-interaction-content">{{ templateSummary(item.key) }}</span>
            </el-button>
          </div>
          <AppStatusNotice
            v-else
            title="什么是指标公式？"
            description="它是一种只允许行情字段和安全函数的计算写法，不是 Python 或 SQL，也不能执行任意代码。"
            size="compact"
          />
        </section>

        <section class="indicator-editor-section">
          <header class="indicator-editor-section__head">
            <span>{{ editingKey ? '01' : '02' }}</span>
            <div><h3>定义指标</h3><p>名称用于页面展示，英文标识用于方案长期引用，保存后不可修改。</p></div>
          </header>
          <div class="indicator-editor-grid indicator-editor-grid--identity">
            <el-form-item label="中文名称" required>
              <el-input v-model="defForm.name_cn" placeholder="如 区间位置" />
            </el-form-item>
            <el-form-item label="英文标识" required>
              <el-input v-model="defForm.key" :disabled="!!editingKey" placeholder="如 range_position" />
            </el-form-item>
          </div>
          <div class="indicator-editor-grid indicator-editor-grid--meta">
            <el-form-item :label="!editingKey && defMode === 'template' ? '结果类型（模板已设定）' : '结果类型'" required>
              <el-radio-group
                v-model="defForm.dtype"
                :disabled="semanticLocked || (!editingKey && defMode === 'template')"
                @change="defPreview = null"
              >
                <el-radio-button value="number">数值</el-radio-button>
                <el-radio-button value="bool">成立 / 不成立</el-radio-button>
              </el-radio-group>
            </el-form-item>
            <el-form-item label="分类">
              <AppFilterSelect
                v-model="defForm.categories"
                :options="categoryOptions"
                :clearable="false"
                :visible-tag-count="3"
                allow-create
                default-first-option
                placeholder="选择或输入分类"
              />
            </el-form-item>
            <el-form-item label="计算周期">
              <el-tag
                size="small"
                effect="plain"
                data-testid="indicator-definition-calculation-period"
              >
                {{ indicatorDefinitionPeriodLabel }}
              </el-tag>
            </el-form-item>
          </div>
          <el-form-item v-if="editingKey || defMode === 'dsl'" label="计算公式" required>
            <el-input
              v-model="defForm.expression"
              type="textarea"
              :rows="4"
              :disabled="semanticLocked"
              placeholder="输入计算公式"
              class="indicator-formula-input"
              @input="defPreview = null"
            />
            <div class="indicator-formula-help">
              <span>示例：(C / REF(C, {window}) - 1) * 100</span>
              <span>C/O/H/L/V/TURN：收开高低、成交量、换手率</span>
              <span>MA、HHV、LLV、REF、COUNT、SUM、ABS：安全函数</span>
              <span>{参数名}：引用下方计算参数</span>
            </div>
          </el-form-item>
          <div v-else-if="defForm.expression" class="indicator-formula-preview">
            <span>模板生成的计算公式</span><code>{{ defForm.expression }}</code>
          </div>
          <el-form-item label="计算参数" class="indicator-param-form-item">
            <IndicatorParamSchemaEditor
              v-model="defForm.params"
              :disabled="semanticLocked"
              @update:model-value="resetPreviewValues"
            />
          </el-form-item>
          <el-form-item label="说明与用法">
            <el-input v-model="defForm.desc" type="textarea" :rows="2" placeholder="说明指标含义和用法" />
          </el-form-item>
        </section>

        <section class="indicator-editor-section indicator-editor-section--preview">
          <header class="indicator-editor-section__head">
            <span>{{ editingKey ? '02' : '03' }}</span>
            <div><h3>用真实行情验证</h3><p>选择一只代表性股票，确认公式能得到符合预期的结果后再保存。</p></div>
          </header>
          <div class="indicator-preview-controls">
            <el-input v-model="previewCode" placeholder="如 600000.SH" class="app-control-width-long" />
            <TradeDatePicker v-model="defPreviewDate" placeholder="默认最新交易日" class="app-control-width-medium" />
            <IndicatorParamFields v-model="previewValues" :params="defForm.params" :disabled="semanticLocked" />
            <el-button type="primary" :loading="defPreviewing" :disabled="semanticLocked" @click="runDefPreview">验证计算</el-button>
          </div>
          <AppStateBlock
            v-if="defPreview && defPreview.status !== 'ok'"
            state="empty"
            size="compact"
            title="这次验证没有得到有效结果"
            :description="defPreview.reason"
          />
          <div v-else-if="defPreview" class="indicator-preview-result">
            <span>{{ defPreview.code }} · {{ defPreview.trade_date }}</span>
            <code>{{ defPreview.rendered_expression }}</code>
            <b>结果：{{ defPreview.value }}</b>
          </div>
          <AppStatusNotice
            v-else
            title="等待验证"
            description="填写股票代码并点击“验证计算”，结果会显示在这里。"
            size="compact"
          />
          <div v-if="defReferences?.count" class="indicator-reference-summary">
            当前被 {{ defReferences.count }} 个方案版本引用，关联 {{ defReferences.backtest_count }} 条回测。
          </div>
        </section>
      </el-form>
      <template #footer>
        <el-button @click="defDrawer = false">取消</el-button>
        <el-button v-permission="'indicator:def-manage'" type="primary" :loading="defSaving" :disabled="!indicatorFormChanged" @click="submitNewDef">保存指标</el-button>
      </template>
    </AppDetailDrawer>

    <PageSettingsDrawer
      v-model="settingsOpen"
      :title="pageTitle"
      :dirty="isDirty || layoutDirty"
      :page-key="configPageKey"
      :config="drawerConfig"
      :component-meta-overrides="configPanelMetaOverrides"
      :component-runtime-value-of="componentRuntimeValueOf"
      @reset="reset(); resetLayout()"
    >
      <template v-if="activeTab === 'score'" #business>
        <PageSettingSection title="行情口径">
          <PageSettingItem label="复权模式">
            <PageSegmented v-model="settingsAdjustMode" aria-label="复权模式" :options="[
              { label: '不复权', value: '' },
              { label: '前复权', value: 'qfq' },
              { label: '后复权', value: 'hfq' },
            ]" />
          </PageSettingItem>
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
.sys-tab-toolbar {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--app-space-3);
  margin-bottom: var(--app-space-3);
}
.sys-alerts {
  flex: 1 1 auto;
  min-width: 0;
}
.sys-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--app-space-2);
  flex: none;
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
.page-head { display: flex; justify-content: space-between; align-items: flex-start; gap: var(--app-space-3); }
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
.editor {
  flex: 1;
  min-width: 0;
}
.editor-score {
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.editor-score > .ed-head {
  margin-bottom: var(--app-space-3);
}
.score-profile-options {
  align-self: flex-start;
  min-height: var(--app-control-height-md);
  margin-bottom: var(--app-space-3);
  display: inline-flex;
  align-items: center;
  gap: var(--app-space-3);
  flex-wrap: wrap;
}
.score-profile-option-label {
  display: inline-flex;
  align-items: center;
  gap: var(--app-space-control-gap);
  color: var(--el-text-color-regular);
  font-size: var(--app-font-size-table);
  font-weight: var(--app-font-weight-medium);
  line-height: var(--app-line-height-table);
  white-space: nowrap;
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
  background: var(--app-section-bg);
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
.band-box > .el-button.is-link {
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
  margin: var(--app-space-5) 0 var(--app-space-3);
}
.run-table-wrap {
  flex: 1 1 auto;
  display: flex;
  flex-direction: column;
}
.run-title {
  font-weight: var(--app-font-weight-section);
  font-size: var(--app-font-size-section-title);
}
.subchip {
  display: inline-block;
  background: var(--app-section-bg);
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
.tech-pane {
  flex-direction: column;
  gap: var(--app-space-3);
  min-height: 0;
}
.tech-filter-card {
  flex: none;
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
  background: var(--app-section-bg);
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
:global(.indicator-definition-form) {
  display: grid;
  min-width: 0;
  gap: var(--app-space-5);
}
:global(.indicator-editor-section) {
  display: grid;
  min-width: 0;
  gap: var(--app-space-4);
}
:global(.indicator-editor-section + .indicator-editor-section) {
  padding-top: var(--app-space-5);
  border-top: 1px solid var(--el-border-color-lighter);
}
:global(.indicator-editor-section__head) {
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr);
  gap: var(--app-space-3);
  align-items: start;
}
:global(.indicator-editor-section__head > span) {
  display: grid;
  width: 34px;
  height: 34px;
  place-items: center;
  border: 1px solid var(--el-color-primary-light-5);
  border-radius: 50%;
  color: var(--el-color-primary);
  font-family: var(--app-font-family-mono);
  font-size: var(--app-font-size-caption);
  font-weight: var(--app-font-weight-strong);
}
:global(.indicator-editor-section__head h3) {
  margin: 0;
  color: var(--el-text-color-primary);
  font-size: var(--app-font-size-section-title);
  line-height: var(--app-line-height-section-title);
}
:global(.indicator-editor-section__head p) {
  margin: var(--app-space-1) 0 0;
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
  line-height: var(--app-line-height-comfy);
}
:global(.indicator-create-mode) { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--app-space-3); }
:global(.indicator-create-mode .el-radio-button) { width: 100%; }
:global(.indicator-create-mode .el-radio-button__inner) {
  display: grid;
  width: 100%;
  height: auto;
  min-height: 68px;
  padding: var(--app-space-3) var(--app-space-4);
  justify-items: start;
  border: 1px solid var(--el-border-color-light) !important;
  border-radius: var(--app-radius-card) !important;
  box-shadow: none !important;
  text-align: left;
}
:global(.indicator-create-mode .el-radio-button__inner b) { color: var(--el-text-color-primary); font-size: var(--app-font-size-body); }
:global(.indicator-create-mode .el-radio-button__inner small) { margin-top: var(--app-space-1); color: var(--el-text-color-secondary); }
:global(.indicator-create-mode .el-radio-button.is-active .el-radio-button__inner) {
  border-color: var(--el-color-primary) !important;
  background: var(--el-bg-color) !important;
  color: var(--el-color-primary) !important;
}
:global(.indicator-template-grid) {
  display: flex;
  flex-wrap: wrap;
  gap: var(--app-space-3);
}
:global(.indicator-template-grid .el-button) {
  --app-interaction-card-border: var(--el-border-color-light);
  display: grid;
  width: min(var(--app-control-width-long), 100%);
  flex: 0 1 var(--app-control-width-long);
  height: auto;
  min-height: 80px;
  margin: 0;
  padding: var(--app-space-3);
  justify-items: start;
  border-color: var(--el-border-color-light);
  white-space: normal;
  text-align: left;
}
:global(.indicator-template-grid .el-button > span) {
  display: grid;
  justify-items: start;
  white-space: normal;
}
:global(.indicator-template-grid .el-button > span > b) { color: var(--el-text-color-primary); font-size: var(--app-font-size-body); }
:global(.indicator-template-grid .el-button > span > span) {
  margin-top: var(--app-space-2);
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
  line-height: var(--app-line-height-comfy);
}
:global(.indicator-editor-grid) { display: grid; gap: var(--app-space-4); }
:global(.indicator-editor-grid--identity) { grid-template-columns: repeat(2, minmax(0, 1fr)); }
:global(.indicator-editor-grid--meta) {
  grid-template-columns: minmax(280px, 1.3fr) minmax(180px, 1fr) max-content;
}
:global(.indicator-definition-form .el-form-item) { margin: 0; }
:global(.indicator-definition-form .el-form-item__label) {
  color: var(--el-text-color-regular);
  font-weight: var(--app-font-weight-section);
}
:global(.indicator-formula-input textarea),
:global(.indicator-formula-preview code),
:global(.indicator-preview-result code) { font-family: var(--app-font-family-mono); }
:global(.indicator-formula-help) {
  display: flex;
  width: 100%;
  flex-wrap: wrap;
  gap: var(--app-space-1) var(--app-space-4);
  margin-top: var(--app-space-2);
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
}
:global(.indicator-formula-preview) {
  display: grid;
  gap: var(--app-space-2);
  padding: var(--app-space-3) var(--app-space-4);
  border-left: 3px solid var(--el-color-primary);
  background: var(--app-section-bg);
}
:global(.indicator-formula-preview span) { color: var(--el-text-color-secondary); font-size: var(--app-font-size-caption); }
:global(.indicator-formula-preview code) { color: var(--el-text-color-primary); overflow-wrap: anywhere; }
:global(.indicator-param-form-item .el-form-item__content) { display: block; }
:global(.indicator-editor-section--preview) {
  padding: var(--app-space-4);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: var(--app-radius-card);
  background: var(--app-section-bg);
}
:global(.indicator-preview-controls) {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--app-space-2);
}
:global(.indicator-preview-result) {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  gap: var(--app-space-3);
  align-items: center;
  padding: var(--app-space-3);
  border: 1px solid var(--el-color-success-light-7);
  border-radius: var(--app-radius-card);
  background: var(--el-color-success-light-9);
}
:global(.indicator-preview-result code) { overflow-wrap: anywhere; }
:global(.indicator-reference-summary) {
  margin-top: var(--app-space-3);
  color: var(--el-color-warning-dark-2);
}
@container app-viewport (max-width: 760px) {
  :global(.indicator-create-mode),
  :global(.indicator-editor-grid--identity),
  :global(.indicator-editor-grid--meta) { grid-template-columns: 1fr; }
  :global(.indicator-template-grid .el-button) {
    width: 100%;
    flex-basis: 100%;
  }
}
.cond-block {
  margin: var(--app-space-3) 0;
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
@container app-viewport (max-width: 980px) {
  .sys-tab-toolbar {
    align-items: stretch;
    flex-direction: column;
  }
  .sys-actions {
    justify-content: flex-start;
  }
  .sys-grid {
    grid-template-columns: 1fr;
  }
}
</style>
