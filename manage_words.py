#!/usr/bin/env python3
"""Interactive manager for this Rime user's blocked and preferred candidates."""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import getpass
import json
import os
import re
import shutil
import struct
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
CUSTOM_WORDS_FILE = ROOT / "dicts" / "custom_user.dict.yaml"
CUSTOM_TABLE = "dicts/custom_user"
FLYPY_CONFIG = ROOT / "double_pinyin_flypy.custom.yaml"
SCHEMAS = ("flypy_bt", "double_pinyin_flypy", "luna_pinyin_simp")
WORD_LIMIT = 80
DEFAULT_WEIGHT = 999999
CJK_RANGE = ("\u3400", "\u9fff")


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


_PRONUNCIATION_CACHE: dict[str, set[str]] = {}


def lookup_pronunciations(words: set[str]) -> dict[str, set[str]]:
    """Scan only active imported tables; unannotated words cannot be inferred.

    One scan costs a couple of seconds, and the interactive flow asks about the
    same words more than once, so results are cached per word for this run.
    """
    missing = {word for word in words if word not in _PRONUNCIATION_CACHE}
    if missing:
        for word in missing:
            _PRONUNCIATION_CACHE[word] = set()
        for path in imported_dictionaries():
            with path.open("r", encoding="utf-8-sig") as dictionary:
                for line in dictionary:
                    if not line or line.startswith("#"):
                        continue
                    fields = line.rstrip("\r\n").split("\t", 2)
                    if len(fields) >= 2 and fields[0] in missing:
                        pronunciation = fields[1].strip().lower()
                        if re.fullmatch(r"[a-z]+(?: [a-z]+)*", pronunciation):
                            _PRONUNCIATION_CACHE[fields[0]].add(pronunciation)
    return {word: set(_PRONUNCIATION_CACHE[word]) for word in words}


_SYLLABLES: set[str] | None = None


def known_syllables() -> set[str]:
    """Union of every syllable used by the active dictionaries; cached for one run."""
    global _SYLLABLES
    if _SYLLABLES is None:
        collected: set[str] = set()
        for path in imported_dictionaries():
            with path.open("r", encoding="utf-8-sig") as dictionary:
                for line in dictionary:
                    if not line or line.startswith("#"):
                        continue
                    fields = line.rstrip("\r\n").split("\t", 2)
                    if len(fields) >= 2:
                        collected.update(fields[1].strip().lower().split())
        _SYLLABLES = collected
    return _SYLLABLES


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


def is_all_cjk(text: str) -> bool:
    return bool(text) and all(CJK_RANGE[0] <= char <= CJK_RANGE[1] for char in text)


def normalize_reading(value: str) -> str:
    """Accept full pinyin with space separated syllables, e.g. 'san ge dian'."""
    value = " ".join(value.strip().lower().split())
    if not re.fullmatch(r"[a-z]+(?: [a-z]+)*", value):
        raise ValueError("读音只能是小写英文字母，音节之间用空格分隔，例如：san ge dian")
    return value


def describe_codes(pronunciation: str) -> tuple[str, str]:
    """Return (flypy code, pinyin code) for one full pinyin reading."""
    return flypy_code(pronunciation), pronunciation.replace(" ", "")


def scheme_codes(flypy: str, pinyin: str) -> dict[str, str]:
    """Same rule for the two Flypy schemas plus the pinyin schema."""
    return {"flypy_bt": flypy, "double_pinyin_flypy": flypy, "luna_pinyin_simp": pinyin}


def describe_scheme_codes(codes: dict[str, str]) -> str:
    return "，".join(f"{schema} = {codes[schema]}" for schema in SCHEMAS if schema in codes)


def normalize_code(value: str) -> str:
    """Accept whatever keys the candidate bar really uses, prefixes included."""
    code = value.strip().lower()
    if code and not re.fullmatch(r"[a-z]+", code):
        raise ValueError("编码只能包含英文字母；请重新运行")
    return code


