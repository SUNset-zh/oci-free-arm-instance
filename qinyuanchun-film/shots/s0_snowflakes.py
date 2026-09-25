"""S0 · 片头：沁园春·雪（0–3.6s）

深蓝的暗处，一片片六角形的雪花（星状枝晶）缓缓飘落、旋转，浅景深，冷色的侧逆光勾出冰晶的棱；
标题在后期叠加。结尾一片雪花飘近镜头、占满画面，转进 S1 的雪夜群山。

雪花形状用 numpy 按晶体生长的样子画成贴图（六重对称的主枝 + 60° 侧枝 + 中心六角板 + 沿主枝的脊），
平面 + 透明度遮罩 + 冰的材质（高光、少量透射、凹凸脊线）。"""
import json
import math
import os
import sys

import bpy
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import blend as B

OUT = sys.argv[sys.argv.index('--out') + 1] if '--out' in sys.argv else '/tmp/s0'
FPS = 24
F0, F1 = 1, 98

POST = dict(exposure=0.0, bloom=.12, bloom_thresh=.6, punch=1.05, sat=1.0, vignette=.35,
            shadow_tint=(.95, .98, 1.06), high_tint=(1.0, 1.0, 1.0))


def crystal(seed, N=512):
    """返回 (alpha, height) 两张 N×N 贴图：六重对称的星状枝晶。"""
    rng = np.random.default_rng(seed)
    y, x = (np.mgrid[0:N, 0:N] - N / 2 + .5) / (N / 2)          # [-1,1]
    r = np.hypot(x, y); th = np.arctan2(y, x)
    # 折叠到一个 30° 扇区：六重对称 + 镜像
    a = np.mod(th, math.pi / 3)
    a = np.minimum(a, math.pi / 3 - a)
    u = r * np.cos(a); v = r * np.sin(a)                         # u：沿主枝，v：离主枝
    arm_w = rng.uniform(.035, .06)
    alpha = ((v < arm_w * (1 - .5 * u)) & (u < .96)).astype(float)
    hgt = np.clip(1 - v / (arm_w + 1e-6), 0, 1) * (u < .96)        # 主枝中脊
    # 侧枝：在主枝上若干位置向外 60°
    nb = rng.integers(4, 7)
    for k in range(nb):
        u0 = rng.uniform(.25, .85) if k else rng.uniform(.3, .45)
        L = (1 - u0) * rng.uniform(.35, .7)
        w = arm_w * rng.uniform(.5, .8)
        # 侧枝方向：与主枝成 60°（在扇区坐标里：从 (u0, 0) 出发，方向 (cos60, sin60)）
        du = u - u0; dv = v
        s_ = du * .5 + dv * .866                                   # 沿侧枝
        t_ = np.abs(-du * .866 + dv * .5)                          # 离侧枝
        side = (s_ > 0) & (s_ < L) & (t_ < w * (1 - .6 * s_ / max(L, 1e-3)))
        alpha = np.maximum(alpha, side)
        hgt = np.maximum(hgt, np.clip(1 - t_ / (w + 1e-6), 0, 1) * side * .8)
    # 中心六角板（带一圈内棱）
    hexr = rng.uniform(.14, .24)
    hx = r * np.cos(np.mod(th, math.pi / 3) - math.pi / 6) / math.cos(math.pi / 6)
    plate = hx < hexr
    alpha = np.maximum(alpha, plate)
    ring = np.abs(hx - hexr * .62) < .012
    hgt = np.maximum(hgt, plate * .5 + ring * .9)
    # 枝尖的小板
    tipr = rng.uniform(.05, .09)
    tip = (np.hypot(u - .9, v) < tipr)
    alpha = np.maximum(alpha, tip)
    from scipy import ndimage
    alpha = ndimage.gaussian_filter(alpha, 1.0)
    hgt = ndimage.gaussian_filter(hgt * alpha, 1.5)
    return alpha.astype(np.float32), hgt.astype(np.float32)


