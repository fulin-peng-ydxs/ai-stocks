# 界面比例与自动缩放策略

本文说明自动比例公式、尺寸档案匹配、用户偏好同步及配置验证。实现入口为 `frontend/src/layout/displayScalePolicy.ts`、`displayScaleProfiles.ts` 和 `frontend/src/composables/useDisplayScale.ts`。

参考：[设计规范](../../DESIGN.md) · [前端布局实现](../architecture/frontend-layout.md) · [环境配置](../architecture/environment-configuration.md) · [页面检查](responsive-pages.md) · [组件清单](responsive-components.md)。

## 自动比例

自动缩放指数是系统外观配置 `ui.display.auto_scale_exponent`，默认 `0.10`，范围 `0～1`，设置步长 `0.01`；缺项或非法运行时值回退默认。保存与首屏缓存恢复均应用同一指数，手动模式不受指数变化影响。它不属于视觉预设，切换颜色或圆角预设不得改变界面比例策略。

计算为 `round(100 × (屏幕可用 CSS 面积 / (2560 × 1440)) ^ 指数)`，结果限制在 90%～110%。指数为零时自动比例保持 100%。1920×1080 可用面积在默认指数下为 94%，2560×1440 为 100%，3360×1890 为 106%。

## 自定义尺寸档案

自定义比例为 `50%～150%`，按 `1%` 微调；100% 表示原始设计尺寸。「恢复100%」进入自定义模式。

- 用户调整自定义比例时保存 `{width, height, percent}`；尺寸来源与自动模式相同，不使用物理像素、DPR、设备名称或浏览器窗口尺寸。
- 当前宽高均在档案 `±15%` 内时采用综合相对距离最近的档案；`5%` 内重复调整更新原档案，无匹配时回退最近一次自定义比例。
- 从自动切到自定义时继承当前自动比例并保存当前尺寸档案；恢复 100% 同样更新当前档案。
- 档案仅属于当前用户，不直接暴露档案管理界面；随既有 `display-scale` 全局用户偏好同步到 PostgreSQL；旧偏好没有档案时保持原 `customPercent` 行为。

## 配置闭环

- 系统设置表单由 `backend/storage/app_config.py` 元数据驱动，沿用现有系统设置权限、API、审计和 `app_config` 覆盖层。
- 后端只接受范围内有限数值，拒绝布尔值、无法转换的字符串、越界和非有限数值。
- 登录公开配置以独立字段 `auto_scale_exponent` 下发，登录前后共用；本地安全缓存用于接口暂时不可用时的首屏恢复。
- 历史预设字段在幂等迁移中导入该系统配置；优先使用启用的内置预设值，缺失时使用 `0.10`。

## 应用缩放、坐标与浮层

`useDisplayScale` 通过根级 `--app-display-scale` 让 `#app` 以左上角为原点整体 `zoom`，统一缩放字体、控件、间距、图表容器及应用内浮层。尺寸输入使用操作系统折算后的当前屏幕可用 CSS 宽高，不枚举设备或分辨率档位；物理像素、DPR 和浏览器页级缩放不能作为目标比例。

浏览器已经按 `zoom` 折算布局画布，不再叠加倒数宽高补偿。布局宽高、滚动量和组件配置使用 `client/offset` 布局像素；只有命中测试、指针位置和视口对齐使用 `getBoundingClientRect/clientX/clientY`，两者相减后经 `displayScaleGeometry.ts` 共享工具换回布局像素。比例变化须触发依赖尺寸的画布重测。

Tooltip、Popover、Select、DatePicker 等 Popper 浮层通过应用级唯一容器入口挂入 `#app`，与触发器共用原生 `zoom` 坐标系；依赖层可通过锁版本补丁将视口裁剪边界换入布局坐标，页面不得增加私有补偿、二次缩放或逐个关闭 Teleport。Dialog、Drawer、MessageBox 的 body 级遮罩复用整体 `zoom`，内部面板不重复缩放，全屏抽屉高度与弹窗上限服从该画布。Message、Notification 按浏览器视口堆叠并保持自身 100% 比例。股票图表的 HTML 行情浮层使用独立的 body 浮层适配。

## 验证

- 前端覆盖自动比例、非法值回退、手动模式隔离、尺寸档案匹配与首屏缓存恢复。
- 后端覆盖元数据默认值、值域校验、公开读取白名单和旧预设迁移。
