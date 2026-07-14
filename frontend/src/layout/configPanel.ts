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
}

export const CONFIG_SYSTEM_GROUP_TABS: ConfigSystemGroupTab[] = [
  { key: 'access', label: '访问安全', groupKeys: ['auth'] },
  { key: 'data-governance', label: '数据治理', groupKeys: ['datasource', 'audit'] },
  { key: 'research-runtime', label: '研究运行', groupKeys: ['cost'] },
]

export const CONFIG_SYSTEM_GROUPS: ConfigPanelGroupSummary[] = [
  { key: 'auth', label: '认证与防滥用' },
  { key: 'datasource', label: '数据源' },
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
      title: '数据源选择',
      hint: '控制主备公开行情数据源。',
      fieldPaths: ['datasource.primary', 'datasource.fallback'],
    },
    {
      key: 'collection',
      title: '采集规模',
      hint: '控制历史覆盖范围和单次采集任务并发。',
      fieldPaths: ['datasource.history_years', 'datasource.update_concurrency'],
    },
    {
      key: 'request',
      title: '请求容错',
      hint: '控制外部数据请求的限流、超时、重试和退避。',
      fieldPaths: [
        'datasource.rate_limit_per_sec',
        'datasource.socket_timeout_sec',
        'datasource.max_retries',
        'datasource.retry_backoff_sec',
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
    })),
  ])
}

export const CONFIG_SYSTEM_COLLAPSE_SECTIONS = configPanelCollapseSectionsOf(CONFIG_SYSTEM_GROUPS)
