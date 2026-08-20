import { describe, expect, it } from 'vitest'
import { parse as parseTemplate } from '@vue/compiler-dom'
import { parse as parseSfc } from '@vue/compiler-sfc'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'

const VIEWS_DIR = resolve(process.cwd(), 'src/views')
const COMPONENTS_DIR = resolve(process.cwd(), 'src/components')

function vueFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const full = join(dir, entry)
    return statSync(full).isDirectory()
      ? vueFiles(full)
      : entry.endsWith('.vue')
        ? [full]
        : []
  })
}

interface ElementFinding {
  file: string
  tag: string
  line: number
  forbiddenProps: string[]
  missingColumnSemantics: boolean
  nestedTableEmpty: boolean
}

function inspectTemplate(file: string): ElementFinding[] {
  const source = readFileSync(file, 'utf8')
  const template = parseSfc(source, { filename: file }).descriptor.template?.content
  if (!template) return []

  const findings: ElementFinding[] = []
  const root = parseTemplate(template, { comments: false })
  const walk = (node: any, ancestors: any[] = []) => {
    if (node.type === 1) {
      const forbiddenProps = node.props
        .map((prop: any) => prop.type === 6 ? prop.name : prop.arg?.content)
        .filter((name: string | undefined) =>
          name === 'width'
          || name === 'min-width'
          || name === 'minWidth'
          || (node.tag === 'AppDataTable' && name === 'fill'))
      const propNames = node.props
        .map((prop: any) => prop.type === 6 ? prop.name : prop.arg?.content)
        .filter(Boolean)
      const missingColumnSemantics = node.tag === 'AppTableColumn'
        && !['label', 'prop', 'type', 'role'].some((name) => propNames.includes(name))
      const nestedTableEmpty = ['el-empty', 'ElEmpty'].includes(node.tag)
        && ancestors.some((ancestor) => ancestor.tag === 'AppDataTable')
        && ancestors.some((ancestor) => ancestor.tag === 'template' && ancestor.props.some(
          (prop: any) => prop.type === 7 && prop.name === 'slot' && prop.arg?.content === 'empty',
        ))
      if (
        ['table', 'el-table', 'el-table-column'].includes(node.tag)
        || (['AppTableColumn', 'AppDataTable'].includes(node.tag)
          && (forbiddenProps.length || missingColumnSemantics))
        || nestedTableEmpty
      ) {
        findings.push({
          file: relative(VIEWS_DIR, file).split('\\').join('/'),
          tag: node.tag,
          line: node.loc.start.line,
          forbiddenProps,
          missingColumnSemantics,
          nestedTableEmpty,
        })
      }
      ancestors = [...ancestors, node]
    }
    for (const child of node.children ?? []) walk(child, ancestors)
    for (const branch of node.branches ?? []) walk(branch, ancestors)
  }
  walk(root)
  return findings
}

describe('统一自适应表格契约', () => {
  it('页面表格统一复用 AppDataTable / AppTableColumn', () => {
    const findings = vueFiles(VIEWS_DIR).flatMap(inspectTemplate)
    const directTables = findings.filter((item) =>
      ['table', 'el-table', 'el-table-column'].includes(item.tag))
    expect(
      directTables,
      `页面不得绕过统一表格组件：\n${directTables.map((item) =>
        `${item.file}:${item.line} <${item.tag}>`).join('\n')}`,
    ).toEqual([])
  })

  it('页面不得给自适应列声明 width / min-width', () => {
    const findings = vueFiles(VIEWS_DIR)
      .flatMap(inspectTemplate)
      .filter((item) => item.tag === 'AppTableColumn' && item.forbiddenProps.length)
    expect(
      findings,
      `列宽必须由语义规则推导：\n${findings.map((item) =>
        `${item.file}:${item.line} ${item.forbiddenProps.join(', ')}`).join('\n')}`,
    ).toEqual([])
  })

  it('页面不得用 fill 布尔值绕过主表/嵌入表语义', () => {
    const findings = vueFiles(VIEWS_DIR)
      .flatMap(inspectTemplate)
      .filter((item) => item.tag === 'AppDataTable' && item.forbiddenProps.includes('fill'))
    expect(
      findings,
      `主表默认成长；抽屉、展开行或局部详情表必须显式使用 embedded：\n${findings.map((item) =>
        `${item.file}:${item.line}`).join('\n')}`,
    ).toEqual([])
  })

  it('无字段列必须显式声明结构、状态或操作等语义', () => {
    const findings = vueFiles(VIEWS_DIR)
      .flatMap(inspectTemplate)
      .filter((item) => item.missingColumnSemantics)
    expect(
      findings,
      `无 label/prop/type 的自定义列无法可靠推导宽度，必须声明 role：\n${findings.map((item) =>
        `${item.file}:${item.line}`).join('\n')}`,
    ).toEqual([])
  })

  it('表格空态插槽不得嵌套第二套 el-empty 图形', () => {
    const findings = [...vueFiles(VIEWS_DIR), ...vueFiles(COMPONENTS_DIR)]
      .flatMap(inspectTemplate)
      .filter((item) => item.nestedTableEmpty)
    expect(
      findings,
      `表格已由全局样式提供空态图标，#empty 只能补充文案和操作：\n${findings.map((item) =>
        `${item.file}:${item.line}`).join('\n')}`,
    ).toEqual([])
  })
})
