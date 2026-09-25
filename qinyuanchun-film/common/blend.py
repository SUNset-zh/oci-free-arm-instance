"""Blender 场景构建工具：网格、材质、天空、镜头、合成、穿模检查。"""
import math

import bpy
import mathutils
import numpy as np

V = mathutils.Vector


# ================================================================ 场景
def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.unit_settings.system = 'METRIC'
    return sc


def render_setup(sc, frames, res=(720, 1280), samples=16, fps=24, motion_blur=True, shutter=.5, exposure=0.0,
                 look='AgX - Medium High Contrast'):
    sc.render.engine = 'CYCLES'
    c = sc.cycles
    c.device = 'CPU'
    c.samples = samples
    c.use_adaptive_sampling = True
    c.adaptive_threshold = .02
    c.use_denoising = True
    c.denoiser = 'OPENIMAGEDENOISE'
    c.denoising_input_passes = 'RGB_ALBEDO_NORMAL'
    c.denoising_prefilter = 'ACCURATE'
    c.max_bounces = 4; c.diffuse_bounces = 2; c.glossy_bounces = 2; c.transmission_bounces = 4
    c.volume_bounces = 0; c.transparent_max_bounces = 8
    c.caustics_reflective = False; c.caustics_refractive = False
    c.sample_clamp_indirect = 6.0
    c.use_light_tree = True
    c.seed = 7
    sc.render.use_persistent_data = True
    sc.render.resolution_x, sc.render.resolution_y = res
    sc.render.resolution_percentage = 100
    sc.render.fps = fps
    sc.frame_start, sc.frame_end = frames
    sc.render.use_motion_blur = motion_blur
    sc.render.motion_blur_shutter = shutter
    sc.render.film_transparent = True
    sc.view_settings.view_transform = 'AgX'
    try:
        sc.view_settings.look = look
    except TypeError:
        pass
    sc.view_settings.exposure = exposure
    sc.render.image_settings.file_format = 'PNG'
    sc.render.image_settings.color_depth = '16'
    sc.render.image_settings.compression = 15
    vl = sc.view_layers[0]
    vl.use_pass_mist = True
    vl.use_pass_environment = True
    vl.use_pass_z = True


# ================================================================ 网格
def mesh_from_height(name, H, extent, cx=0.0, cy=0.0, attrs=None, zoff=0.0):
    """H[j,i]：j→y，i→x。extent 为数或 (ex, ey)。返回对象。attrs: {名称: 与 H 同形状的数组} 存为点属性。"""
    ny, nx = H.shape
    ex, ey = (extent, extent) if np.isscalar(extent) else extent
    xs = np.linspace(cx - ex / 2, cx + ex / 2, nx, dtype=np.float32)
    ys = np.linspace(cy - ey / 2, cy + ey / 2, ny, dtype=np.float32)
    X, Y = np.meshgrid(xs, ys)
    co = np.stack([X.ravel(), Y.ravel(), H.ravel().astype(np.float32) + zoff], 1)
    I, J = np.meshgrid(np.arange(nx - 1), np.arange(ny - 1))
    a = (J * nx + I).ravel()
    faces = np.stack([a, a + 1, a + nx + 1, a + nx], 1).astype(np.int32)
    me = bpy.data.meshes.new(name)
    me.vertices.add(len(co)); me.vertices.foreach_set('co', co.ravel())
    me.loops.add(faces.size); me.loops.foreach_set('vertex_index', faces.ravel())
    me.polygons.add(len(faces)); me.polygons.foreach_set('loop_start', (np.arange(len(faces)) * 4).astype(np.int32))
    me.update(calc_edges=True)
    me.polygons.foreach_set('use_smooth', np.ones(len(faces), bool))
    for k, A in (attrs or {}).items():
        at = me.attributes.new(k, 'FLOAT', 'POINT')
        at.data.foreach_set('value', A.ravel().astype(np.float32))
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def sample_height(H, extent, x, y, cx=0.0, cy=0.0):
    ny, nx = H.shape
    ex, ey = (extent, extent) if np.isscalar(extent) else extent
    fx = (x - (cx - ex / 2)) / ex * (nx - 1)
    fy = (y - (cy - ey / 2)) / ey * (ny - 1)
    i = int(np.clip(np.floor(fx), 0, nx - 2)); j = int(np.clip(np.floor(fy), 0, ny - 2))
    u, v = min(max(fx - i, 0), 1), min(max(fy - j, 0), 1)
    return float(H[j, i] * (1 - u) * (1 - v) + H[j, i + 1] * u * (1 - v) + H[j + 1, i] * (1 - u) * v + H[j + 1, i + 1] * u * v)


class Terrain:
    """tgen_dem 输出的多级地形：按坐标取高度（优先用最精细的一级）。"""

    def __init__(self, d):
        self.levels = []
        for li in range(int(d['NL'])):
            ex = float(d[f'EX{li}']) if f'EX{li}' in d else float(d[f'E{li}'])
            ey = float(d[f'EY{li}']) if f'EY{li}' in d else ex
            self.levels.append((d[f'H{li}'], (ex, ey), float(d[f'CX{li}']), float(d[f'CY{li}'])))

    def height(self, x, y):
        for H, (ex, ey), cx, cy in self.levels:
            if abs(x - cx) <= ex / 2 and abs(y - cy) <= ey / 2:
                return sample_height(H, (ex, ey), x, y, cx, cy)
        H, e, cx, cy = self.levels[-1]
        return sample_height(H, e, x, y, cx, cy)


