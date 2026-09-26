"""
3D 点球大战 - Penalty Shootout 3D
================================
单机3D点球大战小游戏，画风类似FC足球世界，规则与实际点球大战相同。

控制说明:
  射门阶段:
    手机点九宫格 / 电脑数字键1-9或方向键 -> 选择射门目标(九宫格)
    空格键                -> 蓄力(按住)/射门(松开)
  守门阶段:
    手机点九宫格 / 电脑数字键1-9或方向键 -> 选择扑救方向(九宫格)
  其他:
    点击 / 空格 / Enter     -> 确认/继续
    R                     -> 重新开始
    菜单按钮 / ESC         -> 退出/返回菜单

依赖: pygame-ce (>=2.5)
运行: python game.py
"""

import math
import os
import random
import sys
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import List, Optional, Tuple

import pygame

# ====================================================================
# 基础配置
# ====================================================================
WIDTH, HEIGHT = 1280, 800
FPS = 60
VERSION = "1.07"          # 游戏版本号(标题栏 / 主菜单右下角显示)
APP_NAME = "点球乱射"
SEED = None   # 填整数=每局随机序列完全可复现; None=每局真随机(默认)

# 关键: 关闭 SDL 的"触屏模拟鼠标"事件。
# 默认情况下 SDL 收到一次触摸会同时投递 FINGERDOWN 和 MOUSEBUTTONDOWN,
# 导致一次点击被游戏处理两次 —— 表现为"点一下就跳过了选择界面/点不动"。
# 关掉后只保留手指事件, 由 handle_event 统一处理(另有去重兜底)。
os.environ.setdefault("SDL_TOUCH_MOUSE_EVENTS", "0")

# 画面放大交给 GPU 时用线性过滤(双线性), 而不是最邻近 —— 大屏上不会出硬锯齿。
# 只在 SCALED(GPU 缩放)模式下有意义, 对软件缩放路径无任何影响。
os.environ.setdefault("SDL_RENDER_SCALE_QUALITY", "1")

# 本文件所在目录(打包成 apk 后也是资源根目录)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# 是否运行在 Android(python-for-android 会设置这些环境变量)
IS_ANDROID = (sys.platform == "android"
              or "ANDROID_ARGUMENT" in os.environ
              or "ANDROID_PRIVATE" in os.environ
              or "ANDROID_APP_PATH" in os.environ)
# 手机端同样是 60 帧。
# (v1.05 之前这里写的是 FPS = 30 —— 那是个错误决定: 帧率降了并不会让每帧变快,
#  反而让"一帧的时间"变长, 一旦手机跑不满 30 帧, dt 又被截断成 1/30,
#  游戏就整体变成慢动作 —— 玩家看到的"球飞得慢、门将反应慢"就是这么来的。)
# 现在帧率固定 60, 帧时间不够就靠"减少每帧工作量"(见 _set_mode_scaled)解决。
# 内置中文字体: 手机(Android)上系统里没有微软雅黑/黑体, 不内嵌的话中文全是方块
FONT_FALLBACKS = ["microsoftyaheiui", "microsoftyahei", "simhei",
                  "notosanscjk", "wenquanyi", "arial"]
BUNDLED_FONTS = [
    os.path.join(BASE_DIR, "assets", "fonts", "zh.ttf"),
    os.path.join(BASE_DIR, "assets", "zh.ttf"),
    os.path.join(BASE_DIR, "zh.ttf"),
]


def _bundled_font_path() -> Optional[str]:
    for p in BUNDLED_FONTS:
        if os.path.isfile(p):
            return p
    return None


def make_font(size: int, bold: bool = False):
    """建字体: 优先用随包发布的中文字体, 否则退回系统字体, 最后退回默认字体."""
    fp = _bundled_font_path()
    if fp:
        try:
            f = pygame.font.Font(fp, size)
            if bold:
                f.set_bold(True)
            return f
        except Exception:
            pass
    try:
        return pygame.font.SysFont(FONT_FALLBACKS, size, bold=bold)
    except Exception:
        return pygame.font.Font(None, size)


class _CachedFont:
    """字体渲染结果缓存包装.

    手机上 SDL_ttf 的 render() 很贵(尤其 9.7MB 的中文字体),
    而游戏里大量文字每帧内容都一样(标题/标签/九宫格数字/提示语)。
    这里按 (文本, 颜色) 缓存渲染结果, 所有现有 .render() 调用点无需改动。
    """

    __slots__ = ("_f", "_cache")

    def __init__(self, f):
        self._f = f
        self._cache = {}

    def render(self, text, antialias=True, color=(255, 255, 255), background=None):
        try:
            key = (text, bool(antialias), tuple(color), tuple(background) if background else None)
        except Exception:
            return self._f.render(text, antialias, color, background)
        s = self._cache.get(key)
        if s is None:
            s = self._f.render(text, antialias, color, background)
            if len(self._cache) > 500:      # 动态文本(比分/球速)多时避免无限增长
                self._cache.clear()
            self._cache[key] = s
        return s

    def size(self, text):
        return self._f.size(text)

    def get_height(self):
        return self._f.get_height()

    def __getattr__(self, name):
        return getattr(self._f, name)

# 场景3D坐标(米):
#   球门线 z = 11, 点球点 z = 2 (距球门9米, 接近真实11米)
#   球门宽 7.32, 高 2.44
#   摄像机在点球点后方, 略高, 朝向球门
CAM_X, CAM_Y, CAM_Z = 0.0, 1.9, 0.0   # 摄像机位置
FOCAL = 720                            # 焦距(像素), 越大视角越窄

GOAL_W, GOAL_H = 7.32, 2.44            # 球门宽高
GOAL_Z = 11.0                          # 球门线z
NET_DEPTH = 1.6                        # 球网深度
PENALTY_Z = 2.0                        # 点球点
KEEPER_Z = 10.2                        # 守门员初始位置

# 颜色(FC足球世界风格 - 明亮饱和)
SKY_TOP = (96, 165, 235)
SKY_MID = (140, 195, 245)
SKY_BOT = (190, 220, 250)
GRASS_A = (74, 155, 80)
GRASS_B = (88, 170, 92)
GRASS_LINE = (60, 140, 65)
GOAL_POST = (245, 245, 250)
GOAL_NET = (240, 240, 245)
BALL_COLOR = (252, 252, 252)
BALL_SEAM = (35, 35, 38)
CLOUD = (252, 252, 255)
CLOUD_SHADOW = (220, 228, 240)
STAND_COLOR = (70, 78, 88)
STAND_DARK = (55, 62, 72)
TRAIL_COLOR = (255, 230, 120)
WHITE = (255, 255, 255)
BLACK = (24, 24, 28)
INK = (28, 32, 40)
SHADOW = (40, 70, 40, 110)
HUD_BG = (16, 28, 22)
HUD_FG = (245, 240, 220)
GOLD = (255, 198, 70)
RED = (228, 70, 70)
GREEN = (90, 200, 110)
BLUE = (90, 160, 235)
PURPLE = (170, 110, 220)
TEAL = (60, 200, 200)
PANEL = (32, 44, 36)
PANEL_LT = (52, 70, 56)

# ====================================================================
# 真实物理常数(国际单位制, 标准5号球)
# ====================================================================
GRAVITY = 9.81            # 重力加速度 m/s^2
AIR_DENSITY = 1.225       # 空气密度 kg/m^3 (海平面 15°C)
BALL_MASS = 0.43          # 足球质量 kg
BALL_RADIUS = 0.11        # 足球半径 m
BALL_AREA = math.pi * BALL_RADIUS ** 2   # 迎风截面积 m^2
DRAG_CD = 0.25            # 阻力系数(足球在高速湍流区约 0.2~0.3)
MAGNUS_FACTOR = 1.0       # 马格努斯升力系数与自旋参数的比例常数
# 由上面常数派生的加速度系数:
#   阻力加速度   a_drag   = DRAG_K   * v^2     (方向: -v)
#   马格努斯加速 a_magnus = MAGNUS_K * ω * v   (方向: ω̂ × v̂)
DRAG_K = 0.5 * AIR_DENSITY * DRAG_CD * BALL_AREA / BALL_MASS
MAGNUS_K = (0.5 * AIR_DENSITY * BALL_AREA * BALL_RADIUS
            * MAGNUS_FACTOR / BALL_MASS)
GROUND_RESTITUTION = 0.55  # 草地反弹系数
ROLL_DECEL = 4.0           # 贴地滚动减速度 m/s^2
POST_RADIUS = 0.06         # 门柱半径 m
PHYS_DT = 1.0 / 240.0      # 物理积分子步长(固定步长保证可重复)
# 出球速度 -> 到达门线速度 的典型衰减比(9m 飞行, 阻力吃掉约13%)
SPEED_DECAY = 0.87

# 九宫格 - 射门/扑救目标区域
#   1左上 2中上 3右上
#   4左中 5中中 6右中
#   7左下 8中下 9右下
# 球门内坐标系: x∈[-3.66, 3.66], y∈[0, 2.44]
CELL_CENTERS = {
    1: (-2.2, 1.85), 2: (0.0, 1.85), 3: (2.2, 1.85),
    4: (-2.2, 1.22), 5: (0.0, 1.22), 6: (2.2, 1.22),
    7: (-2.2, 0.4),  8: (0.0, 0.4),  9: (2.2, 0.4),
}
# 相邻格子映射(上下左右+对角)
CELL_ADJACENT = {
    1: [2, 4, 5],        # 左上: 中上,左中,中中
    2: [1, 3, 4, 5, 6],  # 中上: 左上,右上,左中,中中,右中
    3: [2, 5, 6],        # 右上: 中上,中中,右中
    4: [1, 2, 5, 7, 8],  # 左中: 左上,中上,中中,左下,中下
    5: [1, 2, 3, 4, 6, 7, 8, 9],  # 中中: 全部相邻
    6: [2, 3, 5, 8, 9],  # 右中: 中上,右上,中中,中下,右下
    7: [4, 5, 8],        # 左下: 左中,中中,中下
    8: [4, 5, 6, 7, 9],  # 中下: 左中,中中,右中,左下,右下
    9: [5, 6, 8],        # 右下: 中中,右中,中下
}
# 九宫格 -> 球门内坐标矩形 (x1,x2,y1,y2). 编号 1/2/3 = 上排, 7/8/9 = 下排.
# 关键: 世界坐标 y 越大越靠上, 而编号的行号必须从下往上数, 否则"选中数字"
# 与"高亮光标"会上下颠倒 —— 这正是 v1.05 及之前两端都出现的错位 bug 根因.
def cell_rect(cell: int):
    # 返回编号对应的球门内矩形, 行号已翻转, 与数字标签/网格完全一致.
    cell = max(1, min(9, cell))
    col = (cell - 1) % 3
    row = 2 - (cell - 1) // 3
    w, h = GOAL_W, GOAL_H
    x1 = -w / 2 + (w / 3) * col
    x2 = x1 + w / 3
    y1 = (h / 3) * row
    y2 = y1 + h / 3
    return x1, x2, y1, y2

# 射门出球速度模型(v1.06 重新标定).
#   * 杰瑞(力量7) 0疲劳 / 10%力度  ≈ 15 m/s, 作为"标准球".
#   * 0疲劳 / 50%力度时: 詹姆斯25, 杰瑞21, 兔同笼21, 牢二24 (m/s).
#   * 詹姆斯"超大力"技能 + 满体力100力度 → 约 60 m/s.
#   * 加入 ±8% 概率浮动, 让每次射门略有差异.
SPD_SLOPE = 15.0                       # 力度条每 +100% 增加的出球速度
SPD_LO = {7: 13.5, 8: 16.5, 9: 17.5}  # 0力度时的基础速度(按力量属性区分)
POWER_SHOT_BOOST = 1.846              # 超大力技能倍率(詹姆斯满力 ≈ 60 m/s)

def _shot_speed(frac, attr, fatigue, skill=False):
    # 计算射门出球速度(已含疲劳衰减与概率浮动).
    f = max(0.0, min(1.0, frac))
    base = SPD_LO.get(attr, 15.0) + SPD_SLOPE * f
    base *= random.uniform(0.92, 1.08)                 # 概率浮动
    if fatigue > 0:
        base *= (1.0 - fatigue * 0.04)                 # 疲劳降速(加强后)
    if skill:
        base *= POWER_SHOT_BOOST
    return max(6.0, base)

# 缓存 Vibrator 句柄: 第一次成功拿到后复用; 若确认拿不到则置 False 直接跳过.
_vibrator = None

def _android_vibrate(ms):
    # 手机端震动反馈; 非安卓 / 无权限时静默跳过. 必须在主线程调用.
    global _vibrator
    if not IS_ANDROID:
        return
    if _vibrator is False:
        return
    try:
        from jnius import autoclass
        if _vibrator is None:
            # 尽量拿到 Vibrator: 先试 PythonActivity, 失败再试 Application Context.
            # (实测部分机型/打包方式下 mActivity 取不到, 走 ActivityThread 兜底.)
            ctx = None
            try:
                PythonActivity = autoclass("org.kivy.android.PythonActivity")
                ctx = PythonActivity.mActivity
            except Exception:
                ctx = None
            if ctx is None:
                try:
                    ActivityThread = autoclass("android.app.ActivityThread")
                    ctx = ActivityThread.currentApplication()
                except Exception:
                    ctx = None
            if ctx is None:
                _vibrator = False
                return
            Context = autoclass("android.content.Context")
            vib = ctx.getSystemService(Context.VIBRATOR_SERVICE)
            if vib is None:
                _vibrator = False
                return
            _vibrator = vib
        vib = _vibrator
        try:
            VibrationEffect = autoclass("android.os.VibrationEffect")
            # 中等强度短震(默认振幅在部分机型上几乎无感, 这里用 200/255 确保能感知)
            vib.vibrate(VibrationEffect.createOneShot(int(ms), 200))
        except Exception:
            try:
                vib.vibrate(int(ms))
            except Exception:
                _vibrator = False
    except Exception:
        _vibrator = False

CORNER_CELLS = {1, 3, 7, 9}
KEY_TO_CELL = {
    # 主键盘数字键: 按九宫格编号 1..9 (1左上 -> 9右下), 与画面上的编号一致
    pygame.K_1: 1, pygame.K_2: 2, pygame.K_3: 3,
    pygame.K_4: 4, pygame.K_5: 5, pygame.K_6: 6,
    pygame.K_7: 7, pygame.K_8: 8, pygame.K_9: 9,
    # 小键盘走"物理布局": 7/8/9 在最上排, 4/5/6 中排, 1/2/3 最下排
    # (之前直接照搬编号, 结果用小键盘选格上下颠倒)
    pygame.K_KP7: 1, pygame.K_KP8: 2, pygame.K_KP9: 3,
    pygame.K_KP4: 4, pygame.K_KP5: 5, pygame.K_KP6: 6,
    pygame.K_KP1: 7, pygame.K_KP2: 8, pygame.K_KP3: 9,
}
ARROW_TO_CELL = {
    pygame.K_UP: 2, pygame.K_DOWN: 8,
    pygame.K_LEFT: 4, pygame.K_RIGHT: 6,
}


# ====================================================================
# 球员数据 - 4种射门球员, 5种守门员
# 属性 1-10, 有技能的角色基础属性稍低以保持平衡
# 射手属性:
#   power(力量)    -> 射门力量上限(球速)
#   accuracy(准度) -> 控制大力射门偏差(大力球偏差主要由准度决定)
#   composure(心理)-> 加时赛准度加成 + 减缓疲劳递增
# 技能:
#   "precision"(超精准,限1次) / "power_shot"(超大力,耗体力)
#   "curve"(弧线球,无限,选2相邻格子) / "none"
# 守门属性:
#   reflex(反应)  -> 扑救远距离(四角)重力球
#   reach(臂展)   -> 防守范围(相邻格子慢球有概率扑到), 克制弧线球
#   dive(扑救)    -> 扑救近距离(非四角)重力球
# ====================================================================
@dataclass
class StrikerProfile:
    key: str
    name: str
    power: int       # 力量 -> 射门力量上限(球速)
    accuracy: int    # 准度 -> 控制大力射门偏差
    composure: int   # 心理 -> 加时准度+减缓疲劳
    color: Tuple[int, int, int]
    skin: Tuple[int, int, int]
    desc: str
    skill: str = "none"
    skill_name: str = ""
    skill_desc: str = ""

STRIKERS: List[StrikerProfile] = [
    StrikerProfile(
        "power", "詹姆斯",
        power=9, accuracy=3, composure=7,
        color=(220, 60, 60), skin=(232, 196, 158),
        desc="重炮手:球速可达28m/s几乎无法扑救,但落点飘忽,大力射门常打飞",
        skill="power_shot", skill_name="超大力射门",
        skill_desc="消耗大量体力(+8疲劳)换取极大射门力度,高风险高回报",
    ),
    StrikerProfile(
        "tech", "杰瑞",
        power=7, accuracy=9, composure=10,
        color=(60, 130, 220), skin=(238, 206, 168),
        desc="手术刀:球速最慢却指哪打哪,零偏差专打死角,靠落点而非力量取胜",
        skill="precision", skill_name="超精准射门",
        skill_desc="限用1次,精度暴增(偏差降至15%),但力度上限60%",
    ),
    StrikerProfile(
        "curve", "兔同龙",
        power=7, accuracy=7, composure=6,
        color=(180, 100, 220), skin=(228, 192, 154),
        desc="香蕉球:球带强侧旋在空中真实弯曲,可选2个相邻格,克制反应型门将",
        skill="curve", skill_name="弧线球",
        skill_desc="无限使用,每次射门选2个相邻格子,球弧线飞行,被臂展型门将克制",
    ),
    StrikerProfile(
        "all", "牢二",
        power=8, accuracy=8, composure=8,
        color=(70, 170, 90), skin=(224, 188, 150),
        desc="六边形:球速/落点/心理全部中上,没有短板也没有绝活",
        skill="none", skill_name="无技能",
        skill_desc="无特殊技能,但三围均衡无短板",
    ),
]

@dataclass
class KeeperProfile:
    key: str
    name: str
    reflex: int     # 反应 -> 扑救远距离(四角)重力球
    reach: int      # 臂展 -> 防守范围(相邻格子慢球可扑), 克制弧线球
    dive: int       # 扑救 -> 扑救近距离(非四角)重力球
    color: Tuple[int, int, int]
    skin: Tuple[int, int, int]
    desc: str
    skill: str = "none"
    skill_name: str = ""
    skill_desc: str = ""

KEEPERS: List[KeeperProfile] = [
    KeeperProfile(
        "reflex", "莱特宁",
        reflex=10, reach=5, dive=8,
        color=(255, 200, 60), skin=(230, 196, 160),
        desc="闪电:反应全球最快(0.20s起跳),专吃四角重力球;但臂展仅5,差一格基本够不到",
        skill="none", skill_name="无技能",
        skill_desc="无特殊技能,反应极致(10),但臂展只有5(相邻格很难捞到)",
    ),
    KeeperProfile(
        "wall", "魏豹",
        reflex=5, reach=10, dive=7,
        color=(90, 90, 110), skin=(210, 178, 140),
        desc="铁壁:臂展10的巨灵神,选差一格也能靠臂展捞到;但反应5,快球常常还没动就进了",
        skill="none", skill_name="无技能",
        skill_desc="无特殊技能,臂展极致(10),但反应只有5(起跳慢半拍)",
    ),
    KeeperProfile(
        "agile", "牢饭",
        reflex=7, reach=6, dive=10,
        color=(120, 200, 220), skin=(236, 200, 162),
        desc="灵猫:鱼跃速度全球第一(0.30s横移到位),专吃非四角近角重力球;臂展偏小",
        skill="none", skill_name="无技能",
        skill_desc="无特殊技能,扑救极致(10),但臂展只有6",
    ),
    KeeperProfile(
        "vet", "领导",
        reflex=7, reach=7, dive=7,
        color=(160, 90, 200), skin=(224, 190, 152),
        desc="老帅:三围平庸,但能预判对方射门力度等级,信息就是优势",
        skill="anticipate", skill_name="预判",
        skill_desc="被动技能:可模糊获知对方射门力度等级(弱/中/强)",
    ),
    KeeperProfile(
        "all", "户晨凤",
        reflex=8, reach=8, dive=8,
        color=(80, 160, 200), skin=(230, 194, 156),
        desc="门神:反应/臂展/扑救全部8分,没有任何明显弱点",
        skill="none", skill_name="无技能",
        skill_desc="无特殊技能,但三围均为8,无短板",
    ),
]


# ====================================================================
# 3D 投影
# ====================================================================
def project(x: float, y: float, z: float) -> Tuple[float, float, float]:
    """3D世界坐标 -> 2D屏幕坐标 + 缩放比例"""
    dx = x - CAM_X
    dy = y - CAM_Y
    dz = z - CAM_Z
    if dz < 0.05:
        dz = 0.05
    sx = WIDTH / 2 + (dx / dz) * FOCAL
    sy = HEIGHT / 2 - (dy / dz) * FOCAL
    scale = FOCAL / dz
    return sx, sy, scale


def scale_of(z: float) -> float:
    dz = max(0.05, z - CAM_Z)
    return FOCAL / dz


# ====================================================================
# 实体数据
# ====================================================================
@dataclass
class Ball:
    x: float = 0.0
    y: float = BALL_RADIUS  # 球心离地 = 半径, 贴地
    z: float = PENALTY_Z
    vx: float = 0.0
    vy: float = 0.0
    vz: float = 0.0
    spin: float = 0.0        # 视觉累积旋转角(rad)
    spin_rate: float = 0.0   # 物理角速度(rad/s), 绕竖直轴, 正=右旋
    active: bool = False
    air_t: float = 0.0       # 已飞行时间(s)
    trail: List[Tuple[float, float, float]] = field(default_factory=list)

    @property
    def speed(self) -> float:
        return math.hypot(math.hypot(self.vx, self.vy), self.vz)


# ====================================================================
# 弹道积分 - 重力 + 空气阻力 + 马格努斯力(弧线球)
# ====================================================================
def ball_accel(vx: float, vy: float, vz: float,
               spin_rate: float) -> Tuple[float, float, float]:
    """返回球的加速度(m/s^2). 注意: 重力单独在积分里处理."""
    v = math.sqrt(vx * vx + vy * vy + vz * vz)
    if v < 1e-6:
        return 0.0, 0.0, 0.0
    # 空气阻力: a = -DRAG_K * v * v_vec (与速度反向, 大小 ∝ v²)
    k = DRAG_K * v
    ax, ay, az = -k * vx, -k * vy, -k * vz
    # 马格努斯: 绕竖直轴自转 ω=(0, spin_rate, 0)
    #   a = MAGNUS_K * spin_rate * (ω̂ × v) = MAGNUS_K * spin_rate * (vz, 0, -vx)
    if spin_rate != 0.0:
        m = MAGNUS_K * spin_rate
        ax += m * vz
        az -= m * vx
    return ax, ay, az


def step_ball(pos: List[float], vel: List[float], spin_rate: float,
              dt: float) -> None:
    """半隐式欧拉推进一步, 并处理地面反弹/滚动. 就地修改 pos/vel."""
    ax, ay, az = ball_accel(vel[0], vel[1], vel[2], spin_rate)
    vel[0] += ax * dt
    vel[1] += (ay - GRAVITY) * dt
    vel[2] += az * dt
    pos[0] += vel[0] * dt
    pos[1] += vel[1] * dt
    pos[2] += vel[2] * dt
    # 地面碰撞
    if pos[1] < BALL_RADIUS:
        pos[1] = BALL_RADIUS
        if vel[1] < 0.0:
            vel[1] = -vel[1] * GROUND_RESTITUTION
            if vel[1] < 0.8:      # 弹跳太弱 -> 转为滚动
                vel[1] = 0.0
        # 触地时水平方向受滚动摩擦
        hs = math.hypot(vel[0], vel[2])
        if hs > 1e-6:
            dec = min(hs, ROLL_DECEL * dt)
            vel[0] -= dec * vel[0] / hs
            vel[2] -= dec * vel[2] / hs


def simulate_to_goal(x0: float, y0: float, z0: float,
                     vx: float, vy: float, vz: float,
                     spin_rate: float) -> Tuple[float, float, float, float]:
    """从 (x0,y0,z0) 以初速度 (vx,vy,vz) 积分到球门线 z=GOAL_Z.
    返回 (x_end, y_end, flight_time, arrive_speed). 用于弹道求解器."""
    pos = [x0, y0, z0]
    vel = [vx, vy, vz]
    t = 0.0
    for _ in range(4000):          # 上限约 16 秒, 足够
        px, py, pz = pos[0], pos[1], pos[2]
        step_ball(pos, vel, spin_rate, PHYS_DT)
        t += PHYS_DT
        if pos[2] >= GOAL_Z:
            # 线性插值回退到精确的 z = GOAL_Z 平面
            dz = pos[2] - pz
            f = (GOAL_Z - pz) / dz if abs(dz) > 1e-9 else 0.0
            v_end = math.sqrt(vel[0] ** 2 + vel[1] ** 2 + vel[2] ** 2)
            return (px + (pos[0] - px) * f,
                    py + (pos[1] - py) * f,
                    t - PHYS_DT * (1.0 - f),
                    v_end)
        if t > 8.0:
            break
    v_end = math.sqrt(vel[0] ** 2 + vel[1] ** 2 + vel[2] ** 2)
    return pos[0], pos[1], t, v_end


def solve_launch(x0: float, y0: float, z0: float,
                 tx: float, ty: float, speed: float,
                 spin_rate: float = 0.0,
                 iters: int = 7) -> Tuple[float, float, float, float]:
    """弹道求解: 给定目标点 (tx,ty)、初速大小 speed 与自转 spin_rate,
    反解初速度向量 (vx,vy,vz), 使球(含阻力/马格努斯)正好飞到目标点.
    返回 (vx, vy, vz, flight_time)."""
    dist = max(0.5, GOAL_Z - z0)
    # 初始猜测: 无阻力抛体解析解
    t = dist / max(6.0, speed)
    vx = (tx - x0) / t
    vy = (ty - y0) / t + 0.5 * GRAVITY * t
    vz = speed
    for _ in range(iters):
        ex, ey, t_act, _ = simulate_to_goal(x0, y0, z0, vx, vy, vz, spin_rate)
        ex_err = tx - ex
        ey_err = ty - ey
        if abs(ex_err) < 0.008 and abs(ey_err) < 0.008:
            break
        tt = max(0.08, t_act)
        vx += ex_err / tt
        vy += ey_err / tt
    _, _, t_final, v_final = simulate_to_goal(x0, y0, z0, vx, vy, vz, spin_rate)
    return vx, vy, vz, t_final, v_final


