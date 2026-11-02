/** 只用于最终展示；返回文本不得参与计算、排序、筛选或存储。 */
export type NumericValue = string | number | null | undefined
export type NumberKind =
  | 'decimal' | 'price' | 'score' | 'ratio' | 'coefficient'
  | 'count' | 'quantity' | 'seconds' | 'milliseconds' | 'parameter'
export interface NumberFormatOptions {
  digits?: number
  grouped?: boolean
  forceSign?: boolean
  empty?: string
  trimZeros?: boolean
}
const rules: Record<NumberKind, { digits: number; grouped?: boolean; trimZeros?: boolean }> = {
  decimal: { digits: 2 }, price: { digits: 2, grouped: true }, score: { digits: 1 },
  ratio: { digits: 2 }, coefficient: { digits: 4 }, count: { digits: 0, grouped: true },
  quantity: { digits: 4, grouped: true, trimZeros: true }, seconds: { digits: 1 },
  milliseconds: { digits: 0 }, parameter: { digits: 0, trimZeros: true },
}

/** 展开科学计数法；精确字符串全程不经过 Number。number 使用其十进制文本。 */
export function decimalText(value: NumericValue, shift = 0): string | null {
  if (value == null || typeof value === 'number' && !Number.isFinite(value)) return null
  const text = String(value).trim()
  const match = /^([+-]?)(\d+)(?:\.(\d*))?(?:[eE]([+-]?\d+))?$/.exec(text)
  if (!match || !Number.isInteger(shift)) return null
  const exponent = Number(match[4] ?? 0) + shift
  // 限制异常输入的展开成本；覆盖 JS 数值范围及数据库 NUMERIC。
  if (!Number.isSafeInteger(exponent) || Math.abs(exponent) > 1000 || text.length > 2000) return null
  const digits = match[2]! + (match[3] ?? '')
  const point = match[2]!.length + exponent
  const whole = (point <= 0 ? '0' : digits.slice(0, point).padEnd(point, '0')).replace(/^0+(?=\d)/, '')
  const fraction = (point < 0 ? '0'.repeat(-point) + digits : digits.slice(point)).replace(/0+$/, '')
  const nonzero = /[1-9]/.test(whole + fraction)
  return `${match[1] === '-' && nonzero ? '-' : ''}${whole}${fraction ? '.' + fraction : ''}`
}

/** 十进制 half-away-from-zero，进位使用整数，避免 1.005 的二进制舍入误差。 */
export function formatNumber(
  value: NumericValue,
  kind: NumberKind = 'decimal',
  options: NumberFormatOptions = {},
): string {
  const digits = options.digits ?? rules[kind].digits
  const grouped = options.grouped ?? rules[kind].grouped
  const trimZeros = options.trimZeros ?? rules[kind].trimZeros
  const { forceSign = false, empty = '—' } = options
  const normalized = decimalText(value)
  if (normalized == null || !Number.isInteger(digits) || digits < 0 || digits > 1000) return empty
  if (kind === 'parameter' && options.digits == null) return normalized
  const negative = normalized.startsWith('-')
  const [whole, fraction = ''] = normalized.replace(/^-/, '').split('.')
  let units = BigInt(whole! + fraction.slice(0, digits).padEnd(digits, '0'))
  if ((fraction[digits] ?? '0') >= '5') units += 1n
  const padded = String(units).padStart(digits + 1, '0')
  let integer = digits ? padded.slice(0, -digits) : padded
  let decimal = digits ? padded.slice(-digits) : ''
  if (trimZeros) decimal = decimal.replace(/0+$/, '')
  if (grouped) integer = integer.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  const sign = units === 0n ? '' : negative ? '-' : forceSign ? '+' : ''
  return `${sign}${integer}${decimal ? '.' + decimal : ''}`
}

/** 方向必须与最终可见精度一致；保留原始值供阈值判断。 */
export function displayDirection(value: NumericValue, digits = 2, shift = 0): -1 | 0 | 1 | null {
  const text = formatNumber(decimalText(value, shift), 'decimal', { digits })
  if (text === '—') return null
  return /^-/.test(text) ? -1 : /[1-9]/.test(text) ? 1 : 0
}

/** 独立摘要自动缩放；同列比较须由列契约固定单位，不能逐行调用自动缩放。 */
export function formatCompactNumber(value: NumericValue, unit: string, options: NumberFormatOptions = {}): string {
  const normalized = decimalText(value)
  if (normalized == null || options.digits != null
    && (!Number.isInteger(options.digits) || options.digits < 0 || options.digits > 1000)) {
    return options.empty ?? '—'
  }
  const length = normalized.replace(/^-/, '').split('.')[0]!.length
  let shift = length > 8 ? 8 : length > 4 ? 4 : 0
  const digits = options.digits ?? 2
  // 舍入达到下一量级时同步升级单位。
  for (const next of [4, 8]) {
    if (shift >= next) continue
    const rounded = formatNumber(decimalText(normalized, -shift), 'decimal', { digits })
    if (BigInt(rounded.replace(/[-.]/g, '')) >= 10n ** BigInt(next - shift + digits)) shift = next
  }
  const text = formatNumber(decimalText(normalized, -shift), 'decimal', {
    grouped: true, ...options, digits,
  })
  return `${text} ${shift === 8 ? '亿' : shift === 4 ? '万' : ''}${unit}`
}

/** 进度条保持原始比例，不让组件内部整数舍入提前宣告完成。 */
export function progressPercent(value: number | null | undefined): number {
  if (value == null || !Number.isFinite(value)) return 0
  return Math.max(0, Math.min(value < 1 ? 99.99 : 100, value * 100))
}

/** 未缩放数量最多四位且去尾零；缩放数量固定两位并保留单位。 */
export function formatCompactQuantity(value: NumericValue, unit: string, empty = '—'): string {
  const normalized = decimalText(value)
  if (normalized == null) return empty
  const length = normalized.replace(/^-/, '').split('.')[0]!.length
  if (length > 4 || BigInt(formatNumber(normalized, 'decimal', { digits: 2 }).replace(/[-.]/g, '')) >= 1000000n) {
    return formatCompactNumber(normalized, unit)
  }
  return `${formatNumber(normalized, 'quantity')} ${unit}`
}

/** 极小非零值的原精度说明；常规值无需额外占用页面空间。 */
export function tinyValueHint(value: NumericValue, unit = '', digits = 2, shift = 0): string | undefined {
  const raw = decimalText(value, shift)
  return raw != null && raw !== '0' && displayDirection(raw, digits) === 0
    ? `原始值 ${raw}${unit}` : undefined
}