# ================================================================ 节点工具
class NB:
    """简化的节点搭建器。"""

    def __init__(self, tree):
        self.t = tree; self.n = tree.nodes; self.l = tree.links

    def node(self, kind, **props):
        nd = self.n.new(kind)
        for k, v in props.items():
            if k.startswith('in_'):
                key = k[3:]
                if isinstance(key, str) and key.isdigit(): key = int(key)
                nd.inputs[key].default_value = v
            else:
                setattr(nd, k, v)
        return nd

    def link(self, a, b):
        self.l.new(a, b); return b

    def math(self, op, a, b=None, clamp=False):
        nd = self.n.new('ShaderNodeMath'); nd.operation = op; nd.use_clamp = clamp
        self._in(nd.inputs[0], a)
        if b is not None: self._in(nd.inputs[1], b)
        return nd.outputs[0]

    def vmath(self, op, a, b=None, scale=None):
        nd = self.n.new('ShaderNodeVectorMath'); nd.operation = op
        self._in(nd.inputs[0], a)
        if b is not None: self._in(nd.inputs[1], b)
        if scale is not None: self._in(nd.inputs['Scale'], scale)
        return nd.outputs[1] if op in ('DOT_PRODUCT', 'LENGTH', 'DISTANCE') else nd.outputs[0]

    def mix(self, fac, a, b, kind='RGBA', blend='MIX'):
        nd = self.n.new('ShaderNodeMix'); nd.data_type = kind
        if kind == 'RGBA': nd.blend_type = blend
        idx = {'FLOAT': (2, 3, 0), 'VECTOR': (4, 5, 1), 'RGBA': (6, 7, 2)}[kind]
        self._in(nd.inputs[0], fac); self._in(nd.inputs[idx[0]], a); self._in(nd.inputs[idx[1]], b)
        return nd.outputs[idx[2]]

    def maprange(self, v, a, b, c=0.0, d=1.0, interp='SMOOTHSTEP'):
        nd = self.n.new('ShaderNodeMapRange'); nd.interpolation_type = interp; nd.clamp = True
        self._in(nd.inputs['Value'], v)
        nd.inputs['From Min'].default_value = a; nd.inputs['From Max'].default_value = b
        nd.inputs['To Min'].default_value = c; nd.inputs['To Max'].default_value = d
        return nd.outputs[0]

    def _in(self, sock, v):
        if hasattr(v, 'is_output'):
            self.l.new(v, sock)
        else:
            if isinstance(v, (tuple, list)) and len(v) == 3 and sock.type == 'RGBA':
                v = (*v, 1.0)
            sock.default_value = v

    def ramp(self, fac, stops):
        nd = self.n.new('ShaderNodeValToRGB')
        cr = nd.color_ramp
        while len(cr.elements) > len(stops): cr.elements.remove(cr.elements[-1])
        while len(cr.elements) < len(stops): cr.elements.new(0.5)
        for e, (p, c) in zip(cr.elements, stops):
            e.position = p; e.color = (*c, 1) if len(c) == 3 else c
        self._in(nd.inputs[0], fac)
        return nd.outputs[0]

    def noise(self, vec, scale, detail=6, rough=.55, dim='3D', ntype='FBM', w=None, distortion=0.0, lac=2.0):
        nd = self.n.new('ShaderNodeTexNoise'); nd.noise_dimensions = dim; nd.noise_type = ntype
        if vec is not None: self._in(nd.inputs['Vector'], vec)
        nd.inputs['Scale'].default_value = scale; nd.inputs['Detail'].default_value = detail
        nd.inputs['Roughness'].default_value = rough; nd.inputs['Lacunarity'].default_value = lac
        nd.inputs['Distortion'].default_value = distortion
        if w is not None: self._in(nd.inputs['W'], w)
        return nd.outputs[0]

    def voronoi(self, vec, scale, feature='F1', rand=1.0, dim='3D', w=None, out='Distance'):
        nd = self.n.new('ShaderNodeTexVoronoi'); nd.voronoi_dimensions = dim; nd.feature = feature
        if vec is not None: self._in(nd.inputs['Vector'], vec)
        nd.inputs['Scale'].default_value = scale; nd.inputs['Randomness'].default_value = rand
        if w is not None: self._in(nd.inputs['W'], w)
        return nd.outputs[out]

    def bump(self, height, strength, dist=1.0, normal=None):
        nd = self.n.new('ShaderNodeBump')
        self._in(nd.inputs['Height'], height); nd.inputs['Strength'].default_value = strength
        nd.inputs['Distance'].default_value = dist
        if normal is not None: self._in(nd.inputs['Normal'], normal)
        return nd.outputs[0]


def new_material(name):
    m = bpy.data.materials.new(name); m.use_nodes = True
    nt = m.node_tree
    for nd in list(nt.nodes): nt.nodes.remove(nd)
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    return m, NB(nt), out


def principled(nb, **kw):
    b = nb.n.new('ShaderNodeBsdfPrincipled')
    for k, v in kw.items():
        nb._in(b.inputs[k.replace('_', ' ')], v)
    return b


