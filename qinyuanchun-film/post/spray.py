"""马蹄踢起的雪粉：沿每匹马的轨迹按固定频率“发射”雪粉团（确定性随机，任意一帧可单独计算），
受重力和空气阻力，团块逐渐扩散变淡；逆光下是一团团发亮的雪雾。"""
import math

import numpy as np

from post import snow as SN


def render(cam, W, H, depth, t, S, fps=24.0):
    tracks = S['tracks']                 # {马: [[x,y,z], ...] 每帧}
    rate, life = S.get('rate', 80), S.get('life', 1.5)
    R = np.array(cam['rot'], np.float64); loc = np.array(cam['loc'], np.float64)
    f = cam['lens'] / cam['sensor'] * max(W, H)
    xs, ys, zs, rad, inten = [], [], [], [], []
    for hk, tr in tracks.items():
        tr = np.asarray(tr, np.float64)
        n = len(tr)
        i1 = int(math.floor(t * rate)); i0 = int(math.ceil((t - life) * rate))
        idx = np.arange(max(i0, 0), i1 + 1)
        if len(idx) == 0:
            continue
        te = idx / rate
        fr = np.clip(te * fps, 0, n - 1.001)
        a = np.floor(fr).astype(int); u = (fr - a)[:, None]
        pe = tr[a] * (1 - u) + tr[np.minimum(a + 1, n - 1)] * u
        vh = (tr[np.minimum(a + 1, n - 1)] - tr[a]) * fps
        rng = np.random.default_rng(abs(hash(hk)) % (2 ** 31) + idx[:, None] * 0)
        r = np.random.default_rng((int(hk) + 1) * 7919)
        rr = r.uniform(-1, 1, (int(life * rate) * 4 + i1 + 10, 5))[idx]
        tau = (t - te)[:, None]
        # 初速度：向后、向上、横向散开；相对于马的速度（马在跑，雪粉留在原地附近）
        v0 = np.stack([rr[:, 0] * S.get('spread', 1.5), rr[:, 1] * S.get('spread', 1.5), S.get('up', 2.0) * (.6 + .4 * (rr[:, 2] + 1))], 1)
        k = S.get('drag', 1.8)
        disp = v0 * (1 - np.exp(-k * tau)) / k + np.array([0, 0, -1.2]) * tau ** 2 * .5
        # 从后蹄处发射：沿马的运动方向往后退一点
        hd = vh / np.maximum(np.linalg.norm(vh, axis=1, keepdims=True), 1e-3)
        p = pe - hd * S.get('back', 1.3) + np.stack([rr[:, 3] * .5, rr[:, 4] * .5, np.full(len(idx), .1)], 1) + disp
        v = (p - loc) @ R
        z = -v[:, 2]
        ok = z > .5
        sx = W / 2 + v[:, 0] / np.maximum(z, 1e-3) * f; sy = H / 2 - v[:, 1] / np.maximum(z, 1e-3) * f
        puff = S.get('size', .05) + S.get('grow', .25) * tau[:, 0]
        age = np.clip(1 - tau[:, 0] / life, 0, 1)
        xs.append(sx[ok]); ys.append(sy[ok]); zs.append(z[ok]); rad.append((puff * f / np.maximum(z, 1e-3))[ok])
        inten.append((S.get('bright', .8) * age ** 1.5 * np.clip(tau[:, 0] / .08, 0, 1))[ok])
    if not xs:
        return np.zeros((H, W), np.float32)
    xs, ys, zs, rad, inten = [np.concatenate(a) for a in (xs, ys, zs, rad, inten)]
    rad = np.maximum(rad, .8)
    buf = np.zeros((H, W), np.float64)
    SN._splat(buf, depth.astype(np.float64), xs, ys, zs, xs, ys, rad, inten * .35, W, H, 1)
    return buf.astype(np.float32)
