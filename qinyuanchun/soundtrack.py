#!/usr/bin/env python3
"""为《沁园春·雪》水墨动画合成配乐（纯 numpy）。

    python3 soundtrack.py out/events.json out/soundtrack.wav

古筝（Karplus-Strong 拨弦）+ 弦乐铺底 + 风声 + 大鼓，全部用五声音阶：
开头风雪清冷（羽调），红日出时刮奏转入明亮的宫调，成吉思汗段鼓声渐起，“还看今朝”时全曲铺满。
"""
import json
import sys
import wave

import numpy as np

SR = 48000
DUR = 60.0
N = int(SR * DUR)
rng = np.random.default_rng(1936)


def midi(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def ts(length):
    return np.arange(int(length * SR)) / SR


def add(buf, sig, t, pan=0.0, gain=1.0):
    i = int(t * SR)
    if i >= N or i < 0:
        return
    sig = sig[: N - i] * gain
    l, r = np.cos((pan + 1) * np.pi / 4), np.sin((pan + 1) * np.pi / 4)
    buf[0, i:i + len(sig)] += sig * l
    buf[1, i:i + len(sig)] += sig * r


def zheng(freq, dur=3.0, damp=.9965, bright=.6):
    """Karplus-Strong 拨弦，按周期分块向量化。"""
    P = max(2, int(round(SR / freq)))
    n = int(dur * SR)
    y = np.zeros(n + P + 1)
    exc = rng.uniform(-1, 1, P + 1)
    for _ in range(int((1 - bright) * 4)):  # 激励低通，控制亮度
        exc[1:] = .5 * (exc[1:] + exc[:-1])
    y[:P + 1] = exc
    k = P + 1
    while k < len(y):
        e = min(k + P, len(y))
        y[k:e] = damp * .5 * (y[k - P:e - P] + y[k - P - 1:e - P - 1])
        k = e
    out = y[P + 1:P + 1 + n]
    out[:int(.002 * SR)] *= np.linspace(0, 1, int(.002 * SR))
    rel = int(.05 * SR)
    out[-rel:] *= np.linspace(1, 0, rel)
    return out / (np.abs(out).max() + 1e-9)


def noise_band(length, lo, hi):
    n = int(length * SR)
    spec = np.fft.rfft(rng.standard_normal(n))
    f = np.fft.rfftfreq(n, 1 / SR)
    spec *= (f > lo) & (f < hi)
    x = np.fft.irfft(spec, n)
    return x / (np.abs(x).max() + 1e-9)


def pad(notes, length, attack=2.0, release=2.0):
    t = ts(length)
    env = np.minimum(1, t / attack) * np.clip((length - t) / release, 0, 1)
    out = np.zeros_like(t)
    for m in notes:
        f = midi(m)
        for d in (-.004, 0, .004):
            ph = 2 * np.pi * f * (1 + d) * t + rng.uniform(0, 6.28)
            out += np.sin(ph) + .35 * np.sin(2 * ph) + .15 * np.sin(3 * ph)
    vib = 1 + .08 * np.sin(2 * np.pi * .3 * t)
    return out * env * vib / (len(notes) * 3)


def reverb(x, seconds=3.2, mix=.35):
    n = int(seconds * SR)
    t = np.arange(n) / SR
    out = np.empty_like(x)
    for c in range(2):
        ir = rng.standard_normal(n) * np.exp(-t * 6.9 / seconds)
        ir[: int(.02 * SR)] = 0
        ir /= np.sqrt((ir ** 2).sum())
        size = 1 << int(np.ceil(np.log2(x.shape[1] + n)))
        wet = np.fft.irfft(np.fft.rfft(x[c], size) * np.fft.rfft(ir, size), size)[: x.shape[1]]
        out[c] = x[c] * (1 - mix) + wet * mix * 2.2
    return out


music = np.zeros((2, N))
events = json.load(open(sys.argv[1]))

# 五声音阶：D 宫（D E F# A B）
PENTA = [50, 52, 54, 57, 59, 62, 64, 66, 69, 71, 74, 76, 78, 81, 83, 86]

# ---------------- 风声（开头风雪） ----------------
wind = noise_band(26, 150, 1800)
wt = ts(26)
wenv = (.55 + .45 * np.sin(2 * np.pi * .13 * wt + 1) * np.sin(2 * np.pi * .07 * wt)) * np.minimum(1, wt / 2) * np.clip((24 - wt) / 5, 0, 1)
add(music, wind * wenv, 0, gain=.07)

# ---------------- 铺底 ----------------
add(music, pad([47, 54, 59], 10.0, 3, 2.5), 0.0, gain=.10)              # Bm 空五度，清冷
add(music, pad([43, 50, 55, 59], 7.0, 2, 2.5), 8.8, gain=.11)           # G
add(music, pad([47, 54, 59, 62], 7.5, 2, 2.5), 15.0, gain=.12)          # Bm
add(music, pad([38, 50, 57, 62, 66], 13.0, 1.2, 3), 22.2, gain=.14)     # D 大调，红日
add(music, pad([43, 50, 55, 59, 62], 8.0, 2, 3), 33.8, gain=.12)        # G
add(music, pad([45, 52, 57, 61, 64], 8.5, 2, 2.5), 40.8, gain=.14)      # A
add(music, pad([38, 50, 57, 62, 66, 69, 74], 12.5, 3.5, 4.5), 47.8, gain=.20)  # 还看今朝

# ---------------- 古筝旋律 ----------------
def phrase(t0, notes, step, gain=.12, pan=.15):
    t = t0
    for m, d in notes:
        if m is not None:
            add(music, zheng(midi(m), 3.2, damp=.997, bright=.65), t, pan=pan, gain=gain)
            if d >= 1.2:  # 长音加一点摇指
                for r in np.arange(.16, min(d, 1.0), .16):
                    add(music, zheng(midi(m), 1.0, damp=.994, bright=.5), t + r, pan=pan, gain=gain * .22)
        t += d * step

# 上阕：羽调，疏朗
phrase(1.0, [(71, 1.5), (None, .5), (66, 1), (69, 1.5), (64, 2)], .6, gain=.10)
phrase(3.4, [(71, 1), (74, 1), (71, 1), (69, 1.5), (66, 1.5), (64, 1), (66, 3)], .62)
phrase(9.4, [(59, 1), (62, 1), (64, 1), (66, 2), (69, 1), (66, 1), (64, 1), (62, 1), (59, 3)], .6)
phrase(15.3, [(66, 1), (69, 1), (71, 1), (74, 2), (76, 1), (74, 1), (71, 1), (69, 2), (74, 1), (76, 1), (78, 3)], .52)
# 下阕：宫调，明亮
phrase(22.9, [(74, 1), (78, 1), (81, 2), (78, 1), (76, 1), (74, 2), (76, 1), (78, 3)], .55, gain=.13)
phrase(28.4, [(81, 1.5), (78, .5), (76, 1), (74, 1), (76, 1), (78, 2), (74, 1), (71, 1), (74, 3)], .58, gain=.13)
phrase(34.4, [(69, 1.5), (None, .5), (66, 1), (64, 2), (None, 1), (69, 1.5), (None, .5), (71, 1), (69, 3)], .56, gain=.11)
phrase(41.4, [(62, 1), (64, 1), (69, 1), (71, 2), (74, 1), (76, 1), (78, 2), (81, 1), (83, 3)], .55, gain=.13)
phrase(49.0, [(86, 2), (83, 1), (81, 1), (78, 2), (81, 1), (83, 1), (86, 4), (None, 1), (81, 1), (86, 5)], .5, gain=.13)

# 低音根音
for t, m in [(0.2, 47), (3.2, 47), (9.2, 43), (12.0, 47), (15.2, 47), (18.6, 42), (22.2, 38), (25.2, 45), (28.2, 43), (31.1, 38),
             (34.2, 43), (37.6, 47), (41.2, 45), (44.6, 45), (48.2, 38), (52.4, 38), (56.0, 38)]:
    add(music, zheng(midi(m), 4.0, damp=.998, bright=.3), t, pan=-.2, gain=.16)

# ---------------- 刮奏 ----------------
for e in events:
    if e["type"] == "gliss":
        for i, m in enumerate(PENTA):
            add(music, zheng(midi(m), 2.5, damp=.996, bright=.7), e["t"] - .6 + i * .038, pan=-.4 + i * .05, gain=.07)

# ---------------- 印章：轻击 ----------------
for e in events:
    if e["type"] == "seal":
        x = ts(.6)
        wood = np.sin(2 * np.pi * 820 * x) * np.exp(-x * 30) + .5 * np.sin(2 * np.pi * 1650 * x) * np.exp(-x * 40)
        add(music, wood, e["t"] + .05, pan=-.3, gain=.10)
        add(music, zheng(midi(83), 2.0, bright=.8), e["t"] + .08, pan=-.3, gain=.05)

# ---------------- 大鼓：成吉思汗段渐强，今朝收束 ----------------
def drum(t, g):
    x = ts(1.2)
    body = np.sin(2 * np.pi * np.cumsum(52 + 50 * np.exp(-x * 14)) / SR) * np.exp(-x * 4.5)
    skin = noise_band(1.2, 60, 900) * np.exp(-x * 18)
    add(music, body + .4 * skin, t, gain=g)

bt = 41.3
while bt < 47.6:
    drum(bt, .22 + .25 * (bt - 41.3) / 6.3)
    bt += .8 if bt < 44.5 else .4
for t, g in [(48.2, .55), (52.4, .45), (56.0, .5)]:
    drum(t, g)

# 箭：一声破空
for e in events:
    if e["type"] == "arrow":
        n = .6
        env = np.exp(-ts(n) * 5) * np.minimum(1, ts(n) / .02)
        add(music, noise_band(n, 1500, 8000) * env, e["t"], pan=-.3, gain=.10)

mix = reverb(music, 3.4, .36)
fs = int(58.6 * SR)
mix[:, fs:] *= np.linspace(1, 0, N - fs) ** 1.4
mix /= np.abs(mix).max() / 0.89
with wave.open(sys.argv[2], "wb") as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes((mix.T * 32767).astype(np.int16).tobytes())
print("audio ->", sys.argv[2])
