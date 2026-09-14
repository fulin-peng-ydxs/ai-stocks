<script setup lang="ts">
import { computed, ref, useSlots, watch } from 'vue'
import { Close, Expand, Fold } from '@element-plus/icons-vue'
import type { EditableKnob } from '@/layout/schema'
import type { LayoutConfigLayer } from '@/layout/merge'
import { applicableComponentFields, getPageEntry, type SlotConfigMeta } from '@/layout/pageRegistry'
import {
  getComponentFieldDef,
  type ComponentConfigLayer,
  type ComponentConfigSource,
} from '@/layout/componentConfig'
import SettingsGroup from './SettingsGroup.vue'
import ComponentAutoSettings from './ComponentAutoSettings.vue'
import PageDrawer from './PageDrawer.vue'
import LayoutSettingsSection from '@/layout/components/LayoutSettingsSection.vue'
import AppIconButton from './AppIconButton.vue'
import AppStatusNotice from './AppStatusNotice.vue'
import type { PageDrawerSize } from './pageDrawerSize'
import { useDrawerPreferences } from '@/composables/useDrawerPreferences'

/** 抽屉自动渲染所需的配置访问器（即 useRemoteLayoutConfig 的返回子集）。 */
export interface DrawerConfig {
  knobs: EditableKnob[]
  valueOf: (path: string) => unknown
  sourceOf: (path: string) => LayoutConfigLayer
  layerValuesOf?: (path: string) => Partial<Record<LayoutConfigLayer, unknown>>
  setKnob: (path: string, value: unknown) => void
  componentValueOf: (slotId: string, field: string) => unknown
  setComponentKnob: (slotId: string, field: string, value: unknown) => void
  componentSourceOf?: (slotId: string, field: string) => ComponentConfigSource
  componentLayerValuesOf?: (slotId: string, field: string) => Partial<Record<ComponentConfigSource, unknown>>
  componentAllowedLayers?: (kind: string, field: string) => ComponentConfigLayer[] | undefined
}

const props = withDefaults(defineProps<{
  modelValue: boolean
  title?: string
  dirty?: boolean
  /** 传入则自动渲染「布局」+「组件设置」段（pageKey 用于查 registry 的组件元数据）。 */
  pageKey?: string
  config?: DrawerConfig
  businessVisible?: boolean
  /** 运行时只开放指定组件 slot；复用 ComponentAutoSettings 的 slotIds 过滤能力。 */
  componentSlotIds?: string[]
  /** 页面运行态组件值，仅用于“采用当前值”入口，不改变默认值单向投影规则。 */
  componentRuntimeValueOf?: (slotId: string, field: string) => unknown
  componentMetaOverrides?: Record<string, SlotConfigMeta>
}>(), {
  businessVisible: true,
})

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  reset: []
}>()
const slots = useSlots()
const drawerPreferences = useDrawerPreferences()

function usesGlobalPreference(slotId: string, field: string): boolean {
  const slot = props.pageKey
    ? getPageEntry(props.pageKey)?.layout.slots.find((candidate) => candidate.id === slotId)
    : undefined
  return !!slot && getComponentFieldDef(slot.component, field)?.userPersistence === 'global-preference'
}

function userLayerAllowed(slotId: string, field: string): boolean {
  const slot = props.pageKey
    ? getPageEntry(props.pageKey)?.layout.slots.find((candidate) => candidate.id === slotId)
    : undefined
  if (!slot) return false
  const def = getComponentFieldDef(slot.component, field)
  return !!def && (props.config?.componentAllowedLayers?.(slot.component, field) ?? def.layers).includes('user')
}

