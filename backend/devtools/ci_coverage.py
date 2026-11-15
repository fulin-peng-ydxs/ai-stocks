"""常用 Python 回归的覆盖率输出协议；首阶段只测量，不设置百分比门槛。"""

import json
import xml.etree.ElementTree as ET
from pathlib import Path


def pytest_arguments(artifacts: Path, env: dict[str, str]) -> list[str]:
    """显式加载插件；数据与报告均归本轮目录，不污染工作树或继承用户覆盖率目标。"""
    env["COVERAGE_FILE"] = str(artifacts / ".coverage")
    for key in list(env):
        if key.startswith("COV_CORE_") or key in {"COVERAGE_RCFILE", "COVERAGE_PROCESS_START"}:
            env.pop(key)
    return [
        "-p", "pytest_cov.plugin", "--cov=backend", "--cov-branch",
        "--cov-config=pyproject.toml",
        "--cov-report=term:skip-covered",
        f"--cov-report=json:{artifacts / 'coverage-python.json'}",
        f"--cov-report=xml:{artifacts / 'coverage-python.xml'}",
    ]


def validate_report(artifacts: Path) -> None:
    """即使用例通过，覆盖率报告缺失或测量集合为空也不能完成本轮 CI。"""
    report = json.loads((artifacts / "coverage-python.json").read_text())
    if not report["files"] or report["totals"]["num_statements"] <= 0:
        raise RuntimeError("Python 覆盖率报告测量集合为空")
    xml = ET.parse(artifacts / "coverage-python.xml").getroot()
    if xml.tag != "coverage" or int(xml.get("lines-valid", "0")) <= 0:
        raise RuntimeError("Python 覆盖率 XML 报告无效")
