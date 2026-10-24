import { readFileSync, readdirSync } from 'node:fs'
import { extname, relative } from 'node:path'
import { describe, expect, it } from 'vitest'
import { baseParse, type ElementNode, type TemplateChildNode } from '@vue/compiler-dom'
import { parse as parseSfc } from '@vue/compiler-sfc'

const SRC_DIR = new URL('../../', import.meta.url)

function vueFiles(dir: URL): URL[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const file = new URL(entry.name, dir)
    if (entry.isDirectory()) return vueFiles(new URL(`${entry.name}/`, dir))
    return extname(entry.name) === '.vue' ? [file] : []
  })
}

describe('PageSegmented 消费契约', () => {
  it('搜索工具栏使用紧凑尺寸，采集与调度共用的表单选项保持中性', () => {
    const violations: string[] = []
    const attr = (node: ElementNode, name: string) => node.props.find(
      prop => prop.type === 6 && prop.name === name,
    )
    const value = (node: ElementNode, name: string) => {
      const prop = attr(node, name)
      return prop?.type === 6 ? prop.value?.content : undefined
    }
    for (const file of vueFiles(SRC_DIR)) {
      const template = parseSfc(readFileSync(file, 'utf8')).descriptor.template
      if (!template) continue
      const path = relative(SRC_DIR.pathname, file.pathname)
      const inspect = (node: TemplateChildNode, ancestors: ElementNode[]) => {
        if (node.type !== 1) return
        if (node.tag === 'PageSegmented') {
          const toolbar = ancestors.some(parent =>
            ['AppAdvancedSearch', 'AppControlRow', 'AppTabToolbar'].includes(parent.tag)
            || /(?:^|[\s_-])toolbar(?:$|[\s_-])/.test(value(parent, 'class') ?? ''),
          )
          const where = `${path}:${template.loc.start.line + node.loc.start.line - 1}`
          if (toolbar && value(node, 'size') !== 'small') violations.push(`${where}: compact toolbar`)
          if (path.startsWith('components/data/') && value(node, 'tone') === 'primary') {
            violations.push(`${where}: neutral task parameters`)
          }
        }
        node.children.forEach(child => inspect(child, [...ancestors, node]))
      }
      baseParse(template.content).children.forEach(node => inspect(node, []))
    }
    expect(violations).toEqual([])
  })

  it('每个分段组都显式提供稳定的可访问名称', () => {
    const violations: string[] = []

    for (const file of vueFiles(SRC_DIR)) {
      const source = readFileSync(file, 'utf8')
      for (const match of source.matchAll(/<PageSegmented\b[\s\S]*?\/>/g)) {
        if (/\baria-label(?:ledby)?=/.test(match[0])) continue
        const line = source.slice(0, match.index).split('\n').length
        violations.push(`${relative(SRC_DIR.pathname, file.pathname)}:${line}`)
      }
    }

    expect(violations).toEqual([])
  })
})
