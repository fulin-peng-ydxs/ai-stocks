<script setup lang="ts">
import { computed, ref, useSlots, watch } from 'vue'
import { Close } from '@element-plus/icons-vue'
import type { EditableKnob } from '@/layout/schema'
import type { LayoutConfigLayer } from '@/layout/merge'
import { getPageEntry, type SlotConfigMeta } from '@/layout/pageRegistry'
import SettingsGroup from './SettingsGroup.vue'
import ComponentAutoSettings from './ComponentAutoSettings.vue'
import PageDrawer from './PageDrawer.vue'
import LayoutSettingsSection from '@/layout/components/LayoutSettingsSection.vue'
import AppIconButton from './AppIconButton.vue'

/** 抽屉自动渲染所需的配置访问器（即 useRemoteLayoutConfig 的返回子集）。 */
export interface DrawerConfig {
  knobs: EditableKnob[]
  valueOf: (path: string) => unknown
  sourceOf: (path: string) => LayoutConfigLayer
  layerValuesOf?: (path: string) => Partial<Record<LayoutConfigLayer, unknown>>
  setKnob: (path: string, value: unknown) => void
  componentValueOf: (slotId: string, field: string) => unknown
  setComponentKnob: (slotId: string, field: string, value: unknown) => void
  componentSourceOf?: (slotId: string, field: string) => 'default' | 'preset' | 'page' | 'user'
  componentLayerValuesOf?: (slotId: string, field: string) => Partial<Record<'default' | 'preset' | 'page' | 'user', unknown>>
}

const props = defineProps<{
  modelValue: boolean
  title?: string
  dirty?: boolean
  /** 传入则自动渲染「布局」+「组件设置」段（pageKey 用于查 registry 的组件元数据）。 */
  pageKey?: string
  config?: DrawerConfig
  businessVisible?: boolean
  componentMetaOverrides?: Record<string, SlotConfigMeta>
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  reset: []
}>()
const slots = useSlots()

const hasLayoutKnobs = computed(() => !!props.config?.knobs?.length)
const hasComponentConfig = computed(
  () => !!props.pageKey && !!getPageEntry(props.pageKey)?.consumedComponentFields,
)
const hasBusinessSlot = computed(() => props.businessVisible !== false && !!slots.business)

type SectionKey = 'layout' | 'components' | 'business'
const SECTION_KEYS: SectionKey[] = ['layout', 'components', 'business']

const collapsibleSections = computed(() => props.config?.componentValueOf('settings', 'collapsibleSections') !== false)
const drawerSize = computed(() => {
  const size = props.config?.componentValueOf('settings', 'size')
  return size === 'sm' ? '320px' : size === 'lg' ? '440px' : '360px'
})
const bodyScroll = computed(() => props.config?.componentValueOf('settings', 'bodyScroll') !== false)
const collapsedSections = computed<SectionKey[]>(() => {
  const raw = props.config?.componentValueOf('settings', 'defaultCollapsed')
  if (!Array.isArray(raw)) return []
  return raw.filter((v): v is SectionKey => SECTION_KEYS.includes(v as SectionKey))
})
const runtimeCollapsedSections = ref<SectionKey[]>([])

watch(
  () => props.modelValue,
  (open) => {
    if (open) runtimeCollapsedSections.value = [...collapsedSections.value]
  },
  { immediate: true },
)

function sectionOpen(key: SectionKey): boolean {
  if (!collapsibleSections.value) return true
  return !runtimeCollapsedSections.value.includes(key)
}

function setSectionOpen(key: SectionKey, open: boolean): void {
  if (!collapsibleSections.value) return
  const next = new Set(runtimeCollapsedSections.value)
  if (open) next.delete(key)
  else next.add(key)
  runtimeCollapsedSections.value = SECTION_KEYS.filter((section) => next.has(section))
}
</script>

