import math, os
from PIL import Image, ImageDraw, ImageFont

OUT = os.path.dirname(os.path.abspath(__file__))
W, H = 1200, 300
FD = "C:/Windows/Fonts/"


def font(name, size, fallback="malgun.ttf"):
    p = FD + name
    if not os.path.exists(p):
        p = FD + fallback
    return ImageFont.truetype(p, size)


SYM = lambda s: font("seguisym.ttf", s)


def seg_width(d, text, f, sf):
    return sum(d.textlength(c, font=sf if c == "\u2714" else f) for c in text)


def draw_mixed(d, xy, text, f, sf, fill):
    x, y = xy
    for c in text:
        ff = sf if c == "\u2714" else f
        d.text((x, y), c, font=ff, fill=fill)
        x += d.textlength(c, font=ff)


# ---------- A: terminal ----------
def make_a():
    bg, win, bar = (13, 17, 23), (22, 27, 34), (33, 38, 45)
    mono = font("consola.ttf", 15)
    sym = SYM(15)
    ttl = font("malgun.ttf", 13)
    cmd = ("PS> python query.py sql smartphone \"SELECT country, SUM(units) FROM "
           "smartphone_market_data WHERE brand='Apple' GROUP BY 1\"")
    rows = [("country", "SUM(units)"), ("Japan", "12,480,000"), ("Korea", "9,215,300"),
            ("US", "7,640,120"), ("Others", "5,102,980")]
    final = "\u2714 4 rows \u00b7 0.12s \u00b7 read-only"

    def frame(nchars, nrows, show_final, cursor):
        im = Image.new("RGB", (W, H), bg)
        d = ImageDraw.Draw(im)
        d.rounded_rectangle((20, 14, 1180, 288), 12, fill=win, outline=(48, 54, 61))
        d.rounded_rectangle((20, 14, 1180, 50), 12, fill=bar)
        d.rectangle((20, 34, 1180, 50), fill=bar)
        for i, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
            cx = 44 + i * 22
            d.ellipse((cx - 6, 26, cx + 6, 38), fill=c)
        t = "mi-sonar \u2014 powershell"
        d.text((600 - d.textlength(t, font=ttl) / 2, 24), t, font=ttl, fill=(139, 148, 158))
        wm = font("consolab.ttf", 18).getname() and font("consolab.ttf", 18)
        w = d.textlength("MI-SONAR", font=wm)
        d.text((1160 - w, 25), "MI-SONAR", font=wm, fill=(255, 166, 128))
        x0, y = 40, 66
        shown = cmd[:nchars]
        d.text((x0, y), shown[:4], font=mono, fill=(86, 211, 100))
        d.text((x0 + d.textlength("PS> ", font=mono), y), shown[4:], font=mono, fill=(230, 237, 243))
        if cursor:
            cx = x0 + d.textlength(shown, font=mono)
            if nrows == 0 and not show_final:
                d.rectangle((cx + 1, y + 1, cx + 9, y + 19), fill=(230, 237, 243))
        for i in range(nrows):
            a, b = rows[i]
            col = (139, 148, 158) if i == 0 else (201, 209, 217)
            d.text((x0, y + 32 + i * 24), f"{a:<12}{b:>12}", font=mono, fill=col)
        if show_final:
            ly = y + 32 + 5 * 24 + 10
            draw_mixed(d, (x0, ly), final, mono, sym, (86, 211, 100))
            d.text((x0 + 8 + seg_width(d, final, mono, sym), ly), "\u2588", font=mono, fill=(230, 237, 243))
        return im

    frames, durs = [], []
    n = len(cmd)
    for k in range(1, 19):
        frames.append(frame(min(n, k * 7), 0, False, True)); durs.append(70)
    frames.append(frame(n, 0, False, False)); durs.append(300)
    for r in range(1, 6):
        frames.append(frame(n, r, False, False)); durs.append(220)
    frames.append(frame(n, 5, True, False)); durs.append(300)
    frames.append(frame(n, 5, True, False)); durs.append(1500)
    p = os.path.join(OUT, "a_terminal.gif")
    frames[0].save(p, save_all=True, append_images=frames[1:], duration=durs, loop=0, optimize=True)
    return p


