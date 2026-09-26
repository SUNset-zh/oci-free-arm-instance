"""地形生成：梯度噪声 + 域扭曲 + 粒子水力侵蚀 + 热侵蚀，输出高度场（米）与积雪/岩石遮罩。

所有函数用 numba 加速；高度场为 float32 二维数组 H[j, i]，行 j 对应 y（北），列 i 对应 x（东）。
"""
import math
import os

os.environ.setdefault("NUMBA_THREADING_LAYER", "workqueue")   # 与 Blender 自带的 TBB 冲突，改用 numba 自己的线程池

import numpy as np
from numba import njit, prange


# ---------------------------------------------------------------- 噪声
def make_perm(seed):
    rng = np.random.default_rng(seed)
    p = rng.permutation(256).astype(np.int32)
    return np.concatenate([p, p])


@njit(cache=True, fastmath=True)
def _grad(h, x, y):
    g = h & 7
    if g == 0: return x + y
    if g == 1: return -x + y
    if g == 2: return x - y
    if g == 3: return -x - y
    if g == 4: return x
    if g == 5: return -x
    if g == 6: return y
    return -y


@njit(cache=True, fastmath=True)
def perlin(x, y, p):
    xi = int(math.floor(x)); yi = int(math.floor(y))
    xf = x - xi; yf = y - yi
    xi &= 255; yi &= 255
    u = xf * xf * xf * (xf * (xf * 6 - 15) + 10)
    v = yf * yf * yf * (yf * (yf * 6 - 15) + 10)
    aa = p[p[xi] + yi]; ab = p[p[xi] + yi + 1]; ba = p[p[xi + 1] + yi]; bb = p[p[xi + 1] + yi + 1]
    x1 = _grad(aa, xf, yf) + u * (_grad(ba, xf - 1, yf) - _grad(aa, xf, yf))
    x2 = _grad(ab, xf, yf - 1) + u * (_grad(bb, xf - 1, yf - 1) - _grad(ab, xf, yf - 1))
    return (x1 + v * (x2 - x1)) * 1.1


@njit(parallel=True, cache=True, fastmath=True)
def fbm_field(X, Y, p, freq, octaves, lac, gain):
    out = np.empty(X.shape, np.float32)
    for j in prange(X.shape[0]):
        for i in range(X.shape[1]):
            a = 1.0; f = freq; v = 0.0
            for o in range(octaves):
                v += a * perlin(X[j, i] * f + o * 17.3, Y[j, i] * f - o * 9.1, p)
                a *= gain; f *= lac
            out[j, i] = v
    return out


@njit(parallel=True, cache=True, fastmath=True)
def ridged_field(X, Y, p, freq, octaves, lac, gain, sharp):
    """脊状多重分形：尖锐山脊，低处平缓。"""
    out = np.empty(X.shape, np.float32)
    for j in prange(X.shape[0]):
        for i in range(X.shape[1]):
            a = 0.5; f = freq; v = 0.0; w = 1.0
            for o in range(octaves):
                n = 1.0 - abs(perlin(X[j, i] * f + o * 31.7, Y[j, i] * f + o * 12.9, p))
                n = max(n, 0.0) ** sharp
                v += n * a * w
                w = min(1.0, max(0.0, n * 1.8))
                a *= gain; f *= lac
            out[j, i] = v
    return out


def grid(n, extent, cx=0.0, cy=0.0):
    x = np.linspace(cx - extent / 2, cx + extent / 2, n, dtype=np.float64)
    y = np.linspace(cy - extent / 2, cy + extent / 2, n, dtype=np.float64)
    return np.meshgrid(x, y)


def warp(X, Y, p, freq, amp):
    return X + amp * fbm_field(X, Y, p, freq, 4, 2.0, .5), Y + amp * fbm_field(X + 511.3, Y - 213.7, p, freq, 4, 2.0, .5)


# ---------------------------------------------------------------- 水力侵蚀（粒子法）
@njit(cache=True)
def _height_grad(H, x, y):
    n = H.shape[0]
    i = int(x); j = int(y)
    u = x - i; v = y - j
    h00 = H[j, i]; h10 = H[j, i + 1]; h01 = H[j + 1, i]; h11 = H[j + 1, i + 1]
    gx = (h10 - h00) * (1 - v) + (h11 - h01) * v
    gy = (h01 - h00) * (1 - u) + (h11 - h10) * u
    h = h00 * (1 - u) * (1 - v) + h10 * u * (1 - v) + h01 * (1 - u) * v + h11 * u * v
    return h, gx, gy


