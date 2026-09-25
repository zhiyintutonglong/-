[app]
# 应用名(安装后桌面上显示的名字)
title = 点球乱射
package.name = dianqiuluanshe
package.domain = org.dqls.game

# 源码目录(. 表示 buildozer.spec 所在目录)
source.dir = .
# 需要打进 apk 的文件类型(字体必须是 ttf)
source.include_exts = py,png,jpg,jpeg,ttf,otf,txt
# 排除临时/测试文件
source.exclude_patterns = _*.py,__pycache__/*,*.pyc,.github/*,打包指南.md,VERSION.txt

# 版本(与 VERSION.txt 保持一致)
version = 1.00

# 依赖: python3 + pygame-ce
# p4a 自带 pygame-ce recipe(pygame_ce 2.5.8, 现代版本, 在 Python 3.12 上编译/运行均稳)。
# 关键: 必须把 Python 锁到 3.12 (p4a 默认 3.14, 在安卓上运行会"打开即闪退")。
# 通过 requirements 的 == 固定版本; 同时在 workflow 里 rm -rf .buildozer 强制重建 dist,
# 否则缓存里的 3.14 dist 会被复用、== 覆盖不生效。
# (注意: 曾经用的 "sed 改 p4a recipe" 方案不可行 —— buildozer 是 clone p4a 而非 pip 安装,
#  sed 步骤 import pythonforandroid 会 ModuleNotFoundError, 反而让整个 job 失败。)
requirements = python3==3.12.10,hostpython3==3.12.10,pygame-ce

# 横屏 + 全屏(点球游戏必须横屏才好看)
orientation = landscape
fullscreen = 1

# iQOO 15 等现代手机都是 64 位, 只打 arm64 即可(体积更小、编译更快)
android.arch = arm64-v8a
android.api = 33
# 必须 >= 24: Python 3.14 的 remote_debugging 用到 preadv/pwritev,
# bionic 从 API 24 才提供, minapi=23 时会报 "call to undeclared function" 硬错误
android.minapi = 24
android.permissions =
android.allow_backup = True
# 自动接受 Android SDK 协议(云端无人值守编译必须)
android.accept_sdk_license = True

# 图标/启动图(可选; 准备好图片后取消注释)
# icon.filename = %(source.dir)s/assets/icon.png
# presplash.filename = %(source.dir)s/assets/presplash.png
presplash.color = #1B5E20

[buildozer]
log_level = 2
warn_on_root = 1
build_dir = ./.buildozer
bin_dir = ./bin
