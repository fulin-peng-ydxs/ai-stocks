<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import AppStateBlock from '@/components/AppStateBlock.vue'
import HelpTip from '@/components/HelpTip.vue'
import PageSettingsDrawer from '@/components/PageSettingsDrawer.vue'
import PageSettingsTrigger from '@/components/PageSettingsTrigger.vue'
import SystemBuiltinTag from '@/components/SystemBuiltinTag.vue'
import LayoutHost from '@/layout/components/LayoutHost.vue'
import PermissionTree from './PermissionTree.vue'
import type { PermNode } from './permissionTree'
import { getPageLayout } from '@/layout'
import { usePageSettings } from '@/composables/usePageSettings'
import { useRemoteLayoutConfig } from '@/composables/useRemoteLayoutConfig'
import { useAuthStore } from '@/stores/auth'
import { hasPermission } from '@/utils/permission'
import {
  listRoles, createRole, updateRole, deleteRole, getRoleGrants, setRoleGrants, type Role,
} from '@/api/role'
import { listMenus, listResources, type MenuNode, type Resource } from '@/api/menu'

const auth = useAuthStore()

// ── 布局/设置抽屉（本页无业务旋钮，抽屉仅布局段）──
const roleLayout = getPageLayout('role-manage')
const {
  effective, knobs: layoutKnobs, setKnob, valueOf, sourceOf,
  isDirty: layoutDirty, resetAll: resetLayout,
  componentValueOf, setComponentKnob, componentSourceOf, layerValuesOf, componentLayerValuesOf,
} = useRemoteLayoutConfig(roleLayout)
const drawerConfig = { knobs: layoutKnobs, valueOf, sourceOf, setKnob, componentValueOf, setComponentKnob, componentSourceOf, layerValuesOf, componentLayerValuesOf }
const { reset: resetBiz } = usePageSettings('role-manage', {})
const settingsOpen = ref(false)

// ── 角色列表 ──
const roles = ref<Role[]>([])
const activeId = ref<string>('')
const activeRole = computed<Role | null>(() => roles.value.find((r) => r.id === activeId.value) ?? null)
const activeIsSystemRole = computed(
  () => activeRole.value?.code === 'system' || activeRole.value?.kind === 'system' || !!activeRole.value?.is_locked,
)
const rolesLoading = ref(false)
const loadError = ref(false)   // 权限树/角色初次加载失败 → 页内错误态 + 重试

async function loadRoles(keepActive = false) {
  rolesLoading.value = true
  try {
    roles.value = await listRoles()
    if (!keepActive || !roles.value.some((r) => r.id === activeId.value)) {
      if (roles.value.length) await selectRole(roles.value[0].id)
    }
  } finally {
    rolesLoading.value = false
  }
}

// ── 权限树：菜单(分组/叶子) + 功能点，组装成三级树（渲染交 PermissionTree）──
const treeData = ref<PermNode[]>([])
const allCheckableLeafKeys = ref<string[]>([]) // 非置灰的原子叶子（功能点 + 无子菜单），供“全选”
const leafMenuKeysNoChildren = ref<Set<string>>(new Set()) // 无任何子节点的菜单（授权回显走叶子）

