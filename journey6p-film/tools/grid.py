import sys
from PIL import Image
# usage: grid.py out.png cols img1 img2 ...
out, cols, files = sys.argv[1], int(sys.argv[2]), sys.argv[3:]
ims = [Image.open(f).convert('RGB') for f in files]
w, h = ims[0].size
rows = (len(ims) + cols - 1) // cols
g = Image.new('RGB', (w * cols, h * rows))
for i, im in enumerate(ims):
    g.paste(im.resize((w, h)), ((i % cols) * w, (i // cols) * h))
g.save(out)
