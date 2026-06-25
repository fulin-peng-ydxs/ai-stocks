/**
 * 布局配置覆盖链路（M3）。
 *
 * 合并优先级：系统代码默认 < 预设配置 < 页面配置 < 用户配置。
 * 用户层仍使用 localStorage；预设层来自 useLayoutPreset；页面层为后续后端配置中心预留输入。
 */
import { computed, reactive, ref, watch } from 'vue'
import type { EditableKnob, PageLayout } from './schema'
import { getLayoutValue } from './path'
import { getLayoutPreset } from './presets'
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
import { useLayoutPreset, presetComponentDefaults } from './useLayoutPreset'
import {
  coerceComponentValue,
  getComponentFieldDef,
  isComponentConfigPath,
  isLayerAllowed,
  parseComponentConfigPath,
  resolveComponentConfig,
  type ComponentConfigLayerInput,
  type ComponentConfigSource,
  type ComponentFieldValue,
} from './componentConfig'

export interface UseLayoutConfigOptions {
  /** 页面级覆盖；初始可为空，运行期由 applyPageConfig 注入后端 layout_page_config。 */
  pageOverride?: LayoutOverride
  /** 页面级覆盖可写路径。缺省沿用 editable 白名单，后续管理员页面可扩展。 */
  pageAllowedPaths?: string[]
  /** 测试或特殊页面可关闭预设层。 */
  enablePresetLayer?: boolean
  /** 页面默认预设 key（来自 layout_page_config.preset_key）；决定预设层的密度等默认。 */
  presetKey?: string | null
}

/** applyPageConfig 入参：后端页面配置（预设 key + 覆盖值）。 */
export interface PageConfigInput {
  presetKey?: string | null
  values?: LayoutOverlayValues
}

type Overlay = LayoutOverlayValues

