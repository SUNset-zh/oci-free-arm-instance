"""后期云层：把一张程序化云图放在某个海拔的水平面上，逐像素用镜头射线求交，得到透视正确的云。

光照近似（日出日落时最重要的几件事）：
- 云底被低角度的太阳从下方照亮：云的受光颜色 = 云所在高度处的太阳颜色（比地面更早见到太阳、更红）；
- 自阴影：沿太阳方向在云图上错位采样，密度差越大越暗（伪体积感）；
- 前向散射：看向太阳方向时云边发亮（Henyey-Greenstein）；
- 环境光：取该像素原本的天空颜色。
全部在线性光下做，之后再和地形、大气透视一起进 AgX。
"""
import math

import numpy as np

from common import terrain as T

_PERM = T.make_perm(1949)


def _fbm(x, y, freq, octaves, gain=.5, lac=2.03, off=0.0):
    return T.fbm_field(x.astype(np.float64) + off, y.astype(np.float64) - off * .7, _PERM, freq, octaves, lac, gain)


def sun_rgb_at(el, alt):
    """某海拔处看到的太阳颜色（含强度，相对值）。高处能看到地平线以下的太阳（视地平下倾）。"""
    dip = math.degrees(math.sqrt(2 * max(alt, 0) / 6371000.0))
    e = el + dip * .85
    if e < -1.0:
        return (0.0, 0.0, 0.0)
    ee = max(e, -.5)
    am = 1.0 / (math.sin(math.radians(ee)) + 0.50572 * (ee + 6.07995) ** -1.6364)
    am *= 1 + max(0, -.5 - e) * .6
    lam = np.array([.61, .55, .465])
    tr = .0088 * lam ** -4.05 * math.exp(-alt / 8400.0)
    ta = .08 * (lam / .55) ** -1.3 * math.exp(-alt / 1500.0)
    Tt = np.exp(-(tr + ta) * am)
    fade = min(1.0, (e + 1.0) / 1.0)
    return tuple((Tt * fade).tolist())


def ray_dirs(cam, W, H):
    f = cam['lens'] / cam['sensor'] * max(W, H)
    xs = (np.arange(W) - W / 2 + .5) / f
    ys = -(np.arange(H) - H / 2 + .5) / f
    X, Y = np.meshgrid(xs, ys)
    R = np.array(cam['rot'], np.float64)
    d = np.stack([X, Y, -np.ones_like(X)], -1) @ R.T
    return d / np.linalg.norm(d, axis=-1, keepdims=True)


def hg(cos_t, g):
    return (1 - g * g) / (4 * math.pi * (1 + g * g - 2 * g * cos_t) ** 1.5)


def cloud_layer(cam, W, H, sky, t, C):
    """返回 (云颜色 rgb, 不透明度 α)，形状 (H,W,3) / (H,W)。
    sky: 该像素的天空辐亮度（线性，用作环境光）。t: 秒（云随风飘移）。C: 参数字典：
      alt 云高(米), cover 覆盖率 0..1, scale 主尺度(米), stretch 沿风向拉伸, wind (vx, vy) 米/秒,
      thick 光学厚度, sun_dir 指向太阳的单位向量, sun_rgb 云高处太阳颜色*强度, amb 环境光系数, bright 受光系数,
      shade 自阴影强度, far 渐隐距离(米), tint 整体色调"""
    d = ray_dirs(cam, W, H)
    cz = cam['loc'][2]
    alt = C.get('alt', 9000.0)
    up = d[..., 2]
    ok = up > 1e-3
    tt = np.where(ok, (alt - cz) / np.maximum(up, 1e-3), 0)
    px = cam['loc'][0] + d[..., 0] * tt
    py = cam['loc'][1] + d[..., 1] * tt
    wx, wy = C.get('wind', (8.0, 2.0))
    px = px - wx * t; py = py - wy * t
    # 沿风向拉伸（卷云/高积云的条纹）
    ang = math.atan2(wy, wx) if (wx or wy) else 0.0
    ca, sa = math.cos(ang), math.sin(ang)
    u = (px * ca + py * sa) / C.get('stretch', 2.5)
    v = -px * sa + py * ca
    sc = C.get('scale', 6000.0)
    n = _fbm(u, v, 1 / sc, 6, .55, off=13.0)
    n2 = _fbm(u * 1.9, v * 1.9, 1 / sc, 4, .5, off=91.0)
    dens = n * .75 + n2 * .35
    cover = C.get('cover', .45)
    thr = .55 - cover * 1.1
    D = np.clip((dens - thr) / .45, 0, 1) ** 1.3
    # 自阴影：朝太阳方向错位采样
    sd = np.array(C.get('sun_dir', (0, 1, .05)), np.float64)
    sxy = sd[:2] / (np.linalg.norm(sd[:2]) + 1e-9)
    off = C.get('shade_off', 350.0)
    uo = ((px + sxy[0] * off) * ca + (py + sxy[1] * off) * sa) / C.get('stretch', 2.5)
    vo = -(px + sxy[0] * off) * sa + (py + sxy[1] * off) * ca
    no = _fbm(uo, vo, 1 / sc, 6, .55, off=13.0) * .75 + _fbm(uo * 1.9, vo * 1.9, 1 / sc, 4, .5, off=91.0) * .35
    Do = np.clip((no - thr) / .45, 0, 1) ** 1.3
    lit = np.exp(-C.get('shade', 2.5) * np.maximum(Do - D * .5, 0))
    # 远处渐隐（地平线附近云层压得很扁，容易出现锯齿）
    far = C.get('far', 120000.0)
    fade = np.clip(1 - tt / far, 0, 1) * ok
    alpha = (1 - np.exp(-C.get('thick', 3.0) * D)) * fade
    cos_t = (d * sd).sum(-1)
    ph = hg(cos_t, .55) * 4 * math.pi * .35 + .65
    sun_rgb = np.array(C.get('sun_rgb', (1, .8, .6)), np.float64)
    col = sky * C.get('amb', .9) + sun_rgb[None, None, :] * (C.get('bright', 1.0) * lit * ph)[..., None]
    col = col * np.array(C.get('tint', (1, 1, 1)), np.float64)
    return col.astype(np.float32), alpha.astype(np.float32)
