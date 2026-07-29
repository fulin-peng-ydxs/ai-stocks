<script setup lang="ts">
import AppTableColumn from '@/components/AppTableColumn.vue'
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import {
  browseProfiles,
  copyProfile,
  getProfile,
  getProfileVersions,
  listProfiles,
  runScreen,
  saveProfile,
  setProfileVisibility,
  type Profile,
  type ProfileVersion,
  type ScreenHit,
} from '@/api/screening'
import { getIndicatorRegistry, type IndicatorDef } from '@/api/scoreProfile'
import { useAuthStore } from '@/stores/auth'
import { hasPermission } from '@/utils/permission'
import AppDataTable from '@/components/AppDataTable.vue'
import AppRowActions from '@/components/AppRowActions.vue'
import AppStateBlock from '@/components/AppStateBlock.vue'
import AssetProfileSelect from '@/components/asset-search/AssetProfileSelect.vue'
import AssetVisibilityActions from '@/components/AssetVisibilityActions.vue'
import HelpTip from '@/components/HelpTip.vue'
import type { AssetBrowseParams, ProfileSummary } from '@/components/asset-search/types'
import PageSettingSection from '@/components/PageSettingSection.vue'
import PageSettingsDrawer from '@/components/PageSettingsDrawer.vue'
import PageSettingsTrigger from '@/components/PageSettingsTrigger.vue'
import PageToggleRow from '@/components/PageToggleRow.vue'
import TradeDatePicker from '@/components/TradeDatePicker.vue'
import { usePageSettings } from '@/composables/usePageSettings'
import { downloadCsv } from '@/utils/csv'
import LayoutHost from '@/layout/components/LayoutHost.vue'
import { getPageLayout } from '@/layout'
import { useRemoteLayoutConfig } from '@/composables/useRemoteLayoutConfig'
import { getErrorMessage } from '@/utils/error'
import type { AppRowAction } from '@/components/rowActions'

const router = useRouter()
const settingsOpen = ref(false)
// 排除 ST、AST 预览属业务态偏好，保留 usePageSettings；结果排序与列显隐迁入组件配置层（plan.md §13.3）。
const screenDefaults = {
  excludeSt: true,
  astExpanded: false,
}
const { settings, isDirty, reset } = usePageSettings('screen', screenDefaults)

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
  componentLayerValuesOf,
} = useRemoteLayoutConfig(screenLayout)

// 抽屉「布局」「组件设置」两段由 PageSettingsDrawer 按元数据自动渲染（见 pageRegistry.componentMeta）。
const drawerConfig = { knobs: layoutKnobs, valueOf, sourceOf, setKnob, componentValueOf, setComponentKnob, componentSourceOf, layerValuesOf, componentLayerValuesOf }

// 抽屉写值由 ComponentAutoSettings 自动渲染；页面只保留排序/渲染要读的 getter。
type ResultSort = 'score' | 'code' | 'name'
const RESULT_SORT_PROPS: Record<string, ResultSort> = { total_score: 'score', code: 'code', name: 'name' }
const resultSort = computed<ResultSort>(() => {
  const raw = componentValueOf('result', 'defaultSort')
  return raw === 'code' || raw === 'name' ? raw : 'score'
})
const elementDefaultSort = computed(() => {
  if (resultSort.value === 'code') return { prop: 'code', order: 'ascending' }
  if (resultSort.value === 'name') return { prop: 'name', order: 'ascending' }
  return { prop: 'total_score', order: 'descending' }
})
const hiddenColumns = computed<string[]>(() => (componentValueOf('result', 'hiddenColumns') as string[]) ?? [])
function colVisible(key: string): boolean {
  return !hiddenColumns.value.includes(key)
}
function tableBorder(slotId: string): boolean {
  return componentValueOf(slotId, 'border') === true
}
function onResultSortChange({ prop }: { prop: string; order: string | null }): void {
  setComponentKnob('result', 'defaultSort', RESULT_SORT_PROPS[prop] ?? 'score')
}

