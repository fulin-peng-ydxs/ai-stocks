"""CI 测试默认自动发现，专项按登记分流；必检 skip/xfail/空集合一律失败。"""

import json
import os
from pathlib import Path

import pytest

from backend.devtools.ci import ROOT, registry
from backend.devtools.database_gate_plugin import (  # noqa: F401
    pytest_deselected,
    pytest_sessionfinish,
)


def pytest_configure(config):
    config._ci_registry = registry()
    config._ci_suite = os.environ["AI_STOCKS_CI_SUITE"]
    config._ci_routed = []


def pytest_ignore_collect(collection_path, config):
    """导入前隔离遗留真实库冒烟与数据库专项，避免收集阶段访问错误的数据源。"""
    relative = collection_path.relative_to(ROOT).as_posix()
    entry = config._ci_registry["special_files"].get(relative)
    if entry:
        return entry["suite"] != config._ci_suite
    # 规模专项只收集登记的文件及包含专项用例的文件。
    if config._ci_suite != "backend" and collection_path.is_file():
        nodes = config._ci_registry["special_nodes"]
        return not any(
            key.split("::")[0] == relative and value["suite"] == config._ci_suite
            for key, value in nodes.items()
        )
    return None


def pytest_collection_modifyitems(config, items):
    """按精确 nodeid 分流参数用例；失效登记失败，不能静默丢失专项覆盖。"""
    data, suite = config._ci_registry, config._ci_suite
    collected = {item.nodeid for item in items}
    expected = {
        node
        for node, entry in data["special_nodes"].items()
        if suite == "backend" or entry["suite"] == suite
    }
    stale = expected - collected
    if stale:
        raise pytest.UsageError("失效的 CI 用例登记：" + ", ".join(sorted(stale)))
    selected = []
    for item in items:
        entry = data["special_nodes"].get(item.nodeid)
        file_entry = data["special_files"].get(item.nodeid.split("::")[0])
        target = (entry or file_entry or {"suite": "backend"})["suite"]
        if target == suite:
            selected.append(item)
        else:
            config._ci_routed.append(item.nodeid)
    items[:] = selected
    config._ci_selected = [item.nodeid for item in selected]


def pytest_collection_finish(session):
    """正式收集结束后落实际清单；单元夹具调用分流函数不能覆盖本轮收集证据。"""
    config = session.config
    destination = os.environ.get("AI_STOCKS_CI_TEST_MANIFEST")
    if destination:
        Path(destination).write_text(json.dumps({
            "suite": config._ci_suite, "selected": config._ci_selected,
            "routed": config._ci_routed,
            "scale_stocks": os.environ.get("INTRADAY_SCALE_STOCKS"),
        }, ensure_ascii=False, indent=2))


def pytest_terminal_summary(terminalreporter, config):
    terminalreporter.write_line(
        f"CI 套件 {config._ci_suite}：{len(config._ci_routed)} 个参数用例按登记分流（非通过/skip）"
    )
