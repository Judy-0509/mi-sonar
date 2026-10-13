import math, os, random
from PIL import Image, ImageDraw
from make_drafts import OUT, W, H, font, SYM, draw_mixed, seg_width

BG, WIN, BAR = (13, 17, 23), (22, 27, 34), (33, 38, 45)
GREEN, TXT, DIM = (86, 211, 100), (230, 237, 243), (139, 148, 158)
mono, monob = font("consola.ttf", 15), font("consolab.ttf", 18)
ttl, big = font("malgun.ttf", 13), font("malgunbd.ttf", 30)
ASK = "> \uc77c\ubcf8 \uc544\uc774\ud3f0 \uc6d4\ubcc4 \ud310\ub9e4\ub7c9 \ubcf4\uc5ec\uc918"
X0, Y0 = 44, 110
HAND = [(10, 0), (17, 0), (17, 15), (21, 13), (26, 15), (27, 18), (31, 19), (32, 23), (32, 31),
        (27, 39), (11, 39), (5, 29), (1, 21), (4, 18), (9, 23)]
FRAG = ["SELECT month, SUM(units) FROM smartphone_market_data", "scanning smartphone_market_data",
        "firm=Counterpoint", "rows 184,220 \u2192 12", "GROUP BY month", "WHERE country='JP'",
        "brand='Apple' AND year=2026", "partition scan ok", "cache miss", "join dim_country"]


def chrome():
    im = Image.new("RGBA", (W, H), BG + (255,))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((20, 14, 1180, 288), 12, fill=WIN, outline=(48, 54, 61))
    d.rounded_rectangle((20, 14, 1180, 50), 12, fill=BAR)
    d.rectangle((20, 34, 1180, 50), fill=BAR)
    for i, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        d.ellipse((44 + i * 22 - 6, 26, 44 + i * 22 + 6, 38), fill=c)
    d.text((600 - d.textlength("mi-sonar", font=ttl) / 2, 24), "mi-sonar", font=ttl, fill=DIM)
    d.text((1160 - d.textlength("MI-SONAR", font=monob), 25), "MI-SONAR", font=monob, fill=(255, 166, 128))
    return im


def hand(im, tip, dy=0):
    d = ImageDraw.Draw(im)
    pts = [(tip[0] - 13 + x, tip[1] + dy + y) for x, y in HAND]
    d.polygon(pts, fill=(255, 255, 255))
    d.line(pts + [pts[0]], fill=(0, 0, 0), width=2, joint="curve")


def rings(im, tip, age):
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)
    for k in range(3):
        a = age - k * 0.8
        if a < 0 or a > 4:
            continue
        r, al = 14 + a * 42, int(255 * (1 - a / 4))
        od.ellipse((tip[0] - r, tip[1] - r, tip[0] + r, tip[1] + r), outline=(86, 211, 100, al), width=3)
    im.alpha_composite(ov)


def label(im, pos, scale):
    f = font("malgunbd.ttf", int(44 * scale))
    t = "\ub534\uae4d!"
    L = Image.new("RGBA", (260, 110), (0, 0, 0, 0))
    ImageDraw.Draw(L).text((130, 55), t, font=f, fill=(255, 255, 255), anchor="mm", stroke_width=5, stroke_fill=(0, 0, 0))
    L = L.rotate(-8, resample=Image.BICUBIC, expand=True)
    im.alpha_composite(L, (int(pos[0] - L.width / 2), int(pos[1] - L.height / 2)))


def ask_base(tip_dy, with_hand=True):
    im = chrome()
    d = ImageDraw.Draw(im)
    d.text((X0, Y0), ASK[:2], font=big, fill=GREEN)
    d.text((X0 + d.textlength(ASK[:2], font=big), Y0), ASK[2:], font=big, fill=TXT)
    tip = (X0 + d.textlength(ASK, font=big) + 30, Y0 + 2)
    if with_hand:
        hand(im, tip, tip_dy)
    return im, tip


def whirr(i, tip):
    im = chrome()
    d = ImageDraw.Draw(im)
    rnd = random.Random(i)
    for row in range(11):
        t = rnd.choice(FRAG + ["0x%06X  %d%%" % (rnd.randrange(1 << 24), rnd.randrange(100))])
        x = 40 + rnd.randrange(0, 500)
        for off, c in ((-14, 28), (0, 70), (13, 38)):
            d.text((x, 58 + row * 22 + off), t, font=mono, fill=(c, c + 40, c + 20))
    return im, tip


def answer():
    im = chrome()
    d = ImageDraw.Draw(im)
    sym = SYM(17)
    f = font("malgunbd.ttf", 20)
    data = [("2026-07", 1184000), ("2026-08", 1062500), ("2026-09", 1431200)]
    d.text((X0, 66), "\uc6d4", font=f, fill=DIM)
    d.text((X0 + 170, 66), "iPhone \ud310\ub9e4\ub7c9 (\uc77c\ubcf8)", font=f, fill=DIM)
    for i, (m, v) in enumerate(data):
        y = 102 + i * 32
        d.text((X0, y), m, font=f, fill=TXT)
        d.text((X0 + 170, y), f"{v:>10,}", font=f, fill=TXT)
        d.rectangle((X0 + 330, y + 6, X0 + 330 + int(v / 1431200 * 360), y + 22), fill=GREEN)
    draw_mixed(d, (X0, 214), "\u2714 3 rows \u00b7 0.09s \u00b7 read-only", f, sym, GREEN)
    return im


def main():
    frames, durs = [], []
    add = lambda im, ms: (frames.append(im.convert("RGB")), durs.append(ms))
    for k in range(4):
        im, tip = ask_base(2 if k % 2 else 0)
        add(im, 150)
    prev = {}
    for k, sc in enumerate((0.8, 1.1, 1.0)):  # click
        im, tip = ask_base(4)
        rings(im, tip, k * 0.5)
        label(im, (tip[0] + 90, tip[1] - 40), sc)
        add(im, 90)
        prev[k] = im
    peak = prev[1]
    mid = None
    for i in range(12):
        im, _ = whirr(i, tip)
        if i < 6:
            rings(im, tip, 1.5 + i * 0.6)
        if i == 5:
            mid = im.copy()
        add(im, 58)
    add(answer(), 90)
    add(answer(), 1500)
    p = os.path.join(OUT, "a_click.gif")
    frames[0].save(p, save_all=True, append_images=frames[1:], duration=durs, loop=0, optimize=True)
    peak.convert("RGB").save(os.path.join(OUT, "a_click_f_click.png"))
    mid.convert("RGB").save(os.path.join(OUT, "a_click_f_whirr.png"))
    frames[-1].save(os.path.join(OUT, "a_click_f_end.png"))
    print(p, os.path.getsize(p), len(frames), sum(durs))


if __name__ == "__main__":
    main()
