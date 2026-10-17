<script setup lang="ts">
import AppHoverInfo from '@/components/AppHoverInfo'
import { useMenuPageTitle } from '@/composables/useMenuPageTitle'
import AppTableColumn from '@/components/AppTableColumn.vue'
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, VideoPlay } from '@element-plus/icons-vue'
import {
  browseProfiles,
  copyProfile,
  deleteProfile,
  getProfile,
  getProfileVersions,
  listProfiles,
  rankScreen,
  runScreen,
  saveProfile,
  setProfileVisibility,
  type Profile,
  type ProfileVersion,
  type ScreenHit,
  type ScreenResult,
} from '@/api/screening'
import {
  browseScoreProfiles,
  copyScoreProfile,
  getIndicatorRegistry,
  listScoreProfiles,
  type IndicatorDef,
  type ScoreProfileSummary,
} from '@/api/scoreProfile'
import { useAuthStore } from '@/stores/auth'
import { hasPermission } from '@/utils/permission'
import AppDetailDrawer from '@/components/AppDetailDrawer.vue'
import AppRowActions from '@/components/AppRowActions.vue'
import AppStateBlock from '@/components/AppStateBlock.vue'
import AppStatusNotice from '@/components/AppStatusNotice.vue'
import RankedStockWorkbench from '@/components/ranked-stock/RankedStockWorkbench.vue'
import type { RankedStockColumnKey } from '@/components/ranked-stock/types'
import {
  relatedBoardFirstLoadContext,
  mergeRelatedBoardResults,
  useRelatedBoardFirstLoad,
} from '@/composables/useRelatedBoardFirstLoad'
import AssetProfileSelect from '@/components/asset-search/AssetProfileSelect.vue'
import AssetVisibilityActions from '@/components/AssetVisibilityActions.vue'
import HelpTip from '@/components/HelpTip.vue'
import HelpTipItem from '@/components/HelpTipItem.vue'
import type { AssetBrowseParams, ProfileSummary } from '@/components/asset-search/types'
import PageSettingSection from '@/components/PageSettingSection.vue'
import PageSettingItem from '@/components/PageSettingItem.vue'
import PageSettingsDrawer from '@/components/PageSettingsDrawer.vue'
import PageSettingsTrigger from '@/components/PageSettingsTrigger.vue'
import PageSegmented from '@/components/PageSegmented.vue'
import PageToggleRow from '@/components/PageToggleRow.vue'
import TradeDatePicker from '@/components/TradeDatePicker.vue'
import IndicatorParamFields from '@/components/indicator/IndicatorParamFields.vue'
import IndicatorSelect from '@/components/indicator/IndicatorSelect.vue'
import StrategyItemEnabledSwitch from '@/components/strategy/StrategyItemEnabledSwitch.vue'
import { usePageSettings } from '@/composables/usePageSettings'
import { useDefaultedSessionValue } from '@/composables/useDefaultedSessionValue'
import { useRankedStockResultView } from '@/composables/useRankedStockResultView'
import {
  useStockAdjustModeSession,
  type StockAdjustMode,
} from '@/composables/useStockAnalysisSession'
import { downloadCsv } from '@/utils/csv'
import { relatedBoardExportValues } from '@/utils/relatedBoardExport'
import LayoutHost from '@/layout/components/LayoutHost.vue'
import { getPageLayout } from '@/layout'
import { useRemoteLayoutConfig } from '@/composables/useRemoteLayoutConfig'
import { useFormChangeTracker } from '@/composables/useFormChangeTracker'
import { useDefaultScoreProfile } from '@/composables/useDefaultScoreProfile'
import { useMarketMasterRatioRuntime } from '@/composables/useMarketMasterRatioRuntime'
import {
  composeComponentRuntimeValueOf,
  useStockChartComponentConfig,
} from '@/composables/useStockChartComponentConfig'
import { getApiErrorCode, getErrorMessage } from '@/utils/error'
import { formatDateTimeMinutes } from '@/utils/dateTime'
import { confirmProfileVisibilityReduction } from '@/utils/assetVisibility'
import type { AppRowAction } from '@/components/rowActions'

const route = useRoute()
const settingsOpen = ref(false)
// 排除 ST、AST 预览属业务态偏好，保留 usePageSettings；结果排序与列显隐迁入组件配置层（plan.md §13.3）。
const screenDefaults = {
  excludeSt: true,
  astExpanded: false,
  adjustMode: 'qfq' as StockAdjustMode,
}
const { settings, isDirty, reset } = usePageSettings('screen', screenDefaults)
const adjustMode = useStockAdjustModeSession(settings)

// 布局声明统一取自 pageRegistry（单一事实源），不再页面内联手写 PageLayout。
const screenLayout = getPageLayout('screen')
const {
  effective: screenEffective,
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
} = useRemoteLayoutConfig(screenLayout)

// 抽屉「布局」「组件设置」两段由 PageSettingsDrawer 按元数据自动渲染（见 pageRegistry.componentMeta）。
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

function tableBorder(slotId: string): boolean {
  return componentValueOf(slotId, 'border') === true
}

// ── 指标注册表（融合：可视化条件直接从注册表取指标，支持动态传参）──
const registry = ref<IndicatorDef[]>([])
const enabledInds = computed(() => registry.value.filter((d) => d.enabled))
function defOf(key: string): IndicatorDef | undefined {
  return registry.value.find((d) => d.key === key)
}
function indicatorName(key: string): string {
  return defOf(key)?.name_cn || key
}
// 旧预设 col 字段 → 注册表 key 的反向别名（其余字段名与 key 一致）
const COL_TO_KEY: Record<string, string> = { is_bull_arrange: 'bull_arrange', dist_to_high: 'dist_to_high_2y' }

const NUM_CMP = [
  { v: '>=', t: '≥' }, { v: '<=', t: '≤' }, { v: '>', t: '>' },
  { v: '<', t: '<' }, { v: 'between', t: '介于' },
]

