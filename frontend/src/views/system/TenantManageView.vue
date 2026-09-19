<script setup lang="ts">
import { useMenuPageTitle } from '@/composables/useMenuPageTitle'
import AppTableColumn from '@/components/AppTableColumn.vue'
// 租户管理页（多租户 RBAC stage3·T14，R14）。承接 tenant-management.html（去勾选列、无批量工具条）。
// 列表 + 筛选 + 分页 + 编辑弹窗（含指定管理员）+ 行内启停 + 查看用户跳转。整页仅系统管理员可达（require_system）。
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import { DEFAULT_PAGE_SIZE, PAGE_SIZE_OPTIONS } from '@/constants/pagination'
import AppControlRow from '@/components/AppControlRow.vue'
import AppSearchInput from '@/components/AppSearchInput.vue'
import AppDataTable from '@/components/AppDataTable.vue'
import AppDialog from '@/components/AppDialog.vue'
import AppRowActions from '@/components/AppRowActions.vue'
import AppStateBlock from '@/components/AppStateBlock.vue'
import HelpTip from '@/components/HelpTip.vue'
import HelpTipItem from '@/components/HelpTipItem.vue'
import PageSettingsDrawer from '@/components/PageSettingsDrawer.vue'
import PageSettingsTrigger from '@/components/PageSettingsTrigger.vue'
import PageSegmented from '@/components/PageSegmented.vue'
import PageSettingSection from '@/components/PageSettingSection.vue'
import SystemBuiltinTag from '@/components/SystemBuiltinTag.vue'
import LayoutHost from '@/layout/components/LayoutHost.vue'
import { getPageLayout } from '@/layout'
import { usePageSettings } from '@/composables/usePageSettings'
import { useDefaultedSessionValue } from '@/composables/useDefaultedSessionValue'
import { useRemoteLayoutConfig } from '@/composables/useRemoteLayoutConfig'
import { useComponentPageSizeSession } from '@/composables/useComponentPageSizeSession'
import { useTableSort } from '@/composables/useTableSort'
import { useFormChangeTracker } from '@/composables/useFormChangeTracker'
import { createLatestRequestGuard } from '@/utils/latestRequestGuard'
import { usePublicDictItems } from '@/composables/usePublicDictItems'
import { useAuthStore } from '@/stores/auth'
import {
  listTenants, createTenant, updateTenant, setTenantStatus, deleteTenant, type Tenant,
} from '@/api/tenant'
import { listUsers, type AdminUser } from '@/api/user'
import { dictItemLabel, dictTagStyleByCode } from '@/utils/dictColor'
import type { AppRowAction } from '@/components/rowActions'
import { formatDateTimeSeconds } from '@/utils/dateTime'

// 默认/平台租户 id：不可停用、不可删除（与后端 pg_ddl.DEFAULT_TENANT_ID 一致）。
const DEFAULT_TENANT_ID = 'default'

const auth = useAuthStore()
const router = useRouter()
// 页级由 require_system 守卫；按钮级统一走全局 v-permission 指令（含 tenant:delete，已 seed 功能码）。
const isSystem = computed(() => auth.role === 'system')

// ── 业务偏好（settings-drawer 业务段）：默认状态筛选 ──
const { settings, isDirty, reset } = usePageSettings('tenant-manage', {
  defaultStatus: 'all' as 'all' | 'active',
})

// ── 布局/组件配置（settings-drawer 布局 + 组件段）──
const tenantLayout = getPageLayout('tenant-manage')
const {
  effective, knobs: layoutKnobs, setKnob, valueOf, sourceOf,
  isDirty: layoutDirty, resetAll: resetLayout,
  componentValueOf, setComponentKnob, componentSourceOf, layerValuesOf, componentLayerValuesOf, componentAllowedLayers,
} = useRemoteLayoutConfig(tenantLayout)
const drawerConfig = { knobs: layoutKnobs, valueOf, sourceOf, setKnob, componentValueOf, setComponentKnob, componentSourceOf, layerValuesOf, componentLayerValuesOf, componentAllowedLayers }
const settingsOpen = ref(false)

