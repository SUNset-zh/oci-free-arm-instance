"""冬季山林：油松（叠锥形，枝上压着雪）+ 落叶杂木（枝干 + 半透明的细枝团）。
用几何节点“在点上实例化”，几十万棵树只占一份网格的内存。"""
import math

import bpy
import numpy as np

from common import blend as B


def _cone(V, F, cx, cy, z0, z1, r0, r1, sides):
    b = len(V)
    for k in range(sides):
        a = 2 * math.pi * k / sides
        V.append((cx + r0 * math.cos(a), cy + r0 * math.sin(a), z0))
    for k in range(sides):
        a = 2 * math.pi * k / sides
        V.append((cx + r1 * math.cos(a), cy + r1 * math.sin(a), z1))
    for k in range(sides):
        k2 = (k + 1) % sides
        F.append((b + k, b + k2, b + sides + k2, b + sides + k))
    if r1 < 1e-3:
        pass
    F.append(tuple(b + sides + k for k in range(sides)))
    F.append(tuple(b + k for k in range(sides - 1, -1, -1)))


def _limb(V, F, p0, p1, r0, r1, sides=4):
    """从 p0 到 p1 的细锥（树枝）。"""
    p0 = np.array(p0, float); p1 = np.array(p1, float)
    d = p1 - p0; L = np.linalg.norm(d); d /= L
    a = np.cross(d, [0, 0, 1.0]);
    if np.linalg.norm(a) < 1e-3: a = np.array([1.0, 0, 0])
    a /= np.linalg.norm(a); bvec = np.cross(d, a)
    b = len(V)
    for (c, r) in ((p0, r0), (p1, r1)):
        for k in range(sides):
            t = 2 * math.pi * k / sides
            V.append(tuple(c + r * (math.cos(t) * a + math.sin(t) * bvec)))
    for k in range(sides):
        k2 = (k + 1) % sides
        F.append((b + k, b + k2, b + sides + k2, b + sides + k))


def mat_pine():
    m, nb, out = B.new_material('pine')
    tc = nb.node('ShaderNodeTexCoord').outputs['Object']
    geo = nb.node('ShaderNodeNewGeometry')
    nz = nb.vmath('DOT_PRODUCT', geo.outputs['Normal'], (0, 0, 1))
    n = nb.noise(tc, 2.5, 3, .6)
    snow = nb.maprange(nb.math('ADD', nz, nb.math('MULTIPLY', nb.math('SUBTRACT', n, .5), .9)), .25, .55)
    needles = nb.mix(nb.noise(tc, 6.0, 2, .5), (.012, .022, .014, 1), (.03, .045, .03, 1))
    bsdf = B.principled(nb, Roughness=.8)
    nb.link(nb.mix(snow, needles, (.85, .88, .93, 1)), bsdf.inputs['Base Color'])
    nb.link(nb.bump(n, .6, .3), bsdf.inputs['Normal'])
    nb.link(bsdf.outputs[0], out.inputs['Surface'])
    return m


def mat_bark():
    m, nb, out = B.new_material('bark')
    geo = nb.node('ShaderNodeNewGeometry')
    nz = nb.vmath('DOT_PRODUCT', geo.outputs['Normal'], (0, 0, 1))
    snow = nb.maprange(nz, .35, .6)
    bsdf = B.principled(nb, Roughness=.85)
    nb.link(nb.mix(snow, (.05, .045, .04, 1), (.8, .83, .88, 1)), bsdf.inputs['Base Color'])
    nb.link(bsdf.outputs[0], out.inputs['Surface'])
    return m


