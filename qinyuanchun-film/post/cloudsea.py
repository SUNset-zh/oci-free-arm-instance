"""云海：在后期里对一个“云顶高度场”做逐像素光线步进（numba 并行）。

云顶 C(x,y,t) = base + A1·大尺度起伏 + A2·积云状鼓包（|噪声| 的反相：圆顶 + 窄缝）。
光线从镜头出发，先落到云层包围盒顶部，再按“离云顶的高度差”自适应步长前进，命中后二分细化。
着色：
  - 太阳：包裹式漫反射（云是半透明的，背光面不会全黑）+ 朝太阳方向的短距离步进求自阴影；
  - 环境：天空色 × 缝隙遮蔽（鼓包之间的窄缝更暗）；
  - 逆光时的银边：视线接近太阳方向时，云缘更亮。
与地形合成：谁近取谁；山体刚露出云顶的那一段（高出云顶 0~mist 米）加一层渐隐的薄雾，接缝就是软的。
"""
import math
import os

os.environ.setdefault("NUMBA_THREADING_LAYER", "workqueue")

import numpy as np
from numba import njit, prange

from common import terrain as T

_P = T.make_perm(2024)


@njit(cache=True, fastmath=True)
def _cloud_h(x, y, t, base, a1, s1, a2, s2, wx, wy, p):
    # 大尺度起伏
    X = x - wx * t; Y = y - wy * t
    v = 0.0; amp = 1.0; f = 1.0 / s1
    for o in range(3):
        v += amp * T.perlin(X * f + o * 5.3, Y * f - o * 3.1, p)
        amp *= .5; f *= 2.0
    # 积云鼓包：1-|n|（尖脊）再取平方的反相 → 圆顶 + 窄缝；不同八度朝不同方向慢慢演变
    b = 0.0; amp = 1.0; f = 1.0 / s2; tot = 0.0
    for o in range(4):
        n = T.perlin(X * f + o * 11.7 + t * .013 * (o + 1), Y * f - o * 7.9 - t * .009 * (o + 1), p)
        b += amp * abs(n) ** .8
        tot += amp
        amp *= .5; f *= 2.1
    b /= tot
    return base + a1 * v + a2 * (b - .5) * 2.0


@njit(parallel=True, cache=True, fastmath=True)
def march(dirs, ox, oy, oz, tmax, t, base, a1, s1, a2, s2, wx, wy, p, sdx, sdy, sdz, shade_steps, shade_len):
    """返回每个像素的命中距离（未命中为 -1）、法线 z 分量、太阳可见度、缝隙遮蔽。"""
    H, W = dirs.shape[0], dirs.shape[1]
    hit = np.full((H, W), -1.0)
    nzs = np.zeros((H, W)); nxs = np.zeros((H, W)); nys = np.zeros((H, W)); vis = np.ones((H, W)); ao = np.ones((H, W))
    top = base + abs(a1) + abs(a2) + 5.0
    for j in prange(H):
        for i in range(W):
            dx = dirs[j, i, 0]; dy = dirs[j, i, 1]; dz = dirs[j, i, 2]
            tt = 0.0
            if oz > top:
                if dz >= -1e-5:
                    continue
                tt = (top - oz) / dz
            tlim = tmax[j, i]
            if tt > tlim:
                continue
            found = False
            prev = tt
            for k in range(160):
                x = ox + dx * tt; y = oy + dy * tt; z = oz + dz * tt
                c = _cloud_h(x, y, t, base, a1, s1, a2, s2, wx, wy, p)
                h = z - c
                if h < 0:
                    found = True
                    break
                if z > top and dz >= 0:
                    break
                prev = tt
                tt += max(2.0, max(h / (abs(dz) + .6), tt * .004))
                if tt > tlim:
                    break
            if not found:
                continue
            lo = prev; hi = tt
            for k in range(10):
                mid = .5 * (lo + hi)
                x = ox + dx * mid; y = oy + dy * mid; z = oz + dz * mid
                if z - _cloud_h(x, y, t, base, a1, s1, a2, s2, wx, wy, p) < 0:
                    hi = mid
                else:
                    lo = mid
            th = hi
            x = ox + dx * th; y = oy + dy * th
            e = max(3.0, th * .002)
            c0 = _cloud_h(x, y, t, base, a1, s1, a2, s2, wx, wy, p)
            cx = _cloud_h(x + e, y, t, base, a1, s1, a2, s2, wx, wy, p)
            cy = _cloud_h(x, y + e, t, base, a1, s1, a2, s2, wx, wy, p)
            gx = (cx - c0) / e; gy = (cy - c0) / e
            nz = 1.0 / math.sqrt(1 + gx * gx + gy * gy)
            nzs[j, i] = nz; nxs[j, i] = -gx * nz; nys[j, i] = -gy * nz
            hit[j, i] = th
            # 朝太阳方向在云顶上方前进，若被更高的云顶挡住则进入阴影（软）
            occ = 0.0
            sx = x; sy = y; sz = c0 + 1.0
            for k in range(shade_steps):
                d = shade_len * (k + 1) / shade_steps
                qx = sx + sdx * d; qy = sy + sdy * d; qz = sz + sdz * d
                ch = _cloud_h(qx, qy, t, base, a1, s1, a2, s2, wx, wy, p)
                if ch > qz:
                    occ += min(1.0, (ch - qz) / 40.0)
            vis[j, i] = math.exp(-occ * .9)
            # 缝隙遮蔽：比周围平均低的地方更暗
            r = max(60.0, th * .01)
            av = (_cloud_h(x + r, y, t, base, a1, s1, a2, s2, wx, wy, p) + _cloud_h(x - r, y, t, base, a1, s1, a2, s2, wx, wy, p)
                  + _cloud_h(x, y + r, t, base, a1, s1, a2, s2, wx, wy, p) + _cloud_h(x, y - r, t, base, a1, s1, a2, s2, wx, wy, p)) * .25
            ao[j, i] = min(1.0, max(0.62, 1.0 - (av - c0) / 160.0))
    return hit, nxs, nys, nzs, vis, ao


