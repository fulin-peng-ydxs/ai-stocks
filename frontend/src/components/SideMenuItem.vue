<script setup lang="ts">
// 递归渲染单个菜单节点：分组 → el-sub-menu（点标题即展开/折叠），叶子 → el-menu-item（router 导航）。
// icon 为 Element Plus 图标名（后端菜单数据化，T15），统一交给 MenuIcon 渲染与回退。
import type { MenuTreeNode } from '@/utils/permission'
import MenuIcon from './MenuIcon.vue'

withDefaults(defineProps<{ node: MenuTreeNode; depth?: number }>(), { depth: 0 })
</script>

<template>
  <el-sub-menu
    v-if="node.children?.length" :index="node.index" class="side-menu-node"
    :class="{ 'is-root-menu-node': depth === 0 }" :style="{ '--side-menu-depth': depth }"
  >
    <template #title>
      <span class="menu-label">
        <span class="menu-icon" aria-hidden="true"><MenuIcon v-if="node.icon" :name="node.icon" /></span>
        <span class="menu-text">{{ node.title }}</span>
      </span>
    </template>
    <SideMenuItem v-for="child in node.children" :key="child.index" :node="child" :depth="depth + 1" />
  </el-sub-menu>
  <el-menu-item
    v-else :index="node.index" class="side-menu-node"
    :class="{ 'is-root-menu-node': depth === 0 }" :style="{ '--side-menu-depth': depth }"
  >
    <span class="menu-label">
      <span class="menu-icon" aria-hidden="true"><MenuIcon v-if="node.icon" :name="node.icon" /></span>
      <span class="menu-text">{{ node.title }}</span>
    </span>
  </el-menu-item>
</template>

<style scoped>
.menu-label {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
  flex: 1;
  min-width: 0;
}
.menu-icon {
  width: var(--side-menu-icon-size);
  height: var(--side-menu-icon-size);
  flex: 0 0 var(--side-menu-icon-size);
  font-size: var(--side-menu-icon-size);
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.menu-text {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
