# myRimeCustom

个人自用的 Rime（Windows 小狼毫 / Weasel）用户配置与词库，通过**私有 Git 仓库**在多台设备间同步。

- **主力方案**：小鹤双拼
- **运行环境**：小狼毫 0.16.3（librime 1.11.2）
- **定位**：不是通用发行版，配置随自己的输入习惯持续调整

> 初始内容来自 [ASC8384/myRime](https://github.com/ASC8384/myRime)（MIT），现已按自己的需要大幅改造：
> 新增笔画筛选方案、候选词管理脚本、多设备同步、自建词表与自定义皮肤。许可与致谢见文末。

---

## 快速开始

新设备第一次接入（完整步骤见 [多设备同步](./SYNC.md)）：

1. 安装小狼毫，**退出它**，把 Rime 用户文件夹原有内容备份后清空
2. 在空出来的文件夹里克隆仓库：`git clone https://github.com/geomann/myRimeCustom .`
3. 启动小狼毫 → 重新部署 → 双击 `同步Rime.bat`，把其它设备的用户词典快照合并进来

> 仓库是私有的，克隆前先配好 GitHub 凭据。
> **不要**复制别的设备的 `installation.yaml`，设备 ID 必须由各设备自行生成。

---

## 输入方案

| 方案 | 名称 | 说明 |
| --- | --- | --- |
| `double_pinyin_flypy` | 小鶴雙拼 | 日常主力。主词典 + 自定义短语 + 英文 `easy_en` |
| `flypy_bt` | 小鹤双拼·笔画筛选（测试） | 实验方案：出候选后按 **Tab** 进入笔画辅码，再按 `h`横 `s`竖 `p`撇 `n`点 `z`折 筛选；`Ctrl+Shift+S` 或状态栏可开关 |
| `luna_pinyin_simp` | 朙月拼音·简化字 | 全拼备用 |

- 方案切换：**Ctrl + 反引号** 或 **Ctrl + F3**
- 候选每页 6 个
- 三个方案共用主词典 `luna_pinyin.extended`，所以自建词条**只需按全拼写一份**，
  小鹤的 `speller/algebra` 会在建索引时自动把全拼音节转成双拼键位

---

## 功能一览

| 功能 | 说明 | 配置位置 |
| --- | --- | --- |
| 简繁切换 | 默认输出简体 | `double_pinyin_flypy.custom.yaml` → `switches` |
| 全角／半角 | 默认半角 | 同上 |
| Emoji 建议 | 默认关闭 | 同上 + `opencc/emoji.json` |
| 符号支持 | 默认开启（「→符」），可用符号表 | `mysymbols.yaml` + `opencc/symbol.json` |
| 生僻字开关 | 「增廣／常用」——**本机实际未生效**，见「已知问题」 | `switches` → `gb2312` |
| 笔画反查 | 反引号进入，`hspnz` 对应 一丨丿丶乙 | `double_pinyin_flypy.custom.yaml` → `reverse_lookup` |
| 日期／时间 | 输入 `date` / `time` 直接出当前日期时间 | `lua/date.lua`、`lua/time.lua` |
| 英文输入 | 直接打英文单词，走 `easy_en` | `easy_en.schema.yaml` |
| 自定义短语 | `dicts/custom_phrase.txt`（公共）、`dicts/custom_personal.txt`（个人） | `user_dict` 配置 |
| 自建词表 | 词库里没有的词，例如「三个点」 | `dicts/custom_user.dict.yaml` |
| 屏蔽误词／常用词置顶 | Lua 滤镜，不改用户词典 | `lua/bad_words.lua`、`lua/preferred_words.lua` |
| 皮肤 | 18 套配色，当前 `sogouClassic`，横向候选，字号 15 | `weasel.style.yaml` |

---

## 维护脚本

根目录两个 `.bat` 是入口，对应两个 Python 脚本（需 Python 3.10+）。

### 管理候选词 — `管理候选词.bat` / `manage_words.py`

| 菜单 | 作用 | 写入位置 |
| --- | --- | --- |
| 1. 屏蔽误词 | 让某个候选彻底不出现 | `lua/bad_words.lua` |
| 2. 将常用词置顶 | 同码时把指定词提前 | `lua/preferred_words.lua` |
| 3. 取消屏蔽 | 撤销屏蔽 | `lua/bad_words.lua` |
| 4. 查看规则 | 只读，列出全部屏蔽、置顶与自建词条 | — |
| 5. 取消置顶 | 撤销置顶 | `lua/preferred_words.lua` |
| 6. 添加词库没有的词 | 把词库里没有的词加进词库 | `dicts/custom_user.dict.yaml` |
| 7. 删除自建词条 | 支持 `2`、`1-3`、`1,3` 选择 | 同上 |

第 6 项会问你全拼读音（如 `san ge dian`），当场显示换算出的编码（小鹤 `sjgedm` / 拼音 `sangedian`），
支持一词多音，权重默认 `999999`。详细说明见 [候选词脚本使用说明](./lua/README.md)。

也可以不进菜单直接用：

```bat
python manage_words.py --add "三个点" --reading "san ge dian"
python manage_words.py --list-custom
python manage_words.py --redeploy
```

### 同步 — `同步Rime.bat` / `sync_rime.py`

依次执行：导出本机用户词典 → 提交并变基到远端 `master` → 合并其它设备快照 → 重新部署 → 推送。
不会强制推送；遇到冲突会停下并保留本地提交。详见 [SYNC.md](./SYNC.md)。

---

## 部署要点

**推荐用 `python manage_words.py --redeploy`，或托盘菜单「重新部署」。**

两个已踩过的坑：

1. **本机 `WeaselDeployer.exe /deploy` 会静默失败**——日志停在 `loading weasel.custom.yaml`
   之后，`build/*.schema.yaml` 不更新、词典不重编，但退出码仍是 0。
   脚本因此改为直接调 librime 的 C API（`deployer_initialize → deploy → finalize`），有真实返回值。
2. **改 `dicts/` 下的词表，托盘「重新部署」不一定重编词典**。
   Rime 判断是否重编看的是源文件 checksum（`dict_compiler.cc` 的 `rebuild_table = ... dict_file_checksum`），
   而修改检测只扫用户文件夹**顶层** yaml 的 mtime，子目录里的变化它看不到。

改完词表想确认是否真生效，别去 `build/*.table.bin` 里搜中文——Table 格式是长度前缀 + 变长编码，
词条文本不是连续明文，搜不到不代表没编进去。

---

## 已知问题

| 问题 | 现象 | 状态 |
| --- | --- | --- |
| `charset_filter@gb2312` 不生效 | 日志报 `charset parameter is unsupported by basic charset_filter`，生僻字开关形同虚设 | 未解决，生僻字过滤不能依赖它 |
| 根目录 `custom_phrase.txt` 是历史遗留 | 与 `dicts/custom_phrase.txt` 内容相同；实际被引用的是后者（`user_dict: dicts/custom_phrase`） | 保留未删，改动请只改 `dicts/` 下那份 |

---

## 目录结构

```
<Rime 用户文件夹>/
├── default.custom.yaml              # 方案列表、每页候选数、方案切换快捷键
├── double_pinyin_flypy.schema.yaml  # 小鹤双拼方案
├── double_pinyin_flypy.custom.yaml  # 小鹤双拼补丁（开关、短语、英文、反查）
├── flypy_bt.schema.yaml             # 笔画筛选实验方案
├── luna_pinyin_simp.custom.yaml     # 朙月拼音补丁
├── luna_pinyin.extended.dict.yaml   # 主词典：用 import_tables 汇总所有词表
├── easy_en.schema.yaml / .dict.yaml # 英文输入
├── weasel.custom.yaml               # 引用下面的样式文件
├── weasel.style.yaml                # 皮肤：布局、字体、18 套配色
├── mysymbols.yaml                   # 符号表
├── rime.lua                         # 注册 Lua 翻译器与滤镜
├── lua/                             # Lua 脚本（见 lua/README.md）
├── dicts/                           # 词库（见 dicts/readme.md）
├── opencc/                          # emoji 与符号的分类/映射表
├── sync/                            # 各设备导出的用户词典快照
├── build/                           # 部署时生成的编译缓存，不要手改，不进 Git
├── 管理候选词.bat → manage_words.py
├── 同步Rime.bat   → sync_rime.py
└── SYNC.md                          # 多设备同步详细说明
```

### 哪些文件进 Git

- **同步**：方案与样式 YAML、`dicts/`、`lua/`、`opencc/`、自定义短语、维护脚本、
  `sync/<设备 ID>/*.userdb.txt`
- **不同步**：`build/` 编译缓存、`*.userdb/` 本机数据库、`installation.yaml`、`user.yaml`、
  调试日志、脚本备份。规则见 `.gitignore`

`sync/` 里的用户词典快照含个人输入习惯，所以仓库必须保持私有。

---

## 变更记录

### 2026-10-25

- 新增「添加词库没有的词」功能：自建词表 `dicts/custom_user.dict.yaml` +
  菜单第 6/7 项 + 命令行 `--add / --list-custom / --redeploy`
- `manage_words.py` 的部署改为 librime C API 驱动，修复 `WeaselDeployer` 静默失败的问题
- 扩充 [候选词脚本使用说明](./lua/README.md)
- 重写本 README（原内容为上游项目原文）

### 2026-10-24

- 建立本仓库，以本机 Rime 用户文件夹为配置来源，接入 `sync_rime.py` 多设备同步

---

## 上游与许可

本项目基于 [ASC8384/myRime](https://github.com/ASC8384/myRime) 改造，沿用其 **MIT License**
（Copyright © 2018 ASC_8384，见 [LICENSE](./LICENSE)）。

词库与方案素材来自以下项目，一并致谢：

- [雾凇拼音 rime-ice](https://github.com/iDvel/rime-ice)（`dicts/ice`）
- [四叶草拼音 rime-cloverpinyin](https://github.com/fkxxyz/rime-cloverpinyin)（`dicts/clover`）
- [rime-symbols](https://github.com/fkxxyz/rime-symbols)、[rime-emoji](https://github.com/rime/rime-emoji)
- [fcitx5-pinyin-zhwiki](https://github.com/ipcjs/fcitx5-pinyin-zhwiki)（`dicts/other`）
- 清华大学 thuocl 词库（`dicts/thuocl`）
- [Rime 本体与 wiki](https://github.com/rime/home/wiki)、[OpenCC](https://github.com/BYVoid/OpenCC)
- [深蓝词库转换](https://github.com/studyzy/imewlconverter)、搜狗细胞词库
