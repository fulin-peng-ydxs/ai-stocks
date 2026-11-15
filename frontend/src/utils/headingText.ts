/** 名称与括注分离；表头以元信息展示，图表标题通过帮助入口承接同一说明。 */
export function splitHeadingText(value = ''): { label: string; description: string } {
  const notes: string[] = []
  const name = value.replace(/[（(]([^（）()]*)[）)]/g, (_match, note: string) => {
    if (note.trim()) notes.push(note.trim())
    return ' '
  })
  return { label: cleanHeadingText(name), description: cleanHeadingText(notes.join(' · ')) }
}

/** 清除残留括号并归一化空白，避免不配对括号泄露到名称或元信息。 */
export function cleanHeadingText(value: string): string {
  return value.replace(/[（）()]/g, ' ').replace(/\s+/g, ' ').trim()
}
