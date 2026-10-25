// @vitest-environment jsdom
import { readFileSync, readdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { parse as parseSfc } from '@vue/compiler-sfc'
import { parse as parseTemplate, NodeTypes, type ElementNode, type RootNode, type TemplateChildNode } from '@vue/compiler-dom'
import postcss from 'postcss'
import { describe, expect, it } from 'vitest'

const SRC_DIR = join(dirname(fileURLToPath(import.meta.url)), '../..')
function vueFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name)
    return entry.isDirectory() ? vueFiles(path) : path.endsWith('.vue') ? [path] : []
  })
}

/** 检查共享主色链接自身的局部声明；祖先/子节点和实际级联另由浏览器复核。 */
function linkStyleOverrides(source: string, role = 'app-interaction-link--primary', properties = ['color']): string[] {
  const { descriptor } = parseSfc(source)
  const violations: string[] = []
  const template = descriptor.template?.content ?? ''
  for (const match of template.matchAll(/<[\w-]+\b(?:"[^"]*"|'[^']*'|[^'">])*>/g)) {
    if (!match[0].includes(role)) continue
    const link = document.createElement('a')
    link.className = Array.from(match[0].matchAll(/\bclass="([^"]*)"/g))
      .flatMap((entry) => entry[1].match(/[A-Za-z_][\w-]*/g) ?? []).join(' ')
    for (const style of descriptor.styles) {
      postcss.parse(style.content).walkRules((rule) => {
        for (const selector of rule.selectors) {
          const ownSelector = selector.replace(/:(?:hover|active|focus-visible|focus)\b/g, '')
          if (/[>\s]/.test(ownSelector.trim())) continue
          let matches = false
          try { matches = link.matches(ownSelector) } catch { continue }
          if (!matches) continue
          rule.walkDecls(declaration => {
            if (properties.includes(declaration.prop)) violations.push(selector)
          })
        }
      })
    }
  }
  return violations
}

/** 字段值链接与行操作分开识别；常量“编辑/删除/添加”等命令不属于阅读字段。 */
function unmarkedFieldLinks(source: string): number[] {
  const template = parseSfc(source).descriptor.template?.content
  if (!template) return []
  const violations: number[] = []
  const attribute = (node: ElementNode, name: string) => node.props.find(
    prop => prop.type === NodeTypes.ATTRIBUTE && prop.name === name,
  )
  const value = (node: ElementNode, name: string) => {
    const prop = attribute(node, name)
    return prop?.type === NodeTypes.ATTRIBUTE ? prop.value?.content ?? '' : ''
  }
  function walk(node: RootNode | TemplateChildNode, column?: ElementNode) {
    if (node.type === NodeTypes.ELEMENT) {
      if (['AppTableColumn', 'el-table-column'].includes(node.tag)) column = node
      const actionColumn = column && (value(column, 'role').startsWith('action') || value(column, 'label') === '操作')
      const navigation = ['RouterLink', 'router-link', 'a', 'ElLink', 'el-link'].includes(node.tag)
      const fieldButton = ['el-button', 'ElButton'].includes(node.tag)
        && attribute(node, 'link') && /\{\{[^}]*\brow(?:\.|\[)[^}]*\}\}/.test(node.loc.source)
      if (column && !actionColumn && (navigation || fieldButton)
        && !value(node, 'class').split(/\s+/).includes('app-table-field-link')) {
        violations.push(node.loc.start.line)
      }
    }
    if (node.type === NodeTypes.ROOT || node.type === NodeTypes.ELEMENT) {
      for (const child of node.children) walk(child, column)
    }
  }
  walk(parseTemplate(template))
  return violations
}

