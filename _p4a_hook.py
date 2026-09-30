# -*- coding: utf-8 -*-
"""p4a 编译钩子 —— 「不要压缩」: 让 APK 里的资源和 .so 全部原样存储。

用法(在 buildozer.spec 里):
    p4a.hook = %(source.dir)s/_p4a_hook.py

用户明确要求: "不要压缩, 空间无所谓, 甚至可以大一点"。
默认的 p4a 会把 lib/arm64-v8a/*.so 用 deflate 压进 APK(压缩率 30%~99%),
装到手机上时要先解压再加载; 改成原样存储(STORE)后:
  - 安装/首次启动不用再解压, 进游戏更快;
  - 运行时可以直接从 APK 里 mmap, 加载更稳;
  - 代价只是 APK 大一些 —— 用户已明确说无所谓。

安全性: 每一步都包在 try 里, 任何意外都只打印警告并原样放过,
绝不会因为钩子本身把编译搞挂。
"""

import io
import os
import re

TAG = "[HOOK noCompress]"

# 需要保持原样存储的后缀(全部游戏资源 + 动态库)。
# 只列 assets/lib 里真正会出现的类型, 不碰 res/ 下的 xml/json
# (那些由 aapt2 单独编译, 塞进 noCompress 反而可能报错)。
NOCOMPRESS_EXT = (
    '"so", "tar", "gz", "zip", "py", "pyc", '
    '"png", "jpg", "jpeg", "ttf", "otf", "txt", '
    '"mp3", "ogg", "wav"'
)


def _log(msg):
    # p4a 会把 stdout 原样打到编译日志里, 便于事后核对是否生效
    try:
        print(TAG + " " + msg)
        import sys
        sys.stdout.flush()
    except Exception:
        pass


def _patch_gradle(path):
    """改 dist 目录下刚渲染出来的 build.gradle。"""
    txt = io.open(path, encoding="utf-8").read()
    orig = txt
    changed = []

    # 1) aaptOptions: 默认只有 noCompress "tflite", 换成全部资源类型
    m = re.search(r"aaptOptions\s*\{(.*?)\}", txt, re.S)
    if m:
        body = m.group(1)
        if "tflite" in body and "so" not in body:
            txt = (txt[:m.start()]
                   + 'aaptOptions {\n        noCompress ' + NOCOMPRESS_EXT + '\n    }'
                   + txt[m.end():])
            changed.append("aaptOptions.noCompress")
    else:
        _log("!! 没找到 aaptOptions 块, 跳过第 1 步")

    # 2) jniLibs.useLegacyPackaging: true=把 so 压缩进 APK(还要解压),
    #    false=原样存储 + 页对齐(现代做法, 装得快、加载也快)
    if "useLegacyPackaging = true" in txt:
        txt = txt.replace("useLegacyPackaging = true",
                          "useLegacyPackaging = false")
        changed.append("jniLibs.useLegacyPackaging=false")

    if txt != orig:
        io.open(path, "w", encoding="utf-8").write(txt)
    _log("已改写 %s : %s" % (os.path.basename(path), ", ".join(changed) or "无改动"))


# ---------------- v1.24: 修复"呼出的是隐私键盘/安全键盘" ----------------
# 根因: SDL2(<=2.0.10, p4a 用的就是这个版本) 安卓端用来接输入法的隐藏编辑框
#   org.libsdl.app.SDLActivity$DummyEdit 里写死了:
#       outAttrs.inputType = InputType.TYPE_CLASS_TEXT
#                          | InputType.TYPE_TEXT_VARIATION_VISIBLE_PASSWORD;
#   "VISIBLE_PASSWORD" 当初是为了绕开三星等机型"联想输入不上屏"的问题才加的,
#   但华为 EMUI / 鸿蒙、小米 MIUI、OPPO、vivo 等国产 ROM 一见 inputType 带
#   password 变体, 就强制切换成自家「安全键盘 / 隐私键盘」——这就是"呼出的
#   不是正常输入法"的真正原因(SDL 官方 bug 4775 亦确认该写法会破坏日文输入)。
#
# 修法: 把 password 变体换成 TYPE_TEXT_VARIATION_NORMAL。
#   注意不能顺手加 TYPE_TEXT_FLAG_NO_SUGGESTIONS —— 那会连中文拼音候选栏一起
#   干掉, 玩家照样打不出中文名。
IME_OLD_VARIANTS = ("InputType.TYPE_TEXT_VARIATION_VISIBLE_PASSWORD",
                    "InputType.TYPE_TEXT_VARIATION_WEB_PASSWORD",
                    "InputType.TYPE_TEXT_VARIATION_PASSWORD")
