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

/** 仅展示日期，不转换时区；兼容后端日期和 ISO 日期时间两种传输形式。 */
export function formatDateOnly(value: string | null | undefined, fallback = '—'): string {
  return value ? normalizeDateTimeText(value).slice(0, 10) || fallback : fallback
}

/** 仅展示年，用于历史批次简称。 */
export function formatDateYear(value: string | null | undefined, fallback = '—'): string {
  return value ? normalizeDateTimeText(value).slice(0, 4) || fallback : fallback
}

/** 日志及成交候选中的时钟文本；接受完整时间戳或单独的 HH:mm:ss。 */
export function formatClockTime(value: string | null | undefined, fallback = '—'): string {
  if (!value) return fallback
  const text = normalizeDateTimeText(value)
  return (text.includes(' ') ? text.slice(11, 19) : /^\d{2}:\d{2}/.test(text) ? text.slice(0, 8) : '') || fallback
}

/** 分钟级时钟与秒级时钟共享归一化，不改变调度业务时区。 */
export function formatClockMinutes(value: string | null | undefined, fallback = '—'): string {
  const text = formatClockTime(value, '')
  return text ? text.slice(0, 5) : fallback
}
