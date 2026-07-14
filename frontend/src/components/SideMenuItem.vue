<script setup lang="ts">
// 递归渲染单个菜单节点：分组 → el-sub-menu（点标题即展开/折叠），叶子 → el-menu-item（router 导航）。
// icon 为 Element Plus 图标名（后端菜单数据化，T15），统一交给 MenuIcon 渲染与回退。
import type { MenuTreeNode } from '@/utils/permission'
import MenuIcon from './MenuIcon.vue'

defineProps<{ node: MenuTreeNode }>()
</script>

<template>
  <el-sub-menu v-if="node.children?.length" :index="node.index">
    <template #title>
      <span class="menu-label">
        <MenuIcon v-if="node.icon" :name="node.icon" class="menu-icon" />{{ node.title }}
      </span>
    </template>
    <SideMenuItem v-for="child in node.children" :key="child.index" :node="child" />
  </el-sub-menu>
  <el-menu-item v-else :index="node.index">
    <span class="menu-label">
      <MenuIcon v-if="node.icon" :name="node.icon" class="menu-icon" />{{ node.title }}
    </span>
  </el-menu-item>
</template>

<style scoped>
.menu-label {
  display: inline-flex;
  align-items: center;
  gap: var(--app-space-control-gap);
  min-width: 0;
}
.menu-icon {
  width: 24px;
  height: 24px;
  flex: 0 0 24px;
  border: 1px solid transparent;
  border-radius: 6px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: background-color 0.16s ease, border-color 0.16s ease, color 0.16s ease;
}
</style>
