import { readFileSync, readdirSync } from 'node:fs'
import { dirname, join, relative, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { parse } from 'vue/compiler-sfc'
import ts from 'typescript'

const frontend = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const hasParenthesis = text => /[（）()]/.test(text)
const isTableColumn = node => node.type === 1 && ['AppTableColumn', 'app-table-column', 'el-table-column'].includes(node.tag)

/** 检查显式列名、元信息及自定义表头；动态数据另由共享列运行时规范化。 */
export function auditTableHeaders(sources) {
  const violations = []
  for (const { file, source } of sources) {
    const block = parse(source).descriptor.template
    if (!block?.ast) continue
    const report = node => violations.push(`${file}:${node.loc.start.line} 表头禁止中英文括号；单位用 header-meta，解释用帮助入口`)
    function expressionHasParenthesis(expression) {
      const ast = ts.createSourceFile('header.ts', expression, ts.ScriptTarget.Latest, true)
      let found = false
      function visit(node) {
        if ((ts.isStringLiteralLike(node) || ts.isTemplateHead(node)
          || ts.isTemplateMiddle(node) || ts.isTemplateTail(node)) && hasParenthesis(node.text)) found = true
        ts.forEachChild(node, visit)
      }
      visit(ast)
      return found
    }
    function visit(node, inHeader = false, columnContext = false) {
      if (node.type === 1) {
        if (isTableColumn(node)) {
          for (const prop of node.props) {
            if (prop.type === 6 && ['label', 'header-meta', 'headerMeta'].includes(prop.name)
              && hasParenthesis(prop.value?.content ?? '')) report(prop)
            if (prop.type === 7 && prop.name === 'bind'
              && ['label', 'header-meta', 'headerMeta'].includes(prop.arg?.content)
              && expressionHasParenthesis(prop.exp?.content ?? '')) report(prop)
          }
        }
        inHeader ||= node.tag === 'th' || columnContext && node.tag === 'template' && node.props.some(
          prop => prop.type === 7 && prop.name === 'slot' && prop.arg?.content === 'header',
        )
      }
      if (inHeader && (node.type === 2 && hasParenthesis(node.content)
        || node.type === 5 && expressionHasParenthesis(node.content.content))) report(node)
      for (const child of node.children ?? []) visit(child, inHeader, columnContext || isTableColumn(node))
    }
    visit(block.ast)
  }
  return violations
}

export function auditTableHeaderTree(root = join(frontend, 'src')) {
  function files(dir) {
    return readdirSync(dir, { withFileTypes: true }).flatMap(entry => {
      const path = join(dir, entry.name)
      return entry.name === '__tests__' ? [] : entry.isDirectory() ? files(path)
        : entry.name.endsWith('.vue') ? [path] : []
    })
  }
  return auditTableHeaders(files(root).map(path => ({ file: relative(root, path), source: readFileSync(path, 'utf8') })))
}
if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const violations = auditTableHeaderTree()
  if (violations.length) { console.error(violations.join('\n')); process.exitCode = 1 }
  else console.log('表头括号检查通过。')
}
