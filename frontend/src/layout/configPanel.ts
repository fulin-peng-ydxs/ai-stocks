export interface ConfigPanelBehavior {
  collapsibleSections: boolean
  defaultCollapsed: string[]
  showGroupDescription: boolean
  showSectionDescription: boolean
}

export interface ConfigFieldSection {
  key: string
  title: string
  hint?: string
  fieldPaths: string[]
  defaultOpen?: boolean
}

export interface ConfigPanelGroupSummary {
  key: string
  label: string
}

export interface ConfigSystemGroupTab {
  key: string
  label: string
  groupKeys: string[]
}

export interface ConfigPanelCollapseSection {
  key: string
  label: string
  /** 配置面板为组/分区两层；省略表示顶层组，子分区明确引用所属组。 */
  parentKey?: string
}

export const CONFIG_SYSTEM_GROUP_TABS: ConfigSystemGroupTab[] = [
  { key: 'access', label: '访问安全', groupKeys: ['auth'] },
  { key: 'data-governance', label: '数据治理', groupKeys: ['datasource', 'ths_board', 'audit'] },
  { key: 'research-runtime', label: '研究运行', groupKeys: ['cost'] },
]

export const CONFIG_SYSTEM_GROUPS: ConfigPanelGroupSummary[] = [
  { key: 'auth', label: '认证与防滥用' },
  { key: 'datasource', label: '数据源' },
  { key: 'ths_board', label: '同花顺板块' },
  { key: 'audit', label: '审计设置' },
  { key: 'cost', label: '回测成本' },
]

export const CONFIG_SYSTEM_GROUP_SECTIONS: Record<string, ConfigFieldSection[]> = {
  auth: [
    {
      key: 'login',
      title: '登录保护',
      hint: '控制登录页验证码和登录接口限流。',
      fieldPaths: [
        'auth.login_captcha_enabled',
        'auth.captcha_after_fails',
        'auth.login_rate_per_min',
      ],
    },
    {
      key: 'register',
      title: '注册校验',
      hint: '控制自助注册校验和注册接口限流。',
      fieldPaths: [
        'auth.require_email_code',
        'auth.register_rate_per_hour',
      ],
    },
    {
      key: 'email-code',
      title: '邮箱验证码发送',
      hint: '控制邮箱验证码按邮箱和 IP 的发送频率。',
      fieldPaths: [
        'auth.email_code_rate_per_hour',
        'auth.email_code_ip_rate_per_hour',
      ],
    },
  ],
  datasource: [
    {
      key: 'source',
      title: '行情接入选择',
      hint: '只控制支持主备切换的行情能力，实际来源及用途见来源能力与健康。',
      fieldPaths: ['datasource.primary', 'datasource.fallback'],
    },
    {
      key: 'collection',
      title: '采集规模',
      hint: '任务启动时确定范围和并发；任务参数可覆盖默认值，来源串行限制优先。',
      fieldPaths: ['datasource.history_years', 'datasource.update_concurrency'],
    },
    {
      key: 'request',
      title: '通用请求规则',
      hint: '行情、股本、估值、分时、板块、修复和测试共用。下一次请求读取新值，在途请求不变。',
      fieldPaths: [
        'datasource.rate_limit_per_sec',
        'datasource.socket_timeout_sec',
        'datasource.max_retries',
        'datasource.retry_backoff_sec',
      ],
    },
    { key: 'session', title: 'BaoStock 会话规则', hint: '共享登录会话强制串行；登录完成后使用通用请求超时。', fieldPaths: ['datasource.baostock_login_timeout_sec'] },
  ],
  ths_board: [
    { key: 'rate', title: '来源频率限制', hint: '与通用频率取更严格值；板块会话保持串行。', fieldPaths: ['ths_board.min_interval_sec'] },
    { key: 'collection', title: '成分采集规则', fieldPaths: ['ths_board.member_update_interval_days'] },
    { key: 'credential', title: '访问凭据', fieldPaths: ['ths_board.login_cookie', 'ths_board.cookie_validity_days'] },
    {
      key: 'compatibility',
      title: '旧请求覆盖',
      hint: '已有自定义值继续生效；关闭单独设置并保存后继承通用规则。',
      defaultOpen: false,
      fieldPaths: [
        'ths_board.timeout_sec',
        'ths_board.max_retries',
        'ths_board.retry_backoff_sec',
      ],
    },
  ],
  audit: [
    {
      key: 'retention',
      title: '日志留存',
      hint: '控制审计页默认查询窗口和自动清理周期。',
      fieldPaths: ['audit.retention_days'],
    },
  ],
  cost: [
    {
      key: 'fee',
      title: '交易费率',
      hint: '控制回测买卖成交时计入的费用比例。',
      fieldPaths: [
        'backtest.cost.commission_rate',
        'backtest.cost.stamp_tax_rate',
      ],
    },
    {
      key: 'execution',
      title: '成交偏移',
      hint: '控制回测成交价相对开盘价的方向性偏移。',
      fieldPaths: ['backtest.cost.slippage'],
    },
  ],
}

export function configPanelSectionsOf(groupKey: string): ConfigFieldSection[] {
  return CONFIG_SYSTEM_GROUP_SECTIONS[groupKey] ?? []
}

export function configPanelCollapseSectionsOf(
  groups: readonly ConfigPanelGroupSummary[],
): ConfigPanelCollapseSection[] {
  return groups.flatMap((group) => [
    { key: group.key, label: group.label },
    ...configPanelSectionsOf(group.key).map((section) => ({
      key: `${group.key}.${section.key}`,
      label: section.title,
      parentKey: group.key,
    })),
  ])
}

export const CONFIG_SYSTEM_COLLAPSE_SECTIONS = [
  { key: 'source-health', label: '数据源能力与健康' },
  ...configPanelCollapseSectionsOf(CONFIG_SYSTEM_GROUPS),
]