function buildTree(menus: MenuNode[], resources: Resource[]) {
  const resByMenu = new Map<string, Resource[]>()
  for (const r of resources) {
    if (!resByMenu.has(r.menu_id)) resByMenu.set(r.menu_id, [])
    resByMenu.get(r.menu_id)!.push(r)
  }
  const leaves: string[] = []
  const noChild = new Set<string>()

  const walk = (m: MenuNode, parentLocked: boolean): PermNode => {
    const locked = parentLocked || m.visible === 'system'
    const children: PermNode[] = []
    for (const c of m.children || []) children.push(walk(c, locked))
    for (const res of resByMenu.get(m.id) || []) {
      const key = `r:${res.id}`
      const baselineLocked = !!res.baseline_locked
      children.push({
        key,
        code: res.code,
        label: res.name,
        kind: 'resource',
        nodeType: res.type,
        sysLocked: locked,
        baselineLocked,
      })
      // baseline 恒勾选、不可反选：排除出可勾选/全选原子叶子集（后端强制注入+保存并入，前端不当作授权项）
      if (!locked && !baselineLocked) leaves.push(key)
    }
    const key = `m:${m.id}`
    if (!children.length) {
      noChild.add(key)
      if (!locked) leaves.push(key) // 无子菜单本身即可勾选的原子叶子
    }
    return { key, label: m.title, kind: 'menu', nodeType: m.type, sysLocked: locked,
             children: children.length ? children : undefined }
  }

  treeData.value = menus.map((m) => walk(m, false))
  allCheckableLeafKeys.value = leaves
  leafMenuKeysNoChildren.value = noChild
}

// ── 三态勾选：以「原子叶子集合 checked」派生分组/菜单态，级联 = 批量增删原子叶子 ──
const checked = ref<Set<string>>(new Set())
const treeReadonly = computed(
  () => !!activeRole.value?.is_locked || !hasPermission(auth.role, auth.permissions, 'role:assign-perm'))

/** 节点下所有可勾选原子叶子（功能点 + 无子菜单）；system 锁定子树排除。 */
function atomicLeaves(node: PermNode): string[] {
  if (!node.children?.length) return (node.sysLocked || node.baselineLocked) ? [] : [node.key]
  return node.children.flatMap(atomicLeaves)
}
function stateOf(node: PermNode): 'on' | 'half' | 'off' {
  if (activeIsSystemRole.value) return 'on'
  const leaves = atomicLeaves(node)
  if (!leaves.length) return 'off'
  let on = 0
  for (const k of leaves) if (checked.value.has(k)) on++
  return on === 0 ? 'off' : on === leaves.length ? 'on' : 'half'
}
function toggle(node: PermNode) {
  if (treeReadonly.value || node.sysLocked || node.baselineLocked) return
  const leaves = atomicLeaves(node)
  if (!leaves.length) return
  const turnOn = stateOf(node) !== 'on'
  const next = new Set(checked.value)
  for (const k of leaves) turnOn ? next.add(k) : next.delete(k)
  checked.value = next
  onCheck()
}

function allNodes(nodes: PermNode[]): PermNode[] {
  return nodes.flatMap((n) => [n, ...(n.children ? allNodes(n.children) : [])])
}

// ── 授权回显 / 收集 / 脏检测 ──
let originalKey = ''
const dirty = ref(false)

/** menuIds=选中∪半选的菜单（含无子被勾的叶子菜单）；resourceIds=选中的功能点。 */
function gatherGrants(): { menuIds: string[]; resourceIds: string[] } {
  const nodes = allNodes(treeData.value)
  const menuIds = nodes.filter((n) => n.kind === 'menu' && stateOf(n) !== 'off').map((n) => n.key.slice(2))
  const resourceIds = [...checked.value].filter((k) => k.startsWith('r:')).map((k) => k.slice(2))
  return { menuIds, resourceIds }
}
function grantsFingerprint(g: { menuIds: string[]; resourceIds: string[] }): string {
  return JSON.stringify([[...g.menuIds].sort(), [...g.resourceIds].sort()])
}

async function selectRole(id: string) {
  activeId.value = id
  const grants = await getRoleGrants(id)
  // 回显走原子叶子：功能点 id + 无子菜单 id；其余分组/菜单由 stateOf 级联回算半选/全选。
  const leaves = [
    ...grants.resource_ids.map((r) => `r:${r}`),
    ...grants.menu_ids.filter((m) => leafMenuKeysNoChildren.value.has(`m:${m}`)).map((m) => `m:${m}`),
  ].filter((k) => allCheckableLeafKeys.value.includes(k)) // 排除 system 锁定叶子
  checked.value = new Set(leaves)
  originalKey = grantsFingerprint(gatherGrants())
  dirty.value = false
}

