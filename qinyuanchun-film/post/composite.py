"""后期：读取多层 EXR，在线性光下做大气透视、高度雾、辉光，再用 AgX 映射到显示，最后调色、暗角、颗粒。

雾色取自“画面中该列山脊线上方的真实天空”，所以远山会自然地融进它背后的天空里。
"""
import json
import math

import numpy as np
import OpenEXR
from scipy import ndimage


def read_exr(path):
    with OpenEXR.File(path, separate_channels=True) as f:
        ch = f.channels()
        def get(name):
            for k in ch:
                if k == name or k.endswith('.' + name.split('.')[-1]) and k.startswith(name.split('.')[0]):
                    return ch[k].pixels.astype(np.float32)
            return None
        out = {}
        out['rgb'] = np.stack([get('Image.R'), get('Image.G'), get('Image.B')], -1)
        out['a'] = get('Image.A')
        out['z'] = get('Depth.V') if get('Depth.V') is not None else get('Depth.Z')
        out['env'] = np.stack([get('Env.R'), get('Env.G'), get('Env.B')], -1)
        out['mist'] = get('Mist.V') if get('Mist.V') is not None else get('Mist.Z')
    return out


# ---------------------------------------------------------------- AgX（与 Blender 默认视图变换近似）
_AGX = np.array([[0.842479062253094, 0.0423282422610123, 0.0423756549057051],
                 [0.0784335999999992, 0.878468636469772, 0.0784336],
                 [0.0792237451477643, 0.0791661274605434, 0.879142973793104]], np.float32)
_AGX_INV = np.linalg.inv(_AGX).astype(np.float32)


def agx(rgb, exposure=0.0, punch=1.0, sat=1.0):
    x = np.maximum(rgb * (2.0 ** exposure), 1e-10) @ _AGX.T
    mn, mx = -12.47393, 4.026069
    x = np.clip((np.log2(x) - mn) / (mx - mn), 0, 1)
    x2 = x * x; x4 = x2 * x2
    y = 15.5 * x4 * x2 - 40.14 * x4 * x + 31.96 * x4 - 6.868 * x2 * x + 0.4298 * x2 + 0.1191 * x - 0.00232
    y = np.clip(y, 0, 1)
    if punch != 1.0:   # 以中灰为轴的轻微对比
        y = np.clip(.5 + (y - .5) * punch, 0, 1)
    y = y @ _AGX_INV.T
    y = np.clip(y, 0, 1)
    if sat != 1.0:
        l = (y * np.array([.2126, .7152, .0722], np.float32)).sum(-1, keepdims=True)
        y = np.clip(l + (y - l) * sat, 0, 1)
    return y   # 已是显示编码（约 sRGB）


# ---------------------------------------------------------------- 大气
def horizon_colors(rgb_env, a, band=(50, 170), smooth=60):
    """每列取山脊线上方一段天空的平均颜色。返回 (W,3)。"""
    H, W = a.shape
    solid = a > .5
    top = np.where(solid.any(0), solid.argmax(0), H)       # 每列第一个实体像素所在行
    cols = np.zeros((W, 3), np.float32); valid = np.zeros(W, bool)
    for x in range(W):
        h = top[x]
        y0, y1 = max(0, h - band[1]), max(0, h - band[0])
        if y1 - y0 >= 3:
            seg = rgb_env[y0:y1, x]; m = a[y0:y1, x] < .05
            if m.sum() >= 2:
                cols[x] = seg[m].mean(0); valid[x] = True
    if not valid.any():
        return None
    idx = np.arange(W)
    for c in range(3):
        cols[:, c] = np.interp(idx, idx[valid], cols[valid, c])
    return ndimage.gaussian_filter1d(cols, smooth, axis=0, mode='nearest')


