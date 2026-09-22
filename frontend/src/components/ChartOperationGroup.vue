<script setup lang="ts">
import SettingsGroup from '@/components/SettingsGroup.vue'

defineProps<{
  label: string
}>()
</script>

<template>
  <SettingsGroup
    :title="label"
    :level="1"
    :collapsible="false"
    class="chart-operation-group"
  >
    <slot />
  </SettingsGroup>
</template>
