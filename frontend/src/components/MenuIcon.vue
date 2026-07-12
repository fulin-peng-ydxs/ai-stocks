<script setup lang="ts">
import { computed } from 'vue'
import { resolveMenuIcon } from '@/utils/menuIcon'

const props = defineProps<{ name?: string | null }>()
const iconComponent = computed(() => resolveMenuIcon(props.name))
</script>

<template>
  <el-icon v-if="iconComponent" aria-hidden="true"><component :is="iconComponent" /></el-icon>
  <span v-else-if="name" aria-hidden="true">{{ name }}</span>
</template>