def first_keys(readings: set[str]) -> tuple[set[str], set[str]]:
    """First key of every single-syllable reading: (flypy keys, pinyin keys).

    Multi-syllable readings return empty sets: a one-letter rule would then also
    match unrelated prefixes, so we refuse to guess.
    """
    flypy_keys: set[str] = set()
    pinyin_keys: set[str] = set()
    for reading in readings:
        if len(reading.split()) != 1:
            return set(), set()
        pinyin_keys.add(reading[0])
        try:
            flypy_keys.add(flypy_code(reading)[0])
        except ValueError:
            return set(), set()
    return flypy_keys, pinyin_keys


def initial_code_suggestion(word: str, reference: str = "") -> dict[str, str] | None:
    """One-key rule that still reaches the word (and the reference, if given).

    Typing a single letter makes the translator emit every candidate whose code
    starts with it, so `l` reaches both 「了」(le/liao) and 「来」(lai) even though
    they share no complete reading.
    """
    words = {word, reference} if reference else {word}
    found = lookup_pronunciations(words)
    flypy_keys, pinyin_keys = first_keys(found[word])
    if not flypy_keys or not pinyin_keys:
        return None
    if reference:
        ref_flypy, ref_pinyin = first_keys(found[reference])
        flypy_keys &= ref_flypy
        pinyin_keys &= ref_pinyin
    if len(flypy_keys) != 1 or len(pinyin_keys) != 1:
        return None
    return scheme_codes(flypy_keys.pop(), pinyin_keys.pop())


def confirm(message: str, default: bool = False) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    answer = input(f"{message} {suffix} ").strip().lower()
    if not answer:
        return default
    return answer in ("y", "yes", "是")


def parse_selection(value: str, count: int) -> list[int]:
    """Parse '1', '1-3', '1,3' style selections into sorted 1-based indexes."""
    picked: list[int] = []
    for part in value.replace("，", ",").split(","):
        part = part.strip()
        if not part:
            continue
        low, separator, high = part.partition("-")
        if separator and low.strip().isdigit() and high.strip().isdigit():
            picked += list(range(int(low), int(high) + 1))
        elif part.isdigit():
            picked.append(int(part))
    return sorted({number for number in picked if 1 <= number <= count})


def load_custom_words() -> list[tuple[str, str, int]]:
    """Read the self-maintained word table as [(text, full pinyin code, weight)]."""
    if not CUSTOM_WORDS_FILE.is_file():
        return []
    entries: list[tuple[str, str, int]] = []
    for line in CUSTOM_WORDS_FILE.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith("---") or line.startswith("..."):
            continue
        fields = line.split("\t")
        if len(fields) < 2:
            continue  # header keys such as "name: custom_user"
        text = fields[0].strip()
        code = fields[1].strip()
        weight = 0
        if len(fields) >= 3 and fields[2].strip().isdigit():
            weight = int(fields[2].strip())
        if text and re.fullmatch(r"[a-z]+(?: [a-z]+)*", code):
            entries.append((text, code, weight))
    return entries


def render_custom_words(entries: list[tuple[str, str, int]]) -> str:
    lines = [
        "# Rime dictionary: custom_user",
        "# 由 manage_words.py 生成；也可以手工编辑后重新部署。",
        "# 格式：文字<TAB>全拼码（音节用空格分隔）<TAB>权重，权重越大候选越靠前。",
        "---",
        "name: custom_user",
        f'version: "{datetime.now().strftime("%Y.%m.%d")}"',
        "sort: by_weight",
        "...",
    ]
    lines += [f"{text}\t{code}\t{weight}" for text, code, weight in entries]
    return "\n".join(lines) + "\n"