# ================================================================ 地形材质：雪 + 岩
def mat_terrain(name='terrain', snow_attr='snow', snow_bias=0.0, rock_tint=(1, 1, 1), wind_dir=0.4, sastrugi=1.0,
                warm=0.0):
    m, nb, out = new_material(name)
    tc = nb.node('ShaderNodeTexCoord').outputs['Object']
    geo = nb.node('ShaderNodeNewGeometry')
    at = nb.node('ShaderNodeAttribute', attribute_name=snow_attr, attribute_type='GEOMETRY').outputs['Fac']
    # 积雪量：属性 + 噪声打散 + 偏置
    brk = nb.noise(tc, .06, 6, .6)
    brk2 = nb.noise(tc, .5, 5, .55)
    s = nb.math('ADD', at, nb.math('MULTIPLY', nb.math('SUBTRACT', brk, .5), .25))
    s = nb.math('ADD', s, nb.math('MULTIPLY', nb.math('SUBTRACT', brk2, .5), .22))
    # 竖向拉长的噪声：在陡坡上形成顺坡而下的岩肋/雪沟条纹
    st = nb.node('ShaderNodeMapping', vector_type='POINT'); nb.link(tc, st.inputs['Vector']); st.inputs['Scale'].default_value = (1, 1, .12)
    streak = nb.noise(st.outputs[0], .09, 5, .55)
    steep = nb.maprange(nb.vmath('DOT_PRODUCT', geo.outputs['Normal'], (0, 0, 1)), .5, .85, 1, 0)
    s = nb.math('ADD', s, nb.math('MULTIPLY', nb.math('MULTIPLY', nb.math('SUBTRACT', streak, .5), .9), steep))
    s = nb.math('ADD', s, snow_bias)
    snow = nb.maprange(s, .3, .46)
    # 陡岩上的积雪粉：岩缝与小台阶上挂着雪，远看是灰白的“椒盐”质感而不是一片黑
    nzz = nb.vmath('DOT_PRODUCT', geo.outputs['Normal'], (0, 0, 1))
    dust = nb.math('ADD', nb.math('MULTIPLY', nb.noise(tc, 1.2, 6, .6), 1.5), nb.math('MULTIPLY', nzz, 1.1))
    dust = nb.maprange(dust, 1.35, 1.7)
    snow = nb.math('MAXIMUM', snow, nb.math('MULTIPLY', dust, .5))
    # ---- 岩石
    rn = nb.noise(tc, .08, 8, .6)
    rcol = nb.ramp(rn, [(0.0, (.03, .032, .036)), (.45, (.07, .072, .078)), (.75, (.12, .118, .12)), (1.0, (.18, .172, .165))])
    wave = nb.node('ShaderNodeTexWave', wave_type='BANDS', bands_direction='Z')
    nb.link(tc, wave.inputs['Vector']); wave.inputs['Scale'].default_value = .035
    wave.inputs['Distortion'].default_value = 7; wave.inputs['Detail'].default_value = 4; wave.inputs['Detail Scale'].default_value = 1.5
    strata = nb.maprange(wave.outputs['Fac'], .2, .9, .88, 1.06, 'LINEAR')
    rcol = nb.mix(1.0, rcol, strata, 'RGBA', 'MULTIPLY')
    rcol = nb.mix(1.0, rcol, (*rock_tint, 1), 'RGBA', 'MULTIPLY')
    cav = nb.maprange(geo.outputs['Pointiness'], .45, .56, .55, 1.0, 'LINEAR')   # 凹处更暗
    rcol = nb.mix(1.0, rcol, cav, 'RGBA', 'MULTIPLY')
    vs = nb.node('ShaderNodeMapping', vector_type='POINT'); nb.link(tc, vs.inputs['Vector']); vs.inputs['Scale'].default_value = (1, 1, .08)
    stain = nb.maprange(nb.noise(vs.outputs[0], .35, 4, .5), .35, .7, .7, 1.05, 'LINEAR')     # 顺坡的水渍条纹
    rcol = nb.mix(1.0, rcol, stain, 'RGBA', 'MULTIPLY')
    crack = nb.voronoi(tc, .9, 'DISTANCE_TO_EDGE')
    rh = nb.math('ADD', nb.math('MULTIPLY', nb.maprange(crack, 0, .08, 0, 1, 'LINEAR'), .6), nb.math('MULTIPLY', nb.noise(tc, 1.6, 10, .62), .9))
    rh = nb.math('ADD', rh, nb.math('MULTIPLY', wave.outputs['Fac'], .2))
    rnorm = nb.bump(rh, .55, 1.0)
    # ---- 雪
    scol = nb.mix(nb.noise(tc, .02, 3, .5), (.86, .9, .96, 1), (.93, .95, .98, 1))
    if warm: scol = nb.mix(warm, scol, (.97, .94, .9, 1))
    # 风蚀雪纹（sastrugi）：沿风向拉长的波纹
    rot = nb.node('ShaderNodeMapping', vector_type='POINT')
    nb.link(tc, rot.inputs['Vector']); rot.inputs['Rotation'].default_value = (0, 0, wind_dir); rot.inputs['Scale'].default_value = (1, 3.5, 1)
    sw = nb.node('ShaderNodeTexWave', wave_type='BANDS', bands_direction='X')
    nb.link(rot.outputs[0], sw.inputs['Vector']); sw.inputs['Scale'].default_value = .9
    sw.inputs['Distortion'].default_value = 9; sw.inputs['Detail'].default_value = 3
    sh = nb.math('ADD', nb.math('MULTIPLY', sw.outputs['Fac'], .35 * sastrugi), nb.math('MULTIPLY', nb.noise(tc, 6, 6, .55), .25))
    sh = nb.math('ADD', sh, nb.math('MULTIPLY', nb.noise(tc, .25, 5, .5), .6))
    snorm = nb.bump(sh, .12, .5)
    # ---- 合成
    bsdf = principled(nb, Roughness=nb.mix(snow, .88, .5, 'FLOAT'))
    nb.link(nb.mix(snow, rcol, scol), bsdf.inputs['Base Color'])
    nb.link(nb.mix(snow, rnorm, snorm, 'VECTOR'), bsdf.inputs['Normal'])
    nb.link(nb.math('MULTIPLY', snow, .35), bsdf.inputs['Subsurface Weight'])
    bsdf.inputs['Subsurface Radius'].default_value = (.9, 1.1, 1.5)
    bsdf.inputs['Subsurface Scale'].default_value = .04
    nb.link(nb.math('MULTIPLY', snow, .25), bsdf.inputs['Sheen Weight'])
    bsdf.inputs['Specular IOR Level'].default_value = .5
    nb.link(bsdf.outputs[0], out.inputs['Surface'])
    return m


