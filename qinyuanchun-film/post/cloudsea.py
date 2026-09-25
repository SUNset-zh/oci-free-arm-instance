"""云海：在后期里对一个“云顶高度场”做逐像素光线步进（numba 并行）。

云顶 C(x,y,t) = 海面 + 成簇的积云团：
  - 海面：base + 几公里的缓慢起伏（A1）+ 顺风拉长的缓浪（A4）；
  - 积云团：大、中、小三层“圆顶”叠在一起（每个格子里一个随机位置、随机大小的扁圆顶，重叠处用平滑最大值
    连成圆角，所以团与团之间没有折痕），再用域扭曲打乱排列；团的覆盖度由低频噪声决定——有的地方平如海面，
    有的地方云团翻涌。团会随时间缓慢胀缩，整体随风漂移。
光线从镜头出发，先落到云层包围盒顶部，再按“离云顶的高度差”自适应步长前进，命中后二分细化。
着色：
  - 太阳：包裹式漫反射（云是半透明的，背光面不会全黑）+ 朝太阳方向的短距离步进求自阴影；
  - 多次散射：阴影里也透着一点被云自己散射过来的光；
  - 环境：天空色 × 缝隙遮蔽（近、远两个尺度），所以阴影是亮的、偏蓝的，不是灰的；
  - 逆光时的银边：视线接近太阳方向时，云缘更亮。
云是体积，不是硬表面：
  - 近处的云按屏幕空间柔化得多一些，远处少一些；
  - 云顶上方贴着一层絮状薄雾（密度随离云顶的高度指数衰减，按噪声成絮）：视线擦过云顶时穿过的薄雾多，
    所以云的轮廓是虚的；镜头刚破云而出时，四周也还笼着一层云气。
与地形合成：谁近取谁；山体刚露出云顶的那一段（高出云顶 0~mist 米）加一层渐隐的薄雾，接缝就是软的。
"""
import math
import os

os.environ.setdefault("NUMBA_THREADING_LAYER", "workqueue")

import numpy as np
from numba import njit, prange

from common import terrain as T

_P = T.make_perm(2024)


def params(C):
    """把参数字典打包成 numba 用的数组。"""
    w = C.get('wind', (6.0, 2.0))
    return np.array([C.get('base', 4800.0), C.get('a1', 180.0), C.get('s1', 9000.0), C.get('a2', 140.0),
                     C.get('s2', 900.0), w[0], w[1], C.get('a3', 0.0), C.get('s3', 120.0), C.get('warp', 0.0),
                     C.get('micro', 0.0), C.get('evolve', 1.0), C.get('mid', .42), C.get('cover', 1.0),
                     C.get('a4', 0.0), C.get('s4', 3000.0)], np.float64)


@njit(cache=True, fastmath=True)
def _hash(ix, iy, s):
    h = (ix * 374761393 + iy * 668265263 + s * 982451653) & 0xffffffff
    h = ((h ^ (h >> 13)) * 1274126177) & 0xffffffff
    return h ^ (h >> 16)


@njit(cache=True, fastmath=True)
def _puffs(x, y, cell, seed, empty, t, expo, ks):
    """一层“云团”：每个格子里一个随机位置、随机大小的扁圆顶（缓慢胀缩），重叠处用平滑最大值圆润地连起来。返回约 0~1。"""
    fx = x / cell; fy = y / cell
    ix = math.floor(fx); iy = math.floor(fy)
    best = 0.0
    for dy in range(-1, 2):
        for dx in range(-1, 2):
            cx = ix + dx; cy = iy + dy
            h = _hash(int(cx), int(cy), seed)
            u1 = (h & 1023) / 1024.0; u2 = ((h >> 10) & 1023) / 1024.0; u3 = ((h >> 20) & 1023) / 1024.0
            if u3 < empty:
                continue
            # 半径 ≤ 1.15 格：保证只查 3×3 个格子就不会漏掉（否则格子边界上会出现一道折线）
            r = (.55 + .55 * (u3 - empty) / (1.0 - empty)) * (1.0 + .04 * math.sin(t * .35 + u1 * 40.0))
            px = cx + .15 + .7 * u1; py = cy + .15 + .7 * u2
            d2 = ((fx - px) * (fx - px) + (fy - py) * (fy - py)) / (r * r)
            if d2 < 1.0:
                z = r * (1.0 - d2) ** expo
                # 平滑最大值：团与团相接处是圆角，不是折痕；圆角在团的边缘处渐隐为 0（否则边缘会多出一级台阶）
                hh = max(ks - abs(z - best), 0.0) / ks
                w = min(1.0, (1.0 - d2) * 5.0)
                best = max(z, best) + hh * hh * ks * .25 * w * w * (3.0 - 2.0 * w)
    return best / 1.1


