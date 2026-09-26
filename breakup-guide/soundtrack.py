#!/usr/bin/env python3
"""为《心碎修复指南》合成配乐与音效（纯 numpy）。

    python3 soundtrack.py out/events.json out/soundtrack.wav

音乐跟着天色走：开头是雨声里的小调钢琴，逐步转到大调，日出时铺满温暖的和弦。
"""
import json
import sys
import wave

import numpy as np

SR = 48000
DUR = 40.0
N = int(SR * DUR)
BEAT = 60 / 84
rng = np.random.default_rng(11)


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


def piano(freq, length=2.5, decay=2.2, harm=(1, .45, .2, .1, .05)):
    t = ts(length)
    out = np.zeros_like(t)
    for k, a in enumerate(harm, 1):
        f = freq * k * (1 + 0.0004 * k * k)  # 轻微非谐性
        out += a * np.sin(2 * np.pi * f * t) * np.exp(-t * decay * (1 + .7 * (k - 1)))
    att = int(.004 * SR)
    out[:att] *= np.linspace(0, 1, att)
    rel = int(.08 * SR)
    out[-rel:] *= np.linspace(1, 0, rel)
    return out


def noise_band(length, lo, hi):
    n = int(length * SR)
    spec = np.fft.rfft(rng.standard_normal(n))
    f = np.fft.rfftfreq(n, 1 / SR)
    spec *= (f > lo) & (f < hi)
    x = np.fft.irfft(spec, n)
    return x / (np.abs(x).max() + 1e-9)


def reverb(x, seconds=2.4, mix=0.3):
    n = int(seconds * SR)
    t = np.arange(n) / SR
    out = np.empty_like(x)
    for c in range(2):
        ir = rng.standard_normal(n) * np.exp(-t * 6.9 / seconds)
        ir[: int(.015 * SR)] = 0
        ir /= np.sqrt((ir ** 2).sum())
        size = 1 << int(np.ceil(np.log2(x.shape[1] + n)))
        wet = np.fft.irfft(np.fft.rfft(x[c], size) * np.fft.rfft(ir, size), size)[: x.shape[1]]
        out[c] = x[c] * (1 - mix) + wet * mix * 2
    return out


music = np.zeros((2, N))
sfx = np.zeros((2, N))

# ---------------- 和声：小调 → 大调 ----------------
bar = 4 * BEAT
# (起始小节, 和弦音, 低音)
PROG = [
    ([57, 60, 64, 71], 45), ([53, 57, 60, 64], 41), ([57, 60, 64, 67], 45), ([53, 57, 60, 64], 41),   # Am9 Fmaj7 Am7 Fmaj7
    ([53, 57, 60, 65], 41), ([55, 59, 62, 67], 43), ([52, 55, 59, 64], 40), ([57, 60, 64, 69], 45),   # F G Em Am
    ([60, 64, 67, 71], 48), ([55, 59, 62, 67], 47), ([57, 60, 64, 67], 45), ([53, 57, 60, 64], 41),   # Cmaj7 G/B Am7 Fmaj7
    ([60, 64, 67, 74], 48), ([55, 59, 62, 69], 43), ([53, 57, 60, 67], 41),                          # Cadd9 G6 Fadd9
]
ARP = [0, 1, 2, 3, 2, 1, 2, 3]
for bi, (ch, bass) in enumerate(PROG):
    t0 = 0.6 + bi * bar
    if t0 > 37.0:
        break
    add(music, piano(midi(bass - 12), 3.2, decay=1.2, harm=(1, .3, .1)), t0, gain=.20)
    if bi >= 1:
        add(music, piano(midi(bass), 3.0, decay=1.4), t0, pan=-.1, gain=.10)
    dens = 4 if bi < 2 else 8          # 开头稀疏，之后流动起来
    for j in range(dens):
        m = ch[ARP[j]] + (12 if bi >= 8 and j % 4 == 3 else 0)
        add(music, piano(midi(m), 2.0, decay=2.6), t0 + j * bar / dens, pan=.25 * np.sin(j), gain=.075)
    if bi >= 4:  # 柔和的铺底
        t = ts(bar + 1.0)
        env = np.minimum(1, t / 1.2) * np.minimum(1, (bar + 1.0 - t) / 1.0)
        for m in ch:
            pad = sum(a * np.sin(2 * np.pi * midi(m) * (1 + d) * t) for a, d in ((1, -.002), (1, .002), (.3, 0)))
            add(music, pad * env, t0, gain=.012 if bi < 8 else .016)

# 结尾大和弦（36.8s 起）
for j, m in enumerate([36, 48, 55, 60, 64, 67, 71, 74, 79]):
    add(music, piano(midi(m), 3.4, decay=.9), 36.9 + j * .05, pan=(j - 4) * .12, gain=.07 if m > 40 else .18)

