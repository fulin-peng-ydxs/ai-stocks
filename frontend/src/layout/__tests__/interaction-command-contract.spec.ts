/**
 * 查询类命令契约守卫：把 DESIGN 中稳定命名、锁定态和显式查询例外变成源码门禁。
 * 这里只检查跨页面不变量；请求竞态与状态提交仍由消费页行为测试覆盖。
 */
import { describe, expect, it } from 'vitest'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'

const SRC_DIR = resolve(process.cwd(), 'src')
const BUTTON = /<(el-button|AppIconButton)\b([^>]*)>([\s\S]*?)<\/\1>/g
const FORBIDDEN_AMBIGUOUS_LABELS = new Set([
  '重置',
  '还原',
  '恢复',
  '重置配置',
  '重置用户覆盖',
])

interface CommandButton {
  attrs: string
  component: 'el-button' | 'AppIconButton'
  file: string
  label: string
  line: number
}

function vueFiles(dir: string): string[] {
  const out: string[] = []
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) {
      if (entry !== '__tests__') out.push(...vueFiles(full))
    } else if (entry.endsWith('.vue')) {
      out.push(full)
    }
  }
  return out
}

function staticAttribute(attrs: string, name: string): string {
  return attrs.match(new RegExp(`\\b${name}\\s*=\\s*["']([^"']+)["']`))?.[1]?.trim() ?? ''
}

function visibleText(body: string): string {
  return body
    .replace(/<[^>]+>/g, '')
    .replace(/\{\{[\s\S]*?\}\}/g, '')
    .replace(/\s+/g, ' ')
    .trim()
}

function commandButtons(): CommandButton[] {
  const sourceFiles = [
    resolve(SRC_DIR, 'App.vue'),
    ...vueFiles(resolve(SRC_DIR, 'views')),
    ...vueFiles(resolve(SRC_DIR, 'components')),
  ]
  const commands: CommandButton[] = []
  for (const file of sourceFiles) {
    const source = readFileSync(file, 'utf8')
    for (const match of source.matchAll(BUTTON)) {
      const component = match[1] as CommandButton['component']
      const attrs = match[2] ?? ''
      const label = component === 'AppIconButton' ? staticAttribute(attrs, 'label') : visibleText(match[3] ?? '')
      if (!label) continue
      commands.push({
        attrs,
        component,
        file: relative(SRC_DIR, file).split('\\').join('/'),
        label,
        line: source.slice(0, match.index).split('\n').length,
      })
    }
  }
  return commands
}

const commands = commandButtons()
const at = (command: CommandButton) => `${command.file}:${command.line} ${command.label}`

const FILTER_CARD = /<el-card\b(?=[^>]*\bfilter-card\b)[^>]*>([\s\S]*?)<\/el-card>/g
const FILTER_CONDITION = /<(AppSearchInput|AppSelect|AppFilterSelect|AppFilterSwitch|AppDatePicker|TradeDatePicker|PageSegmented|StockOptionSelect|el-checkbox)\b/g
const APP_FILTER_SELECT = /<AppFilterSelect\b([\s\S]*?)\/>/g
const APP_CONTROL_ROW = /<AppControlRow\b[^>]*>([\s\S]*?)<\/AppControlRow>/g
const APP_SORT_CONTROL = /<AppSortControl\b[\s\S]*?\/>/g
const APP_TABLE_COLUMN = /<AppTableColumn\b([^>]*)>([\s\S]*?)<\/AppTableColumn>/g

function searchOrderAudit(): { inspected: number; offenders: string[] } {
  const offenders: string[] = []
  let inspected = 0
  for (const file of vueFiles(resolve(SRC_DIR, 'views'))) {
    const source = readFileSync(file, 'utf8')
    for (const card of source.matchAll(FILTER_CARD)) {
      const conditions = [...(card[1] ?? '').matchAll(FILTER_CONDITION)].map((match) => match[1])
      const firstSearch = conditions.indexOf('AppSearchInput')
      if (firstSearch < 0) continue
      inspected += 1
      const laterCondition = conditions
        .slice(firstSearch + 1)
        .find((component) => component !== 'AppSearchInput')
      if (!laterCondition) continue
      const line = source.slice(0, card.index).split('\n').length
      offenders.push(`${relative(SRC_DIR, file).split('\\').join('/')}:${line} 搜索框后仍有 ${laterCondition}`)
    }
  }
  return { inspected, offenders }
}