@njit(cache=True, fastmath=True)
def _cloud_h(x, y, t, q, p):
    base = q[0]; a1 = q[1]; s1 = q[2]; a2 = q[3]; s2 = q[4]; wx = q[5]; wy = q[6]
    a3 = q[7]; s3 = q[8]; warp = q[9]; micro = q[10]; ev = q[11]; mid = q[12]
    cover = q[13]; a4 = q[14]; s4 = q[15]
    X = x - wx * t; Y = y - wy * t
    # 大尺度起伏
    v = 0.0; amp = 1.0; f = 1.0 / s1
    for o in range(3):
        v += amp * T.perlin(X * f + o * 5.3, Y * f - o * 3.1, p)
        amp *= .5; f *= 2.0
    # 域扭曲：云团的排列不规则
    U = X; V = Y
    if warp > 0:
        fw = 1.0 / (1.7 * s2)
        U = X + warp * s2 * T.perlin(X * fw + 17.1, Y * fw - 4.2, p)
        V = Y + warp * s2 * T.perlin(X * fw - 9.4, Y * fw + 13.7, p)
    # 云海“海面”：顺风拉长的缓浪
    h = base + a1 * v
    if a4 > 0:
        h += a4 * T.perlin(U / s4 + 3.3, V / (s4 * .45) - 8.1, p) + a4 * .4 * T.perlin(U / (s4 * .4) - 1.7, V / (s4 * .2) + 4.4, p)
    # 成簇的积云：覆盖度由低频噪声决定（有的地方平如海面，有的地方云团翻涌）
    cov = 1.0
    if cover < 1.0:
        n = T.perlin(U / (s2 * 3.3) + 41.0, V / (s2 * 3.3) - 23.0, p) * .5 + .5
        k = (n - (1.0 - cover) + .12) / .24
        k = min(1.0, max(0.0, k))
        cov = k * k * (3 - 2 * k)
    if cov > 0:
        tt = t * ev
        big = _puffs(U, V, s2, 11, .22, tt, 1.0, .3)
        med = _puffs(U + 37.0, V - 91.0, s2 * mid, 23, .08, tt * 1.3, 1.1, .3)
        sml = _puffs(U - 53.0, V + 17.0, s3, 37, 0.0, tt * 1.7, 1.2, .3)
        h += cov * (a2 * big + a2 * .55 * med + a3 * sml * (.4 + big))
    # 表面的细微起伏
    if micro > 0:
        h += micro * T.perlin(U / (s3 * .35) + 5.5, V / (s3 * .35) - 2.5, p)
    return h