function onCheck() {
  dirty.value = grantsFingerprint(gatherGrants()) !== originalKey
}
function setAll(v: boolean) {
  if (treeReadonly.value) return
  checked.value = v ? new Set(allCheckableLeafKeys.value) : new Set()
  onCheck()
}
function resetGrants() {
  if (!activeId.value) return
  selectRole(activeId.value)
  ElMessage.info('已还原到已保存的权限')
}

const saving = ref(false)
async function save() {
  if (!activeId.value || treeReadonly.value) return
  saving.value = true
  try {
    const g = gatherGrants()
    await setRoleGrants(activeId.value, { menuIds: g.menuIds, resourceIds: g.resourceIds })
    ElMessage.success('已保存并刷新该角色用户权限')
    originalKey = grantsFingerprint(g)
    dirty.value = false
  } catch { /* system-only/不存在等由拦截器弹出 */ } finally { saving.value = false }
}

// ── 角色 新建 / 重命名 / 删除 ──
const dialogVisible = ref(false)
const dialogMode = ref<'create' | 'rename'>('create')
const roleForm = ref<{ code: string; name: string; description: string }>({ code: '', name: '', description: '' })
const roleSaving = ref(false)

function openCreate() {
  dialogMode.value = 'create'
  roleForm.value = { code: '', name: '', description: '' }
  dialogVisible.value = true
}
function openRename() {
  const r = activeRole.value
  if (!r) return
  dialogMode.value = 'rename'
  roleForm.value = { code: r.code, name: r.name, description: r.description ?? '' }
  dialogVisible.value = true
}
async function saveRole() {
  if (!roleForm.value.name.trim()) { ElMessage.warning('请填写角色名称'); return }
  roleSaving.value = true
  try {
    if (dialogMode.value === 'create') {
      const r = await createRole({
        name: roleForm.value.name.trim(),
        description: roleForm.value.description.trim() || null,
      })
      ElMessage.success('已创建')
      await loadRoles(true)
      await selectRole(r.id)
    } else {
      await updateRole(activeId.value, {
        name: roleForm.value.name.trim(), description: roleForm.value.description.trim() || null,
      })
      ElMessage.success('已保存')
      await loadRoles(true)
    }
    dialogVisible.value = false
  } catch { /* 唯一冲突/锁定等由拦截器弹出 */ } finally { roleSaving.value = false }
}
async function removeRole() {
  const r = activeRole.value
  if (!r) return
  try {
    await ElMessageBox.confirm(`确认删除自定义角色「${r.name}」？删除后不可恢复。`, '删除角色',
      { type: 'warning', confirmButtonText: '删除', confirmButtonClass: 'el-button--danger' })
    await deleteRole(r.id)
    ElMessage.success('已删除')
    activeId.value = ''
    await loadRoles()
  } catch (e) { if (e === 'cancel') return /* 被引用/内置等由拦截器弹出 */ }
}

async function loadAll() {
  loadError.value = false
  try {
    // 权限树（菜单+资源）与角色列表任一加载失败都进错误态，保证 error+retry 闭环
    const [menus, resources] = await Promise.all([listMenus(), listResources()])
    buildTree(menus, resources)
    await loadRoles()
  } catch {
    loadError.value = true
  }
}
onMounted(loadAll)
</script>

