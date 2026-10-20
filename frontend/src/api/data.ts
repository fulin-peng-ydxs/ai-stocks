// 数据管理 API（对应 backend/api/data_admin.py + data_tasks.py + stocks.py 的 /data/*）
import http, { type AppRequestConfig } from './client'
import { STOCK_INGEST_RECIPE_LABEL } from '@/utils/stockIngest'

// ── 四层质量模型（M2.9 DM-D15）──
export interface QualityLayer {
  layer: 'L1' | 'L2' | 'L3' | 'L4'
  name_cn: string
  desc: string
  pass_stocks: number
  total: number
  pass_rate: number
  issues: number
}

// ── 概览（FR-DM-1 + M2.9 分层质量评分）──
export interface IntradayCoverage {
  monitoring_start: string | null
  target_end: string | null
  archive_end: string | null
  complete_days: number
  partial_days: number
  missing_days: number
  stocks?: number
  expected_days?: number
}
export interface Overview {
  intraday?: IntradayCoverage
  latest_trade_date: string | null
  codes: { active: number; delisted: number }
  bar_rows: number
  st_status: {
    expected: number; present: number; accurate: number; approximate: number; missing: number
    coverage_rate: number; ready: boolean; first_date: string | null; latest_date: string | null
    updated_at: string | null
    refresh_state: null | {
      status: 'refreshing' | 'ready' | 'failed'; task_id: string | null; target_count: number
      date_start: string | null; date_end: string | null; last_error: string | null; updated_at: string | null
    }
  }
  board?: {
    board_dict: number; board_member: number; board_bar: number; board_fund_flow: number
    concept_count: number; industry_count: number
    member_target: number; member_ready: number; bar_target: number; bar_ready: number
    fund_target: number; fund_ready: number
    latest_bar_date: string | null; latest_fund_date: string | null
    open_issues: number; issues_by_type: Record<string, number>
    last_update: { table_name: string; status: string; detail: string | null; updated_at: string } | null
  }
  quality: { open: number; by_severity: Record<string, number>; score: number; by_layer: QualityLayer[] }
  gaps: { stocks_with_gap: number; gap_days_total: number; latest_trade_date: string | null }
  last_scan_at: string | null
}
export function getOverview(): Promise<Overview> {
  return http.get('/data/overview')
}


export type CatalogDatabase = 'duckdb' | 'postgres'
export type CatalogLifecycle = 'active' | 'legacy_readonly' | 'unregistered'
export type CatalogCountMode = 'estimated' | 'exact' | 'unavailable'
export type CatalogMetadataSource = 'explicit' | 'database_comment' | 'glossary' | 'generated' | 'fallback'
export interface CatalogFreshnessPolicy {
  mode: 'not_applicable' | 'direct' | 'snapshot' | 'snapshot_child'
  column: string | null
  baseline: string | null
  comparison: 'equal' | 'not_before' | null
}
export interface CatalogQualityPolicy {
  mode: 'not_applicable' | 'issue_types' | 'all_issues' | 'pending_outbox'
  issue_types: string[]
  status_column: string | null
  pending_value: string | null
}
export interface CatalogField {
  name: string
  type: string
  name_cn: string
  desc: string
  nullable: boolean
  default: string | null
  primary_key: boolean
  references: string | null
  name_source: CatalogMetadataSource
  description_source: CatalogMetadataSource
  metadata_complete: boolean
}
export interface CatalogTable {
  key: string
  database: CatalogDatabase
  schema: 'main' | 'public'
  table: string
  name_cn: string
  category: string
  purpose: string
  lifecycle: CatalogLifecycle
  source_of_truth: CatalogDatabase
  metadata_complete: boolean
  metadata_issues: string[]
  ownership_scope: string
  data_source: string
  freshness_policy: CatalogFreshnessPolicy | null
  quality_policy: CatalogQualityPolicy | null
  row_count: number | null
  row_count_mode: CatalogCountMode
  rows: number | null
  storage_bytes: number | null
  latest_time: string | null
  fresh: boolean | null
  fields: CatalogField[]
  relations: string[]
  open_issues: number | null
  measured_at: string | null
}
export interface CatalogDatabaseSummary {
  connected: boolean
  schema: 'main' | 'public'
  database_name: string | null
  active_tables: number
  legacy_tables: number
  unregistered_tables: number
  database_size_bytes: number | null
}
export interface CatalogResponse {
  summary: Partial<Record<CatalogDatabase, CatalogDatabaseSummary>>
  tables: CatalogTable[]
}
export interface CatalogQuery {
  database?: 'all' | CatalogDatabase
  include_legacy?: boolean
  table?: string
  count_mode?: 'estimated' | 'exact'
}
export function getCatalog(params?: CatalogQuery): Promise<CatalogResponse> {
  return http.get('/data/catalog', { params })
}