# ---------- B: radar ----------
def make_b():
    cx, cy, R = 300, 150, 125
    base = Image.new("RGBA", (W, H), (4, 10, 24, 255))
    d = ImageDraw.Draw(base)
    for r in (R, R * 3 // 4, R // 2, R // 4):
        d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(20, 110, 60, 255), width=1)
    d.line((cx - R, cy, cx + R, cy), fill=(15, 80, 45, 255))
    d.line((cx, cy - R, cx, cy + R), fill=(15, 80, 45, 255))
    # wordmark
    size = 130
    while True:
        wf = font("impact.ttf", size, "arialbd.ttf")
        tw = d.textlength("MI-SONAR", font=wf)
        if tw <= 540:
            break
        size -= 4
    tx = 620
    d.text((tx + 4, 40 + 4), "MI-SONAR", font=wf, fill=(0, 90, 40, 255))
    d.text((tx, 40), "MI-SONAR", font=wf, fill=(120, 255, 170, 255))
    sub = "\uc2a4\ub9c8\ud2b8\ud3f0 \uc2dc\uc7a5 \ub370\uc774\ud130, \ubb3b\uae30\ub9cc \ud558\uba74 \ub428."
    ss = 26
    while True:
        sf = font("malgunbd.ttf", ss)
        if d.textlength(sub, font=sf) <= 540:
            break
        ss -= 1
    d.text((tx, 40 + size + 25), sub, font=sf, fill=(190, 230, 205, 255))
    lab = font("consola.ttf", 12)
    # scanlines (static)
    sl = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sl)
    for y in range(0, H, 3):
        sd.line((0, y, W, y), fill=(0, 0, 0, 70))
    pings = [("iPhone", 30, 85), ("Galaxy", 110, 60), ("Japan", 190, 95),
             ("Q3", 250, 45), ("MinIO", 320, 80)]
    N = 30
    frames = []
    for i in range(N):
        ang = 360.0 * i / N  # sweep angle, degrees clockwise from east
        im = base.copy()
        ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        od = ImageDraw.Draw(ov)
        for s in range(40):  # trailing wedge, fading
            a1 = ang - s * 1.5
            alpha = int(110 * (1 - s / 40))
            od.pieslice((cx - R, cy - R, cx + R, cy + R), a1 - 1.5, a1, fill=(40, 255, 120, alpha))
        od.line((cx, cy, cx + R * math.cos(math.radians(ang)), cy + R * math.sin(math.radians(ang))),
                fill=(150, 255, 190, 255), width=2)
        for name, pa, pr in pings:
            age = (ang - pa) % 360
            if age > 200:
                continue
            k = 1 - age / 200
            px = cx + pr * math.cos(math.radians(pa))
            py = cy + pr * math.sin(math.radians(pa))
            for gr, ga in ((11, 40), (7, 90), (4, 255)):
                od.ellipse((px - gr, py - gr, px + gr, py + gr), fill=(120, 255, 170, int(ga * k)))
            od.text((px + 9, py - 7), name, font=lab, fill=(200, 255, 220, int(255 * k)))
        im = Image.alpha_composite(im, ov)
        # moving CRT band
        band = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        by = int((i * 20) % (H + 40)) - 20
        ImageDraw.Draw(band).rectangle((0, by, W, by + 16), fill=(120, 255, 170, 14))
        im = Image.alpha_composite(im, band)
        im = Image.alpha_composite(im, sl).convert("RGB")
        frames.append(im)
    p = os.path.join(OUT, "b_radar.gif")
    frames[0].save(p, save_all=True, append_images=frames[1:], duration=80, loop=0, optimize=True)
    return p


