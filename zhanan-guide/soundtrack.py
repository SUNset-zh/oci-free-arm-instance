#!/usr/bin/env python3
"""为《渣男指导手册》合成配乐与音效（纯 numpy）。

    python3 soundtrack.py out/events.json out/soundtrack.wav

第一部分（0–16.6s）：小调拨弦低音 + 响指，偷偷摸摸的喜剧感；每次翻车配一段下行“长号”。
第二部分（16.6–30s）：大调扫弦 + 钟琴旋律，温暖收尾。
"""
import json
import sys
import wave

import numpy as np

SR = 48000
DUR = 30.0
N = int(SR * DUR)
PART2 = 16.6
rng = np.random.default_rng(3)


def midi(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def add(buf, sig, t, pan=0.0, gain=1.0):
    i = int(t * SR)
    if i >= N:
        return
    sig = sig[: N - i] * gain
    l, r = np.cos((pan + 1) * np.pi / 4), np.sin((pan + 1) * np.pi / 4)
    buf[0, i:i + len(sig)] += sig * l
    buf[1, i:i + len(sig)] += sig * r


def ts(length):
    return np.arange(int(length * SR)) / SR


def pluck(freq, length=0.5, decay=9.0, harm=(1, .5, .25, .12)):
    t = ts(length)
    out = sum(a * np.sin(2 * np.pi * freq * k * t) * np.exp(-t * decay * (1 + .5 * (k - 1))) for k, a in enumerate(harm, 1))
    out[: int(.003 * SR)] *= np.linspace(0, 1, int(.003 * SR))
    return out


def noise_band(length, lo, hi):
    n = int(length * SR)
    spec = np.fft.rfft(rng.standard_normal(n))
    f = np.fft.rfftfreq(n, 1 / SR)
    spec *= (f > lo) & (f < hi)
    x = np.fft.irfft(spec, n)
    return x / (np.abs(x).max() + 1e-9)


def glide(f0, f1, length, harm=(1, .3)):
    t = ts(length)
    f = f0 * (f1 / f0) ** (t / length)
    ph = 2 * np.pi * np.cumsum(f) / SR
    return sum(a * np.sin(ph * k) for k, a in enumerate(harm, 1))


def reverb(x, seconds=1.6, mix=0.22):
    n = int(seconds * SR)
    t = np.arange(n) / SR
    out = np.empty_like(x)
    for c in range(2):
        ir = rng.standard_normal(n) * np.exp(-t * 6.9 / seconds)
        ir[: int(.01 * SR)] = 0
        ir /= np.sqrt((ir ** 2).sum())
        size = 1 << int(np.ceil(np.log2(x.shape[1] + n)))
        wet = np.fft.irfft(np.fft.rfft(x[c], size) * np.fft.rfft(ir, size), size)[: x.shape[1]]
        out[c] = x[c] * (1 - mix) + wet * mix * 2
    return out


music = np.zeros((2, N))
sfx = np.zeros((2, N))
events = json.load(open(sys.argv[1]))
fails = [e["t"] for e in events if e["type"] == "fail"]

# ---------------- 第一部分：小调，偷偷摸摸 ----------------
BEAT = 0.5
# 每小节 8 个八分音符（None 为休止），D 小调半音爬行
BASS = [38, None, 41, None, 43, 44, 45, None, 38, None, 41, None, 45, 44, 43, None]
t, k = 0.25, 0
while t < PART2 - 0.2:
    m = BASS[k % len(BASS)]
    if m is not None:
        add(music, pluck(midi(m), 0.4, decay=11, harm=(1, .6, .3, .15)), t, gain=.32)
    if k % 4 == 2:  # 响指（第 2、4 拍）
        n = int(.06 * SR)
        add(music, noise_band(.06, 1800, 6500) * np.exp(-np.arange(n) / SR * 90), t, pan=.3, gain=.12)
    if k % 16 == 0 and t > 2.8:  # Dm7 短和弦
        for j, cm in enumerate([62, 65, 69, 72]):
            add(music, pluck(midi(cm), .5, decay=14), t + BEAT / 2 + j * .012, pan=-.2, gain=.05)
    t += BEAT / 2
    k += 1

# ---------------- 第二部分：大调，温暖 ----------------
CH2 = [[62, 66, 69, 74], [59, 62, 66, 71], [55, 59, 62, 67], [57, 61, 64, 69]]  # D Bm G A
BASS2 = [38, 35, 31, 33]
MEL = [78, None, 81, 78, 76, None, 74, None, 76, None, 78, 81, 83, None, 81, None]
bar = 4 * BEAT
t, k = PART2 + 0.25, 0
while t < 29.2:
    ci = int((t - PART2) // bar) % 4
    if k % 2 == 0:  # 扫弦
        for j, cm in enumerate(CH2[ci]):
            add(music, pluck(midi(cm), .6, decay=7), t + j * .014, pan=-.25, gain=.045 if k % 4 else .06)
    if k % 8 == 0:
        add(music, pluck(midi(BASS2[ci]), 1.6, decay=2.5, harm=(1, .3)), t, gain=.3)
    if t > 18.0:
        mm = MEL[k % len(MEL)]
        if mm is not None:
            add(music, pluck(midi(mm), .9, decay=5, harm=(1, .15, .05)), t, pan=.3, gain=.07)
    t += BEAT / 2
    k += 1
# 结尾和弦
for j, m in enumerate([50, 57, 62, 66, 69, 74, 78]):
    add(music, pluck(midi(m), 3.0, decay=1.3, harm=(1, .3, .1)), 28.1 + j * .03, pan=(j - 3) * .15, gain=.08)

# 翻车时音乐让位
duck = np.ones(N)
for f in fails:
    i0, i1 = int((f - .05) * SR), int((f + 1.1) * SR)
    duck[i0:i1] = np.minimum(duck[i0:i1], 0.35)
k = np.ones(int(.05 * SR)) / int(.05 * SR)
duck = np.convolve(duck, k, mode="same")
music *= duck

# ---------------- 音效 ----------------
for ev in events:
    t, kind = ev["t"], ev["type"]
    if kind == "flip":
        n = .38
        env = np.sin(np.pi * np.linspace(0, 1, int(n * SR))) ** 2
        add(sfx, noise_band(n, 900, 5500) * env, t + .05, pan=-.3, gain=.1)
    elif kind == "pop":
        add(sfx, glide(420, 980, .09) * np.exp(-ts(.09) * 25), t, gain=.12)
    elif kind == "blip":
        m = rng.choice([74, 76, 78, 81, 83])
        add(sfx, pluck(midi(m), .3, decay=16, harm=(1, .2)), t, pan=rng.uniform(-.4, .4), gain=.07)
    elif kind == "fail":  # 下行“长号”：wah wah wah wahhh
        notes = [(58, .22), (57, .22), (56, .22), (55, .75)]
        tt = t
        for m, d in notes:
            x = ts(d)
            vib = 1 + (.012 * np.sin(2 * np.pi * 6 * x) if d > .5 else 0)
            ph = 2 * np.pi * np.cumsum(midi(m - 12) * vib * np.ones_like(x)) / SR
            s = sum(a * np.sin(ph * h) for h, a in enumerate((1, .7, .5, .3, .15), 1))
            env = np.minimum(1, x / .04) * np.minimum(1, (d - x) / .06)
            wah = .55 + .45 * np.minimum(1, x / (d * .6))
            add(sfx, s * env * wah, tt, gain=.075)
            tt += d
    elif kind in ("stamp", "stampGood"):
        x = ts(.25)
        thunk = np.sin(2 * np.pi * 85 * x) * np.exp(-x * 22) + noise_band(.25, 200, 2500) * np.exp(-x * 60) * .6
        add(sfx, thunk, t, gain=.35)
        if kind == "stampGood":
            for j, m in enumerate([83, 88]):
                add(sfx, pluck(midi(m), .9, decay=4, harm=(1, .2)), t + .06 + j * .08, pan=.2, gain=.08)
    elif kind == "ping":
        add(sfx, pluck(1480, .25, decay=14, harm=(1,)) + pluck(1975, .25, decay=18, harm=(1,)) * .6, t, pan=rng.uniform(-.5, .5), gain=.07)
    elif kind == "splash":
        x = ts(.7)
        add(sfx, noise_band(.7, 300, 4000) * np.exp(-x * 5) * np.minimum(1, x / .02), t, gain=.22)
        add(sfx, glide(900, 250, .12) * np.exp(-ts(.12) * 20), t - .03, gain=.12)
    elif kind == "tick":
        add(sfx, pluck(midi(rng.choice([86, 88, 90, 93])), .2, decay=20, harm=(1,)), t, pan=rng.uniform(-.3, .3), gain=.05)
    elif kind == "scribble":
        x = ts(.28)
        jit = (np.sin(2 * np.pi * 22 * x) > 0) * .6 + .4
        add(sfx, noise_band(.28, 2000, 7000) * jit * np.sin(np.pi * x / .28), t, gain=.07)
    elif kind == "end":
        for j, m in enumerate([86, 90, 93, 98]):
            add(sfx, pluck(midi(m), 1.6, decay=2.2, harm=(1, .2)), t + j * .06, pan=(j - 1.5) * .25, gain=.06)

# 第一→第二部分之间的滑哨
add(sfx, glide(380, 1300, .45, harm=(1, .1)) * np.sin(np.pi * np.linspace(0, 1, int(.45 * SR))), PART2 - .45, gain=.07)

mix = reverb(music, 1.4, .2) + reverb(sfx, .8, .12)
fs = int(29.3 * SR)
mix[:, fs:] *= np.linspace(1, 0, N - fs) ** 1.5
mix /= np.abs(mix).max() / 0.89
with wave.open(sys.argv[2], "wb") as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes((mix.T * 32767).astype(np.int16).tobytes())
print("audio ->", sys.argv[2])
