<script setup lang="ts">
import PageSettingItem from '@/components/PageSettingItem.vue'

defineProps<{
  label: string
}>()
</script>

<template>
  <PageSettingItem
    :label="label"
    class="chart-operation-group"
    role="group"
    :aria-label="label"
  >
    <slot />
  </PageSettingItem>
</template>
