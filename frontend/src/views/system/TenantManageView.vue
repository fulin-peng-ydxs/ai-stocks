<script setup lang="ts">
// 租户管理页（多租户 RBAC stage3·T14，R14）。承接 tenant-management.html（去勾选列、无批量工具条）。
// 列表 + 筛选 + 分页 + 编辑弹窗（含指定管理员）+ 行内启停 + 查看用户跳转。整页仅系统管理员可达（require_system）。
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { DEFAULT_PAGE_SIZE, PAGE_SIZE_OPTIONS } from '@/constants/pagination'
import HelpTip from '@/components/HelpTip.vue'
import PageSettingsDrawer from '@/components/PageSettingsDrawer.vue'
import PageSettingsTrigger from '@/components/PageSettingsTrigger.vue'
import LayoutHost from '@/layout/components/LayoutHost.vue'
import { getPageLayout } from '@/layout'
import { usePageSettings } from '@/composables/usePageSettings'
import { useRemoteLayoutConfig } from '@/composables/useRemoteLayoutConfig'
import { useAuthStore } from '@/stores/auth'
import {
  listTenants, createTenant, updateTenant, setTenantStatus, deleteTenant, type Tenant,
} from '@/api/tenant'
import { listUsers, type AdminUser } from '@/api/user'

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
  componentValueOf, setComponentKnob, componentSourceOf, layerValuesOf, componentLayerValuesOf,
} = useRemoteLayoutConfig(tenantLayout)
const drawerConfig = { knobs: layoutKnobs, valueOf, sourceOf, setKnob, componentValueOf, setComponentKnob, componentSourceOf, layerValuesOf, componentLayerValuesOf }
const settingsOpen = ref(false)

const defaultSort = computed<'created' | 'name' | 'userCount'>(
  () => (componentValueOf('table', 'defaultSort') as 'created' | 'name' | 'userCount') ?? 'created')
const hiddenColumns = computed<string[]>(() => (componentValueOf('table', 'hiddenColumns') as string[]) ?? [])
function colVisible(key: string): boolean {
  return !hiddenColumns.value.includes(key)
}

