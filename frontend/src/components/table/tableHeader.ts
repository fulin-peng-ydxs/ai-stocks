/** 表头名称与单位/短口径分离；动态来源的括注也统一进入辅助元信息。 */
export function resolveTableHeader(label = '', headerMeta = '') {
  const notes: string[] = []
  const name = label.replace(/[（(]([^（）()]*)[）)]/g, (_match, note: string) => {
    if (note.trim()) notes.push(note.trim())
    return ' '
  })
  const clean = (value: string) => value.replace(/[（）()]/g, ' ').replace(/\s+/g, ' ').trim()
  return {
    label: clean(name),
    headerMeta: clean([...notes, headerMeta].filter(Boolean).join(' · ')),
  }
}
