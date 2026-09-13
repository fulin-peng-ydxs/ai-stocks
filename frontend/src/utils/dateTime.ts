function normalizeDateTimeText(value: string): string {
  return value
    .trim()
    .replace('T', ' ')
    .replace(/\.\d+(?=(?:Z|[+-]\d{2}:?\d{2})?$)/, '')
    .replace(/(?:Z|[+-]\d{2}:?\d{2})$/, '')
}

/** 格式化后端日期时间文本到秒；仅规范展示形式，不转换时区。 */
export function formatDateTimeSeconds(
  value: string | null | undefined,
  fallback = '—',
): string {
  if (!value) return fallback
  return normalizeDateTimeText(value).slice(0, 19) || fallback
}

/** 格式化后端日期时间文本到分钟；仅规范展示形式，不转换时区。 */
export function formatDateTimeMinutes(
  value: string | null | undefined,
  fallback = '—',
): string {
  if (!value) return fallback
  return normalizeDateTimeText(value).slice(0, 16) || fallback
}