// ── 统一条件行：指标行(ind) 或 表达式行(expr)，同一 AND/OR 组合 ──
interface Row {
  kind: 'ind' | 'expr'
  enabled: boolean
  // ind
  key: string
  params: Record<string, number>
  cmp: string
  value: number
  value2: number
  boolVal: boolean
  // expr
  expr: string
}
const groupOp = ref<'AND' | 'OR'>('AND')
const rows = ref<Row[]>([])
// 加载的方案含本构建器无法平铺的嵌套结构时，原样保留并只读运行
const complexAst = ref<Record<string, unknown> | null>(null)

function newIndRow(key?: string): Row {
  const k = key ?? enabledInds.value[0]?.key ?? ''
  const d = defOf(k)
  const params: Record<string, number> = {}
  ;(d?.params ?? []).forEach((p) => (params[p.name] = p.default))
  return { kind: 'ind', enabled: true, key: k, params, cmp: '>=', value: 0, value2: 0, boolVal: true, expr: '' }
}
function newExprRow(): Row {
  return { kind: 'expr', enabled: true, key: '', params: {}, cmp: '>=', value: 0, value2: 0, boolVal: true, expr: '' }
}
function addIndRow() {
  complexAst.value = null
  rows.value.push(newIndRow())
}
function addExprRow() {
  complexAst.value = null
  rows.value.push(newExprRow())
}
function removeRow(i: number) {
  rows.value.splice(i, 1)
}
function conditionRowActions(i: number): AppRowAction[] {
  return [
    {
      key: 'delete',
      label: '删除',
      type: 'danger',
      disabled: profileReadonly.value,
      onClick: () => removeRow(i),
    },
  ]
}
function onIndKey(row: Row) {
  const d = defOf(row.key)
  const params: Record<string, number> = {}
  ;(d?.params ?? []).forEach((p) => (params[p.name] = p.default))
  row.params = params
}

// ── 行 ⇄ AST 叶子 ──
function rowToLeaf(row: Row): Record<string, unknown> | null {
  if (row.kind === 'expr') {
    const e = row.expr.trim()
    return e ? { type: 'expr', expr: e, enabled: row.enabled } : null
  }
  const d = defOf(row.key)
  if (!d) return null
  const base: Record<string, unknown> = { type: 'ind', key: row.key, enabled: row.enabled }
  if ((d.params?.length ?? 0) > 0) base.params = { ...row.params }
  if (d.dtype === 'bool') {
    const leaf = { ...base, cmp: '>=', value: 1 }
    return row.boolVal ? leaf : { op: 'NOT', children: [leaf] }
  }
  if (row.cmp === 'between') return { ...base, cmp: 'between', value: [row.value, row.value2] }
  return { ...base, cmp: row.cmp, value: row.value }
}
function buildAst(): Record<string, unknown> | null {
  if (complexAst.value) return complexAst.value
  const children = rows.value.map(rowToLeaf).filter(Boolean) as Record<string, unknown>[]
  if (!children.length) return null
  return children.length === 1 ? children[0] : { op: groupOp.value, children }
}

// 把单个叶子（含 NOT 包裹的布尔指标）解析回构建器行；无法表示则返回 null
function leafToRow(node: Record<string, unknown>): Row | null {
  // NOT(单指标布尔叶子) → 布尔“不成立”
  if (node.op === 'NOT') {
    const ch = (node.children as Record<string, unknown>[]) ?? []
    if (ch.length === 1) {
      const inner = leafToRow(ch[0])
      if (inner && inner.kind === 'ind' && defOf(inner.key)?.dtype === 'bool') {
        inner.boolVal = false
        return inner
      }
    }
    return null
  }
  const t = node.type
  if (t === 'expr') {
    const r = newExprRow()
    r.expr = String(node.expr ?? '')
    r.enabled = node.enabled !== false && node.ignore !== true
    return r
  }
  if (t === 'ind' || t === 'col') {
    const key = t === 'ind' ? String(node.key) : (COL_TO_KEY[String(node.field)] ?? String(node.field))
    const d = defOf(key)
    if (!d) return null
    const r = newIndRow(key)
    r.enabled = node.enabled !== false && node.ignore !== true
    if (node.params && typeof node.params === 'object') r.params = { ...(node.params as Record<string, number>) }
    if (d.dtype === 'bool') {
      r.boolVal = node.value === true || node.value === 1
    } else {
      const cmp = String(node.cmp ?? '>=')
      if (cmp === 'between' && Array.isArray(node.value)) {
        r.cmp = 'between'
        r.value = Number((node.value as number[])[0])
        r.value2 = Number((node.value as number[])[1])
      } else {
        r.cmp = cmp
        r.value = Number(node.value ?? 0)
      }
    }
    return r
  }
  return null
}
// 把方案 AST 平铺进构建器；含嵌套分组等无法平铺时返回 null
function parseAst(ast: Record<string, unknown>): { op: 'AND' | 'OR'; rows: Row[] } | null {
  if (!ast || typeof ast !== 'object') return null
  if (ast.op === 'AND' || ast.op === 'OR') {
    const out: Row[] = []
    for (const c of (ast.children as Record<string, unknown>[]) ?? []) {
      const r = leafToRow(c)
      if (!r) return null // 含嵌套子分组 → 交给只读模式
      out.push(r)
    }
    return { op: ast.op as 'AND' | 'OR', rows: out }
  }
  const single = leafToRow(ast)
  return single ? { op: 'AND', rows: [single] } : null
}