# ================================================================ 天空
def world_sky(name='sky', overcast=1.0, sun_elev=5.0, sun_rot=90.0, strength=1.0, oc_top=(.36, .42, .52),
              oc_hor=(.62, .67, .74), cloud_cover=0.0, cloud_scale=2.0, cloud_col=(1, 1, 1), altitude=1500, dust=1.0, air=1.0):
    """Nishita 物理天空，叠加阴天渐变与云层（按视线方向投影的噪声）。返回 (world, 控制节点字典)。"""
    w = bpy.data.worlds.new(name); bpy.context.scene.world = w; w.use_nodes = True
    nt = w.node_tree
    for nd in list(nt.nodes): nt.nodes.remove(nd)
    nb = NB(nt)
    out = nb.node('ShaderNodeOutputWorld')
    bg = nb.node('ShaderNodeBackground')
    sky = nb.node('ShaderNodeTexSky', sky_type='NISHITA', sun_disc=True, sun_size=math.radians(.6), sun_intensity=1.0,
                  sun_elevation=math.radians(sun_elev), sun_rotation=math.radians(sun_rot), altitude=altitude,
                  air_density=air, dust_density=dust, ozone_density=1.0)
    d = nb.node('ShaderNodeTexCoord').outputs['Generated']
    sep = nb.node('ShaderNodeSeparateXYZ'); nb.link(d, sep.inputs[0])
    z = nb.math('MAXIMUM', sep.outputs['Z'], 0.0)
    ocg = nb.mix(nb.math('POWER', z, .45), oc_hor, oc_top)
    # 云层：方向投影到平面（x/z, y/z）
    zz = nb.math('ADD', sep.outputs['Z'], .08)
    px = nb.math('DIVIDE', sep.outputs['X'], zz); py = nb.math('DIVIDE', sep.outputs['Y'], zz)
    comb = nb.node('ShaderNodeCombineXYZ'); nb.link(px, comb.inputs[0]); nb.link(py, comb.inputs[1])
    cw = nb.node('ShaderNodeValue'); cw.outputs[0].default_value = 0.0; cw.label = 'cloud_time'
    cn = nb.noise(comb.outputs[0], cloud_scale, 8, .62, '4D', w=cw.outputs[0])
    cov = nb.node('ShaderNodeValue'); cov.outputs[0].default_value = cloud_cover; cov.label = 'cloud_cover'
    lo = nb.math('SUBTRACT', 1.0, cov.outputs[0])
    cm = nb.maprange(nb.math('SUBTRACT', cn, nb.math('MULTIPLY', lo, .55)), .2, .45)
    cm = nb.math('MULTIPLY', cm, nb.maprange(sep.outputs['Z'], .0, .12))
    ccol = nb.node('ShaderNodeRGB'); ccol.outputs[0].default_value = (*cloud_col, 1); ccol.label = 'cloud_col'
    ocf = nb.node('ShaderNodeValue'); ocf.outputs[0].default_value = overcast; ocf.label = 'overcast'
    skys = nb.node('ShaderNodeValue'); skys.outputs[0].default_value = strength; skys.label = 'strength'
    base = nb.mix(ocf.outputs[0], nb.mix(1.0, sky.outputs[0], (.08, .08, .08, 1), 'RGBA', 'MULTIPLY'), ocg)
    # Nishita 输出物理亮度，这里统一缩放 0.08 以配合 AgX 曝光
    col = nb.mix(cm, base, nb.mix(1.0, ccol.outputs[0], nb.mix(ocf.outputs[0], (.9, .9, .9, 1), (.55, .58, .64, 1)), 'RGBA', 'MULTIPLY'))
    nb.link(col, bg.inputs['Color'])
    nb.link(skys.outputs[0], bg.inputs['Strength'])
    nb.link(bg.outputs[0], out.inputs['Surface'])
    w.cycles.sampling_method = 'MANUAL'; w.cycles.sample_map_resolution = 2048
    ctl = dict(sky=sky, overcast=ocf.outputs[0], strength=skys.outputs[0], cloud_cover=cov.outputs[0],
               cloud_time=cw.outputs[0], cloud_col=ccol.outputs[0], oc_top=None)
    return w, ctl


def add_sun(elev, rot, strength=3.0, color=(1, .95, .9), angle=.6):
    ld = bpy.data.lights.new('sun', 'SUN'); ld.energy = strength; ld.color = color; ld.angle = math.radians(angle)
    ob = bpy.data.objects.new('sun', ld); bpy.context.scene.collection.objects.link(ob)
    set_sun_dir(ob, elev, rot)
    return ob


def set_sun_dir(ob, elev, rot):
    # Nishita: sun_rotation 从 +Y 顺时针（俯视）→ 与此一致：方向 = (sin r cos e, cos r cos e, sin e)
    e, r = math.radians(elev), math.radians(rot)
    d = V((math.sin(r) * math.cos(e), math.cos(r) * math.cos(e), math.sin(e)))
    ob.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
    # 注意：灯光 -Z 指向光线方向，所以要指向 -d
    ob.rotation_euler = (-d).to_track_quat('-Z', 'Y').to_euler()


# ================================================================ 镜头
def hermite(keys, t, k):
    """keys: [(t, v0, v1, ...)] 单调三次插值（Catmull-Rom 切线）。"""
    if t <= keys[0][0]: return keys[0][k]
    if t >= keys[-1][0]: return keys[-1][k]
    i = 0
    while t > keys[i + 1][0]: i += 1
    p0 = keys[max(0, i - 1)]; p1 = keys[i]; p2 = keys[i + 1]; p3 = keys[min(len(keys) - 1, i + 2)]
    dt = p2[0] - p1[0]; u = (t - p1[0]) / dt
    m1 = (p2[k] - p0[k]) / (p2[0] - p0[0]) * dt if i > 0 else (p2[k] - p1[k]) * 0.0
    m2 = (p3[k] - p1[k]) / (p3[0] - p1[0]) * dt if i + 2 < len(keys) else (p2[k] - p1[k]) * 0.0
    u2 = u * u; u3 = u2 * u
    return (2 * u3 - 3 * u2 + 1) * p1[k] + (u3 - 2 * u2 + u) * m1 + (-2 * u3 + 3 * u2) * p2[k] + (u3 - u2) * m2


def camera(name='cam', lens=35, sensor=36, clip=(1, 60000)):
    cd = bpy.data.cameras.new(name); cd.lens = lens; cd.sensor_width = sensor; cd.sensor_fit = 'AUTO'
    cd.clip_start, cd.clip_end = clip
    ob = bpy.data.objects.new(name, cd); bpy.context.scene.collection.objects.link(ob)
    bpy.context.scene.camera = ob
    return ob


