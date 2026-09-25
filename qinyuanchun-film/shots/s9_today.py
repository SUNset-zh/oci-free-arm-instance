"""S9 · 俱往矣，数风流人物，还看今朝（52.3–60s）

新的黎明。镜头从云层里升起——先是一片白，然后破云而出：金色的云海铺到天边，
主峰逆光矗立，镶着一圈金边；镜头继续上升，新的太阳从峰旁升起（片尾字幕在后期叠加）。"""
import json
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import blend as B
from shots import range_scene as RS
from shots import range_terrain as RT

OUT = sys.argv[sys.argv.index('--out') + 1] if '--out' in sys.argv else '/tmp/s9'
FPS = 24
F0, F1 = 1, 194
PEAK = (-185, -475, 7010)

POST = dict(exposure_keys=[[1, .3], [60, .2], [194, 0.0]], h_dens=1.2e-5, h_base=4500, h_scale=1500, dist_fog=110000,
            fog_max=.85, bloom=.1, bloom_thresh=1.0, punch=1.12, sat=1.12, vignette=.25,
            shadow_tint=(.92, .97, 1.08), high_tint=(1.09, 1.0, .86),
            clouds=dict(alt=9500, cover=.3, scale=7000, stretch=3.0, wind=(60, 25), thick=2.2, amb=.9, bright=.5,
                        sun_gain=1.0, shade=3.0, far=140000),
            # 云海同 S6（海面略低一点：镜头约在 52.6–53.0 秒破云而出）
            cloudsea=dict(base=5000, a1=220, s1=9000, a2=170, s2=1000, a3=26, s3=170, warp=.5, cover=.6, a4=35, s4=2800,
                          wind=(35, 12), mist=160, sun_gain=.8, sun_k=1.0, amb=1.6, amb_rgb=(.06, .09, .16), ms=.3,
                          silver=2.2, wrap=.5, soft=1.2, soft_near=4.0, fog_top=40, fog_depth=220,
                          wisp_rho=.008, wisp_w=28),
            sun_disc=dict(size=.27, radiance=90.0, halo=.9, halo_w=2.0, glow=.35, veil=.35, color=(1.0, .78, .5)))


def main():
    os.makedirs(OUT, exist_ok=True)
    d = RT.get(OUT, fine=dict(ex=8000, ey=8000, cx=-250, cy=-600), mid=dict(ex=26000, ey=26000, cx=-5000, cy=1500))
    sc = B.reset()
    B.render_setup(sc, (F0, F1), samples=16, motion_blur=False)
    ctx = RS.build(d, sun=(1.2, 118), mat_kw=dict(strata=.4, ledge=.15))
    RS.animate_sun(ctx, [(0, 1.0, 118), (8.1, 2.6, 118.5)], F0, F1, FPS)
    cam = B.camera(lens=35)
    keys = [(0.0, -8640, 2600, 4980, PEAK[0], PEAK[1], 6000),
            (1.6, -8480, 2530, 5380, PEAK[0], PEAK[1], 6100),
            (3.2, -8250, 2440, 5850, PEAK[0], PEAK[1], 6250),
            (8.1, -7600, 2150, 6780, PEAK[0], PEAK[1], 6700)]
    B.animate_camera(cam, keys, F0, F1, FPS, lens_keys=[(0, 35), (8.1, 38)])
    B.exr_output(sc, os.path.join(OUT, 'exr'))
    B.export_camera(cam, F0, F1, os.path.join(OUT, 'camera.json'))
    json.dump(POST, open(os.path.join(OUT, 'post.json'), 'w'))
    print('clearance issues:', B.check_clearance(cam, F0, F1, min_dist=60, step=8))
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, 'shot.blend'))
    print('saved', os.path.join(OUT, 'shot.blend'))


if __name__ == '__main__':
    main()
