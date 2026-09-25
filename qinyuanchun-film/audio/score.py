#!/usr/bin/env python3
"""《沁园春·雪》配乐 + 朗诵混音。采样乐器（MusyngKite / FluidR3 的逐音采样）按乐谱排布，卷积混响，人声下自动压低。

    python3 audio/score.py 朗诵目录 输出.wav

段落（与镜头对应）：
  0–3.6   片头    尺八一声长音 + 竖琴泛音，暖色长音垫底（B 小调空五度），风声
  3.6–10  北国风光 低音弦乐 Bm，筝的疏落分解和弦
  10–17.6 长城·大河 大提琴长线旋律；冰冻时竖琴上行刮奏 + 高音的“冰晶”
  17.6–24.4 山舞银蛇 太鼓由弱渐强、弦乐一路上行、合唱在“试比高”处推起
  24.4–36.4 红装素裹·江山 转 D 大调：合唱 + 全弦乐 + 圆号主题 + 定音鼓
  36.4–45.3 怀古    回落：大提琴独奏、筝，Bm
  45.3–52.3 一代天骄 太鼓奔马节奏、低音弦乐固定音型，张弓时圆号上行，放箭一声呼啸
  52.3–60  还看今朝 合唱与弦乐全奏推向 D 大调终止，竖琴琶音收尾
"""
import base64
import json
import math
import os
import subprocess
import sys

import numpy as np
import soundfile as sf

SR = 48000
DUR = 60.0
N = int(SR * DUR)
FF = '/usr/local/lib/python3.11/dist-packages/imageio_ffmpeg/binaries/ffmpeg-linux-x86_64-v7.0.2'
ASSETS = '/tmp/claude-0/-home-user-oci-free-arm-instance/33674d5b-35e4-5b5a-b79d-ec7ad6b62fa3/scratchpad/assets'
CACHE = '/tmp/claude-0/-home-user-oci-free-arm-instance/33674d5b-35e4-5b5a-b79d-ec7ad6b62fa3/scratchpad/samples'
rng = np.random.default_rng(1936)

# 朗诵起点（秒），与画面段落对齐
VOICE_AT = [1.2, 3.9, 10.0, 17.5, 24.5, 29.9, 36.6, 45.5, 52.5]

FONTS = {
    'cello': 'mk/cello.js', 'choir': 'mk/choir_aahs.js', 'bass': 'mk/contrabass.js', 'horn': 'mk/french_horn.js',
    'koto': 'mk/koto.js', 'harp': 'mk/orchestral_harp.js', 'pad': 'mk/pad_2_warm.js',
    'shaku': 'sf_shakuhachi.js', 'flute': 'sf_pan_flute.js', 'strings': 'sf_string_ensemble_1.js',
    'taiko': 'sf_taiko_drum.js', 'timp': 'sf_timpani.js',
}
NAMES = ['C', 'Db', 'D', 'Eb', 'E', 'F', 'Gb', 'G', 'Ab', 'A', 'Bb', 'B']


def note_name(m):
    return f'{NAMES[m % 12]}{m // 12 - 1}'


_fonts = {}


def font(instr):
    if instr not in _fonts:
        txt = open(os.path.join(ASSETS, FONTS[instr])).read()
        d = {}
        for line in txt.splitlines():
            line = line.strip()
            if line.startswith('"') and 'base64,' in line:
                k = line.split('"')[1]
                d[k] = line.split('base64,')[1].rstrip('",')
        _fonts[instr] = d
    return _fonts[instr]


_smp = {}