def animate_camera(cam, keys, f0, f1, fps=24, roll_keys=None, lens_keys=None):
    """keys: [(t, x, y, z, tx, ty, tz)]，t 为秒（相对 f0）。每帧写关键帧。"""
    sc = bpy.context.scene
    for f in range(f0, f1 + 1):
        t = (f - f0) / fps
        p = V([hermite(keys, t, k) for k in (1, 2, 3)])
        q = V([hermite(keys, t, k) for k in (4, 5, 6)])
        rot = (q - p).to_track_quat('-Z', 'Y')
        if roll_keys:
            r = hermite(roll_keys, t, 1)
            rot = rot @ mathutils.Quaternion((0, 0, 1), math.radians(r))
        cam.location = p; cam.rotation_mode = 'QUATERNION'; cam.rotation_quaternion = rot
        cam.keyframe_insert('location', frame=f); cam.keyframe_insert('rotation_quaternion', frame=f)
        if lens_keys:
            cam.data.lens = hermite(lens_keys, t, 1); cam.data.keyframe_insert('lens', frame=f)
    for fc in cam.animation_data.action.fcurves:
        for kp in fc.keyframe_points: kp.interpolation = 'LINEAR'


def check_clearance(cam, f0, f1, min_dist=6.0, step=1, rays=40):
    """逐帧从镜头位置向各方向发射射线，距离小于 min_dist 视为穿模风险。返回问题帧列表。"""
    sc = bpy.context.scene
    dg = bpy.context.evaluated_depsgraph_get()
    dirs = []
    g = (1 + 5 ** .5) / 2
    for k in range(rays):
        zz = 1 - 2 * (k + .5) / rays; r = math.sqrt(1 - zz * zz); a = 2 * math.pi * k / g
        dirs.append(V((r * math.cos(a), r * math.sin(a), zz)))
    bad = []
    hidden = [o for o in sc.objects if o.name.startswith('snowfall') or o.type in ('EMPTY', 'LIGHT', 'CAMERA')]
    for o in hidden: o.hide_viewport = True
    for f in range(f0, f1 + 1, step):
        sc.frame_set(f); dg = bpy.context.evaluated_depsgraph_get()
        p = cam.matrix_world.translation.copy()
        md = 1e9
        for d in dirs:
            hit, loc, *_ = sc.ray_cast(dg, p, d, distance=min_dist * 4)
            if hit: md = min(md, (loc - p).length)
        if md < min_dist: bad.append((f, round(md, 2)))
    for o in hidden: o.hide_viewport = False
    return bad


# ================================================================ 合成：大气透视（雾） + 天空背景 + 辉光
def compositor(sc, fog_color=(.6, .65, .72), fog_max=.85, fog_gamma=1.0, mist_start=200, mist_depth=20000, glare=.08):
    sc.use_nodes = True
    nt = sc.node_tree
    for nd in list(nt.nodes): nt.nodes.remove(nd)
    rl = nt.nodes.new('CompositorNodeRLayers')
    comp = nt.nodes.new('CompositorNodeComposite')
    w = sc.world
    w.mist_settings.start = mist_start; w.mist_settings.depth = mist_depth; w.mist_settings.falloff = 'LINEAR'
    am = nt.nodes.new('CompositorNodeMath'); am.operation = 'MAXIMUM'; am.inputs[1].default_value = 1e-3
    nt.links.new(rl.outputs['Alpha'], am.inputs[0])
    dv = nt.nodes.new('CompositorNodeMath'); dv.operation = 'DIVIDE'; dv.use_clamp = True
    nt.links.new(rl.outputs['Mist'], dv.inputs[0]); nt.links.new(am.outputs[0], dv.inputs[1])
    pw = nt.nodes.new('CompositorNodeMath'); pw.operation = 'POWER'; pw.inputs[1].default_value = fog_gamma
    nt.links.new(dv.outputs[0], pw.inputs[0])
    mul = nt.nodes.new('CompositorNodeMath'); mul.operation = 'MULTIPLY'; mul.inputs[1].default_value = fog_max; mul.label = 'fog_max'
    nt.links.new(pw.outputs[0], mul.inputs[0])
    fogc = nt.nodes.new('CompositorNodeRGB'); fogc.outputs[0].default_value = (*fog_color, 1); fogc.label = 'fog_color'
    # 前景（premultiplied）混入雾色：fg*(1-f) + fog*alpha*f
    setA = nt.nodes.new('CompositorNodeSetAlpha'); setA.mode = 'APPLY'
    nt.links.new(fogc.outputs[0], setA.inputs['Image']); nt.links.new(rl.outputs['Alpha'], setA.inputs['Alpha'])
    mix = nt.nodes.new('CompositorNodeMixRGB'); mix.blend_type = 'MIX'; mix.use_alpha = False
    nt.links.new(mul.outputs[0], mix.inputs[0]); nt.links.new(rl.outputs['Image'], mix.inputs[1]); nt.links.new(setA.outputs[0], mix.inputs[2])
    ao = nt.nodes.new('CompositorNodeAlphaOver'); ao.premul = 1.0
    nt.links.new(rl.outputs['Env'], ao.inputs[1]); nt.links.new(mix.outputs[0], ao.inputs[2])
    last = ao.outputs[0]
    if glare > 0:
        gl = nt.nodes.new('CompositorNodeGlare'); gl.glare_type = 'FOG_GLOW'; gl.quality = 'HIGH'; gl.size = 8
        gl.threshold = 1.2; gl.mix = -1 + glare * 2
        nt.links.new(last, gl.inputs[0]); last = gl.outputs[0]
    nt.links.new(last, comp.inputs['Image'])
    return dict(fog_color=fogc.outputs[0], fog_max=mul.inputs[1])


