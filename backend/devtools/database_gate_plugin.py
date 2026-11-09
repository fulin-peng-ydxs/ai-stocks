"""门禁禁止以 skip/xfail/空集合代替真实数据库验证。"""


def pytest_deselected(items):
    """保留真实取消选择的证据，避免 -k/-m 只跑一个通过项也算完整门禁。"""
    if items:
        items[0].config._database_gate_deselected = True


def pytest_sessionfinish(session, exitstatus):
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    stats = reporter.stats if reporter is not None else {}
    if (
        getattr(session.config, "_database_gate_deselected", False)
        or not stats.get("passed")
        or any(stats.get(key) for key in ("skipped", "xfailed", "xpassed"))
    ):
        session.exitstatus = 1