def ensure_custom_table(source: str) -> tuple[str, bool]:
    """Idempotently register the custom table in import_tables; keeps comments intact."""
    if re.search(r"^\s*-\s*" + re.escape(CUSTOM_TABLE) + r"\b", source, re.M):
        return source, False
    lines = source.splitlines(keepends=True)
    ending = "\r\n" if "\r\n" in source[:4096] else "\n"
    for index, line in enumerate(lines):
        if line.startswith("import_tables:"):
            lines.insert(index + 1, f"  - {CUSTOM_TABLE} # manage_words.py 自建词条{ending}")
            return "".join(lines), True
    raise ValueError(f"在 {DICTIONARY_FILE.name} 中找不到 import_tables 段，未修改文件")


def prompt_weight() -> int | None:
    while True:
        print(f"权重：数值越大候选越靠前（回车 = {DEFAULT_WEIGHT}）")
        raw = input("权重：").strip()
        if not raw:
            return DEFAULT_WEIGHT
        if raw.isdigit() and int(raw) > 0:
            return int(raw)
        print("  请输入正整数，或直接回车使用默认值。")


def collect_readings(word: str) -> list[str]:
    """Ask for one or more full pinyin readings for a word."""
    known = sorted(lookup_pronunciations({word})[word])
    if known:
        print(f"词库中已存在「{word}」的读音：{'、'.join(known)}")
        if confirm("直接使用这些读音？", default=True):
            return known
    print("请输入全拼读音，音节之间用空格分隔（例如：三个点 → san ge dian）")
    readings: list[str] = []
    while True:
        raw = input(f"第 {len(readings) + 1} 个读音{'' if readings else '（回车取消）'}：").strip()
        if not raw:
            if readings:
                break
            return []
        try:
            reading = normalize_reading(raw)
            flypy, pinyin = describe_codes(reading)
        except ValueError as error:
            print(f"  {error}")
            continue
        print(f"  {reading}  →  小鹤双拼 {flypy}   朙月拼音 {pinyin}")
        if reading not in readings:
            readings.append(reading)
        if not confirm("还要再加一个读音吗？", default=False):
            break
    return readings


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


def choose_manual_codes(suggestion: dict[str, str] | None = None) -> dict[str, str]:
    print("请输入输入法候选栏中实际使用的编码；留空的方案不会修改。")
    print("  可以填完整编码（如 le），也可以只填你实际打出的前缀（如单字母 l）。")
    if suggestion:
        print(f"  参考：{describe_scheme_codes(suggestion)}")
    shared = normalize_code(input("三个方案共用的编码（直接回车则按方案分别填写）："))
    if shared:
        return scheme_codes(shared, shared)
    flypy = normalize_code(input("小鹤双拼编码（两个双拼方案共用）："))
    pinyin = normalize_code(input("朙月拼音编码："))
    result: dict[str, str] = {}
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
    created: list[Path] = []
    try:
        for path, content in changes.items():
            if path.exists():
                shutil.copy2(path, backup_dir / path.name)
            else:
                created.append(path)
            path.parent.mkdir(parents=True, exist_ok=True)
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
            elif path in created:
                path.unlink(missing_ok=True)
        raise
    finally:
        for temp in staged.values():
            temp.unlink(missing_ok=True)
    return backup_dir


class RimeTraits(ctypes.Structure):
    _fields_ = [
        ("data_size", ctypes.c_int),
        ("shared_data_dir", ctypes.c_char_p),
        ("user_data_dir", ctypes.c_char_p),
        ("distribution_name", ctypes.c_char_p),
        ("distribution_code_name", ctypes.c_char_p),
        ("distribution_version", ctypes.c_char_p),
        ("app_name", ctypes.c_char_p),
        ("modules", ctypes.POINTER(ctypes.c_char_p)),
        ("min_log_level", ctypes.c_int),
        ("log_dir", ctypes.c_char_p),
        ("prebuilt_data_dir", ctypes.c_char_p),
        ("staging_dir", ctypes.c_char_p),
    ]


