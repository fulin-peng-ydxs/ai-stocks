"""质量门禁的失败传播、完整收集与工具安装边界。"""

import hashlib
import io
import sys
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.devtools import ci_quality, ci_tools


def test_ruff_failure_stops_quality_before_workflow_check(monkeypatch):
    monkeypatch.setattr(ci_quality.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1))

    def unexpected_install():
        raise AssertionError("Ruff 失败后不得继续下载或执行 actionlint")

    monkeypatch.setattr(ci_quality, "actionlint_executable", unexpected_install)
    assert ci_quality.run_quality() == 1


def test_workflow_failure_propagates_and_all_yaml_files_are_checked(tmp_path, monkeypatch):
    workflows = tmp_path / ".github/workflows"
    workflows.mkdir(parents=True)
    paths = [workflows / "a.yml", workflows / "new.yaml"]
    for path in paths:
        path.write_text("invalid workflow")
    monkeypatch.setattr(ci_quality, "ROOT", tmp_path)
    monkeypatch.setattr(ci_quality, "actionlint_executable", lambda: Path("/test/actionlint"))
    calls = []

    def execute(arguments, **options):
        calls.append(arguments)
        return SimpleNamespace(returncode=0 if len(calls) == 1 else 1)

    monkeypatch.setattr(ci_quality.subprocess, "run", execute)
    assert ci_quality.run_quality() == 1
    assert calls[0][:4] == [sys.executable, "-m", "ruff", "check"]
    assert set(calls[1][3:]) == set(map(str, paths))


def test_empty_workflow_set_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(ci_quality, "ROOT", tmp_path)
    monkeypatch.setattr(ci_quality.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0))
    with pytest.raises(RuntimeError, match="集合为空"):
        ci_quality.run_quality()


@pytest.mark.parametrize("corrupt", [False, True])
def test_actionlint_installer_checks_archive_and_only_extracts_executable(
    tmp_path, monkeypatch, corrupt
):
    monkeypatch.setattr(ci_tools, "ROOT", tmp_path)
    monkeypatch.setattr(ci_tools.platform, "system", lambda: "Linux")
    monkeypatch.setattr(ci_tools.platform, "machine", lambda: "x86_64")
    source = f"#!{sys.executable}\nprint('{ci_quality.ACTIONLINT_VERSION}')\n".encode()
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, contents in [("actionlint", source), ("../unexpected", b"must not extract")]:
            member = tarfile.TarInfo(name)
            member.size = len(contents)
            archive.addfile(member, io.BytesIO(contents))
    archive_bytes = buffer.getvalue()
    digest = "0" * 64 if corrupt else hashlib.sha256(archive_bytes).hexdigest()
    filename = f"actionlint_{ci_quality.ACTIONLINT_VERSION}_linux_amd64.tar.gz"

    def response(url, **_options):
        assert url.startswith("https://github.com/rhysd/actionlint/releases/download/")
        contents = (
            f"{digest}  {filename}\n".encode() if url.endswith("checksums.txt") else archive_bytes
        )
        return io.BytesIO(contents)

    monkeypatch.setattr(ci_tools, "urlopen", response)
    if corrupt:
        with pytest.raises(RuntimeError, match="校验和"):
            ci_quality.actionlint_executable()
        assert not list(tmp_path.rglob("actionlint"))
    else:
        executable = ci_quality.actionlint_executable()
        assert executable.is_file()
        assert not (executable.parent.parent / "unexpected").exists()
        monkeypatch.setattr(
            ci_tools, "urlopen", lambda *_a, **_k: pytest.fail("缓存不应重复下载")
        )
        assert ci_quality.actionlint_executable() == executable
