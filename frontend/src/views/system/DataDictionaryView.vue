<script setup lang="ts">
import AppTableColumn from '@/components/AppTableColumn.vue'
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import AppControlRow from '@/components/AppControlRow.vue'
import AppSearchInput from '@/components/AppSearchInput.vue'
import AppDataTable from '@/components/AppDataTable.vue'
import AppRowActions from '@/components/AppRowActions.vue'
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
import { useRemoteLayoutConfig } from '@/composables/useRemoteLayoutConfig'
import { useComponentPageSizeSession } from '@/composables/useComponentPageSizeSession'
import { useTableSort } from '@/composables/useTableSort'
import { getPageLayout } from '@/layout'
import LayoutHost from '@/layout/components/LayoutHost.vue'
import { useAuthStore } from '@/stores/auth'
import { DICT_COLOR_PRESETS, dictColorSwatchStyle, dictTagStyle, normalizeDictColor } from '@/utils/dictColor'
import type { AppRowAction } from '@/components/rowActions'

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

const typeKeyword = ref('')
// 当前选中字典类型：会话态（刷新/重进回到未选中），不持久化——它不是默认值，是主区点选状态。
const selectedTypeCode = ref('')

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
const drawerDirty = computed(() => layoutDirty.value)
const canManageDict = computed(() => auth.isSystem)
const activeType = computed(() => typeRows.value.find((row) => row.code === selectedTypeCode.value) ?? null)
let typeRequestSeq = 0
let itemRequestSeq = 0
const { pageSize, changePageSize } = useComponentPageSizeSession({
  resolveDefault: () => componentValueOf('itemTable', 'pageSize'),
  fallback: 50,
  resetPage: () => {
    itemPage.value = 1
  },
  reload: loadItems,
})
const DICT_ITEM_SORT_FIELDS = ['sort', 'code', 'label', 'enabled', 'updated_at'] as const
const { sortBy, sortOrder, elementDefaultSort, onSortChange } = useTableSort<(typeof DICT_ITEM_SORT_FIELDS)[number]>({
  slotId: 'itemTable',
  defaultSort: 'sort:asc',
  componentValueOf,
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
  itemForm.type_code = row?.type_code ?? selectedTypeCode.value
  itemForm.code = row?.code ?? ''
  itemForm.label = row?.label ?? ''
  itemForm.color = row?.color ?? ''
  itemForm.enabled = row?.enabled ?? true
  itemForm.sort = row?.sort ?? 100
  itemForm.remark = row?.remark ?? ''
}

function normalizeTypeSelection() {
  if (!typeRows.value.length) {
    selectedTypeCode.value = ''
    itemRows.value = []
    itemTotal.value = 0
    itemRequestSeq += 1
    return false
  }
  if (!typeRows.value.some((row) => row.code === selectedTypeCode.value)) {
    selectedTypeCode.value = typeRows.value[0].code
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
    const data = await listDictTypes({ q: typeKeyword.value || undefined, page: 1, size: 200 })
    if (seq !== typeRequestSeq) return
    typeRows.value = data.list
    typeTotal.value = data.total
    if (!keepSelection) selectedTypeCode.value = ''
    normalizeTypeSelection()
  } catch {
    if (seq === typeRequestSeq) typeError.value = true
  } finally {
    if (seq === typeRequestSeq) typeLoading.value = false
  }
}

async function loadItems() {
  const currentTypeCode = selectedTypeCode.value
  if (!currentTypeCode) {
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
      type_code: currentTypeCode,
      page: itemPage.value,
      size: pageSize.value,
      sort_by: sortBy.value,
      sort_order: sortOrder.value,
    })
    if (seq !== itemRequestSeq || currentTypeCode !== selectedTypeCode.value) return
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
  if (selectedTypeCode.value) await loadItems()
}

async function selectType(code: string) {
  if (selectedTypeCode.value === code) return
  selectedTypeCode.value = code
  itemPage.value = 1
  await loadItems()
}

async function searchTypes() {
  await loadTypes(true)
  itemPage.value = 1
  if (selectedTypeCode.value) await loadItems()
}


