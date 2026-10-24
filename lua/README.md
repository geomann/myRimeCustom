# 候选词脚本使用说明

本目录中的候选词脚本用于屏蔽误词、调整候选顺序，以及把词库里没有的词加入自建词表。当前已接入 `flypy_bt`、`double_pinyin_flypy` 和 `luna_pinyin_simp` 三个方案；修改规则后重新部署小狼毫即可生效。

## 最方便的用法

双击 Rime 用户文件夹根目录的 `管理候选词.bat`，或在该目录运行 `python manage_words.py`。按菜单选择需要的操作：

1. 屏蔽误词：输入要屏蔽的完整词条。工具会检查是否已经屏蔽，并移除相冲突的置顶规则。
2. 常用词置顶：输入希望置顶的词；可再输入一个希望排在它后面的词，帮助工具找出它们共有的拼音。工具会从当前导入的静态词库查读音，自动换算小鹤双拼编码，展示三个方案的旧顺序和新顺序。
3. 碰到多音字时选择正确读音；词库中查不到带注音的词时，按提示手动填写实际输入编码。
4. 添加词库里没有的词：见下方“添加词库没有的词”。
5. 确认后，工具会备份原文件、写入改动并自动重新部署小狼毫。

菜单还可以取消屏蔽、取消置顶、删除自建词条或查看当前规则。备份存放在根目录的 `word_manager_backups/` 中。要只查询读音，可以运行 `python manage_words.py --lookup 是`；要保存规则但暂不部署，可加 `--no-deploy`；只想重新部署可以运行 `python manage_words.py --redeploy`。需要 Python 3.10 或更新版本。

“屏蔽”是让词不再出现在候选中，“置顶”是调整候选顺序；两者都不直接修改 `.userdb` 或词库数字词频。置顶词必须已经是对应编码的候选，且位于脚本向后查找的前 100 个候选内。

## 文件位置与加载方式

以下路径都相对于 **Rime 用户文件夹**（本机为 `D:\software\Rime\myRime`）：

| 文件 | 用途 | 平时需要修改？ |
| --- | --- | --- |
| `lua/bad_words.lua` | 列出不想看到的候选词，并过滤它们 | 添加误词时修改 |
| `lua/preferred_words.lua` | 按方案和输入编码列出要置顶的词 | 调整顺序时修改 |
| `lua/preferred_words_filter.lua` | 执行候选重排 | 通常不用修改 |
| `rime.lua` | 用 `require(...)` 注册过滤器 | 通常不用修改 |
| `dicts/custom_user.dict.yaml` | 自建词表（词库里没有的词） | 用菜单第 6/7 项维护，也可手工改 |
| `luna_pinyin.extended.dict.yaml` | 主词典，用 `import_tables` 汇总各词表 | 脚本会自动挂载 `dicts/custom_user` |

方案配置里的 `lua_filter@bad_words_filter` 和 `lua_filter@preferred_words_filter` 是过滤器名称，不是文件路径。`rime.lua` 中的 `require("preferred_words_filter")` 会加载 `lua/preferred_words_filter.lua`；后者再加载 `lua/preferred_words.lua`。规则文件里只写方案名、编码和候选文字，不写磁盘路径。

## 屏蔽误词

编辑 `lua/bad_words.lua` 中的 `blocked` 表，每个词占一行：

```lua
local blocked = {
  ["手机商"] = true,
  ["另一个误词"] = true,
}
```

规则按**完整候选文字**匹配，作用于已接入的三个方案，不区分候选来自静态词库还是用户词典。它只隐藏候选，不会删除词库或 `.userdb` 中的数据。

## 常用词置顶

编辑 `lua/preferred_words.lua`。规则结构是 `方案名 = { 输入编码 = { "第一位", "第二位" } }`：

```lua
return {
  flypy_bt = {
    ui = { "是", "事" },
  },
  double_pinyin_flypy = {
    ui = { "是" },
  },
  luna_pinyin_simp = {
    shi = { "是" },
  },
}
```

这是**修改示例**；实际文件目前只将“是”置顶。小鹤双拼的“是”输入码为 `ui`，朙月拼音为 `shi`。如果想在两个双拼方案里使用同一规则，需要分别写在 `flypy_bt` 和 `double_pinyin_flypy` 下。新增规则时保留各行末尾的逗号。

置顶只在**完整输入编码**匹配时生效，而且目标词必须已经是该编码的候选。脚本最多向后查找 100 个候选；找到后将目标词按列表顺序提前，其余候选仍保留。它不会给词增加新编码，也不会修改真实词频或用户词典。

## 添加词库没有的词

菜单第 6 项可以把词库里本来没有的词加入自建词表，写好后重新部署就能直接打出来。

1. 输入要添加的词，例如 `三个点`。
2. 输入全拼读音，音节之间用空格分隔，例如 `san ge dian`。工具会立刻显示换算结果：小鹤双拼 `sjgedm`、朙月拼音 `sangedian`。
3. 同一个词有多个读音时会继续追问，可以用来处理多音字。
4. 权重直接回车即用默认值 `999999`，数值越大候选越靠前。
5. 确认后工具会写入 `dicts/custom_user.dict.yaml`，必要时在 `luna_pinyin.extended.dict.yaml` 的 `import_tables` 中挂载该词表，然后自动重新部署。

**码位只写全拼。** 三套方案共用 `luna_pinyin.extended` 主词典，而小鹤双拼方案的 `speller/algebra` 会在建索引时用 `xform` 规则把全拼音节自动转成双拼键位（见 `build/double_pinyin_flypy.schema.yaml` 的 `speller/algebra`），所以一份全拼码表就能同时覆盖 `flypy_bt`、`double_pinyin_flypy` 和 `luna_pinyin_simp`。

菜单第 7 项用于删除自建词条，支持 `2`、`1-3`、`1,3` 这样选择。也可以不进入菜单直接操作：

```bat
python manage_words.py --add "三个点" --reading "san ge dian"
python manage_words.py --list-custom
python manage_words.py --redeploy
```

自建词表就是一个普通的 Rime 词表，手工编辑也可以，格式为 `文字<TAB>全拼码<TAB>权重`：

```yaml
---
name: custom_user
version: "2026.10.25"
sort: by_weight
...
三个点	san ge dian	999999
```

> 注意：改动 `dicts/` 下的词表后，仅仅在托盘菜单点“重新部署”**不一定**会重编词典。Rime 判断是否重编看的是源文件 checksum（`dict_compiler.cc` 的 `rebuild_table = ... dict_file_checksum`），而 `DetectModifications` 只扫用户文件夹**顶层** yaml 的修改时间。用 `python manage_words.py --redeploy` 走 librime 的 C API 部署最稳妥，它会完整跑 `installation_update → workspace_update`。

## 让修改生效

1. 用 UTF-8 保存规则文件。
2. 在小狼毫托盘菜单中选择“重新部署”。
3. 输入相应编码检查候选顺序，例如双拼方案输入 `ui`，拼音方案输入 `shi`。

如果没有变化，先确认当前使用的是上面列出的三个方案之一，并核对规则中的方案名、输入编码和候选文字。部署后的配置可在 `build/<方案名>.schema.yaml` 中检查是否包含相应的 `lua_filter@...`；`build` 是生成目录，不要直接修改。
