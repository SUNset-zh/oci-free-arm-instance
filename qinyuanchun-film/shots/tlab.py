"""地形实验：不同锐度/侵蚀参数的对比。"""
import sys
import numpy as np
from common import terrain as T

def main(cache, variant, EXT=16000.0, N=1536):
    EXT, N = float(EXT), int(N); CELL = EXT / (N - 1)
    p = T.make_perm(1936)
    X, Y = T.grid(N, EXT)
    WX, WY = T.warp(X, Y, p, 1 / 6000, 1100)
    v = variant
    if v == 'A':   # 尖锐脊 + 峰值幂次
        R = T.ridged_field(WX, WY, p, 1 / 5000, 8, 2.1, .5, 2.6)
        H = 3200 * (R / R.max()) ** 1.5
    elif v == 'B':  # A + 强侵蚀 + 锐化
        R = T.ridged_field(WX, WY, p, 1 / 5000, 8, 2.1, .5, 2.6)
        H = 3200 * (R / R.max()) ** 1.5
    elif v == 'C':  # 更大起伏的主峰群
        R = T.ridged_field(WX, WY, p, 1 / 4200, 8, 2.1, .52, 3.0)
        H = 3600 * (R / R.max()) ** 1.8
    elif v == 'D':
        R = T.ridged_field(WX, WY, p, 1 / 5200, 8, 2.1, .5, 2.2)
        H = 2300 * (R / R.max()) ** 1.25 + 300 * T.fbm_field(X, Y, p, 1 / 14000, 3, 2.0, .5)
    elif v in ('F', 'G'):
        R = T.ridged_field(WX, WY, p, 1 / 5200, 7, 2.1, .5, 2.3)
        H = 2500 * (R / R.max()) ** 1.3 + 300 * T.fbm_field(X, Y, p, 1 / 14000, 3, 2.0, .5)
    elif v == 'E':
        R = T.ridged_field(WX, WY, p, 1 / 5200, 8, 2.1, .5, 2.4)
        H = 2600 * (R / R.max()) ** 1.35 + 300 * T.fbm_field(X, Y, p, 1 / 14000, 3, 2.0, .5)
    H = H.astype(np.float32)
    if v in ('B', 'C', 'D', 'E', 'F', 'G'):
        H = T.erode(H, 2_200_000, 3, CELL, radius=2, erode_s=.5, deposit_s=.15, cap=6).astype(np.float32)
        H = T.thermal(H, CELL, 52, 6).astype(np.float32)
        H = (H + .5 * (H - T.blur(H, 3))).astype(np.float32)
    if v in ('F', 'G'):
        dep = 8.0 if v == 'F' else 14.0
        H, D = T.snow_layer(H, CELL, depth=dep, lo=.3, hi=.55, talus=45 if v == 'F' else 50, iters=80)
        S = np.clip((D - .4) / 1.6, 0, 1).astype(np.float32)
    else:
        S = T.snow_mask(H, CELL, p, slope_lo=.4, slope_hi=.55)
    np.savez(cache, H=H, S=S, EXT=EXT)

if __name__ == '__main__':
    main(*sys.argv[1:])
