// 侧边导航菜单的唯一数据源：新增/调整菜单只改这里，SideMenu 据此渲染。
// 约定：有 children 的节点是分组（点击标题仅展开/折叠，不导航）；叶子节点的 index 即路由路径。
export interface MenuNode {
  /** 分组用稳定别名（如 'quotes'）；叶子用路由路径（如 '/stocks'） */
  index: string
  title: string
  icon?: string
  children?: MenuNode[]
}

export const menuConfig: MenuNode[] = [
  {
    index: 'quotes',
    title: '最新行情',
    icon: '📈',
    children: [
      { index: '/stocks', title: '个股行情' },
      { index: '/board', title: '每日榜单' },
    ],
  },
  { index: '/screen', title: '策略筛选', icon: '🧮' },
  { index: '/backtest', title: '策略回测', icon: '🧪' },
  { index: '/training', title: '盘感训练', icon: '🎮' },
  {
    index: 'data',
    title: '数据管理',
    icon: '🗄️',
    children: [
      { index: '/data/overview', title: '数据概览' },
      { index: '/data/quality', title: '数据质量' },
      { index: '/data/ingest', title: '数据采集' },
      { index: '/data/schedule', title: '任务调度' },
    ],
  },
  {
    index: 'system',
    title: '系统管理',
    icon: '⚙️',
    children: [
      { index: '/system/config', title: '配置管理' },
      {
        index: 'layout',
        title: '布局配置',
        icon: '🎨',
        children: [
          { index: '/system/layout/presets', title: '预设管理' },
          { index: '/system/layout/pages', title: '页面布局' },
          { index: '/system/layout/components', title: '系统组件' },
        ],
      },
    ],
  },
]

/** 找到目标叶子节点的祖先分组链（用于默认只展开当前路由所在的分组）。 */
export function findOpenPath(target: string, nodes: MenuNode[] = menuConfig, trail: string[] = []): string[] {
  for (const node of nodes) {
    if (node.children?.length) {
      const found = findOpenPath(target, node.children, [...trail, node.index])
      if (found.length) return found
    } else if (node.index === target) {
      return trail
    }
  }
  return []
}
