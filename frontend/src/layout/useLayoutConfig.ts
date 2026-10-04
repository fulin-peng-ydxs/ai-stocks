/**
 * 布局配置覆盖链路（M3）。
 *
 * 合并优先级：系统代码默认 < 页面配置 < 用户配置。
 * 用户层以 PG 为权威；localStorage 仅作为离线 fallback 与迁移源。
 */
import { computed, reactive, ref, watch } from 'vue'
import type { EditableKnob, PageLayout } from './schema'
import { getLayoutValue } from './path'
import {
  editablePathSet,
  knobMap,
  LAYOUT_CONFIG_SCHEMA_VERSION,
  makeLayoutOverride,
  mergeLayoutConfig,
  type LayoutConfigLayer,
  type LayoutOverride,
  type LayoutOverlayValue,
  type LayoutOverlayValues,
  type MergeLayer,
} from './merge'
import { coerceEditableValue } from './validator'
import {
  coerceComponentValue,
  componentFieldApplicability,
  getComponentFieldDef,
  isComponentConfigPath,
  isLayerAllowed,
  parseComponentConfigPath,
  resolveComponentConfig,
  type ComponentConfigLayerInput,
  type ComponentConfigSource,
  type ComponentFieldValue,
  type ComponentSlotConfigMeta,
} from './componentConfig'

export interface UseLayoutConfigOptions {
  /** 页面级覆盖；初始可为空，运行期由 applyPageConfig 注入后端 layout_page_config。 */
  pageOverride?: LayoutOverride
  /** 页面级覆盖可写路径。缺省沿用 editable 白名单，后续管理员页面可扩展。 */
  pageAllowedPaths?: string[]
  /** 页面 registry 派生的组件实例候选与适用性；提供后页面/用户合并会拒绝不适用字段。 */
  componentMetaBySlot?: Record<string, ComponentSlotConfigMeta>
}

/** applyPageConfig 入参：后端页面覆盖值。 */
export interface PageConfigInput {
  values?: Record<string, unknown>
}

/** 用户层输入：后端 layout_user_config.config.values 同时承载布局旋钮与组件配置路径。 */
export interface UserConfigInput {
  schemaVersion?: number
  values?: Record<string, unknown>
}

export interface UserConfigExport {
  schemaVersion: number
  values: Record<string, unknown>
}

export interface ComponentFieldPolicyInput {
  componentKind: string
  field: string
  allowedLayers: ComponentConfigLayerInput['layer'][]
}

type Overlay = LayoutOverlayValues

export function readStoredOverlay(storageKey: string, knobs: Map<string, EditableKnob>): Overlay {
  const overlay: Overlay = {}
  try {
    const raw = localStorage.getItem(storageKey)
    if (!raw) return overlay
    const parsed = JSON.parse(raw) as Overlay | LayoutOverride
    const values = 'values' in parsed ? parsed.values : parsed
    const schemaVersion = 'values' in parsed ? parsed.schemaVersion : LAYOUT_CONFIG_SCHEMA_VERSION
    if (schemaVersion !== LAYOUT_CONFIG_SCHEMA_VERSION) return overlay
    for (const [path, value] of Object.entries(values)) {
      const knob = knobs.get(path)
      if (!knob) continue
      try {
        overlay[path] = coerceEditableValue(knob, value) as LayoutOverlayValue
      } catch {
        /* 旧值越界：丢弃 */
      }
    }
  } catch {
    /* 损坏数据：忽略 */
  }
  return overlay
}

/** 组件配置覆盖：路径(slots.<id>.config.<field>) -> 值。 */
type ComponentOverlay = Record<string, ComponentFieldValue>

export function isNonLayoutUserPersistencePath(path: string, slotKindById: Map<string, string>): boolean {
  const parsed = parseComponentConfigPath(path)
  if (!parsed) return false
  const kind = slotKindById.get(parsed.slotId)
  return !!kind && getComponentFieldDef(kind as never, parsed.field)?.userPersistence === 'global-preference'
}