function filterSelectCapacityAudit(): { inspected: number; offenders: string[] } {
  const offenders: string[] = []
  let inspected = 0
  for (const file of vueFiles(SRC_DIR)) {
    const source = readFileSync(file, 'utf8')
    for (const select of source.matchAll(APP_FILTER_SELECT)) {
      const attrs = select[1] ?? ''
      if (/:multiple\s*=\s*["']false["']/.test(attrs)) continue
      inspected += 1
      if (/\bdisplay-mode\s*=\s*["']count["']/.test(attrs)) continue
      if (/:visible-tag-count\s*=\s*["'][1-3]["']/.test(attrs)) continue
      const line = source.slice(0, select.index).split('\n').length
      offenders.push(`${relative(SRC_DIR, file).split('\\').join('/')}:${line}`)
    }
  }
  return { inspected, offenders }
}

function sortControlOrderAudit(): { inspected: number; offenders: string[] } {
  const offenders: string[] = []
  let inspected = 0
  for (const file of vueFiles(SRC_DIR)) {
    const source = readFileSync(file, 'utf8')
    for (const row of [...source.matchAll(APP_CONTROL_ROW), ...source.matchAll(/<template #commands>([\s\S]*?)<\/template>/g)]) {
      const body = row[1] ?? ''
      const sortControls = [...body.matchAll(APP_SORT_CONTROL)]
      if (!sortControls.length) continue
      inspected += sortControls.length
      const lastSort = sortControls.at(-1)
      const trailing = body
        .slice((lastSort?.index ?? 0) + (lastSort?.[0].length ?? 0))
        .replace(/<!--[\s\S]*?-->/g, '')
        .trim()
      if (!trailing) continue
      const line = source.slice(0, row.index).split('\n').length
      offenders.push(`${relative(SRC_DIR, file).split('\\').join('/')}:${line}`)
    }
  }
  return { inspected, offenders }
}

function tableFilterSelectCapacityAudit(): { inspected: number; offenders: string[] } {
  const offenders: string[] = []
  let inspected = 0
  for (const file of vueFiles(SRC_DIR)) {
    const source = readFileSync(file, 'utf8')
    for (const column of source.matchAll(APP_TABLE_COLUMN)) {
      const select = [...(column[2] ?? '').matchAll(APP_FILTER_SELECT)]
        .find((item) => !/:multiple\s*=\s*["']false["']/.test(item[1] ?? ''))
      if (!select) continue
      inspected += 1
      const selectAttrs = select[1] ?? ''
      const visibleCount = selectAttrs.match(
        /:visible-tag-count\s*=\s*["']([1-3])["']/,
      )?.[1]
      const countMode = /\bdisplay-mode\s*=\s*["']count["']/.test(selectAttrs)
      const reservedCount = (column[1] ?? '').match(
        /:filter-select-visible-tag-count\s*=\s*["']([1-3])["']/,
      )?.[1]
      const reservedCountMode = /\bfilter-select-display-mode\s*=\s*["']count["']/.test(
        column[1] ?? '',
      )
      if ((countMode && reservedCountMode) || (visibleCount && visibleCount === reservedCount)) {
        continue
      }
      const line = source.slice(0, column.index).split('\n').length
      offenders.push(`${relative(SRC_DIR, file).split('\\').join('/')}:${line}`)
    }
  }
  return { inspected, offenders }
}

describe('查询、重置与刷新命令契约', () => {
  it('列表筛选区的文本搜索框位于全部条件选择之后', () => {
    const { inspected, offenders } = searchOrderAudit()
    expect(inspected, '至少应扫描当前已登记的列表搜索筛选区').toBeGreaterThanOrEqual(8)
    expect(offenders, `以下筛选区的搜索框不是最后一类条件：\n${offenders.join('\n')}`).toEqual([])
  })

  it('多选 AppFilterSelect 必须声明需要完整显示的标签数', () => {
    const { inspected, offenders } = filterSelectCapacityAudit()
    expect(inspected, '至少应扫描当前已登记的多选选择器').toBeGreaterThanOrEqual(10)
    expect(
      offenders,
      `以下多选缺少 display-mode="count" 或 1–3 的 :visible-tag-count 容量声明：\n${offenders.join('\n')}`,
    ).toEqual([])
  })

  it('AppSortControl 在所属操作栏中固定放在最后', () => {
    const { inspected, offenders } = sortControlOrderAudit()
    expect(inspected, '至少应扫描当前已接入的统一排序控件').toBeGreaterThanOrEqual(1)
    expect(offenders, `以下操作栏在排序控件后仍有内容：\n${offenders.join('\n')}`).toEqual([])
  })

  it('表格内多选下拉的列容量必须与可见标签数一致', () => {
    const { inspected, offenders } = tableFilterSelectCapacityAudit()
    expect(inspected, '至少应扫描当前表格内的多选下拉').toBeGreaterThanOrEqual(1)
    expect(
      offenders,
      `以下表格列没有为多选下拉预留一致容量：\n${offenders.join('\n')}`,
    ).toEqual([])
  })

  it('命令按钮不得使用无对象的含糊重置或还原文案', () => {
    const offenders = commands.filter((command) => FORBIDDEN_AMBIGUOUS_LABELS.has(command.label)).map(at)
    expect(offenders, `以下命令必须改为稳定语义名称：\n${offenders.join('\n')}`).toEqual([])
  })

  it('重置筛选在 clean 状态禁用，空态入口必须声明条件渲染例外', () => {
    const offenders = commands
      .filter((command) => command.label === '重置筛选')
      .filter((command) => !/:disabled\s*=/.test(command.attrs))
      .filter((command) => !/\bv-if\s*=/.test(command.attrs))
      .filter((command) => !/\bdata-filter-reset-empty\b/.test(command.attrs))
      .map(at)
    expect(
      offenders,
      `以下“重置筛选”缺少 clean 禁用或空态条件声明：\n${offenders.join('\n')}`,
    ).toEqual([])
  })

  it('刷新命令必须绑定 loading，不能只靠 disabled 表示进行中', () => {
    const offenders = commands
      .filter((command) => command.label === '刷新' || (command.component === 'AppIconButton' && command.label.startsWith('刷新')))
      .filter((command) => !/:loading\s*=/.test(command.attrs))
      .map(at)
    expect(offenders, `以下刷新命令缺少 :loading 锁定态：\n${offenders.join('\n')}`).toEqual([])
  })

  it('显式查询必须声明例外、使用 primary 并绑定 loading', () => {
    const offenders = commands
      .filter((command) => command.label === '查询')
      .filter((command) => (
        !/\bdata-explicit-query\b/.test(command.attrs)
        || !/\btype\s*=\s*["']primary["']/.test(command.attrs)
        || !/:loading\s*=/.test(command.attrs)
      ))
      .map(at)
    expect(
      offenders,
      `普通列表不得设置查询按钮；显式高成本查询必须标记 data-explicit-query、primary 和 loading：\n${offenders.join('\n')}`,
    ).toEqual([])
  })
})
