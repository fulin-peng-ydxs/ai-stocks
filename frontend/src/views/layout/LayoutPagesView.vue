<script setup lang="ts">
import AppTableColumn from '@/components/AppTableColumn.vue'
import AppDataTable from '@/components/AppDataTable.vue'
/**
 * 页面布局工作区（P4 布局平台 IA 重构）。
 *
 * 职责（plan.md §13.2 / requirement §5.7）：面向单个页面，把「页面默认配置 + 组件特性配置 +
 * 导入导出 + 校验报告」围绕同一页面工作台组织——顶部选页一次，下方各 Tab 共享该页上下文，
 * 不再像旧单页配置中心那样把页面配置/导入导出/报告散到无上下文的独立入口。
 *
 * 由原单页 LayoutConfigView 的「页面配置 + 导入导出(页面/用户/有效) + 校验报告」迁移而来，
 * 能力不丢失。预设维度归「预设管理」工作区，组件目录归「系统组件」工作区。
 * 实时布局预览、页面层组件默认值编辑与只读诊断在同一工作台内闭环。
 */
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import {
  getEffectiveLayoutConfig,
  getLayoutPageConfig,
  getLayoutUserConfig,
  listFieldPolicies,
  listLayoutPresets,
  resetLayoutConfig,
  saveLayoutPageConfig,
  saveLayoutUserConfig,
  validateLayoutConfig,
  type ComponentConfigLayer,
  type EffectiveLayoutConfig,
  type LayoutOverlayValue,
  type LayoutOverlayValues,
  type LayoutPageConfig,
  type LayoutPresetRecord,
  type LayoutUserConfig,
} from '@/api/layout'
import LayoutHost from '@/layout/components/LayoutHost.vue'
import ComponentAutoSettings from '@/components/ComponentAutoSettings.vue'
import AppStateBlock from '@/components/AppStateBlock.vue'
import AppIconButton from '@/components/AppIconButton.vue'
import LayoutPagePreview from '@/layout/components/LayoutPagePreview.vue'
import {
  listManagedPages,
  getPageEntry,
  getPageLayout,
  getComponentFieldDef,
  componentConfigPath,
  isComponentConfigPath,
  resolveComponentConfig,
  responsiveProfileLabel,
  type ComponentFieldDef,
  type ComponentFieldValue,
  type ComponentConfigSource,
  type PageRegistryEntry,
  type SlotSpec,
  type SlotConfigMeta,
} from '@/layout'
import { getErrorMessage } from '@/utils/error'

type TabKey = 'workbench' | 'import' | 'report'
type ExportScope = 'page' | 'user' | 'effective'

const pagesLayout = getPageLayout('layout-pages')

const managedPages = listManagedPages()

const tab = ref<TabKey>('workbench')
const selectedPageKey = ref(managedPages[0].pageKey)
// 点击预览里的 slot → 右侧组件配置定位高亮（Q5「点击预览即配置」）。
const focusedSlot = ref<string | null>(null)
function onPreviewFocus(slotId: string) {
  focusedSlot.value = slotId
}
const selectedUserId = ref('local')
const selectedPage = computed<PageRegistryEntry>(() => getPageEntry(selectedPageKey.value) ?? managedPages[0])

const presets = ref<LayoutPresetRecord[]>([])
const presetLoadError = ref('')
const presetOptions = computed(() => presets.value.filter((p) => p.enabled).map((p) => ({ label: p.name, value: p.key })))

const pageConfig = ref<LayoutPageConfig | null>(null)
const pageLoadError = ref('')
// 页面配置表单值按页面 editable 白名单 + 组件配置路径动态承载（不硬编码字段）。
const pageDraft = reactive<{ presetKey: string; values: LayoutOverlayValues }>({ presetKey: '', values: {} })
const pageSaving = ref(false)
const presetSyncing = ref(false)

/** 设置/清除某个页面级旋钮草稿值；空值视为"不覆盖"。 */
function setPageKnob(path: string, value: unknown): void {
  if (value === '' || value == null) delete pageDraft.values[path]
  else pageDraft.values[path] = value as LayoutOverlayValue
}
function getPageComponentOverride(slotId: string, field: string): unknown {
  return pageDraft.values[componentConfigPath(slotId, field)]
}
function setPageComponentValue(slotId: string, field: string, value: unknown): void {
  setPageKnob(componentConfigPath(slotId, field), value)
}

function componentPathValues(values: LayoutOverlayValues): Record<string, ComponentFieldValue> {
  const out: Record<string, ComponentFieldValue> = {}
  for (const [path, value] of Object.entries(values)) {
    if (isComponentConfigPath(path)) out[path] = value as ComponentFieldValue
  }
  return out
}

