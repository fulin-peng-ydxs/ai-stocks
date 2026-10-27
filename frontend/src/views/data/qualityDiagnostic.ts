import type { QualityIssue } from '@/api/data'
import { formatDateTimeSeconds } from '@/utils/dateTime'
import { businessMessage, enumText } from '@/utils/displayText'
import { intradaySourceLabels, intradayRepairLabels } from './qualityReport'

type RecordValue = Record<string, unknown>
const record = (value: unknown): RecordValue => value !== null && typeof value === 'object'
  && !Array.isArray(value) ? value as RecordValue : {}
const records = (value: unknown): RecordValue[] => Array.isArray(value)
  ? value.filter(item => item !== null && typeof item === 'object' && !Array.isArray(item)) : []
const text = (value: unknown) => typeof value === 'string' && value.trim() ? value : '未记录'
const count = (value: unknown) => typeof value === 'number' && Number.isSafeInteger(value) && value >= 0
  ? value.toLocaleString('zh-CN') : '未记录'
const quantity = (value: unknown, unit: string) => count(value) === '未记录' ? '未记录' : `${count(value)} ${unit}`
const dateTime = (value: unknown) => formatDateTimeSeconds(typeof value === 'string' ? value : null, '未记录')
export interface DiagnosticField { label: string; value: string }

/** 诊断字段只解释已知业务契约；未知值和原文留给技术详情，不猜测零值或来源可用性。 */
export function qualityDiagnostic(row: QualityIssue) {
  let payload: RecordValue = {}
  try { payload = record(JSON.parse(row.detail)) } catch { /* 旧文本仍由业务摘要及原文入口承接。 */ }
  const intraday = row.issue_type.startsWith('intraday_')
  const coverage = intraday ? record(payload.coverage) : {}
  const availability = intraday ? record(payload.availability) : {}
  const diagnostics = intraday ? record(payload.diagnostics) : {}
  const repair = intraday ? record(payload.last_repair) : {}
  const coverageFields: DiagnosticField[] = Object.keys(coverage).length ? [
    { label: '归档分钟', value: quantity(coverage.point_count, '点') },
    { label: '必需分钟覆盖', value: `${count(coverage.covered_count)} / ${count(coverage.required_count)} 点` },
  ] : []
  const ranges = Array.isArray(coverage.missing_ranges)
    ? coverage.missing_ranges.filter((value): value is string => typeof value === 'string' && !!value.trim()) : []
  const missing = Array.isArray(coverage.missing_times)
    ? coverage.missing_times.filter((value): value is string => typeof value === 'string') : null
  if (ranges.length || missing) coverageFields.push({ label: '缺失时段',
    value: ranges.length ? ranges.join('、') : missing!.length ? missing!.join('、') : '无' })
  for (const [key, label] of [['invalid_rows', '非法记录'], ['off_session_rows', '非交易时段记录'], ['duplicate_rows', '重复分钟']]) {
    if (Object.hasOwn(diagnostics, key)) coverageFields.push({ label, value: quantity(diagnostics[key], '条') })
  }
  const observations = records(availability.sources)
  const decisions = records(availability.decisions)
  const providers = [...new Set([...decisions, ...observations].map(item => item.source)
    .filter((value): value is string => typeof value === 'string'))]
  const day = typeof coverage.trade_date === 'string' ? coverage.trade_date : row.trade_date
  const sources = providers.map(source => {
    const observation = observations.find(item => item.source === source) ?? {}
    const decision = decisions.find(item => item.source === source) ?? {}
    const reason = typeof decision.reason === 'string' ? decision.reason
      : observation.outcome === 'error' ? '最近请求失败，需重新核验'
      : observation.outcome === 'empty' ? '最近响应为空，需重新核验' : ''
    return {
      id: source, name: enumText(intradaySourceLabels, source, '未识别来源'),
      decision: decision.request === true ? '可请求核验' : decision.request === false ? '本次跳过' : '未记录',
      reason: businessMessage(reason, observation.outcome === 'error'
        ? '最近请求失败，详细原因见技术详情及关联任务日志' : '详细原因见技术详情及关联任务日志'),
      range: typeof observation.first === 'string' && typeof observation.last === 'string'
        ? `${observation.first} 至 ${observation.last}` : '未记录有效响应范围',
      points: day ? count(record(observation.days)[day]) : '未记录',
      checkedAt: dateTime(observation.checked_at),
    }
  })
  const repairFields: DiagnosticField[] = Object.keys(repair).length ? [
    { label: '修复结果', value: repair.error && !repair.outcome ? '修复未完成'
      : enumText(intradayRepairLabels, repair.outcome, '结果未识别') },
    { label: '复检时间', value: dateTime(repair.checked_at) },
    { label: '修复前归档', value: quantity(repair.before_points, '点') },
    { label: '修复后归档', value: quantity(repair.after_points, '点') },
  ] : []
  return { structured: coverageFields.length > 0 || sources.length > 0 || repairFields.length > 0,
    day: text(day), coverageFields, sources, repairFields,
    availability: enumText({ available: '可尝试补采', needs_verification: '需核验来源',
      unavailable: '当前来源无法覆盖', deferred: '等待源更新或复查' },
      availability.status, '状态未识别'),
    // 分项详情已展开，不重复 availability.reason 中拼接的逐来源长说明。
    summary: businessMessage(payload.base_message ?? payload.message, '请查看覆盖情况及来源核验结果'),
  }
}