class RimeApiHead(ctypes.Structure):
    """Prefix of rime_api_t up to `deploy_config_file`; later members are never touched."""

    _fields_ = [
        ("data_size", ctypes.c_int),
        ("setup", ctypes.c_void_p),
        ("set_notification_handler", ctypes.c_void_p),
        ("initialize", ctypes.c_void_p),
        ("finalize", ctypes.c_void_p),
        ("start_maintenance", ctypes.c_void_p),
        ("is_maintenance_mode", ctypes.c_void_p),
        ("join_maintenance_thread", ctypes.c_void_p),
        ("deployer_initialize", ctypes.c_void_p),
        ("prebuild", ctypes.c_void_p),
        ("deploy", ctypes.c_void_p),
        ("deploy_schema", ctypes.c_void_p),
        ("deploy_config_file", ctypes.c_void_p),
    ]


# 前端（小狼毫外观）配置不走 workspace_update，要单独编译成 build/weasel.yaml。
UI_CONFIG_FILE = "weasel.yaml"
UI_CONFIG_VERSION_KEY = "config_version"


def weasel_directory() -> Path | None:
    found = []
    for key in ("ProgramFiles", "ProgramFiles(x86)"):
        folder = os.environ.get(key)
        if folder:
            found += [path for path in (Path(folder) / "Rime").glob("weasel-*") if path.is_dir()]
    return sorted(found, reverse=True)[0] if found else None


# ---- 与运行中的小狼毫前端对话（复刻官方部署器的完整协议）----
# 只调 rime->deploy() 不够：官方 Configurator::UpdateWorkspace()（weasel 0.16.3，
# WeaselDeployer/Configurator.cpp:120-158）在部署前后还会通过命名管道让
# WeaselServer 进入/退出维护模式：
#   START_MAINTENANCE -> RimeWithWeaselHandler::StartMaintenance() 释放词典、清会话
#   END_MAINTENANCE   -> RimeWithWeaselHandler::EndMaintenance() 重新 initialize、
#                        重新打开 weasel 配置并把新样式应用到 UI
# 少了这两步，编译好的 build/weasel.yaml 不会运行中的进程加载，表现为
# "配色换了却没生效，要手动重新部署"。
# 协议：客户端写 12 字节 PipeMessage{DWORD Msg, wParam, lParam}，
# 服务端读一条、处理、回一条 4 字节 DWORD 结果。
# 管道名 \\.\pipe\<用户名>\WeaselNamedPipe（WeaselIPC.h:8-9, 181-186）。
WM_APP = 0x8000
# 枚举值逐个数自 WeaselIPC.h:17-35，别手滑：
#   ECHO=+1 START_SESSION=+2 END_SESSION=+3 PROCESS_KEY_EVENT=+4
#   SHUTDOWN_SERVER=+5 FOCUS_IN=+6 FOCUS_OUT=+7 UPDATE_INPUT_POS=+8
#   START_MAINTENANCE=+9 END_MAINTENANCE=+10
WEASEL_IPC_START_MAINTENANCE = WM_APP + 9
WEASEL_IPC_END_MAINTENANCE = WM_APP + 10
PIPE_NAME_SUFFIX = "WeaselNamedPipe"
PIPE_TIMEOUT_MS = 5000
GENERIC_READ_WRITE = 0xC0000000
OPEN_EXISTING = 3
PIPE_READMODE_MESSAGE = 2


def weasel_pipe_path() -> str:
    user = os.environ.get("USERNAME") or getpass.getuser()
    return "\\\\.\\pipe\\" + user + "\\" + PIPE_NAME_SUFFIX