const hiddenColumns = computed<string[]>(() => (componentValueOf('table', 'hiddenColumns') as string[]) ?? [])
function colVisible(key: string): boolean {
  return !hiddenColumns.value.includes(key)
}
function tableBorder(slotId: string): boolean {
  return componentValueOf(slotId, 'border') === true
}

// ── 列表 ──
const loading = ref(false)
const loadError = ref(false)   // 列表加载失败 → 页内错误态 + 重试
const list = ref<Tenant[]>([])
const total = ref(0)
const page = ref(1)
const { pageSize: size, changePageSize } = useComponentPageSizeSession({
  resolveDefault: () => componentValueOf('table', 'pageSize'),
  fallback: DEFAULT_PAGE_SIZE,
  resetPage: () => { page.value = 1 },
  reload: () => load(),
})
const defaultFilterStatus = computed(() => settings.defaultStatus === 'active' ? 'active' : '')
const filters = ref<{ status: string; q: string }>({ status: defaultFilterStatus.value, q: '' })
useDefaultedSessionValue(defaultFilterStatus, {
  onSynced: (value) => { filters.value.status = value },
})
const hasQueryFilters = computed(() => (
  filters.value.status !== defaultFilterStatus.value || filters.value.q.trim() !== ''
))
let suppressFilterReload = false
const TENANT_SORT_FIELDS = ['created', 'name', 'userCount'] as const
const { sortBy, sortOrder, elementDefaultSort, onSortChange } = useTableSort<(typeof TENANT_SORT_FIELDS)[number]>({
  slotId: 'table',
  defaultSort: 'created:desc',
  componentValueOf,
  allowedFields: TENANT_SORT_FIELDS,
  onChanged: () => {
    page.value = 1
    void load()
  },
})

const STATUS_TAG: Record<string, { type: 'success' | 'danger'; label: string }> = {
  active: { type: 'success', label: '启用' },
  disabled: { type: 'danger', label: '停用' },
}
const { items: userStatusDictItems, load: loadUserStatusDictItems } = usePublicDictItems('user_status')
const TENANT_STATUS_CODES = ['active', 'disabled'] as const
const tenantStatusOptions = computed(() => TENANT_STATUS_CODES.map((code) => ({
  code,
  label: statusLabel(code),
})))

function statusLabel(code: string): string {
  return dictItemLabel(userStatusDictItems.value, code, STATUS_TAG[code]?.label ?? code)
}

function statusTagStyle(code: string) {
  return dictTagStyleByCode(userStatusDictItems.value, code)
}

const tenantListRequest = createLatestRequestGuard()
async function load() {
  const requestId = tenantListRequest.begin()
  loading.value = true
  loadError.value = false
  try {
    const res = await listTenants({
      status: filters.value.status || undefined,
      q: filters.value.q.trim() || undefined,
      page: page.value, size: size.value,
      sort_by: sortBy.value,
      sort_order: sortOrder.value,
    })
    if (!tenantListRequest.isCurrent(requestId)) return
    list.value = res.items
    total.value = res.total
  } catch {
    if (!tenantListRequest.isCurrent(requestId)) return
    loadError.value = true
  } finally {
    if (tenantListRequest.isCurrent(requestId)) loading.value = false
  }
}

watch(() => filters.value.status, () => {
  if (suppressFilterReload) return
  page.value = 1
  load()
})
function search() { page.value = 1; load() }

async function resetQueryFilters(): Promise<void> {
  if (!hasQueryFilters.value) return
  suppressFilterReload = true
  filters.value.status = defaultFilterStatus.value
  filters.value.q = ''
  page.value = 1
  await nextTick()
  suppressFilterReload = false
  await load()
}

// ── 查看用户：跳用户管理并按该租户预置筛选 ──
function viewUsers(row: Tenant) {
  router.push({ path: '/system/users', query: { tenant: row.id } })
}

