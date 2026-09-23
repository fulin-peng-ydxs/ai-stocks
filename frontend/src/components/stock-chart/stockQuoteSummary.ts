export type StockQuoteTone = 'up' | 'down' | 'neutral'
export interface StockQuoteMetric { label: string; value: string; tone?: StockQuoteTone }
export interface StockQuoteHero extends StockQuoteMetric { details?: StockQuoteMetric[] }
export interface StockQuoteSupplement extends StockQuoteMetric { details?: StockQuoteMetric[] }
export interface StockQuoteSummaryModel {
  time?: string
  hero: StockQuoteHero
  metrics: StockQuoteMetric[]
  rowsPerColumn: number
  /** 行情字段后的独立第三分区，用于涨跌测算等与单日行情并列的派生摘要。 */
  supplement?: StockQuoteSupplement | null
}
export interface StockQuotePalette { text: string; label: string; up: string; down: string; border: string }

function scaledPx(value: number): string {
  return `calc(${value}px * var(--app-display-scale, 1))`
}

function colorOf(tone: StockQuoteTone | undefined, palette: StockQuotePalette): string {
  return tone === 'up' ? palette.up : tone === 'down' ? palette.down : palette.text
}

/** ECharts 浮层与 DOM 行情摘要共用同一字段分组模型。 */
export function stockQuoteSummaryHtml(summary: StockQuoteSummaryModel, palette: StockQuotePalette): string {
  const rowsPerColumn = Math.max(1, Math.floor(summary.rowsPerColumn))
  const supplementGap = 'calc(var(--stock-quote-section-gap) * var(--app-display-scale, 1))'
  const grouped = Array.from(
    { length: Math.ceil(summary.metrics.length / rowsPerColumn) },
    (_, index) => summary.metrics.slice(index * rowsPerColumn, (index + 1) * rowsPerColumn),
  )
  const detailColumnCount = (Math.max(1, grouped.length) * 2) + (summary.supplement ? 1 : 0)
  const time = summary.time
    ? '<thead><tr>'
      + `<th style="padding:0 ${scaledPx(10)} ${scaledPx(4)} 0;text-align:left;color:${palette.label};font-weight:400">时间</th>`
      + `<td colspan="${detailColumnCount}" style="padding:0 0 ${scaledPx(4)} ${scaledPx(10)};text-align:right;color:${palette.text}">${summary.time}</td>`
      + '</tr></thead>'
    : ''
  const heroDetails = summary.hero.details?.length
    ? `<div style="display:flex;justify-content:flex-start;gap:${scaledPx(8)};margin-top:${scaledPx(2)};font-size:${scaledPx(11)};white-space:nowrap">`
      + summary.hero.details.map((detail) => (
        `<span style="color:${colorOf(detail.tone, palette)}">${detail.value}</span>`
      )).join('') + '</div>'
    : ''
  const bodyRows = Array.from({ length: rowsPerColumn }, (_, rowIndex) => {
    const hero = rowIndex === 0
      ? `<td rowspan="${rowsPerColumn}" style="padding:0 ${scaledPx(10)} 0 0;border-right:1px solid ${palette.border};vertical-align:middle;text-align:left">`
        + (summary.hero.label ? `<div style="color:${palette.label};font-size:${scaledPx(11)}">${summary.hero.label}</div>` : '')
        + `<div style="color:${colorOf(summary.hero.tone, palette)};font-size:${scaledPx(18)};line-height:1.35;font-weight:700;white-space:nowrap">${summary.hero.value}</div>${heroDetails}</td>`
      : ''
    const metrics = grouped.map((column, columnIndex) => {
      const metric = column[rowIndex]
      if (!metric) return '<td></td><td></td>'
      const separatorGap = summary.supplement && columnIndex === grouped.length - 1
        ? supplementGap
        : '0'
      return `<th style="padding:0 0 0 ${scaledPx(10)};text-align:left;color:${palette.label};font-weight:400;white-space:nowrap">${metric.label}</th>`
        + `<td style="padding:0 ${separatorGap} 0 ${scaledPx(8)};text-align:right;color:${colorOf(metric.tone, palette)};white-space:nowrap">${metric.value}</td>`
    }).join('')
    const supplement = rowIndex === 0 && summary.supplement
      ? `<td rowspan="${rowsPerColumn}" style="padding:0 0 0 ${supplementGap};border-left:1px solid ${palette.border};vertical-align:middle">`
        + `<div style="color:${palette.label};font-size:${scaledPx(11)};white-space:nowrap">${summary.supplement.label}</div>`
        + `<div style="color:${colorOf(summary.supplement.tone, palette)};font-size:${scaledPx(16)};line-height:1.45;font-weight:700;white-space:nowrap">${summary.supplement.value}</div>`
        + (summary.supplement.details?.length
          ? `<div style="display:flex;flex-direction:column;color:${palette.label};font-size:${scaledPx(11)};white-space:nowrap">${summary.supplement.details.map((detail) => `<span>${detail.value}</span>`).join('')}</div>`
          : '')
        + '</td>'
      : ''
    return `<tr style="height:${scaledPx(21)}">${hero}${metrics}${supplement}</tr>`
  }).join('')

  return '<div style="width:max-content;max-width:calc(100cqw - 32px);box-sizing:border-box;font-variant-numeric:tabular-nums;line-height:1.55">'
    + `<table style="border-collapse:collapse;border-spacing:0;color:${palette.text}">${time}<tbody>${bodyRows}</tbody></table></div>`
}