def _send_weasel_command(command: int) -> bool:
    """向 WeaselServer 发一条 IPC 命令；服务端没跑或管道不通时返回 False。"""
    if os.name != "nt":
        return False
    kernel32 = ctypes.windll.kernel32
    invalid_handle = ctypes.c_void_p(-1).value
    kernel32.CreateFileW.restype = ctypes.wintypes.HANDLE
    kernel32.CreateFileW.argtypes = [
        ctypes.wintypes.LPCWSTR, ctypes.wintypes.DWORD, ctypes.wintypes.DWORD,
        ctypes.wintypes.LPVOID, ctypes.wintypes.DWORD, ctypes.wintypes.DWORD,
        ctypes.wintypes.HANDLE,
    ]
    kernel32.WaitNamedPipeW.argtypes = [ctypes.wintypes.LPCWSTR, ctypes.wintypes.DWORD]
    kernel32.SetNamedPipeHandleState.argtypes = [
        ctypes.wintypes.HANDLE, ctypes.wintypes.LPDWORD,
        ctypes.wintypes.LPDWORD, ctypes.wintypes.LPDWORD,
    ]
    kernel32.WriteFile.argtypes = [
        ctypes.wintypes.HANDLE, ctypes.wintypes.LPCVOID, ctypes.wintypes.DWORD,
        ctypes.wintypes.LPDWORD, ctypes.wintypes.LPVOID,
    ]
    kernel32.ReadFile.argtypes = [
        ctypes.wintypes.HANDLE, ctypes.wintypes.LPVOID, ctypes.wintypes.DWORD,
        ctypes.wintypes.LPDWORD, ctypes.wintypes.LPVOID,
    ]
    kernel32.FlushFileBuffers.argtypes = [ctypes.wintypes.HANDLE]
    kernel32.DisconnectNamedPipe.argtypes = [ctypes.wintypes.HANDLE]
    kernel32.CloseHandle.argtypes = [ctypes.wintypes.HANDLE]
    name = weasel_pipe_path()
    kernel32.WaitNamedPipeW(name, PIPE_TIMEOUT_MS)
    handle = kernel32.CreateFileW(name, GENERIC_READ_WRITE, 0, None,
                                  OPEN_EXISTING, 0, None)
    if not handle or handle == invalid_handle:
        return False
    try:
        mode = ctypes.c_ulong(PIPE_READMODE_MESSAGE)
        kernel32.SetNamedPipeHandleState(handle, ctypes.byref(mode), None, None)
        payload = struct.pack("<III", command, 0, 0)
        written = ctypes.wintypes.DWORD()
        if not kernel32.WriteFile(handle, payload, len(payload),
                                  ctypes.byref(written), None):
            return False
        kernel32.FlushFileBuffers(handle)
        # 服务端回一条 DWORD（4 字节）结果；读不到也不影响部署结果
        reply = ctypes.create_string_buffer(4)
        read = ctypes.wintypes.DWORD()
        kernel32.ReadFile(handle, reply, 4, ctypes.byref(read), None)
        return True
    except (OSError, ValueError):
        return False
    finally:
        kernel32.DisconnectNamedPipe(handle)
        kernel32.CloseHandle(handle)


def weasel_maintenance(enter: bool) -> bool:
    """enter=True 让 WeaselServer 进入维护模式；False 恢复服务并重载配置。"""
    command = WEASEL_IPC_START_MAINTENANCE if enter else WEASEL_IPC_END_MAINTENANCE
    return _send_weasel_command(command)


