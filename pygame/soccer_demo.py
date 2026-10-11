#!/usr/bin/env python3
"""Soccer demo in pygame: a 16.5 s vertical (1080x1920) animation drawn with plain pygame and a little 3D maths.

    python soccer_demo.py                      play in a window
    python soccer_demo.py --render demo.mp4    export a frame-exact MP4 (needs ffmpeg, or: pip install imageio-ffmpeg)
    python soccer_demo.py --frames out --fps 30   export PNG frames instead

Window keys: Space pause, Left/Right seek 1 s, 1/2/3 jump to a scene, R restart, S save a screenshot, Esc quit.

Every frame is a pure function of time (draw(t)), so the window, the PNGs and the MP4 always match.
"""
import argparse
import math
import os
import random
import shutil
import subprocess
import sys

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame  # noqa: E402
import pygame.gfxdraw  # noqa: E402

W, H = 1080, 1920
SCENES = [("PERSPECTIVE", 5.0), ("FORMATION", 5.5), ("FREE KICK", 6.0)]
STARTS = [0.0, 5.0, 10.5]
TOTAL = 16.5
ACC = (255, 209, 31)
WHITE = (255, 255, 255)

# ============================== easing (the same curves GSAP uses) ==============================
def clamp(x, a=0.0, b=1.0):
    return a if x < a else b if x > b else x

def seg(t, a, b):
    return clamp((t - a) / (b - a))

def lerp(a, b, k):
    return a + (b - a) * k

def smooth(x):
    x = clamp(x)
    return x * x * (3 - 2 * x)

def out_cubic(x):
    return 1 - (1 - clamp(x)) ** 3

def in_out_cubic(x):
    x = clamp(x)
    return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2

def in_out_expo(x):
    x = clamp(x)
    if x in (0.0, 1.0):
        return x
    return 2 ** (20 * x - 10) / 2 if x < 0.5 else (2 - 2 ** (-20 * x + 10)) / 2

def out_back(x, s=1.7):
    x = clamp(x)
    return 1 + (s + 1) * (x - 1) ** 3 + s * (x - 1) ** 2

def out_elastic(x, period=0.45):
    x = clamp(x)
    if x in (0.0, 1.0):
        return x
    return 2 ** (-10 * x) * math.sin((x - period / 4) * 2 * math.pi / period) + 1

def out_bounce(x):
    x = clamp(x)
    n, d = 7.5625, 2.75
    if x < 1 / d:
        return n * x * x
    if x < 2 / d:
        x -= 1.5 / d
        return n * x * x + 0.75
    if x < 2.5 / d:
        x -= 2.25 / d
        return n * x * x + 0.9375
    x -= 2.625 / d
    return n * x * x + 0.984375

def bump(t, c, w):
    return clamp(1 - abs(t - c) / w) ** 2

def mix(c1, c2, k):
    return tuple(int(lerp(a, b, clamp(k))) for a, b in zip(c1, c2))

# ============================== a tiny 3D camera ==============================
def sub(a, b): return (a[0] - b[0], a[1] - b[1], a[2] - b[2])
def dot(a, b): return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
def cross(a, b): return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
def norm(a):
    n = math.sqrt(dot(a, a)) or 1.0
    return (a[0] / n, a[1] / n, a[2] / n)
def vlerp(a, b, k): return tuple(lerp(x, y, k) for x, y in zip(a, b))

NEAR = 0.3

class Camera:
    """Look-at pinhole camera. World: x right, y up, z toward the near goal."""

    def __init__(self, w, h):
        self.w, self.h = w, h

    def look(self, eye, at, fov):
        self.eye = eye
        self.f = norm(sub(at, eye))
        self.r = norm(cross(self.f, (0, 1, 0)))
        self.u = cross(self.r, self.f)
        self.foc = (self.h / 2) / math.tan(math.radians(fov) / 2)

    def to_cam(self, p):
        d = sub(p, self.eye)
        return (dot(d, self.r), dot(d, self.u), dot(d, self.f))

    def screen(self, c):
        return (self.w / 2 + c[0] / c[2] * self.foc, self.h / 2 - c[1] / c[2] * self.foc)

    def proj(self, p):
        c = self.to_cam(p)
        if c[2] < NEAR:
            return None
        x, y = self.screen(c)
        return x, y, c[2]

def clip_near(poly):
    """Sutherland-Hodgman clip of a camera-space polygon against the near plane."""
    out = []
    for i, a in enumerate(poly):
        b = poly[(i + 1) % len(poly)]
        ain, bin_ = a[2] >= NEAR, b[2] >= NEAR
        if ain:
            out.append(a)
        if ain != bin_:
            k = (NEAR - a[2]) / (b[2] - a[2])
            out.append(tuple(a[j] + (b[j] - a[j]) * k for j in range(3)))
    return out

def bezier(p0, p1, p2, p3, u):
    a = 1 - u
    return tuple(a ** 3 * p0[i] + 3 * a * a * u * p1[i] + 3 * a * u * u * p2[i] + u ** 3 * p3[i] for i in range(3))

# ============================== the pitch ==============================
HX, HZ = 34.0, 52.5            # touchlines and goal lines
GW, GH = 3.66, 2.44            # half goal width, goal height
STRIPES = 14
GRASS = [(38, 128, 48), (46, 145, 57)]
UNDER = (16, 46, 22)

def circle_pts(cx, cz, r, a0=0.0, a1=2 * math.pi, n=48):
    return [(cx + r * math.sin(a0 + (a1 - a0) * i / n), 0.0, cz + r * math.cos(a0 + (a1 - a0) * i / n)) for i in range(n + 1)]

def pitch_lines():
    L = [[(-HX, 0, HZ), (HX, 0, HZ), (HX, 0, -HZ), (-HX, 0, -HZ), (-HX, 0, HZ)],
         [(-HX, 0, 0), (HX, 0, 0)], circle_pts(0, 0, 9.15, n=64)]
    for s in (1, -1):
        L.append([(-20.16, 0, s * HZ), (-20.16, 0, s * 36), (20.16, 0, s * 36), (20.16, 0, s * HZ)])
        L.append([(-9.16, 0, s * HZ), (-9.16, 0, s * 47), (9.16, 0, s * 47), (9.16, 0, s * HZ)])
        a = math.acos(-5.5 / 9.15)
        arc = [(9.15 * math.sin(th), 0, s * (41.5 + 9.15 * math.cos(th))) for th in [a + (2 * math.pi - 2 * a) * i / 24 for i in range(25)]]
        L.append(arc)
        L.append(circle_pts(0, s * 41.5, 0.22, n=10))
    return L

