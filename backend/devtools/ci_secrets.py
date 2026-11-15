"""受控源码、提交范围与显式历史专项共用的脱敏密钥扫描。"""

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from datetime import UTC, date, datetime
from pathlib import Path

from backend.devtools.ci_changes import git
from backend.devtools.ci_tools import release_executable
from backend.devtools.isolated_environment import create_ci_artifact_dir

ROOT = Path(__file__).resolve().parents[2]
EXCEPTIONS = ROOT / "config/ci-security-exceptions.json"


def exceptions() -> list[dict]:
    """例外只能标识一条固定材料；过期、重复或不完整登记直接阻断。"""
    entries = json.loads(EXCEPTIONS.read_text())["secrets"]
    identities = set()
    for entry in entries:
        identity = (entry["path"], entry["rule"], entry["line_sha256"])
        if (not entry["reason"] or date.fromisoformat(entry["expires"]) <= datetime.now(UTC).date()
                or identity in identities or len(entry["line_sha256"]) != 64):
            raise ValueError("密钥扫描例外过期、重复或缺少精确对象/原因")
        if Path(entry["path"]).is_absolute() or ".." in Path(entry["path"]).parts:
            raise ValueError("密钥扫描例外必须使用仓库内精确文件路径")
        identities.add(identity)
    return entries


def finding_identity(finding: dict, source: Path, *, history: bool) -> tuple[str, str, str]:
    """用文件、规则及原始行摘要识别固定材料，报告和日志不写入明文凭据。"""
    path = Path(finding["File"])
    relative = path.relative_to(source).as_posix() if path.is_absolute() else path.as_posix()
    if Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise ValueError("扫描器返回仓库外路径")
    if history:
        content = subprocess.check_output(
            ["git", "show", f"{finding['Commit']}:{relative}"], cwd=ROOT, timeout=30,
        )
    else:
        content = (source / relative).read_bytes()
    lines = content.splitlines()
    start, end = finding["StartLine"], finding["EndLine"]
    if not 1 <= start <= end <= len(lines):
        raise RuntimeError("密钥扫描结果行范围无效")
    digest = hashlib.sha256(b"\n".join(lines[start - 1:end])).hexdigest()
    return relative, finding["RuleID"], digest


def run_secrets(selected_range: tuple[str, str] | None, *, history: bool = False) -> int:
    """普通入口扫描当前受控树和提交补丁；完整历史只由专项显式调用。"""
    allowed = {
        (entry["path"], entry["rule"], entry["line_sha256"]): entry
        for entry in exceptions()
    }
    artifacts = create_ci_artifact_dir()
    executable = release_executable("gitleaks")
    config = artifacts / "gitleaks.toml"
    config.write_text("[extend]\nuseDefault = true\n")
    ignore = artifacts / ".gitleaksignore"
    ignore.write_text("")
    flags = [
        "--config", str(config), "--gitleaks-ignore-path", str(ignore),
        "--ignore-gitleaks-allow", "--redact=100", "--no-banner", "--no-color",
        "--exit-code=20", "--timeout=300", "--report-format=json",
    ]
    matched_current, failed = set(), False
    with tempfile.TemporaryDirectory(prefix="secret-source-", dir=artifacts) as directory:
        snapshot = Path(directory)
        # 不复制 Git 忽略的个人配置、业务库或缓存；新文件默认纳入，符号链接只扫描链接文本。
        paths = git("ls-files", "--cached", "--others", "--exclude-standard", "-z").split("\0")
        count = 0
        if not history:
            for name in filter(None, paths):
                source = ROOT / name
                if not source.exists() and not source.is_symlink():
                    continue
                destination = snapshot / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                if source.is_symlink():
                    destination.write_text(os.readlink(source))
                else:
                    shutil.copyfile(source, destination)
                count += 1
            if not count:
                raise RuntimeError("密钥扫描受控源码集合为空")
        scans = [] if history else [("source", ["dir", str(snapshot)], snapshot, False)]
        log_options = "--all" if history else (
            f"{selected_range[0]}..{selected_range[1]}" if selected_range else "-1"
        )
        scans.append(("history" if history else "commits",
                      ["git", str(ROOT), f"--log-opts={log_options}"], ROOT, True))
        for label, command, source, from_git in scans:
            report = artifacts / f"secrets-{label}.json"
            code = subprocess.run(
                [str(executable), *command, *flags, "--report-path", str(report)],
                cwd=ROOT, check=False, timeout=330,
            ).returncode
            if code not in {0, 20} or not report.is_file():
                raise RuntimeError(f"密钥扫描未完成：{label}，退出码 {code}")
            findings = json.loads(report.read_text())
            if not isinstance(findings, list) or (code == 20 and not findings):
                raise RuntimeError("密钥扫描报告与退出状态不一致")
            rejected = []
            for finding in findings:
                identity = finding_identity(finding, source, history=from_git)
                if identity not in allowed:
                    rejected.append({"file": identity[0], "rule": identity[1], "line": finding["StartLine"]})
                elif not history:
                    matched_current.add(identity)
            failed |= bool(rejected)
            print(f"密钥扫描 {label}：{len(findings)} 项发现，{len(rejected)} 项未豁免；{report}")
            for finding in rejected:
                print(json.dumps(finding, ensure_ascii=False))
        if not history and set(allowed) - matched_current:
            raise ValueError("密钥扫描例外已失效，请删除未再命中的精确登记")
    return int(failed)
