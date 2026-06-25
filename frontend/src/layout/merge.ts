import type { EditableKnob, PageLayout } from './schema'
import { cloneLayout, getLayoutValue, setLayoutValue } from './path'
import { coerceEditableValue, validateLayout } from './validator'

export const LAYOUT_CONFIG_SCHEMA_VERSION = 1

export type LayoutConfigLayer = 'default' | 'preset' | 'page' | 'user'
export type LayoutOverlayValue = string | number | boolean
export type LayoutOverlayValues = Record<string, LayoutOverlayValue>

export interface LayoutOverride {
  schemaVersion: number
  values: LayoutOverlayValues
}

export interface LayoutMergeResult {
  layout: PageLayout
  sourceMeta: Record<string, LayoutConfigLayer>
  perLayerValues: Record<string, Partial<Record<LayoutConfigLayer, LayoutOverlayValue>>>
  dropped: { layer: LayoutConfigLayer; path: string; reason: string }[]
}

export interface MergeLayer {
  layer: Exclude<LayoutConfigLayer, 'default'>
  override?: LayoutOverride
  allowedPaths: Set<string>
  knobs: Map<string, EditableKnob>
  dropMode: 'whole-layer' | 'item'
}

export function makeLayoutOverride(values: LayoutOverlayValues, schemaVersion = LAYOUT_CONFIG_SCHEMA_VERSION): LayoutOverride {
  return { schemaVersion, values }
}

export function editablePathSet(layout: PageLayout): Set<string> {
  return new Set(layout.editable.map((knob) => knob.path))
}

export function knobMap(layout: PageLayout): Map<string, EditableKnob> {
  return new Map(layout.editable.map((knob) => [knob.path, knob]))
}

function isSchemaCompatible(override: LayoutOverride | undefined): boolean {
  return !override || override.schemaVersion === LAYOUT_CONFIG_SCHEMA_VERSION
}

function sanitizeValue(knobs: Map<string, EditableKnob>, path: string, value: LayoutOverlayValue): LayoutOverlayValue {
  const knob = knobs.get(path)
  if (!knob) return value
  return coerceEditableValue(knob, value) as LayoutOverlayValue
}

function applyOne(layout: PageLayout, path: string, value: LayoutOverlayValue): PageLayout {
  const next = cloneLayout(layout)
  setLayoutValue(next, path, value)
  return next
}

function hasErrors(layout: PageLayout): boolean {
  return validateLayout(layout).some((issue) => issue.level === 'error')
}

export function mergeLayoutConfig(base: PageLayout, layers: MergeLayer[]): LayoutMergeResult {
  let current = cloneLayout(base)
  const sourceMeta: Record<string, LayoutConfigLayer> = {}
  const perLayerValues: Record<string, Partial<Record<LayoutConfigLayer, LayoutOverlayValue>>> = {}
  const dropped: LayoutMergeResult['dropped'] = []

  for (const layer of layers) {
    for (const path of layer.allowedPaths) {
      try {
        const value = getLayoutValue(base, path)
        if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
          ;(perLayerValues[path] ??= {}).default = value
        }
      } catch {
        /* 非法路径会在应用层被 dropped 记录，这里只做来源展示兜底。 */
      }
    }
  }

  for (const layer of layers) {
    const override = layer.override
    if (!override || !Object.keys(override.values).length) continue
    if (!isSchemaCompatible(override)) {
      for (const path of Object.keys(override.values)) {
        dropped.push({ layer: layer.layer, path, reason: 'schemaVersion.mismatch' })
      }
      continue
    }

    if (layer.dropMode === 'whole-layer') {
      let candidate = cloneLayout(current)
      const applied: string[] = []
      let invalid = false
      for (const [path, raw] of Object.entries(override.values)) {
        if (!layer.allowedPaths.has(path)) {
          dropped.push({ layer: layer.layer, path, reason: 'path.notAllowed' })
          continue
        }
        try {
          const value = sanitizeValue(layer.knobs, path, raw)
          ;(perLayerValues[path] ??= {})[layer.layer] = value
          setLayoutValue(candidate, path, value)
          applied.push(path)
        } catch {
          dropped.push({ layer: layer.layer, path, reason: 'value.invalid' })
          invalid = true
        }
      }
      if (invalid || hasErrors(candidate)) {
        for (const path of applied) dropped.push({ layer: layer.layer, path, reason: 'layout.invalid' })
        continue
      }
      current = candidate
      for (const path of applied) sourceMeta[path] = layer.layer
      continue
    }

    for (const [path, raw] of Object.entries(override.values)) {
      if (!layer.allowedPaths.has(path)) {
        dropped.push({ layer: layer.layer, path, reason: 'path.notAllowed' })
        continue
      }
      try {
        const value = sanitizeValue(layer.knobs, path, raw)
        ;(perLayerValues[path] ??= {})[layer.layer] = value
        const candidate = applyOne(current, path, value)
        if (hasErrors(candidate)) {
          dropped.push({ layer: layer.layer, path, reason: 'layout.invalid' })
          continue
        }
        current = candidate
        sourceMeta[path] = layer.layer
      } catch {
        dropped.push({ layer: layer.layer, path, reason: 'value.invalid' })
      }
    }
  }

  return { layout: current, sourceMeta, perLayerValues, dropped }
}
