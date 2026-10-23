import type { IntradayCoverage, Overview } from '@/api/data'
import { formatDateTimeSeconds } from '@/utils/dateTime'
import type { DataMetricInfo } from '@/components/data/DataMetricCard.vue'

export type OverviewAction = 'stocks' | 'intraday-ingest' | 'intraday-quality' | 'st-refresh' | 'board' | 'quality' | 'gaps'
export interface OverviewMetric {
  key: string
  label: string
  value: string
  unit?: string
  summary?: string
  tone?: 'success' | 'warning' | 'danger'
  info: DataMetricInfo
  actionLabel?: string
  action?: OverviewAction
  testId?: string
}
const count = (value?: number | null): string => value == null ? '—' : value.toLocaleString('zh-CN')
const date = (value?: string | null): string => value?.slice(0, 10) || '—'

/** 表格只保留需要行动的覆盖状态；完整分项由同一单元格的统计详情承接。 */
export function intradayCoverageText(coverage: IntradayCoverage): string {
  if (coverage.missing_days) return `缺失 ${count(coverage.missing_days)} 日`
  if (coverage.partial_days) return `部分 ${count(coverage.partial_days)} 日`
  return coverage.complete_days ? `完整 ${count(coverage.complete_days)} 日` : '暂无归档'
}