def world_heights(z, cam):
    """由深度与镜头参数反算每个像素的世界坐标 z（海拔）与到镜头的距离。"""
    H, W = z.shape
    f = cam['lens'] / cam['sensor'] * max(W, H)
    xs = (np.arange(W) - W / 2 + .5) / f
    ys = -(np.arange(H) - H / 2 + .5) / f
    X, Y = np.meshgrid(xs, ys)
    R = np.array(cam['rot'], np.float32)
    d = np.stack([X, Y, -np.ones_like(X)], -1) @ R.T          # 相机坐标 → 世界方向（未归一化，-Z 分量为 1）
    wz = cam['loc'][2] + d[..., 2] * z
    dist = z * np.sqrt(X * X + Y * Y + 1)
    return wz, dist


def fog_amount(dist, wz, cam_z, dens, h_base, h_scale, dist_fog):
    """指数高度雾的光学厚度（沿视线积分）+ 均匀距离雾。"""
    dh = wz - cam_z
    e0 = np.exp(-np.clip((cam_z - h_base) / h_scale, -50, 50))
    e1 = np.exp(-np.clip((wz - h_base) / h_scale, -50, 50))
    with np.errstate(divide='ignore', invalid='ignore'):
        integ = np.where(np.abs(dh) > 1e-2, h_scale * (e0 - e1) / dh, e0)
    tau = dens * dist * np.maximum(integ, 0) + dist / dist_fog
    return 1 - np.exp(-tau)


def bloom(rgb, thresh=1.0, strength=.08, radius=(8, 30, 90)):
    l = rgb.max(-1, keepdims=True)
    hi = rgb * np.clip((l - thresh) / (thresh + 1e-6), 0, 4)
    acc = np.zeros_like(rgb)
    for r in radius:
        acc += ndimage.gaussian_filter(hi, (r, r, 0))
    return rgb + acc * strength / len(radius)


def vignette(img, amt=.25, soft=.65):
    H, W = img.shape[:2]
    y, x = np.mgrid[0:H, 0:W]
    r = np.sqrt(((x - W / 2) / (W / 2)) ** 2 * .55 + ((y - H / 2) / (H / 2)) ** 2)
    v = 1 - amt * np.clip((r - soft) / (1.35 - soft), 0, 1) ** 1.6
    return img * v[..., None]


def frame_cam(cams, f, shutter=.5):
    """第 f 帧的镜头参数，附上快门期间的位移终点（给雪花运动模糊用）。"""
    c = dict(cams[str(f)])
    n = cams.get(str(f + 1)) or cams.get(str(f))
    c['loc_next'] = [a + (b - a) * shutter for a, b in zip(c['loc'], n['loc'])]
    return c


def params_at(P, f):
    """把 P 中以 _keys 结尾的关键帧参数 [[帧, 值], ...] 插值到第 f 帧。"""
    Q = {k: v for k, v in P.items() if not k.endswith('_keys')}
    for k, v in P.items():
        if k.endswith('_keys'):
            fs = [a for a, _ in v]
            vals = np.array([b for _, b in v], np.float64)
            if vals.ndim == 1:
                Q[k[:-5]] = float(np.interp(f, fs, vals))
            else:
                Q[k[:-5]] = [float(np.interp(f, fs, vals[:, c])) for c in range(vals.shape[1])]
    return Q


