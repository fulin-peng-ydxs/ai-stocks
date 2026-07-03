<script setup lang="ts">
// 递归渲染单个菜单节点：分组 → el-sub-menu（点标题即展开/折叠），叶子 → el-menu-item（router 导航）。
// icon 为 Element Plus 图标名（后端菜单数据化，T15）：按名取组件渲染；非图标库名（如 emoji）回退为文本。
import { computed } from 'vue'
import type { Component } from 'vue'
import * as EpIcons from '@element-plus/icons-vue'
import type { MenuTreeNode } from '@/utils/permission'

const props = defineProps<{ node: MenuTreeNode }>()

const iconMap = EpIcons as unknown as Record<string, Component>
const iconComp = computed<Component | null>(() =>
  props.node.icon ? (iconMap[props.node.icon] ?? null) : null)
</script>

<template>
  <el-sub-menu v-if="node.children?.length" :index="node.index">
    <template #title>
      <span class="menu-label">
        <el-icon v-if="iconComp" class="menu-icon"><component :is="iconComp" /></el-icon>
        <span v-else-if="node.icon" class="menu-icon">{{ node.icon }}</span>{{ node.title }}
      </span>
    </template>
    <SideMenuItem v-for="child in node.children" :key="child.index" :node="child" />
  </el-sub-menu>
  <el-menu-item v-else :index="node.index">
    <span class="menu-label">
      <el-icon v-if="iconComp" class="menu-icon"><component :is="iconComp" /></el-icon>
      <span v-else-if="node.icon" class="menu-icon">{{ node.icon }}</span>{{ node.title }}
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
