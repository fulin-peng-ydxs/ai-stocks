<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import AppControlRow from '@/components/AppControlRow.vue'
import AppDataTable from '@/components/AppDataTable.vue'
import AppStateBlock from '@/components/AppStateBlock.vue'
import HelpTip from '@/components/HelpTip.vue'
import PageSettingsDrawer from '@/components/PageSettingsDrawer.vue'
import PageSettingsTrigger from '@/components/PageSettingsTrigger.vue'
import {
  createDictItem,
  createDictType,
  deleteDictItem,
  deleteDictType,
  listDictItems,
  listDictTypes,
  updateDictItem,
  updateDictType,
  type DictItem,
  type DictType,
} from '@/api/dict'
import { usePageSettings } from '@/composables/usePageSettings'
import { useRemoteLayoutConfig } from '@/composables/useRemoteLayoutConfig'
import { useTableSort } from '@/composables/useTableSort'
import { getPageLayout } from '@/layout'
import LayoutHost from '@/layout/components/LayoutHost.vue'
import { useAuthStore } from '@/stores/auth'
import { DICT_COLOR_PRESETS, dictColorSwatchStyle, dictTagStyle, normalizeDictColor } from '@/utils/dictColor'

const pageKey = 'data-dictionary'

const auth = useAuthStore()
const baseLayout = getPageLayout(pageKey)
const {
  effective,
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
} = useRemoteLayoutConfig(baseLayout)
const drawerConfig = {
  knobs: layoutKnobs,
  valueOf,
  sourceOf,
  setKnob,
  componentValueOf,
  setComponentKnob,
  componentSourceOf,
  layerValuesOf,
  componentLayerValuesOf,
}

const { settings, isDirty: bizDirty, reset: resetBiz } = usePageSettings(pageKey, {
  selectedTypeCode: '',
  typeKeyword: '',
})

const settingsOpen = ref(false)
const typeRows = ref<DictType[]>([])
const itemRows = ref<DictItem[]>([])
const typeTotal = ref(0)
const itemTotal = ref(0)
const itemPage = ref(1)
const typeLoading = ref(false)
const itemLoading = ref(false)
const typeError = ref(false)
const itemError = ref(false)
const permissionError = ref(false)
const typeDialogOpen = ref(false)
const itemDialogOpen = ref(false)
const typeDialogMode = ref<'create' | 'edit'>('create')
const itemDialogMode = ref<'create' | 'edit'>('create')
const savingType = ref(false)
const savingItem = ref(false)
const togglingTypeCode = ref('')
const typeForm = reactive({
  code: '',
  name: '',
  enabled: true,
  sort: 100,
  remark: '',
})
const itemForm = reactive({
  type_code: '',
  code: '',
  label: '',
  color: '',
  enabled: true,
  sort: 100,
  remark: '',
})
const drawerDirty = computed(() => layoutDirty.value || bizDirty.value)
const canManageDict = computed(() => auth.isSystem)
const activeType = computed(() => typeRows.value.find((row) => row.code === settings.selectedTypeCode) ?? null)
let typeRequestSeq = 0
let itemRequestSeq = 0
let typeSearchTimer: ReturnType<typeof setTimeout> | null = null
const pageSize = computed(() => {
  const raw = componentValueOf('itemTable', 'pageSize')
  return typeof raw === 'number' && Number.isFinite(raw) ? Math.max(10, Math.min(200, raw)) : 50
})
const DICT_ITEM_SORT_FIELDS = ['sort', 'code', 'label', 'enabled', 'updated_at'] as const
const { sortBy, sortOrder, elementDefaultSort, onSortChange } = useTableSort<(typeof DICT_ITEM_SORT_FIELDS)[number]>({
  slotId: 'itemTable',
  defaultSort: 'sort:asc',
  componentValueOf,
  setComponentKnob,
  allowedFields: DICT_ITEM_SORT_FIELDS,
  defaultOrder: 'asc',
  onChanged: () => {
    itemPage.value = 1
    void loadItems()
  },
})
const hiddenColumns = computed<string[]>(() => {
  const raw = componentValueOf('itemTable', 'hiddenColumns')
  return Array.isArray(raw) ? raw.map(String) : []
})

function colVisible(key: string): boolean {
  return !hiddenColumns.value.includes(key)
}
function tableBorder(slotId: string): boolean {
  return componentValueOf(slotId, 'border') === true
}

