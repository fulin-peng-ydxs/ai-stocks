"""CI 锁定、安装版本核对及依赖审计；不自动升级或忽略漏洞。"""

import hashlib
import json
import re
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

from backend.devtools.isolated_environment import create_ci_artifact_dir

ROOT = Path(__file__).resolve().parents[2]
LOCK = "requirements-ci.lock"


def input_paths() -> list[str]:
    """递归追踪 requirements include，新清单接入后无需另维护文件白名单。"""
    found = set()

    def visit(path: Path) -> None:
        relative = path.resolve().relative_to(ROOT.resolve()).as_posix()
        if relative in found:
            return
        found.add(relative)
        for line in path.read_text().splitlines():
            match = re.match(r"\s*(?:-r\s*|--requirement(?:=|\s+))([^\s#]+)", line)
            if match:
                visit(path.parent / match[1])

    visit(ROOT / "requirements-ci.txt")
    return sorted(found)


def input_digest() -> str:
    """绑定实际安装入口及所有 include；源清单变更必须显式重建锁。"""
    digest = hashlib.sha256()
    for name in input_paths():
        digest.update(name.encode() + b"\0" + (ROOT / name).read_bytes() + b"\0")
    return digest.hexdigest()


def check_lock() -> None:
    """轻量检查可在没有项目依赖的 Actions 规划阶段执行。"""
    text = (ROOT / LOCK).read_text()
    if f"# ai-stocks-input-sha256: {input_digest()}\n" not in text:
        raise ValueError("CI 依赖锁已过期，请执行 scripts/run-ci.sh lock 后复核差异")
    records = lock_records(text)
    if not records or any("--hash=sha256:" not in record for record in records):
        raise ValueError("CI 依赖锁必须非空且每项都有 SHA-256")
    if any(not re.match(r"[A-Za-z0-9_.-]+==[^\s;]+", record) for record in records):
        raise ValueError("CI 依赖必须锁定精确发行版本，禁止动态依赖")


def lock_records(text: str) -> list[str]:
    """将带哈希的 requirements 续行还原，保留平台条件。"""
    return [
        line.strip() for line in text.replace("\\\n", " ").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def locked_versions() -> dict[str, str]:
    """按当前解释器平台计算被实际安装的精确清单，不扫描 Conda 或用户全局环境。"""
    from packaging.requirements import Requirement

    check_lock()
    result = {}
    for record in lock_records((ROOT / LOCK).read_text()):
        requirement = Requirement(record.split(" --hash=", 1)[0].strip())
        if requirement.marker is None or requirement.marker.evaluate():
            result[requirement.name.lower().replace("_", "-")] = next(
                iter(requirement.specifier)
            ).version
    return result


def check_installed() -> None:
    """后端/数据库在运行前拒绝锁与实际版本漂移。"""
    for name, expected in locked_versions().items():
        if version(name) != expected:
            raise RuntimeError(f"CI 安装版本不一致：{name}，请按 {LOCK} 安装")


def lock_requirements(upgrades: list[str]) -> int:
    """复用现有锁保留版本；只有明确指定的包才允许升级，成功后再更新源指纹。"""
    command = [
        sys.executable, "-m", "uv", "pip", "compile", "requirements-ci.txt",
        "--universal", "--python-version", "3.12", "--generate-hashes",
        "--no-header", "--no-annotate", "--output-file", LOCK,
    ]
    for name in upgrades:
        command.extend(["--upgrade-package", name])
    result = subprocess.run(command, cwd=ROOT, check=False, timeout=600)
    if result.returncode == 0:
        path = ROOT / LOCK
        text = path.read_text()
        path.write_text(f"# ai-stocks-input-sha256: {input_digest()}\n" + text)
        check_lock()
    return result.returncode


def run_audit() -> int:
    """审计实际 CI 锁与 npm 锁的全部依赖；工具失败、缺报告和漏洞都失败。"""
    check_lock()
    artifacts = create_ci_artifact_dir()
    commands = [
        ([sys.executable, "-m", "pip_audit", "--strict", "--disable-pip", "--require-hashes",
          "-r", LOCK, "--format", "json", "--output", str(artifacts / "audit-python.json")],
         "audit-python.json"),
        (["npm", "--prefix", "frontend", "audit", "--json", "--package-lock-only",
          "--include=dev", "--registry=https://registry.npmjs.org"], "audit-npm.json"),
    ]
    failed = False
    for command, filename in commands:
        destination = artifacts / filename
        if filename == "audit-npm.json":
            with destination.open("w") as output:
                code = subprocess.run(command, cwd=ROOT, stdout=output, check=False, timeout=300).returncode
        else:
            code = subprocess.run(command, cwd=ROOT, check=False, timeout=300).returncode
        if not destination.is_file():
            raise RuntimeError(f"依赖审计报告缺失：{filename}")
        report = json.loads(destination.read_text())
        if filename == "audit-python.json":
            dependencies = report["dependencies"]
            actual = {entry["name"].lower().replace("_", "-"): entry["version"] for entry in dependencies}
            if actual != locked_versions() or any(entry.get("skip_reason") for entry in dependencies):
                raise RuntimeError("Python 审计集合与实际 CI 锁不一致或存在未审计项")
            findings = sum(len(entry["vulns"]) for entry in dependencies)
        else:
            if report.get("error") or not report.get("metadata", {}).get("dependencies", {}).get("total"):
                raise RuntimeError("npm 审计查询失败或依赖集合为空")
            findings = len(report["vulnerabilities"])
        failed |= bool(code or findings)
        print(f"{filename}：{findings} 项漏洞，退出码 {code}；报告 {destination}", flush=True)
    return int(failed)