// ── 已存/系统内置方案：载入到编辑器（R3/R5，list 形态与评分页对齐）──
// R3/R5：方案选择统一走 AssetProfileSelect——列表只加载「我的」（source=mine 纯 owner），
// 「搜索」入口打开共享搜索抽屉（系统内置/租户公开/全体公开），「加载查看」注入临时只读、
// 「复制为我的」自动刷新并选中（组件内部闭环，本页不再维护列表/复制逻辑）。
const loadedProfile = ref<Profile | null>(null)
const initLoading = ref(true)
const initError = ref('')
const profileLoading = ref(false)
const profileError = ref('')
let profileDetailSeq = 0
// 详情加载失败时的目标项（错误块重试）
let profileDetailAttempt = ''
// 最后一次成功载入编辑器的方案 ref（失败回滚的目标）
let profileLastAppliedRef = ''
const curRef = ref('')
const curId = ref('')
const curVersion = ref<number | null>(null)
const editId = ref('')
const editName = ref('')
const isNew = ref(false)
const screenSubmitPayload = () => ({
  name: editName.value.trim(),
  expression: buildAst(),
})
const {
  hasChanges: screenFormChanged,
  captureBaseline: captureScreenBaseline,
} = useFormChangeTracker(screenSubmitPayload)
const auth = useAuthStore()
const visibilitySaving = ref(false)
const profileReadonly = computed(() => !!loadedProfile.value?.readonly)
const profileVisibility = computed<'private' | 'tenant' | 'public'>(() => loadedProfile.value?.visibility || 'private')
const canPublishTenant = computed(() =>
  hasPermission(auth.role, auth.permissions, 'screen-profile:publish-tenant'),
)
const canPublishPublic = computed(() =>
  hasPermission(auth.role, auth.permissions, 'screen-profile:publish-public'),
)
const canSaveProfile = computed(() =>
  hasPermission(auth.role, auth.permissions, 'screen-profile:save'),
)
const profileSelectRef = ref<InstanceType<typeof AssetProfileSelect> | null>(null)
async function fetchMineProfiles(): Promise<Profile[]> {
  // 次级加载按自身 view 码优雅降级：无 screen-profile:view 的部分授权角色（如只授 screen:run）
  // 不拉方案列表、也不因此 403 卡住页面主体（筛选构建/运行仍可用）。默认业务角色含该码不受影响。
  if (!hasPermission(auth.role, auth.permissions, 'screen-profile:view')) return []
  return listProfiles('mine')
}
function browseScreenProfiles(params: AssetBrowseParams) {
  return browseProfiles(params)
}
function copyAnyProfile(item: ProfileSummary) {
  return copyProfile(item.profile_ref || item.id)
}

// 载入方案详情进编辑器（原子应用 + seq 竞态守卫 + 失败回滚，对齐评分页 selectProfile）。
// 成功才整体写入编辑器，保证「选中项 == 编辑器内容」不错位。
async function selectProfile(profileKey: string) {
  if (!profileKey) return
  const seq = ++profileDetailSeq
  profileDetailAttempt = profileKey
  profileLoading.value = true
  profileError.value = ''
  try {
    const p = await getProfile(profileKey)
    if (seq !== profileDetailSeq) return
    clearScreenResult()
    curRef.value = p.profile_ref || profileKey
    curId.value = p.id
    curVersion.value = p.version
    editId.value = p.id
    editName.value = p.name
    loadedProfile.value = p
    const parsed = parseAst(p.expression || {})
    if (parsed) {
      groupOp.value = parsed.op
      rows.value = parsed.rows
      complexAst.value = null
    } else {
      complexAst.value = p.expression || {} // 嵌套结构：只读运行
      rows.value = []
    }
    profileLastAppliedRef = curRef.value
    isNew.value = false
    captureScreenBaseline()
  } catch (error) {
    if (seq !== profileDetailSeq) return
    // 失败回滚到最后成功载入的项，编辑器保留旧内容（避免「选中新方案、保存到旧方案」）
    curRef.value = profileLastAppliedRef
    profileError.value = getErrorMessage(error, '筛选方案详情加载失败')
  } finally {
    if (seq === profileDetailSeq) profileLoading.value = false
  }
}
// 侧栏选择器选中变化（含「加载查看」注入的临时只读项）→ 载入编辑器
function onScreenSelect(key: string) {
  curRef.value = key
  if (!key) return
  void selectProfile(key)
}
// 列表就绪（组件为列表唯一事实源）：有方案自动选中第一个；无方案进入新建态（保留初始化默认条件）
function onScreenReady(list: ProfileSummary[]) {
  if (list.length && !curRef.value) onScreenSelect(list[0].profile_ref || list[0].id)
  else if (!list.length && !curRef.value) enterNewSession()
}
// 「加载查看」（R5/§7.0）：注入临时只读项 → 页面级载入编辑器只读展示（seq 守卫 + 失败回滚）
function onScreenLoaded(item: ProfileSummary) {
  onScreenSelect(item.profile_ref || item.id)
}
// 行内「×」只移除「加载查看」临时预览项，不删除资产；组件只会为当前 tempItem 发出此事件。
// 页面必须无条件清掉对应身份/参数/运行口径/结果，不能用 readonly 推断是否为临时项：
// 平台内置资产对其物理 owner 可能是 readonly=false，但仍属于 source=preset 的临时加载项。
async function onScreenTempRemoved(item: ProfileSummary) {
  ElMessage.info(`已移除预览的方案「${item.name}」`)
  // 先清空外部身份、条件和结果，再刷新 mine；即使刷新失败也不会残留已移除方案的参数。
  newProfile()
  await profileSelectRef.value?.reload()
}
// 进入「新建」态：清空方案身份，保留当前构建器条件（列表为空时的初始态）
function enterNewSession() {
  profileDetailSeq += 1
  curRef.value = ''
  curId.value = ''
  curVersion.value = null
  editId.value = ''
  editName.value = ''
  loadedProfile.value = null
  isNew.value = true
  profileLastAppliedRef = ''
  profileDetailAttempt = ''
  profileError.value = ''
  clearScreenResult()
  captureScreenBaseline()
}
// 「新建方案」按钮：完全清空（身份 + 条件），从空白开始
function newProfile() {
  enterNewSession()
  rows.value = []
  complexAst.value = null
  captureScreenBaseline()
}

