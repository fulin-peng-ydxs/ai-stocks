<script setup lang="ts">
import AppControlRow from '@/components/AppControlRow.vue'
import AppSummaryDisclosureCard from '@/components/AppSummaryDisclosureCard.vue'

const props = withDefaults(defineProps<{
  panelId: string
  indexLabel: string
  title: string
  meta: string
  content?: string | null
  enabled: boolean
  expanded: boolean
  editable: boolean
}>(), {
  content: null,
})

const emit = defineEmits<{
  toggle: []
  'update:enabled': [value: boolean]
}>()
</script>

<template>
  <AppSummaryDisclosureCard
    :panel-id="panelId"
    :index-label="indexLabel"
    :title="title"
    :toggle-label="`${expanded ? '收起' : '展开'}规则“${title}”`"
    :meta="meta"
    :preview="content"
    preview-fallback="尚未填写规则内容"
    :expanded="expanded"
    :muted="!enabled"
    toggle-test-id="rule-card-toggle"
    editor-test-id="rule-card-editor"
    @toggle="emit('toggle')"
  >
    <template #tools>
      <el-switch
        :model-value="enabled"
        :disabled="!editable"
        :aria-label="`${enabled ? '停用' : '启用'}规则“${title}”`"
        @update:model-value="emit('update:enabled', $event)"
      />
      <AppControlRow v-if="editable" class="rule-summary-card__actions">
        <slot name="actions" />
      </AppControlRow>
    </template>
    <slot />
  </AppSummaryDisclosureCard>
</template>

<style scoped>
.rule-summary-card__actions { display: flex; align-items: center; gap: var(--app-space-1); }
</style>
