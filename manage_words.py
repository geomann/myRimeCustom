#!/usr/bin/env python3
"""Interactive manager for this Rime user's blocked and preferred candidates."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


ROOT = Path(__file__).resolve().parent
BLOCKED_FILE = ROOT / "lua" / "bad_words.lua"
PREFERRED_FILE = ROOT / "lua" / "preferred_words.lua"
DICTIONARY_FILE = ROOT / "luna_pinyin.extended.dict.yaml"
FLYPY_CONFIG = ROOT / "double_pinyin_flypy.custom.yaml"
SCHEMAS = ("flypy_bt", "double_pinyin_flypy", "luna_pinyin_simp")
WORD_LIMIT = 80


def quoted(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def clean_word(value: str) -> str:
    value = value.strip()
    if not value or len(value) > WORD_LIMIT or any(ord(c) < 32 for c in value):
        raise ValueError(f"词必须为 1–{WORD_LIMIT} 个字符，且不能包含控制字符")
    return value


def load_blocked() -> list[str]:
    source = BLOCKED_FILE.read_text(encoding="utf-8-sig")
    body = re.search(r"local blocked = \{(.*?)^\}", source, re.M | re.S)
    if not body:
        raise ValueError(f"无法识别 {BLOCKED_FILE.name} 中的 blocked 表，未修改文件")
    result = []
    for line in body.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("--"):
            continue
        match = re.fullmatch(r'\[("(?:\\.|[^"\\])*")\]\s*=\s*true,?', line)
        if not match:
            raise ValueError(f"无法识别屏蔽规则：{line}")
        value = json.loads(match.group(1))
        if value not in result:
            result.append(value)
    return result


def render_blocked(words: list[str]) -> str:
    lines = [
        "-- Block candidate texts in all configured schemes.",
        "-- Managed by manage_words.py; you can also edit this list by hand.",
        "local blocked = {",
    ]
    lines += [f"  [{quoted(word)}] = true," for word in words]
    lines += [
        "}", "", "return function(input, env)",
        "  for cand in input:iter() do",
        "    if not blocked[cand.text] then", "      yield(cand)",
        "    end", "  end", "end", "",
    ]
    return "\n".join(lines)


def load_preferred() -> dict[str, dict[str, list[str]]]:
    source = PREFERRED_FILE.read_text(encoding="utf-8-sig")
    result: dict[str, dict[str, list[str]]] = {}
    current = None
    started = False
    finished = False
    for line in source.splitlines():
        if not line.strip() or line.lstrip().startswith("--"):
            continue
        if line == "return {" and not started:
            started = True
            continue
        if not started or finished:
            raise ValueError("置顶规则文件的结构无法识别，未修改文件")
        if line == "}":
            if current is not None:
                raise ValueError("置顶规则文件缺少方案结束符")
            finished = True
            continue
        scheme = re.fullmatch(r"  ([a-z][a-z0-9_]*) = \{", line)
        if scheme and current is None:
            current = scheme.group(1)
            result[current] = {}
            continue
        if line == "  }," and current is not None:
            current = None
            continue
        rule = re.fullmatch(r"    ([a-z][a-z0-9]*) = \{\s*(.*?)\s*\},", line)
        if rule and current is not None:
            words = json.loads("[" + rule.group(2) + "]")
            if not words or not all(isinstance(w, str) for w in words):
                raise ValueError(f"无效的置顶规则：{line}")
            result[current][rule.group(1)] = list(dict.fromkeys(words))
            continue
        raise ValueError(f"无法识别置顶规则：{line}")
    if not started or not finished:
        raise ValueError("置顶规则文件不完整，未修改文件")
    return result


def render_preferred(rules: dict[str, dict[str, list[str]]]) -> str:
    lines = [
        "-- Promote existing candidates for an exact input code.",
        "-- Managed by manage_words.py; format: schema -> code -> words in order.",
        "return {",
    ]
    for schema in dict.fromkeys((*SCHEMAS, *rules)):
        lines.append(f"  {schema} = {{")
        for code, words in rules.get(schema, {}).items():
            values = ", ".join(quoted(w) for w in words)
            lines.append(f"    {code} = {{ {values} }},")
        lines.append("  },")
    lines += ["}", ""]
    return "\n".join(lines)


def imported_dictionaries() -> list[Path]:
    source = DICTIONARY_FILE.read_text(encoding="utf-8-sig")
    paths = []
    in_imports = False
    for line in source.splitlines():
        if line.startswith("import_tables:"):
            in_imports = True
            continue
        if not in_imports:
            continue
        if line == "...":
            break
        match = re.match(r"\s+-\s+([\w./-]+)", line)
        if match:
            path = ROOT / (match.group(1) + ".dict.yaml")
            if path.is_file():
                paths.append(path)
    return paths


def lookup_pronunciations(words: set[str]) -> dict[str, set[str]]:
    """Scan only active imported tables; unannotated words cannot be inferred."""
    found = {word: set() for word in words}
    for path in imported_dictionaries():
        with path.open("r", encoding="utf-8-sig") as dictionary:
            for line in dictionary:
                if not line or line.startswith("#"):
                    continue
                fields = line.rstrip("\r\n").split("\t", 2)
                if len(fields) >= 2 and fields[0] in found:
                    pronunciation = fields[1].strip().lower()
                    if re.fullmatch(r"[a-z]+(?: [a-z]+)*", pronunciation):
                        found[fields[0]].add(pronunciation)
    return found


def flypy_transforms() -> tuple[list[tuple[re.Pattern[str], str]], dict[int, int]]:
    """Read xform/xlit from the installed Flypy schema, avoiding a second key map."""
    transforms = []
    translation = {}
    source = FLYPY_CONFIG.read_text(encoding="utf-8-sig")
    in_algebra = False
    for line in source.splitlines():
        if re.match(r"^    algebra:\s*$", line):
            in_algebra = True
            continue
        if in_algebra and re.match(r"^  \S", line):
            break
        if not in_algebra:
            continue
        match = re.match(r"\s+-\s+(xform|xlit)/([^/]*)/([^/]*)/", line)
        if not match:
            continue
        kind, pattern, replacement = match.groups()
        if kind == "xform":
            replacement = re.sub(r"\$(\d+)", r"\\g<\1>", replacement)
            transforms.append((re.compile(pattern), replacement))
        elif len(pattern) == len(replacement):
            translation = str.maketrans(pattern, replacement)
    if not transforms or not translation:
        raise ValueError("无法读取小鹤双拼编码规则；请手动输入编码")
    return transforms, translation


def flypy_code(pronunciation: str) -> str:
    transforms, translation = flypy_transforms()
    output = []
    for syllable in pronunciation.split():
        code = syllable
        for pattern, replacement in transforms:
            code = pattern.sub(replacement, code)
        code = code.translate(translation).lower()
        if not re.fullmatch(r"[a-z]{2}", code):
            raise ValueError(f"无法可靠换算双拼编码：{syllable} → {code}")
        output.append(code)
    return "".join(output)


def choose_pronunciation(word: str, reference: str) -> str | None:
    words = {word, reference} if reference else {word}
    found = lookup_pronunciations(words)
    available = found[word]
    print(f"词库中的「{word}」读音：{', '.join(sorted(available)) or '未找到'}")
    if reference:
        print(f"词库中的「{reference}」读音：{', '.join(sorted(found[reference])) or '未找到'}")
        available = available & found[reference]
        if not available:
            print("没有找到共同读音，无法自动判定同码。")
    choices = sorted(available)
    if not choices:
        return None
    for number, pronunciation in enumerate(choices, 1):
        try:
            code = flypy_code(pronunciation)
        except ValueError:
            code = "无法换算"
        print(f"  {number}. {pronunciation} → 双拼 {code} / 拼音 {pronunciation.replace(' ', '')}")
    if len(choices) == 1:
        return choices[0]
    response = input("选择读音编号（直接回车取消）：").strip()
    if response.isdigit() and 1 <= int(response) <= len(choices):
        return choices[int(response) - 1]
    return None


def choose_manual_codes() -> dict[str, str]:
    print("请输入输入法候选栏中实际使用的编码；留空的方案不会修改。")
    flypy = input("小鹤双拼编码（两个双拼方案共用）：").strip().lower()
    pinyin = input("朙月拼音编码：").strip().lower()
    for code in (flypy, pinyin):
        if code and not re.fullmatch(r"[a-z]+", code):
            raise ValueError("编码只能包含英文字母；请重新运行")
    result = {}
    if flypy:
        result.update({"flypy_bt": flypy, "double_pinyin_flypy": flypy})
    if pinyin:
        result["luna_pinyin_simp"] = pinyin
    return result


def print_rule_diff(before: dict[str, dict[str, list[str]]], after: dict[str, dict[str, list[str]]]) -> None:
    for schema in SCHEMAS:
        for code in sorted(set(before.get(schema, {})) | set(after.get(schema, {}))):
            old = before.get(schema, {}).get(code, [])
            new = after.get(schema, {}).get(code, [])
            if old != new:
                print(f"  {schema} / {code}: {old or '原始顺序'} → {new or '原始顺序'}")


def save_changes(changes: dict[Path, str]) -> Path:
    backup_dir = ROOT / "word_manager_backups" / (datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6])
    backup_dir.mkdir(parents=True)
    staged = {}
    try:
        for path, content in changes.items():
            shutil.copy2(path, backup_dir / path.name)
            temp = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
            temp.write_text(content, encoding="utf-8", newline="\n")
            staged[path] = temp
        for path, temp in staged.items():
            os.replace(temp, path)
    except Exception:
        for path in changes:
            saved = backup_dir / path.name
            if saved.exists():
                shutil.copy2(saved, path)
        raise
    finally:
        for temp in staged.values():
            temp.unlink(missing_ok=True)
    return backup_dir


def deploy() -> None:
    candidates = []
    for key in ("ProgramFiles", "ProgramFiles(x86)"):
        folder = os.environ.get(key)
        if folder:
            candidates += list((Path(folder) / "Rime").glob("weasel-*/WeaselDeployer.exe"))
    if not candidates:
        print("未找到 WeaselDeployer.exe；请在小狼毫托盘菜单中手动选择“重新部署”。")
        return
    executable = sorted(candidates, reverse=True)[0]
    try:
        subprocess.run([str(executable), "/deploy"], cwd=ROOT, check=True, timeout=120)
        print("小狼毫已重新部署。")
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        print(f"自动部署未完成：{exc}\n请在小狼毫托盘菜单中手动选择“重新部署”。")


def main() -> int:
    parser = argparse.ArgumentParser(description="管理 Rime 的误词屏蔽和常用词置顶规则")
    parser.add_argument("--no-deploy", action="store_true", help="保存规则但不自动部署")
    parser.add_argument("--lookup", metavar="词", help="只查询词库读音，不修改文件")
    args = parser.parse_args()
    if args.lookup:
        word = clean_word(args.lookup)
        found = lookup_pronunciations({word})[word]
        print(f"{word}: {', '.join(sorted(found)) or '未找到带注音的词条'}")
        return 0

    blocked = load_blocked()
    preferred = load_preferred()
    print("Rime 候选词管理（只修改 Lua 规则，不修改 .userdb）")
    print("1. 屏蔽误词  2. 将常用词置顶  3. 取消屏蔽  4. 查看规则  5. 取消置顶  0. 退出")
    action = input("请选择：").strip()
    changes: dict[Path, str] = {}

    if action == "1":
        word = clean_word(input("要屏蔽的词："))
        if word in blocked:
            print(f"「{word}」已经在屏蔽列表中，无需修改。")
            return 0
        updated = {schema: {code: [w for w in words if w != word] for code, words in codes.items()}
                   for schema, codes in preferred.items()}
        updated = {schema: {code: words for code, words in codes.items() if words}
                   for schema, codes in updated.items()}
        print(f"将屏蔽所有候选文字恰好为「{word}」的词条。")
        print_rule_diff(preferred, updated)
        if input("确认写入？[y/N] ").strip().lower() != "y":
            print("已取消。")
            return 0
        changes[BLOCKED_FILE] = render_blocked([*blocked, word])
        if updated != preferred:
            changes[PREFERRED_FILE] = render_preferred(updated)

    elif action == "2":
        word = clean_word(input("要置顶的词："))
        reference_input = input("希望排在谁前面？可留空：").strip()
        reference = clean_word(reference_input) if reference_input else ""
        pronunciation = choose_pronunciation(word, reference)
        if pronunciation:
            try:
                flypy = flypy_code(pronunciation)
                codes = {"flypy_bt": flypy, "double_pinyin_flypy": flypy,
                         "luna_pinyin_simp": pronunciation.replace(" ", "")}
            except ValueError as exc:
                print(exc)
                codes = choose_manual_codes()
        else:
            codes = choose_manual_codes()
        if not codes:
            print("没有选定编码，已取消。")
            return 0
        updated = {schema: {code: words.copy() for code, words in items.items()}
                   for schema, items in preferred.items()}
        for schema, code in codes.items():
            schema_rules = updated.setdefault(schema, {})
            previous = schema_rules.get(code, [])
            schema_rules[code] = [word, *[w for w in previous if w != word]]
        print("将修改以下候选顺序：")
        print_rule_diff(preferred, updated)
        if word in blocked:
            print(f"「{word}」目前被屏蔽；置顶时会同时取消屏蔽。")
        if updated == preferred and word not in blocked:
            print("规则已是目标顺序，无需修改。")
            return 0
        if input("确认写入？[y/N] ").strip().lower() != "y":
            print("已取消。")
            return 0
        changes[PREFERRED_FILE] = render_preferred(updated)
        if word in blocked:
            changes[BLOCKED_FILE] = render_blocked([w for w in blocked if w != word])

    elif action == "3":
        word = clean_word(input("要取消屏蔽的词："))
        if word not in blocked:
            print(f"「{word}」不在屏蔽列表中。")
            return 0
        if input(f"确认恢复「{word}」？[y/N] ").strip().lower() != "y":
            print("已取消。")
            return 0
        changes[BLOCKED_FILE] = render_blocked([w for w in blocked if w != word])

    elif action == "4":
        print("屏蔽词：", "、".join(blocked) or "无")
        for schema in SCHEMAS:
            print(f"{schema}：")
            for code, words in preferred.get(schema, {}).items():
                print(f"  {code} → {'、'.join(words)}")
        return 0
    elif action == "5":
        word = clean_word(input("要取消置顶的词："))
        updated = {schema: {code: [w for w in words if w != word] for code, words in codes.items()}
                   for schema, codes in preferred.items()}
        updated = {schema: {code: words for code, words in codes.items() if words}
                   for schema, codes in updated.items()}
        if updated == preferred:
            print(f"「{word}」没有置顶规则。")
            return 0
        print_rule_diff(preferred, updated)
        if input("确认取消？[y/N] ").strip().lower() != "y":
            print("已取消。")
            return 0
        changes[PREFERRED_FILE] = render_preferred(updated)
    elif action in ("0", ""):
        return 0
    else:
        print("无效选项。")
        return 2

    backup = save_changes(changes)
    print(f"规则已保存；原文件备份于：{backup}")
    if not args.no_deploy:
        deploy()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"错误：{error}", file=sys.stderr)
        sys.exit(1)