/** 读 localStorage 中的用户层组件配置覆盖，逐项按字段定义守门，非法项丢弃。 */
export function readStoredComponentOverlay(storageKey: string, slotKindById: Map<string, string>): ComponentOverlay {
  const overlay: ComponentOverlay = {}
  try {
    const raw = localStorage.getItem(storageKey)
    if (!raw) return overlay
    const parsed = JSON.parse(raw) as { schemaVersion?: number; values?: Record<string, unknown> }
    if (parsed.schemaVersion && parsed.schemaVersion !== LAYOUT_CONFIG_SCHEMA_VERSION) return overlay
    for (const [path, value] of Object.entries(parsed.values ?? {})) {
      // 有专用持久化目标的 user 值不从页面级 localStorage 恢复。
      if (isNonLayoutUserPersistencePath(path, slotKindById)) continue
      const parsedPath = parseComponentConfigPath(path)
      if (!parsedPath) continue
      const kind = slotKindById.get(parsedPath.slotId)
      if (!kind) continue
      const def = getComponentFieldDef(kind as never, parsedPath.field)
      if (!def || !isLayerAllowed(def, 'user')) continue
      try {
        overlay[path] = coerceComponentValue(def, value)
      } catch {
        /* 旧值越界：丢弃 */
      }
    }
  } catch {
    /* 损坏数据：忽略 */
  }
  return overlay
}

