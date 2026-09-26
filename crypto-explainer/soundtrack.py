#!/usr/bin/env python3
"""为《币圈黑话翻译器》合成电子配乐与音效（纯 numpy）。

    python3 soundtrack.py out/events.json out/soundtrack.wav

104 BPM 的轻快电子乐：拨弦琶音 + 铺底 + 鼓组；“挖出区块”“解码文字”“爆仓”等画面事件各有音效。
"""
import json
import sys
import wave

import numpy as np

SR = 48000
DUR = 60.0
N = int(SR * DUR)
BEAT = 60 / 104
rng = np.random.default_rng(21)


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


def noise_band(length, lo, hi):
    n = int(length * SR)
    spec = np.fft.rfft(rng.standard_normal(n))
    f = np.fft.rfftfreq(n, 1 / SR)
    spec *= (f > lo) & (f < hi)
    x = np.fft.irfft(spec, n)
    return x / (np.abs(x).max() + 1e-9)


def pluck(freq, length=.4, decay=10.0, harm=(1, .5, .33, .25, .2, .16)):
    t = ts(length)
    out = sum(a * np.sin(2 * np.pi * freq * k * t) * np.exp(-t * decay * (1 + .8 * (k - 1))) for k, a in enumerate(harm, 1))
    a = int(.003 * SR)
    out[:a] *= np.linspace(0, 1, a)
    return out


def glide(f0, f1, length, harm=(1,)):
    t = ts(length)
    f = f0 * (f1 / f0) ** (t / length)
    ph = 2 * np.pi * np.cumsum(f) / SR
    return sum(a * np.sin(ph * k) for k, a in enumerate(harm, 1))


def reverb(x, seconds=1.8, mix=.22):
    n = int(seconds * SR)
    t = np.arange(n) / SR
    out = np.empty_like(x)
    for c in range(2):
        ir = rng.standard_normal(n) * np.exp(-t * 6.9 / seconds)
        ir[: int(.012 * SR)] = 0
        ir /= np.sqrt((ir ** 2).sum())
        size = 1 << int(np.ceil(np.log2(x.shape[1] + n)))
        wet = np.fft.irfft(np.fft.rfft(x[c], size) * np.fft.rfft(ir, size), size)[: x.shape[1]]
        out[c] = x[c] * (1 - mix) + wet * mix * 2
    return out


music = np.zeros((2, N))
drums = np.zeros((2, N))
sfx = np.zeros((2, N))
events = json.load(open(sys.argv[1]))

# ---------------- 音乐 ----------------
# Am  F  C  G，每个和弦 1 小节
CH = [[57, 60, 64, 69], [53, 57, 60, 65], [55, 60, 64, 67], [55, 59, 62, 67]]
BASS = [33, 29, 36, 31]
bar = 4 * BEAT
t0 = 0.0
ARP = [0, 2, 1, 3, 2, 1, 3, 2]
bi = 0
while t0 < 59.0:
    ci = bi % 4
    ch = CH[ci]
    intro = t0 < 3.2
    breakdown = t0 >= 52.0
    # 铺底
    L = bar + .3
    t = ts(L)
    env = np.minimum(1, t / .25) * np.minimum(1, (L - t) / .3)
    for m in ch:
        pad = sum(np.sin(2 * np.pi * midi(m) * (1 + d) * t) for d in (-.003, .003)) + .3 * np.sin(2 * np.pi * midi(m) * 2 * t)
        add(music, pad * env, t0, gain=.010 if intro else .014)
    # 琶音（十六分）
    for j in range(16 if not intro else 8):
        step = BEAT / 4 if not intro else BEAT / 2
        m = ch[ARP[j % 8]] + 12
        add(music, pluck(midi(m), .35, decay=13), t0 + j * step, pan=.35 * np.sin(j * 1.3), gain=.05 if j % 4 else .065)
    # 低音
    if not intro:
        for j in range(8):
            add(music, pluck(midi(BASS[ci]), .3, decay=9, harm=(1, .6, .3)), t0 + j * BEAT / 2, gain=.16 if j % 2 == 0 else .10)
    # 鼓
    if not intro and not breakdown:
        for b in range(4):
            tb = t0 + b * BEAT
            x = ts(.3)
            kick = np.sin(2 * np.pi * np.cumsum(45 + 110 * np.exp(-x * 35)) / SR) * np.exp(-x * 9)
            add(drums, kick, tb, gain=.42)
            if b % 2 == 1:
                add(drums, noise_band(.18, 900, 7000) * np.exp(-ts(.18) * 22), tb, gain=.12)
            for h in (0, .5):
                add(drums, noise_band(.05, 7000, 16000) * np.exp(-ts(.05) * 90), tb + h * BEAT, pan=.3, gain=.05 if t0 > 9.5 else 0)
    t0 += bar
    bi += 1

