<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
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
import AssetProfileLabel from '@/components/AssetProfileLabel.vue'
import AppDataTable from '@/components/AppDataTable.vue'
import TradeDatePicker from '@/components/TradeDatePicker.vue'
import PageSettingSection from '@/components/PageSettingSection.vue'
import PageSettingsDrawer from '@/components/PageSettingsDrawer.vue'
import PageSettingsTrigger from '@/components/PageSettingsTrigger.vue'
import PageToggleRow from '@/components/PageToggleRow.vue'
import ConfigGroupForm from '@/components/config/ConfigGroupForm.vue'
import { usePageSettings } from '@/composables/usePageSettings'
import { useTableSort } from '@/composables/useTableSort'
import { getSettingsView, saveSettings, type SettingGroup } from '@/api/data'
import LayoutHost from '@/layout/components/LayoutHost.vue'
import { getPageLayout } from '@/layout'
import { useRemoteLayoutConfig } from '@/composables/useRemoteLayoutConfig'
import { useAuthStore } from '@/stores/auth'
import { hasPermission } from '@/utils/permission'

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

// ── 系统设置（FR-DM-12：真实参数 Web 可编辑，写 app_config 覆盖层）──
const sysGroups = ref<SettingGroup[]>([])
const sysDraft = ref<Record<string, unknown>>({})
const sysLoading = ref(false)
const sysSaving = ref(false)
const sysSaveError = ref(false)
const activeSysTab = ref('security')
interface SystemGroupTab {
  key: string
  label: string
  groups: SettingGroup[]
}
const SYSTEM_GROUP_TABS = [
  { key: 'security', label: '认证与审计', groupKeys: ['auth', 'audit'] },
  { key: 'data', label: '数据采集', groupKeys: ['datasource'] },
  { key: 'strategy', label: '股票池与回测', groupKeys: ['universe', 'cost', 'topn'] },
]
const canManageSystemSettings = computed(() =>
  hasPermission(auth.role, auth.permissions, 'data-settings:manage'),
)
async function loadSystem() {
  if (!canManageSystemSettings.value) return
  sysLoading.value = true
  sysSaveError.value = false
  try {
    const { groups } = await getSettingsView()
    sysGroups.value = groups
    const d: Record<string, unknown> = {}
    groups.forEach((g) => g.fields.forEach((f) => { d[f.path] = f.value }))
    sysDraft.value = d
  } finally { sysLoading.value = false }
}
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
  const tabs = SYSTEM_GROUP_TABS.map((tab) => ({
    key: tab.key,
    label: tab.label,
    groups: tab.groupKeys.map((key) => groupsByKey.get(key)).filter((group): group is SettingGroup => !!group),
  })).filter((tab) => tab.groups.length)
  const used = new Set(SYSTEM_GROUP_TABS.flatMap((tab) => tab.groupKeys))
  const extra = sysGroups.value.filter((group) => !used.has(group.key))
  if (extra.length) tabs.push({ key: 'other', label: '其他', groups: extra })
  return tabs
})
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
watch(() => sysTabs.value.map((tab) => tab.key).join('|'), () => {
  if (!sysTabs.value.some((tab) => tab.key === activeSysTab.value)) {
    activeSysTab.value = sysTabs.value[0]?.key || 'security'
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
const profiles = ref<ScoreProfileSummary[]>([])
const profilesLoading = ref(false)
const profilesError = ref(false)
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
const canEditProfileVisibility = computed(() =>
  !!curRef.value && !isNew.value && !profileReadonly.value && (canPublishTenant.value || canPublishPublic.value),
)
const weightSum = computed(() =>
  Math.round(items.value.reduce((s, it) => s + (it.weight || 0), 0) * 100),
)

async function loadProfiles() {
  profilesLoading.value = true
  profilesError.value = false
  try {
    profiles.value = await listScoreProfiles()
  } catch (e) {
    profilesError.value = true
    throw e
  } finally {
    profilesLoading.value = false
  }
}

async function selectProfile(profileKey: string) {
  const p = await getScoreProfile(profileKey)
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

// 确保评分项的 params 含该指标全部参数（补默认值），供参数输入框绑定
function ensureParams(item: ScoreItem) {
  if (!item.params) item.params = {}
  const def = defOf(item.indicator)
  for (const p of def?.params ?? []) {
    if (item.params[p.name] === undefined) item.params[p.name] = p.default
  }
}

function newProfile() {
  curRef.value = ''
  curId.value = ''
  curVersion.value = null
  editId.value = ''
  editName.value = ''
  items.value = []
  profileReadonly.value = false
  profileVisibility.value = 'private'
  isNew.value = true
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
    await loadProfiles()
    const saved = profiles.value.find((p) => p.id === r.id && p.source === 'mine')
    if (saved) curRef.value = saved.profile_ref || saved.id
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
  await loadProfiles()
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
  visibilitySaving.value = true
  try {
    const p = await setScoreProfileVisibility(curRef.value, visibility)
    profileVisibility.value = p.visibility || visibility
    ElMessage.success(visibility === 'private' ? '已设为私有' : '公开设置已更新')
    await loadProfiles()
  } finally {
    visibilitySaving.value = false
  }
}

function nextCopyProfileId(base: string): string {
  const root = (base || 'score').replace(/[^\w-]/g, '_') || 'score'
  const mineIds = new Set(profiles.value.filter((p) => p.source === 'mine').map((p) => p.id))
  let id = `${root}_copy`
  let seq = 2
  while (mineIds.has(id)) {
    id = `${root}_copy_${seq}`
    seq += 1
  }
  return id
}

async function copyCurrentScoreProfile() {
  if (!curRef.value) return
  const id = nextCopyProfileId(curId.value)
  await copyScoreProfile(curRef.value, { id, name: `${editName.value || '评分方案'} 副本` })
  ElMessage.success('已复制为我的方案')
  await loadProfiles()
  const copied = profiles.value.find((p) => p.id === id && p.source === 'mine')
  if (copied) await selectProfile(copied.profile_ref || copied.id)
}

// ── 试算 ──
const runDate = ref<string>('')
const runRows = ref<ScoreRunRow[]>([])
const running = ref(false)
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
  try {
    const res = await runScoreProfile({
      items: items.value,
      run_date: runDate.value || undefined,
      top: 30,
    })
    runRows.value = res.list
    runDate.value = res.run_date
    if (!res.list.length) ElMessage.info('无结果（可能该日无数据）')
  } finally {
    running.value = false
  }
}

// ════════════ 买卖指标方案 ════════════
import {
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
const tProfilesLoading = ref(false)
const tProfilesError = ref(false)
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
const canEditTradeVisibility = computed(() =>
  !!tCurRef.value && !tIsNew.value && !tReadonly.value && (canTradePublishTenant.value || canTradePublishPublic.value),
)
function tradeProfileKey(p: TradeProfileSummary): string {
  return p.profile_ref || p.id
}
async function loadTradeProfiles() {
  tProfilesLoading.value = true
  tProfilesError.value = false
  try {
    tProfiles.value = await listTradeProfiles()
  } catch (e) {
    tProfilesError.value = true
    throw e
  } finally {
    tProfilesLoading.value = false
  }
}
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

async function selectTradeProfile(pid: string) {
  const p = await getTradeProfile(pid)
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
}
function newTradeProfile() {
  tCurRef.value = ''
  tCurId.value = ''; tCurVersion.value = null; tEditId.value = ''; tEditName.value = ''; tIsNew.value = true
  tReadonly.value = false
  tVisibility.value = 'private'
  buyLogic.value = 'AND'; buyConds.value = []
  sellLogic.value = 'OR'; sellConds.value = []
  backstop.value = { tp: null, sl: null, hold: null }
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
    await loadTradeProfiles()
    const saved = tProfiles.value.find((p) => p.id === r.id && p.source === 'mine')
    tCurRef.value = saved ? tradeProfileKey(saved) : r.id
  } catch { /* 拦截器已提示 */ } finally { tSaving.value = false }
}
async function removeTrade() {
  if (!tCurRef.value || tReadonly.value) return
  await ElMessageBox.confirm(`确认删除买卖方案「${tEditName.value}」？`, '提示', { type: 'warning' })
  await deleteTradeProfile(tCurRef.value)
  ElMessage.success('已删除'); newTradeProfile(); await loadTradeProfiles()
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
  tVisibilitySaving.value = true
  try {
    const p = await setTradeProfileVisibility(tCurRef.value, visibility)
    tVisibility.value = p.visibility || visibility
    ElMessage.success(visibility === 'private' ? '已设为私有' : '公开设置已更新')
    await loadTradeProfiles()
  } finally {
    tVisibilitySaving.value = false
  }
}
function nextCopyTradeId(base: string): string {
  const root = (base || 'trade').replace(/[^\w-]/g, '_') || 'trade'
  const mineIds = new Set(tProfiles.value.filter((p) => p.source === 'mine').map((p) => p.id))
  let id = `${root}_copy`
  let seq = 2
  while (mineIds.has(id)) {
    id = `${root}_copy_${seq}`
    seq += 1
  }
  return id
}
async function copyCurrentTradeProfile() {
  if (!tCurRef.value) return
  const id = nextCopyTradeId(tCurId.value)
  await copyTradeProfile(tCurRef.value, { id, name: `${tEditName.value || '买卖方案'} 副本` })
  ElMessage.success('已复制为我的方案')
  await loadTradeProfiles()
  const copied = tProfiles.value.find((p) => p.id === id && p.source === 'mine')
  if (copied) await selectTradeProfile(tradeProfileKey(copied))
}

const previewHit = ref<{ buy: number | null; sell: number | null }>({ buy: null, sell: null })
const previewing = ref('')
async function previewSide(side: 'buy' | 'sell') {
  const conds = condListOf(side).value
  if (!conds.length) { ElMessage.warning('该侧无条件'); return }
  previewing.value = side
  try {
    const logic = side === 'buy' ? buyLogic.value : sellLogic.value
    const res = await previewConditions({ tree: toTree(logic, conds), top: 10 })
    previewHit.value[side] = res.hit
    ElMessage.success(`${side === 'buy' ? '买入' : '卖出'}条件今日命中 ${res.hit} 只`)
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

async function initScorePage() {
  await withInitialRetry(async () => {
    await loadProfiles()
    if (profiles.value.length) await selectProfile(profiles.value[0].profile_ref || profiles.value[0].id)
    else newProfile()
  })
}

async function initTradePage() {
  await withInitialRetry(async () => {
    await loadTradeProfiles()
    if (tProfiles.value.length) await selectTradeProfile(tradeProfileKey(tProfiles.value[0]))
    else newTradeProfile()
  })
}

async function retryScoreProfiles() {
  try {
    await initScorePage()
  } catch (e) {
    console.error('[config] 评分方案重试失败', e)
  }
}

async function retryTradeProfiles() {
  try {
    await initTradePage()
  } catch (e) {
    console.error('[config] 买卖方案重试失败', e)
  }
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
      <h2 class="page-title">{{ pageTitle }}</h2>
      <div class="page-head-actions">
        <PageSettingsTrigger :dirty="isDirty || layoutDirty" @click="settingsOpen = true" />
      </div>
    </div>
    </template>

    <template #main>
    <div class="config-body">
    <el-result
      v-if="pageInitError"
      icon="warning"
      title="配置数据加载失败"
      sub-title="权限、菜单或指标目录尚未就绪，请重试"
      class="config-error"
    >
      <template #extra>
        <el-button type="primary" @click="initActivePage()">重试</el-button>
      </template>
    </el-result>
    <div v-else-if="!pageReady" class="config-loading">正在加载配置数据…</div>
    <template v-else>
      <!-- ============ 评分规则 ============ -->
      <template v-if="activeTab === 'score'">
        <div class="score-layout pane-fill">
          <!-- 方案列表 -->
          <aside class="prof-list" v-loading="profilesLoading">
            <el-button type="primary" plain size="small" style="width: 100%" @click="newProfile">
              ＋ 新建方案
            </el-button>
            <el-result v-if="profilesError" icon="warning" title="方案加载失败" class="profile-error">
              <template #extra>
                <el-button type="primary" size="small" @click="retryScoreProfiles">重试</el-button>
              </template>
            </el-result>
            <ul>
              <li
                v-for="p in profiles"
                :key="p.profile_ref || p.id"
                :class="{ active: (p.profile_ref || p.id) === curRef }"
                @click="selectProfile(p.profile_ref || p.id)"
              >
                <AssetProfileLabel
                  :name="p.name"
                  :version="p.version"
                  :source="p.is_preset ? 'preset' : p.source"
                  :is-preset="p.is_preset"
                  :owner-label="p.owner_label"
                  :readonly="p.readonly"
                />
              </li>
            </ul>
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

            <p class="hint">
              每个指标产出 0~100 达标分（布尔=满足100/否0；数值按阈值映射），按权重百分比加权 →
              综合分。调一个权重，其余自动按比例重分配保持 100%。
            </p>

            <el-table :data="items" size="small" border class="item-table">
              <el-table-column label="指标" width="186">
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
              </el-table-column>

              <el-table-column label="打分方式" width="320">
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
                        <el-button link type="danger" :disabled="profileReadonly" @click="removeBand(row, bi)">✕</el-button>
                      </div>
                      <el-button link type="primary" size="small" :disabled="profileReadonly" @click="addBand(row)">＋ 段</el-button>
                    </div>
                  </div>
                </template>
              </el-table-column>

              <el-table-column label="权重">
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
              </el-table-column>

              <el-table-column width="50">
                <template #default="{ $index }">
                  <el-button link type="danger" :disabled="profileReadonly" @click="removeItem($index)">删</el-button>
                </template>
              </el-table-column>
            </el-table>

            <el-button size="small" plain style="margin-top: 8px" :disabled="profileReadonly" @click="addItem">＋ 添加指标</el-button>

            <!-- 试算 -->
            <div class="run-head">
              <span class="run-title">试算榜单</span>
              <el-tag v-if="runRows.length" type="info" size="small" round>共 {{ runRows.length }} 只</el-tag>
              <TradeDatePicker v-model="runDate" />
              <el-button v-permission="'score:run'" :loading="running" type="success" plain @click="tryRun">▶ 用当前配置试算</el-button>
            </div>
            <div v-if="settings.previewExpanded && runRows.length" class="run-table-wrap">
            <el-table :data="runRows" size="small" border height="100%" class="run-table">
              <el-table-column label="#" width="46">
                <template #default="{ row }">{{ row.rank }}</template>
              </el-table-column>
              <el-table-column prop="code" label="代码" width="100" />
              <el-table-column prop="name" label="名称" width="110" />
              <el-table-column label="综合分" width="90">
                <template #default="{ row }"><b style="color: #d92626">{{ row.total_score }}</b></template>
              </el-table-column>
              <el-table-column label="评级" width="104">
                <template #default="{ row }">
                  <el-tag v-if="row.grade" :type="gradeType(row.grade)" size="small" effect="light">
                    {{ row.grade }}
                  </el-tag>
                  <span v-else>—</span>
                </template>
              </el-table-column>
              <el-table-column label="分项达标分" min-width="300">
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
              </el-table-column>
            </el-table>
            </div>
          </section>
        </div>
      </template>

      <!-- ============ 技术指标 ============ -->
      <template v-else-if="activeTab === 'tech'">
        <div class="pane-fill tech-pane">
        <div class="tech-head">
          <p class="hint" style="margin: 0">
            技术指标定义（动态实时计算,无指标值表）。系统内置不可删仅可启停;自定义=一段带参数的表达式,
            供评分/筛选/买卖引用。表达式函数:MA/HHV/LLV/REF/COUNT/SUM/ABS,变量:C/O/H/L/V/TURN。
            分类可多选/自定义命名（直接输入新名回车即可）。
          </p>
          <div class="tech-actions">
            <el-input v-model="techSearch" placeholder="搜索名称/标识/说明/分类" clearable size="small" style="width: 220px" />
            <el-button v-permission="'indicator:def-manage'" type="primary" plain size="small" @click="openNewDef">＋ 新建自定义指标</el-button>
          </div>
        </div>
        <div class="tech-table-wrap">
        <AppDataTable :data="techRows" size="small" border
                  :default-sort="techDefaultSort" @sort-change="onTechSortChange">
          <el-table-column prop="name_cn" label="名称" width="130" sortable="custom" />
          <el-table-column prop="key" label="标识" width="120" />
          <el-table-column prop="catOrder" label="分类" width="280" sortable="custom">
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
          </el-table-column>
          <el-table-column prop="typeLabel" label="类型" width="74" sortable="custom" />
          <el-table-column prop="srcLabel" label="来源" width="88" sortable="custom">
            <template #default="{ row }">
              <el-tag :type="row.is_builtin ? 'info' : 'warning'" size="small" effect="plain">
                {{ row.srcLabel }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="hasParams" label="有无参数" width="100" sortable="custom">
            <template #default="{ row }">
              <span v-if="!row.params.length" class="tip">无</span>
              <span v-else>
                <span v-for="p in row.params" :key="p.name" class="subchip">{{ p.label }}({{ p.default }})</span>
              </span>
            </template>
          </el-table-column>
          <el-table-column label="计算 / 表达式" min-width="170">
            <template #default="{ row }">
              <code v-if="row.expression" class="expr">{{ row.expression }}</code>
              <span v-else class="tip">系统内置·代码向量化计算（无 DSL 表达式）</span>
            </template>
          </el-table-column>
          <el-table-column label="说明 / 用法" min-width="280">
            <template #default="{ row }">
              <span class="usage">{{ row.desc || '—' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="启用" width="64">
            <template #default="{ row }">
              <el-switch v-permission="'indicator:def-manage'" :model-value="row.enabled" size="small" @change="toggleEnabled(row)" />
            </template>
          </el-table-column>
          <el-table-column label="操作" width="60">
            <template #default="{ row }">
              <el-button v-permission="'indicator:def-manage'" v-if="!row.is_builtin" link type="danger" @click="removeDef(row)">删</el-button>
              <span v-else>—</span>
            </template>
          </el-table-column>
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
                  <el-button link type="danger" @click="removeDefParam(i)">✕</el-button>
                </div>
                <el-button link type="primary" size="small" @click="addDefParam">＋ 参数</el-button>
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
          <aside class="prof-list" v-loading="tProfilesLoading">
            <el-button type="primary" plain size="small" style="width: 100%" @click="newTradeProfile">
              ＋ 新建方案
            </el-button>
            <el-result v-if="tProfilesError" icon="warning" title="方案加载失败" class="profile-error">
              <template #extra>
                <el-button type="primary" size="small" @click="retryTradeProfiles">重试</el-button>
              </template>
            </el-result>
            <ul>
              <li v-for="p in tProfiles" :key="tradeProfileKey(p)" :class="{ active: tradeProfileKey(p) === tCurRef }"
                  @click="selectTradeProfile(tradeProfileKey(p))">
                <AssetProfileLabel
                  :name="p.name"
                  :version="p.version"
                  :source="p.is_preset ? 'preset' : p.source"
                  :is-preset="p.is_preset"
                  :owner-label="p.owner_label"
                  :readonly="p.readonly"
                />
              </li>
            </ul>
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
            <p class="hint">买入/卖出各是一组技术指标条件(且/或)。卖出以指标命中为主,止盈/止损/最大持仓为可选兜底,先到先卖。</p>

            <!-- 买入条件 -->
            <div class="cond-block">
              <div class="cond-head">
                <span class="cond-title buy">买入条件</span>
                <el-radio-group v-model="buyLogic" size="small" :disabled="tReadonly">
                  <el-radio-button value="AND">且(全满足)</el-radio-button>
                  <el-radio-button value="OR">或(任一)</el-radio-button>
                </el-radio-group>
                <el-button v-permission="'trade-profile:preview'" size="small" :loading="previewing === 'buy'" @click="previewSide('buy')">▶ 试算</el-button>
                <el-tag v-if="previewHit.buy !== null" type="success" size="small" round>今日命中 {{ previewHit.buy }} 只</el-tag>
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
                <el-button link type="danger" :disabled="tReadonly" @click="removeCond('buy', i)">删</el-button>
              </div>
              <el-button size="small" plain :disabled="tReadonly" @click="addCond('buy')">＋ 买入条件</el-button>
            </div>

            <!-- 卖出条件 -->
            <div class="cond-block">
              <div class="cond-head">
                <span class="cond-title sell">卖出条件</span>
                <el-radio-group v-model="sellLogic" size="small" :disabled="tReadonly">
                  <el-radio-button value="AND">且(全满足)</el-radio-button>
                  <el-radio-button value="OR">或(任一)</el-radio-button>
                </el-radio-group>
                <el-button v-permission="'trade-profile:preview'" size="small" :loading="previewing === 'sell'" @click="previewSide('sell')">▶ 试算</el-button>
                <el-tag v-if="previewHit.sell !== null" type="warning" size="small" round>今日命中 {{ previewHit.sell }} 只</el-tag>
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
                <el-button link type="danger" :disabled="tReadonly" @click="removeCond('sell', i)">删</el-button>
              </div>
              <el-button size="small" plain :disabled="tReadonly" @click="addCond('sell')">＋ 卖出条件</el-button>
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
        <el-result
          v-if="!canManageSystemSettings"
          icon="warning"
          title="无权限维护系统设置"
          sub-title="系统设置仅系统管理员可编辑"
          class="config-error"
        />
        <div v-else class="sys-wrap" v-loading="sysLoading">
          <div class="sys-head">
            <div class="sys-summary">
              <span>保存后即时影响数据源、股票池、回测、榜单、认证和审计查询窗口。</span>
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
                  :model-value="sysDraft"
                  :disabled="sysSaving"
                  :invalid-paths="sysInvalidPaths"
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
          <el-button text type="primary" size="small" @click="restoreScoreVersion(v)">载入此版本</el-button>
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
          <el-button text type="primary" size="small" @click="restoreTradeVersion(v)">载入此版本</el-button>
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
  gap: 14px;
}
.sys-head {
  position: sticky;
  top: 0;
  z-index: 2;
  flex: 0 0 auto;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 4px 0 12px;
  background: var(--el-bg-color-page);
}
.sys-summary {
  min-width: 0;
}
.sys-summary strong,
.sys-summary span {
  display: block;
}
.sys-summary strong {
  font-size: 16px;
  line-height: 1.4;
}
.sys-summary span {
  margin-top: 3px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.sys-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
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
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
  gap: 14px;
  min-width: 0;
}
.page-head { display: flex; justify-content: space-between; align-items: center; }
.config-body {
  flex: 1 1 auto;   /* 填满 LayoutHost 的 .v-grow，页面内容在本区域内滚动 */
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
  font-size: 14px;
}
.profile-error {
  padding: 12px 0;
}
.profile-error :deep(.el-result__title p) {
  font-size: 13px;
}
.setting-item { display: flex; flex-direction: column; gap: 8px; }
.setting-label { font-size: 14px; color: var(--page-settings-text-subtle); }
.page-title {
  margin: 0;
  font-size: 20px;
}
.hint {
  color: var(--el-text-color-secondary);
  font-size: 13px;
  margin: 4px 0 12px;
}
.score-layout {
  display: flex;
  gap: 16px;
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
  font-size: 14px;
  margin-bottom: 4px;
}
.prof-list li:hover {
  background: var(--el-fill-color-light);
}
.prof-list li.active {
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
  font-weight: 600;
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
  gap: 10px;
}
.spacer {
  flex: 1;
}
.ver-badge {
  font-size: 12px;
  color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
  border-radius: 10px;
  padding: 1px 8px;
  font-weight: 600;
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
  font-size: 12px;
}
.mono {
  font-family: var(--el-font-family-mono, monospace);
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
  gap: 10px;
}
.ast {
  margin: 8px 0 0;
  padding: 10px 12px;
  background: var(--el-fill-color-light);
  border-radius: 6px;
  font-size: 12px;
  color: var(--el-text-color-regular);
  max-height: 200px;
  overflow: auto;
  white-space: pre-wrap;
}
.wsum {
  font-size: 13px;
  color: var(--el-color-success);
  font-weight: 600;
}
.wsum.bad {
  color: var(--el-color-danger);
}
.scoring-cell {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.tip {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.linear-row,
.band-row {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
}
.band-box {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.weight-cell {
  display: flex;
  align-items: center;
  gap: 10px;
}
.wval {
  width: 42px;
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.run-head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 22px 0 10px;
}
.run-table-wrap {
  flex: 1 1 auto;
  min-height: 240px;
  display: flex;
  flex-direction: column;
}
.run-title {
  font-weight: 600;
  font-size: 15px;
}
.subchip {
  display: inline-block;
  background: var(--el-fill-color-light);
  border-radius: 4px;
  padding: 1px 6px;
  margin: 0 4px 2px 0;
  font-size: 12px;
}
.param-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 5px;
}
.param-item {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.tech-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;
  flex: none;
}
.tech-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}
.tech-pane {
  flex-direction: column;
  gap: 12px;
  min-height: 0;
}
/* 原依赖全局 .v-grow，迁移后改为页面内自带成长样式（表体内滚、表头吸顶） */
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
  font-family: var(--el-font-family-mono, monospace);
  background: var(--el-fill-color-light);
  border-radius: 4px;
  padding: 1px 6px;
  font-size: 12px;
}
.usage {
  display: block;
  font-size: 12px;
  line-height: 1.55;
  color: var(--el-text-color-regular);
  white-space: normal;
  word-break: break-word;
}
.def-params {
  display: flex;
  flex-direction: column;
  gap: 6px;
  width: 100%;
}
.def-param-row {
  display: flex;
  align-items: center;
  gap: 6px;
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
  gap: 12px;
  margin-bottom: 10px;
}
.cond-title {
  font-weight: 600;
  font-size: 14px;
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
  gap: 7px;
  margin-bottom: 7px;
  flex-wrap: wrap;
}
.backstop-row {
  display: flex;
  gap: 22px;
  margin-top: 8px;
}
.bs-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
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
  gap: 5px;
}
.subchip.score {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  white-space: nowrap;
  margin: 0;
  padding: 2px 7px;
  border-radius: 11px;
  line-height: 1.5;
}
.subchip.score i {
  font-style: normal;
  color: var(--el-text-color-secondary);
}
.subchip.score b {
  font-variant-numeric: tabular-nums;
}
.subchip.score.hi {
  background: rgba(82, 196, 26, 0.14);
}
.subchip.score.hi b {
  color: #52c41a;
}
.subchip.score.mid {
  background: rgba(250, 173, 20, 0.16);
}
.subchip.score.mid b {
  color: #d48806;
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
