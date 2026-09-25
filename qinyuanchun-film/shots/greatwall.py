"""明长城（箭扣—慕田峪一带）的程序化建模：沿山脊路径扫掠出墙体，外侧垛口、内侧宇墙，制高点上建敌楼。

尺寸按明代山地长城的常见规制：墙高约 6.5 m（含基础埋入地下），顶宽约 4.5 m（马道），
外侧垛墙高 1.8 m、每 2.2 m 一个垛口；内侧宇墙高 0.9 m；敌楼约 10×10 m、高出马道 9 m，四面各开 3 个拱窗。
"""
import math

import bpy
import mathutils
import numpy as np

from common import blend as B


def smooth_path(xy, step=1.0, iters=3, win=9):
    """去掉栅格路径的锯齿：多次滑动平均后按弧长等距重采样。"""
    p = np.asarray(xy, float)
    for _ in range(iters):
        k = np.ones(win) / win
        q = np.stack([np.convolve(np.pad(p[:, c], win // 2, mode='edge'), k, 'valid') for c in range(2)], 1)
        q[0], q[-1] = p[0], p[-1]
        p = q
    d = np.concatenate([[0], np.cumsum(np.hypot(*np.diff(p, axis=0).T))])
    s = np.arange(0, d[-1], step)
    return np.stack([np.interp(s, d, p[:, 0]), np.interp(s, d, p[:, 1])], 1), s


def frames(p):
    t = np.gradient(p, axis=0)
    t /= np.linalg.norm(t, axis=1, keepdims=True) + 1e-9
    nrm = np.stack([-t[:, 1], t[:, 0]], 1)          # 左手法向（外侧）
    return t, nrm


def walk_height(ground_c, ground_max, wall_h=5.2, smooth=15):
    """马道高度：沿路径平滑后的地面 + 墙高，并保证不低于横截面上最高的地面 + 0.8 m。"""
    k = np.ones(smooth) / smooth
    g = np.convolve(np.pad(ground_c, smooth // 2, mode='edge'), k, 'valid')
    return np.maximum(g + wall_h, ground_max + .8)


def _fix_normals(me):
    import bmesh
    bm = bmesh.new(); bm.from_mesh(me)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me); bm.free(); me.update()


def _mesh(name, verts, faces, mat, smooth=False):
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts.tolist() if hasattr(verts, 'tolist') else verts, [], faces)
    me.update()
    _fix_normals(me)
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    me.materials.append(mat)
    return ob


def wall_body(p, nrm, walk, base, mat):
    """墙体横截面扫掠（外墙面带收分）：外底 → 外顶 → 马道 → 内顶 → 内底。垛墙与宇墙另建。"""
    prof = [(-3.1, 'b'), (-2.45, 'w'), (2.45, 'w'), (3.1, 'b')]       # (横向偏移, 高度取 base 或 walk)
    V = []
    for i in range(len(p)):
        for off, k in prof:
            z = base[i] if k == 'b' else walk[i]
            V.append((p[i, 0] + nrm[i, 0] * off, p[i, 1] + nrm[i, 1] * off, z))
    m = len(prof)
    F = []
    for i in range(len(p) - 1):
        for j in range(m - 1):
            a = i * m + j
            F.append((a, a + 1, a + m + 1, a + m))
    # 两端封口
    F.append(tuple(range(m - 1, -1, -1)))
    F.append(tuple((len(p) - 1) * m + j for j in range(m)))
    return _mesh('wall_body', np.array(V), F, mat)


def parapets(p, t, nrm, walk, mat, merlon_every=2.2, gap=.55):
    """外侧垛墙：连续的矮墙（高 0.95 m）+ 一个个垛（再高 0.9 m），垛与垛之间留垛口；内侧宇墙高 0.9 m。
    在陡坡上跟着马道一起升降（台阶式）。全部做成盒子，便于雪只积在顶面上。"""
    V, F = [], []

    def box(c, tx, ty, nx, ny, L, Wd, z0, z1):
        b = len(V)
        for sx in (-L / 2, L / 2):
            for sy in (-Wd / 2, Wd / 2):
                for z in (z0, z1):
                    V.append((c[0] + tx * sx + nx * sy, c[1] + ty * sx + ny * sy, z))
        # 顶点顺序：(sx,sy,z) → 索引 b + (ix*2+iy)*2 + iz
        idx = lambda ix, iy, iz: b + (ix * 2 + iy) * 2 + iz
        F.extend([(idx(0, 0, 0), idx(0, 1, 0), idx(1, 1, 0), idx(1, 0, 0)),
                  (idx(0, 0, 1), idx(1, 0, 1), idx(1, 1, 1), idx(0, 1, 1)),
                  (idx(0, 0, 0), idx(1, 0, 0), idx(1, 0, 1), idx(0, 0, 1)),
                  (idx(0, 1, 0), idx(0, 1, 1), idx(1, 1, 1), idx(1, 1, 0)),
                  (idx(0, 0, 0), idx(0, 0, 1), idx(0, 1, 1), idx(0, 1, 0)),
                  (idx(1, 0, 0), idx(1, 1, 0), idx(1, 1, 1), idx(1, 0, 1))])

    seg = 1.1
    s = np.concatenate([[0], np.cumsum(np.hypot(*np.diff(p, axis=0).T))])
    n_seg = int(s[-1] / seg)
    for k in range(n_seg):
        i = int(np.searchsorted(s, (k + .5) * seg))
        i = min(i, len(p) - 1)
        tx, ty = t[i]; nx, ny = nrm[i]; w = walk[i]
        c_out = p[i] + nrm[i] * 2.15
        c_in = p[i] - nrm[i] * 2.2
        box(c_out, tx, ty, nx, ny, seg + .02, .6, w - .3, w + .95)        # 垛墙下段
        box(c_in, tx, ty, nx, ny, seg + .02, .5, w - .3, w + .9)          # 宇墙
    rng = np.random.default_rng(17)
    n_m = int(s[-1] / merlon_every)
    for k in range(n_m):
        # 野长城：少数垛已经塌了，其余高低、宽窄略有参差
        if rng.uniform() < .12:
            continue
        i = min(int(np.searchsorted(s, (k + .5) * merlon_every)), len(p) - 1)
        tx, ty = t[i]; nx, ny = nrm[i]; w = walk[i]
        c_out = p[i] + nrm[i] * 2.15
        top = w + 1.85 - (rng.uniform(.2, .8) if rng.uniform() < .15 else rng.uniform(0, .12))
        box(c_out, tx, ty, nx, ny, merlon_every - gap - rng.uniform(0, .15), .6, w + .9, top)
    return _mesh('parapets', np.array(V), F, mat)


def tower_mesh(mat, size=10.0, h_above=9.0, depth=14.0, taper=.25):
    """单个敌楼（原点在马道中心，局部 x 沿城墙方向）：略带收分的楼身 + 顶部垛墙。"""
    V, F = [], []
    hs = size / 2
    z0, z1 = -depth, h_above
    # 楼身（8 顶点，上窄下宽）
    for z, e in ((z0, hs + taper), (z1, hs)):
        for x, y in ((-e, -e), (e, -e), (e, e), (-e, e)):
            V.append((x, y, z))
    F += [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    # 顶部垛墙
    def box(x0, x1, y0, y1, za, zb):
        b = len(V)
        for z in (za, zb):
            for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
                V.append((x, y, z))
        F.extend([(b, b + 3, b + 2, b + 1), (b + 4, b + 5, b + 6, b + 7), (b, b + 1, b + 5, b + 4),
                  (b + 1, b + 2, b + 6, b + 5), (b + 2, b + 3, b + 7, b + 6), (b + 3, b, b + 4, b + 7)])
    th = .55
    for k in range(5):
        a = -hs + k * size / 5 + .35; b2 = a + size / 5 - .7
        for side in (-1, 1):
            box(a, b2, side * hs - (th if side > 0 else 0), side * hs + (0 if side > 0 else th), z1, z1 + 1.6)
            box(side * hs - (th if side > 0 else 0), side * hs + (0 if side > 0 else th), a, b2, z1, z1 + 1.6)
    box(-hs, hs, -hs, -hs + th, z1, z1 + .8); box(-hs, hs, hs - th, hs, z1, z1 + .8)
    box(-hs, -hs + th, -hs, hs, z1, z1 + .8); box(hs - th, hs, -hs, hs, z1, z1 + .8)
    me = bpy.data.meshes.new('tower')
    me.from_pydata(V, [], F); me.update()
    _fix_normals(me)
    me.materials.append(mat)
    return me


def place_towers(p, t, walk, ground_fn, me, every=260.0, min_gap=150.0):
    """在路径上的局部制高点放敌楼，间距不小于 min_gap；长距离没有制高点时按 every 补一座。"""
    s = np.concatenate([[0], np.cumsum(np.hypot(*np.diff(p, axis=0).T))])
    cand = [i for i in range(20, len(p) - 20) if walk[i] >= walk[max(0, i - 25):i + 26].max() - .01]
    chosen = []
    for i in cand:
        if not chosen or s[i] - s[chosen[-1]] > min_gap:
            chosen.append(i)
    extra = []
    allc = sorted(chosen)
    for a, b in zip([0] + allc, allc + [len(p) - 1]):
        gap = s[b] - s[a]
        k = int(gap // every)
        for m in range(1, k + 1):
            extra.append(int(np.searchsorted(s, s[a] + gap * m / (k + 1))))
    obs = []
    for i in sorted(set(chosen + extra)):
        ob = bpy.data.objects.new(f'tower{i}', me)
        bpy.context.scene.collection.objects.link(ob)
        ob.location = (p[i, 0], p[i, 1], walk[i])
        ob.rotation_euler = (0, 0, math.atan2(t[i, 1], t[i, 0]))
        obs.append((ob, i))
    return obs


def mat_brick(name='brick', base=(.33, .32, .31), snow=True):
    """城砖：砖缝 + 砖色深浅 + 风化斑驳；朝上的面积雪（带噪声，边缘有碎齿）。"""
    m, nb, out = B.new_material(name)
    tc = nb.node('ShaderNodeTexCoord')
    geo = nb.node('ShaderNodeNewGeometry')
    # 用世界坐标：水平方向取沿墙方向的长度近似（x+y），竖直取 z
    sep = nb.node('ShaderNodeSeparateXYZ'); nb.link(tc.outputs['Object'], sep.inputs[0])
    u = nb.math('ADD', sep.outputs['X'], sep.outputs['Y'])
    comb = nb.node('ShaderNodeCombineXYZ'); nb.link(u, comb.inputs[0]); nb.link(sep.outputs['Z'], comb.inputs[1])
    br = nb.node('ShaderNodeTexBrick')
    nb.link(comb.outputs[0], br.inputs['Vector'])
    br.inputs['Scale'].default_value = 2.4
    br.inputs['Mortar Size'].default_value = .015
    br.inputs['Brick Width'].default_value = .42; br.inputs['Row Height'].default_value = .11
    br.inputs['Color1'].default_value = (*base, 1)
    br.inputs['Color2'].default_value = (base[0] * .8, base[1] * .8, base[2] * .82, 1)
    br.inputs['Mortar'].default_value = (.5, .49, .47, 1)
    wx = nb.noise(tc.outputs['Object'], .35, 4, .6)
    col = nb.mix(nb.maprange(wx, .3, .7, 0, .35), br.outputs['Color'], (.18, .17, .16, 1), 'RGBA', 'MULTIPLY')
    col = nb.mix(nb.maprange(nb.noise(tc.outputs['Object'], 2.0, 3, .5), .55, .75, 0, .25), col, (.55, .52, .47, 1))
    nz = nb.vmath('DOT_PRODUCT', geo.outputs['Normal'], (0, 0, 1))
    sn = nb.maprange(nb.math('ADD', nz, nb.math('MULTIPLY', nb.math('SUBTRACT', nb.noise(tc.outputs['Object'], 3.0, 3, .6), .5), .5)), .55, .75)
    if not snow:
        sn = 0.0
    bump = nb.bump(br.outputs['Fac'], .25, .02)
    bsdf = B.principled(nb, Roughness=nb.mix(sn, .85, .6, 'FLOAT'))
    nb.link(nb.mix(sn, col, (.88, .9, .95, 1)), bsdf.inputs['Base Color'])
    nb.link(nb.mix(sn, bump, geo.outputs['Normal'], 'VECTOR'), bsdf.inputs['Normal'])
    nb.link(bsdf.outputs[0], out.inputs['Surface'])
    return m


def mat_tower(name='tower'):
    """敌楼：城砖 + 每面三个深色拱窗（物体坐标里画出来），顶面积雪。"""
    m, nb, out = B.new_material(name)
    tc = nb.node('ShaderNodeTexCoord').outputs['Object']
    geo = nb.node('ShaderNodeNewGeometry')
    sep = nb.node('ShaderNodeSeparateXYZ'); nb.link(tc, sep.inputs[0])
    X, Y, Z = sep.outputs['X'], sep.outputs['Y'], sep.outputs['Z']
    u = nb.math('ADD', X, Y)
    comb = nb.node('ShaderNodeCombineXYZ'); nb.link(u, comb.inputs[0]); nb.link(Z, comb.inputs[1])
    br = nb.node('ShaderNodeTexBrick'); nb.link(comb.outputs[0], br.inputs['Vector'])
    br.inputs['Scale'].default_value = 2.4; br.inputs['Mortar Size'].default_value = .015
    br.inputs['Brick Width'].default_value = .42; br.inputs['Row Height'].default_value = .11
    br.inputs['Color1'].default_value = (.34, .33, .31, 1); br.inputs['Color2'].default_value = (.27, .26, .25, 1)
    br.inputs['Mortar'].default_value = (.5, .49, .47, 1)
    # 拱窗：沿墙面的水平坐标（取 |X|、|Y| 中较小者的那个方向）按 10/3 m 周期，宽 1.1 m、高 2.2 m、顶部半圆
    h = nb.math('MINIMUM', nb.math('ABSOLUTE', X), nb.math('ABSOLUTE', Y))
    hx = nb.math('SUBTRACT', nb.math('ABSOLUTE', nb.math('SUBTRACT', nb.math('ABSOLUTE', h), 3.3)), 0.0)
    cx = nb.math('MINIMUM', nb.math('ABSOLUTE', h), hx)          # 离最近窗中心（0 或 ±3.3 m）的水平距离
    zc = nb.math('SUBTRACT', Z, 4.2)
    rect = nb.math('MULTIPLY', nb.math('LESS_THAN', cx, .55), nb.math('MULTIPLY', nb.math('GREATER_THAN', zc, -1.3), nb.math('LESS_THAN', zc, .3)))
    arch = nb.math('LESS_THAN', nb.math('ADD', nb.math('MULTIPLY', cx, cx), nb.math('MULTIPLY', nb.math('SUBTRACT', zc, .3), nb.math('SUBTRACT', zc, .3))), .3025)
    win = nb.math('MAXIMUM', rect, nb.math('MULTIPLY', arch, nb.math('GREATER_THAN', zc, .3)))
    wall_side = nb.maprange(nb.math('ABSOLUTE', nb.vmath('DOT_PRODUCT', geo.outputs['Normal'], (0, 0, 1))), .3, .1)
    win = nb.math('MULTIPLY', win, wall_side)
    col = nb.mix(win, br.outputs['Color'], (.015, .014, .014, 1))
    nz = nb.vmath('DOT_PRODUCT', geo.outputs['Normal'], (0, 0, 1))
    sn = nb.maprange(nb.math('ADD', nz, nb.math('MULTIPLY', nb.math('SUBTRACT', nb.noise(tc, 3.0, 3, .6), .5), .5)), .55, .75)
    bsdf = B.principled(nb, Roughness=nb.mix(sn, .85, .6, 'FLOAT'))
    nb.link(nb.mix(sn, col, (.88, .9, .95, 1)), bsdf.inputs['Base Color'])
    nb.link(nb.bump(br.outputs['Fac'], .25, .02), bsdf.inputs['Normal'])
    nb.link(bsdf.outputs[0], out.inputs['Surface'])
    return m
