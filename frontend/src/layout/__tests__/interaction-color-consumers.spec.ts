// @vitest-environment jsdom
import { readFileSync, readdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { parse as parseSfc } from '@vue/compiler-sfc'
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
function linkColorOverrides(source: string): string[] {
  const { descriptor } = parseSfc(source)
  const violations: string[] = []
  const template = descriptor.template?.content ?? ''
  for (const match of template.matchAll(/<[\w-]+\b(?:"[^"]*"|'[^']*'|[^'">])*>/g)) {
    if (!match[0].includes('app-interaction-link--primary')) continue
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
          rule.walkDecls('color', () => { violations.push(selector) })
        }
      })
    }
  }
  return violations
}

describe('共享交互颜色的消费者边界', () => {
  it('能拦住蓝框灰字的局部覆盖，同时允许非链接名称保持中性', () => {
    const template = '<template><a class="name app-interaction-link app-interaction-link--primary">板块</a></template>'
    expect(linkColorOverrides(`${template}<style scoped>.name { color: var(--el-text-color-regular); }</style>`)).toEqual(['.name'])
    expect(linkColorOverrides(`${template}<style scoped>.name:not(.app-interaction-link) { color: var(--el-text-color-regular); }</style>`)).toEqual([])
  })

  it('主色导航链接不能被自身局部类的颜色覆盖（含静态名称共用类）', () => {
    const violations = vueFiles(SRC_DIR).flatMap((file) =>
      linkColorOverrides(readFileSync(file, 'utf8')).map((selector) => `${file}: ${selector}`),
    )
    expect(violations).toEqual([])
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