@njit(parallel=True, cache=True, fastmath=True)
def march(dirs, ox, oy, oz, tmax, t, q, p, sdx, sdy, sdz, shade_steps, shade_len, top, ww, wrho, wl, rin):
    """返回每个像素的命中距离（未命中为 -1）、法线、太阳可见度、缝隙遮蔽（近、远两个尺度），
    以及视线穿过云顶絮状薄雾层的光学厚度 tau（薄雾密度 wrho·exp(-离云顶高度/ww)，按 wl 米尺度的噪声成絮）；
    镜头在云里时，视线在云体里走过的距离按消光系数 rin 计入 tau。"""
    H, W = dirs.shape[0], dirs.shape[1]
    hit = np.full((H, W), -1.0)
    nzs = np.zeros((H, W)); nxs = np.zeros((H, W)); nys = np.zeros((H, W)); vis = np.ones((H, W)); ao = np.ones((H, W))
    tau = np.zeros((H, W))
    top_w = top + (4.0 * ww if wrho > 0 else 0.0)
    for j in prange(H):
        for i in range(W):
            dx = dirs[j, i, 0]; dy = dirs[j, i, 1]; dz = dirs[j, i, 2]
            tt = 0.0
            if oz > top_w:
                if dz >= -1e-5:
                    continue
                tt = (top_w - oz) / dz
            tlim = tmax[j, i]
            if tt > tlim:
                continue
            found = False
            prev = tt
            od = 0.0
            # 起点在云里（镜头正在穿云）：先在云体里前进，按穿过的云的长度累积光学厚度，直到走出云顶
            x = ox + dx * tt; y = oy + dy * tt; z = oz + dz * tt
            h = z - _cloud_h(x, y, t, q, p)
            if h < 0:
                for k in range(200):
                    st = max(3.0, min(-h / (abs(dz) + .3), 60.0))
                    od += rin * st
                    tt += st
                    if od > 12.0 or tt > tlim:
                        break
                    x = ox + dx * tt; y = oy + dy * tt; z = oz + dz * tt
                    h = z - _cloud_h(x, y, t, q, p)
                    if h >= 0:
                        break
                if h < 0 or od > 12.0 or tt > tlim:
                    tau[j, i] = od
                    continue
                prev = tt
            for k in range(240):
                x = ox + dx * tt; y = oy + dy * tt; z = oz + dz * tt
                c = _cloud_h(x, y, t, q, p)
                h = z - c
                if h < 0:
                    found = True
                    break
                if z > top_w and dz >= 0:
                    break
                prev = tt
                st = max(1.5, max(h / (abs(dz) + .6), tt * .003))
                if wrho > 0 and h < 4.0 * ww:
                    st = min(st, max(2.0, ww * .7 + tt * .002))
                    rho = wrho * math.exp(-h / ww)
                    rho *= max(0.0, .55 + 1.1 * T.perlin(x / wl + 7.7 - t * .05, y / wl - 3.3, p))
                    od += rho * min(st, tlim - tt)
                tt += st
                if tt > tlim:
                    break
            tau[j, i] = od
            if not found:
                continue
            lo = prev; hi = tt
            for k in range(12):
                mid = .5 * (lo + hi)
                x = ox + dx * mid; y = oy + dy * mid; z = oz + dz * mid
                if z - _cloud_h(x, y, t, q, p) < 0:
                    hi = mid
                else:
                    lo = mid
            th = hi
            x = ox + dx * th; y = oy + dy * th
            # 法线的差分步长随距离变大（远处自然滤掉细节，不闪）
            e = max(2.0, th * .0018)
            c0 = _cloud_h(x, y, t, q, p)
            cx1 = _cloud_h(x + e, y, t, q, p); cx0 = _cloud_h(x - e, y, t, q, p)
            cy1 = _cloud_h(x, y + e, t, q, p); cy0 = _cloud_h(x, y - e, t, q, p)
            gx = (cx1 - cx0) / (2 * e); gy = (cy1 - cy0) / (2 * e)
            nz = 1.0 / math.sqrt(1 + gx * gx + gy * gy)
            nzs[j, i] = nz; nxs[j, i] = -gx * nz; nys[j, i] = -gy * nz
            hit[j, i] = th
            # 朝太阳方向在云顶上方前进，若被更高的云顶挡住则进入阴影（软）
            occ = 0.0
            sx = x; sy = y; sz = c0 + 1.0
            for k in range(shade_steps):
                d = shade_len * ((k + 1) / shade_steps) ** 1.5
                qx = sx + sdx * d; qy = sy + sdy * d; qz = sz + sdz * d
                ch = _cloud_h(qx, qy, t, q, p)
                if ch > qz:
                    occ += min(1.0, (ch - qz) / 35.0)
            vis[j, i] = math.exp(-occ * .8)
            # 缝隙遮蔽：比周围平均低的地方更暗（两个尺度）
            a_ = 0.0
            for r in (max(35.0, th * .005), max(120.0, th * .015)):
                av = (_cloud_h(x + r, y, t, q, p) + _cloud_h(x - r, y, t, q, p)
                      + _cloud_h(x, y + r, t, q, p) + _cloud_h(x, y - r, t, q, p)) * .25
                a_ += max(0.0, av - c0) / (r * .9 + 60.0)
            ao[j, i] = math.exp(-a_ * 1.2)
    return hit, nxs, nys, nzs, vis, ao, tau


@njit(parallel=True, cache=True, fastmath=True)
def heights_at(xs, ys, t, q, p):
    out = np.empty(xs.shape)
    for j in prange(xs.shape[0]):
        for i in range(xs.shape[1]):
            out[j, i] = _cloud_h(xs[j, i], ys[j, i], t, q, p)
    return out


