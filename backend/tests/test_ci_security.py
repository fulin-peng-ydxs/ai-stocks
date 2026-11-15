"""安全 CI 的调用、精确例外、锁漂移与失败报告边界，不连接业务存储或审计服务。"""

import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.devtools import ci, ci_changes, ci_coverage, ci_dependencies, ci_secrets


@pytest.mark.parametrize("paths,expected", [
    ({"frontend/src/views/page.vue"}, False),
    ({"requirements-ci.lock"}, True),
    ({"requirements-extra.txt"}, True),
    ({"frontend/package-lock.json"}, True),
    ({"frontend/patches/echarts+6.1.0.patch"}, True),
    (None, True),
])
def test_common_dependency_routing_is_conservative(monkeypatch, paths, expected):
    monkeypatch.setattr(ci, "commit_range", lambda *_args: None)
    monkeypatch.setattr(ci, "changed_paths", lambda _range: paths)
    suites = {entry["suite"] for entry in ci.plan()["include"]}
    assert ("dependency-audit" in suites) is expected
    assert {"secrets", "quality", "frontend", "backend", "database"} <= suites
    assert ci.plan("dependency-audit")["include"] == [{"suite": "dependency-audit", "kind": "audit"}]


def test_push_and_pr_ranges_include_deleted_dependency_and_local_addition(tmp_path, monkeypatch):
    monkeypatch.setattr(ci_changes, "ROOT", tmp_path)

    def git(*arguments):
        return subprocess.check_output(["git", *arguments], cwd=tmp_path, text=True).strip()

    git("init", "-q")
    git("config", "user.name", "CI probe")
    git("config", "user.email", "probe@example.invalid")
    (tmp_path / "requirements-extra.txt").write_text("pytest==9.0.3\n")
    git("add", ".")
    git("commit", "-qm", "baseline")
    base = git("rev-parse", "HEAD")
    (tmp_path / "requirements-extra.txt").unlink()
    git("add", "-u")
    git("commit", "-qm", "delete dependency manifest")
    head = git("rev-parse", "HEAD")
    (tmp_path / "new.txt").write_text("new source")
    event = tmp_path / "event.json"
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    for payload in [
        {"before": base, "after": head},
        {"pull_request": {"base": {"sha": base}, "head": {"sha": head}}},
    ]:
        event.write_text(json.dumps(payload))
        selected = ci_changes.commit_range()
        assert selected == (base, head)
        assert {"requirements-extra.txt", "new.txt"} <= ci_changes.changed_paths(selected)
    assert ci_changes.commit_range("0" * 40, head) is None
    assert ci_changes.commit_range("-bad-option", head) is None


def test_lock_tracks_recursive_inputs_and_rejects_drift(tmp_path, monkeypatch):
    monkeypatch.setattr(ci_dependencies, "ROOT", tmp_path)
    (tmp_path / "requirements-ci.txt").write_text("-r extra.txt\n")
    extra = tmp_path / "extra.txt"
    extra.write_text("pytest==9.0.3\n")
    lock = tmp_path / ci_dependencies.LOCK
    lock.write_text(f"# ai-stocks-input-sha256: {ci_dependencies.input_digest()}\n"
                    + "pytest==9.0.3 --hash=sha256:" + "a" * 64 + "\n")
    ci_dependencies.check_lock()
    extra.write_text("pytest==9.0.4\n")
    with pytest.raises(ValueError, match="已过期"):
        ci_dependencies.check_lock()


def test_installation_must_match_audited_lock(monkeypatch):
    monkeypatch.setattr(ci_dependencies, "locked_versions", lambda: {"pytest": "9.0.3"})
    monkeypatch.setattr(ci_dependencies, "version", lambda _name: "9.0.2")
    with pytest.raises(RuntimeError, match="安装版本不一致"):
        ci_dependencies.check_installed()


@pytest.mark.parametrize("kind", ["clean", "vulnerability", "query-error", "missing", "wrong-collection"])
def test_dependency_audit_never_accepts_vulnerability_or_missing_evidence(tmp_path, monkeypatch, kind):
    monkeypatch.setattr(ci_dependencies, "create_ci_artifact_dir", lambda: tmp_path)
    monkeypatch.setattr(ci_dependencies, "check_lock", lambda: None)
    monkeypatch.setattr(ci_dependencies, "locked_versions", lambda: {"example": "1.0"})

    def run(command, **options):
        if "pip_audit" in command:
            if kind == "missing":
                return SimpleNamespace(returncode=1)
            report = {"dependencies": [{"name": "example", "version": "2.0" if kind == "wrong-collection" else "1.0",
                                         "vulns": [{"id": "probe"}] if kind == "vulnerability" else []}]}
            Path(command[-1]).write_text(json.dumps(report))
            return SimpleNamespace(returncode=int(kind == "vulnerability"))
        report = {"vulnerabilities": {}, "metadata": {"dependencies": {"total": 1}}}
        if kind == "query-error":
            report = {"error": {"code": "network failure"}}
        options["stdout"].write(json.dumps(report))
        return SimpleNamespace(returncode=int(kind == "query-error"))

    monkeypatch.setattr(ci_dependencies.subprocess, "run", run)
    if kind in {"missing", "query-error", "wrong-collection"}:
        with pytest.raises(RuntimeError):
            ci_dependencies.run_audit()
    else:
        assert ci_dependencies.run_audit() == int(kind == "vulnerability")


def test_secret_exception_requires_exact_content_and_live_expiry(tmp_path, monkeypatch):
    source = tmp_path / "test_probe.py"
    source.write_text("fixed test material\n")
    finding = {"File": str(source), "RuleID": "probe", "StartLine": 1, "EndLine": 1}
    identity = ci_secrets.finding_identity(finding, tmp_path, history=False)
    assert identity == ("test_probe.py", "probe", hashlib.sha256(b"fixed test material").hexdigest())
    source.write_text("different content\n")
    assert ci_secrets.finding_identity(finding, tmp_path, history=False) != identity
    register = tmp_path / "exceptions.json"
    monkeypatch.setattr(ci_secrets, "EXCEPTIONS", register)
    entry = {"path": identity[0], "rule": identity[1], "line_sha256": identity[2],
             "reason": "fixed test material", "expires": "2000-01-01"}
    register.write_text(json.dumps({"secrets": [entry]}))
    with pytest.raises(ValueError, match="例外过期"):
        ci_secrets.exceptions()


def test_missing_or_empty_coverage_is_not_success(tmp_path):
    with pytest.raises(FileNotFoundError):
        ci_coverage.validate_report(tmp_path)
    (tmp_path / "coverage-python.json").write_text(json.dumps({"files": {}, "totals": {"num_statements": 0}}))
    with pytest.raises(RuntimeError, match="集合为空"):
        ci_coverage.validate_report(tmp_path)