def process(exr_path, cam, P):
    """P: 本镜头的参数字典（雾、曝光、调色）。返回 float32 显示编码图像 (H,W,3)。"""
    d = read_exr(exr_path)
    rgb, a, z, env = d['rgb'], d['a'], d['z'], d['env']
    H, W = a.shape
    aa = np.maximum(a, 1e-4)[..., None]
    fg = rgb / aa                                                      # 反预乘
    zc = np.where(a > 1e-3, z, 1e6)
    wz, dist = world_heights(zc, cam)
    if P.get('cloudsea'):
        # 云海：谁近取谁；露出云顶不高的山体加一层渐隐薄雾
        from post import cloudsea as CS
        from post import sky as SK
        Cs = P['cloudsea']
        sun = cam.get('sun') or {'dir': (0, -1, .1)}
        el = math.degrees(math.asin(max(-1, min(1, sun['dir'][2]))))
        srgb = np.array(SK.sun_rgb_at(el, Cs.get('base', 4800.0)), np.float64) * Cs.get('sun_gain', 3.0)
        amb = np.array(Cs.get('amb_rgb', (.25, .32, .45)), np.float64)
        dterr = np.where(a > .5, dist, 1e9)
        ccol, chit = CS.render(cam, W, H, dterr, P.get('time', 0.0), Cs, amb, sun['dir'], srgb)
        m = chit > 0
        if Cs.get('mist', 0) > 0:
            dvec = __import__('post.sky', fromlist=['ray_dirs']).ray_dirs(cam, W, H)
            px = cam['loc'][0] + dvec[..., 0] * dist; py = cam['loc'][1] + dvec[..., 1] * dist
            ct = CS.cloud_top(px, py, P.get('time', 0.0), Cs)
            k = np.clip(1 - (wz - ct) / Cs['mist'], 0, 1) ** 2 * (a > .5) * (~m)
            mc = amb * Cs.get('amb', 1.0) + srgb * Cs.get('sun_k', 1.0) * .6
            fg = fg * (1 - k[..., None]) + (mc * np.array(Cs.get('albedo', (.95, .96, 1.0))))[None, None, :] * k[..., None]
        fg = np.where(m[..., None], ccol, fg)
        dist = np.where(m, chit, dist)
        wz = np.where(m, cam['loc'][2] + __import__('post.sky', fromlist=['ray_dirs']).ray_dirs(cam, W, H)[..., 2] * chit, wz)
        a = np.where(m, 1.0, a).astype(np.float32)
        env = env * (1 - m[..., None])
    fog = fog_amount(dist, wz, cam['loc'][2], P.get('h_dens', 0.0), P.get('h_base', 0.0), P.get('h_scale', 800.0),
                     P.get('dist_fog', 1e9))
    fog = np.clip(fog * P.get('fog_max', 1.0), 0, 1)[..., None]
    hc = horizon_colors(env, a)
    if hc is None:
        hc = np.tile(np.array(P.get('fog_color', (.5, .55, .6)), np.float32), (W, 1))
    fc = np.array(P.get('fog_color', (.5, .55, .6)), np.float32)
    hc = hc * (1 - P.get('fog_color_mix', 0.0)) + fc * P.get('fog_color_mix', 0.0)
    fogc = hc[None, :, :] * np.array(P.get('fog_tint', (1, 1, 1)), np.float32)
    # 越靠下（越近）的雾色略暗，模拟雾层自身受光
    fogged = fg * (1 - fog) + fogc * fog
    if P.get('clouds'):
        from post import sky as SK
        C = dict(P['clouds'])
        sun = cam.get('sun')
        if sun is not None:
            C.setdefault('sun_dir', sun['dir'])
            el = math.degrees(math.asin(max(-1, min(1, sun['dir'][2]))))
            rgb = np.array(SK.sun_rgb_at(el, C.get('alt', 9000.0)), np.float64) * C.get('sun_gain', 2.0)
            C.setdefault('sun_rgb', rgb)
        inv = np.where(a < .999, 1 / np.maximum(1 - a, 1e-3), 0)[..., None]
        bgc = env * inv
        ccol, cal = SK.cloud_layer(cam, W, H, bgc, P.get('time', 0.0), C)
        bgc = bgc * (1 - cal[..., None]) + ccol * cal[..., None]
        env = bgc * (1 - a)[..., None]
    # 太阳圆盘（世界里关掉了太阳圆盘，画面里要看到太阳时在这里补上；被山体/云遮住的地方自然没有）
    if P.get('sun_disc') and cam.get('sun'):
        from post.sky import ray_dirs
        sd = np.array(cam['sun']['dir'], np.float64)
        cosv = (ray_dirs(cam, W, H) * sd).sum(-1)
        ang = np.degrees(np.arccos(np.clip(cosv, -1, 1)))
        SDp = P['sun_disc']
        r0 = SDp.get('size', .27)
        disc = np.clip((r0 * 1.15 - ang) / (r0 * .3), 0, 1)
        halo = np.exp(-ang / SDp.get('halo_w', 2.5)) * SDp.get('halo', .6) + np.exp(-ang / 12.0) * SDp.get('glow', .25)
        vis = (1 - a)[..., None]
        scol = np.array(SDp.get('color', (1.0, .8, .55)), np.float32)
        env = env + vis * (disc[..., None] * SDp.get('radiance', 60.0) + halo[..., None]) * scol
        fogged = fogged + (a[..., None]) * (halo[..., None] * scol) * SDp.get('veil', .35)
    out = fogged * a[..., None] + env
    # 镜头在云里：按镜头低于云顶的深度整体罩上云雾（穿云而出时由白到清）
    if P.get('cloudsea'):
        Cs = P['cloudsea']
        ct = float(CS.cloud_top(np.array([[cam['loc'][0]]]), np.array([[cam['loc'][1]]]), P.get('time', 0.0), Cs)[0, 0])
        inside = float(np.clip((ct + Cs.get('fog_top', 25.0) - cam['loc'][2]) / Cs.get('fog_depth', 90.0), 0, 1))
        if inside > 0:
            fc = (amb * Cs.get('amb', 1.0) * 1.6 + srgb * .55) * np.array(Cs.get('albedo', (.95, .96, 1.0)))
            # 云里并不均匀：加一点缓慢流动的明暗
            yy, xx = np.mgrid[0:H, 0:W]
            wob = 1 + .06 * np.sin(xx / W * 5.0 + P.get('time', 0.0) * 1.3) * np.sin(yy / H * 3.0 - P.get('time', 0.0))
            k = inside ** .7
            out = out * (1 - k) + (fc[None, None, :] * wob[..., None]) * k
    # 飘雪（三维雪花，近处焦外成光斑；被山体遮挡）
    if P.get('snow'):
        from post import snow as SN
        Sp = P['snow']
        dsnow = np.where(a > .5, dist, 1e9)
        sb = SN.render(cam, W, H, dsnow, P.get('time', 0.0), Sp)
        out = out + sb[..., None] * np.array(Sp.get('color', (.6, .65, .75)), np.float32)[None, None, :]
    if P.get('bloom', .06) > 0:
        out = bloom(out, P.get('bloom_thresh', 1.0), P.get('bloom', .06))
    disp = agx(out, P.get('exposure', 0.0), P.get('punch', 1.08), P.get('sat', 1.05))
    # 显示空间调色：lift / gamma / gain（每通道）
    lift = np.array(P.get('lift', (0, 0, 0)), np.float32); gain = np.array(P.get('gain', (1, 1, 1)), np.float32)
    gamma = np.array(P.get('gamma', (1, 1, 1)), np.float32)
    disp = np.clip(disp * gain + lift * (1 - disp), 0, 1) ** (1 / gamma)
    # 分离色调：暗部偏冷、亮部偏暖（按亮度平滑过渡）
    if 'shadow_tint' in P or 'high_tint' in P:
        l = (disp * np.array([.2126, .7152, .0722], np.float32)).sum(-1, keepdims=True)
        w = np.clip((l - .15) / .6, 0, 1); w = w * w * (3 - 2 * w)
        st = np.array(P.get('shadow_tint', (1, 1, 1)), np.float32); ht = np.array(P.get('high_tint', (1, 1, 1)), np.float32)
        disp = np.clip(disp * (st * (1 - w) + ht * w), 0, 1)
    disp = vignette(disp, P.get('vignette', .22))
    return np.clip(disp, 0, 1)