const CFD_RE = /^componentFieldDefaults\.([^.]+)\.([^.]+)$/
const pagePresetComponentValues = computed<Record<string, ComponentFieldValue>>(() => {
  const preset = presets.value.find((p) => p.key === pageDraft.presetKey)
  const raw = preset?.config.values ?? {}
  const out: Record<string, ComponentFieldValue> = {}
  for (const [path, value] of Object.entries(raw)) {
    const match = CFD_RE.exec(path)
    if (!match) continue
    const [, kind, field] = match
    for (const slot of selectedPage.value.layout.slots) {
      if (slot.component === kind) out[componentConfigPath(slot.id, field)] = value as ComponentFieldValue
    }
  }
  return out
})

const pageDefaultComponentResult = computed(() => resolveComponentConfig(selectedPage.value.layout, [
  { layer: 'preset', overlay: { values: pagePresetComponentValues.value } },
  { layer: 'page', overlay: { values: componentPathValues(pageDraft.values) } },
]))

function getPageComponentValue(slotId: string, field: string): unknown {
  return pageDefaultComponentResult.value.configBySlot[slotId]?.[field]
}

function getPageComponentSource(slotId: string, field: string): ComponentConfigSource {
  return pageDefaultComponentResult.value.source[componentConfigPath(slotId, field)] ?? 'default'
}

function getPageComponentLayerValues(slotId: string, field: string): Partial<Record<ComponentConfigSource, unknown>> {
  return pageDefaultComponentResult.value.perLayerValues[componentConfigPath(slotId, field)] ?? {}
}

// 系统组件「可覆盖范围」开放策略（layout_field_policy）：键 `${kind}.${field}` → 当前生效层集合。
// 挂载后拉一次；编辑器的可编辑判定与只读诊断都以此为准，与后端 _enforce_field_policy 同源，
// 避免出现「前端可改、保存时后端才报越权」的脱节。
const fieldPolicyMap = ref<Map<string, ComponentConfigLayer[]>>(new Map())
const fieldPolicyError = ref('')
async function reloadFieldPolicies() {
  fieldPolicyError.value = ''
  try {
    const { policies } = await listFieldPolicies()
    fieldPolicyMap.value = new Map(policies.map((p) => [`${p.componentKind}.${p.field}`, p.allowedLayers]))
  } catch (error) {
    fieldPolicyError.value = getErrorMessage(error, '组件字段策略加载失败')
  }
}
/** 某 (组件种类, 字段) 当前开放的层集合；无策略记录时回退代码最大集 def.layers。 */
function componentAllowedLayers(kind: string, field: string): ComponentConfigLayer[] | undefined {
  return fieldPolicyMap.value.get(`${kind}.${field}`)
}
/** 字段是否允许在指定层覆盖（策略优先，回退 def.layers）。 */
function policyAllows(kind: string, def: ComponentFieldDef, layer: ComponentConfigLayer): boolean {
  return (fieldPolicyMap.value.get(`${kind}.${def.key}`) ?? def.layers).includes(layer)
}

interface ComponentDiagnosticRow {
  slotId: string
  slot: string
  component: string
  field: string
  fieldLabel: string
  valueLabel: string
  sourceLabel: string
  layersLabel: string
  status: 'editable' | 'blocked' | 'missing-meta' | 'unknown'
  statusLabel: string
  detail: string
}

function canRenderPageComponentField(slotId: string, def: ComponentFieldDef): boolean {
  if (def.control === 'bool' || def.control === 'int' || def.control === 'number' || def.control === 'enum') return true
  if (def.control === 'string[]' && def.options?.length) return true
  const meta: SlotConfigMeta | undefined = selectedPage.value.componentMeta?.[slotId]
  if (def.key === 'defaultSort') return !!meta?.sortFields?.length
  if (def.key === 'hiddenColumns') return !!meta?.columns?.length
  if (def.key === 'defaultActive') return !!meta?.tabs?.length
  return false
}

