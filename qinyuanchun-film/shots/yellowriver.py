"""黄河：沿河道中线扫出一条河面带状网格（宽于河道，两岸由地形自然遮挡形成岸线），
材质里用“冰冻前锋”在流水与冰面之间过渡——前锋扫过之处，滔滔河水凝成一片片冰凌，再冻成整块冰面。"""
import math

import bpy
import numpy as np

from common import blend as B
from common import dem


def ribbon(line, half_width=260.0, n_across=42, curve_origin=(0.0, 0.0)):
    """line: (N,4) = x, y, 水面高程, 沿程距离。返回河面对象（点属性 rs=沿程米数, rv=横向米数）。"""
    C = line[:, :2]; z = line[:, 2]; s = line[:, 3]
    t = np.gradient(C, axis=0); t /= np.linalg.norm(t, axis=1, keepdims=True)
    nrm = np.stack([-t[:, 1], t[:, 0]], 1)
    vs = np.linspace(-half_width, half_width, n_across)
    X = C[:, None, 0] + nrm[:, None, 0] * vs[None, :]
    Y = C[:, None, 1] + nrm[:, None, 1] * vs[None, :]
    ox, oy = curve_origin
    Z = z[:, None] + .25 - ((X - ox) ** 2 + (Y - oy) ** 2) / (2 * dem.R_EFF)
    N, M = X.shape
    co = np.stack([X.ravel(), Y.ravel(), Z.ravel()], 1).astype(np.float32)
    I, J = np.meshgrid(np.arange(M - 1), np.arange(N - 1))
    a = (J * M + I).ravel()
    faces = np.stack([a, a + 1, a + M + 1, a + M], 1).astype(np.int32)
    me = bpy.data.meshes.new('river')
    me.vertices.add(len(co)); me.vertices.foreach_set('co', co.ravel())
    me.loops.add(faces.size); me.loops.foreach_set('vertex_index', faces.ravel())
    me.polygons.add(len(faces)); me.polygons.foreach_set('loop_start', (np.arange(len(faces)) * 4).astype(np.int32))
    me.update(calc_edges=True)
    for name, A in (('rs', np.repeat(s[:, None], M, 1)), ('rv', np.repeat(vs[None, :], N, 0))):
        at = me.attributes.new(name, 'FLOAT', 'POINT'); at.data.foreach_set('value', A.ravel().astype(np.float32))
    ob = bpy.data.objects.new('river', me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def mat_river(flow=3.0):
    """返回 (材质, front 值节点, time 值节点)。front：冰冻前锋的沿程位置（米），time：秒。"""
    m, nb, out = B.new_material('river')
    at = lambda k: nb.node('ShaderNodeAttribute', attribute_name=k, attribute_type='GEOMETRY').outputs['Fac']
    u, v = at('rs'), at('rv')
    front = nb.node('ShaderNodeValue'); front.label = 'front'; front.outputs[0].default_value = 0.0
    tim = nb.node('ShaderNodeValue'); tim.label = 'time'; tim.outputs[0].default_value = 0.0
    # 静止的冰面坐标 (u, v)；随水流动的坐标 (u - flow*t, v)
    cs = nb.node('ShaderNodeCombineXYZ'); nb.link(u, cs.inputs[0]); nb.link(v, cs.inputs[1])
    um = nb.math('SUBTRACT', u, nb.math('MULTIPLY', tim.outputs[0], flow))
    cm = nb.node('ShaderNodeCombineXYZ'); nb.link(um, cm.inputs[0]); nb.link(v, cm.inputs[1])
    # 冰块（静止）：Voronoi 格子，格子随机数决定它在前锋附近什么时候冻上
    vs_ = nb.node('ShaderNodeTexVoronoi'); vs_.voronoi_dimensions = '2D'; vs_.feature = 'F1'
    nb.link(cs.outputs[0], vs_.inputs['Vector']); vs_.inputs['Scale'].default_value = 1 / 28.0
    ve = nb.node('ShaderNodeTexVoronoi'); ve.voronoi_dimensions = '2D'; ve.feature = 'DISTANCE_TO_EDGE'
    nb.link(cs.outputs[0], ve.inputs['Vector']); ve.inputs['Scale'].default_value = 1 / 28.0
    r = nb.math('ADD', nb.math('MULTIPLY', vs_.outputs['Color'], 1.0), 0.0)
    ahead = nb.math('SUBTRACT', front.outputs[0], u)                      # >0：前锋已经过去
    frozen = nb.maprange(nb.math('SUBTRACT', nb.math('DIVIDE', ahead, 160.0), nb.math('MULTIPLY', r, .9)), 0, .35)
    crack = nb.maprange(ve.outputs['Distance'], .0, .06, 1, 0)             # 冰块之间的缝
    # 漂流的冰凌（未冻的水面上）：随水流动的稀疏格子
    vd = nb.node('ShaderNodeTexVoronoi'); vd.voronoi_dimensions = '2D'; vd.feature = 'F1'
    nb.link(cm.outputs[0], vd.inputs['Vector']); vd.inputs['Scale'].default_value = 1 / 16.0
    vde = nb.node('ShaderNodeTexVoronoi'); vde.voronoi_dimensions = '2D'; vde.feature = 'DISTANCE_TO_EDGE'
    nb.link(cm.outputs[0], vde.inputs['Vector']); vde.inputs['Scale'].default_value = 1 / 16.0
    drift = nb.math('MULTIPLY', nb.math('GREATER_THAN', vd.outputs['Color'], .72), nb.maprange(vde.outputs['Distance'], .08, .16))
    # 前锋前方 300 米内冰凌越来越密（将冻未冻）
    near_front = nb.maprange(ahead, -300, 0)
    drift = nb.math('MAXIMUM', drift, nb.math('MULTIPLY', nb.math('MULTIPLY', nb.math('GREATER_THAN', vd.outputs['Color'], .35),
                                                                      nb.maprange(vde.outputs['Distance'], .05, .12)), near_front))
    ice = nb.math('MAXIMUM', nb.math('MULTIPLY', frozen, nb.math('SUBTRACT', 1.0, nb.math('MULTIPLY', crack, .7))), drift)
    # 水面：暗、有流动的波纹
    rip = nb.noise(cm.outputs[0], 1 / 6.0, 3, .55)
    wave = nb.bump(rip, .25, 1.0)
    icecol = nb.mix(nb.maprange(nb.noise(cs.outputs[0], 1 / 40.0, 2, .5), .3, .7), (.62, .66, .7, 1), (.8, .83, .87, 1))
    icecol = nb.mix(nb.math('MULTIPLY', crack, frozen), icecol, (.25, .3, .34, 1))
    bsdf = B.principled(nb)
    nb.link(nb.mix(ice, (.018, .026, .03, 1), icecol), bsdf.inputs['Base Color'])
    nb.link(nb.mix(ice, .06, .55, 'FLOAT'), bsdf.inputs['Roughness'])
    nb.link(nb.mix(ice, wave, nb.bump(nb.noise(cs.outputs[0], 1 / 2.0, 2, .5), .05, 1.0), 'VECTOR'), bsdf.inputs['Normal'])
    nb.link(bsdf.outputs[0], out.inputs['Surface'])
    return m, front, tim


def animate(front_node, time_node, f0, f1, fps, front_keys):
    """front_keys: [(t 秒, 前锋沿程米数)]。time 节点 = 秒。"""
    for f in range(f0, f1 + 1):
        t = (f - f0) / fps
        front_node.outputs[0].default_value = B.hermite(front_keys, t, 1)
        front_node.outputs[0].keyframe_insert('default_value', frame=f)
        time_node.outputs[0].default_value = t
        time_node.outputs[0].keyframe_insert('default_value', frame=f)
