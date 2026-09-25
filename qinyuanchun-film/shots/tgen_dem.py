"""真实地形生成（子进程运行，结果缓存为 npz）。

    python3 shots/tgen_dem.py cache.npz spec.json

spec = {
  "lon": .., "lat": ..,               # 本地坐标原点
  "cam": [x, y],                      # 地球曲率以此为切点（通常取镜头中心）
  "levels": [                         # 第 0 级最精细；后面各级覆盖更大范围，内部被上一级覆盖的部分下沉
     {"ex": 12000, "ey": 20000, "cell": 7, "zoom": 13, "cx": 0, "cy": 0,
      "detail": {"noise": 2.5, "drops_per_cell": .6, "talus": 44},
      "snow": {"depth": 10, "lo": .3, "hi": .55, "talus": 50, "iters": 60}},
     {"ex": 90000, "ey": 90000, "cell": 60, "zoom": 11, "snow": {...}}, ...
  ]
}
输出：H0,S0,A0.. 各级高度（含积雪）、积雪遮罩、凹度；EX0,EY0,CX0,CY0.. 各级范围与中心。
"""
import json
import sys

import numpy as np
from scipy import ndimage

from common import dem
from common import terrain as T


def despike(H, thresh=45.0):
    """去掉 SRTM 空洞填补留下的尖刺与深坑。"""
    med = ndimage.median_filter(H, size=5)
    bad = np.abs(H - med) > thresh
    return np.where(bad, med, H).astype(np.float32), int(bad.sum())


def concavity(H, cell, r):
    """局部凹凸：正 = 凹（沟、坑），负 = 凸（脊）。以米计。"""
    return (T.blur(H, r) - H).astype(np.float32)


def terrace(H, cell, p, step=45.0, amount=.8, slope0=.7, slope1=1.2, warp=.6, dip=.06, dip_az=40.0, seed=3):
    """岩层台阶：陡坡上把高程量化成一级级台阶（短而陡的崖 + 平缓的台面）。
    层厚随机（0.4~1.8 倍 step），岩层整体倾斜（dip）并随噪声起伏，避免“千层糕”式的规整条纹。
    积雪会停在台面上，崖壁露岩——远看就是一条条断续的岩带。"""
    ny, nx = H.shape
    X, Y = np.meshgrid(np.arange(nx) * cell, np.arange(ny) * cell)
    n1 = T.fbm_field(X * 1.0, Y * 1.0, p, 1 / 900.0, 4, 2.0, .5)
    gy, gx = np.gradient(H, cell)
    sl = np.hypot(gx, gy)
    n2 = T.fbm_field(X + 377.0, Y - 91.0, p, 1 / 400.0, 3, 2.0, .5)
    m = np.clip((sl - slope0) / (slope1 - slope0), 0, 1) * np.clip(amount + .5 * n2, 0, 1)
    a = np.radians(dip_az)
    He = H + warp * step * n1 + dip * (X * np.sin(a) + Y * np.cos(a))      # 倾斜、起伏的“地层坐标”
    rng = np.random.default_rng(seed)
    lo, hi = float(He.min()) - step, float(He.max()) + step
    bounds = lo + np.cumsum(rng.uniform(.4, 1.8, int((hi - lo) / (step * .4)) + 4) * step)
    bounds = np.concatenate([[lo], bounds])
    k = np.clip(np.searchsorted(bounds, He) - 1, 0, len(bounds) - 2)
    b0, b1 = bounds[k], bounds[k + 1]
    f = (He - b0) / (b1 - b0)
    # 每层：前 55% 是缓台（原坡度的 1/4），后 45% 是陡崖
    g = np.clip(f * .25 + np.clip((f - .55) / .45, 0, 1) ** 1.5 * .75, 0, 1)
    Ht = b0 + g * (b1 - b0) - (He - H)
    return (H + (Ht - H) * m).astype(np.float32)


def amplify(H, cell, p, noise=2.5, drops=0, talus=42.0, seed=1):
    """给插值出来的平滑高程补上细节：随坡度增强的脊状噪声 → 粒子水力侵蚀 → 热侵蚀。"""
    ny, nx = H.shape
    X, Y = np.meshgrid(np.arange(nx) * cell, np.arange(ny) * cell)
    gy, gx = np.gradient(H, cell)
    slope = np.hypot(gx, gy)
    k = np.clip((slope - .15) / .7, 0.0, 1.2).astype(np.float32)   # 陡处粗糙，平处（冰川、河谷）保持光滑
    r1 = T.ridged_field(X, Y, p, 1 / 90.0, 4, 2.1, .5, 2.0)
    r1 = (r1 - r1.mean()) / (r1.std() + 1e-6)
    f1 = T.fbm_field(X + 91.7, Y - 13.3, p, 1 / 35.0, 3, 2.0, .5)
    H = (H + noise * k * (r1 + .5 * f1)).astype(np.float32)
    if drops:
        H = T.erode(H, int(drops), seed, cell, radius=2, erode_s=.35, deposit_s=.2, cap=5).astype(np.float32)
    return T.thermal(H, cell, talus, 6).astype(np.float32)


