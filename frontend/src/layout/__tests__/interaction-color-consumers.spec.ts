// @vitest-environment jsdom
import { FULL_SOURCE_AUDIT_TIMEOUT_MS } from './helpers/fullSourceAudit'
import { readFileSync, readdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { parse as parseSfc } from '@vue/compiler-sfc'
import { parse as parseTemplate, NodeTypes, type ElementNode, type RootNode, type TemplateChildNode } from '@vue/compiler-dom'
import postcss from 'postcss'
import { auditSharedStyles } from '../../../scripts/check-design-contracts.mjs'
import { designContracts } from '../../../scripts/design-source.mjs'
import { describe, expect, it } from 'vitest'

const SRC_DIR = join(dirname(fileURLToPath(import.meta.url)), '../..')
function vueFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name)
    return entry.isDirectory() ? vueFiles(path) : path.endsWith('.vue') ? [path] : []
  })
}

/** 测试与构建消费同一检查器，避免测试独立维护缩水版规则。 */
function linkStyleOverrides(source: string, role = 'app-interaction-link--primary', properties = ['color']): string[] {
  return auditSharedStyles([{ file: 'sample.vue', source }], [{ className: role, properties, descendants: true }])
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
  it('基础及描边列表共用边框和圆角，角色、字典与方案消费方不能重配材质', () => {
    const roles = designContracts.styleRoles.filter(role => role.className === 'app-interaction-list-item')
    const fixture = (style: string) => `<template><div class="entry app-interaction-list-item" /></template><style scoped>${style}</style>`
    expect(roles).toHaveLength(1)
    for (const style of ['.entry { border-radius: var(--app-radius-item); }', '.entry { border: 1px solid transparent; }', '.entry.active { background: red; }']) {
      expect(auditSharedStyles([{ file: 'sample.vue', source: fixture(style) }], roles)).toHaveLength(1)
    }
    expect(auditSharedStyles([{ file: 'sample.vue', source: fixture('.entry { padding: 8px; }') }], roles)).toEqual([])
    const sources = vueFiles(SRC_DIR).map(file => ({ file, source: readFileSync(file, 'utf8') }))
    expect(auditSharedStyles(sources, roles)).toEqual([])
  }, FULL_SOURCE_AUDIT_TIMEOUT_MS)

  it('卡片形态的选择器权重不低于普通宿主，避免声明在后仍被覆盖', () => {
    const css = postcss.parse(readFileSync(join(SRC_DIR, 'styles/global.css'), 'utf8'))
    const selectors: string[] = []
    css.walkRules(rule => {
      if (rule.parent?.type !== 'root') return
      if (!rule.selector.includes('.app-interaction-card')) return
      if (rule.nodes.some(node => node.type === 'decl' && node.prop === 'border-radius')) selectors.push(rule.selector)
    })
    const base = selectors.find(selector => selector.endsWith('.app-interaction-target.app-interaction-card'))!
    // 这里的三个选择器均为 html + class/attribute，无函数伪类或 ID；比较真实优先级，
    // 不依赖 jsdom 对同属性声明的源码顺序处理来冒充浏览器的 specificity 验证。
    const weight = (selector: string) => (selector.match(/\.[\w-]+|\[[^\]]+\]/g) ?? []).length
    for (const shape of ['inset', 'floating']) {
      const variant = selectors.find(selector => selector.endsWith(`.app-interaction-card--${shape}`))!
      expect(variant, shape).toBeDefined()
      expect(weight(variant), shape).toBeGreaterThanOrEqual(weight(base))
      expect(selectors.indexOf(variant), shape).toBeGreaterThan(selectors.indexOf(base))
    }
  })

  it.each([false, true])('独立候选不消费连续按钮接缝，连续组仍有单条选中接缝，disabled=%s', disabled => {
    const css = postcss.parse(readFileSync(join(SRC_DIR, 'styles/borders.css'), 'utf8'))
    const fixture = document.createElement('div')
    const radios = `<label class="el-radio-button"><span class="el-radio-button__inner">一</span></label>
      <label class="el-radio-button is-active${disabled ? ' is-disabled' : ''}"><span class="el-radio-button__inner">二</span></label>`
    fixture.innerHTML = `<div class="el-radio-group">${radios}</div><div class="el-radio-group app-choice-button-card">${radios}</div>`
    const root = document.documentElement
    const previous = root.getAttribute('data-layout-preset')
    root.dataset.layoutPreset = 'balanced'
    document.body.append(fixture)
    try {
      const seamSelectors: string[] = []
      css.walkRules(rule => {
        if (rule.nodes.some(node => node.type === 'decl' && node.prop === 'border-right-color')) seamSelectors.push(...rule.selectors)
      })
      const continuous = fixture.children[0].querySelector('.el-radio-button__inner')!
      const separate = fixture.children[1].querySelector('.el-radio-button__inner')!
      expect(seamSelectors.some(selector => continuous.matches(selector))).toBe(true)
      expect(seamSelectors.filter(selector => separate.matches(selector))).toEqual([])
    } finally {
      fixture.remove()
      if (previous === null) delete root.dataset.layoutPreset
      else root.dataset.layoutPreset = previous
    }
  })

  it('描边列表的颜色、边界和选中标记只由共享状态样式维护', () => {
    const role = 'app-interaction-list-item--outlined'
    const properties = ['background', 'background-color', 'border', 'border-color', 'box-shadow']
    const template = `<template><div class="entry ${role}" :class="{ active: selected }" /></template>`
    expect(linkStyleOverrides(`${template}<style scoped>.entry.active { box-shadow: inset 3px 0 blue; }</style>`, role, properties))
      .toHaveLength(1)
    expect(linkStyleOverrides(`${template}<style scoped>.entry:hover { border-color: blue; }</style>`, role, properties))
      .toHaveLength(1)
    expect(linkStyleOverrides(`${template}<style scoped>.entry { padding: 8px; }</style>`, role, properties))
      .toEqual([])

    const violations = vueFiles(SRC_DIR).flatMap(file => linkStyleOverrides(
      readFileSync(file, 'utf8'), role, properties,
    ).map(selector => `${file}: ${selector}`))
    expect(violations).toEqual([])
  }, FULL_SOURCE_AUDIT_TIMEOUT_MS)

  it('能拦住蓝框灰字的局部覆盖，同时允许非链接名称保持中性', () => {
    const template = '<template><a class="name app-interaction-link app-interaction-link--primary">板块</a></template>'
    expect(linkStyleOverrides(`${template}<style scoped>.name { color: var(--el-text-color-regular); }</style>`)).toHaveLength(1)
    expect(linkStyleOverrides(`${template}<style scoped>.name:not(.app-interaction-link) { color: var(--el-text-color-regular); }</style>`)).toEqual([])
  })

  it('主色导航链接不能被自身局部类的颜色覆盖（含静态名称共用类）', () => {
    const violations = vueFiles(SRC_DIR).flatMap((file) =>
      linkStyleOverrides(readFileSync(file, 'utf8')).map((selector) => `${file}: ${selector}`),
    )
    expect(violations).toEqual([])
  }, FULL_SOURCE_AUDIT_TIMEOUT_MS)

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
  }, FULL_SOURCE_AUDIT_TIMEOUT_MS)

  it('字段链接的字阶只有共享样式维护，消费页不得另配字重或字号', () => {
    const properties = ['font', 'font-family', 'font-size', 'font-weight', 'line-height']
    const template = '<template><el-button class="name app-table-field-link">名称</el-button></template>'
    expect(linkStyleOverrides(`${template}<style>.name { font-weight:var(--app-font-weight-section) }</style>`, 'app-table-field-link', properties)).toHaveLength(1)
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
  }, FULL_SOURCE_AUDIT_TIMEOUT_MS)

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
  it('真实按钮同时接入紧凑选择角色时，普通文字不被通用命令字重覆盖', () => {
    const css = postcss.parse(readFileSync(join(SRC_DIR, 'styles/global.css'), 'utf8'))
    const weights: Record<string, string> = {}
    css.walkRules(rule => {
      if (rule.selector === ':root') rule.walkDecls(/^--(?:app-font-weight-|app-button-font-weight$)/, decl => {
        weights[decl.prop] = decl.value
      })
    })
    const resolveWeight = (value: string): string => value.replace(
      /var\((--[\w-]+)\)/g, (_, key: string) => {
        if (!weights[key]) throw new Error(`未定义字重变量 ${key}`)
        return resolveWeight(weights[key])
      },
    )
    const selectors = new Set([
      'html[data-layout-preset] .el-button', 'html[data-layout-preset] .app-interaction-choice',
    ])
    const style = document.createElement('style')
    // 保留生产样式的真实顺序；jsdom 不解析自定义属性，因此只展开已有字重 token。
    css.walkRules(rule => {
      if (!selectors.has(rule.selector)) return
      rule.walkDecls('font-weight', decl => {
        style.textContent += `${rule.selector} { font-weight: ${resolveWeight(decl.value)}; }`
      })
    })
    const fixture = document.createElement('div')
    fixture.innerHTML = '<button class="el-button">执行命令</button><button class="el-button app-interaction-choice" aria-pressed="false">筛选项</button>'
    const root = document.documentElement
    const previous = root.getAttribute('data-layout-preset')
    root.dataset.layoutPreset = 'balanced'
    document.head.append(style)
    document.body.append(fixture)
    try {
      expect(getComputedStyle(fixture.children[0]).fontWeight).toBe('500')
      expect(getComputedStyle(fixture.children[1]).fontWeight).toBe('400')
    } finally {
      style.remove()
      fixture.remove()
      if (previous === null) delete root.dataset.layoutPreset
      else root.dataset.layoutPreset = previous
    }
  })

})
