import { describe, expect, it } from 'vitest'
import type { Overview } from '@/api/data'
import { overviewMetrics, intradayCoverageText } from '../overviewMetrics'

const completeStStatus = {
  expected: 10, present: 10, accurate: 10, approximate: 0, missing: 0,
  coverage_rate: 100, ready: false, first_date: '2026-10-19', latest_date: '2026-10-19',
  updated_at: null, refresh_state: {
    status: 'failed', task_id: 'task-st', target_count: 1, date_start: null, date_end: null,
    last_error: null, updated_at: null,
  },
} satisfies Overview['st_status']

function fixture(overrides: Partial<Overview> = {}): Overview {
  return {
    latest_trade_date: '2026-10-19', codes: { active: 2, delisted: 0 }, bar_rows: 4,
    quality: { score: 100, open: 0, by_severity: {}, by_layer: [] },
    gaps: { stocks_with_gap: 0, gap_days_total: 0, latest_trade_date: '2026-10-19' },
    last_scan_at: null, st_status: undefined as unknown as Overview['st_status'],
    ...overrides,
  }
}

describe('概览信息层级', () => {
  it.each([
    ['failed', false, '刷新失败，尚未发布'],
    ['refreshing', false, '刷新中，尚未发布'],
    ['ready', true, '权威覆盖就绪'],
  ] as const)('ST 覆盖 100%% 时仍独立展示 %s 发布状态', (status, ready, summary) => {
    const lastError = status === 'failed' ? '1 个刷新步骤失败' : null
    const metric = overviewMetrics(fixture({ st_status: {
      ...completeStStatus, ready,
      refresh_state: { ...completeStStatus.refresh_state, status, last_error: lastError },
    } })).find(item => item.key === 'stStatus')!
    expect(metric).toMatchObject({ value: '100.00%', summary, tone: ready ? undefined : 'danger' })
    if (metric.info.kind !== 'details') throw new Error('ST 应提供事实明细')
    expect(metric.info.rows.filter(row => row.label === '刷新失败原因'))
      .toEqual(lastError ? [{ label: '刷新失败原因', value: lastError }] : [])
  })

  it.each([
    ['SQL: SELECT secret FROM private_table', '刷新失败，请查看任务日志中的详细原因'],
    ['查询失败: select secret FROM private_table', '刷新失败，请查看任务日志中的详细原因'],
    ['数据库异常 SQL: SELECT secret FROM private_table', '刷新失败，请查看任务日志中的详细原因'],
    ['HTTPError: 503 for https://secret.test/token', '刷新失败，请查看任务日志中的详细原因'],
    ['来源请求失败 https://secret.test/token', '刷新失败，请查看任务日志中的详细原因'],
    ['Traceback: 数据读取失败', '刷新失败，请查看任务日志中的详细原因'],
    ['读取失败 /Users/private/secret', '刷新失败，请查看任务日志中的详细原因'],
    ['{"error":"来源异常"}', '刷新失败，请查看任务日志中的详细原因'],
    ['Connection reset by peer', '刷新失败，请查看任务日志中的详细原因'],
    ['  数据源尚未提供目标日的逐日 ST 事实  ', '数据源尚未提供目标日的逐日 ST 事实'],
    ['', null],
    [null, null],
  ])('ST 失败原因遵循业务展示边界：%s', (lastError, expected) => {
    const overview = fixture({ st_status: {
      ...completeStStatus,
      refresh_state: { ...completeStStatus.refresh_state, last_error: lastError },
    } })
    const metric = overviewMetrics(overview).find(item => item.key === 'stStatus')!
    if (metric.info.kind !== 'details') throw new Error('ST 应提供事实明细')
    expect(metric.info.rows.filter(row => row.label === '刷新失败原因'))
      .toEqual(expected ? [{ label: '刷新失败原因', value: expected }] : [])
    expect(metric).toMatchObject({ value: '100.00%', summary: '刷新失败，尚未发布', tone: 'danger' })
    // 仅转换展示；来源错误仍保留给日志及技术诊断，不反写或清空接口记录。
    expect(overview.st_status?.refresh_state?.last_error).toBe(lastError)
  })

  it('单纯定义使用问号帮助，有额外事实分项的指标使用信息详情', () => {
    const metrics = overviewMetrics(fixture())
    expect(metrics.filter((item) => item.info.kind === 'help').map((item) => item.key))
      .toEqual(['latestTradeDate', 'codes', 'barRows', 'score'])
    expect(metrics.filter((item) => item.info.kind === 'details').map((item) => item.key))
      .toEqual(['intraday', 'stStatus', 'board', 'quality', 'gaps'])
  })

  it('逐股表只摘要覆盖状态，完整与空归档不会伪装成异常入口', () => {
    const coverage = { complete_days: 8, partial_days: 0, missing_days: 0, monitoring_start: null, target_end: null, archive_end: null }
    expect(intradayCoverageText(coverage)).toBe('完整 8 日')
    coverage.partial_days = 2
    expect(intradayCoverageText(coverage)).toBe('部分 2 日')
    coverage.missing_days = 1
    expect(intradayCoverageText(coverage)).toBe('缺失 1 日')
    expect(intradayCoverageText({ ...coverage, complete_days: 0, partial_days: 0, missing_days: 0 })).toBe('暂无归档')
  })
  it('只常驻目标日覆盖，累计覆盖与归档日期保留在详情', () => {
    const intraday = {
      stocks: 2, bar_rows: 720, monitoring_start: '2026-10-16', target_end: '2026-10-19',
      archive_end: '2026-10-19', complete_days: 3, partial_days: 1, missing_days: 0,
      latest_complete_stocks: 1, latest_expected_stocks: 2,
    }
    const metric = overviewMetrics(fixture({ intraday })).find((item) => item.key === 'intraday')!
    expect(metric.summary).toBe('目标日完整 50.00%')
    expect(metric.info.kind).toBe('details')
    if (metric.info.kind !== 'details') throw new Error('分时应提供事实明细')
    expect(metric.info.rows).toContainEqual({ label: '目标日完整 / 应采', value: '1 / 2 只' })
    expect(metric.info.rows).toContainEqual({ label: '累计缺失', value: '0 个标的交易日' })
    expect(metric.info.rows).toContainEqual({ label: '监控起点', value: '2026-10-16' })
    expect(metric.action).toBe('stocks')
    intraday.missing_days = 4
    expect(overviewMetrics(fixture({ intraday })).find((item) => item.key === 'intraday')?.action).toBe('stocks')
  })

  it('区别未知、未监控、没有应采日期与真实零值', () => {
    const get = (ov: Overview | null) => overviewMetrics(ov).find((item) => item.key === 'intraday')!
    expect(get(null)).toMatchObject({ value: '—', summary: '尚无统计', action: undefined })
    const intraday = { stocks: 0, bar_rows: 0, monitoring_start: null, target_end: null, archive_end: null, complete_days: 0, partial_days: 0, missing_days: 0 }
    expect(get(fixture({ intraday }))).toMatchObject({ value: '0', summary: '尚未开始监控', action: 'intraday-ingest' })
    intraday.stocks = 1
    expect(get(fixture({ intraday }))).toMatchObject({ summary: '尚无应采目标日', action: 'stocks' })
  })

  it('按最高现存严重程度摘要，不在高危为零时掩盖中危问题', () => {
    const metrics = overviewMetrics(fixture({ quality: { score: 100, open: 7, by_severity: { high: 0, mid: 6, low: 1 }, by_layer: [] } }))
    expect(metrics.find((item) => item.key === 'quality')).toMatchObject({ summary: '中危 6 项', tone: 'warning' })
    expect(metrics.find((item) => item.key === 'score')).toMatchObject({ value: '100.0', tone: 'success' })
  })
  it('只有指数时完整率与处理入口仍有效，不跳转空的逐股表', () => {
    const intraday = { stocks: 0, indices: 6, monitoring_start: '2026-10-08', target_end: '2026-10-22',
      archive_end: '2026-10-22', complete_days: 66, partial_days: 0, missing_days: 0,
      latest_expected_stocks: 0, latest_complete_stocks: 0,
      latest_expected_indices: 6, latest_complete_indices: 6 }
    expect(overviewMetrics(fixture({ intraday })).find(m => m.key === 'intraday'))
      .toMatchObject({ summary: '目标日完整 100.00%', action: 'intraday-quality', actionLabel: '查看分时问题' })
  })
})

it('完成性覆盖从原始分子分母展示，不能被后端预舍入的100掩盖缺口', () => {
  const metric = overviewMetrics(fixture({ st_status: {
    expected: 1_000_000, present: 999_999, accurate: 999_999, coverage_rate: 100,
    updated_at: null, refresh_state: null,
    ready: false, missing: 1, approximate: 0, latest_date: '2026-10-30', first_date: null,
  } })).find(item => item.key === 'stStatus')!
  expect(metric.value).toBe('>99.99%')
  expect(metric.summary).toBe('权威覆盖待补齐')
  expect(metric.tone).toBe('danger')
})
