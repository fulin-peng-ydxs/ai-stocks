<script setup lang="ts">
import AppForm from '@/components/AppForm.vue'
import AppSelect from '@/components/AppSelect.vue'
import AppScrollArea from '@/components/AppScrollArea.vue'
import { useMenuPageTitle } from '@/composables/useMenuPageTitle'
// 菜单与功能管理页（多租户 RBAC stage3·T13，R12+R13）。承接 menu-resource-management.html。
// master-detail：左 AppReorderTree 菜单树 + 右 菜单属性表单(含 IconPicker) + 功能点子表。
// 菜单是平台级全局唯一源，SideMenu 消费它 + 按角色权限过滤（T15）；功能点是角色授权最小资源单位。
import { computed, nextTick, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import AppDataTable from '@/components/AppDataTable.vue'
import AppAsyncRegion from '@/components/AppAsyncRegion.vue'
import AppDialog from '@/components/AppDialog.vue'
import AppIconButton from '@/components/AppIconButton.vue'
import AppReorderTree from '@/components/AppReorderTree.vue'
import AppRowActions from '@/components/AppRowActions.vue'
import AppStateBlock from '@/components/AppStateBlock.vue'
import AppTableColumn from '@/components/AppTableColumn.vue'
import HelpTip from '@/components/HelpTip.vue'
import HelpTipItem from '@/components/HelpTipItem.vue'
import IconPicker from '@/components/IconPicker.vue'
import MenuIcon from '@/components/MenuIcon.vue'
import SystemBuiltinTag from '@/components/SystemBuiltinTag.vue'
import PageSettingsDrawer from '@/components/PageSettingsDrawer.vue'
import PageSettingsTrigger from '@/components/PageSettingsTrigger.vue'
import LayoutHost from '@/layout/components/LayoutHost.vue'
import { getPageLayout } from '@/layout'
import { usePageSettings } from '@/composables/usePageSettings'
import { useRemoteLayoutConfig } from '@/composables/useRemoteLayoutConfig'
import { useFormChangeTracker } from '@/composables/useFormChangeTracker'
import { useAuthStore } from '@/stores/auth'
import {
  listMenus, createMenu, updateMenu, deleteMenu, reorderMenus,
  listResources, createResource, updateResource, deleteResource,
  type MenuNode, type Resource,
} from '@/api/menu'
import { hasPermission } from '@/utils/permission'
import type { AppRowAction } from '@/components/rowActions'

const auth = useAuthStore()
// 按钮显隐走全局 v-permission；脚本逻辑/表单禁用用共用 hasPermission（system 恒过），口径统一。
const canMenuUpdate = computed(() => hasPermission(auth.role, auth.permissions, 'menu:update'))
const canMenuReorder = computed(() => hasPermission(auth.role, auth.permissions, 'menu:reorder'))

// ── 页面设置（无业务选项；布局、功能点表与 settings-drawer 字段由统一抽屉自动渲染）──
const menuLayout = getPageLayout('menu-manage')
const {
  effective, knobs: layoutKnobs, setKnob, valueOf, sourceOf,
  isDirty: layoutDirty, resetAll: resetLayout,
  componentValueOf, setComponentKnob, componentSourceOf, layerValuesOf, componentLayerValuesOf, componentAllowedLayers,
} = useRemoteLayoutConfig(menuLayout)
const drawerConfig = { knobs: layoutKnobs, valueOf, sourceOf, setKnob, componentValueOf, setComponentKnob, componentSourceOf, layerValuesOf, componentLayerValuesOf, componentAllowedLayers }
function tableBorder(slotId: string): boolean { return componentValueOf(slotId, 'border') === true }
const resourceHiddenColumns = computed<string[]>(() =>
  (componentValueOf('resourceTable', 'hiddenColumns') as string[]) ?? [],
)
function resourceColVisible(key: string): boolean { return !resourceHiddenColumns.value.includes(key) }
const { reset: resetBiz } = usePageSettings('menu-manage', {})
const settingsOpen = ref(false)

// ── 菜单树 ──
const tree = ref<MenuNode[]>([])
const reorderSaving = ref(false)
const treeLoading = ref(false)
const treeError = ref(false)   // 菜单树加载失败 → 页内错误态 + 重试
const activeId = ref<string>('')

/** 在嵌套树中按 id 找节点。 */
function findNode(nodes: MenuNode[], id: string): MenuNode | null {
  for (const n of nodes) {
    if (n.id === id) return n
    const hit = n.children?.length ? findNode(n.children, id) : null
    if (hit) return hit
  }
  return null
}
const activeMenu = computed<MenuNode | null>(() => (activeId.value ? findNode(tree.value, activeId.value) : null))

async function loadTree(keepActive = false) {
  treeLoading.value = true
  treeError.value = false
  try {
    tree.value = await listMenus()
    if (keepActive && activeId.value && findNode(tree.value, activeId.value)) {
      loadForm()
    } else if (tree.value.length) {
      selectMenu(tree.value[0].id)
    } else {
      activeId.value = ''
    }
  } catch {
    treeError.value = true
  } finally {
    treeLoading.value = false
  }
}

// ── 右栏：菜单属性表单 + 脏检测 ──
interface MenuForm {
  title: string
  type: string
  routePath: string
  icon: string | null
  visible: string
  sort: number
  parentId: string | null
}
const form = ref<MenuForm>({ title: '', type: 'leaf', routePath: '', icon: null, visible: 'login', sort: 0, parentId: null })
let originalForm = ''
const formDirty = ref(false)

function formFingerprint(f: MenuForm): string {
  return JSON.stringify([f.title, f.type, f.routePath, f.icon, f.visible, f.parentId])
}

interface ParentOption {
  id: string | null
  title: string
  disabled?: boolean
}

function collectGroupOptions(nodes: MenuNode[], currentId: string | null = null, level = 0): ParentOption[] {
  const options: ParentOption[] = []
  for (const n of nodes) {
    if (n.type === 'group') {
      const isCurrent = currentId === n.id
      const disabled = isCurrent || Boolean(currentId && findNode(n.children ?? [], currentId))
      options.push({
        id: n.id,
        title: `${'　'.repeat(level)}${n.title}`,
        disabled,
      })
      options.push(...collectGroupOptions(n.children ?? [], currentId, level + 1))
    }
  }
  return options
}

const parentOptions = computed<ParentOption[]>(() => [
  { id: null, title: '（根节点）' },
  ...collectGroupOptions(tree.value, activeId.value || null),
])

const createParentOptions = computed<ParentOption[]>(() => [
  { id: null, title: '（根节点）' },
  ...collectGroupOptions(tree.value),
])
function loadForm() {
  const m = activeMenu.value
  if (!m) return
  form.value = {
    title: m.title, type: m.type, routePath: m.route_path ?? '',
    icon: m.icon, visible: m.visible, sort: m.sort, parentId: m.parent_id,
  }
  originalForm = formFingerprint(form.value)
  formDirty.value = false
}
function onFormChange() {
  formDirty.value = formFingerprint(form.value) !== originalForm
}
function onParentChange(value: string) {
  form.value.parentId = value || null
  onFormChange()
}
function onCreateParentChange(value: string) {
  menuCreateForm.value.parentId = value || null
}

const resources = ref<Resource[]>([])
const resLoading = ref(false)
const resError = ref(false)
let resourceRequestVersion = 0
async function loadResources(menuId: string) {
  const requestVersion = ++resourceRequestVersion
  resLoading.value = true
  resError.value = false
  try {
    const nextResources = await listResources(menuId)
    // 快速切换菜单时，较早请求可能最后返回；只允许当前菜单的最新响应落状态。
    if (requestVersion !== resourceRequestVersion || activeId.value !== menuId) return
    resources.value = nextResources
  } catch {
    if (requestVersion !== resourceRequestVersion || activeId.value !== menuId) return
    // 功能点列表加载失败给明确错误态 + 重试入口（error+retry 闭环，勿静默结束 loading）
    resources.value = []
    resError.value = true
  } finally {
    if (requestVersion === resourceRequestVersion) resLoading.value = false
  }
}
function retryResources() {
  if (activeId.value) loadResources(activeId.value)
}

async function selectMenu(id: string) {
  activeId.value = id
  loadForm()
  await loadResources(id)
}

const savingForm = ref(false)
async function saveForm() {
  const m = activeMenu.value
  if (!m || !canMenuUpdate.value || !formDirty.value) return
  if (!form.value.title.trim()) { ElMessage.warning('请填写菜单标题'); return }
  savingForm.value = true
  try {
    await updateMenu(m.id, {
      title: form.value.title.trim(),
      type: form.value.type,
      routePath: form.value.type === 'group' ? null : (form.value.routePath.trim() || null),
      icon: form.value.icon,
      visible: form.value.visible,
      parentId: form.value.parentId,
    })
    ElMessage.success('已保存')
    await loadTree(true)
    // 页面标题与侧栏共同消费 /me 菜单树，保存名称后立即刷新全局快照。
    await auth.fetchMe({ background: true })
  } catch { /* 唯一/内置/成环等由拦截器弹出 */ } finally { savingForm.value = false }
}
function resetForm() {
  loadForm()
}

// ── 菜单 新建（root / child）/ 删除 ──
const menuDialog = ref(false)
const menuCreateForm = ref<{ code: string; title: string; type: string; routePath: string; icon: string | null; visible: string; parentId: string | null }>(
  { code: '', title: '', type: 'leaf', routePath: '', icon: null, visible: 'login', parentId: null },
)
const menuSaving = ref(false)

function openCreateRoot() {
  menuCreateForm.value = { code: '', title: '', type: 'group', routePath: '', icon: null, visible: 'login', parentId: null }
  menuDialog.value = true
}
function openCreateChild(node?: MenuNode) {
  const p = node ?? activeMenu.value
  if (!p) return
  // 子节点默认继承父可见域（在 system 分组下新建默认 system），避免误建成登录可见的越权入口
  menuCreateForm.value = { code: '', title: '', type: 'leaf', routePath: '', icon: null, visible: p.visible, parentId: p.id }
  menuDialog.value = true
}
async function saveCreateMenu() {
  const f = menuCreateForm.value
  if (!f.title.trim()) { ElMessage.warning('请填写菜单标题'); return }
  if (!f.code.trim()) { ElMessage.warning('请填写菜单编码'); return }
  if (f.type === 'leaf' && !f.routePath.trim()) { ElMessage.warning('请填写菜单路由'); return }
  menuSaving.value = true
  try {
    const m = await createMenu({
      parentId: f.parentId,
      code: f.code.trim().toLowerCase(),
      title: f.title.trim(),
      type: f.type,
      routePath: f.type === 'group' ? null : (f.routePath.trim() || null),
      icon: f.icon,
      visible: f.visible,
    })
    ElMessage.success('已创建')
    menuDialog.value = false
    await loadTree()
    if (m?.id) selectMenu(m.id)
  } catch { /* 唯一/上级不存在等由拦截器弹出 */ } finally { menuSaving.value = false }
}
async function removeMenu() {
  const m = activeMenu.value
  if (!m) return
  try {
    await ElMessageBox.confirm(`确认删除菜单「${m.title}」？删除后拥有该菜单的角色将失去入口。`, '删除菜单',
      { type: 'warning', confirmButtonText: '删除', confirmButtonType: 'danger' })
    await deleteMenu(m.id)
    ElMessage.success('已删除')
    activeId.value = ''
    await loadTree()
  } catch (e) { if (e === 'cancel') return /* 内置/有子节点/有功能点由拦截器弹出 */ }
}

// ── 拖动与键盘排序进入同一业务入口；保存互斥覆盖请求、重载和导航刷新。 ──
function collectReorder(previous: MenuNode[], next: MenuNode[]): Array<{ id: string; sort: number; parentId: string | null }> {
  const beforeGroups = new Map<string | null, string[]>()
  const capture = (nodes: MenuNode[], parentId: string | null) => {
    beforeGroups.set(parentId, nodes.map(node => node.id))
    nodes.forEach(node => capture(node.children ?? [], node.id))
  }
  capture(previous, null)
  const items: Array<{ id: string; sort: number; parentId: string | null }> = []
  const walk = (children: MenuNode[], parentId: string | null) => {
    const before = beforeGroups.get(parentId) ?? []
    const changed = before.length !== children.length || children.some((node, index) => node.id !== before[index])
    children.forEach((node, index) => {
      // 只归一发生移动的兄弟组，保留其他菜单已有的排序值与配置。
      if (changed) items.push({ id: node.id, sort: (index + 1) * 10, parentId })
      walk(node.children ?? [], node.id)
    })
  }
  walk(next, null)
  return items
}
async function onMenuReorder(next: MenuNode[]): Promise<void> {
  if (!canMenuReorder.value || reorderLocked.value) return
  const previous = tree.value
  const changes = collectReorder(previous, next)
  if (!changes.length) return
  reorderSaving.value = true
  tree.value = next
  let saved = false
  try {
    await reorderMenus(changes)
    saved = true
    ElMessage.success('菜单顺序已保存')
    await loadTree(true)
    await auth.fetchMe({ background: true })
  } catch {
    if (!saved) {
      tree.value = previous
      await loadTree(true) // 失败后读取服务端真值；读取也失败时保留原树并显示重试入口。
    } else {
      ElMessage.warning('菜单顺序已保存，导航刷新失败，请刷新页面')
    }
  } finally {
    reorderSaving.value = false
  }
}

// ── 功能点：表内联增删改（承接原型，无编辑 dialog）──
// editingId：'' 无编辑；'__new__' 新增行；否则为在编辑的功能点 id。同一时刻只一行处于编辑态。
const NEW_ROW = '__new__'
const editingId = ref<string>('')
const resDraft = ref<{ code: string; name: string; type: string; apiMethod: string; apiPath: string }>(
  { code: '', name: '', type: 'api', apiMethod: 'GET', apiPath: '' },
)
const resourceSubmitPayload = () => ({
  code: resDraft.value.code.trim(),
  name: resDraft.value.name.trim(),
  type: resDraft.value.type,
  apiMethod: resDraft.value.type === 'api' ? resDraft.value.apiMethod : null,
  apiPath: resDraft.value.apiPath.trim() || null,
})
const {
  hasChanges: resourceFormChanged,
  captureBaseline: captureResourceBaseline,
} = useFormChangeTracker(resourceSubmitPayload)
const resSaving = ref(false)
// 排序会重载菜单属性；存在未保存表单或功能点编辑时先锁定，避免清掉编辑现场。
const reorderLocked = computed(() => treeLoading.value || reorderSaving.value || savingForm.value
  || menuSaving.value || resSaving.value || formDirty.value || Boolean(editingId.value))
const reorderHint = computed(() => reorderSaving.value ? '正在保存顺序…'
  : formDirty.value || editingId.value ? '结束当前编辑后可排序' : '拖动把手排序')
const resourceRows = computed<Resource[]>(() => {
  if (editingId.value !== NEW_ROW) return resources.value
  return [
    ...resources.value,
    {
      id: NEW_ROW,
      menu_id: activeId.value,
      code: '',
      name: '',
      type: 'api',
      api_method: 'GET',
      api_path: null,
      sort: resources.value.length,
      is_builtin: false,
    },
  ]
})

function resourceRowClassName({ row }: { row: Resource }): string {
  return editingId.value === row.id ? 'mr-edit-row' : ''
}

function bindingText(r: Resource): string {
  return r.api_path ? `${r.api_method || ''} ${r.api_path}`.trim() : '— 纯前端动作'
}
function startCreateRes() {
  if (!activeMenu.value) return
  resDraft.value = { code: '', name: '', type: 'api', apiMethod: 'GET', apiPath: '' }
  captureResourceBaseline()
  editingId.value = NEW_ROW
}
function startEditRes(r: Resource) {
  resDraft.value = { code: r.code, name: r.name, type: r.type, apiMethod: r.api_method ?? 'GET', apiPath: r.api_path ?? '' }
  captureResourceBaseline()
  editingId.value = r.id
}
function cancelRes() {
  editingId.value = ''
}
async function saveResRow() {
  const m = activeMenu.value
  if (!m || !resourceFormChanged.value) return
  const f = resDraft.value
  if (!f.code.trim()) { ElMessage.warning('请填写功能码'); return }
  if (!f.name.trim()) { ElMessage.warning('请填写功能名称'); return }
  resSaving.value = true
  try {
    const body = {
      menuId: m.id, code: f.code.trim(), name: f.name.trim(), type: f.type,
      apiMethod: f.type === 'api' ? f.apiMethod : null,
      apiPath: f.apiPath.trim() || null,
    }
    const creating = editingId.value === NEW_ROW
    if (creating) await createResource(body)
    else await updateResource(editingId.value, body)
    ElMessage.success(creating ? '已创建' : '已保存')
    editingId.value = ''
    await loadResources(m.id)
  } catch { /* 唯一/内置由拦截器弹出 */ } finally { resSaving.value = false }
}
async function removeRes(r: Resource) {
  const m = activeMenu.value
  if (!m) return
  try {
    await ElMessageBox.confirm(`确认删除功能点「${r.name}」（${r.code}）？被角色引用时将同时解除授权。`, '删除功能点',
      { type: 'warning', confirmButtonText: '删除', confirmButtonType: 'danger' })
    await deleteResource(r.id)
    ElMessage.success('已删除')
    await loadResources(m.id)
  } catch (e) { if (e === 'cancel') return /* 内置由拦截器弹出 */ }
}

function resourceEditRowActions(): AppRowAction[] {
  return [
    {
      key: 'save',
      label: '保存',
      type: 'primary',
      loading: resSaving.value,
      disabled: !resourceFormChanged.value,
      onClick: () => saveResRow(),
    },
    {
      key: 'cancel',
      label: '取消',
      onClick: () => cancelRes(),
    },
  ]
}

function resourceRowActions(r: Resource): AppRowAction[] {
  const editingOther = editingId.value !== ''
  return [
    {
      key: 'edit',
      label: '编辑',
      permission: 'resource:update',
      disabled: r.is_builtin || editingOther,
      tooltip: r.is_builtin
        ? '系统内置功能点不可编辑'
        : editingOther
          ? '请先完成当前编辑'
          : undefined,
      onClick: () => startEditRes(r),
    },
    {
      key: 'delete',
      label: '删除',
      type: 'danger',
      permission: 'resource:delete',
      disabled: r.is_builtin,
      tooltip: r.is_builtin ? '系统内置功能点不可删除' : undefined,
      placement: 'more',
      onClick: () => removeRes(r),
    },
  ]
}

onMounted(() => { loadTree() })
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
              <HelpTip title="菜单与功能管理说明" :width="440">
                <HelpTipItem question="菜单树如何维护">
                  <ul>
                    <li>左侧菜单树可新增、拖拽排序和删除；选中节点后在右侧维护其属性与功能点。</li>
                  </ul>
                </HelpTipItem>
                <HelpTipItem question="菜单图标与路由如何配置">
                  <ul>
                    <li>菜单 icon 存 Element Plus 图标名并从图标选择器中选择；分组不导航，无需路由。</li>
                  </ul>
                </HelpTipItem>
                <HelpTipItem question="功能点是什么">
                  <ul>
                    <li>功能点是角色授权的最小资源单位；「接口」类绑定后端接口路径，「按钮」类代表前端动作。</li>
                  </ul>
                </HelpTipItem>
                <HelpTipItem question="系统菜单如何隔离">
                  <ul>
                    <li>「仅系统管理员」可见的菜单不会授予普通角色。</li>
                  </ul>
                </HelpTipItem>
              </HelpTip>
            </h2>
            <p class="page-subtitle">维护菜单树、功能点与接口绑定，支持拖拽排序。</p>
          </div>
          <div class="page-head-actions">
            <PageSettingsTrigger :dirty="layoutDirty" @click="settingsOpen = true" />
          </div>
        </div>
      </div>
    </template>

    <template #main>
      <AppScrollArea class="mr-split">
        <!-- 左：菜单树 -->
        <div class="app-surface mr-col mr-left">
          <div class="mr-col-head">
            <span>菜单树</span>
            <span v-if="canMenuReorder" class="mini" role="status">{{ reorderHint }}</span>
            <div class="mr-head-spacer" />
            <AppIconButton
              v-permission="'menu:create'"
              label="新增根节点"
              tooltip="新增根节点"
              size="sm"
              class="mr-root-add"
              :disabled="reorderSaving"
              @click="openCreateRoot"
            >
              <Plus />
            </AppIconButton>
          </div>
          <AppScrollArea :as="AppAsyncRegion"
            class="mr-col-body"
            :loading="treeLoading"
            :has-content="tree.length > 0"
            :error="treeError ? '请重试' : ''"
            state-size="compact"
            loading-title="正在加载菜单…"
            error-title="菜单加载失败"
            empty-title="暂无菜单"
            retry
            @retry="loadTree()"
          >
            <AppReorderTree
              :items="tree"
              :item-label="item => item.title"
              :can-contain="item => item.type === 'group'"
              label="菜单树"
              :current-key="activeId"
              :can-reorder="canMenuReorder"
              :disabled="reorderLocked"
              :busy="reorderSaving"
              @select="selectMenu"
              @reorder="onMenuReorder"
            >
              <template #default="{ item: data }">
                <span class="mr-tnode">
                  <MenuIcon v-if="data.icon" :name="data.icon" class="mr-ticon" />
                  <span class="mr-tlabel">{{ data.title }}</span>
                  <el-tag v-if="!data.is_builtin" size="small" effect="plain" type="info" class="mr-ttag">
                    自定义
                  </el-tag>
                  <AppIconButton
                    v-if="data.type === 'group'"
                    v-permission="'menu:create'"
                    label="新增子节点"
                    tooltip="新增子节点"
                    class="mr-node-add"
                    size="sm"
                    @click.stop="openCreateChild(data)"
                  >
                    <Plus />
                  </AppIconButton>
                </span>
              </template>
            </AppReorderTree>
          </AppScrollArea>
        </div>

        <!-- 右：属性 + 功能点 -->
        <div class="app-surface mr-col mr-right" :inert="reorderSaving || undefined" :aria-busy="reorderSaving">
          <template v-if="activeMenu">
            <div class="mr-detail-bar">
              <div class="mr-detail-title">
                <h2 class="mname">
                  <MenuIcon v-if="activeMenu.icon" :name="activeMenu.icon" class="mr-ticon" />
                  {{ activeMenu.title }}
                  <SystemBuiltinTag v-if="activeMenu.is_builtin" />
                </h2>
                <div class="mmeta">
                  菜单编码 {{ activeMenu.code }}
                </div>
              </div>
              <div class="page-head-actions">
                <el-button v-permission="'menu:delete'" size="small" type="danger" plain :disabled="activeMenu.is_builtin" @click="removeMenu">删除节点</el-button>
              </div>
            </div>

            <AppScrollArea class="mr-col-body mr-detail-body">
              <!-- 菜单属性 -->
              <div class="mr-section">
                <h4>菜单属性</h4>
                <AppForm class="mr-form-grid">
                  <div class="mr-field"><label>标题</label>
                    <el-input v-model="form.title" :disabled="!canMenuUpdate" @input="onFormChange" />
                  </div>
                  <div class="mr-field"><label>类型</label>
                    <AppSelect
                      v-model="form.type"
                      :disabled="!canMenuUpdate"
                      @change="onFormChange"
                    >
                      <el-option label="叶子（可导航）" value="leaf" />
                      <el-option label="分组（不导航）" value="group" />
                    </AppSelect>
                  </div>
                  <div class="mr-field"><label>上级</label>
                    <AppSelect
                      :model-value="form.parentId ?? ''"
                      :disabled="!canMenuUpdate"
                      @change="onParentChange"
                    >
                      <el-option
                        v-for="opt in parentOptions"
                        :key="opt.id ?? '__root__'"
                        :label="opt.title"
                        :value="opt.id ?? ''"
                        :disabled="opt.disabled"
                      />
                    </AppSelect>
                  </div>
                  <div class="mr-field"><label>路由</label>
                    <el-input v-model="form.routePath" placeholder="如 /board" class="mono"
                              :disabled="form.type === 'group' || !canMenuUpdate" @input="onFormChange" />
                  </div>
                  <div class="mr-field"><label>图标</label>
                    <IconPicker v-model="form.icon" :disabled="!canMenuUpdate" @update:model-value="onFormChange" />
                  </div>
                  <div class="mr-field"><label>排序</label>
                    <el-input :model-value="form.sort" disabled>
                      <template #suffix><span class="hint">拖拽树调整</span></template>
                    </el-input>
                  </div>
                  <div class="mr-field"><label>可见性</label>
                    <AppSelect
                      v-model="form.visible"
                      :disabled="!canMenuUpdate"
                      @change="onFormChange"
                    >
                      <el-option label="登录可见" value="login" />
                      <el-option label="仅系统管理员" value="system" />
                    </AppSelect>
                  </div>
                </AppForm>
              </div>

              <!-- 功能点 -->
              <div class="mr-section mr-resource-section">
                <div class="mr-func-head">
                  <h4 style="margin: 0">功能点
                    <HelpTip title="功能点说明" :width="360">
                      <HelpTipItem question="功能点用于什么">
                        <ul><li>功能点用于角色授权，控制接口和按钮的访问权限。</li></ul>
                      </HelpTipItem>
                      <HelpTipItem question="功能码有什么约束">
                        <ul>
                          <li>功能码全局唯一、稳定且不可复用，并与后端接口权限码对账。</li>
                        </ul>
                      </HelpTipItem>
                      <HelpTipItem question="功能点类型表示什么">
                        <ul>
                          <li>「接口」类绑定后端接口路径，「按钮」类代表前端动作。</li>
                        </ul>
                      </HelpTipItem>
                      <HelpTipItem question="删除与内置保护如何处理">
                        <ul>
                          <li>系统内置功能点不可编辑、不可删除；删除被角色引用的功能点会同时解除授权。</li>
                        </ul>
                      </HelpTipItem>
                    </HelpTip>
                  </h4>
                  <el-button v-permission="'resource:create'" size="small" :disabled="editingId === NEW_ROW"
                             @click="startCreateRes">
                    <template #icon><el-icon><Plus /></el-icon></template>
                    新增功能点
                  </el-button>
                </div>
                <!-- 表内联增删改（承接原型，无编辑 dialog）；宽度由统一语义列规则自适应。 -->
                <AppStateBlock
                  v-if="resError"
                  state="error"
                  size="compact"
                  title="功能点加载失败"
                  retry
                  @retry="retryResources"
                />
                <AppDataTable
                  v-else
                  class="resource-table"
                  kind="wide-table"
                  :data="resourceRows"
                  :loading="resLoading"
                  row-key="id"
                  empty-text="该菜单暂无功能点"
                  :row-class-name="resourceRowClassName"
                  aria-label="功能点"
                  :border="tableBorder('resourceTable')"
                >
                  <AppTableColumn v-if="resourceColVisible('code')" label="功能码" prop="code" role="key">
                    <template #default="{ row: r }">
                      <el-input
                        v-if="editingId === r.id"
                        v-model="resDraft.code"
                        size="small"
                        class="mono"
                        :placeholder="r.id === NEW_ROW ? 'menu:action（全局唯一）' : 'menu:action'"
                      />
                      <div v-else class="mr-code-cell">
                        <span class="mono">{{ r.code }}</span>
                      </div>
                    </template>
                  </AppTableColumn>
                  <AppTableColumn v-if="resourceColVisible('name')" label="名称" prop="name">
                    <template #default="{ row: r }">
                      <el-input v-if="editingId === r.id" v-model="resDraft.name" size="small" placeholder="名称" />
                      <span v-else>{{ r.name }}</span>
                    </template>
                  </AppTableColumn>
                  <AppTableColumn v-if="resourceColVisible('type')" label="类型" prop="type" role="status">
                    <template #default="{ row: r }">
                      <AppSelect
                        v-if="editingId === r.id"
                        v-model="resDraft.type"
                        size="small"
                      >
                        <el-option label="接口" value="api" />
                        <el-option label="按钮" value="button" />
                      </AppSelect>
                      <el-tag v-else size="small" effect="plain" :type="r.type === 'api' ? 'success' : 'warning'">
                        {{ r.type === 'api' ? '接口' : '按钮' }}
                      </el-tag>
                    </template>
                  </AppTableColumn>
                  <AppTableColumn v-if="resourceColVisible('apiPath')" label="绑定接口" prop="api_path" role="description">
                    <template #default="{ row: r }">
                      <div v-if="editingId === r.id" class="mr-bind">
                        <AppSelect
                          v-if="resDraft.type === 'api'"
                          v-model="resDraft.apiMethod"
                          size="small"
                          class="mr-method-select"
                        >
                          <el-option v-for="mth in ['GET','POST','PUT','DELETE']" :key="mth" :label="mth" :value="mth" />
                        </AppSelect>
                        <el-input v-model="resDraft.apiPath" size="small" class="mono" placeholder="/api/…（按钮可空）" />
                      </div>
                      <span v-else class="mono" :class="{ dim: !r.api_path }">{{ bindingText(r) }}</span>
                    </template>
                  </AppTableColumn>
                  <AppTableColumn label="操作" role="action">
                    <template #default="{ row: r }">
                      <AppRowActions
                        :actions="editingId === r.id ? resourceEditRowActions() : resourceRowActions(r)"
                        :inline-limit="editingId === r.id ? 2 : 1"
                      />
                    </template>
                  </AppTableColumn>
                </AppDataTable>
              </div>
            </AppScrollArea>

            <div class="mr-detail-foot">
              <span class="dirty" :class="{ hidden: !formDirty }">● 菜单属性有未保存修改</span>
              <div class="page-head-actions">
                <el-button :disabled="!formDirty" @click="resetForm">还原修改</el-button>
                <el-button type="primary" :loading="savingForm" :disabled="!formDirty || !canMenuUpdate" @click="saveForm">保存</el-button>
              </div>
            </div>
          </template>
          <el-empty v-else class="app-empty app-empty--compact" description="请选择左侧菜单节点" />
        </div>
      </AppScrollArea>
    </template>

    <template #overlays>
      <!-- 新建菜单 -->
      <AppDialog v-model="menuDialog" title="新增菜单节点" size="medium">
        <AppForm label-width="72px">
          <el-form-item label="上级">
            <AppSelect
              :model-value="menuCreateForm.parentId ?? ''"
              filterable
              @change="onCreateParentChange"
            >
              <el-option
                v-for="opt in createParentOptions"
                :key="opt.id ?? '__root__'"
                :label="opt.title"
                :value="opt.id ?? ''"
              />
            </AppSelect>
          </el-form-item>
          <el-form-item label="标题" required>
            <el-input v-model="menuCreateForm.title" placeholder="如：每日榜单" />
          </el-form-item>
          <el-form-item label="菜单编码" required>
            <el-input
              v-model="menuCreateForm.code"
              class="mono"
              placeholder="必填，创建后不可修改"
            />
          </el-form-item>
          <el-form-item label="类型" required>
            <AppSelect
              v-model="menuCreateForm.type"
            >
              <el-option label="叶子（可导航）" value="leaf" />
              <el-option label="分组（不导航）" value="group" />
            </AppSelect>
          </el-form-item>
          <el-form-item label="路由" v-if="menuCreateForm.type !== 'group'" required>
            <el-input v-model="menuCreateForm.routePath" class="mono" placeholder="如 /board（须与前端已注册路由对应）" />
          </el-form-item>
          <el-form-item label="图标">
            <IconPicker v-model="menuCreateForm.icon" />
          </el-form-item>
          <el-form-item label="可见性" required>
            <AppSelect
              v-model="menuCreateForm.visible"
            >
              <el-option label="登录可见" value="login" />
              <el-option label="仅系统管理员" value="system" />
            </AppSelect>
          </el-form-item>
        </AppForm>
        <template #footer>
          <el-button @click="menuDialog = false">取消</el-button>
          <el-button type="primary" :loading="menuSaving" @click="saveCreateMenu">创建</el-button>
        </template>
      </AppDialog>

      <!-- 功能点无编辑 dialog：增删改一律表内联（见右栏功能点表） -->
      <PageSettingsDrawer
        v-model="settingsOpen"
        title="菜单与功能"
        :dirty="layoutDirty"
        page-key="menu-manage"
        :config="drawerConfig"
        @reset="resetBiz(); resetLayout()"
      />
    </template>
  </LayoutHost>
</template>

<style scoped>
.page-head { display: flex; justify-content: space-between; align-items: flex-start; gap: var(--app-space-3); }
.page-head-actions { display: flex; align-items: center; gap: var(--app-space-2); }
/* master-detail：窄视口体内横滚，右栏不被压垮 */
.mr-split { height: 100%; --app-scroll-display: flex; --app-scroll-gap: var(--app-space-4); min-height: 0; }
.mr-col {
  display: flex; flex-direction: column; min-height: 0; }
.mr-left { width: 300px; flex: none; }
.mr-right { flex: 1 1 auto; min-width: 480px; }
.mr-col-head { padding: 11px 14px; border-bottom: 1px solid var(--el-border-color-lighter); font-weight: var(--app-font-weight-section);
  display: flex; align-items: center; gap: var(--app-space-2); }
.mr-col-head .mini { font-size: var(--app-font-size-caption); color: var(--el-text-color-secondary); font-weight: var(--app-font-weight-regular); }
.mr-head-spacer { flex: 1; }
.mr-col-body { flex: 1 1 auto; min-height: 0; --app-scroll-padding-top: 8px; --app-scroll-padding-right: 8px; --app-scroll-padding-bottom: 8px; --app-scroll-padding-left: 8px; }
.mr-detail-body { --app-scroll-display: flex; --app-scroll-direction: column; }
.mr-tnode { display: inline-flex; align-items: center; gap: var(--app-space-2); min-width: 0; width: 100%; }
.mr-ticon { color: var(--el-text-color-regular); }
.mr-tlabel { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mr-ttag { transform: scale(0.9); flex: none; }
.mr-node-add {
  margin-left: auto;
  opacity: 0;
}
.mr-tnode:hover .mr-node-add, .mr-tnode:focus-within .mr-node-add {
  opacity: 1;
}
.mr-detail-bar { padding: 12px 16px; border-bottom: 1px solid var(--el-border-color-lighter);
  display: flex; align-items: center; justify-content: space-between; gap: var(--app-space-3); }
.mr-detail-title .mname { margin: 0; font-size: var(--app-font-size-section-title); font-weight: var(--app-font-weight-strong); display: inline-flex; align-items: center; gap: var(--app-space-control-gap); }
.mr-detail-title .mmeta { font-size: var(--app-font-size-caption); color: var(--el-text-color-secondary); margin-top: 2px; }
.mr-section { padding: 14px 16px; border-bottom: 1px solid var(--el-border-color-lighter); }
.mr-resource-section {
  flex: 1 1 auto;
  min-height: 300px;
  display: flex;
  flex-direction: column;
  border-bottom: none;
}
.mr-section h4 { margin: 0 0 12px; font-size: var(--app-font-size-table); color: var(--el-text-color-secondary); font-weight: var(--app-font-weight-section);
  display: inline-flex; align-items: center; }
.mr-form-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: var(--app-space-3) var(--app-space-5); }
.mr-field { display: flex; align-items: center; gap: var(--app-space-2); }
.mr-field label { width: 54px; text-align: right; color: var(--el-text-color-regular); font-size: var(--app-font-size-table); flex: none; }
.mr-field :deep(.el-select), .mr-field :deep(.el-input) { flex: 1; }
.mono :deep(input), .mono { font-family: var(--app-font-family-mono); }
.hint { font-size: var(--app-font-size-caption); color: var(--el-text-color-placeholder); }
.mr-func-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.resource-table {
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: var(--layout-card-radius);
}
.resource-table :deep(.mr-edit-row > td) { background: var(--el-fill-color-lighter); }
.resource-table :deep(.dim) { color: var(--el-text-color-placeholder); }
.mr-bind { display: flex; gap: var(--app-space-control-gap); }
.mr-method-select { flex: 0 0 92px; }
.mr-code-cell { display: flex; align-items: center; gap: var(--app-space-2); white-space: nowrap; }
.mr-detail-foot { border-top: 1px solid var(--el-border-color-lighter); padding: 12px 16px;
  display: flex; align-items: center; justify-content: space-between; }
.dirty { font-size: var(--app-font-size-caption); color: var(--el-color-warning); }
.dirty.hidden { visibility: hidden; }
</style>
