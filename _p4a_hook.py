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


def before_apk_assemble(ctx):
    """gradle 组装前: 此时 build.gradle 已经被 build.py 渲染出来, 正好改它。

    注意: before_apk_build 太早(build.gradle 还没生成), 必须放在这里。
    当前工作目录是 dist 目录(p4a 用 current_directory 包着)。
    """
    try:
        gradle = os.path.join(os.getcwd(), "build.gradle")
        if not os.path.isfile(gradle):
            _log("!! 找不到 build.gradle (%s), 跳过" % os.getcwd())
            return
        _patch_gradle(gradle)
    except Exception as e:      # 钩子绝不能把编译搞挂
        _log("!! 出错, 已跳过(不影响编译): %r" % (e,))
