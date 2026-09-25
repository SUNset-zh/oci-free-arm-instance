"""天山镜头共用：地形网格、材质、物理天空、太阳（可做延时摄影式的日出动画）。"""
import math

import bpy

from common import blend as B


def build(d, mat_kw=None, sun=(3.0, 118.0), alt=4500.0, sky_strength=.07, dust=.15, ozone=1.6, sun_k=1.6, overcast=None):
    mat = B.mat_lean(**dict(dict(ledge=.25), **(mat_kw or {})))
    B.load_levels(d, mat)
    if overcast is not None:
        w, bg = B.world_overcast(**overcast)
        return dict(ter=B.Terrain(d), sky=None, bg=bg, sun=None, alt=alt, sun_k=0, mat=mat)
    w, sky, bg = B.world_nishita(sun[0], sun[1], strength=sky_strength, altitude=alt, dust=dust, ozone=ozone)
    col, T = B.sun_color(sun[0], alt)
    lamp = B.add_sun(sun[0], sun[1], strength=4.5 * T * sun_k, color=col, angle=.55)
    return dict(ter=B.Terrain(d), sky=sky, bg=bg, sun=lamp, alt=alt, sun_k=sun_k, mat=mat)


def sun_light(el, alt):
    """太阳在地平线附近时：光线掠过低层大气，更红更暗；el<0 时只有高处还能被照到（由地形与地球曲率自然遮挡）。"""
    col, T = B.sun_color(max(el, -.5), alt)
    if el < -.5:
        k = math.exp(-.9 * (-.5 - el))
        col = (col[0], col[1] * k ** 1.5, col[2] * k ** 3)
        T *= k
    return col, T


def animate_sun(ctx, keys, f0, f1, fps=24):
    """keys: [(t, 仰角, 方位)]。每帧写太阳灯方向/颜色/强度与 Nishita 天空的太阳位置。"""
    sc = bpy.context.scene
    lamp, sky = ctx['sun'], ctx['sky']
    for f in range(f0, f1 + 1):
        t = (f - f0) / fps
        el, az = B.hermite(keys, t, 1), B.hermite(keys, t, 2)
        col, T = sun_light(el, ctx['alt'])
        lamp.data.energy = 4.5 * T * ctx['sun_k']; lamp.data.color = col
        B.set_sun_dir(lamp, el, az)
        lamp.data.keyframe_insert('energy', frame=f); lamp.data.keyframe_insert('color', frame=f)
        lamp.keyframe_insert('rotation_euler', frame=f)
        sky.sun_elevation = math.radians(el); sky.sun_rotation = math.radians(az)
        sky.keyframe_insert('sun_elevation', frame=f); sky.keyframe_insert('sun_rotation', frame=f)
