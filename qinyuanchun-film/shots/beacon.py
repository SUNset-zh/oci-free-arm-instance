"""夯土烽火台：圆角方形（超椭圆）截面、上小下大，雨水冲出竖向沟槽，顶部与一角坍塌；
一层层夯土的层理、雨痕、积雪都在材质里。几何在柱坐标里生成，天然闭合、无接缝。"""
import math

import bpy
import numpy as np

from common import blend as B
from common import npnoise as NN


def _pfbm(TH, Z, kx, off, kz, perm, octaves):
    """沿 θ 周期的噪声（首尾混合），避免 θ=0 处出现接缝。"""
    sgm = TH / (2 * math.pi)
    a = NN.fbm(TH * kx + off, Z * kz, perm, 1.0, octaves, 2.0, .5)
    b = NN.fbm((TH - 2 * math.pi) * kx + off, Z * kz, perm, 1.0, octaves, 2.0, .5)
    return a * (1 - sgm) + b * sgm


def tower(name='beacon', base_half=4.6, top_half=2.9, height=13.5, p_exp=6.0, n_th=320, n_z=110, seed=7, bury=3.0):
    rng = np.random.default_rng(seed)
    perm = NN.make_perm(seed)
    th = np.linspace(0, 2 * math.pi, n_th, endpoint=False)
    zs = np.linspace(-bury, height, n_z)
    TH, Z = np.meshgrid(th, zs)
    sq = (np.abs(np.cos(TH)) ** p_exp + np.abs(np.sin(TH)) ** p_exp) ** (-1 / p_exp)     # 圆角方形
    zz = np.clip(Z, 0, height)
    R = (base_half + (top_half - base_half) * zz / height) * sq
    # 侵蚀：竖向拉长的噪声 → 雨水冲沟；越往上越烂
    g1 = _pfbm(TH, Z, 6.0, 0.0, .18, perm, 4)
    g2 = _pfbm(TH, Z, 18.0, 40.0, .5, perm, 3)
    ero = .26 * np.maximum(g1, -.2) + .05 * g2
    ero += .6 * np.clip((zz - height * .7) / (height * .3), 0, 1) * np.maximum(_pfbm(TH, Z, 4.2, 9.0, .3, perm, 3) + .2, 0)
    # 一角大块坍塌（朝向随机）
    ca = rng.uniform(0, 2 * math.pi)
    dang = np.angle(np.exp(1j * (TH - ca)))
    ero += 1.5 * np.exp(-(dang / .35) ** 2) * np.clip((zz - height * .45) / (height * .55), 0, 1) ** 1.5
    R = np.maximum(R - ero, 1.0)
    X = R * np.cos(TH); Y = R * np.sin(TH)
    V = np.stack([X, Y, Z], -1).reshape(-1, 3)
    F = []
    for j in range(n_z - 1):
        for i in range(n_th):
            i2 = (i + 1) % n_th
            a = j * n_th + i; b = j * n_th + i2
            F.append((a, b, b + n_th, a + n_th))
    # 顶面：从顶圈向中心收成一个起伏的平台（坍塌得坑坑洼洼）
    top_ring = (n_z - 1) * n_th
    rings = 10
    rt = R[-1]
    base_idx = len(V)
    extra = []
    for k in range(1, rings):
        f = 1 - k / rings
        zk = height + .35 * NN.fbm(np.cos(th) * 3 * f + 5, np.sin(th) * 3 * f, perm, 1.0, 3, 2.0, .5) - .5 * (1 - f)
        extra.append(np.stack([rt * f * np.cos(th), rt * f * np.sin(th), zk], -1))
    V = np.concatenate([V] + extra + [np.array([[0, 0, height - .4]])], 0)
    prev = top_ring
    for k in range(1, rings):
        cur = base_idx + (k - 1) * n_th
        for i in range(n_th):
            i2 = (i + 1) % n_th
            F.append((prev + i, prev + i2, cur + i2, cur + i))
        prev = cur
    c = len(V) - 1
    for i in range(n_th):
        F.append((prev + i, prev + (i + 1) % n_th, c))
    me = bpy.data.meshes.new(name)
    me.from_pydata(V.tolist(), [], F)
    me.update()
    import bmesh
    bm = bmesh.new(); bm.from_mesh(me)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me); bm.free()
    me.polygons.foreach_set('use_smooth', np.ones(len(me.polygons), bool))
    me.update()
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def mat_earth(name='rammed_earth'):
    """夯土：水平夯层（每层约 16 cm，层间略凹）+ 每隔一米一排的“棒孔”（当年夹板横木留下的洞）
    + 大尺度色块 + 轻微的雨痕 + 顶面积雪。"""
    m, nb, out = B.new_material(name)
    tc = nb.node('ShaderNodeTexCoord').outputs['Object']
    geo = nb.node('ShaderNodeNewGeometry')
    sep = nb.node('ShaderNodeSeparateXYZ'); nb.link(tc, sep.inputs[0])
    X, Y, z = sep.outputs['X'], sep.outputs['Y'], sep.outputs['Z']
    n_big = nb.noise(tc, .25, 3, .55)
    layer = nb.math('SINE', nb.math('ADD', nb.math('MULTIPLY', z, 2 * math.pi / .17), nb.math('MULTIPLY', nb.noise(tc, .8, 2, .5), 1.5)))
    lay = nb.maprange(layer, -1, 1, .82, 1.06, 'LINEAR')
    # 棒孔：沿周长方向（用 atan2 求角度×半径近似弧长）每 1.4 m、竖向每 1.05 m 一个 18×14 cm 的暗洞
    ang = nb.math('ARCTAN2', Y, X)
    arc = nb.math('MULTIPLY', ang, 4.0)
    fu = nb.math('FRACT', nb.math('DIVIDE', nb.math('ADD', arc, nb.math('MULTIPLY', nb.noise(tc, .9, 2, .5), .6)), 1.9))
    fz = nb.math('FRACT', nb.math('DIVIDE', nb.math('ADD', z, .3), 1.25))
    hole = nb.math('MULTIPLY', nb.math('LESS_THAN', nb.math('ABSOLUTE', nb.math('SUBTRACT', fu, .5)), .065),
                   nb.math('LESS_THAN', nb.math('ABSOLUTE', nb.math('SUBTRACT', fz, .5)), .07))
    hole = nb.math('MULTIPLY', hole, nb.math('GREATER_THAN', nb.noise(tc, .6, 2, .5), .56))       # 大半的洞被土填平了
    streak_map = nb.node('ShaderNodeMapping', vector_type='POINT'); nb.link(tc, streak_map.inputs['Vector'])
    streak_map.inputs['Scale'].default_value = (3.0, 3.0, .15)
    streak = nb.maprange(nb.noise(streak_map.outputs[0], 1.6, 3, .6), .5, .72, 1.0, .88)
    col = nb.mix(nb.maprange(n_big, .3, .7), (.43, .34, .23, 1), (.53, .43, .3, 1))
    col = nb.mix(1.0, col, lay, 'RGBA', 'MULTIPLY')
    col = nb.mix(1.0, col, streak, 'RGBA', 'MULTIPLY')
    col = nb.mix(hole, col, (.04, .03, .025, 1))
    nz = nb.vmath('DOT_PRODUCT', geo.outputs['Normal'], (0, 0, 1))
    sn = nb.maprange(nb.math('ADD', nz, nb.math('MULTIPLY', nb.math('SUBTRACT', nb.noise(tc, 2.0, 3, .6), .5), .6)), .5, .72)
    bump = nb.bump(nb.math('SUBTRACT', nb.math('ADD', nb.math('MULTIPLY', layer, .45), nb.noise(tc, 3.0, 4, .6)), nb.math('MULTIPLY', hole, 1.5)), .6, .05)
    bsdf = B.principled(nb, Roughness=nb.mix(sn, .95, .6, 'FLOAT'))
    nb.link(nb.mix(sn, col, (.86, .88, .92, 1)), bsdf.inputs['Base Color'])
    nb.link(bump, bsdf.inputs['Normal'])
    nb.link(bsdf.outputs[0], out.inputs['Surface'])
    return m
