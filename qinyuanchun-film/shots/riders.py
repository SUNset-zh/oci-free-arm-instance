"""草原骑手：Horse.glb 的奔跑形变动画（按真实步频重映射）+ 程序化的蒙古骑手（皮帽、长袍、弓、箭囊）
+ 程序化的雕（宽翼、翼尖分叉的初级飞羽、扇形尾），以剪影为主要观感来设计。"""
import math

import bmesh
import bpy
import mathutils
import numpy as np

from common import blend as B

V = mathutils.Vector


def mat_dark(name, col=(.035, .03, .028), rough=.8, sheen=0.0):
    m, nb, out = B.new_material(name)
    b = B.principled(nb, Roughness=rough)
    b.inputs['Base Color'].default_value = (*col, 1)
    b.inputs['Sheen Weight'].default_value = sheen
    nb.link(b.outputs[0], out.inputs['Surface'])
    return m


# ---------------------------------------------------------------- 马
def load_horse(path, scale=.0068):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    o = [o for o in bpy.data.objects if o not in before][0]
    o.rotation_mode = 'XYZ'
    o.scale = (scale, scale, scale)
    ad = o.data.shape_keys.animation_data
    act = ad.action
    ad.action = None
    curves = {fc.data_path.split('"')[1]: fc for fc in act.fcurves if '"' in fc.data_path}
    return o, curves, act.frame_range[1]


def animate_horse(o, curves, cycle, f0, f1, fps, period=.42, phase=0.0, path_fn=None):
    """形变按真实步频播放；path_fn(t) → (位置, 朝向角) 让马沿路线前进。"""
    kb = o.data.shape_keys.key_blocks
    for f in range(f0, f1 + 1):
        t = (f - f0) / fps
        tau = ((t / period + phase) % 1.0) * cycle
        for name, fc in curves.items():
            kb[name].value = fc.evaluate(tau)
            kb[name].keyframe_insert('value', frame=f)
        if path_fn is not None:
            p, yaw = path_fn(t)
            o.location = p; o.rotation_euler = (0, 0, yaw)
            o.keyframe_insert('location', frame=f); o.keyframe_insert('rotation_euler', frame=f)


def saddle_index(o):
    """马背（鞍位）顶点：静止形态下，身长中段里最高的点。"""
    co = np.array([v.co[:] for v in o.data.vertices])
    y = co[:, 1]; z = co[:, 2]
    lo, hi = np.percentile(y, 40), np.percentile(y, 58)
    m = (y > lo) & (y < hi)
    idx = np.nonzero(m)[0]
    return int(idx[np.argmax(z[idx])])


# ---------------------------------------------------------------- 骑手（局部坐标：原点在鞍座，+Y 朝马头，+Z 向上）
def _add(bm, geom_fn, **kw):
    return geom_fn(bm, **kw)


