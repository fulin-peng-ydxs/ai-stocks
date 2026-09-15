<script setup lang="ts">
import { useMenuPageTitle } from '@/composables/useMenuPageTitle'
import AppTableColumn from '@/components/AppTableColumn.vue'
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import { DEFAULT_PAGE_SIZE, PAGE_SIZE_OPTIONS } from '@/constants/pagination'
import AppControlRow from '@/components/AppControlRow.vue'
import AppSearchInput from '@/components/AppSearchInput.vue'
import AppDataTable from '@/components/AppDataTable.vue'
import AppDialog from '@/components/AppDialog.vue'
import AppRowActions from '@/components/AppRowActions.vue'
import AppStateBlock from '@/components/AppStateBlock.vue'
import AppStatusNotice from '@/components/AppStatusNotice.vue'
import HelpTip from '@/components/HelpTip.vue'
import HelpTipItem from '@/components/HelpTipItem.vue'
import PageSegmented from '@/components/PageSegmented.vue'
import PageSettingSection from '@/components/PageSettingSection.vue'
import PageSettingItem from '@/components/PageSettingItem.vue'
import PageSettingsDrawer from '@/components/PageSettingsDrawer.vue'
import PageSettingsTrigger from '@/components/PageSettingsTrigger.vue'
import LayoutHost from '@/layout/components/LayoutHost.vue'
import { getPageLayout } from '@/layout'
import { usePageSettings } from '@/composables/usePageSettings'
import { useDefaultedSessionValue } from '@/composables/useDefaultedSessionValue'
import { useRemoteLayoutConfig } from '@/composables/useRemoteLayoutConfig'
import { useComponentPageSizeSession } from '@/composables/useComponentPageSizeSession'
import { useTableSort } from '@/composables/useTableSort'
import { usePublicDictItems } from '@/composables/usePublicDictItems'
import { createLatestRequestGuard } from '@/utils/latestRequestGuard'
import { useAuthStore } from '@/stores/auth'
import {
  listUsers, createUser, updateUser, setUserStatus, resetUserPassword, deleteUser,
  listAssignableRoles, type AdminUser, type AssignableRole,
} from '@/api/user'
import { listTenants, type Tenant } from '@/api/tenant'
import { dictItemLabel, dictTagStyleByCode } from '@/utils/dictColor'
import { getErrorMessage } from '@/utils/error'
import type { AppRowAction } from '@/components/rowActions'
import { formatDateTimeSeconds } from '@/utils/dateTime'

const auth = useAuthStore()
const route = useRoute()
// 身份分流：仅系统管理员可跨租户（切租户筛选 + 新建时指定归属租户）；租户管理员限本租户，不展示租户维度。
const isSystem = computed(() => auth.role === 'system')
// 按钮级权限一律走全局 v-permission 指令（消费 auth.permissions，system 恒过）；本页不再自定义 can()。

// ── 业务偏好（settings-drawer 业务段）：默认状态筛选 ──
const { settings, isDirty, reset } = usePageSettings('user-manage', {
  defaultStatus: 'all' as 'all' | 'active',
})

// ── 布局/组件配置（settings-drawer 布局 + 组件段，按 pageRegistry.componentMeta 自动渲染）──
const userLayout = getPageLayout('user-manage')
const {
  effective, knobs: layoutKnobs, setKnob, valueOf, sourceOf,
  isDirty: layoutDirty, resetAll: resetLayout,
  componentValueOf, setComponentKnob, componentSourceOf, layerValuesOf, componentLayerValuesOf, componentAllowedLayers,
} = useRemoteLayoutConfig(userLayout)
const drawerConfig = { knobs: layoutKnobs, valueOf, sourceOf, setKnob, componentValueOf, setComponentKnob, componentSourceOf, layerValuesOf, componentLayerValuesOf, componentAllowedLayers }
const settingsOpen = ref(false)

const hiddenColumns = computed<string[]>(() => (componentValueOf('table', 'hiddenColumns') as string[]) ?? [])
function colVisible(key: string): boolean {
  return !hiddenColumns.value.includes(key)
}
function tableBorder(slotId: string): boolean {
  return componentValueOf(slotId, 'border') === true
}