/** 只组织展示层级；覆盖和质检统计分别保留服务端口径，不在页面重新推导质量结论。 */
export function overviewMetrics(overview: Overview | null): OverviewMetric[] {
  const intraday = overview?.intraday
  const st = overview?.st_status
  const board = overview?.board
  const quality = overview?.quality
  const gaps = overview?.gaps
  const monitored = !!(intraday?.stocks || intraday?.indices)
  const severity = (['high', 'mid', 'low'] as const).find((key) => quality?.by_severity?.[key])
  const latestExpected = (intraday?.latest_expected_stocks ?? 0) + (intraday?.latest_expected_indices ?? 0)
  const latestComplete = ((intraday?.latest_expected_stocks && intraday.latest_complete_stocks == null)
    || (intraday?.latest_expected_indices && intraday.latest_complete_indices == null))
    ? null : (intraday?.latest_complete_stocks ?? 0) + (intraday?.latest_complete_indices ?? 0)
  const latestCoverage = latestExpected
    ? `目标日完整 ${latestComplete == null ? '—' : ((latestComplete / latestExpected) * 100).toLocaleString('zh-CN', { maximumFractionDigits: 1 }) + '%'}`
    : monitored ? '尚无应采目标日' : intraday ? '尚未开始监控' : '尚无统计'
  return [
    {
      key: 'latestTradeDate', label: '最新交易日', value: date(overview?.latest_trade_date),
      info: { kind: 'help', text: '库内日线的最大交易日，用作鲜活度基准；不表示全市场均已更新。' },
    },
    {
      key: 'codes', label: '在市 / 退市', value: `${count(overview?.codes.active)} / ${count(overview?.codes.delisted)}`, unit: '只',
      info: { kind: 'help', text: '在市与退市数量按股票基础资料统计；退市股票的历史数据继续保留。' },
    },
    {
      key: 'barRows', label: '日线总行数', value: count(overview?.bar_rows), unit: '行',
      info: { kind: 'help', text: '全市场已入库的日线记录总数；记录规模不代表日期覆盖或质量达标。' },
    },
    {
      key: 'intraday', label: '分时归档', value: count(intraday?.bar_rows), unit: '行', summary: latestCoverage,
      info: { kind: 'details',
        rows: [
          { label: '目标交易日', value: date(intraday?.target_end) },
          { label: '目标日完整 / 应采', value: `${count(intraday?.latest_complete_stocks)} / ${count(intraday?.latest_expected_stocks)} 只` },
          { label: '监控股票', value: `${count(intraday?.stocks)} 只` },
          { label: '监控指数', value: `${count(intraday?.indices ?? 0)} 个` },
          { label: '指数目标日完整 / 应采', value: `${count(intraday?.latest_complete_indices ?? 0)} / ${count(intraday?.latest_expected_indices ?? 0)} 个` },
          { label: '监控起点', value: date(intraday?.monitoring_start) },
          { label: '最新归档日', value: date(intraday?.archive_end) },
          { label: '累计完整', value: `${count(intraday?.complete_days)} 个标的交易日` },
          { label: '累计部分', value: `${count(intraday?.partial_days)} 个标的交易日` },
          { label: '累计缺失', value: `${count(intraday?.missing_days)} 个标的交易日` },
        ],
        notes: [
          '累计覆盖按全局统一监控起点后的应有交易日统计，排除上市前、退市后及明确停牌日；一个股票的一天计一个标的交易日。',
          '完整表示必需分钟已覆盖，不表示量价对账通过；最新归档日不代表全市场已采齐。',
        ],
      },
      // 未监控时明确提供采集空态入口；覆盖入口本身始终只定位本页逐股表。
      actionLabel: intraday?.indices ? '查看分时问题' : monitored ? '查看逐股覆盖' : intraday ? '去采集分时' : undefined,
      action: intraday?.indices ? 'intraday-quality' : monitored ? 'stocks' : intraday ? 'intraday-ingest' : undefined,
      testId: 'overview-intraday-card',
    },
    {
      key: 'stStatus', label: 'ST 点时事实', value: count(st?.coverage_rate), unit: '%',
      summary: st ? st.ready ? '权威覆盖就绪' : '权威覆盖待补齐' : '尚无统计',
      tone: st?.ready === false ? 'danger' : undefined,
      info: { kind: 'details',
        rows: [
          { label: '权威 / 应有', value: `${count(st?.accurate)} / ${count(st?.expected)}` },
          { label: '事实缺失', value: count(st?.missing) },
          { label: '非权威记录', value: count(st?.approximate) },
          { label: '发布状态', value: ({ refreshing: '刷新中', ready: '就绪', failed: '失败' } as Record<string, string>)[st?.refresh_state?.status || ''] || '未执行' },
          { label: '事实最新日期', value: date(st?.latest_date) },
        ],
        notes: ['权威 ST 逐日事实对日线的覆盖比例。缺失或非权威事实会阻断相关筛选、评分、回测和涨跌停计算。刷新入口进入采集参数页，不直接执行任务。'],
      },
      actionLabel: '刷新 ST 事实', action: 'st-refresh', testId: 'overview-st-status-card',
    },
    {
      key: 'board', label: '板块数据', value: count(board?.board_dict), unit: '板块',
      summary: board ? `台账待处理 ${count(board.open_issues)} 项` : '尚无统计',
      info: { kind: 'details',
        rows: [{ label: '概念板块', value: count(board?.concept_count) }, { label: '行业板块', value: count(board?.industry_count) }, { label: '台账待处理', value: count(board?.open_issues) }],
        notes: ['板块规模和质量台账分别统计；零待处理问题不代表成分、指数和资金流全部采齐。覆盖及鲜活度在板块专区查看。'],
      },
      actionLabel: '查看板块', action: 'board', testId: 'overview-board-card',
    },
    {
      key: 'score', label: '日线四层评分', value: count(quality?.score),
      tone: quality ? quality.score >= 90 ? 'success' : quality.score >= 70 ? 'warning' : 'danger' : undefined,
      info: { kind: 'help', text: '当前在市股票日线四层全部达标的占比，范围为 0～100；分时质量独立统计，不计入此评分。' },
    },
    {
      key: 'quality', label: '未解决质检', value: count(quality?.open), unit: '项',
      summary: quality ? quality.open ? severity
        ? `${{ high: '高危', mid: '中危', low: '低危' }[severity]} ${count(quality.by_severity[severity])} 项`
        : '有待处理问题' : '暂无待处理问题' : '尚无统计',
      tone: quality?.by_severity?.high ? 'danger' : quality?.open ? 'warning' : undefined,
      info: { kind: 'details',
        rows: [
          ...['high', 'mid', 'low'].map((key, index) => ({ label: ['高危', '中危', '低危'][index], value: quality ? `${count(quality.by_severity?.[key] ?? 0)} 项` : '—' })),
          { label: '最近质检', value: formatDateTimeSeconds(overview?.last_scan_at, '尚未质检') },
        ],
        notes: ['未解决质量台账项数，包含独立分时质量；与日线评分、逐股覆盖的统计单位不同。'],
      },
      actionLabel: '处理问题', action: 'quality',
    },
    {
      key: 'gaps', label: '缺口 / 滞后', value: count(gaps?.stocks_with_gap), unit: '只',
      summary: '日线近 90 个交易日', tone: gaps?.stocks_with_gap ? 'warning' : undefined,
      info: { kind: 'details',
        rows: [{ label: '存在缺口 / 滞后', value: `${count(gaps?.stocks_with_gap)} 只` }, { label: '累计缺口 / 滞后', value: `${count(gaps?.gap_days_total)} 个标的交易日` }],
        notes: ['按股票累计日线近 90 个交易日的缺口或滞后，排除明确停牌。台账按全历史缺口和滞后处理，范围与近端指标不同，数量不直接比较。'],
      },
      actionLabel: '查看缺口台账', action: 'gaps',
    },
  ]
}
