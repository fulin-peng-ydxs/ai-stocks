// 这些集成用例解析整个生产源码树并验证违规材料，实测约 13 秒；V8 采集下约 38 秒。
// 单独给予有界的文件树扫描预算；普通单元测试仍使用 Vitest 默认时限，业务断言不变。
export const FULL_SOURCE_AUDIT_TIMEOUT_MS = 60_000