# 结尾和弦
for j, m in enumerate([45, 57, 60, 64, 69, 72, 76]):
    add(music, pluck(midi(m), 3.0, decay=1.2, harm=(1, .4, .2, .1)), 58.2 + j * .03, pan=(j - 3) * .15, gain=.07)

# 爆仓时让音乐停一下
duck = np.ones(N)
for e in events:
    if e["type"] == "boom":
        i0, i1 = int((e["t"] - .02) * SR), int((e["t"] + 1.0) * SR)
        duck[i0:i1] = .25
k = int(.04 * SR)
duck = np.convolve(duck, np.ones(k) / k, mode="same")
music *= duck
drums *= duck

# ---------------- 音效 ----------------
for ev in events:
    t, kind = ev["t"], ev["type"]
    if kind == "whoosh":
        n = .5
        env = np.sin(np.pi * np.linspace(0, 1, int(n * SR))) ** 2
        add(sfx, noise_band(n, 600, 6000) * env, t - .05, gain=.06)
        add(sfx, glide(300, 1200, n) * env, t - .05, gain=.015)
    elif kind == "mine":
        for j, m in enumerate([84, 91]):
            s = pluck(midi(m), .25, decay=14, harm=(1, 0, .33, 0, .2))
            add(sfx, s, t + j * .07, pan=.2, gain=.06)
        x = ts(.2)
        add(sfx, np.sin(2 * np.pi * 90 * x) * np.exp(-x * 25), t, gain=.2)
    elif kind == "decode":
        d = ev.get("d", 1.0)
        for q in np.arange(0, d, .035):
            add(sfx, noise_band(.012, 3000, 9000) * np.hanning(int(.012 * SR)), t + q, pan=rng.uniform(-.3, .3), gain=.025)
    elif kind == "pop":
        add(sfx, glide(500, 1100, .08) * np.exp(-ts(.08) * 30), t, pan=rng.uniform(-.3, .3), gain=.06)
    elif kind == "click":
        add(sfx, noise_band(.03, 2000, 9000) * np.exp(-ts(.03) * 160), t, gain=.12)
    elif kind == "alarm":
        for q in range(3):
            x = ts(.14)
            add(sfx, np.sign(np.sin(2 * np.pi * (880 if q % 2 == 0 else 660) * x)) * np.minimum(1, (.14 - x) / .02), t + q * .16, gain=.025)
    elif kind == "stamp":
        x = ts(.3)
        add(sfx, np.sin(2 * np.pi * 80 * x) * np.exp(-x * 20) + noise_band(.3, 200, 2500) * np.exp(-x * 50) * .6, t, gain=.3)
    elif kind == "coin":
        x = ts(.6)
        clink = sum(np.sin(2 * np.pi * f * x) * a for f, a in ((2637, 1), (3951, .6), (5274, .35))) * np.exp(-x * 9)
        add(sfx, clink, t, pan=.2, gain=.05)
    elif kind == "zap":
        x = ts(.35)
        buzz = np.sign(np.sin(2 * np.pi * 120 * x)) * noise_band(.35, 500, 5000) * np.exp(-x * 6)
        add(sfx, buzz, t, pan=-.4, gain=.07)
    elif kind == "shield":
        add(sfx, glide(260, 900, .25, harm=(1, .3)) * np.exp(-ts(.25) * 8), t, pan=.4, gain=.08)
    elif kind == "gear":
        d = ev.get("d", 1.0)
        for q in np.arange(0, d, .07):
            add(sfx, noise_band(.02, 1500, 6000) * np.exp(-ts(.02) * 200), t + q, gain=.07)
    elif kind == "ding":
        add(sfx, pluck(midi(88), 1.0, decay=4, harm=(1, .2, .05)), t, pan=.1, gain=.06)
        add(sfx, pluck(midi(95), .8, decay=5, harm=(1, .1)), t + .06, pan=-.1, gain=.035)
    elif kind == "boom":
        x = ts(1.2)
        boom = np.sin(2 * np.pi * np.cumsum(35 + 80 * np.exp(-x * 8)) / SR) * np.exp(-x * 3.5)
        add(sfx, boom, t, gain=.5)
        add(sfx, noise_band(1.2, 100, 5000) * np.exp(-x * 5), t, gain=.2)

mix = reverb(music, 1.8, .25) + drums + reverb(sfx, 1.0, .15)
fs = int(59.0 * SR)
mix[:, fs:] *= np.linspace(1, 0, N - fs) ** 1.5
mix /= np.abs(mix).max() / 0.89
with wave.open(sys.argv[2], "wb") as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes((mix.T * 32767).astype(np.int16).tobytes())
print("audio ->", sys.argv[2])
