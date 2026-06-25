<script setup lang="ts">
// 递归渲染单个菜单节点：分组 → el-sub-menu（点标题即展开/折叠），叶子 → el-menu-item（router 导航）。
import type { MenuNode } from './menuConfig'

defineProps<{ node: MenuNode }>()
</script>

<template>
  <el-sub-menu v-if="node.children?.length" :index="node.index">
    <template #title>
      <span class="menu-label">
        <span v-if="node.icon" class="menu-icon">{{ node.icon }}</span>{{ node.title }}
      </span>
    </template>
    <SideMenuItem v-for="child in node.children" :key="child.index" :node="child" />
  </el-sub-menu>
  <el-menu-item v-else :index="node.index">
    <span class="menu-label">
      <span v-if="node.icon" class="menu-icon">{{ node.icon }}</span>{{ node.title }}
    </span>
  </el-menu-item>
</template>

<style scoped>
.menu-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
</style>