def mat_twigs():
    """细枝团：大部分透明，用噪声做出一簇簇的细枝，灰褐色，顶面挂一点雪。"""
    m, nb, out = B.new_material('twigs')
    tc = nb.node('ShaderNodeTexCoord').outputs['Object']
    geo = nb.node('ShaderNodeNewGeometry')
    n1 = nb.noise(tc, 3.5, 4, .7, distortion=1.5)
    n2 = nb.noise(tc, 11.0, 2, .6)
    dens = nb.maprange(nb.math('ADD', n1, nb.math('MULTIPLY', n2, .4)), .68, .82)
    nz = nb.vmath('DOT_PRODUCT', geo.outputs['Normal'], (0, 0, 1))
    snow = nb.math('MULTIPLY', nb.maprange(nz, .3, .8), .6)
    bsdf = B.principled(nb, Roughness=.9)
    nb.link(nb.mix(snow, (.07, .06, .055, 1), (.75, .78, .84, 1)), bsdf.inputs['Base Color'])
    tr = nb.node('ShaderNodeBsdfTransparent')
    mix = nb.node('ShaderNodeMixShader')
    nb.link(dens, mix.inputs[0]); nb.link(tr.outputs[0], mix.inputs[1]); nb.link(bsdf.outputs[0], mix.inputs[2])
    nb.link(mix.outputs[0], out.inputs['Surface'])
    return m


def make_protos(seed=3, pines=True):
    """返回原型树对象列表（都放在一个隐藏的集合里）。"""
    rng = np.random.default_rng(seed)
    col = bpy.data.collections.new('tree_protos')
    bpy.context.scene.collection.children.link(col)
    col.hide_render = False
    mp, mb, mtw = mat_pine(), mat_bark(), mat_twigs()
    protos = []
    # 油松：3~4 层下垂的锥（只做一个原型，约占四分之一）
    for v in range(1 if pines else 0):
        V, F = [], []
        _cone(V, F, 0, 0, 0, 2.2, .18, .12, 6)
        h = 2.0
        layers = 4
        for k in range(layers):
            r = 2.4 * (1 - k / layers) + .4 + rng.uniform(-.2, .2)
            _cone(V, F, rng.uniform(-.1, .1), rng.uniform(-.1, .1), h, h + 2.2, r, .05, 9)
            h += 1.5 + rng.uniform(-.2, .2)
        me = bpy.data.meshes.new(f'pine{v}'); me.from_pydata(V, [], F); me.update(); me.materials.append(mp)
        ob = bpy.data.objects.new(f'pine{v}', me); col.objects.link(ob); protos.append(ob)
    # 落叶杂木：主干 + 5 根主枝 + 3~4 个细枝团（低面数椭球）
    for v in range(3):
        V, F = [], []
        _limb(V, F, (0, 0, -.3), (0, 0, 4.2), .16, .07, 6)
        tips = []
        for k in range(5):
            a = rng.uniform(0, 2 * math.pi); z0 = rng.uniform(2.0, 3.6); L = rng.uniform(1.8, 2.8)
            p1 = (math.cos(a) * L * .8, math.sin(a) * L * .8, z0 + L * .7)
            _limb(V, F, (0, 0, z0), p1, .07, .02, 4)
            tips.append(p1)
        me = bpy.data.meshes.new(f'dec{v}'); me.from_pydata(V, [], F); me.update(); me.materials.append(mb)
        me.materials.append(mtw)
        # 细枝团
        import bmesh
        bm = bmesh.new(); bm.from_mesh(me)
        for tp in tips[:4]:
            r = rng.uniform(.9, 1.4)
            res = bmesh.ops.create_icosphere(bm, subdivisions=2, radius=r)
            for vv in res['verts']:
                vv.co.x = vv.co.x * 1.0 + tp[0] * .7; vv.co.y = vv.co.y * 1.0 + tp[1] * .7; vv.co.z = vv.co.z * .75 + tp[2]
            for f in {f for vv in res['verts'] for f in vv.link_faces}:
                f.material_index = 1
        bm.to_mesh(me); bm.free(); me.update()
        ob = bpy.data.objects.new(f'dec{v}', me); col.objects.link(ob); protos.append(ob)
    for ob in protos:
        ob.location = (0, 0, -10000)       # 原型放到地下，只用它们的实例
    return col, protos


