export type StockQuoteTone = 'up' | 'down' | 'neutral'
export interface StockQuoteMetric {
  label: string
  value: string
  tone?: StockQuoteTone
  /** 序列身份色仅由图表主题传入，例如分时均价；方向色仍使用 tone。 */
  color?: string
  /** 常驻摘要通过 HelpHint 图标承接说明；说明正文不参与字符容量计算。 */
  hint?: string
}
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

export interface StockQuoteSectionWidths {
  label: string
  value: string
  details: string[]
}

/** 内容推导的字符容量；跟随字体和界面比例，禁止消费页另设固定像素列宽。 */
export interface StockQuoteSummaryWidths {
  hero: StockQuoteSectionWidths
  columns: { label: string; value: string }[]
  supplement?: StockQuoteSectionWidths
}

/** 同一中文字符数下记录最长数字串，避免把不同字段的最长数字和最长单位拼在一起。 */
type TextCapacity = Map<number, number>

function includeText(capacity: TextCapacity, text: string): void {
  let narrow = 0
  let wide = 0
  for (const char of text) {
    if (char.charCodeAt(0) <= 127) narrow += 1
    else wide += 1
  }
  // 数字/符号按 tabular-nums 的 ch、中文单位按 em；保留实际出现过的组合。
  capacity.set(wide, Math.max(capacity.get(wide) ?? 0, narrow))
}

function capacityWidth(capacity: TextCapacity, reserve = 0): string {
  const candidates = [...(capacity.size ? capacity : new Map([[0, 0]]))]
    .map(([wide, narrow]) => `calc(${narrow + reserve}ch + ${wide}em)`)
  // 由浏览器按当前字号取真实组合中的最大宽度，再只多留一个数字字符。
  return candidates.length === 1 ? candidates[0] : `max(${candidates.join(', ')})`
}

/** 只在数据或可视窗口改变时汇总，光标摘要消费同一份容量而不参与重新计算。 */
export function stockQuoteSummaryWidths(
  summaries: Iterable<StockQuoteSummaryModel>,
): StockQuoteSummaryWidths {
  const empty = (): TextCapacity => new Map()
  const section = () => ({ label: empty(), value: empty(), details: [] as TextCapacity[] })
  const hero = section()
  const supplement = section()
  let hasSupplement = false
  const columns: { label: TextCapacity; value: TextCapacity }[] = []
  const includeSection = (target: ReturnType<typeof section>, source: StockQuoteHero) => {
    includeText(target.label, source.label)
    includeText(target.value, source.value)
    source.details?.forEach((detail, index) => {
      target.details[index] ??= empty()
      includeText(target.details[index], detail.value)
    })
  }
  for (const summary of summaries) {
    includeSection(hero, summary.hero)
    const rows = Math.max(1, Math.floor(summary.rowsPerColumn))
    summary.metrics.forEach((metric, index) => {
      const column = Math.floor(index / rows)
      columns[column] ??= { label: empty(), value: empty() }
      includeText(columns[column].label, metric.label)
      includeText(columns[column].value, metric.value)
    })
    if (summary.supplement) {
      hasSupplement = true
      includeSection(supplement, summary.supplement)
    }
  }
  const sectionWidths = (target: ReturnType<typeof section>): StockQuoteSectionWidths => ({
    label: capacityWidth(target.label),
    value: capacityWidth(target.value, 1),
    details: target.details.map((capacity) => capacityWidth(capacity, 1)),
  })
  return {
    hero: sectionWidths(hero),
    columns: columns.map((column) => ({
      label: capacityWidth(column.label),
      value: capacityWidth(column.value, 1),
    })),
    ...(hasSupplement ? { supplement: sectionWidths(supplement) } : {}),
  }
}

/** HTML 与 Vue 都把宽度应用到文本本身，避免不同字号的 ch/em 被父级字号换算。 */
function widthCss(width: string | undefined, block = false): string {
  return width ? `display:${block ? 'block' : 'inline-block'};width:${width};flex-shrink:0;` : ''
}

function scaledPx(value: number): string {
  return `calc(${value}px * var(--app-display-scale, 1))`
}

function colorOf(tone: StockQuoteTone | undefined, palette: StockQuotePalette): string {
  return tone === 'up' ? palette.up : tone === 'down' ? palette.down : palette.text
}

/** 挂到未缩放 body 的行情浮层共用字号、比例和紧凑内距。 */
export const STOCK_QUOTE_TOOLTIP_CSS = 'transition:opacity .14s ease,visibility .14s ease;'
  + 'font-size:calc(var(--app-font-size-caption) * var(--app-display-scale, 1))!important;'
  + 'line-height:var(--app-line-height-compact)!important;'
  + 'padding:calc(4px * var(--app-display-scale, 1)) calc(6px * var(--app-display-scale, 1))!important;'

