const TRUSTED_DETAIL_RETURN_RE = new RegExp([
  '^/(?:limit-ladder|board|screen|trade-discipline)(?:\\?|$)',
  '^/system/config/score(?:\\?|$)',
  '^/(?:stocks|sectors)(?:/[^/?#]+)?(?:\\?|$)',
].join('|'))

/** 详情页只允许返回已知业务页，禁止持久化来源形成开放跳转。 */
export function trustedDetailReturnPath(value: unknown): string | undefined {
  if (typeof value !== 'string' || value.length > 2000) return undefined
  return TRUSTED_DETAIL_RETURN_RE.test(value) ? value : undefined
}

/**
 * 详情页返回按钮按已解析的可信业务地址展示目标名称。
 * 地址是否合法仍由各详情页自己的来源边界负责，本函数只统一文案映射。
 */
export function detailReturnLabel(returnPath: string | undefined, fallback: string): string {
  const path = returnPath?.split(/[?#]/, 1)[0]?.replace(/\/+$/, '') ?? ''
  if (path === '/limit-ladder') return '返回连板天梯'
  if (/^\/stocks\/[^/]+$/.test(path)) return '返回个股详情'
  if (path === '/stocks') return '返回个股查询'
  if (/^\/sectors\/[^/]+$/.test(path)) return '返回板块详情'
  if (path === '/sectors') return '返回板块行情'
  if (path === '/board') return '返回每日榜单'
  if (path === '/screen') return '返回策略筛选'
  if (path === '/trade-discipline') return '返回交易纪律'
  if (path === '/system/config/score') return '返回评分规则'
  return fallback
}