const activeConfig = computed<DrawerConfig | undefined>(() => {
  if (!props.config) return undefined
  return {
    ...props.config,
    componentValueOf(slotId: string, field: string) {
      if (usesGlobalPreference(slotId, field) && userLayerAllowed(slotId, field) && field === 'size') {
        return drawerPreferences.size.value ?? props.config?.componentValueOf(slotId, field)
      }
      return props.config?.componentValueOf(slotId, field)
    },
    setComponentKnob(slotId: string, field: string, value: unknown) {
      if (usesGlobalPreference(slotId, field) && userLayerAllowed(slotId, field) && field === 'size') {
        drawerPreferences.setSize(value)
        return
      }
      props.config?.setComponentKnob(slotId, field, value)
    },
    componentSourceOf(slotId: string, field: string) {
      if (usesGlobalPreference(slotId, field) && userLayerAllowed(slotId, field) && field === 'size' && drawerPreferences.size.value) return 'user'
      return props.config?.componentSourceOf?.(slotId, field) ?? 'default'
    },
    componentLayerValuesOf(slotId: string, field: string) {
      const values = props.config?.componentLayerValuesOf?.(slotId, field) ?? {}
      if (usesGlobalPreference(slotId, field) && userLayerAllowed(slotId, field) && field === 'size' && drawerPreferences.size.value) {
        return { ...values, user: drawerPreferences.size.value }
      }
      return values
    },
  }
})

const hasLayoutKnobs = computed(() => !!activeConfig.value?.knobs?.length)
const regularComponentSlotIds = computed(() => {
  const entry = props.pageKey ? getPageEntry(props.pageKey) : undefined
  if (!entry) return []
  return entry.layout.slots
    .map((slot) => slot.id)
    .filter((slotId) => !props.componentSlotIds || props.componentSlotIds.includes(slotId))
})

function hasUserComponentConfig(slotIds: string[]): boolean {
  const entry = props.pageKey ? getPageEntry(props.pageKey) : undefined
  if (!entry) return false
  const visible = new Set(slotIds)
  return entry.layout.slots
    .filter((slot) => visible.has(slot.id))
    .some((slot) => applicableComponentFields(entry, slot.id, 'user').some((def) =>
      (activeConfig.value?.componentAllowedLayers?.(slot.component, def.key) ?? def.layers).includes('user'),
    ))
}

const hasComponentConfig = computed(() => hasUserComponentConfig(regularComponentSlotIds.value))
const hasBusinessSlot = computed(() => props.businessVisible !== false && !!slots.business)
const hasBusinessContent = computed(() => hasBusinessSlot.value)

type SectionKey = 'layout' | 'components' | 'business'
const SECTION_KEYS: SectionKey[] = ['layout', 'components', 'business']

const drawerSize = computed<PageDrawerSize>(() => {
  const size = activeConfig.value?.componentValueOf('settings', 'size')
  return size === 'sm' || size === 'lg' ? size : 'md'
})
const bodyScroll = computed(() => props.config?.componentValueOf('settings', 'bodyScroll') !== false)
const drawerPreferenceSyncing = computed(() => props.modelValue && !drawerPreferences.hydrated.value)
const drawerPreferenceFallback = computed(() => props.modelValue && drawerPreferences.failed.value)
const collapsedSections = computed<SectionKey[]>(() => {
  const raw = drawerPreferences.collapsedSections.value
  if (!Array.isArray(raw)) return []
  return raw.filter((v): v is SectionKey => SECTION_KEYS.includes(v as SectionKey))
})
const visibleSectionKeys = computed<SectionKey[]>(() => {
  const active = !!activeConfig.value
  return SECTION_KEYS.filter((key) => {
    if (key === 'layout') return active ? hasLayoutKnobs.value : !!slots.layout
    if (key === 'components') return active ? hasComponentConfig.value : !!slots.components
    return active ? hasBusinessContent.value : hasBusinessSlot.value
  })
})
const runtimeCollapsedSections = ref<SectionKey[]>([])
const runtimeTouched = ref(false)
const allVisibleSectionsCollapsed = computed(() => (
  visibleSectionKeys.value.length > 0
  && visibleSectionKeys.value.every((key) => runtimeCollapsedSections.value.includes(key))
))
const bulkToggleLabel = computed(() => allVisibleSectionsCollapsed.value ? '全部展开' : '全部收起')