export interface Dimension {
  dimension: string
  name_cn: string
  status: 'collected' | 'planned' | 'partial'
  source: string
  tables: string[]
  descr: string
}
export function getDimensions(): Promise<{ dimensions: Dimension[] }> {
  return http.get('/data/dimensions')
}

export interface StockQualityLayer {
  name_cn: string
  ok: boolean
  issues?: number
  breakdown?: Array<{ issue_type: string; count: number }>
  mv_detail?: string
  mv_gap_days?: number
  mv_gap_lo?: string | null
  mv_gap_hi?: string | null
  capital_issues?: number
  capital_detail?: string
  mv_invalid_days?: number
  mv_invalid_lo?: string | null
  mv_invalid_hi?: string | null
  mv_invalid_detail?: string
  gap_days?: number
  gap_lo?: string | null
  gap_hi?: string | null
  history_gap_days?: number
  stale_days?: number
  stale_lo?: string | null
  is_fresh?: boolean
}
export interface StockQualityRow {
  intraday?: IntradayCoverage | null
  code: string
  name: string
  latest_date: string | null
  is_fresh: boolean
  total_mv_ok: boolean
  gap_days: number
  open_issues: number
  layers: Record<'L1' | 'L2' | 'L3' | 'L4', StockQualityLayer>
}
export interface StockQuality {
  total: number
  page: number
  size: number
  latest_trade_date: string | null
  list: StockQualityRow[]
}
export function getStockQuality(
  params?: { codes?: string; keyword?: string; page?: number; size?: number },
): Promise<StockQuality> {
  return http.get('/data/stock-quality', { params })
}

// 板块搜索（采集页「指定板块」下拉用）：板块代码/名称模糊匹配
export interface BoardSearchItem { code: string; name: string; board_type: string }
export function searchBoards(
  params?: { keyword?: string; board_type?: string; size?: number },
): Promise<{ list: BoardSearchItem[]; total: number }> {
  return http.get('/data/boards', { params })
}

// ── 数据状态 / 采集日志（FR-DM-6）──
export interface UpdateLog {
  table_name: string
  source: string
  status: string
  row_count: number
  date_start: string | null
  date_end: string | null
  detail: string | null
  updated_at: string
}
export interface DataStatus {
  latest_trade_date: string
  distinct_codes: number
  bar_rows: number
  // 当前活跃质量问题：status in ('open', 'fixing')，与质量页默认筛选一致。
  quality_issues: number
  recent_updates: UpdateLog[]
}
export function getDataStatus(): Promise<DataStatus> {
  return http.get('/data/status')
}

// ── 质检与修复（FR-DM-4）──
export type QualityIgnoreScope = 'occurrence' | 'object'