// ── 角色/租户字典（用于列表展示映射 + 表单下拉）──
const ROLE_LABEL_FALLBACK: Record<string, string> = {
  system: '系统管理员', tenant_admin: '租户管理员', normal: '普通用户',
}
const assignableRoles = ref<AssignableRole[]>([])
const { items: roleTypeDictItems, load: loadRoleTypeDictItems } = usePublicDictItems('role_type')
const { items: userStatusDictItems, load: loadUserStatusDictItems } = usePublicDictItems('user_status')
const roleNameMap = computed<Record<string, string>>(() => {
  const m: Record<string, string> = {}
  for (const r of assignableRoles.value) m[r.code] = r.name
  return m
})
const roleDictOrder = computed(() => new Map(
  roleTypeDictItems.value.map((item, index) => [item.code, { sort: item.sort, index }]),
))
function roleName(row: AdminUser, code: string): string {
  return row.role_names?.[code] ?? roleNameMap.value[code] ?? ROLE_LABEL_FALLBACK[code] ?? code
}
function orderedRoles(row: AdminUser): string[] {
  return (row.roles || [])
    .map((code, index) => ({ code, index, dict: roleDictOrder.value.get(code) }))
    .sort((a, b) => {
      if (a.dict && !b.dict) return -1
      if (!a.dict && b.dict) return 1
      if (a.dict && b.dict) return a.dict.sort - b.dict.sort || a.dict.index - b.dict.index
      return a.index - b.index
    })
    .map(({ code }) => code)
}
function roleTagType(code: string): 'primary' | 'warning' | 'info' {
  if (code === 'system' || code === 'tenant_admin') return 'primary'
  return 'info'
}
function roleTagStyle(code: string) {
  return dictTagStyleByCode(roleTypeDictItems.value, code)
}
function statusTagStyle(code: string) {
  return dictTagStyleByCode(userStatusDictItems.value, code)
}

const tenants = ref<Tenant[]>([])
const dependencyLoading = ref(true)
const dependencyError = ref('')
const tenantNameMap = computed<Record<string, string>>(() => {
  const m: Record<string, string> = {}
  for (const t of tenants.value) m[t.id] = t.name
  return m
})
function tenantName(id: string): string {
  return tenantNameMap.value[id] ?? id
}

async function loadDependencies() {
  dependencyLoading.value = true
  dependencyError.value = ''
  const failures: string[] = []
  try {
    assignableRoles.value = await listAssignableRoles()
  } catch (error) {
    failures.push(getErrorMessage(error, '可分配角色加载失败'))
  }
  if (isSystem.value) {
    try {
      tenants.value = (await listTenants({ size: 200 })).items
    } catch (error) {
      failures.push(getErrorMessage(error, '租户列表加载失败'))
    }
  }
  dependencyError.value = failures.join('；')
  dependencyLoading.value = false
}

// ── 列表 ──
const loading = ref(false)
const loadError = ref(false)   // 列表加载失败 → 页内错误态 + 重试（不只依赖全局 toast）
const list = ref<AdminUser[]>([])
const total = ref(0)
const page = ref(1)
const { pageSize: size, changePageSize } = useComponentPageSizeSession({
  resolveDefault: () => componentValueOf('table', 'pageSize'),
  fallback: DEFAULT_PAGE_SIZE,
  resetPage: () => { page.value = 1 },
  reload: () => load(),
})
const defaultFilterStatus = computed(() => settings.defaultStatus === 'active' ? 'active' : '')
const filters = ref<{ tenant: string; role: string; status: string; q: string }>(
  { tenant: '', role: '', status: defaultFilterStatus.value, q: '' })