export function useLayoutConfig(base: PageLayout, options: UseLayoutConfigOptions = {}) {
  const storageKey = `ai-stocks:layout:${base.pageKey}`
  const componentStorageKey = `ai-stocks:layout-cc:${base.pageKey}`
  const knobs = knobMap(base)
  const editablePaths = editablePathSet(base)
  const pageAllowedPaths = new Set(options.pageAllowedPaths ?? [...editablePaths])
  const slotKindById = new Map(base.slots.map((s) => [s.id, s.component as string]))
  const pageOverlay = reactive<Overlay>({ ...(options.pageOverride?.values ?? {}) })
  const userOverlay = reactive<Overlay>(readStoredOverlay(storageKey, knobs))
  const remoteUserHydrated = ref(false)
  const preHydrationDirtyPaths = reactive(new Set<string>())

  // 组件配置覆盖层（与 L2 布局参数并行的独立通道，路径 slots.<id>.config.<field>）。
  const pageComponentOverlay = reactive<ComponentOverlay>({})
  const userComponentOverlay = reactive<ComponentOverlay>(readStoredComponentOverlay(componentStorageKey, slotKindById))
  const componentFieldPolicies = reactive<Record<string, ComponentConfigLayerInput['layer'][]>>({})

  function componentAllowedLayers(kind: string, field: string): ComponentConfigLayerInput['layer'][] | undefined {
    return componentFieldPolicies[`${kind}.${field}`]
  }

  watch(
    userOverlay,
    () => {
      try {
        localStorage.setItem(storageKey, JSON.stringify(makeLayoutOverride({ ...userOverlay })))
      } catch {
        /* ignore */
      }
    },
    { deep: true },
  )

  watch(
    userComponentOverlay,
    () => {
      try {
        localStorage.setItem(
          componentStorageKey,
          JSON.stringify({ schemaVersion: LAYOUT_CONFIG_SCHEMA_VERSION, values: { ...userComponentOverlay } }),
        )
      } catch {
        /* ignore */
      }
    },
    { deep: true },
  )

  const mergeResult = computed(() => {
    const layers: MergeLayer[] = [
      {
        layer: 'page',
        override: makeLayoutOverride({ ...pageOverlay }, options.pageOverride?.schemaVersion ?? LAYOUT_CONFIG_SCHEMA_VERSION),
        allowedPaths: pageAllowedPaths,
        knobs,
        dropMode: 'whole-layer',
      },
      {
        layer: 'user',
        override: makeLayoutOverride({ ...userOverlay }),
        allowedPaths: editablePaths,
        knobs,
        dropMode: 'item',
      },
    ]
    return mergeLayoutConfig(base, layers)
  })

  /** 合并后的有效布局（交给 LayoutHost）。 */
  const effective = computed<PageLayout>(() => mergeResult.value.layout)
  const sourceMeta = computed(() => mergeResult.value.sourceMeta)
  const dropped = computed(() => mergeResult.value.dropped)

  // 组件配置：slot.config（default） < page < user。视觉预设不再承载组件策略。
  const componentResult = computed(() => {
    const layers: ComponentConfigLayerInput[] = [
      { layer: 'page', overlay: { values: { ...pageComponentOverlay } } },
      { layer: 'user', overlay: { values: { ...userComponentOverlay } } },
    ]
    return resolveComponentConfig(base, layers, {
      metaBySlot: options.componentMetaBySlot,
      allowedLayersOf: (kind, field) => componentAllowedLayers(kind, field),
    })
  })

  /** 某 slot 的有效组件配置（含代码默认 + 各层覆盖）。 */
  function componentConfigOf(slotId: string): Record<string, ComponentFieldValue> {
    return componentResult.value.configBySlot[slotId] ?? {}
  }

  /** 读某 slot 某字段的有效值（供页面/表单回显）。 */
  function componentValueOf(slotId: string, field: string): ComponentFieldValue | undefined {
    return componentResult.value.configBySlot[slotId]?.[field]
  }

  /** 读某 slot 某字段的生效来源层。 */
  function componentSourceOf(slotId: string, field: string): ComponentConfigSource {
    return componentResult.value.source[`slots.${slotId}.config.${field}`] ?? 'default'
  }

  function componentLayerValuesOf(slotId: string, field: string) {
    return componentResult.value.perLayerValues[`slots.${slotId}.config.${field}`] ?? {}
  }

  function markUserPathDirty(path: string): void {
    if (!remoteUserHydrated.value) preHydrationDirtyPaths.add(path)
  }

  function assignComponentOverlay(path: string, value: unknown, target: ComponentOverlay): boolean {
    if (isNonLayoutUserPersistencePath(path, slotKindById)) return false
    const parsedPath = parseComponentConfigPath(path)
    if (!parsedPath) return false
    const kind = slotKindById.get(parsedPath.slotId)
    const def = kind ? getComponentFieldDef(kind as never, parsedPath.field) : undefined
    if (!def || !isLayerAllowed(def, 'user')) return false
    if (options.componentMetaBySlot && !componentFieldApplicability(def, options.componentMetaBySlot[parsedPath.slotId]).applicable) return false
    if (componentAllowedLayers(kind!, parsedPath.field)?.includes('user') === false) return false
    try {
      target[path] = coerceComponentValue(def, value)
      return true
    } catch {
      return false
    }
  }

  /** 改一个用户层组件配置（越权/越界抛错）。 */
  function setComponentKnob(slotId: string, field: string, value: unknown): void {
    const kind = slotKindById.get(slotId)
    const def = kind ? getComponentFieldDef(kind as never, field) : undefined
    if (!def) throw new Error(`未登记的组件配置项: ${slotId}.${field}`)
    if (!isLayerAllowed(def, 'user')) throw new Error(`该字段不允许用户层修改: ${slotId}.${field}`)
    if (options.componentMetaBySlot && !componentFieldApplicability(def, options.componentMetaBySlot[slotId]).applicable) {
      throw new Error(`该字段不适用于当前组件实例: ${slotId}.${field}`)
    }
    if (componentAllowedLayers(kind!, field)?.includes('user') === false) {
      throw new Error(`当前字段策略不允许用户层修改: ${slotId}.${field}`)
    }
    if (def.userPersistence === 'global-preference') {
      throw new Error(`该字段必须通过全局偏好入口修改: ${slotId}.${field}`)
    }
    const path = `slots.${slotId}.config.${field}`
    if (value == null) delete userComponentOverlay[path]
    else userComponentOverlay[path] = coerceComponentValue(def, value)
    markUserPathDirty(path)
  }

  function resetComponentKnob(slotId: string, field: string): void {
    const path = `slots.${slotId}.config.${field}`
    delete userComponentOverlay[path]
    markUserPathDirty(path)
  }

  /** 改一个用户层旋钮（越界/类型不符抛 LayoutConfigError）。 */
  function setKnob(path: string, value: unknown): void {
    const knob = knobs.get(path)
    if (!knob) throw new Error(`未开放编辑的布局项: ${path}`)
    userOverlay[path] = coerceEditableValue(knob, value) as LayoutOverlayValue
    markUserPathDirty(path)
  }

  function resetKnob(path: string): void {
    delete userOverlay[path]
    markUserPathDirty(path)
  }

  function resetLayer(layer: Exclude<LayoutConfigLayer, 'default'>): void {
    const target = layer === 'page' ? pageOverlay : userOverlay
    for (const key of Object.keys(target)) {
      delete target[key]
      if (layer === 'user') markUserPathDirty(key)
    }
  }

  /**
   * 注入后端页面配置（layout_page_config）：替换页面层覆盖。
   * 非法/越权项由 mergeLayoutConfig 在合并时按 allowedPaths + validateLayout 守门丢弃，页面不崩。
   */
  function applyPageConfig(input: PageConfigInput = {}): void {
    for (const key of Object.keys(pageOverlay)) delete pageOverlay[key]
    for (const key of Object.keys(pageComponentOverlay)) delete pageComponentOverlay[key]
    // 后端页面配置的 values 同时含 L2 布局参数与组件配置，按路径分流到对应通道。
    for (const [path, value] of Object.entries(input.values ?? {})) {
      if (isComponentConfigPath(path)) pageComponentOverlay[path] = value as ComponentFieldValue
      else pageOverlay[path] = value as LayoutOverlayValue
    }
  }

  /** 注入后端当前生效字段策略；组件抽屉、页面/用户合并和写入口共同消费。 */
  function applyComponentFieldPolicies(policies: ComponentFieldPolicyInput[]): void {
    for (const key of Object.keys(componentFieldPolicies)) delete componentFieldPolicies[key]
    for (const policy of policies) {
      componentFieldPolicies[`${policy.componentKind}.${policy.field}`] = [...policy.allowedLayers]
    }
  }

  function applyUserConfig(input: UserConfigInput = {}, opts: { preserveDirty?: boolean } = {}): { preservedDirty: boolean } {
    const preserveDirty = opts.preserveDirty !== false
    const values = input.values ?? {}
    let preservedDirty = false

    for (const key of Object.keys(userOverlay)) {
      if (preserveDirty && preHydrationDirtyPaths.has(key)) {
        preservedDirty = true
        continue
      }
      delete userOverlay[key]
    }
    for (const key of Object.keys(userComponentOverlay)) {
      if (preserveDirty && preHydrationDirtyPaths.has(key)) {
        preservedDirty = true
        continue
      }
      delete userComponentOverlay[key]
    }

    for (const [path, value] of Object.entries(values)) {
      if (preserveDirty && preHydrationDirtyPaths.has(path)) {
        preservedDirty = true
        continue
      }
      if (isComponentConfigPath(path)) {
        assignComponentOverlay(path, value, userComponentOverlay)
        continue
      }
      const knob = knobs.get(path)
      if (!knob) continue
      try {
        userOverlay[path] = coerceEditableValue(knob, value) as LayoutOverlayValue
      } catch {
        /* 远端旧值越界：丢弃 */
      }
    }

    remoteUserHydrated.value = true
    preHydrationDirtyPaths.clear()
    return { preservedDirty }
  }

  function exportUserConfig(): UserConfigExport {
    return {
      schemaVersion: LAYOUT_CONFIG_SCHEMA_VERSION,
      values: { ...userOverlay, ...userComponentOverlay },
    }
  }

  function resetAll(): void {
    resetLayer('user')
    for (const key of Object.keys(userComponentOverlay)) {
      delete userComponentOverlay[key]
      markUserPathDirty(key)
    }
  }

  const isDirty = computed(() => Object.keys(userOverlay).length > 0 || Object.keys(userComponentOverlay).length > 0)
  const userConfigValues = computed(() => exportUserConfig().values)

  /** 读某旋钮当前有效值（供表单回显）。 */
  function valueOf(path: string): unknown {
    return getLayoutValue(effective.value, path)
  }

  function sourceOf(path: string): LayoutConfigLayer {
    return sourceMeta.value[path] ?? 'default'
  }

  function layerValuesOf(path: string) {
    return mergeResult.value.perLayerValues[path] ?? {}
  }

  return {
    effective,
    knobs: base.editable,
    setKnob,
    resetKnob,
    resetLayer,
    resetAll,
    applyPageConfig,
    applyComponentFieldPolicies,
    applyUserConfig,
    exportUserConfig,
    remoteUserHydrated,
    userConfigValues,
    isDirty,
    valueOf,
    sourceOf,
    layerValuesOf,
    sourceMeta,
    dropped,
    // 组件配置层
    componentConfigOf,
    componentValueOf,
    componentSourceOf,
    componentLayerValuesOf,
    componentAllowedLayers,
    setComponentKnob,
    resetComponentKnob,
    componentDropped: computed(() => componentResult.value.dropped),
  }
}
