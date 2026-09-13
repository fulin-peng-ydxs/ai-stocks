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
import { PAGE_DRAWER_WIDTHS } from '@/components/pageDrawerSize'

const SOURCE_DIR = resolve(process.cwd(), 'src')
const VIEWS_DIR = resolve(SOURCE_DIR, 'views')
const APP_SOURCE = readFileSync(resolve(process.cwd(), 'src/App.vue'), 'utf8')
const GLOBAL_CSS = readFileSync(resolve(process.cwd(), 'src/styles/global.css'), 'utf8')
const ADAPTIVE_GROW_SOURCE = readFileSync(
  resolve(process.cwd(), 'src/layout/components/VAdaptiveGrow.vue'),
  'utf8',
)
const MIXED_GROW_SOURCE = readFileSync(
  resolve(process.cwd(), 'src/layout/components/VMixedGrow.vue'),
  'utf8',
)

/**
 * 视口高度红线：禁止用 height / min-height 绑定视口单位（vh/dvh/svh/lvh，含 calc）驱动布局高度。
 * 允许 max-height 作视口相对上限（drawer/dialog 目录里就有 maxHeight），也允许 el-dialog 的 top 偏移。
 */
const VIEWPORT_HEIGHT =
  /(?<!max-)\b(?:min-)?height\s*[:=]\s*["']?(?:calc\([^)"']*\b\d*\.?\d+(?:vh|dvh|svh|lvh)|[^;"'=}]*?\b\d*\.?\d+(?:vh|dvh|svh|lvh))/i

/** 模板里真正手写布局契约类（排除注释/文档里的 .v-page 提及）。 */
const HANDWRITTEN_LAYOUT = /class="[^"]*\bv-(?:page|grow|scroll)\b/
const SCAFFOLD_PLACEHOLDER = /\bdata-scaffold-placeholder\b/
const PRIVATE_DEFAULT_FILTER_SECTION = /<PageSettingSection\b[^>]*\btitle=["']默认筛选["']/
const VIEWPORT_DRAWER = /<(?:el-drawer|ElDrawer)\b/
const DIRECT_PAGINATION = /<(?:el-pagination|ElPagination)\b/
const PAGE_DRAWER = /<PageDrawer\b[\s\S]*?>/g
const DRAWER_SIZE_KEYS = Object.keys(PAGE_DRAWER_WIDTHS)
const CONTROLLED_DRAWER_SIZE = new RegExp(`\\bsize\\s*=\\s*["'](?:${DRAWER_SIZE_KEYS.join('|')})["']`)

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

  it('应用主内容 flex 链允许低视口收缩，页面一级子项不得被全局固定', () => {
    const mainBlock = APP_SOURCE.match(/\.main\s*\{([\s\S]*?)\}/)?.[1] ?? ''
    expect(mainBlock).toMatch(/min-height\s*:\s*0/)
    expect(mainBlock).toMatch(/overflow\s*:\s*clip/)
    expect(GLOBAL_CSS).not.toMatch(/\.v-page\s*>\s*\*\s*\{[^}]*\bflex\s*:/)
  })

  it('成长区卡片样式只作用于直接子卡片，不得覆盖业务区内嵌卡片', () => {
    expect(ADAPTIVE_GROW_SOURCE).toMatch(
      /\.v-adaptive-grow__main\s*>\s*:deep\(\.el-card\)/,
    )
    expect(ADAPTIVE_GROW_SOURCE).not.toMatch(
      /\.v-adaptive-grow__main\s+:deep\(\.el-card\)/,
    )
    expect(MIXED_GROW_SOURCE).toMatch(/\.v-mixed-main\s*>\s*:deep\(\.el-card\)/)
    expect(MIXED_GROW_SOURCE).not.toMatch(/\.v-mixed-main\s+:deep\(\.el-card\)/)
  })

  it('页面不得绕过 LayoutHost 手写 .v-page/.v-grow 契约', () => {
    const offenders: string[] = []
    for (const file of files) {
      if (HANDWRITTEN_LAYOUT.test(readFileSync(file, 'utf8'))) {
        offenders.push(rel(file))
      }
    }
    expect(offenders, `以下页面手写了布局契约类，应改用 <LayoutHost>：\n${offenders.join('\n')}`).toEqual([])
  })

  it('registry 页面不得保留脚手架占位内容', () => {
    const offenders = files
      .filter((file) => SCAFFOLD_PLACEHOLDER.test(readFileSync(file, 'utf8')))
      .map(rel)
    expect(
      offenders,
      `以下页面仍保留脚手架占位内容，必须接入真实组件和四态后再交付：\n${offenders.join('\n')}`,
    ).toEqual([])
  })

  it('页面设置中的默认查询分区必须统一命名', () => {
    const offenders = files
      .filter((file) => PRIVATE_DEFAULT_FILTER_SECTION.test(readFileSync(file, 'utf8')))
      .map(rel)
    expect(
      offenders,
      `以下页面仍使用私有“默认筛选”分区，应统一为“默认查询”：\n${offenders.join('\n')}`,
    ).toEqual([])
  })

  it('页面抽屉必须使用 PageDrawer，不得覆盖应用顶栏与导航', () => {
    const offenders = files
      .filter((file) => VIEWPORT_DRAWER.test(readFileSync(file, 'utf8')))
      .map(rel)
    expect(
      offenders,
      `以下页面直接使用了 <el-drawer>，应改用页面边界组件 <PageDrawer>：\n${offenders.join('\n')}`,
    ).toEqual([])
  })

  it('分页必须统一使用 AppPagination，不得复制底层分页器和响应式逻辑', () => {
    const offenders = vueFiles(SOURCE_DIR)
      .filter((file) => !file.endsWith('/components/AppPagination.vue'))
      .filter((file) => DIRECT_PAGINATION.test(readFileSync(file, 'utf8')))
      .map((file) => relative(SOURCE_DIR, file).split('\\').join('/'))
    expect(
      offenders,
      `以下组件直接使用了 <el-pagination>，应统一改用 <AppPagination>：\n${offenders.join('\n')}`,
    ).toEqual([])
  })

  it('PageDrawer 只允许使用受控语义尺寸档位', () => {
    const offenders: string[] = []
    for (const file of files) {
      const source = readFileSync(file, 'utf8')
      for (const match of source.matchAll(PAGE_DRAWER)) {
        const tag = match[0]
        if (!/\b:?size\s*=/.test(tag) || CONTROLLED_DRAWER_SIZE.test(tag)) continue
        const line = source.slice(0, match.index).split('\n').length
        offenders.push(`${rel(file)}:${line} ${tag.replace(/\s+/g, ' ')}`)
      }
    }
    expect(
      offenders,
      `页面业务抽屉必须使用 ${DRAWER_SIZE_KEYS.join('/')} 语义档位：\n${offenders.join('\n')}`,
    ).toEqual([])
  })

  it('响应式 wide 抽屉只用于已登记的宽内容场景', () => {
    const consumers = files
      .filter((file) =>
        [...readFileSync(file, 'utf8').matchAll(PAGE_DRAWER)]
          .some((match) => /\bsize\s*=\s*["']wide["']/.test(match[0])))
      .map(rel)
      .sort()
    expect(consumers).toEqual([
      'data/IngestView.vue',
      'system/AuditLogView.vue',
    ])
  })
})
