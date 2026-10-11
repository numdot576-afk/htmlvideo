"""How a retractable pitch works: a 34 s vertical (1080x1920) explainer drawn with plain pygame, with subtitles.

    py retractable_pitch.py                        play in a window   (python3 on Mac/Linux)
    py retractable_pitch.py --render pitch.mp4     export a frame-exact MP4 (needs ffmpeg, or: pip install imageio-ffmpeg)
    py retractable_pitch.py --frames out --fps 30  export PNG frames instead

Window keys: Space pause, Left/Right seek 1 s, 1-5 jump to a scene, R restart, S save a screenshot, Esc quit.

The stadium is the Tottenham Hotspur Stadium in London: its grass pitch is split into three steel trays
(about 3,000 tonnes each) that slide under the south stand in about 25 minutes, uncovering an artificial
NFL field underneath. Every frame is a pure function of time, so the window and the export always match.
"""
import argparse
import math
import os
import shutil
import subprocess
import sys

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
os.environ.setdefault("SDL_VIDEO_CENTERED", "1")
import pygame  # noqa: E402
import pygame.gfxdraw  # noqa: E402

W, H = 1080, 1920
TITLE = "HOW A RETRACTABLE PITCH WORKS"
SCENES = [6.5, 6.5, 7.0, 7.0, 6.5]
STARTS = [sum(SCENES[:i]) for i in range(len(SCENES))]
TOTAL = sum(SCENES)
ACC = (79, 209, 255)
WHITE = (255, 255, 255)

# Subtitles: (start time in the scene, text); *stars* mark highlighted words
SUBS = [
    [(0.0, "This stadium hides a *second pitch.*"), (2.6, "The whole grass pitch *slides away.*")],
    [(0.0, "Football needs *real grass,*"), (3.0, "but NFL games use *artificial turf.*")],
    [(0.0, "The grass grows on *three steel trays,*"), (3.3, "each weighing about *3,000 tonnes.*")],
    [(0.0, "They slide under the *south stand*"), (3.2, "in about *25 minutes.*")],
    [(0.0, "Underneath: a ready-made *NFL field.*"), (3.2, "Two sports. *One stadium.*")],
]

# ============================== easing ==============================
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

def out_back(x, s=1.7):
    x = clamp(x)
    return 1 + (s + 1) * (x - 1) ** 3 + s * (x - 1) ** 2

def bump(t, c, w):
    return clamp(1 - abs(t - c) / w) ** 2

def mix(c1, c2, k):
    return tuple(int(lerp(a, b, clamp(k))) for a, b in zip(c1, c2))

def shade(c, k):
    return tuple(max(0, min(255, int(v * k))) for v in c)

# ============================== 3D camera ==============================
def sub(a, b): return (a[0] - b[0], a[1] - b[1], a[2] - b[2])
def dot(a, b): return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
def cross(a, b): return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
def norm(a):
    n = math.sqrt(dot(a, a)) or 1.0
    return (a[0] / n, a[1] / n, a[2] / n)
def vlerp(a, b, k): return tuple(lerp(x, y, k) for x, y in zip(a, b))

NEAR = 0.3

class Camera:
    """Look-at pinhole camera. World: x east, y up, z north (the south stand is at -z)."""

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

def clip_poly(poly, axis, val, keep_ge=True):
    """Clip a polygon against the plane coordinate[axis] = val (keeps >= val, or <= val)."""
    out = []
    for i, a in enumerate(poly):
        b = poly[(i + 1) % len(poly)]
        ain = a[axis] >= val if keep_ge else a[axis] <= val
        bin_ = b[axis] >= val if keep_ge else b[axis] <= val
        if ain:
            out.append(a)
        if ain != bin_:
            k = (val - a[axis]) / (b[axis] - a[axis])
            out.append(tuple(a[j] + (b[j] - a[j]) * k for j in range(3)))
    return out

def clip_seg(p, q, clips):
    """Clip segment p-q against [(axis, val, keep_ge), ...]. Returns (p, q) or None."""
    t0, t1 = 0.0, 1.0
    for axis, val, ge in clips:
        a, b = p[axis] - val, q[axis] - val
        if not ge:
            a, b = -a, -b
        if a < 0 and b < 0:
            return None
        if a < 0:
            t0 = max(t0, a / (a - b))
        elif b < 0:
            t1 = min(t1, a / (a - b))
    if t0 >= t1:
        return None
    return vlerp(p, q, t0), vlerp(p, q, t1)

# ============================== the stadium ==============================
FW, FL, DEPTH = 72.0, 114.0, 1.2        # tray footprint (3 trays of 24 m x 114 m) and how deep the pit is
ZT = -FL / 2                            # the south end of the pit: the tunnel under the south stand
OUT = FL + 6                            # how far a tray travels to be completely under the stand
TRAY_X = [(-36.0, -12.0), (-12.0, 12.0), (12.0, 36.0)]
LAYERS = [(0.07, (66, 170, 76)), (0.33, (96, 64, 38)), (0.80, (122, 130, 142))]   # grass, soil, steel (m)
GRASS = [(44, 138, 56), (53, 156, 66)]
YD = 0.9144

