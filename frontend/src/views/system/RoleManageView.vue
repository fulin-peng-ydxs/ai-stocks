<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox, ElTree } from 'element-plus'
import HelpTip from '@/components/HelpTip.vue'
import PageSettingsDrawer from '@/components/PageSettingsDrawer.vue'
import PageSettingsTrigger from '@/components/PageSettingsTrigger.vue'
import LayoutHost from '@/layout/components/LayoutHost.vue'
import { getPageLayout } from '@/layout'
import { usePageSettings } from '@/composables/usePageSettings'
import { useRemoteLayoutConfig } from '@/composables/useRemoteLayoutConfig'
import { useAuthStore } from '@/stores/auth'
import {
  listRoles, createRole, updateRole, deleteRole, getRoleGrants, setRoleGrants, type Role,
} from '@/api/role'
import { listMenus, listResources, type MenuNode, type Resource } from '@/api/menu'

const auth = useAuthStore()
function can(code: string): boolean {
  return auth.role === 'system' || auth.permissions.includes(code)
}

// ── 布局/设置抽屉（本页无业务旋钮，抽屉仅布局+组件段）──
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
const rolesLoading = ref(false)

function roleTag(r: Role): { text: string; type: 'warning' | 'info' | 'primary' } {
  if (r.is_locked) return { text: '超管·锁定', type: 'warning' }
  if (r.kind === 'paid') return { text: '付费·预留', type: 'primary' }
  if (r.is_builtin) return { text: '内置', type: 'info' }
  return { text: '自定义', type: 'info' }
}

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

// ── 权限树：菜单(分组/叶子) + 功能点，组装成三级三态树 ──
interface TreeNode {
  key: string
  label: string
  kind: 'menu' | 'resource'
  nodeType: string // menu: group/leaf；resource: button/api
  sysLocked: boolean // system 可见菜单子树：非 system 角色不可授（后端 system-only 码硬拒，前端置灰）
  children?: TreeNode[]
}
const treeData = ref<TreeNode[]>([])
const allCheckableLeafKeys = ref<string[]>([]) // 非置灰的叶子（功能点 + 无子菜单），供“全选”
const leafMenuKeysNoChildren = ref<Set<string>>(new Set()) // 无任何子节点的菜单（授权回显走叶子）

function buildTree(menus: MenuNode[], resources: Resource[]) {
  const resByMenu = new Map<string, Resource[]>()
  for (const r of resources) {
    if (!resByMenu.has(r.menu_id)) resByMenu.set(r.menu_id, [])
    resByMenu.get(r.menu_id)!.push(r)
  }
  const leaves: string[] = []
  const noChild = new Set<string>()

  const walk = (m: MenuNode, parentLocked: boolean): TreeNode => {
    const locked = parentLocked || m.visible === 'system'
    const children: TreeNode[] = []
    for (const c of m.children || []) children.push(walk(c, locked))
    for (const res of resByMenu.get(m.id) || []) {
      const key = `r:${res.id}`
      const node: TreeNode = {
        key, label: res.name, kind: 'resource',
        nodeType: res.type, sysLocked: locked,
      }
      children.push(node)
      if (!locked) leaves.push(key)
    }
    const key = `m:${m.id}`
    if (!children.length) {
      noChild.add(key)
      if (!locked) leaves.push(key) // 无子菜单本身即可勾选的叶子
    }
    return { key, label: m.title, kind: 'menu', nodeType: m.type, sysLocked: locked,
             children: children.length ? children : undefined }
  }

  treeData.value = menus.map((m) => walk(m, false))
  allCheckableLeafKeys.value = leaves
  leafMenuKeysNoChildren.value = noChild
}

const treeRef = ref<InstanceType<typeof ElTree>>()
const treeProps = {
  label: 'label', children: 'children',
  // 超管锁定 → 整树只读；system 可见菜单子树 → 任何可编辑角色都不可授（后端亦硬拒）
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  disabled: (data: any) => treeReadonly.value || Boolean((data as TreeNode).sysLocked),
}
const treeReadonly = computed(() => !!activeRole.value?.is_locked || !can('role:assign-perm'))

// ── 授权回显 / 收集 / 脏检测 ──
let originalKey = '' // 载入时的规范化授权指纹，用于脏检测与“还原”
const dirty = ref(false)

