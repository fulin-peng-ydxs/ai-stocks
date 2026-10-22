"""配置覆盖层（DM-D2/D3，FR-DM-12）。

Web 表单改的参数写 `app_config` 表（点分路径 → JSON 值），settings.yaml 仅作默认兜底；
读取时覆盖层优先（见 backend.config.settings.get_effective_settings）。

只允许白名单内的真实可调参数被覆盖（R-DM-5）——评分权重/分档阈值已被 score_profile 取代，
不进白名单。每个字段带类型与范围规则，保存时逐项校验。
"""

from __future__ import annotations

import json
import math
from datetime import datetime

from backend.common.logging import get_logger
from backend.security.config_crypto import (
    ConfigEncryptionError,
    decrypt_config_value,
    encrypt_config_value,
    is_encrypted_config_value,
)
from backend.storage.pg_client import PostgresClient, get_pg_client

log = get_logger("storage.app_config")

# 可覆盖配置分组与字段（点分路径对齐 backend.config.settings.Settings 结构）。
# 这同时是 GET /api/data 系统设置表单的 schema（M2.8-D 复用）。
CONFIG_GROUPS: list[dict] = [
    {"key": "ui", "label": "界面显示", "desc": "控制所有用户共享的界面显示基线，不包含个人页面密度。", "fields": [
        {"path": "ui.display.auto_scale_exponent", "label": "自动界面比例强度", "type": "number", "min": 0, "max": 1, "default": 0.10, "app_config_only": True, "desc": "按当前屏幕可用面积自动缩放的指数；0 表示保持 100%，自动结果仍限制在 90%～110%。"},
    ]},
    {"key": "datasource", "label": "数据源", "desc": "统一行情采集、修复和源测试的请求规则；特殊来源限制在下方说明。", "fields": [
        {"path": "datasource.primary", "label": "行情主接入器", "type": "enum", "options": ["akshare", "baostock"], "desc": "只控制支持切换的行情能力。AKShare 内部使用新浪、东财等接口；分时、股本和板块按各自能力取源。"},
        {"path": "datasource.fallback", "label": "行情备用接入器", "type": "enum", "options": ["akshare", "baostock"], "desc": "行情主接入器不可用时的备用来源。"},
        {"path": "datasource.history_years", "label": "回填年限", "type": "int", "min": 1, "max": 30, "desc": "历史行情回填向前覆盖的年数。"},
        {"path": "datasource.update_concurrency", "label": "默认采集并发数", "type": "int", "min": 1, "max": 16, "desc": "单任务工作单元上限；任务显式参数可覆盖。分时按股票并发，BaoStock 和板块会话保持串行；不放大来源请求频率。"},
        {"path": "datasource.rate_limit_per_sec", "label": "每来源请求上限(次/秒)", "type": "number", "min": 0.1, "max": 50, "desc": "按实际来源跨线程、跨进程合计限制请求起始频率，分页及重试均计入；新浪行情与新浪分时共享限额。"},
        {"path": "datasource.baostock_login_timeout_sec", "label": "BaoStock登录超时(秒)", "type": "number", "min": 1, "max": 600, "desc": "仅限登录等待，登录完成后恢复普通请求超时。"},
        {"path": "datasource.socket_timeout_sec", "label": "请求超时(秒)", "type": "number", "min": 1, "desc": "每次网络尝试的连接和读取超时；不是整个任务的时长上限。下一次请求读取新值，在途请求不变。"},
        {"path": "datasource.max_retries", "label": "最多尝试次数", "type": "int", "min": 1, "max": 10, "desc": "包含首次请求；3 表示首次加最多两次重试。一次多接口业务操作可能包含多个请求。"},
        {"path": "datasource.retry_backoff_sec", "label": "重试初始等待(秒)", "type": "number", "min": 0, "max": 60, "desc": "指数退避起点；2 秒表示依次等待 2、4、8……秒。"},
    ]},
    {"key": "cost", "label": "回测成本", "desc": "控制回测成交记账时使用的默认交易成本。", "fields": [
        {"path": "backtest.cost.commission_rate", "label": "佣金率", "type": "number", "min": 0, "max": 0.1, "desc": "买卖双边计入的佣金比例。"},
        {"path": "backtest.cost.stamp_tax_rate", "label": "印花税率", "type": "number", "min": 0, "max": 0.1, "desc": "卖出成交时计入的印花税比例。"},
        {"path": "backtest.cost.slippage", "label": "滑点", "type": "number", "min": 0, "max": 0.1, "desc": "成交价相对开盘价的方向性滑点比例。"},
    ]},
    {"key": "auth", "label": "认证与防滥用", "desc": "控制注册校验、登录验证码和认证接口限流。", "fields": [
        {"path": "auth.require_email_code", "label": "注册需邮箱验证码", "type": "bool", "desc": "开启后自助注册必须提交真实邮箱验证码。"},
        {"path": "auth.login_captcha_enabled", "label": "登录图形验证码", "type": "bool", "desc": "开启后登录页展示并校验图形验证码。"},
        {"path": "auth.captcha_after_fails", "label": "图形验证码强制失败次数", "type": "int", "min": 1, "max": 10, "desc": "登录图形验证码开关开启时，同一账号连续失败达到该次数后，后端强制要求提交图形验证码。"},
        {"path": "auth.login_rate_per_min", "label": "登录限流(次/分钟)", "type": "int", "min": 1, "max": 120, "desc": "同一 IP 每分钟允许的登录请求数。"},
        {"path": "auth.register_rate_per_hour", "label": "注册限流(次/小时)", "type": "int", "min": 1, "max": 120, "desc": "同一 IP 每小时允许的注册请求数。"},
        {"path": "auth.email_code_rate_per_hour", "label": "邮箱验证码限流(次/小时·单邮箱)", "type": "int", "min": 1, "max": 120, "desc": "同一邮箱每小时允许发送验证码的次数。"},
        {"path": "auth.email_code_ip_rate_per_hour", "label": "邮箱验证码限流(次/小时·单IP)", "type": "int", "min": 1, "max": 500, "desc": "同一 IP 每小时允许发送验证码的次数，防止一个来源对海量不同邮箱各发几次。"},
    ]},
    {"key": "audit", "label": "审计设置", "desc": "控制审计查询默认窗口和保留期自动清理。", "fields": [
        {"path": "audit.retention_days", "label": "审计保留期/默认查询窗口(天)", "type": "int", "min": 7, "max": 365, "desc": "审计页未选择时间时默认查询最近多少天，同时用于自动清理超期审计日志。"},
    ]},
    {"key": "ths_board", "label": "同花顺板块", "desc": "板块来源的特殊频率限制、采集规则和访问凭据；同花顺股票分钟不使用本组Cookie。", "fields": [
        {"path": "ths_board.min_interval_sec", "label": "请求间隔(秒)", "type": "number", "min": 0.05, "max": 30, "desc": "板块接口最小请求起始间隔，与通用来源频率取更严格限制；不影响同花顺股票分钟接口。"},
        {"path": "ths_board.timeout_sec", "nullable": True, "label": "请求超时(秒)", "type": "number", "min": 1, "max": 120, "desc": "旧显式覆盖；关闭单独设置后继承通用请求超时。"},
        {"path": "ths_board.max_retries", "nullable": True, "label": "最多尝试次数", "type": "int", "min": 1, "max": 10, "desc": "旧显式覆盖，包含首次；关闭单独设置后继承通用最多尝试次数。"},
        {"path": "ths_board.retry_backoff_sec", "nullable": True, "label": "重试初始等待(秒)", "type": "number", "min": 0, "max": 60, "desc": "旧显式覆盖；关闭单独设置后继承通用重试初始等待。"},
        {"path": "ths_board.member_update_interval_days", "label": "成分快照更新间隔(天)", "type": "int", "min": 1, "max": 30, "desc": "成分股快照多久全量拉取一次；未达间隔且上次完整时跳过（默认 7=周频）。"},
        {"path": "ths_board.cookie_validity_days", "label": "Cookie 默认有效期(天)", "type": "int", "min": 1, "max": 365, "desc": "从保存或最近成功校验起计算的期限提醒；测试连通时仍会真实访问登录态页面确认是否有效。"},
        {"path": "ths_board.login_cookie", "label": "登录 Cookie", "type": "password",
         "encrypted": True,
         "placeholder": "粘贴登录后的完整 Cookie；数据库只保存加密密文",
         "desc": "用于解除深页登录墙。页面只回显已设置状态，数据库使用独立主密钥加密存储；环境变量或受控文件仍可优先覆盖。"},
    ]},
    # 定时调度（遗留）：调度系统重构后改用 scheduled_job 表 + 「任务调度」页，旧的单一每日配置
    # 已不再作为运行态。这些白名单项仅供启动时一次性迁移读取旧值（读后即删，见 scheduler._migrate_legacy_config），
    # 不在表单渲染（hidden_in_form）。迁移消费完即从 app_config 删除，正常运行期不会再出现。
    {"key": "scheduler", "label": "定时调度（遗留）", "hidden_in_form": True, "fields": [
        {"path": "scheduler.enabled", "label": "启用每日自动任务（遗留）", "type": "bool", "desc": "仅供旧配置迁移读取，不在系统设置页面展示。"},
        {"path": "scheduler.daily_cron_hour", "label": "执行小时（遗留）", "type": "int", "min": 0, "max": 23, "desc": "旧每日任务执行小时，仅迁移使用。"},
        {"path": "scheduler.daily_cron_minute", "label": "执行分钟（遗留）", "type": "int", "min": 0, "max": 59, "desc": "旧每日任务执行分钟，仅迁移使用。"},
    ]},
]

