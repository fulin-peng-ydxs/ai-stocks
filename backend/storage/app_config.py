"""配置覆盖层（DM-D2/D3，FR-DM-12）。

Web 表单改的参数写 `app_config` 表（点分路径 → JSON 值），settings.yaml 仅作默认兜底；
读取时覆盖层优先（见 backend.config.settings.get_effective_settings）。

只允许白名单内的真实可调参数被覆盖（R-DM-5）——评分权重/分档阈值已被 score_profile 取代，
不进白名单。每个字段带类型与范围规则，保存时逐项校验。
"""

from __future__ import annotations

import json
from datetime import datetime

from backend.common.logging import get_logger
from backend.storage.duckdb_client import DuckDBClient, get_client

log = get_logger("storage.app_config")

# 可覆盖配置分组与字段（点分路径对齐 backend.config.settings.Settings 结构）。
# 这同时是 GET /api/data 系统设置表单的 schema（M2.8-D 复用）。
CONFIG_GROUPS: list[dict] = [
    {"key": "datasource", "label": "数据源", "fields": [
        {"path": "datasource.primary", "label": "主数据源", "type": "enum", "options": ["akshare", "baostock"]},
        {"path": "datasource.fallback", "label": "备用数据源", "type": "enum", "options": ["akshare", "baostock"]},
        {"path": "datasource.history_years", "label": "回填年限", "type": "int", "min": 1, "max": 30},
        {"path": "datasource.update_concurrency", "label": "采集并发数(增量/回填/重拉/估值)", "type": "int", "min": 1, "max": 16},
        {"path": "datasource.rate_limit_per_sec", "label": "请求限流(次/秒)", "type": "number", "min": 0.1, "max": 50},
        {"path": "datasource.socket_timeout_sec", "label": "请求超时(秒)", "type": "number", "min": 1},
        {"path": "datasource.max_retries", "label": "失败重试次数", "type": "int", "min": 1, "max": 10},
        {"path": "datasource.retry_backoff_sec", "label": "重试退避(秒)", "type": "number", "min": 0, "max": 60},
    ]},
    {"key": "universe", "label": "股票池", "fields": [
        {"path": "universe.float_mv_min", "label": "流通市值下界(元)", "type": "number", "min": 0},
        {"path": "universe.float_mv_max", "label": "流通市值上界(元)", "type": "number", "min": 0},
        {"path": "universe.min_list_days", "label": "次新剔除(上市<N交易日)", "type": "int", "min": 0},
        {"path": "universe.exclude_st", "label": "剔除ST", "type": "bool"},
        {"path": "universe.exclude_one_word_limit", "label": "剔除一字板", "type": "bool"},
    ]},
    {"key": "cost", "label": "回测成本", "fields": [
        {"path": "backtest.cost.commission_rate", "label": "佣金率", "type": "number", "min": 0, "max": 0.1},
        {"path": "backtest.cost.stamp_tax_rate", "label": "印花税率", "type": "number", "min": 0, "max": 0.1},
        {"path": "backtest.cost.slippage", "label": "滑点", "type": "number", "min": 0, "max": 0.1},
    ]},
    {"key": "topn", "label": "选股数量", "fields": [
        {"path": "backtest.top_n", "label": "回测 TopN", "type": "int", "min": 1, "max": 500},
        {"path": "scoring.top_n", "label": "榜单 TopN", "type": "int", "min": 1, "max": 500},
    ]},
    # 定时调度（遗留）：调度系统重构后改用 scheduled_job 表 + 「任务调度」页，旧的单一每日配置
    # 已不再作为运行态。这些白名单项仅供启动时一次性迁移读取旧值（读后即删，见 scheduler._migrate_legacy_config），
    # 不在表单渲染（hidden_in_form）。迁移消费完即从 app_config 删除，正常运行期不会再出现。
    {"key": "scheduler", "label": "定时调度（遗留）", "hidden_in_form": True, "fields": [
        {"path": "scheduler.enabled", "label": "启用每日自动任务（遗留）", "type": "bool"},
        {"path": "scheduler.daily_cron_hour", "label": "执行小时（遗留）", "type": "int", "min": 0, "max": 23},
        {"path": "scheduler.daily_cron_minute", "label": "执行分钟（遗留）", "type": "int", "min": 0, "max": 59},
    ]},
]