export interface QualityIssue {
  id: number
  code: string
  name: string
  trade_date: string | null
  issue_type: string
  severity: 'high' | 'mid' | 'low'
  status: 'open' | 'fixing' | 'resolved' | 'ignored'
  detail: string
  detected_at: string | null
  resolved_at: string | null
  ignore_scope: QualityIgnoreScope | null
  ignore_active: boolean
}
export interface QualitySummaryItem { issue_type: string; n: number }
export interface DataQuality {
  summary: QualitySummaryItem[]
  total: number
  page: number
  size: number
  list: QualityIssue[]
}
export function getDataQuality(params?: {
  issue_type?: string
  severity?: string
  status?: string
  code?: string
  page?: number
  size?: number
  sort_by?: string
  sort_order?: 'asc' | 'desc'
}): Promise<DataQuality> {
  return http.get('/data/quality', { params })
}
export function fixQualityIssue(issueId: number): Promise<{ task_id: string }> {
  return http.post(`/data/quality/${issueId}/fix`)
}
export function fixQualityBatch(issueIds: number[]): Promise<{ task_id: string }> {
  return http.post('/data/quality/fix-batch', { issue_ids: issueIds })
}
export function ignoreQualityIssue(issueId: number, scope: QualityIgnoreScope):
  Promise<{ id: number; status: string; ignore_scope: QualityIgnoreScope }> {
  return http.post(`/data/quality/${issueId}/ignore`, { scope })
}
export function restoreQualityMonitoring(issueId: number):
  Promise<{ id: number; status: string; ignore_active: boolean }> {
  return http.post(`/data/quality/${issueId}/restore-monitoring`)
}
// 手动复位「修复中」→「未处理」：绑定的修复任务已失败/中断/卡死时解套
export function resetQualityIssue(issueId: number): Promise<{ id: number; status: string }> {
  return http.post(`/data/quality/${issueId}/reset`)
}
// 标记退市：人工指定退市日，解决该股缺口/滞后（应对数据源退市识别不准）
export function getDelistingInfo(issueId: number): Promise<{ code: string; list_date: string | null; delist_date: string | null; delist_date_manual: boolean; delist_date_reported: string | null; last_bar_date: string | null }> {
  return http.get(`/data/quality/${issueId}/delisting`)
}
export function markDelisted(issueId: number, delistDate: string | null, reason: string):
  Promise<{ task_id: string }> {
  return http.post(`/data/quality/${issueId}/mark-delisted`, { delist_date: delistDate, reason })
}
export function recoverQualityBatch(
  // issue_type/severity 支持多值（数组，后端按 IN 过滤）
  filter: { issue_type?: string[]; severity?: string[]; code?: string },
): Promise<{ task_id: string; count: number }> {
  return http.post('/data/quality/recover-batch', filter)
}
export function ignoreQualityBatch(
  filter: { issue_type?: string[]; severity?: string[]; code?: string },
  scope: QualityIgnoreScope,
): Promise<{ count: number; status: 'ignored'; ignore_scope: QualityIgnoreScope }> {
  return http.post('/data/quality/ignore-batch', { ...filter, scope })
}

// ── 定时任务（调度系统重构）──
export type FreqType = 'daily' | 'weekly' | 'monthly' | 'cron'
export type TriggerMode = 'time' | 'dependency'
export type TriggerCondition = 'success' | 'failure' | 'completion'
export type DelayUnit = 'second' | 'minute' | 'hour'
export interface DelayConfig { value: number; unit: DelayUnit }
export interface RetryConfig {
  enabled: boolean
  condition: TriggerCondition
  delay: DelayConfig
  max_retries: number
}
export interface FreqConfig {
  time?: string          // 'HH:MM'（daily/weekly/monthly）
  weekdays?: number[]    // 1..7（weekly）
  day?: number           // 1..28（monthly）
  cron?: string          // cron 表达式（cron）
}
export interface ScheduledJob {
  id: string
  name: string
  task_type: TaskType
  params: Record<string, any>
  freq_type: FreqType | null
  freq_config: FreqConfig
  trigger_mode: TriggerMode
  dependency_job_id: string | null
  dependency_job_name?: string | null
  dependency_condition: TriggerCondition | null
  dependency_delay: DelayConfig
  retry_config: RetryConfig
  trading_day_only: boolean
  enabled: boolean
  last_run_at: string | null
  last_task_id: string | null
  created_at: string
  updated_at: string
  freq_text: string
  trigger_text: string
  waiting_trigger_count: number
  next_dependency_run_at?: string | null
  next_run_time: string | null
}
export interface ScheduledJobInput {
  name: string
  task_type: TaskType
  params?: Record<string, unknown>
  freq_type?: FreqType | null
  freq_config: FreqConfig
  trigger_mode: TriggerMode
  dependency_job_id?: string | null
  dependency_condition?: TriggerCondition | null
  dependency_delay: DelayConfig
  retry_config: RetryConfig
  trading_day_only: boolean
  enabled: boolean
}
export interface ScheduleListQuery {
  page: number
  size: number
  sort_by: 'name' | 'freq'
  sort_order: 'asc' | 'desc'
}
export interface ScheduledJobOption {
  id: string
  name: string
  enabled: boolean
}
export function listSchedules(query: ScheduleListQuery): Promise<{
  jobs: ScheduledJob[]
  total: number
  page: number
  size: number
  task_types: TaskType[]
  quality_issue_types: string[]
}> {
  return http.get('/data/schedules', { params: query })
}
export function listScheduleOptions(q = '', limit = 50): Promise<{ list: ScheduledJobOption[] }> {
  return http.get('/data/schedules/options', { params: { q, limit } })
}
export function createSchedule(body: ScheduledJobInput): Promise<ScheduledJob> {
  return http.post('/data/schedules', body)
}
export function updateSchedule(id: string, body: ScheduledJobInput): Promise<ScheduledJob> {
  return http.put(`/data/schedules/${id}`, body)
}
export function setScheduleEnabled(id: string, enabled: boolean): Promise<ScheduledJob> {
  return http.post(`/data/schedules/${id}/enabled`, null, { params: { enabled } })
}
export function deleteSchedule(id: string): Promise<{ id: string }> {
  return http.delete(`/data/schedules/${id}`)
}
export function runSchedule(id: string): Promise<{ task_id: string }> {
  return http.post(`/data/schedules/${id}/run`)
}
export type TriggerEventStatus = 'waiting' | 'dispatching' | 'dispatched' | 'cancelled' | 'exhausted' | 'failed'
export interface ScheduledTriggerEvent {
  id: string
  chain_id: string
  source_task_id: string
  source_attempt: number
  source_status: TaskStatus
  source_job_name?: string | null
  target_job_id: string
  trigger_kind: 'dependency' | 'retry'
  trigger_condition?: TriggerCondition | null
  retry_count: number
  due_at: string | null
  dispatched_at?: string | null
  status: TriggerEventStatus
  task_id?: string | null
  message?: string | null
  created_at: string
  updated_at: string
}
export function listScheduleTriggerEvents(id: string, limit = 100): Promise<{ events: ScheduledTriggerEvent[] }> {
  return http.get(`/data/schedules/${id}/trigger-events`, { params: { limit } })
}