// ── 指标注册表（融合：可视化条件直接从注册表取指标，支持动态传参）──
const registry = ref<IndicatorDef[]>([])
const enabledInds = computed(() => registry.value.filter((d) => d.enabled))
function defOf(key: string): IndicatorDef | undefined {
  return registry.value.find((d) => d.key === key)
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
  return { kind: 'ind', key: k, params, cmp: '>=', value: 0, value2: 0, boolVal: true, expr: '' }
}
function newExprRow(): Row {
  return { kind: 'expr', key: '', params: {}, cmp: '>=', value: 0, value2: 0, boolVal: true, expr: '' }
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
    return e ? { type: 'expr', expr: e } : null
  }
  const d = defOf(row.key)
  if (!d) return null
  const base: Record<string, unknown> = { type: 'ind', key: row.key }
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
    return r
  }
  if (t === 'ind' || t === 'col') {
    const key = t === 'ind' ? String(node.key) : (COL_TO_KEY[String(node.field)] ?? String(node.field))
    const d = defOf(key)
    if (!d) return null
    const r = newIndRow(key)
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

// ── 已存/系统内置方案：载入到构建器 ──
// R3/R5：方案选择统一走 AssetProfileSelect——下拉只加载「我的」（source=mine 纯 owner），
// 「搜索」入口打开共享搜索抽屉（系统内置/租户公开/全体公开），「加载查看」注入临时只读、
// 「复制为我的」自动刷新并选中（组件内部闭环，本页不再维护列表/复制逻辑）。
const loadId = ref('')
const loadedProfile = ref<Profile | null>(null)
const initLoading = ref(true)
const initError = ref('')
const profileLoading = ref(false)
const profileError = ref('')
let profileLoadSeq = 0
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
async function loadSelectedProfile(id: string) {
  const seq = ++profileLoadSeq
  if (!id) {
    loadedProfile.value = null
    profileError.value = ''
    profileLoading.value = false
    return
  }
  profileLoading.value = true
  profileError.value = ''
  try {
    const p = await getProfile(id)
    if (seq !== profileLoadSeq) return
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
  } catch (error) {
    if (seq !== profileLoadSeq) return
    loadedProfile.value = null
    profileError.value = getErrorMessage(error, '筛选方案详情加载失败')
  } finally {
    if (seq === profileLoadSeq) profileLoading.value = false
  }
}
watch(loadId, (id) => {
  void loadSelectedProfile(id)
})
function clearAll() {
  rows.value = []
  complexAst.value = null
  loadId.value = ''
  loadedProfile.value = null
}

// ── 运行 / 结果 ──
const runDate = ref('')
const excludeSt = ref(Boolean(settings.excludeSt))
const loading = ref(false)
const resultError = ref('')
const result = ref<{ date: string; count: number; hits: ScreenHit[] } | null>(null)
const gradeTag: Record<string, '' | 'success' | 'warning' | 'info'> = {
  主升浪核心: 'success', 龙头候选: 'warning', 观察: 'info',
}
const displayHits = computed(() => {
  const list = [...(result.value?.hits ?? [])]
  if (resultSort.value === 'code') list.sort((a, b) => a.code.localeCompare(b.code))
  else if (resultSort.value === 'name') list.sort((a, b) => (a.name || '').localeCompare(b.name || ''))
  else list.sort((a, b) => (b.total_score ?? 0) - (a.total_score ?? 0))
  return list
})

watch(() => settings.excludeSt, (value) => {
  excludeSt.value = Boolean(value)
})

async function run() {
  const ast = buildAst()
  if (!ast) return ElMessage.warning('请先添加条件')
  loading.value = true
  resultError.value = ''
  // 不清空 result：让旧结果留在 loading 遮罩下，避免闪回空态（结果区盒子保持不变）
  try {
    const r = await runScreen({
      ...(profileReadonly.value && loadId.value ? { profile_id: loadId.value } : { expression: ast }),
      run_date: runDate.value || undefined,
      exclude_st: excludeSt.value,
    })
    result.value = { date: r.run_date, count: r.count, hits: r.hits }
  } catch (error) {
    resultError.value = getErrorMessage(error, '筛选运行失败')
    ElMessage.error(resultError.value)
  } finally {
    loading.value = false
  }
}

// ── 保存为方案（实质变更才版本+1；载入的自定义方案可覆盖更新）──
const saveVisible = ref(false)
const saveName = ref('')
const saving = ref(false)
const canOverwrite = computed(() => !!loadedProfile.value && !loadedProfile.value.is_preset && !profileReadonly.value)
const overwrite = ref(false)
function openSave() {
  if (profileReadonly.value) return ElMessage.warning('公开方案为只读，请先复制为自己的方案')
  if (!buildAst()) return ElMessage.warning('请先添加条件')
  saveName.value = canOverwrite.value ? loadedProfile.value!.name : ''
  overwrite.value = canOverwrite.value
  saveVisible.value = true
}
async function doSave() {
  const expr = buildAst()
  if (!saveName.value.trim()) return ElMessage.warning('请输入方案名称')
  if (!expr) return ElMessage.warning('条件为空')
  saving.value = true
  try {
    const id = overwrite.value && canOverwrite.value && loadedProfile.value ? loadedProfile.value.id : 'custom_' + Date.now()
    const r = await saveProfile({ id, name: saveName.value.trim(), expression: expr })
    ElMessage.success(`已保存（v${r.version}）`)
    saveVisible.value = false
    const list = await profileSelectRef.value?.reload()
    const saved = list?.find((p) => p.id === id)
    loadId.value = saved ? (saved.profile_ref || saved.id) : id
  } catch {
    /* 统一弹错 */
  } finally {
    saving.value = false
  }
}

async function publishProfile(visibility: 'private' | 'tenant' | 'public') {
  if (!loadId.value || profileReadonly.value || visibilitySaving.value) return
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
    loadedProfile.value = await setProfileVisibility(loadId.value, visibility)
    ElMessage.success(visibility === 'private' ? '已设为私有' : '公开设置已更新')
    await profileSelectRef.value?.reload()
  } finally {
    visibilitySaving.value = false
  }
}
// C8：复制由后端生成唯一 id、名称默认「原名 副本」，返回新标识供选中
async function copyCurrentProfile() {
  if (!loadId.value || !loadedProfile.value) return
  const r = await copyProfile(loadId.value)
  ElMessage.success('已复制为我的方案')
  const list = await profileSelectRef.value?.reload()
  const copied = list?.find((p) => p.id === r.id)
  loadId.value = copied ? (copied.profile_ref || copied.id) : (r.profile_ref || r.id)
}

