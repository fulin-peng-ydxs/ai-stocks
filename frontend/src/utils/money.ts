import { formatDecimalString } from '@/utils/fixedDecimal'

export type MoneyValue = string | number | null | undefined

export interface MoneyFormatOptions {
  digits?: number
  empty?: string
  forceSign?: boolean
}

/**
 * 全站金额数值格式化入口。字符串金额不经过 JavaScript number，避免大额定点数失真；
 * number 金额只在既有浮点业务口径内按指定精度归整。
 */
export function formatMoney(
  value: MoneyValue,
  { digits = 2, empty = '—', forceSign = false }: MoneyFormatOptions = {},
): string {
  if (!Number.isInteger(digits) || digits < 0) return empty
  if (value === null || value === undefined || value === '') return empty
  const normalized = typeof value === 'number'
    ? (Number.isFinite(value) ? value.toFixed(digits) : null)
    : value.trim()
  if (!normalized) return empty
  const decimalPattern = digits === 0
    ? /^[+-]?\d+$/
    : new RegExp(`^[+-]?\\d+(?:\\.\\d{0,${digits}})?$`)
  if (!decimalPattern.test(normalized)) return empty
  const grouped = formatDecimalString(normalized, digits)
  return forceSign && !grouped.startsWith('-') && !grouped.startsWith('+') && Number(normalized) > 0
    ? `+${grouped}`
    : grouped
}

/** 金额输入展示函数：只插入三位分隔符，不补零、不改变用户当前小数位。 */
export function formatMoneyInput(value: string): string {
  if (!value) return ''
  const normalized = value.replaceAll(',', '')
  const match = /^([+-]?)(\d+)(\.\d*)?$/.exec(normalized)
  if (!match) return value
  const whole = match[2]!.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  return `${match[1]}${whole}${match[3] ?? ''}`
}

/** 金额输入解析函数：接口与业务状态只保存无分隔符数值。 */
export function parseMoneyInput(value: string): string {
  return value.replaceAll(',', '')
}

/**
 * 大额金额需要以万/亿展示时仍统一格式化数值部分；单位仅负责缩放，不绕过千分位规范。
 */
export function formatCompactMoneyYuan(
  value: number | null | undefined,
  { digits = 2, empty = '—' }: Pick<MoneyFormatOptions, 'digits' | 'empty'> = {},
): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return empty
  const absolute = Math.abs(value)
  if (absolute >= 1e8) return `${formatMoney(value / 1e8, { digits, empty })} 亿`
  if (absolute >= 1e4) return `${formatMoney(value / 1e4, { digits, empty })} 万`
  return `${formatMoney(value, { digits, empty })} 元`
}
