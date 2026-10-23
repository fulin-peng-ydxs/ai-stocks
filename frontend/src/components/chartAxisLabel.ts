interface MarketAxisColors {
  up: string
  down: string
  label: string
}

/** 有零基准的金融数值轴共用判色；价格轴先换算成相对基准涨跌幅。 */
export function marketAxisLabelColor(colors: MarketAxisColors, reference: number | null = 0) {
  return (value?: string | number): string => {
    const numeric = Number(value)
    if (!Number.isFinite(numeric) || reference == null || !Number.isFinite(reference)
      || reference < 0) return colors.label
    const change = reference === 0 ? numeric : (numeric / reference - 1) * 100
    // 与两位小数轴标签一致，避免浮点误差或舍入后的零值被标成涨跌。
    const displayed = Number(change.toFixed(2))
    return displayed > 0 ? colors.up : displayed < 0 ? colors.down : colors.label
  }
}

/** 光标标签不支持动态 color 回调，用富文本复用刻度判色并保留数值格式。 */
export function marketAxisPointerLabel(
  colors: MarketAxisColors & { tooltipBackground: string; tooltipBorder: string },
  format: (value: number) => string,
  reference: number | null = 0,
) {
  const colorOf = marketAxisLabelColor(colors, reference)
  return {
    backgroundColor: colors.tooltipBackground,
    borderColor: colors.tooltipBorder,
    borderWidth: 1,
    color: colors.label,
    rich: {
      u: { color: colors.up },
      d: { color: colors.down },
      n: { color: colors.label },
    },
    formatter: ({ value }: { value: unknown }) => {
      const numeric = Number(value)
      const color = colorOf(numeric)
      const tone = color === colors.up ? 'u' : color === colors.down ? 'd' : 'n'
      return `{${tone}|${format(numeric)}}`
    },
  }
}
