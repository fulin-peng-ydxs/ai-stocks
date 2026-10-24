<script setup lang="ts">
import AppForm from '@/components/AppForm.vue'
import { provideTradeDisciplineCategories, tradeConditionMeta } from '@/composables/useTradeDisciplineCategories'
import AppSelect from '@/components/AppSelect.vue'
import AppScrollArea from '@/components/AppScrollArea.vue'
import { useMenuPageTitle } from '@/composables/useMenuPageTitle'
import AppTableColumn from '@/components/AppTableColumn.vue'
import AppDataTable from '@/components/AppDataTable.vue'
import AppAsyncRegion from '@/components/AppAsyncRegion.vue'
import AppTabToolbar from '@/components/AppTabToolbar.vue'
/**
 * 页面布局工作区（P4 布局平台 IA 重构）。
 *
 * 职责（plan.md §13.2 / requirement §5.7）：面向单个页面，把「页面默认配置 + 组件特性配置 +
 * 导入导出 + 校验报告」围绕同一页面工作台组织——顶部选页一次，下方各 Tab 共享该页上下文，
 * 不再像旧单页配置中心那样把页面配置/导入导出/报告散到无上下文的独立入口。
 *
 * 由原单页 LayoutConfigView 的「页面配置 + 导入导出(页面/用户/有效) + 校验报告」迁移而来，
 * 能力不丢失。预设维度归「视觉预设」工作区，组件目录归「系统组件」工作区。
 * 实时布局预览、页面层组件默认值编辑与只读诊断在同一工作台内闭环。
 */
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getEffectiveLayoutConfig,
  getLayoutPageConfig,
  getLayoutUserConfig,
  listFieldPolicies,
  resetLayoutConfig,
  saveLayoutPageConfig,
  saveLayoutUserConfig,
  validateLayoutConfig,
  type ComponentConfigLayer,
  type EffectiveLayoutConfig,
  type LayoutOverlayValue,
  type LayoutOverlayValues,
  type LayoutPageConfig,
} from '@/api/layout'
import LayoutHost from '@/layout/components/LayoutHost.vue'
import ComponentAutoSettings from '@/components/ComponentAutoSettings.vue'
import HelpHint from '@/components/HelpHint.vue'
import AppStatusNotice from '@/components/AppStatusNotice.vue'
import LayoutPagePreview from '@/layout/components/LayoutPagePreview.vue'
import LayoutConfigTransferPanel from '@/layout/components/LayoutConfigTransferPanel.vue'
import {
  listManagedPages,
  getPageEntry,
  getPageLayout,
  getComponentFieldDefs,
  componentFieldApplicability,
  componentMetaForSlot,
  componentConfigPath,
  isComponentConfigPath,
  resolveComponentConfig,
  responsiveProfileLabel,
  type ComponentFieldDef,
  type ComponentFieldValue,
  type ComponentConfigSource,
  type PageRegistryEntry,
  type SlotSpec,
} from '@/layout'
import { getErrorMessage } from '@/utils/error'
import { useFormChangeTracker } from '@/composables/useFormChangeTracker'
import { createLatestRequestGuard } from '@/utils/latestRequestGuard'

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
const selectedPage = computed<PageRegistryEntry>(() => getPageEntry(selectedPageKey.value) ?? managedPages[0])
const conditionDictionary = provideTradeDisciplineCategories()
const dictionaryMeta = computed(() => selectedPageKey.value === 'trade-discipline' ? tradeConditionMeta(conditionDictionary.categories.value) : {})
watch(selectedPageKey, key => { if (key === 'trade-discipline') void conditionDictionary.load() }, { immediate: true })

const densityLabels: Record<string, string> = {
  compact: '紧凑',
  standard: '标准',
  comfortable: '宽松',
}

const pageConfig = ref<LayoutPageConfig | null>(null)
const pageLoadError = ref('')
// 页面配置表单值按页面 editable 白名单 + 组件配置路径动态承载（不硬编码字段）。
const pageDraft = reactive<{ values: LayoutOverlayValues }>({ values: {} })
const pageSaving = ref(false)
const pageResetting = ref(false)
const userResetting = ref(false)
const pageDensityLabel = computed(() => {
  const density = String(pageDraft.values.density ?? selectedPage.value.layout.density)
  return densityLabels[density] ?? density
})

