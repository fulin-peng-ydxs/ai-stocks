/** ECharts 提示行共用左右对齐外壳；字段内容由各图表生成。 */
export function chartTooltipRowHtml(labelHtml: string, valueHtml: string): string {
  return '<div style="display:flex;justify-content:space-between;gap:18px">'
    + labelHtml + valueHtml + '</div>'
}
