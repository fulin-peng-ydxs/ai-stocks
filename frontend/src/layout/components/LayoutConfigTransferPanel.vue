<script setup lang="ts">
import { ref } from 'vue'
import AppControlRow from '@/components/AppControlRow.vue'
import HelpHint from '@/components/HelpHint.vue'

withDefaults(defineProps<{
  mode: 'import' | 'export'
  title: string
  description: string
  modelValue: string
  editorLabel: string
  placeholder?: string
  busy?: boolean
}>(), { placeholder: '', busy: false })

const emit = defineEmits<{
  'update:modelValue': [value: string]
  'file-change': [event: Event]
}>()
const fileInput = ref<HTMLInputElement>()
const fileName = ref('')

/** 原生文件选择只负责取文件，解析、校验和保存仍由消费工作区负责。 */
function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  if (!input.files?.length) return
  fileName.value = input.files[0].name
  emit('file-change', event)
  // 允许重新选择同一文件，例如修正文件内容后重试。
  input.value = ''
}
</script>

<template>
  <section class="layout-config-transfer-panel" :aria-label="title">
    <header class="layout-config-transfer-panel__header">
      <h3 class="app-section-title">{{ title }}</h3>
      <HelpHint :text="description" />
    </header>

    <AppControlRow class="layout-config-transfer-panel__toolbar">
      <template v-if="mode === 'import'">
        <el-button :disabled="busy" @click="fileInput?.click()">选择 JSON 文件</el-button>
        <input ref="fileInput" hidden type="file" accept="application/json,.json" :disabled="busy" :aria-label="`${title}文件`" @change="onFileChange" />
        <span class="layout-config-transfer-panel__filename app-caption-text">{{ fileName || '未选择文件，可直接粘贴' }}</span>
      </template>
      <slot v-else name="toolbar" />
    </AppControlRow>

    <el-input
      class="layout-config-transfer-panel__editor app-textarea-fill app-code-input"
      :model-value="modelValue"
      type="textarea"
      :rows="6"
      resize="none"
      :disabled="busy"
      :aria-label="editorLabel"
      :placeholder="placeholder"
      spellcheck="false"
      @update:model-value="emit('update:modelValue', $event)"
    />
    <slot name="feedback" />

    <AppControlRow class="layout-config-transfer-panel__actions" justify="end">
      <slot name="actions" />
    </AppControlRow>
  </section>
</template>

<style scoped>
.layout-config-transfer-panel {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-3);
  min-width: 0;
  /* 同时为工具行、六行编辑内容和固定操作行保留可用空间；低窗口交给外层滚动。 */
  min-height: 400px;
  padding: var(--app-density-card-padding);
  border: 1px solid var(--el-border-color);
  border-radius: var(--layout-card-radius);
  background: var(--el-bg-color);
}
.layout-config-transfer-panel__header {
  display: flex;
  align-items: center;
  flex: 0 0 auto;
  gap: var(--app-space-2);
}
.layout-config-transfer-panel__header h3 { margin: 0; }
.layout-config-transfer-panel__toolbar,
.layout-config-transfer-panel__actions {
  flex: 0 0 auto;
}
.layout-config-transfer-panel__filename {
  flex: 1 1 120px;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--el-text-color-secondary);
}
.layout-config-transfer-panel__editor {
  display: flex;
  flex: 1 1 0;
}
.layout-config-transfer-panel__actions {
  padding-top: var(--app-space-3);
  border-top: 1px solid var(--el-border-color-lighter);
}
</style>
