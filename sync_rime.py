#!/usr/bin/env python3
"""Sync this Windows Rime user folder through Git and Rime snapshots."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
REMOTE = "origin"
BRANCH = "master"
REPO_URL = "https://github.com/geomann/myRimeCustom"


def call(*args: str) -> subprocess.CompletedProcess[str]:
    """Run a command quietly and keep its output for diagnostics."""
    return subprocess.run(args, cwd=ROOT, text=True, encoding="utf-8",
                          errors="replace", capture_output=True)


def run(*args: str, interactive: bool = False) -> str:
    """Run a command, echo its output, and fail with a readable message.

    `interactive=True` leaves stdio attached to the console: `git pull` and
    `git push` must be able to prompt for GitHub credentials the first time,
    and a captured pipe makes git report "terminal prompts disabled" instead.
    """
    print("运行：" + " ".join(args), flush=True)
    if interactive:
        result = subprocess.run(args, cwd=ROOT)
        if result.returncode != 0:
            raise RuntimeError(f"命令失败：{' '.join(args)}（退出码 {result.returncode}）")
        return ""
    result = call(*args)
    for stream in (result.stdout, result.stderr):
        text = (stream or "").strip()
        if text:
            print(text, flush=True)
    if result.returncode != 0:
        raise RuntimeError(f"命令失败：{' '.join(args)}（退出码 {result.returncode}）")
    return result.stdout


def check_repository() -> None:
    """Fail early with an actionable hint instead of git's bare exit code 128."""
    try:
        result = call("git", "rev-parse", "--show-toplevel")
    except FileNotFoundError:
        raise RuntimeError("找不到 git 命令；请安装 Git for Windows 并加入 PATH。") from None
    detail = (result.stderr or "").strip()
    if result.returncode != 0:
        if "not a git repository" in detail:
            raise RuntimeError(
                "这个文件夹不是 Git 仓库（缺少 .git 目录）。\n"
                "整盘复制过来的 Rime 文件夹经常丢 .git，在本目录按顺序执行即可恢复：\n"
                f"  git init -b {BRANCH}\n"
                f"  git remote add {REMOTE} {REPO_URL}\n"
                f"  git fetch {REMOTE}\n"
                f"  git reset --mixed {REMOTE}/{BRANCH}"
            )
        if "dubious ownership" in detail:
            raise RuntimeError(
                "Git 认为这个文件夹属于其他用户（从别的电脑复制过来时常见）。任选一种处理：\n"
                f'  icacls "{ROOT}" /setowner "%USERNAME%"\n'
                f"  git config --global --add safe.directory {ROOT.as_posix()}"
            )
        raise RuntimeError("无法读取 Git 仓库：\n" + (detail or "（无输出）"))
    if Path(result.stdout.strip()).resolve() != ROOT:
        raise RuntimeError("请将脚本放在 Git 管理的 Rime 用户文件夹根目录。")


def check_git_setup() -> None:
    """Remote and committer identity must exist, or the sync stops halfway."""
    if REMOTE not in call("git", "remote").stdout.split():
        raise RuntimeError(
            f"没有配置远端 {REMOTE}，无法同步。请执行：\n"
            f"  git remote add {REMOTE} {REPO_URL}"
        )
    missing = [key for key in ("user.name", "user.email")
               if not call("git", "config", key).stdout.strip()]
    if missing:
        raise RuntimeError(
            "Git 没有配置提交者身份，提交会失败。请执行：\n"
            '  git config user.name "你的名字"\n'
            '  git config user.email "你的邮箱"'
        )


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
    run(str(executable), action)


def commit_if_needed(message: str) -> bool:
    run("git", "add", "--all")
    staged = call("git", "diff", "--cached", "--quiet")
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
    check_repository()
    check_git_setup()

    executable = deployer()
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Export this device's current learned words before pulling other devices.
    rime_action(executable, "/sync")
    commit_if_needed(f"Sync Rime from this PC {stamp}")

    # A failed rebase stops here. Never force push during routine sync.
    run("git", "pull", "--rebase", REMOTE, BRANCH, interactive=True)

    # Rime merges all device snapshots now present under sync/.
    rime_action(executable, "/sync")
    commit_if_needed(f"Merge Rime user dictionaries {stamp}")
    rime_action(executable, "/deploy")
    try:
        run("git", "push", REMOTE, BRANCH, interactive=True)
    except RuntimeError as exc:
        raise RuntimeError(
            f"{exc}\n推送被拒绝。第一次推送需要在弹窗里登录 GitHub（凭据由 Git Credential "
            "Manager 保存，只需一次）；若仓库已改为私有，拉取时同样会要求登录。"
        ) from exc
    print("配置和用户词典快照已同步。")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"同步中止：{exc}", file=sys.stderr)
        print("已保留本地文件和提交；解决错误后重新运行，不要强制推送。", file=sys.stderr)
        sys.exit(1)
