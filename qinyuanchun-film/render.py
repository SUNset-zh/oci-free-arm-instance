#!/usr/bin/env python3
"""渲染一个镜头的 .blend。

    python3 render.py shot.blend --stills 1,90,170 --out dir [--res 360x640] [--samples 8]
    python3 render.py shot.blend --range 1 178 --out dir
"""
import os
import sys
import time

import bpy

argv = sys.argv[1:]
blend = argv[0]
opt = lambda k, d=None: argv[argv.index('--' + k) + 1] if '--' + k in argv else d
out = opt('out', '/tmp/render')
os.makedirs(out, exist_ok=True)
bpy.ops.wm.open_mainfile(filepath=blend)
sc = bpy.context.scene
if opt('res'):
    w, h = map(int, opt('res').split('x')); sc.render.resolution_x, sc.render.resolution_y = w, h
if opt('samples'):
    sc.cycles.samples = int(opt('samples'))
if '--nomb' in argv:
    sc.render.use_motion_blur = False
if '--png' in argv:            # 调色前的快速预览：不走合成，直接 AgX 输出
    sc.use_nodes = False
    sc.render.film_transparent = False
if opt('exposure'):
    sc.view_settings.exposure = float(opt('exposure'))
frames = []
if opt('stills'):
    frames = [int(float(x)) for x in opt('stills').split(',')]
elif opt('range'):
    i = argv.index('--range'); a, b = int(argv[i + 1]), int(argv[i + 2])
    step = int(opt('step', 1))
    frames = list(range(a, b + 1, step))
t0 = time.time()
for k, f in enumerate(frames):
    path = os.path.join(out, f'f{f:04d}.png')
    if os.path.exists(path) and '--force' not in argv:
        continue
    sc.frame_set(f)
    sc.render.filepath = path
    t = time.time()
    bpy.ops.render.render(write_still=True)
    print(f'frame {f} {time.time() - t:.1f}s  ({k + 1}/{len(frames)}, total {time.time() - t0:.0f}s)', flush=True)