/** 从树勾选态收集授权：menuIds=选中∪半选的菜单；resourceIds=选中的功能点。 */
function gatherGrants(): { menuIds: string[]; resourceIds: string[] } {
  const t = treeRef.value
  if (!t) return { menuIds: [], resourceIds: [] }
  const checked = t.getCheckedKeys(false) as string[]
  const half = t.getHalfCheckedKeys() as string[]
  const menuIds = [...checked, ...half].filter((k) => k.startsWith('m:')).map((k) => k.slice(2))
  const resourceIds = checked.filter((k) => k.startsWith('r:')).map((k) => k.slice(2))
  return { menuIds, resourceIds }
}
function grantsFingerprint(g: { menuIds: string[]; resourceIds: string[] }): string {
  return JSON.stringify([[...g.menuIds].sort(), [...g.resourceIds].sort()])
}

async function selectRole(id: string) {
  activeId.value = id
  const grants = await getRoleGrants(id)
  await nextTick()
  // 回显走叶子：功能点 id + 无子菜单 id；其余菜单/分组由 el-tree 级联回算半选/全选。
  const leaves = [
    ...grants.resource_ids.map((r) => `r:${r}`),
    ...grants.menu_ids.filter((m) => leafMenuKeysNoChildren.value.has(`m:${m}`)).map((m) => `m:${m}`),
  ]
  treeRef.value?.setCheckedKeys(leaves, false)
  await nextTick()
  originalKey = grantsFingerprint(gatherGrants())
  dirty.value = false
}

