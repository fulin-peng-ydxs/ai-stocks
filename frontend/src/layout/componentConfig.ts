/**
 * 组件特性配置层（P2 / M8-0）——把组件专属配置从"纯校验 shape"升级为
 * "字段元数据 + 分层合并 + 来源追踪"，作为配置中心/页面设置抽屉的唯一字段源。
 *
 * 与 componentSchemas.ts 的关系：componentSchemas 负责"任意 config 对象的结构校验"
 * （宽松、覆盖全部组件种类）；本文件负责"可被 Web 配置的高频字段"的**受控元数据**
 * （label / 控件 / 允许层级 / 取值域 / 默认值 / 是否高频），是产品化配置的单一事实源。
 *
 * 覆盖路径格式（与后端 layout_config 一致）：`slots.<slotId>.config.<field>`。
 * 合并优先级：slot.config（代码默认） < preset < page < user，仅允许各字段声明的层级覆盖。
 */
import type { ComponentKind, PageLayout, SlotSpec } from './schema'

/** 可覆盖层级（不含 default：default 即 slot.config 代码默认）。 */
export type ComponentConfigLayer = 'preset' | 'page' | 'user'
/** 含 default 的来源标记（用于来源追踪展示）。 */
export type ComponentConfigSource = 'default' | ComponentConfigLayer

/** Web 配置控件类型。 */
export type ComponentControl = 'enum' | 'int' | 'number' | 'bool' | 'string' | 'string[]' | 'object'

export type ComponentFieldValue = string | number | boolean | string[] | number[] | Record<string, unknown>

export interface ComponentFieldDef {
  /** 字段名（slot.config 里的键）。 */
  key: string
  /** 配置界面展示名。 */
  label: string
  /** 控件类型，驱动配置表单渲染。 */
  control: ComponentControl
  /** 允许覆盖该字段的层级（从低到高的子集）。 */
  layers: ComponentConfigLayer[]
  /** enum 选项。 */
  options?: (string | number)[]
  /** enum 选项中文名（按 String(value) 取）。 */
  optionLabels?: Record<string, string>
  /** 数值下限。 */
  min?: number
  /** 数值上限。 */
  max?: number
  /** 代码默认值（slot.config 未声明时的兜底，仅用于展示"默认"）。 */
  default?: ComponentFieldValue
  /** 是否高频字段（配置中心默认展示；array/object 等复杂字段通常 false，留待页面侧带列信息编辑）。 */
  highFrequency?: boolean
  /** 简短帮助文案。 */
  help?: string
}

/**
 * 受控组件字段定义。
 *
 * 口径（响应 review）：本表**只登记已被页面真实消费的字段**，不预先铺设"将来可能用"的字段，
 * 避免配置中心暴露不生效的配置项。新增字段时必须同时：页面消费 + 在 pageRegistry.consumedComponentFields
 * 登记 + 后端 COMPONENT_CONFIG_FIELD_RULES 同步。其余结构性 config 仍由 componentSchemas.ts 宽松校验。
 *
 * 注：page 专属枚举/数组字段（defaultSort/hiddenColumns/defaultActive）的取值集合随页面而异，
 * 由各页设置抽屉用页面自带的枚举控件安全编辑（用户层）；配置中心不对其做自由文本编辑（见 ComponentSettingsSection）。
 */