def top_of(C):
    return (C.get('base', 4800.0) + 1.3 * abs(C.get('a1', 180.0)) + 1.7 * abs(C.get('a2', 140.0)) + 1.6 * abs(C.get('a3', 0.0))
            + 1.5 * abs(C.get('a4', 0.0)) + abs(C.get('micro', 0.0)) + 5.0)


def cloud_top(xs, ys, t, C):
    return heights_at(xs.astype(np.float64), ys.astype(np.float64), float(t), params(C), _P)


def render(cam, W, H, dist_terrain, t, C, sky_amb, sun_dir, sun_rgb):
    """返回 (颜色 HxWx3 线性, 命中距离 HxW（未命中 -1）, 絮状薄雾的透过率 HxW, 薄雾颜色 HxWx3)。
    dist_terrain：每像素到地形的距离（天空为很大）。薄雾要叠在最终画面上（地形、天空、云都在它后面）。"""
    from post.sky import ray_dirs
    from scipy import ndimage
    d = ray_dirs(cam, W, H)
    sd = np.array(sun_dir, np.float64); sd = sd / np.linalg.norm(sd)
    hit, nx, ny, nz, vis, ao, tau = march(d, float(cam['loc'][0]), float(cam['loc'][1]), float(cam['loc'][2]),
                                          np.minimum(dist_terrain, C.get('tmax', 150000.0)).astype(np.float64), float(t),
                                          params(C), _P, sd[0], sd[1], max(sd[2], .02), int(C.get('shade_steps', 8)),
                                          C.get('shade_len', 900.0), top_of(C), C.get('wisp_w', 25.0),
                                          C.get('wisp_rho', 0.0), C.get('wisp_l', 260.0), C.get('rho_in', 0.0))
    wrap = C.get('wrap', .5)
    ndl = np.clip((nx * sd[0] + ny * sd[1] + nz * sd[2] + wrap) / (1 + wrap), 0, 1)
    cos_v = (d * sd).sum(-1)
    silver = np.clip(cos_v, 0, 1) ** 8 * C.get('silver', 1.5)
    sun_rgb = np.array(sun_rgb, np.float64)
    direct = C.get('sun_k', 1.0) * ndl * vis + silver * vis
    # 多次散射：被挡住的地方仍有从周围云体透过来的光（越深的缝越少）
    ms = C.get('ms', 0.0) * (1 - vis) * (.4 + .6 * ao)
    sky = C.get('amb', 1.0) * ao * (.55 + .45 * nz)
    col = sun_rgb[None, None, :] * (direct + ms)[..., None] + sky_amb * sky[..., None]
    col *= np.array(C.get('albedo', (.95, .96, 1.0)))
    # 体积感：近处柔化多、远处少（只在云内部混合）
    soft, near = C.get('soft', 1.6), C.get('soft_near', C.get('soft', 1.6))
    if soft > 0:
        m = (hit > 0).astype(np.float32)

        def blur(s_):
            cb = np.stack([ndimage.gaussian_filter(col[..., c] * m, s_) for c in range(3)], -1)
            return cb / np.maximum(ndimage.gaussian_filter(m, s_)[..., None], 1e-4)
        out = blur(soft)
        if near != soft:
            k = np.clip(1 - (hit - C.get('near_d0', 600.0)) / C.get('near_d1', 2500.0), 0, 1)[..., None]
            out = out * (1 - k) + blur(near) * k
        col = np.where(m[..., None] > 0, out, col)
    # 絮状薄雾：颜色 = 天光 + 阳光（朝太阳方向的前向散射更亮）
    trans = np.exp(-tau)
    fwd = 1.0 + C.get('wisp_fwd', 1.5) * np.clip(cos_v, 0, 1) ** 6
    # 往上看更亮、往下看更暗（在云里或贴着云顶时，光从上面来）
    updown = .85 + .3 * np.clip(d[..., 2] * 2.0 + .5, 0, 1)
    wcol = ((sun_rgb[None, None, :] * (C.get('sun_k', 1.0) * .55 * fwd)[..., None] + sky_amb * C.get('amb', 1.0))
            * updown[..., None] * np.array(C.get('albedo', (.95, .96, 1.0))))
    return col.astype(np.float32), hit.astype(np.float32), trans.astype(np.float32), wcol.astype(np.float32)