useDefaultedSessionValue(defaultFilterStatus, {
  onSynced: (value) => { filters.value.status = value },
})
const hasQueryFilters = computed(() => (
  filters.value.tenant !== ''
  || filters.value.role !== ''
  || filters.value.status !== defaultFilterStatus.value
  || filters.value.q.trim() !== ''
))
let suppressFilterReload = false
const USER_SORT_FIELDS = ['created', 'lastLogin', 'account', 'tenant'] as const
const { sortBy, sortOrder, elementDefaultSort, onSortChange } = useTableSort<(typeof USER_SORT_FIELDS)[number]>({
  slotId: 'table',
  defaultSort: 'created:desc',
  componentValueOf,
  allowedFields: USER_SORT_FIELDS,
  onChanged: () => {
    page.value = 1
    void load()
  },
})

const STATUS_TAG: Record<string, { type: 'success' | 'danger' | 'warning'; label: string }> = {
  active: { type: 'success', label: '启用' },
  disabled: { type: 'danger', label: '停用' },
  locked: { type: 'warning', label: '锁定' },
}
const USER_STATUS_CODES = ['active', 'disabled', 'locked'] as const
const userStatusOptions = computed(() => USER_STATUS_CODES.map((code) => ({
  code,
  label: statusLabel(code),
})))

function statusLabel(code: string): string {
  return dictItemLabel(userStatusDictItems.value, code, STATUS_TAG[code]?.label ?? code)
}

const userListRequest = createLatestRequestGuard()
async function load() {
  const requestId = userListRequest.begin()
  loading.value = true
  loadError.value = false
  try {
    const res = await listUsers({
      tenant_id: isSystem.value && filters.value.tenant ? filters.value.tenant : undefined,
      role: filters.value.role || undefined,
      status: filters.value.status || undefined,
      q: filters.value.q.trim() || undefined,
      page: page.value, size: size.value,
      sort_by: sortBy.value,
      sort_order: sortOrder.value,
    })
    if (!userListRequest.isCurrent(requestId)) return
    list.value = res.items
    total.value = res.total
  } catch {
    if (!userListRequest.isCurrent(requestId)) return
    loadError.value = true   // 拦截器已弹全局提示；页内保留错误态可重试
  } finally {
    if (userListRequest.isCurrent(requestId)) loading.value = false
  }
}

// 下拉筛选变更自动查询（列表交互标准）；搜索框回车/清空触发。
watch(() => [filters.value.tenant, filters.value.role, filters.value.status],
  () => {
    if (suppressFilterReload) return
    page.value = 1
    load()
  })
function search() { page.value = 1; load() }

async function resetQueryFilters(): Promise<void> {
  if (!hasQueryFilters.value) return
  suppressFilterReload = true
  Object.assign(filters.value, {
    tenant: '',
    role: '',
    status: defaultFilterStatus.value,
    q: '',
  })
  page.value = 1
  await nextTick()
  suppressFilterReload = false
  await load()
}

// ── 新建 / 编辑弹窗 ──
const dialogVisible = ref(false)
const editing = ref<AdminUser | null>(null)
const saving = ref(false)
const form = ref<{
  account: string; email: string; roleIds: string[]; status: string; tenantId: string; password: string
}>({ account: '', email: '', roleIds: [], status: 'active', tenantId: '', password: '' })

const isEdit = computed(() => editing.value !== null)
const editingSelf = computed(() => editing.value ? isSelfUser(editing.value) : false)
const editingOwnSystemRole = computed(
  () => editingSelf.value && !!editing.value?.roles?.includes('system'),
)
// 角色 id→code 反查（编辑回填时把用户 roles 的 code 映射回可分配角色 id）。
const roleIdByCode = computed<Record<string, string>>(() => {
  const m: Record<string, string> = {}
  for (const r of assignableRoles.value) m[r.code] = r.id
  return m
})
const protectedRoleNames = computed(() => {
  if (!editing.value || isSystem.value) return []
  return (editing.value.roles || [])
    .filter((code) => !roleIdByCode.value[code])
    .map((code) => editing.value?.role_names?.[code] || code)
})

