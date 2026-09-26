"""S2 · 望长城内外，惟余莽莽（10.0–13.4s）

箭扣—慕田峪一带的真实山脊（SRTM），明长城沿山脊蜿蜒，敌楼立在一个个山头上。
阴天，大雪还在下，天地一片灰白；山谷里雾气弥漫（后期云海压得很低，当作谷雾）——内外一片苍茫。
镜头从城墙马道上方缓缓前推：积雪的马道像一条白带，垛口一路排开，城墙翻过山头伸向雾里的敌楼。"""
import json
import os
import sys

import bpy
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import blend as B
from shots import greatwall as GW
from shots import trees as TR
from shots import range_scene as RS
from shots import range_terrain as RT

OUT = sys.argv[sys.argv.index('--out') + 1] if '--out' in sys.argv else '/tmp/s2'
FPS = 24
F0, F1 = 1, 108
LON, LAT = 116.525, 40.452
HERE = os.path.dirname(os.path.abspath(__file__))

POST = dict(exposure_keys=[[1, -.2], [108, -.25]], h_dens=1.2e-4, h_base=500, h_scale=400, dist_fog=9000,
            fog_max=.97, fog_color=(.8, .82, .86), fog_color_mix=.6, bloom=.03, bloom_thresh=1.5, punch=1.06, sat=.9,
            vignette=.22, shadow_tint=(.96, .98, 1.03), high_tint=(1.0, 1.0, 1.0),
            cloudsea=dict(base=560, a1=70, s1=5000, a2=45, s2=900, wind=(4, 1), mist=110, sun_gain=0.0, sun_k=0.0,
                          amb=1.0, amb_rgb=(.72, .75, .8), silver=0.0, wrap=.7, soft=1.5),
            snow=dict(n=120000, L=30.0, wind=(1.6, .4), fall=1.4, sway=.35, size=.018, focus=3000.0, coc=30.0,
                      bright=.75, near=.25, color=(.5, .52, .56), mode='over', seed=5))


def spec():
    ter = {"step": 30, "amount": 0.35, "slope0": 0.8, "slope1": 1.4, "warp": 1.5, "dip": 0.05, "dip_az": 70}
    mt = {"slope_lo": .12, "slope_hi": .3, "flute": .12, "n1": .12, "n2": .1, "cover": .28}
    return {"lon": LON, "lat": LAT, "cam": [800, 300], "mat": mt,
            "vexag": {"k": 1.25, "r": 400}, "sharpen": {"k": .5, "r": 40}, "levels": [
        dict(ex=4200, ey=3200, cx=1000, cy=0, cell=2.0, zoom=14, terrace=ter,
             detail={"noise": 1.0, "drops_per_cell": 1.0, "talus": 45},
             snow={"depth": 1.2, "lo": .25, "hi": .5, "talus": 45, "iters": 80, "d0": .1, "d1": .4}),
        dict(ex=14000, ey=14000, cx=800, cy=0, cell=8, zoom=13, detail={"noise": 1.5, "drops_per_cell": .7, "talus": 44},
             snow={"depth": 2.0, "lo": .25, "hi": .5, "talus": 45, "iters": 60, "d0": .15, "d1": .6}),
        dict(ex=60000, ey=60000, cell=40, zoom=11, snow={"depth": 8, "lo": .3, "hi": .55, "talus": 45, "iters": 20, "d0": .3, "d1": 2}),
        dict(ex=300000, ey=300000, cell=300, zoom=8, snow={"depth": 30, "lo": .3, "hi": .55, "talus": 40, "iters": 10, "d0": 1, "d1": 5}),
    ]}


def main():
    os.makedirs(OUT, exist_ok=True)
    d = RT.generate(OUT, spec())
    sc = B.reset()
    B.render_setup(sc, (F0, F1), samples=16, motion_blur=False)
    ctx = RS.build(d, alt=900, overcast=dict(top=(.52, .56, .62), horizon=(.8, .83, .88), ground=(.4, .41, .43), strength=1.0),
                   mat_kw=dict(rock=(.06, .055, .05), rock2=(.12, .1, .085), strata=.3, ledge=.15, brush=.5))
    ter = ctx['ter']
    # 城墙：路径来自 DEM 上的最小代价山脊路线（见 README），这里按最终地形取地面高度
    P = np.load(os.path.join(HERE, 'data', 'jiankou_wall_path.npy'))
    t, nrm = GW.frames(P)
    gc = np.array([ter.height(x, y) for x, y in P])
    gl = np.array([ter.height(x + nx * 3, y + ny * 3) for (x, y), (nx, ny) in zip(P, nrm)])
    gr = np.array([ter.height(x - nx * 3, y - ny * 3) for (x, y), (nx, ny) in zip(P, nrm)])
    gmax = np.maximum(gc, np.maximum(gl, gr)); gmin = np.minimum(gc, np.minimum(gl, gr))
    walk = GW.walk_height(gc, gmax, wall_h=5.2)
    base = gmin - 3.0
    mb = GW.mat_brick(); mt = GW.mat_tower()
    GW.wall_body(P, nrm, walk, base, mb)
    GW.parapets(P, t, nrm, walk, mb)
    tme = GW.tower_mesh(mt)
    GW.place_towers(P, t, walk, ter.height, tme)
    # 冬季灌木：由地形材质里的细碎“灌木点”表现（远看是雪地上一层灰褐色的毛）
    # 镜头：制高点上、马道上方约 14 m，沿墙缓缓前推、略升，望向城墙蜿蜒伸进雾里的远方
    i0, i1, it = 5985, 6012, 6420
    d0 = P[i0 + 15] - P[i0]; d0 /= np.linalg.norm(d0)
    n0 = np.array([-d0[1], d0[0]])
    c0 = (P[i0, 0] + n0[0] * 2.0, P[i0, 1] + n0[1] * 2.0, walk[i0] + 13.0)
    c1 = (P[i1, 0] + n0[0] * 2.0, P[i1, 1] + n0[1] * 2.0, walk[i1] + 17.0)
    tg = (P[it, 0], P[it, 1], walk[it] - 2)
    cam = B.camera(lens=32, clip=(.5, 80000))
    B.animate_camera(cam, [(0.0, *c0, *tg), (4.5, *c1, tg[0], tg[1], tg[2] + 2)], F0, F1, FPS)
    B.exr_output(sc, os.path.join(OUT, 'exr'))
    B.export_camera(cam, F0, F1, os.path.join(OUT, 'camera.json'))
    json.dump(POST, open(os.path.join(OUT, 'post.json'), 'w'))
    print('clearance issues:', B.check_clearance(cam, F0, F1, min_dist=3, step=6))
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, 'shot.blend'))
    print('saved', os.path.join(OUT, 'shot.blend'))


if __name__ == '__main__':
    main()
