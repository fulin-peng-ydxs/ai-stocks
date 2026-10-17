<script setup lang="ts">
// 递归渲染分区内部节点；depth 是展示深度，二级菜单从 0 开始，原始授权层级不变。
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
