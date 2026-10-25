# CLAUDE.md

> 始终用简体中文与用户交互。命令、代码、日志和原文可保持原样。

## 入口职责

- 本文件只提供 Claude Code 的项目入口；仓库级开发规则以 [AGENTS.md](AGENTS.md) 为准。
- 产品概览和模块入口见 [README.md](README.md)。
- 模块技术细节见 [`agent-works/architecture/`](agent-works/architecture/)；个股与板块数据采集分别见 [`stock-collection.md`](agent-works/architecture/stock-collection.md) 和 [`board-collection.md`](agent-works/architecture/board-collection.md)。
- 环境变量、变量文件和配置覆盖层见 [`environment-configuration.md`](agent-works/architecture/environment-configuration.md)。
- 前端页面、布局和视觉规则见 [DESIGN.md](DESIGN.md) 与 [`page-template.md`](agent-works/configurable-layout-system/page-template.md)。
- 本文件仅维护 Claude 入口和记忆使用边界；项目规则、实现事实或阶段验证结果分别更新上述来源及当次交付，不复制到此处。

## 工作方式

- 改动前读取 [AGENTS.md](AGENTS.md)、相关事实源及同类实现；服务、测试、归档和提交统一遵守 AGENTS，不在此维护第二套执行规则。
- 页面任务按 [DESIGN.md](DESIGN.md#9-ai-开发入口) 进入页面模板；记忆不得替代当前仓库事实。

## Claude 记忆

- 本项目 Claude 记忆位于 `/Users/pengshuaifeng/.claude/projects/-Users-pengshuaifeng-ai-stocks/memory/`。
- 记忆只存仓库里不容易看出的用户偏好、决策原因、长期坑和事实源指针。
- 如果记忆与仓库代码或文档冲突，以仓库当前事实为准，并优先更新/删除过期记忆。
- 不把阶段流水、历史修复过程、测试数字快照或已沉淀到仓库的规则复制进记忆。