def deploy_via_api() -> bool:
    """Rebuild dictionaries by driving librime directly.

    `WeaselDeployer.exe /deploy` stops right after loading weasel.custom.yaml on this
    machine and never recompiles dictionaries, so build/*.table.bin stays stale.
    The C API runs installation_update -> workspace_update synchronously.
    """
    home = weasel_directory()
    if home is None:
        return False
    library_path = home / "rime.dll"
    if not library_path.is_file():
        return False
    try:
        library = ctypes.CDLL(str(library_path))
        resolve = library.rime_get_api
        resolve.restype = ctypes.c_void_p
        head = RimeApiHead.from_address(resolve())
        if not head.deployer_initialize or not head.deploy:
            return False
        traits = RimeTraits()
        traits.data_size = ctypes.sizeof(RimeTraits) - ctypes.sizeof(ctypes.c_int)
        traits.shared_data_dir = str(home / "data").encode()
        traits.user_data_dir = str(ROOT).encode()
        traits.distribution_name = "小狼毫".encode()
        traits.distribution_code_name = b"Weasel"
        traits.distribution_version = home.name.partition("-")[2].encode() or b"0"
        traits.app_name = b"rime.deployer"
        traits.min_log_level = 3
        log_dir = Path(os.environ.get("TEMP", str(ROOT))) / "rime.weasel"
        log_dir.mkdir(parents=True, exist_ok=True)
        traits.log_dir = str(log_dir).encode()
        traits.prebuilt_data_dir = None
        # Must be absolute: SetupDeployer stores it verbatim (setup.cc:62-69), so a
        # relative value would be resolved against the process cwd.
        traits.staging_dir = str(ROOT / "build").encode()

        initialize = ctypes.CFUNCTYPE(None, ctypes.POINTER(RimeTraits))(head.deployer_initialize)
        deploy_workspace = ctypes.CFUNCTYPE(ctypes.c_bool)(head.deploy)
        finalize = ctypes.CFUNCTYPE(None)(head.finalize)
        initialize(ctypes.byref(traits))
        # 与官方部署器保持一致：先让运行中的小狼毫进入维护模式（释放词典），
        # 部署完成、本进程 finalize 之后再恢复服务，服务端才会重新加载
        # build/weasel.yaml 并刷新外观。
        engaged = weasel_maintenance(True)
        try:
            workspace_ok = bool(deploy_workspace())
            # 外观配置（weasel.style.yaml 等）不在 workspace_update 里，
            # 由 config_file_update 单独编译成 build/weasel.yaml；漏掉这步换配色不会生效。
            if head.deploy_config_file:
                deploy_config = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_char_p, ctypes.c_char_p)(
                    head.deploy_config_file)
                config_ok = bool(deploy_config(UI_CONFIG_FILE.encode(),
                                               UI_CONFIG_VERSION_KEY.encode()))
            else:
                config_ok = True
            return workspace_ok and config_ok
        finally:
            finalize()
            if engaged:
                weasel_maintenance(False)
    except (OSError, AttributeError, TypeError, ValueError):
        return False


@contextlib.contextmanager
def quiet_stderr():
    """librime logs to fd 2 directly; mute it so the interactive menu stays readable."""
    if os.environ.get("RIME_DEPLOY_VERBOSE"):
        yield
        return
    try:
        sys.stderr.flush()
        saved = os.dup(2)
    except (OSError, ValueError):
        yield
        return
    try:
        sink = os.open(os.devnull, os.O_WRONLY)
        os.dup2(sink, 2)
        os.close(sink)
        yield
    finally:
        os.dup2(saved, 2)
        os.close(saved)


def deploy() -> None:
    print("正在重新部署（词典重建可能需要一两分钟）…")
    with quiet_stderr():
        deployed = deploy_via_api()
    if deployed:
        print("已重新部署，新内容已生效。")
        return
    home = weasel_directory()
    executable = home / "WeaselDeployer.exe" if home else None
    if executable is None or not executable.is_file():
        print("未找到 WeaselDeployer.exe；请在小狼毫托盘菜单中手动选择“重新部署”。")
        return
    try:
        subprocess.run([str(executable), "/deploy"], cwd=str(home), check=True, timeout=180)
        print("小狼毫已重新部署。")
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        print(f"自动部署未完成：{exc}\n请在小狼毫托盘菜单中手动选择“重新部署”。")


def summarize_readings(readings: list[str]) -> str:
    parts = []
    for reading in readings:
        try:
            flypy, pinyin = describe_codes(reading)
        except ValueError:
            flypy, pinyin = "无法换算", reading.replace(" ", "")
        parts.append(f"{reading}（小鹤 {flypy} / 拼音 {pinyin}）")
    return "；".join(parts)


