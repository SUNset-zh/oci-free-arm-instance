"""后期飘雪：三维空间里的雪花（随镜头平铺的无限雪场），按真实透视投影到画面上。

- 雪花在一个以镜头为中心、边长 L 的立方体里循环平铺，随风飘落并带一点湍流摆动；靠近立方体边界的雪花淡出，避免“跳变”。
- 近处雪花处于焦外：按弥散圆画成柔和的大光斑（能量守恒：光斑越大越淡）；
- 快门期间的运动拉成短线（运动模糊）；
- 用深度图做遮挡：落在山体后面的雪花不画。
"""
import math
import os

os.environ.setdefault("NUMBA_THREADING_LAYER", "workqueue")

import numpy as np
from numba import njit


def flakes(n, L, seed=7):
    rng = np.random.default_rng(seed)
    p = rng.uniform(-L / 2, L / 2, (n, 3))
    ph = rng.uniform(0, 2 * math.pi, (n, 3))
    sz = rng.lognormal(0, .35, n)
    return p, ph, sz


def positions(p0, ph, t, cam_pos, L, wind, fall, sway, carry=(0.0, 0.0, 0.0)):
    """t 秒时各雪花的世界坐标（以镜头为中心平铺）。carry：雪场随镜头一起平移的量（见 render 的 follow）。"""
    drift = np.array([wind[0] * t, wind[1] * t, -fall * t]) + np.asarray(carry, np.float64)
    w = sway * np.stack([np.sin(t * .9 + ph[:, 0]), np.sin(t * .7 + ph[:, 1]), .3 * np.sin(t * 1.3 + ph[:, 2])], -1)
    q = p0 + drift + w
    c = np.array(cam_pos)
    return ((q - c + L / 2) % L) - L / 2 + c


@njit(cache=True)
def _splat(buf, depth, xs, ys, zs, x2, y2, rad, inten, W, H, soft=0):
    for k in range(xs.shape[0]):
        r = rad[k]
        # 沿运动方向分段画（运动模糊）
        dx = x2[k] - xs[k]; dy = y2[k] - ys[k]
        segs = max(1, int(math.sqrt(dx * dx + dy * dy) / max(r * .5, .5)) + 1)
        segs = min(segs, 40)
        a = inten[k] / segs
        for s in range(segs):
            u = s / max(segs - 1, 1) if segs > 1 else 0.0
            cx = xs[k] + dx * u; cy = ys[k] + dy * u
            x0 = int(cx - r - 1); x1 = int(cx + r + 2); y0 = int(cy - r - 1); y1 = int(cy + r + 2)
            if x1 < 0 or y1 < 0 or x0 >= W or y0 >= H:
                continue
            inv = 1.0 / (r * r)
            for yy in range(max(0, y0), min(H, y1)):
                for xx in range(max(0, x0), min(W, x1)):
                    d2 = ((xx + .5 - cx) ** 2 + (yy + .5 - cy) ** 2) * inv
                    if d2 < 1.0 and zs[k] < depth[yy, xx]:
                        # 焦外光斑：边缘略亮的圆盘（接近真实镜头的光斑），焦内：高斯点
                        wgt = (1.0 - d2) ** .35 if (r > 2.5 and soft == 0) else math.exp(-3.0 * d2)
                        buf[yy, xx] += a * wgt


def render(cam, W, H, depth, t, S, shutter=1 / 48.0):
    """返回雪层的辐亮度 (H,W) 标量（乘以雪花颜色后加到画面上），depth: 每像素到景物的距离（天空为很大）。
    S: n 数量, L 平铺边长(米), wind (vx,vy), fall 下落速度, sway 摆动幅度, size 雪花直径(米),
       focus 对焦距离(米), coc 弥散系数(像素·米), bright 亮度, near 最近距离, seed"""
    n = int(S.get('n', 12000)); L = S.get('L', 40.0)
    p0, ph, sz = flakes(n, L, S.get('seed', 7))
    loc = np.array(cam['loc'], np.float64)
    R = np.array(cam['rot'], np.float64)
    f = cam['lens'] / cam['sensor'] * max(W, H)
    loc1 = np.array(cam.get('loc_next', cam['loc']), np.float64)
    # 镜头高速飞行时（S1、S3 约 100~170 m/s），按真实 180° 快门，近处雪花会拉成几百像素的虚线，像雨。
    # shutter_k 缩短快门（拖影变短）；follow 让雪场随镜头平移一部分（雪花迎面扑来的速度变慢，是“飘”而不是“冲”）。
    k = S.get('shutter_k', 1.0)
    loc1 = loc + (loc1 - loc) * k
    shutter = shutter * k
    fol = S.get('follow', 0.0)
    loc0 = np.array(S.get('loc0', cam['loc']), np.float64)
    c0, c1 = fol * (loc - loc0), fol * (loc1 - loc0)

    def project(P, c):
        v = (P - c) @ R          # 世界 → 相机坐标（R 的列为相机轴）
        z = -v[:, 2]
        return W / 2 + v[:, 0] / np.maximum(z, 1e-3) * f, H / 2 - v[:, 1] / np.maximum(z, 1e-3) * f, z

    P0 = positions(p0, ph, t, loc, L, S.get('wind', (.6, .2)), S.get('fall', 1.2), S.get('sway', .25), c0)
    P1 = positions(p0, ph, t + shutter, loc, L, S.get('wind', (.6, .2)), S.get('fall', 1.2), S.get('sway', .25), c1)
    x0, y0, z0 = project(P0, loc)
    x1, y1, z1 = project(P1 + (loc - loc1), loc)      # 镜头自身的运动也会拉线
    near = S.get('near', .35)
    edge = np.clip((L / 2 - np.abs(P0 - loc).max(1)) / (L * .12), 0, 1)
    ok = (z0 > near) & (x0 > -200) & (x0 < W + 200) & (y0 > -200) & (y0 < H + 200) & (edge > 0)
    size_px = S.get('size', .012) * sz * f / np.maximum(z0, 1e-3)
    coc = S.get('coc', 30.0) * np.abs(1.0 / np.maximum(z0, 1e-3) - 1.0 / S.get('focus', 1e4))
    rad = np.maximum(np.maximum(size_px * .5, coc), .7)
    # 能量守恒：雪花的“截面”光通量 ∝ size_px²，摊到光斑面积 rad² 上
    inten = S.get('bright', 1.0) * (np.maximum(size_px, .7) ** 2) / (rad ** 2) * edge
    inten *= np.clip((z0 - near) / .5, 0, 1)
    buf = np.zeros((H, W), np.float64)
    _splat(buf, depth.astype(np.float64), x0[ok], y0[ok], z0[ok], x1[ok], y1[ok], rad[ok], inten[ok], W, H)
    return buf.astype(np.float32)
