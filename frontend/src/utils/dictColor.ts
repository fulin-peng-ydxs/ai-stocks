import type { CSSProperties } from 'vue'

interface DictDisplayItem {
  code?: string
  value?: string
  label?: string | null
  color?: string | null
}

export const DICT_COLOR_PRESETS = [
  '#F56C6C',
  '#E6A23C',
  '#409EFF',
  '#67C23A',
  '#909399',
  '#B882FF',
] as const

export function normalizeDictColor(value: string | null | undefined): string {
  const color = String(value ?? '').trim()
  return /^#[0-9a-fA-F]{6}$/.test(color) ? color.toUpperCase() : ''
}

export function dictItemLabel(
  items: DictDisplayItem[],
  code: string | null | undefined,
  fallback: string,
): string {
  if (!code) return fallback
  return items.find((item) => item.code === code)?.label || fallback
}

export function dictItemColor(
  items: DictDisplayItem[],
  code: string | null | undefined,
): string | null | undefined {
  if (!code) return null
  return items.find((item) => (item.code ?? item.value) === code)?.color
}

export function dictTagStyle(color: string | null | undefined): CSSProperties | undefined {
  const normalized = normalizeDictColor(color)
  if (!normalized) return undefined
  return {
    '--el-tag-text-color': normalized,
    '--el-tag-border-color': `color-mix(in srgb, ${normalized} 44%, transparent)`,
    '--el-tag-bg-color': `color-mix(in srgb, ${normalized} 10%, transparent)`,
  } as CSSProperties
}

export function dictTagStyleByCode(
  items: DictDisplayItem[],
  code: string | null | undefined,
): CSSProperties | undefined {
  return dictTagStyle(dictItemColor(items, code))
}

export function dictColorSwatchStyle(color: string | null | undefined): CSSProperties | undefined {
  const normalized = normalizeDictColor(color)
  return normalized ? { backgroundColor: normalized } : undefined
}