function formatTime(value: string | null | undefined): string {
  if (!value) return '-'
  return value.replace('T', ' ').replace(/\.\d+/, '').replace(/\+.*$/, '').slice(0, 19)
}

function resetTypeForm(row?: DictType) {
  typeForm.code = row?.code ?? ''
  typeForm.name = row?.name ?? ''
  typeForm.enabled = row?.enabled ?? true
  typeForm.sort = row?.sort ?? 100
  typeForm.remark = row?.remark ?? ''
}

function resetItemForm(row?: DictItem) {
  itemForm.type_code = row?.type_code ?? settings.selectedTypeCode
  itemForm.code = row?.code ?? ''
  itemForm.label = row?.label ?? ''
  itemForm.color = row?.color ?? ''
  itemForm.enabled = row?.enabled ?? true
  itemForm.sort = row?.sort ?? 100
  itemForm.remark = row?.remark ?? ''
}

function normalizeTypeSelection() {
  if (!typeRows.value.length) {
    settings.selectedTypeCode = ''
    itemRows.value = []
    itemTotal.value = 0
    itemRequestSeq += 1
    return false
  }
  if (!typeRows.value.some((row) => row.code === settings.selectedTypeCode)) {
    settings.selectedTypeCode = typeRows.value[0].code
  }
  return true
}

async function loadTypes(keepSelection = true) {
  if (!canManageDict.value) {
    permissionError.value = true
    return
  }
  const seq = ++typeRequestSeq
  typeLoading.value = true
  typeError.value = false
  permissionError.value = false
  try {
    const data = await listDictTypes({ q: settings.typeKeyword || undefined, page: 1, size: 200 })
    if (seq !== typeRequestSeq) return
    typeRows.value = data.list
    typeTotal.value = data.total
    if (!keepSelection) settings.selectedTypeCode = ''
    normalizeTypeSelection()
  } catch {
    if (seq === typeRequestSeq) typeError.value = true
  } finally {
    if (seq === typeRequestSeq) typeLoading.value = false
  }
}

async function loadItems() {
  const selectedTypeCode = settings.selectedTypeCode
  if (!selectedTypeCode) {
    itemRows.value = []
    itemTotal.value = 0
    itemRequestSeq += 1
    return
  }
  const seq = ++itemRequestSeq
  itemLoading.value = true
  itemError.value = false
  try {
    const data = await listDictItems({
      type_code: selectedTypeCode,
      page: itemPage.value,
      size: pageSize.value,
      sort_by: sortBy.value,
      sort_order: sortOrder.value,
    })
    if (seq !== itemRequestSeq || selectedTypeCode !== settings.selectedTypeCode) return
    itemRows.value = data.list
    itemTotal.value = data.total
    if (data.list.length === 0 && data.total > 0 && itemPage.value > 1) {
      itemPage.value = Math.max(1, Math.ceil(data.total / pageSize.value))
      await loadItems()
    }
  } catch {
    if (seq === itemRequestSeq) itemError.value = true
  } finally {
    if (seq === itemRequestSeq) itemLoading.value = false
  }
}

async function loadAll() {
  if (!canManageDict.value) {
    permissionError.value = true
    return
  }
  await loadTypes(true)
  if (settings.selectedTypeCode) await loadItems()
}

async function selectType(code: string) {
  if (settings.selectedTypeCode === code) return
  settings.selectedTypeCode = code
  itemPage.value = 1
  await loadItems()
}

async function searchTypes() {
  if (typeSearchTimer) clearTimeout(typeSearchTimer)
  typeSearchTimer = null
  await loadTypes(true)
  itemPage.value = 1
  if (settings.selectedTypeCode) await loadItems()
}

function scheduleSearchTypes() {
  if (typeSearchTimer) clearTimeout(typeSearchTimer)
  typeSearchTimer = setTimeout(() => {
    void searchTypes()
  }, 300)
}

function pageChanged(value: number) {
  itemPage.value = value
  void loadItems()
}

function pageSizeChanged(value: number) {
  if (value === pageSize.value) return
  setComponentKnob('itemTable', 'pageSize', value)
  itemPage.value = 1
}

function openCreateType() {
  typeDialogMode.value = 'create'
  resetTypeForm()
  typeDialogOpen.value = true
}