function openCreate() {
  editing.value = null
  form.value = {
    account: '', email: '', roleIds: [], status: 'active',
    tenantId: isSystem.value ? (auth.tenantId || '') : '', password: '',
  }
  dialogVisible.value = true
}
function openEdit(row: AdminUser) {
  if (isTenantAdminBlocked(row)) return
  editing.value = row
  form.value = {
    account: row.account,
    email: row.email ?? '',
    // 仅提交当前操作者可维护的角色；不可分配的存量角色由后端原样保留。
    roleIds: (row.roles || []).map((c) => roleIdByCode.value[c]).filter(Boolean),
    status: row.status,
    tenantId: row.tenant_id,
    password: '',
  }
  dialogVisible.value = true
}
async function save() {
  if (!form.value.roleIds.length && !protectedRoleNames.value.length) {
    ElMessage.warning('请至少选择一个角色')
    return
  }
  saving.value = true
  try {
    if (isEdit.value && editing.value) {
      await updateUser(editing.value.id, {
        email: form.value.email.trim() || null,
        roleIds: form.value.roleIds,
        status: form.value.status,
      })
      ElMessage.success('已保存')
    } else {
      if (!form.value.account.trim()) { ElMessage.warning('请填写账号'); return }
      if (!form.value.password) { ElMessage.warning('请填写初始密码'); return }
      await createUser({
        account: form.value.account.trim(),
        password: form.value.password,
        email: form.value.email.trim() || null,
        roleIds: form.value.roleIds,
        status: form.value.status,
        tenantId: isSystem.value ? (form.value.tenantId || null) : null,
      })
      ElMessage.success('已创建')
    }
    dialogVisible.value = false
    await load()
  } catch { /* 业务校验/唯一性错误由拦截器弹出 */ } finally { saving.value = false }
}

// ── 重置密码弹窗 ──
const resetVisible = ref(false)
const resetTarget = ref<AdminUser | null>(null)
const resetForm = ref<{ pwd: string; confirm: string }>({ pwd: '', confirm: '' })
const resetting = ref(false)
function openReset(row: AdminUser) {
  if (isTenantAdminBlocked(row)) return
  resetTarget.value = row
  resetForm.value = { pwd: '', confirm: '' }
  resetVisible.value = true
}
async function confirmReset() {
  if (!resetTarget.value) return
  if (!resetForm.value.pwd) { ElMessage.warning('请填写新密码'); return }
  if (resetForm.value.pwd !== resetForm.value.confirm) { ElMessage.warning('两次输入的密码不一致'); return }
  resetting.value = true
  try {
    await resetUserPassword(resetTarget.value.id, resetForm.value.pwd)
    ElMessage.success('密码已重置，该用户需重新登录')
    resetVisible.value = false
  } catch { /* 强度不足等由拦截器弹出 */ } finally { resetting.value = false }
}

// ── 行内启停 / 删除 ──
async function changeStatus(row: AdminUser, status: string, verb: string) {
  try {
    if (status !== 'active') {
      await ElMessageBox.confirm(`确认${verb}用户「${row.account}」？${verb}后该用户将立即无法访问。`,
        verb, { type: 'warning' })
    }
    await setUserStatus(row.id, status)
    ElMessage.success(`已${verb}`)
    await load()
  } catch (e) { if (e === 'cancel') return /* 其余错误由拦截器弹出 */ }
}
function isSelfUser(row: AdminUser): boolean {
  return row.id === auth.user?.id
}
function isTenantAdminBlocked(row: AdminUser): boolean {
  return !isSystem.value && !!row.roles?.includes('system')
}
async function removeUser(row: AdminUser) {
  try {
    await ElMessageBox.confirm(`确认删除用户「${row.account}」？该操作不可恢复。`, '删除用户',
      { type: 'warning', confirmButtonText: '删除', confirmButtonClass: 'el-button--danger' })
    await deleteUser(row.id)
    ElMessage.success('已删除')
    await load()
  } catch (e) { if (e === 'cancel') return }
}