watch(
  () => props.modelValue,
  (open) => {
    if (open) {
      runtimeTouched.value = false
      runtimeCollapsedSections.value = [...collapsedSections.value]
    }
  },
  { immediate: true },
)
watch(collapsedSections, (value) => {
  if (props.modelValue && !runtimeTouched.value) runtimeCollapsedSections.value = [...value]
})

function sectionOpen(key: SectionKey): boolean {
  return !runtimeCollapsedSections.value.includes(key)
}

function setSectionOpen(key: SectionKey, open: boolean): void {
  const next = new Set(runtimeCollapsedSections.value)
  if (open) next.delete(key)
  else next.add(key)
  runtimeTouched.value = true
  runtimeCollapsedSections.value = SECTION_KEYS.filter((section) => next.has(section))
  drawerPreferences.setCollapsedSections(runtimeCollapsedSections.value)
}

function toggleAllSections(): void {
  const next = new Set(runtimeCollapsedSections.value)
  if (allVisibleSectionsCollapsed.value) {
    visibleSectionKeys.value.forEach((key) => next.delete(key))
  } else {
    visibleSectionKeys.value.forEach((key) => next.add(key))
  }
  runtimeTouched.value = true
  runtimeCollapsedSections.value = SECTION_KEYS.filter((section) => next.has(section))
  drawerPreferences.setCollapsedSections(runtimeCollapsedSections.value)
}

function handleReset(): void {
  runtimeTouched.value = false
  runtimeCollapsedSections.value = []
  drawerPreferences.reset()
  emit('reset')
}
</script>

