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
# 锁到 3.12: pygame-ce 2.5.x 对 3.12 支持最稳, Python 3.14 在 p4a 上有打开即退的先例
requirements = python3==3.12.10,hostpython3==3.12.10,pygame-ce

# 横屏 + 全屏(点球游戏必须横屏才好看)
orientation = landscape
fullscreen = 1

# 双架构: 同时支持 32 位(armeabi-v7a)和 64 位(arm64-v8a)手机,
# 否则很老或个别国产 32 位机型会因 ABI 不匹配直接打开即退
android.arch = armeabi-v7a,arm64-v8a
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