// ── 数据源状态（FR-DM-5）──
export interface SourceStatus {
  source: string
  role: 'primary' | 'fallback' | 'board' | 'intraday'
  up: boolean | null
  last_test_at: string | null
  last_success_at: string | null
  failure_reason: string | null
  timeout_sec: number
  credential?: CredentialStatus
}
export function getSources(ping = false): Promise<{ sources: SourceStatus[] }> {
  return http.get('/data/sources', { params: { ping } })
}
export function testSources(): Promise<{ sources: SourceStatus[] }> {
  return http.post('/data/sources/test')
}

// ── 系统设置（FR-DM-12）──
export interface SettingField {
  path: string
  label: string
  desc?: string
  type: 'int' | 'number' | 'bool' | 'enum' | 'string' | 'password'
  value: any
  default: any
  overridden: boolean
  options?: string[]
  placeholder?: string
  min?: number
  max?: number
  secret_status?: 'unset' | 'usable' | 'unavailable'
  credential?: CredentialStatus
}
export type CredentialState = 'unset' | 'unavailable' | 'pending' | 'valid' | 'expiring' | 'expired' | 'invalid' | 'unknown' | 'check_failed'
export interface CredentialStatus {
  status: CredentialState
  source: 'environment' | 'file' | 'app_config' | null
  validity_days: number
  saved_at: string | null
  checked_at: string | null
  expires_at: string | null
  remaining_days: number | null
}
export interface SettingGroup { key: string; label: string; desc?: string; fields: SettingField[] }
// 只读的邮件能力就绪状态（脱敏）：来自部署级环境变量，不可在页面编辑，仅用于开关旁提示底层是否真发。
export interface MailStatus {
  enabled: boolean
  username_masked: string
  password_set: boolean
  mode: 'disabled' | 'incomplete' | 'ready'
  ready: boolean
}
export function getSettingsView(): Promise<{ groups: SettingGroup[]; mail_status?: MailStatus }> {
  return http.get('/data/settings')
}
export function saveSettings(updates: Record<string, any>): Promise<{ saved: number }> {
  return http.post('/data/settings', { updates })
}
export function resetSettings(paths: string[]): Promise<{ reset: number }> {
  return http.post('/data/settings/reset', { paths })
}

// ── 异步数据任务（M2.6 + M2.8-B）──
export type TaskType =
  | 'update' | 'backfill' | 'ingest_date' | 'ingest_codes' | 'rebuild_price_factors'
  | 'recompute' | 'verify' | 'checkup' | 'fix'
  | 'enrich_basic' | 'audit_cleanup' | 'board' | 'stock_ingest' | 'intraday_ingest' | 'stock_board_correlation'
  | 'limit_ladder_invalidate' | 'limit_ladder_recompute' | 'stock_special_trading_day'