def build_add_changes(word: str, readings: list[str], weight: int) -> tuple[dict[Path, str], list[tuple[str, str, int]]]:
    invalid = []
    for reading in readings:
        try:
            describe_codes(reading)
        except ValueError:
            invalid.append(reading)
    if invalid:
        raise ValueError("这些读音无法换算成小鹤双拼，请检查拼写（例如 diann 应为 dian）：" + "、".join(invalid))
    unknown = sorted({syllable for reading in readings for syllable in reading.split()}
                     - known_syllables())
    if unknown:
        print(f"提示：这些音节不在当前任何词表中，可能拼错了：{'、'.join(unknown)}")
    entries = load_custom_words()
    existing = {(text, code) for text, code, _ in entries}
    added = [(word, reading, weight) for reading in readings if (word, reading) not in existing]
    if not added:
        return {}, []
    changes: dict[Path, str] = {CUSTOM_WORDS_FILE: render_custom_words([*entries, *added])}
    source = DICTIONARY_FILE.read_text(encoding="utf-8-sig")
    patched, registered = ensure_custom_table(source)
    if registered:
        changes[DICTIONARY_FILE] = patched
    return changes, added


def action_add_word() -> dict[Path, str]:
    word = clean_word(input("要添加的词（词库里本来没有的）："))
    existing = {text for text, _, _ in load_custom_words()}
    if word in existing:
        print(f"「{word}」已在自建词表中。")
        if not confirm("继续（会追加新的读音）？", default=False):
            return {}
    readings = collect_readings(word)
    if not readings:
        print("没有输入读音，已取消。")
        return {}
    if is_all_cjk(word) and any(len(reading.split()) != len(word) for reading in readings):
        print(f"提示：「{word}」是 {len(word)} 个字，读音音节数与此不一致，请事后确认是否有误。")
    weight = prompt_weight()
    if weight is None:
        print("已取消。")
        return {}
    changes, added = build_add_changes(word, readings, weight)
    if not added:
        print(f"「{word}」的这些读音都已存在，无需修改。")
        return {}
    print("将写入自建词表：")
    for text, code, value in added:
        print(f"  {text}\t{code}\t{value}")
    print(f"编码：{summarize_readings([code for _, code, _ in added])}")
    if DICTIONARY_FILE not in changes:
        print(f"{DICTIONARY_FILE.name} 已挂载 {CUSTOM_TABLE}，无需修改。")
    if not confirm("确认写入并重新部署？", default=False):
        print("已取消。")
        return {}
    return changes


def action_remove_word() -> dict[Path, str]:
    entries = load_custom_words()
    if not entries:
        print(f"自建词表为空（{CUSTOM_WORDS_FILE} 不存在或没有词条）。")
        return {}
    print("自建词条：")
    for number, (text, code, weight) in enumerate(entries, 1):
        print(f"  {number}. {text}  （{code}，权重 {weight}）")
    raw = input("要删除的编号，支持 1 / 1-3 / 1,3（回车取消）：").strip()
    picked = parse_selection(raw, len(entries))
    if not picked:
        print("已取消。")
        return {}
    removing = [entries[number - 1] for number in picked]
    print("将删除：")
    for text, code, weight in removing:
        print(f"  {text}\t{code}\t{weight}")
    if not confirm("确认删除？", default=False):
        print("已取消。")
        return {}
    remaining = [entry for number, entry in enumerate(entries, 1) if number not in picked]
    return {CUSTOM_WORDS_FILE: render_custom_words(remaining)}


def print_custom_words() -> None:
    entries = load_custom_words()
    print(f"自建词条（{CUSTOM_WORDS_FILE.name}）：{len(entries)} 条")
    for number, (text, code, weight) in enumerate(entries, 1):
        print(f"  {number}. {text}  （{code}，权重 {weight}）")


