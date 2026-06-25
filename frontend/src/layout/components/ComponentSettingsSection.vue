<script setup lang="ts">
/**
 * 组件特性配置表单区块（P2 / M8-0）——配置中心与页面设置抽屉复用的唯一组件配置 UI。
 *
 * 由 componentConfig.ts 的字段元数据驱动：按页面 slots × 各 slot 组件种类的受控字段，
 * 过滤出"允许在当前层(layer)覆盖"的字段并渲染对应控件。取值/写值经父级回调（draft 或 useLayoutConfig），
 * 控件类型由 ComponentFieldDef.control 决定，越权/越界守门在 set 链路（父级）与后端最终拒绝。
 */
import { computed, nextTick, ref, watch } from 'vue'
import {
  getComponentFieldDefs,
  isLayerAllowed,
  type ComponentConfigLayer,
  type ComponentConfigSource,
  type ComponentFieldDef,
} from '../componentConfig'
import type { SlotSpec } from '../schema'
import type { SlotConfigMeta } from '../pageRegistry'
import PageToggleRow from '@/components/PageToggleRow.vue'

const props = defineProps<{
  slots: SlotSpec[]
  /** 当前编辑层（决定显示哪些字段）。 */
  layer: ComponentConfigLayer
  /** 读某 slot 某字段当前值。 */
  getValue: (slotId: string, field: string) => unknown
  /** 写某 slot 某字段。 */
  setValue: (slotId: string, field: string, value: unknown) => void
  /** 可选：读取生效来源层用于展示来源徽标。 */
  sourceOf?: (slotId: string, field: string) => ComponentConfigSource
  /** 仅显示高频字段（页面设置抽屉给用户时建议开启）。 */
  highFrequencyOnly?: boolean
  /**
   * 可选：按 slotId -> 字段 key 列表，只渲染该页"实际消费"的字段（来自 pageRegistry.consumedComponentFields）。
   * 不传则渲染该组件种类全部受控字段。配置中心必须传，避免暴露页面不读的配置项。
   */
  fields?: Record<string, string[]>
  /** 页面专属字段的安全枚举来源（列、排序字段、tabs），来自 pageRegistry.componentMeta。 */
  meta?: Record<string, SlotConfigMeta>
  /** 可选：高亮并滚动到该 slot 的配置组（页面布局工作台"点击预览即配置"用，Q5）。 */
  highlightSlot?: string | null
}>()

const root = ref<HTMLElement | null>(null)
watch(
  () => props.highlightSlot,
  async (id) => {
    if (!id) return
    await nextTick()
    root.value?.querySelector(`[data-cc-slot="${id}"]`)?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  },
)

/**
 * 页面专属枚举/数组/对象字段（取值集合随页面而异）不在配置中心做自由编辑，只读展示，
 * 由各页设置抽屉用页面自带枚举控件安全编辑。仅页面无关的标量（int/number/bool/带全局 options 的 enum）可中心编辑。
 */
const SOURCE_LABELS: Record<ComponentConfigSource, string> = {
  default: '默认',
  preset: '预设',
  page: '页面',
  user: '个人',
}

interface SlotGroup {
  slotId: string
  title: string
  fields: ComponentFieldDef[]
  meta: SlotConfigMeta
}

function isRenderable(slotId: string, def: ComponentFieldDef): boolean {
  if (def.control === 'bool' || def.control === 'int' || def.control === 'number' || def.control === 'enum') return true
  if (def.control === 'string[]' && def.options?.length) return true
  const meta = props.meta?.[slotId]
  if (def.key === 'defaultSort') return !!meta?.sortFields?.length
  if (def.key === 'hiddenColumns') return !!meta?.columns?.length
  if (def.key === 'defaultActive') return !!meta?.tabs?.length
  return false
}

const groups = computed<SlotGroup[]>(() => {
  const out: SlotGroup[] = []
  for (const slot of props.slots) {
    const consumed = props.fields?.[slot.id]
    const fields = getComponentFieldDefs(slot.component).filter(
      (def) =>
        isLayerAllowed(def, props.layer) &&
        (!props.highFrequencyOnly || def.highFrequency) &&
        (!consumed || consumed.includes(def.key)) &&
        isRenderable(slot.id, def),
    )
    if (!fields.length) continue
    out.push({ slotId: slot.id, title: `${slot.label || slot.id} · ${slot.component}`, fields, meta: props.meta?.[slot.id] ?? {} })
  }
  return out
})

function listValue(slotId: string, field: string): string[] {
  const value = props.getValue(slotId, field)
  return Array.isArray(value) ? value as string[] : []
}

function strValue(slotId: string, field: string): string {
  const value = props.getValue(slotId, field)
  return typeof value === 'string' ? value : ''
}

function sortField(slotId: string): string {
  return strValue(slotId, 'defaultSort').split(':')[0] ?? ''
}

function sortOrder(slotId: string): string {
  return strValue(slotId, 'defaultSort').split(':')[1] || 'desc'
}

function setSort(slotId: string, field: string, order: string, withDirection: boolean): void {
  if (!field) props.setValue(slotId, 'defaultSort', null)
  else props.setValue(slotId, 'defaultSort', withDirection ? `${field}:${order}` : field)
}

function columnVisible(slotId: string, key: string): boolean {
  return !listValue(slotId, 'hiddenColumns').includes(key)
}

function setColumnVisible(slotId: string, key: string, visible: boolean): void {
  const next = new Set(listValue(slotId, 'hiddenColumns'))
  if (visible) next.delete(key)
  else next.add(key)
  props.setValue(slotId, 'hiddenColumns', [...next])
}
</script>

