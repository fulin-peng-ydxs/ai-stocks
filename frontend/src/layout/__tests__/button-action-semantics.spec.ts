import { FULL_SOURCE_AUDIT_TIMEOUT_MS } from './helpers/fullSourceAudit'
import { readFileSync, readdirSync } from 'node:fs'
import { dirname, join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'
import { parse } from '@vue/compiler-sfc'
import { baseParse, NodeTypes, type RootNode, type TemplateChildNode } from '@vue/compiler-dom'
import ts from 'typescript'
import { describe, expect, it } from 'vitest'

const SRC_DIR = join(dirname(fileURLToPath(import.meta.url)), '../..')

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap(entry => {
    const path = join(dir, entry.name)
    if (entry.isDirectory()) return entry.name === '__tests__' ? [] : sourceFiles(path)
    return /\.(vue|ts)$/.test(entry.name) && !entry.name.endsWith('.spec.ts') ? [path] : []
  })
}

const sources = sourceFiles(SRC_DIR).map(file => ({
  file: relative(SRC_DIR, file), source: readFileSync(file, 'utf8'),
}))

/** 分别检查条件分支，避免“恢复 / 归档”共用确认框时只核对其中一种动作。 */
function branches(expression?: ts.Expression): ts.Expression[] {
  if (!expression) return []
  return ts.isConditionalExpression(expression)
    ? [...branches(expression.whenTrue), ...branches(expression.whenFalse)]
    : [expression]
}

function literal(expression?: ts.Expression): string {
  if (!expression) return ''
  if (ts.isStringLiteral(expression) || ts.isNoSubstitutionTemplateLiteral(expression)) {
    return expression.text
  }
  return ts.isTemplateExpression(expression) ? expression.head.text : ''
}

describe('按钮动作语义', () => {
  it('确认框显式声明动作颜色，破坏性确认不沿用普通主色', () => {
    const violations: string[] = []
    const validTones = new Set(['primary', 'danger', 'warning', 'success', 'info', 'default'])
    for (const { file, source } of sources) {
      const script = file.endsWith('.vue') ? parse(source).descriptor.scriptSetup?.content : source
      if (!script) continue
      const ast = ts.createSourceFile(file, script, ts.ScriptTarget.Latest, true)
      function visit(node: ts.Node): void {
        if (ts.isCallExpression(node) && node.expression.getText(ast) === 'ElMessageBox.confirm') {
          const options = node.arguments[2]
          const where = `${file}: ${node.arguments[1]?.getText(ast)}`
          let parent = node.parent
          let handlesCancellation = false
          while (parent && !ts.isFunctionLike(parent)) {
            if (ts.isTryStatement(parent) && parent.catchClause) {
              handlesCancellation = true
              break
            }
            parent = parent.parent
          }
          if (!handlesCancellation) violations.push(`${where} 未处理取消或关闭确认框`)
          if (!options || !ts.isObjectLiteralExpression(options)) {
            violations.push(`${where} 缺少显式确认配置`)
          } else {
            const props = new Map(options.properties.flatMap(prop =>
              ts.isPropertyAssignment(prop) ? [[prop.name.getText(ast), prop.initializer] as const] : [],
            ))
            const tones = branches(props.get('confirmButtonType')).map(literal)
            if (!tones.length || tones.some(tone => !validTones.has(tone))) {
              violations.push(`${where} 未声明有效 confirmButtonType`)
            }
            if (props.has('confirmButtonClass')) violations.push(`${where} 用类型类覆盖按钮语义`)
            const labels = branches(props.get('confirmButtonText') ?? node.arguments[0]).map(literal)
            labels.forEach((label, index) => {
              if (/^(?:确认)?(?:删除|停用|禁用|终止|归档|放弃|清空|清除)/.test(label)
                && tones[tones.length === 1 ? 0 : index] !== 'danger') {
                violations.push(`${where} 的 ${label} 未使用 danger`)
              }
            })
            if (literal(props.get('cancelButtonText')) === '重新回测'
              && literal(props.get('cancelButtonType')) !== 'warning') {
              violations.push(`${where} 覆盖重跑未使用 warning`)
            }
          }
        }
        ts.forEachChild(node, visit)
      }
      visit(ast)
    }
    expect(violations).toEqual([])
  }, FULL_SOURCE_AUDIT_TIMEOUT_MS)

  it('删除图标使用危险语义，自选切换通过 aria-pressed 接入共享选中态', () => {
    const violations: string[] = []
    for (const { file, source } of sources.filter(item => item.file.endsWith('.vue'))) {
      const template = parse(source).descriptor.template?.content
      if (!template) continue
      function visit(node: RootNode | TemplateChildNode): void {
        if (node.type !== NodeTypes.ROOT && node.type !== NodeTypes.ELEMENT) return
        if (node.type === NodeTypes.ELEMENT && node.tag === 'AppIconButton') {
          const label = node.props.find(prop => prop.type === NodeTypes.ATTRIBUTE && prop.name === 'label')
          const tone = node.props.find(prop => prop.type === NodeTypes.ATTRIBUTE && prop.name === 'tone')
          if (label?.type === NodeTypes.ATTRIBUTE && /^删除/.test(label.value?.content ?? '')
            && !(tone?.type === NodeTypes.ATTRIBUTE && tone.value?.content === 'danger')) {
            violations.push(`${file}: ${label.value?.content} 未使用 danger`)
          }
          const bound = new Map(node.props.flatMap(prop =>
            prop.type === NodeTypes.DIRECTIVE && prop.name === 'bind'
              && prop.arg?.type === NodeTypes.SIMPLE_EXPRESSION
              ? [[prop.arg.content, prop.exp?.type === NodeTypes.SIMPLE_EXPRESSION ? prop.exp.content : '']]
              : [],
          ))
          const boundLabel = bound.get('label') ?? ''
          if (boundLabel.includes('加入') && boundLabel.includes('移出') && !bound.has('aria-pressed')) {
            violations.push(`${file}: 自选切换缺少 aria-pressed`)
          }
        }
        node.children.forEach(visit)
      }
      visit(baseParse(template))
    }
    expect(violations).toEqual([])
  }, FULL_SOURCE_AUDIT_TIMEOUT_MS)
})