@dataclass
class KeeperState:
    x: float = 0.0      # 当前位置(脚底水平坐标)
    y: float = 0.0      # 当前离地高度(脚底)
    z: float = KEEPER_Z
    target_x: float = 0.0
    target_y: float = 0.0
    diving: bool = False
    dive_t: float = 0.0  # 扑救已进行时间(s)
    dive_dir: int = 0    # -1左 0中 1右
    dive_high: bool = False
    committed: bool = False  # 已选好扑救方向
    # --- 起跳抛体参数(鱼跃) ---
    jump_x0: float = 0.0     # 起跳点
    jump_vx: float = 0.0     # 水平速度 m/s
    jump_vy: float = 0.0     # 垂直初速 m/s
    landed: bool = False     # 是否已落地
    land_x: float = 0.0      # 落地点(之后贴地滑行)


@dataclass
class StrikerState:
    x: float = 0.0
    y: float = 0.0
    z: float = PENALTY_Z - 0.6
    run_t: float = 0.0        # 摆腿动画相位
    kicked: bool = False
    kick_vz: float = 0.0      # 踢球后的前冲速度(m/s), 会被摩擦减速
    approach_vz: float = 0.0  # 助跑速度(m/s)


# ====================================================================
# 游戏状态机
# ====================================================================
class State(Enum):
    MENU = auto()
    HELP = auto()                # 操作说明页面
    SELECT_STRIKER = auto()
    SELECT_KEEPER = auto()
    READY = auto()              # 准备阶段(显示轮次/攻守)
    PLAYER_AIM = auto()         # 玩家瞄准(射门/扑救)
    PLAYER_POWER = auto()       # 玩家蓄力(仅射门)
    BALL_FLY = auto()           # 球飞行
    ROUND_RESULT = auto()       # 本轮结果
    EARLY_END = auto()          # 提前结束弹窗(选择继续或结算)
    GAME_OVER = auto()


