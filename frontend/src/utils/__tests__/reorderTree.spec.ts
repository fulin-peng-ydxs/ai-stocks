import { describe, expect, it } from 'vitest'
import { moveTreeItem } from '../reorderTree'

interface Item { id: string; group: boolean; children: Item[] }
const leaf = (id: string): Item => ({ id, group: false, children: [] })
const sample = (): Item[] => [
  { id: 'g1', group: true, children: [leaf('a'), leaf('b')] },
  { id: 'g2', group: true, children: [leaf('c')] },
]
const canContain = (item: Item) => item.group
describe('树移动边界', () => {
  it('同级前后排序不改变原树及节点集合', () => {
    const original = sample()
    const next = moveTreeItem(original, 'a', { id: 'b', position: 'after' }, canContain)!
    expect(next[0].children.map(item => item.id)).toEqual(['b', 'a'])
    expect(original[0].children.map(item => item.id)).toEqual(['a', 'b'])
    expect(next[1]).toEqual(original[1])
  })
  it('允许跨分组移入及移出到根层，携带完整子树', () => {
    const original = sample()
    const next = moveTreeItem(original, 'g1', { id: 'g2', position: 'inside' }, canContain)!
    expect(next.map(item => item.id)).toEqual(['g2'])
    expect(next[0].children[1].children.map(item => item.id)).toEqual(['a', 'b'])
    const root = moveTreeItem(original, 'a', { id: 'g2', position: 'before' }, canContain)!
    expect(root.map(item => item.id)).toEqual(['g1', 'a', 'g2'])
  })
  it.each([
    ['g1', 'a', 'inside'], ['g1', 'a', 'after'], ['a', 'a', 'before'],
    ['a', 'b', 'inside'], ['a', 'b', 'before'], ['b', 'g1', 'inside'],
    ['missing', 'g1', 'inside'], ['a', 'missing', 'before'],
  ] as const)('拒绝无效或无变化移动 %s → %s/%s', (source, id, position) => {
    expect(moveTreeItem(sample(), source, { id, position }, canContain)).toBeNull()
  })
})