<template>
  <PageDrawer
    :model-value="props.modelValue"
    @update:model-value="(value: boolean) => emit('update:modelValue', value)"
    direction="rtl"
    :size="drawerSize"
    class="page-settings-drawer"
    modal-class="ps-settings-modal"
  >
    <div class="ps-card">
      <header class="ps-header">
        <div class="ps-title">
          <span>{{ props.title || '页面设置' }}</span>
          <span v-if="props.dirty" class="ps-dirty-dot" />
        </div>
        <AppIconButton class="ps-close" label="关闭页面设置" size="sm" @click="emit('update:modelValue', false)">
          <el-icon><Close /></el-icon>
        </AppIconButton>
      </header>

      <!--
        固定三段（P13）：布局 / 组件设置 / 业务选项，均为可折叠的 SettingsGroup（level 1 卡片）。
        - 传 :config(+:pageKey)：布局段(editable 旋钮)与组件设置段(ComponentAutoSettings)由元数据自动渲染。
        - 未迁移页：回落具名插槽 #layout/#components/#business（+ default 插槽）。
        业务选项始终由页面声明（业务态/「页面记忆」，不进四层配置链路）。
      -->
      <div class="ps-body" :class="{ 'is-scroll-disabled': !bodyScroll }">
        <template v-if="config">
          <SettingsGroup
            v-if="hasLayoutKnobs"
            title="布局"
            hint="预设 / 明暗 / 密度等整页布局设置"
            :level="1"
            :collapsible="collapsibleSections"
            :model-value="sectionOpen('layout')"
            @update:model-value="(open) => setSectionOpen('layout', open)"
          >
            <LayoutSettingsSection
              :knobs="config.knobs"
              :value-of="config.valueOf"
              :source-of="config.sourceOf"
              :layer-values-of="config.layerValuesOf"
              :set="config.setKnob"
            />
          </SettingsGroup>

          <SettingsGroup
            v-if="hasComponentConfig"
            title="组件设置"
            hint="本页开放可调的组件特性（列显隐 / 排序 / 分页等），统一走组件配置层"
            :level="1"
            :collapsible="collapsibleSections"
            :model-value="sectionOpen('components')"
            @update:model-value="(open) => setSectionOpen('components', open)"
          >
            <ComponentAutoSettings
              :page-key="pageKey!"
              :config="config"
              :drawer-business-visible="hasBusinessSlot"
              :component-meta-overrides="componentMetaOverrides"
            />
          </SettingsGroup>

          <SettingsGroup
            v-if="hasBusinessSlot"
            title="业务选项"
            badge="页面记忆"
            :level="1"
            :collapsible="collapsibleSections"
            :model-value="sectionOpen('business')"
            @update:model-value="(open) => setSectionOpen('business', open)"
          >
            <slot name="business" />
          </SettingsGroup>
        </template>

        <template v-else>
          <SettingsGroup v-if="$slots.layout" title="布局" hint="预设 / 明暗 / 密度等整页布局设置" :level="1">
            <slot name="layout" />
          </SettingsGroup>
          <SettingsGroup
            v-if="$slots.components"
            title="组件设置"
            hint="本页开放可调的组件特性（列显隐 / 排序 / 分页等）"
            :level="1"
          >
            <slot name="components" />
          </SettingsGroup>
          <SettingsGroup v-if="hasBusinessSlot" title="业务选项" badge="页面记忆" :level="1">
            <slot name="business" />
          </SettingsGroup>
          <slot />
        </template>
      </div>

      <footer class="ps-footer">
        <el-button class="ps-reset" @click="emit('reset')">恢复默认</el-button>
      </footer>
    </div>
  </PageDrawer>
</template>

<style scoped>
:global(.page-settings-drawer) {
  --el-drawer-bg-color: transparent;
}
/* 淡遮罩：抽屉卡片按内容取高后，下方/周围以压暗背景兜底，避免透出页面表格显得"空/乱"。 */
:global(.el-overlay.ps-settings-modal) {
  background-color: rgba(0, 0, 0, 0.32) !important;
}
:global(.page-settings-drawer .el-drawer) {
  background: transparent;
  box-shadow: none;
}
:global(.page-settings-drawer .el-drawer__header) {
  display: none;
  margin: 0;
  padding: 0;
}
:global(.page-settings-drawer .el-drawer__body) {
  padding: 14px;
  display: flex;
  align-items: stretch;
  min-height: 0;
}
.ps-card {
  width: 100%;
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: var(--page-settings-bg);
  border: 1px solid var(--page-settings-border);
  border-radius: 16px;
  box-shadow: 0 10px 30px var(--page-settings-shadow);
  overflow: hidden;
}
.ps-header {
  flex: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  border-bottom: 1px solid var(--page-settings-divider);
}
.ps-title {
  display: inline-flex;
  align-items: center;
  gap: var(--app-space-2);
  font-size: var(--app-font-size-section-title);
  font-weight: var(--app-font-weight-section);
  color: var(--page-settings-text);
}
.ps-dirty-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--page-settings-accent);
}
.ps-close {
  color: var(--page-settings-text-muted);
}
.ps-close:hover:not(:disabled) {
  border-color: transparent;
  background: var(--page-settings-seg-hover-bg);
  color: var(--page-settings-text);
}
.ps-body {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  padding: 14px 16px;
}
.ps-body.is-scroll-disabled {
  overflow: hidden;
}
/* 三段结构已抽到 SettingsGroup.vue（level 1 卡片 + 折叠 + 比例标题），此处不再重复样式。 */
.ps-footer {
  flex: none;
  padding: 12px 16px 14px;
  border-top: 1px solid var(--page-settings-divider);
}
.ps-reset {
  width: 100%;
}
</style>