def smax(a, b, k):
    """平滑最大值（多项式），k 为过渡宽度（米）。"""
    h = np.clip(.5 + .5 * (a - b) / k, 0, 1)
    return a * h + b * (1 - h) + k * h * (1 - h)


def add_peak(H, X, Y, pk, p):
    """在真实地形上“长”出一座金字塔形主峰：几个平面坡面相交成刃脊，坡面上陡下缓（冰斗形），
    域扭曲让刃脊弯折，脊状噪声给出次级山脊与锯齿。与原地形做平滑最大值融合。"""
    cx, cy = pk['x'], pk['y']
    WX, WY = T.warp((X - cx).astype(np.float64), (Y - cy).astype(np.float64), p, 1 / pk.get('warp_l', 3500.0), pk.get('warp', 450.0))
    d = np.full(X.shape, -1e9, np.float64)
    for k, (az, A, L, s2) in enumerate(pk['faces']):
        a = np.radians(az)
        dk = WX * np.sin(a) + WY * np.cos(a)
        Fk = A * (1 - np.exp(-np.maximum(dk, 0) / L)) + s2 * np.maximum(dk, 0)
        # 用“下降量”的最大值来组合：哪一面降得最多就取哪一面，面与面之间形成尖锐的脊
        d = np.maximum(d, Fk)
    Hp = pk['h0'] - d
    R = T.ridged_field(WX, WY, p, 1 / pk.get('rough_l', 1600.0), 5, 2.1, .5, 2.0)
    R = (R - R.mean()) / (R.std() + 1e-6)
    rel = np.clip(d / 2500.0, 0, 1) * np.clip((pk['h0'] - Hp) / 300.0, 0, 1)   # 峰顶附近保持干净的尖顶
    Hp = Hp + pk.get('rough', 90.0) * R * rel
    return smax(H.astype(np.float64), Hp, pk.get('blend', 180.0)).astype(np.float32)


def surface(Hs, S, A, cell, X, Y, p, mat):
    """把原先在着色器里逐像素算的大尺度图案（≥ 网格间距）预先算到顶点上：
    snow = 积雪覆盖（模拟积雪 ∪ 坡度+凹槽规则，带打散噪声）；rockv = 岩石色相/明暗变化。"""
    nxv, nyv, nz = T.normals(Hs, cell)
    b1 = T.fbm_field(X, Y, p, 1 / 70.0, 3, 2.0, .5) * .5
    b2 = T.fbm_field(X + 51.0, Y + 17.0, p, 1 / 14.0, 3, 2.0, .5) * .5
    sl = nz + mat.get('flute', .09) * np.clip(A, -4, 6) + b1 * mat.get('n1', .22)
    lo, hi = mat.get('slope_lo', .42), mat.get('slope_hi', .6)
    cov = np.clip((sl - lo) / (hi - lo), 0, 1)
    cov = cov * cov * (3 - 2 * cov)
    sv = np.maximum(S, cov) + b2 * mat.get('n2', .2) + mat.get('cover', 0.0)
    snow = np.clip((sv - .4) / .2, 0, 1)
    snow = snow * snow * (3 - 2 * snow)
    g = T.fbm_field(X - 9.0, Y + 33.0, p, 1 / 500.0, 3, 2.0, .5) * .5
    g2 = T.fbm_field(X + 7.0, Y - 5.0, p, 1 / 25.0, 3, 2.0, .5) * .5
    rockv = np.clip(.5 + g + .4 * g2, 0, 1)
    return snow.astype(np.float32), rockv.astype(np.float32)


def level_dims(L):
    ex = float(L.get('ex', L.get('extent')))
    ey = float(L.get('ey', L.get('extent')))
    if 'cell' in L:
        nx = int(round(ex / L['cell'])) + 1; ny = int(round(ey / L['cell'])) + 1
    else:
        nx = ny = int(L['n'])
    return ex, ey, nx, ny


def sample_grid(A, ex, ey, cx, cy, X, Y, order=3):
    """在另一套网格坐标 (X, Y) 上采样数组 A（覆盖 cx±ex/2, cy±ey/2）。"""
    ny, nx = A.shape
    fi = (X - (cx - ex / 2)) / ex * (nx - 1)
    fj = (Y - (cy - ey / 2)) / ey * (ny - 1)
    return ndimage.map_coordinates(A, [fj, fi], order=order, mode='nearest').astype(np.float32)