// ── 列表 ──
const loading = ref(false)
const loadError = ref(false)   // 列表加载失败 → 页内错误态 + 重试
const list = ref<Tenant[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(DEFAULT_PAGE_SIZE)
const filters = ref<{ status: string; q: string }>({ status: '', q: '' })

const STATUS_TAG: Record<string, { type: 'success' | 'danger'; label: string }> = {
  active: { type: 'success', label: '启用' },
  disabled: { type: 'danger', label: '已停用' },
}

// 服务端分页，排序仅影响当前页（与用户管理页口径一致）。
const displayList = computed(() => {
  const rows = [...list.value]
  if (defaultSort.value === 'name') {
    rows.sort((a, b) => a.name.localeCompare(b.name))
  } else if (defaultSort.value === 'userCount') {
    rows.sort((a, b) => (b.user_count ?? 0) - (a.user_count ?? 0))
  }
  return rows
})

async function load() {
  loading.value = true
  loadError.value = false
  try {
    const res = await listTenants({
      status: filters.value.status || undefined,
      q: filters.value.q.trim() || undefined,
      page: page.value, size: size.value,
    })
    list.value = res.items
    total.value = res.total
  } catch {
    loadError.value = true
  } finally {
    loading.value = false
  }
}

watch(() => filters.value.status, () => { page.value = 1; load() })
function search() { page.value = 1; load() }

function fmtTime(v?: string | null): string {
  return (v || '—').slice(0, 19).replace('T', ' ')
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

// ── 新建 / 编辑弹窗 ──
const dialogVisible = ref(false)
const editing = ref<Tenant | null>(null)
const isEdit = computed(() => editing.value !== null)
const form = ref<{ name: string; status: string; adminUserId: string }>(
  { name: '', status: 'active', adminUserId: '' })
const saving = ref(false)
// 编辑时该租户用户（供「指定管理员」下拉）
const tenantUsers = ref<AdminUser[]>([])
const usersLoading = ref(false)

function openCreate() {
  editing.value = null
  form.value = { name: '', status: 'active', adminUserId: '' }
  tenantUsers.value = []
  dialogVisible.value = true
}
async function openEdit(row: Tenant) {
  editing.value = row
  form.value = { name: row.name, status: row.status, adminUserId: row.admin_user_id ?? '' }
  dialogVisible.value = true
  // 拉该租户用户填充「指定管理员」下拉（system 可跨租户按 tenant 过滤）
  usersLoading.value = true
  try {
    tenantUsers.value = (await listUsers({ tenant_id: row.id, size: 200 })).items
  } catch { tenantUsers.value = [] } finally { usersLoading.value = false }
}
async function save() {
  if (!form.value.name.trim()) { ElMessage.warning('请填写租户名称'); return }
  saving.value = true
  try {
    if (isEdit.value) {
      await updateTenant(editing.value!.id, {
        name: form.value.name.trim(),
        adminUserId: form.value.adminUserId || null,
      })
      ElMessage.success('已保存')
    } else {
      await createTenant({ name: form.value.name.trim(), status: form.value.status })
      ElMessage.success('已创建')
    }
    dialogVisible.value = false
    await load()
  } catch { /* 名称唯一/管理员不属该租户等由拦截器弹出 */ } finally { saving.value = false }
}

onMounted(async () => {
  filters.value.status = settings.defaultStatus === 'active' ? 'active' : ''
  await load()
})
watch(() => settings.defaultStatus, (v) => { filters.value.status = v === 'active' ? 'active' : '' })
</script>

<template>
  <LayoutHost :layout="effective">
    <template #action>
      <div class="lh-action">
        <div class="page-head">
          <h2>
            租户管理
            <HelpTip title="租户管理说明" :width="420">
              租户增删改、指定管理员、启停。<br /><br />
              默认租户不可停用 / 删除；<b>停用</b>后其下用户立即不可登录（在线会话下次校验即失效）。<br /><br />
              删除仅限无用户的租户；「查看用户」跳用户管理并按该租户过滤。
            </HelpTip>
          </h2>
          <div class="page-head-actions">
            <el-button v-permission="'tenant:create'" type="primary" @click="openCreate">＋ 新建租户</el-button>
            <PageSettingsTrigger :dirty="isDirty || layoutDirty" @click="settingsOpen = true" />
          </div>
        </div>

        <div class="filter-bar">
          <el-select v-model="filters.status" placeholder="状态：全部" clearable style="width: 140px">
            <el-option label="启用" value="active" />
            <el-option label="已停用" value="disabled" />
          </el-select>
          <el-input v-model="filters.q" placeholder="搜索租户名 / ID" clearable style="width: 220px"
                    @keyup.enter="search" @clear="search" />
          <el-button @click="search">查询</el-button>
        </div>
      </div>
    </template>

    <template #main>
      <el-card shadow="never">
        <el-result v-if="loadError" icon="warning" title="租户列表加载失败" sub-title="请检查网络或稍后重试">
          <template #extra><el-button type="primary" @click="load">重试</el-button></template>
        </el-result>
        <template v-else>
        <!-- row-key：稳定行标识，避免新增/重排时 fixed 列单元格 v-if（如「内置」标签）DOM 复用错位 -->
        <el-table :data="displayList" row-key="id" size="small" height="100%" v-loading="loading">
          <el-table-column label="租户名" prop="name" min-width="180" fixed="left" show-overflow-tooltip>
            <template #default="{ row }">
              {{ row.name }}
              <el-tag v-if="row.id === DEFAULT_TENANT_ID" type="info" size="small" effect="plain" class="builtin-tag">内置</el-tag>
            </template>
          </el-table-column>
          <el-table-column v-if="colVisible('id')" label="租户 ID" prop="id" width="150">
            <template #default="{ row }"><span class="mono">{{ row.id }}</span></template>
          </el-table-column>
          <el-table-column label="状态" width="92">
            <template #default="{ row }">
              <el-tag :type="STATUS_TAG[row.status]?.type ?? 'info'" size="small" effect="plain">
                {{ STATUS_TAG[row.status]?.label ?? row.status }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column v-if="colVisible('admin')" label="租户管理员" min-width="150" show-overflow-tooltip>
            <template #default="{ row }">{{ row.admin_account || '—' }}</template>
          </el-table-column>
          <el-table-column v-if="colVisible('userCount')" label="用户数" width="90" align="right">
            <template #default="{ row }">{{ row.user_count ?? 0 }}</template>
          </el-table-column>
          <el-table-column v-if="colVisible('created')" label="创建时间" width="160">
            <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="230" fixed="right">
            <template #default="{ row }">
              <el-button v-permission="'tenant:update'" type="primary" size="small" link
                         @click="openEdit(row)">编辑</el-button>
              <el-button type="primary" size="small" link @click="viewUsers(row)">查看用户</el-button>
              <el-button v-if="row.status === 'active' && row.id !== DEFAULT_TENANT_ID" v-permission="'tenant:disable'"
                         type="danger" size="small" link @click="changeStatus(row, 'disabled', '停用')">停用</el-button>
              <el-button v-if="row.status === 'disabled'" v-permission="'tenant:disable'"
                         type="success" size="small" link @click="changeStatus(row, 'active', '启用')">启用</el-button>
              <el-button v-if="row.id !== DEFAULT_TENANT_ID" v-permission="'tenant:delete'" type="danger" size="small" link
                         :disabled="(row.user_count ?? 0) > 0"
                         :title="(row.user_count ?? 0) > 0 ? '该租户仍有用户，不可删除' : ''"
                         @click="removeTenant(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
        <div class="pager">
          <el-pagination layout="total, sizes, prev, pager, next" :total="total" background
                         :current-page="page" :page-size="size" :page-sizes="PAGE_SIZE_OPTIONS"
                         @current-change="(p: number) => { page = p; load() }"
                         @size-change="(s: number) => { size = s; page = 1; load() }" />
        </div>
        </template>
      </el-card>
    </template>

    <template #overlays>
      <el-dialog v-model="dialogVisible" :title="isEdit ? '编辑租户' : '新建租户'" width="460px">
        <el-form label-width="88px">
          <el-form-item label="租户名">
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
          <el-form-item v-if="!isEdit" label="状态">
            <el-radio-group v-model="form.status">
              <el-radio-button value="active">启用</el-radio-button>
              <el-radio-button value="disabled">停用</el-radio-button>
            </el-radio-group>
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="dialogVisible = false">取消</el-button>
          <el-button type="primary" :loading="saving" @click="save">保存</el-button>
        </template>
      </el-dialog>

      <PageSettingsDrawer
        v-model="settingsOpen"
        title="租户管理"
        :dirty="isDirty || layoutDirty"
        page-key="tenant-manage"
        :config="drawerConfig"
        @reset="reset(); resetLayout()"
      />
    </template>
  </LayoutHost>
</template>

<style scoped>
.page-head { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 14px; }
.page-head h2 { margin: 0; font-size: 20px; }
.page-head-actions { display: flex; align-items: center; gap: 10px; }
.filter-bar { display: flex; gap: 10px; align-items: center; margin-bottom: 12px; flex-wrap: wrap; }
.builtin-tag { margin-left: 4px; }
.mono { font-family: ui-monospace, Menlo, monospace; font-size: 12px; }
.muted { color: var(--el-text-color-secondary); }
.locked-field { color: var(--el-text-color-regular); }
.pager { display: flex; justify-content: flex-end; margin-top: 12px; }
</style>
