#!/usr/bin/env python3
"""Sync this Windows Rime user folder through Git and Rime snapshots."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def run(*args: str) -> None:
    print("运行：" + " ".join(args), flush=True)
    subprocess.run(args, cwd=ROOT, check=True)


def deployer() -> Path:
    candidates = []
    for key in ("ProgramFiles", "ProgramFiles(x86)"):
        folder = os.environ.get(key)
        if folder:
            candidates.extend((Path(folder) / "Rime").glob("weasel-*/WeaselDeployer.exe"))
    if not candidates:
        raise RuntimeError("找不到 WeaselDeployer.exe；请先安装小狼毫。")
    return sorted(candidates, reverse=True)[0]


def rime_action(executable: Path, action: str) -> None:
    print(f"Rime：{action}", flush=True)
    subprocess.run([str(executable), action], cwd=ROOT, check=True, timeout=120)


def commit_if_needed(message: str) -> bool:
    run("git", "add", "--all")
    staged = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT)
    if staged.returncode == 0:
        print("没有新的文件变更。")
        return False
    if staged.returncode != 1:
        raise RuntimeError("无法检查待提交文件。")
    run("git", "commit", "-m", message)
    return True


def main() -> int:
    if os.name != "nt":
        raise RuntimeError("此脚本用于 Windows 小狼毫；其他平台请按 README 手动同步。")
    top = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], cwd=ROOT,
        text=True, encoding="utf-8", capture_output=True, check=True,
    ).stdout.strip()
    if Path(top).resolve() != ROOT:
        raise RuntimeError("请将脚本放在 Git 管理的 Rime 用户文件夹根目录。")

    executable = deployer()
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Export this device's current learned words before pulling other devices.
    rime_action(executable, "/sync")
    commit_if_needed(f"Sync Rime from this PC {stamp}")

    # A failed rebase stops here. Never force push during routine sync.
    run("git", "pull", "--rebase", "origin", "master")

    # Rime merges all device snapshots now present under sync/.
    rime_action(executable, "/sync")
    commit_if_needed(f"Merge Rime user dictionaries {stamp}")
    rime_action(executable, "/deploy")
    run("git", "push", "origin", "master")
    print("配置和用户词典快照已同步。")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, RuntimeError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        print(f"同步中止：{exc}", file=sys.stderr)
        print("已保留本地文件和提交；解决错误后重新运行，不要强制推送。", file=sys.stderr)
        sys.exit(1)
