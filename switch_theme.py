#!/usr/bin/env python3
"""按数字选择切换小狼毫配色方案，并自动重新部署。

配色方案列表读自 weasel.style.yaml 的 preset_color_schemes 段，
切换时只改 style/color_scheme 这一行，注释与格式保持原样。

用法:
    python switch_theme.py              # 交互式，输入编号选择
    python switch_theme.py 5            # 直接切到第 5 套
    python switch_theme.py --set stele  # 按方案名切换
    python switch_theme.py --list       # 只列出，不修改
    python switch_theme.py --no-deploy  # 改完不部署
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import unicodedata
import uuid
from datetime import datetime
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


ROOT = Path(__file__).resolve().parent
STYLE_FILE = ROOT / "weasel.style.yaml"
BACKUP_ROOT = ROOT / "word_manager_backups"

SCHEMES_HEADER = "preset_color_schemes:"
# 这几个字段决定候选栏最直观的观感，用于终端里画色块预览。
PREVIEW_FIELDS = (
    "back_color",
    "candidate_text_color",
    "hilited_candidate_back_color",
    "hilited_candidate_text_color",
)


def enable_ansi() -> None:
    """Windows 控制台默认不解析 ANSI 转义；跑一次空命令即可打开 VT 处理。"""
    if os.name == "nt":
        try:
            os.system("")
        except Exception:
            pass


def read_style() -> str:
    """整文件读入，newline='' 保留原始 CRLF，避免改动其它行。"""
    with STYLE_FILE.open("r", encoding="utf-8-sig", newline="") as handle:
        return handle.read()


def parse_schemes(text: str) -> list[dict]:
    rows: list[dict] = []
    current: dict | None = None
    in_block = False
    for line in text.splitlines():
        if line.startswith(SCHEMES_HEADER):
            in_block = True
            continue
        if not in_block:
            continue
        if line and not line[0].isspace() and not line.lstrip().startswith("#"):
            break  # 离开 preset_color_schemes 段
        heading = re.match(r"^  ([A-Za-z][A-Za-z0-9_]*):\s*$", line)
        if heading:
            current = {"key": heading.group(1), "name": "", "colors": {}}
            rows.append(current)
            continue
        field = re.match(r"^    ([A-Za-z_]+):\s*(.+)$", line)
        if field and current is not None:
            label, value = field.group(1), field.group(2).split("#")[0].strip()
            if label == "name":
                current["name"] = value.strip('"').strip("'")
            elif label in PREVIEW_FIELDS:
                current["colors"][label] = value
    return rows


def current_key(text: str) -> str:
    match = re.search(r"^[ \t]*color_scheme:[ \t]*(\S+)", text, re.M)
    return match.group(1) if match else ""


def rewrite(text: str, key: str) -> str:
    pattern = re.compile(r"^([ \t]*color_scheme:[ \t]*)(\S+)([ \t]*(?:#.*)?)(\r?)$", re.M)
    if not pattern.search(text):
        raise ValueError(f"{STYLE_FILE.name} 里找不到 color_scheme 这一行")
    return pattern.sub(lambda m: m.group(1) + key + m.group(3) + m.group(4), text, count=1)


def to_rgb(value: str) -> tuple[int, int, int] | None:
    """Rime/小狼毫 的色值是 0xBBGGRR，转成 (R, G, B)。"""
    try:
        number = int(value, 16)
    except (TypeError, ValueError):
        return None
    return number & 0xFF, (number >> 8) & 0xFF, (number >> 16) & 0xFF


def is_dark(row: dict) -> bool:
    rgb = to_rgb(row["colors"].get("back_color", "0xFFFFFF"))
    if rgb is None:
        return False
    red, green, blue = rgb
    return 0.299 * red + 0.587 * green + 0.114 * blue < 128


def swatch(row: dict, use_color: bool) -> str:
    if not use_color:
        return ""
    back = to_rgb(row["colors"].get("back_color", "0xFFFFFF"))
    text = to_rgb(row["colors"].get("candidate_text_color", "0x000000"))
    hit_back = to_rgb(row["colors"].get("hilited_candidate_back_color", "0xFFFFFF"))
    hit_text = to_rgb(row["colors"].get("hilited_candidate_text_color", "0x000000"))
    if None in (back, text, hit_back, hit_text):
        return ""
    return (
        f"  \x1b[48;2;{back[0]};{back[1]};{back[2]}m"
        f"\x1b[38;2;{text[0]};{text[1]};{text[2]}m 候选 \x1b[0m"
        f"\x1b[48;2;{hit_back[0]};{hit_back[1]};{hit_back[2]}m"
        f"\x1b[38;2;{hit_text[0]};{hit_text[1]};{hit_text[2]}m 首选 \x1b[0m"
    )


def display_width(text: str) -> int:
    """中日韩字符在终端里占两格，按显示宽度算才能对齐。"""
    return sum(2 if unicodedata.east_asian_width(char) in ("W", "F") else 1 for char in text)


def pad(text: str, width: int) -> str:
    return text + " " * max(0, width - display_width(text))


def print_rows(rows: list[dict], current: str, use_color: bool) -> None:
    width = len(str(len(rows)))
    for number, row in enumerate(rows, 1):
        mark = "●" if row["key"] == current else " "
        tone = "暗" if is_dark(row) else "亮"
        print(f" {mark} {number:>{width}}. {pad(row['key'], 22)}{pad(row['name'], 24)} {tone}"
              f"{swatch(row, use_color)}")


def save_style(text: str) -> Path:
    """备份原文件后原子写入，保留 CRLF。"""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    backup_dir = BACKUP_ROOT / stamp
    backup_dir.mkdir(parents=True)
    shutil.copy2(STYLE_FILE, backup_dir / STYLE_FILE.name)
    temp = STYLE_FILE.with_name(STYLE_FILE.name + ".tmp-" + uuid.uuid4().hex)
    try:
        with temp.open("w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        os.replace(temp, STYLE_FILE)
    finally:
        temp.unlink(missing_ok=True)
    return backup_dir


def redeploy() -> None:
    try:
        from manage_words import deploy  # 与候选词脚本共用同一套 librime API 部署
    except Exception as error:  # noqa: BLE001 - 部署只是收尾，失败要能降级
        print(f"无法调用部署逻辑（{error}）；请在小狼毫托盘菜单选择「重新部署」。")
        return
    deploy()


def resolve(args, rows: list[dict]) -> dict | None:
    if args.set:
        for row in rows:
            if row["key"] == args.set:
                return row
        valid = "、".join(row["key"] for row in rows)
        raise ValueError(f"没有名为「{args.set}」的配色方案。可选：{valid}")
    if args.number is not None:
        if not 1 <= args.number <= len(rows):
            raise ValueError(f"编号必须在 1–{len(rows)} 之间")
        return rows[args.number - 1]
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="切换小狼毫配色方案并重新部署")
    parser.add_argument("number", nargs="?", type=int, help="直接指定编号（从 1 开始）")
    parser.add_argument("--set", metavar="方案名", help="按方案名切换，例如 stele")
    parser.add_argument("--list", action="store_true", help="只列出配色方案，不修改")
    parser.add_argument("--no-deploy", action="store_true", help="保存后不自动部署")
    parser.add_argument("--no-color", action="store_true", help="不输出彩色预览")
    args = parser.parse_args()

    if not STYLE_FILE.is_file():
        print(f"找不到 {STYLE_FILE}", file=sys.stderr)
        return 1

    use_color = not args.no_color
    if use_color:
        enable_ansi()

    text = read_style()
    rows = parse_schemes(text)
    if not rows:
        print(f"{STYLE_FILE.name} 里没有读到 preset_color_schemes，未修改任何文件。", file=sys.stderr)
        return 1
    current = current_key(text)
    known = {row["key"] for row in rows}

    print(f"小狼毫配色切换（共 {len(rows)} 套，当前：{current or '未设置'}）")
    print_rows(rows, current, use_color)
    if current and current not in known:
        print(f"\n注意：当前配色「{current}」不在这个列表里（可能是小狼毫内置配色）。")

    if args.list:
        return 0

    try:
        chosen = resolve(args, rows)
        if chosen is None:
            answer = input(f"\n请输入编号 1–{len(rows)}（回车退出）：").strip()
            if not answer:
                print("已退出，未做修改。")
                return 0
            if not answer.isdigit() or not 1 <= int(answer) <= len(rows):
                print(f"「{answer}」不是有效编号，未做修改。", file=sys.stderr)
                return 2
            chosen = rows[int(answer) - 1]
    except ValueError as error:
        print(f"{error}", file=sys.stderr)
        return 2

    key = chosen["key"]
    if key == current:
        print(f"\n已经是「{key}」，无需修改。")
        return 0

    backup = save_style(rewrite(text, key))
    print(f"\n已切换：{current or '未设置'} → {key}"
          f"{'（' + chosen['name'] + '）' if chosen['name'] else ''}")
    print(f"备份：{backup}")
    if args.no_deploy:
        print("已按 --no-deploy 跳过部署；生效需要在托盘菜单「重新部署」。")
    else:
        redeploy()

    print("\n复用速查")
    print("  交互选择：切换配色.bat   或   python switch_theme.py")
    print("  直接切换：python switch_theme.py <编号>")
    print("  按名字切：python switch_theme.py --set <方案名>")
    print("  只看列表：python switch_theme.py --list")
    print("  改配置文件：weasel.style.yaml 的 style/color_scheme")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError) as error:
        print(f"错误：{error}", file=sys.stderr)
        sys.exit(1)
