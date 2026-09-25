"""把某个镜头已渲染的 EXR 帧过一遍后期，输出 PNG（调参用）。
    python3 post/preview.py <镜头输出目录> 帧号,帧号 [--scale 0.5]"""
import json, os, sys
import numpy as np
from PIL import Image
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from post import composite as C
d = sys.argv[1]; frames = [int(x) for x in sys.argv[2].split(',')]
P = json.load(open(os.path.join(d, 'post.json')))
if '--set' in sys.argv:
    P.update(json.loads(sys.argv[sys.argv.index('--set') + 1]))
cams = json.load(open(os.path.join(d, 'camera.json')))['frames']
for f in frames:
    Pf = C.params_at(P, f); Pf.setdefault('time', f / 24.0)
    img = C.process(os.path.join(d, 'exr', f'f{f:04d}.exr'), cams[str(f)], Pf)
    Image.fromarray((img * 255 + .5).astype(np.uint8)).save(os.path.join(d, f'post_{f:04d}.png'))
    print('post', f, flush=True)
