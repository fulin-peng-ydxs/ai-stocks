import type { CheckupCheck, CheckupIssueItem, QualityIssue } from '@/api/data'
import type { AdaptiveColumnRole } from '@/components/table/adaptiveColumnWidth'

export const checkupIssueLabels = {
  open: '待处理', fixing: '修复中', ignored: '已忽略', unrecorded: '未入账',
} as const

interface CheckupDetailColumn { key: string; label: string; role: AdaptiveColumnRole }
export interface CheckupDetailGroup {
  label: string
  total: number
  context?: string
  columns: CheckupDetailColumn[]
  rows: { id: string; values: Record<string, string>; issue?: CheckupIssueItem }[]
}

function evidenceColumnRole(key: string): AdaptiveColumnRole {
  if (key === 'code' || key.endsWith('_code')) return 'code'
  if (key.endsWith('date') || ['检查日', '下一开市日', '最远开市日'].includes(key)) return 'date'
  if (key.endsWith('_at')) return 'datetime'
  if (['status', 'quality', 'projected_is_st', 'fact_is_st'].includes(key)
    || key.startsWith('is_') || key.startsWith('has_') || key.endsWith('_fallback')) return 'status'
  if (['open', 'high', 'low', 'close', 'pre_close', 'volume', 'amount', 'float_mv', 'total_mv',
    'score', 'corr_20', 'corr_60', 'sample_20', 'sample_60', 'turnover_rate', 'total_share',
    'price_limit_pct', 'adj_factor', 'adj_factor_clean', 'net_inflow', 'attempt_count'].includes(key)) return 'number'
  return 'text'
}

/** 板块处置明细与 SQL 样例统一为行列模型，布局只在同一表格入口维护。 */
export function checkupDetailGroups(check: CheckupCheck): CheckupDetailGroup[] {
  const groups: CheckupDetailGroup[] = []
  if (check.items?.length) {
    const dates = [...new Set(check.items.map(item => item.target_date))]
    const indexOnly = check.items.every(item => item.issue_type === 'board_index_gap')
    const fundOnly = check.items.every(item => item.issue_type === 'board_fund_missing')
    const columns: CheckupDetailColumn[] = [
      { key: 'object', label: '板块 / 代码', role: 'entity' },
      { key: 'status', label: '状态', role: 'status' },
      { key: 'gap', label: indexOnly ? '最近指数' : fundOnly ? '缺失周期' : '覆盖缺口', role: indexOnly ? 'date' : 'description' },
    ]
    if (dates.length > 1) columns.push({ key: 'target_date', label: '基准日', role: 'date' })
    groups.push({
      label: '对象明细', total: check.items.length,
      context: dates.length === 1 ? `基准日 ${dates[0]}` : undefined,
      columns,
      rows: orderedCheckupItems(check.items).map((item, index) => ({
        id: String(index), issue: item,
        values: {
          object: `${item.name} ${item.code}`, status: checkupIssueLabels[item.status],
          gap: (item.issue_type === 'board_index_gap'
            ? `${indexOnly ? '' : '最近指数：'}${item.latest_date || '尚无数据'}`
            : `${fundOnly ? '' : '缺失周期：'}${item.missing_periods.join('、')}`)
            + (item.status === 'unrecorded' ? '；先运行数据质检生成台账' : ''),
          target_date: item.target_date,
        },
      })),
    })
  }
  for (const evidence of check.evidence || []) {
    groups.push({
      label: evidence.label, total: evidence.total,
      columns: evidence.columns.map(column => ({ ...column, role: evidenceColumnRole(column.key) })),
      rows: evidence.rows.map((values, index) => ({ id: String(index), values })),
    })
  }
  return groups
}

export function orderedCheckupItems(items: CheckupIssueItem[]) {
  return [...items].sort((a, b) => Number(a.status === 'ignored') - Number(b.status === 'ignored'))
}

/** 显式选择已办状态时应能查看，不能被“隐藏已办”偏好再次过滤。 */
export function visibleQualityRows(rows: QualityIssue[], hideDone: boolean, statuses: string[]) {
  return hideDone ? rows.filter(row => !['ignored', 'resolved'].includes(row.status)
    || statuses.includes(row.status)) : rows
}

/** 下钻清除不相关的筛选，避免严重度或默认待办状态隐藏目标。 */
export function checkupIssueFilters(item: CheckupIssueItem) {
  return {
    code: item.code,
    issue_type: [item.issue_type],
    severity: [] as string[],
    status: item.status === 'unrecorded' ? [] : [item.status],
  }
}


/** 质量列表统一承接结构化诊断；保留旧文本，样例有界，不把接口 JSON 直接展示给用户。 */
export function qualityDetailText(detail: string): string {
  try {
    const payload = JSON.parse(detail)
    const message = payload?.message ?? payload?.reason
    if (typeof message !== 'string' || !message) return detail
    const collection = payload.last_collection
    if (!collection) return message
    const samples: string[] = []
    for (const group of Object.values(collection.diagnostics?.remaining ?? {}) as any[]) {
      for (const row of [...(group.evidence ?? []), ...(group.exchange_evidence ?? [])]) {
        let evidence = ''
        if (row.valuation_close != null) {
          evidence = `${row.trade_date}：本地收盘 ${row.raw_close}，市值源收盘 ${row.valuation_close}`
        } else if (row.exchange_total != null) {
          evidence = `${row.trade_date}：统计总股本 ${row.exchange_total}，已存流通股本 ${row.stored_float}，统计精度 ${row.precision_shares} 股`
        } else if (row.available_date) {
          evidence = `${row.trade_date}：生效 ${row.effective_date}，披露 ${row.available_date}`
        }
        if (evidence && !samples.includes(evidence) && samples.length < 3) samples.push(evidence)
      }
    }
    const errors = collection.diagnostics?.errors
    return [message, `最近核验范围：${String(collection.date_start).slice(0, 10)}~${String(collection.date_end).slice(0, 10)}`,
      ...samples, ...(Array.isArray(errors) && errors.length ? ['来源请求失败，详见关联采集任务日志'] : [])].join('；')
  } catch {
    return detail
  }
}