function readStoredOverlay(storageKey: string, knobs: Map<string, EditableKnob>): Overlay {
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

/** 读 localStorage 中的用户层组件配置覆盖，逐项按字段定义守门，非法项丢弃。 */
function readStoredComponentOverlay(storageKey: string, slotKindById: Map<string, string>): ComponentOverlay {
  const overlay: ComponentOverlay = {}
  try {
    const raw = localStorage.getItem(storageKey)
    if (!raw) return overlay
    const parsed = JSON.parse(raw) as { schemaVersion?: number; values?: Record<string, unknown> }
    if (parsed.schemaVersion && parsed.schemaVersion !== LAYOUT_CONFIG_SCHEMA_VERSION) return overlay
    for (const [path, value] of Object.entries(parsed.values ?? {})) {
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
  const { activePreset } = useLayoutPreset()

  // 页面默认预设：来自后端 layout_page_config.preset_key。未配置时回落到全局当前预设（App.vue 用户选择）。
  const pagePresetKey = ref<string | null | undefined>(options.presetKey)
  const effectivePreset = computed(() =>
    pagePresetKey.value ? getLayoutPreset(pagePresetKey.value) : activePreset.value,
  )

  const pageOverlay = reactive<Overlay>({ ...(options.pageOverride?.values ?? {}) })
  const userOverlay = reactive<Overlay>(readStoredOverlay(storageKey, knobs))

  // 组件配置覆盖层（与 L2 布局参数并行的独立通道，路径 slots.<id>.config.<field>）。
  const pageComponentOverlay = reactive<ComponentOverlay>({})
  const userComponentOverlay = reactive<ComponentOverlay>(readStoredComponentOverlay(componentStorageKey, slotKindById))

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

  const presetOverride = computed<LayoutOverride | undefined>(() => {
    if (options.enablePresetLayer === false) return undefined
    const values: LayoutOverlayValues = {}
    if (editablePaths.has('density')) values.density = effectivePreset.value.componentDefaults.density
    return makeLayoutOverride(values)
  })

  const mergeResult = computed(() => {
    const layers: MergeLayer[] = [
      {
        layer: 'preset',
        override: presetOverride.value,
        allowedPaths: editablePaths,
        knobs,
        dropMode: 'whole-layer',
      },
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

  // 组件配置：slot.config（default） < preset < page < user。
  // 预设层：把生效预设的「预设×组件默认」（componentFieldDefaults[kind]）展开到每个该种类 slot（P11）。
  const presetComponentOverlay = computed<ComponentOverlay>(() => {
    if (options.enablePresetLayer === false) return {}
    const cfd = presetComponentDefaults(effectivePreset.value.key)
    const values: ComponentOverlay = {}
    for (const slot of base.slots) {
      const defaults = cfd[slot.component as string]
      if (!defaults) continue
      for (const [field, val] of Object.entries(defaults)) {
        values[`slots.${slot.id}.config.${field}`] = val as ComponentFieldValue
      }
    }
    return values
  })

  const componentResult = computed(() => {
    const layers: ComponentConfigLayerInput[] = [
      { layer: 'preset', overlay: { values: { ...presetComponentOverlay.value } } },
      { layer: 'page', overlay: { values: { ...pageComponentOverlay } } },
      { layer: 'user', overlay: { values: { ...userComponentOverlay } } },
    ]
    return resolveComponentConfig(base, layers)
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

  /** 改一个用户层组件配置（越权/越界抛错）。 */
  function setComponentKnob(slotId: string, field: string, value: unknown): void {
    const kind = slotKindById.get(slotId)
    const def = kind ? getComponentFieldDef(kind as never, field) : undefined
    if (!def) throw new Error(`未登记的组件配置项: ${slotId}.${field}`)
    if (!isLayerAllowed(def, 'user')) throw new Error(`该字段不允许用户层修改: ${slotId}.${field}`)
    userComponentOverlay[`slots.${slotId}.config.${field}`] = coerceComponentValue(def, value)
  }

  function resetComponentKnob(slotId: string, field: string): void {
    delete userComponentOverlay[`slots.${slotId}.config.${field}`]
  }

  /** 改一个用户层旋钮（越界/类型不符抛 LayoutConfigError）。 */
  function setKnob(path: string, value: unknown): void {
    const knob = knobs.get(path)
    if (!knob) throw new Error(`未开放编辑的布局项: ${path}`)
    userOverlay[path] = coerceEditableValue(knob, value) as LayoutOverlayValue
  }

  function resetKnob(path: string): void {
    delete userOverlay[path]
  }

  function resetLayer(layer: Exclude<LayoutConfigLayer, 'default' | 'preset'>): void {
    const target = layer === 'page' ? pageOverlay : userOverlay
    for (const key of Object.keys(target)) delete target[key]
  }

  /**
   * 注入后端页面配置（layout_page_config）：替换页面层覆盖并切换页面默认预设。
   * 非法/越权项由 mergeLayoutConfig 在合并时按 allowedPaths + validateLayout 守门丢弃，页面不崩。
   * 用户层仍走 localStorage（决策：用户配置后端化属后续多用户阶段）。
   */
  function applyPageConfig(input: PageConfigInput = {}): void {
    if (input.presetKey !== undefined) pagePresetKey.value = input.presetKey
    for (const key of Object.keys(pageOverlay)) delete pageOverlay[key]
    for (const key of Object.keys(pageComponentOverlay)) delete pageComponentOverlay[key]
    // 后端页面配置的 values 同时含 L2 布局参数与组件配置，按路径分流到对应通道。
    for (const [path, value] of Object.entries(input.values ?? {})) {
      if (isComponentConfigPath(path)) pageComponentOverlay[path] = value as ComponentFieldValue
      else pageOverlay[path] = value
    }
  }

  function resetAll(): void {
    resetLayer('user')
    for (const key of Object.keys(userComponentOverlay)) delete userComponentOverlay[key]
  }

  const isDirty = computed(() => Object.keys(userOverlay).length > 0 || Object.keys(userComponentOverlay).length > 0)

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
    setComponentKnob,
    resetComponentKnob,
    componentDropped: computed(() => componentResult.value.dropped),
  }
}
