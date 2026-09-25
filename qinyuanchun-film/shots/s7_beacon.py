"""S7 · 惜秦皇汉武，略输文采；唐宗宋祖，稍逊风骚（36.4–45.3s）

黄河峡谷东岸的黄土梁顶，一座残破的夯土烽火台。延时摄影式的日落：太阳从 7° 落到地平线下，
光从金黄变成橙红，烽火台的长影在雪地上扫过；卷云被烧红又暗下去。镜头绕着烽火台缓缓转半圈，
从侧光转到逆光——最后烽火台成了落日前的一道剪影。千年兴亡，都在这一明一暗之间。"""
import json
import os
import sys

import bpy
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import blend as B
from shots import beacon as BC
from shots import range_scene as RS
from shots import range_terrain as RT
from shots import s3_river as S3

OUT = sys.argv[sys.argv.index('--out') + 1] if '--out' in sys.argv else '/tmp/s7'
FPS = 24
F0, F1 = 1, 233
TX, TY = 2200.0, 900.0

POST = dict(exposure_keys=[[1, .2], [120, .45], [233, 1.2]], h_dens=3e-5, h_base=560, h_scale=300, dist_fog=40000,
            fog_max=.9, bloom=.08, bloom_thresh=1.0, punch=1.12, sat=1.12, vignette=.25,
            shadow_tint=(.92, .96, 1.08), high_tint_keys=[[1, [1.08, 1.0, .9]], [233, [1.12, .97, .86]]],
            clouds=dict(alt=7000, cover=.45, scale=5000, stretch=2.5, wind=(-260, 90), thick=2.6, amb=.9, bright=.6,
                        sun_gain=1.0, shade=3.0, far=120000),
            sun_disc=dict(size=.27, radiance=70.0, halo=.8, halo_w=2.0, glow=.3, veil=.3, color=(1.0, .72, .45)))


def spec():
    sp = S3.spec()
    fine = dict(ex=1400, ey=1400, cx=TX, cy=TY, cell=1.0, zoom=14, terrace=dict(sp['levels'][0]['terrace']),
                detail={"noise": .4, "drops_per_cell": .3, "talus": 50},
                snow={"depth": .35, "lo": .45, "hi": .7, "talus": 40, "iters": 60, "d0": .05, "d1": .15})
    sp['levels'] = [fine] + sp['levels']
    sp['cam'] = [TX, TY]
    return sp


def main():
    os.makedirs(OUT, exist_ok=True)
    d = RT.generate(OUT, spec())
    sc = B.reset()
    B.render_setup(sc, (F0, F1), samples=16, motion_blur=False)
    ctx = RS.build(d, sun=(7.0, 240), alt=900, dust=2.2, ozone=1.2, sky_strength=.07,
                   mat_kw=dict(rock=(.2, .15, .1), rock2=(.34, .26, .18), strata=.8, ledge=.1, cav_dark=.35, brush=0.0, snow_bump=.16,
                               brush_col=(.09, .07, .05)))
    RS.animate_sun(ctx, [(0, 7.0, 240), (4.8, 3.0, 241), (9.7, -.8, 242)], F0, F1, FPS)
    ter = ctx['ter']
    g = min(ter.height(TX + dx, TY + dy) for dx in (-6, 0, 6) for dy in (-6, 0, 6))
    tw = BC.tower()
    tw.location = (TX, TY, g + .2)
    tw.data.materials.append(BC.mat_earth())
    # 绕塔半圈：从东南（侧光）转到东北偏东（正对夕阳，逆光剪影）
    keys = []
    for k, (t, az, r, h) in enumerate([(0, 150, 44, 7), (3.2, 124, 43, 8), (6.4, 98, 42, 9), (9.7, 72, 43, 9.5)]):
        a = np.radians(az)
        x, y = TX + r * np.sin(a), TY + r * np.cos(a)
        keys.append((t, x, y, ter.height(x, y) + h, TX, TY, g + 6.5))
    cam = B.camera(lens=30, clip=(.3, 150000))
    B.animate_camera(cam, keys, F0, F1, FPS)
    B.exr_output(sc, os.path.join(OUT, 'exr'))
    B.export_camera(cam, F0, F1, os.path.join(OUT, 'camera.json'))
    json.dump(POST, open(os.path.join(OUT, 'post.json'), 'w'))
    print('clearance issues:', B.check_clearance(cam, F0, F1, min_dist=1.5, step=6))
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, 'shot.blend'))
    print('saved', os.path.join(OUT, 'shot.blend'))


if __name__ == '__main__':
    main()