# ================================================================ 飞雪
def snowfall(center, size, count, lifetime, frames, vel=(0, 0, -1.6), size_m=.012, wind=(0.4, 0.2, 0), seed=1, name='snowfall'):
    """在 center 周围的立方体内发射雪花（小圆片），带运动模糊即成雪线。"""
    sc = bpy.context.scene
    bpy.ops.mesh.primitive_cube_add(size=1, location=center)
    em = bpy.context.active_object; em.name = name; em.scale = size
    em.hide_render = False
    ps = em.modifiers.new('ps', 'PARTICLE_SYSTEM').particle_system
    st = ps.settings
    st.count = count; st.frame_start = frames[0] - lifetime; st.frame_end = frames[1]; st.lifetime = lifetime
    st.emit_from = 'VOLUME'; st.distribution = 'RAND'; st.use_emit_random = True
    st.normal_factor = 0; st.object_align_factor = vel
    st.physics_type = 'NEWTON'; st.effector_weights.gravity = 0.0
    st.brownian_factor = .3; st.drag_factor = 0
    st.render_type = 'OBJECT'
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=1, location=(0, 0, -99999))
    flake = bpy.context.active_object; flake.name = name + '_flake'
    mm, nb, out = new_material('flake')
    b = principled(nb, Base_Color=(.95, .97, 1, 1), Roughness=.6)
    b.inputs['Subsurface Weight'].default_value = .5; b.inputs['Subsurface Scale'].default_value = .002
    nb.link(b.outputs[0], out.inputs['Surface'])
    flake.data.materials.append(mm)
    st.instance_object = flake; st.particle_size = size_m; st.size_random = .6
    ps.seed = seed
    em.show_instancer_for_render = False
    # 风：一个 wind 力场
    if any(wind):
        bpy.ops.object.effector_add(type='WIND', location=center)
        wd = bpy.context.active_object; wd.field.strength = V(wind).length * 10
        wd.rotation_euler = V(wind).to_track_quat('Z', 'Y').to_euler()
        st.effector_weights.wind = 1.0
    return em


def bake_particles(cache_dir):
    """把所有粒子系统烘焙到磁盘缓存（渲染单帧时才能拿到正确的粒子状态）。"""
    import os
    os.makedirs(cache_dir, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(cache_dir, '_bake.blend'))  # 磁盘缓存需要 .blend 路径
    for ob in bpy.context.scene.objects:
        for ps in getattr(ob, 'particle_systems', []):
            ps.point_cache.use_disk_cache = True
            ps.point_cache.use_library_path = False
    ov = {'scene': bpy.context.scene}
    with bpy.context.temp_override(**ov):
        bpy.ops.ptcache.bake_all(bake=True)


# ================================================================ 输出：多层 EXR（线性光）+ 每帧镜头参数
def exr_output(sc, out_dir):
    """合成器只负责把各个通道写成多层 EXR；雾、调色都在 post/composite.py 里做。"""
    import os
    sc.use_nodes = True
    nt = sc.node_tree
    for nd in list(nt.nodes): nt.nodes.remove(nd)
    rl = nt.nodes.new('CompositorNodeRLayers')
    comp = nt.nodes.new('CompositorNodeComposite')
    nt.links.new(rl.outputs['Image'], comp.inputs['Image'])
    fo = nt.nodes.new('CompositorNodeOutputFile')
    fo.base_path = os.path.join(out_dir, 'f')
    fo.format.file_format = 'OPEN_EXR_MULTILAYER'
    fo.format.color_depth = '16'
    fo.format.exr_codec = 'DWAA'
    fo.file_slots.clear()
    for name in ('Image', 'Depth', 'Env', 'Mist'):
        fo.file_slots.new(name)
        nt.links.new(rl.outputs[name], fo.inputs[name])
    sc.render.film_transparent = True


def export_camera(cam, f0, f1, path):
    """每帧的镜头矩阵、焦距；若场景里有名为 sun 的太阳灯，也记下它的方向（指向太阳）、颜色、强度（后期云层要用）。"""
    import json
    sc = bpy.context.scene
    sun = bpy.data.objects.get('sun')
    data = {}
    for f in range(f0, f1 + 1):
        sc.frame_set(f)
        m = cam.matrix_world
        e = dict(loc=list(m.translation), rot=[list(r) for r in m.to_3x3()], lens=cam.data.lens, sensor=cam.data.sensor_width)
        if sun is not None:
            z = sun.matrix_world.to_3x3() @ V((0, 0, 1))
            e['sun'] = dict(dir=list(z.normalized()), color=list(sun.data.color), energy=sun.data.energy)
        data[f] = e
    json.dump(dict(res=[sc.render.resolution_x, sc.render.resolution_y], frames=data), open(path, 'w'))


# ================================================================ 真实地形（多级网格）+ 高效材质 + 物理天空
def load_levels(d, mat, name='terrain'):
    """tgen_dem.py 输出的各级网格 -> Blender 对象（点属性 snow / cav）。"""
    obs = []
    for li in range(int(d['NL'])):
        ex = float(d[f'EX{li}']) if f'EX{li}' in d else float(d[f'E{li}'])
        ey = float(d[f'EY{li}']) if f'EY{li}' in d else ex
        ob = mesh_from_height(f'{name}{li}', d[f'H{li}'], (ex, ey), float(d[f'CX{li}']), float(d[f'CY{li}']),
                              attrs={'snow': d[f'S{li}'], 'cav': d[f'A{li}'],
                                     **({'rockv': d[f'R{li}']} if f'R{li}' in d else {})})
        ob.data.materials.append(mat)
        obs.append(ob)
    return obs


