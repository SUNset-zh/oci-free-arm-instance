"""把一个镜头渲染好的 EXR 逐帧过后期，放大到 1080×1920，存成成片用的 PNG（已存在的跳过）。

    python3 post/grade_shot.py 镜头目录 [起始帧 结束帧]"""
import json
import os
import sys

import numpy as np
from PIL import Image, ImageFilter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from post import composite as C

OW, OH = 1080, 1920


def main(d, f0=None, f1=None):
    P = json.load(open(os.path.join(d, 'post.json')))
    cams = json.load(open(os.path.join(d, 'camera.json')))['frames']
    if P.get('spray') and os.path.exists(os.path.join(d, 'horses.json')):
        P['spray']['tracks'] = json.load(open(os.path.join(d, 'horses.json')))
    out = os.path.join(d, 'graded'); os.makedirs(out, exist_ok=True)
    frames = sorted(int(k) for k in cams)
    if f0 is not None:
        frames = [f for f in frames if f0 <= f <= f1]
    for f in frames:
        dst = os.path.join(out, f'g{f:04d}.png')
        src = os.path.join(d, 'exr', f'f{f:04d}.exr')
        if os.path.exists(dst) or not os.path.exists(src):
            continue
        Pf = C.params_at(P, f); Pf.setdefault('time', f / 24.0)
        img = C.process(src, C.frame_cam(cams, f), Pf)
        im = Image.fromarray((np.clip(img, 0, 1) * 255 + .5).astype(np.uint8))
        if im.size != (OW, OH):
            im = im.resize((OW, OH), Image.LANCZOS).filter(ImageFilter.UnsharpMask(radius=1.4, percent=45, threshold=1))
        im.save(dst + '.tmp.png'); os.replace(dst + '.tmp.png', dst)
        print('graded', d.rsplit('/', 1)[-1], f, flush=True)


if __name__ == '__main__':
    a = sys.argv[1:]
    main(a[0], *(int(x) for x in a[1:3]))