LINES = pitch_lines()

# ============================== people ==============================
SKIN = [(198, 141, 104), (141, 94, 62), (232, 186, 150), (96, 62, 40), (176, 120, 84)]
HAIR = [(40, 28, 20), (20, 18, 16), (120, 80, 40), (60, 40, 25), (15, 12, 10)]
HOME = dict(shirt=(255, 209, 31), shorts=(22, 24, 30), socks=(255, 209, 31), num=(22, 24, 30))
HOME_GK = dict(shirt=(60, 200, 120), shorts=(22, 24, 30), socks=(60, 200, 120), num=(22, 24, 30))
AWAY = dict(shirt=(32, 48, 112), shorts=(32, 48, 112), socks=(222, 52, 52), num=WHITE)
AWAY_GK = dict(shirt=(255, 122, 26), shorts=(22, 24, 30), socks=(255, 122, 26), num=(22, 24, 30))

F433 = [(0, 48), (-24, 34), (-9, 34), (9, 34), (24, 34), (-16, 16), (0, 16), (16, 16), (-22, -2), (0, -2), (22, -2)]
F352 = [(0, 48), (-28, 14), (-15, 34), (15, 34), (28, 14), (-12, 12), (0, 34), (12, 12), (-8, -4), (0, 18), (8, -4)]
# formations are drawn a little narrower than real so the whole shape fits the vertical frame
F433 = [(x * 0.62, z) for x, z in F433]
F352 = [(x * 0.62, z) for x, z in F352]
LINKS = [(0, 6), (6, 2), (6, 3), (2, 1), (3, 4), (6, 9), (9, 5), (9, 7), (5, 8), (7, 10), (1, 8), (4, 10), (8, 10)]

# free kick set-up
BALL0 = (9.0, 0.11, -31.0)
_d = norm((-9.0, 0.0, -21.5))
WALL_C = (BALL0[0] + _d[0] * 9.15, 0.0, BALL0[2] + _d[2] * 9.15)
WALL_P = (-_d[2], 0.0, _d[0])
WALL = [(WALL_C[0] + WALL_P[0] * o, 0.0, WALL_C[2] + WALL_P[2] * o) for o in (-1.65, -0.55, 0.55, 1.65)]
CURVE = [BALL0, (11.5, 4.5, -38.0), (3.0, 5.2, -47.0), (-2.9, 2.0, -53.2)]
T_KICK, T_FLIGHT = 1.0, 1.2           # scene-3 times
T_GOAL = T_KICK + T_FLIGHT

random.seed(7)
CONFETTI = [((random.uniform(-1, 1) * 9, random.uniform(5, 13), random.uniform(3, 10)),
             random.choice([ACC, WHITE, (60, 200, 255), (255, 90, 90)]), random.uniform(0, 6.28)) for _ in range(220)]

# ============================== rendering ==============================
def find_font(names, size, bold=True):
    for n in names:
        path = pygame.font.match_font(n, bold=bold)
        if path:
            return pygame.font.Font(path, size)
    return pygame.font.Font(None, int(size * 1.3))