IME_NEW_VARIANT = "InputType.TYPE_TEXT_VARIATION_NORMAL"
# SDL 2.30+ 把 DummyEdit 拆成了独立文件, 两个文件名都要找
IME_JAVA_NAMES = ("SDLActivity.java", "SDLDummyEdit.java", "SDLInputConnection.java")


# 扫 java 的时间/数量上限: 绝不能让钩子把 CI 拖超时(编译整体有 90 分钟上限,
# 但 NDK 目录有好几个 G, 无脑 os.walk 一次就要好几分钟)。
_IME_SCAN_BUDGET_SEC = 20.0
_IME_SCAN_MAX_FILES = 200000
# 明确不进的目录: NDK/SDK/头文件/预编译库这类"体积巨大且不可能放 java"的地方
_IME_SKIP_DIRS = {".git", "node_modules", "__pycache__", "obj", "libs",
                  "ndk", "sdk", "sysroot", "toolchain", "platforms",
                  "build-tools", "prebuilt", "docs", "include", "samples"}


def _iter_sdl_java(roots):
    """在给定根目录里找 SDL 的 java 源文件(带时间与数量预算)。"""
    import time as _tt
    hits = []
    seen = set()
    deadline = _tt.time() + _IME_SCAN_BUDGET_SEC
    visited = 0
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in _IME_SKIP_DIRS]
            visited += len(filenames)
            if visited > _IME_SCAN_MAX_FILES or _tt.time() > deadline:
                _log("IME 扫描触顶(已看 %d 个文件), 提前收工" % visited)
                return hits
            norm = dirpath.replace("\\", "/")
            for fn in filenames:
                if not fn.endswith(".java"):
                    continue
                if fn in IME_JAVA_NAMES or "/org/libsdl/app/" in norm:
                    p = os.path.join(dirpath, fn)
                    if p not in seen:
                        seen.add(p)
                        hits.append(p)
    return hits


def _patch_sdl_ime():
    # 只扫两个"确定小而准"的地方:
    #   1) dist 目录(gradle 实际编译时用的 java 就在这里)
    #   2) p4a 源码树里的 sdl2 bootstrap 模板(万一 dist 还没拷好, 改源头)
    # 绝不扫整个 .buildozer —— 里面含 NDK, 几 GB, 会拖垮 CI。
    roots = [os.getcwd()]
    home = os.path.expanduser("~")
    for cand in (os.path.join(home, ".buildozer", "android", "platform",
                              "python-for-android"),
                 os.path.join(os.getcwd(), "..", "..", "..", "..", "..", "..",
                              "python-for-android")):
        cand = os.path.normpath(cand)
        if os.path.isdir(cand):
            roots.append(cand)
    files = _iter_sdl_java(roots)
    _log("IME 扫描到 SDL java %d 个: %s" % (
        len(files), ", ".join(os.path.basename(f) for f in files[:8]) or "无"))
    changed = []
    already = []
    for p in files:
        try:
            txt = io.open(p, encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        orig = txt
        for old in IME_OLD_VARIANTS:
            txt = txt.replace(old, IME_NEW_VARIANT)
        if txt == orig:
            if "onCreateInputConnection" in orig:
                already.append(os.path.basename(p))
            continue
        try:
            io.open(p, "w", encoding="utf-8").write(txt)
            changed.append(os.path.basename(p))
        except Exception as e:
            _log("!! 写回失败 %s: %r" % (p, e))
    if changed:
        _log("IME 已把 password 变体改为 NORMAL: %s" % ", ".join(changed))
    elif already:
        _log("IME %s 里已经是 NORMAL(无需改)" % ", ".join(already))
    else:
        _log("!! IME 没找到含 onCreateInputConnection 的 SDL java, 隐私键盘可能仍会出现")


def before_apk_assemble(ctx):
    """gradle 组装前: 此时 build.gradle 已经被 build.py 渲染出来, 正好改它。

    注意: before_apk_build 太早(build.gradle 还没生成), 必须放在这里。
    当前工作目录是 dist 目录(p4a 用 current_directory 包着)。
    """
    try:
        gradle = os.path.join(os.getcwd(), "build.gradle")
        if not os.path.isfile(gradle):
            _log("!! 找不到 build.gradle (%s), 跳过" % os.getcwd())
        else:
            _patch_gradle(gradle)
    except Exception as e:      # 钩子绝不能把编译搞挂
        _log("!! gradle 改写出错, 已跳过(不影响编译): %r" % (e,))
    try:
        _patch_sdl_ime()
    except Exception as e:      # 同上, 绝不能搞挂编译
        _log("!! IME 补丁出错, 已跳过(不影响编译): %r" % (e,))
