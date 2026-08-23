/**
 * 将普通十进制值转换为定点最小单位。解析基于字符串而非二进制浮点运算，
 * 适合金额上限、额度等只允许固定小数位的比较与求和。
 */
export function decimalToMinorUnits(
  value: string | number | null | undefined,
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
