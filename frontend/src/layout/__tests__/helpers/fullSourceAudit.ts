// 全树源码集成检查包含 Vue/TS/CSS 解析与违规反例，不是业务响应延迟断言。
// 为 Linux Actions 双工作进程 + V8 覆盖率下的全树解析保留有界预算。
// 仅供显式扫描生产源码树的用例使用；普通单元测试继续采用 Vitest 默认时限。
export const FULL_SOURCE_AUDIT_TIMEOUT_MS = 120_000
