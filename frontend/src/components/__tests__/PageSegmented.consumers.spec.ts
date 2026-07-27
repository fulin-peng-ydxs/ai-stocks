import { readFileSync, readdirSync } from 'node:fs'
import { extname, relative } from 'node:path'
import { describe, expect, it } from 'vitest'

const SRC_DIR = new URL('../../', import.meta.url)

function vueFiles(dir: URL): URL[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const file = new URL(entry.name, dir)
    if (entry.isDirectory()) return vueFiles(new URL(`${entry.name}/`, dir))
    return extname(entry.name) === '.vue' ? [file] : []
  })
}

describe('PageSegmented 消费契约', () => {
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