function openEditType(row = activeType.value) {
  if (!row) return
  typeDialogMode.value = 'edit'
  resetTypeForm(row)
  typeDialogOpen.value = true
}

function openCreateItem() {
  if (!settings.selectedTypeCode) return
  itemDialogMode.value = 'create'
  resetItemForm()
  itemDialogOpen.value = true
}

function openEditItem(row: DictItem) {
  itemDialogMode.value = 'edit'
  resetItemForm(row)
  itemDialogOpen.value = true
}

function validateCode(value: string): boolean {
  return /^[a-z][a-z0-9_:-]{0,63}$/.test(value.trim())
}

async function saveType() {
  const code = typeForm.code.trim()
  const name = typeForm.name.trim()
  if (!validateCode(code)) {
    ElMessage.error('类型 code 只能使用小写字母、数字、下划线、短横线或冒号，且以字母开头')
    return
  }
  if (!name) {
    ElMessage.error('请填写类型名称')
    return
  }
  savingType.value = true
  try {
    const body = {
      name,
      enabled: typeForm.enabled,
      sort: Number(typeForm.sort) || 100,
      remark: typeForm.remark.trim() || null,
    }
    if (typeDialogMode.value === 'create') {
      await createDictType({ ...body, code })
      settings.selectedTypeCode = code
    } else {
      await updateDictType(code, body)
    }
    typeDialogOpen.value = false
    await loadTypes(true)
    await loadItems()
    ElMessage.success('已保存')
  } catch {
    // 全局请求拦截器已展示后端错误，弹窗保留当前输入供修正。
  } finally {
    savingType.value = false
  }
}

async function saveItem() {
  const code = itemForm.code.trim()
  const label = itemForm.label.trim()
  if (!validateCode(code)) {
    ElMessage.error('字典项 code 只能使用小写字母、数字、下划线、短横线或冒号，且以字母开头')
    return
  }
  if (!label) {
    ElMessage.error('请填写字典项名称')
    return
  }
  savingItem.value = true
  try {
    const body = {
      label,
      color: normalizeDictColor(itemForm.color) || null,
      enabled: itemForm.enabled,
      sort: Number(itemForm.sort) || 100,
      remark: itemForm.remark.trim() || null,
    }
    if (itemDialogMode.value === 'create') {
      await createDictItem({ ...body, type_code: settings.selectedTypeCode, code })
    } else {
      await updateDictItem(itemForm.type_code, code, body)
    }
    itemDialogOpen.value = false
    await loadTypes(true)
    await loadItems()
    ElMessage.success('已保存')
  } catch {
    // 全局请求拦截器已展示后端错误，弹窗保留当前输入供修正。
  } finally {
    savingItem.value = false
  }
}

async function removeType(row = activeType.value) {
  if (!row) return
  await ElMessageBox.confirm(`确认删除字典类型「${row.name}」？`, '删除字典类型', {
    type: 'warning',
    confirmButtonText: '删除',
    cancelButtonText: '取消',
  })
  await deleteDictType(row.code)
  settings.selectedTypeCode = ''
  await loadTypes(false)
  if (settings.selectedTypeCode) await loadItems()
  ElMessage.success('已删除')
}

async function removeItem(row: DictItem) {
  await ElMessageBox.confirm(`确认删除字典项「${row.label}」？`, '删除字典项', {
    type: 'warning',
    confirmButtonText: '删除',
    cancelButtonText: '取消',
  })
  await deleteDictItem(row.type_code, row.code)
  await loadTypes(true)
  await loadItems()
  ElMessage.success('已删除')
}

async function toggleType(row: DictType, value: boolean) {
  if (togglingTypeCode.value) return
  togglingTypeCode.value = row.code
  try {
    await updateDictType(row.code, {
      name: row.name,
      enabled: value,
      sort: row.sort,
      remark: row.remark ?? null,
    })
    row.enabled = value
    ElMessage.success(value ? '已启用类型' : '已停用类型')
  } catch {
    row.enabled = !value
  } finally {
    togglingTypeCode.value = ''
  }
}

async function toggleItem(row: DictItem, value: boolean) {
  try {
    await updateDictItem(row.type_code, row.code, {
      label: row.label,
      color: row.color ?? null,
      enabled: value,
      sort: row.sort,
      remark: row.remark ?? null,
    })
    row.enabled = value
    await loadTypes(true)
    ElMessage.success(value ? '已启用字典项' : '已停用字典项')
  } catch {
    row.enabled = !value
  }
}