def sample(instr, m):
    """某乐器某音高的采样（单声道 float32，48 kHz）。缓存解码结果。"""
    key = (instr, m)
    if key in _smp:
        return _smp[key]
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, f'{instr}_{m}.npy')
    if os.path.exists(path):
        _smp[key] = np.load(path)
        return _smp[key]
    f = font(instr)
    nm = note_name(m)
    if nm not in f:                                   # 超出采样范围：取最近的音再移调
        have = [k for k in f]
        idx = {note_name(i): i for i in range(21, 109)}
        best = min((abs(idx[k] - m), k) for k in have if k in idx)[1]
        raw = base64.b64decode(f[best])
        shift = m - idx[best]
    else:
        raw = base64.b64decode(f[nm]); shift = 0
    p = subprocess.run([FF, '-v', 'quiet', '-i', 'pipe:0', '-f', 'f32le', '-ac', '1', '-ar', str(SR), 'pipe:1'],
                       input=raw, capture_output=True, check=True)
    x = np.frombuffer(p.stdout, np.float32).copy()
    if shift:
        ratio = 2 ** (shift / 12)
        n_out = int(len(x) / ratio)
        x = np.interp(np.arange(n_out) * ratio, np.arange(len(x)), x).astype(np.float32)
    np.save(path, x)
    _smp[key] = x
    return x


buf = {}


def bus(name):
    if name not in buf:
        buf[name] = np.zeros((2, N), np.float32)
    return buf[name]


def put(name, sig, t, pan=0.0, gain=1.0):
    b = bus(name)
    i = int(t * SR)
    if i >= N:
        return
    if i < 0:
        sig = sig[-i:]; i = 0
    sig = sig[:N - i] * gain
    l, r = math.cos((pan + 1) * math.pi / 4), math.sin((pan + 1) * math.pi / 4)
    b[0, i:i + len(sig)] += sig * l
    b[1, i:i + len(sig)] += sig * r


def env(n, attack, release, sustain_len=None):
    e = np.ones(n, np.float32)
    a = max(1, int(attack * SR)); r = max(1, int(release * SR))
    e[:a] *= np.linspace(0, 1, a) ** 1.5
    if r < n:
        e[-r:] *= np.linspace(1, 0, r) ** 1.3
    return e


def play(instr, m, t, dur, vel=1.0, pan=0.0, attack=.01, release=.4, name=None, loop=False):
    """放一个音。dur 超过采样长度时（弦乐、合唱这类长音）用错位叠加的方式延长。"""
    x = sample(instr, m)
    n = int((dur + release) * SR)
    if len(x) < n and loop:
        seg = x[int(.25 * len(x)):int(.85 * len(x))]
        out = np.zeros(n, np.float32)
        out[:len(x)] = x
        pos = int(.6 * len(x)); fl = int(.25 * SR)
        while pos < n:
            L = min(len(seg), n - pos)
            w = np.ones(L, np.float32)
            w[:min(fl, L)] = np.linspace(0, 1, min(fl, L))
            out[pos:pos + L] = out[pos:pos + L] * (1 - w) + seg[:L] * w
            pos += len(seg) - fl
        x = out
    x = x[:n]
    if len(x) < n:
        x = np.pad(x, (0, n - len(x)))
    x = x * env(n, attack, release)
    put(name or instr, x, t, pan, vel)


def chord(instr, ms, t, dur, vel=1.0, spread=.5, **kw):
    for k, m in enumerate(ms):
        pan = (k / max(1, len(ms) - 1) - .5) * 2 * spread
        play(instr, m, t + k * .012, dur, vel / math.sqrt(len(ms)), pan, **kw)


def noise_band(length, lo, hi):
    n = int(length * SR)
    spec = np.fft.rfft(rng.standard_normal(n))
    fr = np.fft.rfftfreq(n, 1 / SR)
    spec *= ((fr > lo) & (fr < hi)).astype(float)
    x = np.fft.irfft(spec, n)
    return (x / (np.abs(x).max() + 1e-9)).astype(np.float32)


def reverb(x, seconds=3.0, mix=.3, pre=.025, bright=.6):
    n = int(seconds * SR)
    t = np.arange(n) / SR
    out = np.empty_like(x)
    for c in range(2):
        ir = rng.standard_normal(n) * np.exp(-t * 6.9 / seconds)
        # 高频衰减得更快（大厅的空气吸收）
        spec = np.fft.rfft(ir); fr = np.fft.rfftfreq(n, 1 / SR)
        ir = np.fft.irfft(spec / (1 + (fr / (3000 + 6000 * bright)) ** 2), n)
        ir[:int(pre * SR)] = 0
        ir /= np.sqrt((ir ** 2).sum())
        size = 1 << int(np.ceil(np.log2(x.shape[1] + n)))
        wet = np.fft.irfft(np.fft.rfft(x[c], size) * np.fft.rfft(ir, size), size)[:x.shape[1]]
        out[c] = x[c] * (1 - mix) + wet * mix * 1.8
    return out