export const COMPONENT_FIELD_DEFS: Partial<Record<ComponentKind, ComponentFieldDef[]>> = {
  'data-table': [
    { key: 'pageSize', label: '默认分页大小', control: 'int', layers: ['preset', 'page', 'user'], min: 10, max: 500, default: 20, highFrequency: true },
    { key: 'defaultSort', label: '默认排序', control: 'string', layers: ['page', 'user'], help: '字段:方向，如 score:desc（取值随页面而异）' },
    { key: 'hiddenColumns', label: '隐藏列', control: 'string[]', layers: ['page', 'user'], help: '列 key 列表（随页面而异）' },
  ],
  tabs: [
    { key: 'defaultActive', label: '默认激活页', control: 'string', layers: ['page', 'user'], help: '激活的 tab name（随页面而异）' },
  ],
  'settings-drawer': [
    {
      key: 'size',
      label: '抽屉尺寸',
      control: 'enum',
      layers: ['preset', 'page', 'user'],
      options: ['sm', 'md', 'lg'],
      optionLabels: { sm: '小', md: '中', lg: '大' },
      default: 'md',
      highFrequency: true,
      help: '控制页面设置抽屉宽度。',
    },
    {
      key: 'bodyScroll',
      label: '内容区滚动',
      control: 'bool',
      layers: ['preset', 'page', 'user'],
      default: true,
      highFrequency: true,
      help: '关闭后抽屉内容区不再独立滚动，仅适合短设置面板。',
    },
    {
      key: 'collapsibleSections',
      label: '允许折叠分组',
      control: 'bool',
      layers: ['preset', 'page'],
      default: true,
      highFrequency: true,
      help: '关闭后页面设置抽屉三段固定展开，不记录个人折叠态。',
    },
    {
      key: 'defaultCollapsed',
      label: '默认折叠段',
      control: 'string[]',
      layers: ['preset', 'page', 'user'],
      options: ['layout', 'components', 'business'],
      optionLabels: { layout: '布局', components: '组件设置', business: '业务选项' },
      default: [],
      highFrequency: true,
      help: '控制页面设置抽屉三段默认折叠；用户点击折叠会写入个人层。',
    },
  ],
}

const FIELD_DEF_INDEX = new Map<string, ComponentFieldDef>()
for (const [kind, defs] of Object.entries(COMPONENT_FIELD_DEFS)) {
  for (const def of defs ?? []) FIELD_DEF_INDEX.set(`${kind}.${def.key}`, def)
}

/** 取某组件种类的全部受控字段定义。 */
export function getComponentFieldDefs(kind: ComponentKind): ComponentFieldDef[] {
  return COMPONENT_FIELD_DEFS[kind] ?? []
}

/** 取某组件某字段定义。 */
export function getComponentFieldDef(kind: ComponentKind, field: string): ComponentFieldDef | undefined {
  return FIELD_DEF_INDEX.get(`${kind}.${field}`)
}

/** 组件配置覆盖路径：slots.<slotId>.config.<field>。 */
export function componentConfigPath(slotId: string, field: string): string {
  return `slots.${slotId}.config.${field}`
}

const COMPONENT_CONFIG_PATH_RE = /^slots\.([^.]+)\.config\.([^.]+)$/

/** 解析组件配置路径；非组件配置路径返回 null。 */
export function parseComponentConfigPath(path: string): { slotId: string; field: string } | null {
  const m = COMPONENT_CONFIG_PATH_RE.exec(path)
  return m ? { slotId: m[1], field: m[2] } : null
}

export function isComponentConfigPath(path: string): boolean {
  return COMPONENT_CONFIG_PATH_RE.test(path)
}

/** 某字段是否允许在指定层覆盖。 */
export function isLayerAllowed(def: ComponentFieldDef, layer: ComponentConfigLayer): boolean {
  return def.layers.includes(layer)
}

export class ComponentConfigError extends Error {}

/** 按字段定义规整取值；类型/取值域非法抛 ComponentConfigError。 */
export function coerceComponentValue(def: ComponentFieldDef, value: unknown): ComponentFieldValue {
  switch (def.control) {
    case 'bool':
      if (typeof value !== 'boolean') throw new ComponentConfigError(`${def.label} 需为布尔值`)
      return value
    case 'int':
    case 'number': {
      const n = typeof value === 'number' ? value : Number(value)
      if (!Number.isFinite(n)) throw new ComponentConfigError(`${def.label} 需为数值`)
      if (def.control === 'int' && !Number.isInteger(n)) throw new ComponentConfigError(`${def.label} 需为整数`)
      if (def.min != null && n < def.min) throw new ComponentConfigError(`${def.label} 不能小于 ${def.min}`)
      if (def.max != null && n > def.max) throw new ComponentConfigError(`${def.label} 不能大于 ${def.max}`)
      return n
    }
    case 'enum':
      if (!def.options?.some((o) => o === value)) throw new ComponentConfigError(`${def.label} 取值非法`)
      return value as string | number
    case 'string':
      if (typeof value !== 'string') throw new ComponentConfigError(`${def.label} 需为字符串`)
      return value
    case 'string[]':
      if (!Array.isArray(value) || !value.every((v) => typeof v === 'string'))
        throw new ComponentConfigError(`${def.label} 需为字符串数组`)
      if (def.options?.length && !value.every((v) => def.options?.some((o) => String(o) === v)))
        throw new ComponentConfigError(`${def.label} 取值非法`)
      return value as string[]
    case 'object':
      if (value == null || typeof value !== 'object' || Array.isArray(value))
        throw new ComponentConfigError(`${def.label} 需为对象`)
      return value as Record<string, unknown>
  }
}

