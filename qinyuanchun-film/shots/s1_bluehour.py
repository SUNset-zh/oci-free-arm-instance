"""S1 · 北国风光，千里冰封，万里雪飘（3.6–10.0s）

黎明前的蓝调时刻。高空朝东：层层雪岭退入蓝色的雾里，天边一线橙红。
雪从镜头前飘过（近处焦外成光斑，后期三维雪花，见 post/snow.py）。镜头缓缓前滑、略降。"""
import json
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import blend as B
from shots import range_scene as RS
from shots import range_terrain as RT

OUT = sys.argv[sys.argv.index('--out') + 1] if '--out' in sys.argv else '/tmp/s1'
FPS = 24
F0, F1 = 1, 178

POST = dict(exposure_keys=[[1, 3.3], [178, 3.1]], h_dens=1.5e-5, h_base=4000, h_scale=1200, dist_fog=80000,
            fog_max=.9, bloom=.05, bloom_thresh=1.2, punch=1.1, sat=1.15, vignette=.25,
            shadow_tint=(.92, .97, 1.08), high_tint=(1.03, 1.0, .97),
            sky_vblur=55,                     # 暮光带上下沿柔化
            # 镜头飞得快：雪场跟随镜头平移 90%、快门缩短到 0.3，雪是“飘”而不是迎面冲来的雨线
            snow=dict(n=22000, L=36.0, wind=(.9, -.3), fall=1.1, sway=.3, size=.016, focus=8000.0, coc=30.0,
                      bright=.05, near=2.5, color=(.55, .62, .8), seed=11, follow=.9, shutter_k=.3))


def main():
    os.makedirs(OUT, exist_ok=True)
    d = RT.get(OUT, fine=dict(ex=9000, ey=9000, cx=13500, cy=1000), mid=dict(ex=26000, ey=26000, cx=17000, cy=-2500),
               terrace=dict(amount=.15), mat=dict(cover=.12, slope_lo=.32, slope_hi=.5))
    sc = B.reset()
    B.render_setup(sc, (F0, F1), samples=16, motion_blur=False)
    ctx = RS.build(d, sun=(-3.4, 118), mat_kw=dict(strata=.4, ledge=.15))
    RS.animate_sun(ctx, [(0, -3.5, 118), (7.4, -3.0, 118)], F0, F1, FPS)
    cam = B.camera(lens=30)
    keys = [(0.0, 10600, 3600, 7500, 27900, -6400, 6100),
            (7.4, 11050, 3340, 7400, 28350, -6660, 6050)]
    B.animate_camera(cam, keys, F0, F1, FPS)
    B.exr_output(sc, os.path.join(OUT, 'exr'))
    B.export_camera(cam, F0, F1, os.path.join(OUT, 'camera.json'))
    json.dump(POST, open(os.path.join(OUT, 'post.json'), 'w'))
    print('clearance issues:', B.check_clearance(cam, F0, F1, min_dist=60, step=8))
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, 'shot.blend'))
    print('saved', os.path.join(OUT, 'shot.blend'))


if __name__ == '__main__':
    main()
