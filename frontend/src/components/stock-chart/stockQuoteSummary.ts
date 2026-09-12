export type StockQuoteTone = 'up' | 'down' | 'neutral'
export interface StockQuoteMetric { label: string; value: string; tone?: StockQuoteTone }
export interface StockQuoteHero extends StockQuoteMetric { details?: StockQuoteMetric[] }
export interface StockQuoteSummaryModel {
  time?: string
  hero: StockQuoteHero
  metrics: StockQuoteMetric[]
  rowsPerColumn: number
}
export interface StockQuotePalette { text: string; label: string; up: string; down: string; border: string }

function colorOf(tone: StockQuoteTone | undefined, palette: StockQuotePalette): string {
  return tone === 'up' ? palette.up : tone === 'down' ? palette.down : palette.text
}
function metricRow(metric: StockQuoteMetric, palette: StockQuotePalette): string {
  return '<div style="display:flex;justify-content:space-between;gap:8px;white-space:nowrap">'
    + `<span style="color:${palette.label}">${metric.label}</span>`
    + `<span style="color:${colorOf(metric.tone, palette)}">${metric.value}</span></div>`
}

/** ECharts 浮层与 DOM 行情摘要共用同一字段分组模型。 */
export function stockQuoteSummaryHtml(summary: StockQuoteSummaryModel, palette: StockQuotePalette): string {
  const rowsPerColumn = Math.max(1, Math.floor(summary.rowsPerColumn))
  const grouped = Array.from(
    { length: Math.ceil(summary.metrics.length / rowsPerColumn) },
    (_, index) => summary.metrics.slice(index * rowsPerColumn, (index + 1) * rowsPerColumn),
  )
  const columns = grouped.map((column) => (
    '<div style="display:flex;flex-direction:column;gap:1px;min-width:0">'
    + column.map((metric) => metricRow(metric, palette)).join('') + '</div>'
  )).join('')
  const time = summary.time
    ? `<div style="display:flex;justify-content:space-between;margin-bottom:3px;color:${palette.label}"><span>时间</span><span style="color:${palette.text}">${summary.time}</span></div>`
    : ''
  const heroDetails = summary.hero.details?.length
    ? '<div style="display:flex;gap:8px;margin-top:2px;font-size:11px;white-space:nowrap">'
      + summary.hero.details.map((detail) => (
        `<span style="color:${colorOf(detail.tone, palette)}">${detail.value}</span>`
      )).join('') + '</div>'
    : ''
  return '<div style="width:max-content;max-width:calc(100cqw - 32px);box-sizing:border-box;line-height:1.55">'
    + time + '<div style="display:flex;align-items:stretch;gap:8px">'
    + `<div style="display:flex;align-items:center;justify-content:center;align-self:stretch;padding-right:8px;border-right:1px solid ${palette.border};text-align:center">`
    + (summary.hero.label ? `<div style="color:${palette.label};font-size:11px">${summary.hero.label}</div>` : '')
    + `<div><div style="color:${colorOf(summary.hero.tone, palette)};font-size:18px;line-height:1.35;font-weight:700;white-space:nowrap">${summary.hero.value}</div>${heroDetails}</div></div>`
    + columns + '</div></div>'
}