# ============================================================ 乐谱
PENTA = [50, 52, 54, 57, 59, 62, 64, 66, 69, 71, 74, 76, 78, 81, 83, 86]   # D 大调五声


def compose():
    # ---- 0–3.6 片头
    chord('pad', [47, 54, 59], 0.0, 4.2, .5, attack=1.6, release=1.2, loop=True)
    play('shaku', 66, .35, 2.4, .55, -.15, attack=.25, release=.9)
    play('shaku', 69, 2.5, 1.4, .35, -.15, attack=.2, release=.8)
    for tt, m in [(1.25, 83), (1.9, 90), (2.55, 86), (3.1, 95)]:
        play('harp', m, tt, 2.5, .22, .35, release=1.5)
    # ---- 3.6–10 北国风光
    chord('strings', [47, 54, 59, 62], 3.4, 6.8, .75, attack=1.8, release=1.5, loop=True)
    play('bass', 35, 3.5, 6.6, .55, 0, attack=1.2, release=1.2, loop=True)
    for k, m in enumerate([59, 62, 66, 69, 71, 69, 66, 62, 59, 66]):
        play('koto', m + 12 * (k % 3 == 2), 4.2 + k * .58, 1.8, .22, -.3 + .06 * k, release=.9)
    # ---- 10–17.6 长城 · 大河
    chord('strings', [43, 50, 55, 59], 10.0, 3.8, .7, attack=1.2, release=1.2, loop=True)
    chord('strings', [40, 47, 52, 55, 59], 13.4, 4.4, .72, attack=1.0, release=1.4, loop=True)
    play('bass', 31, 10.0, 3.6, .45, attack=.8, release=1.0, loop=True)
    play('bass', 28, 13.4, 4.2, .45, attack=.8, release=1.2, loop=True)
    for tt, m, d in [(10.3, 59, 1.6), (11.9, 57, 1.1), (13.0, 54, 2.2), (15.2, 52, 2.2)]:
        play('cello', m, tt, d, .42, .2, attack=.35, release=.9, loop=True)
    # 冰冻：竖琴快速上行刮奏 + 高音冰晶
    for k, m in enumerate(PENTA):
        play('harp', m + 12, 14.05 + k * .045, 1.8, .2 + .01 * k, -.5 + k * .065, release=1.2)
    for k, m in enumerate([95, 90, 98, 93, 100, 97]):
        play('koto', m, 14.6 + k * .21, 1.2, .1, .5 - .18 * k, release=.9)
    # ---- 17.6–24.4 山舞银蛇 … 欲与天公试比高
    chord('strings', [47, 54, 59, 62], 17.4, 2.4, .72, attack=.8, release=.8, loop=True)
    chord('strings', [43, 50, 55, 59, 62], 19.7, 2.2, .78, attack=.6, release=.8, loop=True)
    chord('strings', [45, 52, 57, 61, 64], 21.8, 2.8, .88, attack=.5, release=.6, loop=True)
    play('bass', 35, 17.5, 2.3, .5, loop=True); play('bass', 31, 19.8, 2.1, .5, loop=True); play('bass', 33, 21.9, 2.6, .6, loop=True)
    chord('choir', [62, 66, 69], 21.4, 3.1, .55, attack=1.4, release=.6, loop=True)
    tt = 18.3; g = .12
    while tt < 24.2:
        play('taiko', 45, tt, .9, g, -.1, release=.5)
        step = .8 if tt < 21.5 else (.4 if tt < 23.2 else .2)
        g = min(.55, g + .035)
        tt += step
    for k in range(18):
        play('timp', 38, 23.0 + k * .075, .5, .08 + .02 * k, 0, release=.3)
    # ---- 24.4–30 须晴日，看红装素裹
    play('timp', 38, 24.4, 3.0, .8, 0, release=2.0)
    play('taiko', 41, 24.4, 2.0, .6, 0, release=1.4)
    chord('choir', [62, 66, 69, 74], 24.4, 5.8, .8, attack=.3, release=1.6, loop=True)
    chord('strings', [38, 45, 50, 54, 57, 62], 24.4, 5.8, 1.0, attack=.25, release=1.5, loop=True)
    play('bass', 26, 24.4, 5.8, .6, attack=.2, release=1.4, loop=True)
    for k, m in enumerate(reversed(PENTA)):
        play('harp', m + 12, 24.25 + k * .04, 2.0, .18, .5 - k * .06, release=1.5)
    for tt, m, d in [(24.9, 57, .9), (25.8, 62, .9), (26.7, 66, 1.4), (28.2, 64, .7), (28.9, 62, 1.5)]:
        play('horn', m, tt, d, .45, -.2, attack=.08, release=.7, loop=True)
    # ---- 30–36.4 江山如此多娇，引无数英雄竞折腰
    for tt, ms, d in [(30.0, [43, 50, 55, 59, 62], 1.7), (31.7, [38, 45, 50, 54, 57], 1.6),
                      (33.3, [45, 52, 57, 61, 64], 1.5), (34.8, [38, 45, 50, 54, 57, 62], 2.0)]:
        chord('strings', ms, tt, d, .9, attack=.25, release=.8, loop=True)
        play('bass', ms[0] - 12, tt, d, .55, attack=.15, release=.8, loop=True)
    chord('choir', [62, 66, 69], 30.0, 6.4, .5, attack=.8, release=1.5, loop=True)
    for tt, m, d in [(30.3, 62, .6), (30.9, 64, .6), (31.5, 66, 1.0), (32.6, 69, .8), (33.4, 71, .6), (34.0, 69, .8), (34.8, 74, 1.6)]:
        play('horn', m, tt, d, .5, -.2, attack=.06, release=.6, loop=True)
    for tt in (30.0, 31.7, 33.3, 34.8):
        play('timp', 38 if tt != 33.3 else 45, tt, 1.5, .35, 0, release=1.0)
    # ---- 36.4–45.3 惜秦皇汉武 … 稍逊风骚（回落、怀古）
    chord('strings', [47, 54, 59, 62], 36.2, 4.6, .45, attack=1.4, release=1.4, loop=True)
    chord('strings', [43, 50, 55, 59], 40.8, 4.6, .45, attack=1.2, release=1.6, loop=True)
    chord('pad', [47, 54, 59], 36.2, 9.0, .3, attack=2.0, release=2.0, loop=True)
    play('bass', 35, 36.3, 4.5, .35, attack=1.0, release=1.0, loop=True)
    play('bass', 31, 40.8, 4.5, .35, attack=1.0, release=1.4, loop=True)
    for tt, m, d in [(36.9, 66, 1.4), (38.5, 64, .9), (39.5, 62, 1.8), (41.6, 59, 1.2), (43.0, 57, .7), (43.7, 59, 1.6)]:
        play('cello', m - 12, tt, d, .5, .15, attack=.3, release=.9, loop=True)
    for k, m in enumerate([71, 69, 66, 62, 66, 59]):
        play('koto', m, 37.4 + k * 1.2, 2.0, .16, -.3, release=1.0)
    # ---- 45.3–52.3 一代天骄，成吉思汗，只识弯弓射大雕（奔马）
    beat = 60 / 150.0
    tt = 45.3; k = 0
    while tt < 50.4:
        acc = 1 if k % 3 == 0 else 0
        play('taiko', 41 if acc else 45, tt, .6, .3 + .25 * acc + .02 * (tt - 45.3), (-.2 if k % 2 else .2), release=.35)
        tt += beat * (.5 if k % 3 != 2 else 1.0)          # 奔马：哒-哒-哒（空）
        k += 1
    for k in range(int((50.4 - 45.3) / (beat / 2))):
        tt = 45.3 + k * beat / 2
        m = [35, 42, 35, 47][k % 4]
        play('bass', m, tt, beat / 2 * .9, .38, 0, attack=.01, release=.12)
        play('cello', m + 12, tt, beat / 2 * .9, .22, .25, attack=.01, release=.12)
    chord('strings', [47, 54, 59], 45.3, 5.6, .55, attack=.4, release=.5, loop=True)
    for tt, m, d in [(48.7, 59, .45), (49.15, 62, .45), (49.6, 66, .8)]:
        play('horn', m, tt, d, .5, -.2, attack=.05, release=.4, loop=True)
    # 放箭：一声呼啸（后面在音效里加），配一记定音鼓
    play('timp', 38, 50.42, 1.8, .6, 0, release=1.4)
    # ---- 52.3–60 俱往矣，数风流人物，还看今朝
    chord('strings', [43, 50, 55, 59, 62], 52.3, 2.2, .75, attack=.8, release=.6, loop=True)
    chord('strings', [45, 52, 57, 61, 64], 54.5, 2.2, .85, attack=.4, release=.6, loop=True)
    chord('strings', [38, 45, 50, 54, 57, 62, 66], 56.7, 3.3, 1.0, attack=.2, release=2.2, loop=True)
    chord('choir', [62, 66, 69], 52.4, 4.3, .55, attack=1.0, release=.5, loop=True)
    chord('choir', [62, 66, 69, 74], 56.7, 3.3, .85, attack=.25, release=2.2, loop=True)
    play('bass', 31, 52.3, 2.2, .5, loop=True); play('bass', 33, 54.5, 2.2, .55, loop=True)
    play('bass', 26, 56.7, 3.3, .65, attack=.1, release=2.2, loop=True)
    for tt, m, d in [(52.9, 62, .9), (53.9, 66, .9), (54.9, 69, 1.2), (56.3, 71, .4), (56.7, 74, 2.8)]:
        play('horn', m, tt, d, .5, -.2, attack=.06, release=1.2, loop=True)
    for k in range(24):
        play('timp', 38, 55.0 + k * .07, .5, .06 + .022 * k, 0, release=.3)
    play('timp', 38, 56.7, 3.0, .85, 0, release=2.5)
    play('taiko', 41, 56.7, 2.0, .6, 0, release=1.6)
    for k, m in enumerate(PENTA[5:]):
        play('harp', m, 56.75 + k * .09, 2.6, .18, -.4 + k * .08, release=1.8)
    play('shaku', 78, 58.1, 1.6, .25, .2, attack=.2, release=1.0)


