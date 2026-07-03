<script setup lang="ts">
// 角色权限树节点（多租户 RBAC stage3·T12 / Codex 整改：承接 role-management.html 定制三级树）。
// 递归渲染：分组=可折叠卡片；叶子菜单=菜单行 + 其功能点 chip 面板；三态勾选（on/half/off）级联。
// 勾选态由父组件以「原子叶子集合」派生（stateOf），toggle 交回父组件级联，故本组件仅负责渲染 + 事件。
import { ref, computed } from 'vue'
import { ArrowDown } from '@element-plus/icons-vue'

export interface PermNode {
  key: string
  label: string
  kind: 'menu' | 'resource'
  nodeType: string // menu: group/leaf；resource: button/api
  sysLocked: boolean // system 可见子树：非 system 角色不可授（后端硬拒，前端置灰）
  children?: PermNode[]
}

const props = defineProps<{
  node: PermNode
  stateOf: (n: PermNode) => 'on' | 'half' | 'off'
  toggle: (n: PermNode) => void
  readonly: boolean
}>()

// 分组默认展开；system 锁定分组默认折叠（对齐原型：置灰组收起）
const collapsed = ref(props.node.sysLocked)

const childMenus = computed(() => (props.node.children ?? []).filter((c) => c.kind === 'menu'))
const childResources = computed(() => (props.node.children ?? []).filter((c) => c.kind === 'resource'))
const isGroup = computed(() => props.node.nodeType === 'group')
</script>

<template>
  <!-- 分组：可折叠卡片 -->
  <div v-if="isGroup" class="pt-grp" :class="{ collapsed, locked: node.sysLocked }">
    <div class="pt-grp-head" @click="collapsed = !collapsed">
      <el-icon class="pt-caret"><ArrowDown /></el-icon>
      <el-checkbox
        :model-value="stateOf(node) === 'on'"
        :indeterminate="stateOf(node) === 'half'"
        :disabled="readonly || node.sysLocked"
        @click.stop
        @change="toggle(node)"
      />
      <span class="pt-grp-title">{{ node.label }}</span>
      <el-tag v-if="node.sysLocked" type="warning" size="small" effect="plain" class="pt-lock">仅系统管理员</el-tag>
      <span v-else class="pt-gcount">分组</span>
    </div>
    <div v-show="!collapsed" class="pt-grp-body">
      <PermissionTree
        v-for="c in childMenus" :key="c.key"
        :node="c" :state-of="stateOf" :toggle="toggle" :readonly="readonly"
      />
      <!-- 分组直挂功能点（少见）：chip 面板 -->
      <div v-if="childResources.length" class="pt-funcs">
        <span v-for="r in childResources" :key="r.key" class="pt-func" :class="{ locked: r.sysLocked }">
          <el-checkbox
            :model-value="stateOf(r) === 'on'"
            :disabled="readonly || r.sysLocked"
            @change="toggle(r)"
          />
          <span class="pt-fname">{{ r.label }}</span>
          <span class="pt-ftype" :class="r.nodeType">{{ r.nodeType === 'api' ? '接口' : '按钮' }}</span>
        </span>
      </div>
    </div>
  </div>

  <!-- 叶子菜单：菜单行 + 功能点 chip 面板 -->
  <div v-else class="pt-menu" :class="{ locked: node.sysLocked }">
    <div class="pt-menu-row">
      <el-checkbox
        :model-value="stateOf(node) === 'on'"
        :indeterminate="stateOf(node) === 'half'"
        :disabled="readonly || node.sysLocked"
        @change="toggle(node)"
      />
      <span class="pt-mlabel"><span class="pt-ico">●</span>{{ node.label }}</span>
    </div>
    <div v-if="childResources.length" class="pt-funcs">
      <span v-for="r in childResources" :key="r.key" class="pt-func" :class="{ locked: r.sysLocked }">
        <el-checkbox
          :model-value="stateOf(r) === 'on'"
          :disabled="readonly || r.sysLocked"
          @change="toggle(r)"
        />
        <span class="pt-fname">{{ r.label }}</span>
        <span class="pt-ftype" :class="r.nodeType">{{ r.nodeType === 'api' ? '接口' : '按钮' }}</span>
      </span>
    </div>
  </div>
</template>

<style scoped>
/* 分组卡片（一级） */
.pt-grp { border: 1px solid var(--el-border-color-lighter); border-radius: 8px; margin-bottom: 10px; overflow: hidden; }
.pt-grp.locked { opacity: 0.6; }
.pt-grp-head { display: flex; align-items: center; gap: 9px; padding: 9px 12px; background: var(--el-fill-color-light);
  cursor: pointer; font-weight: 600; font-size: 13px; }
.pt-caret { color: var(--el-text-color-secondary); transition: transform 0.15s; }
.pt-grp.collapsed .pt-caret { transform: rotate(-90deg); }
.pt-grp.collapsed .pt-grp-body { display: none; }
.pt-grp-title { user-select: none; }
.pt-gcount { margin-left: auto; font-size: 11px; color: var(--el-text-color-secondary);
  background: var(--el-bg-color); border: 1px solid var(--el-border-color); border-radius: 10px; padding: 1px 8px; }
.pt-lock { margin-left: auto; transform: scale(0.9); }
.pt-grp-body { padding: 6px 12px 8px; }
/* 嵌套分组缩进 + 引导线 */
.pt-grp-body .pt-grp { margin-left: 14px; border-left: 2px solid var(--el-border-color); }
/* 菜单行（二级） */
.pt-menu { margin-left: 8px; border-left: 2px solid var(--el-border-color-lighter); padding-left: 12px; }
.pt-menu-row { display: flex; align-items: center; gap: 9px; padding: 6px 0; }
.pt-mlabel { font-size: 13px; display: inline-flex; align-items: center; gap: 6px; }
.pt-ico { color: var(--el-color-success); font-size: 10px; }
/* 功能点 chip 面板（三级） */
.pt-funcs { display: flex; flex-wrap: wrap; gap: 6px 16px; padding: 8px 12px; margin: 2px 0 8px 20px;
  background: var(--el-fill-color-light); border: 1px dashed var(--el-border-color); border-radius: 6px; }
.pt-func { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--el-text-color-regular); }
.pt-func.locked { opacity: 0.6; }
.pt-fname { user-select: none; }
.pt-ftype { font-size: 10px; color: var(--el-text-color-secondary); border: 1px solid var(--el-border-color);
  border-radius: 3px; padding: 0 4px; }
.pt-ftype.api { color: var(--el-color-success); border-color: color-mix(in srgb, var(--el-color-success) 40%, transparent); }
.pt-ftype.button { color: var(--el-color-warning); border-color: color-mix(in srgb, var(--el-color-warning) 40%, transparent); }
/* el-checkbox 只留框，不占 label 宽度 */
.pt-grp-head :deep(.el-checkbox), .pt-menu-row :deep(.el-checkbox), .pt-func :deep(.el-checkbox) { height: auto; margin-right: 0; }
.pt-grp-head :deep(.el-checkbox__label), .pt-menu-row :deep(.el-checkbox__label), .pt-func :deep(.el-checkbox__label) { display: none; }
</style>
