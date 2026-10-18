export interface ReorderTreeItem { id: string; children: ReorderTreeItem[] }
export interface TreeDropTarget { id: string; position: 'before' | 'after' | 'inside' }

export function findTreeItem<T extends ReorderTreeItem>(items: T[], id: string): T | undefined {
  for (const item of items) {
    if (item.id === id) return item
    const child = findTreeItem(item.children as T[], id)
    if (child) return child
  }
}

export function treeSiblings<T extends ReorderTreeItem>(items: T[], id: string): T[] | undefined {
  if (items.some(item => item.id === id)) return items
  for (const item of items) {
    const siblings = treeSiblings(item.children as T[], id)
    if (siblings) return siblings
  }
}

export function treeRevision<T extends ReorderTreeItem>(items: T[]): unknown[] {
  return items.flatMap(item => [item, item.id, ...treeRevision(item.children)])
}

/** 在完整树的副本上移动，拒绝叶子容器、自己/后代与无变化目标，不提前改写业务树。 */
export function moveTreeItem<T extends ReorderTreeItem>(
  items: T[], sourceId: string, target: TreeDropTarget, canContain: (item: T) => boolean,
): T[] | null {
  const source = findTreeItem(items, sourceId), destination = findTreeItem(items, target.id)
  if (!source || !destination || sourceId === target.id || findTreeItem(source.children, target.id)) return null
  if (target.position === 'inside' && !canContain(destination)) return null
  const clone = (nodes: T[]): T[] => nodes.map(item => ({ ...item, children: clone(item.children as T[]) }))
  const next = clone(items)
  const siblings = treeSiblings(next, sourceId)!
  const [moved] = siblings.splice(siblings.findIndex(item => item.id === sourceId), 1)
  const targetItem = findTreeItem(next, target.id)!
  const targetSiblings = target.position === 'inside' ? targetItem.children as T[] : treeSiblings(next, target.id)!
  const index = target.position === 'inside' ? targetSiblings.length
    : targetSiblings.findIndex(item => item.id === target.id) + (target.position === 'after' ? 1 : 0)
  targetSiblings.splice(index, 0, moved!)
  const shape = (nodes: ReorderTreeItem[]): unknown[] => nodes.map(item => [item.id, shape(item.children)])
  return JSON.stringify(shape(items)) === JSON.stringify(shape(next)) ? null : next
}