def sfx():
    """风声、冰裂、放箭呼啸、过场的气流声。"""
    t = np.arange(N) / SR
    wind = noise_band(DUR, 180, 2200)
    wenv = (.55 + .45 * np.sin(2 * np.pi * .11 * t + 1) * np.sin(2 * np.pi * .06 * t))
    wenv *= np.interp(t, [0, 1, 17, 19, 36, 38, 44, 46, 52, 54, 60], [0, 1, 1, .15, .15, .7, .7, .35, .35, .5, 0])
    put('sfx', wind * wenv, 0, 0, .06)
    # 冰裂：短促的高频“咔”声 + 共振
    for k in range(9):
        tt = 14.1 + k * rng.uniform(.18, .42)
        n = int(.25 * SR)
        x = rng.standard_normal(n).astype(np.float32) * np.exp(-np.arange(n) / (.012 * SR))
        f0 = rng.uniform(900, 2400)
        x += .6 * np.sin(2 * np.pi * f0 * np.arange(n) / SR).astype(np.float32) * np.exp(-np.arange(n) / (.05 * SR))
        put('sfx', x, tt, rng.uniform(-.6, .6), .1)
    # 放箭：从低到高的气流呼啸
    n = int(1.1 * SR)
    wh = noise_band(1.1, 700, 5000) * np.exp(-((np.arange(n) / SR - .22) / .14) ** 2)
    put('sfx', wh, 50.3, .4, .12)
    # 过场气流（每个镜头切换处一声很轻的“呼”）
    for tt in (3.5, 9.9, 13.3, 17.5, 24.3, 29.9, 36.3, 45.2, 52.2):
        n = int(1.2 * SR)
        wh = noise_band(1.2, 200, 3000) * np.sin(np.linspace(0, np.pi, n)) ** 2
        put('sfx', wh, tt - .5, rng.uniform(-.3, .3), .05)