// ── 数据结构体检报告（checkup 任务 result.checkup）──
export type CheckupStatus = 'pass' | 'warn' | 'fail'
export interface CheckupIssueItem {
  code: string
  name: string
  issue_type: string
  target_date: string
  latest_date?: string | null
  missing_periods: string[]
  status: 'open' | 'fixing' | 'ignored' | 'unrecorded'
}
export interface CheckupCheck {
  name: string
  ok: boolean
  status?: CheckupStatus
  detail: string
  help?: string
  items?: CheckupIssueItem[]
  evidence?: CheckupEvidence[]
}
export interface CheckupEvidence {
  label: string
  total: number
  limit: number
  columns: { key: string; label: string }[]
  rows: Record<string, string>[]
}
export interface CheckupGroup { group: string; checks: CheckupCheck[] }
export interface CheckupReport {
  passed: number
  warning_count?: number
  warnings?: string[]
  total: number
  all_ok: boolean
  fails: string[]
  groups: CheckupGroup[]
}
export type TaskStatus = 'pending' | 'running' | 'done' | 'failed' | 'interrupted'
export type TriggerSource = 'manual' | 'scheduled' | 'dependency' | 'retry' | 'system'
export interface AsyncTask {
  id: string
  task_type: TaskType
  status: TaskStatus
  progress: number
  message: string
  result?: Record<string, any> | null
  params?: Record<string, any> | null
  trigger_source?: TriggerSource | null
  job_id?: string | null
  job_name?: string | null
  chain_id?: string | null
  parent_task_id?: string | null
  trigger_event_id?: string | null
  retry_count?: number
  execution_attempt?: number
  cancel_requested_at?: string | null
  capability?: {
    can_cancel?: boolean
    can_resume?: boolean
    cancel_mode?: 'checkpoint' | 'none' | string
    resume_granularity?: string | null
    current_phase?: string | null
    current_item?: string | number | null
    cancel_message?: string | null
    checkpoint?: Record<string, any>
  }
  created_at: string
  updated_at: string
}
export interface TaskLogLine { seq: number; ts: string; level: string; message: string }

export function createTask(task_type: TaskType, params?: Record<string, unknown>): Promise<{ task_id: string }> {
  return http.post('/data/tasks', { task_type, params: params || {} })
}
export function getTask(id: string, options: { silent?: boolean } = {}): Promise<AsyncTask> {
  const config: AppRequestConfig = { skipGlobalError: options.silent === true }
  return http.get(`/data/tasks/${id}`, config)
}
export function getTaskLogs(id: string, afterSeq = 0): Promise<{ logs: TaskLogLine[] }> {
  return http.get(`/data/tasks/${id}/logs`, { params: { after_seq: afterSeq } })
}
export function resumeTask(id: string): Promise<{ task_id: string }> {
  return http.post(`/data/tasks/${id}/resume`)
}
export function cancelTask(id: string): Promise<{ task_id: string; cancelling: boolean }> {
  return http.post(`/data/tasks/${id}/cancel`)
}
export interface TaskListParams {
  page?: number; size?: number; status?: string; task_type?: string
  sort?: 'time' | 'type' | 'status'; order?: 'asc' | 'desc'; limit?: number
}
export function listTasks(params: TaskListParams = {}): Promise<{ tasks: AsyncTask[]; total?: number }> {
  return http.get('/data/tasks', { params })
}

// ── 采集日志（服务端分页/排序/筛选，M2.9.5）──
export interface UpdateLogPage {
  list: UpdateLog[]; total: number; page: number; size: number; tables: string[]
}
export function getUpdateLogs(params: {
  page?: number; size?: number; status?: string; table_name?: string
  sort?: 'time' | 'table' | 'status'; order?: 'asc' | 'desc'
} = {}): Promise<UpdateLogPage> {
  return http.get('/data/update-logs', { params })
}