<template>
  <div v-if="groups.length" ref="root" class="cc-section">
    <div
      v-for="group in groups"
      :key="group.slotId"
      :data-cc-slot="group.slotId"
      class="cc-group"
      :class="{ 'is-highlight': group.slotId === highlightSlot }"
    >
      <div class="cc-group-title">{{ group.title }}</div>
      <div v-for="def in group.fields" :key="def.key" class="cc-field">
        <div class="cc-field-label">
          <span>{{ def.label }}</span>
          <span v-if="props.sourceOf" class="cc-source">{{ SOURCE_LABELS[props.sourceOf(group.slotId, def.key)] }}</span>
        </div>

        <el-switch
          v-if="def.control === 'bool'"
          :model-value="Boolean(props.getValue(group.slotId, def.key))"
          @update:model-value="(v: string | number | boolean) => props.setValue(group.slotId, def.key, v)"
        />
        <el-select
          v-else-if="def.control === 'enum'"
          :model-value="(props.getValue(group.slotId, def.key) as string | number) ?? ''"
          clearable
          placeholder="不覆盖"
          @update:model-value="(v: unknown) => props.setValue(group.slotId, def.key, v)"
        >
          <el-option
            v-for="opt in def.options"
            :key="String(opt)"
            :label="def.optionLabels?.[String(opt)] ?? String(opt)"
            :value="opt"
          />
        </el-select>
        <el-input-number
          v-else-if="def.control === 'int' || def.control === 'number'"
          :model-value="(props.getValue(group.slotId, def.key) as number)"
          :min="def.min"
          :max="def.max"
          :step="def.control === 'int' ? 10 : undefined"
          controls-position="right"
          @update:model-value="(v: number | undefined) => props.setValue(group.slotId, def.key, v ?? '')"
        />
        <el-checkbox-group
          v-else-if="def.control === 'string[]' && def.options?.length"
          :model-value="Array.isArray(props.getValue(group.slotId, def.key)) ? (props.getValue(group.slotId, def.key) as string[]) : []"
          @update:model-value="(v: string[]) => props.setValue(group.slotId, def.key, v)"
        >
          <el-checkbox v-for="opt in def.options" :key="String(opt)" :label="String(opt)">
            {{ def.optionLabels?.[String(opt)] ?? String(opt) }}
          </el-checkbox>
        </el-checkbox-group>

        <template v-else-if="def.key === 'defaultSort' && group.meta.sortFields?.length">
          <el-select
            :model-value="sortField(group.slotId)"
            clearable
            placeholder="不覆盖"
            @update:model-value="(v: string) => setSort(group.slotId, v, sortOrder(group.slotId), group.meta.sortHasDirection !== false)"
          >
            <el-option
              v-for="opt in group.meta.sortFields"
              :key="opt.key"
              :label="opt.label"
              :value="opt.key"
            />
          </el-select>
          <el-segmented
            v-if="group.meta.sortHasDirection !== false"
            :model-value="sortOrder(group.slotId)"
            :options="[{ label: '升序', value: 'asc' }, { label: '降序', value: 'desc' }]"
            @update:model-value="(v: string | number) => setSort(group.slotId, sortField(group.slotId), String(v), true)"
          />
        </template>

        <el-select
          v-else-if="def.key === 'defaultActive' && group.meta.tabs?.length"
          :model-value="strValue(group.slotId, 'defaultActive')"
          clearable
          placeholder="不覆盖"
          @update:model-value="(v: string) => props.setValue(group.slotId, 'defaultActive', v || null)"
        >
          <el-option v-for="tab in group.meta.tabs" :key="tab.key" :label="tab.label" :value="tab.key" />
        </el-select>

        <div v-else-if="def.key === 'hiddenColumns' && group.meta.columns?.length" class="cc-columns">
          <div class="cc-columns-head">
            <span>默认显示列</span>
            <el-button link size="small" @click="props.setValue(group.slotId, 'hiddenColumns', null)">不覆盖</el-button>
          </div>
          <PageToggleRow
            v-for="col in group.meta.columns"
            :key="col.key"
            :model-value="columnVisible(group.slotId, col.key)"
            :label="`显示${col.label}`"
            @update:model-value="(v: boolean) => setColumnVisible(group.slotId, col.key, v)"
          />
        </div>

        <div v-if="def.help" class="cc-help">{{ def.help }}</div>
      </div>
    </div>
  </div>
  <el-empty v-else description="该页面暂无可配置的组件特性" :image-size="48" />
</template>

<style scoped>
.cc-section {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.cc-group {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  padding: 12px;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}
.cc-group.is-highlight {
  border-color: var(--el-color-primary);
  box-shadow: 0 0 0 1px var(--el-color-primary) inset;
}
.cc-group-title {
  font-size: 13px;
  font-weight: 650;
  color: var(--el-text-color-primary);
  margin-bottom: 10px;
}
.cc-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 12px;
}
.cc-field:last-child {
  margin-bottom: 0;
}
.cc-field-label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  font-size: 13px;
  color: var(--el-text-color-regular);
}
.cc-source {
  flex: none;
  border: 1px solid var(--el-border-color);
  border-radius: 999px;
  padding: 1px 7px;
  font-size: 11px;
  color: var(--el-text-color-secondary);
}
.cc-help {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.cc-columns {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
}
.cc-columns-head {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  font-size: 13px;
  color: var(--el-text-color-regular);
}
</style>