def image_from(name, A):
    N = A.shape[0]
    img = bpy.data.images.new(name, N, N, alpha=True, float_buffer=True)
    rgba = np.zeros((N, N, 4), np.float32)
    rgba[..., 0] = rgba[..., 1] = rgba[..., 2] = A; rgba[..., 3] = 1
    img.pixels.foreach_set(rgba.ravel())
    img.pack()
    return img


def mat_flake(name, alpha_img, h_img):
    m, nb, out = B.new_material(name)
    tc = nb.node('ShaderNodeTexCoord').outputs['UV']
    ta = nb.node('ShaderNodeTexImage'); ta.image = alpha_img; ta.interpolation = 'Cubic'; nb.link(tc, ta.inputs['Vector'])
    th = nb.node('ShaderNodeTexImage'); th.image = h_img; th.interpolation = 'Cubic'; nb.link(tc, th.inputs['Vector'])
    ice = B.principled(nb, Roughness=.18, IOR=1.31)
    ice.inputs['Base Color'].default_value = (.8, .88, 1.0, 1)
    ice.inputs['Transmission Weight'].default_value = .15
    ice.inputs['Coat Weight'].default_value = .5
    nb.link(nb.bump(th.outputs['Color'], .9, .02), ice.inputs['Normal'])
    # 冰晶内部的散射：沿脊线更亮（像微距照片里雪花自己在发光）
    em = nb.node('ShaderNodeEmission'); em.inputs['Color'].default_value = (.6, .78, 1.0, 1)
    nb.link(nb.math('ADD', nb.math('MULTIPLY', th.outputs['Color'], 2.2), .35), em.inputs['Strength'])
    add = nb.node('ShaderNodeAddShader'); nb.link(ice.outputs[0], add.inputs[0]); nb.link(em.outputs[0], add.inputs[1])
    tr = nb.node('ShaderNodeBsdfTransparent')
    mix = nb.node('ShaderNodeMixShader')
    nb.link(ta.outputs['Color'], mix.inputs[0]); nb.link(tr.outputs[0], mix.inputs[1]); nb.link(add.outputs[0], mix.inputs[2])
    nb.link(mix.outputs[0], out.inputs['Surface'])
    return m


