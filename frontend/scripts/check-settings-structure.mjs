import { basename, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import ts from 'typescript'
import { designSources, scriptAst, sourceParts, walkScript, walkTemplate } from './design-source.mjs'

const canonical = tag => tag.replaceAll('-', '').toLowerCase()
const namedSlot = node => node.type === 1 && node.tag === 'template' && node.props.some(
  prop => prop.type === 7 && prop.name === 'slot' && prop.arg?.content !== 'default',
)

/** 叶子事项必须有控件/值，不得作为空标题或复合设置的外壳。 */
export function auditSettingsStructure(sources) {
  const violations = []
  const components = sources.filter(({ file }) => file.endsWith('.vue')).map(({ file, source }) => {
    const { template, scripts } = sourceParts(file, source)
    const aliases = new Map()
    for (const script of scripts) walkScript(scriptAst(file, script), node => {
      if (ts.isImportDeclaration(node) && ts.isStringLiteral(node.moduleSpecifier)
        && node.moduleSpecifier.text.endsWith('.vue') && node.importClause?.name) {
        aliases.set(canonical(node.importClause.name.text), canonical(basename(node.moduleSpecifier.text, '.vue')))
      }
    })
    const nodes = []
    walkTemplate(template, (node, ancestors) => nodes.push({ node, ancestors }))
    return { file, name: canonical(basename(file, '.vue')), nodes,
      tag: node => aliases.get(canonical(node.tag)) ?? canonical(node.tag) }
  })
  // 从真实组件关系传播设置容器角色，新增复合组件不另维护一份名字白名单。
  const nestedSettings = new Set(['PageSettingItem', 'PageToggleRow', 'SettingsGroup', 'PageSettingSection'].map(canonical))
  let changed = true
  while (changed) {
    changed = false
    for (const component of components) if (!nestedSettings.has(component.name)
      && component.nodes.some(({ node }) => nestedSettings.has(component.tag(node)))) {
      nestedSettings.add(component.name)
      changed = true
    }
  }
  for (const { file, nodes, tag } of components) {
    const item = node => tag(node) === 'pagesettingitem'
    for (const { node, ancestors } of nodes) {
      if (nestedSettings.has(tag(node)) && ancestors.some(item)) {
        violations.push(`${file}:${node.loc.start.line} 子设置须归属 SettingsGroup，不能嵌入叶子 PageSettingItem`)
      }
      if (item(node) && !node.children.some(child => !namedSlot(child)
        && (child.type === 1 || child.type === 5 || child.type === 2 && child.content.trim()))) {
        violations.push(`${file}:${node.loc.start.line} PageSettingItem 缺少控件/值；复合标题应使用 SettingsGroup`)
      }
    }
  }
  return violations
}

export function auditSettingsStructureTree() { return auditSettingsStructure(designSources()) }

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const violations = auditSettingsStructureTree()
  if (violations.length) { console.error(violations.join('\n')); process.exitCode = 1 }
  else console.log('设置分组与叶子结构检查通过。')
}
