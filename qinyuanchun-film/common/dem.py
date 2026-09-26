"""真实地形：从 AWS Open Data 的 Terrarium 高程瓦片（SRTM 30 m 等）取数据，重采样到以某点为中心的本地米制网格。

    H = dem.local(lon0, lat0, extent_m, n, zoom)      # H[j, i]，行 j 向北，列 i 向东，单位米
    H = dem.curve(H, extent_m)                         # 叠加地球曲率（含大气折射），远景地平线才对

高程 = R*256 + G + B/256 - 32768
"""
import math
import os
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PIL import Image

URL = 'https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png'
CACHE = os.environ.get('DEM_CACHE', '/tmp/claude-0/-home-user-oci-free-arm-instance/33674d5b-35e4-5b5a-b79d-ec7ad6b62fa3/scratchpad/dem_cache')
R_EARTH = 6371008.8
R_EFF = R_EARTH / (1 - 0.13)          # 标准大气折射系数 k=0.13


def tile_xy(lon, lat, z):
    """经纬度 -> 该缩放级别下的全局像素坐标（每瓦片 256 像素）。"""
    n = 2 ** z
    x = (lon + 180.0) / 360.0 * n
    la = np.radians(lat)
    y = (1.0 - np.log(np.tan(la) + 1.0 / np.cos(la)) / math.pi) / 2.0 * n
    return x * 256.0, y * 256.0


def _fetch(z, x, y):
    path = os.path.join(CACHE, str(z), str(x), f'{y}.png')
    if not os.path.exists(path):
        import urllib.request
        os.makedirs(os.path.dirname(path), exist_ok=True)
        for attempt in range(4):
            try:
                with urllib.request.urlopen(URL.format(z=z, x=x, y=y), timeout=60) as r:
                    data = r.read()
                with open(path + '.part', 'wb') as f:
                    f.write(data)
                os.replace(path + '.part', path)
                break
            except Exception:
                if attempt == 3:
                    raise
    a = np.asarray(Image.open(path).convert('RGB')).astype(np.float64)
    return a[..., 0] * 256 + a[..., 1] + a[..., 2] / 256 - 32768


def mosaic(px0, py0, px1, py1, z):
    """取覆盖全局像素矩形的所有瓦片并拼接。返回 (高程, 左上角全局像素坐标)。"""
    tx0, ty0 = int(px0 // 256) - 1, int(py0 // 256) - 1
    tx1, ty1 = int(px1 // 256) + 1, int(py1 // 256) + 1
    jobs = [(z, x, y) for y in range(ty0, ty1 + 1) for x in range(tx0, tx1 + 1)]
    with ThreadPoolExecutor(8) as ex:
        tiles = list(ex.map(lambda a: _fetch(*a), jobs))
    W, Hh = (tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256
    M = np.empty((Hh, W), np.float64)
    k = 0
    for y in range(ty0, ty1 + 1):
        for x in range(tx0, tx1 + 1):
            M[(y - ty0) * 256:(y - ty0 + 1) * 256, (x - tx0) * 256:(x - tx0 + 1) * 256] = tiles[k]
            k += 1
    return M, tx0 * 256, ty0 * 256


def _cubic(M, fx, fy):
    """Catmull-Rom 双三次插值。"""
    ix = np.floor(fx).astype(np.int64); iy = np.floor(fy).astype(np.int64)
    tx = fx - ix; ty = fy - iy

    def w(t):
        return [((-t + 2) * t - 1) * t / 2, ((3 * t - 5) * t * t + 2) / 2, ((-3 * t + 4) * t + 1) * t / 2, (t - 1) * t * t / 2]

    wx = w(tx); wy = w(ty)
    out = np.zeros(fx.shape, np.float64)
    for m in range(4):
        row = np.clip(iy - 1 + m, 0, M.shape[0] - 1)
        acc = np.zeros(fx.shape, np.float64)
        for k in range(4):
            col = np.clip(ix - 1 + k, 0, M.shape[1] - 1)
            acc += wx[k] * M[row, col]
        out += wy[m] * acc
    return out


def local(lon0, lat0, extent, n, z, cx=0.0, cy=0.0):
    """以 (lon0, lat0) 为原点的本地东-北米制网格，覆盖 [cx±ex/2, cy±ey/2]。
    extent 可为数或 (ex, ey)；n 可为数或 (nx, ny)。返回 H[ny, nx]。"""
    ex, ey = (extent, extent) if np.isscalar(extent) else extent
    nx, ny = (n, n) if np.isscalar(n) else n
    xs = np.linspace(cx - ex / 2, cx + ex / 2, nx)
    ys = np.linspace(cy - ey / 2, cy + ey / 2, ny)
    X, Y = np.meshgrid(xs, ys)
    lat = lat0 + np.degrees(Y / R_EARTH)
    lon = lon0 + np.degrees(X / (R_EARTH * np.cos(np.radians(lat))))
    px, py = tile_xy(lon, lat, z)
    M, ox, oy = mosaic(px.min(), py.min(), px.max(), py.max(), z)
    H = _cubic(M, px - ox, py - oy)
    return H.astype(np.float32)


def curve(H, extent, cx=0.0, cy=0.0, ox=0.0, oy=0.0):
    """减去地球曲率下沉量 d²/(2R_eff)，d 为到 (ox, oy)（通常是机位）的水平距离。"""
    ex, ey = (extent, extent) if np.isscalar(extent) else extent
    ny, nx = H.shape
    X, Y = np.meshgrid(np.linspace(cx - ex / 2, cx + ex / 2, nx), np.linspace(cy - ey / 2, cy + ey / 2, ny))
    return (H - ((X - ox) ** 2 + (Y - oy) ** 2) / (2 * R_EFF)).astype(np.float32)


def hillshade(H, cell, az=315, alt=35, exag=1.0):
    gy, gx = np.gradient(H * exag, cell)
    a, e = np.radians(az), np.radians(alt)
    lx, ly, lz = np.sin(a) * np.cos(e), np.cos(a) * np.cos(e), np.sin(e)
    nz = 1 / np.sqrt(1 + gx * gx + gy * gy)
    return np.clip((-gx * lx - gy * ly + lz) * nz, 0, 1)


def preview(H, cell, path, marks=()):
    """地形预览：分层设色 + 山体阴影，行 0 在图片底部（北向上）。"""
    hs = hillshade(H, cell)
    lo, hi = np.percentile(H, 1), np.percentile(H, 99.5)
    t = np.clip((H - lo) / (hi - lo + 1e-9), 0, 1)
    stops = np.array([[.20, .35, .25], [.55, .60, .40], [.70, .55, .40], [.60, .55, .55], [1, 1, 1]])
    idx = t * (len(stops) - 1)
    i0 = np.clip(idx.astype(int), 0, len(stops) - 2)
    f = (idx - i0)[..., None]
    col = stops[i0] * (1 - f) + stops[i0 + 1] * f
    img = col * (.35 + .75 * hs[..., None])
    img = (np.clip(img, 0, 1) ** (1 / 1.1) * 255).astype(np.uint8)[::-1]
    im = Image.fromarray(img)
    if marks:
        from PIL import ImageDraw
        d = ImageDraw.Draw(im)
        n = H.shape[0]
        for (i, j, label) in marks:
            y = n - 1 - j
            d.ellipse([i - 5, y - 5, i + 5, y + 5], outline=(255, 0, 0), width=2)
            d.text((i + 7, y - 7), label, fill=(255, 0, 0))
    im.save(path)