def main() -> int:
    parser = argparse.ArgumentParser(description="管理 Rime 的误词屏蔽、常用词置顶与自建词条")
    parser.add_argument("--no-deploy", action="store_true", help="保存规则但不自动部署")
    parser.add_argument("--lookup", metavar="词", help="只查询词库读音，不修改文件")
    parser.add_argument("--add", metavar="词", help="把词库里没有的词加入自建词表")
    parser.add_argument("--reading", action="append", default=[], metavar="全拼",
                        help="配合 --add 使用：全拼读音，可重复多次表示多音")
    parser.add_argument("--weight", type=int, default=DEFAULT_WEIGHT,
                        help=f"配合 --add 使用：词条权重（默认 {DEFAULT_WEIGHT}）")
    parser.add_argument("--list-custom", action="store_true", help="列出自建词条")
    parser.add_argument("--redeploy", action="store_true", help="只重新部署，不修改任何文件")
    parser.add_argument("--yes", action="store_true", help="配合 --add：跳过确认")
    args = parser.parse_args()

    if args.redeploy:
        deploy()
        return 0

    if args.lookup:
        word = clean_word(args.lookup)
        found = lookup_pronunciations({word})[word]
        print(f"{word}: {', '.join(sorted(found)) or '未找到带注音的词条'}")
        return 0

    if args.list_custom:
        print_custom_words()
        return 0

    if args.add:
        word = clean_word(args.add)
        readings = [normalize_reading(value) for value in args.reading]
        if not readings:
            print("错误：--add 需要至少一个 --reading（全拼读音，例如 \"san ge dian\"）", file=sys.stderr)
            return 2
        if args.weight <= 0:
            print("错误：--weight 必须是正整数", file=sys.stderr)
            return 2
        changes, added = build_add_changes(word, readings, args.weight)
        if not added:
            print(f"「{word}」的这些读音都已存在，无需修改。")
            return 0
        for text, code, value in added:
            print(f"待写入：{text}\t{code}\t{value}")
        if not args.yes and not confirm("确认写入并重新部署？", default=False):
            print("已取消。")
            return 0
        backup = save_changes(changes)
        print(f"已保存；原文件备份于：{backup}")
        print(f"编码：{summarize_readings([code for _, code, _ in added])}")
        if not args.no_deploy:
            deploy()
        return 0

    blocked = load_blocked()
    preferred = load_preferred()
    print("Rime 候选词管理（屏蔽与置顶只改 Lua 规则，自建词条写入独立词表）")
    print("1. 屏蔽误词  2. 将常用词置顶  3. 取消屏蔽  4. 查看规则")
    print("5. 取消置顶  6. 添加词库没有的词  7. 删除自建词条  0. 退出")
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
                codes = scheme_codes(flypy_code(pronunciation), pronunciation.replace(" ", ""))
            except ValueError as exc:
                print(exc)
                codes = choose_manual_codes()
            else:
                print(f"完整编码：{describe_scheme_codes(codes)}")
                initial = initial_code_suggestion(word)
                if initial and initial != codes:
                    print(f"只按首字母：{describe_scheme_codes(initial)}"
                          f"（打一个字母时也会把「{word}」提前）")
                    if confirm("改用首字母置顶？", default=False):
                        codes = initial
        else:
            suggestion = initial_code_suggestion(word, reference)
            if suggestion:
                print(f"两者读音不同，但都能用同一个首字母打出来：{describe_scheme_codes(suggestion)}")
                if confirm("按首字母置顶？", default=True):
                    codes = suggestion
                else:
                    codes = choose_manual_codes(suggestion)
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
        print_custom_words()
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
    elif action == "6":
        changes = action_add_word()
        if not changes:
            return 0
    elif action == "7":
        changes = action_remove_word()
        if not changes:
            return 0
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
