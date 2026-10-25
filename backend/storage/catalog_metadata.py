"""数据资产目录的稳定元数据契约与字段中文化工具。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

FreshnessMode = Literal["not_applicable", "direct", "snapshot", "snapshot_child"]
FreshnessComparison = Literal["equal", "not_before"]
QualityMode = Literal["not_applicable", "issue_types", "all_issues", "pending_outbox"]
FieldMetadataSource = Literal["explicit", "database_comment", "glossary", "generated", "fallback"]


@dataclass(frozen=True)
class FreshnessPolicy:
    """表级鲜活度策略；不适用也必须显式声明。"""

    mode: FreshnessMode
    column: str | None = None
    baseline: str | None = None
    comparison: FreshnessComparison | None = None


@dataclass(frozen=True)
class QualityPolicy:
    """表级质量统计策略；不适用与已检查零问题必须可区分。"""

    mode: QualityMode
    issue_types: tuple[str, ...] = ()
    status_column: str | None = None
    pending_value: str | None = None


@dataclass(frozen=True)
class TableAssetMeta:
    """一张逻辑表必须具备的业务元数据。"""

    database: Literal["duckdb", "postgres"]
    table: str
    name_cn: str
    category: str
    purpose: str
    ownership_scope: str
    data_source: str
    relations: tuple[str, ...]
    freshness: FreshnessPolicy
    quality: QualityPolicy


FRESHNESS_NOT_APPLICABLE = FreshnessPolicy(mode="not_applicable")
QUALITY_NOT_APPLICABLE = QualityPolicy(mode="not_applicable")


# 字段名优先读取表级显式注解，其次使用本词典；复合字段再按 token 生成。
# 未识别 token 不做伪翻译，而是保留 fallback 并交给目录契约阻断。
FIELD_LABELS: dict[str, str] = {
    "initialized_on": "账本起算交易日",
    "opening_positions": "期初持仓快照",
    "opening_cash": "期初现金",
    "withdrawn": "已撤回",
    "max_positions": "最大同时持仓数",
    "peak_positions": "当日最大同时持仓数",
    "price_min": "股价下限",
    "price_max": "股价上限",
    "st_filter": "ST选股条件",
    "loss_filter": "亏损选股条件",
    "st_risk_filter": "ST风险选股条件",
    "selection_facts": "选股事实快照",
    "checklist_items": "选股分类检查项",
    "checklist_results": "选股逐项核对结果",
    "id": "标识",
    "key": "键",
    "code": "代码",
    "name": "名称",
    "name_cn": "中文名称",
    "title": "标题",
    "description": "说明",
    "descr": "说明",
    "detail": "详情",
    "message": "消息",
    "note": "备注",
    "value": "值",
    "type": "类型",
    "status": "状态",
    "source": "来源",
    "quality": "质量",
    "version": "版本",
    "revision": "修订号",
    "seq": "序号",
    "rank": "排名",
    "score": "评分",
    "amount": "金额",
    "price": "价格",
    "shares": "股数",
    "pnl": "盈亏",
    "ts": "时间戳",
    "field": "字段",
    "table": "表",
    "tables": "表集合",
    "rows": "行数",
    "items": "明细项",
    "config": "配置",
    "params": "参数",
    "result": "结果",
    "extra": "扩展信息",
    "snapshot": "快照",
    "signature": "签名",
    "visibility": "可见范围",
    "n_positions": "持仓数量",
    "max_dd_days": "最大回撤天数",
    "hit_rate_by_grade": "分等级命中率",
    "grade_thresholds": "等级阈值",
    "sub_scores": "分项评分",
    "n_rounds": "回合数量",
    "initial_capital": "初始资金",
    "n_codes": "股票数量",
    "window_metadata_json": "窗口元数据",
    "action_subtype": "动作子类型",
    "action_subtype_label": "买卖类型名称快照",
    "display_order": "展示顺序",
    "normalized_name": "规范化名称",
    "submission_source": "提交来源",
    "checkin_id": "打卡标识",
    "no_operation": "是否无操作",
    "violation_detail": "违规详情",
    "violation_items": "未履约事项",
    "compliance_status": "合规状态",
    "effective_from_trade_date": "生效交易日",
    "next_activation_seq": "下次启用序号",
    "draft_revision": "草稿修订号",
    "claimed_name": "占用名称",
    "published_by": "发布人",
    "actor_user_id": "操作人用户标识",
    "actor_account": "操作人账号",
    "resource_code": "资源代码",
    "target_label": "目标标签",
    "duration_ms": "耗时毫秒",
    "command_id": "命令标识",
    "request_ip": "请求网络地址",
    "request_method": "请求方法",
    "request_path": "请求路径",
    "request_id": "请求标识",
    "param_hash": "参数哈希",
    "route_path": "路由路径",
    "menu_id": "菜单标识",
    "api_method": "API 方法",
    "api_path": "API 路径",
    "is_locked": "是否锁定",
    "role_id": "角色标识",
    "resource_id": "资源标识",
    "admin_user_id": "管理员用户标识",
    "password_hash": "密码哈希",
    "role_code": "角色代码",
    "perm_ver": "权限版本",
}

FIELD_TOKENS: dict[str, str] = {
    "actual": "实际", "add": "加入", "affected": "影响", "allowed": "允许",
    "annual": "年化", "attempt": "尝试", "auto": "自动", "avg": "平均",
    "backstop": "兜底", "base": "基准", "benchmark": "基准", "board": "板块",
    "buy": "买入", "calmar": "卡玛比率", "cancel": "取消", "captured": "采集",
    "cash": "现金", "categories": "分类集合", "category": "分类", "chain": "链路",
    "change": "变更", "changed": "变更", "close": "收盘", "color": "颜色",
    "completed": "完成", "component": "组件", "computed": "计算", "confirmed": "确认",
    "consecutive": "连续", "cost": "成本", "count": "数量", "coverage": "覆盖",
    "cur": "当前", "current": "当前", "cursor": "游标", "date": "日期",
    "day": "日", "days": "天数", "decide": "决策", "default": "默认",
    "delay": "延迟", "dependency": "依赖", "dimension": "维度", "direction": "方向",
    "dispatched": "派发", "drawdown": "回撤", "dtype": "数据类型", "due": "到期",
    "enabled": "是否启用", "end": "结束", "entry": "入场", "equity": "权益",
    "event": "事件", "excess": "超额", "execution": "执行", "exit": "退出",
    "expression": "表达式", "factor": "因子", "failure": "失败", "fee": "费用",
    "fetched": "获取", "fill": "成交", "filters": "筛选条件", "final": "最终",
    "finished": "结束", "fingerprint": "指纹", "flags": "标记", "from": "起始",
    "freq": "频率", "grade": "等级", "group": "分组", "hands": "换手",
    "has": "是否有", "hit": "命中", "hold": "持有", "idx": "索引",
    "industry": "行业", "initial": "初始", "invalid": "失效", "is": "是否",
    "job": "调度任务", "json": "JSON", "kind": "种类", "last": "最近",
    "layer": "层级", "layers": "层级集合", "level": "级别", "limit": "涨跌停",
    "matched": "匹配", "max": "最大", "mode": "模式", "model": "模型",
    "n": "数量", "new": "新", "no": "编号", "old": "原", "one": "一字",
    "only": "仅限", "page": "页面", "parent": "父级", "pending": "待处理",
    "pick": "入选", "point": "点位", "pool": "候选池", "pos": "持仓",
    "position": "持仓", "preset": "预设", "profile": "方案", "profit": "盈利",
    "progress": "进度", "range": "区间", "rate": "比例", "realized": "已实现",
    "reason": "原因", "ref": "引用", "rel": "相对", "requested": "请求",
    "retry": "重试", "return": "收益", "review": "复核", "risk": "风险",
    "round": "回合", "rule": "规则", "run": "运行", "saved": "保存",
    "schema": "结构", "scope": "范围", "sell": "卖出", "session": "会话",
    "side": "方向", "snapshot": "快照", "sortino": "索提诺比率", "st": "ST",
    "stale": "是否滞后", "start": "开始", "stock": "股票", "sub": "子项",
    "success": "成功", "summary": "摘要", "target": "目标", "task": "任务",
    "total": "总计", "trade": "交易", "trades": "交易数", "trading": "交易",
    "tree": "规则树", "trigger": "触发", "up": "上涨", "upstream": "上游",
    "user": "用户", "vol": "波动率", "win": "胜率", "window": "窗口",
    "word": "板", "at": "时间",
    "account": "账号", "action": "动作", "activation": "启用", "active": "有效",
    "audit": "审计", "builtin": "内置", "condition": "条件", "data": "数据",
    "error": "错误", "history": "历史", "open": "开启", "owner": "所有者",
    "ratio": "占比", "refresh": "刷新", "time": "时间", "updated": "更新",
    "created": "创建", "member": "成员", "latest": "最新", "meta": "元数据",
    "metric": "指标", "flow": "流", "inflow": "流入", "outflow": "流出",
    "net": "净额", "leader": "领涨", "pct": "比例", "exchange": "交易所",
    "list": "上市", "delist": "退市", "float": "流通", "share": "股本",
    "concept": "概念", "pre": "前", "volume": "成交量", "suspended": "停牌",
    "turnover": "换手率", "ohl": "开高低", "detected": "检出", "resolved": "解决",
    "ignore": "忽略", "issue": "问题", "severity": "严重度", "app": "应用",
    "first": "首次", "seen": "观测",
    "algorithm": "算法", "confidence": "可信度", "fallback": "回退",
    "sample": "样本", "approx": "近似", "input": "输入",
    "source": "来源", "version": "版本", "status": "状态",
    "calendar": "日历", "suspension": "停牌", "basic": "基础",
    "metrics": "指标", "bar": "行情", "index": "指数", "fund": "资金",
    "correlation": "相关性", "invalidation": "失效", "outbox": "发件箱",
    "positions": "持仓数量", "dd": "回撤", "sharpe": "夏普比率",
    "thresholds": "阈值", "scores": "分项评分", "rounds": "回合数量",
    "capital": "资金", "codes": "股票数量", "metadata": "元数据",
    "subtype": "子类型", "content": "内容", "display": "展示", "order": "顺序",
    "normalized": "规范化", "submitted": "提交", "amended": "修订",
    "submission": "提交", "checkin": "打卡", "assessment": "评估",
    "operation": "操作", "violation": "违规", "quantity": "数量",
    "operated": "操作", "compliance": "合规", "deleted": "删除",
    "next": "下次", "occurred": "发生", "activated": "启用",
    "effective": "生效", "proposed": "拟定", "claimed": "占用",
    "published": "发布", "marker": "标记", "state": "状态", "details": "详情",
    "applied": "应用", "by": "操作人", "actor": "操作人", "resource": "资源",
    "label": "标签", "ip": "网络地址", "method": "方法", "path": "路径",
    "duration": "耗时", "ms": "毫秒", "context": "上下文", "changes": "变更内容",
    "command": "命令", "payload": "载荷", "delivered": "投递",
    "pref": "偏好", "added": "加入", "param": "参数", "hash": "哈希",
    "route": "路由", "icon": "图标", "sort": "排序", "visible": "是否可见",
    "menu": "菜单", "api": "API", "locked": "锁定", "role": "角色",
    "tenant": "租户", "admin": "管理员", "email": "邮箱", "password": "密码",
    "perm": "权限", "login": "登录", "remark": "备注",
}


def resolve_field_metadata(
    *,
    name: str,
    table_name_cn: str,
    explicit_name: str | None,
    explicit_desc: str | None,
    database_comment: str | None,
    primary_key: bool,
    reference: str | None,
    glossary_name: str | None = None,
    glossary_desc: str | None = None,
) -> dict[str, str | bool]:
    """按显式注解、数据库注释、词典和组合生成的顺序解析字段展示元数据。"""

    if explicit_name and explicit_name != name:
        name_cn = explicit_name
        name_source: FieldMetadataSource = "explicit"
        name_complete = True
    elif glossary_name and glossary_name != name:
        name_cn = glossary_name
        name_source = "glossary"
        name_complete = True
    elif name in FIELD_LABELS:
        name_cn = FIELD_LABELS[name]
        name_source = "glossary"
        name_complete = True
    else:
        tokens = name.split("_")
        translated = [FIELD_TOKENS.get(token) or FIELD_LABELS.get(token) for token in tokens]
        if all(translated):
            name_cn = "".join(str(item) for item in translated)
            name_source = "generated"
            name_complete = True
        else:
            name_cn = name
            name_source = "fallback"
            name_complete = False

    if explicit_desc:
        desc = explicit_desc
        desc_source: FieldMetadataSource = "explicit"
    elif database_comment:
        desc = database_comment
        desc_source = "database_comment"
    elif glossary_desc:
        desc = glossary_desc
        desc_source = "glossary"
    elif name_complete:
        suffixes: list[str] = []
        if primary_key:
            suffixes.append("主键")
        if reference:
            suffixes.append(f"关联 {reference}")
        suffix = f"；{'；'.join(suffixes)}" if suffixes else ""
        desc = f"{table_name_cn}中的{name_cn}字段{suffix}。"
        desc_source = "generated"
    else:
        desc = ""
        desc_source = "fallback"

    return {
        "name_cn": name_cn,
        "desc": desc,
        "name_source": name_source,
        "description_source": desc_source,
        "metadata_complete": name_complete and bool(desc),
    }