function userRowActions(row: AdminUser): AppRowAction[] {
  const tenantAdminBlocked = isTenantAdminBlocked(row)
  const self = isSelfUser(row)
  const blockedTitle = tenantAdminBlocked
    ? '租户管理员不能操作系统管理员'
    : self
      ? '不能操作当前登录用户'
      : undefined
  return [
    {
      key: 'edit',
      label: '编辑',
      permission: 'user:update',
      disabled: tenantAdminBlocked,
      title: blockedTitle,
      onClick: () => openEdit(row),
    },
    {
      key: 'reset',
      label: '重置密码',
      permission: 'user:reset-password',
      disabled: tenantAdminBlocked,
      title: blockedTitle,
      onClick: () => openReset(row),
    },
    {
      key: 'disable',
      label: '禁用',
      type: 'danger',
      permission: 'user:disable',
      visible: row.status === 'active',
      disabled: self || tenantAdminBlocked,
      title: blockedTitle,
      onClick: () => changeStatus(row, 'disabled', '禁用'),
    },
    {
      key: 'enable',
      label: '启用',
      type: 'success',
      permission: 'user:disable',
      visible: row.status === 'disabled',
      disabled: tenantAdminBlocked,
      title: blockedTitle,
      onClick: () => changeStatus(row, 'active', '启用'),
    },
    {
      key: 'unlock',
      label: '解锁',
      type: 'success',
      permission: 'user:disable',
      visible: row.status === 'locked',
      disabled: tenantAdminBlocked,
      title: blockedTitle,
      onClick: () => changeStatus(row, 'active', '解锁'),
    },
    {
      key: 'delete',
      label: '删除',
      type: 'danger',
      permission: 'user:delete',
      disabled: self || tenantAdminBlocked,
      title: blockedTitle,
      placement: 'more',
      onClick: () => removeUser(row),
    },
  ]
}

