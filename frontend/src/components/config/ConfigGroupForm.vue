<script setup lang="ts">
import type { SettingGroup } from '@/api/data'

const props = defineProps<{
  group: SettingGroup
  modelValue: Record<string, unknown>
  disabled?: boolean
  invalidPaths?: string[]
}>()

const emit = defineEmits<{
  'update-field': [path: string, value: unknown]
}>()

function valueOf(path: string) {
  return props.modelValue[path]
}

function setValue(path: string, value: unknown) {
  emit('update-field', path, value)
}

function isInvalid(path: string): boolean {
  return (props.invalidPaths ?? []).includes(path)
}

function defaultLabel(value: unknown): string {
  if (value === true) return '开启'
  if (value === false) return '关闭'
  if (value === null || value === undefined || value === '') return '-'
  return String(value)
}

function rangeLabel(field: SettingGroup['fields'][number]): string {
  if (field.min == null && field.max == null) return ''
  if (field.min != null && field.max != null) return `${field.min} - ${field.max}`
  if (field.min != null) return `>= ${field.min}`
  return `<= ${field.max}`
}
</script>

<template>
  <section class="config-group-panel" :aria-label="group.label">
    <header class="config-group-head">
      <div>
        <h3>{{ group.label }}</h3>
        <span>{{ group.fields.length }} 项</span>
      </div>
    </header>

    <el-form class="config-group-form" label-position="top">
      <el-form-item
        v-for="field in group.fields"
        :key="field.path"
        :class="{ 'is-invalid': isInvalid(field.path) }"
      >
        <template #label>
          <span class="field-label">
            {{ field.label }}
            <el-tag v-if="field.overridden" size="small" type="warning" effect="plain">已覆盖</el-tag>
          </span>
        </template>

        <div class="field-control">
          <el-switch
            v-if="field.type === 'bool'"
            :model-value="Boolean(valueOf(field.path))"
            :disabled="disabled"
            @update:model-value="(value: boolean) => setValue(field.path, value)"
          />
          <el-select
            v-else-if="field.type === 'enum'"
            :model-value="String(valueOf(field.path) ?? '')"
            :disabled="disabled"
            @update:model-value="(value: string) => setValue(field.path, value)"
          >
            <el-option v-for="opt in field.options ?? []" :key="opt" :label="opt" :value="opt" />
          </el-select>
          <el-input-number
            v-else
            :model-value="Number(valueOf(field.path))"
            :min="field.min"
            :max="field.max"
            :step="field.type === 'number' ? 0.0001 : 1"
            :controls="field.type === 'int'"
            :disabled="disabled"
            @update:model-value="(value: number | undefined) => setValue(field.path, value)"
          />
        </div>

        <div class="field-meta">
          <span>默认 {{ defaultLabel(field.default) }}</span>
          <span v-if="rangeLabel(field)">范围 {{ rangeLabel(field) }}</span>
          <span v-if="isInvalid(field.path)" class="field-error">超出允许范围</span>
        </div>
      </el-form-item>
    </el-form>
  </section>
</template>

<style scoped>
.config-group-panel {
  min-width: 0;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-bg-color-overlay);
}
.config-group-head {
  padding: 12px 14px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.config-group-head h3 {
  margin: 0;
  font-size: 16px;
  line-height: 1.35;
}
.config-group-head span {
  display: block;
  margin-top: 3px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.config-group-form {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
  gap: 12px 16px;
  padding: 14px;
}
.field-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.field-control :deep(.el-select),
.field-control :deep(.el-input-number) {
  width: 100%;
}
.field-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  min-height: 18px;
  margin-top: 5px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.field-error {
  color: var(--el-color-danger);
}
.is-invalid :deep(.el-input-number .el-input__wrapper),
.is-invalid :deep(.el-select .el-select__wrapper) {
  box-shadow: 0 0 0 1px var(--el-color-danger) inset;
}
</style>