def circle_pts(cx, cz, r, a0=0.0, a1=2 * math.pi, n=48):
    return [(cx + r * math.sin(a0 + (a1 - a0) * i / n), 0.0, cz + r * math.cos(a0 + (a1 - a0) * i / n)) for i in range(n + 1)]

def football_lines():
    HX, HZ = 34.0, 52.5
    L = [[(-HX, 0, HZ), (HX, 0, HZ), (HX, 0, -HZ), (-HX, 0, -HZ), (-HX, 0, HZ)], [(-HX, 0, 0), (HX, 0, 0)], circle_pts(0, 0, 9.15, n=64)]
    for s in (1, -1):
        L.append([(-20.16, 0, s * HZ), (-20.16, 0, s * 36), (20.16, 0, s * 36), (20.16, 0, s * HZ)])
        L.append([(-9.16, 0, s * HZ), (-9.16, 0, s * 47), (9.16, 0, s * 47), (9.16, 0, s * HZ)])
        a = math.acos(-5.5 / 9.15)
        L.append([(9.15 * math.sin(th), 0, s * (41.5 + 9.15 * math.cos(th))) for th in [a + (2 * math.pi - 2 * a) * i / 24 for i in range(25)]])
    return L

FOOT_LINES = football_lines()
NFL_HW, NFL_HL, NFL_EZ = 26.67 * YD, 60 * YD, 50 * YD   # half width, half length incl. end zones, goal line

# stands: (front-bottom left, front-bottom right, back-top right, back-top left)
STANDS = [
    [(-62, 7, -60), (62, 7, -60), (62, 44, -98), (-62, 44, -98)],      # south (the big one)
    [(62, 2, 62), (-62, 2, 62), (-62, 24, 90), (62, 24, 90)],          # north
    [(40, 2, -58), (40, 2, 60), (66, 24, 60), (66, 24, -58)],          # east
    [(-40, 2, 60), (-40, 2, -58), (-66, 24, -58), (-66, 24, 60)],      # west
]