onMounted(async () => {
  // 租户管理页「查看用户」跳转带 ?tenant=<id>：system 预置租户筛选（tenant_admin 无越权、忽略）。
  const qTenant = route.query.tenant
  if (isSystem.value && typeof qTenant === 'string' && qTenant) filters.value.tenant = qTenant
  void Promise.all([loadRoleTypeDictItems(), loadUserStatusDictItems()])
  await Promise.all([loadDependencies(), load()])
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
              <HelpTip title="用户管理说明" :width="420">
                <HelpTipItem question="管理员能管理谁">
                  <ul>
                    <li>系统管理员可跨租户查看与管理，租户管理员仅限本租户。</li>
                  </ul>
                </HelpTipItem>
                <HelpTipItem question="角色如何分配">
                  <ul>
                    <li>一个用户可关联多个角色，权限取并集；租户管理员只能分配平台明确开放的角色，系统管理员角色不会开放。</li>
                  </ul>
                </HelpTipItem>
                <HelpTipItem question="租户管理员有哪些限制">
                  <ul>
                    <li>可看到本租户的系统管理员，但不能编辑、重置密码、启停或删除。</li>
                  </ul>
                </HelpTipItem>
                <HelpTipItem question="账号变更何时生效">
                  <ul>
                    <li>禁用、锁定或重置密码保存后，该用户会在下次校验时失效并需要重新登录。</li>
                  </ul>
                </HelpTipItem>
              </HelpTip>
            </h2>
            <p class="page-subtitle">管理系统用户、账号状态与租户归属。</p>
          </div>
          <div class="page-head-actions">
            <el-button v-permission="'user:create'" type="primary" @click="openCreate">
              <template #icon><el-icon><Plus /></el-icon></template>
              新建用户
            </el-button>
            <PageSettingsTrigger :dirty="isDirty || layoutDirty" @click="settingsOpen = true" />
          </div>
        </div>

        <el-card shadow="never" class="filter-card">
          <AppControlRow>
            <el-select v-if="isSystem" v-model="filters.tenant" placeholder="租户：全部" clearable
                       :loading="dependencyLoading" class="app-control-width-medium" @change="search">
              <el-option v-for="t in tenants" :key="t.id" :label="t.name" :value="t.id" />
            </el-select>
            <el-select v-model="filters.role" :loading="dependencyLoading" placeholder="角色：全部" clearable class="app-control-width-medium" @change="search">
              <el-option v-for="r in assignableRoles" :key="r.id" :label="r.name" :value="r.code" />
            </el-select>
            <el-select v-model="filters.status" placeholder="状态：全部" clearable class="app-control-width-short" @change="search">
              <el-option v-for="item in userStatusOptions" :key="item.code" :label="item.label" :value="item.code" />
            </el-select>
            <AppSearchInput v-model="filters.q" placeholder="搜索账号 / 邮箱" class="app-control-width-long" @search="search" />
            <el-button data-testid="user-reset-filters" :disabled="!hasQueryFilters" @click="resetQueryFilters">重置筛选</el-button>
          </AppControlRow>
        </el-card>
        <AppStatusNotice
          v-if="dependencyError"
          tone="warning"
          size="compact"
          title="筛选与表单选项加载不完整"
          :description="dependencyError"
          action-text="重新加载"
          @action="loadDependencies"
        />
      </div>
    </template>

    <template #main>
      <el-card shadow="never">
        <AppStateBlock
          v-if="loadError"
          state="error"
          title="用户列表加载失败"
          description="请检查网络或稍后重试"
          retry
          @retry="load"
        />
        <template v-else>
        <AppDataTable
          :data="list"
          size="small"
          aria-label="用户列表"
          :loading="loading || dependencyLoading"
          :border="tableBorder('table')"
          :default-sort="elementDefaultSort"
          :pagination="{ currentPage: page, pageSize: size, total, pageSizes: PAGE_SIZE_OPTIONS }"
          @sort-change="onSortChange"
          @page-change="(p: number) => { page = p; load() }"
          @size-change="changePageSize"
        >
          <AppTableColumn label="账号" prop="account" fixed="left" sortable="custom" />
          <AppTableColumn v-if="colVisible('email')" label="邮箱" prop="email">
            <template #default="{ row }">{{ row.email || '—' }}</template>
          </AppTableColumn>
          <AppTableColumn v-if="colVisible('roles')" label="角色">
            <template #default="{ row }">
              <span v-if="row.roles?.length" class="app-inline-info">
                <el-tag v-for="c in orderedRoles(row)" :key="c" :type="roleTagType(c)" :style="roleTagStyle(c)" size="small"
                        effect="plain" class="role-tag">{{ roleName(row, c) }}</el-tag>
              </span>
              <span v-if="!row.roles?.length" class="muted">—</span>
            </template>
          </AppTableColumn>
          <AppTableColumn v-if="isSystem && colVisible('tenant')" label="租户" prop="tenant"
                           sortable="custom">
            <template #default="{ row }">{{ tenantName(row.tenant_id) }}</template>
          </AppTableColumn>
          <AppTableColumn v-if="colVisible('status')" label="状态">
            <template #default="{ row }">
              <el-tag :type="STATUS_TAG[row.status]?.type ?? 'info'" :style="statusTagStyle(row.status)" size="small" effect="plain">
                {{ statusLabel(row.status) }}
              </el-tag>
            </template>
          </AppTableColumn>
          <AppTableColumn v-if="colVisible('lastLogin')" label="最后登录" prop="lastLogin" sortable="custom">
            <template #default="{ row }">{{ formatDateTimeSeconds(row.last_login_at) }}</template>
          </AppTableColumn>
          <AppTableColumn v-if="colVisible('created')" label="创建时间" prop="created" sortable="custom">
            <template #default="{ row }">{{ formatDateTimeSeconds(row.created_at) }}</template>
          </AppTableColumn>
          <AppTableColumn label="操作" role="action" fixed="right">
            <template #default="{ row }">
              <AppRowActions
                :actions="userRowActions(row)"
                :inline-limit="3"
                :test-id="`user-row-actions-${row.account}`"
              />
            </template>
          </AppTableColumn>
        </AppDataTable>
        </template>
      </el-card>
    </template>

    <template #overlays>
      <!-- 新建 / 编辑用户 -->
      <AppDialog v-model="dialogVisible" :title="isEdit ? '编辑用户' : '新建用户'" size="large">
        <el-form label-width="76px">
          <el-form-item label="账号" :required="!isEdit">
            <el-input v-model="form.account" :disabled="isEdit" placeholder="账号唯一，创建后不可改" />
          </el-form-item>
          <el-form-item v-if="!isEdit" label="初始密码" required>
            <el-input v-model="form.password" type="password" show-password
                      placeholder="≥8 位，含字母与数字" />
          </el-form-item>
          <el-form-item label="邮箱">
            <el-input v-model="form.email" placeholder="选填" />
          </el-form-item>
          <el-form-item label="角色" :required="!protectedRoleNames.length">
            <el-select v-model="form.roleIds" multiple placeholder="可多选，权限取并集"
                       style="width: 100%">
              <el-option
                v-for="r in assignableRoles"
                :key="r.id"
                :label="r.name"
                :value="r.id"
                :disabled="editingOwnSystemRole && r.code === 'system'"
              />
            </el-select>
          </el-form-item>
          <el-form-item v-if="isEdit && protectedRoleNames.length" label="平台保留">
            <span class="locked-field">
              {{ protectedRoleNames.join('、') }}
              <span class="muted">（仅平台管理员可调整，本次保存会保留）</span>
            </span>
          </el-form-item>
          <el-form-item label="租户">
            <el-select v-if="isSystem && !isEdit" v-model="form.tenantId" placeholder="归属租户"
                       style="width: 100%">
              <el-option v-for="t in tenants" :key="t.id" :label="t.name" :value="t.id" />
            </el-select>
            <span v-else class="locked-field">
              {{ tenantName(form.tenantId) }}<span class="muted">（{{ isEdit ? '归属不可改' : '限本租户' }}）</span>
            </span>
          </el-form-item>
          <el-form-item label="状态" :required="!editingSelf">
            <el-radio-group v-model="form.status" :disabled="editingSelf">
              <el-radio-button v-for="item in userStatusOptions" :key="item.code" :value="item.code">
                {{ item.label }}
              </el-radio-button>
            </el-radio-group>
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="dialogVisible = false">取消</el-button>
          <el-button type="primary" :loading="saving" @click="save">保存</el-button>
        </template>
      </AppDialog>

      <!-- 重置密码 -->
      <AppDialog v-model="resetVisible" title="重置密码" size="compact">
        <el-form label-width="76px">
          <el-form-item label="账号">
            <span>{{ resetTarget?.account }}</span>
          </el-form-item>
          <el-form-item label="新密码" required>
            <el-input v-model="resetForm.pwd" type="password" show-password
                      placeholder="≥8 位，含字母与数字" />
          </el-form-item>
          <el-form-item label="确认" required>
            <el-input v-model="resetForm.confirm" type="password" show-password placeholder="再次输入" />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="resetVisible = false">取消</el-button>
          <el-button type="primary" :loading="resetting" @click="confirmReset">重置密码</el-button>
        </template>
      </AppDialog>

      <PageSettingsDrawer
        v-model="settingsOpen"
        title="用户管理"
        :dirty="isDirty || layoutDirty"
        page-key="user-manage"
        :config="drawerConfig"
        @reset="reset(); resetLayout()"
      >
        <template #business>
          <PageSettingSection title="默认查询">
            <PageSettingItem label="状态筛选">
              <PageSegmented v-model="settings.defaultStatus" aria-label="状态筛选" :options="[
                { label: '全部', value: 'all' },
                { label: '仅启用', value: 'active' },
              ]" />
            </PageSettingItem>
          </PageSettingSection>
        </template>
      </PageSettingsDrawer>
    </template>
  </LayoutHost>
</template>

<style scoped>
.page-head { display: flex; justify-content: space-between; align-items: flex-start; gap: var(--app-space-3); }
.page-head-actions { display: flex; align-items: center; gap: var(--app-space-2); }
.muted { color: var(--el-text-color-secondary); }
.locked-field { color: var(--el-text-color-regular); }
</style>
