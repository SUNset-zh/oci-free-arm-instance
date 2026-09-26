"""纯 numpy 的二维 Perlin 噪声（在 Blender 进程里用；numba 与 Blender 自带的 LLVM 不能共存）。"""
import numpy as np


def make_perm(seed):
    rng = np.random.default_rng(seed)
    p = rng.permutation(256)
    return np.concatenate([p, p])


_G = np.array([[1, 1], [-1, 1], [1, -1], [-1, -1], [1, 0], [-1, 0], [0, 1], [0, -1]], np.float64)


def perlin(x, y, p):
    x = np.asarray(x, np.float64); y = np.asarray(y, np.float64)
    xi = np.floor(x).astype(np.int64); yi = np.floor(y).astype(np.int64)
    xf = x - xi; yf = y - yi
    xi &= 255; yi &= 255
    u = xf ** 3 * (xf * (xf * 6 - 15) + 10); v = yf ** 3 * (yf * (yf * 6 - 15) + 10)

    def g(h, dx, dy):
        gg = _G[h & 7]
        return gg[..., 0] * dx + gg[..., 1] * dy
    aa = p[p[xi] + yi]; ab = p[p[xi] + yi + 1]; ba = p[p[xi + 1] + yi]; bb = p[p[xi + 1] + yi + 1]
    x1 = g(aa, xf, yf) + u * (g(ba, xf - 1, yf) - g(aa, xf, yf))
    x2 = g(ab, xf, yf - 1) + u * (g(bb, xf - 1, yf - 1) - g(ab, xf, yf - 1))
    return (x1 + v * (x2 - x1)) * 1.1


def fbm(x, y, p, freq=1.0, octaves=4, lac=2.0, gain=.5):
    out = np.zeros(np.broadcast(np.asarray(x), np.asarray(y)).shape)
    a = 1.0; f = freq
    for o in range(octaves):
        out += a * perlin(np.asarray(x) * f + o * 17.3, np.asarray(y) * f - o * 9.1, p)
        a *= gain; f *= lac
    return out
