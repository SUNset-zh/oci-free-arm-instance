"""Tile screenshots into a labelled contact sheet: python sheet.py <dir> <out.jpg> [cols] [width]"""
import glob, os, sys
from PIL import Image, ImageDraw, ImageFont

d, out = sys.argv[1], sys.argv[2]
cols = int(sys.argv[3]) if len(sys.argv) > 3 else 6
tw = int(sys.argv[4]) if len(sys.argv) > 4 else 300
files = sorted(glob.glob(os.path.join(d, 't*.jpg')))
th = int(tw * 1920 / 1080)
rows = (len(files) + cols - 1) // cols
sheet = Image.new('RGB', (cols * (tw + 8) + 8, rows * (th + 36) + 8), (40, 40, 46))
font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 20)
dr = ImageDraw.Draw(sheet)
for i, f in enumerate(files):
    im = Image.open(f).convert('RGB').resize((tw, th), Image.LANCZOS)
    x, y = 8 + (i % cols) * (tw + 8), 8 + (i // cols) * (th + 36)
    sheet.paste(im, (x, y + 28))
    dr.text((x + 4, y + 4), os.path.basename(f)[1:-4].lstrip('0') + 's', fill=(255, 220, 120), font=font)
sheet.save(out, quality=88)
print(out, sheet.size)