# ============================== people ==============================
SKIN, HAIR = (198, 141, 104), (40, 28, 20)
CREW = dict(shirt=(255, 140, 30), shorts=(40, 44, 52), socks=(40, 44, 52), num=WHITE)

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
        self.fonts, self.cache = {}, {}
        self.bg = self._background()
        self.vig = self._vignette()

    # ---------- helpers ----------
    def px(self, v):
        return v * self.S

    def font(self, size, mono=False):
        key = (max(6, int(round(size * self.S / 2) * 2)), mono)
        if key not in self.fonts:
            names = ["consolas", "dejavusansmono", "couriernew"] if mono else ["arialblack", "segoeuiblack", "interdisplay", "inter", "helveticaneue", "dejavusans"]
            self.fonts[key] = find_font(names, key[0])
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
        for y in range(self.h):
            pygame.draw.line(bg, mix((5, 8, 18), (14, 24, 44), y / self.h), (0, y), (self.w, y))
        return bg

    def _vignette(self):
        small = pygame.Surface((90, 160), pygame.SRCALPHA)
        for y in range(160):
            for x in range(90):
                d = math.hypot((x - 45) / 45, (y - 80) / 80)
                small.set_at((x, y), (0, 0, 0, int(190 * clamp((d - 0.55) / 0.75) ** 1.6)))
        return pygame.transform.smoothscale(small, (self.w, self.h))

    # ---------- 3D drawing ----------
    def poly(self, pts, color, target=None):
        c = [self.cam.to_cam(p) for p in pts]
        c = clip_poly(c, 2, NEAR)
        if len(c) >= 3:
            pygame.draw.polygon(target or self.surf, color, [self.cam.screen(q) for q in c])

    def depth(self, pts):
        return sum(self.cam.to_cam(p)[2] for p in pts) / len(pts)

    def facing(self, pts, n):
        c = tuple(sum(p[i] for p in pts) / len(pts) for i in range(3))
        return dot(n, sub(self.cam.eye, c)) > 0

    def line3(self, pts, color, width_m, clips=(), k=1.0, target=None, step=3.0, min_w=1):
        """Polyline in 3D (drawn on up to fraction k of its length), clipped to clips, perspective-correct width."""
        target = target or self.surf
        segs, total = [], 0.0
        for a, b in zip(pts, pts[1:]):
            n = max(1, int(math.dist(a, b) / step))
            for i in range(n):
                p, q = vlerp(a, b, i / n), vlerp(a, b, (i + 1) / n)
                segs.append((p, q, math.dist(p, q)))
                total += segs[-1][2]
        left = total * clamp(k)
        for p, q, ln in segs:
            if left <= 0:
                break
            if ln > left:
                q = vlerp(p, q, left / ln)
            left -= ln
            cs = clip_seg(p, q, clips) if clips else (p, q)
            if not cs:
                continue
            a, b = self.cam.to_cam(cs[0]), self.cam.to_cam(cs[1])
            if a[2] < NEAR and b[2] < NEAR:
                continue
            if a[2] < NEAR:
                a = vlerp(a, b, (NEAR - a[2]) / (b[2] - a[2]))
            if b[2] < NEAR:
                b = vlerp(b, a, (NEAR - b[2]) / (a[2] - b[2]))
            wpx = max(min_w, int(width_m * self.cam.foc / ((a[2] + b[2]) / 2)))
            sa, sb = self.cam.screen(a), self.cam.screen(b)
            if max(abs(sa[0]), abs(sa[1]), abs(sb[0]), abs(sb[1])) > 30000:
                continue
            pygame.draw.line(target, color, sa, sb, wpx)
            if wpx > 3:
                pygame.draw.circle(target, color, sb, wpx / 2)

    # ---------- the pieces of the stadium ----------
    def stadium(self, items):
        """Apron, stands and roof lights; adds depth-sorted draw calls to items."""
        # apron around the pit (y = 0)
        for x0, x1, z0, z1 in [(-80, 80, 57, 100), (-80, 80, -100, -57), (-80, -36, -57, 57), (36, 80, -57, 57)]:
            self.poly([(x0, 0, z1), (x1, 0, z1), (x1, 0, z0), (x0, 0, z0)], (26, 40, 38))
        for i, (a, b, c, d) in enumerate(STANDS):
            n = norm(cross(sub(b, a), sub(d, a)))
            if not self.facing([a, b, c, d], n):
                continue
            def draw(a=a, b=b, c=c, d=d, i=i):
                self.poly([a, b, c, d], (30, 38, 62) if i else (36, 44, 72))
                for j in range(1, 22):
                    p, q = vlerp(a, d, j / 22), vlerp(b, c, j / 22)
                    pa, pb = self.cam.proj(p), self.cam.proj(q)
                    if pa and pb and max(map(abs, (pa[0], pa[1], pb[0], pb[1]))) < 30000:
                        pygame.draw.aaline(self.surf, (58, 70, 104), pa[:2], pb[:2])
                # roof edge with floodlights
                e1, e2 = (d[0], d[1] + 5, d[2]), (c[0], c[1] + 5, c[2])
                self.poly([d, c, e2, e1], (16, 18, 26))
                for j in range(12):
                    lp = self.cam.proj(vlerp(e1, e2, (j + 0.5) / 12))
                    if lp and abs(lp[0]) < 30000 and abs(lp[1]) < 30000:
                        r = clamp(0.9 * self.cam.foc / lp[2], 1.0, self.px(7))
                        pygame.draw.circle(self.glow, (200, 210, 230), lp[:2], r)
            items.append((self.depth([a, b, c, d]) + 20, draw))
        # south stand front: concourse wall with the tunnel the trays slide into
        def south_front():
            self.poly([(-62, 7, -60), (62, 7, -60), (62, 3.6, ZT), (-62, 3.6, ZT)], (22, 26, 36))
            self.poly([(-62, 3.6, ZT), (62, 3.6, ZT), (62, -DEPTH, ZT), (-62, -DEPTH, ZT)], (30, 34, 44))
            self.poly([(-36.5, 3.2, ZT + 0.02), (36.5, 3.2, ZT + 0.02), (36.5, -DEPTH, ZT + 0.02), (-36.5, -DEPTH, ZT + 0.02)], (5, 7, 10))
        items.append((self.depth([(0, 1, ZT)]) + 10, south_front))

    def pit(self):
        """The NFL field at the bottom of the pit and the pit walls (drawn before the trays)."""
        y = -DEPTH
        self.poly([(-36, y, 57), (36, y, 57), (36, y, ZT), (-36, y, ZT)], (36, 104, 48))
        self.poly([(-NFL_HW - 1.8, y, NFL_HL + 1.8), (NFL_HW + 1.8, y, NFL_HL + 1.8), (NFL_HW + 1.8, y, -NFL_HL - 1.8), (-NFL_HW - 1.8, y, -NFL_HL - 1.8)], (44, 122, 56))
        for s in (1, -1):
            self.poly([(-NFL_HW, y, s * NFL_EZ), (NFL_HW, y, s * NFL_EZ), (NFL_HW, y, s * NFL_HL), (-NFL_HW, y, s * NFL_HL)], (24, 44, 104))
        wl = (238, 242, 236)
        self.line3([(-NFL_HW, y, NFL_HL), (NFL_HW, y, NFL_HL), (NFL_HW, y, -NFL_HL), (-NFL_HW, y, -NFL_HL), (-NFL_HW, y, NFL_HL)], wl, 0.15)
        for yd in range(-50, 51, 5):
            z = yd * YD
            self.line3([(-NFL_HW, y, z), (NFL_HW, y, z)], wl, 0.2 if yd in (-50, 50) else 0.1)
        for yd in range(-49, 50):
            if yd % 5:
                z = yd * YD
                for x in (-NFL_HW, -3.1, 3.1, NFL_HW - 0.6):
                    self.line3([(x, y, z), (x + 0.6, y, z)], wl, 0.1)
        # pit walls (only the inside faces that face the camera)
        for pts, n in [([(-36, 0, 57), (36, 0, 57), (36, y, 57), (-36, y, 57)], (0, 0, -1)),
                       ([(36, 0, 57), (36, 0, ZT), (36, y, ZT), (36, y, 57)], (-1, 0, 0)),
                       ([(-36, 0, ZT), (-36, 0, 57), (-36, y, 57), (-36, y, ZT)], (1, 0, 0))]:
            if self.facing(pts, n):
                self.poly(pts, (70, 74, 82))

    def tray(self, items, i, d=0.0, lift=0.0, gx=0.0, seams=0.0):
        """One steel tray of grass: d = slid south (m), lift = raised (m), gx = pushed sideways (m)."""
        x0, x1 = TRAY_X[i][0] + gx, TRAY_X[i][1] + gx
        top, bot = lift, lift - DEPTH
        z0, z1 = ZT - d, -ZT - d
        in_pit = lift < 0.01
        zc = ZT if in_pit else -1e9   # inside the pit, anything south of the tunnel mouth is under the stand
        if in_pit and z1 <= ZT + 0.05:
            return

        def cz(pts):
            return clip_poly(pts, 2, zc) if in_pit else pts

        # the top: mowing stripes and the football lines, both moving with the tray
        def draw_top():
            for s in range(16):
                za, zb = lerp(z0, z1, s / 16), lerp(z0, z1, (s + 1) / 16)
                p = cz([(x0, top, zb), (x1, top, zb), (x1, top, za), (x0, top, za)])
                if len(p) >= 3:
                    self.poly(p, GRASS[s % 2])
            clips = [(0, x0 + 0.05, True), (0, x1 - 0.05, False)] + ([(2, ZT, True)] if in_pit else [])
            for L in FOOT_LINES:
                self.line3([(p[0] + gx, top + 0.01, p[2] - d) for p in L], (238, 242, 236), 0.12, clips=clips)
            if seams > 0.01:
                for sx in (x0, x1):
                    if -35 < sx - gx < 35:
                        self.line3([(sx, top + 0.02, max(z0, zc)), (sx, top + 0.02, z1)], (int(60 * seams), int(170 * seams), int(255 * seams)), 0.6, target=self.glow)
                        self.line3([(sx, top + 0.02, max(z0, zc)), (sx, top + 0.02, z1)], mix((240, 244, 240), (140, 220, 255), seams), 0.18)
        items.append((self.depth([(x0, top, max(z0, zc)), (x1, top, z1)]), draw_top))

        # the sides show the layers: grass, soil, steel (with a truss pattern)
        def side(pts_at, n):
            outline = pts_at(top), pts_at(bot)
            if not self.facing([outline[0][0], outline[0][1], outline[1][1], outline[1][0]], n):
                return
            def draw():
                y = top
                for thick, col in LAYERS:
                    a, b = pts_at(y), pts_at(y - thick)
                    p = cz([a[0], a[1], b[1], b[0]])
                    if len(p) >= 3:
                        self.poly(p, shade(col, 0.8 if n[0] else 1.0))
                    y -= thick
                a, b = pts_at(top - 0.4), pts_at(bot)
                steps = max(2, int(math.dist(a[0], a[1]) / 2.4))
                for j in range(steps):
                    p0, p1 = vlerp(a[0], a[1], j / steps), vlerp(b[0], b[1], (j + 1) / steps)
                    self.line3([p0, p1], (88, 94, 106), 0.05, clips=[(2, ZT, True)] if in_pit else ())
            ctr = vlerp(pts_at(top)[0], pts_at(bot)[1], 0.5)
            items.append((self.cam.to_cam(ctr)[2], draw))

        # in the pit, faces pressed against the pit walls are hidden (between trays, the neighbour's top covers them)
        if not (in_pit and z1 > -ZT - 0.05):
            side(lambda y: [(x0, y, z1), (x1, y, z1)], (0, 0, 1))         # north face
        if not in_pit:
            side(lambda y: [(x1, y, z0), (x0, y, z0)], (0, 0, -1))        # south face
        if not (in_pit and x1 > 35.9):
            side(lambda y: [(x1, y, z1), (x1, y, z0)], (1, 0, 0))         # east face
        if not (in_pit and x0 < -35.9):
            side(lambda y: [(x0, y, z0), (x0, y, z1)], (-1, 0, 0))        # west face

    def football_goal(self, items, zg, d, scale=1.0):
        """A football goal standing on the middle tray at goal line zg (moves with the tray)."""
        if scale < 0.02:
            return
        z = zg - d
        if z < ZT:
            return
        s = 1 if zg > 0 else -1
        h = 2.44 * scale

        def draw():
            for xs in (-3.66, 3.66):
                self.line3([(xs, 0, z), (xs, h, z + s * 1.0 * scale), (xs, 0, z + s * 2.0 * scale)], (215, 222, 228), 0.03, min_w=1)
            for j in range(9):
                x = -3.66 + 7.32 * j / 8
                self.line3([(x, h, z), (x, h, z + s * 1.0 * scale), (x, 0, z + s * 2.0 * scale)], (200, 206, 214), 0.025, min_w=1)
            for xs in (-3.66, 3.66):
                self.line3([(xs, 0, z), (xs, h, z)], (248, 250, 252), 0.12)
            self.line3([(-3.66, h, z), (3.66, h, z)], (248, 250, 252), 0.12)
        items.append((self.cam.to_cam((0, 1, z))[2] - 0.5, draw))

    def nfl_posts(self, items, k):
        """Yellow NFL goalposts at the back of each end zone, rising with k (0..1)."""
        if k < 0.02:
            return
        y0, gold = -DEPTH, (255, 208, 38)
        for s in (1, -1):
            z = s * NFL_HL
            bar = y0 + 3.05 * k

            def draw(z=z, s=s, bar=bar):
                self.line3([(0, y0, z + s * 1.8), (0, bar, z + s * 1.8), (0, bar, z)], gold, 0.22)
                self.line3([(-2.82, bar, z), (2.82, bar, z)], gold, 0.18)
                for x in (-2.82, 2.82):
                    self.line3([(x, bar, z), (x, bar + 9.1 * k, z)], gold, 0.14)
                for x in (-2.82, 2.82):
                    self.line3([(x, bar, z), (x, bar + 9.1 * k, z)], (90, 70, 10), 0.4, target=self.glow)
            items.append((self.cam.to_cam((0, 2, z))[2], draw))

    def shadow(self, p, r_m):
        c = self.cam.proj(p)
        if not c:
            return
        rx = r_m * self.cam.foc / c[2]
        ry = rx * clamp(abs(self.cam.f[1]) * 1.2, 0.22, 1.0)
        if 1 <= rx < 4000 and abs(c[0]) < 20000 and abs(c[1]) < 20000:
            pygame.gfxdraw.filled_ellipse(self.surf, int(c[0]), int(c[1]), int(rx), max(1, int(ry)), (0, 0, 0, 90))

    def person(self, p, kit, wave=0.0):
        """A cartoon groundsman, feet at p, facing the camera."""
        self.shadow(p, 0.42)
        c = self.cam.proj(p)
        if not c:
            return
        h = 1.8 * self.cam.foc / c[2]
        if h < 6:
            return
        s = self.surf
        P = lambda x, y: (c[0] + x * h, c[1] - y * h)
        lw, aw = max(2, int(0.075 * h)), max(2, int(0.06 * h))
        for hx in (-0.06, 0.06):
            pygame.draw.line(s, kit["shorts"], P(hx, 0.5), P(hx * 1.1, 0.02), lw + 1)
            pygame.draw.ellipse(s, (18, 18, 22), pygame.Rect(0, 0, 0.11 * h, 0.05 * h).move(P(hx * 1.1 - 0.055, 0.04)))
        hands = [(-0.17, 0.52), (0.2 + 0.05 * math.sin(wave), 0.95 + 0.06 * math.sin(wave * 2))]
        for sx, hd in zip((-0.135, 0.135), hands):
            pygame.draw.line(s, kit["shirt"], P(sx, 0.78), P(*hd), aw + 1)
            pygame.draw.circle(s, SKIN, P(*hd), aw * 0.75)
        torso = [P(-0.14, 0.8), P(0.14, 0.8), P(0.115, 0.48), P(-0.115, 0.48)]
        pygame.draw.polygon(s, kit["shirt"], torso)
        pygame.draw.line(s, (230, 235, 240), P(-0.13, 0.62), P(0.13, 0.62), max(1, int(0.03 * h)))   # hi-vis stripe
        hc, r = P(0, 0.91), 0.078 * h
        pygame.draw.circle(s, (20, 20, 24), hc, r + 1.2)
        pygame.draw.circle(s, SKIN, hc, r)
        pygame.draw.circle(s, HAIR, (hc[0], hc[1] - r * 0.45), r * 0.75, draw_top_left=True, draw_top_right=True)
        for ex in (-0.32, 0.32):
            pygame.draw.circle(s, WHITE, (hc[0] + ex * r, hc[1] + r * 0.05), max(1, r * 0.26))
            pygame.draw.circle(s, (12, 12, 14), (hc[0] + ex * r, hc[1] + r * 0.1), max(1, r * 0.13))

    # ---------- overlay ----------
    def callout(self, anchor, title, sub_, age, life, side=0):
        if anchor is None or age < 0 or age > life:
            return
        k_in, k_out = out_cubic(age / 0.5), 1 - seg(age, life - 0.35, life)
        ax, ay = anchor[0], anchor[1]
        if not (self.px(380) < ay < self.px(1300)) or not (-self.px(40) < ax < self.w + self.px(40)):
            return
        side = side or (1 if ax < self.w * 0.55 else -1)
        ex, ey = ax + side * self.px(80), ay - self.px(110)
        t1, t2 = self.text(title, 34, WHITE), self.text(sub_, 28, ACC)
        pw, ph = max(t1.get_width(), t2.get_width()) + self.px(56), self.px(104)
        x = clamp(ex if side > 0 else ex - pw, self.px(30), self.w - self.px(30) - pw)
        y = ey - ph / 2
        pygame.draw.line(self.surf, WHITE, (ax, ay), (lerp(ax, ex, k_in), lerp(ay, ey, k_in)), max(2, int(self.px(3))))
        pygame.draw.circle(self.surf, ACC, (ax, ay), self.px(9) * k_in)
        pygame.draw.circle(self.surf, WHITE, (ax, ay), self.px(16) * k_in, max(1, int(self.px(3))))
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

    def subtitle(self, words, age):
        """words: list of (word, highlighted); each word pops in 0.06 s after the previous one."""
        size, maxw = 58, self.px(900)
        sp = self.text(" ", size, WHITE).get_width()
        surfs = [self.text(wd, size, ACC if hl else WHITE) for wd, hl in words]
        lines, cur, cw = [], [], 0
        for s_ in surfs:
            if cur and cw + sp + s_.get_width() > maxw:
                lines.append((cur, cw))
                cur, cw = [], 0
            cw += (sp if cur else 0) + s_.get_width()
            cur.append(s_)
        lines.append((cur, cw))
        lh = self.px(74)
        bw, bh = max(w for _, w in lines) + self.px(80), len(lines) * lh + self.px(44)
        bx, by = (self.w - bw) / 2, self.px(1530) - bh
        ka = out_cubic(age / 0.3)
        self.surf.blit(self.panel(bw, bh, self.px(30), int(170 * ka), int(40 * ka)), (bx, by))
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

    def hud(self, main, subtxt, stat, bar, y0):
        x, y, w, h = self.px(150), self.px(y0), self.px(780), self.px(170)
        self.surf.blit(self.panel(w, h, self.px(32), 150), (x, y))
        self.surf.blit(self.text(main, 54, WHITE, mono=True), (x + self.px(40), y + self.px(30)))
        self.surf.blit(self.text(subtxt.upper(), 24, (190, 196, 205)), (x + self.px(40), y + self.px(100)))
        lab, val = self.text(stat[0], 22, ACC), self.text(stat[1], 40, WHITE, mono=True)
        self.surf.blit(lab, lab.get_rect(topright=(x + w - self.px(40), y + self.px(26))))
        self.surf.blit(val, val.get_rect(topright=(x + w - self.px(40), y + self.px(52))))
        bx, by, bw = x + self.px(40), y + h - self.px(28), w - self.px(80)
        pygame.draw.rect(self.surf, (60, 64, 72), (bx, by, bw, self.px(10)), border_radius=int(self.px(5)))
        pygame.draw.rect(self.surf, ACC, (bx, by, max(self.px(10), bw * clamp(bar)), self.px(10)), border_radius=int(self.px(5)))

    def title(self):
        """The title, on two lines when it is too wide for one. Returns where the HUD should start."""
        words = TITLE.split(" ")
        lines = [TITLE]
        if self.text(TITLE, 60, ACC).get_width() > self.px(960):
            best = min(range(1, len(words)), key=lambda i: max(self.text(" ".join(words[:i]), 60, ACC).get_width(), self.text(" ".join(words[i:]), 60, ACC).get_width()))
            lines = [" ".join(words[:best]), " ".join(words[best:])]
        for i, ln in enumerate(lines):
            t, sh = self.text(ln, 60, ACC), self.text(ln, 60, (8, 12, 20))
            r = t.get_rect(center=(self.w / 2, self.px(70 + i * 66 if len(lines) > 1 else 88)))
            self.glow.blit(t, r)
            for dx, dy in ((-3, 0), (3, 0), (0, -3), (0, 3)):
                self.surf.blit(sh, r.move(self.px(dx), self.px(dy)))
            self.surf.blit(t, r)
        return 186 if len(lines) > 1 else 150

    # ---------- the frame ----------
    def draw(self, T):
        T = T % TOTAL
        si = max(i for i in range(len(STARTS)) if T >= STARTS[i])
        t = T - STARTS[si]
        self.surf.blit(self.bg, (0, 0))
        self.glow.fill((0, 0, 0))
        hud, callouts, flash = [self.scene_pitch, self.scene_surfaces, self.scene_trays, self.scene_slide, self.scene_gameday][si](t)
        small = pygame.transform.smoothscale(self.glow, (max(1, self.w // 10), max(1, self.h // 10)))
        blur = pygame.transform.smoothscale(small, (self.w, self.h))
        self.surf.blit(blur, (0, 0), special_flags=pygame.BLEND_ADD)
        self.surf.blit(blur, (0, 0), special_flags=pygame.BLEND_ADD)
        self.surf.blit(self.glow, (0, 0), special_flags=pygame.BLEND_ADD)
        self.surf.blit(self.vig, (0, 0))
        cut = max([bump(T, s, 0.15) for s in STARTS[1:]] + [0])
        f = max(cut * 0.8, flash)
        if f > 0.01:
            self.surf.fill((int(255 * f),) * 3, special_flags=pygame.BLEND_ADD)
        for c in callouts:
            self.callout(*c)
        y0 = self.title()
        self.hud(*hud, t / SCENES[si], y0)
        subs = SUBS[si]
        j = max(i for i in range(len(subs)) if t >= subs[i][0])
        self.subtitle(parse_sub(subs[j][1]), t - subs[j][0])
        fade = max(1 - seg(T, 0, 0.3), seg(T, TOTAL - 0.4, TOTAL))
        if fade > 0:
            self.surf.fill((int(255 * (1 - fade)),) * 3, special_flags=pygame.BLEND_MULT)
        return self.surf

    def world(self, trays, goals=0.0, posts=0.0, seams=0.0, people=()):
        """Draw the whole stadium. trays: three (d, lift, gx) tuples."""
        self.pit()
        items = []
        self.stadium(items)
        for i, (d, lift, gx) in enumerate(trays):
            self.tray(items, i, d, lift, gx, seams)
        if goals > 0.02 and trays[1][1] < 0.01:
            for zg in (52.5, -52.5):
                self.football_goal(items, zg, trays[1][0], goals)
        self.nfl_posts(items, posts)
        for p, kit, wave in people:
            items.append((self.cam.to_cam(p)[2] - 0.3, lambda p=p, kit=kit, wave=wave: self.person(p, kit, wave)))
        for _, fn in sorted(items, key=lambda it: -it[0]):
            fn()

    # ---------- scene 1: the pitch ----------
    def scene_pitch(self, t):
        a = lerp(0.55, 0.12, in_out_cubic(seg(t, 0, 6.5)))
        self.cam.look((math.sin(a) * 150, lerp(105, 88, smooth(t / 6.5)), math.cos(a) * 150), (0, 0, -8), 44)
        d = 18 * in_out_cubic(seg(t, 3.6, 6.4))
        seams = smooth(seg(t, 1.8, 2.6)) * (0.7 + 0.3 * math.sin(t * 7))
        self.world([(d, 0, 0)] * 3, goals=1 - smooth(seg(t, 3.0, 3.6)), seams=seams)
        cs = [(self.cam.proj((0, 0.5, 10 - d)), "THE GRASS IS MOVING", "one whole pitch", t - 3.8, 2.5)]
        return ("THE PITCH", "Tottenham Hotspur Stadium", ("PITCHES", "2")), cs, 0.0

    # ---------- scene 2: two surfaces ----------
    def scene_surfaces(self, t):
        e = in_out_cubic(seg(t, 2.6, 5.6))
        self.cam.look(vlerp((15, 6.5, 74), (30, 22, 78), e), vlerp((0, 1.2, 50), (-2, -1, 26), e), lerp(40, 46, e))
        d = 46 * in_out_cubic(seg(t, 2.8, 5.6))
        self.world([(d, 0, 0)] * 3, goals=1.0 if t < 2.9 else 1 - smooth(seg(t, 2.9, 3.2)))
        cs = [(self.cam.proj((-12, 0.4, 40 - d)), "NATURAL GRASS", "for football", t - 0.3, 2.6),
              (self.cam.proj((-12, -DEPTH, 38)), "ARTIFICIAL TURF", "for the NFL", t - 3.6, 2.8)]
        return ("TWO SURFACES", "grass for football, turf for the NFL", ("SPORTS", "2")), cs, 0.0

    # ---------- scene 3: the trays ----------
    def scene_trays(self, t):
        trays = []
        for i in range(3):   # lift each tray out of the pit (bottom at ground level) and spread them apart
            k = out_back(seg(t, 0.2 + i * 0.25, 1.4 + i * 0.25), 1.3)
            trays.append((0.0, DEPTH * k + 0.01, (i - 1) * 5.0 * k))
        e = in_out_cubic(seg(t, 1.6, 4.2))   # wide shot of the lift, then push in on the cut end of the east tray
        self.cam.look(vlerp((62, 16, 98), (37.5, 1.7, 67.0), e), vlerp((4, 0.0, 38), (28.5, 0.7, 57), e), lerp(44, 40, e))
        man = (30.2, 0.0, 59.4)
        self.world(trays, people=[(man, CREW, t * 6)])
        kg = 3000 * out_cubic(seg(t, 3.3, 5.0))
        tx = TRAY_X[2][1] + 5.0
        cs = [(self.cam.proj((tx - 16.5, DEPTH - 0.2, 57)), "GRASS + SOIL", "growing on top", t - 4.0, 1.6, -1),
              (self.cam.proj((tx - 14, DEPTH - 0.9, 57)), "STEEL TRAY", "carries the pitch", t - 4.6, 1.6),
              (self.cam.proj((man[0], 1.95, man[2])), "PERSON FOR SCALE", "about 1.8 m", t - 5.3, 1.6)]
        return ("3 STEEL TRAYS", "grass and soil on a steel base", ("EACH", f"~{int(kg):,} T")), cs, 0.0

    # ---------- scene 4: the slide ----------
    def scene_slide(self, t):
        offs = [OUT * in_out_cubic(seg(t, 0.6 + i * 1.0, 3.6 + i * 1.0)) for i in range(3)]
        a = lerp(0.95, 0.75, in_out_cubic(seg(t, 0, 7)))
        self.cam.look((math.sin(a) * 140, 92, math.cos(a) * 140), (0, -2, -18), 46)
        self.world([(o, 0, 0) for o in offs])
        mins = int(25 * seg(t, 0.6, 5.6))
        cs = [(self.cam.proj((0, 3.5, ZT)), "SOUTH STAND", "the trays park underneath", t - 1.2, 3.0)]
        return ("SLIDING", "time-lapse", ("TIME", f"{mins:02d} MIN")), cs, 0.0

    # ---------- scene 5: game day ----------
    def scene_gameday(self, t):
        e = in_out_cubic(seg(t, 0.2, 5.0))
        self.cam.look(vlerp((22, 7.5, 76), (0, 105, 128), e), vlerp((0, 1.0, 46), (0, -2, -6), e), lerp(42, 46, e))
        self.world([(OUT, 0, 0)] * 3, posts=out_back(seg(t, 0.5, 1.6)))
        cs = [(self.cam.proj((0, -DEPTH + 7, NFL_HL)), "NFL GOALPOSTS", "for game day", t - 1.0, 2.2)]
        return ("GAME DAY", "the NFL field underneath", ("SPORTS", "2")), cs, 0.3 * bump(t, 3.2, 0.12)

def parse_sub(s):
    words, hl = [], False
    for w in s.split(" "):
        st = w.startswith("*")
        w = w.lstrip("*")
        end = w.endswith("*")
        w = w.rstrip("*")
        words.append((w, hl or st))
        hl = (hl or st) and not end
    return words

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
    times = [float(x) for x in args.times.split(",")] if args.times else [i / args.fps for i in range(int(round(TOTAL * args.fps)))]
    proc = None
    if args.render:
        exe = ffmpeg_exe()
        if not exe:
            sys.exit("ffmpeg not found: install it, or `pip install imageio-ffmpeg`, or use --frames DIR")
        proc = subprocess.Popen([exe, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(args.fps), "-i", "-",
                                 "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "17", "-preset", "medium", "-movflags", "+faststart", args.render], stdin=subprocess.PIPE)
    else:
        os.makedirs(args.frames, exist_ok=True)
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
    print(f"Opening the window ({r.w}x{r.h}) ...", flush=True)
    screen = pygame.display.set_mode((r.w, r.h))
    pygame.display.set_caption("How a retractable pitch works  -  Space pause, arrows seek, 1-5 scenes, S screenshot")
    print("Playing. Space pause, Left/Right seek, 1-5 scenes, S screenshot, Esc or close the window to quit.", flush=True)
    clock, t, playing = pygame.time.Clock(), 0.0, True
    keys = [pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4, pygame.K_5]
    while True:
        dt = clock.tick(60) / 1000
        for e in pygame.event.get():
            if e.type == pygame.QUIT or (e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE):
                print("Window closed.", flush=True)
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
                elif e.key in keys:
                    t = STARTS[keys.index(e.key)] + 0.01
                elif e.key == pygame.K_s:
                    pygame.image.save(screen, f"retractable_pitch_{t:05.2f}.png")
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
    print(f"How a retractable pitch works: pygame {pygame.version.ver}, Python {sys.version.split()[0]}", flush=True)
    pygame.display.init()
    pygame.font.init()
    try:
        export(args) if (args.render or args.frames) else play(args)
    finally:
        pygame.quit()

if __name__ == "__main__":
    main()