# 雨声（随画面里的雨在 8–14s 淡出）
rain = noise_band(14.5, 400, 7000) * .5 + noise_band(14.5, 3000, 12000) * .3
env = np.minimum(1, ts(14.5) / .8) * np.clip((14 - ts(14.5)) / 6, 0, 1)
add(music, rain * env, 0, gain=.05)

# ---------------- 音效 ----------------
events = json.load(open(sys.argv[1]))
for ev in events:
    t, kind = ev["t"], ev["type"]
    if kind == "crack":
        x = ts(.12)
        add(sfx, noise_band(.12, 2500, 11000) * np.exp(-x * 45), t, gain=.25)
        add(sfx, np.sin(2 * np.pi * 1900 * x) * np.exp(-x * 60), t, gain=.12)
    elif kind == "shatter":
        for q in range(9):
            f = rng.uniform(1800, 5200)
            x = ts(.35)
            ping = sum(np.sin(2 * np.pi * f * r * x) * a for r, a in ((1, 1), (2.76, .4), (5.4, .2))) * np.exp(-x * rng.uniform(12, 25))
            add(sfx, ping, t + q * .028 + rng.uniform(0, .02), pan=rng.uniform(-.7, .7), gain=.05)
        add(sfx, noise_band(.4, 1500, 9000) * np.exp(-ts(.4) * 12), t, gain=.12)
    elif kind == "swipe":
        n = .42
        env = np.sin(np.pi * np.linspace(0, 1, int(n * SR))) ** 2
        add(sfx, noise_band(n, 500, 3500) * env, t, gain=.05)
    elif kind == "pop":
        x = ts(.12)
        f = 520 * (1 + 1.2 * x / .12)
        add(sfx, np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-x * 30), t, pan=rng.uniform(-.4, .4), gain=.09)
    elif kind == "toggle":
        x = ts(.04)
        add(sfx, noise_band(.04, 2000, 8000) * np.exp(-x * 150), t, gain=.14)
    elif kind == "whoosh":
        n = .3
        add(sfx, noise_band(n, 800, 5000) * np.sin(np.pi * np.linspace(0, 1, int(n * SR))), t, gain=.05)
    elif kind == "thud":
        x = ts(.25)
        add(sfx, np.sin(2 * np.pi * 110 * x) * np.exp(-x * 25) + noise_band(.25, 150, 1200) * np.exp(-x * 40) * .5, t, gain=.25)
    elif kind == "key":
        x = ts(.05)
        add(sfx, noise_band(.05, 2500, 8000) * np.exp(-x * 120), t, pan=rng.uniform(-.2, .2), gain=.08)
    elif kind == "deny":
        x = ts(.25)
        add(sfx, (np.sin(2 * np.pi * 180 * x) + .4 * np.sin(2 * np.pi * 360 * x)) * np.exp(-x * 10), t, gain=.10)
    elif kind == "check":
        for j, m in enumerate([84, 88]):
            add(sfx, piano(midi(m), .8, decay=5, harm=(1, .2)), t + j * .06, pan=.2, gain=.06)
    elif kind == "ring":
        for r in range(3):
            x = ts(.18)
            tone = (np.sin(2 * np.pi * 1320 * x) + np.sin(2 * np.pi * 1760 * x)) * np.minimum(1, (.18 - x) / .03)
            add(sfx, tone, t + r * .26, gain=.025)
    elif kind == "scribble":
        d = ev.get("d", 1.0)
        x = ts(d)
        jit = .5 + .5 * np.abs(np.sin(2 * np.pi * 7 * x + np.sin(2 * np.pi * 2.3 * x)))
        add(sfx, noise_band(d, 2500, 9000) * jit * np.minimum(1, x / .05) * np.minimum(1, (d - x) / .1), t, gain=.035)
    elif kind == "mend":
        x = ts(.3)
        add(sfx, np.sin(2 * np.pi * 240 * x) * np.exp(-x * 18) + noise_band(.3, 800, 4000) * np.exp(-x * 50) * .4, t + .5, gain=.10)
    elif kind == "gold":
        for j, m in enumerate([88, 91, 95, 100]):
            add(sfx, piano(midi(m), 1.6, decay=2.4, harm=(1, .25, .08)), t + j * .09, pan=(j - 1.5) * .25, gain=.035)
    elif kind == "final":
        for j, m in enumerate([91, 95, 98, 103, 107]):
            add(sfx, piano(midi(m), 2.0, decay=1.8, harm=(1, .2)), t + j * .12, pan=(j - 2) * .3, gain=.03)

mix = reverb(music, 2.6, .32) + reverb(sfx, 1.2, .18)
fs = int(38.8 * SR)
mix[:, fs:] *= np.linspace(1, 0, N - fs) ** 1.5
mix /= np.abs(mix).max() / 0.89
with wave.open(sys.argv[2], "wb") as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes((mix.T * 32767).astype(np.int16).tobytes())
print("audio ->", sys.argv[2])
