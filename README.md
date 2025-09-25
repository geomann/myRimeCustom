# myRime

##
本仓库fork自[ASC8384/myRime](https://github.com/ASC8384/myRime)

基本使用方法见原仓库。

本仓库的目的是备份仓库，并替换一些自己修改的内容(20250925_0952)：
- 修改顿号的键入规则 (double_pinyin_flypy.custom.yaml)
- 添加若干自定义配色，取消weasel.custom.yaml对于style的强制定义，具体可以在weasel.style.yaml进行配置
- weasel.style.yaml里将常用的几个应用Q-Dir.exe、explorer.exe等设置为默认英文输入，更符合日常使用习惯。


备注:
- caplock配置没有解决，无法像搜狗那样在大写状态下用shift切换
- 原有的中英文提示无法区分英文大小写，所以搭配[abgox/InputTip](https://github.com/abgox/InputTip)使用效果更佳。