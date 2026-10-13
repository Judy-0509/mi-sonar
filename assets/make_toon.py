import math, os
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
PREV = r"C:\Users\jieun\AppData\Local\Temp\claude\C--Users-jieun-Desktop--Ai-driven-project-10-MI-Agent-db\e336b76e-4152-4f10-a04c-a60896611dc3\scratchpad\banners"
W, H, S = 1200, 300, 2
FD = "C:/Windows/Fonts/"
PINK, BLUE, LIME, YEL, BLK, WHT, TEAL, SKIN, SKIN2 = (
    "#FF3E9A", "#35C4F0", "#B8F03C", "#FFE600", "#111111", "#FFFFFF", "#0E3B45", "#FFD1A8", "#E8A474")


def F(name, size):
    return ImageFont.truetype(FD + name, int(size * S))


IMP = "impact.ttf" if os.path.exists(FD + "impact.ttf") else "arialbd.ttf"
SC = (700, 150)  # starburst center
CX, CY, R = 430, 150, 100  # sonar


def P(pts):
    return [(x * S, y * S) for x, y in pts]


def ell(d, cx, cy, rx, ry, fill, w=6):
    d.ellipse(P([(cx - rx, cy - ry), (cx + rx, cy + ry)]), fill=fill, outline=BLK, width=w * S)


def poly(d, pts, fill, w=6):
    p = P(pts)
    d.polygon(p, fill=fill)
    d.line(p + [p[0]], fill=BLK, width=w * S, joint="curve")


def rr(d, box, r, fill, w=6, shadow=None):
    x0, y0, x1, y1 = box
    if shadow:
        d.rounded_rectangle(P([(x0 + shadow[0], y0 + shadow[1]), (x1 + shadow[0], y1 + shadow[1])]), r * S,
                            fill=shadow[2], outline=BLK, width=w * S)
    d.rounded_rectangle(P([(x0, y0), (x1, y1)]), r * S, fill=fill, outline=BLK, width=w * S)


def star(cx, cy, ro, ri, n, rot=0):
    pts = []
    for i in range(n * 2):
        r = ro if i % 2 == 0 else ri
        a = math.radians(rot + i * 180 / n)
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def text(d, xy, s, f, fill=WHT, sw=6, anchor="la", shadow=None):
    x, y = xy
    if shadow:
        d.text(((x + shadow[0]) * S, (y + shadow[1]) * S), s, font=f, fill=shadow[2],
               stroke_width=sw * S, stroke_fill=shadow[2], anchor=anchor)
    d.text((x * S, y * S), s, font=f, fill=fill, stroke_width=sw * S, stroke_fill=BLK, anchor=anchor)


def background(d, ang):
    n = 20
    for i in range(n):
        a0 = math.radians(ang + i * 360 / n)
        a1 = math.radians(ang + (i + 1) * 360 / n)
        c = PINK if i % 2 == 0 else YEL
        d.polygon(P([SC, (SC[0] + 1500 * math.cos(a0), SC[1] + 1500 * math.sin(a0)),
                     (SC[0] + 1500 * math.cos(a1), SC[1] + 1500 * math.sin(a1))]), fill=c)


def sonar(d, sweep, ghosts=0, dots=()):
    ell(d, CX, CY, R, R, TEAL, 8)
    for k in (0.66, 0.33):
        d.ellipse(P([(CX - R * k, CY - R * k), (CX + R * k, CY + R * k)]), outline=LIME, width=2 * S)
    d.line(P([(CX - R + 8, CY), (CX + R - 8, CY)]), fill=LIME, width=2 * S)
    d.line(P([(CX, CY - R + 8), (CX, CY + R - 8)]), fill=LIME, width=2 * S)

    def wedge(a, fill, outline):
        pts = [(CX, CY)] + [(CX + (R - 5) * math.cos(math.radians(a - t)),
                             CY + (R - 5) * math.sin(math.radians(a - t))) for t in range(0, 41, 5)]
        if outline:
            poly(d, pts, fill, 4)
        else:
            d.polygon(P(pts), fill=fill)

    for g in range(ghosts, 0, -1):
        wedge(sweep - g * 45, "#6E9A2A" if g == 2 else "#8CBF30", False)
    wedge(sweep, LIME, True)
    for (dx, dy) in dots:
        ell(d, CX + dx, CY + dy, 9, 9, YEL, 4)
    ell(d, CX, CY, 7, 7, BLK, 1)