// ── 运行 / 结果 ──
const runDate = ref('')
const excludeSt = useDefaultedSessionValue(computed(() => Boolean(settings.excludeSt)))
const loading = ref(false)
const resultError = ref('')
const result = ref<(ScreenResult & { date: string }) | null>(null)
const scoreProfileRef = ref('')
const scoreProfiles = ref<ScoreProfileSummary[]>([])
const externalScoreProfile = ref<ScoreProfileSummary | null>(null)
const scoreSelectRef = ref<InstanceType<typeof AssetProfileSelect> | null>(null)
const defaultScoreProfile = useDefaultScoreProfile()
async function fetchMineScoreProfiles(): Promise<ScoreProfileSummary[]> {
  if (!hasPermission(auth.role, auth.permissions, 'score-profile:view')) return []
  return listScoreProfiles('mine')
}
function browseScreenScoreProfiles(params: AssetBrowseParams) {
  return browseScoreProfiles(params)
}
function copyAnyScoreProfile(item: ProfileSummary) {
  return copyScoreProfile(item.profile_ref || item.id)
}
function onScoreProfileLoaded(item: ProfileSummary) {
  externalScoreProfile.value = item as ScoreProfileSummary
}
function applyInitialScoreProfile(): void {
  if (scoreProfileRef.value || !defaultScoreProfile.hydrated.value) return
  const saved = defaultScoreProfile.value
  const key = saved.profile_ref || saved.id
  if (key) {
    const mine = scoreProfiles.value.find((profile) => (profile.profile_ref || profile.id) === key)
    if (mine) scoreProfileRef.value = key
    else scoreSelectRef.value?.applyLoaded({
      id: saved.id,
      profile_ref: saved.profile_ref || undefined,
      name: saved.name,
      version: saved.version,
      is_preset: saved.is_preset,
      source: (saved.source as ProfileSummary['source']) ?? undefined,
      owner_label: saved.owner_label,
      readonly: true,
    })
  } else if (scoreProfiles.value.length) {
    scoreProfileRef.value = scoreProfiles.value[0].profile_ref || scoreProfiles.value[0].id
  }
}
function onScoreProfilesReady(items: ProfileSummary[]) {
  scoreProfiles.value = items as ScoreProfileSummary[]
  applyInitialScoreProfile()
}
watch(defaultScoreProfile.hydrated, applyInitialScoreProfile)

let rankSequence = 0
async function onScoreProfileSelect(key: string) {
  scoreProfileRef.value = key
  if (externalScoreProfile.value
    && (externalScoreProfile.value.profile_ref || externalScoreProfile.value.id) !== key) {
    externalScoreProfile.value = null
  }
  if (!result.value?.candidate_codes.length || !key) return
  const sequence = ++rankSequence
  loading.value = true
  resultError.value = ''
  try {
    const reranked = await rankScreen({
      run_date: result.value.run_date,
      score_profile_id: key,
      codes: result.value.candidate_codes,
      exclude_st: excludeSt.value,
    })
    if (sequence !== rankSequence) return
    result.value = { ...reranked, date: reranked.run_date }
  } catch (error) {
    if (sequence !== rankSequence) return
    const defaultKey = defaultScoreProfile.value.profile_ref || defaultScoreProfile.value.id
    if (key === defaultKey && getApiErrorCode(error) === 404) defaultScoreProfile.reset()
    const previousKey = result.value?.score_profile_ref
    if (previousKey) scoreProfileRef.value = previousKey
    resultError.value = getErrorMessage(error, '切换评分方案失败，已保留原评分结果')
    ElMessage.error(resultError.value)
  } finally {
    if (sequence === rankSequence) loading.value = false
  }
}
function onSetScreenScoreDefault(item: ProfileSummary | null) {
  defaultScoreProfile.setDefault(item)
  if (item) ElMessage.success(`已将「${item.name}」设为默认评分方案`)
  else ElMessage.info('已取消默认评分方案')
}
function clearScreenResult() {
  result.value = null
  resultError.value = ''
}
const resultSubKeys = computed(() => (
  result.value?.hits[0] ? Object.keys(result.value.hits[0].sub_scores || {}) : []
))
const resultColumnKeys = computed<RankedStockColumnKey[]>(() => [
  'rank',
  'code', 'name', 'board', 'relatedIndustry', 'relatedConcept', 'score', 'grade',
  ...(resultSubKeys.value.length ? ['subScores' as const] : []),
])
const {
  rows: displayHits,
  columns: resultColumns,
  columnVisible: colVisible,
  onSortChange: onResultSortChange,
} = useRankedStockResultView({
  rows: () => result.value?.hits ?? [],
  columnKeys: resultColumnKeys,
  componentValueOf,
})

let runSequence = 0
async function runScreenResults(background = false) {
  const ast = buildAst()
  if (!ast || (!complexAst.value && !rows.value.some((row) => row.enabled))) {
    if (!background) ElMessage.warning(ast ? '请至少启用一个条件' : '请先添加条件')
    return
  }
  if (!scoreProfileRef.value) {
    if (!background) ElMessage.warning('请先选择或加载评分方案')
    return
  }
  const sequence = ++runSequence
  if (!background) {
    loading.value = true
    resultError.value = ''
  }
  // 不清空 result：让旧结果留在 loading 遮罩下，避免闪回空态（结果区盒子保持不变）
  try {
    const r = await runScreen({
      // 只读公开态（含「加载查看」，不改选中）按所查看方案的 profile_ref 运行，保证跑的是该方案口径
      // 而非当前可能脏改的表达式；get_visible 解析 opaque ref 后后端 fail-closed 校验可见性。
      ...(profileReadonly.value && loadedProfile.value
        ? { profile_id: loadedProfile.value.profile_ref || loadedProfile.value.id }
        : { expression: ast }),
      run_date: runDate.value || undefined,
      exclude_st: excludeSt.value,
      score_profile_id: scoreProfileRef.value,
    })
    if (sequence !== runSequence) return
    if (background && result.value) mergeRelatedBoardResults(result.value.hits, r.hits)
    else result.value = { ...r, date: r.run_date }
    relatedBoardFirstLoad.observe(
      r.hits,
      relatedBoardFirstLoadContext(r.hits, r.run_date),
    )
    // 回填实际运行交易日（默认最新时让用户看到本次结果口径，与评分试算一致）
    runDate.value = r.run_date
  } catch (error) {
    if (sequence !== runSequence || background) return
    const defaultKey = defaultScoreProfile.value.profile_ref || defaultScoreProfile.value.id
    if (scoreProfileRef.value === defaultKey && getApiErrorCode(error) === 404) {
      defaultScoreProfile.reset()
      const invalidKey = scoreProfileRef.value
      const fallback = scoreProfiles.value.find(
        (profile) => (profile.profile_ref || profile.id) !== invalidKey,
      )
      scoreProfileRef.value = fallback ? (fallback.profile_ref || fallback.id) : ''
    }
    resultError.value = getErrorMessage(error, '筛选运行失败')
    ElMessage.error(resultError.value)
  } finally {
    if (!background && sequence === runSequence) loading.value = false
  }
}

function run() {
  return runScreenResults(false)
}

