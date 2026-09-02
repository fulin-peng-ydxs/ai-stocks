/**
 * 为同一数据区域分配单调递增的请求序号，只允许最后启动的请求提交页面状态。
 * 网络请求本身可以并发；消费方在写入结果、错误和 loading 前检查 isCurrent。
 */
export function createLatestRequestGuard() {
  let currentId = 0
  return {
    begin(): number {
      currentId += 1
      return currentId
    },
    isCurrent(requestId: number): boolean {
      return requestId === currentId
    },
    invalidate(): void {
      currentId += 1
    },
  }
}
