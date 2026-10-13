"""Five README banner directions -> assets/styles/s1..s5. Pillow only."""
import os
from PIL import Image, ImageDraw, ImageFont

MASCOT_PATH = r"C:\Users\jieun\Desktop\★Ai driven project\10_MI Agent_db\assets\styles\mascot.png"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "styles")
FD = "C:/Windows/Fonts/"
S = 2  # supersample

NAME = "MI-SONAR"
TAG_KO = "스마트폰 시장 데이터, Claude / OpenCode에서 바로 조회"
ORG = "MI Sales · System LSI"
# (label, value, value color, pill text)
BADGES = [
    ("python", "3.10+", "#3776AB", "python 3.10+"),
    ("postgres", "read-only", "#336791", "postgres read-only"),
    ("storage", "minio", "#C72C48", "minio"),
    ("agent", "claude code · opencode", "#D97757", "claude code · opencode"),
    ("tests", "48 passing", "#4C1", "tests 48 passing"),
]

_fc = {}


def font(name, size):
    k = (name, size)
    if k not in _fc:
        _fc[k] = ImageFont.truetype(FD + name, int(size * S))
    return _fc[k]


def ko(t):
    return any("\uac00" <= c <= "\ud7a3" for c in t)


def tfont(t, size, bold=False, light=False):
    if ko(t):
        return font("malgunbd.ttf" if bold else "malgun.ttf", size)
    return font("segoeuib.ttf" if bold else "segoeuisl.ttf" if light else "segoeui.ttf", size)


class Canvas:
    def __init__(self, w, h, bg):
        self.w, self.h = w, h
        self.img = Image.new("RGB", (w * S, h * S), bg)
        self.d = ImageDraw.Draw(self.img)

    def rr(self, x0, y0, x1, y1, r, fill=None, outline=None):
        self.d.rounded_rectangle([x0 * S, y0 * S, x1 * S - 1, y1 * S - 1], r * S, fill=fill,
                                 outline=outline, width=S if outline else 0)

    def rect(self, x0, y0, x1, y1, fill):
        self.d.rectangle([x0 * S, y0 * S, x1 * S - 1, y1 * S - 1], fill=fill)

    def circ(self, cx, cy, r, fill=None, outline=None, width=1):
        self.d.ellipse([(cx - r) * S, (cy - r) * S, (cx + r) * S, (cy + r) * S], fill=fill,
                       outline=outline, width=int(width * S) if outline else 0)

    def text(self, x, y, t, f, fill, anchor="ls"):
        self.d.text((x * S, y * S), t, font=f, fill=fill, anchor=anchor)

    def width(self, t, f):
        return f.getlength(t) / S

    def tracked(self, x, y, t, f, fill, track):
        for ch in t:
            self.text(x, y, ch, f, fill)
            x += self.width(ch, f) + track
        return x

    def center_text(self, cx, y, t, f, fill):
        self.text(cx - self.width(t, f) / 2, y, t, f, fill)

    def save(self, name):
        p = os.path.join(OUT, name)
        self.img.resize((self.w, self.h), Image.LANCZOS).save(p)
        return p, (self.w, self.h)


def badge_w(c, label, value):
    f = tfont("x", 11)
    return c.width(label, f) + c.width(value, f) + 24


def badge(c, x, y, label, value, color):
    f = tfont("x", 11)
    lw = c.width(label, f) + 12
    w = lw + c.width(value, f) + 12
    c.rr(x, y, x + w, y + 20, 3, fill=color)
    c.rr(x, y, x + lw, y + 20, 3, fill="#555555")
    c.rect(x + lw - 4, y, x + lw, y + 20, "#555555")
    c.text(x + 6, y + 14, label, f, "#FFFFFF")
    c.text(x + lw + 6, y + 14, value, f, "#FFFFFF")
    return w


def badge_row(c, x, y, gap=8, center=False, maxx=None):
    ws = [badge_w(c, b[0], b[1]) for b in BADGES]
    if center:
        x = (c.w - (sum(ws) + gap * (len(ws) - 1))) / 2
    x0 = x
    for b, w in zip(BADGES, ws):
        badge(c, x, y, b[0], b[1], b[2])
        x += w + gap
    assert maxx is None or x - gap <= maxx, "badges overflow"
    return x0, x - gap


def pill_row(c, x, y):
    f = tfont("x", 14)
    for b in BADGES:
        w = c.width(b[3], f) + 16 + 14 + 6
        c.rr(x, y, x + w, y + 24, 12, fill="#18181B", outline="#27272A")
        c.circ(x + 14, y + 12, 3.5, fill=b[2])
        c.text(x + 24, y + 17.5, b[3], f, "#D4D4D8")
        x += w + 10


def sonar_glyph(c, ox, oy, size):
    k = size / 72
    cx, cy = ox + 22 * k, oy + 52 * k
    for r in (15, 29):
        R = r * k
        c.d.arc([(cx - R) * S, (cy - R) * S, (cx + R) * S, (cy + R) * S], 270, 360, fill="#FFFFFF",
                width=int(3 * k * S))
    c.circ(cx, cy, 4.5 * k, fill="#FFFFFF")


# 1 -------------------------------------------------------------------------
def s1():
    c = Canvas(1280, 400, "#0B0B0F")
    c.rect(96, 72, 256, 76, "#F59E0B")
    c.tracked(96, 232, NAME, font("segoeuib.ttf", 128), "#FFFFFF", -4)
    c.text(96, 290, TAG_KO, tfont(TAG_KO, 30), "#9CA3AF")
    badge_row(c, 96, 322)
    return c.save("s1_bun.png")