<template>
  <LayoutHost :layout="effective">
    <template #action>
      <div class="lh-action">
        <div class="page-head">
          <div>
            <h2 class="app-page-title">
              角色管理
              <HelpTip title="角色管理说明" :width="440">
                角色勾选菜单与功能点后保存，拥有该角色的用户权限即时生效（无权按钮消失 / 接口 403）。<br /><br />
                授权按菜单分组展示，功能点默认收起；需要精细调整时再展开对应菜单，避免所有权限同时铺开。<br /><br />
                「基线」是登录后的共享读权限，后端自动拥有、不可取消，也不作为角色授权保存。<br /><br />
                系统管理员角色拥有全部菜单与功能点，页面仅展示已拥有且锁定；「仅系统管理员」资源不能授予其它角色。
              </HelpTip>
            </h2>
            <p class="page-subtitle">管理角色及其功能点/菜单授权，多角色可叠加权限。</p>
          </div>
          <div class="page-head-actions">
            <el-button v-permission="'role:create'" type="primary" @click="openCreate">
              <template #icon><el-icon><Plus /></el-icon></template>
              新建角色
            </el-button>
            <PageSettingsTrigger :dirty="layoutDirty" @click="settingsOpen = true" />
          </div>
        </div>
      </div>
    </template>

    <template #main>
      <AppStateBlock
        v-if="loadError"
        state="error"
        title="权限树加载失败"
        description="请检查网络或稍后重试"
        class="rm-error"
        retry
        @retry="loadAll"
      />
      <div v-else class="rm-split">
        <!-- 左：角色列表 -->
        <div class="rm-col rm-left">
          <div class="rm-col-head">
            <span class="rm-head-title">角色 <span class="mini">{{ roles.length }}</span></span>
          </div>
          <div class="rm-col-body" v-loading="rolesLoading">
            <div
              v-for="r in roles"
              :key="r.id"
              class="role"
              :class="{ active: r.id === activeId }"
              @click="selectRole(r.id)"
            >
              <div class="role-name">
                {{ r.name }}
                <SystemBuiltinTag v-if="r.is_builtin" />
              </div>
              <div v-if="r.member_count != null" class="role-desc">关联用户 {{ r.member_count }} 名</div>
            </div>
            <el-empty v-if="!rolesLoading && !roles.length" class="app-empty app-empty--compact" description="暂无角色" />
          </div>
        </div>

        <!-- 右：权限树 -->
        <div class="rm-col rm-right">
          <div class="rm-detail-bar">
              <div class="rm-detail-title">
              <h2 class="rname">
                {{ activeRole?.name || '—' }}
                <SystemBuiltinTag v-if="activeRole?.is_builtin" />
              </h2>
              <div class="rmeta">
                <template v-if="activeRole">
                  角色码 {{ activeRole.code }}<span v-if="activeRole.member_count != null"> · 关联用户 {{ activeRole.member_count }} 名</span>
                  <span v-if="activeIsSystemRole" class="lock-note"> · 全量权限锁定，不可编辑</span>
                </template>
              </div>
            </div>
            <div class="page-head-actions" v-if="activeRole">
              <el-button v-if="!activeRole.is_locked" v-permission="'role:update'" size="small" @click="openRename">重命名</el-button>
              <el-button v-if="!activeRole.is_builtin" v-permission="'role:delete'" size="small" type="danger" plain
                         @click="removeRole">删除</el-button>
              <el-button size="small" :disabled="treeReadonly" @click="setAll(true)">全选</el-button>
              <el-button size="small" :disabled="treeReadonly" @click="setAll(false)">清空</el-button>
            </div>
          </div>

          <div class="rm-col-body">
            <template v-if="activeRole">
              <PermissionTree
                v-for="node in treeData" :key="node.key"
                :node="node" :state-of="stateOf" :toggle="toggle" :readonly="treeReadonly"
              />
            </template>
            <el-empty v-else class="app-empty app-empty--compact" description="请选择左侧角色" />
          </div>

          <div class="rm-detail-foot" v-if="activeRole">
            <span class="dirty" :class="{ hidden: !dirty }">● 有未保存修改</span>
            <div class="page-head-actions">
              <el-button :disabled="!dirty || treeReadonly" @click="resetGrants">还原</el-button>
              <el-button type="primary" :loading="saving" :disabled="treeReadonly" @click="save">保存并刷新权限</el-button>
            </div>
          </div>
        </div>
      </div>
    </template>

    <template #overlays>
      <el-dialog v-model="dialogVisible" :title="dialogMode === 'create' ? '新建角色' : '重命名角色'" width="420px">
        <el-form label-width="72px">
          <el-form-item label="角色名">
            <el-input v-model="roleForm.name" placeholder="如：数据分析员" />
          </el-form-item>
          <el-form-item v-if="dialogMode === 'rename'" label="角色码">
            <el-input v-model="roleForm.code" :disabled="dialogMode === 'rename'"
                      placeholder="系统生成，创建后不可改" />
          </el-form-item>
          <el-form-item label="描述">
            <el-input v-model="roleForm.description" placeholder="可选" />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="dialogVisible = false">取消</el-button>
          <el-button type="primary" :loading="roleSaving" @click="saveRole">保存</el-button>
        </template>
      </el-dialog>

      <PageSettingsDrawer
        v-model="settingsOpen"
        title="角色管理"
        :dirty="layoutDirty"
        page-key="role-manage"
        :config="drawerConfig"
        @reset="resetBiz(); resetLayout()"
      />
    </template>
  </LayoutHost>
