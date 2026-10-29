"""实际来源的稳定额度组；接入器、能力展示和配置 schema 共用，导入不访问存储。"""

BAOSTOCK_MAX_CONCURRENCY = 4

SOURCE_GROUPS = {
    "sina": {"label": "新浪", "domains": ("sina.com.cn", "sina.cn"), "serial": False},
    "eastmoney": {"label": "东方财富", "domains": ("eastmoney.com",), "serial": False},
    "sse": {"label": "上交所", "domains": ("sse.com.cn",), "serial": False},
    "szse": {"label": "深交所", "domains": ("szse.cn",), "serial": False},
    "bse": {"label": "北交所资料接口", "domains": ("bse.cn",), "serial": False},
    "ths": {"label": "同花顺分时", "domains": (), "serial": False},
    "ths_board": {"label": "同花顺板块", "domains": (), "serial": False},
    # SDK会话在进程内互斥；独立进程也受同一个来源频率和总网络额度约束。
    "baostock": {"label": "BaoStock", "domains": (), "serial": False,
                 "max_concurrency": BAOSTOCK_MAX_CONCURRENCY},
}