# 2 -------------------------------------------------------------------------
def s2():
    c = Canvas(1280, 480, "#111318")
    f1, f2 = tfont(NAME, 36, bold=True), tfont(TAG_KO, 22)
    sep = "  ·  "
    fs = tfont(sep, 22)
    total = c.width(NAME, f1) + c.width(sep, fs) + c.width(TAG_KO, f2)
    x = (1280 - total) / 2
    c.text(x, 62, NAME, f1, "#FFFFFF")
    x += c.width(NAME, f1)
    c.text(x, 62, sep, fs, "#9CA3AF")
    x += c.width(sep, fs)
    c.text(x, 62, TAG_KO, f2, "#9CA3AF")

    cx0, cy0 = 120, 100
    c.rr(cx0, cy0, cx0 + 1040, cy0 + 330, 12, fill="#1B1E26", outline="#2A2E3A")
    for i, col in enumerate(("#FF5F57", "#FEBC2E", "#28C840")):
        c.circ(cx0 + 22 + i * 22, cy0 + 20, 6, fill=col)
    c.center_text(640, cy0 + 26, "mi-sonar", tfont("x", 14), "#8B93A7")
    c.rect(cx0 + 1, cy0 + 40, cx0 + 1039, cy0 + 41, "#2A2E3A")

    m = font("consola.ttf", 20)
    green, white, grey = "#7EE2A8", "#E6E8EF", "#8B93A7"
    x0, y = cx0 + 28, cy0 + 76
    lh = 29
    c.text(x0, y, "PS>", m, green)
    px = x0 + c.width("PS> ", m)
    c.text(px, y, 'python query.py sql smartphone "SELECT month, SUM(units) FROM smartphone_market_data', m, white)
    y += lh
    c.text(x0 + c.width("PS> ", m), y, "WHERE country='JP' AND brand='Apple' GROUP BY 1 ORDER BY 1\"", m, white)
    y += lh
    c.text(x0, y, "month      SUM(units)", m, grey)
    for row in ("2026-07     1,184,000", "2026-08     1,062,500", "2026-09     1,431,200"):
        y += lh
        c.text(x0, y, row, m, white)
    y += lh + 4
    c.text(x0, y, "\u2714", font("seguisym.ttf", 20), green)
    c.text(x0 + c.width("\u2714 ", m), y, "3 rows · 0.09s · read-only", m, green)
    return c.save("s2_starship.png")


# 3 -------------------------------------------------------------------------
def s3():
    c = Canvas(1280, 400, "#0A0A0A")
    for gx in range(0, 1280, 24):
        for gy in range(0, 400, 24):
            c.rect(gx, gy, gx + 1, gy + 1, "#1F1F1F")
    for r, col in ((280, "#1A1A1A"), (200, "#212121"), (120, "#262626")):
        c.circ(1180, 200, r, outline=col, width=1)
    ix, iy = 96, 108
    c.rr(ix, iy, ix + 72, iy + 72, 16, fill="#3ECF8E")
    sonar_glyph(c, ix, iy, 72)
    c.text(192, iy + 72, NAME, font("segoeuib.ttf", 64), "#FFFFFF")
    c.text(96, 232, TAG_KO, tfont(TAG_KO, 26), "#A1A1AA")
    pill_row(c, 96, 262)
    return c.save("s3_supabase.png")


# 4 -------------------------------------------------------------------------
def s4():
    c = Canvas(1280, 400, "#FAFAF7")
    m = Image.open(MASCOT_PATH).convert("RGBA")
    m = m.crop(m.getchannel("A").getbbox())
    k = min(300 * S / m.width, 300 * S / m.height)
    m = m.resize((round(m.width * k), round(m.height * k)), Image.LANCZOS)
    c.img.paste(m, (120 * S + (300 * S - m.width) // 2, 50 * S + (300 * S - m.height) // 2), m)
    x = 460
    c.tracked(x, 164, NAME, font("segoeuib.ttf", 96), "#1F2937", -2)
    c.text(x, 216, TAG_KO, tfont(TAG_KO, 28), "#4B5563")
    c.text(x, 256, ORG, tfont(ORG, 20), "#6B7280")
    badge_row(c, x, 280, maxx=1160)
    c.rect(120, 360, 1160, 361, "#E5E7EB")
    return c.save("s4_mascot.png")


# 5 -------------------------------------------------------------------------
def s5():
    c = Canvas(1280, 420, "#FFFFFF")
    n = 120 * S
    logo = Image.new("RGB", (n, n), "#6366F1")
    ImageDraw.Draw(logo).polygon([(0, 0), (n, 0), (0, n)], fill="#0EA5E9")
    mask = Image.new("L", (n, n), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, n - 1, n - 1], 28 * S, fill=255)
    lx, ly = 640 - 60, 48
    c.img.paste(logo, (lx * S, ly * S), mask)
    sonar_glyph(c, lx, ly, 120)
    c.center_text(640, 250, NAME, font("segoeuib.ttf", 56), "#111827")
    c.center_text(640, 298, TAG_KO, tfont(TAG_KO, 24), "#6B7280")
    badge_row(c, 0, 334, center=True)
    return c.save("s5_vite.png")


if __name__ == "__main__":
    for fn in (s1, s2, s3, s4, s5):
        p, sz = fn()
        print(p, sz)
