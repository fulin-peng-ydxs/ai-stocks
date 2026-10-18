<script setup lang="ts">
/** 业务选项分区的语义别名；视觉、折叠和树关系统一委托 SettingsGroup。 */
import SettingsGroup from './SettingsGroup.vue'

const props = withDefaults(
  defineProps<{ sectionKey: string; title?: string; desc?: string; collapsible?: boolean }>(),
  { collapsible: true },
)
</script>

<template>
  <SettingsGroup :title="title" :hint="desc" :level="2" :collapsible="collapsible" :fold-key="`business:${sectionKey}`">
    <slot />
  </SettingsGroup>
</template>
