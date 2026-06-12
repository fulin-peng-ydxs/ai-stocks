---
name: feedback_build_after_change
description: 每次前端代码改动后必须执行构建
metadata:
  type: feedback
---

每次修改前端代码后，必须执行 `cd frontend && npm run build` 构建。

**Why:** 用户明确要求，每次改了都要构建。

**How to apply:** 任何 frontend/src 下的文件改动完成后，立即执行构建，不需要用户提醒。