function formatDiagnosticValue(value: unknown): string {
  if (value === undefined) return '未设置'
  if (value === null || value === '') return '不覆盖'
  if (Array.isArray(value)) return value.length ? value.join(', ') : '空数组'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function diagnosticValue(slot: SlotSpec, field: string): string {
  return formatDiagnosticValue(getPageComponentValue(slot.id, field))
}

function diagnosticSource(slot: SlotSpec, field: string): string {
  const source = getPageComponentSource(slot.id, field)
  if (source === 'default') return '代码默认'
  if (source === 'preset') return '页面预设'
  if (source === 'page') return '页面覆盖'
  return source
}

function diagnosticLayers(kind: string, def: ComponentFieldDef): string {
  return (fieldPolicyMap.value.get(`${kind}.${def.key}`) ?? def.layers).join(' / ')
}

const componentDiagnosticRows = computed<ComponentDiagnosticRow[]>(() => {
  const consumed = selectedPage.value.consumedComponentFields ?? {}
  const slots = new Map(selectedPage.value.layout.slots.map((s) => [s.id, s]))
  const rows: ComponentDiagnosticRow[] = []
  for (const [slotId, fields] of Object.entries(consumed)) {
    const slot = slots.get(slotId)
    if (!slot) {
      rows.push({
        slotId,
        slot: slotId,
        component: '—',
        field: fields.join(', '),
        fieldLabel: fields.join(', '),
        valueLabel: '—',
        sourceLabel: '—',
        layersLabel: '—',
        status: 'unknown',
        statusLabel: 'slot 未登记',
        detail: 'pageRegistry.consumedComponentFields 指向了不存在的 slot。',
      })
      continue
    }
    for (const field of fields) {
      const def = getComponentFieldDef(slot.component, field)
      if (!def) {
        rows.push({
          slotId,
          slot: slot.label || slot.id,
          component: slot.component,
          field,
          fieldLabel: field,
          valueLabel: '—',
          sourceLabel: '—',
          layersLabel: '—',
          status: 'unknown',
          statusLabel: '字段未登记',
          detail: '该字段未进入 COMPONENT_FIELD_DEFS，页面布局不会开放编辑。',
        })
        continue
      }
      if (!policyAllows(slot.component, def, 'page')) {
        rows.push({
          slotId,
          slot: slot.label || slot.id,
          component: slot.component,
          field,
          fieldLabel: def.label,
          valueLabel: diagnosticValue(slot, field),
          sourceLabel: diagnosticSource(slot, field),
          layersLabel: diagnosticLayers(slot.component, def),
          status: 'blocked',
          statusLabel: '不可编辑',
          detail: '「系统组件」已将该字段的可覆盖范围收紧，不含 page 层；此处不开放编辑，保存也会被后端拒绝。',
        })
        continue
      }
      if (!canRenderPageComponentField(slotId, def)) {
        rows.push({
          slotId,
          slot: slot.label || slot.id,
          component: slot.component,
          field,
          fieldLabel: def.label,
          valueLabel: diagnosticValue(slot, field),
          sourceLabel: diagnosticSource(slot, field),
          layersLabel: diagnosticLayers(slot.component, def),
          status: 'missing-meta',
          statusLabel: '缺少安全枚举',
          detail: '该字段需要页面提供列、排序字段或 tab 枚举；未提供时只做诊断展示。',
        })
        continue
      }
      rows.push({
        slotId,
        slot: slot.label || slot.id,
        component: slot.component,
        field,
        fieldLabel: def.label,
        valueLabel: diagnosticValue(slot, field),
        sourceLabel: diagnosticSource(slot, field),
        layersLabel: diagnosticLayers(slot.component, def),
        status: 'editable',
        statusLabel: '可编辑',
        detail: '已消费、允许 page 层覆盖，且具备安全控件元数据。',
      })
    }
  }
  return rows
})

function diagnosticTagType(status: ComponentDiagnosticRow['status']): 'success' | 'warning' | 'info' | 'danger' {
  if (status === 'editable') return 'success'
  if (status === 'missing-meta') return 'warning'
  if (status === 'blocked') return 'info'
  return 'danger'
}

const focusedSlotSpec = computed<SlotSpec | null>(() =>
  focusedSlot.value ? (selectedPage.value.layout.slots.find((s) => s.id === focusedSlot.value) ?? null) : null,
)
// 聚焦单个 slot：仅把该 slot 交给共享渲染器（page 层）。
const focusedSlotIds = computed<string[]>(() => (focusedSlot.value ? [focusedSlot.value] : []))
// 把页面草稿访问器包装成共享渲染器期望的「组件配置访问器」形状（page 层写值经页面草稿）。
const pageComponentConfig = {
  componentValueOf: getPageComponentValue,
  componentOverrideOf: getPageComponentOverride,
  componentSourceOf: getPageComponentSource,
  componentLayerValuesOf: getPageComponentLayerValues,
  setComponentKnob: setPageComponentValue,
}
const focusedDiagnosticRows = computed(() =>
  focusedSlot.value ? componentDiagnosticRows.value.filter((row) => row.slotId === focusedSlot.value) : [],
)

const exportScope = ref<ExportScope>('page')
const exportText = ref('')
const importText = ref('')
const importSaving = ref(false)

const reportLoading = ref(false)
const reportError = ref('')
const pageLoading = ref(true)
const effectiveConfig = ref<EffectiveLayoutConfig | null>(null)
const userConfig = ref<LayoutUserConfig | null>(null)
const pageValidationErrors = ref<string[]>([])
const userValidationErrors = ref<string[]>([])

async function reloadPresets(notify = false) {
  presetSyncing.value = true
  presetLoadError.value = ''
  try {
    const data = await listLayoutPresets(true)
    presets.value = data.presets
    if (notify) ElMessage.success('预设已同步')
  } catch (error) {
    presetLoadError.value = getErrorMessage(error, '布局预设加载失败')
  } finally {
    presetSyncing.value = false
  }
}

function pageDraftValues(): LayoutOverlayValues {
  // 回写：页面 editable 白名单内的 L2 旋钮 + 组件配置路径（slots.<id>.config.<field>）。空值视为"不覆盖"。
  const allowed = new Set(selectedPage.value.layout.editable.map((k) => k.path))
  const values: LayoutOverlayValues = {}
  for (const [path, value] of Object.entries(pageDraft.values)) {
    if (value === '' || value == null) continue
    if (allowed.has(path) || isComponentConfigPath(path)) values[path] = value
  }
  return values
}

async function loadPageConfig(options: { clearCurrent?: boolean } = {}) {
  if (options.clearCurrent) pageConfig.value = null
  pageLoading.value = true
  pageLoadError.value = ''
  try {
    const cfg = await getLayoutPageConfig(selectedPageKey.value)
    pageConfig.value = cfg
    pageDraft.presetKey = cfg.presetKey ?? ''
    for (const key of Object.keys(pageDraft.values)) delete pageDraft.values[key]
    const stored = cfg.config.values ?? {}
    for (const knob of selectedPage.value.layout.editable) {
      if (stored[knob.path] !== undefined) pageDraft.values[knob.path] = stored[knob.path]
    }
    for (const [path, value] of Object.entries(stored)) {
      if (isComponentConfigPath(path)) pageDraft.values[path] = value
    }
  } catch (error) {
    pageLoadError.value = getErrorMessage(error, '页面布局配置加载失败')
  } finally {
    pageLoading.value = false
  }
}

async function savePageConfig() {
  pageSaving.value = true
  try {
    const validation = await validateLayoutConfig({
      config: { values: pageDraftValues() },
      layout: selectedPage.value.layout as unknown as Record<string, unknown>,
    })
    if (!validation.valid) {
      ElMessage.error(validation.errors[0] || '页面配置校验失败')
      return
    }
    pageConfig.value = await saveLayoutPageConfig(selectedPageKey.value, {
      presetKey: pageDraft.presetKey || null,
      config: { values: pageDraftValues() },
      layout: selectedPage.value.layout as unknown as Record<string, unknown>,
    })
    ElMessage.success('页面默认布局已保存')
  } finally {
    pageSaving.value = false
  }
}

async function resetPageConfig() {
  await resetLayoutConfig({ scope: 'page', pageKey: selectedPageKey.value })
  ElMessage.success('页面配置已重置')
  await loadPageConfig()
}

async function buildExport() {
  if (exportScope.value === 'page') {
    const cfg = await getLayoutPageConfig(selectedPageKey.value)
    exportText.value = JSON.stringify({ type: 'layout-page-config', page: cfg }, null, 2)
    return
  }
  if (exportScope.value === 'user') {
    const cfg = await getLayoutUserConfig(selectedPageKey.value, selectedUserId.value)
    exportText.value = JSON.stringify({ type: 'layout-user-config', user: cfg }, null, 2)
    return
  }
  const cfg = await getEffectiveLayoutConfig(selectedPageKey.value, selectedUserId.value)
  exportText.value = JSON.stringify({ type: 'layout-effective-config', effective: cfg }, null, 2)
}

async function downloadExport() {
  if (!exportText.value) await buildExport()
  const blob = new Blob([exportText.value], { type: 'application/json;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `layout-${exportScope.value}-${selectedPageKey.value}.json`
  a.click()
  URL.revokeObjectURL(url)
}

function onImportFile(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (!file) return
  const reader = new FileReader()
  reader.onload = () => { importText.value = String(reader.result ?? '') }
  reader.readAsText(file, 'utf-8')
}

async function importConfig() {
  importSaving.value = true
  try {
    const parsed = JSON.parse(importText.value)
    const layout = selectedPage.value.layout as unknown as Record<string, unknown>
    if (parsed.type === 'layout-page-config') {
      const page = parsed.page
      const validation = await validateLayoutConfig({ config: page.config, layout })
      if (!validation.valid) {
        ElMessage.error(validation.errors[0] || '导入配置非法')
        return
      }
      await saveLayoutPageConfig(page.pageKey, { presetKey: page.presetKey, config: page.config, layout })
      ElMessage.success('页面配置导入完成')
      await loadPageConfig()
      return
    }
    if (parsed.type === 'layout-user-config') {
      const user = parsed.user
      const validation = await validateLayoutConfig({ config: user.config, layout })
      if (!validation.valid) {
        ElMessage.error(validation.errors[0] || '导入配置非法')
        return
      }
      await saveLayoutUserConfig(user.pageKey, { userId: user.userId, config: user.config, layout })
      ElMessage.success('用户配置导入完成')
      return
    }
    ElMessage.error('请导入页面/用户配置文件；预设请在「预设管理」工作区导入')
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '导入内容不是合法 JSON')
  } finally {
    importSaving.value = false
  }
}

async function runValidationReport() {
  reportLoading.value = true
  reportError.value = ''
  try {
    const layout = selectedPage.value.layout as unknown as Record<string, unknown>
    const page = await getLayoutPageConfig(selectedPageKey.value)
    const user = await getLayoutUserConfig(selectedPageKey.value, selectedUserId.value)
    const eff = await getEffectiveLayoutConfig(selectedPageKey.value, selectedUserId.value)
    const pageResult = await validateLayoutConfig({ config: page.config, layout })
    const userResult = await validateLayoutConfig({ config: user.config, layout })
    pageConfig.value = page
    userConfig.value = user
    effectiveConfig.value = eff
    pageValidationErrors.value = pageResult.errors
    userValidationErrors.value = userResult.errors
  } catch (error) {
    reportError.value = getErrorMessage(error, '校验报告加载失败')
  } finally {
    reportLoading.value = false
  }
}

async function resetUserConfig() {
  await resetLayoutConfig({ scope: 'user', pageKey: selectedPageKey.value, userId: selectedUserId.value })
  ElMessage.success('用户覆盖已重置')
  await runValidationReport()
}

function onTabChange(name: string | number) {
  if (name === 'report') runValidationReport()
}

const sourceRows = computed(() => {
  const eff = effectiveConfig.value
  if (!eff) return []
  return Object.entries(eff.values).map(([path, value]) => ({
    path,
    value,
    source: eff.source[path] ?? 'default',
  }))
})

watch(selectedPageKey, async () => {
  exportText.value = ''
  focusedSlot.value = null
  await loadPageConfig({ clearCurrent: true })
  if (tab.value === 'report') await runValidationReport()
})

onMounted(async () => {
  await reloadFieldPolicies()
  await reloadPresets()
  await loadPageConfig({ clearCurrent: true })
})
</script>

<template>
  <LayoutHost :layout="pagesLayout">
    <template #action>
      <div class="layout-toolbar">
        <div>
          <div class="page-title app-page-title">页面布局</div>
          <div class="page-subtitle app-body-text">面向单个页面的默认配置、组件特性、导入导出与校验报告（围绕同一页面）</div>
        </div>
        <div class="toolbar-actions">
          <el-select v-model="selectedPageKey" class="page-select">
            <el-option v-for="page in managedPages" :key="page.pageKey" :label="page.label" :value="page.pageKey" />
          </el-select>
        </div>
      </div>
    </template>

    <template #main>
      <div class="layout-pages-view" v-loading="pageLoading && !!pageConfig">
        <AppStateBlock
          v-if="pageLoading && !pageConfig"
          state="loading"
          title="正在加载页面布局配置…"
        />
        <AppStateBlock
          v-else-if="pageLoadError && !pageConfig"
          state="error"
          title="页面布局配置加载失败"
          :description="pageLoadError"
          retry
          @retry="loadPageConfig"
        />
        <template v-else>
        <AppStateBlock
          v-if="pageLoadError"
          state="error"
          size="compact"
          title="页面布局配置刷新失败"
          :description="pageLoadError"
          retry
          @retry="loadPageConfig"
        />
        <AppStateBlock
          v-if="presetLoadError"
          state="error"
          size="compact"
          title="布局预设加载失败"
          :description="presetLoadError"
          retry
          @retry="reloadPresets(true)"
        />
        <AppStateBlock
          v-if="fieldPolicyError"
          state="error"
          size="compact"
          title="组件字段策略加载失败"
          :description="fieldPolicyError"
          retry
          @retry="reloadFieldPolicies"
        />
        <el-tabs v-model="tab" class="config-tabs" @tab-change="onTabChange">
          <el-tab-pane label="预览与配置" name="workbench">
            <div class="workbench-pane">
            <section class="plain-panel source-panel">
              <div class="source-head">
                <div>
                  <div class="section-title app-section-title">布局源信息</div>
                  <div class="section-subtitle app-caption-text">来自页面注册表（pageRegistry）的单一事实源。</div>
                </div>
                <el-tag effect="plain">{{ selectedPage.path }} · {{ selectedPage.pageKey }}</el-tag>
              </div>
              <el-descriptions :column="4" size="small" border class="meta-desc">
                <el-descriptions-item label="原型">{{ selectedPage.archetype }}</el-descriptions-item>
                <el-descriptions-item label="目标响应式策略">{{ responsiveProfileLabel(selectedPage.responsiveProfile) }}</el-descriptions-item>
                <el-descriptions-item label="当前页面预设">{{ pageConfig?.presetKey || '继承全局' }}</el-descriptions-item>
                <el-descriptions-item label="组件配置">{{ selectedPage.supportsComponentConfig ? '已纳入页面默认配置' : '暂未开放' }}</el-descriptions-item>
                <el-descriptions-item label="组件槽位" :span="4">
                  <div class="slot-chips">
                    <el-tag v-for="s in selectedPage.layout.slots" :key="s.id" size="small" effect="plain">
                      {{ s.region }}:{{ s.component }}{{ s.growMain ? '(grow)' : '' }}
                    </el-tag>
                  </div>
                </el-descriptions-item>
              </el-descriptions>
              <el-collapse class="source-collapse">
                <el-collapse-item title="页面默认布局字段" name="editable">
                  <AppDataTable v-if="selectedPage.layout.editable.length" :data="selectedPage.layout.editable" max-height="140" size="small" embedded>
                    <AppTableColumn prop="label" label="字段" />
                    <AppTableColumn prop="path" label="路径" />
                    <AppTableColumn prop="type" label="类型" />
                    <AppTableColumn label="范围">
                      <template #default="{ row }">
                        {{ row.options?.join('/') || `${row.min ?? '-'} ~ ${row.max ?? '-'}` }}
                      </template>
                    </AppTableColumn>
                  </AppDataTable>
                  <el-empty v-if="!selectedPage.layout.editable.length" class="app-empty app-empty--tiny" description="该页无页面默认布局字段" />
                </el-collapse-item>
              </el-collapse>
            </section>

            <div class="page-config-grid">
              <!-- 左：结构示意预览（点击 slot → 右侧组件配置定位高亮，Q5）。 -->
              <section class="plain-panel preview-panel">
                <div class="section-title">{{ selectedPage.label }} · 结构示意预览</div>
                <div class="section-subtitle">点击任一 slot/组件 → 右侧定位其配置；按预览档位看列数退化路径。占位示意，不挂载真实组件。</div>
                <LayoutPagePreview
                  :key="selectedPageKey"
                  :layout="selectedPage.layout"
                  :profile="selectedPage.responsiveProfile"
                  class="preview-host"
                  @focus-slot="onPreviewFocus"
                />
              </section>

              <!-- 右：页面配置（默认预设 + 页面默认布局 + 组件特性配置 + 只读诊断，与左侧预览同屏一体）。 -->
              <section class="plain-panel config-panel">
                <div class="section-title">{{ selectedPage.label }} · 配置</div>
                <div class="section-subtitle">{{ selectedPage.path }} · {{ selectedPage.pageKey }}</div>
                <el-form label-position="top" class="config-form">
                  <el-form-item label="默认预设">
                    <div class="preset-picker-row">
                      <el-select v-model="pageDraft.presetKey" class="preset-select" clearable>
                        <el-option v-for="item in presetOptions" :key="item.value" :label="item.label" :value="item.value" />
                      </el-select>
                      <el-tooltip content="同步预设管理里的最新可选项和组件默认值" placement="top">
                        <AppIconButton
                          class="preset-sync-button"
                          label="同步预设"
                          variant="soft"
                          :loading="presetSyncing"
                          :native-title="false"
                          @click="reloadPresets(true)"
                        >
                          <el-icon><Refresh /></el-icon>
                        </AppIconButton>
                      </el-tooltip>
                    </div>
                  </el-form-item>
                  <!-- 页面级旋钮按本页 editable 白名单动态渲染（不再手写字段）。 -->
                  <el-form-item v-for="knob in selectedPage.layout.editable" :key="knob.path" :label="knob.label">
                    <el-select
                      v-if="knob.type === 'enum'"
                      :model-value="pageDraft.values[knob.path] ?? ''"
                      clearable
                      placeholder="不覆盖"
                      @update:model-value="(v: unknown) => setPageKnob(knob.path, v)"
                    >
                      <el-option
                        v-for="opt in knob.options"
                        :key="String(opt)"
                        :label="knob.optionLabels?.[String(opt)] ?? String(opt)"
                        :value="opt"
                      />
                    </el-select>
                    <el-switch
                      v-else-if="knob.type === 'bool'"
                      :model-value="Boolean(pageDraft.values[knob.path])"
                      @update:model-value="(v: string | number | boolean) => setPageKnob(knob.path, v)"
                    />
                    <el-input-number
                      v-else
                      :model-value="(pageDraft.values[knob.path] as number)"
                      :min="knob.min"
                      :max="knob.max"
                      :step="knob.type === 'int' ? 10 : undefined"
                      @update:model-value="(v: number | undefined) => setPageKnob(knob.path, v ?? '')"
                    />
                  </el-form-item>
                  <el-empty
                    v-if="!selectedPage.layout.editable.length"
                    class="app-empty app-empty--compact"
                    description="该页面未开放页面级布局旋钮"
                  />
                </el-form>

                <!-- 组件特性配置（页面层）：复用与设置抽屉同一渲染器 ComponentAutoSettings（page 层、聚焦单 slot、按策略门控、可清除）。 -->
                <template v-if="selectedPage.supportsComponentConfig">
                  <div class="cc-block-title">组件特性配置</div>
                  <div class="section-subtitle">点击左侧预览里的某个 slot 后，这里展示代码默认、页面预设和页面覆盖合并后的页面默认值。个人偏好仍在各页面设置抽屉里调整。</div>
                  <!-- 受约束宽度容器：还原共享渲染器在窄抽屉里的密度，避免分段控件在宽面板被拉爆/溢出。 -->
                  <div v-if="focusedSlotSpec" class="cc-cfg-host">
                    <div class="focused-slot-card">
                      <div class="diag-main">{{ focusedSlotSpec.label || focusedSlotSpec.id }}</div>
                      <div class="muted">{{ focusedSlotSpec.id }} · {{ focusedSlotSpec.component }} · {{ focusedSlotSpec.region }}</div>
                    </div>
                    <ComponentAutoSettings
                      :page-key="selectedPageKey"
                      :config="pageComponentConfig"
                      layer="page"
                      :slot-ids="focusedSlotIds"
                      :allowed-layers-of="componentAllowedLayers"
                      :show-slot-title="false"
                      clearable
                    />
                  </div>
                  <el-empty
                    v-else
                    class="app-empty app-empty--compact"
                    description="点击左侧预览中的一个组件后，在这里编辑它的页面默认配置"
                  />
                </template>

                <div class="cc-block-title">只读诊断</div>
                <div class="section-subtitle">只显示当前点击 slot 的页面默认值、可覆盖范围和安全枚举诊断；不可编辑字段只在这里解释原因。</div>
                <AppDataTable v-if="focusedDiagnosticRows.length" :data="focusedDiagnosticRows" max-height="220" size="small" class="diagnostic-table" embedded>
                  <AppTableColumn label="字段">
                    <template #default="{ row }">
                      <div class="diag-main">{{ row.fieldLabel }}</div>
                      <div class="muted">{{ row.field }}</div>
                    </template>
                  </AppTableColumn>
                  <AppTableColumn label="页面默认值">
                    <template #default="{ row }">
                      <div class="diag-main">{{ row.valueLabel }}</div>
                      <div class="muted">{{ row.sourceLabel }}</div>
                    </template>
                  </AppTableColumn>
                  <AppTableColumn label="可覆盖范围">
                    <template #default="{ row }">
                      <span class="muted">{{ row.layersLabel }}</span>
                    </template>
                  </AppTableColumn>
                  <AppTableColumn label="状态">
                    <template #default="{ row }">
                      <el-tag size="small" :type="diagnosticTagType(row.status)" effect="plain">{{ row.statusLabel }}</el-tag>
                    </template>
                  </AppTableColumn>
                  <AppTableColumn prop="detail" label="说明" show-overflow-tooltip />
                </AppDataTable>
                <el-empty
                  v-if="!focusedDiagnosticRows.length"
                  class="app-empty app-empty--compact"
                  :description="focusedSlotSpec ? '当前 slot 暂无组件字段消费诊断' : '点击左侧预览中的一个组件后查看诊断'"
                />

                <div class="button-row cc-save-row">
                  <el-button v-permission="'layout:page-manage'" type="primary" :loading="pageSaving" @click="savePageConfig">保存页面配置</el-button>
                  <el-button v-permission="'layout:page-manage'" @click="resetPageConfig">重置页面配置</el-button>
                </div>
              </section>
            </div>
            </div>
          </el-tab-pane>

          <el-tab-pane label="导入导出" name="import">
            <div class="import-grid">
              <section class="plain-panel">
                <div class="section-title">导出</div>
                <div class="section-subtitle">导出当前页面的页面/用户/有效配置；预设导出在「预设管理」工作区。</div>
                <div class="inline-controls">
                  <el-select v-model="exportScope">
                    <el-option label="当前页面配置" value="page" />
                    <el-option label="当前用户配置" value="user" />
                    <el-option label="当前有效配置" value="effective" />
                  </el-select>
                  <el-button @click="buildExport">生成</el-button>
                  <el-button @click="downloadExport">下载</el-button>
                </div>
                <el-input v-model="exportText" type="textarea" :rows="16" spellcheck="false" />
              </section>

              <section class="plain-panel">
                <div class="section-title">导入</div>
                <div class="section-subtitle">导入前会校验 schema version、路径、取值域、组件归属。</div>
                <input class="file-input" type="file" accept="application/json,.json" @change="onImportFile" />
                <el-input v-model="importText" type="textarea" :rows="16" spellcheck="false" placeholder="粘贴导出的页面/用户配置 JSON" />
                <div class="button-row">
                  <el-button v-permission="'layout:page-manage'" type="primary" :loading="importSaving" @click="importConfig">校验并导入</el-button>
                </div>
              </section>
            </div>
          </el-tab-pane>

          <el-tab-pane label="校验报告" name="report">
            <div class="tab-head">
              <div>
                <div class="section-title">校验报告</div>
                <div class="section-subtitle">检查当前页面配置和用户覆盖，并展示字段来源。</div>
              </div>
              <div class="toolbar-actions">
                <el-input v-model="selectedUserId" class="user-input" placeholder="userId" />
                <el-button v-permission="'layout:page-manage'" type="primary" :loading="reportLoading" @click="runValidationReport">重新校验</el-button>
                <el-button v-permission="'layout:page-manage'" @click="resetUserConfig">重置用户覆盖</el-button>
              </div>
            </div>

            <div class="report-grid">
              <section class="plain-panel">
                <div class="section-title">错误项</div>
                <AppStateBlock
                  v-if="reportError"
                  state="error"
                  size="compact"
                  title="校验报告加载失败"
                  :description="reportError"
                  retry
                  @retry="runValidationReport"
                />
                <el-alert
                  v-if="!reportError && !pageValidationErrors.length && !userValidationErrors.length"
                  type="success"
                  title="当前页面配置和用户覆盖均通过校验"
                  :closable="false"
                />
                <el-alert
                  v-for="err in [...pageValidationErrors, ...userValidationErrors]"
                  :key="err"
                  type="error"
                  :title="err"
                  :closable="false"
                  class="report-alert"
                />
              </section>

              <section class="plain-panel">
                <div class="section-title">字段来源</div>
                <AppDataTable :data="sourceRows" height="320" embedded>
                  <AppTableColumn prop="path" label="路径" />
                  <AppTableColumn prop="value" label="值" />
                  <AppTableColumn prop="source" label="来源" />
                </AppDataTable>
              </section>
            </div>
          </el-tab-pane>
        </el-tabs>
        </template>
      </div>
    </template>
  </LayoutHost>
</template>

<style scoped>
.layout-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-4);
  padding: 14px 16px;
  border: 1px solid var(--el-border-color);
  background: var(--el-bg-color);
  border-radius: 6px;
}
.page-title {
  font-size: var(--app-font-size-title-md);
  font-weight: var(--app-font-weight-strong);
  color: var(--el-text-color-primary);
}
.page-subtitle,
.section-subtitle,
.muted {
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
}
.toolbar-actions,
.inline-controls,
.button-row {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
}
.page-select {
  width: 180px;
}
.layout-pages-view {
  height: 100%;
  min-height: 0;
  padding: 0 2px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.config-tabs {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.config-tabs :deep(.el-tabs__content) {
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}
.config-tabs :deep(.el-tab-pane) {
  height: 100%;
  min-height: 0;
  overflow: hidden;
}
.workbench-pane {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: var(--app-space-3);
  overflow: hidden;
}
.tab-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-4);
  margin-bottom: 12px;
}
.section-title {
  font-size: var(--app-font-size-section-title);
  font-weight: var(--app-font-weight-strong);
  color: var(--el-text-color-primary);
}
.page-config-grid,
.import-grid,
.report-grid {
  display: grid;
  grid-template-columns: minmax(320px, 0.85fr) minmax(360px, 1.15fr);
  gap: var(--app-space-3);
}
.page-config-grid {
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}
.import-grid,
.report-grid {
  height: 100%;
  min-height: 0;
  overflow: hidden;
}
.plain-panel {
  min-width: 0;
  min-height: 0;
  border: 1px solid var(--el-border-color);
  background: var(--el-bg-color);
  border-radius: 6px;
  padding: 14px;
}
.preview-panel,
.config-panel,
.import-grid > .plain-panel,
.report-grid > .plain-panel {
  overflow: auto;
}
.source-panel {
  flex: 0 0 auto;
}
.source-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--app-space-3);
}
.source-collapse {
  margin-top: 8px;
}
.config-form {
  margin-top: 14px;
}
.preset-picker-row {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
  width: 100%;
}
.preset-select {
  flex: 1 1 auto;
  min-width: 0;
}
.preset-sync-button {
  flex: 0 0 32px;
}
.preview-host {
  margin-top: 12px;
}
.cc-block-title {
  margin-top: 16px;
  font-size: var(--app-font-size-body);
  font-weight: var(--app-font-weight-section);
  color: var(--el-text-color-primary);
}
.cc-save-row {
  margin-top: 16px;
}
.diagnostic-table {
  margin-top: 10px;
}
.cc-cfg-host {
  /* 与同卡片内的「默认预设/信息密度」等控件一致填满面板内容宽，避免窄一截、不对齐的空盒子观感。 */
  width: 100%;
}
.focused-slot-card {
  margin-top: 10px;
  margin-bottom: 10px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  padding: 10px 12px;
  background: var(--el-fill-color-light);
}
.diag-main {
  font-weight: var(--app-font-weight-section);
  color: var(--el-text-color-primary);
}
.meta-desc {
  margin-top: 12px;
}
.slot-chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--app-space-control-gap);
}
.file-input {
  display: block;
  margin: 12px 0;
  color: var(--el-text-color-regular);
}
.report-alert {
  margin-top: 8px;
}
.user-input {
  width: 140px;
}
@media (max-width: 980px) {
  .layout-toolbar,
  .tab-head {
    align-items: stretch;
    flex-direction: column;
  }
  .page-config-grid,
  .import-grid,
  .report-grid {
    grid-template-columns: 1fr;
    overflow: auto;
  }
  .toolbar-actions,
  .inline-controls,
  .button-row {
    flex-wrap: wrap;
  }
}
</style>