def main(cache, spec_path):
    spec = json.load(open(spec_path))
    lon, lat = spec['lon'], spec['lat']
    ox, oy = spec.get('cam', [0, 0])
    p = T.make_perm(spec.get('seed', 1936))
    levels = spec['levels']
    res = {}
    # 从最粗的一级算起；细一级在边缘一圈过渡到粗一级的结果，保证接缝处严丝合缝
    for li in reversed(range(len(levels))):
        L = levels[li]
        ex, ey, nx, ny = level_dims(L)
        z = int(L['zoom'])
        cx, cy = float(L.get('cx', 0)), float(L.get('cy', 0))
        cell = ex / (nx - 1)
        X, Y = np.meshgrid(np.linspace(cx - ex / 2, cx + ex / 2, nx), np.linspace(cy - ey / 2, cy + ey / 2, ny))
        H = dem.local(lon, lat, (ex, ey), (nx, ny), z, cx, cy)
        H, nbad = despike(H, L.get('despike', 45.0) * max(1.0, cell / 15.0))
        H = (H * L.get('vexag', 1.0) + L.get('zshift', 0.0)).astype(np.float32)
        if 'peak' in spec:
            H = add_peak(H, X, Y, spec['peak'], p)
        print(f'level {li}: {ex / 1000:.1f}x{ey / 1000:.1f} km, {nx}x{ny}, cell {cell:.1f} m, despiked {nbad}', flush=True)
        if 'terrace' in L:
            H = terrace(H, cell, p, **L['terrace'])
        if 'detail' in L:
            d = L['detail']
            drops = d.get('drops', d.get('drops_per_cell', 0) * nx * ny)
            H = amplify(H, cell, p, d.get('noise', 2.5), drops, d.get('talus', 42.0), seed=li + 1)
        H = dem.curve(H, (ex, ey), cx, cy, ox, oy)
        sn = L.get('snow', {})
        Hs, D = T.snow_layer(H, cell, depth=sn.get('depth', 8.0), lo=sn.get('lo', .3), hi=sn.get('hi', .55),
                             talus=sn.get('talus', 50), iters=sn.get('iters', 40))
        S = np.clip((D - sn.get('d0', .3)) / sn.get('d1', 1.5), 0, 1).astype(np.float32)
        A = concavity(H, cell, max(1, int(round(30 / cell))))
        S, RV = surface(Hs, S, A, cell, X, Y, p, spec.get('mat', {}))
        if li + 1 < len(levels):
            Hc, Sc, Ac, RVc, cex, cey, ccx, ccy, ccell = res[li + 1]
            band = max(20 * cell, 6 * ccell)
            dist = np.minimum(ex / 2 - np.abs(X - cx), ey / 2 - np.abs(Y - cy))
            w = np.clip(1 - dist / band, 0, 1)
            w = (w * w * (3 - 2 * w)).astype(np.float32)
            Hs = Hs * (1 - w) + sample_grid(Hc, cex, cey, ccx, ccy, X, Y, 1) * w
            S = S * (1 - w) + sample_grid(Sc, cex, cey, ccx, ccy, X, Y, 1) * w
            A = A * (1 - w) + sample_grid(Ac, cex, cey, ccx, ccy, X, Y, 1) * w
            RV = RV * (1 - w) + sample_grid(RVc, cex, cey, ccx, ccy, X, Y, 1) * w
        res[li] = (Hs.astype(np.float32), S.astype(np.float32), A.astype(np.float32), RV.astype(np.float32), ex, ey, cx, cy, cell)
    out = {}
    for li in range(len(levels)):
        Hs, S, A, RV, ex, ey, cx, cy, cell = res[li]
        if li > 0:
            # 被细一级覆盖的区域下沉：边界处先下沉几米（避免共面闪烁），往里再整体下沉
            _, _, _, _, pex, pey, pcx, pcy, _ = res[li - 1]
            ny, nx = Hs.shape
            X, Y = np.meshgrid(np.linspace(cx - ex / 2, cx + ex / 2, nx), np.linspace(cy - ey / 2, cy + ey / 2, ny))
            dist = np.minimum(pex / 2 - np.abs(X - pcx), pey / 2 - np.abs(Y - pcy))
            drop = .6 * np.clip(dist / (2 * cell), 0, 1) + 400 * np.clip((dist - 4 * cell) / cell, 0, 1)
            Hs = (Hs - drop).astype(np.float32)
        out[f'H{li}'] = Hs; out[f'S{li}'] = S; out[f'A{li}'] = A; out[f'R{li}'] = RV
        out[f'EX{li}'] = ex; out[f'EY{li}'] = ey; out[f'CX{li}'] = cx; out[f'CY{li}'] = cy
    out['NL'] = len(levels)
    np.savez(cache, **out)
    print('saved', cache, flush=True)


if __name__ == '__main__':
    main(*sys.argv[1:])
