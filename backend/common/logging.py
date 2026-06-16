"""结构化日志（需求 F-CFG-03 关键流程有日志）。

统一入口 get_logger(name)，输出到控制台 + 文件（按天滚动可后续加）。
日志格式含时间/级别/模块/消息，便于排查数据更新/回测耗时与异常。
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

_CONFIGURED = False
_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


def _configure_root(log_dir: Path | None = None, level: int = logging.INFO) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return

    root = logging.getLogger("ai_stocks")
    root.setLevel(level)
    formatter = logging.Formatter(_FORMAT, datefmt=_DATEFMT)

    # 控制台
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(formatter)
    root.addHandler(sh)

    # 文件日志默认关闭：start.sh 已把 stdout/stderr 汇总到 logs/backend.log。
    # 如需应用内另写 ai_stocks.log，可显式设置 AI_STOCKS_FILE_LOG=1。
    if log_dir is not None and os.environ.get("AI_STOCKS_FILE_LOG") == "1":
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_dir / "ai_stocks.log", encoding="utf-8")
        fh.setFormatter(formatter)
        root.addHandler(fh)

    root.propagate = False
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """获取命名 logger（统一挂在 ai_stocks 命名空间下）。"""
    if not _CONFIGURED:
        # 延迟导入避免循环依赖
        try:
            from backend.config import get_settings

            _configure_root(get_settings().log_path())
        except Exception:
            _configure_root(None)
    return logging.getLogger(f"ai_stocks.{name}")
