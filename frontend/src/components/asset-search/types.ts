import { formatDateTimeMinutes } from '@/utils/dateTime'

// 资产搜索抽屉/选择器共享类型（R5/R7/R14）。
// 方案类 summary 契约对齐后端 services/asset_visibility.py::summarize_asset_row；
// 回测 summary 契约对齐 summarize_backtest_row（无 name/version/is_preset/updated_at）。

export type AssetSource = 'mine' | 'tenant' | 'public' | 'preset'
export type AssetBrowseSource = 'preset' | 'tenant' | 'public'
export type AssetVisibility = 'private' | 'tenant' | 'public'

export interface ProfileSummary {
  id: string
  profile_ref?: string
  asset_ref?: string
  name: string
  version: number
  is_preset: boolean
  visibility?: AssetVisibility
  source?: AssetSource
  readonly?: boolean
  owner_label?: string | null
  updated_at?: string | null
}

export interface BacktestRunSummary {
  id: string
  run_ref?: string
  asset_ref?: string
  kind: string | null
  date_start: string | null
  date_end: string | null
  status: string | null
  created_at: string | null
  finished_at: string | null
  visibility?: AssetVisibility
  source?: AssetSource
  readonly?: boolean
  owner_label?: string | null
  profile_name?: string | null
  score_profile_name?: string | null
  trade_profile_name?: string | null
}

const BACKTEST_KIND_LABELS: Record<string, string> = {
  strategy: '策略回测',
  score_check: '评分验证',
  signal: '评分验证',
}

const BACKTEST_STATUS_LABELS: Record<string, string> = {
  running: '运行中',
  done: '已完成',
  failed: '失败',
}

export function formatBacktestKind(value?: string | null): string {
  if (!value) return '回测'
  return BACKTEST_KIND_LABELS[value] ?? value
}

export function formatBacktestStatus(value?: string | null): string {
  if (!value) return '—'
  return BACKTEST_STATUS_LABELS[value] ?? value
}

export type AssetBrowseItem = ProfileSummary | BacktestRunSummary

export interface AssetBrowseParams {
  source: AssetBrowseSource
  q: string
  page: number
  pageSize: number
}

export interface AssetBrowseResult<T = AssetBrowseItem> {
  items: T[]
  total: number
  page: number
  page_size: number
  source: string
}

// C8：复制由后端生成唯一 id、名称默认「原名 副本」，返回新标识供前端选中
// P2-2（五次复审）：name/version 收紧为必填（后端复制契约必返，默认「原名 副本」+version=1），
// 前端兜底不再退化为 profile_ref/id（opaque ref），缺名时用中文兜底名。
export interface AssetCopyResult {
  id: string
  profile_ref?: string
  name: string
  version: number
}

export function isProfileSummary(item: AssetBrowseItem): item is ProfileSummary {
  return 'name' in item
}

// 列表/选择的稳定标识：优先 opaque ref（profile_ref/run_ref），回退裸 id
export function assetItemKey(item: AssetBrowseItem): string {
  if (isProfileSummary(item)) return item.profile_ref || item.asset_ref || item.id
  return item.run_ref || item.asset_ref || item.id
}

// mine-only 选择器里归属已由入口语义确定，不重复显示“我的”；外部只读资产仍保留来源。
export function assetDisplaySource(
  source?: AssetSource | null,
  isPreset = false,
): AssetSource | null {
  if (isPreset) return 'preset'
  return source && source !== 'mine' ? source : null
}

export function formatAssetTime(value?: string | null): string {
  // 后端为 ISO/「YYYY-MM-DD HH:MM:SS」字符串；列表只展示到分钟
  return formatDateTimeMinutes(value)
}
