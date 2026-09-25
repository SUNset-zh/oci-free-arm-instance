"""S4 · 山舞银蛇，原驰蜡象，欲与天公试比高（17.6–24.4s）

第一缕阳光：只有最高的山脊被点亮，一道道金银色的脊线在蓝色的阴影里蜿蜒（银蛇）；
圆润的雪丘在脚下起伏（蜡象）。镜头在高空侧向滑行，层层山脊彼此错动；
最后一拍镜头向右摇、向上抬，主峰从山脊之后拔地而起，峰顶已被朝阳点燃（试比高）。"""
import json
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import blend as B
from shots import range_scene as RS
from shots import range_terrain as RT

OUT = sys.argv[sys.argv.index('--out') + 1] if '--out' in sys.argv else '/tmp/s4'
FPS = 24
F0, F1 = 1, 185
PEAK = (-185, -475, 7010)

POST = dict(exposure_keys=[[1, 1.3], [185, 1.1]], h_dens=1.5e-5, h_base=4000, h_scale=1200, dist_fog=110000,
            fog_max=.9, bloom=.05, bloom_thresh=1.2, punch=1.12, sat=1.15, vignette=.22,
            shadow_tint=(.92, .97, 1.08), high_tint=(1.05, 1.0, .94),
            clouds=dict(alt=9500, cover=.4, scale=7000, stretch=3.0, wind=(40, 15), thick=2.5, amb=.9, bright=.35,
                        sun_gain=1.0, shade=3.0, far=140000))


def main():
    os.makedirs(OUT, exist_ok=True)
    d = RT.get(OUT, fine=dict(ex=8000, ey=8000, cx=-250, cy=-600), mid=dict(ex=26000, ey=26000, cx=4000, cy=-5000))
    sc = B.reset()
    B.render_setup(sc, (F0, F1), samples=16, motion_blur=True, shutter=.3)
    ctx = RS.build(d, sun=(1.0, 118), mat_kw=dict(strata=.4, ledge=.15))
    RS.animate_sun(ctx, [(0, .9, 118), (7.7, 1.7, 118.3)], F0, F1, FPS)
    cam = B.camera(lens=50)
    keys = [(0.0, 12500, -10000, 6900, 0, -13500, 5200),
            (4.2, 12400, -8800, 6880, 0, -9800, 5250),
            (7.7, 12200, -7600, 6550, PEAK[0], PEAK[1], 6450)]
    B.animate_camera(cam, keys, F0, F1, FPS, lens_keys=[(0, 50), (4.2, 52), (7.7, 72)])
    B.exr_output(sc, os.path.join(OUT, 'exr'))
    B.export_camera(cam, F0, F1, os.path.join(OUT, 'camera.json'))
    json.dump(POST, open(os.path.join(OUT, 'post.json'), 'w'))
    print('clearance issues:', B.check_clearance(cam, F0, F1, min_dist=60, step=8))
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, 'shot.blend'))
    print('saved', os.path.join(OUT, 'shot.blend'))


if __name__ == '__main__':
    main()