def main():
    os.makedirs(OUT, exist_ok=True)
    sc = B.reset()
    B.render_setup(sc, (F0, F1), samples=64, motion_blur=True, shutter=.5)
    sc.render.film_transparent = False
    # 背景：深蓝渐变（上暗下略亮，像黎明前的雪夜）
    w = bpy.data.worlds.new('dark'); sc.world = w; w.use_nodes = True
    nt = w.node_tree; bg = nt.nodes['Background']
    nb = B.NB(nt)
    d = nb.node('ShaderNodeTexCoord').outputs['Generated']
    sep = nb.node('ShaderNodeSeparateXYZ'); nb.link(d, sep.inputs[0])
    col = nb.mix(nb.maprange(sep.outputs['Z'], -.4, .6), (.012, .02, .045, 1), (.002, .004, .012, 1))
    nb.link(col, bg.inputs['Color']); bg.inputs['Strength'].default_value = 1.0
    # 冷色侧逆光 + 很弱的暖色补光
    key = bpy.data.lights.new('key', 'AREA'); key.energy = 400; key.size = 2; key.color = (.75, .85, 1.0)
    ko = bpy.data.objects.new('key', key); sc.collection.objects.link(ko); ko.location = (2.5, -1.0, 2.5)
    ko.rotation_euler = B.V((-3, -6, -4)).to_track_quat('-Z', 'Y').to_euler()
    fill = bpy.data.lights.new('fill', 'AREA'); fill.energy = 60; fill.size = 6; fill.color = (1.0, .85, .7)
    fo = bpy.data.objects.new('fill', fill); sc.collection.objects.link(fo); fo.location = (-5, -4, 1)
    fo.rotation_euler = B.V((5, 4, -1)).to_track_quat('-Z', 'Y').to_euler()
    # 镜头：微距（雪花直径约 3 mm），对焦在 0.12 m
    cam = B.camera(lens=60, clip=(.005, 50))
    cam.location = (0, -0.0, 0); cam.rotation_euler = (math.radians(90), 0, 0)
    cam.data.dof.use_dof = True; cam.data.dof.focus_distance = .12; cam.data.dof.aperture_fstop = 2.8
    rng = np.random.default_rng(1936)
    flakes = []
    for k in range(7):
        A, Hh = crystal(100 + k, 1024 if k == 0 else 512)
        ai, hi = image_from(f'fa{k}', A), image_from(f'fh{k}', Hh)
        flakes.append(mat_flake(f'flake{k}', ai, hi))
    # 雪花在镜头前 5~40 cm 的范围里缓缓飘落、旋转；最后一片从右上飘近镜头
    # 0 号：主角雪花（对焦面上、画面中偏上，缓缓旋转，最后飘进镜头）；1~8：对焦面附近的几片；其余：前后景的虚化光斑
    for i in range(34):
        me = bpy.data.meshes.new(f'f{i}')
        s = (rng.uniform(.0028, .0038) if i else .0036) / 2
        me.from_pydata([(-s, 0, -s), (s, 0, -s), (s, 0, s), (-s, 0, s)], [], [(0, 1, 2, 3)])
        uv = me.uv_layers.new(); uv.data.foreach_set('uv', [0, 0, 1, 0, 1, 1, 0, 1])
        me.materials.append(flakes[i % len(flakes)])
        ob = bpy.data.objects.new(f'f{i}', me); sc.collection.objects.link(ob)
        if 1 <= i <= 8:
            dist = rng.uniform(.105, .15)
        elif i > 8:
            dist = rng.uniform(.035, .07) if i % 2 else rng.uniform(.25, .6)
        else:
            dist = .12
        x0 = rng.uniform(-.15, .15) * dist; z0 = rng.uniform(-.1, .4) * dist
        vx = rng.uniform(-.003, .003) * dist / .2; vz = -rng.uniform(.004, .008) * dist / .2
        rot0 = rng.uniform(0, 6.28, 3); wr = rng.uniform(-.8, .8, 3)
        for f in range(F0, F1 + 1):
            t = (f - F0) / FPS
            if i == 0:
                u = max(0.0, (t - 2.3) / 1.35); u = u * u * (3 - 2 * u)
                yy = .12 - (.12 - .011) * u; xx = .002 * (1 - u); zz = (.014 - .0015 * t) * (1 - u)
                rx, ry, rz = .25 * math.sin(.7 * t), .35 * t, .2 * math.sin(.5 * t + 1)
            else:
                yy = dist; xx = x0 + vx * t; zz = z0 + vz * t
                rx, ry, rz = .35 * math.sin(rot0[0] + wr[0] * t), rot0[1] + wr[1] * t * .6, .35 * math.sin(rot0[2] + wr[2] * t)
            ob.location = (xx, yy, zz); ob.rotation_euler = (rx, ry, rz)
            ob.keyframe_insert('location', frame=f); ob.keyframe_insert('rotation_euler', frame=f)
    # 对焦：前 2.2s 对在 0.12 m，最后随那片雪花拉近
    for f in range(F0, F1 + 1):
        t = (f - F0) / FPS
        u = max(0.0, (t - 2.3) / 1.35); u = u * u * (3 - 2 * u)
        cam.data.dof.focus_distance = .12 - (.12 - .011) * u
        cam.data.dof.keyframe_insert('focus_distance', frame=f)
    sc.render.image_settings.file_format = 'PNG'
    B.exr_output(sc, os.path.join(OUT, 'exr'))
    B.export_camera(cam, F0, F1, os.path.join(OUT, 'camera.json'))
    json.dump(POST, open(os.path.join(OUT, 'post.json'), 'w'))
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, 'shot.blend'))
    print('saved', os.path.join(OUT, 'shot.blend'))


if __name__ == '__main__':
    main()
