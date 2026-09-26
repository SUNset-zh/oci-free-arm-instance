"""S8 · 一代天骄，成吉思汗，只识弯弓射大雕（45.3–52.3s）

锡林郭勒的雪原（真实 DEM，抹平了雷达噪点），日落后的余晖。六骑在缓坡上疾驰而过，成了逆光的剪影，
马蹄踢起的雪粉被天光照亮；一只大雕在头顶盘旋。领头的骑手张弓、瞄准、放箭——镜头随箭抬向天空。"""
import json
import math
import os
import sys

import bpy
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import blend as B
from shots import range_scene as RS
from shots import range_terrain as RT
from shots import riders as RD

OUT = sys.argv[sys.argv.index('--out') + 1] if '--out' in sys.argv else '/tmp/s8'
FPS = 24
F0, F1 = 1, 187
LON, LAT = 116.6, 43.9
CAMX, CAMY = 300.0, -300.0
HEAD = 340.0                       # 骑队前进方位角
SPEED = 12.5
ASSETS = '/tmp/claude-0/-home-user-oci-free-arm-instance/33674d5b-35e4-5b5a-b79d-ec7ad6b62fa3/scratchpad/assets'

POST = dict(exposure_keys=[[1, 2.0], [187, 2.2]], h_dens=1e-5, h_base=1200, h_scale=400, dist_fog=30000,
            fog_max=.9, bloom=.07, bloom_thresh=1.0, punch=1.1, sat=1.1, vignette=.28,
            shadow_tint=(.92, .96, 1.08), high_tint=(1.08, 1.0, .9),
            clouds=dict(alt=6000, cover=.42, scale=4500, stretch=3.0, wind=(-40, 12), thick=2.4, amb=.9, bright=.7,
                        sun_gain=1.0, shade=3.0, far=100000),
            spray=dict(rate=120, life=1.2, spread=1.3, up=1.2, drag=2.0, size=.05, grow=.25, bright=.3, back=1.4, color=(.62, .54, .52)))


def spec():
    mt = {"slope_lo": .2, "slope_hi": .4, "flute": .0, "n1": .05, "n2": .05, "cover": .4}
    return {"lon": LON, "lat": LAT, "cam": [CAMX, CAMY], "mat": mt, "smooth": 40.0, "levels": [
        dict(ex=2400, ey=2400, cx=CAMX - 200, cy=CAMY + 100, cell=2.0, zoom=13,
             detail={"noise": .6, "drops_per_cell": 0, "talus": 40},
             snow={"depth": .3, "lo": .3, "hi": .6, "talus": 40, "iters": 20, "d0": .02, "d1": .1}),
        dict(ex=20000, ey=20000, cx=0, cy=0, cell=10, zoom=12, snow={"depth": .5, "lo": .3, "hi": .6, "talus": 40, "iters": 10, "d0": .05, "d1": .2}),
        dict(ex=100000, ey=100000, cell=80, zoom=10, snow={"depth": 2, "lo": .3, "hi": .6, "talus": 40, "iters": 8, "d0": .1, "d1": .5}),
        dict(ex=400000, ey=400000, cell=400, zoom=8, snow={"depth": 8, "lo": .3, "hi": .6, "talus": 40, "iters": 6, "d0": .5, "d1": 2}),
    ]}


