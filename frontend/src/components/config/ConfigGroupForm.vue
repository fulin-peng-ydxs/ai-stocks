<script setup lang="ts">
import AppForm from '@/components/AppForm.vue'
import AppSelect from '@/components/AppSelect.vue'
import { computed } from 'vue'
import type { SettingField, SettingGroup } from '@/api/data'
import HelpHint from '@/components/HelpHint.vue'
import type { ConfigFieldSection, ConfigPanelBehavior } from '@/layout/configPanel'
import ConfigPanelSection from './ConfigPanelSection.vue'

// fieldStatus：按字段 path 附带的只读能力就绪徽标（如邮箱码开关下的「真实发信是否就绪」）。
// 通用机制——后续新能力集成可复用同一映射，不必逐个改表单结构。
type FieldStatus = { tone: 'ok' | 'warn'; text: string }
interface FieldBlock {
  key: string
  title?: string
  hint?: string
  badge?: string
  defaultOpen: boolean
  fields: SettingField[]
}
const props = defineProps<{
  group: SettingGroup
  sections?: ConfigFieldSection[]
  panelBehavior?: ConfigPanelBehavior
  modelValue: Record<string, unknown>
  disabled?: boolean
  invalidPaths?: string[]
  fieldStatus?: Record<string, FieldStatus>
}>()

function statusOf(path: string): FieldStatus | undefined {
  return props.fieldStatus?.[path]
}

