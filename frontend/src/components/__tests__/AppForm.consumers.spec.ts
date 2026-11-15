import { FULL_SOURCE_AUDIT_TIMEOUT_MS } from '../../layout/__tests__/helpers/fullSourceAudit'
import { readFileSync, readdirSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { parse } from '@vue/compiler-sfc'
import { baseParse } from '@vue/compiler-dom'

function sources(dir: URL): URL[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap(entry => entry.isDirectory()
    ? sources(new URL(`${entry.name}/`, dir))
    : entry.name.endsWith('.vue') ? [new URL(entry.name, dir)] : [])
}

describe('表单尺寸公共入口', () => {
  it('业务表单统一通过 AppForm 消费共享尺寸与表单能力', () => {
    const violations: string[] = []
    for (const file of sources(new URL('../../', import.meta.url))) {
      if (file.pathname.endsWith('/AppForm.vue')) continue
      const template = parse(readFileSync(file, 'utf8')).descriptor.template?.content
      if (!template) continue
      const ast = baseParse(template)
      function visit(node: typeof ast.children[number]) {
        if (node.type !== 1) return
        if (['el-form', 'ElForm'].includes(node.tag)) violations.push(file.pathname)
        node.children.forEach(visit)
      }
      ast.children.forEach(visit)
    }
    expect(violations).toEqual([])
  }, FULL_SOURCE_AUDIT_TIMEOUT_MS)
})
