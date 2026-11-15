import { FULL_SOURCE_AUDIT_TIMEOUT_MS } from './helpers/fullSourceAudit'
/**
 * 布局契约守卫（M6）——把 DESIGN.md §7 的 CSS/DOM 层红线变成机制性测试。
 *
 * validator.ts 只能判定 schema 层规则；视口硬编码高度、新页面绕过 LayoutHost 手写
 * `.v-page/.v-grow` 这类 CSS/DOM 红线无法从 PageLayout 推断，改由本测试扫描 `src/views`
 * 源码强制。新增页面若违规，`npm test` 直接失败，不靠人肉 review 或浏览器肉眼检查。
 */
import { describe, expect, it } from 'vitest'
import { parse as parseSfc } from '@vue/compiler-sfc'
import { baseParse, type RootNode, type TemplateChildNode } from '@vue/compiler-dom'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'
import { PAGE_DRAWER_WIDTHS } from '@/components/pageDrawerSize'
import { APP_DIALOG_WIDTHS } from '@/components/appDialogSize'

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
const RESPONSIVE_REVIEW_PENDING = /\bresponsive-review-pending\b/
const SCAFFOLD_PLACEHOLDER = /\bdata-scaffold-placeholder\b/
const PRIVATE_DEFAULT_FILTER_SECTION = /<PageSettingSection\b[^>]*\btitle=["']默认筛选["']/
const VIEWPORT_DRAWER = /<(?:el-drawer|ElDrawer)\b/
const DIRECT_DIALOG = /<(?:el-dialog|ElDialog)\b/
const DIRECT_DESCRIPTIONS = /<(?:el-descriptions|ElDescriptions)\b/
const DIRECT_PAGINATION = /<(?:el-pagination|ElPagination)\b/
const PAGE_DRAWER = /<(?:PageDrawer|AppDetailDrawer)\b[\s\S]*?>/g
const APP_DIALOG = /<AppDialog\b[\s\S]*?>/g
const DRAWER_SIZE_KEYS = Object.keys(PAGE_DRAWER_WIDTHS)
const CONTROLLED_DRAWER_SIZE = new RegExp(`\\bsize\\s*=\\s*["'](?:${DRAWER_SIZE_KEYS.join('|')})["']`)
const DIALOG_SIZE_KEYS = Object.keys(APP_DIALOG_WIDTHS)
const CONTROLLED_DIALOG_SIZE = new RegExp(`\\bsize\\s*=\\s*["'](?:${DIALOG_SIZE_KEYS.join('|')})["']`)

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
const allVueFiles = vueFiles(SOURCE_DIR)
const rel = (f: string) => relative(VIEWS_DIR, f).split('\\').join('/')
const sourceRel = (f: string) => relative(SOURCE_DIR, f).split('\\').join('/')

// 只检查路由页直接声明的抽屉；共享组件的宿主来自消费页，由浏览器装配验证。
function unhostedDrawers(template: string): string[] {
  const result: string[] = []
  function visit(node: RootNode | TemplateChildNode, hosted = false) {
    if (node.type !== 0 && node.type !== 1) return
    if (node.type === 1) {
      if (['PageSettingsDrawer', 'PageDrawer', 'AppDetailDrawer'].includes(node.tag) && !hosted) {
        result.push(node.tag)
      }
      hosted ||= node.tag === 'LayoutHost'
    }
    node.children.forEach(child => visit(child, hosted))
  }
  visit(baseParse(template))
  return result
}

describe('布局契约守卫（M6）', () => {
  it('页面设置业务分组声明稳定且同页唯一的记忆标识', () => {
    const offenders: string[] = []
    for (const file of files) {
      const keys = new Set<string>()
      for (const tag of readFileSync(file, 'utf8').matchAll(/<PageSettingSection\b[^>]*>/g)) {
        const key = tag[0].match(/\bsection-key="([a-z][a-z0-9-]*)"/)?.[1]
        if (!key || keys.has(key)) offenders.push(`${rel(file)}: ${tag[0]}`)
        if (key) keys.add(key)
      }
    }
    expect(offenders).toEqual([])
  }, FULL_SOURCE_AUDIT_TIMEOUT_MS)
  it('发现页面源码', () => {
    expect(files.length).toBeGreaterThan(0)
  }, FULL_SOURCE_AUDIT_TIMEOUT_MS)

  it('页面不得出现视口硬编码高度（DESIGN.md §7 红线）', () => {
    const offenders: string[] = []
    for (const file of files) {
      readFileSync(file, 'utf8').split('\n').forEach((line, i) => {
        if (VIEWPORT_HEIGHT.test(line)) offenders.push(`${rel(file)}:${i + 1}  ${line.trim()}`)
      })
    }
    expect(offenders, `视口硬编码高度违规（应交给布局系统的 flex 链路）：\n${offenders.join('\n')}`).toEqual([])
  }, FULL_SOURCE_AUDIT_TIMEOUT_MS)

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
  }, FULL_SOURCE_AUDIT_TIMEOUT_MS)

  it('路由页直接声明的抽屉必须位于 LayoutHost 内，复用页面追加目标', () => {
    const router = readFileSync(resolve(SOURCE_DIR, 'router/index.ts'), 'utf8')
    const entries = [...router.matchAll(/import\('@\/views\/([^']+\.vue)'\)/g)]
    expect(entries.length).toBeGreaterThan(0)
    const offenders = entries.flatMap(([, file]) => {
      const { descriptor } = parseSfc(readFileSync(resolve(VIEWS_DIR, file), 'utf8'))
      return unhostedDrawers(descriptor.template?.content ?? '').map(tag => `${file}: ${tag}`)
    })
    expect(offenders).toEqual([])
  })

  it('抽屉宿主检查识别阶段外的悬空抽屉，允许 overlays 中的嵌套与条件内容', () => {
    expect(unhostedDrawers('<LayoutHost v-if="ready" /><PageSettingsDrawer />')).toEqual(['PageSettingsDrawer'])
    expect(unhostedDrawers('<section><AppDetailDrawer /></section>')).toEqual(['AppDetailDrawer'])
    expect(unhostedDrawers('<LayoutHost><template #overlays><section v-if="ready"><PageSettingsDrawer /></section></template></LayoutHost>')).toEqual([])
  })

  it('registry 页面不得保留脚手架占位内容', () => {
    const offenders = files
      .filter((file) => SCAFFOLD_PLACEHOLDER.test(readFileSync(file, 'utf8')))
      .map(rel)
    expect(
      offenders,
      `以下页面仍保留脚手架占位内容，必须接入真实组件和四态后再交付：\n${offenders.join('\n')}`,
    ).toEqual([])
  }, FULL_SOURCE_AUDIT_TIMEOUT_MS)

  it('新页面必须完成响应式复核，不能只删除业务占位即交付', () => {
    const offenders = files
      .filter((file) => RESPONSIVE_REVIEW_PENDING.test(readFileSync(file, 'utf8')))
      .map(rel)
    expect(
      offenders,
      `以下页面尚未完成响应式设计与关键视口复核，请按 page-template.md 完成后替换标记：\n${offenders.join('\n')}`,
    ).toEqual([])
  }, FULL_SOURCE_AUDIT_TIMEOUT_MS)

  it('页面设置中的默认查询分区必须统一命名', () => {
    const offenders = files
      .filter((file) => PRIVATE_DEFAULT_FILTER_SECTION.test(readFileSync(file, 'utf8')))
      .map(rel)
    expect(
      offenders,
      `以下页面仍使用私有“默认筛选”分区，应统一为“默认查询”：\n${offenders.join('\n')}`,
    ).toEqual([])
  }, FULL_SOURCE_AUDIT_TIMEOUT_MS)

  it('页面抽屉必须使用 PageDrawer，不得覆盖应用顶栏与导航', () => {
    const offenders = files
      .filter((file) => VIEWPORT_DRAWER.test(readFileSync(file, 'utf8')))
      .map(rel)
    expect(
      offenders,
      `以下页面直接使用了 <el-drawer>，应改用页面边界组件 <PageDrawer>：\n${offenders.join('\n')}`,
    ).toEqual([])
  }, FULL_SOURCE_AUDIT_TIMEOUT_MS)

  it('所有抽屉统一由 PageDrawer 管理外壳，消费方不得覆盖 Element 抽屉结构', () => {
    const directDrawerOffenders = allVueFiles
      .filter((file) => !file.endsWith('/components/PageDrawer.vue'))
      .filter((file) => VIEWPORT_DRAWER.test(readFileSync(file, 'utf8')))
      .map(sourceRel)
    const shellStyleOffenders = allVueFiles
      .filter((file) => !file.endsWith('/components/PageDrawerSurface.vue'))
      .filter((file) => /\.el-drawer__(?:header|body|footer)|--el-drawer-bg-color/.test(readFileSync(file, 'utf8')))
      .map(sourceRel)

    expect(
      directDrawerOffenders,
      `以下组件绕过了统一抽屉 <PageDrawer>：\n${directDrawerOffenders.join('\n')}`,
    ).toEqual([])
    expect(
      shellStyleOffenders,
      `以下组件私自覆盖抽屉外壳：\n${shellStyleOffenders.join('\n')}`,
    ).toEqual([])
  }, FULL_SOURCE_AUDIT_TIMEOUT_MS)

  it('业务弹窗必须使用 AppDialog，详情字段必须使用统一详情组件', () => {
    const dialogOffenders = vueFiles(SOURCE_DIR)
      .filter((file) => !file.endsWith('/components/AppDialog.vue'))
      .filter((file) => DIRECT_DIALOG.test(readFileSync(file, 'utf8')))
      .map((file) => relative(SOURCE_DIR, file).split('\\').join('/'))
    const detailOffenders = vueFiles(SOURCE_DIR)
      .filter((file) => DIRECT_DESCRIPTIONS.test(readFileSync(file, 'utf8')))
      .map((file) => relative(SOURCE_DIR, file).split('\\').join('/'))
    expect(dialogOffenders, `以下组件绕过了 <AppDialog>：\n${dialogOffenders.join('\n')}`).toEqual([])
    expect(detailOffenders, `以下组件绕过了统一详情字段：\n${detailOffenders.join('\n')}`).toEqual([])
  }, FULL_SOURCE_AUDIT_TIMEOUT_MS)

  it('AppDialog 只允许使用受控语义尺寸档位', () => {
    const offenders: string[] = []
    for (const file of vueFiles(SOURCE_DIR)) {
      const source = readFileSync(file, 'utf8')
      for (const match of source.matchAll(APP_DIALOG)) {
        const tag = match[0]
        if (!/\b:?size\s*=/.test(tag) || CONTROLLED_DIALOG_SIZE.test(tag)) continue
        const line = source.slice(0, match.index).split('\n').length
        offenders.push(`${relative(SOURCE_DIR, file)}:${line} ${tag.replace(/\s+/g, ' ')}`)
      }
    }
    expect(
      offenders,
      `业务弹窗必须使用 ${DIALOG_SIZE_KEYS.join('/')} 语义档位：\n${offenders.join('\n')}`,
    ).toEqual([])
  }, FULL_SOURCE_AUDIT_TIMEOUT_MS)

  it('页面级业务详情必须使用 AppDetailDrawer，PageDrawer 只保留专用底层场景', () => {
    const directConsumers = files
      .filter((file) => /<PageDrawer\b/.test(readFileSync(file, 'utf8')))
      .map(rel)
      .sort()
    expect(directConsumers).toEqual(['data/IngestView.vue'])
  }, FULL_SOURCE_AUDIT_TIMEOUT_MS)

  it('分页必须统一使用 AppPagination，不得复制底层分页器和响应式逻辑', () => {
    const offenders = vueFiles(SOURCE_DIR)
      .filter((file) => !file.endsWith('/components/AppPagination.vue'))
      .filter((file) => DIRECT_PAGINATION.test(readFileSync(file, 'utf8')))
      .map((file) => relative(SOURCE_DIR, file).split('\\').join('/'))
    expect(
      offenders,
      `以下组件直接使用了 <el-pagination>，应统一改用 <AppPagination>：\n${offenders.join('\n')}`,
    ).toEqual([])
  }, FULL_SOURCE_AUDIT_TIMEOUT_MS)

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
  }, FULL_SOURCE_AUDIT_TIMEOUT_MS)

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
  }, FULL_SOURCE_AUDIT_TIMEOUT_MS)
})