// ── 中文化映射（FR-DM-6，UI 用）──
export const TASK_LABEL: Record<TaskType, string> = {
  update: '增量更新', backfill: '历史补数', ingest_date: '指定日期采集',
  ingest_codes: '指定股票采集', rebuild_price_factors: '重算价格因子',
  recompute: '每日榜单失效', verify: '数据质检',
  checkup: '结构体检', fix: '质检问题恢复',
  enrich_basic: STOCK_INGEST_RECIPE_LABEL.basic_refresh,
  audit_cleanup: '审计日志清理', board: '板块采集', stock_ingest: '个股采集', intraday_ingest: '分时采集',
  stock_board_correlation: '走势相关重算',
  limit_ladder_invalidate: '连板天梯失效',
  stock_special_trading_day: '特殊交易日维护',
  limit_ladder_recompute: '连板天梯重算',
}
export const STATUS_LABEL: Record<TaskStatus, string> = {
  pending: '排队中', running: '运行中', done: '已完成', failed: '失败', interrupted: '已中断',
}
// 当前在用的问题类型（下拉筛选用此顺序；missing_or_suspended 已废弃，不再产出/不再列出）。
export const ISSUE_TYPES_ACTIVE = [
  'intraday_gap', 'intraday_partial', 'intraday_invalid',
  'null_close', 'ohl_repaired', 'abnormal_change', 'price_volume_mismatch',
  'history_data_gap', 'stale',
  'adj_jump',
  'capital_gap', 'capital_invalid', 'capital_mismatch',
  'st_status_missing', 'st_status_approximate', 'st_status_mismatch',
  'market_index_gap', 'market_index_gap_daily', 'market_index_invalid',
  'board_index_gap', 'board_index_gap_daily', 'board_index_invalid', 'board_member_incomplete',
  'board_fund_unmatched', 'board_fund_missing', 'board_fund_stale',
] as const
/** 统一质量筛选与调度选项顺序；保留服务端新增类型及历史类型，不扩大可选范围。 */
export function sortQualityIssueTypes(types: readonly string[]): string[] {
  const order: readonly string[] = ISSUE_TYPES_ACTIVE
  const rank = (type: string) => {
    const index = order.indexOf(type)
    return index < 0 ? order.length : index
  }
  return [...types].sort((a, b) => rank(a) - rank(b))
}
export const ISSUE_TYPE_LABEL: Record<string, string> = {
  intraday_gap: '分时·整日缺失', intraday_partial: '分时·分钟不完整', intraday_invalid: '分时·数据非法',
  // 展示名统一为「对象·现象」，现象词固定：缺失/缺口(近端缺某日)/滞后(未更新到最新)/非法/异常/跳变/修补/为空。
  null_close: '行情·收盘价为空(丢弃)', ohl_repaired: '行情·开高低修补', mv_missing: '市值·整段缺失',
  capital_raw_invalid: '来源记录·历史异常', capital_gap: '股本市值·缺失', capital_invalid: '股本市值·数值或日期非法',
  capital_mismatch: '股本市值·不一致',
  mv_gap: '市值·近端缺某日', mv_invalid: '市值·数值非法', abnormal_change: '行情·涨跌幅异常',
  price_volume_mismatch: '行情·价量口径错配', adj_jump: '复权·因子跳变',
  history_data_gap: '行情·日线缺口', data_gap: '行情·近端缺某日', stale: '行情·未更新到最新',
  st_status_missing: 'ST状态·逐日事实缺失',
  st_status_approximate: 'ST状态·非权威兼容值',
  st_status_mismatch: 'ST状态·日线投影不一致',
  market_index_gap: '市场指数·未更新到最新',
  market_index_gap_daily: '市场指数·近端缺某日',
  market_index_invalid: '市场指数·字段非法',
  board_index_gap: '板块指数·未更新到最新', board_index_gap_daily: '板块指数·近端缺某日',
  board_index_invalid: '板块指数·字段非法', board_member_incomplete: '板块成分·采集不完整',
  board_fund_unmatched: '板块资金流·未映射',
  board_fund_missing: '板块资金流·源未收录', board_fund_stale: '板块资金流·未更新到最新',
}