def scatter(name, pts, col, rng_seed=1, scale=(.75, 1.25)):
    """pts: (N,3) 树根位置。几何节点：在点上实例化集合里的子对象（随机挑选、随机旋转与缩放）。"""
    me = bpy.data.meshes.new(name)
    me.vertices.add(len(pts)); me.vertices.foreach_set('co', np.asarray(pts, np.float32).ravel())
    me.update()
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    ng = bpy.data.node_groups.new(name + '_gn', 'GeometryNodeTree')
    ng.interface.new_socket('Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
    ng.interface.new_socket('Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')
    N = ng.nodes; Lk = ng.links
    gi = N.new('NodeGroupInput'); go = N.new('NodeGroupOutput')
    ci = N.new('GeometryNodeCollectionInfo'); ci.inputs['Collection'].default_value = col
    ci.inputs['Separate Children'].default_value = True; ci.inputs['Reset Children'].default_value = True
    iop = N.new('GeometryNodeInstanceOnPoints'); iop.inputs['Pick Instance'].default_value = True
    ridx = N.new('FunctionNodeRandomValue'); ridx.data_type = 'INT'
    ridx.inputs['Min'].default_value = 0; ridx.inputs['Max'].default_value = 100; ridx.inputs['Seed'].default_value = rng_seed
    rrot = N.new('FunctionNodeRandomValue'); rrot.data_type = 'FLOAT_VECTOR'
    rrot.inputs['Min'].default_value = (-.06, -.06, 0); rrot.inputs['Max'].default_value = (.06, .06, 6.283)
    rrot.inputs['Seed'].default_value = rng_seed + 1
    rsc = N.new('FunctionNodeRandomValue'); rsc.data_type = 'FLOAT'
    rsc.inputs['Min'].default_value = scale[0]; rsc.inputs['Max'].default_value = scale[1]; rsc.inputs['Seed'].default_value = rng_seed + 2
    Lk.new(gi.outputs['Geometry'], iop.inputs['Points'])
    Lk.new(ci.outputs['Instances'], iop.inputs['Instance'])
    Lk.new(ridx.outputs[2], iop.inputs['Instance Index'])
    Lk.new(rrot.outputs[0], iop.inputs['Rotation'])
    Lk.new(rsc.outputs[1], iop.inputs['Scale'])
    Lk.new(iop.outputs['Instances'], go.inputs['Geometry'])
    mod = ob.modifiers.new('trees', 'NODES'); mod.node_group = ng
    return ob


def forest_points(ter, area, spacing, wall_xy=None, wall_clear=12.0, max_slope_deg=42.0, seed=5, density=.6):
    """在 area=(x0,x1,y0,y1) 内按抖动网格撒点，坡太陡、离城墙太近的地方不长树。"""
    rng = np.random.default_rng(seed)
    x0, x1, y0, y1 = area
    xs = np.arange(x0, x1, spacing); ys = np.arange(y0, y1, spacing)
    X, Y = np.meshgrid(xs, ys)
    X = X + rng.uniform(-.45, .45, X.shape) * spacing; Y = Y + rng.uniform(-.45, .45, Y.shape) * spacing
    X = X.ravel(); Y = Y.ravel()
    keep = rng.uniform(0, 1, X.shape) < density
    X, Y = X[keep], Y[keep]
    Z = np.array([ter.height(x, y) for x, y in zip(X, Y)])
    e = 3.0
    Zx = np.array([ter.height(x + e, y) for x, y in zip(X, Y)]); Zy = np.array([ter.height(x, y + e) for x, y in zip(X, Y)])
    slope = np.degrees(np.arctan(np.hypot((Zx - Z) / e, (Zy - Z) / e)))
    ok = slope < max_slope_deg
    if wall_xy is not None:
        from scipy.spatial import cKDTree
        d, _ = cKDTree(wall_xy).query(np.stack([X, Y], 1))
        ok &= d > wall_clear
    return np.stack([X[ok], Y[ok], Z[ok] - .3], 1)
