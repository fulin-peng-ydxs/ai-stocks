<script setup lang="ts">
/**
 * 预设管理工作区（P4 布局平台 IA 重构）。
 *
 * 职责（plan.md §13.2）：管理全局风格预设、token、组件默认策略、引用关系与启停状态，
 * 以及预设维度的导入导出。页面/用户配置与校验报告归「页面布局」工作区，组件目录归「系统组件」。
 * 由原单页 LayoutConfigView 的「预设管理 + 导入导出(预设部分)」迁移而来，能力不丢失。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  deleteLayoutPreset,
  listLayoutPresets,
  saveLayoutPreset,
  type LayoutOverlayValues,
  type LayoutPresetRecord,
} from '@/api/layout'
import LayoutHost from '@/layout/components/LayoutHost.vue'
import AppRowActions from '@/components/AppRowActions.vue'
import AppStateBlock from '@/components/AppStateBlock.vue'
import {
  getLayoutPreset,
  getPageLayout,
  hasDistinctTextHierarchy,
  isHexColor,
  setPresetOverrides,
  type StyleTokenConfig,
  type ThemeMode,
} from '@/layout'
import { getErrorMessage } from '@/utils/error'
import type { AppRowAction } from '@/components/rowActions'

// 可编辑 token 清单（颜色按白天/夜间各一套；形态/密度明暗共用）。label 给编辑器展示用。
const COLOR_KEYS: { key: keyof StyleTokenConfig; label: string }[] = [
  { key: 'primary', label: '主色' },
  { key: 'success', label: '成功' },
  { key: 'warning', label: '警告' },
  { key: 'danger', label: '危险' },
  { key: 'pageBg', label: '页面背景' },
  { key: 'surfaceBg', label: '卡片背景' },
  { key: 'surfaceHover', label: '悬浮背景' },
  { key: 'border', label: '边框' },
  { key: 'borderStrong', label: '强边框' },
  { key: 'text', label: '正文' },
  { key: 'textStrong', label: '强调文字' },
  { key: 'textMuted', label: '弱化文字' },
  { key: 'activeBg', label: '激活背景' },
  { key: 'submenuBg', label: '子菜单背景' },
]
const SHAPE_KEYS: { key: keyof StyleTokenConfig; label: string; max: number }[] = [
  { key: 'cardRadius', label: '卡片圆角', max: 24 },
  { key: 'controlRadius', label: '控件圆角', max: 24 },
  { key: 'pageGap', label: '页间距', max: 32 },
  { key: 'cardPadding', label: '卡片内距', max: 32 },
  { key: 'tableCellPaddingY', label: '表格行距', max: 24 },
]
const REFLOW_BREAKPOINTS = [1024, 1100, 1280]

const presetsLayout = getPageLayout('layout-presets')

const loading = ref(false)
const loadError = ref('')
const presets = ref<LayoutPresetRecord[]>([])
const selectedPresetKey = ref('balanced')

const presetDialog = ref(false)
const presetSaving = ref(false)
const tokenTab = ref<ThemeMode>('light')
type TokenMap = Record<string, string>
const presetForm = reactive({
  key: '',
  name: '',
  description: '',
  enabled: true,
  is_builtin: false,
  // 组件默认策略
  density: 'standard',
  tableSize: 'standard',
  filterDefaultExpanded: true,
  drawerSize: 'md',
  pageSize: 20, // 预设×组件默认：data-table 默认分页
  // 响应式默认（受控枚举）
  reflowBreakpoint: 1024,
  // 视觉 token：颜色按模式两套 + 形态密度共用
  light: {} as TokenMap,
  dark: {} as TokenMap,
  shadowLight: '',
  shadowDark: '',
  shared: {} as Record<string, number>,
})

// 导入导出（预设维度）
const exportText = ref('')
const importText = ref('')
const importSaving = ref(false)

function presetToForm(row?: LayoutPresetRecord) {
  const values = row?.config.values ?? {}
  presetForm.key = row?.key ?? ''
  presetForm.name = row?.name ?? ''
  presetForm.description = row?.description ?? ''
  presetForm.enabled = row?.enabled ?? true
  presetForm.is_builtin = row?.is_builtin ?? false
  presetForm.density = String(values['density'] ?? values['componentDefaults.density'] ?? 'standard')
  presetForm.tableSize = String(values['componentDefaults.tableSize'] ?? presetForm.density)
  presetForm.filterDefaultExpanded = Boolean(values['componentDefaults.filterDefaultExpanded'] ?? true)
  presetForm.drawerSize = String(values['componentDefaults.drawerSize'] ?? 'md')
  presetForm.pageSize = Number(values['componentFieldDefaults.data-table.pageSize'] ?? 20)
  presetForm.reflowBreakpoint = Number(values['responsiveDefaults.reflowBreakpoint'] ?? 1024)
  // token 回显：以前端内置预设该模式 token 为底（保证编辑内置时看到真实颜色），叠加后端覆盖。
  const base = getLayoutPreset(row?.key)
  for (const mode of ['light', 'dark'] as ThemeMode[]) {
    const target = (mode === 'light' ? presetForm.light : presetForm.dark) as TokenMap
    for (const { key } of COLOR_KEYS) {
      target[key] = String(values[`tokens.${mode}.${key}`] ?? base.tokens[mode][key])
    }
  }
  presetForm.shadowLight = String(values['tokens.light.shadow'] ?? base.tokens.light.shadow)
  presetForm.shadowDark = String(values['tokens.dark.shadow'] ?? base.tokens.dark.shadow)
  for (const { key } of SHAPE_KEYS) {
    presetForm.shared[key] = Number(values[`tokens.shared.${key}`] ?? base.tokens.light[key])
  }
  tokenTab.value = 'light'
}

function presetFormValues(): LayoutOverlayValues {
  const out: LayoutOverlayValues = {
    density: presetForm.density,
    'componentDefaults.density': presetForm.density,
    'componentDefaults.tableSize': presetForm.tableSize,
    'componentDefaults.filterDefaultExpanded': presetForm.filterDefaultExpanded,
    'componentDefaults.drawerSize': presetForm.drawerSize,
    'componentFieldDefaults.data-table.pageSize': Number(presetForm.pageSize),
    'responsiveDefaults.reflowBreakpoint': Number(presetForm.reflowBreakpoint),
    'tokens.light.shadow': presetForm.shadowLight,
    'tokens.dark.shadow': presetForm.shadowDark,
  }
  for (const { key } of COLOR_KEYS) {
    out[`tokens.light.${key}`] = presetForm.light[key]
    out[`tokens.dark.${key}`] = presetForm.dark[key]
  }
  for (const { key } of SHAPE_KEYS) {
    out[`tokens.shared.${key}`] = Number(presetForm.shared[key])
  }
  return out
}

function presetTextHierarchyError(values: Record<string, unknown>): string | null {
  for (const mode of ['light', 'dark'] as ThemeMode[]) {
    const text = values[`tokens.${mode}.text`]
    const textMuted = values[`tokens.${mode}.textMuted`]
    if (isHexColor(text) && isHexColor(textMuted) && !hasDistinctTextHierarchy(text, textMuted)) {
      return `${mode === 'light' ? '白天' : '夜间'}模式的正文与弱化文字亮度过于接近`
    }
  }
  return null
}

async function reloadPresets() {
  loading.value = true
  loadError.value = ''
  try {
    const data = await listLayoutPresets(true)
    presets.value = data.presets
    if (!presets.value.some((p) => p.key === selectedPresetKey.value)) {
      selectedPresetKey.value = presets.value[0]?.key ?? 'balanced'
    }
    // 同步运行时：让预设编辑/启停/导入即时驱动外观（P11 运行时打通）。
    const map: Record<string, Record<string, string | number>> = {}
    for (const p of presets.value) {
      const v = p.config?.values
      if (v && Object.keys(v).length) map[p.key] = v as Record<string, string | number>
    }
    setPresetOverrides(map)
  } catch (error) {
    loadError.value = getErrorMessage(error, '布局预设加载失败')
  } finally {
    loading.value = false
  }
}

function openNewPreset() {
  presetToForm()
  presetForm.key = `custom-${Date.now().toString(36)}`
  presetForm.name = '自定义预设'
  presetDialog.value = true
}

function openEditPreset(row: LayoutPresetRecord) {
  presetToForm(row)
  presetDialog.value = true
}

async function submitPreset() {
  if (!presetForm.key || !presetForm.name) {
    ElMessage.warning('请填写预设标识和名称')
    return
  }
  const values = presetFormValues()
  const hierarchyError = presetTextHierarchyError(values)
  if (hierarchyError) {
    ElMessage.warning(hierarchyError)
    return
  }
  presetSaving.value = true
  try {
    const saved = await saveLayoutPreset({
      key: presetForm.key,
      name: presetForm.name,
      description: presetForm.description,
      enabled: presetForm.enabled,
      is_builtin: presetForm.is_builtin,
      config: { values },
    })
    selectedPresetKey.value = saved.key
    presetDialog.value = false
    ElMessage.success('布局预设已保存')
    await reloadPresets()
  } finally {
    presetSaving.value = false
  }
}

async function togglePreset(row: LayoutPresetRecord) {
  await saveLayoutPreset({
    key: row.key,
    name: row.name,
    description: row.description,
    enabled: !row.enabled,
    is_builtin: row.is_builtin,
    config: row.config,
  })
  await reloadPresets()
}

async function removePreset(row: LayoutPresetRecord) {
  await ElMessageBox.confirm(`确认删除预设「${row.name}」？`, '删除预设', { type: 'warning' })
  await deleteLayoutPreset(row.key)
  ElMessage.success('已删除')
  await reloadPresets()
}

function presetRowActions(row: LayoutPresetRecord): AppRowAction[] {
  return [
    {
      key: 'edit',
      label: row.is_builtin ? '查看' : '编辑',
      onClick: () => openEditPreset(row),
    },
    {
      key: 'toggle',
      label: row.enabled ? '停用' : '启用',
      type: row.enabled ? 'danger' : 'success',
      permission: 'layout:preset-manage',
      onClick: () => togglePreset(row),
    },
    {
      key: 'delete',
      label: '删除',
      type: 'danger',
      permission: 'layout:preset-manage',
      disabled: row.is_builtin,
      title: row.is_builtin ? '系统内置预设不可删除' : undefined,
      placement: 'more',
      onClick: () => removePreset(row),
    },
  ]
}

function buildExport() {
  exportText.value = JSON.stringify({ type: 'layout-presets', presets: presets.value }, null, 2)
}

function downloadExport() {
  if (!exportText.value) buildExport()
  const blob = new Blob([exportText.value], { type: 'application/json;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'layout-presets.json'
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

async function importPresets() {
  importSaving.value = true
  try {
    const parsed = JSON.parse(importText.value)
    if (parsed.type !== 'layout-presets') {
      ElMessage.error('请导入预设类型（layout-presets）文件；页面/用户配置请在「页面布局」工作区导入')
      return
    }
    for (const preset of parsed.presets ?? []) {
      const values = preset.config?.values
      const hierarchyError = values && typeof values === 'object'
        ? presetTextHierarchyError(values as Record<string, unknown>)
        : null
      if (hierarchyError) throw new Error(`预设「${preset.name || preset.key}」：${hierarchyError}`)
      await saveLayoutPreset({
        key: preset.key,
        name: preset.name,
        description: preset.description,
        enabled: preset.enabled,
        is_builtin: false,
        config: preset.config,
      })
    }
    ElMessage.success('预设导入完成')
    await reloadPresets()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '导入内容不是合法 JSON')
  } finally {
    importSaving.value = false
  }
}

const importExportVisible = ref(false)
const presetCount = computed(() => presets.value.length)

onMounted(reloadPresets)
</script>

<template>
  <LayoutHost :layout="presetsLayout">
    <template #action>
      <div class="layout-toolbar">
        <div>
          <div class="page-title">预设管理</div>
          <div class="page-subtitle">全局风格预设、token、组件默认策略与引用关系（共 {{ presetCount }} 套）</div>
        </div>
        <div class="toolbar-actions">
          <el-button @click="importExportVisible = true">导入导出</el-button>
          <el-button @click="reloadPresets">刷新</el-button>
          <el-button v-permission="'layout:preset-manage'" type="primary" @click="openNewPreset">新增预设</el-button>
        </div>
      </div>
    </template>

    <template #main>
      <section class="plain-panel">
        <!-- 整区滚动（section scroll=region），表格按内容自然成高随区域滚动，不写视口硬编码高度（DESIGN.md §7 红线）。 -->
        <AppStateBlock
          v-if="loadError && !presets.length"
          state="error"
          title="布局预设加载失败"
          :description="loadError"
          retry
          @retry="reloadPresets"
        />
        <template v-else>
        <AppStateBlock
          v-if="loadError"
          state="error"
          size="compact"
          title="布局预设刷新失败"
          :description="loadError"
          retry
          @retry="reloadPresets"
        />
        <el-table :data="presets" v-loading="loading" row-key="key">
          <el-table-column prop="name" label="名称" min-width="140">
            <template #default="{ row }">
              <div class="preset-name">{{ row.name }}</div>
              <div class="muted">{{ row.key }}</div>
            </template>
          </el-table-column>
          <el-table-column prop="description" label="说明" min-width="220" show-overflow-tooltip />
          <el-table-column label="密度" width="96">
            <template #default="{ row }">{{ row.config.values.density || row.config.values['componentDefaults.density'] || '-' }}</template>
          </el-table-column>
          <el-table-column label="引用页面" min-width="160">
            <template #default="{ row }">
              <span v-if="row.referenceCount">{{ row.referencedPages?.join('、') }}</span>
              <span v-else class="muted">未引用</span>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="110">
            <template #default="{ row }">
              <el-tag :type="row.enabled ? 'success' : 'info'" effect="plain">{{ row.enabled ? '启用' : '停用' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="类型" width="100">
            <template #default="{ row }">
              <el-tag :type="row.is_builtin ? 'warning' : 'primary'" effect="plain">{{ row.is_builtin ? '系统内置' : '自定义' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="230" fixed="right">
            <template #default="{ row }">
              <AppRowActions :actions="presetRowActions(row)" :inline-limit="2" />
            </template>
          </el-table-column>
        </el-table>
        </template>
      </section>
    </template>

    <template #overlays>
      <el-dialog v-model="presetDialog" width="720px" title="布局预设">
        <el-form label-position="top" class="preset-form">
          <div class="form-grid">
            <el-form-item label="标识">
              <el-input v-model="presetForm.key" :disabled="presetForm.is_builtin" />
            </el-form-item>
            <el-form-item label="名称">
              <el-input v-model="presetForm.name" />
            </el-form-item>
          </div>
          <el-form-item label="说明">
            <el-input v-model="presetForm.description" />
          </el-form-item>

          <div class="form-section-title">组件默认策略</div>
          <div class="form-grid three">
            <el-form-item label="密度">
              <el-select v-model="presetForm.density">
                <el-option label="紧凑" value="compact" />
                <el-option label="标准" value="standard" />
                <el-option label="宽松" value="comfortable" />
              </el-select>
            </el-form-item>
            <el-form-item label="表格密度">
              <el-select v-model="presetForm.tableSize">
                <el-option label="紧凑" value="compact" />
                <el-option label="标准" value="standard" />
                <el-option label="宽松" value="comfortable" />
              </el-select>
            </el-form-item>
            <el-form-item label="抽屉尺寸">
              <el-select v-model="presetForm.drawerSize">
                <el-option label="小" value="sm" />
                <el-option label="中" value="md" />
                <el-option label="大" value="lg" />
              </el-select>
            </el-form-item>
            <el-form-item label="表格默认分页(data-table)">
              <el-input-number v-model="presetForm.pageSize" :min="10" :max="500" :step="10" controls-position="right" />
            </el-form-item>
            <el-form-item label="重排断点(响应式默认)">
              <el-select v-model="presetForm.reflowBreakpoint">
                <el-option v-for="bp in REFLOW_BREAKPOINTS" :key="bp" :label="`${bp}px`" :value="bp" />
              </el-select>
            </el-form-item>
            <el-form-item label="筛选区默认展开">
              <el-switch v-model="presetForm.filterDefaultExpanded" />
            </el-form-item>
          </div>

          <div class="form-section-title">视觉 token（颜色按白天/夜间各一套，形态/密度两模式共用）</div>
          <el-tabs v-model="tokenTab">
            <el-tab-pane label="白天" name="light">
              <div class="form-grid three">
                <el-form-item v-for="c in COLOR_KEYS" :key="c.key" :label="c.label">
                  <el-color-picker v-model="presetForm.light[c.key]" />
                </el-form-item>
                <el-form-item label="阴影">
                  <el-input v-model="presetForm.shadowLight" placeholder="rgba(…)" />
                </el-form-item>
              </div>
            </el-tab-pane>
            <el-tab-pane label="夜间" name="dark">
              <div class="form-grid three">
                <el-form-item v-for="c in COLOR_KEYS" :key="c.key" :label="c.label">
                  <el-color-picker v-model="presetForm.dark[c.key]" />
                </el-form-item>
                <el-form-item label="阴影">
                  <el-input v-model="presetForm.shadowDark" placeholder="rgba(…)" />
                </el-form-item>
              </div>
            </el-tab-pane>
          </el-tabs>

          <div class="form-section-title">形态 / 密度（明暗共用）</div>
          <div class="form-grid three">
            <el-form-item v-for="s in SHAPE_KEYS" :key="s.key" :label="s.label">
              <el-input-number v-model="presetForm.shared[s.key]" :min="0" :max="s.max" controls-position="right" />
            </el-form-item>
          </div>

          <el-switch v-model="presetForm.enabled" active-text="启用" inactive-text="停用" />
        </el-form>
        <template #footer>
          <el-button @click="presetDialog = false">取消</el-button>
          <el-button v-permission="'layout:preset-manage'" type="primary" :loading="presetSaving" @click="submitPreset">保存</el-button>
        </template>
      </el-dialog>

      <el-dialog v-model="importExportVisible" width="720px" title="预设导入导出">
        <div class="ie-grid">
          <section>
            <div class="section-title">导出全部预设</div>
            <div class="inline-controls">
              <el-button @click="buildExport">生成</el-button>
              <el-button @click="downloadExport">下载</el-button>
            </div>
            <el-input v-model="exportText" type="textarea" :rows="12" spellcheck="false" />
          </section>
          <section>
            <div class="section-title">导入预设</div>
            <div class="section-subtitle">仅接受 layout-presets 文件；导入的预设一律落为自定义。</div>
            <input class="file-input" type="file" accept="application/json,.json" @change="onImportFile" />
            <el-input v-model="importText" type="textarea" :rows="10" spellcheck="false" placeholder="粘贴导出的 JSON" />
            <div class="button-row">
              <el-button v-permission="'layout:preset-manage'" type="primary" :loading="importSaving" @click="importPresets">校验并导入</el-button>
            </div>
          </section>
        </div>
      </el-dialog>
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
.plain-panel {
  min-width: 0;
  border: 1px solid var(--el-border-color);
  background: var(--el-bg-color);
  border-radius: 6px;
  padding: 14px;
}
.section-title {
  font-size: var(--app-font-size-section-title);
  font-weight: var(--app-font-weight-strong);
  color: var(--el-text-color-primary);
}
.preset-name {
  font-weight: var(--app-font-weight-section);
}
.preset-form {
  max-height: 62vh;
  overflow: auto;
  padding-right: 4px;
}
.form-section-title {
  margin: 14px 0 8px;
  font-size: var(--app-font-size-table);
  font-weight: var(--app-font-weight-strong);
  color: var(--el-text-color-primary);
  padding-bottom: 4px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--app-space-3);
}
.form-grid.three {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}
.ie-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--app-space-4);
}
.inline-controls {
  margin: 8px 0;
}
.file-input {
  display: block;
  margin: 10px 0;
  color: var(--el-text-color-regular);
}
.button-row {
  margin-top: 10px;
}
@media (max-width: 980px) {
  .layout-toolbar {
    align-items: stretch;
    flex-direction: column;
  }
  .ie-grid {
    grid-template-columns: 1fr;
  }
  .toolbar-actions {
    flex-wrap: wrap;
  }
}
</style>