def mat_real(name='terrain', rock=(.07, .066, .062), rock2=(.14, .128, .115), snow_col=(.88, .91, .96), ledge=.5,
             cav_dark=.5, rock_bump=.45, cover=0.0, strata=1.0, flute=.09, slope_lo=.5, slope_hi=.68, snow_bump=.08,
             wind=.6, dust=.7):
    """真实地形材质。积雪 = max(模拟积雪, 坡度 + 凹槽)：陡壁上沟槽积雪、岩肋裸露（冲沟纹理）；
    岩层台阶上挂着横向雪带。雪面光滑（细节来自几何），岩面有凹凸。只用少量低阶噪声，渲染便宜。"""
    m, nb, out = new_material(name)
    tc = nb.node('ShaderNodeTexCoord').outputs['Object']
    geo = nb.node('ShaderNodeNewGeometry')
    S = nb.node('ShaderNodeAttribute', attribute_name='snow', attribute_type='GEOMETRY').outputs['Fac']
    A = nb.node('ShaderNodeAttribute', attribute_name='cav', attribute_type='GEOMETRY').outputs['Fac']
    nz = nb.vmath('DOT_PRODUCT', geo.outputs['Normal'], (0, 0, 1))
    b1 = nb.noise(tc, 1 / 70, 3, .5)
    b2 = nb.noise(tc, 1 / 14, 3, .5)
    # 坡度 + 凹槽：沟里有雪、脊上露岩
    sl = nb.math('ADD', nz, nb.math('MULTIPLY', nb.math('MINIMUM', nb.math('MAXIMUM', A, -4), 6), flute))
    sl = nb.math('ADD', sl, nb.math('MULTIPLY', nb.math('SUBTRACT', b1, .5), .22))
    cov = nb.maprange(sl, slope_lo, slope_hi)
    s = nb.math('MAXIMUM', S, cov)
    s = nb.math('ADD', s, nb.math('MULTIPLY', nb.math('SUBTRACT', b2, .5), .3))
    s = nb.math('ADD', s, cover)
    b3 = nb.noise(tc, 1 / 2.2, 3, .6)                                    # 雪线边缘的碎齿
    s = nb.math('ADD', s, nb.math('MULTIPLY', nb.math('SUBTRACT', b3, .5), .35))
    snow = nb.maprange(s, .4, .6)
    # 陡壁上顺着岩层的雪带：水平方向拉长的噪声
    mp = nb.node('ShaderNodeMapping', vector_type='POINT'); nb.link(tc, mp.inputs['Vector'])
    mp.inputs['Scale'].default_value = (.12, .12, 1.0)
    led = nb.math('ADD', nb.noise(mp.outputs[0], 1 / 7, 3, .6), nb.math('MULTIPLY', nz, .45))
    led = nb.maprange(led, .78, .9)
    snow = nb.math('MAXIMUM', snow, nb.math('MULTIPLY', led, ledge))
    # 岩缝里的雪：细碎的白点/白线，陡到接近垂直的地方挂不住
    crk = nb.voronoi(tc, 1 / 2.5, 'DISTANCE_TO_EDGE')
    spk = nb.math('ADD', nb.maprange(crk, .0, .06, 1, 0), nb.math('MULTIPLY', nb.maprange(b3, .6, .75), .8))
    spk = nb.math('MULTIPLY', spk, nb.maprange(nz, .15, .45))
    snow = nb.math('MAXIMUM', snow, nb.math('MULTIPLY', nb.math('MINIMUM', spk, 1.0), dust))
    # ---- 岩石
    g = nb.noise(tc, 1 / 500, 3, .5)
    g2 = nb.noise(tc, 1 / 25, 3, .6)
    rcol = nb.mix(nb.maprange(nb.math('ADD', g, nb.math('MULTIPLY', nb.math('SUBTRACT', g2, .5), .8)), .3, .7), rock, rock2)
    wave = nb.node('ShaderNodeTexWave', wave_type='BANDS', bands_direction='Z')
    nb.link(tc, wave.inputs['Vector']); wave.inputs['Scale'].default_value = 1 / 60
    wave.inputs['Distortion'].default_value = 6; wave.inputs['Detail'].default_value = 2; wave.inputs['Detail Scale'].default_value = 1.2
    rcol = nb.mix(1.0, rcol, nb.maprange(wave.outputs['Fac'], .2, .9, 1 - .15 * strata, 1 + .12 * strata, 'LINEAR'), 'RGBA', 'MULTIPLY')
    cav = nb.maprange(A, -6, 8, 1.25, 1 - cav_dark, 'LINEAR')          # 凸脊略亮、沟槽暗
    rcol = nb.mix(1.0, rcol, cav, 'RGBA', 'MULTIPLY')
    rh = nb.noise(tc, 1 / 3.5, 4, .6)
    rnorm = nb.bump(nb.math('ADD', rh, nb.math('MULTIPLY', wave.outputs['Fac'], .5)), rock_bump, 1.0)
    # ---- 雪：颜色随凹度略偏蓝；表面有风蚀雪纹（沿风向拉长）与大尺度起伏，低角度光下才看得出
    scol = nb.mix(nb.maprange(A, 0, 10), snow_col, (snow_col[0] * .9, snow_col[1] * .95, snow_col[2] * 1.02))
    wr = nb.node('ShaderNodeMapping', vector_type='POINT'); nb.link(tc, wr.inputs['Vector'])
    wr.inputs['Rotation'].default_value = (0, 0, wind); wr.inputs['Scale'].default_value = (1.0, 4.0, 1.0)
    rip = nb.noise(wr.outputs[0], 1 / 3.0, 3, .55)
    und = nb.noise(tc, 1 / 18.0, 2, .5)
    snorm = nb.bump(nb.math('ADD', nb.math('MULTIPLY', rip, .35), und), snow_bump, 1.0)
    bsdf = principled(nb, Roughness=nb.mix(snow, .9, .6, 'FLOAT'))
    nb.link(nb.mix(snow, rcol, scol), bsdf.inputs['Base Color'])
    nb.link(nb.mix(snow, rnorm, snorm, 'VECTOR'), bsdf.inputs['Normal'])
    nb.link(nb.math('MULTIPLY', snow, .3), bsdf.inputs['Sheen Weight'])
    bsdf.inputs['Specular IOR Level'].default_value = .45
    nb.link(bsdf.outputs[0], out.inputs['Surface'])
    return m