def main(vdir, out):
    compose()
    sfx()
    # ---- 朗诵
    voice = np.zeros((2, N), np.float32)
    vmask = np.zeros(N, np.float32)
    for i, t0 in enumerate(VOICE_AT):
        x, sr = sf.read(os.path.join(vdir, f'line_{i}.wav'), dtype='float32')
        if x.ndim > 1:
            x = x.mean(1)
        if sr != SR:
            n_out = int(len(x) * SR / sr)
            x = np.interp(np.arange(n_out) * sr / SR, np.arange(len(x)), x).astype(np.float32)
        x = x / (np.abs(x).max() + 1e-9)
        X = np.fft.rfft(x); fr = np.fft.rfftfreq(len(x), 1 / SR)
        x = np.fft.irfft(X * (1 + .5 / (1 + (fr / 250) ** 2)) * (1 + .25 * (fr > 3000)), len(x)).astype(np.float32)   # 温暖 + 一点清晰度
        x /= np.abs(x).max()
        i0 = int(t0 * SR)
        voice[:, i0:i0 + len(x)] += x[None, :N - i0] * .9
        vmask[i0:min(N, i0 + len(x))] = 1
    voice = reverb(voice, 1.6, .14, pre=.02, bright=.8)
    # ---- 配乐总线
    music = sum(buf[k] for k in buf if k != 'sfx')
    music = reverb(music, 3.4, .36, pre=.03, bright=.55)
    # 整体的起伏（分贝）：片头与怀古处收着，红装素裹、奔马与终止处放开
    tt = np.arange(N) / SR
    arc = np.interp(tt, [0, 3.6, 10, 17.6, 22.5, 24.4, 30, 36.4, 38, 45.3, 50.8, 52.3, 56.7, 59, 60],
                    [-3, -1, 0, 1, 4, 7, 6, 3, -2, 1, 5, 3, 9, 9, 6])
    music = music * (10 ** (arc / 20))[None, :] * 1.75
    k = int(.35 * SR)
    duck = 1 - .64 * np.convolve(vmask, np.ones(k) / k, mode="same")
    music *= duck[None, :]
    sfxb = reverb(buf.get('sfx', np.zeros((2, N), np.float32)), 2.0, .25)
    mix = music + voice + sfxb
    vm = vmask > 0
    rms = lambda a, m: 20 * np.log10(np.sqrt((a[:, m] ** 2).mean()) + 1e-9)
    print('voice/music during speech dB:', round(rms(voice, vm), 1), round(rms(music, vm), 1),
          '| music between lines dB:', round(rms(music, ~vm), 1))
    if os.environ.get('STEMS'):
        sf.write(out.replace('.wav', '_music.wav'), music.T, SR, subtype='PCM_16')
        sf.write(out.replace('.wav', '_voice.wav'), voice.T, SR, subtype='PCM_16')
    fs = int(58.6 * SR)
    mix[:, fs:] *= (np.linspace(1, 0, N - fs) ** 1.6)[None, :]
    import pyloudnorm as pyln
    meter = pyln.Meter(SR)
    lufs = meter.integrated_loudness(mix.T)
    mix *= 10 ** ((-16.0 - lufs) / 20)
    # 软限幅：只压最尖的峰，不整体降音量
    thr = .8
    over = np.abs(mix) > thr
    mix[over] = np.sign(mix[over]) * (thr + (1 - thr) * np.tanh((np.abs(mix[over]) - thr) / (1 - thr)))
    mix *= min(1.0, .97 / np.abs(mix).max())
    lufs2 = meter.integrated_loudness(mix.T)
    print('loudness', round(lufs, 1), '->', round(lufs2, 1), 'LUFS, peak', round(float(np.abs(mix).max()), 3))
    sf.write(out, mix.T, SR, subtype='PCM_24')
    print('->', out)


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