/** 任务列表/调度/顶栏共用的展示口径：fix 任务带上动态恢复的质检问题类型。 */
export function taskDisplayLabel(
  taskType: TaskType | string,
  params?: Record<string, any> | null,
): string {
  const base = TASK_LABEL[taskType as TaskType] ?? taskType
  if (taskType === 'fix' && params?.manual_delisting) return `${base}·人工退市日期`
  if (taskType === 'fix' && params?.review_suspensions) return `${base}·停牌证据复查`
  const issueType = taskType === 'fix' && typeof params?.issue_type === 'string'
    ? params.issue_type
    : ''
  if (issueType) return `${base}·${ISSUE_TYPE_LABEL[issueType] ?? issueType}`
  if (taskType === 'intraday_ingest') {
    return params?.mode === 'refetch' ? base + '·日期区间重采' : base + '·近期增量补采'
  }
  if (taskType === 'stock_ingest') {
    const recipe = typeof params?.recipe === 'string' ? params.recipe : ''
    return recipe ? `${base}·${STOCK_INGEST_RECIPE_LABEL[recipe as keyof typeof STOCK_INGEST_RECIPE_LABEL] ?? recipe}` : base
  }
  if (taskType === 'board') {
    const parts = [params?.mode === 'backfill' ? '全量回填' : '增量']
    if (params?.board_type === 'concept') parts.push('概念')
    if (params?.board_type === 'industry') parts.push('行业')
    if (Array.isArray(params?.only) && params.only.length > 0 && params.only.length < 4) {
      const labels: Record<string, string> = { dict: '字典', members: '成分', bar: '指数', fund: '资金流' }
      parts.push(params.only.map((stage: string) => labels[stage] ?? stage).join('+'))
    }
    return `${base}·${parts.join('·')}`
  }
  if (taskType === 'stock_board_correlation') {
    const scope = Array.isArray(params?.codes) && params.codes.length
      ? `指定 ${params.codes.length} 只`
      : '全市场'
    const tradeDate = typeof params?.trade_date === 'string' ? params.trade_date : '最新完整交易日'
    return `${base}·${tradeDate}·${scope}`
  }
  if (taskType === 'recompute' || taskType === 'limit_ladder_invalidate') {
    const scope = params?.target_mode === 'all'
      ? '全部快照'
      : (typeof params?.trade_date === 'string' && params.trade_date
          ? params.trade_date
          : '最新完整交易日')
    return `${base}·${scope}`
  }
  if (taskType === 'limit_ladder_recompute') {
    const tradeDate = typeof params?.trade_date === 'string' ? params.trade_date : ''
    return tradeDate ? `${base}·${tradeDate}` : base
  }
  return base
}
// 各问题类型归属的质量层（M2.9 DM-D15 / M2.9.2 DM-D20），用于质量页/概览按层归类。
export const ISSUE_LAYER: Record<string, string> = {
  intraday_gap: '分时', intraday_partial: '分时', intraday_invalid: '分时',
  capital_raw_invalid: '来源', capital_gap: 'L2', capital_invalid: 'L2', capital_mismatch: 'L2',
  null_close: 'L1', ohl_repaired: 'L1', mv_missing: 'L2', mv_gap: 'L2', mv_invalid: 'L2',
  abnormal_change: 'L3', price_volume_mismatch: 'L3', adj_jump: 'L3',
  history_data_gap: 'L4', data_gap: 'L4', stale: 'L4',
  st_status_missing: 'ST', st_status_approximate: 'ST', st_status_mismatch: 'ST',
  market_index_gap: '指数', market_index_gap_daily: '指数', market_index_invalid: '指数',
  board_index_gap: '板块', board_index_gap_daily: '板块', board_index_invalid: '板块',
  board_member_incomplete: '板块', board_fund_unmatched: '板块',
  board_fund_missing: '板块', board_fund_stale: '板块',
}
// 各问题类型的恢复动作文案（DM-D22）：按类型分派，不再统一“重拉/重算”。
export const RECOVER_ACTION_LABEL: Record<string, string> = {
  null_close: '重采该日', ohl_repaired: '重采该日', mv_missing: '补市值', mv_gap: '补市值缺口',
  capital_raw_invalid: '重采原始股本并复检', capital_gap: '多源补采并复检', capital_invalid: '多源修复并复检', capital_mismatch: '多源核验并复检',
  mv_invalid: '刷新异常市值',
  abnormal_change: '重采该日', price_volume_mismatch: '重采该日',
  adj_jump: '重采整段重算复权',
  history_data_gap: '补采全历史缺口', data_gap: '重采缺口', stale: '增量补尾',
  st_status_missing: '刷新ST状态', st_status_approximate: '刷新ST状态',
  st_status_mismatch: '同步ST状态',
  market_index_gap: '补齐市场指数', market_index_gap_daily: '重采市场指数缺失日',
  market_index_invalid: '重采市场指数异常日',
  intraday_gap: '重采分时', intraday_partial: '补采分时', intraday_invalid: '重采分时',
  board_index_gap: '重采指数', board_index_gap_daily: '重采缺失日指数',
  board_index_invalid: '重采异常日指数', board_member_incomplete: '重采成分',
  board_fund_unmatched: '重采资金流',
  board_fund_missing: '重采资金流', board_fund_stale: '重采资金流',
}
export const LAYER_LABEL: Record<string, string> = {
  分时: '分钟归档质量，独立于日线四层评分',
  L1: 'L1 入库闸门', L2: 'L2 字段契约', L3: 'L3 正确性', L4: 'L4 覆盖鲜活',
  指数: '市场指数维度',
  板块: '板块维度',  // 板块 issue 独立层（不混入个股 L1-L4 打分）
  ST: 'ST 点时事实',
  来源: '历史来源记录（当前来源核验见结构体检提醒）',
}
// 四层质量模型的权威说明（单一出处）：质量页 HelpTip / 概览逐股列等处统一引用此处，
// 以后调整口径或新增层/指标只改这里，不再各页各写一份（避免漏改）。
export const LAYER_DESC: Record<string, string> = {
  L1: 'L1 入库闸门：原始/复权响应配对一致、收盘价合法、开高低正常；除权边界按官方前收盘校准',
  L2: 'L2 字段契约：全历史股本与市值非空、合法、同日一致；保留披露、精度和价格来源差异，市值关系允许万分之一相对误差',
  L3: 'L3 正确性：复权因子、涨跌停边界及成交价量口径一致',
  L4: 'L4 覆盖鲜活：无缺口且更新到最新交易日',
  指数: '市场指数维度：每个配置指数均更新到最新、近端无缺口且 OHLC/成交字段合法',
  板块: '板块维度：指数覆盖与字段合法、成分快照完整、资金流覆盖与映射（独立于个股四层质量）',
}
export const LAYER_ISSUE_SUMMARY: Record<string, (issues: number) => string> = {
  L1: (issues) => `${issues} 项待处理`,
  L2: (issues) => `${issues} 只未达标`,
  L3: (issues) => `${issues} 项待处理`,
  L4: (issues) => `累计 ${issues} 个交易日缺口/滞后`,
}
export const SEVERITY_LABEL: Record<string, string> = { high: '高', mid: '中', low: '低' }
export const ISSUE_STATUS_LABEL: Record<string, string> = {
  open: '未处理', fixing: '修复中', resolved: '已解决', ignored: '已忽略',
}
export const SOURCE_LABEL: Record<string, string> = { intraday_sina: '新浪分时', intraday_eastmoney: '东财分时', akshare: 'AKShare', baostock: 'BaoStock', ths_board: '同花顺板块' }

