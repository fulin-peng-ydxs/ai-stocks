import { readFileSync, readdirSync } from 'node:fs'
import { resolve, relative } from 'node:path'
import { describe, expect, it } from 'vitest'
import { PAGE_REGISTRY } from '../pageRegistry'

const root = resolve(__dirname, '../../../..')
const sourceRoot = resolve(root, 'frontend/src')
const inventory = readFileSync(resolve(root,
  'agent-works/configurable-layout-system/responsive-components.md'), 'utf8')

function vueFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = resolve(dir, entry.name)
    return entry.isDirectory() ? vueFiles(path) : entry.name.endsWith('.vue') ? [path] : []
  })
}

const normalize = (value: string) => value.replace(/\s+/g, ' ').trim()
const rows = inventory.split('\n').filter((line) => line.startsWith('| `frontend/src/'))
const paths = rows.map((line) => line.match(/^\| `([^`]+)`/)![1])

describe('响应式组件清单覆盖契约', () => {
  it('每个登记页面及登录页均有独立检查记录', () => {
    const report = readFileSync(resolve(root,
      'agent-works/configurable-layout-system/responsive-pages.md'), 'utf8')
    const recorded = report.split('\n').filter((line) => line.startsWith('| `/'))
      .map((line) => line.match(/^\| `([^`]+)`/)![1])
    expect(recorded.length).toBe(new Set(recorded).size)
    expect([...recorded].sort()).toEqual([...PAGE_REGISTRY.map((page) => page.path), '/login'].sort())
  })

  it('所有 Vue 文件恰好登记一次，删除文件不会遗留假登记', () => {
    expect(paths.length).toBe(new Set(paths).size)
    expect([...paths].sort()).toEqual(vueFiles(sourceRoot).map((file) =>
      relative(root, file).replaceAll('\\', '/')).sort())
  })

  it('每个组件的容器和媒体查询与清单双向一致', () => {
    for (const file of paths) {
      const source = readFileSync(resolve(root, file), 'utf8')
      const queries = [...new Set((source.match(/@(?:container|media)\s+[^{}]+(?=\{)/g) ?? [])
        .map(normalize))].sort()
      const row = rows.find((line) => line.startsWith(`| \`${file}\``))!
      const recorded = [...row.matchAll(/`(@(?:container|media)[^`]+)`/g)]
        .map((match) => normalize(match[1].replaceAll('\\|', '|'))).sort()
      expect(recorded, file).toEqual(queries)
    }
  })
})