// ── 历史版本 ──
const verVisible = ref(false)
const versions = ref<ProfileVersion[]>([])
async function openVersions() {
  if (!loadId.value) return
  versions.value = (await getProfileVersions(loadId.value)).versions
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
  return [
    { key: 'restore', label: '载入此版本', onClick: () => restoreVersion(v) },
  ]
}

function rowClass({ row }: { row: ScreenHit }) {
  return row.is_st ? 'st-row' : ''
}
function exportCsv() {
  if (!result.value?.hits.length) return
  const headers = ['代码', '名称', '综合分', '评级', '是否ST']
  const data = result.value.hits.map((h) => [
    h.code, h.name ?? '', h.total_score ?? '', h.grade ?? '', h.is_st ? 'ST' : '',
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
</script>

<template>
  <LayoutHost :layout="screenEffective">
    <template #action>
    <div class="lh-action">
    <div class="page-head">
      <div class="page-head-actions" style="width: 100%; justify-content: space-between;">
        <h2 class="title-row">
          策略筛选
          <HelpTip title="筛选 与 榜单 的区别" :width="400">
            <p><b>筛选</b>：给一组布尔条件，返回<b>所有满足</b>的股票（命中即入，无门槛排序）。</p>
            <p style="margin:6px 0"><b>榜单</b>：对全市场打分排序取 Top N。</p>
            <p style="margin:0">本页一套构建器即可：每条条件可选<b>注册表指标</b>（含动态参数）或手写<b>表达式</b>，用 且/或 组合。命中结果用榜单同款评分打分并按分排序，方便判断质量；可「排除 ST」、存为方案。</p>
          </HelpTip>
        </h2>
        <PageSettingsTrigger :dirty="isDirty || layoutDirty" @click="settingsOpen = true" />
      </div>
    </div>

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
    <el-card v-else shadow="never" class="cond-card">
      <!-- 载入我的方案 + 搜索系统内置/租户/全体公开（R3/R5/R14） -->
      <div class="load-row">
        <span class="hint">载入方案</span>
        <AssetProfileSelect
          ref="profileSelectRef"
          v-model="loadId"
          asset-label="筛选方案"
          :fetch-mine="fetchMineProfiles"
          :browse="browseScreenProfiles"
          :copy-item="copyAnyProfile"
          copy-permission="screen-profile:save"
          view-permission="screen-profile:view"
          placeholder="选我的筛选方案（可选）"
          style="width: 400px"
        />
        <span class="ver-link" v-if="loadedProfile" title="点击查看历史版本" @click="openVersions">v{{ loadedProfile.version }}</span>
        <AssetVisibilityActions
          v-if="loadedProfile"
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
        <el-button text size="small" @click="clearAll">清空</el-button>
      </div>
      <AppStateBlock
        v-if="profileError"
        state="error"
        size="inline"
        title="筛选方案详情加载失败"
        :description="profileError"
        retry
        @retry="loadSelectedProfile(loadId)"
      />

      <!-- 复杂嵌套方案：只读运行 -->
      <el-alert
        v-if="complexAst"
        type="info"
        :closable="false"
        show-icon
        title="该方案含嵌套分组，构建器暂以只读方式运行；如需改写请清空后重建。"
        style="margin: 10px 0"
      />
      <pre v-if="complexAst" class="ast">{{ JSON.stringify(complexAst, null, 2) }}</pre>

      <!-- 融合构建器 -->
      <template v-else>
        <div class="b-group">
          <span class="hint">组合方式</span>
          <el-radio-group v-model="groupOp" size="small">
            <el-radio-button value="AND">满足全部（且）</el-radio-button>
            <el-radio-button value="OR">满足任一（或）</el-radio-button>
          </el-radio-group>
        </div>

        <div class="b-conds" :class="{ 'readonly-builder': profileReadonly }">
        <div v-for="(c, i) in rows" :key="i" class="b-cond">
          <!-- 指标条件 -->
          <template v-if="c.kind === 'ind'">
            <el-tag size="small" type="success" effect="plain" class="kind-tag">指标</el-tag>
            <el-select v-model="c.key" filterable size="small" style="width: 180px" :disabled="profileReadonly" @change="onIndKey(c)">
              <el-option v-for="d in enabledInds" :key="d.key" :value="d.key" :label="d.name_cn" />
            </el-select>
            <!-- 动态参数 -->
            <template v-for="p in defOf(c.key)?.params ?? []" :key="p.name">
              <span class="param-lb">{{ p.label }}</span>
              <el-input-number
                v-model="c.params[p.name]"
                :disabled="profileReadonly"
                :controls="false"
                :min="p.min ?? undefined"
                :max="p.max ?? undefined"
                size="small"
                style="width: 70px"
              />
            </template>
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
          <el-button v-permission="'screen-profile:save'" text type="primary" size="small" :disabled="profileReadonly" @click="openSave">
            <template #icon><el-icon><Plus /></el-icon></template>
            保存为方案
          </el-button>
        </div>
        <div class="dsl-help">
          表达式算子：MA / HHV / LLV / REF / COUNT / SUM / ABS；变量：C 收 O 开 H 高 L 低 V 量 TURN 换手。
          点时安全（仅用 ≤ 当日数据，无未来函数）。
        </div>
        <pre v-if="settings.astExpanded && buildAst()" class="ast">{{ JSON.stringify(buildAst(), null, 2) }}</pre>
      </template>

      <!-- 运行栏 -->
      <div class="run-bar">
        <TradeDatePicker v-model="runDate" placeholder="最新交易日" clearable style="width: 160px" />
        <el-button v-permission="'screen:run'" type="primary" :loading="loading" @click="run">运行筛选</el-button>
        <span class="run-hint">含表达式/带参指标需全市场逐股求值，约十几秒</span>
      </div>
    </el-card>
    </div>
    </template>

    <template #main>
    <el-card shadow="never" class="result-card" v-loading="loading">
      <template #header>
        <span v-if="result">
          命中 <strong class="cnt">{{ result.count }}</strong> 只 · 交易日 {{ result.date }} ·
          已按综合分排序{{ excludeSt ? ' · 已排除 ST' : '' }}
        </span>
        <span v-else>筛选结果</span>
        <el-button v-if="result && result.hits.length" size="small" style="float:right" @click="exportCsv">导出 CSV</el-button>
      </template>
      <AppStateBlock
        v-if="resultError && !result"
        state="error"
        title="筛选运行失败"
        :description="resultError"
        retry
        @retry="run"
      />
      <template v-else>
      <AppStateBlock
        v-if="resultError"
        state="error"
        size="compact"
        title="筛选结果刷新失败"
        :description="resultError"
        retry
        @retry="run"
      />
      <AppDataTable
        v-if="result && result.hits.length"
        :data="displayHits"
        :border="tableBorder('result')"
        :default-sort="elementDefaultSort"
        :row-class-name="rowClass"
        clickable
        @sort-change="onResultSortChange"
        @row-click="(r: ScreenHit) => router.push(`/stocks/${r.code}`)"
      >
        <AppTableColumn label="#" type="index" />
        <AppTableColumn v-if="colVisible('code')" label="代码" prop="code" sortable />
        <AppTableColumn v-if="colVisible('name')" label="名称" sortable :sort-by="(r:any)=>r.name || ''">
          <template #default="{ row }">
            <span>{{ row.name || '—' }}</span>
            <el-tag v-if="colVisible('st') && row.is_st" type="danger" size="small" effect="dark" style="margin-left: 6px">ST</el-tag>
          </template>
        </AppTableColumn>
        <AppTableColumn v-if="colVisible('score')" label="综合分" prop="total_score" sortable :sort-by="(r:any)=>r.total_score ?? -Infinity">
          <template #default="{ row }">
            <strong class="score">{{ row.total_score ?? '—' }}</strong>
          </template>
        </AppTableColumn>
        <AppTableColumn v-if="colVisible('grade')" label="评级">
          <template #default="{ row }">
            <el-tag v-if="row.grade" :type="gradeTag[row.grade] ?? 'info'" effect="light">{{ row.grade }}</el-tag>
            <span v-else class="muted">—</span>
          </template>
        </AppTableColumn>
      </AppDataTable>
      <el-empty v-else-if="result" class="app-empty" description="无命中" />
      <el-empty v-else class="app-empty" description="运行后在这里展示筛选结果" />
      </template>
    </el-card>
    </template>

    <template #overlays>
    <!-- 历史版本 -->
    <el-dialog v-model="verVisible" :title="`历史版本 · ${loadedProfile?.name || ''}`" width="560px">
      <el-empty v-if="!versions.length" class="app-empty app-empty--compact" description="暂无历史版本" />
      <div v-for="v in versions" :key="v.version" class="ver-item">
        <div class="ver-head">
          <b>v{{ v.version }}</b>
          <span class="hint">{{ v.saved_at?.slice(0, 16) }}</span>
          <AppRowActions :actions="versionRowActions(v)" :inline-limit="1" />
        </div>
        <pre class="ast">{{ JSON.stringify(v.expression, null, 2) }}</pre>
      </div>
    </el-dialog>

    <!-- 保存方案 -->
    <el-dialog v-model="saveVisible" title="保存为筛选方案" width="440px">
      <el-input v-model="saveName" placeholder="方案名称，如：我的连涨策略" maxlength="30" show-word-limit />
      <el-checkbox v-if="canOverwrite" v-model="overwrite" style="margin-top: 10px">
        覆盖更新当前方案「{{ loadedProfile?.name }}」（版本 +1）
      </el-checkbox>
      <pre class="ast" style="margin-top: 12px">{{ JSON.stringify(buildAst(), null, 2) }}</pre>
      <template #footer>
        <el-button @click="saveVisible = false">取消</el-button>
        <el-button v-permission="'screen-profile:save'" type="primary" :loading="saving" @click="doSave">保存</el-button>
      </template>
    </el-dialog>

    <PageSettingsDrawer
      v-model="settingsOpen"
      title="策略筛选"
      :dirty="isDirty || layoutDirty"
      page-key="screen"
      :config="drawerConfig"
      @reset="reset(); resetLayout()"
    >
      <template #business>
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
.page-head h2 {
  margin: 0;
  font-size: var(--app-font-size-page-title-sm);
}
.title-row {
  display: flex;
  align-items: center;
}
/* 间距由 .lh-action（操作区）与 .v-page（操作区↔主区）统一提供，组件本身不再加外边距 */
/* 条件行区限高内滚：操作区(构建器)不会随条件增多无限增高、挤压下方结果区 */
.b-conds {
  max-height: 220px;
  overflow-y: auto;
}
/* 空态/无命中在结果卡内居中，不再切换外层盒子（避免状态切换抖动）*/
.result-card :deep(.el-card__body) > .el-empty {
  margin: auto;
}
.load-row {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
  padding-bottom: 12px;
  margin-bottom: 12px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.hint {
  color: var(--app-muted-text);
  font-size: var(--app-font-size-caption);
}
.b-group {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
  margin-bottom: 10px;
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
  gap: var(--app-space-2);
  margin-top: 4px;
}
.dsl-help {
  margin-top: 10px;
  color: var(--app-muted-text);
  font-size: var(--app-font-size-caption);
  line-height: var(--app-line-height-reading);
}
.ast {
  margin: 12px 0 0;
  padding: 10px 12px;
  background: var(--el-fill-color-light);
  border-radius: 6px;
  font-size: var(--app-font-size-caption);
  color: var(--el-text-color-regular);
  max-height: 200px;
  overflow: auto;
}
.ver-link {
  font-size: var(--app-font-size-caption);
  color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
  border-radius: 10px;
  padding: 1px 8px;
  font-weight: var(--app-font-weight-section);
  cursor: pointer;
  user-select: none;
}
.ver-link:hover {
  background: var(--el-color-primary-light-7);
}
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
.run-bar {
  display: flex;
  align-items: center;
  gap: var(--app-space-3);
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px solid #ebeef5;
}
.run-hint {
  color: var(--app-placeholder-text);
  font-size: var(--app-font-size-caption);
}
.setting-item {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-2);
}
.setting-label {
  font-size: var(--app-font-size-body);
  color: var(--page-settings-text-subtle);
}
.cnt {
  color: var(--app-danger-text);
  font-size: var(--app-font-size-data);
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
.clickable :deep(.st-row) {
  background: #fef0f0;
}
</style>