</template>

<style scoped>
.page-head { display: flex; justify-content: space-between; align-items: flex-start; gap: var(--app-space-3); }
.page-head-actions { display: flex; align-items: center; gap: var(--app-space-2); }
.rm-error { height: 100%; }
/* master-detail：窄视口体内横滚，右栏不被压垮 */
.rm-split { height: 100%; display: flex; gap: var(--app-space-4); min-height: 0; overflow-x: auto; }
.rm-col { border: 1px solid var(--el-border-color); border-radius: 8px; background: var(--el-bg-color-overlay);
  display: flex; flex-direction: column; min-height: 0; }
.rm-left { width: 288px; flex: none; }
.rm-right { flex: 1 1 auto; min-width: 460px; }
.rm-col-head { padding: 11px 14px; border-bottom: 1px solid var(--el-border-color-lighter); font-weight: var(--app-font-weight-section);
  display: flex; align-items: center; justify-content: space-between; gap: var(--app-space-2); }
.rm-head-title { display: inline-flex; align-items: center; gap: var(--app-space-2); min-width: 0; }
.rm-col-head .mini { font-size: var(--app-font-size-caption); color: var(--el-text-color-secondary); font-weight: var(--app-font-weight-regular); }
.rm-col-body { flex: 1 1 auto; min-height: 0; overflow: auto; padding: 10px 14px; }
.role { padding: 10px 12px; border-radius: 7px; cursor: pointer; margin-bottom: 4px; border: 1px solid transparent; }
.role:hover { background: var(--el-fill-color-light); }
.role.active { background: var(--el-color-primary-light-9); border-color: var(--el-color-primary-light-5); }
.role-name { font-size: var(--app-font-size-body); font-weight: var(--app-font-weight-section); display: flex; align-items: center; gap: var(--app-space-2); }
.role-desc { font-size: var(--app-font-size-caption); color: var(--el-text-color-secondary); margin-top: 3px; }
.rm-detail-bar { padding: 12px 16px; border-bottom: 1px solid var(--el-border-color-lighter);
  display: flex; align-items: center; justify-content: space-between; gap: var(--app-space-3); }
.rm-detail-title .rname { font-size: var(--app-font-size-section-title); font-weight: var(--app-font-weight-strong);
  display: flex; align-items: center; gap: var(--app-space-2); margin: 0; }
.rm-detail-title .rmeta { font-size: var(--app-font-size-caption); color: var(--el-text-color-secondary); margin-top: 2px; }
.lock-note { color: var(--el-color-warning); }
.rm-detail-foot { border-top: 1px solid var(--el-border-color-lighter); padding: 12px 16px;
  display: flex; align-items: center; justify-content: space-between; }
.dirty { font-size: var(--app-font-size-caption); color: var(--el-color-warning); }
.dirty.hidden { visibility: hidden; }
</style>
