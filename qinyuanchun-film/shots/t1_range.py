"""S1 地形：26km 雪岭。脊状多重分形 → 粒子水力侵蚀 → 热侵蚀 → 物理积雪层；外圈 120km 远山。"""
import sys
import numpy as np
from common import terrain as T


def main(cache, EXT=26000.0, N=2048):
    EXT, N = float(EXT), int(N)
    CELL = EXT / (N - 1)
    p = T.make_perm(1936)
    X, Y = T.grid(N, EXT)
    WX, WY = T.warp(X, Y, p, 1 / 7000, 1300)
    R = T.ridged_field(WX, WY, p, 1 / 12000, 7, 2.1, .5, 2.2)
    H = 2800 * (R / R.max()) ** 1.3 + 350 * T.fbm_field(X, Y, p, 1 / 20000, 3, 2.0, .5)
    H = H.astype(np.float32)
    H = T.erode(H, 2_600_000, 3, CELL, radius=2, erode_s=.5, deposit_s=.15, cap=6).astype(np.float32)
    H = T.thermal(H, CELL, 48, 10).astype(np.float32)
    H = (H + .2 * (H - T.blur(H, 3))).astype(np.float32)
    Hs, D = T.snow_layer(H, CELL, depth=14.0, lo=.25, hi=.5, talus=55, iters=80)
    S = np.clip((D - .4) / 1.6, 0, 1).astype(np.float32)
    # 外圈远山
    FE, FN = 240000.0, 1536
    FX, FY = T.grid(FN, FE)
    FWX, FWY = T.warp(FX, FY, p, 1 / 7000, 1300)
    FR = T.ridged_field(FWX, FWY, p, 1 / 12000, 6, 2.1, .5, 2.2)
    HF = (2800 * (FR / R.max()) ** 1.3 + 350 * T.fbm_field(FX, FY, p, 1 / 20000, 3, 2.0, .5)).astype(np.float32)
    inner = (np.abs(FX) < EXT / 2 - 500) & (np.abs(FY) < EXT / 2 - 500)
    HF[inner] -= 300
    HFs, DF = T.snow_layer(HF, FE / (FN - 1), depth=30.0, lo=.25, hi=.5, talus=45, iters=20)
    SF = np.clip((DF - .5) / 2, 0, 1).astype(np.float32)
    np.savez(cache, H=Hs, S=S, HF=HFs, SF=SF, FE=FE, EXT=EXT, N=N)


if __name__ == '__main__':
    main(*sys.argv[1:])
