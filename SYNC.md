# 多设备同步

本仓库以这台 PC 的 Rime 用户文件夹为配置来源。Git 同步配置和文本词库；Rime 自带的“同步用户数据”将输入习惯导出为 `sync/<设备 ID>/*.userdb.txt`，Git 再同步这些快照。其他设备运行 Rime 同步时，会将不同设备的快照合并进自己的用户词典。

## 本机使用

在 Windows 小狼毫上双击用户文件夹根目录的 `同步Rime.bat`，或运行 `python sync_rime.py`。脚本依次：

1. 调用小狼毫 `/sync`，导出本机最新词频与自造词。
2. 提交本机配置和快照，拉取并变基到远端 `master`。
3. 再调用 `/sync`，合并其他设备的词典快照；重新部署配置；推送到远端。

脚本不会在日常同步中强制推送。若出现 Git 冲突或推送被拒绝，它会停下并保留本地文件与提交。解决冲突后重新运行。请确保 Git 和 Python 3.10+ 已安装，并配置好 GitHub 私有仓库访问权限。

## 新 Windows 设备首次接入

1. 安装小狼毫，找到该设备实际使用的 **Rime 用户文件夹**，退出小狼毫。
2. 如果文件夹已有内容，先复制到别处备份，再把该用户文件夹改名；在原位置创建一个空文件夹。
3. 在这个空文件夹中克隆仓库：`git clone https://github.com/geomann/myRimeCustom .`。
4. 启动小狼毫，并运行一次“重新部署”。不要复制另一台设备的 `installation.yaml`；小狼毫会为本机生成独立的设备 ID。
5. 双击 `同步Rime.bat`。它会将仓库中其他设备的用户词典快照合并到本机。

如果该设备原来有要保留的个人词条，先备份原用户文件夹，并通过小狼毫的“用户词典管理”导出词典快照，再按 Rime 的导入或同步功能合并。不要直接复制运行中的 `.userdb` 数据库。

## 整盘复制后仓库丢失（`.git` 不见了）

把整个 Rime 文件夹从旧电脑拷到新位置（换盘符、换机器）时，隐藏的 `.git` 常常没跟过来，`同步Rime.bat` 会报
`git rev-parse ... returned non-zero exit status 128`。在本目录执行下面四行即可把仓库接回远端，**工作区文件不会被动**：

```bat
git init -b master
git remote add origin https://github.com/geomann/myRimeCustom
git fetch origin
git reset --mixed origin/master
```

`git reset --mixed` 只把索引对齐到远端提交，磁盘上的文件保持原样，随后的 `git status` 会列出本机与远端的差异，下一次同步正常提交即可。

如果 git 报 `detected dubious ownership`（目录所有者仍是旧电脑的用户 SID），执行一次：

```bat
icacls "%CD%" /setowner "%USERNAME%"
```

## 第一次推送要登录

仓库是 HTTPS 地址，`git push` 需要 GitHub 凭据。Git for Windows 自带 Git Credential Manager（`credential.helper=manager`），
第一次推送时会弹窗登录，之后凭据由 Windows 凭据管理器保存。脚本让 `git pull` / `git push` 直接接在控制台上运行，
就是为了让这个登录窗口能弹出来。

> 注意：当前远端仓库是**公开**的，而 `sync/*/*.userdb.txt` 含个人输入习惯。要真正私有，需在 GitHub 仓库设置里改成 Private；
> 改成私有后拉取也需要登录。

## 哪些文件进入 Git

- 同步：方案和样式 YAML、`dicts/`、`lua/`、`opencc/`、自定义短语、管理脚本，以及 `sync/<设备 ID>/*.userdb.txt`。
- 不同步：`build/` 编译缓存、`*.userdb/` 本机数据库、`installation.yaml`、`user.yaml`、调试日志、脚本备份和 `sync/` 内 Rime 复制的配置副本。规则由根目录的 `.gitignore` 控制。

`sync/` 中每个设备都应有不同的设备 ID。词典快照可能含有个人输入习惯，因此仓库应保持私有。Git 的历史重建只改变分支上可见的提交历史；如果旧历史含有必须彻底删除的敏感信息，需要另外处理 GitHub 缓存和其他引用。