# ====================================================================
# 游戏主类
# ====================================================================
class Game:
    # ----------------------------------------------------------------
    # 显示模式(手机端能不能跑满 60 帧, 几乎全看这里)
    # ----------------------------------------------------------------
    def _window_size(self):
        """SDL 窗口的真实像素尺寸。

        注意: SCALED 模式下 screen.get_size() 是"逻辑尺寸"(1280x800),
        而窗口本身可能是 3168x1440 —— 触摸坐标换算必须用真实窗口尺寸,
        否则黑边区域会让点击整体偏移。
        """
        try:
            w, h = pygame.display.get_window_size()
            if w > 0 and h > 0:
                return int(w), int(h)
        except Exception:
            pass
        try:
            info = pygame.display.Info()
            if getattr(info, "current_w", 0) > 0 and getattr(info, "current_h", 0) > 0:
                return int(info.current_w), int(info.current_h)
        except Exception:
            pass
        try:
            return pygame.display.get_surface().get_size()
        except Exception:
            return WIDTH, HEIGHT

    def _init_display(self):
        """挑一种显示模式。手机端优先 SCALED —— 这是本次提速的关键。

        旧方案((0,0)+FULLSCREEN, 拿手机真实分辨率):
            每帧要先用 CPU 把 1280x800 软件放大到 2304x1440(几百万像素),
            再把这一整块(十几 MB)上传给 SDL 的纹理。手机上这两项加起来
            能吃掉 20~30ms —— 60 帧的预算才 16.7ms, 根本不可能达标,
            于是只能跑到 20 帧出头, 再叠加 dt 截断就成了慢动作。

        新方案(SCALED):
            画面依然按 1280x800 绘制(逻辑分辨率), 由 SDL/GPU 等比放大到
            全屏并居中留黑边。CPU 一次都不用放大, 上传量也只有原来的 1/3,
            而且 GPU 放大还是双线性的, 比原来的最邻近更好看。
        """
        scaled = getattr(pygame, "SCALED", 0)
        if IS_ANDROID and scaled:
            try:
                pygame.display.set_mode((WIDTH, HEIGHT),
                                        pygame.FULLSCREEN | scaled)
                surf = pygame.display.get_surface()
                # 必须拿到真实窗口尺寸, 否则触摸坐标无从换算(见 _window_size)
                w, h = self._window_size()
                if surf is not None and surf.get_size() == (WIDTH, HEIGHT) and (w, h) != (0, 0):
                    return surf
            except Exception:
                pass
            # 退回老办法: 拿真实分辨率, 由 _present() 自己软件缩放
            try:
                return pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
            except Exception:
                return pygame.display.set_mode((WIDTH, HEIGHT))
        # 桌面端: 1:1 窗口(SCALED 让窗口可自由拉伸且不变形)
        try:
            return pygame.display.set_mode((WIDTH, HEIGHT), scaled, vsync=1)
        except Exception:
            try:
                return pygame.display.set_mode((WIDTH, HEIGHT))
            except Exception:
                return pygame.display.set_mode((0, 0), pygame.FULLSCREEN)

    def __init__(self):
        pygame.init()
        # 窗口真实像素尺寸(可能与绘制表面尺寸不同, 见下面的 SCALED)
        self._win_w, self._win_h = WIDTH, HEIGHT
        self.screen = self._init_display()
        self._win_w, self._win_h = self._window_size()
        pygame.display.set_caption(f"{APP_NAME} v{VERSION} - 3D 点球大战")
        self.clock = pygame.time.Clock()
        if SEED is not None:
            random.seed(SEED)

        # 字体(手机端依赖随包的中文字体, 见 make_font)
        # 用 _CachedFont 包一层: 同样的(文本,颜色)只渲染一次, 之后复用
        self.font_xl = _CachedFont(make_font(64, bold=True))
        self.font_l = _CachedFont(make_font(36, bold=True))
        self.font_m = _CachedFont(make_font(24))
        self.font_s = _CachedFont(make_font(18))
        self.font_xs = _CachedFont(make_font(14))

        # 自适应画布: 所有绘制都发生在 1280x800 的固定画布上,
        # 再等比缩放贴到真实窗口/手机屏幕(手机端必需, 桌面端 1:1 无影响)
        self._canvas = pygame.Surface((WIDTH, HEIGHT))

        # 预渲染缓存(性能关键: 静态图层只画一次, 之后每帧直接 blit)
        self._grass_cache: Optional[pygame.Surface] = None
        self._bg_cache: Optional[pygame.Surface] = None      # 天空渐变 + 云
        self._scene_cache: Optional[pygame.Surface] = None   # 天空+看台+草地 合成图
        self._stands_cache: Optional[pygame.Surface] = None  # 看台 + 观众
        self._net_cache: Optional[pygame.Surface] = None     # 球网(半透明)
        self._net_small: Optional[pygame.Surface] = None     # 球网(裁剪到球门那一小块)
        self._net_rect: Tuple[int, int, int, int] = (0, 0, WIDTH, HEIGHT)
        self._grid_cache: Optional[pygame.Surface] = None    # 九宫格网格线(整屏, 备用)
        self._grid_small: Optional[pygame.Surface] = None    # 九宫格网格线(只球门一小块)
        self._grid_rect: Tuple[int, int, int, int] = (0, 0, WIDTH, HEIGHT)
        self._hl: Optional[pygame.Surface] = None            # 瞄准高亮(只球门一小块)
        self._scaled: Optional[pygame.Surface] = None        # 放大后的画布
        self._scale_dest_ok = True                           # scale() 是否支持目标 surface 参数
        self._overlay: Optional[pygame.Surface] = None       # 复用的全屏遮罩
        self._num_cache = {}                                 # 队号数字(按字号缓存)
        self._effect_font_cache = {}                         # GOAL/SAVE 大字(按字号缓存)
        self._card_cache = {}                                # 球员卡片(按 索引+选中态 缓存)

        # 预热: 开局第一帧要现场生成 5 张全屏图(手机上好几十毫秒), 会明显顿一下。
        # 菜单是空闲状态, 提前十几帧在那里把它们做好, 进比赛时就直接 blit。
        self._warm_layers = False
        self._warm_frames = 0

        # 手机端自适应流畅度(v1.04): 只调帧率 60/30, 绝不缩小画面。
        # (v1.03 的"自适应画质"会一路把画面压到 0.60 —— 2K 屏上又小又糊,
        #  用户明确要求: 不要压缩画面, 空间无所谓, 甚至可以更大。已改成只降帧。)
        self._frame_ms = 8.0        # 单帧"真实干活时间"的滑动平均(ms)
        self._present_cap = 1.0     # 画面铺满系数, 恒为 1.0(见 _adapt_quality: 只降帧, 不缩画面)
        self._present_rect = None   # 上一次贴图的区域(用于只清黑边/局部刷新)
        self._update_ok = True      # display.update(rect) 是否可用(老设备退回 flip)
        self._fps_target = FPS      # 当前帧率目标
        self._adapt_t = 0.0         # 上次调整至今的时间

        # 游戏状态
        self.state = State.MENU
        self.running = True
        self.selected_striker_idx = 0
        self.selected_keeper_idx = 0
        self.menu_idx = 0  # 菜单/选择项高亮

        # 比赛
        self.total_rounds = 5
        self.round_num = 0           # 当前轮 1~5
        self.player_score = 0
        self.ai_score = 0
        self.is_overtime = False     # 是否加时赛(突然死亡)
        self.results_log: List[Tuple[int, str, str]] = []  # (轮次, 谁, 结果)

        # 本回合
        self.attacker_is_player = True   # True=玩家射门, False=AI射门
        self.round_phase = 0             # 0=玩家射门 1=AI射门 (一轮内)
        self.last_result_text = ""
        self.last_outcome = ""           # "GOAL"/"SAVE"/"MISS"
        self.save_fail_reason = ""       # 扑救失败原因(方向错误/臂展不足/反应不足/扑救不足)
        self._key_attr_ok = True         # 本次判定的关键属性是否够用
        self._key_attr_name = "扑救"
        self._key_attr_value = 0
        self._slow_factor = 0.0          # 慢速系数(球越慢越大)
        self.curve_cell2 = 0             # 弧线球第二格子(0=未选/不用弧线球)

        # 实体
        self.ball = Ball()
        self.keeper = KeeperState()
        self.striker = StrikerState()

        # AI 球员属性(在AI回合开始时选定, 整个回合内固定)
        self.ai_striker_profile: Optional[StrikerProfile] = None
        self.ai_keeper_profile: Optional[KeeperProfile] = None

        # 球员疲劳系统 - 仅射手有疲劳(射门累积), 守门员不疲劳
        self.player_fatigue = 0      # 玩家射手疲劳值(0-10)
        self.ai_fatigue = 0          # AI射手疲劳值
        self.last_ball_speed = 0.0   # 上次球速(用于球速可视化)
        self.last_flight_time = 0.0  # 上次射门的真实飞行时间(s)
        self.last_arrive_speed = 0.0  # 到达门线时的速度(已扣除空气阻力)
        self.aim_point = (0.0, 1.22)  # 上次射门的实际目标点(含偏差)
        self._break_defense = False  # 破防标记(重力球属性不够时)

        # 技能充能系统 - 技能需充能到阈值才能释放
        self.player_skill_charge = 0   # 充能值(0-100)
        self.ai_skill_charge = 0
        # 充能阈值: precision需80, power_shot需60
        self.precision_shot_used = False
        self.ai_precision_used = False      # AI 超精准射门(同样每场1次)
        self.power_shot_active = False
        self.selected_skill = "normal"
        self.curve_cell2 = 0
        self.save_fail_reason = ""
        # AI 本回合选用的进攻技能: normal / power_shot / precision / curve
        self.ai_selected_skill = "normal"
        self.ai_curve_cell2 = 0          # AI 弧线球第二落点
        self.ai_curve_dir = 1.0          # AI 弧线球侧旋方向(+1=向右弯)
        # 本次射门"实际生效"的技能(射门瞬间写入, 结算时统计用)
        self._shot_skill = "normal"

        # AI 学习系统 - 记录玩家射门/扑救历史, 用于AI策略优化
        self.player_shot_history: List[int] = []  # 玩家射门选格历史(1-9)
        self.player_dive_history: List[int] = []  # 玩家扑救选格历史
        self.player_power_history: List[float] = []  # 玩家射门力度历史

        # 赛后数据统计
        self.match_stats = {
            "player_shots": 0, "player_goals": 0, "player_saves": 0,
            "player_misses": 0, "player_skill_uses": 0,
            "ai_shots": 0, "ai_goals": 0, "ai_saves": 0,
            "ai_misses": 0, "ai_skill_uses": 0,
            "player_power_shots": 0, "ai_power_shots": 0,
            "max_ball_speed": 0.0, "total_shots": 0,
            "key_events": [],  # 关键事件列表 (round, text)
        }

        # 玩家选择
        self.aim_cell = 5                # 默认中下
        self.power_charging = False
        self.power_value = 0.0           # 0~1
        self.power_dir = 1
        self.ai_target: Optional[Tuple[float, float, float]] = None
        self.ai_dive_target: Optional[Tuple[float, float]] = None

        # 时序
        self.state_t = 0.0
        self.result_t = 0.0
        self.intro_t = 0.0
        self.shake_t = 0.0
        self.shake_amp = 0.0
        # 进球反馈
        self.goal_flash = 0.0
        self.goal_effect_t = 0.0    # 进球特效动画时间(>0时显示GOAL特效)
        self.save_effect_t = 0.0    # 扑救特效动画时间

        # 输入冷却(防抖)
        self.cooldown = 0.0

        # 鼠标状态
        self.mouse_pos = (WIDTH // 2, HEIGHT // 2)
        self.mouse_down = False
        # 触摸去重(见 _accept_tap)
        self._last_tap_t = -10.0
        self._last_tap_pos = (-9999.0, -9999.0)

    # ----------------------------------------------------------------
    # 属性访问
    # ----------------------------------------------------------------
    @property
    def striker_profile(self) -> StrikerProfile:
        return STRIKERS[self.selected_striker_idx]

    @property
    def keeper_profile(self) -> KeeperProfile:
        return KEEPERS[self.selected_keeper_idx]

    # ----------------------------------------------------------------
    # 状态切换
    # ----------------------------------------------------------------
    def reset_match(self):
        self.round_num = 0
        self.player_score = 0
        self.ai_score = 0
        self.is_overtime = False
        self.player_fatigue = 0
        self.ai_fatigue = 0
        self.last_ball_speed = 0.0
        self.player_skill_charge = 0
        self.ai_skill_charge = 0
        self.precision_shot_used = False
        self.ai_precision_used = False
        # AI 整场固定一名射手 + 一名门将, 与玩家对等(不再每个球换人)
        self.ai_striker_profile = random.choice(STRIKERS)
        self.ai_keeper_profile = random.choice(KEEPERS)
        self.power_shot_active = False
        self.selected_skill = "normal"
        self.ai_selected_skill = "normal"
        self._shot_skill = "normal"
        self.curve_cell2 = 0
        self.save_fail_reason = ""
        self.player_shot_history.clear()
        self.player_dive_history.clear()
        self.player_power_history.clear()
        self.match_stats = {
            "player_shots": 0, "player_goals": 0, "player_saves": 0,
            "player_misses": 0, "player_skill_uses": 0,
            "ai_shots": 0, "ai_goals": 0, "ai_saves": 0,
            "ai_misses": 0, "ai_skill_uses": 0,
            "player_power_shots": 0, "ai_power_shots": 0,
            "max_ball_speed": 0.0, "total_shots": 0,
            "key_events": [],
        }
        self.results_log.clear()
        self.round_phase = 0
        self.attacker_is_player = True
        self._start_new_round()

    def _start_new_round(self):
        self.round_num += 1
        self.round_phase = 0
        self.attacker_is_player = True
        self._charge_skills()
        self._setup_shot(player_attacker=True)

    def _charge_skills(self):
        """每轮充能 - 充能速度受比赛节奏与角色状态影响."""
        # 比分差距小(激烈) = 充能快; 差距大(一边倒) = 充能慢
        score_gap = abs(self.player_score - self.ai_score)
        rhythm_bonus = max(0, 8 - score_gap * 2)  # 差距0->+8, 差距4+->+0
        # 玩家充能
        p_fatigue_penalty = max(0, self.player_fatigue - 3) * 1.5  # 疲劳>3开始减慢
        p_charge_gain = 20 + rhythm_bonus - p_fatigue_penalty
        self.player_skill_charge = min(100, self.player_skill_charge + max(5, p_charge_gain))
        # AI充能
        a_fatigue_penalty = max(0, self.ai_fatigue - 3) * 1.5
        a_charge_gain = 20 + rhythm_bonus - a_fatigue_penalty
        self.ai_skill_charge = min(100, self.ai_skill_charge + max(5, a_charge_gain))

    def _setup_shot(self, player_attacker: bool):
        self.attacker_is_player = player_attacker
        self._shot_skill = "normal"      # 每次射门前重置(结算时读取实际生效技能)
        self.ai_selected_skill = "normal"
        self.ball = Ball()
        self.keeper = KeeperState()
        self.keeper.x = 0.0
        self.keeper.y = 0.0
        self.striker = StrikerState()
        self.striker.z = PENALTY_Z - 0.6 if player_attacker else PENALTY_Z - 0.6
        # AI 决策
        if player_attacker:
            # 玩家射门 - AI守门, 选好扑救方向
            self._ai_decide_dive()
        else:
            # AI 射门 - 选好射门参数(目标+力度)
            self._ai_decide_shot()
        self.aim_cell = 5
        self.power_charging = False
        self.power_value = 0.0
        self.power_dir = 1
        self.selected_skill = "normal"
        self.curve_cell2 = 0
        self.save_fail_reason = ""   # 清掉上一球的扑救失败原因
        self.power_shot_active = False
        self.state = State.READY
        self.intro_t = 0.0
        self.state_t = 0.0

    def _ai_decide_shot(self):
        """AI 决定射门目标 + 力度 - 智能策略系统."""
        # 整场固定一名射手(在 reset_match 里已选定), 这里只取用, 不再换人
        ai_sp = self.ai_striker_profile
        if ai_sp is None:
            ai_sp = random.choice(STRIKERS)
            self.ai_striker_profile = ai_sp
        cells = list(CELL_CENTERS.keys())

        # 1. 比分形势分析: 落后=激进, 领先=保守, 平局=正常
        score_diff = self.ai_score - self.player_score
        if score_diff < 0:
            # 落后: 偏好边角+大力
            aggression = 1.3
            power_bias = 0.15
        elif score_diff > 0:
            # 领先: 偏好中路+稳射
            aggression = 0.7
            power_bias = -0.15
        else:
            aggression = 1.0
            power_bias = 0.0

        # 2. 疲劳分析: 疲劳高则降低力度
        fatigue_factor = 1.0 - self.ai_fatigue * 0.05

        # 3. 目标选择 - 边角权重根据形势调整
        weights = []
        for c in cells:
            x, y = CELL_CENTERS[c]
            edge = (abs(x) + (1.85 - y)) / 5.0
            w_val = (1.0 + edge * aggression) * fatigue_factor
            weights.append(max(0.3, w_val))
        cell = random.choices(cells, weights=weights, k=1)[0]
        tx, ty = CELL_CENTERS[cell]

        # 4. 力度决策
        acc = ai_sp.accuracy
        max_safe_power = (0.55 + 0.04 * acc + power_bias) * fatigue_factor
        power = random.uniform(0.5, max(0.65, min(0.95, max_safe_power)))

        # 5. 技能使用决策(加强版: 三种进攻技能都会用, 并按比分形势调整概率)
        self.ai_selected_skill = self._ai_pick_skill(ai_sp, score_diff)
        if self.ai_selected_skill == "power_shot":
            power = 1.3                       # 超大力射门
        elif self.ai_selected_skill == "precision":
            power = min(power, 0.6)           # 超精准射门: 力度上限60%
        elif self.ai_selected_skill == "curve":
            # 弧线球: 再选一个格子作第二落点, 真实落点在两格之间(与玩家一致)
            c2 = self._ai_pick_curve_cell2(cell)
            self.ai_curve_cell2 = c2
            tx2, ty2 = CELL_CENTERS[c2]
            mix = random.uniform(0.3, 0.7)
            tx = tx * mix + tx2 * (1 - mix)
            ty = ty * mix + ty2 * (1 - mix)
            # 侧旋方向: 由第一目标指向第二目标(决定球往哪边弯)
            self.ai_curve_dir = 1.0 if (tx2 - CELL_CENTERS[cell][0]) > 0 else -1.0

        self.ai_target = (tx, ty, power)

    def _ai_pick_skill(self, ai_sp, score_diff: int) -> str:
        """AI 进攻技能决策 - 按射手技能 + 充能 + 比分形势决定使用哪种技能.

        返回 "normal" / "power_shot" / "precision" / "curve".
        超大力需充能60, 超精准需充能80且每场1次, 弧线球无限使用(与玩家一致).
        """
        sk = getattr(ai_sp, "skill", "none")
        if sk in (None, "", "none"):
            return "normal"
        # 关键时刻(加时/突然死亡)AI 更敢用技能
        clutch = 0.20 if self.is_overtime else 0.0
        if sk == "power_shot":
            if self.ai_skill_charge < 60:
                return "normal"
            # 落后=拼命搏重炮, 领先=少见血
            p = 0.60 if score_diff < 0 else (0.45 if score_diff == 0 else 0.32)
            return "power_shot" if random.random() < min(0.85, p + clutch) else "normal"
        if sk == "precision":
            if self.ai_precision_used or self.ai_skill_charge < 80:
                return "normal"
            # 领先/平局时更倾向用精准稳住(打死角)
            p = 0.50 if score_diff >= 0 else 0.30
            return "precision" if random.random() < min(0.80, p + clutch) else "normal"
        if sk == "curve":
            # 弧线球无限使用, AI 使用率很高(这是它的立身之本)
            p = 0.72 if abs(score_diff) >= 1 else 0.58
            return "curve" if random.random() < min(0.90, p + clutch) else "normal"
        return "normal"

    def _ai_pick_curve_cell2(self, cell: int) -> int:
        """AI 弧线球第二落点: 优先选同一行相邻的格子(弧线更明显)."""
        row = (cell - 1) // 3          # 0=上, 1=中, 2=下
        candidates = [row * 3 + 1, row * 3 + 2, row * 3 + 3]
        candidates = [c for c in candidates if c != cell and 1 <= c <= 9]
        if not candidates:
            candidates = [c for c in range(1, 10) if c != cell]
        return random.choice(candidates)

    def _ai_decide_dive(self):
        """AI 决定扑救方向 - 学习玩家射门模式."""
        # 整场固定一名门将(在 reset_match 里已选定), 这里只取用, 不再换人
        ai_kp = self.ai_keeper_profile
        if ai_kp is None:
            ai_kp = random.choice(KEEPERS)
            self.ai_keeper_profile = ai_kp
        cells = list(CELL_CENTERS.keys())

        # 1. 比分形势: 落后=赌边角, 领先=守中路
        score_diff = self.ai_score - self.player_score
        if score_diff < 0:
            corner_bias = 1.4  # 落后时更倾向猜边角(玩家倾向边角)
        elif score_diff > 0:
            corner_bias = 0.8  # 领先时倾向猜中路
        else:
            corner_bias = 1.0

        # 2. 学习玩家射门历史 - 如果玩家重复选某个方向, 提高该方向权重
        pattern_weights = [10, 4, 10, 8, 8, 8, 10, 20, 10]  # 基础权重
        if len(self.player_shot_history) >= 2:
            # 统计玩家最常选的方向(大方向: 左/中/右)
            recent = self.player_shot_history[-3:]  # 最近3次
            for c in recent:
                col = (c - 1) % 3          # 0=左, 1=中, 2=右
                # 玩家常打这一列 -> 该列的上/中/下三格权重都提高
                # (原实现判断条件恒为左列、加权却按行, 导致学习机制完全失效)
                for row in range(3):
                    pattern_weights[col + row * 3] *= 1.5

        # 3. 应用形势修正
        weights = []
        for i, c in enumerate(cells):
            x, y = CELL_CENTERS[c]
            is_corner = abs(x) > 1.5 and (y > 1.5 or y < 0.8)
            w_val = pattern_weights[i] * (corner_bias if is_corner else 1.0)
            weights.append(max(1, w_val))
        cell = random.choices(cells, weights=weights, k=1)[0]
        tx, ty = CELL_CENTERS[cell]
        self.ai_dive_target = (tx, ty)

    # ----------------------------------------------------------------
    # 鼠标辅助方法
    # ----------------------------------------------------------------
    def _point_in_rect(self, pos, rect):
        """判断点是否在矩形内. rect=(x,y,w,h)."""
        x, y, w, h = rect
        return x <= pos[0] <= x + w and y <= pos[1] <= y + h

    def _point_in_quad(self, pt, p1, p2, p3, p4):
        """判断点pt是否在凸四边形p1p2p3p4内(叉积同号法)."""
        def cross(o, a, b):
            return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
        pts = [(p1[0], p1[1]), (p2[0], p2[1]), (p3[0], p3[1]), (p4[0], p4[1])]
        signs = []
        for i in range(4):
            cp = cross(pts[i], pts[(i + 1) % 4], (pt[0], pt[1]))
            if cp != 0:
                signs.append(1 if cp > 0 else -1)
        if not signs:
            return False
        return all(s > 0 for s in signs) or all(s < 0 for s in signs)

    def _cell_at_pos(self, pos):
        """返回鼠标位置对应的九宫格编号(1-9), None=不在球门格内."""
        gz = GOAL_Z
        w, h = GOAL_W, GOAL_H
        for cell in range(1, 10):
            x1, x2, y1, y2 = cell_rect(cell)
            p1 = project(x1, y1, gz)
            p2 = project(x2, y1, gz)
            p3 = project(x2, y2, gz)
            p4 = project(x1, y2, gz)
            if self._point_in_quad(pos, p1, p2, p3, p4):
                return cell
        return None

    def _draw_button(self, screen, rect, text, hover=False, active=False,
                     font=None):
        """绘制按钮. rect=(x,y,w,h). 返回rect供点击检测."""
        if font is None:
            font = self.font_m
        x, y, w, h = rect
        if active:
            bg, border, bw = GOLD, GOLD, 3
            tc = BLACK
        elif hover:
            bg, border, bw = PANEL_LT, GOLD, 2
            tc = WHITE
        else:
            bg, border, bw = PANEL, (90, 110, 95), 1
            tc = WHITE
        pygame.draw.rect(screen, bg, (x, y, w, h), border_radius=10)
        pygame.draw.rect(screen, border, (x, y, w, h), bw, border_radius=10)
        txt = font.render(text, True, tc)
        screen.blit(txt, (x + w // 2 - txt.get_width() // 2,
                          y + h // 2 - txt.get_height() // 2))
        return rect

    def _button_rect(self, cx, cy, w, h):
        """根据中心坐标和宽高返回按钮矩形."""
        return (cx - w // 2, cy - h // 2, w, h)

    def _get_power_level(self):
        """返回当前射门力度等级('weak'/'medium'/'strong')及显示信息.
        基于AI射门参数(玩家守门时)或玩家蓄力(玩家射门时)."""
        if not self.attacker_is_player and self.ai_target:
            power = self.ai_target[2]
        elif self.attacker_is_player and self.state == State.BALL_FLY:
            power = 0.5  # 球已飞出, 用中等
        else:
            power = self.power_value
        # 球速估算
        sp_power = self.striker_profile.power if self.attacker_is_player else (
            self.ai_striker_profile.power if self.ai_striker_profile else 8)
        # 估算出球速度, 再乘以空气阻力衰减 = 到达门线时的真实速度
        est_speed = (SPD_LO.get(sp_power, 15.0) + SPD_SLOPE * power) * SPEED_DECAY
        if est_speed < 19.0:
            return "weak", "弱力", GREEN, "球速慢 - 反应时间充足, 相邻格也能靠臂展扑到"
        elif est_speed < 23.5:
            return "medium", "中力", GOLD, "正常球速 - 正常扑救即可"
        else:
            return "strong", "重力", RED, "球速极快 - 相邻格几乎扑不到, 必须选准格子"

    def _est_ball_speed(self) -> float:
        """估算本次射门到达门线时的速度(已扣除空气阻力, 用于守门面板展示)."""
        if not self.attacker_is_player and self.ai_target:
            power = self.ai_target[2]
        elif self.attacker_is_player and self.state == State.BALL_FLY:
            power = 0.5
        else:
            power = self.power_value
        sp_power = self.striker_profile.power if self.attacker_is_player else (
            self.ai_striker_profile.power if self.ai_striker_profile else 8)
        return (SPD_LO.get(sp_power, 15.0) + SPD_SLOPE * power) * SPEED_DECAY

    def _adjacent_save_prob(self, speed: float = None) -> float:
        """门将选到相邻格(臂展覆盖)时的扑救成功率 - 臂展越长越高, 球越慢越高."""
        kp = self.keeper_profile
        if speed is None:
            speed = self._est_ball_speed()
        slow = max(0.0, min(1.0, (26.0 - speed) / 8.0))
        reach_n = max(0.30, kp.reach / 10.0)
        p = (0.02 + slow * 0.48) * (reach_n ** 2.2)
        rf = 0.6 + 0.04 * kp.reach
        ref_f = 0.6 + 0.04 * kp.reflex
        df = 0.6 + 0.04 * kp.dive
        p *= (ref_f * 0.15 + rf * 0.70 + df * 0.15)
        # 与实际判定 _resolve_outcome 保持同一套系数, 避免界面估算误导玩家
        sp = self.ai_striker_profile if self.ai_striker_profile else STRIKERS[0]
        p *= max(0.80, 1.0 - (sp.power - 5) * 0.022)
        p *= 1.0 - (sp.accuracy - 6) * 0.042
        return max(0.0, min(1.0, p))

    # ----------------------------------------------------------------
    # 输入
    # ----------------------------------------------------------------
    def handle_event(self, ev):
        if ev.type == pygame.QUIT:
            self.running = False
            return

        # 手机端: SDL 触屏事件 -> 转成鼠标事件, 这样整套鼠标交互都能用
        # 注意: 触屏坐标在这里已经换算成画布坐标了, 下面不能再换算一次
        already_canvas = False
        if ev.type in (getattr(pygame, "FINGERDOWN", -1),
                       getattr(pygame, "FINGERMOTION", -2),
                       getattr(pygame, "FINGERUP", -3)):
            # 触屏给的是 0~1 的归一化坐标, 必须乘"窗口真实像素尺寸"——
            # SCALED 模式下 screen.get_size() 是 1280x800 的逻辑尺寸,
            # 乘它的话黑边区域会被算进去, 点击整体偏移。
            tw, th = self._win_w, self._win_h
            cpos = self._to_canvas_pos((ev.x * tw, ev.y * th))
            already_canvas = True
            if ev.type == getattr(pygame, "FINGERDOWN", -1):
                # 去重: 若 SDL 的"触屏模拟鼠标"没被完全关掉, 同一次触摸会
                # 先到 FINGERDOWN 再到 MOUSEBUTTONDOWN。只认第一次。
                if not self._accept_tap(cpos):
                    return
                ev = pygame.event.Event(pygame.MOUSEBUTTONDOWN,
                                        pos=cpos, button=1)
            elif ev.type == getattr(pygame, "FINGERMOTION", -2):
                # 触屏拖动不改选择(rel 置 0, 被"必须真的移动"的规则挡掉)
                ev = pygame.event.Event(pygame.MOUSEMOTION, pos=cpos,
                                        rel=(0, 0), buttons=(0, 0, 0))
            else:
                ev = pygame.event.Event(pygame.MOUSEBUTTONUP,
                                        pos=cpos, button=1)

        # 鼠标事件 - 先把真实屏幕坐标换算到 1280x800 画布, 再更新鼠标状态
        if (not already_canvas and
                ev.type in (pygame.MOUSEMOTION, pygame.MOUSEBUTTONDOWN,
                            pygame.MOUSEBUTTONUP)):
            try:
                if ev.type == pygame.MOUSEMOTION:
                    ev = pygame.event.Event(
                        ev.type, pos=self._to_canvas_pos(ev.pos),
                        rel=ev.rel, buttons=ev.buttons)
                else:
                    ev = pygame.event.Event(
                        ev.type, pos=self._to_canvas_pos(ev.pos),
                        button=ev.button)
            except Exception:
                pass
            # 同上: 触摸模拟出来的鼠标按下也要去重, 否则一次点击处理两遍
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                try:
                    if not self._accept_tap(ev.pos):
                        return
                except Exception:
                    pass

        if ev.type == pygame.MOUSEMOTION:
            self.mouse_pos = ev.pos
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            self.mouse_pos = ev.pos
            self.mouse_down = True
        elif ev.type == pygame.MOUSEBUTTONUP and ev.button == 1:
            self.mouse_pos = ev.pos
            self.mouse_down = False

        if ev.type == pygame.KEYDOWN:
            # K_AC_BACK = 安卓返回键
            ac_back = getattr(pygame, "K_AC_BACK", None)
            if ev.key == pygame.K_ESCAPE or (ac_back and ev.key == ac_back):
                if self.state == State.MENU:
                    self.running = False
                else:
                    self.state = State.MENU
                    self.state_t = 0.0
                return
            if ev.key == pygame.K_r:
                # 重新开始 - GAME_OVER 时直接重选球员, 其他状态回菜单
                if self.state == State.GAME_OVER:
                    self.state = State.SELECT_STRIKER
                else:
                    self.state = State.MENU
                self.state_t = 0.0
                return

        if self.state == State.MENU:
            self._handle_menu(ev)
        elif self.state == State.HELP:
            self._handle_help(ev)
        elif self.state == State.SELECT_STRIKER:
            self._handle_select_striker(ev)
        elif self.state == State.SELECT_KEEPER:
            self._handle_select_keeper(ev)
        elif self.state == State.READY:
            self._handle_ready(ev)
        elif self.state == State.PLAYER_AIM:
            self._handle_player_aim(ev)
        elif self.state == State.PLAYER_POWER:
            self._handle_player_power(ev)
        elif self.state == State.ROUND_RESULT:
            self._handle_result(ev)
        elif self.state == State.EARLY_END:
            self._handle_early_end(ev)
        elif self.state == State.GAME_OVER:
            self._handle_gameover(ev)

    def _menu_item_rect(self, i):
        """返回菜单项i的点击矩形."""
        y = 340 + i * 70
        w, h = 320, 56
        return (WIDTH // 2 - w // 2, y, w, h)

    def _menu_confirm(self):
        if self.menu_idx == 0:
            self.state = State.SELECT_STRIKER
            self.menu_idx = 0
            self.state_t = 0.0
        elif self.menu_idx == 1:
            self.state = State.HELP
            self.state_t = 0.0
        else:
            self.running = False

    def _handle_menu(self, ev):
        if ev.type == pygame.KEYDOWN:
            if ev.key in (pygame.K_UP, pygame.K_w):
                self.menu_idx = (self.menu_idx - 1) % 3
            elif ev.key in (pygame.K_DOWN, pygame.K_s):
                self.menu_idx = (self.menu_idx + 1) % 3
            elif ev.key in (pygame.K_RETURN, pygame.K_SPACE):
                self._menu_confirm()
        elif ev.type == pygame.MOUSEMOTION:
            for i in range(3):
                if self._point_in_rect(ev.pos, self._menu_item_rect(i)):
                    self.menu_idx = i
                    break
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            for i in range(3):
                if self._point_in_rect(ev.pos, self._menu_item_rect(i)):
                    self.menu_idx = i
                    self._menu_confirm()
                    break

    def _striker_card_rect(self, i):
        """返回射门球员卡片i的矩形.

        注意: 4 张卡必须整体装进 1280 宽的画面里。
        原来 card_w=320/gap=40 时总宽 1400 > 1280, 首尾两张被推到屏幕外,
        手机上看着"点了没反应" —— 这里收窄到总宽 1170, 四张都完整可见可点。
        """
        n = len(STRIKERS)
        card_w, card_h = 270, 500
        gap = 30
        total_w = n * card_w + (n - 1) * gap
        start_x = (WIDTH - total_w) // 2
        x = start_x + i * (card_w + gap)
        return (x, 130, card_w, card_h)

    def _handle_select_striker(self, ev):
        n = len(STRIKERS)
        if ev.type == pygame.KEYDOWN:
            if ev.key in (pygame.K_LEFT, pygame.K_a):
                self.selected_striker_idx = (self.selected_striker_idx - 1) % n
            elif ev.key in (pygame.K_RIGHT, pygame.K_d):
                self.selected_striker_idx = (self.selected_striker_idx + 1) % n
            elif ev.key in (pygame.K_RETURN, pygame.K_SPACE):
                self.state = State.SELECT_KEEPER
                self.state_t = 0.0
        elif ev.type == pygame.MOUSEMOTION:
            for i in range(n):
                if self._point_in_rect(ev.pos, self._striker_card_rect(i)):
                    self.selected_striker_idx = i
                    break
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            for i in range(n):
                if self._point_in_rect(ev.pos, self._striker_card_rect(i)):
                    self.selected_striker_idx = i
                    self.state = State.SELECT_KEEPER
                    self.state_t = 0.0
                    break

    def _keeper_card_rect(self, i):
        """返回守门员卡片i的矩形."""
        n = len(KEEPERS)
        card_w, card_h = 220, 420
        gap = 18
        total_w = n * card_w + (n - 1) * gap
        start_x = (WIDTH - total_w) // 2
        x = start_x + i * (card_w + gap)
        return (x, 150, card_w, card_h)

    def _handle_select_keeper(self, ev):
        n = len(KEEPERS)
        if ev.type == pygame.KEYDOWN:
            if ev.key in (pygame.K_LEFT, pygame.K_a):
                self.selected_keeper_idx = (self.selected_keeper_idx - 1) % n
            elif ev.key in (pygame.K_RIGHT, pygame.K_d):
                self.selected_keeper_idx = (self.selected_keeper_idx + 1) % n
            elif ev.key in (pygame.K_RETURN, pygame.K_SPACE):
                self.reset_match()
        elif ev.type == pygame.MOUSEMOTION:
            for i in range(n):
                if self._point_in_rect(ev.pos, self._keeper_card_rect(i)):
                    self.selected_keeper_idx = i
                    break
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            for i in range(n):
                if self._point_in_rect(ev.pos, self._keeper_card_rect(i)):
                    self.selected_keeper_idx = i
                    self.reset_match()
                    break

    def _ready_button_rect(self):
        """READY阶段"继续"按钮矩形."""
        return self._button_rect(WIDTH // 2, HEIGHT // 2 + 100, 220, 50)

    def _handle_ready(self, ev):
        if ev.type == pygame.KEYDOWN:
            if ev.key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_UP, pygame.K_w,
                          pygame.K_DOWN, pygame.K_s, pygame.K_LEFT, pygame.K_a,
                          pygame.K_RIGHT, pygame.K_d):
                self._enter_aim()
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            if self._point_in_rect(ev.pos, self._ready_button_rect()):
                self._enter_aim()

    def _enter_aim(self):
        self.state = State.PLAYER_AIM
        self.state_t = 0.0
        self.aim_cell = 5

    def _aim_confirm_button_rect(self):
        """瞄准阶段确认按钮矩形(射门=蓄力射门, 守门=确认扑救)."""
        return self._button_rect(WIDTH // 2, HEIGHT - 80, 200, 44)

    def _handle_player_aim(self, ev):
        sp = self.striker_profile
        is_curve_mode = (sp.skill == "curve" and self.selected_skill == "curve")
        if ev.type == pygame.KEYDOWN:
            if ev.key in KEY_TO_CELL:
                cell = KEY_TO_CELL[ev.key]
                self._handle_cell_select(cell, is_curve_mode)
            elif ev.key in ARROW_TO_CELL:
                cell = ARROW_TO_CELL[ev.key]
                self._handle_cell_select(cell, is_curve_mode)
            elif ev.key == pygame.K_q:
                self._toggle_skill()
            elif ev.key in (pygame.K_SPACE, pygame.K_RETURN):
                self._aim_confirm()
        elif ev.type == pygame.MOUSEMOTION:
            cell = self._cell_at_pos(ev.pos)
            # 只有鼠标"真的移动过"才让悬停改写选择:
            # 否则用键盘选好格子后, 鼠标停在球门上被轻微抖一下就被顶掉
            moved = abs(getattr(ev, "rel", (0, 0))[0]) + \
                abs(getattr(ev, "rel", (0, 0))[1]) >= 2
            if cell is not None and moved:
                if is_curve_mode and self.curve_cell2 != 0:
                    # 弧线模式: 主目标已定(正在等第二格/已选完), 悬停不动主目标
                    pass
                else:
                    self.aim_cell = cell
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            cell = self._cell_at_pos(ev.pos)
            if cell is not None:
                self._handle_cell_select(cell, is_curve_mode)
            sp = self.striker_profile
            # 守门阶段不画技能按钮, 也就不能留一个看不见的点击热区
            if (self.attacker_is_player and sp.skill != "none" and
                    self._point_in_rect(ev.pos, self._skill_button_rect())):
                self._toggle_skill()
            if self._point_in_rect(ev.pos, self._aim_confirm_button_rect()):
                self._aim_confirm()

    def _handle_cell_select(self, cell, is_curve_mode):
        """处理格子选择 - 弧线球模式支持选两个相邻格."""
        if is_curve_mode:
            if self.curve_cell2 == 0:
                # 第一次点击 = 主目标
                self.aim_cell = cell
                self.curve_cell2 = -1  # 标记等待第二格
            elif self.curve_cell2 == -1:
                # 第二次点击 = 必须是相邻格
                if cell in CELL_ADJACENT.get(self.aim_cell, []) and cell != self.aim_cell:
                    self.curve_cell2 = cell
                else:
                    # 非相邻格 -> 重新选主目标
                    self.aim_cell = cell
                    self.curve_cell2 = -1
            else:
                # 已选好两格, 再点 = 重新开始
                self.aim_cell = cell
                self.curve_cell2 = -1
        else:
            self.aim_cell = cell
            self.curve_cell2 = 0

    def _toggle_skill(self):
        """切换射门技能选择."""
        sp = self.striker_profile
        if sp.skill == "precision" and not self.precision_shot_used:
            if self.player_skill_charge >= 80:
                self.selected_skill = ("precision" if self.selected_skill != "precision"
                                       else "normal")
                if self.selected_skill != "precision":
                    self.curve_cell2 = 0
        elif sp.skill == "power_shot":
            if self.player_skill_charge >= 60:
                self.selected_skill = ("power_shot" if self.selected_skill != "power_shot"
                                        else "normal")
                if self.selected_skill != "power_shot":
                    self.curve_cell2 = 0
        elif sp.skill == "curve":
            # 弧线球: 无限使用, 无需充能
            self.selected_skill = ("curve" if self.selected_skill != "curve"
                                   else "normal")
            # 进入弧线模式时先等玩家点"第一目标"(curve_cell2=0),
            # 之后第一格 -> -1(等第二格) -> 第二格 -> 具体编号
            # (之前直接置 -1, 导致第一次点击被当成第二格, 主目标还是旧值)
            self.curve_cell2 = 0
            self.aim_cell = 5

    def _aim_confirm(self):
        if self.attacker_is_player:
            # 进入蓄力
            self.state = State.PLAYER_POWER
            self.state_t = 0.0
            self.power_charging = True
            self.power_value = 0.0
            self.power_dir = 1
        else:
            # 玩家守门 - 直接确认扑救方向
            self._commit_player_defense()

    def _shoot_button_rect(self):
        """蓄力阶段射门按钮矩形."""
        return self._button_rect(WIDTH // 2, HEIGHT - 80, 200, 44)

    def _handle_player_power(self, ev):
        if ev.type == pygame.KEYUP and ev.key == pygame.K_SPACE:
            self._commit_player_shot()
        elif ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_RETURN:
                self._commit_player_shot()
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            # 鼠标点击 -> 射门(蓄力条在当前值射门)
            # 忽略刚从PLAYER_AIM进入时的误触(state_t<0.15秒)
            if self.state_t > 0.15:
                self._commit_player_shot()

    def _result_button_rect(self):
        """结果阶段"继续"按钮矩形."""
        return self._button_rect(WIDTH // 2, HEIGHT // 2 + 60, 220, 50)

    def _handle_result(self, ev):
        if ev.type == pygame.KEYDOWN:
            if ev.key in (pygame.K_RETURN, pygame.K_SPACE):
                self._advance_after_result()
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            # 按钮 0.6s 后才画出来, 之前点同一位置不应生效(防止连点误触)
            if (self.result_t > 0.6 and
                    self._point_in_rect(ev.pos, self._result_button_rect())):
                self._advance_after_result()

    def _gameover_menu_rect(self):
        """GAME_OVER "返回菜单"按钮矩形."""
        return self._button_rect(WIDTH // 2 - 140, 600, 220, 50)

    def _gameover_retry_rect(self):
        """GAME_OVER "再来一局"按钮矩形."""
        return self._button_rect(WIDTH // 2 + 140, 600, 220, 50)

    def _handle_help(self, ev):
        if ev.type == pygame.KEYDOWN:
            if ev.key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_ESCAPE):
                self.state = State.MENU
                self.state_t = 0.0
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            # 点击返回按钮
            rect = self._button_rect(WIDTH // 2, HEIGHT - 80, 200, 50)
            if self._point_in_rect(ev.pos, rect):
                self.state = State.MENU
                self.state_t = 0.0

    def _early_end_continue_rect(self):
        return self._button_rect(WIDTH // 2 - 130, HEIGHT // 2 + 80, 220, 50)

    def _early_end_end_rect(self):
        return self._button_rect(WIDTH // 2 + 130, HEIGHT // 2 + 80, 220, 50)

    def _handle_early_end(self, ev):
        if ev.type == pygame.KEYDOWN:
            if ev.key in (pygame.K_RETURN, pygame.K_SPACE):
                # 默认继续比赛
                self._continue_after_early_end()
            elif ev.key == pygame.K_e:
                # 直接结算
                self._end_match_early()
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            if self._point_in_rect(ev.pos, self._early_end_continue_rect()):
                self._continue_after_early_end()
            elif self._point_in_rect(ev.pos, self._early_end_end_rect()):
                self._end_match_early()

    def _continue_after_early_end(self):
        """用户选择继续比赛(把剩下的罚球踢完)."""
        if self.round_phase == 0:
            # 本轮 AI 那一球还没罚
            self.round_phase = 1
            self._setup_shot(player_attacker=False)
        else:
            if self.round_num >= self.total_rounds:
                if self.player_score == self.ai_score:
                    self._start_overtime()
                else:
                    self.state = State.GAME_OVER
                    self.state_t = 0.0
            else:
                self._start_new_round()
        self.state = State.READY
        self.state_t = 0.0

    def _end_match_early(self):
        """用户选择直接结算."""
        self.state = State.GAME_OVER
        self.state_t = 0.0

    def _handle_gameover(self, ev):
        if ev.type == pygame.KEYDOWN:
            if ev.key in (pygame.K_RETURN, pygame.K_SPACE):
                self.state = State.MENU
                self.state_t = 0.0
            elif ev.key == pygame.K_r:
                self.state = State.SELECT_STRIKER
                self.state_t = 0.0
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            if self._point_in_rect(ev.pos, self._gameover_menu_rect()):
                self.state = State.MENU
                self.state_t = 0.0
            elif self._point_in_rect(ev.pos, self._gameover_retry_rect()):
                self.state = State.SELECT_STRIKER
                self.state_t = 0.0

    # ----------------------------------------------------------------
    # 玩家操作提交
    # ----------------------------------------------------------------
    def _commit_player_shot(self):
        """玩家完成射门 - 计算球速和落点.
        力量->射门力量上限, 准度->大力球偏差, 心理->加时准度+疲劳减缓
        """
        sp = self.striker_profile
        tx, ty = CELL_CENTERS[self.aim_cell]
        power = max(0.25, min(1.0, self.power_value))
        self.player_shot_history.append(self.aim_cell)
        self.player_power_history.append(power)
        # 疲劳: 力度上限降低(疲劳10->力度上限20%)
        fatigue_power_cap = 1.0 - self.player_fatigue * 0.12
        power = min(power, max(0.25, fatigue_power_cap))

        # 弧线球: 在两格间随机落点(无限使用,不需充能)
        is_curve = (sp.skill == "curve" and self.curve_cell2 > 0)
        if is_curve:
            tx2, ty2 = CELL_CENTERS[self.curve_cell2]
            mix = random.uniform(0.3, 0.7)
            tx = tx * mix + tx2 * (1 - mix)
            ty = ty * mix + ty2 * (1 - mix)

        # 技能效果(需充能达到阈值)
        is_precision = (self.selected_skill == "precision" and
                        sp.skill == "precision" and not self.precision_shot_used
                        and self.player_skill_charge >= 80)
        is_power_shot = (self.selected_skill == "power_shot" and
                         sp.skill == "power_shot"
                         and self.player_skill_charge >= 60)

        if is_precision:
            power = min(power, 0.6)
            noise_amp = 0.12
            self.precision_shot_used = True
            self.player_skill_charge = 0
        elif is_power_shot:
            power = 1.3
            # 超大力: 准度控制偏差(accuracy越高偏差越小)
            noise_amp = (1.0 - sp.accuracy / 10.0) * 0.6
            self.player_skill_charge = 0
        else:
            # 普通射门: 准度控制偏差(accuracy越高偏差越小)
            noise_amp = (1.0 - sp.accuracy / 10.0) * 0.6
        # 记录本次射门"实际生效"的技能(赛后统计只认真正生效的, 不被按钮状态误导)
        if is_power_shot:
            self._shot_skill = "power_shot"
        elif is_precision:
            self._shot_skill = "precision"
        elif is_curve:
            self._shot_skill = "curve"
        else:
            self._shot_skill = "normal"
        # 心理(composure): 加时赛准度加成
        if self.is_overtime:
            ot_bonus = sp.composure / 10.0 * 0.15  # composure10->偏差减15%
            noise_amp *= (1.0 - ot_bonus)
        # 疲劳增加偏差
        fatigue_penalty = self.player_fatigue * 0.14
        noise_amp += fatigue_penalty
        # 力度系数
        power_factor = 0.3 + 0.7 * min(1.0, power)
        # 大力射门偏差: 准度高的球员大力球偏差惩罚更小
        if power > 0.7:
            big_power_penalty = (power - 0.7) / 0.3
            # 准度10->惩罚系数0.4, 准度5->惩罚系数0.8
            acc_mod = 0.8 - sp.accuracy * 0.04
            noise_amp *= (1 + big_power_penalty * acc_mod)
        dev_x = random.gauss(0, 1.5 * noise_amp * power_factor)
        dev_y = random.gauss(0, 1.2 * noise_amp * power_factor)
        actual_tx = tx + dev_x
        actual_ty = max(0.05, ty + dev_y)
        # 球速(向前分量) - 力量决定上限, 疲劳降速(v1.06 重新标定 + 概率浮动)
        speed = _shot_speed(power, sp.power, self.player_fatigue, is_power_shot)
        # 自转(rad/s, 绕竖直轴): 弧线球给强侧旋, 普通球只有轻微随机旋转
        # 真实香蕉球约 8~12 转/秒; 弧线球为了踢出旋转必须"搓"球,
        # 触球不实 => 球速下降约12%(这也是真实规律)
        if is_curve:
            speed *= 0.88
            dx_curve = (CELL_CENTERS[self.curve_cell2][0]
                        - CELL_CENTERS[self.aim_cell][0])
            if abs(dx_curve) < 0.15:
                sgn = random.choice([-1.0, 1.0])
                strength = 95 + sp.power * 3.2
            else:
                sgn = 1.0 if dx_curve > 0 else -1.0
                strength = 118 + sp.power * 3.6
            spin_rate = sgn * strength
        else:
            spin_rate = random.uniform(-9.0, 9.0)
        self._launch_ball(actual_tx, actual_ty, speed, spin_rate)
        self.ball.active = True
        self.ball.trail = []
        self.striker.kicked = True
        self.striker.run_t = 0.0
        self.striker.kick_vz = 2.6       # 踢完球后的前冲初速
        self.power_charging = False
        self._setup_keeper_dive_for_ball_fly()
        self.state = State.BALL_FLY
        self.state_t = 0.0

    def _launch_ball(self, tx: float, ty: float, speed: float,
                     spin_rate: float):
        """用弹道求解器发射足球 - 保证球在门线处正好到达 (tx, ty),
        并且飞行过程完全遵循 重力+空气阻力+马格努斯 的真实物理."""
        b = self.ball
        tx = max(-GOAL_W / 2 - 1.2, min(GOAL_W / 2 + 1.2, tx))
        ty = max(BALL_RADIUS, min(GOAL_H + 1.0, ty))
        b.x, b.y, b.z = 0.0, BALL_RADIUS, PENALTY_Z
        b.vx, b.vy, b.vz, t_flight, v_arrive = solve_launch(
            b.x, b.y, b.z, tx, ty, speed, spin_rate)
        b.spin_rate = spin_rate
        b.spin = 0.0
        b.air_t = 0.0
        # 出球速度(合速度) 与 到达门线时的速度(空气阻力已吃掉约13%)
        self.last_ball_speed = math.hypot(math.hypot(b.vx, b.vy), b.vz)
        self.last_arrive_speed = v_arrive
        self.last_flight_time = t_flight
        self.aim_point = (tx, ty)
        self.ball_fly_t = 0.0

    def _setup_keeper_dive_for_ball_fly(self):
        """球飞起前, 设置守门员扑救的启动参数(反应延迟+方向)."""
        # 决定使用哪个守门员属性
        if self.attacker_is_player:
            # 玩家射门, AI 守门
            kp = self.ai_keeper_profile if self.ai_keeper_profile else random.choice(KEEPERS)
            # 用 AI 在 _ai_decide_dive 时选定的目标
            target_x, target_y = self.ai_dive_target if self.ai_dive_target else (0.0, 1.22)
        else:
            # AI 射门, 玩家守门
            kp = self.keeper_profile
            # 用玩家在 _commit_player_defense 时设置的 target
            target_x = self.keeper.target_x
            target_y = self.keeper.target_y
        # 反应延迟(秒) - reflex 6->0.32s, reflex 10->0.20s
        reaction_delay = 0.50 - 0.030 * kp.reflex
        self.keeper.target_x = target_x
        self.keeper.target_y = target_y
        self.keeper.committed = True
        self.keeper.dive_t = -reaction_delay  # 负值=还没开始扑
        self.keeper.diving = False
        self.keeper.dive_dir = -1 if target_x < -0.2 else (1 if target_x > 0.2 else 0)
        self.keeper.dive_high = target_y > 1.0

    def _commit_player_defense(self):
        """玩家完成守门 - 设置扑救目标."""
        tx, ty = CELL_CENTERS[self.aim_cell]
        # 记录玩家扑救历史(供AI学习)
        self.player_dive_history.append(self.aim_cell)
        self.keeper.target_x = tx
        self.keeper.target_y = ty
        self.keeper.committed = True
        self._ai_execute_shot()

    def _ai_execute_shot(self):
        """AI 完成射门(玩家已选好扑救).
        与玩家射门公式一致: 力量->上限, 准度->偏差, 心理->加时+疲劳
        """
        tx, ty, power = self.ai_target
        ai_sp = self.ai_striker_profile if self.ai_striker_profile else random.choice(STRIKERS)
        # 疲劳: 力度上限降低
        fatigue_power_cap = 1.0 - self.ai_fatigue * 0.12
        power = min(power, max(0.25, fatigue_power_cap))
        # AI 技能生效(决策阶段已选定, 这里只负责生效 + 扣充能)
        ai_skill = getattr(self, "ai_selected_skill", "normal")
        ai_use_skill = ai_skill != "normal"
        if ai_skill == "power_shot":
            power = 1.3                       # 超大力射门(不受疲劳力度上限压制)
            self.ai_skill_charge = 0
        elif ai_skill == "precision":
            power = min(power, 0.6)           # 超精准射门
            self.ai_skill_charge = 0
            self.ai_precision_used = True
        # 准度控制偏差(与玩家一致)
        noise_amp = (1.0 - ai_sp.accuracy / 10.0) * 0.6
        if ai_skill == "power_shot":
            noise_amp *= 1.2  # 超大力偏差略增
        elif ai_skill == "precision":
            noise_amp = 0.12  # 超精准: 偏差暴降至12%
        # 心理: 加时赛准度加成
        if self.is_overtime:
            ot_bonus = ai_sp.composure / 10.0 * 0.15
            noise_amp *= (1.0 - ot_bonus)
        # 疲劳增加偏差
        fatigue_penalty = self.ai_fatigue * 0.14
        noise_amp += fatigue_penalty
        power_factor = 0.3 + 0.7 * min(1.0, power)
        # 大力射门偏差: 准度影响惩罚系数
        if power > 0.7:
            big_power_penalty = (power - 0.7) / 0.3
            acc_mod = 0.8 - ai_sp.accuracy * 0.04
            noise_amp *= (1 + big_power_penalty * acc_mod)
        dev_x = random.gauss(0, 1.5 * noise_amp * power_factor)
        dev_y = random.gauss(0, 1.2 * noise_amp * power_factor)
        actual_tx = tx + dev_x
        actual_ty = max(0.05, ty + dev_y)
        # 球速 - 力量决定上限(与玩家一致)
        speed = _shot_speed(power, ai_sp.power, self.ai_fatigue,
                            ai_skill == "power_shot")
        # AI 弧线球同样用真实侧旋(马格努斯力), 搓球同样损失球速
        if ai_skill == "curve":
            speed *= 0.88
            spin_rate = self.ai_curve_dir * (118 + ai_sp.power * 3.6)
        else:
            spin_rate = random.uniform(-9.0, 9.0)
        # 记录本次射门实际生效的技能(供赛后统计)
        self._shot_skill = ai_skill
        self._launch_ball(actual_tx, actual_ty, speed, spin_rate)
        self.ball.active = True
        self.ball.trail = []
        self.striker.kicked = True
        self.striker.run_t = 0.0
        self.striker.kick_vz = 2.6
        # 启动玩家守门员扑救(用玩家选定的守门员属性, 已在 _commit_player_defense 中设置 target)
        self._setup_keeper_dive_for_ball_fly()
        self.state = State.BALL_FLY
        self.state_t = 0.0

    # ----------------------------------------------------------------
    # 更新
    # ----------------------------------------------------------------
    def update(self, dt: float):
        self.state_t += dt
        if self.cooldown > 0:
            self.cooldown = max(0.0, self.cooldown - dt)

        if self.state == State.READY:
            self.intro_t += dt
            # 球员做助跑准备动画
            self.striker.run_t += dt * 0.5
        elif self.state == State.PLAYER_AIM:
            self.striker.run_t += dt * 0.3
        elif self.state == State.PLAYER_POWER:
            # 蓄力条来回摆动
            if self.power_charging:
                self.power_value += self.power_dir * dt * 1.4
                if self.power_value >= 1.0:
                    self.power_value = 1.0
                    self.power_dir = -1
                elif self.power_value <= 0.0:
                    self.power_value = 0.0
                    self.power_dir = 1
        elif self.state == State.BALL_FLY:
            self._update_ball_fly(dt)
        elif self.state == State.ROUND_RESULT:
            self.result_t += dt
        elif self.state == State.GAME_OVER:
            pass

        # 屏幕震动衰减
        if self.shake_t > 0:
            self.shake_t -= dt
            if self.shake_t < 0:
                self.shake_t = 0
                self.shake_amp = 0
        # 进球闪光衰减
        if self.goal_flash > 0:
            self.goal_flash = max(0.0, self.goal_flash - dt * 1.5)
        # 进球特效衰减
        if self.goal_effect_t > 0:
            self.goal_effect_t = max(0.0, self.goal_effect_t - dt)
        # 扑救特效衰减
        if self.save_effect_t > 0:
            self.save_effect_t = max(0.0, self.save_effect_t - dt)

    def _update_ball_fly(self, dt: float):
        # 物理更新 - 真实弹道: 重力 + 空气阻力 + 马格努斯力 + 地面反弹
        if self.ball.active:
            b = self.ball
            # 固定子步长积分(保证与弹道求解器完全一致, 且帧率无关)
            # 这里的上限必须 >= run() 里 dt 的上限(0.10), 否则掉帧时球会"补不回来",
            # 越卡球飞得越慢 —— 这正是手机上观感变慢的元凶之一。
            remaining = min(dt, 0.12)
            while remaining > 1e-6:
                h = min(PHYS_DT, remaining)
                pos = [b.x, b.y, b.z]
                vel = [b.vx, b.vy, b.vz]
                step_ball(pos, vel, b.spin_rate, h)
                b.x, b.y, b.z = pos[0], pos[1], pos[2]
                b.vx, b.vy, b.vz = vel[0], vel[1], vel[2]
                b.air_t += h
                remaining -= h
            # 自转视觉角度(角速度 → 累积角)
            b.spin += b.spin_rate * dt * 0.55 + dt * 4.0
            # 拖尾
            b.trail.append((b.x, b.y, b.z))
            if len(b.trail) > 14:
                b.trail.pop(0)

        # 守门员扑救动画
        if self.attacker_is_player:
            # 玩家射门, AI守门 - 使用AI在 _ai_decide_dive 时选定的守门员
            kp = self.ai_keeper_profile if self.ai_keeper_profile else random.choice(KEEPERS)
            self._update_keeper_dive(dt, kp)
        else:
            # AI射门, 玩家守门 - 玩家选的守门员属性影响扑救
            kp = self.keeper_profile
            self._update_keeper_dive(dt, kp)

        # 射手: 踢出后靠惯性前冲, 受地面摩擦减速(不再是匀速平移)
        if self.striker.kicked:
            st = self.striker
            st.run_t += dt * 3.2          # 摆腿随挥动画
            if st.kick_vz > 0.05:
                st.z += st.kick_vz * dt
                st.kick_vz -= 5.5 * dt    # 急停摩擦减速度 m/s^2
                if st.kick_vz < 0.05:
                    st.kick_vz = 0.0
            if st.z > PENALTY_Z + 0.45:   # 最多冲出点球点 0.45m
                st.z = PENALTY_Z + 0.45
                st.kick_vz = 0.0

        # 判定进球/扑救/射偏
        if self.ball.active:
            self.ball_fly_t += dt
        if self.ball.active and self.ball.z >= GOAL_Z:
            self._resolve_outcome()
        elif self.ball.active and self.ball_fly_t > 3.0:
            # 兜底: 万一球因数值异常没能到达门线, 也要按当前位置出结果,
            # 否则游戏会永久卡在 BALL_FLY 状态
            self._resolve_outcome()

    def _start_keeper_jump(self, kp: KeeperProfile):
        """门将起跳 - 用真实鱼跃参数: 水平匀速 + 垂直抛物线(受重力)."""
        k = self.keeper
        k.jump_x0 = k.x
        tx, ty = k.target_x, k.target_y
        # 到位时间: 扑救(dive)越高, 横向移动越快
        #   dive10 -> 0.30s, dive7 -> 0.37s, dive4 -> 0.44s
        t_reach = 0.54 - 0.024 * kp.dive
        k.jump_vx = (tx - k.jump_x0) / t_reach if t_reach > 0.05 else 0.0
        # 起跳高度上限(脚离地): dive4 -> 0.73m, dive10 -> 1.15m
        apex_cap = 0.45 + 0.07 * kp.dive
        # 想让身体够到目标高度(手再伸出约0.75m)
        want = ty - 0.75
        want = max(0.0, min(want, apex_cap))
        # 抛物线 y(t_reach) = vy*t - 0.5*g*t^2 = want
        vy = want / t_reach + 0.5 * GRAVITY * t_reach
        # 不能超过身体能力上限(vy_max = sqrt(2*g*apex_cap))
        k.jump_vy = min(vy, math.sqrt(2.0 * GRAVITY * apex_cap))
        k.landed = False
        k.land_x = tx

    def _update_keeper_dive(self, dt: float, kp: KeeperProfile):
        if not self.keeper.committed:
            return
        # 反应延迟(还没起跳)
        if self.keeper.dive_t < 0:
            self.keeper.dive_t += dt
            return
        if not self.keeper.diving:
            self.keeper.diving = True
            self.keeper.dive_t = 0.0
            self._start_keeper_jump(kp)
        k = self.keeper
        k.dive_t += dt
        t = k.dive_t
        if not k.landed:
            # 腾空阶段: 水平匀速 + 垂直抛体
            x = k.jump_x0 + k.jump_vx * t
            y = k.jump_vy * t - 0.5 * GRAVITY * t * t
            # 不许冲过目标(鱼跃到目标即止)
            if k.jump_vx > 0:
                x = min(x, k.target_x)
            elif k.jump_vx < 0:
                x = max(x, k.target_x)
            else:
                x = k.jump_x0
            if y <= 0.0:
                # 落地 - 之后贴地滑行到目标
                y = 0.0
                k.landed = True
                k.land_x = x
            k.x, k.y = x, y
        else:
            # 落地后: 沿地面滑向目标(草地摩擦减速)
            remain = k.target_x - k.x
            if abs(remain) > 0.01:
                step = k.jump_vx * 0.45 * dt
                if abs(step) > abs(remain):
                    k.x = k.target_x
                else:
                    k.x += step
            k.y = 0.0

    def _pos_to_cell(self, x: float, y: float) -> int:
        """将球门内坐标转换为最近的格子编号(1-9)."""
        best_cell = 5
        best_dist = 999.0
        for cell, (cx, cy) in CELL_CENTERS.items():
            d = (x - cx) ** 2 + (y - cy) ** 2
            if d < best_dist:
                best_dist = d
                best_cell = cell
        return best_cell

    def _resolve_outcome(self):
        """球到达球门线时判定结果 - 新属性分工系统."""
        self._break_defense = False
        self.save_fail_reason = ""
        self.ball.active = False
        bx, by, bz = self.ball.x, self.ball.y, GOAL_Z
        # 1. 是否在球门内?(用球心判定, 与真实规则一致: 球整体越过门线)
        in_goal = (-GOAL_W / 2 <= bx <= GOAL_W / 2) and (0 <= by <= GOAL_H)
        if not in_goal:
            self.last_outcome = "MISS"
            # 打在门框上? (球半径 + 门柱半径)
            hit_frame = (
                abs(abs(bx) - GOAL_W / 2) <= BALL_RADIUS + POST_RADIUS
                or abs(by - GOAL_H) <= BALL_RADIUS + POST_RADIUS
            ) and abs(bx) <= GOAL_W / 2 + 0.5 and by <= GOAL_H + 0.5
            if hit_frame:
                self.last_result_text = ("打中门框!" if self.attacker_is_player
                                         else "AI打中门框!")
            else:
                self.last_result_text = ("射偏了!" if self.attacker_is_player
                                         else "AI射偏了!")
            self._finish_shot(False)
            return
        # 2. 守门员/射手属性
        if self.attacker_is_player:
            kp = self.ai_keeper_profile if self.ai_keeper_profile else random.choice(KEEPERS)
            sp = self.striker_profile
        else:
            kp = self.keeper_profile
            sp = (self.ai_striker_profile if self.ai_striker_profile else STRIKERS[0])
        sp_power = sp.power
        sp_acc = sp.accuracy
        reaction_ok = self.keeper.dive_t > 0

        # 3. 方向判定 - 精确到格子级
        ball_cell = self._pos_to_cell(bx, by)
        keeper_cell = self._pos_to_cell(self.keeper.target_x, self.keeper.target_y)
        dir_correct = (ball_cell == keeper_cell)
        # 相邻格子(臂展覆盖)
        is_adjacent = (not dir_correct and
                       keeper_cell in CELL_ADJACENT.get(ball_cell, []))
        # 四角判定(反应属性)
        ball_is_corner = ball_cell in CORNER_CELLS

        # 4. 基础扑救概率
        if dir_correct:
            base_prob = 0.68
        elif is_adjacent:
            base_prob = 0.15  # 占位, 下面按球速+臂展重算
        else:
            base_prob = 0.02  # 完全猜错
        # 落点高度难度: 门将重心向下倒(低球)远快于向上跳(高球), 这是物理事实
        #   上排(1/2/3, 1.85m) 最难, 中排(4/5/6) 中等, 下排(7/8/9, 0.4m) 最好扑
        if by >= 1.55:
            base_prob *= 0.78
        elif by <= 0.75:
            base_prob *= 1.22

        # 5. 球速等级 + 慢速系数
        # 用"到达门线瞬间"的真实速度(空气阻力已让球衰减约13%), 而不是出球速度
        ball_speed = self.ball.speed
        if ball_speed < 19.0:
            level = "weak"
        elif ball_speed < 23.5:
            level = "medium"
        else:
            level = "strong"
        # 越慢 -> 系数越大(臂展覆盖相邻格的成功率越高)
        slow_factor = max(0.0, min(1.0, (26.0 - ball_speed) / 8.0))

        # 射手疲劳影响球质
        striker_fat = self.player_fatigue if self.attacker_is_player else self.ai_fatigue
        ball_quality = 1.0 - striker_fat * 0.03

        # 6. 属性分工判定(核心重构)
        # 反应(reflex): 扑四角远距离重力球
        # 扑救(dive): 扑非四角近距离重力球
        # 臂展(reach): 相邻格覆盖范围, 球越慢概率越高
        # 关键属性(用于失败原因提示)
        if ball_is_corner:
            key_attr_value = kp.reflex
            key_attr_name = "反应"
        else:
            key_attr_value = kp.dive
            key_attr_name = "扑救"
        need = 0.30 + sp_power * 0.028          # 力量越大, 要求的门将数值越高
        attr_score = (key_attr_value / 10.0) * ball_quality + slow_factor * 0.10
        self._key_attr_ok = attr_score >= need  # 数值是否够用
        self._key_attr_name = key_attr_name
        self._key_attr_value = key_attr_value
        self._slow_factor = slow_factor

        if dir_correct:
            save_power = (kp.reflex if ball_is_corner else kp.dive) / 10.0
            attr_type = "reflex" if ball_is_corner else "dive"
            effective_power = save_power * ball_quality
            if level == "strong" and effective_power < 0.55:
                base_prob *= 0.16
                self._break_defense = True
                attr_type = "break"
            elif level == "strong":
                base_prob *= 0.85
            elif level == "weak":
                base_prob *= 1.12
        elif is_adjacent:
            # 臂展覆盖相邻格: 臂展是主导因素(指数加成), 球速越慢整体越高
            # 慢球: 臂展10≈42% / 臂展8≈24% / 臂展6≈12% / 臂展5≈8%
            # 快球: 无论臂展都基本扑不到(<5%)
            reach_n = max(0.30, kp.reach / 10.0)
            base_prob = (0.02 + slow_factor * 0.48) * (reach_n ** 2.2)
            attr_type = "reach"
        else:
            attr_type = "none"

        if level == "strong":
            speed_factor = 0.88
        elif level == "medium":
            speed_factor = 0.95
        else:
            speed_factor = 1.0
        if is_adjacent:
            speed_factor = 1.0  # 臂展概率已由 slow_factor 完整表达

        base_prob *= speed_factor

        # 7. 属性修正(各属性独立因子, 权重按场景分配)
        reflex_factor = 0.6 + 0.04 * kp.reflex
        reach_factor = 0.6 + 0.04 * kp.reach
        dive_factor = 0.6 + 0.04 * kp.dive
        if is_adjacent:
            # 相邻格: 臂展权重最大
            attr_factor = (reflex_factor * 0.15 + reach_factor * 0.70 + dive_factor * 0.15)
        elif level == "strong" and ball_is_corner:
            # 四角重力球: 反应权重最大
            attr_factor = (reflex_factor * 0.65 + reach_factor * 0.10 + dive_factor * 0.25)
        elif level == "strong":
            # 非四角重力球: 扑救权重最大
            attr_factor = (reflex_factor * 0.20 + reach_factor * 0.10 + dive_factor * 0.70)
        else:
            attr_factor = (reflex_factor + reach_factor + dive_factor) / 3.0
        base_prob *= attr_factor

        # 射手力量越大, 门将越难挡(但收益递减, 保证力量型不会无敌)
        power_factor = max(0.80, 1.0 - (sp_power - 5) * 0.022)
        # 射手准度: 打得准的人把球送进格子边角(死角), 门将即便判断对方向
        # 也常常差那十几厘米; 打得飘的人落点随机, 平均更靠近门将够得到的区域
        place_factor = 1.0 - (sp_acc - 6) * 0.042   # 准10->0.83, 准6->1.00, 准3->1.13
        base_prob *= power_factor * place_factor

        # 反应不及
        if not reaction_ok:
            if level == "strong":
                base_prob *= 0.08
            else:
                base_prob *= 0.25

        # 抛硬币判定
        if random.random() < base_prob:
            self.last_outcome = "SAVE"
            who = "你扑出了!" if not self.attacker_is_player else "AI扑出了!"
            self.last_result_text = who
            self._finish_shot(False)
            self.shake_t = 0.35
            self.shake_amp = 7
            self.save_effect_t = 1.0
        else:
            self.last_outcome = "GOAL"
            # 扑救失败原因(门将方向对/错 + 数值是否够用)
            if True:
                pct = max(0, min(100, base_prob * 100))
                if not reaction_ok:
                    self.save_fail_reason = "反应不及(扑救动作未完成, 起跳太晚)"
                elif not dir_correct and not is_adjacent:
                    self.save_fail_reason = "方向错误(完全猜错方向)"
                elif is_adjacent:
                    # 方向相邻(臂展可覆盖范围)但没扑到 -> 臂展不足
                    self.save_fail_reason = (
                        f"臂展不足(相邻格, 臂展{kp.reach}覆盖概率{pct:.0f}%)")
                elif self._break_defense:
                    # 方向对了但被重炮破防(本质仍是对应数值不足)
                    if ball_is_corner:
                        self.save_fail_reason = (
                            f"反应速度不够(四角对方向, 反应{kp.reflex}被重炮压制)")
                    else:
                        self.save_fail_reason = (
                            f"扑救能力不足(非四角对方向, 扑救{kp.dive}被重炮压制)")
                elif not self._key_attr_ok:
                    # 方向正确, 但门将对应数值不足
                    if ball_is_corner:
                        self.save_fail_reason = (
                            f"反应速度不够(四角对方向, 反应{kp.reflex}不足, 成功率{pct:.0f}%)")
                    else:
                        self.save_fail_reason = (
                            f"扑救能力不足(非四角对方向, 扑救{kp.dive}不足, 成功率{pct:.0f}%)")
                else:
                    self.save_fail_reason = (
                        f"差之毫厘(方向对了但没挡住, 成功率{pct:.0f}%)")
            # 进球反馈
            speed = self.ball.vz
            if self._break_defense:
                who = "破防!重力轰入!" if self.attacker_is_player else "AI破防轰入!"
                self.shake_t = 0.6
                self.shake_amp = 15
                self.goal_flash = 1.0
            elif speed > 27:
                who = "重炮进球!" if self.attacker_is_player else "AI重炮进球!"
                self.shake_t = 0.5
                self.shake_amp = 12
                self.goal_flash = 0.9
            elif speed > 22:
                who = "进球!" if self.attacker_is_player else "AI进球!"
                self.shake_t = 0.35
                self.shake_amp = 8
                self.goal_flash = 0.65
            else:
                who = "轻巧推射!" if self.attacker_is_player else "AI轻推!"
                self.shake_t = 0.25
                self.shake_amp = 5
                self.goal_flash = 0.45
            self.last_result_text = who
            self._finish_shot(True)
            self.goal_effect_t = 1.5

    def _finish_shot(self, scored: bool):
        # 记录统计
        self.match_stats["total_shots"] += 1
        if self.last_ball_speed > self.match_stats["max_ball_speed"]:
            self.match_stats["max_ball_speed"] = self.last_ball_speed
        skill_used = self._shot_skill != "normal"
        # v1.06: "超大力射门"统计口径改为 到达门线速度>=25 的所有射门
        is_power = self.last_ball_speed >= 25.0
        if self.attacker_is_player:
            # 玩家射门 -> 结果归玩家; 被扑出 = AI 门将扑救 +1
            self.match_stats["player_shots"] += 1
            if scored:
                self.match_stats["player_goals"] += 1
            elif self.last_outcome == "MISS":
                self.match_stats["player_misses"] += 1
            else:                              # SAVE
                self.match_stats["ai_saves"] += 1
            if skill_used:
                self.match_stats["player_skill_uses"] += 1
            if is_power:
                self.match_stats["player_power_shots"] += 1
        else:
            # AI 射门 -> 结果归 AI; 被扑出 = 玩家门将扑救 +1
            self.match_stats["ai_shots"] += 1
            if scored:
                self.match_stats["ai_goals"] += 1
            elif self.last_outcome == "MISS":
                self.match_stats["ai_misses"] += 1
            else:                              # SAVE
                self.match_stats["player_saves"] += 1
            if skill_used:
                self.match_stats["ai_skill_uses"] += 1
            if is_power:
                self.match_stats["ai_power_shots"] += 1
        # 超大力射门进球: 手机端画面轻微震荡 + 震动反馈(v1.06 新增)
        if scored and is_power:
            self.shake_t = max(self.shake_t, 0.45)
            self.shake_amp = max(self.shake_amp, 11)
            if IS_ANDROID:
                _android_vibrate(80)
        # 记录关键事件
        event_text = ""
        if self.last_outcome == "GOAL":
            if self.last_ball_speed >= 25:
                event_text = f"R{self.round_num} {'玩家' if self.attacker_is_player else 'AI'}重炮进球 {self.last_ball_speed:.0f}m/s"
            else:
                event_text = f"R{self.round_num} {'玩家' if self.attacker_is_player else 'AI'}进球"
            # 玩家守门失球时, 事件里带上扑救失败原因
            if not self.attacker_is_player and self.save_fail_reason:
                event_text += f" [{self.save_fail_reason}]"
        elif self.last_outcome == "SAVE":
            event_text = f"R{self.round_num} {'玩家' if not self.attacker_is_player else 'AI'}扑救成功"
        elif self.last_outcome == "MISS":
            event_text = f"R{self.round_num} {'玩家' if self.attacker_is_player else 'AI'}射偏"
        if event_text:
            self.match_stats["key_events"].append(event_text)

        if self.attacker_is_player and scored:
            self.player_score += 1
        elif not self.attacker_is_player and scored:
            self.ai_score += 1
        # 疲劳系统: 大力消耗大, 轻射恢复, composure减缓疲劳
        if self.attacker_is_player:
            power = self.power_value
            sp = self.striker_profile
            is_power_shot = (self.selected_skill == "power_shot" and
                             sp.skill == "power_shot")
            if is_power_shot:
                fatigue_change = 8
            elif power > 0.7:
                fatigue_change = 4
            elif power > 0.4:
                fatigue_change = 2
            else:
                fatigue_change = -2
            # composure高=心理优势=疲劳减缓(composure10减30%, composure7减21%)
            fatigue_change *= (1.0 - sp.composure * 0.03)
            self.player_fatigue = max(0, min(10, self.player_fatigue + fatigue_change))
        else:
            ai_sp = self.ai_striker_profile if self.ai_striker_profile else random.choice(STRIKERS)
            ai_power = self.ai_target[2] if self.ai_target else 0.5
            if ai_power > 0.7:
                fatigue_change = 4
            elif ai_power > 0.4:
                fatigue_change = 2
            else:
                fatigue_change = -2
            fatigue_change *= (1.0 - ai_sp.composure * 0.03)
            self.ai_fatigue = max(0, min(10, self.ai_fatigue + fatigue_change))
        self.power_shot_active = False
        self.selected_skill = "normal"
        self.curve_cell2 = 0
        # 注意: 不要在这里清空 save_fail_reason, 否则结果界面读不到失败原因
        # (它在下一次 _resolve_outcome 开头统一清空)
        self.results_log.append((self.round_num,
                                 "玩家" if self.attacker_is_player else "AI",
                                 self.last_outcome))
        self.state = State.ROUND_RESULT
        self.result_t = 0.0

    def _early_decided(self) -> bool:
        """按点球规则判断胜负是否已提前锁定(剩余罚球已无法改变结果).

        round_phase == 0: 本轮玩家已罚、AI 还未罚 -> AI 多剩 1 球
        round_phase == 1: 本轮双方都已罚 -> 双方剩余球数相同
        """
        if self.is_overtime:
            return False                      # 突然死亡阶段不存在提前锁定
        rem_player = self.total_rounds - self.round_num   # 玩家还剩几球
        rem_ai = rem_player + (1 if self.round_phase == 0 else 0)
        if rem_player <= 0 and rem_ai <= 0:
            return False
        diff = self.player_score - self.ai_score
        # 玩家领先超过 AI 全部剩余罚球 -> 玩家锁胜; 反之 AI 锁胜
        return diff > rem_ai or -diff > rem_player

    def _advance_after_result(self):
        # 每一球之后都要检查是否已提前锁定胜负(不只是整轮结束)
        if self._early_decided():
            self.state = State.EARLY_END
            self.state_t = 0.0
            return
        if self.round_phase == 0:
            # 玩家射门刚结束, 进入AI射门(玩家守门)
            self.round_phase = 1
            self._setup_shot(player_attacker=False)
        else:
            # 本轮双方都踢完
            if self.is_overtime:
                # 加时赛(突然死亡): 一方进一方不进则结束
                if self.player_score != self.ai_score:
                    self.state = State.GAME_OVER
                    self.state_t = 0.0
                else:
                    # 继续加时
                    self._start_new_round()
            else:
                # 正常5轮制
                if self.round_num >= self.total_rounds:
                    if self.player_score == self.ai_score:
                        # 平局 -> 加时赛
                        self._start_overtime()
                    else:
                        self.state = State.GAME_OVER
                        self.state_t = 0.0
                else:
                    self._start_new_round()

    def _start_overtime(self):
        """5轮平局后进入加时赛(突然死亡)."""
        self.is_overtime = True
        self.round_num = 0
        self._start_new_round()

    # ----------------------------------------------------------------
    # 渲染
    # ----------------------------------------------------------------
    def draw(self, screen=None):
        # 自适应: 真实窗口/手机屏幕尺寸不等于 1280x800 时,
        # 先把画面画到固定尺寸画布, 最后再等比缩放贴出去(手机端必需)
        if screen is None:
            screen = self.screen
        target = screen
        if target.get_size() != (WIDTH, HEIGHT):
            screen = self._canvas
        # 屏幕震动
        ox, oy = 0, 0
        if self.shake_amp > 0 and self.shake_t > 0:
            ox = random.uniform(-self.shake_amp, self.shake_amp)
            oy = random.uniform(-self.shake_amp, self.shake_amp)

        if self.state == State.MENU:
            self._draw_menu(screen)
        elif self.state == State.HELP:
            self._draw_help(screen)
        elif self.state == State.SELECT_STRIKER:
            self._draw_select_striker(screen)
        elif self.state == State.SELECT_KEEPER:
            self._draw_select_keeper(screen)
        elif self.state in (State.READY, State.PLAYER_AIM, State.PLAYER_POWER,
                            State.BALL_FLY, State.ROUND_RESULT):
            self._draw_match(screen, ox, oy)
        elif self.state == State.EARLY_END:
            self._draw_match(screen, ox, oy)
            self._draw_early_end_popup(screen)
        elif self.state == State.GAME_OVER:
            self._draw_match(screen, ox, oy)
            self._draw_gameover(screen)

        # 全局闪光
        if self.goal_flash > 0:
            alpha = int(120 * self.goal_flash)
            screen.blit(self._dim_overlay(alpha, (255, 255, 220)), (0, 0))

        # 画布 -> 真实屏幕(等比缩放 + 居中黑边)
        if screen is not target:
            self._present(target, screen)

    def _present(self, target: pygame.Surface, canvas: pygame.Surface):
        """把 1280x800 画布等比缩放贴到真实屏幕(letterbox 居中)."""
        tw, th = target.get_size()
        # 安卓上 SDL 偶尔会给出 0 尺寸 surface, 不拦住的话下面会除零/缩放崩溃
        if tw <= 0 or th <= 0:
            return
        # _present_cap 恒为 1.0: 屏幕多大就铺多大, 绝不为了省算力把画面压小
        scale = min(tw / WIDTH, th / HEIGHT) * self._present_cap
        if scale <= 0:
            return
        dw, dh = max(1, int(WIDTH * scale)), max(1, int(HEIGHT * scale))
        # 只清黑边: 中间区域马上会被整块覆盖, 没必要每帧全屏 fill 一遍
        bx, by = (tw - dw) // 2, (th - dh) // 2
        if self._present_rect != (bx, by, dw, dh):
            target.fill((0, 0, 0))      # 尺寸变了(自适应画质调档)才整屏清, 防残留
            self._present_rect = (bx, by, dw, dh)
        else:
            top, bottom = by, th - dh - by
            left, right = bx, tw - dw - bx
            if top > 0:
                target.fill((0, 0, 0), (0, 0, tw, top))
            if bottom > 0:
                target.fill((0, 0, 0), (0, th - bottom, tw, bottom))
            if left > 0:
                target.fill((0, 0, 0), (0, top, left, dh))
            if right > 0:
                target.fill((0, 0, 0), (tw - right, top, right, dh))
        if (dw, dh) == (WIDTH, HEIGHT):
            target.blit(canvas, ((tw - dw) // 2, (th - dh) // 2))
            return
        # 性能关键: 手机上每帧都要把画布放大到 2K 级别,
        #  1) 用 scale 而不是 smoothscale(后者是双线性, 慢一个数量级)
        #  2) 复用同一块目标 surface, 避免每帧新建/销毁上百万像素的缓冲区
        if self._scaled is None or self._scaled.get_size() != (dw, dh):
            try:
                self._scaled = pygame.Surface((dw, dh), 0, canvas)
            except Exception:
                self._scaled = pygame.Surface((dw, dh))
            self._scaled = self._scaled.convert(canvas)
        if self._scale_dest_ok:
            try:
                # scale(带目标 surface) 可复用缓冲区; 老版本 pygame 不支持该参数,
                # 首次失败后永久退回两参数版本, 避免每帧抛异常
                pygame.transform.scale(canvas, (dw, dh), self._scaled)
            except Exception:
                self._scale_dest_ok = False
                self._scaled = pygame.transform.scale(canvas, (dw, dh))
        else:
            self._scaled = pygame.transform.scale(canvas, (dw, dh))
        target.blit(self._scaled, ((tw - dw) // 2, (th - dh) // 2))

    def _scale_factor(self) -> Tuple[float, float, float]:
        """真实屏幕 -> 画布 的缩放与偏移, 供鼠标/触摸坐标反算."""
        # 安卓上用窗口真实像素尺寸, 而不是 screen.get_size():
        # SCALED 模式下后者是 1280x800 的逻辑尺寸, 拿它算会把黑边算漏。
        # 桌面端窗口大小本来就等于绘制尺寸, 保持原来的算法即可。
        tw, th = (self._win_w, self._win_h) if IS_ANDROID else (0, 0)
        if tw <= 0 or th <= 0:
            try:
                tw, th = self.screen.get_size()
            except Exception:
                return 1.0, 0.0, 0.0
        if tw <= 0 or th <= 0:
            return 1.0, 0.0, 0.0
        if (tw, th) == (WIDTH, HEIGHT) and self._present_cap >= 1.0:
            return 1.0, 0.0, 0.0
        # 与 _present() 用同一个放大系数, 否则触摸点会偏移
        scale = min(tw / WIDTH, th / HEIGHT) * self._present_cap
        if scale <= 0:
            return 1.0, 0.0, 0.0
        dw, dh = WIDTH * scale, HEIGHT * scale
        return scale, (tw - dw) / 2.0, (th - dh) / 2.0

    def _to_canvas_pos(self, pos):
        """把真实屏幕(触摸)坐标换算成 1280x800 画布坐标."""
        scale, ox, oy = self._scale_factor()
        if scale == 1.0:
            return pos
        return ((pos[0] - ox) / scale, (pos[1] - oy) / scale)

    # ----- 菜单 -----
    def _draw_help(self, screen):
        """操作说明页面."""
        self._draw_gradient_bg(screen, SKY_TOP, SKY_MID)
        pygame.draw.rect(screen, GRASS_A, (0, HEIGHT * 0.7, WIDTH, HEIGHT * 0.3))
        # 标题
        title = self.font_xl.render("操作说明", True, WHITE)
        screen.blit(title, (WIDTH // 2 - title.get_width() // 2, 60))
        # 说明内容
        if IS_ANDROID:
            lines = [
                ("射门阶段", GOLD),
                ("  点击球门九宫格选射门目标", WHITE),
                ("  点击「蓄力射门」按钮开始蓄力", WHITE),
                ("  蓄力条摆动时, 点击「射门」按钮射门", WHITE),
                ("  力度越大球越快越难扑, 但准度下降可能射偏", (210, 210, 210)),
                ("", WHITE),
                ("守门阶段", BLUE),
                ("  观察左上角力度等级(弱/中/强)选择策略", WHITE),
                ("  点击球门九宫格选扑救方向", WHITE),
                ("  点击「确认扑救」按钮确认", WHITE),
                ("  弱力球: 精确扑(选对方向+高度)概率最高", (210, 210, 210)),
                ("  重力球: 赌大方向(选对左/中/右)更划算", (210, 210, 210)),
                ("", WHITE),
                ("通用", GOLD),
                ("  点击「菜单」按钮返回菜单   全程触摸操作", WHITE),
                ("  5轮平局后进入加时赛(突然死亡)", WHITE),
                ("  一方已无法追平时, 可选择继续或提前结算", WHITE),
            ]
        else:
            lines = [
                ("射门阶段", GOLD),
                ("  鼠标点击球门九宫格 / 数字键1-9 选目标", WHITE),
                ("  点击「蓄力射门」按钮 / 按空格 开始蓄力", WHITE),
                ("  蓄力条摆动时, 点击「点击射门」/ 松开空格 射门", WHITE),
                ("  力度越大球越快越难扑, 但准度下降可能射偏", (210, 210, 210)),
                ("", WHITE),
                ("守门阶段", BLUE),
                ("  观察左上角力度等级(弱/中/强)选择策略", WHITE),
                ("  鼠标点击球门九宫格 / 数字键1-9 选扑救方向", WHITE),
                ("  点击「确认扑救」按钮 / 按空格 确认", WHITE),
                ("  弱力球: 精确扑(选对方向+高度)概率最高", (210, 210, 210)),
                ("  重力球: 赌大方向(选对左/中/右)更划算", (210, 210, 210)),
                ("", WHITE),
                ("通用", GOLD),
                ("  R 重新开始   ESC 返回菜单/退出   鼠标全程可用", WHITE),
                ("  5轮平局后进入加时赛(突然死亡)", WHITE),
                ("  一方已无法追平时, 可选择继续或提前结算", WHITE),
            ]
        y = 140
        for text, color in lines:
            if text:
                t = self.font_m.render(text, True, color)
                screen.blit(t, (WIDTH // 2 - t.get_width() // 2, y))
            y += 30
        # 返回按钮
        rect = self._button_rect(WIDTH // 2, HEIGHT - 80, 200, 50)
        hover = self._point_in_rect(self.mouse_pos, rect)
        self._draw_button(screen, rect, "返回菜单", hover=hover)

    def _draw_early_end_popup(self, screen):
        """提前结束弹窗 - 用户选择继续或结算."""
        # 半透明遮罩
        screen.blit(self._dim_overlay(160), (0, 0))
        # 弹窗主体
        pw, ph = 560, 280
        px = (WIDTH - pw) // 2
        py = (HEIGHT - ph) // 2 - 20
        pygame.draw.rect(screen, PANEL, (px, py, pw, ph), border_radius=16)
        pygame.draw.rect(screen, GOLD, (px, py, pw, ph), 3, border_radius=16)
        # 标题
        title = self.font_l.render("比赛已无悬念!", True, GOLD)
        screen.blit(title, (WIDTH // 2 - title.get_width() // 2, py + 20))
        # 说明文字(注意: 本轮 AI 还没罚时, AI 实际多剩一球)
        rem_player = self.total_rounds - self.round_num
        rem_ai = rem_player + (1 if self.round_phase == 0 else 0)
        if self.player_score > self.ai_score:
            leader = "你"
            diff = self.player_score - self.ai_score
            rem = rem_ai
        else:
            leader = "AI"
            diff = self.ai_score - self.player_score
            rem = rem_player
        info = f"{leader}领先{diff}分, 对方最多还能罚{rem}球, 已无法追平"
        info_s = self.font_m.render(info, True, WHITE)
        screen.blit(info_s, (WIDTH // 2 - info_s.get_width() // 2, py + 70))
        choice = self.font_s.render("你可以选择继续完成剩余轮次, 或直接结算比赛",
                                     True, (210, 210, 210))
        screen.blit(choice, (WIDTH // 2 - choice.get_width() // 2, py + 105))
        # 两个按钮
        r1 = self._early_end_continue_rect()
        h1 = self._point_in_rect(self.mouse_pos, r1)
        self._draw_button(screen, r1, "继续比赛", hover=h1)
        r2 = self._early_end_end_rect()
        h2 = self._point_in_rect(self.mouse_pos, r2)
        self._draw_button(screen, r2, "直接结算", hover=h2)
        # 快捷键提示
        hint = self.font_xs.render("Enter=继续   E=结算", True, (160, 160, 160))
        screen.blit(hint, (WIDTH // 2 - hint.get_width() // 2, py + ph - 30))

    def _warmup(self):
        """在菜单的空闲帧把静态图层提前做好, 避免开局第一帧卡一下.

        这几张全屏图(天空/看台/草地/球网/网格)在手机上要几十毫秒,
        如果等到"开始比赛"的那一帧才做, 玩家会看到明显的一顿。
        """
        if self._warm_layers:
            return
        self._warm_frames += 1
        if self._warm_frames < 12:      # 先让菜单正常显示出来, 别拖慢启动
            return
        try:
            self._ensure_static_layers()
        except Exception:
            pass
        self._warm_layers = True

    def _draw_menu(self, screen):
        self._warmup()
        # 渐变背景
        self._draw_gradient_bg(screen, SKY_TOP, SKY_MID)
        # 草地
        pygame.draw.rect(screen, GRASS_A, (0, HEIGHT * 0.62, WIDTH, HEIGHT * 0.38))
        # 远处的球门
        gz = GOAL_Z
        # 用一个简单球门做装饰
        self._draw_distant_goal(screen, 0.0, gz)

        # 标题
        title = self.font_xl.render("3D 点球大战", True, WHITE)
        sub = self.font_l.render("PENALTY SHOOTOUT 3D", True, GOLD)
        screen.blit(title, (WIDTH // 2 - title.get_width() // 2, 110))
        screen.blit(sub, (WIDTH // 2 - sub.get_width() // 2, 180))
        # 版本号(右下角)
        ver = self.font_xs.render(f"{APP_NAME}  v{VERSION}", True, (150, 160, 150))
        screen.blit(ver, (WIDTH - ver.get_width() - 18, HEIGHT - 28))

        # 菜单选项
        items = ["开始比赛", "操作说明", "退出游戏"]
        for i, it in enumerate(items):
            sel = (i == self.menu_idx)
            rect = self._menu_item_rect(i)
            hover = self._point_in_rect(self.mouse_pos, rect)
            if sel or hover:
                # 高亮框
                pygame.draw.rect(screen, PANEL, rect, border_radius=12)
                pygame.draw.rect(screen, GOLD, rect, 3, border_radius=12)
                # 箭头
                arrow = self.font_l.render("▶", True, GOLD)
                screen.blit(arrow, (rect[0] + 20, rect[1] + 10))
            txt = self.font_l.render(it, True, GOLD if sel else HUD_FG)
            screen.blit(txt, (rect[0] + rect[2] // 2 - txt.get_width() // 2,
                              rect[1] + rect[3] // 2 - txt.get_height() // 2))

        # 底部提示
        tip_text = ("点击卡片选择   点击确认   (返回: 菜单按钮)"
                    if IS_ANDROID else
                    "鼠标点击 / ↑↓ 选择   Enter/空格/点击 确认   ESC 退出")
        tip = self.font_s.render(tip_text, True, HUD_FG)
        screen.blit(tip, (WIDTH // 2 - tip.get_width() // 2, HEIGHT - 60))

    def _draw_distant_goal(self, screen, cx, gz):
        # 简单画一个远处的球门框
        w = GOAL_W
        h = GOAL_H
        # 球门四角
        p1 = project(cx - w / 2, 0, gz)
        p2 = project(cx + w / 2, 0, gz)
        p3 = project(cx + w / 2, h, gz)
        p4 = project(cx - w / 2, h, gz)
        # 横梁立柱
        pts = [(p1[0], p1[1]), (p2[0], p2[1]), (p3[0], p3[1]), (p4[0], p4[1])]
        thickness = max(2, int(0.06 * p1[2]))
        pygame.draw.lines(screen, GOAL_POST, False,
                          [(p1[0], p1[1]), (p4[0], p4[1])], thickness)
        pygame.draw.lines(screen, GOAL_POST, False,
                          [(p2[0], p2[1]), (p3[0], p3[1])], thickness)
        pygame.draw.lines(screen, GOAL_POST, False,
                          [(p4[0], p4[1]), (p3[0], p3[1])], thickness)

    # ----- 选择射门球员 -----
    def _draw_select_striker(self, screen):
        self._draw_gradient_bg(screen, SKY_TOP, SKY_MID)
        pygame.draw.rect(screen, GRASS_A, (0, HEIGHT * 0.65, WIDTH, HEIGHT * 0.35))
        title = self.font_l.render("选择你的射门球员 (1/2)", True, WHITE)
        screen.blit(title, (WIDTH // 2 - title.get_width() // 2, 50))

        # 卡片位置统一取自 _striker_card_rect, 保证"画在哪"和"点哪"完全一致
        for i, sp in enumerate(STRIKERS):
            x, y, card_w, card_h = self._striker_card_rect(i)
            sel = (i == self.selected_striker_idx)
            screen.blit(self._cached_card(
                ("S", i, sel), card_w, card_h,
                lambda s, i=i, sp=sp, sel=sel: self._draw_player_card(
                    s, 0, 0, card_w, card_h, sp.name,
                    [("力量", sp.power), ("准度", sp.accuracy),
                     ("心理", sp.composure)],
                    sp.color, sp.skin, sp.desc, sel, "射门",
                    skill_name=sp.skill_name,
                    skill_desc=sp.skill_desc)),
                (x, y))

        tip = self.font_s.render("点卡片选中并确认   ← → 可切换", True, HUD_FG)
        screen.blit(tip, (WIDTH // 2 - tip.get_width() // 2, HEIGHT - 50))

    def _draw_select_keeper(self, screen):
        self._draw_gradient_bg(screen, SKY_TOP, SKY_MID)
        pygame.draw.rect(screen, GRASS_A, (0, HEIGHT * 0.65, WIDTH, HEIGHT * 0.35))
        title = self.font_l.render("选择你的守门员 (2/2)", True, WHITE)
        screen.blit(title, (WIDTH // 2 - title.get_width() // 2, 50))

        # 卡片位置统一取自 _keeper_card_rect, 保证"画在哪"和"点哪"完全一致
        for i, kp in enumerate(KEEPERS):
            x, y, card_w, card_h = self._keeper_card_rect(i)
            sel = (i == self.selected_keeper_idx)
            # 综合扑救力(用于判断能否挡重力球)
            save_power = (kp.reflex * 0.4 + kp.dive * 0.6) / 10.0
            sp_color = GREEN if save_power >= 0.55 else RED
            screen.blit(self._cached_card(
                ("K", i, sel), card_w, card_h,
                lambda s, i=i, kp=kp, sel=sel: self._draw_player_card(
                    s, 0, 0, card_w, card_h, kp.name,
                    [("反应", kp.reflex), ("臂展", kp.reach),
                     ("扑救", kp.dive)],
                    kp.color, kp.skin, kp.desc, sel, "守门",
                    small=True,
                    skill_name=kp.skill_name,
                    skill_desc=kp.skill_desc)),
                (x, y))
            # 在卡片底部显示综合扑救力
            sp_label = self.font_xs.render(
                f"综合扑救力: {save_power:.2f}", True, sp_color)
            screen.blit(sp_label, (x + card_w // 2 - sp_label.get_width() // 2,
                                   y + card_h - 18))
            if save_power < 0.55:
                warn = self.font_xs.render("(无法挡重力球)", True, (200, 100, 100))
                screen.blit(warn, (x + card_w // 2 - warn.get_width() // 2,
                                   y + card_h - 34))

        # 臂展机制说明
        hint = self.font_s.render(
            "臂展越长 -> 差一格(相邻格)也越容易扑到, 球速越慢效果越明显",
            True, (200, 225, 170))
        screen.blit(hint, (WIDTH // 2 - hint.get_width() // 2, HEIGHT - 82))
        tip_text = ("滑动或点击卡片选择   点击确认   (返回: 菜单按钮)"
                    if IS_ANDROID else
                    "鼠标点击卡片 / ← → 切换   Enter/空格/点击 确认   (返回: ESC)")
        tip = self.font_s.render(tip_text, True, HUD_FG)
        screen.blit(tip, (WIDTH // 2 - tip.get_width() // 2, HEIGHT - 50))

    def _draw_player_card(self, screen, x, y, w, h, name, stats, color, skin,
                          desc, sel, role, small=False,
                          skill_name="", skill_desc=""):
        # 卡片背景
        bg = PANEL_LT if sel else PANEL
        pygame.draw.rect(screen, bg, (x, y, w, h), border_radius=14)
        border_color = GOLD if sel else (90, 110, 95)
        bw = 4 if sel else 2
        pygame.draw.rect(screen, border_color, (x, y, w, h), bw, border_radius=14)

        # 角色标签
        tag = self.font_xs.render(role, True, WHITE)
        tag_w = tag.get_width() + 16
        pygame.draw.rect(screen, color, (x + w - tag_w - 8, y + 8, tag_w, 22),
                         border_radius=10)
        screen.blit(tag, (x + w - tag_w - 8 + 8, y + 10))

        # 技能标签(如果有)
        if skill_name and skill_name != "无技能":
            sk_tag = self.font_xs.render("技:" + skill_name, True, BLACK)
            sk_w = sk_tag.get_width() + 12
            pygame.draw.rect(screen, GOLD, (x + 8, y + 8, sk_w, 22),
                             border_radius=10)
            screen.blit(sk_tag, (x + 8 + 6, y + 10))

        # 球员头像(简化人物)
        avatar_cx = x + w // 2
        avatar_cy = y + (130 if small else 170)
        scale = 1.0 if not small else 0.85
        self._draw_character(screen, avatar_cx, avatar_cy, scale, color, skin, pose="stand")

        # 名字
        name_font = self.font_m if small else self.font_l
        nm = name_font.render(name, True, WHITE)
        screen.blit(nm, (x + w // 2 - nm.get_width() // 2,
                         avatar_cy + (50 if small else 70)))

        # 属性条
        bar_y = avatar_cy + (90 if small else 120)
        for i, (lbl, val) in enumerate(stats):
            by = bar_y + i * 36
            lbl_s = self.font_s.render(lbl, True, HUD_FG)
            screen.blit(lbl_s, (x + 18, by))
            # 进度条
            bar_x = x + 70
            bar_w = w - 90
            pygame.draw.rect(screen, (15, 22, 18), (bar_x, by + 4, bar_w, 14),
                             border_radius=7)
            fill_w = int(bar_w * val / 10)
            # 颜色按值
            if val >= 9:
                fc = GOLD
            elif val >= 7:
                fc = GREEN
            else:
                fc = (200, 180, 80)
            pygame.draw.rect(screen, fc, (bar_x, by + 4, fill_w, 14),
                             border_radius=7)
            val_s = self.font_xs.render(str(val), True, WHITE)
            screen.blit(val_s, (bar_x + bar_w - val_s.get_width() - 6, by + 4))

        # 技能说明(如果有)
        desc_y_start = h - 16
        if skill_desc and skill_desc != "无特殊技能":
            sk_lines = self._wrap_text("【" + skill_name + "】" + skill_desc,
                                        self.font_xs, w - 24)
            desc_y_start -= len(sk_lines) * 16 + 8
            dy2 = desc_y_start + 8
            for line in sk_lines:
                ls = self.font_xs.render(line, True, GOLD)
                screen.blit(ls, (x + 12, dy2))
                dy2 += 16
        # 描述
        desc_lines = self._wrap_text(desc, self.font_xs, w - 24)
        dy = desc_y_start - len(desc_lines) * 16
        for line in desc_lines:
            ls = self.font_xs.render(line, True, (200, 210, 200))
            screen.blit(ls, (x + 12, dy))
            dy += 16

    def _wrap_text(self, text, font, max_w):
        # 简单中文换行 - 按字符
        lines = []
        cur = ""
        for ch in text:
            test = cur + ch
            if font.size(test)[0] > max_w:
                if cur:
                    lines.append(cur)
                cur = ch
            else:
                cur = test
        if cur:
            lines.append(cur)
        return lines

    # ----- 比赛场景 -----
    def _draw_match(self, screen, ox=0, oy=0):
        # 天空 + 云朵
        # 静态图层(天空/云/看台/草地)只在第一帧渲染一次, 之后每帧直接贴
        self._ensure_static_layers()
        if (ox == 0 and oy == 0 and self._scene_cache is not None):
            screen.blit(self._scene_cache, (0, 0))   # 合成图: 一次搞定
        else:
            # 震屏时三层要各自偏移, 退回三次 blit
            screen.blit(self._bg_cache, (0, 0))
            screen.blit(self._stands_cache, (ox, oy))
            screen.blit(self._grass_cache, (ox, oy))
        # 球门
        self._draw_goal(screen, ox, oy)
        # 守门员
        self._draw_keeper(screen, ox, oy)
        # 足球
        self._draw_ball(screen, ox, oy)
        # 射手(前景)
        self._draw_striker(screen, ox, oy)
        # HUD
        self._draw_hud(screen)
        # 操作提示/瞄准UI
        if self.state in (State.PLAYER_AIM, State.PLAYER_POWER):
            self._draw_aiming_ui(screen)
        elif self.state == State.READY:
            self._draw_ready_overlay(screen)
        elif self.state == State.ROUND_RESULT:
            self._draw_result_overlay(screen)
        # 进球/扑救特效(最上层)
        if self.goal_effect_t > 0:
            self._draw_goal_effect(screen)
        if self.save_effect_t > 0:
            self._draw_save_effect(screen)

    def _draw_goal_effect(self, screen):
        """进球特效 - GOAL大字 + 粒子."""
        t = 1.0 - self.goal_effect_t / 1.5  # 0->1
        # 缩放动画: 快速放大然后稳定
        if t < 0.3:
            scale = t / 0.3  # 0->1
        else:
            scale = 1.0
        scale = max(0.1, min(1.0, scale))
        # 透明度
        alpha = int(255 * min(1.0, self.goal_effect_t / 0.5))
        # "GOAL!" 大字
        font_size = int(100 * scale)
        if font_size < 10:
            font_size = 10
        goal_text = self._big_text("GOAL!", font_size, GOLD)
        # 描边效果
        cx = WIDTH // 2
        cy = HEIGHT // 2 - 40
        for dx, dy in [(-2,0),(2,0),(0,-2),(0,2)]:
            outline = self._big_text("GOAL!", font_size, BLACK)
            screen.blit(outline, (cx - outline.get_width()//2 + dx, cy + dy))
        screen.blit(goal_text, (cx - goal_text.get_width()//2, cy))
        # 球速信息
        if self.last_ball_speed > 0:
            sp = self.striker_profile if self.attacker_is_player else (
                self.ai_striker_profile if self.ai_striker_profile else self.striker_profile)
            info = f"{sp.name}  {self.last_ball_speed:.0f} m/s"
            info_s = self.font_m.render(info, True, WHITE)
            screen.blit(info_s, (cx - info_s.get_width()//2, cy + font_size + 10))
        # 粒子爆炸效果
        num_particles = 12
        for i in range(num_particles):
            ang = i * 2 * math.pi / num_particles + t * 3
            dist = 50 + t * 200
            px = cx + math.cos(ang) * dist
            py = cy + math.sin(ang) * dist * 0.6
            pr = max(2, int(8 * (1 - t)))
            p_alpha = int(200 * (1 - t))
            if p_alpha > 0 and pr > 0:
                s = pygame.Surface((pr*2+2, pr*2+2), pygame.SRCALPHA)
                pygame.draw.circle(s, (255, 200, 80, p_alpha),
                                   (pr+1, pr+1), pr)
                screen.blit(s, (px-pr-1, py-pr-1))

    def _draw_save_effect(self, screen):
        """扑救特效 - SAVE文字."""
        t = 1.0 - self.save_effect_t / 1.0
        alpha = int(255 * min(1.0, self.save_effect_t / 0.3))
        scale = max(0.3, min(1.0, t * 3))
        font_size = int(80 * scale)
        if font_size < 10:
            font_size = 10
        save_text = self._big_text("SAVE!", font_size, BLUE)
        cx = WIDTH // 2
        cy = HEIGHT // 2 - 40
        for dx, dy in [(-2,0),(2,0),(0,-2),(0,2)]:
            outline = self._big_text("SAVE!", font_size, BLACK)
            screen.blit(outline, (cx - outline.get_width()//2 + dx, cy + dy))
        screen.blit(save_text, (cx - save_text.get_width()//2, cy))

    def _draw_clouds(self, screen):
        """画几朵固定位置的云."""
        clouds = [
            (100, 60, 70, 22), (280, 40, 90, 26), (480, 75, 60, 20),
            (680, 50, 80, 24), (900, 65, 65, 21), (1080, 45, 75, 23),
            (1200, 80, 55, 18),
        ]
        for cx, cy, w, h in clouds:
            # 云用几个重叠的椭圆组成
            parts = [(-w*0.35, 0, h*0.85), (0, -h*0.35, h*1.0),
                     (w*0.35, 0, h*0.85), (w*0.15, h*0.15, h*0.7),
                     (-w*0.15, h*0.1, h*0.65)]
            # 阴影
            for dx, dy, r in parts:
                pygame.draw.ellipse(screen, CLOUD_SHADOW,
                    (cx + dx - r, cy + dy - r * 0.6 + 2, r * 2, r * 1.2))
            # 主体
            for dx, dy, r in parts:
                pygame.draw.ellipse(screen, CLOUD,
                    (cx + dx - r, cy + dy - r * 0.6, r * 2, r * 1.2))

    def _draw_stands(self, screen, ox=0, oy=0):
        """画远处看台和观众."""
        z = GOAL_Z + 5.5
        # 看台主体
        p1 = project(-16, 0, z)
        p2 = project(16, 0, z)
        p3 = project(16, 4.0, z)
        p4 = project(-16, 4.0, z)
        pygame.draw.polygon(screen, STAND_DARK,
                            [(p1[0]+ox, p1[1]+oy), (p2[0]+ox, p2[1]+oy),
                             (p3[0]+ox, p3[1]+oy), (p4[0]+ox, p4[1]+oy)])
        # 看台前沿
        p5 = project(-16, 0.5, z)
        p6 = project(16, 0.5, z)
        pygame.draw.line(screen, STAND_COLOR,
                         (p5[0]+ox, p5[1]+oy), (p6[0]+ox, p6[1]+oy),
                         max(2, int(0.05 * p5[2])))
        # 观众(固定位置, 避免闪烁)
        crowd_colors = [(200,200,210),(180,180,195),(220,220,230),
                        (190,190,200),(210,210,220)]
        row_count = 0
        for row in range(3):
            yy = 1.0 + row * 0.8
            for i in range(40):
                xx = -15 + i * 0.75
                p = project(xx, yy, z)
                r = max(1, int(0.03 * p[2]))
                ci = (i * 7 + row * 13) % len(crowd_colors)
                pygame.draw.circle(screen, crowd_colors[ci],
                                   (int(p[0]+ox), int(p[1]+oy)), r)
        # 广告牌(看台前)
        ad_z = GOAL_Z + 4.2
        ad_y = 0.3
        p1a = project(-14, ad_y, ad_z)
        p2a = project(14, ad_y, ad_z)
        p3a = project(14, ad_y + 0.6, ad_z)
        p4a = project(-14, ad_y + 0.6, ad_z)
        pygame.draw.polygon(screen, (250, 250, 250),
                            [(p1a[0]+ox, p1a[1]+oy), (p2a[0]+ox, p2a[1]+oy),
                             (p3a[0]+ox, p3a[1]+oy), (p4a[0]+ox, p4a[1]+oy)])
        pygame.draw.polygon(screen, (200, 200, 210),
                            [(p1a[0]+ox, p1a[1]+oy), (p2a[0]+ox, p2a[1]+oy),
                             (p3a[0]+ox, p3a[1]+oy), (p4a[0]+ox, p4a[1]+oy)], 1)

    def _draw_gradient_bg(self, screen, top, bot):
        # 简单垂直渐变
        h = HEIGHT
        for i in range(0, h, 4):
            t = i / h
            r = int(top[0] * (1 - t) + bot[0] * t)
            g = int(top[1] * (1 - t) + bot[1] * t)
            b = int(top[2] * (1 - t) + bot[2] * t)
            pygame.draw.rect(screen, (r, g, b), (0, i, WIDTH, 4))

    def _draw_grass(self, screen, ox=0, oy=0):
        # 草地用透视网格 - 离摄像机越远越窄
        # 找到地平线y坐标(无穷远处)
        horizon_y = HEIGHT // 2 - (0 - CAM_Y) / 1000 * FOCAL + HEIGHT // 2
        # 草地起点 - 摄像机y=1.9, 草地y=0, 投影y
        _, gy_proj, _ = project(0, 0, 0.5)
        grass_top = int(gy_proj)
        if grass_top < 0:
            grass_top = 0
        if grass_top > HEIGHT:
            grass_top = HEIGHT
        # 整片草地
        pygame.draw.rect(screen, GRASS_A,
                         (0, grass_top, WIDTH, HEIGHT - grass_top))
        # 草地条纹(横条)
        for z in range(int(PENALTY_Z), int(GOAL_Z + 12), 1):
            z = float(z) + 0.0
            _, py, _ = project(0, 0, z)
            if 0 <= py <= HEIGHT:
                color = GRASS_B if int(z) % 2 == 0 else GRASS_A
                pygame.draw.line(screen, color, (0, py), (WIDTH, py), 2)
        # 草地纵线(透视)
        for x in range(-12, 13, 2):
            p1 = project(x, 0, 0.5)
            p2 = project(x, 0, GOAL_Z + 5)
            if 0 <= p1[1] <= HEIGHT + 50 and 0 <= p2[1] <= HEIGHT + 50:
                pygame.draw.line(screen, GRASS_LINE,
                                (p1[0] + ox, p1[1] + oy),
                                (p2[0] + ox, p2[1] + oy), 1)
        # 罚球区线
        self._draw_field_line(screen,
                              [(-GOAL_W / 2 - 2.5, 0, GOAL_Z - 0.3),
                               (-GOAL_W / 2 - 2.5, 0, GOAL_Z - 5),
                               (GOAL_W / 2 + 2.5, 0, GOAL_Z - 5),
                               (GOAL_W / 2 + 2.5, 0, GOAL_Z - 0.3)],
                              GRASS_LINE, 2, ox, oy)
        # 球门区线
        self._draw_field_line(screen,
                              [(-GOAL_W / 2 - 1.0, 0, GOAL_Z - 0.3),
                               (-GOAL_W / 2 - 1.0, 0, GOAL_Z - 1.8),
                               (GOAL_W / 2 + 1.0, 0, GOAL_Z - 1.8),
                               (GOAL_W / 2 + 1.0, 0, GOAL_Z - 0.3)],
                              GRASS_LINE, 2, ox, oy)
        # 点球点
        px_proj = project(0, 0.01, PENALTY_Z)
        pygame.draw.circle(screen, WHITE,
                           (int(px_proj[0] + ox), int(px_proj[1] + oy)),
                           max(2, int(0.04 * px_proj[2])))

    def _draw_field_line(self, screen, pts, color, width, ox=0, oy=0):
        proj_pts = []
        for x, y, z in pts:
            sx, sy, _ = project(x, y, z)
            proj_pts.append((sx + ox, sy + oy))
        if len(proj_pts) >= 2:
            pygame.draw.lines(screen, color, False, proj_pts, width)

    def _ensure_static_layers(self):
        """静态图层只渲染一次(天空/云/看台/草地/球网), 之后每帧直接 blit.

        这些图层原本每帧重画: 渐变 200 次 fill + 云 70 个椭圆 + 看台 120 个圆
        + 草地数十条线 + 两块全屏半透明球网 —— 在手机上占了绝大部分帧时间。
        抖动(shake)改为整体平移贴图, 视觉等价。
        """
        if self._bg_cache is not None:
            return
        bg = pygame.Surface((WIDTH, HEIGHT))
        self._draw_gradient_bg(bg, SKY_TOP, SKY_MID)
        self._draw_clouds(bg)
        self._bg_cache = bg.convert()

        stands = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        self._draw_stands(stands, 0, 0)
        self._stands_cache = stands

        grass = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        self._draw_grass(grass, 0, 0)
        self._grass_cache = grass

        # 合成图: 天空+看台+草地三层合成成一张不透明图, 每帧只 blit 一次
        # (原来三次全屏 blit, 其中两次还是带 alpha 混合的, 在手机上很贵)
        scene = pygame.Surface((WIDTH, HEIGHT))
        scene.blit(self._bg_cache, (0, 0))
        scene.blit(stands, (0, 0))
        scene.blit(grass, (0, 0))
        self._scene_cache = scene.convert()

        net = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        self._draw_net(net)
        self._net_cache = net
        # 球网只占球门那一小块, 但上面是一整张 1280x800 的半透明图 ——
        # 每帧整屏 alpha 混合很贵(实测 0.6ms/帧, 手机上要几 ms)。
        # 这里一次性量出真正有内容的包围盒, 之后只贴这一小块。
        try:
            r = net.get_bounding_rect()
            if r.width > 0 and r.height > 0:
                self._net_rect = (r.x, r.y, r.width, r.height)
                self._net_small = net.subsurface(r).copy()
        except Exception:
            pass

        grid = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        self._draw_grid_lines(grid)
        self._grid_cache = grid
        # 瞄准用的小块: 网格线 + 高亮都只画球门这一块(见 _goal_area_rect)
        gx, gy, gw, gh = self._goal_area_rect()
        self._grid_rect = (gx, gy, gw, gh)
        small = pygame.Surface((gw, gh), pygame.SRCALPHA)
        self._draw_grid_lines(small, -gx, -gy)
        self._grid_small = small
        self._hl = pygame.Surface((gw, gh), pygame.SRCALPHA)

        self._overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)

    def _draw_grid_lines(self, surf, ox=0, oy=0):
        """九宫格网格线 —— 静态, 只在构建缓存时调用一次.

        ox/oy: 缓存只画球门那一小块, 传入负的包围盒原点做坐标平移。
        """
        gz = GOAL_Z
        w, h = GOAL_W, GOAL_H
        for i in range(1, 3):
            t = i / 3.0
            x = -w / 2 + w * t
            p1 = project(x, 0, gz)
            p2 = project(x, h, gz)
            pygame.draw.line(surf, (255, 255, 255, 80),
                             (p1[0] + ox, p1[1] + oy),
                             (p2[0] + ox, p2[1] + oy), 2)
        for i in range(1, 3):
            t = i / 3.0
            y = h * t
            p1 = project(-w / 2, y, gz)
            p2 = project(w / 2, y, gz)
            pygame.draw.line(surf, (255, 255, 255, 80),
                             (p1[0] + ox, p1[1] + oy),
                             (p2[0] + ox, p2[1] + oy), 2)

    def _goal_area_rect(self):
        """球门区域的屏幕包围盒 —— 瞄准网格/高亮都只在这一小块里画。

        原来网格线和高亮都是整屏(1280x800)的 SRCALPHA 贴图, 每帧要白白混合
        上百万个全透明像素; 球门实际只占画面中间一小块, 缩小后快一个数量级。
        """
        gz = GOAL_Z
        w, h = GOAL_W, GOAL_H
        pts = [project(-w / 2, 0, gz), project(w / 2, 0, gz),
               project(-w / 2, h, gz), project(w / 2, h, gz)]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        pad = 18                      # 给高亮描边(3px)+数字留余量
        x0 = max(0, int(min(xs)) - pad)
        y0 = max(0, int(min(ys)) - pad)
        x1 = min(WIDTH, int(max(xs)) + pad + 1)
        y1 = min(HEIGHT, int(max(ys)) + pad + 1)
        return (x0, y0, max(1, x1 - x0), max(1, y1 - y0))

    def _accept_tap(self, pos):
        """触摸去重.

        SDL 收到一次触摸时, 默认会同时投递 FINGERDOWN 和"模拟的" MOUSEBUTTONDOWN,
        于是游戏把同一次点击处理了两遍: 先选中射手并立刻确认 -> 跳到选门将,
        紧接着第二次事件又在当前界面上生效 —— 表现为"点了没反应/选不了人"。

        这里把 0.35 秒内、位置几乎相同的第二次按下判为重复并丢弃。
        桌面端两次真实点击间隔一般都大于 0.35 秒, 不受影响。
        """
        try:
            now = time.time()
            px, py = float(pos[0]), float(pos[1])
        except Exception:
            return True
        lx, ly = self._last_tap_pos
        if (now - self._last_tap_t < 0.35 and
                abs(px - lx) < 60 and abs(py - ly) < 60):
            return False
        self._last_tap_t = now
        self._last_tap_pos = (px, py)
        return True

    def _cached_card(self, key, w, h, draw_fn):
        """球员卡片缓存: 卡面是静态的(只有"选中/未选中"两态), 只渲染一次."""
        s = self._card_cache.get(key)
        if s is None:
            s = pygame.Surface((w, h), pygame.SRCALPHA)
            try:
                draw_fn(s)
            except Exception:
                pass
            if len(self._card_cache) > 40:
                self._card_cache.clear()
            self._card_cache[key] = s
        return s

    def _team_number(self, size):
        """球员队号"9" —— 按字号缓存(原来每帧 SysFont + render)."""
        key = max(8, min(160, int(size)))
        s = self._num_cache.get(key)
        if s is None:
            try:
                f = pygame.font.SysFont(["arial"], key, bold=True)
            except Exception:
                f = self.font_s
            s = f.render("9", True, WHITE)
            self._num_cache[key] = s
        return s

    def _big_text(self, text, size, color):
        """GOAL!/SAVE! 之类的大字 —— 字号量化到 4 的倍数后缓存."""
        key = (text, max(10, int(size)) // 4 * 4, tuple(color))
        s = self._effect_font_cache.get(key)
        if s is None:
            try:
                f = pygame.font.SysFont(FONT_FALLBACKS, key[1], bold=True)
            except Exception:
                f = self.font_l
            s = f.render(text, True, color)
            if len(self._effect_font_cache) > 120:
                self._effect_font_cache.clear()
            self._effect_font_cache[key] = s
        return s

    def _clear_overlay(self):
        """清空并复用的全屏半透明缓冲(避免每帧新建 1280x800 的 SRCALPHA)."""
        self._ensure_static_layers()
        self._overlay.fill((0, 0, 0, 0))
        return self._overlay

    def _dim_overlay(self, alpha, color=(0, 0, 0)):
        """全屏压暗遮罩(复用缓冲)."""
        s = self._clear_overlay()
        s.fill((color[0], color[1], color[2], max(0, min(255, int(alpha)))))
        return s

    def _draw_net(self, surf, ox=0, oy=0):
        """球网(半透明面 + 网格线)—— 只在构建缓存时调用一次."""
        w, h = GOAL_W, GOAL_H
        gz = GOAL_Z
        back_z = gz + NET_DEPTH
        fl_b = project(-w / 2, 0, gz)
        fl_t = project(-w / 2, h, gz)
        fr_b = project(w / 2, 0, gz)
        fr_t = project(w / 2, h, gz)
        bl_b = project(-w / 2, 0, back_z)
        bl_t = project(-w / 2, h, back_z)
        br_b = project(w / 2, 0, back_z)
        br_t = project(w / 2, h, back_z)
        # 球网半透明
        # 顶网
        top_pts = [(fl_t[0] + ox, fl_t[1] + oy), (fr_t[0] + ox, fr_t[1] + oy),
                   (br_t[0] + ox, br_t[1] + oy), (bl_t[0] + ox, bl_t[1] + oy)]
        pygame.draw.polygon(surf, (250, 250, 255, 80), top_pts)
        # 后网
        back_pts = [(bl_t[0] + ox, bl_t[1] + oy), (br_t[0] + ox, br_t[1] + oy),
                     (br_b[0] + ox, br_b[1] + oy), (bl_b[0] + ox, bl_b[1] + oy)]
        pygame.draw.polygon(surf, (250, 250, 255, 60), back_pts)
        # 左侧网
        left_pts = [(fl_b[0] + ox, fl_b[1] + oy), (fl_t[0] + ox, fl_t[1] + oy),
                    (bl_t[0] + ox, bl_t[1] + oy), (bl_b[0] + ox, bl_b[1] + oy)]
        pygame.draw.polygon(surf, (250, 250, 255, 60), left_pts)
        # 右侧网
        right_pts = [(fr_b[0] + ox, fr_b[1] + oy), (fr_t[0] + ox, fr_t[1] + oy),
                     (br_t[0] + ox, br_t[1] + oy), (br_b[0] + ox, br_b[1] + oy)]
        pygame.draw.polygon(surf, (250, 250, 255, 60), right_pts)

        # 网格线(更精细 - 顶网+后网+侧网)
        # 顶网 - 纵向
        for i in range(1, 12):
            t = i / 12.0
            x_l = -w / 2 + w * t
            p1 = project(x_l, h, gz)
            p2 = project(x_l, h, back_z)
            pygame.draw.line(surf, (230, 230, 240, 90),
                             (p1[0] + ox, p1[1] + oy),
                             (p2[0] + ox, p2[1] + oy), 1)
        # 顶网 - 横向
        for i in range(1, 5):
            t = i / 5.0
            z_t = gz + NET_DEPTH * t
            p1 = project(-w / 2, h, z_t)
            p2 = project(w / 2, h, z_t)
            pygame.draw.line(surf, (230, 230, 240, 90),
                             (p1[0] + ox, p1[1] + oy),
                             (p2[0] + ox, p2[1] + oy), 1)
        # 后网 - 纵向
        for i in range(1, 12):
            t = i / 12.0
            x_l = -w / 2 + w * t
            p1 = project(x_l, 0, back_z)
            p2 = project(x_l, h, back_z)
            pygame.draw.line(surf, (225, 225, 235, 70),
                             (p1[0] + ox, p1[1] + oy),
                             (p2[0] + ox, p2[1] + oy), 1)
        # 后网 - 横向
        for i in range(1, 6):
            t = i / 6.0
            y_t = h * t
            p1 = project(-w / 2, y_t, back_z)
            p2 = project(w / 2, y_t, back_z)
            pygame.draw.line(surf, (225, 225, 235, 70),
                             (p1[0] + ox, p1[1] + oy),
                             (p2[0] + ox, p2[1] + oy), 1)
        # 左侧网
        for i in range(1, 5):
            t = i / 5.0
            y_t = h * t
            p1 = project(-w / 2, y_t, gz)
            p2 = project(-w / 2, y_t, back_z)
            pygame.draw.line(surf, (225, 225, 235, 60),
                             (p1[0] + ox, p1[1] + oy),
                             (p2[0] + ox, p2[1] + oy), 1)
        # 右侧网
        for i in range(1, 5):
            t = i / 5.0
            y_t = h * t
            p1 = project(w / 2, y_t, gz)
            p2 = project(w / 2, y_t, back_z)
            pygame.draw.line(surf, (225, 225, 235, 60),
                             (p1[0] + ox, p1[1] + oy),
                             (p2[0] + ox, p2[1] + oy), 1)

    def _draw_goal(self, screen, ox=0, oy=0):
        # 球门 + 球网
        w, h = GOAL_W, GOAL_H
        gz = GOAL_Z
        # 后侧球网框(深NET_DEPTH)
        back_z = gz + NET_DEPTH
        # 立柱底/顶
        fl_b = project(-w / 2, 0, gz)
        fl_t = project(-w / 2, h, gz)
        fr_b = project(w / 2, 0, gz)
        fr_t = project(w / 2, h, gz)
        # 后侧
        bl_b = project(-w / 2, 0, back_z)
        bl_t = project(-w / 2, h, back_z)
        br_b = project(w / 2, 0, back_z)
        br_t = project(w / 2, h, back_z)

        # 球网: 静态图层, 只构建一次后每帧直接贴
        # (原来每帧新建两块 1280x800 的 SRCALPHA surface, 是最大的性能瓶颈之一)
        self._ensure_static_layers()
        # 只贴球门那一小块(整屏半透明混合太贵); 拿不到小块时退回整张
        if self._net_small is not None:
            nx, ny, nw, nh = self._net_rect
            screen.blit(self._net_small, (nx + ox, ny + oy))
        else:
            screen.blit(self._net_cache, (ox, oy))

        # 立柱(白) - 带阴影
        post_w = max(3, int(0.12 * fl_b[2]))
        # 立柱阴影
        pygame.draw.line(screen, (200, 200, 210),
                         (fl_b[0] + ox + 2, fl_b[1] + oy),
                         (fl_t[0] + ox + 2, fl_t[1] + oy), post_w)
        pygame.draw.line(screen, (200, 200, 210),
                         (fr_b[0] + ox + 2, fr_b[1] + oy),
                         (fr_t[0] + ox + 2, fr_t[1] + oy), post_w)
        # 左立柱
        pygame.draw.line(screen, GOAL_POST,
                         (fl_b[0] + ox, fl_b[1] + oy),
                         (fl_t[0] + ox, fl_t[1] + oy), post_w)
        # 右立柱
        pygame.draw.line(screen, GOAL_POST,
                         (fr_b[0] + ox, fr_b[1] + oy),
                         (fr_t[0] + ox, fr_t[1] + oy), post_w)
        # 横梁
        pygame.draw.line(screen, GOAL_POST,
                         (fl_t[0] + ox, fl_t[1] + oy),
                         (fr_t[0] + ox, fr_t[1] + oy), post_w)
        # 立柱底座
        base_r = max(2, post_w // 2)
        pygame.draw.circle(screen, GOAL_POST,
                           (int(fl_b[0] + ox), int(fl_b[1] + oy)), base_r)
        pygame.draw.circle(screen, GOAL_POST,
                           (int(fr_b[0] + ox), int(fr_b[1] + oy)), base_r)

    def _draw_keeper(self, screen, ox=0, oy=0):
        kp = self.keeper
        # 守门员位置 - 守门员站在球门前
        kx = kp.x
        ky = kp.y  # y为扑救高度(扑到空中)
        kz = kp.z
        # 用扑救动画来表现
        diving = kp.diving
        # dive_t 现在是真实秒数, 归一化到 0~1 供姿态插值(0.42s ≈ 到位时间)
        prog = min(1.0, max(0.0, kp.dive_t / 0.42))
        # 玩家守门用玩家所选守门员颜色, AI守门用AI选定守门员颜色
        if self.attacker_is_player:
            ai_kp = self.ai_keeper_profile if self.ai_keeper_profile else random.choice(KEEPERS)
            keeper_color = ai_kp.color
            skin = ai_kp.skin
        else:
            keeper_color = self.keeper_profile.color
            skin = self.keeper_profile.skin

        # 球员投影
        self._draw_shadow(screen, kx, 0, kz, ox, oy, radius=0.6)
        # 球员
        self._draw_character_3d(screen, kx, ky, kz, keeper_color, skin,
                                pose="dive" if diving else "stand",
                                dive_dir=kp.dive_dir, dive_high=kp.dive_high,
                                prog=prog, ox=ox, oy=oy, is_keeper=True)

    def _draw_ball(self, screen, ox=0, oy=0):
        b = self.ball
        if not b.active and self.state not in (State.PLAYER_AIM, State.PLAYER_POWER,
                                                State.READY, State.BALL_FLY,
                                                State.ROUND_RESULT):
            return
        # 阴影(贴地) - 先画, 在轨迹之下
        self._draw_shadow(screen, b.x, 0, b.z, ox, oy, radius=0.13)
        # 轨迹线 + 拖尾
        if b.active and len(b.trail) >= 2:
            trail_pts = b.trail + [(b.x, b.y, b.z)]
            pts_2d = []
            for tx, ty, tz in trail_pts:
                sx, sy, sc = project(tx, ty, tz)
                pts_2d.append((sx + ox, sy + oy, sc))
            # 画渐变轨迹线(黄白色) —— 复用全屏缓冲, 不再每帧新建
            trail_surf = self._clear_overlay()
            for i in range(len(pts_2d) - 1):
                t = (i + 1) / len(pts_2d)
                alpha = int(220 * t)
                w = max(2, int(5 * t))
                col = (255, 235, 130, alpha)
                x1, y1, _ = pts_2d[i]
                x2, y2, _ = pts_2d[i + 1]
                pygame.draw.line(trail_surf, col, (x1, y1), (x2, y2), w)
            screen.blit(trail_surf, (0, 0))
            # 拖尾粒子(发光点)
            for i, (px, py, psc) in enumerate(pts_2d[:-1]):
                t = (i + 1) / len(pts_2d)
                r = max(3, int(0.10 * psc * t))
                if 0 < r < 60:
                    s = pygame.Surface((r * 2 + 4, r * 2 + 4), pygame.SRCALPHA)
                    # 外层光晕
                    pygame.draw.circle(s, (255, 235, 130, int(60 * t)),
                                       (r + 2, r + 2), r + 2)
                    # 内层亮点
                    pygame.draw.circle(s, (255, 255, 255, int(160 * t)),
                                       (r + 2, r + 2), max(1, r - 1))
                    screen.blit(s, (px - r - 2, py - r - 2))
        # 球
        sx, sy, sc = project(b.x, b.y, b.z)
        r = max(4, int(0.13 * sc))
        # 球身(带渐变高光)
        pygame.draw.circle(screen, (200, 200, 205),
                           (int(sx + ox + 1), int(sy + oy + 1)), r)  # 阴影边
        pygame.draw.circle(screen, BALL_COLOR,
                           (int(sx + ox), int(sy + oy)), r)
        # 高光
        hl_r = max(1, int(r * 0.35))
        pygame.draw.circle(screen, (255, 255, 255),
                           (int(sx + ox - r * 0.3), int(sy + oy - r * 0.3)), hl_r)
        # 黑色五边形(旋转)
        spin = b.spin
        for i in range(5):
            ang = spin + i * (2 * math.pi / 5)
            px = sx + math.cos(ang) * r * 0.55
            py = sy + math.sin(ang) * r * 0.55
            pr = max(1, int(r * 0.22))
            pygame.draw.circle(screen, BALL_SEAM,
                               (int(px + ox), int(py + oy)), pr)
        # 边框
        pygame.draw.circle(screen, (180, 180, 190),
                           (int(sx + ox), int(sy + oy)), r, 1)

    def _draw_striker(self, screen, ox=0, oy=0):
        st = self.striker
        # 玩家射门用玩家选的射手属性, AI射门用AI选定的射手属性
        if self.attacker_is_player:
            sp = self.striker_profile
        else:
            sp = self.ai_striker_profile if self.ai_striker_profile else random.choice(STRIKERS)
        # 射手颜色
        if self.attacker_is_player:
            color = sp.color
            skin = sp.skin
        else:
            color = sp.color  # 用 AI 选定射手的颜色
            skin = sp.skin
        # 阴影
        self._draw_shadow(screen, st.x, 0, st.z, ox, oy, radius=0.5)
        # 球员
        pose = "kick" if st.kicked else ("run" if self.state in (State.PLAYER_AIM, State.PLAYER_POWER) else "stand")
        self._draw_character_3d(screen, st.x, 0, st.z, color, skin,
                                pose=pose, prog=st.run_t, ox=ox, oy=oy)

    def _draw_shadow(self, screen, x, y, z, ox, oy, radius=0.4):
        """柔和阴影 - 多层渐变."""
        sx, sy, sc = project(x, 0, z)
        r = max(2, int(radius * sc))
        s = pygame.Surface((r * 2 + 8, r + 8), pygame.SRCALPHA)
        # 外层柔光
        pygame.draw.ellipse(s, (20, 40, 25, 50), (0, 0, r * 2 + 8, r + 8))
        # 中层
        pygame.draw.ellipse(s, (20, 40, 25, 90), (4, 2, r * 2, r))
        # 内层深色
        pygame.draw.ellipse(s, (15, 30, 20, 130), (6, 3, r * 2 - 4, r - 2))
        screen.blit(s, (sx - r - 4 + ox, sy - r // 2 + oy))

    def _draw_character_3d(self, screen, x, y, z, color, skin, pose="stand",
                           dive_dir=0, dive_high=False, prog=0.0,
                           ox=0, oy=0, is_keeper=False):
        """在3D位置画一个简化人物. pose: stand/run/kick/dive."""
        sx, sy, sc = project(x, y, z)
        # 人物高度1.8m -> 缩放
        h_px = 1.8 * sc * 0.55  # 视觉调整
        w_px = 0.6 * sc * 0.55
        if h_px < 8:
            return  # 太远不画

        # 疲劳影响姿势 - 疲劳高时身体前倾(头部下垂)
        fatigue = 0
        if not is_keeper:
            if self.attacker_is_player:
                fatigue = self.player_fatigue
            else:
                fatigue = self.ai_fatigue
        fatigue_lean = fatigue * 0.02  # 疲劳10->头部下移0.2*h_px

        # 投影点 -> 各部位
        if pose == "dive":
            # 扑救姿态: 横向/纵向
            if dive_high:
                # 高空扑救 - 身体斜向上
                head_y = sy - h_px * 0.6
                body_y = sy - h_px * 0.3
                leg_y = sy
                # 横向偏移
                dx = dive_dir * w_px * 1.5 * prog
                self._draw_humanoid(screen, sx + dx, head_y, body_y, leg_y,
                                    w_px, color, skin, pose="dive_h",
                                    dive_dir=dive_dir, ox=ox, oy=oy)
            else:
                # 低空/地面扑救
                head_y = sy - h_px * 0.35
                body_y = sy - h_px * 0.15
                leg_y = sy
                dx = dive_dir * w_px * 1.5 * prog
                self._draw_humanoid(screen, sx + dx, head_y, body_y, leg_y,
                                    w_px, color, skin, pose="dive_l",
                                    dive_dir=dive_dir, ox=ox, oy=oy)
        elif pose == "kick":
            # 踢球姿势 - 疲劳影响姿势(头部下垂)
            self._draw_humanoid(screen, sx, sy - h_px * 0.85 + fatigue_lean * h_px,
                                sy - h_px * 0.4 + fatigue_lean * h_px * 0.5, sy,
                                w_px, color, skin, pose="kick",
                                prog=prog, ox=ox, oy=oy, fatigue=fatigue)
        elif pose == "run":
            self._draw_humanoid(screen, sx, sy - h_px * 0.85 + fatigue_lean * h_px,
                                sy - h_px * 0.4 + fatigue_lean * h_px * 0.5, sy,
                                w_px, color, skin, pose="run",
                                prog=prog, ox=ox, oy=oy, fatigue=fatigue)
        else:
            self._draw_humanoid(screen, sx, sy - h_px * 0.85 + fatigue_lean * h_px,
                                sy - h_px * 0.4 + fatigue_lean * h_px * 0.5, sy,
                                w_px, color, skin, pose="stand",
                                ox=ox, oy=oy, fatigue=fatigue)

    def _draw_humanoid(self, screen, cx, head_y, body_y, leg_y, w,
                       color, skin, pose="stand", dive_dir=0,
                       prog=0.0, ox=0, oy=0, fatigue=0):
        """画精细人物 - 锥形躯干/圆角四肢/头发/面部. fatigue影响表情和汗水."""
        cx_i = int(cx + ox)
        # === 头部 ===
        head_r = max(3, int(w * 0.32))
        hy = int(head_y + oy)
        # 头发(深色弧形)
        hair_color = (40, 30, 25)
        pygame.draw.circle(screen, hair_color, (cx_i, hy - head_r // 3),
                           head_r + 1)
        # 头部阴影
        shadow_col = (max(0, skin[0]-25), max(0, skin[1]-25), max(0, skin[2]-25))
        pygame.draw.circle(screen, shadow_col, (cx_i + 1, hy + 1), head_r)
        # 头部主体
        pygame.draw.circle(screen, skin, (cx_i, hy), head_r)
        # 头部高光
        hl_col = (min(255, skin[0]+25), min(255, skin[1]+25), min(255, skin[2]+25))
        pygame.draw.circle(screen, hl_col,
                           (cx_i - int(head_r * 0.3), hy - int(head_r * 0.3)),
                           max(1, int(head_r * 0.35)))
        # 描边
        pygame.draw.circle(screen, (160, 130, 100), (cx_i, hy), head_r, 1)

        # === 面部 ===
        eye_r = max(1, int(head_r * 0.14))
        eye_off = head_r * 0.38
        eye_y = hy + head_r * 0.05
        if fatigue >= 6:
            pygame.draw.line(screen, (35, 25, 15),
                             (cx_i - int(eye_off) - 2, int(eye_y)),
                             (cx_i - int(eye_off) + 2, int(eye_y)), 2)
            pygame.draw.line(screen, (35, 25, 15),
                             (cx_i + int(eye_off) - 2, int(eye_y)),
                             (cx_i + int(eye_off) + 2, int(eye_y)), 2)
        else:
            pygame.draw.circle(screen, (35, 25, 15),
                               (cx_i - int(eye_off), int(eye_y)), eye_r)
            pygame.draw.circle(screen, (35, 25, 15),
                               (cx_i + int(eye_off), int(eye_y)), eye_r)
        # 嘴
        mouth_y = hy + head_r * 0.5
        if fatigue >= 7:
            # 疲惫张嘴
            pygame.draw.arc(screen, (60, 30, 20),
                            (cx_i - head_r // 3, int(mouth_y) - 2,
                             head_r * 2 // 3, 5), math.pi, 2 * math.pi, 1)
        else:
            pygame.draw.line(screen, (60, 30, 20),
                             (cx_i - 2, int(mouth_y)),
                             (cx_i + 2, int(mouth_y)), 1)

        # === 颈部 ===
        neck_w = max(2, int(w * 0.15))
        neck_h = max(3, int((body_y - head_y) * 0.15))
        neck_col = (max(0, skin[0]-10), max(0, skin[1]-10), max(0, skin[2]-10))
        pygame.draw.rect(screen, neck_col,
                         (cx_i - neck_w // 2, int(head_y + oy) + head_r - 1,
                          neck_w, neck_h), border_radius=2)

        # === 躯干(锥形) ===
        body_h = max(4, (leg_y - head_y) * 0.55)
        body_w = w * 0.7
        shoulder_w = body_w * 1.1
        waist_w = body_w * 0.85
        by = int(body_y + oy)
        # 锥形多边形
        torso_pts = [
            (cx_i - shoulder_w / 2, by),
            (cx_i + shoulder_w / 2, by),
            (cx_i + waist_w / 2, by + body_h),
            (cx_i - waist_w / 2, by + body_h),
        ]
        pygame.draw.polygon(screen, color, torso_pts)
        # 右侧阴影
        dark_c = (max(0, color[0]-35), max(0, color[1]-35), max(0, color[2]-35))
        shadow_pts = [
            (cx_i + shoulder_w * 0.15, by),
            (cx_i + shoulder_w / 2, by),
            (cx_i + waist_w / 2, by + body_h),
            (cx_i + waist_w * 0.15, by + body_h),
        ]
        pygame.draw.polygon(screen, dark_c, shadow_pts)
        # 左侧高光
        light_c = (min(255, color[0]+25), min(255, color[1]+25), min(255, color[2]+25))
        light_pts = [
            (cx_i - shoulder_w / 2, by),
            (cx_i - shoulder_w * 0.15, by),
            (cx_i - waist_w * 0.15, by + body_h),
            (cx_i - waist_w / 2, by + body_h),
        ]
        pygame.draw.polygon(screen, light_c, light_pts)
        # 队号(原来每帧 SysFont + render, 很贵 -> 按字号缓存)
        num = self._team_number(max(8, int(body_w * 0.35)))
        screen.blit(num, (cx_i - num.get_width() // 2,
                          by + int(body_h * 0.3) - num.get_height() // 2))

        # === 汗水(疲劳可视化) ===
        if fatigue >= 5:
            sweat_n = min(3, int(fatigue) - 4)
            for i in range(sweat_n):
                sx2 = cx_i + (i - 1) * head_r * 0.5
                sy2 = hy - head_r - 4 - i * 3
                pygame.draw.circle(screen, (100, 180, 240),
                                   (int(sx2), int(sy2)),
                                   max(1, int(head_r * 0.18)))

        # === 四肢(圆角粗线) ===
        leg_w = max(3, int(w * 0.16))
        arm_w = max(2, int(w * 0.12))
        leg_col = (35, 35, 55)
        ly = int(leg_y + oy)
        leg_top_y = by + int(body_h * 0.9)
        leg_len = max(4, ly - leg_top_y)
        arm_top_y = by + int(body_h * 0.1)
        arm_len = max(4, int(body_h * 0.55))

        if pose == "stand":
            # 双腿(直线)
            pygame.draw.line(screen, leg_col,
                             (cx_i - int(shoulder_w * 0.2), leg_top_y),
                             (cx_i - int(shoulder_w * 0.25), ly), leg_w)
            pygame.draw.line(screen, leg_col,
                             (cx_i + int(shoulder_w * 0.2), leg_top_y),
                             (cx_i + int(shoulder_w * 0.25), ly), leg_w)
            # 双臂(下垂)
            pygame.draw.line(screen, color,
                             (cx_i - int(shoulder_w * 0.45), arm_top_y),
                             (cx_i - int(shoulder_w * 0.5), arm_top_y + arm_len), arm_w)
            pygame.draw.line(screen, color,
                             (cx_i + int(shoulder_w * 0.45), arm_top_y),
                             (cx_i + int(shoulder_w * 0.5), arm_top_y + arm_len), arm_w)
        elif pose == "run":
            swing = math.sin(prog * math.pi) * 0.25
            # 腿前后摆
            pygame.draw.line(screen, leg_col,
                             (cx_i - int(shoulder_w * 0.2), leg_top_y),
                             (cx_i - int(shoulder_w * (0.2 + swing * 2)), ly), leg_w)
            pygame.draw.line(screen, leg_col,
                             (cx_i + int(shoulder_w * 0.2), leg_top_y),
                             (cx_i + int(shoulder_w * (0.2 + swing * 2)), ly), leg_w)
            # 手臂前后摆
            a_swing = -swing
            pygame.draw.line(screen, color,
                             (cx_i - int(shoulder_w * 0.45), arm_top_y),
                             (cx_i - int(shoulder_w * (0.45 + a_swing * 2)),
                              arm_top_y + arm_len), arm_w)
            pygame.draw.line(screen, color,
                             (cx_i + int(shoulder_w * 0.45), arm_top_y),
                             (cx_i + int(shoulder_w * (0.45 + a_swing * 2)),
                              arm_top_y + arm_len), arm_w)
        elif pose == "kick":
            # 支撑腿
            pygame.draw.line(screen, leg_col,
                             (cx_i - int(shoulder_w * 0.2), leg_top_y),
                             (cx_i - int(shoulder_w * 0.25), ly), leg_w)
            # 踢球腿(前伸)
            kick_ext = math.sin(prog * math.pi) * shoulder_w * 0.8
            kick_y = leg_top_y - int(body_h * 0.15)
            pygame.draw.line(screen, leg_col,
                             (cx_i, kick_y),
                             (cx_i + int(kick_ext), kick_y - int(leg_len * 0.3)), leg_w + 1)
            # 手臂张开
            pygame.draw.line(screen, color,
                             (cx_i - int(shoulder_w * 0.45), arm_top_y),
                             (cx_i - int(shoulder_w * 0.6), arm_top_y + int(arm_len * 0.7)), arm_w)
            pygame.draw.line(screen, color,
                             (cx_i + int(shoulder_w * 0.45), arm_top_y),
                             (cx_i + int(shoulder_w * 0.6), arm_top_y + int(arm_len * 0.7)), arm_w)
        elif pose == "dive_h":
            # 高空扑救 - 身体斜向上, dive_dir控制左右
            body_len = body_h * 0.9
            # 身体末端(头部)
            end_x = cx + dive_dir * body_len * 0.6
            end_y = body_y - body_len * 0.7  # 向上
            pygame.draw.line(screen, color,
                             (cx + ox, body_y + oy),
                             (end_x + ox, end_y + oy),
                             max(3, int(body_w * 0.5)))
            # 双手向目标方向伸
            arm_len = body_h * 0.7
            hand_x = cx + dive_dir * arm_len * prog * 1.2
            hand_y = body_y - arm_len * 0.6 * prog
            pygame.draw.line(screen, skin,
                             (cx + ox, body_y + oy),
                             (hand_x + ox, hand_y + oy), arm_w)
            # 头在身体末端
            pygame.draw.circle(screen, skin,
                               (int(end_x + ox), int(end_y + oy)),
                               head_r)
            # 腿(向反方向)
            pygame.draw.line(screen, (40, 40, 60),
                             (cx + ox, body_y + oy),
                             (cx - dive_dir * body_w * 0.3 + ox,
                              leg_y + oy), leg_w)
        elif pose == "dive_l":
            # 低空扑救 - 身体横向, dive_dir控制左右
            body_len = body_h * 0.9
            end_x = cx + dive_dir * body_len * 0.7
            end_y = body_y - body_len * 0.2  # 略向上
            pygame.draw.line(screen, color,
                             (cx + ox, body_y + oy),
                             (end_x + ox, end_y + oy),
                             max(3, int(body_w * 0.5)))
            # 手伸
            arm_len = body_h * 0.6
            hand_x = cx + dive_dir * arm_len * prog * 1.5
            hand_y = body_y - arm_len * 0.2 * prog
            pygame.draw.line(screen, skin,
                             (cx + ox, body_y + oy),
                             (hand_x + ox, hand_y + oy), arm_w)
            # 头
            pygame.draw.circle(screen, skin,
                               (int(end_x + ox), int(end_y + oy)), head_r)
            # 腿
            pygame.draw.line(screen, (40, 40, 60),
                             (cx + ox, body_y + oy),
                             (cx - dive_dir * body_w * 0.3 + ox,
                              leg_y + oy), leg_w)

    def _draw_character(self, screen, cx, cy, scale, color, skin, pose="stand"):
        """简化版人物(用于卡片)."""
        h = 140 * scale
        w = 50 * scale
        head_r = int(20 * scale)
        # 头
        pygame.draw.circle(screen, skin, (cx, int(cy - h * 0.4)), head_r)
        pygame.draw.circle(screen, (180, 140, 110),
                           (cx, int(cy - h * 0.4)), head_r, 1)
        # 身
        body_h = h * 0.4
        body_w = w * 0.7
        body_rect = pygame.Rect(cx - body_w / 2, cy - h * 0.3,
                                body_w, body_h)
        pygame.draw.rect(screen, color, body_rect, border_radius=int(body_w * 0.2))
        # 腿
        leg_w = w * 0.18
        pygame.draw.rect(screen, (40, 40, 60),
                         (cx - body_w * 0.25, cy + h * 0.1,
                          leg_w, h * 0.3), border_radius=3)
        pygame.draw.rect(screen, (40, 40, 60),
                         (cx + body_w * 0.25 - leg_w, cy + h * 0.1,
                          leg_w, h * 0.3), border_radius=3)
        # 手臂
        arm_w = w * 0.13
        pygame.draw.rect(screen, color,
                         (cx - body_w * 0.55, cy - h * 0.25,
                          arm_w, h * 0.25), border_radius=3)
        pygame.draw.rect(screen, color,
                         (cx + body_w * 0.55 - arm_w, cy - h * 0.25,
                          arm_w, h * 0.25), border_radius=3)

    # ----- HUD -----
    def _draw_hud(self, screen):
        # 顶部信息栏
        hud_h = 80
        pygame.draw.rect(screen, HUD_BG, (0, 0, WIDTH, hud_h))
        pygame.draw.line(screen, GOLD, (0, hud_h), (WIDTH, hud_h), 2)
        # 比分(加时赛时标注)
        if self.is_overtime:
            score_str = f"加时赛  玩家 {self.player_score} : {self.ai_score} AI"
        else:
            score_str = f"玩家  {self.player_score}  :  {self.ai_score}  AI"
        score_txt = self.font_l.render(score_str, True, HUD_FG)
        screen.blit(score_txt, (WIDTH // 2 - score_txt.get_width() // 2, 16))
        # 轮次
        if self.is_overtime:
            round_txt = self.font_m.render(f"加时第 {self.round_num} 轮", True, RED)
        else:
            round_txt = self.font_m.render(
                f"第 {self.round_num} / {self.total_rounds} 轮", True, GOLD)
        screen.blit(round_txt, (20, 24))
        # 当前阶段
        if self.attacker_is_player:
            phase = "玩家射门"
            pc = GREEN
        else:
            phase = "玩家守门"
            pc = BLUE
        ph = self.font_m.render(phase, True, pc)
        screen.blit(ph, (WIDTH - ph.get_width() - 20, 24))
        # 球员名 + 疲劳度
        sp_name = self.font_s.render(
            f"射手: {self.striker_profile.name}", True, HUD_FG)
        screen.blit(sp_name, (20, 56))
        # 疲劳条(玩家)
        fat_label = self.font_xs.render(f"疲劳", True, HUD_FG)
        screen.blit(fat_label, (20 + sp_name.get_width() + 8, 59))
        fat_bar_x = 20 + sp_name.get_width() + 44
        pygame.draw.rect(screen, (40, 50, 45), (fat_bar_x, 60, 60, 10),
                         border_radius=3)
        fat_fill = int(60 * self.player_fatigue / 10)
        fat_color = RED if self.player_fatigue >= 6 else (GOLD if self.player_fatigue >= 4 else GREEN)
        pygame.draw.rect(screen, fat_color, (fat_bar_x, 60, fat_fill, 10),
                         border_radius=3)

        kp_name = self.font_s.render(
            f"守门: {self.keeper_profile.name}", True, HUD_FG)
        screen.blit(kp_name, (WIDTH - kp_name.get_width() - 20, 56))
        # AI疲劳条
        ai_fat_label = self.font_xs.render(f"AI疲劳", True, HUD_FG)
        ai_fat_x = WIDTH - kp_name.get_width() - 20 - 60 - 8
        screen.blit(ai_fat_label, (ai_fat_x - 40, 59))
        pygame.draw.rect(screen, (40, 50, 45), (ai_fat_x, 60, 60, 10),
                         border_radius=3)
        ai_fat_fill = int(60 * self.ai_fatigue / 10)
        ai_fat_color = RED if self.ai_fatigue >= 6 else (GOLD if self.ai_fatigue >= 4 else GREEN)
        pygame.draw.rect(screen, ai_fat_color, (ai_fat_x, 60, ai_fat_fill, 10),
                         border_radius=3)

        # 球速可视化(球飞行时显示)
        if self.state == State.BALL_FLY and self.last_ball_speed > 0:
            speed_txt = self.font_l.render(
                f"{self.last_ball_speed:.0f} m/s", True, GOLD)
            sx = WIDTH // 2 - speed_txt.get_width() // 2
            sy = hud_h + 10
            # 背景条
            bg = pygame.Surface((speed_txt.get_width() + 24, speed_txt.get_height() + 8),
                                pygame.SRCALPHA)
            bg.fill((16, 28, 22, 200))
            screen.blit(bg, (sx - 12, sy - 4))
            screen.blit(speed_txt, (sx, sy))

    # ----- READY 阶段 -----
    def _draw_ready_overlay(self, screen):
        # 半透明覆盖
        alpha = min(180, int(self.intro_t * 400))
        screen.blit(self._dim_overlay(alpha), (0, 0))
        # 文字
        if self.attacker_is_player:
            big = self.font_xl.render("你来射门!", True, GREEN)
            sub = self.font_m.render("选好角度 + 蓄力 → 一击制胜", True, WHITE)
        else:
            big = self.font_xl.render("你来守门!", True, BLUE)
            sub = self.font_m.render("预判方向 → 扑救!", True, WHITE)
        screen.blit(big, (WIDTH // 2 - big.get_width() // 2, HEIGHT // 2 - 80))
        screen.blit(sub, (WIDTH // 2 - sub.get_width() // 2, HEIGHT // 2))
        # "继续"按钮
        rect = self._ready_button_rect()
        hover = self._point_in_rect(self.mouse_pos, rect)
        self._draw_button(screen, rect, "点击继续", hover=hover)

    # ----- 瞄准UI -----
    def _skill_button_rect(self):
        """技能按钮矩形(右上角)."""
        return self._button_rect(WIDTH - 160, 110, 280, 44)

    def _draw_skill_button(self, screen, sp):
        """绘制技能选择按钮 + 充能进度条."""
        rect = self._skill_button_rect()
        hover = self._point_in_rect(self.mouse_pos, rect)
        # 弧线球不需要充能
        if sp.skill == "curve":
            if self.selected_skill == "curve":
                if self.curve_cell2 > 0:
                    self._draw_button(screen, rect, "弧线球[双格已选]", hover=hover, active=True)
                elif self.curve_cell2 == -1:
                    self._draw_button(screen, rect, "弧线球[选第二格]", hover=hover, active=True)
                else:
                    self._draw_button(screen, rect, "弧线球[已激活]", hover=hover, active=True)
            else:
                self._draw_button(screen, rect, "弧线球(无限)", hover=hover)
            # 说明
            desc_lines = self._wrap_text(sp.skill_desc, self.font_xs, rect[2])
            dy = rect[1] + rect[3] + 6
            for line in desc_lines[:2]:
                ls = self.font_xs.render(line, True, (200, 180, 220))
                screen.blit(ls, (rect[0] + rect[2] // 2 - ls.get_width() // 2, dy))
                dy += 14
            return
        # 充能阈值
        threshold = 80 if sp.skill == "precision" else 60
        charged = self.player_skill_charge >= threshold
        if sp.skill == "precision":
            if self.precision_shot_used:
                self._draw_button(screen, rect, "超精准(已用)", hover=False)
            elif self.selected_skill == "precision":
                self._draw_button(screen, rect, "超精准[已选]", hover=hover, active=True)
            elif charged:
                self._draw_button(screen, rect, "超精准射门(就绪)", hover=hover)
            else:
                self._draw_button(screen, rect, "超精准(充能中)", hover=False)
        elif sp.skill == "power_shot":
            if self.selected_skill == "power_shot":
                self._draw_button(screen, rect, "超大力[已选]", hover=hover, active=True)
            elif charged:
                self._draw_button(screen, rect, "超大力射门(就绪)", hover=hover)
            else:
                self._draw_button(screen, rect, "超大力(充能中)", hover=False)
        # 充能进度条(按钮下方)
        bar_x = rect[0]
        bar_y = rect[1] + rect[3] + 2
        bar_w = rect[2]
        bar_h = 8
        pygame.draw.rect(screen, (30, 40, 35), (bar_x, bar_y, bar_w, bar_h),
                         border_radius=3)
        fill_w = int(bar_w * self.player_skill_charge / 100)
        bar_color = GREEN if charged else (GOLD if self.player_skill_charge >= threshold * 0.5 else RED)
        pygame.draw.rect(screen, bar_color, (bar_x, bar_y, fill_w, bar_h),
                         border_radius=3)
        pct = self.font_xs.render(f"{int(self.player_skill_charge)}%", True, WHITE)
        screen.blit(pct, (bar_x + bar_w - pct.get_width() - 4, bar_y - 16))
        desc_lines = self._wrap_text(sp.skill_desc, self.font_xs, bar_w)
        dy = bar_y + bar_h + 4
        for line in desc_lines[:2]:
            ls = self.font_xs.render(line, True, (180, 190, 180))
            screen.blit(ls, (bar_x + bar_w // 2 - ls.get_width() // 2, dy))
            dy += 14

    def _draw_aiming_ui(self, screen):
        if self.attacker_is_player:
            # 射门 - 在球门上画九宫格瞄准准星
            self._draw_aim_grid(screen, "shoot")
            # 力度条
            if self.state == State.PLAYER_POWER:
                self._draw_power_bar(screen)
                # 射门按钮(点击射门)
                rect = self._shoot_button_rect()
                hover = self._point_in_rect(self.mouse_pos, rect)
                self._draw_button(screen, rect, "点击射门!", hover=hover)
            else:
                # 蓄力射门按钮
                rect = self._aim_confirm_button_rect()
                hover = self._point_in_rect(self.mouse_pos, rect)
                self._draw_button(screen, rect, "蓄力射门", hover=hover)
            # 技能选择按钮(只有射手有技能时显示)
            sp = self.striker_profile
            if sp.skill != "none" and self.state == State.PLAYER_AIM:
                self._draw_skill_button(screen, sp)
        else:
            # 守门 - 在球门上画九宫格扑救准星
            self._draw_aim_grid(screen, "defend")
            # 确认扑救按钮
            rect = self._aim_confirm_button_rect()
            hover = self._point_in_rect(self.mouse_pos, rect)
            self._draw_button(screen, rect, "确认扑救", hover=hover)
            # 力度信息: 仅当玩家选的守门员有"预判"技能时才显示
            kp = self.keeper_profile
            if kp.skill == "anticipate":
                self._draw_power_level_panel(screen)
            else:
                self._draw_no_info_panel(screen)
        # 底部条
        if self.attacker_is_player:
            if self.state == State.PLAYER_AIM:
                sp = self.striker_profile
                if sp.skill == "curve" and self.selected_skill == "curve":
                    if self.curve_cell2 == -1:
                        tip = ("弧线球: 再点击一个相邻格子选第二目标   点技能按钮取消"
                               if IS_ANDROID else
                               "弧线球: 再点击一个相邻格子选第二目标  Q取消")
                    elif self.curve_cell2 > 0:
                        tip = "弧线球双格已选  点击蓄力射门  再点格子重选"
                    else:
                        tip = "弧线球已激活: 点击格子选第一目标"
                elif sp.skill != "none":
                    tip = ("点击九宫格选目标  点击技能按钮切换技能  蓄力射门"
                           if IS_ANDROID else
                           "点击九宫格选目标  Q/点击技能按钮切换技能  蓄力射门")
                else:
                    tip = "点击九宫格选目标  点击蓄力射门按钮开始蓄力"
            else:
                tip = ("点击「射门」按钮 → 射门!"
                       if IS_ANDROID else "点击射门按钮 / 松开空格 → 射门!")
        else:
            tip = "点击九宫格选扑救方向  点击确认扑救"
        tip_s = self.font_m.render(tip, True, WHITE)
        bg = pygame.Rect(0, HEIGHT - 50, WIDTH, 50)
        pygame.draw.rect(screen, HUD_BG, bg)
        screen.blit(tip_s, (WIDTH // 2 - tip_s.get_width() // 2, HEIGHT - 40))

    def _draw_no_info_panel(self, screen):
        """无预判技能时显示的提示面板."""
        px, py = 20, 100
        pw, ph = 340, 70
        panel = pygame.Surface((pw, ph), pygame.SRCALPHA)
        panel.fill((16, 28, 22, 220))
        screen.blit(panel, (px, py))
        pygame.draw.rect(screen, (90, 100, 95), (px, py, pw, ph), 2, border_radius=8)
        title = self.font_s.render("对方射门力度", True, HUD_FG)
        screen.blit(title, (px + 12, py + 8))
        info = self.font_m.render("???  未知", True, (130, 140, 130))
        screen.blit(info, (px + 12, py + 28))
        hint = self.font_xs.render("你的守门员无预判技能, 无法获知力度", True, (150, 160, 150))
        screen.blit(hint, (px + 12, py + 52))

    def _draw_power_level_panel(self, screen):
        """守门时显示对方射门力度等级面板(核心扑救博弈信息)."""
        level, level_text, level_color, hint = self._get_power_level()
        # 面板位置 - 左上角
        px, py = 20, 100
        pw, ph = 340, 124
        # 背景
        panel = pygame.Surface((pw, ph), pygame.SRCALPHA)
        panel.fill((16, 28, 22, 220))
        screen.blit(panel, (px, py))
        pygame.draw.rect(screen, level_color, (px, py, pw, ph), 2, border_radius=8)
        # 标题
        title = self.font_s.render("对方射门力度", True, HUD_FG)
        screen.blit(title, (px + 12, py + 8))
        # 力度等级文字(大号+彩色)
        lv = self.font_l.render(level_text, True, level_color)
        screen.blit(lv, (px + 12, py + 28))
        # 力度等级条
        bar_x = px + 100
        bar_y = py + 38
        bar_w = 220
        bar_h = 20
        pygame.draw.rect(screen, (40, 50, 45), (bar_x, bar_y, bar_w, bar_h),
                         border_radius=6)
        # 填充宽度根据等级
        if level == "weak":
            fill_w = int(bar_w * 0.33)
        elif level == "medium":
            fill_w = int(bar_w * 0.66)
        else:
            fill_w = bar_w
        pygame.draw.rect(screen, level_color, (bar_x, bar_y, fill_w, bar_h),
                         border_radius=6)
        pygame.draw.rect(screen, WHITE, (bar_x, bar_y, bar_w, bar_h), 1,
                         border_radius=6)
        # 策略提示
        hint_lines = self._wrap_text(hint, self.font_xs, pw - 24)
        hy = py + 66
        for line in hint_lines:
            hs = self.font_xs.render(line, True, (210, 220, 210))
            screen.blit(hs, (px + 12, hy))
            hy += 16
        # 相邻格(臂展覆盖)成功率 - 球越慢越高
        kp = self.keeper_profile
        adj_p = self._adjacent_save_prob()
        adj_color = GREEN if adj_p >= 0.25 else (GOLD if adj_p >= 0.12 else RED)
        adj_line = (f"相邻格: 臂展{kp.reach}可覆盖, 成功率约 {adj_p * 100:.0f}%"
                    f" (球越慢越高)")
        hs = self.font_xs.render(adj_line, True, adj_color)
        screen.blit(hs, (px + 12, py + ph - 20))

    def _draw_aim_grid(self, screen, mode):
        # 在球门处画九宫格
        gz = GOAL_Z
        w, h = GOAL_W, GOAL_H
        # 网格四角
        cells_x = [-w / 2, -w / 6, w / 6, w / 2]
        cells_y = [0, h / 3, 2 * h / 3, h]
        # 半透明覆盖球门区域
        # 画格子线 —— 静态, 只画一次后缓存; 且只占球门那一小块
        self._ensure_static_layers()
        gx, gy = self._grid_rect[0], self._grid_rect[1]
        small = self._grid_small if self._grid_small is not None else self._grid_cache
        screen.blit(small, (gx, gy))

        def lp(pt):
            """屏幕坐标 -> 小块贴图坐标"""
            return (pt[0] - gx, pt[1] - gy)

        # 当前选中的格子 - 高亮
        # 防御: aim_cell 可能因状态切换残留非法值(0/-1), 兜底回中路
        if self.aim_cell not in CELL_CENTERS:
            self.aim_cell = 5
        cx, cy = CELL_CENTERS[self.aim_cell]
        # 计算格子范围
        x1, x2, y1, y2 = cell_rect(self.aim_cell)
        # 四角投影
        p1 = project(x1, y1, gz)
        p2 = project(x2, y1, gz)
        p3 = project(x2, y2, gz)
        p4 = project(x1, y2, gz)
        # 高亮(也只画球门那一小块, 不再整屏混合)
        hl = self._hl
        if hl is None:
            hl = self._clear_overlay()
            gx, gy = 0, 0
        else:
            hl.fill((0, 0, 0, 0))
        color = (255, 220, 100, 100) if mode == "shoot" else (100, 200, 255, 100)
        pygame.draw.polygon(hl, color,
                             [lp(p1), lp(p2), lp(p3), lp(p4)])
        pygame.draw.polygon(hl, (255, 255, 255, 200),
                             [lp(p1), lp(p2), lp(p3), lp(p4)], 3)

        # 弧线球: 高亮第二格(紫色)
        if self.curve_cell2 > 0:
            cx2, cy2 = CELL_CENTERS[self.curve_cell2]
            x1b, x2b, y1b, y2b = cell_rect(self.curve_cell2)
            q1 = project(x1b, y1b, gz)
            q2 = project(x2b, y1b, gz)
            q3 = project(x2b, y2b, gz)
            q4 = project(x1b, y2b, gz)
            pygame.draw.polygon(hl, (180, 100, 220, 100),
                                 [lp(q1), lp(q2), lp(q3), lp(q4)])
            pygame.draw.polygon(hl, (220, 180, 255, 200),
                                 [lp(q1), lp(q2), lp(q3), lp(q4)], 3)
            # 弧线连接线
            pmid1 = project(cx, cy, gz)
            pmid2 = project(cx2, cy2, gz)
            pygame.draw.line(hl, (220, 180, 255, 150),
                             lp(pmid1), lp(pmid2), 2)

        # 弧线模式等待第二格: 高亮可选相邻格
        if self.curve_cell2 == -1 and mode == "shoot":
            for adj in CELL_ADJACENT.get(self.aim_cell, []):
                xa, xb, ya, yb = cell_rect(adj)
                a1 = project(xa, ya, gz)
                a2 = project(xb, ya, gz)
                a3 = project(xb, yb, gz)
                a4 = project(xa, yb, gz)
                pygame.draw.polygon(hl, (180, 100, 220, 40),
                                     [lp(a1), lp(a2), lp(a3), lp(a4)])

        screen.blit(hl, (gx, gy))

        # 数字标签
        for c in range(1, 10):
            tx, ty = CELL_CENTERS[c]
            p = project(tx, ty, gz)
            if c == self.aim_cell:
                num_color = GOLD
            elif c == self.curve_cell2:
                num_color = (220, 180, 255)
            else:
                num_color = (255, 255, 255)
            num = self.font_m.render(str(c), True, num_color)
            screen.blit(num, (p[0] - num.get_width() // 2,
                              p[1] - num.get_height() // 2))

    def _draw_power_bar(self, screen):
        # 底部力度条
        bar_w = 600
        bar_h = 30
        bar_x = (WIDTH - bar_w) // 2
        bar_y = HEIGHT - 100
        # 背景
        pygame.draw.rect(screen, (15, 22, 18),
                         (bar_x, bar_y, bar_w, bar_h), border_radius=10)
        # 刻度
        for i in range(11):
            tx = bar_x + bar_w * i / 10
            pygame.draw.line(screen, (60, 80, 65),
                             (tx, bar_y), (tx, bar_y + bar_h), 1)
        # 当前值
        fill_w = int(bar_w * self.power_value)
        # 颜色渐变 - 绿黄红
        if self.power_value < 0.4:
            col = GREEN
        elif self.power_value < 0.75:
            col = GOLD
        else:
            col = RED
        pygame.draw.rect(screen, col,
                         (bar_x, bar_y, fill_w, bar_h), border_radius=10)
        # 边框
        pygame.draw.rect(screen, WHITE,
                         (bar_x, bar_y, bar_w, bar_h), 2, border_radius=10)
        # 标签
        lbl = self.font_m.render("力度", True, WHITE)
        screen.blit(lbl, (bar_x - lbl.get_width() - 12, bar_y))
        pct = self.font_m.render(f"{int(self.power_value * 100)}%", True, WHITE)
        screen.blit(pct, (bar_x + bar_w + 12, bar_y))
        # 提示
        hint_text = ("点击「射门」按钮 → 射门" if IS_ANDROID
                     else "点击射门按钮 / 松开空格 → 射门")
        hint = self.font_s.render(hint_text, True, GOLD)
        screen.blit(hint, (WIDTH // 2 - hint.get_width() // 2, bar_y - 28))

    # ----- 结果显示 -----
    def _draw_result_overlay(self, screen):
        alpha = min(120, int(self.result_t * 200))
        screen.blit(self._dim_overlay(alpha), (0, 0))
        # 结果文字
        if self.last_outcome == "GOAL":
            txt = self.font_xl.render(self.last_result_text, True, GOLD)
            color = GOLD
        elif self.last_outcome == "SAVE":
            txt = self.font_xl.render(self.last_result_text, True, BLUE)
            color = BLUE
        else:
            txt = self.font_xl.render(self.last_result_text, True, RED)
            color = RED
        # 弹出动画
        scale = min(1.0, self.result_t * 4)
        scale = 1.0 - (1 - scale) ** 3  # ease out
        # 实际blit
        screen.blit(txt, (WIDTH // 2 - txt.get_width() // 2,
                          HEIGHT // 2 - 80))
        # 扑救失败原因(失球时显示: 玩家守门=自己失败原因, 玩家射门=对方门将失误原因)
        if self.last_outcome == "GOAL" and self.save_fail_reason:
            if not self.attacker_is_player:
                prefix, rc = "扑救失败: ", (255, 160, 100)
            else:
                prefix, rc = "对方门将失误: ", (130, 220, 160)
            reason_txt = self.font_m.render(
                f"{prefix}{self.save_fail_reason}", True, rc)
            screen.blit(reason_txt, (WIDTH // 2 - reason_txt.get_width() // 2,
                                     HEIGHT // 2 - 20))

        # 等待 - 显示继续按钮
        if self.result_t > 0.6:
            rect = self._result_button_rect()
            hover = self._point_in_rect(self.mouse_pos, rect)
            self._draw_button(screen, rect, "点击继续", hover=hover)

    def _draw_gameover(self, screen):
        """赛后数据统计界面 - 全面分析."""
        screen.blit(self._dim_overlay(200), (0, 0))

        st = self.match_stats
        # 标题
        if self.player_score > self.ai_score:
            result_txt, result_col = "胜利!", GOLD
        elif self.player_score < self.ai_score:
            result_txt, result_col = "失败...", RED
        else:
            result_txt, result_col = "平局", BLUE
        title = self.font_xl.render(result_txt, True, result_col)
        screen.blit(title, (WIDTH // 2 - title.get_width() // 2, 30))
        score = self.font_l.render(
            f"最终比分  玩家 {self.player_score} : {self.ai_score} AI", True, WHITE)
        screen.blit(score, (WIDTH // 2 - score.get_width() // 2, 90))

        # === 左侧: 核心数据 ===
        lx, ly = 40, 150
        lw = 360
        pygame.draw.rect(screen, PANEL, (lx, ly, lw, 420), border_radius=10)
        pygame.draw.rect(screen, (60, 80, 65), (lx, ly, lw, 420), 1, border_radius=10)
        hdr = self.font_m.render("核心数据", True, GOLD)
        screen.blit(hdr, (lx + 16, ly + 10))

        p_acc = (st["player_goals"] / max(1, st["player_shots"]) * 100)
        a_acc = (st["ai_goals"] / max(1, st["ai_shots"]) * 100)
        # 扑救率 = 扑救数 / 面对射正数(射正 = 进球 + 被扑出, 不含射偏)
        p_faced = st["player_saves"] + st["ai_goals"]   # 玩家门将面对的射正
        a_faced = st["ai_saves"] + st["player_goals"]   # AI 门将面对的射正
        if p_faced > 0:
            p_save_rate = f"{st['player_saves'] / p_faced * 100:.0f}%"
        else:
            p_save_rate = "-"
        if a_faced > 0:
            a_save_rate = f"{st['ai_saves'] / a_faced * 100:.0f}%"
        else:
            a_save_rate = "-"
        rows = [
            ("", "玩家", "AI", ""),
            ("射门次数", str(st["player_shots"]), str(st["ai_shots"]), ""),
            ("进球数", str(st["player_goals"]), str(st["ai_goals"]), ""),
            ("射偏次数", str(st["player_misses"]), str(st["ai_misses"]), ""),
            ("射正次数(攻)", str(a_faced), str(p_faced), ""),
            ("扑救次数(守)", str(st["player_saves"]), str(st["ai_saves"]), ""),
            ("射门精度", f"{p_acc:.0f}%", f"{a_acc:.0f}%", ""),
            ("扑救率(守)", p_save_rate, a_save_rate, ""),
            ("技能使用", str(st["player_skill_uses"]), str(st["ai_skill_uses"]), ""),
            ("超大力射门", str(st["player_power_shots"]), str(st["ai_power_shots"]), ""),
            ("最高球速", f"{st['max_ball_speed']:.0f} m/s", "", ""),
        ]
        ry = ly + 40
        for row in rows:
            if row[0] == "":
                # 表头
                h = self.font_xs.render("项目", True, HUD_FG)
                screen.blit(h, (lx + 16, ry))
                h2 = self.font_xs.render("玩家", True, GREEN)
                screen.blit(h2, (lx + 200, ry))
                h3 = self.font_xs.render("AI", True, RED)
                screen.blit(h3, (lx + 290, ry))
            else:
                lbl = self.font_s.render(row[0], True, HUD_FG)
                screen.blit(lbl, (lx + 16, ry))
                pv = self.font_s.render(row[1], True, WHITE)
                screen.blit(pv, (lx + 200, ry))
                av = self.font_s.render(row[2], True, WHITE)
                screen.blit(av, (lx + 290, ry))
            ry += 34

        # === 中间: 关键事件回顾 ===
        mx, my = 420, 150
        mw = 420
        pygame.draw.rect(screen, PANEL, (mx, my, mw, 420), border_radius=10)
        pygame.draw.rect(screen, (60, 80, 65), (mx, my, mw, 420), 1, border_radius=10)
        hdr2 = self.font_m.render("关键事件回顾", True, GOLD)
        screen.blit(hdr2, (mx + 16, my + 10))
        events = st["key_events"]
        ey = my + 40
        for i, ev in enumerate(events[:10]):
            col = GOLD if "进球" in ev else (BLUE if "扑救" in ev else RED)
            ev_s = self.font_xs.render(ev, True, col)
            screen.blit(ev_s, (mx + 16, ey))
            ey += 20
        if not events:
            ev_s = self.font_xs.render("无关键事件记录", True, (130, 130, 130))
            screen.blit(ev_s, (mx + 16, ey))

        # === 右侧: 战术分析 ===
        rx2, ry2 = 860, 150
        rw2 = 380
        pygame.draw.rect(screen, PANEL, (rx2, ry2, rw2, 420), border_radius=10)
        pygame.draw.rect(screen, (60, 80, 65), (rx2, ry2, rw2, 420), 1, border_radius=10)
        hdr3 = self.font_m.render("战术执行评估", True, GOLD)
        screen.blit(hdr3, (rx2 + 16, ry2 + 10))

        # 射门偏好分析
        ty2 = ry2 + 40
        if self.player_shot_history:
            cells = self.player_shot_history
            corners = sum(1 for c in cells if c in (1, 3, 7, 9))
            center = sum(1 for c in cells if c in (2, 5, 8))
            sides = sum(1 for c in cells if c in (4, 6))
            total = len(cells)
            analysis = [
                f"玩家射门偏好:",
                f"  边角 {corners}/{total} ({corners/total*100:.0f}%)",
                f"  中路 {center}/{total} ({center/total*100:.0f}%)",
                f"  侧翼 {sides}/{total} ({sides/total*100:.0f}%)",
            ]
            if corners / total > 0.5:
                analysis.append("  -> 偏好边角, AI易针对")
            elif center / total > 0.5:
                analysis.append("  -> 偏好中路, 较为保守")
            else:
                analysis.append("  -> 射门分散, 难以预测")
            # 力度分析
            if self.player_power_history:
                avg_p = sum(self.player_power_history) / len(self.player_power_history)
                analysis.append(f"平均力度: {avg_p:.0%}")
                if avg_p > 0.7:
                    analysis.append("  -> 激进型(常大力)")
                elif avg_p < 0.4:
                    analysis.append("  -> 保守型(常轻射)")
                else:
                    analysis.append("  -> 均衡型(中力为主)")
        else:
            analysis = ["无射门数据"]
        for line in analysis:
            col = WHITE if not line.startswith("  ->") else (200, 210, 200)
            ls = self.font_xs.render(line, True, col)
            screen.blit(ls, (rx2 + 16, ty2))
            ty2 += 20

        # 扑救偏好
        ty2 += 10
        if self.player_dive_history:
            dives = self.player_dive_history
            d_left = sum(1 for c in dives if c in (1, 4, 7))
            d_right = sum(1 for c in dives if c in (3, 6, 9))
            d_center = sum(1 for c in dives if c in (2, 5, 8))
            total = len(dives)
            analysis2 = [
                f"玩家扑救偏好:",
                f"  左侧 {d_left}/{total}",
                f"  中路 {d_center}/{total}",
                f"  右侧 {d_right}/{total}",
            ]
            for line in analysis2:
                ls = self.font_xs.render(line, True, WHITE)
                screen.blit(ls, (rx2 + 16, ty2))
                ty2 += 20

        # 按钮
        r1 = self._gameover_menu_rect()
        h1 = self._point_in_rect(self.mouse_pos, r1)
        self._draw_button(screen, r1, "返回菜单", hover=h1)
        r2 = self._gameover_retry_rect()
        h2 = self._point_in_rect(self.mouse_pos, r2)
        self._draw_button(screen, r2, "再来一局", hover=h2)

    # ----------------------------------------------------------------
    # 主循环
    # ----------------------------------------------------------------
    def _adapt_quality(self, work_ms: float, frame_dt: float):
        """只做一件事: 保证帧率目标恒为 60, 并且画面永远铺满。

        v1.03~v1.04 这里的"自适应降帧/缩画面"已全部删掉 —— 那套逻辑的代价
        远大于收益: 降帧并不会让每帧变快, 只是把卡顿藏起来; 缩画面更是直接
        把 2K 屏糊成一片。现在帧率固定 60、画面固定铺满, 不够快就去优化
        每帧本身的工作量(见 _init_display 的 SCALED)。
        """
        if self._fps_target != FPS:
            self._fps_target = FPS
        if self._present_cap != 1.0:
            self._present_cap = 1.0
            self._scaled = None

    def run(self):
        while self.running:
            # dt 必须是"真实经过的时间", 绝不能再截断成 1/30:
            # 手机只要跑不满 30 帧(比如只有 20 帧 = 50ms/帧), 截断后每帧
            # 只推进 33ms —— 游戏就整体变成 66% 速度的慢动作,
            # 表现为"球飞得慢、门将反应慢"。这里上限只用来防止切后台回来
            # 时一次跳几秒导致穿模, 0.1s 已经足够安全。
            dt = min(self.clock.tick(self._fps_target) / 1000.0, 0.10)
            # 注意: 计时必须放在 tick() 之后 —— tick 里含"等到下一帧"的等待时间,
            # 若把它也计进 work, 会把等待时间误当成干活时间。
            t0 = time.perf_counter()
            for ev in pygame.event.get():
                self.handle_event(ev)
            self.update(dt)
            self.draw(self.screen)
            # 只把"真正有画面的那一块"提交给 SDL, 四周常黑的边不重复上传
            # (手机 2K 屏上每次全屏上传要好几 MB, 只更新中间能省不少)
            pr = self._present_rect
            if (self._update_ok and pr is not None
                    and self.screen.get_size() != (WIDTH, HEIGHT)):
                try:
                    pygame.display.update(pr)
                except Exception:
                    self._update_ok = False
                    pygame.display.flip()
            else:
                pygame.display.flip()
            # 只统计"干活时间"(不含 tick 的等待), 才能判断机器是否还有余量
            work = (time.perf_counter() - t0) * 1000.0
            self._frame_ms = self._frame_ms * 0.82 + work * 0.18
            self._adapt_quality(self._frame_ms, dt)
        pygame.quit()


# ====================================================================
# 入口
# ====================================================================
def main():
    g = Game()
    g.run()


if __name__ == "__main__":
    main()
