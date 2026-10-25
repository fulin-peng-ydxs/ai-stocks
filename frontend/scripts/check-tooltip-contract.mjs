import { readFileSync, readdirSync } from 'node:fs'
import { dirname, join, relative, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { parse } from 'vue/compiler-sfc'
import ts from 'typescript'

const frontend = resolve(dirname(fileURLToPath(import.meta.url)), '..')
// 这些组件的 title 是内容标题；其余 Element Plus 控件会把 title 透传成原生属性。
const titledLibraryComponents = new Set(['el-dialog', 'el-drawer', 'el-alert', 'el-result', 'el-popover'])

/** 按模板/脚本语义检查提示入口，避免把组件标题、路由标题和 iframe 名称误删。 */
export function auditTooltipContract(sources) {
  const violations = []
  for (const { file, source } of sources) {
    const report = (line, message) => violations.push(`${file}:${line} ${message}`)
    const descriptor = file.endsWith('.vue') ? parse(source).descriptor : null
    function template(node, parent) {
      if (node.type === 1) {
        if (node.tag === 'AppIconButton') {
          const label = node.props.find(prop => prop.type === 6 && prop.name === 'label'
            || prop.type === 7 && prop.name === 'bind' && prop.arg?.content === 'label')
          if (!label || !(label.type === 6 ? label.value?.content : label.exp?.content)?.trim()) {
            report(node.loc.start.line, '图标按钮必须提供非空 label，供可访问名称与默认提示共同使用')
          }
          if (['AppHoverInfo', 'AppActionHint', 'el-tooltip'].includes(parent?.tag)) {
            const suppressed = node.props.some(prop => prop.type === 7 && prop.name === 'bind'
              && prop.arg?.content === 'tooltip' && prop.exp?.content.trim() === 'false')
            if (!suppressed) report(node.loc.start.line, '外层已有提示时优先收口到 AppIconButton.tooltip；保留外层时必须 :tooltip="false" 避免重复')
          }
        }
        for (const prop of node.props) {
          const name = prop.type === 6 ? prop.name : prop.type === 7 && prop.name === 'bind' ? prop.arg?.content : undefined
          if (node.tag === 'AppCloseButton' && name === 'tooltip') report(prop.loc.start.line, '关闭入口不增加重复说明')
          if (name === 'native-title' || name === 'nativeTitle') report(prop.loc.start.line, '旧 nativeTitle 接口已移除；说明必须显式消费共享提示组件')
          if (name === 'title' && (node.tagType === 0 && node.tag !== 'iframe'
            || node.tag.startsWith('el-') && !titledLibraryComponents.has(node.tag)
            || ['AppIconButton', 'AppCloseButton', 'AppActionHint'].includes(node.tag))) {
            report(prop.loc.start.line, `<${node.tag}> 禁止以原生 title 提供提示；截断交给全局宿主，必要说明使用共享组件`)
          }
        }
      }
      for (const child of node.children ?? []) template(child, node)
    }
    if (descriptor?.template?.ast) template(descriptor.template.ast)
    const scripts = descriptor ? [descriptor.script, descriptor.scriptSetup].filter(Boolean).map(block => block.content)
      : file.endsWith('.ts') ? [source] : []
    for (const script of scripts) {
      const ast = ts.createSourceFile(file, script, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS)
      function visit(node) {
        const line = ast.getLineAndCharacterOfPosition(node.getStart(ast)).line + 1
        if (ts.isIdentifier(node) && ['nativeTitle', 'findNativeTitleTooltipTarget'].includes(node.text)) {
          report(line, '禁止恢复旧 title 自动提示链路')
        }
        if (ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression)
          && node.expression.name.text === 'setAttribute' && node.arguments[0]?.getText(ast).match(/^['"]title['"]$/)) {
          report(line, '禁止运行时写入原生提示 title')
        }
        if (ts.isCallExpression(node) && ['h', 'createVNode'].includes(node.expression.getText(ast))
          && node.arguments[0] && ts.isStringLiteral(node.arguments[0]) && node.arguments[0].text !== 'iframe'
          && node.arguments[1] && ts.isObjectLiteralExpression(node.arguments[1])) {
          for (const prop of node.arguments[1].properties) {
            if (prop.name?.getText(ast).replace(/['"]/g, '') === 'title') report(line, '渲染函数不得绕过共享提示入口')
          }
        }
        ts.forEachChild(node, visit)
      }
      visit(ast)
    }
  }
  return [...new Set(violations)]
}
export function auditTooltipTree(root = join(frontend, 'src')) {
  function files(dir) {
    return readdirSync(dir, { withFileTypes: true }).flatMap(entry => {
      if (entry.name === '__tests__') return []
      const path = join(dir, entry.name)
      return entry.isDirectory() ? files(path) : /\.(vue|ts)$/.test(path) && !/\.(d|spec|test)\.ts$/.test(path) ? [path] : []
    })
  }
  return auditTooltipContract(files(root).map(path => ({ file: relative(root, path), source: readFileSync(path, 'utf8') })))
}
if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const violations = auditTooltipTree()
  if (violations.length) { console.error(violations.join('\n')); process.exitCode = 1 }
  else console.log('提示契约校验通过：无原生 title 提示或旧自动提示接口。')
}
