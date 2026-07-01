"""配置中心：从 config/settings.yaml 加载全局配置（需求 F-CFG-01 改参不改码）。

用法：
    from backend.config import get_settings
    s = get_settings()
    s.paths.duckdb_file

设计要点：
- 单例缓存（lru_cache），进程内只读一次；改 YAML 后调 reload_settings() 重载。
- Pydantic v2 模型做类型校验，缺字段/类型错会在启动时暴露。
- YAML 路径可用环境变量 AI_STOCKS_CONFIG 覆盖（便于测试/多环境）。
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from backend.common.exceptions import ConfigError

# 项目根目录 = 本文件上溯三级（backend/config/settings.py -> 项目根）
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "settings.yaml"


# ── 各配置段模型 ──────────────────────────────────────────────


class PathsConfig(BaseModel):
    duckdb_file: str = "data/ai_stocks.duckdb"
    parquet_dir: str = "data/parquet"
    export_dir: str = "data/exports"
    log_dir: str = "logs"


class DataSourceConfig(BaseModel):
    primary: str = "akshare"
    fallback: str = "baostock"
    history_years: int = 5
    rate_limit_per_sec: float = 5
    max_retries: int = 3
    retry_backoff_sec: float = 2
    socket_timeout_sec: float = 30  # 全局 socket 超时，防请求挂死
    cache_enabled: bool = True
    update_concurrency: int = 1     # 增量更新并发线程数（>1 提速；每线程独立限流，总速≈N×rate_limit）


class UniverseConfig(BaseModel):
    boards: list[str] = Field(default_factory=lambda: ["主板", "创业板", "科创板"])
    include_bse: bool = False
    exclude_st: bool = True
    min_list_days: int = 60
    long_period_na_days: int = 480
    exclude_suspended: bool = True
    exclude_one_word_limit: bool = True
    float_mv_min: float = 5.0e9
    float_mv_max: float = 4.0e10


class PriceLimitConfig(BaseModel):
    main_board: float = 0.10
    star_gem: float = 0.20
    st: float = 0.05


class IndicatorsConfig(BaseModel):
    ma_periods: list[int] = Field(default_factory=lambda: [5, 10, 20, 60, 250])
    hhv_periods: list[int] = Field(default_factory=lambda: [60, 120, 240, 480])
    ma_up_lookback: int = 5
    vol_breakout_n: int = 20
    vol_breakout_x: float = 2.0
    vol_sustain_s: int = 5
    vol_sustain_y: float = 1.5
    platform_breakout_n: int = 60
    turnover_healthy_min: float = 3.0
    turnover_healthy_max: float = 20.0
    turnover_risk_high: float = 35.0
    rs_window: int = 120
    adjust: str = "qfq"


class GradeThresholds(BaseModel):
    watch: float = 80
    leader: float = 90
    core: float = 95


class ScoringConfig(BaseModel):
    weights: dict[str, float] = Field(
        default_factory=lambda: {
            "position": 30,
            "trend": 20,
            "volume": 20,
            "turnover": 10,
            "rs": 10,
            "fund_flow": 0,
        }
    )
    normalize_to_100: bool = True
    top_n: int = 20
    grade_thresholds: GradeThresholds = Field(default_factory=GradeThresholds)


class CostConfig(BaseModel):
    commission_rate: float = 0.00025
    commission_min: float = 5.0
    stamp_tax_rate: float = 0.001
    transfer_fee_rate: float = 0.00001
    slippage: float = 0.002


class BacktestConfig(BaseModel):
    benchmark_main: str = "000905.SH"
    benchmark_others: list[str] = Field(default_factory=lambda: ["000300.SH"])
    initial_capital: float = 1_000_000.0
    top_n: int = 20
    lot_size: int = 100
    buy_price: str = "next_open"
    sell_rule: str = "break_ma"
    sell_ma_period: int = 20
    capital_alloc: str = "equal"
    industry_max_pct: float | None = None
    hit_horizons: list[int] = Field(default_factory=lambda: [5, 10, 20, 60])
    hit_thresholds: list[float] = Field(default_factory=lambda: [0.10, 0.20, 0.30])
    hit_horizon_main: int = 20
    hit_threshold_main: float = 0.10
    cost: CostConfig = Field(default_factory=CostConfig)


class SchedulerConfig(BaseModel):
    enabled: bool = False
    daily_cron_hour: int = 18
    daily_cron_minute: int = 0


class ServerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8000
    log_level: str = "info"


class PostgresConfig(BaseModel):
    """PostgreSQL 资产/权限/审计/字典库（多租户混合持久层，stage1）。

    非敏感连接参数放 YAML；**密码不入 YAML、不入码**，运行时从环境变量读取：
    - AI_STOCKS_PG_DSN：整串覆盖（优先级最高，便于多环境/容器）
    - AI_STOCKS_PG_PASSWORD：仅覆盖密码
    见 Settings.pg_conninfo()。
    """

    host: str = "127.0.0.1"
    port: int = 5432
    database: str = "ai_stocks"
    user: str = "ai_stocks"
    pool_min: int = 1          # 连接池下限
    pool_max: int = 10         # 连接池上限（与线程池并发匹配）


class RedisConfig(BaseModel):
    """Redis 短状态库（限流/验证码/token 黑名单/perm_ver，stage1 仅建底座）。

    密码从环境变量读取：
    - AI_STOCKS_REDIS_URL：整串覆盖（优先级最高）
    - AI_STOCKS_REDIS_PASSWORD：仅覆盖密码
    见 Settings.redis_url()。
    """

    host: str = "127.0.0.1"
    port: int = 6379
    db: int = 0


class AuthConfig(BaseModel):
    """认证与鉴权（多租户 RBAC stage2）。

    非敏感参数放 YAML；**JWT 签名密钥不入 YAML、不入码**，运行时从环境变量读取：
    - AI_STOCKS_JWT_SECRET：HS256 签名密钥（缺失即报错，无弱默认）。见 Settings.jwt_secret()。
    """

    algorithm: str = "HS256"
    access_ttl_min: int = 60        # access token 有效期（分钟）
    refresh_ttl_days: int = 14      # refresh token 有效期（天）
    min_password_len: int = 8       # 密码最小长度（注册/改密强度校验）

    # 登录失败与锁定（R15）
    max_login_fail: int = 5         # 窗口内失败达此数即锁定
    fail_window_min: int = 15       # 失败计数窗口（分钟）
    lock_minutes: int = 15          # 锁定时长（分钟）

    # 防滥用开关（R16；默认对齐需求：邮箱码开、图形码关）
    require_email_code: bool = True     # 注册需邮箱验证码
    login_captcha_enabled: bool = False  # 登录失败达阈值后要求图形验证码
    captcha_after_fails: int = 3        # 触发图形验证码的失败次数
    email_code_ttl_min: int = 10        # 邮箱验证码有效期（分钟）
    captcha_ttl_min: int = 5            # 图形验证码有效期（分钟）

    # 限流（R15；按 IP 维度，令牌桶/固定窗口）
    login_rate_per_min: int = 10        # 单 IP 每分钟登录尝试上限
    register_rate_per_hour: int = 5     # 单 IP 每小时注册上限
    email_code_rate_per_hour: int = 5   # 单邮箱每小时验证码发送上限


class Settings(BaseModel):
    """全局配置根模型。"""

    paths: PathsConfig = Field(default_factory=PathsConfig)
    datasource: DataSourceConfig = Field(default_factory=DataSourceConfig)
    universe: UniverseConfig = Field(default_factory=UniverseConfig)
    price_limit: PriceLimitConfig = Field(default_factory=PriceLimitConfig)
    indicators: IndicatorsConfig = Field(default_factory=IndicatorsConfig)
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)
    backtest: BacktestConfig = Field(default_factory=BacktestConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    postgres: PostgresConfig = Field(default_factory=PostgresConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)

    # ── 派生：绝对路径辅助 ──
    def duckdb_path(self) -> Path:
        return _resolve(self.paths.duckdb_file)

    # ── 派生：外部存储连接（密码走环境变量，不入库不入码）──
    def pg_conninfo(self) -> str:
        """组装 psycopg 连接串（keyword/value）。

        优先级：AI_STOCKS_PG_DSN（整串） > YAML 参数 + AI_STOCKS_PG_PASSWORD（密码）。
        """
        dsn = os.environ.get("AI_STOCKS_PG_DSN")
        if dsn:
            return dsn
        p = self.postgres
        # connect_timeout 上界 libpq 建连耗时，避免 PG 不可达时长时间挂起（启动自检/测试 skip 更干脆）
        parts = [
            f"host={p.host}",
            f"port={p.port}",
            f"dbname={p.database}",
            f"user={p.user}",
            "connect_timeout=10",
        ]
        pwd = os.environ.get("AI_STOCKS_PG_PASSWORD", "")
        if pwd:
            parts.append(f"password={pwd}")
        return " ".join(parts)

    def redis_url(self) -> str:
        """组装 redis URL。优先级：AI_STOCKS_REDIS_URL > YAML 参数 + AI_STOCKS_REDIS_PASSWORD。"""
        url = os.environ.get("AI_STOCKS_REDIS_URL")
        if url:
            return url
        r = self.redis
        pwd = os.environ.get("AI_STOCKS_REDIS_PASSWORD", "")
        auth = f":{pwd}@" if pwd else ""
        return f"redis://{auth}{r.host}:{r.port}/{r.db}"

    def jwt_secret(self) -> str:
        """JWT 签名密钥，仅从环境变量 AI_STOCKS_JWT_SECRET 读取。

        **无弱默认**：缺失即抛 ConfigError（避免用可预测密钥签发可伪造 token）。
        惰性调用（签发/校验 token 时），不影响不涉认证的启动/测试。
        """
        secret = os.environ.get("AI_STOCKS_JWT_SECRET")
        if not secret:
            raise ConfigError(
                "缺少环境变量 AI_STOCKS_JWT_SECRET：JWT 签名密钥必须显式配置，无弱默认")
        return secret

    def export_path(self) -> Path:
        return _resolve(self.paths.export_dir)

    def log_path(self) -> Path:
        return _resolve(self.paths.log_dir)


def _resolve(p: str) -> Path:
    """相对路径按项目根解析为绝对路径。"""
    path = Path(p)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _config_path() -> Path:
    env = os.environ.get("AI_STOCKS_CONFIG")
    return Path(env) if env else DEFAULT_CONFIG_PATH


def _raw_yaml() -> dict:
    """读 settings.yaml 原始 dict（缺失返回空 dict）。"""
    path = _config_path()
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """加载并缓存全局配置（仅 settings.yaml 基线，单例）。

    注意：本函数**只读 YAML**，不合并 app_config 覆盖层——它被 DuckDB 连接初始化
    （duckdb_path）依赖，若在此访问 DB 会造成循环。需要覆盖层生效的业务读取请用
    get_effective_settings()。
    """
    return Settings.model_validate(_raw_yaml())


def get_effective_settings() -> Settings:
    """生效配置 = settings.yaml 基线 ⊕ app_config 覆盖层（覆盖层优先，DM-D3）。

    每次调用重新合并（不缓存），保证 Web 改参后即时生效；DB 不可用时回落到 YAML 基线。
    """
    base = _raw_yaml()
    try:
        from backend.storage.app_config import AppConfigRepo, apply_overrides
        overrides = AppConfigRepo().get_overrides()
        if overrides:
            base = apply_overrides(base, overrides)
    except Exception:  # noqa: BLE001 —— DB 未就绪/异常时静默回落 YAML
        pass
    return Settings.model_validate(base)


def reload_settings() -> Settings:
    """清缓存并重新加载（改 YAML 后调用，支持配置即时生效）。"""
    get_settings.cache_clear()
    return get_settings()
