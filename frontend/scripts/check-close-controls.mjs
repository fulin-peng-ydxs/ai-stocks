import { readFileSync, readdirSync } from 'node:fs'
import { dirname, join, relative, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { parse } from 'vue/compiler-sfc'
import postcss from 'postcss'

const frontend = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const libraryClose = /\.el-(?:dialog__headerbtn|message-box__headerbtn|tag__close|input__clear|textarea__clear|select__clear|cascader__clear-btn|alert__close-btn|message__closeBtn|notification__closeBtn|range__close-icon)|\.clear-icon/
const privateVisual = /^(?:width|min-width|max-width|height|min-height|max-height|(?:min-|max-)?(?:inline|block)-size|padding(?:-.+)?|border(?:-.+)?|background(?:-.+)?|color|font(?:-.+)?|line-height|box-shadow|transform|translate|scale|rotate|filter|transition(?:-.+)?|animation(?:-.+)?|outline(?:-.+)?|cursor|--app-(?:close|icon-button)-.*)$/

/** 检查关闭图形的语义归属及私有视觉配方；布局和显隐仍由宿主控制。 */
export function auditCloseControls(sources) {
  const violations = []
  for (const { file, source } of sources) {
    const report = message => violations.push(`${file}: ${message}`)
    const classes = new Set(['app-close-control'])
    const descriptor = file.endsWith('.vue') ? parse(source).descriptor : null
    function visit(node, ancestors = []) {
      if (node.type === 1) {
        const attr = name => node.props.find(prop => prop.type === 6 && prop.name === name)?.value?.content
        if (node.tag === 'AppCloseButton') {
          for (const name of (attr('class') ?? '').split(/\s+/)) if (name) classes.add(name)
          const label = node.props.some(prop => prop.type === 6 && prop.name === 'label' && prop.value?.content
            || prop.type === 7 && prop.name === 'bind' && prop.arg?.content === 'label')
          if (!label) report('AppCloseButton 必须提供 label')
          if (node.props.some(prop => prop.name === 'style' || prop.type === 7 && prop.arg?.content === 'style')) report('关闭入口禁止内联样式')
          if (attr('size') && !['default', 'compact', 'inline'].includes(attr('size'))) report('关闭档位必须来自统一角色')
        }
        if (node.tag === 'Close' && file !== 'components/AppCloseButton.vue') {
          const destructive = ancestors.some(parent => parent.tag === 'AppIconButton'
            && parent.props.some(prop => prop.type === 6 && prop.name === 'tone' && prop.value?.content === 'danger'))
          const preview = file === 'layout/components/LayoutComponentPreview.vue'
            && !ancestors.some(parent => ['button', 'el-button', 'AppIconButton'].includes(parent.tag))
          if (!destructive && !preview) report('关闭图形必须消费 AppCloseButton；真实删除保留危险操作')
        }
      }
      for (const child of node.children ?? []) visit(child, node.type === 1 ? [...ancestors, node] : ancestors)
    }
    if (descriptor?.template?.ast) visit(descriptor.template.ast)
    const styles = descriptor ? descriptor.styles.map(style => style.content) : file.endsWith('.css') ? [source] : []
    for (const style of styles) {
      postcss.parse(style).walkRules(rule => {
        if (file === 'styles/global.css') return
        if (libraryClose.test(rule.selector)) report('组件库关闭样式必须集中在 global.css')
        const owned = [...classes].some(name => new RegExp(`\\.${name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}(?![\\w-])`).test(rule.selector))
        if (owned) rule.walkDecls(decl => {
          if (privateVisual.test(decl.prop)) report(`关闭入口不得私设 ${decl.prop}（${rule.selector}）`)
        })
      })
    }
  }
  return violations
}

export function auditCloseControlsTree(root = join(frontend, 'src')) {
  function files(dir) {
    return readdirSync(dir, { withFileTypes: true }).flatMap(entry => {
      if (entry.name === '__tests__') return []
      const path = join(dir, entry.name)
      return entry.isDirectory() ? files(path) : /\.(vue|css)$/.test(path) ? [path] : []
    })
  }
  return auditCloseControls(files(root).map(path => ({ file: relative(root, path), source: readFileSync(path, 'utf8') })))
}
if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const violations = auditCloseControlsTree()
  if (violations.length) { console.error(violations.join('\n')); process.exitCode = 1 }
  else console.log('关闭入口校验通过：图形归属、可访问名称与共享视觉配方。')
}