watch(pageSize, () => {
  itemPage.value = 1
  void loadItems()
})

onMounted(loadAll)
onBeforeUnmount(() => {
  if (typeSearchTimer) clearTimeout(typeSearchTimer)
})
</script>

<template>
  <LayoutHost :layout="effective">
    <template #action>
      <div class="dict-page-head">
        <div class="dict-title">
          <h2>数据字典</h2>
          <HelpTip title="数据字典说明" :width="420">
            维护系统枚举与稳定业务枚举。字典类型和字典项 code 创建后不可修改，业务判断只使用 code。
          </HelpTip>
        </div>
        <div class="dict-actions">
          <el-button v-permission="'dict:type-manage'" type="primary" @click="openCreateType">新建类型</el-button>
          <PageSettingsTrigger :dirty="drawerDirty" @click="settingsOpen = true" />
        </div>
      </div>
    </template>

    <template #main>
      <AppStateBlock
        v-if="permissionError"
        state="permission"
        title="无权限维护数据字典"
        description="数据字典管理仅系统管理员可用"
        class="dict-state"
      />
      <div v-else class="dict-workspace">
        <section class="dict-panel dict-left">
          <header class="dict-panel-head">
            <strong>字典类型</strong>
            <span class="muted">{{ typeTotal }} 类</span>
          </header>
          <AppControlRow class="dict-type-tools">
            <el-input v-model="settings.typeKeyword" clearable placeholder="搜索类型 / code" @input="scheduleSearchTypes" @keyup.enter="searchTypes" @clear="searchTypes" />
          </AppControlRow>
          <div class="dict-type-list" v-loading="typeLoading">
            <AppStateBlock
              v-if="typeError"
              state="error"
              size="compact"
              title="类型加载失败"
              description="请稍后重试"
              class="compact-state"
              retry
              @retry="loadTypes(true)"
            />
            <el-empty v-else-if="!typeRows.length" class="app-empty app-empty--compact" description="暂无字典类型">
              <el-button v-permission="'dict:type-manage'" type="primary" @click="openCreateType">新建类型</el-button>
            </el-empty>
            <template v-else>
              <div
                v-for="row in typeRows"
                :key="row.code"
                role="button"
                tabindex="0"
                class="dict-type-row"
                :class="{ active: row.code === settings.selectedTypeCode }"
                @click="selectType(row.code)"
                @keydown.enter.prevent="selectType(row.code)"
                @keydown.space.prevent="selectType(row.code)"
              >
                <span class="type-main">
                  <b>{{ row.name }}</b>
                </span>
                <button
                  type="button"
                  class="dict-type-status"
                  :class="{ enabled: row.enabled, disabled: !row.enabled }"
                  :aria-pressed="row.enabled"
                  :disabled="togglingTypeCode === row.code"
                  @click.stop="toggleType(row, !row.enabled)"
                >
                  {{ row.enabled ? '启用' : '停用' }}
                </button>
              </div>
            </template>
          </div>
        </section>

        <section class="dict-panel dict-right">
          <header class="dict-detail-bar">
            <div class="dict-current">
              <strong>{{ activeType?.name || '未选择类型' }}</strong>
              <span>{{ activeType?.code || '请选择左侧字典类型' }}</span>
            </div>
            <div class="dict-actions">
              <el-button v-if="activeType" v-permission="'dict:type-manage'" size="small" @click="openEditType()">编辑类型</el-button>
              <el-button v-if="activeType" v-permission="'dict:type-manage'" size="small" type="danger" plain @click="removeType()">删除类型</el-button>
              <el-button v-if="activeType" v-permission="'dict:item-manage'" size="small" type="primary" @click="openCreateItem">新建字典项</el-button>
            </div>
          </header>

          <AppStateBlock
            v-if="itemError"
            state="error"
            title="字典项加载失败"
            description="请稍后重试，业务消费端会回落默认枚举"
            class="dict-state"
            retry
            @retry="loadItems"
          />
          <div v-else class="dict-table-wrap">
            <AppDataTable
              :data="itemRows"
              :loading="itemLoading"
              row-key="id"
              :border="tableBorder('itemTable')"
              stripe
              framed
              :default-sort="elementDefaultSort"
              :pagination="{ currentPage: itemPage, pageSize, total: itemTotal }"
              @sort-change="onSortChange"
              @page-change="pageChanged"
              @size-change="pageSizeChanged"
            >
              <el-table-column v-if="colVisible('code')" label="code" prop="code" width="150" show-overflow-tooltip sortable="custom">
                <template #default="{ row }"><span class="mono">{{ row.code }}</span></template>
              </el-table-column>
              <el-table-column v-if="colVisible('label')" label="名称" prop="label" min-width="150" show-overflow-tooltip sortable="custom">
                <template #default="{ row }">
                  <el-tag v-if="row.color" effect="plain" :style="dictTagStyle(row.color)">{{ row.label }}</el-tag>
                  <span v-else>{{ row.label }}</span>
                </template>
              </el-table-column>
              <el-table-column v-if="colVisible('color')" label="颜色" prop="color" width="122">
                <template #default="{ row }">
                  <span v-if="row.color" class="dict-color-cell">
                    <i class="dict-color-swatch" :style="dictColorSwatchStyle(row.color)" />
                    <span class="mono">{{ row.color }}</span>
                  </span>
                  <span v-else class="muted">-</span>
                </template>
              </el-table-column>
              <el-table-column v-if="colVisible('sort')" label="排序" prop="sort" width="90" sortable="custom" />
              <el-table-column v-if="colVisible('enabled')" label="启用" prop="enabled" width="110" sortable="custom">
                <template #default="{ row }">
                  <el-switch
                    v-model="row.enabled"
                    v-permission="'dict:item-manage'"
                    size="small"
                    @change="(value: boolean) => toggleItem(row, value)"
                  />
                </template>
              </el-table-column>
              <el-table-column v-if="colVisible('remark')" label="备注" prop="remark" min-width="220" show-overflow-tooltip />
              <el-table-column v-if="colVisible('updated_at')" label="更新时间" prop="updated_at" width="170" sortable="custom">
                <template #default="{ row }">{{ formatTime(row.updated_at) }}</template>
              </el-table-column>
              <el-table-column label="操作" width="132" fixed="right">
                <template #default="{ row }">
                  <el-button v-permission="'dict:item-manage'" link type="primary" @click="openEditItem(row)">编辑</el-button>
                  <el-button v-permission="'dict:item-manage'" link type="danger" @click="removeItem(row)">删除</el-button>
                </template>
              </el-table-column>
              <template #empty>
                <el-empty class="app-empty" :description="activeType ? '暂无字典项' : '请选择字典类型'">
                  <el-button v-if="activeType" v-permission="'dict:item-manage'" type="primary" @click="openCreateItem">新建字典项</el-button>
                </el-empty>
              </template>
            </AppDataTable>
          </div>
        </section>
      </div>
    </template>

    <template #overlays>
      <el-dialog v-model="typeDialogOpen" :title="typeDialogMode === 'create' ? '新建字典类型' : '编辑字典类型'" width="520px">
        <el-form label-width="92px">
          <el-form-item label="类型 code">
            <el-input v-model="typeForm.code" :disabled="typeDialogMode === 'edit'" placeholder="如 user_status" />
          </el-form-item>
          <el-form-item label="类型名称">
            <el-input v-model="typeForm.name" placeholder="如 用户状态" />
          </el-form-item>
          <el-form-item label="排序">
            <el-input-number v-model="typeForm.sort" :min="0" :max="9999" />
          </el-form-item>
          <el-form-item label="启用">
            <el-switch v-model="typeForm.enabled" />
          </el-form-item>
          <el-form-item label="备注">
            <el-input v-model="typeForm.remark" type="textarea" :rows="3" />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="typeDialogOpen = false">取消</el-button>
          <el-button type="primary" :loading="savingType" @click="saveType">保存</el-button>
        </template>
      </el-dialog>

      <el-dialog v-model="itemDialogOpen" :title="itemDialogMode === 'create' ? '新建字典项' : '编辑字典项'" width="520px">
        <el-form label-width="92px">
          <el-form-item label="类型 code">
            <el-input v-model="itemForm.type_code" disabled />
          </el-form-item>
          <el-form-item label="item code">
            <el-input v-model="itemForm.code" :disabled="itemDialogMode === 'edit'" placeholder="如 active" />
          </el-form-item>
          <el-form-item label="名称">
            <el-input v-model="itemForm.label" placeholder="如 启用" />
          </el-form-item>
          <el-form-item label="颜色">
            <div class="dict-color-editor">
              <el-color-picker v-model="itemForm.color" clearable :predefine="DICT_COLOR_PRESETS" />
              <el-tag v-if="itemForm.color" effect="plain" :style="dictTagStyle(itemForm.color)">
                {{ itemForm.label || itemForm.code || '预览' }}
              </el-tag>
              <span v-else class="muted">未绑定颜色</span>
            </div>
          </el-form-item>
          <el-form-item label="排序">
            <el-input-number v-model="itemForm.sort" :min="0" :max="9999" />
          </el-form-item>
          <el-form-item label="启用">
            <el-switch v-model="itemForm.enabled" />
          </el-form-item>
          <el-form-item label="备注">
            <el-input v-model="itemForm.remark" type="textarea" :rows="3" />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="itemDialogOpen = false">取消</el-button>
          <el-button type="primary" :loading="savingItem" @click="saveItem">保存</el-button>
        </template>
      </el-dialog>

      <PageSettingsDrawer
        v-model="settingsOpen"
        title="数据字典"
        :dirty="drawerDirty"
        :page-key="pageKey"
        :config="drawerConfig"
        @reset="resetBiz(); resetLayout()"
      />
    </template>
  </LayoutHost>
