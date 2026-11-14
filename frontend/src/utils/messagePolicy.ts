import type { MessageConfigContext } from 'element-plus'

/** 全应用消息条的展示策略；业务方只决定内容和级别，详细原因由页面记录承接。 */
export const APP_MESSAGE_POLICY: Readonly<MessageConfigContext> = Object.freeze({
  duration: 3000,
  showClose: false,
})