# path → field 元信息（含 group label）
_FIELD_BY_PATH: dict[str, dict] = {
    f["path"]: {**f, "group": g["key"], "group_label": g["label"]}
    for g in CONFIG_GROUPS for f in g["fields"]
}
WHITELIST: frozenset[str] = frozenset(_FIELD_BY_PATH)


class ConfigValidationError(ValueError):
    """配置校验失败（非法 key / 类型 / 范围 / 跨字段约束）。"""


def _coerce(field: dict, value):
    """按字段类型转换并做范围校验，返回规范化后的值。"""
    t = field["type"]
    path = field["path"]
    if t == "bool":
        if not isinstance(value, bool):
            raise ConfigValidationError(f"{path} 需为布尔值")
        return value
    if t == "enum":
        if value not in field["options"]:
            raise ConfigValidationError(f"{path} 需为 {field['options']} 之一")
        return value
    if t in ("int", "number"):
        if isinstance(value, bool):  # bool 是 int 子类，显式拒绝
            raise ConfigValidationError(f"{path} 需为数值")
        try:
            num = int(value) if t == "int" else float(value)
        except (TypeError, ValueError):
            raise ConfigValidationError(f"{path} 需为{'整数' if t == 'int' else '数值'}")
        if "min" in field and num < field["min"]:
            raise ConfigValidationError(f"{path} 不能小于 {field['min']}")
        if "max" in field and num > field["max"]:
            raise ConfigValidationError(f"{path} 不能大于 {field['max']}")
        return num
    raise ConfigValidationError(f"{path} 未知类型 {t}")


class AppConfigRepo:
    def __init__(self, client: DuckDBClient | None = None):
        self.c = client or get_client()
        from backend.storage.ddl import init_db
        init_db(self.c)

    def get_overrides(self) -> dict[str, object]:
        """返回 {点分路径: 值}（仅白名单内、可解析的项）。"""
        df = self.c.query_df("SELECT key, value FROM app_config")
        out: dict[str, object] = {}
        for _, r in df.iterrows():
            key = r["key"]
            if key not in WHITELIST:
                continue
            try:
                out[key] = json.loads(r["value"])
            except (ValueError, TypeError):
                continue
        return out

    def set_many(self, updates: dict[str, object]) -> int:
        """校验并写入覆盖值。任一项非法则整批拒绝（不部分写入）。返回写入条数。"""
        if not updates:
            return 0
        normalized: dict[str, object] = {}
        for path, value in updates.items():
            field = _FIELD_BY_PATH.get(path)
            if field is None:
                raise ConfigValidationError(f"不允许覆盖的配置项: {path}")
            normalized[path] = _coerce(field, value)
        # 跨字段约束：流通市值上界 > 下界
        self._check_cross_field(normalized)
        now = datetime.now()
        for path, value in normalized.items():
            self.c.execute(
                "INSERT INTO app_config (key, value, updated_at) VALUES (?,?,?) "
                "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=EXCLUDED.updated_at",
                [path, json.dumps(value, ensure_ascii=False), now])
        log.info("配置覆盖写入 %d 项: %s", len(normalized), list(normalized))
        return len(normalized)

    def _check_cross_field(self, normalized: dict[str, object]) -> None:
        """仅校验本批 + 已存覆盖合并后的跨字段约束（市值上界>下界）。"""
        merged = {**self.get_overrides(), **normalized}
        lo = merged.get("universe.float_mv_min")
        hi = merged.get("universe.float_mv_max")
        if lo is not None and hi is not None and float(hi) <= float(lo):
            raise ConfigValidationError("流通市值上界必须大于下界")

    def reset(self, path: str) -> None:
        """删除某项覆盖，回落到 settings.yaml 默认。"""
        self.c.execute("DELETE FROM app_config WHERE key=?", [path])


def apply_overrides(base: dict, overrides: dict[str, object]) -> dict:
    """把 {点分路径: 值} 深合并进 base 配置 dict（就地嵌套写入），返回 base。"""
    for path, value in overrides.items():
        parts = path.split(".")
        node = base
        for p in parts[:-1]:
            nxt = node.get(p)
            if not isinstance(nxt, dict):
                nxt = {}
                node[p] = nxt
            node = nxt
        node[parts[-1]] = value
    return base