const relatedBoardFirstLoad = useRelatedBoardFirstLoad(() => runScreenResults(true))

// ── 保存（实质变更才版本+1；载入的自定义方案可覆盖更新；id 为空由后端自动生成）──
const saving = ref(false)
async function save() {
  if (!screenFormChanged.value) return
  if (profileReadonly.value) {
    ElMessage.warning('公开方案为只读，请先复制为自己的方案')
    return
  }
  const expr = buildAst()
  if (!editName.value.trim()) return ElMessage.warning('请填写方案名称')
  if (!expr || (!complexAst.value && !rows.value.some((row) => row.enabled))) return ElMessage.warning('请至少启用一个条件')
  saving.value = true
  try {
    const r = await saveProfile({
      id: editId.value || null,
      name: editName.value.trim(),
      expression: expr,
    })
    curVersion.value = r.version
    ElMessage.success(`已保存（v${r.version}）`)
    isNew.value = false
    editId.value = r.id
    curId.value = r.id
    captureScreenBaseline()
    // 先落到新标识再刷新列表：避免 reload→ready 在 curRef 为空时自动选中列表首项覆盖新建态
    curRef.value = r.id
    const list = await profileSelectRef.value?.reload()
    const saved = list?.find((p) => p.id === r.id)
    if (saved) curRef.value = saved.profile_ref || saved.id
  } finally {
    saving.value = false
  }
}

async function publishProfile(visibility: 'private' | 'tenant' | 'public') {
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
    editName.value || loadedProfile.value?.name || '当前方案',
    profileVisibility.value,
    visibility,
  )) return
  visibilitySaving.value = true
  try {
    loadedProfile.value = await setProfileVisibility(curRef.value, visibility)
    const affected = loadedProfile.value.affected_run_count || 0
    ElMessage.success(affected
      ? `可见性已更新，并同步收窄 ${affected} 条关联回测`
      : visibility === 'private' ? '已设为私有' : '公开设置已更新')
    await profileSelectRef.value?.reload()
  } finally {
    visibilitySaving.value = false
  }
}
// C8：复制由后端生成唯一 id、名称默认「原名 副本」，返回新标识供选中
async function copyCurrentProfile(version?: number) {
  if (!curRef.value || !loadedProfile.value) return
  const r = await copyProfile(curRef.value, version ? { version } : undefined)
  ElMessage.success(version ? `已将 v${version} 复制为我的方案` : '已复制为我的方案')
  verVisible.value = false
  const list = await profileSelectRef.value?.reload()
  const copied = list?.find((p) => p.id === r.id)
  onScreenSelect(copied ? (copied.profile_ref || copied.id) : (r.profile_ref || r.id))
}

// 删除自己的方案（readonly/公开态不可删，后端亦按归属 403）；删后清空编辑器并刷新 mine 列表
async function remove() {
  if (!curRef.value || !loadedProfile.value || profileReadonly.value) return
  await ElMessageBox.confirm(`确认删除方案「${editName.value}」？`, '提示', { type: 'warning' })
  await deleteProfile(curRef.value)
  ElMessage.success('已删除')
  newProfile()
  await profileSelectRef.value?.reload()
}

// ── 历史版本 ──
const verVisible = ref(false)
const versions = ref<ProfileVersion[]>([])
async function openVersions() {
  if (!curRef.value) return
  versions.value = (await getProfileVersions(curRef.value)).versions
  verVisible.value = true
}
// 恢复=仅把该历史版本载入编辑器（不写库）；用户确认后点「保存」才生成新版本
function restoreVersion(v: ProfileVersion) {
  const parsed = parseAst(v.expression)
  if (parsed) { groupOp.value = parsed.op; rows.value = parsed.rows; complexAst.value = null }
  else { complexAst.value = v.expression; rows.value = [] }
  verVisible.value = false
  ElMessage.success(`已载入 v${v.version} 到编辑器，确认后点「保存」生成新版本`)
}

function versionRowActions(v: ProfileVersion): AppRowAction[] {
  if (!canSaveProfile.value) return []
  if (profileReadonly.value) {
    return [
      { key: 'copy', label: '复制此版本为我的', onClick: () => { void copyCurrentProfile(v.version) } },
    ]
  }
  return [
    { key: 'restore', label: '载入此版本', onClick: () => restoreVersion(v) },
  ]
}

function exportCsv() {
  if (!result.value?.hits.length) return
  const relatedColumns = [
    { key: 'relatedIndustry', label: '行业走势', type: 'industry' as const },
    { key: 'relatedConcept', label: '概念走势', type: 'concept' as const },
  ].filter((column) => colVisible(column.key))
  const showBoard = colVisible('board')
  const subScoreKeys = colVisible('subScores') ? resultSubKeys.value : []
  const headers = [
    '全市场排名', '代码', '名称', ...(showBoard ? ['板块'] : []),
    ...relatedColumns.flatMap((column) => [column.label, `${column.label}截止日`, `${column.label}状态`]), '综合分', '评级',
    ...subScoreKeys.map((key) => indicatorName(key)), '评分状态',
  ]
  const data = result.value.hits.map((h) => [
    h.rank ?? '', h.code, h.name ?? '', ...(showBoard ? [h.board ?? ''] : []),
    ...relatedColumns.flatMap((column) => relatedBoardExportValues(h.related_boards, column.type)),
    h.total_score ?? '', h.grade ?? '',
    ...subScoreKeys.map((key) => Math.round(h.sub_scores[key] ?? 0)), h.score_status,
  ])
  downloadCsv(`筛选结果_${result.value.date}.csv`, headers, data)
}

async function initializeScreen() {
  initLoading.value = true
  initError.value = ''
  try {
    registry.value = (await getIndicatorRegistry(true)).items
    if (!rows.value.length && !complexAst.value) {
      rows.value = [newIndRow('bull_arrange'), newIndRow('rs_pct')]
      rows.value[1].cmp = '>='
      rows.value[1].value = 90
    }
  } catch (error) {
    initError.value = getErrorMessage(error, '筛选配置加载失败')
  } finally {
    initLoading.value = false
  }
}

onMounted(initializeScreen)
const menuPageTitle = useMenuPageTitle()
</script>