// ── 启停 ──
async function changeStatus(row: Tenant, to: string, actionLabel: string) {
  try {
    if (to !== 'active') {
      await ElMessageBox.confirm(
        `停用租户「${row.name}」后，其下全部用户将立即无法登录（在线会话下次校验即失效）。确认停用？`,
        '停用租户', { type: 'warning', confirmButtonText: '停用', confirmButtonClass: 'el-button--danger' })
    }
    await setTenantStatus(row.id, to)
    ElMessage.success(`已${actionLabel}`)
    await load()
  } catch (e) { if (e === 'cancel') return /* 默认租户不可停用等由拦截器弹出 */ }
}

// ── 删除 ──
async function removeTenant(row: Tenant) {
  try {
    await ElMessageBox.confirm(`确认删除租户「${row.name}」？删除后不可恢复。`, '删除租户',
      { type: 'warning', confirmButtonText: '删除', confirmButtonClass: 'el-button--danger' })
    await deleteTenant(row.id)
    ElMessage.success('已删除')
    await load()
  } catch (e) { if (e === 'cancel') return /* 默认租户/仍有用户由拦截器弹出 */ }
}

function tenantRowActions(row: Tenant): AppRowAction[] {
  const isDefaultTenant = row.id === DEFAULT_TENANT_ID
  const hasUsers = (row.user_count ?? 0) > 0
  return [
    { key: 'edit', label: '编辑', permission: 'tenant:update', onClick: () => openEdit(row) },
    { key: 'users', label: '查看用户', onClick: () => viewUsers(row) },
    {
      key: 'disable',
      label: '停用',
      type: 'danger',
      permission: 'tenant:disable',
      visible: row.status === 'active' && !isDefaultTenant,
      onClick: () => changeStatus(row, 'disabled', '停用'),
    },
    {
      key: 'enable',
      label: '启用',
      type: 'success',
      permission: 'tenant:disable',
      visible: row.status === 'disabled',
      onClick: () => changeStatus(row, 'active', '启用'),
    },
    {
      key: 'delete',
      label: '删除',
      type: 'danger',
      permission: 'tenant:delete',
      visible: !isDefaultTenant,
      disabled: hasUsers,
      title: hasUsers ? '该租户仍有用户，不可删除' : undefined,
      placement: 'more',
      onClick: () => removeTenant(row),
    },
  ]
}

// ── 新建 / 编辑弹窗 ──
const dialogVisible = ref(false)
const editing = ref<Tenant | null>(null)
const isEdit = computed(() => editing.value !== null)
const form = ref<{ name: string; status: string; adminUserId: string }>(
  { name: '', status: 'active', adminUserId: '' })
const saving = ref(false)
const tenantSubmitPayload = () => isEdit.value
  ? {
      name: form.value.name.trim(),
      adminUserId: form.value.adminUserId || null,
    }
  : {
      name: form.value.name.trim(),
      status: form.value.status,
    }
const {
  hasChanges: tenantFormChanged,
  captureBaseline: captureTenantBaseline,
} = useFormChangeTracker(tenantSubmitPayload)
// 编辑时该租户用户（供「指定管理员」下拉）
const tenantUsers = ref<AdminUser[]>([])
const usersLoading = ref(false)

function openCreate() {
  editing.value = null
  form.value = { name: '', status: 'active', adminUserId: '' }
  tenantUsers.value = []
  captureTenantBaseline()
  dialogVisible.value = true
}
async function openEdit(row: Tenant) {
  editing.value = row
  form.value = { name: row.name, status: row.status, adminUserId: row.admin_user_id ?? '' }
  captureTenantBaseline()
  dialogVisible.value = true
  // 拉该租户用户填充「指定管理员」下拉（system 可跨租户按 tenant 过滤）
  usersLoading.value = true
  try {
    tenantUsers.value = (await listUsers({ tenant_id: row.id, size: 200 })).items
  } catch { tenantUsers.value = [] } finally { usersLoading.value = false }
}
async function save() {
  if (!tenantFormChanged.value) return
  if (!form.value.name.trim()) { ElMessage.warning('请填写租户名称'); return }
  saving.value = true
  try {
    if (isEdit.value) {
      await updateTenant(editing.value!.id, tenantSubmitPayload())
      ElMessage.success('已保存')
    } else {
      await createTenant(tenantSubmitPayload())
      ElMessage.success('已创建')
    }
    dialogVisible.value = false
    await load()
  } catch { /* 名称唯一/管理员不属该租户等由拦截器弹出 */ } finally { saving.value = false }
}

