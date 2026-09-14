<script setup lang="ts">
import AppTableColumn from '@/components/AppTableColumn.vue'
import AppDataTable from '@/components/AppDataTable.vue'
/**
 * 预设管理工作区（P4 布局平台 IA 重构）。
 *
 * 职责（plan.md §13.2）：管理全局视觉预设、token 与启停状态，
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
import SystemBuiltinTag from '@/components/SystemBuiltinTag.vue'
import {
  getLayoutPreset,
  getPageLayout,
  setRuntimePresetSources,
  type StyleTokenConfig,
  type ThemeMode,
} from '@/layout'
import { getErrorMessage } from '@/utils/error'
import type { AppRowAction } from '@/components/rowActions'

// 可编辑 token 清单（颜色按白天/夜间各一套；圆角明暗共用）。
const COLOR_KEYS: { key: keyof StyleTokenConfig; label: string }[] = [
  { key: 'primary', label: '主色' },
  { key: 'success', label: '成功' },
  { key: 'warning', label: '警告' },
  { key: 'danger', label: '危险' },
  { key: 'marketUp', label: '上涨' },
  { key: 'marketDown', label: '下跌' },
  { key: 'border', label: '边框' },
  { key: 'borderStrong', label: '强调边框' },
]
const SHAPE_KEYS: { key: keyof StyleTokenConfig; label: string; max: number }[] = [
  { key: 'cardRadius', label: '卡片圆角', max: 24 },
  { key: 'controlRadius', label: '控件圆角', max: 24 },
]
const VISUAL_PRESET_PATH = /^tokens\.(?:light|dark)\.(?:primary|success|warning|danger|marketUp|marketDown|border|borderStrong|shadow)$|^tokens\.shared\.(?:cardRadius|controlRadius)$/

const presetsLayout = getPageLayout('layout-presets')
// 平台布局管理页不开放用户级组件配置；表格仍显式消费统一边框契约。
const tableBorder = (_slotId: string) => false

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
  // 视觉 token：颜色按模式两套 + 圆角共用
  light: {} as TokenMap,
  dark: {} as TokenMap,
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
  // token 回显：以前端内置预设该模式 token 为底（保证编辑内置时看到真实颜色），叠加后端覆盖。
  const base = getLayoutPreset(row?.key)
  for (const mode of ['light', 'dark'] as ThemeMode[]) {
    const target = (mode === 'light' ? presetForm.light : presetForm.dark) as TokenMap
    for (const { key } of COLOR_KEYS) {
      target[key] = String(values[`tokens.${mode}.${key}`] ?? base.tokens[mode][key])
    }
    target.shadow = String(values[`tokens.${mode}.shadow`] ?? base.tokens[mode].shadow)
  }
  for (const { key } of SHAPE_KEYS) {
    presetForm.shared[key] = Number(values[`tokens.shared.${key}`] ?? base.tokens.light[key])
  }
  tokenTab.value = 'light'
}

function presetFormValues(): LayoutOverlayValues {
  const out: LayoutOverlayValues = {}
  for (const { key } of COLOR_KEYS) {
    out[`tokens.light.${key}`] = presetForm.light[key]
    out[`tokens.dark.${key}`] = presetForm.dark[key]
  }
  out['tokens.light.shadow'] = presetForm.light.shadow
  out['tokens.dark.shadow'] = presetForm.dark.shadow
  for (const { key } of SHAPE_KEYS) {
    out[`tokens.shared.${key}`] = Number(presetForm.shared[key])
  }
  return out
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
    const enabledPresets = presets.value.filter((preset) => preset.enabled)
    setRuntimePresetSources(enabledPresets)
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
  if (!presetForm.key.trim() || !presetForm.name.trim()) {
    ElMessage.warning('请填写预设标识和名称')
    return
  }
  const numberValues = SHAPE_KEYS.map(({ key }) => presetForm.shared[key])
  const colorsComplete = COLOR_KEYS.every(({ key }) => (
    Boolean(presetForm.light[key]) && Boolean(presetForm.dark[key])
  )) && Boolean(presetForm.light.shadow) && Boolean(presetForm.dark.shadow)
  if (numberValues.some((value) => !Number.isFinite(Number(value))) || !colorsComplete) {
    ElMessage.warning('请补全布局预设中的必填配置')
    return
  }
  const values = presetFormValues()
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
    const incoming = Array.isArray(parsed.presets) ? parsed.presets : []
    const discarded = incoming.reduce((total: number, preset: LayoutPresetRecord) => (
      total + Object.keys(preset.config?.values ?? {}).filter((path) => !VISUAL_PRESET_PATH.test(path)).length
    ), 0)
    if (discarded > 0) {
      try {
        await ElMessageBox.confirm(
          `检测到 ${discarded} 个旧版布局、密度或组件字段。它们已不属于视觉预设，导入时将被移除。`,
          '兼容旧版预设',
          { type: 'warning', confirmButtonText: '移除并导入' },
        )
      } catch {
        return
      }
    }
    for (const preset of incoming) {
      const values = Object.fromEntries(
        Object.entries(preset.config?.values ?? {}).filter(([path]) => VISUAL_PRESET_PATH.test(path)),
      )
      await saveLayoutPreset({
        key: preset.key,
        name: preset.name,
        description: preset.description,
        enabled: preset.enabled,
        is_builtin: false,
        config: { schemaVersion: preset.config?.schemaVersion, values },
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
      <div class="lh-action">
        <div class="page-head">
          <div>
            <h2 class="app-page-title">预设管理</h2>
            <p class="page-subtitle">管理颜色、圆角、边框与阴影等全局视觉预设（共 {{ presetCount }} 套）。</p>
          </div>
          <div class="page-head-actions">
            <el-button @click="importExportVisible = true">导入导出</el-button>
            <el-button :loading="loading" @click="reloadPresets">刷新</el-button>
            <el-button v-permission="'layout:preset-manage'" type="primary" @click="openNewPreset">新增预设</el-button>
          </div>
        </div>
      </div>
    </template>

    <template #main>
      <section class="plain-panel preset-list-panel">
        <AppStateBlock
          v-if="loadError"
          state="error"
          :title="presets.length ? '布局预设刷新失败' : '布局预设加载失败'"
          :description="loadError"
          retry
          @retry="reloadPresets"
        />
        <AppDataTable
          v-else
          :data="presets"
          :loading="loading"
          row-key="key"
          :border="tableBorder('table')"
          data-testid="preset-table"
        >
          <AppTableColumn prop="name" label="名称">
            <template #default="{ row }">
              <div class="preset-name">{{ row.name }}</div>
              <div class="muted">{{ row.key }}</div>
            </template>
          </AppTableColumn>
          <AppTableColumn prop="description" label="说明" />
          <AppTableColumn label="卡片圆角">
            <template #default="{ row }">{{ row.config.values['tokens.shared.cardRadius'] ?? '默认' }}</template>
          </AppTableColumn>
          <AppTableColumn label="状态">
            <template #default="{ row }">
              <el-tag :type="row.enabled ? 'success' : 'info'" effect="plain">{{ row.enabled ? '启用' : '停用' }}</el-tag>
            </template>
          </AppTableColumn>
          <AppTableColumn label="类型">
            <template #default="{ row }">
              <SystemBuiltinTag v-if="row.is_builtin" />
              <el-tag v-else type="primary" effect="plain">自定义</el-tag>
            </template>
          </AppTableColumn>
          <AppTableColumn label="操作" role="action" fixed="right">
            <template #default="{ row }">
              <AppRowActions :actions="presetRowActions(row)" :inline-limit="2" />
            </template>
          </AppTableColumn>
        </AppDataTable>
      </section>
    </template>

    <template #overlays>
      <el-dialog v-model="presetDialog" width="720px" title="布局预设">
        <el-form label-position="top" class="preset-form">
          <div class="form-grid">
            <el-form-item label="标识" :required="!presetForm.is_builtin">
              <el-input v-model="presetForm.key" :disabled="presetForm.is_builtin" />
            </el-form-item>
            <el-form-item label="名称" required>
              <el-input v-model="presetForm.name" />
            </el-form-item>
          </div>
          <el-form-item label="说明">
            <el-input v-model="presetForm.description" />
          </el-form-item>

          <div class="form-section-title">强调色 token（背景与边栏由明暗模式固定）</div>
          <el-tabs v-model="tokenTab">
            <el-tab-pane label="白天" name="light">
              <div class="form-grid three">
                <el-form-item v-for="c in COLOR_KEYS" :key="c.key" :label="c.label" required>
                  <el-color-picker v-model="presetForm.light[c.key]" />
                </el-form-item>
                <el-form-item label="阴影" required><el-input v-model="presetForm.light.shadow" /></el-form-item>
              </div>
            </el-tab-pane>
            <el-tab-pane label="夜间" name="dark">
              <div class="form-grid three">
                <el-form-item v-for="c in COLOR_KEYS" :key="c.key" :label="c.label" required>
                  <el-color-picker v-model="presetForm.dark[c.key]" />
                </el-form-item>
                <el-form-item label="阴影" required><el-input v-model="presetForm.dark.shadow" /></el-form-item>
              </div>
            </el-tab-pane>
          </el-tabs>

          <div class="form-section-title">圆角（明暗共用）</div>
          <div class="form-grid three">
            <el-form-item v-for="s in SHAPE_KEYS" :key="s.key" :label="s.label" required>
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
.section-subtitle,
.muted {
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
}
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
  padding: var(--app-density-card-padding);
}
.preset-list-panel {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
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
  max-height: 62cqh;
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
@container app-viewport (max-width: 980px) {
  .ie-grid {
    grid-template-columns: 1fr;
  }
}
</style>