def finger(d, ox=0, oy=0, sx=1.0, sy=1.0):
    def T(pts):
        return [(60 + ox + (x - 60) * sx, 150 + oy + (y - 150) * sy) for x, y in pts]
    poly(d, T([(60, 118), (150, 118), (160, 130), (160, 190), (60, 190)]), SKIN, 7)
    poly(d, T([(130, 124), (275, 124), (290, 137), (275, 150), (130, 150)]), SKIN, 7)
    ex, ey = T([(278, 137)])[0]
    ell(d, ex, ey, 14 * sx, 13 * sy, SKIN, 7)
    for i, y in enumerate((158, 172)):
        c = T([(120 + i * 6, y)])[0]
        ell(d, c[0], c[1], 32 * sx, 10 * sy, SKIN2, 6)
    th = T([(105, 118)])[0]
    ell(d, th[0], th[1], 24 * sx, 14 * sy, SKIN2, 6)
    rr(d, (28 + ox, 110 + oy, 66 + ox, 200 + oy), 8, BLUE, 7)
    return T([(300, 137)])[0]


def wordmark(d):
    text(d, (940, 14), "MI-SONAR", F(IMP, 74), WHT, 8, "ma", shadow=(6, 6, PINK))


def tagline(d):
    f = F("malgunbd.ttf", 21)
    rr(d, (706, 112, 1180, 160), 18, WHT, 5)
    poly(d, [(850, 158), (880, 158), (830, 180)], WHT, 5)
    d.rectangle(P([(853, 154), (877, 160)]), fill=WHT)
    d.text((943 * S, 136 * S), "Market Intelligence, 딸깍 한 번.", font=f, fill=BLK, anchor="mm")


def bubble(d, s):
    f = F("malgunbd.ttf", 17)
    w = d.textlength(s, font=f) / S + 26
    x0, y0 = 30, 18
    rr(d, (x0, y0, x0 + w, y0 + 40), 14, WHT, 5)
    poly(d, [(x0 + 36, y0 + 38), (x0 + 66, y0 + 38), (x0 + 50, y0 + 66)], WHT, 5)
    d.rectangle(P([(x0 + 40, y0 + 34), (x0 + 62, y0 + 41)]), fill=WHT)
    d.text(((x0 + w / 2) * S, (y0 + 20) * S), s, font=f, fill=BLK, anchor="mm")


def card(d, sc=1.0):
    cx, cy = 920, 199
    bw, bh = 500 * sc, 170 * sc
    x0, y0, x1, y1 = cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2
    k = lambda v: v * sc
    rr(d, (x0, y0, x1, y1), 14 * sc, WHT, 6, shadow=(9, 9, PINK))
    ft, fr = F("malgunbd.ttf", 19 * sc), F("malgunbd.ttf", 17 * sc)
    d.text(((x0 + k(20)) * S, (y0 + k(10)) * S), "일본 iPhone 판매량", font=ft, fill=BLK)
    for i, (m, v, lab) in enumerate([("7월", 0.8, "1.18M"), ("8월", 0.7, "1.06M"), ("9월", 1.0, "1.43M")]):
        yy = y0 + k(44 + i * 30)
        d.text(((x0 + k(20)) * S, (yy + k(4)) * S), m, font=fr, fill=BLK)
        rr(d, (x0 + k(64), yy + k(2), x0 + k(64 + 240 * v), yy + k(24)), 6 * sc, LIME, 4)
        d.text(((x0 + k(64 + 240 * v + 12)) * S, (yy + k(4)) * S), lab, font=fr, fill=BLK)
    py = y0 + k(138)
    rr(d, (x0 + k(20), py, x0 + k(250), py + k(24)), 12 * sc, BLK, 2)
    f1, f2 = F("malgunbd.ttf", 13 * sc), F("seguisym.ttf", 13 * sc)
    d.text(((x0 + k(34)) * S, (py + k(12)) * S), "✔", font=f2, fill=LIME, anchor="lm")
    d.text(((x0 + k(54)) * S, (py + k(12)) * S), "3 rows · read-only", font=f1, fill=WHT, anchor="lm")