export interface ComponentConfigOverlay {
  /** 路径 -> 值，路径形如 slots.<slotId>.config.<field>。 */
  values: Record<string, unknown>
}

export interface ComponentConfigLayerInput {
  layer: ComponentConfigLayer
  overlay?: ComponentConfigOverlay
}

export interface ResolvedComponentConfig {
  /** 每个 slot 的有效配置（含 slot.config 代码默认 + 各层覆盖）。 */
  configBySlot: Record<string, Record<string, ComponentFieldValue>>
  /** 路径 -> 生效来源层。 */
  source: Record<string, ComponentConfigSource>
  /** 路径 -> 各层取值，用于来源 hover 展示。 */
  perLayerValues: Record<string, Partial<Record<ComponentConfigSource, ComponentFieldValue>>>
  /** 被丢弃的覆盖项（未知组件/字段、越权层级、类型非法）。 */
  dropped: { layer: ComponentConfigLayer; path: string; reason: string }[]
}

/**
 * 合并组件配置：slot.config（default） < preset < page < user。
 * 每个覆盖项都要求 (1) 路径合法 (2) slot 存在 (3) 字段已登记 (4) 该字段允许在该层覆盖 (5) 取值合法，
 * 否则丢弃并记录原因，绝不让非法/越权项污染有效配置。
 */
export function resolveComponentConfig(layout: PageLayout, layers: ComponentConfigLayerInput[]): ResolvedComponentConfig {
  const slotById = new Map<string, SlotSpec>(layout.slots.map((s) => [s.id, s]))
  const configBySlot: Record<string, Record<string, ComponentFieldValue>> = {}
  const source: Record<string, ComponentConfigSource> = {}
  const perLayerValues: Record<string, Partial<Record<ComponentConfigSource, ComponentFieldValue>>> = {}
  const dropped: ResolvedComponentConfig['dropped'] = []

  // default 层：slot.config 中已登记的字段
  for (const slot of layout.slots) {
    for (const def of getComponentFieldDefs(slot.component)) {
      if (def.default === undefined) continue
      const path = componentConfigPath(slot.id, def.key)
      ;(configBySlot[slot.id] ??= {})[def.key] = def.default
      source[path] = 'default'
      ;(perLayerValues[path] ??= {}).default = def.default
    }
    const cfg = slot.config
    if (!cfg) continue
    for (const [field, value] of Object.entries(cfg)) {
      const def = getComponentFieldDef(slot.component, field)
      if (!def) continue // slot.config 可含非受控结构字段，交给 componentSchemas，不在本层产品化
      try {
        const v = coerceComponentValue(def, value)
        ;(configBySlot[slot.id] ??= {})[field] = v
        const path = componentConfigPath(slot.id, field)
        source[path] = 'default'
        ;(perLayerValues[path] ??= {}).default = v
      } catch {
        /* 代码默认非法理应在开发期被 componentSchemas 拦下，这里稳妥跳过 */
      }
    }
  }

  for (const { layer, overlay } of layers) {
    if (!overlay) continue
    for (const [path, raw] of Object.entries(overlay.values)) {
      const parsed = parseComponentConfigPath(path)
      if (!parsed) {
        dropped.push({ layer, path, reason: 'path.invalid' })
        continue
      }
      const slot = slotById.get(parsed.slotId)
      if (!slot) {
        dropped.push({ layer, path, reason: 'slot.notFound' })
        continue
      }
      const def = getComponentFieldDef(slot.component, parsed.field)
      if (!def) {
        dropped.push({ layer, path, reason: 'field.unknown' })
        continue
      }
      if (!isLayerAllowed(def, layer)) {
        dropped.push({ layer, path, reason: 'layer.notAllowed' })
        continue
      }
      try {
        const v = coerceComponentValue(def, raw)
        ;(configBySlot[slot.id] ??= {})[parsed.field] = v
        source[path] = layer
        ;(perLayerValues[path] ??= {})[layer] = v
      } catch {
        dropped.push({ layer, path, reason: 'value.invalid' })
      }
    }
  }

  return { configBySlot, source, perLayerValues, dropped }
}
