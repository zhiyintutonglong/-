# -*- coding: utf-8 -*-
"""
点球乱射 — Android 入口
======================
由 python-for-android(Buildozer) 打包时作为程序入口。

带崩溃诊断: 一旦启动或运行期抛异常, 会
  1) 把完整 traceback + 环境信息写入 dqls_crash.txt(多个候选目录都试)
  2) 尽力在屏幕上显示错误信息(等触摸或 25 秒后退出)
这样手机上闪退时可以直接把 dqls_crash.txt 发回来定位。
"""
import os
import sys
import time
import traceback

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

# 只用横屏(手机竖屏时画面会很小)
os.environ.setdefault("SDL_ANDROID_BLOCK_ON_PAUSE", "1")

CRASH_NAME = "dqls_crash.txt"


def collect_env() -> str:
    lines = ["点球乱射 崩溃报告", "时间: " + time.strftime("%Y-%m-%d %H:%M:%S"),
             "python: " + sys.version.replace("\n", " "),
             "platform: " + sys.platform]
    try:
        import pygame
        lines.append("pygame: " + pygame.version.ver)
        lines.append("SDL: " + str(pygame.get_sdl_version()))
    except Exception as e:
        lines.append("pygame 导入失败: %r" % (e,))
    for k in ("ANDROID_PRIVATE", "ANDROID_ARGUMENT", "ANDROID_APP_PATH",
              "EXTERNAL_STORAGE", "PYTHONHOME", "PYTHONPATH"):
        lines.append("env %s = %s" % (k, os.environ.get(k)))
    lines.append("cwd = " + os.getcwd())
    try:
        lines.append("BASE 目录内容: " + ", ".join(sorted(os.listdir(BASE))[:40]))
        ap = os.path.join(BASE, "assets", "fonts")
        if os.path.isdir(ap):
            lines.append("assets/fonts: " + ", ".join(sorted(os.listdir(ap))[:20]))
    except Exception as e:
        lines.append("列目录失败: %r" % (e,))
    return "\n".join(lines)


def crash_paths():
    ext = os.environ.get("EXTERNAL_STORAGE") or "/sdcard"
    return [
        os.path.join(ext, "Android", "data", "org.dqls.game", "files"),
        os.path.join(ext, "Download"),
        os.path.join(ext, "Documents"),
        ext,
        os.environ.get("ANDROID_PRIVATE", ""),
        "/data/data/org.dqls.game/files",
        BASE,
    ]


def write_report(text: str):
    written = []
    for d in crash_paths():
        if not d:
            continue
        try:
            os.makedirs(d, exist_ok=True)
            p = os.path.join(d, CRASH_NAME)
            with open(p, "w", encoding="utf-8") as f:
                f.write(text)
            written.append(p)
        except Exception:
            pass
    print("[CRASH] 报告已写入: %s" % written)
    sys.stdout.flush()
    return written


def show_on_screen(text: str):
    """尽最大努力把错误画到屏幕上(若 SDL 还能起来)"""
    try:
        import pygame
        pygame.init()
        try:
            scr = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        except Exception:
            scr = pygame.display.set_mode((800, 480))
        w, h = scr.get_size()
        scr.fill((30, 0, 0))
        try:
            font = pygame.font.Font(None, max(16, h // 34))
        except Exception:
            font = None
        if font:
            y = 10
            for line in text.splitlines():
                line = line.rstrip()
                if not line:
                    y += 8
                    continue
                try:
                    img = font.render(line[:110], True, (255, 220, 220))
                    if y + img.get_height() > h - 10:
                        break
                    scr.blit(img, (10, y))
                    y += img.get_height() + 2
                except Exception:
                    break
        pygame.display.flip()
        t0 = time.time()
        while time.time() - t0 < 25:
            for ev in pygame.event.get():
                if ev.type in (pygame.QUIT, pygame.KEYDOWN,
                               pygame.MOUSEBUTTONDOWN, pygame.FINGERDOWN):
                    return
            time.sleep(0.05)
    except Exception:
        pass


def main():
    try:
        import pygame
        pygame.init()
        import game
        g = game.Game()
        g.run()
    except SystemExit:
        raise
    except Exception:
        text = collect_env() + "\n\n" + traceback.format_exc()
        try:
            write_report(text)
        except Exception:
            pass
        try:
            show_on_screen(text)
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