@njit(cache=True)
def erode(H, drops, seed, cell, radius=3, inertia=.05, cap=4.0, min_slope=.01, erode_s=.3, deposit_s=.3,
          evap=.015, gravity=4.0, max_steps=64):
    """Sebastian Lague 风格的粒子水力侵蚀。H 以“米”为单位，cell 为网格间距（米）。"""
    np.random.seed(seed)
    ny_, nx_ = H.shape[0], H.shape[1]
    # 侵蚀刷子权重
    offs = []
    ws = []
    for dj in range(-radius, radius + 1):
        for di in range(-radius, radius + 1):
            d = math.sqrt(di * di + dj * dj)
            if d <= radius:
                offs.append((di, dj)); ws.append(radius - d)
    wsum = 0.0
    for w in ws: wsum += w
    Hs = H / cell   # 以网格为单位计算坡度，避免尺度问题
    for _ in range(drops):
        x = np.random.random() * (nx_ - 2 * radius - 2) + radius
        y = np.random.random() * (ny_ - 2 * radius - 2) + radius
        dx = 0.0; dy = 0.0; speed = 1.0; water = 1.0; sed = 0.0
        for _s in range(max_steps):
            i = int(x); j = int(y); u = x - i; v = y - j
            h, gx, gy = _height_grad(Hs, x, y)
            dx = dx * inertia - gx * (1 - inertia)
            dy = dy * inertia - gy * (1 - inertia)
            l = math.sqrt(dx * dx + dy * dy)
            if l < 1e-9: break
            dx /= l; dy /= l
            nx = x + dx; ny = y + dy
            if not (nx == nx and ny == ny): break
            if nx < radius + 1 or ny < radius + 1 or nx > nx_ - radius - 2 or ny > ny_ - radius - 2: break
            nh, _a, _b = _height_grad(Hs, nx, ny)
            dh = nh - h
            c = max(-dh, min_slope) * speed * water * cap
            if sed > c or dh > 0:
                amt = min(dh, sed) if dh > 0 else (sed - c) * deposit_s
                sed -= amt
                Hs[j, i] += amt * (1 - u) * (1 - v); Hs[j, i + 1] += amt * u * (1 - v)
                Hs[j + 1, i] += amt * (1 - u) * v; Hs[j + 1, i + 1] += amt * u * v
            else:
                amt = min((c - sed) * erode_s, -dh)
                for k in range(len(offs)):
                    di, dj = offs[k]
                    w = ws[k] / wsum * amt
                    ii = i + di; jj = j + dj
                    take = w if Hs[jj, ii] >= w else Hs[jj, ii]
                    Hs[jj, ii] -= w
                sed += amt
            speed = math.sqrt(max(0.0, speed * speed + dh * gravity))
            water *= (1 - evap)
            x = nx; y = ny
    return Hs * cell


@njit(parallel=True, cache=True)
def thermal(H, cell, talus_deg, iters, rate=.25):
    """热侵蚀：超过休止角的坡面向下滑落，磨圆尖刺、形成碎石坡。"""
    ny_, nx_ = H.shape[0], H.shape[1]
    T = math.tan(math.radians(talus_deg)) * cell
    A = H.copy()
    for _ in range(iters):
        D = np.zeros_like(A)
        for j in prange(1, ny_ - 1):
            for i in range(1, nx_ - 1):
                h = A[j, i]
                for dj in (-1, 0, 1):
                    for di in (-1, 0, 1):
                        if di == 0 and dj == 0: continue
                        d = h - A[j + dj, i + di]
                        lim = T * (1.4142 if di != 0 and dj != 0 else 1.0)
                        if d > lim:
                            m = (d - lim) * rate / 8
                            D[j, i] -= m
                            D[j + dj, i + di] += m
        A += D
    return A


# ---------------------------------------------------------------- 分析
def normals(H, cell):
    gy, gx = np.gradient(H, cell)
    nz = 1 / np.sqrt(1 + gx * gx + gy * gy)
    return -gx * nz, -gy * nz, nz