/** ECharts 浮层与 DOM 行情摘要共用同一字段分组模型。 */
export function stockQuoteSummaryHtml(
  summary: StockQuoteSummaryModel,
  palette: StockQuotePalette,
  widths?: StockQuoteSummaryWidths,
): string {
  const rowsPerColumn = Math.max(1, Math.floor(summary.rowsPerColumn))
  const grouped = Array.from(
    { length: Math.ceil(summary.metrics.length / rowsPerColumn) },
    (_, index) => summary.metrics.slice(index * rowsPerColumn, (index + 1) * rowsPerColumn),
  )
  const detailColumnCount = Math.max(1, grouped.length) * 2
  const time = summary.time
    ? '<thead><tr>'
      + `<th style="padding:0 ${scaledPx(6)} ${scaledPx(2)} 0;text-align:left;color:${palette.label};font-weight:var(--app-font-weight-regular)">时间</th>`
      + `<td colspan="${detailColumnCount}" style="padding:0 0 ${scaledPx(2)} ${scaledPx(6)};text-align:right;color:${palette.text}">${summary.time}</td>`
      + '</tr></thead>'
    : ''
  const heroDetails = summary.hero.details?.length
    ? `<div style="display:flex;justify-content:flex-start;gap:${scaledPx(6)};margin-top:${scaledPx(2)};font-size:calc(var(--app-font-size-micro) * var(--app-display-scale, 1));white-space:nowrap">`
      + summary.hero.details.map((detail, index) => (
        `<span style="${widthCss(widths?.hero.details[index])}color:${colorOf(detail.tone, palette)}">${detail.value}</span>`
      )).join('') + '</div>'
    : ''
  const bodyRows = Array.from({ length: rowsPerColumn }, (_, rowIndex) => {
    const hero = rowIndex === 0
      ? `<td rowspan="${rowsPerColumn}" style="padding:0 ${scaledPx(6)} 0 0;border-right:1px solid ${palette.border};vertical-align:middle;text-align:left">`
        + (summary.hero.label ? `<div style="color:${palette.label};font-size:calc(var(--app-font-size-micro) * var(--app-display-scale, 1))">${summary.hero.label}</div>` : '')
        + `<div style="${widthCss(widths?.hero.value, true)}color:${colorOf(summary.hero.tone, palette)};font-size:calc(var(--app-font-size-data) * var(--app-display-scale, 1));line-height:var(--app-line-height-compact);font-weight:var(--app-font-weight-strong);white-space:nowrap">${summary.hero.value}</div>${heroDetails}</td>`
      : ''
    const metrics = grouped.map((column, columnIndex) => {
      const metric = column[rowIndex]
      if (!metric) return '<td></td><td></td>'
      return `<th style="padding:0 0 0 ${scaledPx(6)};text-align:left;color:${palette.label};font-weight:var(--app-font-weight-regular);white-space:nowrap"><span style="${widthCss(widths?.columns[columnIndex]?.label)}">${metric.label}</span></th>`
        + `<td style="padding:0 0 0 ${scaledPx(6)};text-align:right;color:${metric.color ?? colorOf(metric.tone, palette)};white-space:nowrap"><span style="${widthCss(widths?.columns[columnIndex]?.value)}">${metric.value}</span></td>`
    }).join('')
    return `<tr style="height:${scaledPx(16)}">${hero}${metrics}</tr>`
  }).join('')
  // 截止测算放在底部单行，避免旁列与日期重复撑宽行情卡片。
  const supplement = summary.supplement
    ? `<div style="display:flex;align-items:baseline;gap:${scaledPx(6)};margin-top:${scaledPx(2)};padding-top:${scaledPx(2)};border-top:1px solid ${palette.border};white-space:nowrap">`
      + `<span style="${widthCss(widths?.supplement?.label)}color:${palette.label}">${summary.supplement.label}</span>`
      + `<strong style="${widthCss(widths?.supplement?.value)}color:${colorOf(summary.supplement.tone, palette)}">${summary.supplement.value}</strong>`
      + (summary.supplement.details ?? []).map((detail, index) => (
        `<span style="${widthCss(widths?.supplement?.details[index])}color:${palette.label}">${detail.value}</span>`
      )).join('') + '</div>'
    : ''

  return '<div style="width:max-content;max-width:calc(100vw - 24px);box-sizing:border-box;font-variant-numeric:tabular-nums;line-height:var(--app-line-height-compact)">'
    + `<table style="border-collapse:collapse;border-spacing:0;color:${palette.text}">${time}<tbody>${bodyRows}</tbody></table>${supplement}</div>`
}