</template>

<style scoped>
.dict-page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.dict-title {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.dict-title h2 {
  margin: 0;
  font-size: 20px;
}
.dict-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  justify-content: flex-end;
}
.dict-workspace {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  gap: 14px;
  overflow: auto;
}
.dict-panel {
  min-height: 0;
  display: flex;
  flex-direction: column;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-bg-color-overlay);
}
.dict-left {
  flex: 0 0 320px;
  min-width: 280px;
}
.dict-right {
  flex: 1 1 auto;
  min-width: 680px;
}
.dict-panel-head,
.dict-detail-bar {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 10px;
}
.dict-type-tools {
  flex: 0 0 auto;
}
.dict-panel-head,
.dict-detail-bar {
  justify-content: space-between;
  padding: 11px 14px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.dict-detail-bar {
  flex-wrap: wrap;
}
.dict-type-tools {
  padding: 10px 12px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.dict-type-tools .el-input {
  min-width: 0;
}
.dict-type-list {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  padding: 8px;
}
.dict-type-row {
  width: 100%;
  border: 1px solid transparent;
  border-radius: 6px;
  background: transparent;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 8px;
  color: var(--el-text-color-primary);
  cursor: pointer;
  text-align: left;
}
.dict-type-row:hover {
  background: var(--el-fill-color-light);
}
.dict-type-row:focus-visible {
  outline: none;
  border-color: var(--el-color-primary);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--el-color-primary) 16%, transparent);
}
.dict-type-row.active {
  background: var(--el-color-primary-light-9);
}
.type-main {
  flex: 1 1 auto;
  min-width: 0;
}
.type-main b {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.dict-type-status {
  flex: none;
  min-width: 42px;
  border: 1px solid var(--el-border-color);
  border-radius: 4px;
  background: var(--el-bg-color);
  padding: 1px 7px;
  color: var(--el-text-color-secondary);
  cursor: pointer;
  font-size: 12px;
  line-height: 20px;
}
.dict-type-status.enabled {
  border-color: color-mix(in srgb, var(--el-color-success) 42%, transparent);
  color: var(--el-color-success);
}
.dict-type-status.disabled {
  border-color: var(--el-border-color);
  color: var(--el-text-color-secondary);
}
.dict-type-status:hover:not(:disabled) {
  background: var(--el-fill-color-light);
  border-color: currentColor;
}
.dict-type-status:disabled {
  cursor: wait;
  opacity: 0.62;
}
.dict-current {
  flex: 1 1 150px;
  min-width: 140px;
}
.dict-current strong,
.dict-current span {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.dict-current span,
.muted {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.w110 {
  width: 110px;
}
.dict-table-wrap {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.dict-state {
  height: 100%;
}
.compact-state {
  padding: 24px 0;
}
.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
}
.dict-color-cell,
.dict-color-editor {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.dict-color-swatch {
  width: 14px;
  height: 14px;
  flex: none;
  border: 1px solid var(--el-border-color);
  border-radius: 3px;
}
@media (max-width: 980px) {
  .dict-page-head {
    flex-direction: column;
  }
  .dict-actions {
    justify-content: flex-start;
  }
}
</style>
