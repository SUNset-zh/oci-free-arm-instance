#!/usr/bin/env python3
"""为宣传片合成配乐与音效（纯 numpy，无外部素材）。

    python3 soundtrack.py out/events.json out/soundtrack.wav

events.json 由 render.js 从 film.html 导出，保证按键声、转场声与画面逐帧同步。
"""
import json
import sys
import wave

import numpy as np

SR = 48000
DUR = 30.0
N = int(SR * DUR)
BPM = 128
BEAT = 60 / BPM
rng = np.random.default_rng(7)


def midi(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def env_adsr(n, a, d, s, r, sus_len=None):
    a, d, r = int(a * SR), int(d * SR), int(r * SR)
    sus_len = n - a - d - r if sus_len is None else int(sus_len * SR)
    sus_len = max(sus_len, 0)
    e = np.concatenate([np.linspace(0, 1, a, endpoint=False), np.linspace(1, s, d, endpoint=False),
                        np.full(sus_len, s), np.linspace(s, 0, r)])
    return np.pad(e, (0, max(0, n - len(e))))[:n]


def add(buf, sig, t, pan=0.0):
    i = int(t * SR)
    if i >= N or i + len(sig) <= 0:
        return
    if i < 0:
        sig, i = sig[-i:], 0
    sig = sig[: N - i]
    l, r = np.cos((pan + 1) * np.pi / 4), np.sin((pan + 1) * np.pi / 4)
    buf[0, i:i + len(sig)] += sig * l
    buf[1, i:i + len(sig)] += sig * r


def shaped_noise(n, lo, hi):
    spec = np.fft.rfft(rng.standard_normal(n))
    f = np.fft.rfftfreq(n, 1 / SR)
    spec *= ((f > lo) & (f < hi)) * 1.0
    x = np.fft.irfft(spec, n)
    return x / (np.abs(x).max() + 1e-9)


def tone(freq, length, harmonics=(1.0,), decay=None, detune=0.0):
    t = np.arange(int(length * SR)) / SR
    out = np.zeros_like(t)
    for k, amp in enumerate(harmonics, 1):
        for dt in ((0.0,) if detune == 0 else (-detune, detune)):
            ph = rng.uniform(0, 2 * np.pi)
            h = amp * np.sin(2 * np.pi * freq * k * (1 + dt) * t + ph)
            if decay:
                h *= np.exp(-t * decay * (1 + 0.6 * (k - 1)))
            out += h
    return out


def reverb(x, seconds=2.6, mix=0.3):
    n = int(seconds * SR)
    t = np.arange(n) / SR
    out = np.empty_like(x)
    for c in range(x.shape[0]):
        ir = rng.standard_normal(n) * np.exp(-t * 6.9 / seconds)
        ir[: int(0.012 * SR)] = 0
        ir /= np.sqrt((ir ** 2).sum())
        size = 1 << int(np.ceil(np.log2(x.shape[1] + n)))
        wet = np.fft.irfft(np.fft.rfft(x[c], size) * np.fft.rfft(ir, size), size)[: x.shape[1]]
        out[c] = x[c] * (1 - mix) + wet * mix * 2.2
    return out


# ---------------- 音乐 ----------------
music = np.zeros((2, N))
# D 大调：Dmaj9 → Bm9 → Gmaj9 → A6sus，每个和弦 2 小节
CHORDS = [
    [50, 57, 61, 64, 66], [47, 54, 57, 62, 66],
    [43, 50, 54, 57, 62], [45, 52, 57, 59, 64],
]
bar = 4 * BEAT
for i in range(8):
    t0 = i * 2 * bar
    ch = CHORDS[i % 4]
    for j, m in enumerate(ch):
        sig = tone(midi(m), 2 * bar + 1.2, harmonics=(1, .35, .15, .06), detune=0.0025)
        sig *= env_adsr(len(sig), 0.9, 0.5, 0.8, 1.2) * 0.05
        add(music, sig, t0, pan=(j - 2) * 0.25)
    # 低音
    bass = tone(midi(ch[0] - 12), 2 * bar, harmonics=(1, .25)) * env_adsr(int(2 * bar * SR), 0.05, 0.3, 0.7, 0.4) * 0.14
    if t0 >= 3.5:
        add(music, bass, t0)

# 琶音拨弦：3.6s 起，Agent 段加密，结尾停止
ARP = [0, 2, 3, 4, 3, 2, 1, 2]
step = BEAT / 2
t = 3.75
k = 0
while t < 26.4:
    ch = CHORDS[int(t // (2 * bar)) % 4]
    m = ch[ARP[k % len(ARP)]] + 12
    amp = 0.07 if t < 19.2 else 0.085
    sig = tone(midi(m), 0.9, harmonics=(1, .5, .25, .12), decay=6.5) * amp
    sig[: int(0.004 * SR)] *= np.linspace(0, 1, int(0.004 * SR))
    add(music, sig, t, pan=0.35 * np.sin(k * 0.9))
    if t >= 19.2 and k % 2 == 0:  # Agent 段叠一层高八度
        add(music, tone(midi(m + 12), 0.5, harmonics=(1, .3), decay=9) * 0.03, t + step / 2, pan=-0.3)
    t += step
    k += 1

# 轻柔的低频脉冲（通话 → Agent 段）
t = 12.6
while t < 25.4:
    n = int(0.35 * SR)
    tt = np.arange(n) / SR
    f = 42 + 60 * np.exp(-tt * 30)
    kick = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tt * 9) * 0.28
    add(music, kick, t)
    t += BEAT

# 结尾大和弦
for j, m in enumerate([38, 50, 57, 61, 64, 69, 73]):
    sig = tone(midi(m), 4.2, harmonics=(1, .4, .18, .08), detune=0.003)
    sig *= env_adsr(len(sig), 0.02, 1.0, 0.6, 2.4) * (0.07 if m > 40 else 0.2)
    add(music, sig, 26.6, pan=(j - 3) * 0.2)

# 开场氛围：低频嗡鸣 + 上升噪声
drone = tone(midi(38), 3.8, harmonics=(1, .5, .2)) * env_adsr(int(3.8 * SR), 1.6, 0.2, 0.9, 1.5) * 0.08
add(music, drone, 0.0)
riser = shaped_noise(int(2.4 * SR), 2000, 9000) * np.linspace(0, 1, int(2.4 * SR)) ** 2 * 0.05
add(music, riser, 1.2)

# ---------------- 音效 ----------------
sfx = np.zeros((2, N))
events = json.load(open(sys.argv[1]))
for ev in events:
    t, kind = ev["t"], ev["type"]
    if kind == "key":
        n = int(0.05 * SR)
        click = shaped_noise(n, 1800, 7000) * np.exp(-np.arange(n) / SR * 140) * 0.22
        thock = tone(210 + rng.uniform(-15, 15), 0.05, decay=90) * 0.18
        add(sfx, click + thock, t - 0.01, pan=rng.uniform(-.2, .2))
    elif kind == "tap":
        add(sfx, tone(900, 0.12, harmonics=(1, .3), decay=40) * 0.12, t)
    elif kind == "ring":
        for r in range(2):
            for q, m in enumerate([81, 76, 81, 88]):
                add(sfx, tone(midi(m), 0.5, harmonics=(1, .4, .1), decay=8) * 0.06, t + r * 0.8 + q * 0.13, pan=.1)
    elif kind == "tick":
        add(sfx, tone(midi(93), 0.25, harmonics=(1, .2), decay=18) * 0.05, t)
    elif kind == "success":
        for q, m in enumerate([81, 85, 88, 93]):
            add(sfx, tone(midi(m), 1.2, harmonics=(1, .3, .1), decay=4) * 0.07, t + q * 0.07, pan=(q - 1.5) * .2)
    elif kind == "whoosh":
        d = max(ev.get("d", 1.0), 0.6)
        n = int(d * SR)
        x = shaped_noise(n, 150, 6000)
        # 分段带通扫频
        out = np.zeros(n)
        seg = 2048
        win = np.hanning(seg)
        for s in range(0, n - seg, seg // 2):
            p = s / n
            center = 400 + 3600 * np.sin(np.pi * p)
            spec = np.fft.rfft(x[s:s + seg] * win)
            f = np.fft.rfftfreq(seg, 1 / SR)
            spec *= np.exp(-((np.log(f + 1) - np.log(center)) ** 2) / 0.5)
            out[s:s + seg] += np.fft.irfft(spec, seg)
        out *= np.sin(np.pi * np.linspace(0, 1, n)) ** 1.5
        out /= np.abs(out).max() + 1e-9
        for c, pan in ((0, -0.6), (1, 0.6)):
            add(sfx, out * 0.09, t + c * 0.03, pan=pan)
    elif kind == "wake":
        for q, m in enumerate([74, 78, 81, 86]):
            add(sfx, tone(midi(m), 1.8, harmonics=(1, .2), decay=2.5) * 0.045, t + q * 0.05, pan=(q - 1.5) * .3)
    elif kind == "end":
        n = int(2.5 * SR)
        tt = np.arange(n) / SR
        boom = np.sin(2 * np.pi * np.cumsum(38 + 40 * np.exp(-tt * 6)) / SR) * np.exp(-tt * 1.6) * 0.35
        add(sfx, boom, t - 0.6)

mix = reverb(music, 2.8, 0.35) + reverb(sfx, 1.2, 0.15)
# 收尾淡出
fade = np.ones(N)
fs = int(28.6 * SR)
fade[fs:] = np.linspace(1, 0, N - fs) ** 1.5
mix *= fade
mix /= np.abs(mix).max() / 0.89
pcm = (mix.T * 32767).astype(np.int16)
with wave.open(sys.argv[2], "wb") as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes(pcm.tobytes())
print("audio ->", sys.argv[2])
