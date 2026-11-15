"""常用静态门禁：使用固定 Ruff 与校验安装的 actionlint，不需要业务存储。"""

import subprocess
import sys
from pathlib import Path

from backend.devtools.ci_tools import TOOLS, release_executable

ROOT = Path(__file__).resolve().parents[2]
ACTIONLINT_VERSION = TOOLS["actionlint"][1]


def actionlint_executable() -> Path:
    """从官方固定版本安装工具；验证归档校验和，只提取预期的可执行文件。"""
    return release_executable("actionlint")


def run_quality() -> int:
    """完整扫描后端与所有 workflow；工具不可用或任一检查失败均返回失败。"""
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "backend"], cwd=ROOT, check=False,
    )
    if result.returncode:
        return result.returncode
    workflows = sorted((ROOT / ".github/workflows").glob("*.y*ml"))
    if not workflows:
        raise RuntimeError("workflow 集合为空，不能把未检查当作成功")
    # 仅做 actionlint 的工作流语法与表达式检查；不隐式依赖可选的 ShellCheck/Pyflakes。
    return subprocess.run(
        [str(actionlint_executable()), "-shellcheck=", "-pyflakes=", *map(str, workflows)],
        cwd=ROOT,
        check=False,
    ).returncode
