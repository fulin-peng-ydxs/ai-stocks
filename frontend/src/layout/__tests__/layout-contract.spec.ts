/**
 * 布局契约守卫（M6）——把 DESIGN.md §7 的 CSS/DOM 层红线变成机制性测试。
 *
 * validator.ts 只能判定 schema 层规则；视口硬编码高度、新页面绕过 LayoutHost 手写
 * `.v-page/.v-grow` 这类 CSS/DOM 红线无法从 PageLayout 推断，改由本测试扫描 `src/views`
 * 源码强制。新增页面若违规，`npm test` 直接失败，不靠人肉 review 或浏览器肉眼检查。
 */
import { describe, expect, it } from 'vitest'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'

const VIEWS_DIR = resolve(process.cwd(), 'src/views')

/**
 * 存量未迁移、仍手写 `.v-page/.v-grow/.v-scroll` 契约的页面白名单（相对 src/views）。
 * 迁移到 LayoutHost 后必须从这里移除并在 DESIGN.md §8 登记——本测试会反向校验，
 * 已不再手写布局类却仍留在名单里也会失败，迫使名单与实际迁移进度同步。
 */
const LEGACY_HANDWRITTEN = new Set<string>([
  // 全部存量页面已迁移到 LayoutHost；新页面若手写 .v-page/.v-grow 会被下方用例直接拦截。
])

/**
 * 视口高度红线：禁止用 height / min-height 绑定视口单位（vh/dvh/svh/lvh，含 calc）驱动布局高度。
 * 允许 max-height 作视口相对上限（drawer/dialog 目录里就有 maxHeight），也允许 el-dialog 的 top 偏移。
 */
const VIEWPORT_HEIGHT =
  /(?<!max-)\b(?:min-)?height\s*[:=]\s*["']?(?:calc\([^)"']*\b\d*\.?\d+(?:vh|dvh|svh|lvh)|[^;"'=}]*?\b\d*\.?\d+(?:vh|dvh|svh|lvh))/i

/** 模板里真正手写布局契约类（排除注释/文档里的 .v-page 提及）。 */
const HANDWRITTEN_LAYOUT = /class="[^"]*\bv-(?:page|grow|scroll)\b/

function vueFiles(dir: string): string[] {
  const out: string[] = []
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) out.push(...vueFiles(full))
    else if (entry.endsWith('.vue')) out.push(full)
  }
  return out
}

const files = vueFiles(VIEWS_DIR)
const rel = (f: string) => relative(VIEWS_DIR, f).split('\\').join('/')

describe('布局契约守卫（M6）', () => {
  it('发现页面源码', () => {
    expect(files.length).toBeGreaterThan(0)
  })

  it('页面不得出现视口硬编码高度（DESIGN.md §7 红线）', () => {
    const offenders: string[] = []
    for (const file of files) {
      readFileSync(file, 'utf8').split('\n').forEach((line, i) => {
        if (VIEWPORT_HEIGHT.test(line)) offenders.push(`${rel(file)}:${i + 1}  ${line.trim()}`)
      })
    }
    expect(offenders, `视口硬编码高度违规（应交给布局系统的 flex 链路）：\n${offenders.join('\n')}`).toEqual([])
  })

  it('新页面必须走 LayoutHost，不得手写 .v-page/.v-grow 契约', () => {
    const offenders: string[] = []
    for (const file of files) {
      if (HANDWRITTEN_LAYOUT.test(readFileSync(file, 'utf8')) && !LEGACY_HANDWRITTEN.has(rel(file))) {
        offenders.push(rel(file))
      }
    }
    expect(offenders, `以下页面手写了布局契约类，应改用 <LayoutHost>：\n${offenders.join('\n')}`).toEqual([])
  })

  it('已迁移页面必须从存量白名单移除（保持名单与迁移进度同步）', () => {
    const stale: string[] = []
    for (const legacy of LEGACY_HANDWRITTEN) {
      const full = join(VIEWS_DIR, legacy)
      const exists = files.includes(full)
      if (!exists || !HANDWRITTEN_LAYOUT.test(readFileSync(full, 'utf8'))) stale.push(legacy)
    }
    expect(stale, `这些页面已不再手写布局类，请从 LEGACY_HANDWRITTEN 移除并在 DESIGN.md §8 登记：\n${stale.join('\n')}`).toEqual([])
  })
})
