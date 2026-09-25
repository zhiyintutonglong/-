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
# 版本锁定(踩坑经验, 重要):
#  - p4a 默认 Python 3.14: 在安卓上打开即闪退(已验证能编过但运行不稳), 不能用。
#  - Python 3.12/3.13: 编译期会挂 —— 其 configure 加了 -Werror=implicit-function-declaration,
#    而 CPython 的 Modules/grpmodule.c 里 setgrent/getgrent 在 bionic 下未声明 -> 硬错误。
#    (实测锁 3.12.10 + NDK r25b 仍然报同样的 [-Werror,-Wimplicit-function-declaration], NDK 无解。)
#  - 所以锁到 3.11.x: 3.11 的 configure 还没加该 -Werror, grpmodule 仅警告、可正常编过;
#    且 3.11 是 p4a/pygame 在安卓上最稳的组合之一, 也避开了 3.14 的运行时问题。
#  - 同时 workflow 里 rm -rf .buildozer 强制重建 dist, 避免缓存复用旧 Python。
requirements = python3==3.11.9,hostpython3==3.11.9,pygame-ce

# 横屏 + 全屏(点球游戏必须横屏才好看)
orientation = landscape
fullscreen = 1

# iQOO 15 等现代手机都是 64 位, 只打 arm64 即可(体积更小、编译更快)
android.arch = arm64-v8a
# 锁定 NDK r25b: 其 Clang 14 不会把 Python 3.12 grpmodule.c 里的 setgrent/getgrent
# 隐式声明当硬错误(新版 NDK Clang16+ 会, 导致 3.12 编译失败)。r25b 是 p4a 官方推荐版本。
android.ndk = 25b
android.api = 33
# 必须 >= 24: Python 3.14 的 remote_debugging 用到 preadv/pwritev,
# bionic 从 API 24 才提供, minapi=23 时会报 "call to undeclared function" 硬错误
android.minapi = 24
android.permissions =
android.allow_backup = True
# 自动接受 Android SDK 协议(云端无人值守编译必须)
android.accept_sdk_license = True

# 图标/启动图(v1.01: 兔子踢球简笔画, buildozer 会用 Pillow 自动生成各尺寸 mipmap)
icon.filename = %(source.dir)s/icon.jpg
presplash.filename = %(source.dir)s/icon.jpg
presplash.color = #FFFFFF

[buildozer]
log_level = 2
warn_on_root = 1
build_dir = ./.buildozer
bin_dir = ./bin
