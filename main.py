# -*- coding: utf-8 -*-
"""
点球乱射 — Android 入口
======================
由 python-for-android(Buildozer) 打包时作为程序入口。
游戏本体在 game.py, 已做手机适配:
  - 画面固定按 1280x800 绘制, 再等比缩放到任意手机屏幕(letterbox 居中)
  - SDL 触屏事件(FINGER*) 转成鼠标事件, 点击即选格
  - 安卓返回键等同 ESC
"""
import os
import sys

# 让 game.py 能被 import(打包后所有文件都在同一目录)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 只用横屏(手机竖屏时画面会很小)
os.environ.setdefault("SDL_ANDROID_BLOCK_ON_PAUSE", "1")

import pygame  # noqa: E402


def main():
    pygame.init()
    try:
        import game
    except Exception as e:
        print("game.py 导入失败:", e)
        raise
    g = game.Game()
    g.run()


if __name__ == "__main__":
    main()