const emit = defineEmits<{
  'update-field': [path: string, value: unknown]
  'reset-field': [path: string]
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

function helpText(field: SettingField): string {
  const range = rangeLabel(field)
  return [
    field.desc,
    field.nullable ? "留空：继承通用请求配置" : "",
    `默认值：${defaultLabel(field.default)}`,
    range ? `允许范围：${range}` : '',
  ].filter(Boolean).join('；')
}

const fieldBlocks = computed<FieldBlock[]>(() => {
  const fieldsByPath = new Map(props.group.fields.map((field) => [field.path, field]))
  const used = new Set<string>()
  const sections: FieldBlock[] = (props.sections ?? []).map((section) => {
    const fields = section.fieldPaths
      .map((path) => fieldsByPath.get(path))
      .filter((field): field is SettingField => !!field)
    fields.forEach((field) => used.add(field.path))
    return {
      key: section.key,
      title: section.title,
      hint: section.hint,
      badge: `${fields.length} 项`,
      defaultOpen: section.defaultOpen ?? true,
      fields,
    }
  }).filter((section) => section.fields.length)

  const rest = props.group.fields.filter((field) => !used.has(field.path))
  if (rest.length) {
    sections.push({
      key: `${props.group.key}-other`,
      title: sections.length ? '其他配置' : undefined,
      badge: sections.length ? `${rest.length} 项` : undefined,
      defaultOpen: true,
      fields: rest,
    })
  }
  return sections
})

const behavior = computed<ConfigPanelBehavior>(() => ({
  collapsibleSections: props.panelBehavior?.collapsibleSections ?? true,
  defaultCollapsed: props.panelBehavior?.defaultCollapsed ?? [],
  showGroupDescription: props.panelBehavior?.showGroupDescription ?? true,
  showSectionDescription: props.panelBehavior?.showSectionDescription ?? true,
}))

function collapsed(key: string): boolean {
  return behavior.value.defaultCollapsed.includes(key)
}
</script>

<template>
  <ConfigPanelSection
    class="config-group-panel"
    :title="group.label"
    :description="group.desc"
    :badge="`${group.fields.length} 项`"
    :level="1"
    :collapsible="behavior.collapsibleSections"
    :default-open="!collapsed(group.key)"
    :show-description="behavior.showGroupDescription"
    :aria-label="group.label"
  >
    <ConfigPanelSection
      v-for="block in fieldBlocks"
      :key="block.key"
      class="config-field-block"
      :title="block.title"
      :description="block.hint"
      :badge="block.badge"
      :level="2"
      :collapsible="behavior.collapsibleSections && !!block.title"
      :default-open="block.defaultOpen && !collapsed(`${group.key}.${block.key}`)"
      :show-description="behavior.showSectionDescription"
    >
      <AppForm class="config-group-form" label-position="top">
        <el-form-item
          v-for="field in block.fields"
          :key="field.path"
          :required="!disabled && !field.nullable && (field.type === 'enum' || field.type === 'int' || field.type === 'number')"
          :class="{ 'is-invalid': isInvalid(field.path) }"
        >
          <template #label>
            <span class="field-label">
              {{ field.label }}
              <HelpHint :text="helpText(field)" />
            </span>
          </template>

          <div class="field-control" :class="`is-${field.type}`">
            <div v-if="field.nullable" class="app-stack-sm">
              <el-switch
                :model-value="valueOf(field.path) != null"
                :aria-label="`${field.label}独立覆盖`"
                active-text="单独设置" inactive-text="继承通用"
                :disabled="disabled"
                @update:model-value="(enabled: boolean) => setValue(field.path, enabled ? field.inherited_value ?? field.min ?? 0 : null)"
              />
              <el-input-number v-if="valueOf(field.path) != null"
                :model-value="Number(valueOf(field.path))" :min="field.min" :max="field.max"
                :controls="field.type === 'int'" :disabled="disabled"
                @update:model-value="(value: number | undefined) => setValue(field.path, value ?? null)" />
              <span v-else class="field-inherited">当前继承：{{ field.inherited_value ?? '通用配置' }}</span>
            </div>
            <el-switch
              v-else-if="field.type === 'bool'"
              :model-value="Boolean(valueOf(field.path))"
              :disabled="disabled"
              @update:model-value="(value: boolean) => setValue(field.path, value)"
            />
            <AppSelect
              v-else-if="field.type === 'enum'"
              :model-value="String(valueOf(field.path) ?? '')"
              :disabled="disabled"
              placeholder="请选择"
              @update:model-value="(value: string) => setValue(field.path, value)"
            >
              <el-option v-for="opt in field.options ?? []" :key="opt" :label="opt" :value="opt" />
            </AppSelect>
            <el-input-number
              v-else-if="field.type === 'number' || field.type === 'int'"
              :model-value="valueOf(field.path) == null ? undefined : Number(valueOf(field.path))"
              :placeholder="field.nullable ? '继承通用配置' : undefined"
              :min="field.min"
              :max="field.max"
              :step="field.type === 'number' ? 0.0001 : 1"
              :controls="field.type === 'int'"
              :disabled="disabled"
              @update:model-value="(value: number | undefined) => setValue(field.path, value ?? (field.nullable ? null : value))"
            />
            <el-input
              v-else-if="field.type === 'password'"
              :model-value="String(valueOf(field.path) ?? '')"
              :disabled="disabled"
              type="password"
              show-password
              :placeholder="field.placeholder || (valueOf(field.path) ? '已设置，留空不修改' : '请输入')"
              autocomplete="new-password"
              readonly
              @focus="($event.target as HTMLInputElement).removeAttribute('readonly')"
              @update:model-value="(value: string) => setValue(field.path, value)"
            />
            <el-input
              v-else-if="field.type === 'string'"
              :model-value="String(valueOf(field.path) ?? '')"
              :disabled="disabled"
              :placeholder="field.placeholder || ''"
              @update:model-value="(value: string) => setValue(field.path, value)"
            />
          </div>

          <el-button v-if="field.type === 'password' && field.secret_status && field.secret_status !== 'unset'"
            v-permission="'data-settings:manage'" text type="danger" :disabled="disabled"
            @click="emit('reset-field', field.path)">清除已存配置</el-button>

          <div v-if="isInvalid(field.path) || statusOf(field.path)" class="field-meta">
            <span v-if="isInvalid(field.path)" class="field-error">超出允许范围</span>
            <span
              v-if="statusOf(field.path)"
              class="field-status"
              :class="`is-${statusOf(field.path)!.tone}`"
            >
              <span class="dot" aria-hidden="true" />{{ statusOf(field.path)!.text }}
            </span>
          </div>
        </el-form-item>
      </AppForm>
    </ConfigPanelSection>
  </ConfigPanelSection>
</template>

<style scoped>
.config-group-panel {
  min-width: 0;
}
.config-group-form {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 280px));
  gap: var(--app-space-3) var(--app-space-5);
  align-items: start;
}
.field-label {
  display: inline-flex;
  align-items: center;
  gap: var(--app-space-control-gap);
  min-width: 0;
}
.field-inherited { display: block; color: var(--el-text-color-secondary); font-size: var(--app-font-size-caption); }
.field-control {
  width: 100%;
  min-width: 0;
}
.field-control.is-bool {
  display: flex;
  align-items: center;
  min-height: 32px;
  width: auto;
}
.field-control :deep(.el-select),
.field-control :deep(.el-input-number) {
  width: 100%;
}
.field-meta {
  display: flex;
  align-items: flex-start;
  flex-wrap: wrap;
  gap: var(--app-space-control-gap) var(--app-space-2);
  min-height: 18px;
  margin-top: 7px;
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
  line-height: var(--app-line-height-comfy);
}
.field-error {
  color: var(--el-color-danger);
}
.field-status {
  flex-basis: 100%;
  display: inline-flex;
  align-items: center;
  gap: var(--app-space-control-gap);
}
.field-status .dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex: none;
}
.field-status.is-ok { color: var(--el-color-success); }
.field-status.is-ok .dot { background: var(--el-color-success); }
.field-status.is-warn { color: var(--el-color-warning); }
.field-status.is-warn .dot { background: var(--el-color-warning); }
.is-invalid :deep(.el-input-number .el-input__wrapper),
.is-invalid :deep(.el-select .el-select__wrapper) {
  box-shadow: 0 0 0 1px var(--el-color-danger) inset;
}

@container app-viewport (max-width: 720px) {
  .config-group-form {
    grid-template-columns: minmax(0, 1fr);
  }

  .field-control,
  .field-control :deep(.el-select),
  .field-control :deep(.el-input-number) {
    width: 100%;
    max-width: none;
  }
}
</style>
