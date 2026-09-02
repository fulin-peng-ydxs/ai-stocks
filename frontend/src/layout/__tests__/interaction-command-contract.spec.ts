/**
 * 查询类命令契约守卫：把 DESIGN 中稳定命名、锁定态和显式查询例外变成源码门禁。
 * 这里只检查跨页面不变量；请求竞态与状态提交仍由消费页行为测试覆盖。
 */
import { describe, expect, it } from 'vitest'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'

const SRC_DIR = resolve(process.cwd(), 'src')
const DESIGN_SOURCE = readFileSync(resolve(process.cwd(), '../DESIGN.md'), 'utf8')
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

describe('查询、重置与刷新命令契约', () => {
  it('DESIGN 保留统一操作状态和稳定语义名称', () => {
    for (const state of ['idle-clean', 'idle-dirty', 'querying', 'resetting', 'refreshing', 'error']) {
      expect(DESIGN_SOURCE).toContain(`\`${state}\``)
    }
    for (const label of ['重置筛选', '刷新状态', '重新执行', '重新计算', '还原修改', '恢复默认', '清除用户覆盖']) {
      expect(DESIGN_SOURCE).toContain(`“${label}”`)
    }
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