def main():
    os.makedirs(OUT, exist_ok=True)
    d = RT.generate(OUT, spec())
    sc = B.reset()
    B.render_setup(sc, (F0, F1), samples=16, motion_blur=True, shutter=.5)
    ctx = RS.build(d, sun=(-1.6, 240), alt=1200, dust=1.4, ozone=1.3, sky_strength=.07,
                   mat_kw=dict(rock=(.25, .22, .16), rock2=(.35, .3, .2), strata=0, ledge=0, brush=.55,
                               brush_col=(.32, .27, .18), snow_bump=.12))
    ter = ctx['ter']
    blk = RD.mat_dark('rider', (.03, .025, .022), .85)
    hb = np.array([math.sin(math.radians(HEAD)), math.cos(math.radians(HEAD))])
    side = np.array([math.sin(math.radians(250)), math.cos(math.radians(250))])
    P0 = np.array([CAMX, CAMY]) + 115 * side
    # 骑队：(纵向偏移, 离镜头的距离, 步态相位)
    team = [(8, 46, .0), (2, 40, .31), (-3, 55, .57), (-9, 44, .83), (-14, 52, .14), (-20, 60, .66)]
    horses = []
    for k, (dl, dist, ph) in enumerate(team):
        o, curves, cyc = RD.load_horse(os.path.join(ASSETS, 'Horse.glb'))
        o.data.materials.clear(); o.data.materials.append(blk)
        base = np.array([CAMX, CAMY]) + dist * side

        def path_fn(t, base=base, dl=dl):
            q = base + hb * (dl + SPEED * (t - 3.8))
            return (q[0], q[1], ter.height(q[0], q[1]) - .05), math.radians(180 - HEAD)
        RD.animate_horse(o, curves, cyc, F0, F1, FPS, period=.43, phase=ph, path_fn=path_fn)
        horses.append((o, path_fn))
    # 骑手：每帧取马背顶点的位置
    riders = []
    for k, (o, pf) in enumerate(horses):
        r, arm = RD.rider_mesh(f'rider{k}', archer=(k == 0))
        r.data.materials.append(blk)
        if arm:
            arm.data.materials.append(blk)
        riders.append((r, arm))
    si = RD.saddle_index(horses[0][0])
    dg = bpy.context.evaluated_depsgraph_get()
    track = {k: [] for k in range(len(horses))}
    for f in range(F0, F1 + 1):
        sc.frame_set(f)
        dg = bpy.context.evaluated_depsgraph_get()
        for k, (o, pf) in enumerate(horses):
            oe = o.evaluated_get(dg); me = oe.to_mesh()
            p = o.matrix_world @ me.vertices[si].co
            oe.to_mesh_clear()
            r, arm = riders[k]
            r.location = (p.x - .22 * hb[0], p.y - .22 * hb[1], p.z - .05)
            r.rotation_euler = (0, 0, math.radians(-HEAD))
            r.keyframe_insert('location', frame=f); r.keyframe_insert('rotation_euler', frame=f)
            track[k].append([o.location.x, o.location.y, o.location.z])
            if arm is not None:
                t = (f - F0) / FPS
                # 张弓：3.9s 起抬臂，4.8s 满弓瞄准（指向左上方的雕），5.5s 放箭后保持
                a = np.interp(t, [0, 3.9, 4.8, 7.8], [8, 8, 62, 66])
                arm.rotation_euler = (math.radians(a), 0, 0)
                arm.keyframe_insert('rotation_euler', frame=f)
    # 雕：在骑队上空由右向左盘旋
    b, wl, wr = RD.eagle(span=2.6)
    for ob in (b, wl, wr):
        ob.data.materials.append(blk)
    def lead(t):
        return np.array([CAMX, CAMY]) + 46 * side + hb * (8 + SPEED * (t - 3.8))

    def eagle_path(t):
        # 先在高处盘旋（画外），4.4s 后低掠过骑队上空、从右上方滑向左上方
        L = lead(t)
        u = np.clip((t - 4.0) / 3.8, 0, 1)
        c = L + hb * (14 - 16 * u) + side * (-4 - 26 * u)
        hgt = 55 - 38 * min(1.0, u * 1.5)
        a = math.radians(HEAD + 180 - 30 * u)
        p = (c[0], c[1], ter.height(c[0], c[1]) + hgt + 1.5 * math.sin(t * 1.3))
        return p, a, math.radians(-10 + 16 * u)
    RD.animate_eagle(b, wl, wr, eagle_path, F0, F1, FPS, flaps=((.6, 2.0), (5.4, 6.6)), flap_period=.95)
    # 箭：5.5s 从弓上射出，朝雕的方向飞
    arrow_me = bpy.data.meshes.new('arrow')
    import bmesh
    bm = bmesh.new(); bmesh.ops.create_cone(bm, cap_ends=True, segments=5, radius1=.012, radius2=.012, depth=.9); bm.to_mesh(arrow_me); bm.free()
    arrow = bpy.data.objects.new('arrow', arrow_me); sc.collection.objects.link(arrow); arrow.data.materials.append(blk)
    for f in range(F0, F1 + 1):
        t = (f - F0) / FPS
        sc.frame_set(f)
        if t < 5.5:
            arrow.hide_render = True; arrow.keyframe_insert('hide_render', frame=f)
            continue
        arrow.hide_render = False; arrow.keyframe_insert('hide_render', frame=f)
        a0 = riders[0][0].matrix_world.translation
        tgt = eagle_path(t + .6)[0]
        u = min(1.0, (t - 5.5) / 1.4)
        pos = a0 + (mathutils_vec(tgt) - a0) * u * .85 + mathutils_vec((0, 0, .9))
        d = (mathutils_vec(tgt) - a0).normalized()
        arrow.location = pos
        arrow.rotation_mode = 'QUATERNION'; arrow.rotation_quaternion = d.to_track_quat('Z', 'Y')
        arrow.keyframe_insert('location', frame=f); arrow.keyframe_insert('rotation_quaternion', frame=f)
    # 镜头：贴着雪面、与骑队并行跟拍（离领头骑手约 48 m）；最后随张弓的方向抬向天空里的雕
    cam = B.camera(lens=70, clip=(.3, 150000))
    keys = []
    for t in np.arange(0, 7.85, .25):
        f = min(int(round(t * FPS)) + F0, F1)
        lp = np.array(track[0][f - F0])
        c = lp[:2] + (-side) * 0 + np.array([CAMX, CAMY]) * 0
        c = lead(t) - side * 40 - hb * 9
        cz = ter.height(c[0], c[1]) + .55
        grp = np.mean([np.array(track[k][f - F0]) for k in track], 0)
        tg = grp * .45 + lp * .55 + np.array([0, 0, 4.2])
        if t > 4.4:
            u = min(1.0, (t - 4.4) / 2.6); u = u * u * (3 - 2 * u)
            ep = np.array(eagle_path(t)[0])
            tg = tg * (1 - u) + ep * u
        keys.append((t, c[0], c[1], cz, *tg))
    B.animate_camera(cam, keys, F0, F1, FPS, lens_keys=[(0, 70), (4.4, 70), (7.8, 50)])
    B.exr_output(sc, os.path.join(OUT, 'exr'))
    B.export_camera(cam, F0, F1, os.path.join(OUT, 'camera.json'))
    # 马的轨迹（后期雪粉要用）
    json.dump({k: v for k, v in track.items()}, open(os.path.join(OUT, 'horses.json'), 'w'))
    json.dump(POST, open(os.path.join(OUT, 'post.json'), 'w'))
    print('clearance issues:', B.check_clearance(cam, F0, F1, min_dist=.35, step=6))
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, 'shot.blend'))
    print('saved', os.path.join(OUT, 'shot.blend'))


def mathutils_vec(v):
    import mathutils
    return mathutils.Vector(v)


if __name__ == '__main__':
    main()
