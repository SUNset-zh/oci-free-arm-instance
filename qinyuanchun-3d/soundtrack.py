#!/usr/bin/env python3
"""《沁园春·雪》配乐 + 朗诵混音（纯 numpy）。

    python3 soundtrack.py out/voice out/soundtrack.wav

- 朗诵：按 VOICE_AT 摆放每一句，加一点厅堂混响。
- 配乐：合成古筝（Karplus-Strong）+ 弦乐铺底 + 风声 + 大鼓，五声音阶。
  古筝旋律主要落在句与句之间的停顿里，人声出现时音乐自动压低。
"""
import json
import sys
import wave

import numpy as np
import soundfile as sf

SR = 48000
DUR = 60.0
N = int(SR * DUR)
rng = np.random.default_rng(1936)

# 每句朗诵的起始时间（秒），与 world.html 的镜头段落对齐
VOICE_AT = [1.2, 4.0, 10.2, 18.0, 25.0, 30.6, 37.0, 45.6, 52.8]


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
    P = max(2, int(round(SR / freq)))
    n = int(dur * SR)
    y = np.zeros(n + P + 1)
    exc = rng.uniform(-1, 1, P + 1)
    for _ in range(int((1 - bright) * 4)):
        exc[1:] = .5 * (exc[1:] + exc[:-1])
    y[:P + 1] = exc
    k = P + 1
    while k < len(y):
        e = min(k + P, len(y))
        y[k:e] = damp * .5 * (y[k - P:e - P] + y[k - P - 1:e - P - 1])
        k = e
    out = y[P + 1:P + 1 + n]
    out[:int(.002 * SR)] *= np.linspace(0, 1, int(.002 * SR))
    out[-int(.05 * SR):] *= np.linspace(1, 0, int(.05 * SR))
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
    return out * env * (1 + .08 * np.sin(2 * np.pi * .3 * t)) / (len(notes) * 3)


def reverb(x, seconds=3.0, mix=.35, pre=.02):
    n = int(seconds * SR)
    t = np.arange(n) / SR
    out = np.empty_like(x)
    for c in range(x.shape[0]):
        ir = rng.standard_normal(n) * np.exp(-t * 6.9 / seconds)
        ir[: int(pre * SR)] = 0
        ir /= np.sqrt((ir ** 2).sum())
        size = 1 << int(np.ceil(np.log2(x.shape[1] + n)))
        wet = np.fft.irfft(np.fft.rfft(x[c], size) * np.fft.rfft(ir, size), size)[: x.shape[1]]
        out[c] = x[c] * (1 - mix) + wet * mix * 2.2
    return out