def mat_lean(name='terrain', rock=(.07, .066, .062), rock2=(.15, .135, .12), snow_col=(.88, .91, .96), ledge=.5,
             cav_dark=.5, rock_bump=.45, snow_bump=.06, strata=1.0, wind=.6, edge=.3):
    """精简版地形材质：大尺度图案已预计算在顶点属性（snow / rockv / cav）上，
    着色器只补网格间距以下的细节：雪线碎齿、陡壁雪带、岩层明暗、一个共用的凹凸。约为 mat_real 的 1/3 开销。"""
    m, nb, out = new_material(name)
    tc = nb.node('ShaderNodeTexCoord').outputs['Object']
    geo = nb.node('ShaderNodeNewGeometry')
    at = lambda k: nb.node('ShaderNodeAttribute', attribute_name=k, attribute_type='GEOMETRY').outputs['Fac']
    S, A, RV = at('snow'), at('cav'), at('rockv')
    nz = nb.vmath('DOT_PRODUCT', geo.outputs['Normal'], (0, 0, 1))
    fine = nb.noise(tc, 1 / 3.0, 2, .6)                                   # 一个细噪声复用：雪线碎齿 + 凹凸
    mid = nb.noise(tc, 1 / 9.0, 2, .5)                                    # 打散顶点插值留下的菱形块状边缘
    s = nb.math('ADD', S, nb.math('MULTIPLY', nb.math('SUBTRACT', fine, .5), edge))
    s = nb.math('ADD', s, nb.math('MULTIPLY', nb.math('SUBTRACT', mid, .5), .45))
    snow = nb.maprange(s, .3, .7)
    mp = nb.node('ShaderNodeMapping', vector_type='POINT'); nb.link(tc, mp.inputs['Vector'])
    mp.inputs['Scale'].default_value = (.12, .12, 1.0)
    led = nb.maprange(nb.math('ADD', nb.noise(mp.outputs[0], 1 / 7, 2, .6), nb.math('MULTIPLY', nz, .45)), .78, .9)
    snow = nb.math('MAXIMUM', snow, nb.math('MULTIPLY', led, ledge))
    # 岩石：顶点上的色相变化 + 按海拔的岩层（sin 代替波纹纹理）+ 凹凸明暗
    rcol = nb.mix(RV, rock, rock2)
    zs = nb.node('ShaderNodeSeparateXYZ'); nb.link(tc, zs.inputs[0])
    band = nb.math('SINE', nb.math('ADD', nb.math('MULTIPLY', zs.outputs['Z'], 2 * math.pi / 23.0), nb.math('MULTIPLY', RV, 9.0)))
    rcol = nb.mix(1.0, rcol, nb.maprange(band, -1, 1, 1 - .12 * strata, 1 + .1 * strata, 'LINEAR'), 'RGBA', 'MULTIPLY')
    rcol = nb.mix(1.0, rcol, nb.maprange(A, -6, 8, 1.25, 1 - cav_dark, 'LINEAR'), 'RGBA', 'MULTIPLY')
    scol = nb.mix(nb.maprange(A, 0, 10), snow_col, (snow_col[0] * .9, snow_col[1] * .95, snow_col[2] * 1.02))
    bs = nb.mix(snow, rock_bump, snow_bump, 'FLOAT')
    bump = nb.node('ShaderNodeBump'); nb.link(fine, bump.inputs['Height']); nb.link(bs, bump.inputs['Strength'])
    bump.inputs['Distance'].default_value = 1.0
    bsdf = principled(nb, Roughness=nb.mix(snow, .9, .6, 'FLOAT'))
    nb.link(nb.mix(snow, rcol, scol), bsdf.inputs['Base Color'])
    nb.link(bump.outputs[0], bsdf.inputs['Normal'])
    nb.link(nb.math('MULTIPLY', snow, .3), bsdf.inputs['Sheen Weight'])
    bsdf.inputs['Specular IOR Level'].default_value = .45
    nb.link(bsdf.outputs[0], out.inputs['Surface'])
    return m


def sun_color(elev_deg, altitude=3000.0, turbidity=1.0):
    """大气透过率近似：瑞利 + 气溶胶，Kasten-Young 大气质量。返回线性 RGB（归一化到最大分量 1）与透过率均值。"""
    e = max(elev_deg, -0.5)
    am = 1.0 / (math.sin(math.radians(e)) + 0.50572 * (e + 6.07995) ** -1.6364)
    lam = np.array([.61, .55, .465])
    tr = .0088 * lam ** -4.05 * math.exp(-altitude / 8400.0)
    ta = .08 * turbidity * (lam / .55) ** -1.3 * math.exp(-altitude / 1500.0)
    T = np.exp(-(tr + ta) * am)
    return tuple((T / T.max()).tolist()), float(T.mean())


def world_nishita(sun_elev, sun_rot, strength=1.0, altitude=3000, air=1.0, dust=1.0, ozone=1.0, name='sky'):
    """纯 Nishita 天空（不带太阳圆盘，太阳用灯光），渲染开销极小。"""
    w = bpy.data.worlds.new(name); bpy.context.scene.world = w; w.use_nodes = True
    nt = w.node_tree
    for nd in list(nt.nodes): nt.nodes.remove(nd)
    nb = NB(nt)
    out = nb.node('ShaderNodeOutputWorld')
    bg = nb.node('ShaderNodeBackground')
    sky = nb.node('ShaderNodeTexSky', sky_type='NISHITA', sun_disc=False, sun_elevation=math.radians(sun_elev),
                  sun_rotation=math.radians(sun_rot), altitude=altitude, air_density=air, dust_density=dust, ozone_density=ozone)
    nb.link(sky.outputs[0], bg.inputs['Color'])
    bg.inputs['Strength'].default_value = strength
    nb.link(bg.outputs[0], out.inputs['Surface'])
    w.cycles.sampling_method = 'MANUAL'; w.cycles.sample_map_resolution = 1024
    return w, sky, bg
