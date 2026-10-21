/** 业务标签仅转换展示值，调用方仍使用原始 key 完成筛选、定位和提交。 */
export function enumText(
  labels: Readonly<Record<string, string>>, value: unknown, fallback = '未识别',
): string {
  if (value === null || value === undefined || value === '') return '—'
  const label = typeof value === 'string' && Object.hasOwn(labels, value) ? labels[value] : null
  return typeof label === 'string' && label.trim() ? label : fallback
}

/** 普通业务反馈不承载原始对象、异常或查询；技术详情和原始日志不经过此入口。 */
export function businessMessage(value: unknown, fallback: string): string {
  if (typeof value !== 'string') return fallback
  const text = value.trim()
  if (!text || !/[\u3400-\u9fff]/u.test(text) || /^(?:\{|\[)/.test(text)
    || /https?:\/\/|\/(?:Users|home|var|private|tmp|opt)\/|\bTraceback\b|\b\w*(?:Error|Exception)\b|\bSQL\s*:|\b(?:SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s/i.test(text)) {
    return fallback
  }
  return text
}
