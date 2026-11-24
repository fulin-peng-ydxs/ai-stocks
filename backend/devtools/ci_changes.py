"""本地、push 与 PR 共用的变更范围识别；信息不足时保守调用依赖审计。"""

import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def commit_range(base: str | None = None, head: str | None = None) -> tuple[str, str] | None:
    """只接受可验证的提交；新分支首推可从默认分支恢复基线，其余缺失范围保持未知。"""
    if base is None and head is None:
        event_path = os.environ.get("GITHUB_EVENT_PATH")
        if event_path:
            event = json.loads(Path(event_path).read_text())
            if "pull_request" in event:
                base = event["pull_request"]["base"]["sha"]
                head = event["pull_request"]["head"]["sha"]
                # PR 只比较共同祖先之后的修改，避免基线分支新增内容造成漏判。
                if valid_commit(base) and valid_commit(head):
                    base = git("merge-base", base, head).strip()
            else:
                base, head = event.get("before"), event.get("after")
                if base == "0" * 40:
                    base = _new_branch_base(event, head)
    if not valid_commit(base) or not valid_commit(head):
        return None
    return base, head


def _new_branch_base(event: dict, head: str | None) -> str | None:
    """首推覆盖功能分支全部提交；默认分支自身首推、标签和缺失历史不猜基线。"""
    repository = event.get("repository")
    default = repository.get("default_branch") if isinstance(repository, dict) else None
    ref = event.get("ref")
    if (event.get("created") is not True or event.get("deleted") is not False
            or not isinstance(default, str) or not default
            or not isinstance(ref, str) or not ref.startswith("refs/heads/")
            or ref == f"refs/heads/{default}"
            or not isinstance(head, str) or not valid_commit(head)):
        return None
    # Actions 的全历史 checkout 使用 origin；只使用已获取、可验证的远端引用，
    # 不从 HEAD 父提交猜测，避免功能分支首推包含多个提交时漏掉早期改动。
    default_ref = f"refs/remotes/origin/{default}"
    for candidate in (ref, default_ref):
        if subprocess.run(
            ["git", "check-ref-format", candidate], cwd=ROOT,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30, check=False,
        ).returncode != 0:
            return None
    try:
        target = git("rev-parse", "--verify", "--quiet", default_ref + "^{commit}").strip()
        if not valid_commit(target):
            return None
        return git("merge-base", target, head).strip()
    except subprocess.CalledProcessError as exc:
        # quiet rev-parse 找不到引用、merge-base 没有共同祖先均返回 1。
        # 其它 Git 故障保留原始失败，不伪装成可接受的空范围。
        if exc.returncode == 1:
            return None
        raise


def git(*arguments: str) -> str:
    """Git 参数始终按数组传递，输出只用于范围和路径判定。"""
    return subprocess.check_output(["git", *arguments], cwd=ROOT, text=True, timeout=30)


def valid_commit(value: str | None) -> bool:
    """禁止把选项或任意修订表达式传给 Git，并确认浅克隆中确有该提交。"""
    if not value or not re.fullmatch(r"[0-9a-fA-F]{40}", value) or set(value) == {"0"}:
        return False
    return subprocess.run(
        ["git", "cat-file", "-e", value + "^{commit}"], cwd=ROOT,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30, check=False,
    ).returncode == 0


def changed_paths(selected_range: tuple[str, str] | None) -> set[str] | None:
    """包含删除、重命名的两侧和本地未提交/新文件；范围未知不能推断为无变更。"""
    if selected_range is None:
        return None
    base, head = selected_range
    committed = git("diff", "--no-renames", "--name-only", "-z", base, head, "--")
    working = git("diff", "--no-renames", "--name-only", "-z", head, "--")
    added = git("ls-files", "--others", "--exclude-standard", "-z")
    return set(filter(None, (committed + working + added).split("\0")))
