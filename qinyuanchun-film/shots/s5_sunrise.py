"""S5 · 须晴日，看红装素裹，分外妖娆（24.4–30.0s）

东南侧山脊上空，正对主峰朝阳的一面。延时摄影式的日出：太阳从地平线下 1.8° 升到 9°——
先是峰尖染上一点红，红光顺着山体往下淌，卷云也被染成粉金色，最后整座雪山在晴空下白得发亮。
镜头缓缓横移并前推，前景山脊与主峰之间有视差。"""
import json
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import blend as B
from shots import range_scene as RS
from shots import range_terrain as RT

OUT = sys.argv[sys.argv.index('--out') + 1] if '--out' in sys.argv else '/tmp/s5'
FPS = 24
F0, F1 = 1, 154
PEAK = (-185, -475, 7010)

POST = dict(exposure_keys=[[1, 1.9], [50, 1.0], [100, .2], [154, -.3]], h_dens=1.5e-5, h_base=4000, h_scale=1200,
            dist_fog=150000, fog_max=.9, bloom=.05, bloom_thresh=1.2, punch=1.12, sat=1.15, vignette=.22,
            shadow_tint=(.92, .97, 1.08), high_tint_keys=[[1, [1.1, .96, .92]], [70, [1.12, .99, .86]], [154, [1.04, 1.0, .96]]],
            clouds=dict(alt=9500, cover=.45, scale=7000, stretch=3.0, wind=(160, 60), thick=2.5, amb=.9, bright=.35,
                        sun_gain=1.0, shade=3.0, far=140000))


def main():
    os.makedirs(OUT, exist_ok=True)
    d = RT.get(OUT, fine=dict(ex=8000, ey=9000, cx=1400, cy=-3100))
    sc = B.reset()
    B.render_setup(sc, (F0, F1), samples=16, motion_blur=False)
    ctx = RS.build(d, sun=(-1.8, 118))
    RS.animate_sun(ctx, [(0, -1.8, 118), (2.2, .6, 118.5), (6.4, 9.0, 120)], F0, F1, FPS)
    cam = B.camera(lens=45)
    keys = [(0.0, 4300, -6600, 5700, PEAK[0], PEAK[1], 6050),
            (6.4, 3700, -6000, 5820, PEAK[0], PEAK[1], 6150)]
    B.animate_camera(cam, keys, F0, F1, FPS, lens_keys=[(0, 45), (6.4, 48)])
    B.exr_output(sc, os.path.join(OUT, 'exr'))
    B.export_camera(cam, F0, F1, os.path.join(OUT, 'camera.json'))
    json.dump(POST, open(os.path.join(OUT, 'post.json'), 'w'))
    print('clearance issues:', B.check_clearance(cam, F0, F1, min_dist=12, step=6))
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, 'shot.blend'))
    print('saved', os.path.join(OUT, 'shot.blend'))


if __name__ == '__main__':
    main()
