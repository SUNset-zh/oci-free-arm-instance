"""S6 · 江山如此多娇，引无数英雄竞折腰（30.0–36.4s）

日出后的金色侧光：镜头贴着云海顶（约 5900 米）从西南望向主峰，太阳在右侧。云海铺到天边，
群峰像岛屿一样拔出云面，受光面金黄、背光面青蓝。镜头缓缓横移，云海按延时摄影的节奏流动
（云海在后期里光线步进渲染，见 post/cloudsea.py）。"""
import json
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import blend as B
from shots import range_scene as RS
from shots import range_terrain as RT

OUT = sys.argv[sys.argv.index('--out') + 1] if '--out' in sys.argv else '/tmp/s6'
FPS = 24
F0, F1 = 1, 173
PEAK = (-185, -475, 7010)

POST = dict(exposure_keys=[[1, .45], [173, .4]], h_dens=1.2e-5, h_base=4500, h_scale=1500, dist_fog=110000,
            fog_max=.85, bloom=.08, bloom_thresh=1.0, punch=1.12, sat=1.12, vignette=.25,
            shadow_tint=(.92, .97, 1.08), high_tint=(1.08, 1.0, .88),
            clouds=dict(alt=9500, cover=.3, scale=7000, stretch=3.0, wind=(60, 25), thick=2.2, amb=.9, bright=.45,
                        sun_gain=1.0, shade=3.0, far=140000),
            # 云海：平缓的海面（base 是海面高度）上成簇的积云团，见 post/cloudsea.py
            cloudsea=dict(base=5060, a1=220, s1=9000, a2=170, s2=1000, a3=26, s3=170, warp=.5, cover=.6, a4=35, s4=2800,
                          wind=(45, 18), mist=160, sun_gain=.8, sun_k=1.0, amb=1.6, amb_rgb=(.06, .09, .16), ms=.3,
                          silver=1.0, wrap=.5, soft=1.2, soft_near=4.0, wisp_rho=.008, wisp_w=28))


def main():
    os.makedirs(OUT, exist_ok=True)
    d = RT.get(OUT, fine=dict(ex=8000, ey=8000, cx=-250, cy=-600), mid=dict(ex=26000, ey=26000, cx=-3000, cy=-6000))
    sc = B.reset()
    B.render_setup(sc, (F0, F1), samples=16, motion_blur=False)
    ctx = RS.build(d, sun=(7.5, 120), mat_kw=dict(strata=.4, ledge=.15))
    RS.animate_sun(ctx, [(0, 7.2, 120), (7.2, 8.2, 120.5)], F0, F1, FPS)
    cam = B.camera(lens=40)
    keys = [(0.0, -7600, -11200, 5950, PEAK[0] + 400, PEAK[1], 6000),
            (7.2, -5800, -12000, 5920, PEAK[0], PEAK[1], 6050)]
    B.animate_camera(cam, keys, F0, F1, FPS, lens_keys=[(0, 40), (7.2, 42)])
    B.exr_output(sc, os.path.join(OUT, 'exr'))
    B.export_camera(cam, F0, F1, os.path.join(OUT, 'camera.json'))
    json.dump(POST, open(os.path.join(OUT, 'post.json'), 'w'))
    print('clearance issues:', B.check_clearance(cam, F0, F1, min_dist=60, step=8))
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, 'shot.blend'))
    print('saved', os.path.join(OUT, 'shot.blend'))


if __name__ == '__main__':
    main()
