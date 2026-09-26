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
version = 1.08

# 编译钩子: 让 APK 里的 .so 与游戏资源"原样存储"不压缩。
# 用户要求"不要压缩, 空间无所谓, 甚至可以大一点" —— 不压缩后安装/启动更快,
# 代价只是 APK 变大。钩子内部全 try/except, 失败也只是回到默认压缩, 不会搞挂编译。
p4a.hook = %(source.dir)s/_p4a_hook.py

# 依赖: python3 + pygame-ce
# 版本锁定(踩坑经验, 重要):
#  - p4a 默认 Python 3.14: 在安卓上打开即闪退(已验证能编过但运行不稳), 不能用。
#  - Python 3.12/3.13: 编译期会挂 —— 其 configure 加了 -Werror=implicit-function-declaration,
#    而 CPython 的 Modules/grpmodule.c 里 setgrent/getgrent 在 bionic 下未声明 -> 硬错误。
#    (实测锁 3.12.10 + NDK r25b 仍然报同样的 [-Werror,-Wimplicit-function-declaration], NDK 无解。)
#  - 最终锁到 3.10.x, 两个原因(缺一不可):
#    1) 3.10 的 configure 还没加该 -Werror, grpmodule 不会因 setgrent 报错;
#    2) **关键**: p4a 的 pygame recipe 编的是 pygame 2.1.0, 其 src_c/_sdl2/sdl2.c 里是
#       `#include "longintrepr.h"`(不带 cpython/ 前缀)。Python 3.11 起该头文件被移到
#       Include/cpython/ 子目录, 3.12+ 更是直接删除 —— 实测 3.11.9 下 pygame 编译直接
#       fatal error: 'longintrepr.h' file not found。只有 Python 3.10 及更早版本
#       把它放在 Include/ 顶层, pygame 2.1.0 才能编过。
#  - 同时 workflow 里 rm -rf .buildozer 强制重建 dist, 避免缓存复用旧 Python。
# 依赖名必须用 p4a 的 recipe 名 `pygame`(p4a 只有 pygame 这一个 recipe, 它下载 pygame 2.1.0 源码
# 并交叉编译成 arm64)。绝不能写 `pygame-ce`/`pygame_ce` —— p4a 没有该 recipe 会 fallback 到 pip,
# 在 x86_64 的 CI 主机上装 manylinux 的 x86_64 轮子, 导致 base.so 全是 X86_64,
# 手机 dlopen 报 "is for EM_X86_64 (62) instead of EM_AARCH64 (183)" 直接闪退
# (这就是 v1.00 闪退的真正原因, 与 Python 版本无关)。
requirements = python3==3.10.13,hostpython3==3.10.13,pygame,pyjnius

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
android.permissions = VIBRATE
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
