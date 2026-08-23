/**
 * 将普通十进制值转换为定点最小单位。解析基于字符串而非二进制浮点运算，
 * 适合金额上限、额度等只允许固定小数位的比较与求和。
 */
export function decimalToMinorUnits(
  value: string | null | undefined,
  scale = 2,
): bigint | null {
  if (!Number.isInteger(scale) || scale < 0) return null
  if (value === null || value === undefined || value === '') return null
  const normalized = String(value).trim()
  const match = /^([+-]?)(\d+)(?:\.(\d*))?$/.exec(normalized)
  if (!match || (match[3]?.length ?? 0) > scale) return null
  const factor = 10n ** BigInt(scale)
  const fraction = (match[3] ?? '').padEnd(scale, '0') || '0'
  const units = BigInt(match[2]!) * factor + BigInt(fraction)
  return match[1] === '-' ? -units : units
}

/**
 * 判断非负十进制输入是否可由指定精度的 NUMERIC 字段无损承载。
 * 整数位按去除前导零后的有效位数计算，允许用户输入过程中的末尾小数点。
 */
export function isFixedDecimalInput(
  value: string,
  scale = 2,
  integerDigits = 18,
): boolean {
  if (!Number.isInteger(scale) || scale < 0) return false
  if (!Number.isInteger(integerDigits) || integerDigits < 1) return false
  const pattern = scale === 0 ? /^\d+$/ : new RegExp(`^\\d+(?:\\.\\d{0,${scale}})?$`)
  if (!pattern.test(value)) return false
  const integerPart = value.split('.')[0]!.replace(/^0+(?=\d)/, '')
  return integerPart.length <= integerDigits
}

export function formatMinorUnits(value: bigint, scale = 2): string {
  if (!Number.isInteger(scale) || scale < 0) return String(value)
  const negative = value < 0n
  const absolute = negative ? -value : value
  if (scale === 0) return `${negative ? '-' : ''}${absolute}`
  const factor = 10n ** BigInt(scale)
  const whole = absolute / factor
  const fraction = String(absolute % factor).padStart(scale, '0')
  return `${negative ? '-' : ''}${whole}.${fraction}`
}

/** 将两个定点十进制字符串相乘，并按 half-up 归整到目标最小单位。 */
export function multiplyToMinorUnits(
  left: string | null | undefined,
  right: string | null | undefined,
  leftScale = 4,
  rightScale = 4,
  targetScale = 2,
): bigint | null {
  const leftUnits = decimalToMinorUnits(left, leftScale)
  const rightUnits = decimalToMinorUnits(right, rightScale)
  if (leftUnits === null || rightUnits === null) return null
  const sourceScale = leftScale + rightScale
  if (targetScale > sourceScale || targetScale < 0) return null
  const factor = 10n ** BigInt(sourceScale - targetScale)
  const product = leftUnits * rightUnits
  const negative = product < 0n
  const absolute = negative ? -product : product
  const quotient = absolute / factor
  const remainder = absolute % factor
  const rounded = quotient + (remainder * 2n >= factor ? 1n : 0n)
  return negative ? -rounded : rounded
}

/** 对已受数据库精度约束的十进制字符串做分组展示，不经过 JS number。 */
export function formatDecimalString(
  value: string | null | undefined,
  digits = 2,
): string {
  if (value === null || value === undefined || value === '') return '—'
  if (!Number.isInteger(digits) || digits < 0) return value
  const match = /^([+-]?)(\d+)(?:\.(\d*))?$/.exec(value)
  if (!match || (match[3]?.length ?? 0) > digits) return value
  const whole = match[2]!.replace(/^0+(?=\d)/, '').replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  if (digits === 0) return `${match[1]}${whole}`
  return `${match[1]}${whole}.${(match[3] ?? '').padEnd(digits, '0')}`
}