def curvature(H, cell):
    """正值为凹（沟谷，积雪），负值为凸（山脊，风吹裸露）。"""
    lap = (np.roll(H, 1, 0) + np.roll(H, -1, 0) + np.roll(H, 1, 1) + np.roll(H, -1, 1) - 4 * H) / (cell * cell)
    return lap


def blur(A, r):
    """可分离的盒式模糊，r 为半径（格）。"""
    if r < 1: return A
    k = np.ones(2 * r + 1) / (2 * r + 1)
    B = np.apply_along_axis(lambda v: np.convolve(np.pad(v, r, mode='edge'), k, 'valid'), 0, A)
    return np.apply_along_axis(lambda v: np.convolve(np.pad(v, r, mode='edge'), k, 'valid'), 1, B)


def snow_mask(H, cell, p, snow_line=-1e9, slope_lo=.55, slope_hi=.7, wind=(0.7, 0.3), ridge=.25):
    """积雪遮罩：由坡度主导（>约 50° 的陡崖露岩），凹沟积雪、凸脊略薄。返回 0..1（1 = 厚雪）。"""
    nx, ny, nz = normals(H, cell)
    cv = blur(curvature(H, cell), 1)
    s = np.clip((nz - slope_lo) / (slope_hi - slope_lo), 0, 1)
    cvn = np.tanh(cv * cell * cell / 8.0)
    lee = np.clip(-(nx * wind[0] + ny * wind[1]) * 1.5, -1, 1)
    X, Y = np.meshgrid(np.arange(H.shape[1]) * cell, np.arange(H.shape[0]) * cell)
    brk = fbm_field(X.astype(np.float64), Y.astype(np.float64), p, 1 / 90.0, 4, 2.0, .5)
    m = s + .18 * cvn + .06 * lee + .12 * brk
    m = np.clip((m - .3) / .5, 0, 1)
    alt = np.clip((H - snow_line) / 200, 0, 1)
    return (m * alt).astype(np.float32)


# ---------------------------------------------------------------- 积雪层（物理近似）
@njit(parallel=True, cache=True)
def _snow_slide(H, D, cell, talus, rate):
    ny_, nx_ = H.shape[0], H.shape[1]
    T = math.tan(math.radians(talus)) * cell
    M = np.zeros_like(D)
    for j in prange(1, ny_ - 1):
        for i in range(1, nx_ - 1):
            if D[j, i] <= 0: continue
            s = H[j, i] + D[j, i]
            tot = 0.0
            for dj in (-1, 0, 1):
                for di in (-1, 0, 1):
                    if di == 0 and dj == 0: continue
                    lim = T * (1.4142 if di != 0 and dj != 0 else 1.0)
                    d = s - (H[j + dj, i + di] + D[j + dj, i + di]) - lim
                    if d > 0: tot += d
            if tot <= 0: continue
            mv = min(D[j, i], tot * rate)
            for dj in (-1, 0, 1):
                for di in (-1, 0, 1):
                    if di == 0 and dj == 0: continue
                    lim = T * (1.4142 if di != 0 and dj != 0 else 1.0)
                    d = s - (H[j + dj, i + di] + D[j + dj, i + di]) - lim
                    if d > 0:
                        M[j + dj, i + di] += mv * d / tot
            M[j, i] -= mv
    return M


def snow_layer(H, cell, depth=6.0, lo=.35, hi=.6, talus=42, iters=60, rate=.2):
    """在地形上铺一层雪并让它从陡坡滑落、在凹处堆积。返回 (雪面高度 H+D, 雪深 D)。"""
    nx, ny, nz = normals(H, cell)
    cv = blur(curvature(H, cell), 2)
    c = np.clip((nz - lo) / (hi - lo), 0, 1)
    D = (depth * c * (1 + .6 * np.tanh(cv * cell * cell / 6.0))).astype(np.float32)
    D = np.maximum(D, 0).astype(np.float32)
    Hf = H.astype(np.float32)
    for _ in range(iters):
        D = np.maximum(D + _snow_slide(Hf, D, cell, talus, rate), 0).astype(np.float32)
    D = blur(D, 1).astype(np.float32)
    return (Hf + D).astype(np.float32), D