# ---------- C: neo-brutalist ----------
def star(d, c, r, fill, n=4, inner=0.35, rot=0):
    pts = []
    for i in range(n * 2):
        rr = r if i % 2 == 0 else r * inner
        a = math.radians(rot + i * 180 / n - 90)
        pts.append((c[0] + rr * math.cos(a), c[1] + rr * math.sin(a)))
    d.polygon(pts, fill=fill, outline=(0, 0, 0))
    d.line(pts + [pts[0]], fill=(0, 0, 0), width=3)


def make_c():
    bg = (255, 230, 0)
    im = Image.new("RGBA", (W, H), bg + (255,))
    d = ImageDraw.Draw(im)
    wf = font("impact.ttf", 140, "arialbd.ttf")
    t = "MI-SONAR"
    tw = d.textlength(t, font=wf)
    x, y = (W - tw) / 2, 30
    for dx, dy in ((9, 9),):
        d.text((x + dx, y + dy), t, font=wf, fill=(255, 255, 255), stroke_width=4, stroke_fill=(0, 0, 0))
    d.text((x, y), t, font=wf, fill=(0, 0, 0))
    # stars
    for c, r, f, n in (((70, 150), 22, (255, 107, 53), 4), ((1130, 150), 22, (255, 255, 255), 4),
                       ((340, 22), 14, (255, 107, 53), 4), ((880, 25), 16, (255, 255, 255), 4),
                       ((250, 280), 13, (255, 255, 255), 8), ((960, 280), 13, (255, 107, 53), 8),
                       ((612, 268), 0, None, 4)):
        if f:
            star(d, c, r, f, n=n, inner=0.38 if n == 4 else 0.55)

    f = font("malgunbd.ttf", 26)
    sf = SYM(26)

    def sticker(text, center, angle, fill=(255, 255, 255)):
        tmp = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        w = int(seg_width(tmp, text, f, sf)) + 36
        h = 52
        L = Image.new("RGBA", (w + 20, h + 20), (0, 0, 0, 0))
        ld = ImageDraw.Draw(L)
        ld.rounded_rectangle((10 + 6, 10 + 6, 10 + w + 6 - 1, 10 + h + 6 - 1), 8, fill=(0, 0, 0, 255))
        ld.rounded_rectangle((10, 10, 10 + w - 1, 10 + h - 1), 8, fill=fill + (255,), outline=(0, 0, 0, 255), width=4)
        draw_mixed(ld, (10 + 18, 10 + 6), text, f, sf, (0, 0, 0, 255))
        L = L.rotate(angle, resample=Image.BICUBIC, expand=True)
        im.alpha_composite(L, (int(center[0] - L.width / 2), int(center[1] - L.height / 2)))

    sticker("SQL \ubab0\ub77c\ub3c4 \ub428", (190, 60), 6)
    sticker("\uc77d\uae30 \uc804\uc6a9 \u2714", (1010, 62), -5, fill=(180, 255, 200))
    sticker("Claude \u00b7 OpenCode", (185, 222), -5)
    sticker("\uc6d0\ubcf8 PDF \ubc14\ub85c \ubc1b\uae30", (1010, 222), 5, fill=(255, 190, 160))
    # pill
    pf = font("malgunbd.ttf", 22)
    pt = "MI Sales \u00b7 System LSI"
    pw = int(d.textlength(pt, font=pf)) + 48
    px = (W - pw) // 2
    d.rounded_rectangle((px, 245, px + pw, 287), 21, fill=(0, 0, 0))
    d.text((px + 24, 249), pt, font=pf, fill=(255, 255, 255))
    p = os.path.join(OUT, "c_brutal.png")
    im.convert("RGB").save(p)
    return p


if __name__ == "__main__":
    for nm in ("malgun.ttf", "malgunbd.ttf"):
        f = font(nm, 24)
        ok = f.getmask("\ubab0").getbbox() and bytes(f.getmask("\ubab0")) != bytes(f.getmask("\uffff"))
        print(nm, f.getname(), "Korean glyph ok:", bool(ok))
    for p in (make_a(), make_b(), make_c()):
        print(p, os.path.getsize(p))