def rider_mesh(name, archer=False):
    """返回 (身体网格对象, 弓臂对象或 None)。弓臂在拉弓时单独转动。"""
    bm = bmesh.new()

    def part(fn, loc, rot=(0, 0, 0), scale=(1, 1, 1), **kw):
        tmp = bmesh.new()
        fn(tmp, **kw)
        M = mathutils.Matrix.LocRotScale(V(loc), mathutils.Euler([math.radians(a) for a in rot]).to_quaternion(), V(scale))
        bmesh.ops.transform(tmp, matrix=M, verts=tmp.verts)
        me = bpy.data.meshes.new('tmp'); tmp.to_mesh(me); tmp.free()
        bm.from_mesh(me); bpy.data.meshes.remove(me)

    cone = lambda b, **k: bmesh.ops.create_cone(b, cap_ends=True, segments=12, **k)
    sph = lambda b, **k: bmesh.ops.create_uvsphere(b, u_segments=12, v_segments=8, **k)
    # 长袍下摆（盖在马背两侧）、上身前倾、头、皮帽（圆顶 + 翻起的帽檐）
    part(cone, (0, -.02, .12), (-6, 0, 0), (1.0, 1.2, 1.0), radius1=.27, radius2=.17, depth=.36)
    part(cone, (0, .1, .48), (-22, 0, 0), (1.0, .8, 1.0), radius1=.18, radius2=.14, depth=.5)
    part(sph, (0, .24, .8), (0, 0, 0), (1, 1, 1.1), radius=.095)
    part(sph, (0, .23, .87), (-10, 0, 0), (1.15, 1.15, .75), radius=.11)
    part(cone, (0, .22, .95), (-10, 0, 0), (1, 1, 1), radius1=.06, radius2=.0, depth=.13)
    # 腿（贴着马身两侧，弯膝踩镫）
    for sgn in (-1, 1):
        part(cone, (sgn * .19, .08, -.1), (-30, sgn * 12, 0), (1, 1, 1), radius1=.06, radius2=.08, depth=.4)
        part(cone, (sgn * .22, .2, -.37), (20, 0, 0), (1, 1, 1), radius1=.05, radius2=.06, depth=.3)
    # 箭囊（斜挎在背后）
    part(cone, (.1, -.06, .5), (25, 0, 20), (1, 1, 1), radius1=.05, radius2=.06, depth=.45)
    if not archer:
        # 握缰的双臂：向前下方
        for sgn in (-1, 1):
            part(cone, (sgn * .14, .32, .44), (-120, 0, 0), (1, 1, 1), radius1=.035, radius2=.045, depth=.38)
    else:
        part(cone, (.14, .32, .44), (-120, 0, 0), (1, 1, 1), radius1=.035, radius2=.045, depth=.38)
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    ob = bpy.data.objects.new(name, me); bpy.context.scene.collection.objects.link(ob)
    arm = None
    if archer:
        # 弓臂：左臂 + 弓（原点在左肩），拉弓时整体抬起指向天空
        bm2 = bmesh.new()
        tmp = bmesh.new(); bmesh.ops.create_cone(tmp, cap_ends=True, segments=10, radius1=.05, radius2=.055, depth=.62)
        bmesh.ops.transform(tmp, matrix=mathutils.Matrix.LocRotScale(V((0, .31, 0)), mathutils.Euler((math.radians(90), 0, 0)).to_quaternion(), V((1, 1, 1))), verts=tmp.verts)
        me_t = bpy.data.meshes.new('t'); tmp.to_mesh(me_t); tmp.free(); bm2.from_mesh(me_t); bpy.data.meshes.remove(me_t)
        # 弓：一段反曲的弧（管状）
        pts = []
        for k in range(25):
            u = -1 + 2 * k / 24
            x = 0.0; z = .62 * u
            yb = .62 + .16 * (1 - u * u) - .05 * (abs(u) ** 3) * 2.5
            pts.append((x, yb, z))
        for a, b in zip(pts[:-1], pts[1:]):
            tmp = bmesh.new(); bmesh.ops.create_cone(tmp, cap_ends=True, segments=6, radius1=.018, radius2=.018,
                                                     depth=(V(b) - V(a)).length)
            mid = (V(a) + V(b)) / 2; d = (V(b) - V(a)).normalized()
            q = d.to_track_quat('Z', 'Y')
            bmesh.ops.transform(tmp, matrix=mathutils.Matrix.LocRotScale(mid, q, V((1, 1, 1))), verts=tmp.verts)
            me_t = bpy.data.meshes.new('t'); tmp.to_mesh(me_t); tmp.free(); bm2.from_mesh(me_t); bpy.data.meshes.remove(me_t)
        # 弓弦（细线）+ 箭
        for a, b, r in [((0, .6, .62), (0, .6, -.62), .005), ((0, -.1, 0), (0, .95, 0), .008)]:
            tmp = bmesh.new(); bmesh.ops.create_cone(tmp, cap_ends=True, segments=5, radius1=r, radius2=r, depth=(V(b) - V(a)).length)
            mid = (V(a) + V(b)) / 2; q = (V(b) - V(a)).normalized().to_track_quat('Z', 'Y')
            bmesh.ops.transform(tmp, matrix=mathutils.Matrix.LocRotScale(mid, q, V((1, 1, 1))), verts=tmp.verts)
            me_t = bpy.data.meshes.new('t'); tmp.to_mesh(me_t); tmp.free(); bm2.from_mesh(me_t); bpy.data.meshes.remove(me_t)
        me2 = bpy.data.meshes.new(name + '_bow'); bm2.to_mesh(me2); bm2.free()
        arm = bpy.data.objects.new(name + '_bow', me2); bpy.context.scene.collection.objects.link(arm)
        arm.parent = ob; arm.location = (-.15, .2, .62)
    return ob, arm


