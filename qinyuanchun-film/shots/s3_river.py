"""S3 · 大河上下，顿失滔滔（13.4–17.6s）

陕北清涧—延川一带的黄河（真实 DEM），在黄土高原里切出 S 形大弯；雪后的梯田一圈圈白线。
镜头从高空顺流而下地望：起初河面还是暗流翻涌、冰凌漂浮（滔滔），一道“冰冻前锋”顺流疾驰而去，
所过之处冰凌挤拢、冻成一整片白色冰面——“顿失滔滔”。"""
import json
import os
import sys

import bpy
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import blend as B
from shots import range_scene as RS
from shots import range_terrain as RT
from shots import yellowriver as YR

OUT = sys.argv[sys.argv.index('--out') + 1] if '--out' in sys.argv else '/tmp/s3'
FPS = 24
F0, F1 = 1, 125
LON, LAT = 110.40, 36.88
HERE = os.path.dirname(os.path.abspath(__file__))
LINE = os.path.join(HERE, 'data', 'yellowriver_center.npy')

POST = dict(exposure_keys=[[1, -.1], [125, -.15]], h_dens=2e-5, h_base=560, h_scale=260, dist_fog=45000,
            fog_max=.95, fog_color=(.78, .8, .84), fog_color_mix=.6, bloom=.03, bloom_thresh=1.5, punch=1.08, sat=.95,
            vignette=.22, shadow_tint=(.95, .98, 1.04), high_tint=(1.0, 1.0, 1.0),
            snow=dict(n=60000, L=30.0, wind=(1.2, .5), fall=1.3, sway=.3, size=.016, focus=3000.0, coc=26.0,
                      bright=.7, near=.25, color=(.5, .52, .56), mode='over', seed=9))


def spec():
    ter = {"step": 4.0, "amount": .8, "slope0": .1, "slope1": .42, "warp": .35, "dip": 0.0, "dip_az": 0}
    mt = {"slope_lo": .5, "slope_hi": .68, "flute": .08, "n1": .1, "n2": .1, "cover": .05}
    return {"lon": LON, "lat": LAT, "cam": [-500, 0], "mat": mt,
            "carve": {"line": LINE, "width": 130, "depth": 1.5, "soft": 50},
            "levels": [
                dict(ex=8000, ey=10000, cx=-400, cy=-1000, cell=5.0, zoom=13, terrace=ter,
                     detail={"noise": 1.0, "drops_per_cell": .6, "talus": 50},
                     snow={"depth": .6, "lo": .45, "hi": .7, "talus": 40, "iters": 60, "d0": .08, "d1": .25}),
                dict(ex=30000, ey=30000, cx=0, cy=0, cell=20, zoom=13, terrace=dict(ter, amount=.5),
                     detail={"noise": 1.0, "drops_per_cell": .5, "talus": 50},
                     snow={"depth": .8, "lo": .45, "hi": .7, "talus": 40, "iters": 40, "d0": .1, "d1": .3}),
                dict(ex=120000, ey=120000, cell=100, zoom=11, snow={"depth": 3, "lo": .45, "hi": .7, "talus": 40, "iters": 15, "d0": .2, "d1": 1}),
                dict(ex=400000, ey=400000, cell=400, zoom=8, snow={"depth": 10, "lo": .4, "hi": .65, "talus": 40, "iters": 8, "d0": .5, "d1": 3}),
            ]}


def main():
    os.makedirs(OUT, exist_ok=True)
    d = RT.generate(OUT, spec())
    sc = B.reset()
    B.render_setup(sc, (F0, F1), samples=16, motion_blur=False)
    ctx = RS.build(d, alt=600, overcast=dict(top=(.52, .56, .62), horizon=(.8, .82, .86), ground=(.42, .41, .4), strength=.85,
                                             soft_sun=dict(el=14, az=140, energy=.9, angle=14.0, color=(1.0, .96, .9))),
                   mat_kw=dict(rock=(.2, .15, .1), rock2=(.34, .26, .18), strata=.8, ledge=.1, cav_dark=.35, brush=.25,
                               brush_col=(.09, .07, .05),
                               contours=dict(step=6.0, width=.14, strength=.85, color=(.28, .22, .16))))
    line = np.load(LINE)
    YR.ribbon(line, half_width=260, curve_origin=(-500, 0))
    rm, front, tim = YR.mat_river(flow=3.5)
    bpy.data.objects['river'].data.materials.append(rm)
    # 冰冻前锋：开场河面还在流（前锋在画面近端之前），随后顺流疾驰而去
    YR.animate(front, tim, F0, F1, FPS, [(0.0, 5200.0), (.6, 5600.0), (4.4, 16500.0), (5.2, 18500.0)])
    cam = B.camera(lens=26, clip=(1, 150000))
    keys = [(0.0, 150, 3700, 3300, -450, -2400, 540),
            (5.2, 50, 3150, 3150, -520, -2900, 540)]
    B.animate_camera(cam, keys, F0, F1, FPS)
    B.exr_output(sc, os.path.join(OUT, 'exr'))
    B.export_camera(cam, F0, F1, os.path.join(OUT, 'camera.json'))
    json.dump(POST, open(os.path.join(OUT, 'post.json'), 'w'))
    print('clearance issues:', B.check_clearance(cam, F0, F1, min_dist=40, step=8))
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, 'shot.blend'))
    print('saved', os.path.join(OUT, 'shot.blend'))


if __name__ == '__main__':
    main()
