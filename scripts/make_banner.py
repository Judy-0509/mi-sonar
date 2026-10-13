"""Generate assets/banner.png: 5x7 pixel-font title, scaled, high contrast."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

GLYPHS = {  # 5 wide x 7 tall, '#' = pixel
    "M": ["#...#", "##.##", "#.#.#", "#...#", "#...#", "#...#", "#...#"],
    "I": ["#####", "..#..", "..#..", "..#..", "..#..", "..#..", "#####"],
    "-": [".....", ".....", ".....", "#####", ".....", ".....", "....."],
    "S": [".####", "#....", "#....", ".###.", "....#", "....#", "####."],
    "O": [".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."],
    "N": ["#...#", "##..#", "#.#.#", "#..##", "#...#", "#...#", "#...#"],
    "A": [".###.", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"],
    "R": ["####.", "#...#", "#...#", "####.", "#.#..", "#..#.", "#...#"],
}
TEXT = "MI-SONAR"
PX = 14            # pixel size
GAP = 1            # glyph gap in pixels
BG, FG, ACCENT = (18, 22, 34), (120, 230, 180), (255, 200, 80)
W, H = 1200, 300

img = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(img)
for x in range(0, W, PX * 2):  # subtle pixel grid
    d.line([(x, 0), (x, H)], fill=(24, 30, 46))
for y in range(0, H, PX * 2):
    d.line([(0, y), (W, y)], fill=(24, 30, 46))

text_w = len(TEXT) * (5 + GAP) * PX - GAP * PX
x0, y0 = (W - text_w) // 2, 70
for i, ch in enumerate(TEXT):
    gx = x0 + i * (5 + GAP) * PX
    for r, row in enumerate(GLYPHS[ch]):
        for c, cell in enumerate(row):
            if cell == "#":
                x, y = gx + c * PX, y0 + r * PX
                d.rectangle([x, y, x + PX - 1, y + PX - 1], fill=ACCENT if ch == "-" else FG)

try:
    font = ImageFont.truetype("C:/Windows/Fonts/malgun.ttf", 28)  # Korean-capable on Windows
except OSError:
    font = ImageFont.load_default(size=28)
sub = "MI Sales · System LSI  |  스마트폰 시장 데이터를 Claude / OpenCode에서 바로 조회"
tw = d.textlength(sub, font=font)
d.text(((W - tw) // 2, 205), sub, fill=(220, 225, 235), font=font)

out = Path(__file__).resolve().parent.parent / "assets" / "banner.png"
out.parent.mkdir(exist_ok=True)
img.save(out)
print(out)