/** 设置/清除某个页面级旋钮草稿值；空值视为"不覆盖"。 */
function setPageKnob(path: string, value: unknown): void {
  if (operationBusy.value) return
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

const pageDefaultComponentResult = computed(() => resolveComponentConfig(selectedPage.value.layout, [
  { layer: 'page', overlay: { values: componentPathValues(pageDraft.values) } },
], {
  metaBySlot: Object.fromEntries(selectedPage.value.layout.slots.map((slot) => [
    slot.id,
    componentMetaForSlot(selectedPage.value, slot),
  ])),
  allowedLayersOf: (kind, field) => componentAllowedLayers(kind, field),
}))

function getPageComponentValue(slotId: string, field: string): unknown {
  if (selectedPageKey.value === 'trade-discipline' && slotId === 'stockConditions' && field === 'defaultCollapsed'
    && getPageComponentOverride(slotId, field) === undefined) {
    return tradeConditionMeta(conditionDictionary.categories.value).stockConditions.collapseSections.map(item => item.key)
  }
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
  status: 'editable' | 'blocked' | 'not-applicable' | 'unknown'
  statusLabel: string
  detail: string
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
  if (source === 'page') return '页面覆盖'
  return source
}

function diagnosticLayers(kind: string, def: ComponentFieldDef): string {
  return (fieldPolicyMap.value.get(`${kind}.${def.key}`) ?? def.layers).join(' / ')
}

const componentDiagnosticRows = computed<ComponentDiagnosticRow[]>(() => {
  const rows: ComponentDiagnosticRow[] = []
  for (const slot of selectedPage.value.layout.slots) {
    const meta = componentMetaForSlot(selectedPage.value, slot)
    for (const def of getComponentFieldDefs(slot.component)) {
      const field = def.key
      const applicability = componentFieldApplicability(def, meta)
      if (!applicability.applicable) {
        rows.push({
          slotId: slot.id,
          slot: slot.label || slot.id,
          component: slot.component,
          field,
          fieldLabel: def.label,
          valueLabel: '—',
          sourceLabel: '组件实例',
          layersLabel: diagnosticLayers(slot.component, def),
          status: 'not-applicable',
          statusLabel: '不适用',
          detail: applicability.reason,
        })
        continue
      }
      if (!policyAllows(slot.component, def, 'page')) {
        rows.push({
          slotId: slot.id,
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
      rows.push({
        slotId: slot.id,
        slot: slot.label || slot.id,
        component: slot.component,
        field,
        fieldLabel: def.label,
        valueLabel: diagnosticValue(slot, field),
        sourceLabel: diagnosticSource(slot, field),
        layersLabel: diagnosticLayers(slot.component, def),
        status: 'editable',
        statusLabel: '可编辑',
        detail: '由组件种类自动继承，允许 page 层覆盖，且组件实例适用。',
      })
    }
  }
  return rows
})

function diagnosticTagType(status: ComponentDiagnosticRow['status']): 'success' | 'warning' | 'info' | 'danger' {
  if (status === 'editable') return 'success'
  if (status === 'not-applicable') return 'warning'
  if (status === 'blocked') return 'info'
  return 'danger'
}

const focusedSlotSpec = computed<SlotSpec | null>(() =>
  focusedSlot.value ? (selectedPage.value.layout.slots.find((s) => s.id === focusedSlot.value) ?? null) : null,
)
const focusedSlotHint = computed(() => focusedSlotSpec.value
  ? componentMetaForSlot(selectedPage.value, focusedSlotSpec.value).hint
  : undefined)
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
const exportAction = ref<'generate' | 'download' | null>(null)
const exportError = ref('')
const importText = ref('')
const importSaving = ref(false)

const reportLoading = ref(false)
const reportError = ref('')
const reportReady = ref(false)
const pageLoading = ref(true)
const effectiveConfig = ref<EffectiveLayoutConfig | null>(null)
const pageValidationErrors = ref<string[]>([])
const userValidationErrors = ref<string[]>([])
const pageRequest = createLatestRequestGuard()
const reportRequest = createLatestRequestGuard()
const operationBusy = computed(() => pageSaving.value || pageResetting.value
  || userResetting.value || importSaving.value || Boolean(exportAction.value) || reportLoading.value)
const contextLocked = computed(() => pageLoading.value || operationBusy.value)

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

const { hasChanges: pageConfigChanged, captureBaseline: capturePageConfigBaseline } = useFormChangeTracker(
  () => ({ pageKey: selectedPageKey.value, values: pageDraftValues() }),
)

async function loadPageConfig(options: { clearCurrent?: boolean } = {}) {
  const pageKey = selectedPageKey.value
  const requestId = pageRequest.begin()
  if (options.clearCurrent) pageConfig.value = null
  pageLoading.value = true
  pageLoadError.value = ''
  try {
    const cfg = await getLayoutPageConfig(pageKey)
    if (!pageRequest.isCurrent(requestId) || pageKey !== selectedPageKey.value) return
    pageConfig.value = cfg
    for (const key of Object.keys(pageDraft.values)) delete pageDraft.values[key]
    const stored = cfg.config.values ?? {}
    for (const knob of selectedPage.value.layout.editable) {
      if (stored[knob.path] !== undefined) pageDraft.values[knob.path] = stored[knob.path]
    }
    for (const [path, value] of Object.entries(stored)) {
      if (isComponentConfigPath(path)) pageDraft.values[path] = value
    }
    capturePageConfigBaseline()
  } catch (error) {
    if (!pageRequest.isCurrent(requestId) || pageKey !== selectedPageKey.value) return
    pageLoadError.value = getErrorMessage(error, '页面布局配置加载失败')
  } finally {
    if (pageRequest.isCurrent(requestId)) pageLoading.value = false
  }
}

const pageRegionError = computed(() => pageLoadError.value || fieldPolicyError.value)
const pageRegionErrorTitle = computed(() => {
  if (pageLoadError.value) return pageConfig.value ? '页面布局配置刷新失败' : '页面布局配置加载失败'
  return '组件字段策略加载失败'
})

/** 依赖任一失败时整区由 error 接管；重试统一恢复页面配置及其两个必要依赖。 */
async function retryPageRegion() {
  await Promise.all([loadPageConfig(), reloadFieldPolicies()])
}

async function savePageConfig() {
  if (contextLocked.value || !pageConfigChanged.value) return
  const pageKey = selectedPageKey.value
  // 校验和落库必须消费同一份草稿，不能在两次请求之间重新读取表单。
  const values: LayoutOverlayValues = JSON.parse(JSON.stringify(pageDraftValues()))
  const layout = selectedPage.value.layout as unknown as Record<string, unknown>
  pageSaving.value = true
  try {
    const validation = await validateLayoutConfig({
      config: { values },
      layout,
    })
    if (!validation.valid) {
      ElMessage.error(validation.errors[0] || '页面配置校验失败')
      return
    }
    const saved = await saveLayoutPageConfig(pageKey, {
      presetKey: null,
      config: { values },
      layout,
    })
    if (pageKey === selectedPageKey.value) {
      pageConfig.value = saved
      capturePageConfigBaseline()
      exportText.value = ''
    }
    ElMessage.success('页面默认布局已保存')
  } catch {
    // API 拦截器已展示失败原因；保留草稿与原基线，允许重试。
  } finally {
    pageSaving.value = false
  }
}

async function resetPageConfig() {
  if (contextLocked.value) return
  const pageKey = selectedPageKey.value
  const pageLabel = selectedPage.value.label
  pageResetting.value = true
  try {
    try {
      await ElMessageBox.confirm(
        `确认将「${pageLabel}」的页面布局和组件默认配置恢复为系统初始值？这将影响所有用户的页面默认设置，并丢弃当前未保存修改；各用户的个性化覆盖会保留。`,
        '恢复页面系统默认',
        { type: 'warning', confirmButtonText: '恢复默认', cancelButtonText: '取消', confirmButtonType: 'warning' },
      )
    } catch { return }
    await resetLayoutConfig({ scope: 'page', pageKey })
    exportText.value = ''
    ElMessage.success('所选页面已恢复系统默认配置')
    if (pageKey === selectedPageKey.value) await loadPageConfig()
  } catch {
    // API 拦截器已展示失败原因；失败时保留当前配置。
  } finally {
    pageResetting.value = false
  }
}

async function readExport(pageKey: string, scope: ExportScope): Promise<string> {
  if (scope === 'page') {
    const cfg = await getLayoutPageConfig(pageKey)
    return JSON.stringify({ type: 'layout-page-config', page: cfg }, null, 2)
  }
  if (scope === 'user') {
    const cfg = await getLayoutUserConfig(pageKey)
    return JSON.stringify({ type: 'layout-user-config', user: cfg }, null, 2)
  }
  const cfg = await getEffectiveLayoutConfig(pageKey)
  return JSON.stringify({ type: 'layout-effective-config', effective: cfg }, null, 2)
}

/** 生成与下载共享在途锁，下载缺少内容时在同一次操作内生成。 */
async function runExport(action: 'generate' | 'download') {
  if (contextLocked.value) return
  const pageKey = selectedPageKey.value
  const scope = exportScope.value
  exportAction.value = action
  exportError.value = ''
  try {
    const content = action === 'download' && exportText.value
      ? exportText.value : await readExport(pageKey, scope)
    if (pageKey !== selectedPageKey.value || scope !== exportScope.value) return
    exportText.value = content
    if (action === 'download') {
      const url = URL.createObjectURL(new Blob([content], { type: 'application/json;charset=utf-8' }))
      try {
        const a = document.createElement('a')
        a.href = url
        a.download = `layout-${scope}-${pageKey}.json`
        a.click()
      } finally { URL.revokeObjectURL(url) }
    }
  } catch (error) {
    exportError.value = getErrorMessage(error, '配置导出失败，请重试')
  } finally {
    exportAction.value = null
  }
}

function onImportFile(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (!file) return
  const reader = new FileReader()
  reader.onload = () => { importText.value = String(reader.result ?? '') }
  reader.readAsText(file, 'utf-8')
}

async function importConfig() {
  if (contextLocked.value || !importText.value.trim()) return
  const pageKey = selectedPageKey.value
  const layout = selectedPage.value.layout as unknown as Record<string, unknown>
  importSaving.value = true
  try {
    const parsed = JSON.parse(importText.value)
    const imported = parsed?.type === 'layout-page-config' ? parsed.page
      : parsed?.type === 'layout-user-config' ? parsed.user : null
    if (!imported?.config || imported.pageKey !== pageKey) {
      ElMessage.error('请选择与当前页面一致的页面/用户配置文件')
      return
    }
    if (parsed.type === 'layout-page-config') {
      const page = parsed.page
      const validation = await validateLayoutConfig({ config: page.config, layout })
      if (!validation.valid) {
        ElMessage.error(validation.errors[0] || '导入配置非法')
        return
      }
      await saveLayoutPageConfig(pageKey, { presetKey: null, config: page.config, layout })
      ElMessage.success('页面配置导入完成')
      if (pageKey === selectedPageKey.value) await loadPageConfig()
      exportText.value = ''
      return
    }
    if (parsed.type === 'layout-user-config') {
      const user = parsed.user
      const validation = await validateLayoutConfig({ config: user.config, layout })
      if (!validation.valid) {
        ElMessage.error(validation.errors[0] || '导入配置非法')
        return
      }
      // 用户归属始终由后端登录上下文确定，不沿用导出文件的用户标识。
      await saveLayoutUserConfig(pageKey, { config: user.config, layout })
      exportText.value = ''
      ElMessage.success('当前登录用户的配置导入完成')
      return
    }
    ElMessage.error('请导入页面/用户配置文件；预设请在「视觉预设」工作区导入')
  } catch (e) {
    ElMessage.error(getErrorMessage(e, '配置文件格式不正确，请检查后重新导入'))
  } finally {
    importSaving.value = false
  }
}

async function runValidationReport() {
  if (contextLocked.value) return
  const pageKey = selectedPageKey.value
  const requestId = reportRequest.begin()
  const layout = selectedPage.value.layout as unknown as Record<string, unknown>
  reportLoading.value = true
  reportError.value = ''
  try {
    const [page, user, eff] = await Promise.all([
      getLayoutPageConfig(pageKey), getLayoutUserConfig(pageKey), getEffectiveLayoutConfig(pageKey),
    ])
    const [pageResult, userResult] = await Promise.all([
      validateLayoutConfig({ config: page.config, layout }),
      validateLayoutConfig({ config: user.config, layout }),
    ])
    if (!reportRequest.isCurrent(requestId) || pageKey !== selectedPageKey.value) return
    effectiveConfig.value = eff
    pageValidationErrors.value = pageResult.errors
    userValidationErrors.value = userResult.errors
    reportReady.value = true
  } catch (error) {
    if (!reportRequest.isCurrent(requestId) || pageKey !== selectedPageKey.value) return
    reportError.value = getErrorMessage(error, '校验报告加载失败')
  } finally {
    if (reportRequest.isCurrent(requestId)) reportLoading.value = false
  }
}

async function resetUserConfig() {
  if (contextLocked.value) return
  const pageKey = selectedPageKey.value
  const pageLabel = selectedPage.value.label
  let reset = false
  userResetting.value = true
  try {
    try {
      await ElMessageBox.confirm(
        `确认清除当前登录用户在「${pageLabel}」页面的全部个性化覆盖？`,
        '清除用户覆盖',
        { type: 'warning', confirmButtonText: '清除覆盖', cancelButtonText: '取消', confirmButtonType: 'danger' },
      )
    } catch { return }
    await resetLayoutConfig({ scope: 'user', pageKey })
    exportText.value = ''
    ElMessage.success('当前登录用户的覆盖已清除')
    reset = true
  } catch {
    // API 拦截器已展示失败原因；不误报清除成功。
  } finally {
    userResetting.value = false
  }
  if (reset && pageKey === selectedPageKey.value) await runValidationReport()
}

function onTabChange(name: string | number) {
  if (name === 'report') runValidationReport()
}

const sourceRows = computed(() => {
  const eff = effectiveConfig.value
  if (!eff) return []
  return Object.entries(eff.values).map(([path, value]) => ({
    path,
    value: formatDiagnosticValue(value),
    source: eff.source[path] ?? 'default',
  }))
})

watch(selectedPageKey, async () => {
  exportText.value = ''
  exportError.value = ''
  reportRequest.invalidate()
  reportLoading.value = false
  reportReady.value = false
  reportError.value = ''
  effectiveConfig.value = null
  pageValidationErrors.value = []
  userValidationErrors.value = []
  focusedSlot.value = null
  await loadPageConfig({ clearCurrent: true })
  if (tab.value === 'report') await runValidationReport()
})

watch(exportScope, () => { exportText.value = ''; exportError.value = '' })

onMounted(async () => {
  await reloadFieldPolicies()
  await loadPageConfig({ clearCurrent: true })
})
const menuPageTitle = useMenuPageTitle()
</script>

<template>
  <LayoutHost :layout="pagesLayout">
    <template #action>
      <div class="lh-action">
        <div class="page-head">
          <div>
            <h2 class="app-page-title">{{ menuPageTitle }}</h2>
            <p class="page-subtitle">配置单个页面的默认布局、组件特性、导入导出与校验报告。</p>
          </div>
          <div class="page-head-actions">
            <AppSelect
              v-model="selectedPageKey"
              class="page-select"
              aria-label="选择配置页面"
              :disabled="contextLocked"
            >
              <el-option v-for="page in managedPages" :key="page.pageKey" :label="page.label" :value="page.pageKey" />
            </AppSelect>
          </div>
        </div>
      </div>
    </template>

    <template #main>
      <AppAsyncRegion
        class="layout-pages-view"
        :loading="pageLoading"
        :has-content="Boolean(pageConfig)"
        :error="pageRegionError"
        loading-title="正在加载页面布局配置…"
        :error-title="pageRegionErrorTitle"
        empty-title="暂无页面布局配置"
        retry
        @retry="retryPageRegion"
      >
        <el-tabs v-model="tab" class="config-tabs" :before-leave="() => !operationBusy" @tab-change="onTabChange">
          <el-tab-pane label="页面设计" name="workbench">
            <div class="workbench-pane">
            <section class="app-surface plain-panel source-panel">
              <div class="source-head">
                <div class="source-identity">
                  <div class="section-title app-section-title">页面结构</div>
                  <el-tag type="info" size="small" effect="plain">{{ selectedPage.archetype }}</el-tag>
                  <el-tag type="info" size="small" effect="plain">{{ responsiveProfileLabel(selectedPage.responsiveProfile) }}</el-tag>
                </div>
                <span class="source-path app-caption-text">{{ selectedPage.path }} · {{ selectedPage.pageKey }}</span>
              </div>
              <div class="source-facts">
                <span>槽位 <strong>{{ selectedPage.layout.slots.length }}</strong></span>
                <span>页面密度 <strong>{{ pageDensityLabel }}</strong></span>
                <span>组件设置 <strong>{{ selectedPage.supportsComponentConfig ? '可配置' : '未开放' }}</strong></span>
              </div>
            </section>

            <AppScrollArea class="page-config-grid">
              <!-- 左侧只表达结构和选中关系；配置说明统一由右侧检查器承接。 -->
              <AppScrollArea as="section" class="app-surface plain-panel preview-panel">
                <div class="panel-heading">
                  <div>
                    <div class="section-title">结构预览</div>
                    <div class="section-subtitle">选择结构块后，在右侧查看和修改它的页面默认设置。</div>
                  </div>
                  <el-tag type="info" size="small" effect="plain">{{ selectedPage.label }}</el-tag>
                </div>
                <LayoutPagePreview
                  :key="selectedPageKey"
                  :layout="selectedPage.layout"
                  :profile="selectedPage.responsiveProfile"
                  class="preview-host"
                  @focus-slot="onPreviewFocus"
                />
              </AppScrollArea>

              <!-- 右侧是唯一配置入口：页面默认、所选组件、折叠诊断、保存。 -->
              <section class="app-surface plain-panel config-panel">
                <div class="inspector-head">
                  <div>
                    <div class="section-title">配置检查器</div>
                    <div class="section-subtitle">页面默认值会影响所有用户，个人仍可在页面设置中覆盖。</div>
                  </div>
                  <el-tag v-if="focusedSlotSpec" size="small" type="primary" effect="plain">已选组件</el-tag>
                </div>

                <AppScrollArea class="inspector-scroll" :inert="operationBusy || undefined">
                  <section class="inspector-section">
                    <div class="inspector-section-head">
                      <div>
                        <div class="inspector-title">页面默认设置</div>
                        <div class="section-subtitle">未设置时使用系统默认值。</div>
                      </div>
                    </div>
                    <!-- 布局编辑器的局部组件参数跟随页面密度，非一级业务表单。 -->
                    <AppForm size="default" label-position="top" class="config-form" :disabled="operationBusy">
                      <!-- 页面级旋钮按本页 editable 白名单动态渲染。 -->
                      <el-form-item v-for="knob in selectedPage.layout.editable" :key="knob.path" :label="knob.label">
                        <AppSelect
                          v-if="knob.type === 'enum'"
                          :model-value="pageDraft.values[knob.path] ?? ''"
                          clearable
                          placeholder="使用系统默认"
                          @update:model-value="(v: unknown) => setPageKnob(knob.path, v)"
                        >
                          <el-option
                            v-for="opt in knob.options"
                            :key="String(opt)"
                            :label="knob.optionLabels?.[String(opt)] ?? String(opt)"
                            :value="opt"
                          />
                        </AppSelect>
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
                      <div v-if="!selectedPage.layout.editable.length" class="inspector-empty">
                        该页面没有可调整的页面级设置
                      </div>
                    </AppForm>
                  </section>

                  <section v-if="selectedPage.supportsComponentConfig" class="inspector-section">
                    <div class="inspector-section-head">
                      <div>
                        <div class="inspector-title">组件设置</div>
                        <div class="section-subtitle">先从左侧结构图选择一个组件。</div>
                      </div>
                    </div>
                    <div v-if="focusedSlotSpec" class="cc-cfg-host">
                      <div class="focused-slot-card">
                        <div class="focused-slot-name">
                          <span class="app-inline-info">
                            <span>{{ focusedSlotSpec.label || focusedSlotSpec.id }}</span>
                            <HelpHint v-if="focusedSlotHint" :text="focusedSlotHint" :label="`${focusedSlotSpec.label || focusedSlotSpec.id}说明`" />
                          </span>
                        </div>
                        <div class="muted app-inline-info">
                          <span>{{ focusedSlotSpec.component }}</span>
                          <span>{{ focusedSlotSpec.region }}</span>
                          <span>{{ focusedSlotSpec.id }}</span>
                        </div>
                      </div>
                      <AppStatusNotice v-if="selectedPageKey === 'trade-discipline' && conditionDictionary.error.value" tone="warning" title="检查项分类加载失败" action-text="重试" :action-loading="conditionDictionary.loading.value" @action="conditionDictionary.load" />
                      <ComponentAutoSettings
                        :page-key="selectedPageKey"
                        :config="pageComponentConfig"
                        :component-meta-overrides="dictionaryMeta"
                        layer="page"
                        :slot-ids="focusedSlotIds"
                        :allowed-layers-of="componentAllowedLayers"
                        :show-slot-title="false"
                        clearable
                      />
                    </div>
                    <div v-else class="inspector-empty">
                      选择左侧任一结构块后，在这里配置该组件
                    </div>
                  </section>

                  <section v-else class="inspector-section inspector-section--muted">
                    <div class="inspector-title">组件设置</div>
                    <div class="section-subtitle">该页面暂未开放组件级默认设置。</div>
                  </section>

                  <el-collapse class="inspector-collapse">
                    <el-collapse-item name="diagnostic">
                      <template #title>
                        <span class="diagnostic-title">配置依据与诊断</span>
                        <el-tag type="info" size="small" effect="plain">{{ focusedDiagnosticRows.length }} 项</el-tag>
                      </template>
                      <div class="section-subtitle diagnostic-intro">查看当前组件的默认值来源、可覆盖范围与不可编辑原因。</div>
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
                        <AppTableColumn prop="detail" label="说明" />
                      </AppDataTable>
                      <div v-else class="inspector-empty">
                        {{ focusedSlotSpec ? '当前组件没有配置诊断项' : '选择组件后查看配置依据' }}
                      </div>
                    </el-collapse-item>
                  </el-collapse>
                </AppScrollArea>

                <div class="button-row cc-save-row">
                  <el-button v-permission="'layout:page-manage'" type="primary" :loading="pageSaving" :disabled="!pageConfigChanged || (operationBusy && !pageSaving)" @click="savePageConfig">保存页面配置</el-button>
                  <el-button v-permission="'layout:page-manage'" type="warning" plain :loading="pageResetting" :disabled="operationBusy && !pageResetting" @click="resetPageConfig">恢复页面系统默认</el-button>
                </div>
              </section>
            </AppScrollArea>
            </div>
          </el-tab-pane>

          <el-tab-pane label="导入导出" name="import">
            <AppScrollArea class="import-grid">
              <LayoutConfigTransferPanel
                v-model="exportText"
                mode="export"
                title="导出"
                description="导出当前页面的页面默认、当前登录用户或最终生效配置。视觉预设请到「视觉预设」工作区导出。"
                editor-label="导出配置 JSON"
                placeholder="点击生成或下载配置"
                :busy="operationBusy"
              >
                <template #toolbar>
                  <AppSelect
                    v-model="exportScope"
                    width="medium"
                    aria-label="导出范围"
                    :disabled="operationBusy"
                  >
                    <el-option label="当前页面配置" value="page" />
                    <el-option label="当前用户配置" value="user" />
                    <el-option label="当前有效配置" value="effective" />
                  </AppSelect>
                </template>
                <template #actions>
                  <el-button :loading="exportAction === 'generate'" :disabled="operationBusy && exportAction !== 'generate'" @click="runExport('generate')">生成</el-button>
                  <el-button :loading="exportAction === 'download'" :disabled="operationBusy && exportAction !== 'download'" @click="runExport('download')">下载</el-button>
                </template>
                <template #feedback>
                  <AppStatusNotice v-if="exportError" tone="error" title="配置导出失败" :description="exportError" />
                </template>
              </LayoutConfigTransferPanel>

              <LayoutConfigTransferPanel
                v-model="importText"
                mode="import"
                title="导入"
                description="仅导入当前页面的配置；用户配置应用于当前登录用户。导入前校验版本、路径、取值域和组件归属。"
                editor-label="导入配置 JSON"
                placeholder="粘贴页面/用户配置 JSON"
                :busy="operationBusy"
                @file-change="onImportFile"
              >
                <template #actions>
                  <el-button v-permission="'layout:page-manage'" type="primary" :loading="importSaving" :disabled="!importText.trim() || (operationBusy && !importSaving)" @click="importConfig">校验并导入</el-button>
                </template>
              </LayoutConfigTransferPanel>
            </AppScrollArea>
          </el-tab-pane>

          <el-tab-pane label="校验报告" name="report">
            <AppTabToolbar label="校验报告操作" actions-align="end">
              <template #actions>
                <el-button v-permission="'layout:page-manage'" :loading="reportLoading" :disabled="operationBusy && !reportLoading" @click="runValidationReport">重新校验</el-button>
                <el-button v-permission="'layout:page-manage'" type="danger" plain :loading="userResetting" :disabled="operationBusy && !userResetting" @click="resetUserConfig">清除用户覆盖</el-button>
              </template>
              <template #description>检查当前页面已保存的默认配置和当前登录用户的覆盖，并展示字段来源。</template>
            </AppTabToolbar>

            <AppAsyncRegion
              class="report-region"
              :loading="reportLoading"
              :has-content="reportReady"
              :error="reportError"
              loading-title="正在校验布局配置…"
              error-title="校验报告加载失败"
              empty-title="尚未生成校验报告"
              retry
              @retry="runValidationReport"
            >
            <AppScrollArea class="report-grid">
              <AppScrollArea as="section" class="app-surface plain-panel">
                <div class="section-title">错误项</div>
                <el-alert
                  v-if="!pageValidationErrors.length && !userValidationErrors.length"
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
              </AppScrollArea>

              <AppScrollArea as="section" class="app-surface plain-panel">
                <div class="section-title">字段来源</div>
                <AppDataTable :data="sourceRows" height="320" embedded>
                  <AppTableColumn prop="path" label="路径" />
                  <AppTableColumn prop="value" label="值" />
                  <AppTableColumn prop="source" label="来源" />
                </AppDataTable>
              </AppScrollArea>
            </AppScrollArea>
            </AppAsyncRegion>
          </el-tab-pane>
        </el-tabs>
      </AppAsyncRegion>
    </template>
  </LayoutHost>
</template>

<style scoped>
.section-subtitle,
.muted {
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
}
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
.report-region {
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}
.config-tabs :deep(#pane-report) { display: flex; flex-direction: column; }
.section-title {
  font-size: var(--app-font-size-section-title);
  font-weight: var(--app-font-weight-strong);
  color: var(--el-text-color-primary);
}
.import-grid,
.report-grid {
  --app-scroll-display: grid;
  --app-scroll-columns: minmax(320px, 0.85fr) minmax(360px, 1.15fr);
  --app-scroll-gap: var(--app-space-3);
}
.import-grid {
  --app-scroll-columns: repeat(2, minmax(0, 1fr));
  --app-scroll-rows: minmax(400px, 1fr);
}
.page-config-grid {
  --app-scroll-display: grid;
  --app-scroll-columns: minmax(420px, 1.3fr) minmax(360px, 0.7fr);
  --app-scroll-gap: var(--app-space-3);
  flex: 1 1 auto;
  min-height: 0;
  overflow: clip;
}
.import-grid,
.report-grid {
  height: 100%;
  min-height: 0;
  overflow: clip;
}
.plain-panel {
  padding: var(--app-density-card-padding);
  min-width: 0;
  min-height: 0;
  --app-scroll-padding-top: var(--app-density-card-padding); --app-scroll-padding-right: var(--app-density-card-padding); --app-scroll-padding-bottom: var(--app-density-card-padding); --app-scroll-padding-left: var(--app-density-card-padding);
}
.preview-panel,
.report-grid :deep(> .app-scroll-area__renderer > .el-scrollbar__wrap > .app-scroll-area__content) > .plain-panel {
  padding: var(--app-density-card-padding);
}
.plain-panel.app-scroll-area { padding: 0; }
.source-panel {
  flex: 0 0 auto;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--app-space-3);
}
.source-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-3);
}
.source-identity,
.source-facts,
.panel-heading,
.inspector-head,
.inspector-section-head {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
}
.source-path {
  white-space: nowrap;
}
.source-facts {
  justify-content: flex-end;
  flex-wrap: wrap;
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
}
.source-facts > span + span {
  padding-left: var(--app-space-2);
  border-left: 1px solid var(--el-border-color-lighter);
}
.source-facts strong {
  color: var(--el-text-color-primary);
  font-weight: var(--app-font-weight-section);
}
.panel-heading,
.inspector-head,
.inspector-section-head {
  justify-content: space-between;
  align-items: flex-start;
}
.config-panel {
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.inspector-head {
  flex: 0 0 auto;
  padding-bottom: var(--app-space-3);
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.inspector-scroll {
  flex: 1 1 auto;
  min-height: 0;
  --app-scroll-padding-top: var(--app-space-3); --app-scroll-padding-right: 2px; --app-scroll-padding-bottom: var(--app-space-3); --app-scroll-padding-left: 0;
  --app-scroll-display: flex;
  --app-scroll-direction: column;
  --app-scroll-gap: var(--app-space-4);
}
.inspector-section {
  padding-bottom: var(--app-space-4);
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.inspector-section--muted {
  border: 1px dashed var(--el-border-color);
  border-radius: var(--layout-control-radius);
  padding: var(--app-space-3);
  background: var(--app-section-bg);
}
.inspector-title {
  font-size: var(--app-font-size-body);
  font-weight: var(--app-font-weight-section);
  color: var(--el-text-color-primary);
}
.config-form {
  margin-top: var(--app-space-3);
}
.config-form :deep(.el-form-item:last-child) {
  margin-bottom: 0;
}
.preview-host {
  margin-top: var(--app-space-3);
}
.cc-save-row {
  flex: 0 0 auto;
  justify-content: flex-end;
  padding-top: var(--app-space-3);
  border-top: 1px solid var(--el-border-color-lighter);
  background: var(--el-bg-color);
}
.inspector-empty {
  border: 1px dashed var(--el-border-color);
  border-radius: var(--layout-control-radius);
  padding: var(--app-space-3);
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
  text-align: center;
}
.inspector-collapse {
  border-top: 0;
}
.diagnostic-title {
  margin-right: var(--app-space-2);
  color: var(--el-text-color-primary);
  font-weight: var(--app-font-weight-section);
}
.diagnostic-intro {
  margin-bottom: var(--app-space-2);
}
.diagnostic-table {
  margin-top: var(--app-space-2);
}
.cc-cfg-host {
  width: 100%;
}
.focused-slot-card {
  margin-top: var(--app-space-3);
  margin-bottom: var(--app-space-3);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: var(--layout-control-radius);
  padding: var(--app-space-3);
  background: var(--app-section-bg);
}
.focused-slot-name,
.diag-main {
  font-weight: var(--app-font-weight-section);
  color: var(--el-text-color-primary);
}
.report-alert {
  margin-top: 8px;
}
@container app-viewport (max-width: 980px) {
  .page-config-grid,
  .import-grid,
  .report-grid {
    --app-scroll-columns: 1fr;
  }
  .import-grid {
    --app-scroll-rows: repeat(2, minmax(400px, 1fr));
  }
  .source-panel {
    grid-template-columns: 1fr;
  }
  .source-facts {
    justify-content: flex-start;
  }
  .config-panel {
    overflow: visible;
  }
  .button-row {
    flex-wrap: wrap;
  }
}
</style>
