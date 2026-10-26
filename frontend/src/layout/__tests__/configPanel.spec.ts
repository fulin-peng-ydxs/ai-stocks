import { describe, expect, it } from 'vitest'
import {
  CONFIG_SYSTEM_COLLAPSE_SECTIONS,
  CONFIG_SYSTEM_GROUP_SECTIONS,
  configPanelCollapseSectionsOf,
} from '../configPanel'

describe('配置面板折叠候选层级', () => {
  it('板块成分工作并发登记在已有采集规则分区，来源网络参数继续复用请求覆盖', () => {
    expect(CONFIG_SYSTEM_GROUP_SECTIONS.ths_board.find(section => section.key === 'collection')?.fieldPaths)
      .toEqual(['ths_board.member_concurrency', 'ths_board.member_update_interval_days'])
    expect(CONFIG_SYSTEM_GROUP_SECTIONS.datasource.find(section => section.key === 'source-ths_board')?.fieldPaths)
      .toContain('datasource.sources.ths_board.network_concurrency')
  })
  it('分区显式引用父组，沿用已存储的折叠 key', () => {
    const sections = configPanelCollapseSectionsOf([{ key: 'datasource', label: '数据源' }])
    expect(sections[0]).toEqual({ key: 'datasource', label: '数据源' })
    expect(sections.slice(1).map(({ key, parentKey }) => ({ key, parentKey }))).toEqual([
      { key: 'datasource.source', parentKey: 'datasource' },
      { key: 'datasource.collection', parentKey: 'datasource' },
      { key: 'datasource.request', parentKey: 'datasource' },
      ...['sina', 'eastmoney', 'sse', 'szse', 'bse', 'ths', 'ths_board', 'baostock'].map(source => ({ key: `datasource.source-${source}`, parentKey: 'datasource' })),
      { key: 'datasource.session', parentKey: 'datasource' },
    ])
  })

  it('配置中心登记与页面共享唯一两层关系，每个子分区归属于真实顶层组', () => {
    const sections = CONFIG_SYSTEM_COLLAPSE_SECTIONS
    const roots = new Set(sections.filter((section) => !section.parentKey).map((section) => section.key))
    expect(new Set(sections.map((section) => section.key)).size).toBe(sections.length)
    expect(roots.has('source-health')).toBe(true)
    for (const section of sections) {
      if (section.parentKey) expect(roots.has(section.parentKey)).toBe(true)
    }
  })
})