# path → field 元信息（含 group label）
_FIELD_BY_PATH: dict[str, dict] = {
    f["path"]: {**f, "group": g["key"], "group_label": g["label"]}
    for g in CONFIG_GROUPS for f in g["fields"]
}
WHITELIST: frozenset[str] = frozenset(_FIELD_BY_PATH)
ENCRYPTED_CONFIG_PATHS: frozenset[str] = frozenset(
    path for path, field in _FIELD_BY_PATH.items() if field.get("encrypted")
)
SECRET_STATUS_UNSET = "unset"
SECRET_STATUS_USABLE = "usable"
SECRET_STATUS_UNAVAILABLE = "unavailable"
THS_COOKIE_STATUS_KEY = "runtime.ths_board.login_cookie_validation"


def get_field_meta(path: str) -> dict | None:
    """返回可覆盖配置的字段元数据，未登记路径返回 None。"""
    field = _FIELD_BY_PATH.get(path)
    return dict(field) if field else None


def is_sensitive_config_path(path: str) -> bool:
    """配置元数据驱动的敏感字段判定，供写库前审计脱敏复用。"""
    field = _FIELD_BY_PATH.get(str(path))
    return bool(field and field.get("type") == "password")


def protect_serialized_config_value(path: str, serialized: object) -> str | None:
    """把迁移来源的 JSON 配置值转换为安全存储格式；无密钥时拒绝迁移敏感明文。"""
    if path not in ENCRYPTED_CONFIG_PATHS:
        return str(serialized)
    try:
        value = json.loads(serialized)
    except (TypeError, ValueError):
        return None
    if is_encrypted_config_value(value):
        return str(serialized)
    if not isinstance(value, str):
        return None
    try:
        return json.dumps(encrypt_config_value(value), ensure_ascii=False)
    except ConfigEncryptionError as exc:
        log.error("敏感配置迁移已跳过 %s: %s", path, exc)
        return None