describe('共享交互样式的消费者边界', () => {
  it('能拦住蓝框灰字的局部覆盖，同时允许非链接名称保持中性', () => {
    const template = '<template><a class="name app-interaction-link app-interaction-link--primary">板块</a></template>'
    expect(linkStyleOverrides(`${template}<style scoped>.name { color: var(--el-text-color-regular); }</style>`)).toEqual(['.name'])
    expect(linkStyleOverrides(`${template}<style scoped>.name:not(.app-interaction-link) { color: var(--el-text-color-regular); }</style>`)).toEqual([])
  })

  it('主色导航链接不能被自身局部类的颜色覆盖（含静态名称共用类）', () => {
    const violations = vueFiles(SRC_DIR).flatMap((file) =>
      linkStyleOverrides(readFileSync(file, 'utf8')).map((selector) => `${file}: ${selector}`),
    )
    expect(violations).toEqual([])
  })

  it('字段值链接必须登记共享角色，普通命令和操作列不被误降字重', () => {
    expect(unmarkedFieldLinks('<template><AppTableColumn><el-button link>{{ row.name }}</el-button></AppTableColumn></template>')).toHaveLength(1)
    expect(unmarkedFieldLinks('<template><AppTableColumn><RouterLink to="/stocks/600000.SH">名称</RouterLink></AppTableColumn></template>')).toHaveLength(1)
    expect(unmarkedFieldLinks('<template><AppTableColumn><el-button link class="app-table-field-link">{{ row.name }}</el-button><el-button link>编辑</el-button></AppTableColumn></template>')).toEqual([])
    expect(unmarkedFieldLinks('<template><AppTableColumn role="action"><el-button link>{{ row.action }}</el-button></AppTableColumn></template>')).toEqual([])
    const violations = vueFiles(SRC_DIR).flatMap(file => unmarkedFieldLinks(readFileSync(file, 'utf8'))
      .map(line => `${file}:${line}`))
    expect(violations).toEqual([])
    expect(parseSfc(readFileSync(join(SRC_DIR, 'components/StockAnalysisNameCell.vue'), 'utf8')).descriptor.template?.content)
      .toContain('app-table-field-link')
    // 板块标签属于领域展示，字阶与颜色由详情/表格共享的组件维护。
    expect(parseSfc(readFileSync(join(SRC_DIR, 'components/RelatedBoardCell.vue'), 'utf8')).descriptor.template?.content)
      .toContain('<MarketBoardTag')
  })

  it('字段链接的字阶只有共享样式维护，消费页不得另配字重或字号', () => {
    const properties = ['font', 'font-family', 'font-size', 'font-weight', 'line-height']
    const template = '<template><el-button class="name app-table-field-link">名称</el-button></template>'
    expect(linkStyleOverrides(`${template}<style>.name { font-weight:var(--app-font-weight-section) }</style>`, 'app-table-field-link', properties)).toEqual(['.name'])
    const violations = vueFiles(SRC_DIR).flatMap(file => linkStyleOverrides(
      readFileSync(file, 'utf8'), 'app-table-field-link', properties,
    ).map(selector => `${file}: ${selector}`))
    expect(violations).toEqual([])
    const css = postcss.parse(readFileSync(join(SRC_DIR, 'styles/global.css'), 'utf8'))
    const rules: postcss.Rule[] = []
    css.walkRules(rule => { if (rule.selectors.includes('html[data-layout-preset] .el-button.app-table-field-link')) rules.push(rule) })
    expect(rules).toHaveLength(1)
    const declarations: Record<string, string> = {}
    rules[0]!.walkDecls(declaration => { declarations[declaration.prop] = declaration.value })
    expect(declarations).toMatchObject({ 'font-size': 'inherit', 'line-height': 'inherit', 'font-weight': 'var(--app-font-weight-regular)' })
  })

  it('图标选择消费者使用 aria-pressed，不再覆盖正文或主色', () => {
    for (const file of ['components/ComparePinButton.vue', 'components/StockGroupFavoriteButton.vue']) {
      const { descriptor } = parseSfc(readFileSync(join(SRC_DIR, file), 'utf8'))
      expect(descriptor.template?.content, file).toContain(':aria-pressed="active"')
      for (const style of descriptor.styles) {
        postcss.parse(style.content).walkDecls('color', () => {
          throw new Error(`${file} 不应私配图标选择颜色`)
        })
      }
    }
  })
})