function onCheck() {
  dirty.value = grantsFingerprint(gatherGrants()) !== originalKey
}
function setAll(v: boolean) {
  if (treeReadonly.value) return
  treeRef.value?.setCheckedKeys(v ? allCheckableLeafKeys.value : [], false)
  onCheck()
}
function resetGrants() {
  if (!activeId.value) return
  selectRole(activeId.value) // 重新拉取回显 = 还原到已保存态
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
      if (!roleForm.value.code.trim()) { ElMessage.warning('请填写角色标识 code'); return }
      const r = await createRole({
        code: roleForm.value.code.trim(), name: roleForm.value.name.trim(),
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

onMounted(async () => {
  try {
    const [menus, resources] = await Promise.all([listMenus(), listResources()])
    buildTree(menus, resources)
  } catch { /* 拦截器已提示 */ }
  await loadRoles()
})
</script>

<template>
  <LayoutHost :layout="effective">
    <template #action>
      <div class="lh-action">
        <div class="page-head">
          <h2>
            角色管理
            <HelpTip title="角色管理说明" :width="440">
              角色勾选菜单与功能点后保存，拥有该角色的用户权限即时生效（无权按钮消失 / 接口 403）。<br /><br />
              勾选父级级联子级，子级部分选中父级显半选。<br /><br />
              系统管理员为超管，权限锁定不可改；「系统管理」类菜单仅超管可用，其它角色置灰。
            </HelpTip>
          </h2>
          <div class="page-head-actions">
            <el-button v-if="can('role:create')" type="primary" @click="openCreate">＋ 新建角色</el-button>
            <PageSettingsTrigger :dirty="layoutDirty" @click="settingsOpen = true" />
          </div>
        </div>
      </div>
    </template>

    <template #main>
      <div class="rm-split">
        <!-- 左：角色列表 -->
        <div class="rm-col rm-left">
          <div class="rm-col-head">角色 <span class="mini">{{ roles.length }}</span></div>
          <div class="rm-col-body" v-loading="rolesLoading">
            <div v-for="r in roles" :key="r.id" class="role" :class="{ active: r.id === activeId }"
                 @click="selectRole(r.id)">
              <div class="role-name">
                {{ r.name }}
                <el-tag :type="roleTag(r).type" size="small" effect="plain">{{ roleTag(r).text }}</el-tag>
              </div>
              <div class="role-desc">角色码 {{ r.code }}<span v-if="r.member_count != null"> · 关联用户 {{ r.member_count }} 名</span></div>
            </div>
            <el-empty v-if="!rolesLoading && !roles.length" description="暂无角色" :image-size="72" />
          </div>
        </div>

        <!-- 右：权限树 -->
        <div class="rm-col rm-right">
          <div class="rm-detail-bar">
            <div class="rm-detail-title">
              <div class="rname">{{ activeRole?.name || '—' }}</div>
              <div class="rmeta">
                <template v-if="activeRole">
                  角色码 {{ activeRole.code }}<span v-if="activeRole.member_count != null"> · 关联用户 {{ activeRole.member_count }} 名</span>
                  <span v-if="activeRole.is_locked" class="lock-note"> · 超管权限锁定，不可编辑</span>
                </template>
              </div>
            </div>
            <div class="page-head-actions" v-if="activeRole">
              <el-button v-if="can('role:update') && !activeRole.is_locked" size="small" @click="openRename">重命名</el-button>
              <el-button v-if="can('role:delete') && !activeRole.is_builtin" size="small" type="danger" plain
                         @click="removeRole">删除</el-button>
              <el-button size="small" :disabled="treeReadonly" @click="setAll(true)">全选</el-button>
              <el-button size="small" :disabled="treeReadonly" @click="setAll(false)">清空</el-button>
            </div>
          </div>

          <div class="rm-col-body">
            <el-tree v-if="activeRole" ref="treeRef" :data="treeData" :props="treeProps" node-key="key"
                     show-checkbox default-expand-all :check-strictly="false" @check="onCheck">
              <template #default="{ data }">
                <span class="tree-node" :class="{ locked: treeReadonly || data.sysLocked }">
                  <span class="tn-label">{{ data.label }}</span>
                  <el-tag v-if="data.kind === 'menu'" size="small" effect="plain"
                          :type="data.nodeType === 'group' ? 'primary' : 'success'" class="tn-tag">
                    {{ data.nodeType === 'group' ? '分组' : '菜单' }}
                  </el-tag>
                  <el-tag v-else size="small" effect="plain"
                          :type="data.nodeType === 'api' ? 'success' : 'warning'" class="tn-tag">
                    {{ data.nodeType === 'api' ? '接口' : '按钮' }}
                  </el-tag>
                </span>
              </template>
            </el-tree>
            <el-empty v-else description="请选择左侧角色" :image-size="72" />
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
          <el-form-item label="角色码">
            <el-input v-model="roleForm.code" :disabled="dialogMode === 'rename'"
                      placeholder="如：analyst（全局唯一，创建后不可改）" />
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
.page-head { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 14px; }
.page-head h2 { margin: 0; font-size: 20px; }
.page-head-actions { display: flex; align-items: center; gap: 10px; }
/* master-detail：窄视口体内横滚，右栏不被压垮 */
.rm-split { height: 100%; display: flex; gap: 16px; min-height: 0; overflow-x: auto; }
.rm-col { border: 1px solid var(--el-border-color); border-radius: 8px; background: var(--el-bg-color-overlay);
  display: flex; flex-direction: column; min-height: 0; }
.rm-left { width: 288px; flex: none; }
.rm-right { flex: 1 1 auto; min-width: 460px; }
.rm-col-head { padding: 11px 14px; border-bottom: 1px solid var(--el-border-color-lighter); font-weight: 600;
  display: flex; align-items: center; gap: 8px; }
.rm-col-head .mini { font-size: 12px; color: var(--el-text-color-secondary); font-weight: 400; }
.rm-col-body { flex: 1 1 auto; min-height: 0; overflow: auto; padding: 8px; }
.role { padding: 10px 12px; border-radius: 7px; cursor: pointer; margin-bottom: 4px; border: 1px solid transparent; }
.role:hover { background: var(--el-fill-color-light); }
.role.active { background: var(--el-color-primary-light-9); border-color: var(--el-color-primary-light-5); }
.role-name { font-size: 14px; font-weight: 600; display: flex; align-items: center; gap: 8px; }
.role-desc { font-size: 12px; color: var(--el-text-color-secondary); margin-top: 3px; }
.rm-detail-bar { padding: 12px 16px; border-bottom: 1px solid var(--el-border-color-lighter);
  display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.rm-detail-title .rname { font-size: 15px; font-weight: 700; }
.rm-detail-title .rmeta { font-size: 12px; color: var(--el-text-color-secondary); margin-top: 2px; }
.lock-note { color: var(--el-color-warning); }
.rm-detail-foot { border-top: 1px solid var(--el-border-color-lighter); padding: 12px 16px;
  display: flex; align-items: center; justify-content: space-between; }
.dirty { font-size: 12px; color: var(--el-color-warning); }
.dirty.hidden { visibility: hidden; }
.tree-node { display: inline-flex; align-items: center; gap: 8px; }
.tree-node.locked { opacity: 0.55; }
.tn-tag { transform: scale(0.9); }
</style>