def resample(x, sr_in):
    if sr_in == SR:
        return x
    n_out = int(len(x) * SR / sr_in)
    X = np.fft.rfft(x)
    Y = np.zeros(n_out // 2 + 1, dtype=complex)
    m = min(len(X), len(Y))
    Y[:m] = X[:m]
    return np.fft.irfft(Y, n_out) * (n_out / len(x))


# ---------------- 朗诵 ----------------
vdir = sys.argv[1]
meta = json.load(open(f'{vdir}/durations.json'))
voice = np.zeros((2, N))
vmask = np.zeros(N)
for i, t0 in enumerate(VOICE_AT):
    x, sr = sf.read(f'{vdir}/line{i}.wav', dtype='float32')
    x = resample(x.astype(np.float64), sr)
    x /= np.abs(x).max() + 1e-9
    # 轻微温暖化：300Hz 以下略提升
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    x = np.fft.irfft(X * (1 + .6 / (1 + (f / 300) ** 2)), len(x))
    x /= np.abs(x).max()
    add(voice, x, t0, gain=.9)
    i0, i1 = int(t0 * SR), min(N, int((t0 + len(x) / SR) * SR))
    vmask[i0:i1] = 1
voice = reverb(voice, 1.8, .16, pre=.03)

# ---------------- 配乐 ----------------
music = np.zeros((2, N))
PENTA = [50, 52, 54, 57, 59, 62, 64, 66, 69, 71, 74, 76, 78, 81, 83, 86]

wind = noise_band(26, 150, 1800)
wt = ts(26)
wenv = (.55 + .45 * np.sin(2 * np.pi * .13 * wt + 1) * np.sin(2 * np.pi * .07 * wt)) * np.minimum(1, wt / 1.5) * np.clip((25 - wt) / 5, 0, 1)
add(music, wind * wenv, 0, gain=.09)

add(music, pad([47, 54, 59], 10.5, 3, 2.5), 0.0, gain=.10)             # 雪：Bm 空五度
add(music, pad([43, 50, 55, 59], 8.0, 2, 2.5), 9.6, gain=.11)          # 长城、大河
add(music, pad([47, 54, 59, 62, 66], 7.5, 2, 2), 17.2, gain=.12)       # 群山
add(music, pad([38, 50, 57, 62, 66], 12.5, 1.0, 3), 24.2, gain=.15)    # 红日：D 大调
add(music, pad([43, 50, 55, 59, 62], 9.5, 2.5, 3), 35.8, gain=.12)     # 怀古
add(music, pad([45, 52, 57, 61, 64], 8.0, 2, 2.5), 44.6, gain=.14)     # 草原
add(music, pad([38, 50, 57, 62, 66, 69, 74], 8.2, 2.5, 3.5), 51.8, gain=.20)  # 今朝


def phrase(t0, notes, step, gain=.12, pan=.15):
    t = t0
    for m, d in notes:
        if m is not None:
            add(music, zheng(midi(m), 3.2, damp=.997, bright=.65), t, pan=pan, gain=gain)
            if d >= 1.5:
                for r in np.arange(.16, min(d * step, 1.0), .16):
                    add(music, zheng(midi(m), 1.0, damp=.994, bright=.5), t + r, pan=pan, gain=gain * .22)
        t += d * step


# 旋律主要落在句间停顿
phrase(0.3, [(71, 1.5), (66, 1), (69, 1.5)], .5, gain=.10)
phrase(8.9, [(66, 1), (69, 1), (71, 2)], .45)
phrase(16.6, [(74, 1), (76, 1), (78, 2)], .42)
phrase(29.3, [(81, 1), (78, 1), (76, 1), (78, 2)], .38, gain=.12)
phrase(35.6, [(69, 1.5), (66, 1), (64, 2)], .45, gain=.11)
phrase(44.3, [(62, 1), (64, 1), (69, 1), (71, 2)], .32, gain=.12)
phrase(57.6, [(86, 2), (83, 1), (81, 1), (86, 5)], .38, gain=.13)
# 人声下方的轻拨伴奏
for t0, ch in [(4.2, [59, 62, 66]), (10.4, [55, 59, 62]), (18.2, [59, 62, 66]), (25.4, [62, 66, 69]), (30.8, [62, 66, 69]),
               (37.2, [55, 59, 62]), (45.8, [57, 61, 64]), (53.0, [62, 66, 69])]:
    for k in range(8):
        add(music, zheng(midi(ch[k % 3] + 12), 2.2, damp=.995, bright=.55), t0 + k * .62, pan=-.25 + .1 * (k % 3), gain=.045)

# 低音
for t, m in [(0.2, 47), (4.0, 47), (9.6, 43), (13.6, 43), (17.4, 47), (21.0, 42), (24.4, 38), (27.5, 45), (30.2, 43), (33.2, 38),
             (36.3, 43), (40.0, 47), (44.8, 45), (48.4, 45), (52.2, 38), (56.0, 38)]:
    add(music, zheng(midi(m), 4.0, damp=.998, bright=.3), t, pan=-.2, gain=.16)

# 大河冰封：一串清冷的高音
for i, m in enumerate([88, 93, 90, 95, 98]):
    add(music, zheng(midi(m), 2.0, damp=.996, bright=.9), 15.7 + i * .22, pan=.4 - i * .15, gain=.05)

# 刮奏：红日破云、穿云而上
for tg in (24.2, 52.4):
    for i, m in enumerate(PENTA):
        add(music, zheng(midi(m), 2.5, damp=.996, bright=.7), tg - .6 + i * .038, pan=-.4 + i * .05, gain=.07)


def drum(t, g):
    x = ts(1.2)
    body = np.sin(2 * np.pi * np.cumsum(52 + 50 * np.exp(-x * 14)) / SR) * np.exp(-x * 4.5)
    add(music, body + .4 * noise_band(1.2, 60, 900) * np.exp(-x * 18), t, gain=g)


drum(22.7, .35)                  # 欲与天公试比高
for t in (36.6, 39.0, 41.4):     # 烽火
    drum(t, .22)
bt = 45.2
while bt < 51.6:                 # 草原，渐强
    drum(bt, .2 + .22 * (bt - 45.2) / 6.4)
    bt += .8 if bt < 48.6 else .4
for t, g in [(52.4, .5), (56.0, .4)]:
    drum(t, g)

music = reverb(music, 3.2, .34)

# 人声出现时压低配乐
k = int(.25 * SR)
duck = 1 - .5 * np.convolve(vmask, np.ones(k) / k, mode='same')
music *= duck

vm = vmask > 0
print('voice rms dB', round(20 * np.log10(np.sqrt((voice[:, vm] ** 2).mean())), 1),
      '| music under voice dB', round(20 * np.log10(np.sqrt((music[:, vm] ** 2).mean())), 1))
mix = music + voice
fs = int(58.8 * SR)
mix[:, fs:] *= np.linspace(1, 0, N - fs) ** 1.4
mix /= np.abs(mix).max() / 0.89
with wave.open(sys.argv[2], 'wb') as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes((mix.T * 32767).astype(np.int16).tobytes())
print('audio ->', sys.argv[2])