class ConfigValidationError(ValueError):
    """配置校验失败（非法 key / 类型 / 范围 / 跨字段约束）。"""


def _coerce(field: dict, value):
    """按字段类型转换并做范围校验，返回规范化后的值。"""
    if value is None and field.get("nullable"):
        return None
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
            if t == "int" and float(value) != num:
                raise ValueError("fractional integer")
        except (TypeError, ValueError, OverflowError):
            raise ConfigValidationError(f"{path} 需为{'整数' if t == 'int' else '数值'}")
        if not math.isfinite(num):
            raise ConfigValidationError(f"{path} 需为有限数值")
        if "min" in field and num < field["min"]:
            raise ConfigValidationError(f"{path} 不能小于 {field['min']}")
        if "max" in field and num > field["max"]:
            raise ConfigValidationError(f"{path} 不能大于 {field['max']}")
        return num
    if t in ("string", "password"):
        if not isinstance(value, str):
            raise ConfigValidationError(f"{path} 需为字符串")
        return value
    raise ConfigValidationError(f"{path} 未知类型 {t}")


class AppConfigRepo:
    """平台级配置覆盖层（多租户混合持久层 stage1·T2）。

    app_config 是平台全局配置（仅系统管理员可改、无归属列），落 PG，多实例一致。
    PG 不可用时由上层 get_effective_settings 的 try/except 回落 settings.yaml 基线。
    """

    def __init__(self, pg: PostgresClient | None = None):
        self.pg = pg or get_pg_client()

    def get_overrides(self) -> dict[str, object]:
        """返回解密后的覆盖值；密钥缺失或密文非法时跳过敏感项，不把密文当配置消费。"""
        df = self.pg.query_df("SELECT key, value FROM app_config")
        out: dict[str, object] = {}
        for _, r in df.iterrows():
            key = r["key"]
            if key not in WHITELIST:
                continue
            try:
                value = json.loads(r["value"])
            except (ValueError, TypeError):
                continue
            if key in ENCRYPTED_CONFIG_PATHS:
                if not is_encrypted_config_value(value):
                    log.error("拒绝读取未加密的敏感配置: %s", key)
                    continue
                try:
                    value = decrypt_config_value(value)
                except ConfigEncryptionError as exc:
                    log.error("敏感配置不可用 %s: %s", key, exc)
                    continue
            out[key] = value
        return out

    def get_override_keys(self) -> set[str]:
        """返回数据库中已持久化的白名单 key，不触碰或解密配置值。"""
        df = self.pg.query_df("SELECT key FROM app_config")
        return {str(key) for key in df["key"].tolist() if str(key) in WHITELIST}

    def get_secret_statuses(self) -> dict[str, str]:
        """返回敏感配置可用性，不返回明文或密文。

        数据库无记录为 unset；密文能由当前主密钥成功解密为 usable；明文、未知格式、
        密钥缺失/错误或密文损坏统一为 unavailable。该状态供管理页面准确反映运行态。
        """
        statuses = {path: SECRET_STATUS_UNSET for path in ENCRYPTED_CONFIG_PATHS}
        df = self.pg.query_df("SELECT key, value FROM app_config")
        for _, row in df.iterrows():
            key = str(row["key"])
            if key not in ENCRYPTED_CONFIG_PATHS:
                continue
            try:
                value = json.loads(row["value"])
                if not is_encrypted_config_value(value):
                    raise ConfigEncryptionError("敏感配置不是受支持的加密格式")
                decrypt_config_value(value)
            except (ConfigEncryptionError, TypeError, ValueError):
                statuses[key] = SECRET_STATUS_UNAVAILABLE
            else:
                statuses[key] = SECRET_STATUS_USABLE
        return statuses

    def get_updated_at(self, path: str) -> datetime | None:
        """读取单项配置更新时间，不返回配置值。"""
        df = self.pg.query_df("SELECT updated_at FROM app_config WHERE key=%s", [path])
        if df.empty or df.iloc[0]["updated_at"] is None:
            return None
        return df.iloc[0]["updated_at"]

    def get_ths_cookie_validation(self) -> dict:
        """读取脱敏的同花顺 Cookie 校验记录。"""
        df = self.pg.query_df("SELECT value FROM app_config WHERE key=%s", [THS_COOKIE_STATUS_KEY])
        if df.empty:
            return {}
        try:
            value = json.loads(df.iloc[0]["value"])
        except (TypeError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}

    def set_ths_cookie_validation(self, value: dict) -> None:
        """保存不含 Cookie 明文的真实校验结果。"""
        now = datetime.now()  # noqa: DTZ005 -- 与 app_config 既有无时区时间口径一致
        self.pg.execute(
            "INSERT INTO app_config (key, value, updated_at) VALUES (%s,%s,%s) "
            "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=EXCLUDED.updated_at",
            [THS_COOKIE_STATUS_KEY, json.dumps(value, ensure_ascii=False), now],
        )

    def clear_ths_cookie_validation(self) -> None:
        self.pg.execute("DELETE FROM app_config WHERE key=%s", [THS_COOKIE_STATUS_KEY])

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
        self._check_cross_field(normalized)
        stored_values = dict(normalized)
        for path, value in normalized.items():
            if path not in ENCRYPTED_CONFIG_PATHS or value == "":
                continue
            try:
                stored_values[path] = encrypt_config_value(str(value))
            except ConfigEncryptionError as exc:
                raise ConfigValidationError(str(exc)) from exc
        now = datetime.now()
        for path, value in stored_values.items():
            if path in ENCRYPTED_CONFIG_PATHS:
                if value == "":
                    self.pg.execute("DELETE FROM app_config WHERE key=%s", [path])
                    continue
            self.pg.execute(
                "INSERT INTO app_config (key, value, updated_at) VALUES (%s,%s,%s) "
                "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=EXCLUDED.updated_at",
                [path, json.dumps(value, ensure_ascii=False), now])
        if "ths_board.login_cookie" in normalized:
            self.clear_ths_cookie_validation()
        log.info("配置覆盖写入 %d 项: %s", len(normalized), list(normalized))
        return len(normalized)

    def _check_cross_field(self, normalized: dict[str, object]) -> None:
        """跨字段约束入口。当前 Web 可维护配置暂无跨字段约束。"""

    def reset(self, path: str) -> None:
        """删除某项覆盖，回落到 settings.yaml 默认。"""
        self.pg.execute("DELETE FROM app_config WHERE key=%s", [path])
        if path == "ths_board.login_cookie":
            self.clear_ths_cookie_validation()

    def reset_many(self, paths: list[str]) -> int:
        """批量删除覆盖项，回落到 settings.yaml 默认。返回删除条数。"""
        normalized: list[str] = []
        for path in paths:
            key = str(path or "").strip()
            if key not in WHITELIST:
                raise ConfigValidationError(f"不允许重置的配置项: {key}")
            if key not in normalized:
                normalized.append(key)
        if not normalized:
            return 0
        df = self.pg.query_df(
            "SELECT key FROM app_config WHERE key = ANY(%s)",
            [normalized],
        )
        self.pg.execute("DELETE FROM app_config WHERE key = ANY(%s)", [normalized])
        if "ths_board.login_cookie" in normalized:
            self.clear_ths_cookie_validation()
        return int(len(df))


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
