import { readFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { parse as parseVue } from 'vue/compiler-sfc'
import { baseParse } from '@vue/compiler-dom'
import postcss from 'postcss'
import ts from 'typescript'
import { designSources, frontendRoot, scriptAst, walkScript } from './design-source.mjs'

/** 按括号层级解析 var，避免把嵌套函数的逗号或字符串误当作 fallback。 */
export function cssVariableReferences(value) {
  const references = []
  function scan(start, end) {
    for (let index = start; index < end; index++) {
      if (value.startsWith('/*', index)) {
        const close = value.indexOf('*/', index + 2)
        index = close < 0 ? end : close + 1
        continue
      }
      if (value[index] === '"' || value[index] === "'") {
        const quote = value[index++]
        while (index < end && value[index] !== quote) {
          if (value[index] === '\\') index++
          index++
        }
        continue
      }
      if (!value.startsWith('var(', index) || /[\w-]/.test(value[index - 1] ?? '')) continue
      let depth = 1
      let comma = -1
      let close = index + 4
      for (; close < end && depth; close++) {
        if (value[close] === '"' || value[close] === "'") {
          const quote = value[close++]
          while (close < end && value[close] !== quote) {
            if (value[close] === '\\') close++
            close++
          }
        } else if (value.startsWith('/*', close)) {
          const commentEnd = value.indexOf('*/', close + 2)
          close = commentEnd < 0 ? end : commentEnd + 1
        } else if (value[close] === '(') depth++
        else if (value[close] === ')') depth--
        else if (value[close] === ',' && depth === 1 && comma < 0) comma = close
      }
      if (depth) continue
      const name = value.slice(index + 4, comma < 0 ? close - 1 : comma)
        .replace(/\/\*[\s\S]*?\*\//g, ' ').trim()
      if (/^--[\w-]+$/.test(name)) references.push({ name, fallback: comma >= 0, index })
      if (comma >= 0) scan(comma + 1, close - 1)
      index = close - 1
    }
  }
  scan(0, value.length)
  return references
}

/** 定义来自 CSS、模板样式、脚本对象及运行时 setProperty；不按变量前缀整包豁免。 */
export function auditCssVariables(sources, externalSources = []) {
  const definitions = new Set()
  const references = []
  const violations = []
  const report = (file, line, message) => violations.push(`${file}:${line} ${message}`)
  const define = name => { if (/^--[\w-]+$/.test(name)) definitions.add(name) }
  function value(file, content, line) {
    for (const reference of cssVariableReferences(content)) {
      references.push({ ...reference, file,
        line: line + content.slice(0, reference.index).split('\n').length - 1 })
    }
  }
  function css(file, content, offset = 0, external = false) {
    try {
      const root = postcss.parse(content)
      root.walkAtRules('property', rule => define(rule.params.trim()))
      root.walkDecls(decl => {
        define(decl.prop)
        if (!external) value(file, decl.value, offset + (decl.source?.start?.line ?? 1))
      })
    } catch (error) { report(file, offset + 1, `CSS 无法解析: ${error.reason ?? error.message}`) }
  }
  function script(file, content, offset = 0) {
    const ast = scriptAst(file, content)
    const unwrap = node => {
      while (ts.isParenthesizedExpression(node) || ts.isAsExpression(node)
        || ts.isSatisfiesExpression(node)) node = node.expression
      return node
    }
    // Object.fromEntries 的有限字面量 map 也是定义来源，不手工维护第二份主题变量白名单。
    function mappedDefinitions(node) {
      if (!ts.isTemplateExpression(node) || !node.head.text.startsWith('--')
        || !ts.isArrayLiteralExpression(node.parent) || node.parent.elements[0] !== node) return
      let callback = node.parent
      while (callback.parent && !ts.isArrowFunction(callback)) callback = callback.parent
      const call = callback.parent
      if (!ts.isArrowFunction(callback) || !ts.isCallExpression(call)
        || !ts.isPropertyAccessExpression(call.expression) || call.expression.name.text !== 'map') return
      const owner = call.parent
      if (!ts.isCallExpression(owner) || owner.expression.getText(ast) !== 'Object.fromEntries') return
      const array = unwrap(call.expression.expression)
      if (!ts.isArrayLiteralExpression(array) || !array.elements.every(ts.isStringLiteralLike)) return
      const parameter = callback.parameters[0]?.name.getText(ast)
      for (const entry of array.elements) {
        let name = node.head.text
        for (const span of node.templateSpans) {
          if (span.expression.getText(ast) !== parameter) return
          name += entry.text + span.literal.text
        }
        define(name)
      }
    }
    walkScript(ast, node => {
      const line = offset + ast.getLineAndCharacterOfPosition(node.getStart(ast)).line + 1
      if (ts.isPropertyAssignment(node)) {
        const name = ts.isComputedPropertyName(node.name) ? node.name.expression : node.name
        if (ts.isStringLiteralLike(name)) define(name.text)
      }
      if (ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression)
        && node.expression.name.text === 'setProperty'
        && node.arguments[0] && ts.isStringLiteralLike(node.arguments[0])) define(node.arguments[0].text)
      mappedDefinitions(node)
      if (ts.isStringLiteralLike(node) || ts.isTemplateHead(node)
        || ts.isTemplateMiddle(node) || ts.isTemplateTail(node)) {
        value(file, node.text, line)
        // HTML tooltip 的引号属于 HTML 属性边界，不能按 CSS 字符串整体跳过。
        for (const match of node.text.matchAll(/\bstyle\s*=\s*(["'])([\s\S]*?)\1/g)) {
          css(file, `x{${match[2]}}`, line + node.text.slice(0, match.index).split('\n').length - 2)
        }
        if (/^\s*--[\w-]+\s*:/.test(node.text)) css(file, `x{${node.text}}`, line - 1)
      }
    })
  }
  for (const { file, source } of externalSources) css(file, source, 0, true)
  for (const { file, source } of sources) {
    if (file.endsWith('.css')) css(file, source)
    else if (file.endsWith('.ts')) script(file, source)
    else if (file.endsWith('.vue')) {
      const { descriptor, errors } = parseVue(source, { filename: file })
      if (errors.length) report(file, 1, 'Vue 无法解析')
      for (const block of descriptor.styles) css(file, block.content, block.loc.start.line - 1)
      for (const block of [descriptor.script, descriptor.scriptSetup].filter(Boolean)) {
        script(file, block.content, block.loc.start.line - 1)
      }
      const template = descriptor.template
      function inspect(node) {
        for (const prop of node.props ?? []) {
          const line = template.loc.start.line + prop.loc.start.line - 1
          if (prop.type === 6 && prop.name === 'style') css(file, `x{${prop.value?.content ?? ''}}`, line - 1)
          if (prop.type === 7 && prop.name === 'bind' && prop.exp) {
            script(file, `(${prop.exp.content})`, line - 1)
          }
        }
        node.children?.forEach(inspect)
      }
      if (template) inspect(baseParse(template.content))
    }
  }
  for (const { file, line, name, fallback } of references) {
    if (!definitions.has(name) && !fallback) report(file, line, `未定义 CSS 变量: ${name}；使用有效变量或显式 fallback`)
  }
  return [...new Set(violations)]
}

export function auditCssVariablesTree() {
  // 仅读取当前锁定组件库的真实定义；--el-* 拼写错误也必须失败。
  const externalSources = ['index.css', 'theme-chalk/dark/css-vars.css'].map(file => {
    const path = file === 'index.css' ? 'dist/index.css' : file
    return { file: `element-plus/${path}`, source: readFileSync(join(frontendRoot, 'node_modules/element-plus', path), 'utf8') }
  })
  return auditCssVariables(designSources(), externalSources)
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const violations = auditCssVariablesTree()
  if (violations.length) {
    console.error(violations.join('\n'))
    process.exitCode = 1
  } else console.log('CSS 变量检查通过：源码、运行时定义、组件库定义及嵌套 fallback')
}