onMounted(async () => {
  void loadUserStatusDictItems()
  await load()
})
const menuPageTitle = useMenuPageTitle()
</script>

<template>
  <LayoutHost :layout="effective">
    <template #action>
      <div class="lh-action">
        <div class="page-head">
          <div>
            <h2 class="app-page-title">
              {{ menuPageTitle }}
              <HelpTip title="租户管理说明" :width="420">
                <HelpTipItem question="可以维护什么">
                  <ul>
                    <li>支持租户增删改、指定管理员和启停。</li>
                  </ul>
                </HelpTipItem>
                <HelpTipItem question="默认租户如何保护">
                  <ul>
                    <li>默认租户不可停用或删除；停用其他租户后，其下用户立即不可登录，在线会话在下次校验时失效。</li>
                  </ul>
                </HelpTipItem>
                <HelpTipItem question="何时可以删除">
                  <ul>
                    <li>仅可删除没有用户的租户；「查看用户」会进入用户管理并按该租户过滤。</li>
                  </ul>
                </HelpTipItem>
              </HelpTip>
            </h2>
            <p class="page-subtitle">管理租户、默认套餐与租户级配置。</p>
          </div>
          <div class="page-head-actions">
            <el-button v-permission="'tenant:create'" type="primary" @click="openCreate">
              <template #icon><el-icon><Plus /></el-icon></template>
              新建租户
            </el-button>
            <PageSettingsTrigger :dirty="isDirty || layoutDirty" @click="settingsOpen = true" />
          </div>
        </div>

        <el-card shadow="never" class="filter-card">
          <AppControlRow>
            <el-select v-model="filters.status" placeholder="状态：全部" clearable class="app-control-width-short">
              <el-option v-for="item in tenantStatusOptions" :key="item.code" :label="item.label" :value="item.code" />
            </el-select>
            <AppSearchInput v-model="filters.q" placeholder="搜索租户名 / ID" class="app-control-width-long" @search="search" />
            <el-button data-testid="tenant-reset-filters" :disabled="!hasQueryFilters" @click="resetQueryFilters">重置筛选</el-button>
          </AppControlRow>
        </el-card>
      </div>
    </template>

    <template #main>
      <el-card shadow="never">
        <AppStateBlock
          v-if="loadError"
          state="error"
          title="租户列表加载失败"
          description="请检查网络或稍后重试"
          retry
          @retry="load"
        />
        <template v-else>
        <!-- row-key：稳定行标识，避免新增/重排时 fixed 列单元格 v-if（如「内置」标签）DOM 复用错位 -->
        <AppDataTable
          :data="list"
          row-key="id"
          size="small"
          :loading="loading"
          :border="tableBorder('table')"
          :default-sort="elementDefaultSort"
          :pagination="{ currentPage: page, pageSize: size, total, pageSizes: PAGE_SIZE_OPTIONS }"
          @sort-change="onSortChange"
          @page-change="(p: number) => { page = p; load() }"
          @size-change="changePageSize"
        >
          <AppTableColumn label="租户名" prop="name" fixed="left" sortable="custom">
            <template #default="{ row }">
              <span class="app-inline-info app-inline-info--nowrap">
                <span>{{ row.name }}</span>
                <SystemBuiltinTag v-if="row.id === DEFAULT_TENANT_ID" />
              </span>
            </template>
          </AppTableColumn>
          <AppTableColumn v-if="colVisible('id')" label="租户 ID" prop="id">
            <template #default="{ row }"><span class="mono">{{ row.id }}</span></template>
          </AppTableColumn>
          <AppTableColumn label="状态">
            <template #default="{ row }">
              <el-tag :type="STATUS_TAG[row.status]?.type ?? 'info'" :style="statusTagStyle(row.status)" size="small" effect="plain">
                {{ statusLabel(row.status) }}
              </el-tag>
            </template>
          </AppTableColumn>
          <AppTableColumn v-if="colVisible('admin')" label="租户管理员">
            <template #default="{ row }">{{ row.admin_account || '—' }}</template>
          </AppTableColumn>
          <AppTableColumn v-if="colVisible('userCount')" label="用户数" prop="userCount" align="right" sortable="custom">
            <template #default="{ row }">{{ row.user_count ?? 0 }}</template>
          </AppTableColumn>
          <AppTableColumn v-if="colVisible('created')" label="创建时间" prop="created" sortable="custom">
            <template #default="{ row }">{{ formatDateTimeSeconds(row.created_at) }}</template>
          </AppTableColumn>
          <AppTableColumn label="操作" role="action" fixed="right">
            <template #default="{ row }">
              <AppRowActions :actions="tenantRowActions(row)" :inline-limit="3" />
            </template>
          </AppTableColumn>
        </AppDataTable>
        </template>
      </el-card>
    </template>

    <template #overlays>
      <AppDialog v-model="dialogVisible" :title="isEdit ? '编辑租户' : '新建租户'" size="medium">
        <el-form label-width="88px">
          <el-form-item label="租户名" required>
            <el-input v-model="form.name" placeholder="全局唯一" />
          </el-form-item>
          <el-form-item v-if="isEdit" label="租户 ID">
            <span class="locked-field mono">{{ editing?.id }}<span class="muted">（系统生成，不可改）</span></span>
          </el-form-item>
          <el-form-item v-if="isEdit" label="租户管理员">
            <el-select v-model="form.adminUserId" placeholder="从该租户用户中指定" clearable filterable
                       :loading="usersLoading" style="width: 100%">
              <el-option v-for="u in tenantUsers" :key="u.id" :label="u.account" :value="u.id" />
            </el-select>
          </el-form-item>
          <el-form-item v-if="!isEdit" label="状态" required>
            <el-radio-group v-model="form.status">
              <el-radio-button v-for="item in tenantStatusOptions" :key="item.code" :value="item.code">
                {{ item.label }}
              </el-radio-button>
            </el-radio-group>
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="dialogVisible = false">取消</el-button>
          <el-button type="primary" :loading="saving" :disabled="!tenantFormChanged" @click="save">保存</el-button>
        </template>
      </AppDialog>

      <PageSettingsDrawer
        v-model="settingsOpen"
        title="租户管理"
        :dirty="isDirty || layoutDirty"
        page-key="tenant-manage"
        :config="drawerConfig"
        @reset="reset(); resetLayout()"
      >
        <template #business>
          <PageSettingSection title="默认状态筛选" desc="设置每次进入租户管理时的初始查询范围。">
            <PageSegmented v-model="settings.defaultStatus" aria-label="状态筛选" :options="[
              { label: '全部', value: 'all' },
              { label: '仅启用', value: 'active' },
            ]" />
          </PageSettingSection>
        </template>
      </PageSettingsDrawer>
    </template>
  </LayoutHost>
</template>

<style scoped>
.page-head { display: flex; justify-content: space-between; align-items: flex-start; gap: var(--app-space-3); }
.page-head-actions { display: flex; align-items: center; gap: var(--app-space-2); }
.mono { font-family: var(--app-font-family-mono); font-size: var(--app-font-size-caption); }
.muted { color: var(--el-text-color-secondary); }
.locked-field { color: var(--el-text-color-regular); }
</style>
