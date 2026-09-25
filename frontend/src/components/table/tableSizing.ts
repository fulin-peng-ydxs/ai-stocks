/**
 * 长文档中的嵌入表格：少量行自然撑高，超过可读区后由表体内部滚动。
 * 使用布局容器高度而不是浏览器视口，确保界面缩放与 LayoutHost 使用同一坐标系。
 */
export const LONG_DOCUMENT_TABLE_MAX_HEIGHT = 'clamp(320px, 42cqh, 440px)'

/**
 * 纵向混合工作台中位于成长主区之前的主业务表。
 * 它需要比局部编辑表保留更多连续阅读空间，同时为末尾 growMain 留出最低可用区。
 */
export const LEADING_WORKBENCH_TABLE_MAX_HEIGHT = 'clamp(640px, 72cqh, 960px)'