# ---------------------------------------------------------------- 雕
def eagle(name='eagle', span=2.3):
    """俯视轮廓（米）：身体 + 扇形尾 + 两翼（宽、翼尖 6 根分叉的初级飞羽），挤出成薄片。两翼单独成对象以便扇动。"""
    s = span / 2.3
    body = [(0, .55), (.07, .45), (.11, .2), (.1, -.25), (.2, -.62), (.12, -.7), (0, -.66), (-.12, -.7), (-.2, -.62), (-.1, -.25), (-.11, .2), (-.07, .45)]
    wing = [(.08, .18), (.45, .26), (.8, .22), (1.0, .16)]
    fingers = []
    for k in range(6):
        a0 = .16 - k * .075
        fingers += [(1.0 + .02 * k, a0 + .01), (1.15 - .02 * abs(k - 2), a0 - .02), (1.0 + .02 * k, a0 - .045)]
    wing += fingers + [(.95, -.33), (.6, -.3), (.3, -.26), (.08, -.14)]

    def poly_obj(nm, pts, thick=.03, mirror=False):
        bm = bmesh.new()
        vs = [bm.verts.new((x * s * (-1 if mirror else 1), y * s, 0)) for x, y in pts]
        f = bm.faces.new(vs if not mirror else list(reversed(vs)))
        bmesh.ops.triangulate(bm, faces=[f])
        ext = bmesh.ops.extrude_face_region(bm, geom=bm.faces[:])
        bmesh.ops.translate(bm, verts=[e for e in ext['geom'] if isinstance(e, bmesh.types.BMVert)], vec=(0, 0, thick))
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        me = bpy.data.meshes.new(nm); bm.to_mesh(me); bm.free()
        o = bpy.data.objects.new(nm, me); bpy.context.scene.collection.objects.link(o)
        return o

    b = poly_obj(name, body, .08)
    wl = poly_obj(name + '_wl', wing, .025, mirror=True)
    wr = poly_obj(name + '_wr', wing, .025)
    for w in (wl, wr):
        w.parent = b
    return b, wl, wr


def animate_eagle(b, wl, wr, path_fn, f0, f1, fps, flaps=((1.2, 2.6),), flap_period=.9):
    """滑翔为主，在 flaps 列出的时间段里缓慢扇翅。path_fn(t) → (位置, 航向角, 侧倾角)。"""
    for f in range(f0, f1 + 1):
        t = (f - f0) / fps
        p, yaw, bank = path_fn(t)
        b.location = p; b.rotation_mode = 'XYZ'; b.rotation_euler = (0, bank, yaw)
        b.keyframe_insert('location', frame=f); b.keyframe_insert('rotation_euler', frame=f)
        amp = 0.0
        for (a0, a1) in flaps:
            if a0 <= t <= a1:
                w = min(1, (t - a0) / .3, (a1 - t) / .3)
                amp = max(amp, w)
        ang = math.radians(8 + 28 * amp * math.sin(2 * math.pi * t / flap_period))
        wl.rotation_mode = 'XYZ'; wr.rotation_mode = 'XYZ'
        wl.rotation_euler = (0, ang, 0); wr.rotation_euler = (0, -ang, 0)
        wl.keyframe_insert('rotation_euler', frame=f); wr.keyframe_insert('rotation_euler', frame=f)
