"""S1 · 北国风光，千里冰封，万里雪飘（3.6–10.0s）
黎明前的蓝调时刻：无边雪岭层层退入蓝色的雾里，东方地平线透出一线暖光；近处雪花斜飘而过。"""
import json
import math
import os
import sys

import bpy
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import blend as B, tcache

OUT = sys.argv[sys.argv.index('--out') + 1] if '--out' in sys.argv else '/tmp/s1'
FPS = 24
DUR = 7.4
F0, F1 = 1, int(DUR * FPS)
EXT, N = 26000.0, 2048

# 后期参数（post/composite.py 读取）
POST = dict(exposure=1.6, h_dens=.0009, h_base=1100, h_scale=320, dist_fog=26000, fog_max=.96, fog_tint=(1, 1, 1),
            fog_color=(.13, .17, .28), fog_color_mix=.55,
            bloom=.05, punch=1.06, sat=1.0, lift=(.004, .006, .012), gain=(.98, 1.0, 1.03), vignette=.28)


def main():
    os.makedirs(OUT, exist_ok=True)
    d = tcache.get('shots/t1_range.py', os.path.join(OUT, 'terrain_s1.npz'), EXT, N)
    H = d['H']
    sc = B.reset()
    B.render_setup(sc, (F0, F1), samples=16)
    mat = B.mat_terrain(sastrugi=.6)
    ter = B.mesh_from_height('terrain', H, EXT, attrs={'snow': d['S']}); ter.data.materials.append(mat)
    far = B.mesh_from_height('far', d['HF'], float(d['FE']), attrs={'snow': d['SF']}); far.data.materials.append(mat)
    # 蓝调时刻：太阳在地平线下 4°，只有天光
    w, ctl = B.world_sky(overcast=0.0, sun_elev=-4.0, sun_rot=65, strength=9.0, cloud_cover=0.0, dust=1.5, air=1.1, altitude=2000)
    cam = B.camera(lens=30)
    gz = B.sample_height(H, EXT, 2000, -10500)
    z0 = gz + 1150
    keys = [
        (0.0, 2000, -10500, z0, 0, 6000, 350),
        (3.7, 1900, -9900, z0 + 30, 0, 6000, 450),
        (7.4, 1800, -9300, z0 + 80, 0, 6000, 620),
    ]
    B.animate_camera(cam, keys, F0, F1, FPS)
    B.snowfall(center=(1900, -9700, z0 + 30), size=(500, 1500, 300), count=30000, lifetime=int(DUR * FPS) + 60, frames=(F0, F1),
               vel=(.25, 0, -1.4), size_m=.35, wind=(0, 0, 0))
    B.bake_particles(os.path.join(OUT, 'cache_s1'))
    B.exr_output(sc, os.path.join(OUT, 'exr'))
    B.export_camera(cam, F0, F1, os.path.join(OUT, 'camera.json'))
    json.dump(POST, open(os.path.join(OUT, 'post.json'), 'w'))
    print('clearance issues:', B.check_clearance(cam, F0, F1, min_dist=150, step=12))
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, 's1.blend'))
    print('saved', os.path.join(OUT, 's1.blend'))


if __name__ == '__main__':
    main()