<template>
  <PageDrawer
    :model-value="props.modelValue"
    @update:model-value="(value: boolean) => emit('update:modelValue', value)"
    direction="rtl"
    :size="drawerSize"
    class="page-settings-drawer"
    data-testid="page-settings-drawer"
    modal-class="ps-settings-modal"
  >
    <div class="ps-card">
      <header class="ps-header">
        <div class="ps-title">
          <span>{{ props.title || '页面设置' }}</span>
          <span v-if="props.dirty" class="ps-dirty-dot" />
        </div>
        <div class="ps-header-actions">
          <AppIconButton
            v-if="visibleSectionKeys.length"
            class="ps-fold-all"
            :label="bulkToggleLabel"
            size="sm"
            @click="toggleAllSections"
          >
            <el-icon><Expand v-if="allVisibleSectionsCollapsed" /><Fold v-else /></el-icon>
          </AppIconButton>
          <AppIconButton class="ps-close" label="关闭页面设置" size="sm" @click="emit('update:modelValue', false)">
            <el-icon><Close /></el-icon>
          </AppIconButton>
        </div>
      </header>

      <!--
        固定三段（P13）：布局 / 组件设置 / 业务选项，均为可折叠的 SettingsGroup（level 1 卡片）。
        - 传 :config(+:pageKey)：布局段与组件字段由元数据自动渲染；指定组件字段可归入业务选项。
        - 未迁移页：回落具名插槽 #layout/#components/#business（+ default 插槽）。
        业务选项以页面声明为主；归入其中的组件字段仍保持原配置链路和来源展示。
      -->
      <div class="ps-body" :class="{ 'is-scroll-disabled': !bodyScroll }">
        <AppStatusNotice
          v-if="drawerPreferenceSyncing"
          class="ps-sync-state"
          loading
          size="compact"
          title="正在同步抽屉偏好…"
        />
        <AppStatusNotice
          v-else-if="drawerPreferenceFallback"
          class="ps-sync-state"
          tone="warning"
          size="compact"
          title="抽屉偏好暂用本地设置"
          description="远端同步失败，当前使用本地偏好"
        />

        <template v-if="activeConfig">
          <SettingsGroup
            v-if="hasLayoutKnobs"
            title="布局"
            hint="预设 / 明暗 / 密度等整页布局设置"
            :level="1"
            :model-value="sectionOpen('layout')"
            @update:model-value="(open) => setSectionOpen('layout', open)"
          >
            <LayoutSettingsSection
              :knobs="activeConfig.knobs"
              :value-of="activeConfig.valueOf"
              :source-of="activeConfig.sourceOf"
              :layer-values-of="activeConfig.layerValuesOf"
              :set="activeConfig.setKnob"
            />
          </SettingsGroup>

          <SettingsGroup
            v-if="hasComponentConfig"
            title="组件设置"
            hint="本页开放可调的组件特性（列显隐 / 排序 / 分页等），统一走组件配置层"
            :level="1"
            :model-value="sectionOpen('components')"
            @update:model-value="(open) => setSectionOpen('components', open)"
          >
            <ComponentAutoSettings
              :page-key="pageKey!"
              :config="activeConfig"
              :drawer-business-visible="hasBusinessContent"
              :slot-ids="regularComponentSlotIds"
              :component-meta-overrides="componentMetaOverrides"
              :allowed-layers-of="activeConfig.componentAllowedLayers"
              :runtime-value-of="componentRuntimeValueOf"
            />
          </SettingsGroup>

          <SettingsGroup
            v-if="hasBusinessContent"
            title="业务选项"
            :level="1"
            :model-value="sectionOpen('business')"
            @update:model-value="(open) => setSectionOpen('business', open)"
          >
            <slot name="business" />
          </SettingsGroup>
        </template>

        <template v-else>
          <SettingsGroup
            v-if="$slots.layout"
            title="布局"
            hint="预设 / 明暗 / 密度等整页布局设置"
            :level="1"
            :model-value="sectionOpen('layout')"
            @update:model-value="(open) => setSectionOpen('layout', open)"
          >
            <slot name="layout" />
          </SettingsGroup>
          <SettingsGroup
            v-if="$slots.components"
            title="组件设置"
            hint="本页开放可调的组件特性（列显隐 / 排序 / 分页等）"
            :level="1"
            :model-value="sectionOpen('components')"
            @update:model-value="(open) => setSectionOpen('components', open)"
          >
            <slot name="components" />
          </SettingsGroup>
          <SettingsGroup
            v-if="hasBusinessSlot"
            title="业务选项"
            :level="1"
            :model-value="sectionOpen('business')"
            @update:model-value="(open) => setSectionOpen('business', open)"
          >
            <slot name="business" />
          </SettingsGroup>
          <slot />
        </template>
      </div>

      <footer class="ps-footer">
        <el-button class="ps-reset" data-testid="page-settings-reset" @click="handleReset">恢复默认</el-button>
      </footer>
    </div>
  </PageDrawer>
</template>

<style scoped>
:global(.page-settings-drawer) {
  --el-drawer-bg-color: transparent;
}
/* 页面设置沿用抽屉遮光层，明确浮层焦点；抽屉与页面自身底色仍由中性主题表面控制。 */
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
  padding: var(--app-density-overlay-group-gap);
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
  padding: var(--app-density-overlay-padding);
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
.ps-header-actions {
  display: inline-flex;
  align-items: center;
  gap: var(--app-space-1);
}
.ps-fold-all,
.ps-close {
  color: var(--page-settings-text-muted);
}
.ps-fold-all:hover:not(:disabled),
.ps-close:hover:not(:disabled) {
  border-color: transparent;
  background: var(--page-settings-seg-hover-bg);
  color: var(--page-settings-text);
}
.ps-body {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  padding: var(--app-density-overlay-padding);
}
.ps-body.is-scroll-disabled {
  overflow: hidden;
}
.ps-sync-state {
  margin-bottom: var(--app-density-overlay-group-gap);
}
/* 三段结构已抽到 SettingsGroup.vue（level 1 卡片 + 折叠 + 比例标题），此处不再重复样式。 */
.ps-footer {
  flex: none;
  padding: var(--app-density-overlay-group-gap) var(--app-density-overlay-padding)
    var(--app-density-overlay-padding);
  border-top: 1px solid var(--page-settings-divider);
}
.ps-reset {
  width: 100%;
}
</style>