<template>
  <LayoutHost :layout="screenEffective">
    <template #action>
    <div class="page-head">
      <div>
        <h2 class="app-page-title page-title-row">
          {{ menuPageTitle }}
          <HelpTip title="筛选 与 榜单 的区别" :width="400">
            <HelpTipItem question="筛选是什么">
              <ul>
                <li>给定一组布尔条件，返回所有满足条件的股票，命中即入，不设置排名门槛。</li>
              </ul>
            </HelpTipItem>
            <HelpTipItem question="榜单是什么">
              <ul>
                <li>对全市场打分排序后取 Top N。</li>
              </ul>
            </HelpTipItem>
            <HelpTipItem question="本页如何构建条件">
              <ul>
                <li>每条条件可选带动态参数的注册表指标或手写表达式，再用且、或组合。命中结果使用榜单同款评分排序，并可排除 ST、保存为方案。</li>
              </ul>
            </HelpTipItem>
          </HelpTip>
        </h2>
        <p class="page-subtitle">组合技术指标条件筛选候选股，支持表达式与嵌套分组。</p>
      </div>
      <div class="page-head-actions">
        <PageSettingsTrigger :dirty="isDirty || layoutDirty" @click="settingsOpen = true" />
      </div>
    </div>
    </template>

    <template #main>
    <AppStateBlock
      v-if="initLoading"
      state="loading"
      title="正在加载筛选配置…"
    />
    <AppStateBlock
      v-else-if="initError"
      state="error"
      title="筛选配置加载失败"
      :description="initError"
      retry
      @retry="initializeScreen"
    />
    <div v-else class="screen-body">
      <div class="screen-layout">
        <!-- 方案列表（R3/R5/R7：统一选择器 list 形态，仅我的 + 搜索系统内置/租户/全体公开） -->
        <aside class="prof-list">
          <el-button type="primary" plain size="small" style="width: 100%" @click="newProfile">
            <template #icon><el-icon><Plus /></el-icon></template>
            新建方案
          </el-button>
          <AssetProfileSelect
            ref="profileSelectRef"
            mode="list"
            :model-value="curRef"
            asset-label="筛选方案"
            :fetch-mine="fetchMineProfiles"
            :browse="browseScreenProfiles"
            :copy-item="copyAnyProfile"
            copy-permission="screen-profile:save"
            view-permission="screen-profile:view"
            test-id="screen-profile-select"
            @update:model-value="onScreenSelect"
            @loaded="onScreenLoaded"
            @ready="onScreenReady"
            @temp-removed="onScreenTempRemoved"
          />
        </aside>

        <!-- 编辑器 -->
        <section class="editor editor-screen">
          <div class="ed-head app-cluster-md">
            <el-input v-model="editName" :disabled="profileReadonly" placeholder="方案名称" style="width: 200px" />
            <AppHoverInfo v-if="curVersion && !isNew" content="点击查看历史版本">
              <span tabindex="0"
                class="ver-badge"
                data-testid="screen-profile-version"
                role="button" @click="openVersions" @keydown.enter.prevent="openVersions" @keydown.space.prevent="openVersions"
              >v{{ curVersion }}</span>
            </AppHoverInfo>
            <AssetVisibilityActions
              v-if="!isNew"
              :visibility="profileVisibility"
              :readonly="profileReadonly"
              :can-publish-tenant="canPublishTenant"
              :can-publish-public="canPublishPublic"
              :saving="visibilitySaving"
              :copy-visible="profileReadonly"
              copy-permission="screen-profile:save"
              @publish="publishProfile"
              @copy="copyCurrentProfile"
            />
            <div class="spacer" />
            <el-button v-permission="'screen-profile:save'" :disabled="profileReadonly || !screenFormChanged" :loading="saving" type="primary" @click="save">保存</el-button>
            <el-button v-permission="'screen-profile:delete'" v-if="curId && !isNew && !profileReadonly" type="danger" plain @click="remove">删除</el-button>
          </div>

          <!-- 详情加载态/失败态（原子应用 + seq 守卫）：失败已回滚选中值，编辑器保留旧内容 -->
          <AppStateBlock
            v-if="profileError"
            state="error"
            size="compact"
            title="筛选方案详情加载失败"
            :description="profileError"
            retry
            @retry="onScreenSelect(profileDetailAttempt || curRef)"
          />
          <AppStateBlock
            v-else-if="profileLoading"
            state="loading"
            size="compact"
            title="正在加载方案详情…"
          />

          <!-- 复杂嵌套方案：只读运行 -->
          <AppStatusNotice
            v-if="complexAst"
            class="complex-ast-notice"
            title="该方案含嵌套分组，构建器暂以只读方式运行；如需改写请新建方案。"
          />
          <pre v-if="complexAst" class="ast">{{ JSON.stringify(complexAst, null, 2) }}</pre>

          <!-- 融合构建器（卡片包裹，与结果区/编辑器头区分边界，对齐买卖 cond-block） -->
          <template v-else>
            <div class="cond-block">
            <div class="b-group">
              <span class="hint">组合方式</span>
              <el-radio-group v-model="groupOp" size="small">
                <el-radio-button value="AND">满足全部（且）</el-radio-button>
                <el-radio-button value="OR">满足任一（或）</el-radio-button>
              </el-radio-group>
            </div>

            <div
              class="b-conds"
              data-testid="screen-condition-builder"
              :class="{ 'readonly-builder': profileReadonly }"
            >
            <div
              v-for="(c, i) in rows"
              :key="i"
              class="b-cond"
              data-testid="screen-condition-row"
            >
              <StrategyItemEnabledSwitch
                v-model="c.enabled"
                :disabled="profileReadonly"
                label="是否启用筛选条件"
              />
              <!-- 指标条件 -->
              <template v-if="c.kind === 'ind'">
                <el-tag size="small" type="success" effect="plain" class="kind-tag">指标</el-tag>
                <IndicatorSelect v-model="c.key" :definitions="registry" :disabled="profileReadonly" @change="onIndKey(c)" />
                <!-- 动态参数 -->
                <IndicatorParamFields v-model="c.params" :params="defOf(c.key)?.params ?? []" :disabled="profileReadonly" />
                <!-- 布尔：成立/不成立 -->
                <template v-if="defOf(c.key)?.dtype === 'bool'">
                  <el-select v-model="c.boolVal" size="small" style="width: 104px" :disabled="profileReadonly">
                    <el-option :value="true" label="成立" />
                    <el-option :value="false" label="不成立" />
                  </el-select>
                </template>
                <!-- 数值：比较符 + 阈值 -->
                <template v-else>
                  <el-select v-model="c.cmp" size="small" style="width: 84px" :disabled="profileReadonly">
                    <el-option v-for="o in NUM_CMP" :key="o.v" :value="o.v" :label="o.t" />
                  </el-select>
                  <el-input-number v-model="c.value" :disabled="profileReadonly" :controls="false" size="small" style="width: 86px" />
                  <template v-if="c.cmp === 'between'">
                    <span>~</span>
                    <el-input-number v-model="c.value2" :disabled="profileReadonly" :controls="false" size="small" style="width: 86px" />
                  </template>
                </template>
              </template>

              <!-- 表达式条件 -->
              <template v-else>
                <el-tag size="small" type="warning" effect="plain" class="kind-tag">表达式</el-tag>
                <el-input
                  v-model="c.expr"
                  :disabled="profileReadonly"
                  size="small"
                  placeholder="如：COUNT(C > REF(C,1), 5) == 5"
                  style="flex: 1; min-width: 260px"
                />
              </template>

              <AppRowActions :actions="conditionRowActions(i)" :inline-limit="1" />
            </div>
            </div>

            <div class="b-actions">
              <el-button size="small" :disabled="profileReadonly" @click="addIndRow">
                <template #icon><el-icon><Plus /></el-icon></template>
                指标条件
              </el-button>
              <el-button size="small" :disabled="profileReadonly" @click="addExprRow">
                <template #icon><el-icon><Plus /></el-icon></template>
                表达式条件
              </el-button>
              <HelpTip title="表达式语法" :width="400">
                <HelpTipItem question="支持哪些语法">
                  <ul>
                    <li>算子支持 MA / HHV / LLV / REF / COUNT / SUM / ABS；变量支持 C 收、O 开、H 高、L 低、V 量、TURN 换手。</li>
                  </ul>
                </HelpTipItem>
                <HelpTipItem question="如何保证点时安全">
                  <ul>
                    <li>仅使用不晚于当日的数据，不使用未来函数。</li>
                  </ul>
                </HelpTipItem>
              </HelpTip>
            </div>
            <pre v-if="settings.astExpanded && buildAst()" class="ast">{{ JSON.stringify(buildAst(), null, 2) }}</pre>
            </div>
          </template>

          <!-- 运行筛选 -->
          <div class="run-head">
            <span class="run-title">筛选结果</span>
            <AssetProfileSelect
              ref="scoreSelectRef"
              :model-value="scoreProfileRef"
              asset-label="评分方案"
              :fetch-mine="fetchMineScoreProfiles"
              :browse="browseScreenScoreProfiles"
              :copy-item="copyAnyScoreProfile"
              copy-permission="score-profile:save"
              view-permission="score-profile:view"
              placeholder="请选择评分方案"
              select-loaded
              :default-item-key="defaultScoreProfile.value.profile_ref || defaultScoreProfile.value.id"
              test-id="screen-score-profile-select"
              class="app-control-width-wide"
              @update:model-value="onScoreProfileSelect"
              @loaded="onScoreProfileLoaded"
              @ready="onScoreProfilesReady"
              @set-default="onSetScreenScoreDefault"
            />
            <TradeDatePicker v-model="runDate" placeholder="默认最新交易日" default-latest style="width: 160px" />
            <el-button v-permission="'screen:run'" type="primary" :loading="loading" :disabled="!scoreProfileRef" @click="run">
              <template #icon><el-icon><VideoPlay /></el-icon></template>
              运行筛选
            </el-button>
            <el-button v-if="result && result.hits.length" size="small" @click="exportCsv">导出 CSV</el-button>
            <span class="run-hint">含表达式/带参指标需全市场逐股求值，约十几秒</span>
          </div>
          <!-- ready 摘要：结果可回溯——命中数、是否排除 ST、按哪个只读方案口径跑的；交易日由日期选择器展示，不重复 -->
          <div v-if="result" class="run-meta">
            共 <b>{{ result.count }}</b> 只 · 评分方案「{{ result.score_profile_name }}」v{{ result.score_profile_version }}
            · {{ result.include_st ? '全市场排名含 ST' : '全市场排名不含 ST' }}
            · {{ result.exclude_st ? '筛选结果已排除 ST' : '筛选结果保留 ST' }}
            <template v-if="profileReadonly && loadedProfile"> · 按筛选方案「{{ loadedProfile.name }}」运行</template>
          </div>

          <!-- 筛选结果表 -->
          <div class="run-table-wrap">
            <AppStateBlock
              v-if="loading && (!result || !result.hits.length)"
              state="loading"
              title="正在运行筛选…"
            />
            <AppStateBlock
              v-else-if="resultError"
              state="error"
              :title="result ? '筛选结果刷新失败' : '筛选运行失败'"
              :description="resultError"
              retry
              @retry="run"
            />
            <RankedStockWorkbench
              v-else-if="result && result.hits.length"
              registry-page-key="screen"
              :adjust-mode="adjustMode"
              :analysis-defaults="chartPreferences.stockAnalysis.value"
              :rows="displayHits"
              :columns="resultColumns"
              :title="runDate || '最新交易日'"
              :meta="`${result.count} 只候选`"
              :run-date="runDate"
              :loading="loading"
              :border="tableBorder('result')"
              :score-keys="resultSubKeys"
              :label-of="indicatorName"
              :return-path="route.fullPath"
              collection-label="策略筛选"
              :default-master-ratio="Number(componentValueOf('workspace', 'masterRatio') ?? 45)"
              :master-ratio-profiles="componentValueOf('workspace', 'masterRatioProfiles')"
              :slot2="chartPreferences.preferences.value.slot2"
              :slot3="chartPreferences.preferences.value.slot3"
              :height-ratios="chartPreferences.currentRatios.value"
              v-model:return-measurement-mode="chartPreferences.returnMeasurementMode.value"
              v-model:kline-period="chartPreferences.klinePeriod.value"
              @sort-change="onResultSortChange"
              @master-ratio-sample-change="setCurrentMasterRatioSample"
              @ratio-draft="chartPreferences.handleRatioDraft"
              @ratio-commit="chartPreferences.handleRatioCommit"
              @workspace-resize="chartPreferences.handleWorkspaceResize"
            />
            <AppStateBlock v-else-if="result" state="empty" title="当前条件暂无命中" />
            <AppStateBlock v-else state="empty" title="运行后在这里展示筛选结果" />
          </div>
        </section>
      </div>
    </div>
    </template>

    <template #overlays>
    <!-- 历史版本 -->
    <AppDetailDrawer v-model="verVisible" :title="`历史版本 · ${loadedProfile?.name || ''}`" size="xl">
      <el-empty v-if="!versions.length" class="app-empty app-empty--compact" description="暂无历史版本" />
      <div v-for="v in versions" :key="v.version" class="ver-item">
        <div class="ver-head">
          <b>v{{ v.version }}</b>
          <span class="hint">{{ formatDateTimeMinutes(v.saved_at) }}</span>
          <AppRowActions :actions="versionRowActions(v)" :inline-limit="1" />
        </div>
        <pre class="ast">{{ JSON.stringify(v.expression, null, 2) }}</pre>
      </div>
    </AppDetailDrawer>

    <PageSettingsDrawer
      v-model="settingsOpen"
      title="策略筛选"
      :dirty="isDirty || layoutDirty"
      page-key="screen"
      :config="drawerConfig"
      :component-runtime-value-of="componentRuntimeValueOf"
      @reset="reset(); resetLayout()"
    >
      <template #business>
        <PageSettingSection title="行情口径">
          <PageSettingItem label="复权模式">
            <PageSegmented v-model="settings.adjustMode" aria-label="复权模式" :options="[
              { label: '不复权', value: '' },
              { label: '前复权', value: 'qfq' },
              { label: '后复权', value: 'hfq' },
            ]" />
          </PageSettingItem>
        </PageSettingSection>
        <PageSettingSection title="默认行为">
          <PageToggleRow v-model="settings.excludeSt" label="默认排除 ST" />
          <PageToggleRow v-model="settings.astExpanded" label="展开 AST 预览" />
        </PageSettingSection>
      </template>
    </PageSettingsDrawer>
    </template>
  </LayoutHost>
