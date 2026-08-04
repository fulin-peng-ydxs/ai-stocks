# 验证：榜单页「默认加载方案」

> 验证日期 2026-08-04。环境：后端 `127.0.0.1:8000` 运行中；前端 Vite 专用预览端口 `5181`；调试账号 `debug_board_only`（`debug_tenant`，角色 `debug_role_board_only`：仅 `board:view`，无 `score-profile:save`——无自己的评分方案且无复制权限，正好覆盖「无方案」前提）。

## 自动化

| 项 | 结果 |
|----|------|
| `vue-tsc -b` 类型检查 | 通过（无输出） |
| `AssetSearchDrawer.spec.ts` | 17 passed（含新增 2：未传 `setDefaultItem` 不渲染默认动作；传入后渲染+点击上送行+互斥切换「取消默认」+取消上送 null） |
| `AssetProfileSelect.spec.ts` | 10 passed（回归） |
| `npm run build`（vue-tsc + vite build） | 成功，`frontend/dist` 与源码同步 |

> 注：跑单测遇到 `ERR_MODULE_NOT_FOUND`，是后台 shell 漂移到仓库根 + node18 所致的环境问题，与本次改动无关；在 `frontend/` 目录用项目 node 直接跑 `node_modules/vitest/vitest.mjs` 即正常。

## 浏览器预览（preview 工具，端口 5181）

| 场景 | 操作 | 结果 |
|------|------|------|
| 无方案+未设默认 | 登录后进 `/board` | 空态「暂无可用评分方案」，无报错 ✅ |
| 设默认 | 打开抽屉（系统内置段），点「设为默认加载方案」 | 行变「取消默认」，toast 成功；localStorage + 远端 `user_preference` 均写入 summary 快照 ✅ |
| 自动装载 | 刷新页面（仍无自己方案） | 下拉自动装入「默认趋势分 v1 系统内置」，标题显示规则名+版本，榜单刷新出 50 行，cache_status=已更新 ✅ |
| 递归陷阱 | 全程观察 console | 无 error/warn，无 ElSelect 递归/超限告警 ✅ |
| 取消默认 | 抽屉点「取消默认」 | 偏好清空（本地+远端），行恢复「设为默认加载方案」 ✅ |
| 取消后刷新 | 再次刷新 | 回到空态「暂无可用评分方案」 ✅ |

## 未覆盖（说明原因）

- **「有自己的方案时默认被忽略」（R5）**：当前 `debug_board_only` 无 `score-profile:save`，无法在 UI 复制出自己的方案来实测该分支；但代码守卫为 `tryApplyDefault` 的 `if (profiles.value.length) return` 与 `onProfilesReady` 的「自动选中我的第一个」优先，逻辑直白。可用一个有 `score-profile:save` 的普通账号（如 `debug_normal`）补测：复制一个方案→再进榜单页应自动选中「我的第一个」而非默认。
- **失效兜底（R6）**：需把已设默认的方案取消公开/删除后刷新验证自清，涉及改动他人资产可见性，未在共享调试库执行；逻辑在 `load()` catch 的 `pendingDefaultKey` 命中分支。
- **无 `board:view` 权限态**：`debug_board_only` 本身有 `board:view`；无权分支由 `canViewBoardProfiles` 守卫，未单独用零权限账号实测。