def new(ang):
    im = Image.new("RGB", (W * S, H * S), PINK)
    d = ImageDraw.Draw(im)
    background(d, ang)
    return im, d


def done(im):
    return im.resize((W, H), Image.LANCZOS)


frames, durs = [], []
bg = 0.0

# 1 hover
for i in range(4):
    bg += 2
    im, d = new(bg)
    sonar(d, 20 + i * 18)
    finger(d, oy=[0, -3, 0, 3][i])
    wordmark(d); tagline(d); bubble(d, "일본 아이폰 월별 판매량?")
    frames.append(done(im)); durs.append(130)
# 2 click
for i, (sx, sy, ss, rings) in enumerate([(1.15, 0.9, 0.8, [34]), (1.0, 1.0, 1.2, [60, 100]), (1.0, 1.0, 1.0, [90, 130, 160])]):
    bg += 3
    im, d = new(bg)
    sonar(d, 100 + i * 25)
    for r in rings:
        rr_ = R + r * 0.45
        d.ellipse(P([(CX - rr_, CY - rr_), (CX + rr_, CY + rr_)]), outline=BLK, width=14 * S)
        d.ellipse(P([(CX - rr_, CY - rr_), (CX + rr_, CY + rr_)]), outline=LIME, width=6 * S)
    tip = finger(d, sx=sx, sy=sy)
    poly(d, star(tip[0] + 6, tip[1], 34 * ss, 16 * ss, 8, 10), WHT, 5)
    wordmark(d); tagline(d)
    tl = Image.new("RGBA", (W * S, H * S), (0, 0, 0, 0))
    text(ImageDraw.Draw(tl), (330, 70), "딸깍!", F("malgunbd.ttf", 62 * ss), WHT, 7, "mm")
    tl = tl.rotate(10, center=(330 * S, 70 * S), resample=Image.BICUBIC)
    im.paste(tl, (0, 0), tl)
    frames.append(done(im)); durs.append(100)
# 3 whirr
dots = [(-40, -30), (35, -50), (55, 20), (-20, 45), (10, -10), (-60, 10), (40, 55), (-30, -60), (0, 30), (60, -15)]
ang = 200
for i in range(10):
    bg += 14
    ang += 70
    im, d = new(bg)
    for j in range(16):
        a = math.radians(j * 22.5 + i * 11)
        r0, r1 = R + 14, R + 40 + 14 * (j % 3)
        d.line(P([(CX + r0 * math.cos(a), CY + r0 * math.sin(a)), (CX + r1 * math.cos(a), CY + r1 * math.sin(a))]), fill=BLK, width=14 * S)
        d.line(P([(CX + (r0 + 3) * math.cos(a), CY + (r0 + 3) * math.sin(a)), (CX + (r1 - 3) * math.cos(a), CY + (r1 - 3) * math.sin(a))]), fill=WHT, width=5 * S)
    sonar(d, ang, ghosts=2, dots=dots[:i])
    finger(d)
    wordmark(d); tagline(d)
    frames.append(done(im)); durs.append(60)
# 4 snap + hold
for i, sc in enumerate([1.12] + [1.0] * 10):
    bg += 3
    im, d = new(bg)
    sonar(d, ang + 40 + i * 12)
    finger(d)
    wordmark(d)
    card(d, sc)
    frames.append(done(im)); durs.append(90 if i == 0 else 150)

out = os.path.join(HERE, "a_toon.gif")
pal = [f.quantize(colors=48, method=Image.MEDIANCUT, dither=Image.NONE) for f in frames]
pal[0].save(out, save_all=True, append_images=pal[1:], duration=durs, loop=0, optimize=True, disposal=1)
os.makedirs(PREV, exist_ok=True)
for name, idx in (("hover", 1), ("click", 5), ("whirr", 12), ("end", len(frames) - 1)):
    frames[idx].save(os.path.join(PREV, f"toon_{name}.png"))
print(out, os.path.getsize(out), len(frames), sum(durs))
