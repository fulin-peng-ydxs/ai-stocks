"""隔离测试子进程环境：不继承业务连接、凭据、调试开关和测试筛选。"""

import os
import sys
from pathlib import Path
from uuid import uuid4


def clean_environment() -> dict[str, str]:
    """调用方再注入自身临时连接；普通路径不能回落到本机环境覆盖。"""
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("AI_STOCKS_", "PYTEST_")) and key != "ENV"
    }
    env.update(
        {
            "AI_STOCKS_ENV": "test",
            "AI_STOCKS_ENV_FILE": "/dev/null",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "AI_STOCKS_ADMIN_PASSWORD": uuid4().hex,
            "AI_STOCKS_JWT_SECRET": uuid4().hex + uuid4().hex,
            "AI_STOCKS_CONFIG_ENCRYPTION_KEY": "bsKvJrJKsi9lG2hlViiCnZimaUG5tyKh0Rbt5d3ngQU=",
            "AI_STOCKS_TASK_STORAGE_BACKEND": "auto",
            "AI_STOCKS_SMTP_ENABLED": "0",
        }
    )
    # 测试里的 shell 子入口也使用当前解释器，且不能重新加载本机变量文件。
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    env["PYTHON"] = sys.executable
    return env