export type BoardTypeScope = '' | 'concept' | 'industry'
export type BoardIngestStage = 'dict' | 'members' | 'bar' | 'fund'
export const BOARD_TYPE_OPTIONS: { label: string; value: BoardTypeScope }[] = [
  { label: '全部', value: '' }, { label: '概念', value: 'concept' }, { label: '行业', value: 'industry' },
]
export const BOARD_STAGE_OPTIONS: { label: string; value: BoardIngestStage }[] = [
  { label: '字典', value: 'dict' }, { label: '成分', value: 'members' },
  { label: '指数', value: 'bar' }, { label: '资金流', value: 'fund' },
]
export const BOARD_ISSUE_ITEMS = [
  { key: 'board_member_incomplete', label: '成分·采集不完整', hint: '重采成分快照' },
  { key: 'board_index_gap', label: '指数·未到最新', hint: '补齐至最新交易日' },
  { key: 'board_index_gap_daily', label: '指数·近端缺某日', hint: '补齐具体缺失日' },
  { key: 'board_index_invalid', label: '指数·字段非法', hint: '重采 OHLC/成交异常日' },
  { key: 'board_fund_unmatched', label: '资金流·未映射', hint: '重采全源并检查归属' },
  { key: 'board_fund_missing', label: '资金流·源未收录', hint: '补齐最新交易日覆盖' },
  { key: 'board_fund_stale', label: '资金流·未到最新', hint: '按问题日期重采滞后周期' },
] as const