class Renderer:
    def __init__(self, scale):
        self.S = scale
        self.w, self.h = int(W * scale), int(H * scale)
        self.surf = pygame.Surface((self.w, self.h))
        self.glow = pygame.Surface((self.w, self.h))
        self.cam = Camera(self.w, self.h)
        self.fonts = {}
        self.cache = {}
        self.bg = self._background()
        self.vig = self._vignette()

    # ---------- helpers ----------
    def px(self, v):
        return v * self.S

    def font(self, size, mono=False):
        key = (max(6, int(round(size * self.S / 2) * 2)), mono)  # sizes snap to 2 px so fonts get reused
        if key not in self.fonts:
            names = ["consolas", "dejavusansmono", "couriernew"] if mono else ["arialblack", "segoeuiblack", "interdisplay", "inter", "helveticaneue", "dejavusans"]
            self.fonts[key] = find_font(names, max(6, key[0]))
        return self.fonts[key]

    def text(self, s, size, color, mono=False):
        key = (s, int(size * self.S), color, mono)
        if key not in self.cache:
            if len(self.cache) > 600:
                self.cache.clear()
            self.cache[key] = self.font(size, mono).render(s, True, color)
        return self.cache[key]

    def panel(self, w, h, r, alpha=150, border=40):
        key = ("panel", int(w), int(h), int(r), alpha, border)
        if key not in self.cache:
            p = pygame.Surface((int(w), int(h)), pygame.SRCALPHA)
            pygame.draw.rect(p, (6, 10, 18, alpha), p.get_rect(), border_radius=int(r))
            pygame.draw.rect(p, (255, 255, 255, border), p.get_rect(), width=max(1, int(self.px(2))), border_radius=int(r))
            self.cache[key] = p
        return self.cache[key]

    def _background(self):
        bg = pygame.Surface((self.w, self.h))
        top, bot = (6, 12, 10), (10, 30, 18)
        for y in range(self.h):
            pygame.draw.line(bg, mix(top, bot, y / self.h), (0, y), (self.w, y))
        return bg

    def _vignette(self):
        small = pygame.Surface((90, 160), pygame.SRCALPHA)
        for y in range(160):
            for x in range(90):
                d = math.hypot((x - 45) / 45, (y - 80) / 80)
                small.set_at((x, y), (0, 0, 0, int(200 * clamp((d - 0.55) / 0.75) ** 1.6)))
        return pygame.transform.smoothscale(small, (self.w, self.h))

    # ---------- 3D drawing ----------
    def quad(self, pts, color):
        c = clip_near([self.cam.to_cam(p) for p in pts])
        if len(c) >= 3:
            pygame.draw.polygon(self.surf, color, [self.cam.screen(q) for q in c])

    def ground_line(self, pts, k, color, width_m, target=None, step=3.0):
        """Polyline on the ground, drawn on up to fraction k of its length, with perspective-correct width."""
        target = target or self.surf
        segs, total = [], 0.0
        for a, b in zip(pts, pts[1:]):
            n = max(1, int(math.dist(a, b) / step))
            for i in range(n):
                p, q = vlerp(a, b, i / n), vlerp(a, b, (i + 1) / n)
                segs.append((p, q, math.dist(p, q)))
                total += segs[-1][2]
        left = total * clamp(k)
        for p, q, l in segs:
            if left <= 0:
                break
            if l > left:
                q = vlerp(p, q, left / l)
            left -= l
            a, b = self.cam.to_cam(p), self.cam.to_cam(q)
            if a[2] < NEAR and b[2] < NEAR:
                continue
            if a[2] < NEAR:
                a = vlerp(a, b, (NEAR - a[2]) / (b[2] - a[2]))
            if b[2] < NEAR:
                b = vlerp(b, a, (NEAR - b[2]) / (a[2] - b[2]))
            wpx = max(1, int(width_m * self.cam.foc / ((a[2] + b[2]) / 2)))
            sa, sb = self.cam.screen(a), self.cam.screen(b)
            pygame.draw.line(target, color, sa, sb, wpx)
            if wpx > 3:
                pygame.draw.circle(target, color, sb, wpx / 2)

    def goal(self, z0, rise, bulge=None):
        """Goal frame and net; z0 = goal line, the net hangs away from the field. Returns draw callables by depth."""
        s = 1 if z0 > 0 else -1
        h = GH * rise
        if h < 0.02:
            return []
        net = []
        def np_(x, y, back):
            p = (x, y, z0 + s * back)
            if bulge:
                bx, by, a = bulge
                w = a * math.exp(-((x - bx) ** 2 + (y - by) ** 2) * 0.6)
                p = (p[0], p[1], p[2] + s * w)
            return p
        for i in range(13):  # back net: verticals from the top-back bar to the ground
            x = -GW + 2 * GW * i / 12
            net.append([np_(x, h, 1.0 * rise), np_(x, h * 0.5, 1.6 * rise), np_(x, 0, 2.0 * rise)])
        for j in range(6):
            y = h * j / 5
            back = lerp(2.0, 1.0, j / 5) * rise
            net.append([np_(-GW + 2 * GW * i / 12, y, back) for i in range(13)])
        for sx in (-GW, GW):  # side nets
            for j in range(5):
                y = h * j / 4
                net.append([(sx, y, z0), (sx, y, z0 + s * lerp(2.0, 1.0, j / 4) * rise)])
        for j in range(6):
            x = -GW + 2 * GW * j / 5
            net.append([(x, h, z0), np_(x, h, 1.0 * rise)])

        def draw_net():
            for line in net:
                ps = [self.cam.proj(p) for p in line]
                for a, b in zip(ps, ps[1:]):
                    if a and b and max(abs(a[0]), abs(a[1]), abs(b[0]), abs(b[1])) < 20000:
                        pygame.gfxdraw.line(self.surf, int(a[0]), int(a[1]), int(b[0]), int(b[1]), (230, 236, 240, 120))

        def draw_frame():
            for a, b in [((-GW, 0, z0), (-GW, h, z0)), ((GW, 0, z0), (GW, h, z0)), ((-GW, h, z0), (GW, h, z0))]:
                pa, pb = self.cam.proj(a), self.cam.proj(b)
                if pa and pb:
                    wpx = max(2, int(0.12 * self.cam.foc / ((pa[2] + pb[2]) / 2)))
                    pygame.draw.line(self.surf, (245, 247, 250), pa[:2], pb[:2], wpx)
                    pygame.draw.circle(self.surf, (245, 247, 250), pb[:2], wpx / 2)
        c = self.cam.to_cam((0, h / 2, z0))[2]
        return [(c + 1.5, draw_net), (c, draw_frame)]

    def shadow(self, p, r_m):
        c = self.cam.proj(p)
        if not c:
            return
        rx = r_m * self.cam.foc / c[2]
        ry = rx * clamp(abs(self.cam.f[1]) * 1.2, 0.22, 1.0)
        if 1 <= rx < 4000 and abs(c[0]) < 20000 and abs(c[1]) < 20000:
            pygame.gfxdraw.filled_ellipse(self.surf, int(c[0]), int(c[1]), int(rx), max(1, int(ry)), (0, 0, 0, 90))

    def person(self, p, kit, pose="stand", phase=0.0, front=False, num=None, skin=0, tilt=0.0, lift=0.0):
        """A cartoon player drawn as a billboard: p = feet on the ground (world), lift = metres off the ground."""
        self.shadow(p, 0.42)
        c = self.cam.proj((p[0], p[1] + lift, p[2]))
        if not c:
            return
        h = 1.85 * self.cam.foc / c[2]
        if h < 6:
            return
        if tilt:
            size = int(h * 2.6)
            tmp = pygame.Surface((size, size), pygame.SRCALPHA)
            self._body(tmp, size / 2, size / 2 + h * 0.5, h, kit, pose, phase, front, num, skin)
            rot = pygame.transform.rotate(tmp, math.degrees(tilt))
            cy = c[1] - h * 0.5
            self.surf.blit(rot, rot.get_rect(center=(c[0], cy)))
        else:
            self._body(self.surf, c[0], c[1], h, kit, pose, phase, front, num, skin)

    def _body(self, s, fx, fy, h, kit, pose, phase, front, num, skin):
        P = lambda x, y: (fx + x * h, fy - y * h)
        sk, hair = SKIN[skin % len(SKIN)], HAIR[skin % len(HAIR)]
        sn = math.sin(phase)
        hip_y, sh_y = 0.50, 0.80
        feet = [(-0.07, 0.0), (0.07, 0.0)]
        hands = [(-0.17, 0.52), (0.17, 0.52)]
        bob = 0.0
        if pose == "run":
            feet = [(-0.07, 0.11 * max(0, sn)), (0.07, 0.11 * max(0, -sn))]
            hands = [(-0.18, 0.56 + 0.08 * sn), (0.18, 0.56 - 0.08 * sn)]
            bob = 0.02 * abs(math.cos(phase))
        elif pose == "ready":
            hip_y, sh_y = 0.44, 0.73
            feet = [(-0.13, 0.0), (0.13, 0.0)]
            hands = [(-0.2, 0.5), (0.2, 0.5)]
        elif pose == "wall":
            hands = [(-0.03, 0.47), (0.03, 0.47)]
        elif pose == "jump":
            feet = [(-0.1, 0.07), (0.1, 0.07)]
            hands = [(-0.03, 0.49), (0.03, 0.49)]
        elif pose == "kick":
            feet = [(-0.07, 0.0), (0.24, 0.24)]
            hands = [(-0.27, 0.68), (0.26, 0.6)]
        elif pose == "cheer":
            hands = [(-0.21, 1.06 + 0.04 * sn), (0.21, 1.06 - 0.04 * sn)]
            feet = [(-0.08, 0.04 * max(0, sn)), (0.08, 0.04 * max(0, -sn))]
        elif pose == "dive":
            hip_y, sh_y = 0.47, 0.77
            hands = [(-0.06, 1.12), (0.06, 1.1)]
            feet = [(-0.09, 0.02), (0.11, 0.06)]
        o = lambda q: (q[0], q[1] + bob)
        lw, aw = max(2, int(0.075 * h)), max(2, int(0.06 * h))
        hips = [(-0.06, hip_y), (0.06, hip_y)]
        # legs (skin, then socks and boots)
        for (hx, hy), (ftx, fty) in zip(hips, feet):
            knee = ((hx + ftx) / 2 + (0.02 if hx > 0 else -0.02), (hy + fty) / 2 + 0.02)
            pygame.draw.line(s, sk, P(*o((hx, hy))), P(*o(knee)), lw)
            pygame.draw.line(s, kit["socks"], P(*o(knee)), P(*o((ftx, fty + 0.02))), lw + 1)
            pygame.draw.ellipse(s, (18, 18, 22), pygame.Rect(0, 0, 0.11 * h, 0.05 * h).move(P(*o((ftx - 0.055, fty + 0.035)))))
        # shorts
        pygame.draw.polygon(s, kit["shorts"], [P(*o(q)) for q in [(-0.115, hip_y + 0.04), (0.115, hip_y + 0.04), (0.125, hip_y - 0.11), (0.015, hip_y - 0.11), (0, hip_y - 0.06), (-0.015, hip_y - 0.11), (-0.125, hip_y - 0.11)]])
        # arms (sleeve then skin)
        for sx, hd in zip((-0.135, 0.135), hands):
            sh = (sx, sh_y - 0.02)
            el = ((sx + hd[0]) / 2, (sh[1] + hd[1]) / 2)
            pygame.draw.line(s, sk, P(*o(el)), P(*o(hd)), aw)
            pygame.draw.line(s, kit["shirt"], P(*o(sh)), P(*o(el)), aw + 1)
            pygame.draw.circle(s, sk, P(*o(hd)), aw * 0.75)
        # torso with a light edge for volume
        torso = [P(*o(q)) for q in [(-0.14, sh_y), (0.14, sh_y), (0.115, hip_y + 0.03), (-0.115, hip_y + 0.03)]]
        pygame.draw.polygon(s, tuple(int(v * 0.55) for v in kit["shirt"]), [(x + 1, y + 1) for x, y in torso])
        pygame.draw.polygon(s, kit["shirt"], torso)
        hl = tuple(min(255, int(v * 1.18 + 20)) for v in kit["shirt"])
        pygame.draw.polygon(s, hl, [P(*o(q)) for q in [(-0.14, sh_y), (-0.08, sh_y), (-0.07, hip_y + 0.03), (-0.115, hip_y + 0.03)]])
        if num is not None and not front and h > 60:
            t = self.font(0.14 * h / self.S).render(str(num), True, kit["num"])
            s.blit(t, t.get_rect(center=P(*o((0, (sh_y + hip_y) / 2 + 0.03)))))
        # head
        hc, r = P(*o((0, sh_y + 0.11))), 0.078 * h
        pygame.draw.circle(s, sk, (hc[0], hc[1] + 0.03 * h), 0.03 * h)  # neck
        pygame.draw.circle(s, (20, 20, 24), hc, r + 1.2)
        pygame.draw.circle(s, sk, hc, r)
        if front:
            pygame.draw.circle(s, hair, (hc[0], hc[1] - r * 0.45), r * 0.75, draw_top_left=True, draw_top_right=True)
            for ex in (-0.32, 0.32):
                pygame.draw.circle(s, WHITE, (hc[0] + ex * r, hc[1] + r * 0.05), max(1, r * 0.26))
                pygame.draw.circle(s, (12, 12, 14), (hc[0] + ex * r, hc[1] + r * 0.1), max(1, r * 0.13))
        else:
            pygame.draw.circle(s, hair, hc, r * 0.97)
            pygame.draw.circle(s, sk, (hc[0], hc[1] + r * 0.55), r * 0.5)

    def ball(self, p, spin):
        self.shadow((p[0], 0, p[2]), 0.13)
        c = self.cam.proj(p)
        if not c:
            return
        r = 0.11 * self.cam.foc / c[2]
        if r < 1:
            return
        pygame.draw.circle(self.surf, (30, 30, 34), c[:2], r + max(1, r * 0.08))
        pygame.draw.circle(self.surf, (248, 248, 250), c[:2], r)
        if r > 3:
            for k in range(5):  # rotating panels
                a = spin + k * 2 * math.pi / 5
                q = (c[0] + math.cos(a) * r * 0.62, c[1] + math.sin(a) * r * 0.62 * math.cos(spin * 0.7))
                pygame.draw.circle(self.surf, (34, 34, 40), q, r * 0.24)
            pygame.draw.circle(self.surf, (34, 34, 40), c[:2], r * 0.28)

    # ---------- overlay ----------
    def callout(self, anchor, title, sub, age, life):
        if anchor is None or age < 0 or age > life:
            return
        k_in, k_out = out_cubic(age / 0.5), 1 - seg(age, life - 0.35, life)
        ax, ay = anchor[0], anchor[1]
        if not (self.px(40) < ay < self.px(1500)):
            return
        side = 1 if ax < self.w * 0.55 else -1
        ex, ey = ax + side * self.px(80), ay - self.px(110)
        t1, t2 = self.text(title, 34, WHITE), self.text(sub, 28, ACC)
        pw, ph = max(t1.get_width(), t2.get_width()) + self.px(56), self.px(104)
        x = ex if side > 0 else ex - pw
        x = clamp(x, self.px(30), self.w - self.px(30) - pw)
        y = ey - ph / 2
        col = (255, 255, 255)
        pygame.draw.line(self.surf, col, (ax, ay), (lerp(ax, ex, k_in), lerp(ay, ey, k_in)), max(2, int(self.px(3))))
        pygame.draw.circle(self.surf, ACC, (ax, ay), self.px(9) * k_in)
        pygame.draw.circle(self.surf, col, (ax, ay), self.px(16) * k_in, max(1, int(self.px(3))))
        if k_in > 0.5:
            sc = out_back((k_in - 0.5) * 2) * k_out
            if sc > 0.05:
                pnl = pygame.transform.smoothscale(self.panel(pw, ph, ph / 2, 215, 0), (max(1, int(pw * sc)), max(1, int(ph * sc))))
                r = pnl.get_rect(center=(x + pw / 2, y + ph / 2))
                self.surf.blit(pnl, r)
                pygame.draw.rect(self.surf, ACC, r, max(1, int(self.px(3))), border_radius=int(r.height / 2))
                if sc > 0.8:
                    self.surf.blit(t1, t1.get_rect(center=(r.centerx, r.centery - self.px(18))))
                    self.surf.blit(t2, t2.get_rect(center=(r.centerx, r.centery + self.px(22))))

    def caption(self, words, age):
        """words: list of (word, highlighted); each word pops in 0.06 s after the previous one."""
        size, maxw = 56, self.px(900)
        sp = self.text(" ", size, WHITE).get_width()
        surfs = [(self.text(wd, size, ACC if hl else WHITE), hl) for wd, hl in words]
        lines, cur, cw = [], [], 0
        for s_, hl in surfs:
            if cur and cw + sp + s_.get_width() > maxw:
                lines.append((cur, cw))
                cur, cw = [], 0
            cw += (sp if cur else 0) + s_.get_width()
            cur.append(s_)
        lines.append((cur, cw))
        lh = self.px(72)
        bw, bh = max(w for _, w in lines) + self.px(80), len(lines) * lh + self.px(44)
        bx, by = (self.w - bw) / 2, self.px(1530) - bh
        ka = out_cubic(age / 0.3)
        pnl = self.panel(bw, bh, self.px(30), int(165 * ka), int(40 * ka))
        self.surf.blit(pnl, (bx, by))
        i = 0
        for li, (line, lw_) in enumerate(lines):
            x = (self.w - lw_) / 2
            for s_ in line:
                k = clamp((age - i * 0.06) / 0.25)
                if k > 0:
                    sc = 0.6 + 0.4 * out_back(k)
                    ws = pygame.transform.smoothscale(s_, (max(1, int(s_.get_width() * sc)), max(1, int(s_.get_height() * sc)))) if sc != 1 else s_
                    ws.set_alpha(int(255 * clamp(k * 1.6)))
                    cy = by + self.px(22) + li * lh + lh / 2 + (1 - k) * self.px(14)
                    self.surf.blit(ws, ws.get_rect(center=(x + s_.get_width() / 2, cy)))
                x += s_.get_width() + sp
                i += 1

    def hud(self, main, subtxt, stat, bar):
        x, y, w, h = self.px(150), self.px(150), self.px(780), self.px(170)
        self.surf.blit(self.panel(w, h, self.px(32), 150), (x, y))
        self.surf.blit(self.text(main, 58, WHITE, mono=True), (x + self.px(40), y + self.px(28)))
        self.surf.blit(self.text(subtxt.upper(), 24, (190, 196, 205)), (x + self.px(40), y + self.px(100)))
        lab, val = self.text(stat[0], 22, ACC), self.text(stat[1], 40, WHITE, mono=True)
        self.surf.blit(lab, lab.get_rect(topright=(x + w - self.px(40), y + self.px(26))))
        self.surf.blit(val, val.get_rect(topright=(x + w - self.px(40), y + self.px(52))))
        bx, by, bw = x + self.px(40), y + h - self.px(28), w - self.px(80)
        pygame.draw.rect(self.surf, (60, 64, 72), (bx, by, bw, self.px(10)), border_radius=int(self.px(5)))
        pygame.draw.rect(self.surf, ACC, (bx, by, max(self.px(10), bw * clamp(bar)), self.px(10)), border_radius=int(self.px(5)))

    def title(self):
        t = self.text("PYGAME SOCCER DEMO", 62, ACC)
        r = t.get_rect(center=(self.w / 2, self.px(88)))
        self.glow.blit(t, r)
        sh = self.text("PYGAME SOCCER DEMO", 62, (10, 14, 10))
        for dx, dy in ((-3, 0), (3, 0), (0, -3), (0, 3)):
            self.surf.blit(sh, r.move(self.px(dx), self.px(dy)))
        self.surf.blit(t, r)

    # ---------- the frame ----------
    def draw(self, T):
        T = T % TOTAL
        si = 0 if T < STARTS[1] else 1 if T < STARTS[2] else 2
        t = T - STARTS[si]
        self.surf.blit(self.bg, (0, 0))
        self.glow.fill((0, 0, 0))
        for i in range(7):  # floodlight glows above the pitch
            pygame.draw.circle(self.glow, (20, 24, 16), (self.w * (0.08 + i * 0.14), self.px(330 + 30 * math.sin(i))), self.px(30))
        shake = (0.0, 0.0)
        hud, cap, flash = None, None, 0.0
        if si == 0:
            hud, cap = self.scene_perspective(t)
        elif si == 1:
            hud, cap = self.scene_formation(t)
        else:
            hud, cap, shake, flash = self.scene_freekick(t)
        # bloom: blur the glow layer by scaling it down and up, then add it
        small = pygame.transform.smoothscale(self.glow, (max(1, self.w // 10), max(1, self.h // 10)))
        blur = pygame.transform.smoothscale(small, (self.w, self.h))
        self.surf.blit(blur, (0, 0), special_flags=pygame.BLEND_ADD)
        self.surf.blit(blur, (0, 0), special_flags=pygame.BLEND_ADD)
        self.surf.blit(self.glow, (0, 0), special_flags=pygame.BLEND_ADD)
        if shake != (0.0, 0.0):
            self.surf.scroll(int(self.px(shake[0])), int(self.px(shake[1])))
        self.surf.blit(self.vig, (0, 0))
        # cuts: a quick white flash, plus any flash the scene asks for
        cut = max(bump(T, STARTS[1], 0.15), bump(T, STARTS[2], 0.15))
        f = max(cut * 0.8, flash)
        if f > 0.01:
            self.surf.fill((int(255 * f),) * 3, special_flags=pygame.BLEND_ADD)
        self.title()
        self.hud(*hud, t / SCENES[si][1])
        cap_words, cap_age = cap
        self.caption(cap_words, cap_age)
        fade = max(1 - seg(T, 0, 0.3), seg(T, TOTAL - 0.4, TOTAL))
        if fade > 0:
            self.surf.fill((int(255 * (1 - fade)),) * 3, special_flags=pygame.BLEND_MULT)
        return self.surf

    def _pitch(self, flip_t=None):
        """Apron, 14 stripes (flipping in when flip_t is given) and nothing else."""
        self.quad([(-HX - 8, 0, HZ + 9), (HX + 8, 0, HZ + 9), (HX + 8, 0, -HZ - 9), (-HX - 8, 0, -HZ - 9)], (12, 40, 18))
        order = []
        for i in range(STRIPES):
            z0, z1 = -HZ + 2 * HZ * i / STRIPES, -HZ + 2 * HZ * (i + 1) / STRIPES
            zc, half = (z0 + z1) / 2, (z1 - z0) / 2
            th, lift = 0.0, 0.0
            if flip_t is not None:
                t0 = 0.3 + 0.08 * abs(i - (STRIPES - 1) / 2)
                k = seg(flip_t, t0, t0 + 0.9)
                th, lift = lerp(-math.pi, 0, out_back(k)), lerp(14, 0, out_cubic(k))
                if k <= 0:
                    continue
            pts = [(x, lift + dz * math.sin(th), zc + dz * math.cos(th)) for x, dz in ((-HX, -half), (HX, -half), (HX, half), (-HX, half))]
            col = GRASS[i % 2] if math.cos(th) >= 0 else UNDER
            order.append((self.cam.to_cam((0, lift, zc))[2], pts, col))
        for _, pts, col in sorted(order, key=lambda o: -o[0]):
            self.quad(pts, col)

    def _lines(self, k=1.0):
        for L in LINES:
            self.ground_line(L, k, (236, 240, 232), 0.12)

    def _draw_sorted(self, items):
        for _, fn in sorted(items, key=lambda it: -it[0]):
            fn()

    # ---------- scene 1: the pitch builds itself ----------
    def scene_perspective(self, t):
        e = in_out_expo(seg(t, 0, 3.6))
        a, d, h = lerp(-1.3, 0.0, e), lerp(6, 88, e), lerp(150, 46, e)
        self.cam.look((math.sin(a) * d, h, 12 + math.cos(a) * d), (0, 0, 12 * e), 50)
        self._pitch(flip_t=t)
        k = in_out_cubic(seg(t, 2.2, 3.8))
        self._lines(k)
        for L in LINES[:3]:
            self.ground_line(L, k, (90, 110, 20), 0.5, target=self.glow)
        items = self.goal(-HZ, out_elastic(seg(t, 3.0, 4.3))) + self.goal(HZ, out_elastic(seg(t, 3.15, 4.45)))
        self._draw_sorted(items)
        self.callout(self.cam.proj((0, 0, 0)), "STAGGERED FLIP", "ease: out-back", t - 1.0, 2.2)
        self.callout(self.cam.proj((0, GH, -HZ)), "ELASTIC GOALS", "ease: out-elastic", t - 3.3, 1.7)
        words = cap_words(["A *3D pitch* drawn in plain *pygame...*", "stripes flip in on a *stagger,* then the *lines draw on.*"], t, 2.5)
        return ("PERSPECTIVE", "3D maths in plain pygame", ("CAMERA", "SWOOP")), words

    # ---------- scene 2: formation ----------
    def scene_formation(self, t):
        a = lerp(0.0, 0.25, in_out_cubic(seg(t, 0, 5.5)))
        self.cam.look((math.sin(a) * 70, 36, 16 + math.cos(a) * 70), (0, 0, 16), 50)
        self._pitch()
        self._lines()
        run = smooth(seg(t, 2.4, 2.7)) * (1 - smooth(seg(t, 3.6, 4.0)))
        items = self.goal(-HZ, 1) + self.goal(HZ, 1)
        heads = []
        for i in range(11):
            p, lift = formation_pos(i, t)
            if t < i * 0.08:
                continue
            c = self.cam.to_cam(p)[2]
            pose = "run" if run > 0.05 and F433[i] != F352[i] else ("ready" if i == 0 else "stand")
            items.append((c, lambda p=p, lift=lift, i=i, pose=pose: self.person(p, HOME_GK if i == 0 else HOME, pose, t * 11 + i, num=i + 1, skin=i, lift=lift)))
            heads.append((i, p, lift))
        # passing network after the morph (glowing, drawn on one link after another)
        for j, (u, v) in enumerate(LINKS):
            k = out_cubic(seg(t, 4.0 + j * 0.07, 4.6 + j * 0.07))
            if k > 0:
                A, B = F352[u], F352[v]
                M = ((A[0] + B[0]) / 2 + (B[1] - A[1]) * 0.12, (A[1] + B[1]) / 2 - (B[0] - A[0]) * 0.12)
                pts = [((1 - q) ** 2 * A[0] + 2 * (1 - q) * q * M[0] + q * q * B[0], 0.0, (1 - q) ** 2 * A[1] + 2 * (1 - q) * q * M[1] + q * q * B[1]) for q in [n / 16 for n in range(17)]]
                self.ground_line(pts, k, (190, 225, 60), 0.18, step=4)
                self.ground_line(pts, k, (55, 75, 8), 0.45, target=self.glow, step=4)
        self._draw_sorted(items)
        for i, p, lift in heads:  # numbers pop above the heads once each player lands
            pk = out_back(seg(t, i * 0.08 + 0.7, i * 0.08 + 1.1), 3)
            c = self.cam.proj((p[0], p[1] + lift + 2.6, p[2]))
            if c and pk > 0.02:
                s_ = self.text(str(i + 1), 34, WHITE)
                s_ = pygame.transform.smoothscale(s_, (max(1, int(s_.get_width() * pk)), max(1, int(s_.get_height() * pk))))
                self.surf.blit(s_, s_.get_rect(center=c[:2]))
        self.callout(self.cam.proj((F433[9][0], 2.2, F433[9][1])), "BOUNCE DROP", "staggered 0.08 s", t - 0.4, 1.9)
        p6 = formation_pos(6, t)[0]
        self.callout(self.cam.proj((p6[0], 2.2, p6[2])), "ELASTIC MORPH", "4-3-3 -> 3-5-2", t - 2.5, 2.9)
        words = cap_words(["Players drop in on a *bounce* ease...", "then switch *4-3-3 to 3-5-2* on an *elastic* ease."], t, 2.6)
        return ("FORMATION", "bounce drop · elastic morph", ("SHAPE", "4-3-3" if t < 3.1 else "3-5-2")), words

    # ---------- scene 3: free kick ----------
    def scene_freekick(self, t):
        u = seg(t, T_KICK, T_GOAL)
        bp = bezier(*CURVE, u) if t >= T_KICK else BALL0
        if t > T_GOAL:  # the ball drops inside the net
            d = t - T_GOAL
            bp = (CURVE[3][0], max(0.11, CURVE[3][1] - 4.9 * d * d - 1.0 * d), CURVE[3][2] - 0.3 * out_cubic(d * 3))
        e1, e2 = in_out_cubic(seg(t, T_KICK + 0.05, T_GOAL)), out_cubic(seg(t, T_GOAL + 0.2, T_GOAL + 1.8))
        eye = vlerp(vlerp((14.8, 2.7, -17.6), (6.0, 3.6, -40.0), e1), (3.0, 9.0, -31.0), e2)
        at = vlerp(vlerp((1.0, 1.8, -52.0), (-1.0, 1.8, -53.0), e1), (0.0, 3.6, -53.0), e2)
        sh = math.exp(-max(0, t - T_GOAL) * 4) * (t > T_GOAL)
        shake = (math.sin(t * 80) * 14 * sh, math.cos(t * 67) * 10 * sh)
        self.cam.look(eye, at, lerp(38, 46, e2))
        self._pitch()
        self._lines()
        nb = max(0.0, t - T_GOAL)
        bulge = (-2.9, 2.0, 0.9 * math.sin(min(nb / 0.12, 1) * math.pi / 2) * math.exp(-max(0, nb - 0.12) * 2.5)) if nb > 0 else None
        items = self.goal(-HZ, 1, bulge)
        # kicker: run-up, strike, then celebrate
        kp = vlerp((11.6, 0, -26.6), (9.55, 0, -30.2), smooth(seg(t, 0.3, T_KICK)))
        kpose = "run" if 0.3 < t < T_KICK - 0.05 else "kick" if t < T_KICK + 0.35 else ("cheer" if t > T_GOAL + 0.3 else "stand")
        items.append((self.cam.to_cam(kp)[2], lambda: self.person(kp, HOME, kpose, t * 12, num=10, skin=1)))
        for j, wp in enumerate(WALL):  # the wall jumps: up on out-cubic, down on a bounce
            jt = t - (T_KICK + 0.08 + j * 0.04)
            lift = 0.6 * out_cubic(jt / 0.22) if jt < 0.22 else 0.6 * (1 - out_bounce((jt - 0.22) / 0.4)) if jt < 0.62 else 0.0
            lift = max(0.0, lift) if jt > 0 else 0.0
            items.append((self.cam.to_cam(wp)[2], lambda wp=wp, lift=lift, j=j: self.person(wp, AWAY, "jump" if lift > 0.05 else "wall", 0, front=True, skin=j + 2, lift=lift)))
        dk = out_cubic(seg(t, T_GOAL - 0.45, T_GOAL + 0.05))
        gp = (lerp(0.0, -2.1, dk), 0.0, -51.2)
        items.append((self.cam.to_cam(gp)[2], lambda: self.person(gp, AWAY_GK, "dive" if dk > 0.05 else "ready", 0, front=True, skin=3,
                                                                  tilt=1.2 * dk, lift=0.7 * math.sin(dk * math.pi) + 0.25 * dk)))
        items.append((self.cam.to_cam(bp)[2], lambda: self.ball(bp, t * 14 if t > T_KICK else 0)))
        # the trail
        if t > T_KICK:
            prev = None
            for n in range(40):
                q = u - n * 0.012
                if q < 0:
                    break
                c = self.cam.proj(bezier(*CURVE, q))
                fade = (1 - n / 40) * (1 - seg(t, T_GOAL + 0.3, T_GOAL + 1.2))
                if c and prev and fade > 0:
                    wpx = max(1, int(0.06 * self.cam.foc / c[2]))
                    pygame.draw.line(self.glow, (int(130 * fade), int(180 * fade), int(30 * fade)), prev[:2], c[:2], wpx)
                prev = c
        self._draw_sorted(items)
        # GOAL letters and confetti
        if t > T_GOAL + 0.25:
            for i, ch in enumerate("GOAL"):
                k = out_back(seg(t, T_GOAL + 0.35 + i * 0.1, T_GOAL + 0.95 + i * 0.1), 3)
                c = self.cam.proj((-3.0 + i * 2.0, 6.4, -53.5))
                if c and k > 0.02:
                    base = self.text(ch, 130, ACC)
                    s_ = pygame.transform.rotozoom(base, (1 - k) * 25, k)
                    r = s_.get_rect(center=c[:2])
                    out = self.text(ch, 130, (12, 16, 10))
                    o_ = pygame.transform.rotozoom(out, (1 - k) * 25, k)
                    for dx, dy in ((-4, 0), (4, 0), (0, -4), (0, 4)):
                        self.surf.blit(o_, r.move(self.px(dx), self.px(dy)))
                    self.surf.blit(s_, r)
                    self.glow.blit(s_, r)
            ct = t - T_GOAL
            for (vx, vy, vz), col, ph in CONFETTI:
                p = (vx * ct * 0.6, 1.5 + vy * ct - 4.9 * ct * ct * 0.55, -52.5 + vz * ct * 0.6)
                if p[1] < 0.05:
                    continue
                c = self.cam.proj(p)
                if c:
                    sz = max(1, 0.07 * self.cam.foc / c[2])
                    fl = abs(math.sin(ph + ct * 9))
                    pygame.draw.rect(self.surf, col, (c[0], c[1], sz, sz * (0.3 + fl)))
        self.callout(self.cam.proj(bp), "BEZIER CURVE", "4 control points", t - T_KICK - 0.05, 1.15)
        self.callout(self.cam.proj((WALL[0][0], 2.3, WALL[0][2])), "WALL JUMP", "out-cubic + bounce", t - 0.3, 2.0)
        flash = 0.35 * bump(t, T_GOAL, 0.12)
        words = cap_words(["The ball curls along a *3D Bezier curve...*", "over the jumping wall and into the *top corner!*"], t, 2.4)
        return ("FREE KICK", "curved path · wall jump · keeper dive", ("CURVE", "BEZIER")), words, shake, flash

def formation_pos(i, t):
    """Scene 2: player i drops in (bounce, staggered 0.08 s), then morphs 4-3-3 -> 3-5-2 (elastic, staggered from the edges)."""
    k = out_bounce(seg(t, i * 0.08, i * 0.08 + 1.0))
    st = (i if i % 2 else 10 - i) * 0.03
    m = out_elastic(seg(t, 2.4 + st, 3.8 + st), 0.55)
    return (lerp(F433[i][0], F352[i][0], m), 0.0, lerp(F433[i][1], F352[i][1], m)), lerp(22, 0, k)

def cap_words(lines, t, split):
    """Two caption lines; *stars* mark highlighted words. Returns (words, age) for the line showing at t."""
    i = 0 if t < split else 1
    words, hl = [], False
    for w in lines[i].split(" "):
        st = w.startswith("*")
        w = w.lstrip("*")
        end = w.endswith("*")
        w = w.rstrip("*")
        words.append((w, hl or st))
        hl = (hl or st) and not end
    return words, t - (0 if i == 0 else split)

# ============================== export / window ==============================
def ffmpeg_exe():
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None

def export(args):
    r = Renderer(args.ss)
    n = int(round(TOTAL * args.fps))
    proc = None
    if args.render:
        exe = ffmpeg_exe()
        if not exe:
            sys.exit("ffmpeg not found: install it, or `pip install imageio-ffmpeg`, or use --frames DIR")
        proc = subprocess.Popen([exe, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(args.fps), "-i", "-",
                                 "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "17", "-preset", "medium", "-movflags", "+faststart", args.render], stdin=subprocess.PIPE)
    else:
        os.makedirs(args.frames, exist_ok=True)
    times = [float(x) for x in args.times.split(",")] if args.times else [i / args.fps for i in range(n)]
    for i, t in enumerate(times):
        frame = r.draw(t)
        if frame.get_size() != (W, H):
            frame = pygame.transform.smoothscale(frame, (W, H))
        if proc:
            proc.stdin.write(pygame.image.tobytes(frame, "RGB"))
        else:
            pygame.image.save(frame, os.path.join(args.frames, f"f{t:07.3f}.png" if args.times else f"f{i:05d}.png"))
        if i % 30 == 0:
            print(f"\r{i + 1}/{len(times)} frames", end="", flush=True)
    if proc:
        proc.stdin.close()
        proc.wait()
    print(f"\rdone: {len(times)} frames -> {args.render or args.frames}")

def play(args):
    info = pygame.display.Info()
    scale = args.scale or (min(1.0, (info.current_h - 100) / H) if info.current_h > 0 else 0.5)
    r = Renderer(scale)
    screen = pygame.display.set_mode((r.w, r.h))
    pygame.display.set_caption("Pygame soccer demo  -  Space pause, arrows seek, 1-3 scenes, S screenshot")
    clock, t, playing = pygame.time.Clock(), 0.0, True
    while True:
        dt = clock.tick(60) / 1000
        for e in pygame.event.get():
            if e.type == pygame.QUIT or (e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE):
                return
            if e.type == pygame.KEYDOWN:
                if e.key == pygame.K_SPACE:
                    playing = not playing
                elif e.key == pygame.K_RIGHT:
                    t = min(TOTAL - 0.01, t + 1)
                elif e.key == pygame.K_LEFT:
                    t = max(0.0, t - 1)
                elif e.key == pygame.K_r:
                    t = 0.0
                elif e.key in (pygame.K_1, pygame.K_2, pygame.K_3):
                    t = STARTS[e.key - pygame.K_1] + 0.01
                elif e.key == pygame.K_s:
                    pygame.image.save(screen, f"soccer_demo_{t:05.2f}.png")
        if playing:
            t = (t + dt) % TOTAL
        screen.blit(r.draw(t), (0, 0))
        pygame.display.flip()

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--render", metavar="OUT.mp4", help="export an MP4 (frame-exact)")
    ap.add_argument("--frames", metavar="DIR", help="export PNG frames")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--ss", type=float, default=2.0, help="export supersampling (2 = draw at 2160x3840, then scale down)")
    ap.add_argument("--scale", type=float, help="window scale (default: fit the screen)")
    ap.add_argument("--times", help="with --frames: comma-separated times to export instead of every frame")
    args = ap.parse_args()
    if args.render or args.frames:
        os.environ["SDL_VIDEODRIVER"] = "dummy"
    pygame.display.init()  # no audio needed, so no mixer
    pygame.font.init()
    try:
        export(args) if (args.render or args.frames) else play(args)
    finally:
        pygame.quit()

if __name__ == "__main__":
    main()
