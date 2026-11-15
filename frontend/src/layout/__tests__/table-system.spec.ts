import { FULL_SOURCE_AUDIT_TIMEOUT_MS } from './helpers/fullSourceAudit'
import { describe, expect, it } from 'vitest'
import { parse as parseTemplate } from '@vue/compiler-dom'
import { parse as parseSfc } from '@vue/compiler-sfc'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'

const COMPONENTS_DIR = resolve(process.cwd(), 'src/components')
const SRC_DIR = resolve(process.cwd(), 'src')
const TABLE_RUNTIME_FILES = new Set([
  resolve(COMPONENTS_DIR, 'AppDataTable.vue'),
  resolve(COMPONENTS_DIR, 'AppTableColumn.vue'),
])

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

function tableConsumerFiles(): string[] {
  return vueFiles(SRC_DIR).filter((file) => !TABLE_RUNTIME_FILES.has(file))
}

function privateTableAlignmentStyles(file: string): string[] {
  const source = readFileSync(file, 'utf8')
  const styles = parseSfc(source, { filename: file }).descriptor.styles
  const tableSelectorWithAlignment = /(?:\.app-data-table|\.el-table)[^{]*\{[^}]*\btext-align\s*:/g
  return styles.flatMap((style) => style.content.match(tableSelectorWithAlignment) ?? [])
}

interface ElementFinding {
  file: string
  tag: string
  line: number
  forbiddenProps: string[]
  missingColumnSemantics: boolean
  ambiguousActionRole: boolean
  nestedTableEmpty: boolean
}

function inspectTemplateSource(source: string, file: string): ElementFinding[] {
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
          || (node.tag === 'AppTableColumn' && (
            name === 'align'
            || name === 'header-align'
            || name === 'headerAlign'
          ))
          || (node.tag === 'AppDataTable' && name === 'fill'))
      const propNames = node.props
        .map((prop: any) => prop.type === 6 ? prop.name : prop.arg?.content)
        .filter(Boolean)
      const staticAttr = (name: string): string | undefined => node.props.find(
        (prop: any) => prop.type === 6 && prop.name === name,
      )?.value?.content
      const missingColumnSemantics = node.tag === 'AppTableColumn'
        && !['label', 'prop', 'type', 'role'].some((name) => propNames.includes(name))
      const ambiguousActionRole = node.tag === 'AppTableColumn'
        && staticAttr('label') === '操作'
        && !['action', 'action-compact'].includes(staticAttr('role') ?? '')
      const nestedTableEmpty = ['el-empty', 'ElEmpty'].includes(node.tag)
        && ancestors.some((ancestor) => ancestor.tag === 'AppDataTable')
        && ancestors.some((ancestor) => ancestor.tag === 'template' && ancestor.props.some(
          (prop: any) => prop.type === 7 && prop.name === 'slot' && prop.arg?.content === 'empty',
        ))
      if (
        ['table', 'el-table', 'el-table-column'].includes(node.tag)
        || (['AppTableColumn', 'AppDataTable'].includes(node.tag)
          && (forbiddenProps.length || missingColumnSemantics))
        || ambiguousActionRole
        || nestedTableEmpty
      ) {
        findings.push({
          file: relative(SRC_DIR, file).split('\\').join('/'),
          tag: node.tag,
          line: node.loc.start.line,
          forbiddenProps,
          missingColumnSemantics,
          ambiguousActionRole,
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

function inspectTemplate(file: string): ElementFinding[] {
  return inspectTemplateSource(readFileSync(file, 'utf8'), file)
}

describe('统一自适应表格契约', () => {
  it('页面和业务组件的表格统一复用 AppDataTable / AppTableColumn', () => {
    const findings = tableConsumerFiles().flatMap(inspectTemplate)
    const directTables = findings.filter((item) =>
      ['table', 'el-table', 'el-table-column'].includes(item.tag))
    expect(
      directTables,
      `页面和业务组件不得绕过统一表格组件：\n${directTables.map((item) =>
        `${item.file}:${item.line} <${item.tag}>`).join('\n')}`,
    ).toEqual([])
  }, FULL_SOURCE_AUDIT_TIMEOUT_MS)

  it('页面不得给自适应列声明 width / min-width', () => {
    const widthProps = new Set(['width', 'min-width', 'minWidth'])
    const findings = tableConsumerFiles()
      .flatMap(inspectTemplate)
      .filter((item) => item.tag === 'AppTableColumn'
        && item.forbiddenProps.some((prop) => widthProps.has(prop)))
    expect(
      findings,
      `列宽必须由语义规则推导：\n${findings.map((item) =>
        `${item.file}:${item.line} ${item.forbiddenProps.join(', ')}`).join('\n')}`,
    ).toEqual([])
  }, FULL_SOURCE_AUDIT_TIMEOUT_MS)

  it('业务调用方不得手写列对齐，必须使用语义角色', () => {
    const alignmentProps = new Set(['align', 'header-align', 'headerAlign'])
    const findings = tableConsumerFiles()
      .flatMap(inspectTemplate)
      .filter((item) => item.tag === 'AppTableColumn'
        && item.forbiddenProps.some((prop) => alignmentProps.has(prop)))
    expect(
      findings,
      `列对齐必须由 role 统一推导：\n${findings.map((item) =>
        `${item.file}:${item.line} ${item.forbiddenProps.join(', ')}`).join('\n')}`,
    ).toEqual([])
  }, FULL_SOURCE_AUDIT_TIMEOUT_MS)

  it('能识别静态和动态的手写列对齐属性', () => {
    const findings = inspectTemplateSource(`
      <template>
        <AppDataTable :data="[]">
          <AppTableColumn label="涨跌幅" align="right" />
          <AppTableColumn label="评级" :header-align="headerAlign" />
        </AppDataTable>
      </template>
    `, resolve(SRC_DIR, '__table-contract-fixture__.vue'))
    expect(findings.flatMap((item) => item.forbiddenProps)).toEqual([
      'align',
      'header-align',
    ])
  })

  it('业务页面和组件不得用私有表格 CSS 覆盖语义对齐', () => {
    const findings = tableConsumerFiles().flatMap((file) =>
      privateTableAlignmentStyles(file).map((rule) => ({
        file: relative(SRC_DIR, file).split('\\').join('/'),
        rule,
      })))
    expect(
      findings,
      `表格对齐只能由 AppTableColumn 的语义角色维护：\n${findings.map((item) =>
        `${item.file} ${item.rule}`).join('\n')}`,
    ).toEqual([])
  }, FULL_SOURCE_AUDIT_TIMEOUT_MS)

  it('页面不得用 fill 布尔值绕过主表/嵌入表语义', () => {
    const findings = tableConsumerFiles()
      .flatMap(inspectTemplate)
      .filter((item) => item.tag === 'AppDataTable' && item.forbiddenProps.includes('fill'))
    expect(
      findings,
      `主表默认成长；抽屉、展开行或局部详情表必须显式使用 embedded：\n${findings.map((item) =>
        `${item.file}:${item.line}`).join('\n')}`,
    ).toEqual([])
  }, FULL_SOURCE_AUDIT_TIMEOUT_MS)

  it('无字段列必须显式声明结构、状态或操作等语义', () => {
    const findings = tableConsumerFiles()
      .flatMap(inspectTemplate)
      .filter((item) => item.missingColumnSemantics)
    expect(
      findings,
      `无 label/prop/type 的自定义列无法可靠推导宽度，必须声明 role：\n${findings.map((item) =>
        `${item.file}:${item.line}`).join('\n')}`,
    ).toEqual([])
  }, FULL_SOURCE_AUDIT_TIMEOUT_MS)

  it('操作列必须显式声明动作密度语义', () => {
    const findings = tableConsumerFiles()
      .flatMap(inspectTemplate)
      .filter((item) => item.ambiguousActionRole)
    expect(
      findings,
      `操作列必须按动作密度声明 action / action-compact：\n${findings.map((item) =>
        `${item.file}:${item.line}`).join('\n')}`,
    ).toEqual([])
  }, FULL_SOURCE_AUDIT_TIMEOUT_MS)

  it('表格空态插槽不得嵌套第二套 el-empty 图形', () => {
    const findings = tableConsumerFiles()
      .flatMap(inspectTemplate)
      .filter((item) => item.nestedTableEmpty)
    expect(
      findings,
      `表格已由全局样式提供空态图标，#empty 只能补充文案和操作：\n${findings.map((item) =>
        `${item.file}:${item.line}`).join('\n')}`,
    ).toEqual([])
  }, FULL_SOURCE_AUDIT_TIMEOUT_MS)
})
