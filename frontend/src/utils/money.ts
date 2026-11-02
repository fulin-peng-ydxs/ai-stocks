import { formatCompactNumber, formatNumber } from '@/utils/numberFormat'

export type MoneyValue = string | number | null | undefined

export interface MoneyFormatOptions {
  digits?: number
  empty?: string
  forceSign?: boolean
}

/**
 * 全站金额数值格式化入口。字符串金额不经过 JavaScript number，避免大额定点数失真；
 * number 金额以十进制文本按 half-away-from-zero 舍入。
 */
export function formatMoney(
  value: MoneyValue,
  { digits = 2, empty = '—', forceSign = false }: MoneyFormatOptions = {},
): string {
  return formatNumber(value, 'decimal', { digits, grouped: true, empty, forceSign })
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
  value: MoneyValue,
  { digits = 2, empty = '—', forceSign = false }: MoneyFormatOptions = {},
): string {
  return formatCompactNumber(value, '元', { digits, empty, forceSign })
}