</template>

<style scoped>
.page-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  flex-wrap: wrap;
  gap: var(--app-space-2);
}
.page-title-row {
  display: flex;
  align-items: center;
}
/* 间距由 .lh-action（操作区）与 .v-page（操作区↔主区）统一提供，组件本身不再加外边距 */
/* 条件行区限高内滚：操作区(构建器)不会随条件增多无限增高、挤压下方结果区 */
.b-conds {
  max-height: 220px;
  overflow-y: auto;
}
/* 空态/无命中在结果区内居中，不再切换外层盒子（避免状态切换抖动）*/
.run-table-wrap :deep(.el-empty) {
  margin: auto;
}
.screen-body {
  flex: 1 1 auto;   /* 填满 LayoutHost 的条件成长区，页面内容在本区域内滚动 */
  min-height: 0;
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: auto;
}
.screen-layout {
  display: flex;
  gap: var(--app-space-4);
  flex: 1 1 auto;
  min-height: 0;
}
.prof-list {
  width: 190px;
  flex-shrink: 0;
}
/* 方案列表限高内滚：不会随方案数量无限增高、挤压下方结果区 */
.prof-list :deep(.asset-profile-select__list),
.prof-list :deep(.asset-profile-select__empty) {
  max-height: 360px;
  overflow-y: auto;
}
.editor {
  flex: 1;
  min-width: 0;
}
.editor-screen {
  display: flex;
  flex-direction: column;
  min-height: 0;
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
.hint {
  color: var(--app-muted-text);
  font-size: var(--app-font-size-caption);
}
/* 条件构建区卡片包裹：与编辑器头/结果区区分边界（对齐买卖 cond-block） */
.cond-block {
  margin: var(--app-space-3) 0;
  padding: 12px 14px;
  border: 1px solid var(--el-border-color-light);
  border-radius: 8px;
  background: var(--el-fill-color-blank);
}
.b-group {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
  margin: 0 0 10px;
}
.b-cond {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
  margin-bottom: 8px;
  flex-wrap: wrap;
}
.kind-tag {
  width: 52px;
  text-align: center;
  flex-shrink: 0;
}
.param-lb {
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
}
.b-actions {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
  margin-top: 4px;
}
/* 按钮组内的帮助图标：去掉自带左间距（由 flex gap 统一），并取消 inline 基线偏移以对齐按钮 */
.b-actions :deep(.help-icon) {
  margin-left: 0;
  vertical-align: baseline;
}
.ast {
  margin: 12px 0 0;
  padding: 10px 12px;
  background: var(--app-section-bg);
  border-radius: 6px;
  font-size: var(--app-font-size-caption);
  color: var(--el-text-color-regular);
  max-height: 200px;
  overflow: auto;
}
.complex-ast-notice { margin: var(--app-space-3) 0; }
.readonly-builder {
  opacity: 0.82;
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
.run-head {
  display: flex;
  align-items: center;
  gap: var(--app-space-3);
  margin: var(--app-space-5) 0 var(--app-space-3);
  flex: none;
}
.run-title {
  font-weight: var(--app-font-weight-section);
  font-size: var(--app-font-size-section-title);
}
.run-meta {
  margin: -4px 0 8px;
  color: var(--app-muted-text);
  font-size: var(--app-font-size-caption);
}
.run-meta b {
  color: var(--el-text-color-regular);
  font-weight: var(--app-font-weight-section);
}
.run-table-wrap {
  flex: 1 1 auto;
  display: flex;
  flex-direction: column;
}
.run-table-wrap .el-table {
  flex: 1 1 auto;
  min-height: 0;
}
.run-hint {
  color: var(--app-placeholder-text);
  font-size: var(--app-font-size-caption);
  margin-left: auto;
}
.score {
  color: var(--app-danger-text);
}
.muted {
  color: var(--app-placeholder-text);
}
.clickable :deep(.el-table__row) {
  cursor: pointer;
}
</style>