function pageChanged(value: number) {
  itemPage.value = value
  void loadItems()
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
  if (!selectedTypeCode.value) return
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
      selectedTypeCode.value = code
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
      await createDictItem({ ...body, type_code: selectedTypeCode.value, code })
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
  selectedTypeCode.value = ''
  await loadTypes(false)
  if (selectedTypeCode.value) await loadItems()
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

function itemRowActions(row: DictItem): AppRowAction[] {
  return [
    { key: 'edit', label: '编辑', permission: 'dict:item-manage', onClick: () => openEditItem(row) },
    {
      key: 'delete',
      label: '删除',
      type: 'danger',
      permission: 'dict:item-manage',
      placement: 'more',
      onClick: () => removeItem(row),
    },
  ]
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


onMounted(loadAll)
</script>

<template>
  <LayoutHost :layout="effective">
    <template #action>
      <div class="dict-page-head">
        <div class="dict-title">
          <h2 class="app-page-title">数据字典
            <HelpTip title="数据字典说明" :width="420">
              维护系统枚举与稳定业务枚举。字典类型和字典项 code 创建后不可修改，业务判断只使用 code。
            </HelpTip>
          </h2>
          <p class="page-subtitle">维护数据字段、类型与口径说明。</p>
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
        state="error"
        variant="permission"
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
          <el-card shadow="never" class="filter-card dict-type-card">
            <AppControlRow class="dict-type-tools">
              <AppSearchInput v-model="typeKeyword" placeholder="搜索类型 / code" @search="searchTypes" />
            </AppControlRow>
          </el-card>
          <div class="dict-type-list" v-loading="typeLoading && typeRows.length > 0">
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
            <AppStateBlock
              v-else-if="typeLoading && !typeRows.length"
              state="loading"
              size="compact"
              title="正在加载字典类型…"
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
                :class="{ active: row.code === selectedTypeCode }"
                @click="selectType(row.code)"
                @keydown.enter.prevent="selectType(row.code)"
                @keydown.space.prevent="selectType(row.code)"
              >
                <span class="type-main">
                  <b>{{ row.name }}</b>
                </span>
                <el-switch
                  class="dict-type-status"
                  :model-value="row.enabled"
                  :loading="togglingTypeCode === row.code"
                  inline-prompt
                  active-text="启"
                  inactive-text="停"
                  aria-label="切换字典类型状态"
                  @click.stop
                  @update:model-value="(value: boolean) => toggleType(row, value)"
                />
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
              <el-button v-if="activeType" v-permission="'dict:item-manage'" size="small" type="success" plain @click="openCreateItem">新建字典项</el-button>
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
              @size-change="changePageSize"
            >
              <AppTableColumn v-if="colVisible('code')" label="code" prop="code" show-overflow-tooltip sortable="custom">
                <template #default="{ row }"><span class="mono">{{ row.code }}</span></template>
              </AppTableColumn>
              <AppTableColumn v-if="colVisible('label')" label="名称" prop="label" show-overflow-tooltip sortable="custom">
                <template #default="{ row }">
                  <el-tag v-if="row.color" effect="plain" :style="dictTagStyle(row.color)">{{ row.label }}</el-tag>
                  <span v-else>{{ row.label }}</span>
                </template>
              </AppTableColumn>
              <AppTableColumn v-if="colVisible('color')" label="颜色" prop="color">
                <template #default="{ row }">
                  <span v-if="row.color" class="dict-color-cell">
                    <i class="dict-color-swatch" :style="dictColorSwatchStyle(row.color)" />
                    <span class="mono">{{ row.color }}</span>
                  </span>
                  <span v-else class="muted">-</span>
                </template>
              </AppTableColumn>
              <AppTableColumn v-if="colVisible('sort')" label="排序" prop="sort" sortable="custom" />
              <AppTableColumn v-if="colVisible('enabled')" label="启用" prop="enabled" sortable="custom">
                <template #default="{ row }">
                  <el-switch
                    v-model="row.enabled"
                    v-permission="'dict:item-manage'"
                    size="small"
                    @change="(value: boolean) => toggleItem(row, value)"
                  />
                </template>
              </AppTableColumn>
              <AppTableColumn v-if="colVisible('remark')" label="备注" prop="remark" show-overflow-tooltip />
              <AppTableColumn v-if="colVisible('updated_at')" label="更新时间" prop="updated_at" sortable="custom">
                <template #default="{ row }">{{ formatTime(row.updated_at) }}</template>
              </AppTableColumn>
              <AppTableColumn label="操作" fixed="right">
                <template #default="{ row }">
                  <AppRowActions :actions="itemRowActions(row)" :inline-limit="1" />
                </template>
              </AppTableColumn>
              <template #empty>
                <div class="app-table-empty">
                  <span class="app-table-empty__description">{{ activeType ? '暂无字典项' : '请选择字典类型' }}</span>
                  <el-button v-if="activeType" v-permission="'dict:item-manage'" type="success" plain @click="openCreateItem">新建字典项</el-button>
                </div>
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
        @reset="resetLayout"
      />
    </template>
  </LayoutHost>
</template>

<style scoped>
.dict-page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--app-space-3);
}
.dict-title {
  min-width: 0;
}
.dict-title h2 {
  margin: 0;
}
.dict-actions {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
  flex-wrap: wrap;
  justify-content: flex-end;
}
.dict-workspace {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  gap: var(--app-space-3);
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
  gap: var(--app-space-2);
}
.dict-type-card {
  flex: none;
  border: none;
  border-bottom: 1px solid var(--el-border-color-lighter);
  background: transparent;
  box-shadow: none;
  border-radius: 0;
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
  gap: var(--app-space-2);
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
  --el-switch-on-color: var(--el-color-success);
  --el-switch-off-color: color-mix(in srgb, var(--el-text-color-regular) 88%, var(--el-fill-color-dark) 12%);
}
html[data-layout-mode='dark'] .dict-type-status {
  --el-switch-off-color: color-mix(in srgb, var(--el-fill-color-dark) 88%, var(--el-bg-color) 12%);
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
  font-size: var(--app-font-size-caption);
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
  font-family: var(--app-font-family-mono);
  font-size: var(--app-font-size-caption);
}
.dict-color-cell,
.dict-color-editor {
  display: inline-flex;
  align-items: center;
  gap: var(--app-space-2);
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