@njit(parallel=True, cache=True, fastmath=True)
def heights_at(xs, ys, t, base, a1, s1, a2, s2, wx, wy, p):
    out = np.empty(xs.shape)
    for j in prange(xs.shape[0]):
        for i in range(xs.shape[1]):
            out[j, i] = _cloud_h(xs[j, i], ys[j, i], t, base, a1, s1, a2, s2, wx, wy, p)
    return out


def cloud_top(xs, ys, t, C):
    w = C.get('wind', (6.0, 2.0))
    return heights_at(xs.astype(np.float64), ys.astype(np.float64), float(t), C.get('base', 4800.0), C.get('a1', 180.0),
                      C.get('s1', 9000.0), C.get('a2', 140.0), C.get('s2', 900.0), w[0], w[1], _P)


def render(cam, W, H, dist_terrain, t, C, sky_amb, sun_dir, sun_rgb):
    """返回 (颜色 HxWx3 线性, 命中距离 HxW，未命中 -1)。dist_terrain：每像素到地形的距离（天空为很大）。"""
    from post.sky import ray_dirs
    d = ray_dirs(cam, W, H)
    sd = np.array(sun_dir, np.float64); sd = sd / np.linalg.norm(sd)
    hit, nx, ny, nz, vis, ao = march(d, float(cam['loc'][0]), float(cam['loc'][1]), float(cam['loc'][2]),
                             np.minimum(dist_terrain, C.get('tmax', 150000.0)).astype(np.float64), float(t),
                             C.get('base', 4800.0), C.get('a1', 180.0), C.get('s1', 9000.0), C.get('a2', 140.0),
                             C.get('s2', 900.0), C.get('wind', (6.0, 2.0))[0], C.get('wind', (6.0, 2.0))[1], _P,
                             sd[0], sd[1], max(sd[2], .02), int(C.get('shade_steps', 6)), C.get('shade_len', 900.0))
    wrap = C.get('wrap', .5)
    ndl = np.clip((nx * sd[0] + ny * sd[1] + nz * sd[2] + wrap) / (1 + wrap), 0, 1)
    cos_v = (d * sd).sum(-1)
    silver = np.clip(cos_v, 0, 1) ** 8 * C.get('silver', 1.5)
    sun_rgb = np.array(sun_rgb, np.float64)
    col = (sun_rgb[None, None, :] * (C.get('sun_k', 1.0) * ndl * vis + silver * vis)[..., None]
           + sky_amb * (C.get('amb', 1.0) * ao)[..., None])
    col *= np.array(C.get('albedo', (.95, .96, 1.0)))
    # 云是体积散射体，边缘不会像固体那样锐利：按屏幕空间做一点柔化（只在云内部混合）
    soft = C.get('soft', 1.6)
    if soft > 0:
        from scipy import ndimage
        m = (hit > 0).astype(np.float32)
        cb = np.stack([ndimage.gaussian_filter(col[..., c] * m, soft) for c in range(3)], -1)
        mb = ndimage.gaussian_filter(m, soft)[..., None]
        col = np.where(m[..., None] > 0, cb / np.maximum(mb, 1e-4), col)
    return col.astype(np.float32), hit.astype(np.float32)
