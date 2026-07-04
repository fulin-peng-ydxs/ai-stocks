# CLAUDE.md

> 始终用简体中文与用户交互。命令、代码、日志和原文可保持原样。

## 入口职责

- 本文件只提供 Claude Code 的项目入口；仓库级规则以 [AGENTS.md](AGENTS.md) 为准。
- 产品概览和模块入口见 [README.md](README.md)。
- 模块技术细节见 [`agent-works/architecture/`](agent-works/architecture/)。
- 前端页面、布局和视觉规则见 [DESIGN.md](DESIGN.md) 与 [`page-template.md`](agent-works/configurable-layout-system/page-template.md)。

## 工作方式

- 改代码前先读 [AGENTS.md](AGENTS.md)、相关架构文档和同类实现；不要只凭历史记忆动手。
- 服务起停、端口、测试、构建和数据准备命令按 [AGENTS.md](AGENTS.md) 执行。
- 需求、计划、开发留痕、业务核查和 SQL 归档放入 `agent-works/{feature-slug}/`，同一功能复用同一目录。
- 涉及页面或交互时，先按 `DESIGN.md` 判断是否触发页面设计闭环和组件/布局维护矩阵。
- 不在用户未要求时提交或推送；不要把本地数据库、日志、个人配置或密钥纳入提交。

## Claude 记忆

- 本项目 Claude 记忆位于 `/Users/pengshuaifeng/.claude/projects/-Users-pengshuaifeng-ai-stocks/memory/`。
- 记忆只存仓库里不容易看出的用户偏好、决策原因、长期坑和事实源指针。
- 如果记忆与仓库代码或文档冲突，以仓库当前事实为准，并优先更新/删除过期记忆。
- 不把阶段流水、历史修复过程、测试数字快照或已沉淀到仓库的规则复制进记忆。
