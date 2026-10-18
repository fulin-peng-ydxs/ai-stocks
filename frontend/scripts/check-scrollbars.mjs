import { readFileSync, readdirSync } from 'node:fs'
import { dirname, join, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { parse as parseSfc } from '@vue/compiler-sfc'
import { parse as parseTemplate } from '@vue/compiler-dom'
import postcss from 'postcss'
import ts from 'typescript'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../src')
const findings = []
function files(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
    if (entry.name === '__tests__') return []
    const full = join(directory, entry.name)
    return entry.isDirectory() ? files(full) : [full]
  })
}
function report(file, line, message) { findings.push(`${relative(root, file)}:${line} ${message}`) }
function inspectStyleBinding(file, expression, line) {
  const ast = ts.createSourceFile('style.ts', `(${expression})`, ts.ScriptTarget.Latest, true)
  const visit = node => {
    if (ts.isPropertyAssignment(node)) {
      const name = node.name.getText(ast).replace(/^['"]|['"]$/g, '')
      if (/^scrollbar(?:Width|Color|-)/.test(name)
        || (/^overflow(?:[XY]|-[xy])?$/.test(name)
          && ts.isStringLiteral(node.initializer) && /^(auto|scroll|overlay)$/.test(node.initializer.text))) {
        report(file, line, '动态样式不得绕过 AppScrollArea 或公共滚动条样式。')
      }
    }
    ts.forEachChild(node, visit)
  }
  visit(ast)
}
function inspectStyles(file, css, lineOffset = 0) {
  postcss.parse(css).walkDecls(decl => {
    if (/^overflow(?:-[xy])?$/.test(decl.prop) && /\b(auto|scroll|overlay)\b/.test(decl.value)) {
      report(file, lineOffset + decl.source.start.line, '自建滚动区必须使用 AppScrollArea，不能直接设置原生滚动。')
    }
    if (/^scrollbar-/.test(decl.prop) || decl.parent.selector?.includes('::-webkit-scrollbar')) {
      report(file, lineOffset + decl.source.start.line, '滚动条样式必须由 scrollbar.css 统一维护。')
    }
  })
}
for (const file of files(root)) {
  if (file.endsWith('/styles/scrollbar.css') || file.endsWith('/components/AppScrollArea.vue')) continue
  const source = readFileSync(file, 'utf8')
  if (file.endsWith('.css')) inspectStyles(file, source)
  if (!file.endsWith('.vue')) continue
  const { descriptor } = parseSfc(source)
  for (const style of descriptor.styles) inspectStyles(file, style.content, style.loc.start.line - 1)
  if (!descriptor.template) continue
  const visit = node => {
    if (node.type === 1) {
      if (['el-scrollbar', 'ElScrollbar'].includes(node.tag)) {
        report(file, node.loc.start.line, '业务代码必须消费 AppScrollArea，不能直接使用 ElScrollbar。')
      }
      for (const prop of node.props) {
        const name = prop.type === 6 ? prop.name : prop.arg?.content
        if (['scrollbar-always-on', 'scrollbarAlwaysOn', 'native-scrollbar', 'nativeScrollbar'].includes(name)
          && !file.endsWith('/components/AppDataTable.vue')) {
          report(file, node.loc.start.line, '消费方不得覆盖公共显隐策略或切换原生滚动条。')
        }
        if (prop.type === 6 && prop.name === 'style' && prop.value) {
          inspectStyles(file, `a { ${prop.value.content} }`, node.loc.start.line - 1)
        }
        if (prop.type === 7 && prop.name === 'bind' && name === 'style' && prop.exp) {
          inspectStyleBinding(file, prop.exp.content, node.loc.start.line)
        }
      }
    }
    for (const child of node.children ?? []) visit(child)
    for (const branch of node.branches ?? []) visit(branch)
  }
  visit(parseTemplate(descriptor.template.content))
}
if (findings.length) {
  console.error(`滚动条契约检查失败：\n${findings.join('\n')}`)
  process.exitCode = 1
} else console.log('滚动条契约检查通过。')
