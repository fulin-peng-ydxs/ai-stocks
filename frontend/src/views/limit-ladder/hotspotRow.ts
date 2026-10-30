/** 按实测布局宽度收敛首行；选中项超出首行时替换末项，不改变筛选条件。 */
export function fitHotspotRow(
  keys: string[],
  widths: Record<string, number>,
  availableWidth: number,
  moreWidth: number,
  gap: number,
  activeKey: string | null,
): { keys: string[]; count: number } {
  if (!keys.length) return { keys: [], count: 0 }
  const active = activeKey && keys.includes(activeKey) ? activeKey : null
  // 首次测量前只露出一项，避免首帧多行闪现；其余项仍参与隐藏区域的测量。
  if (availableWidth <= 0) {
    const first = active ?? keys[0]!
    return { keys: [first, ...keys.filter(key => key !== first)], count: 1 }
  }
  const widthOf = (items: string[]) => items.reduce((sum, key) => sum + (widths[key] ?? 0), 0)
    + Math.max(0, items.length - 1) * gap
  if (widthOf(keys) <= availableWidth) return { keys, count: keys.length }

  const budget = Math.max(0, availableWidth - moreWidth - gap)
  const visible: string[] = []
  for (const key of keys) {
    if (visible.length && widthOf([...visible, key]) > budget) break
    visible.push(key)
  }
  if (active && !visible.includes(active)) {
    while (visible.length && widthOf([...visible, active]) > budget) visible.pop()
    visible.push(active)
  }
  return {
    keys: [...visible, ...keys.filter(key => !visible.includes(key))],
    count: visible.length,
  }
}
