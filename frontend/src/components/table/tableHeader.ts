import { cleanHeadingText, splitHeadingText } from '@/utils/headingText'

/** 表头名称与单位/短口径分离；动态来源的括注也统一进入辅助元信息。 */
export function resolveTableHeader(label = '', headerMeta = '') {
  const heading = splitHeadingText(label)
  return {
    label: heading.label,
    headerMeta: cleanHeadingText([heading.description, headerMeta].filter(Boolean).join(' · ')),
  }
}
