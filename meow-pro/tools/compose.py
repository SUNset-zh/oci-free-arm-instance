"""Soundtrack for 喵 Pro — synthesized from scratch, locked to the picture.

120 BPM (one bar = 2 s), F major. Groove progression IV–V–iii–vi
(Bbmaj7 – C – Am7 – Dm7), resolving to Fmaj9 on the logo at 48 s.
Every whoosh / hit / UI sound sits on a cue from web/keynote.js.

usage: python compose.py out.wav
"""
import sys
from functools import lru_cache
import numpy as np
from scipy.ndimage import minimum_filter1d
import scipy.signal as ss
from scipy.io import wavfile

SR = 48000
DUR = 50.0
N = int(SR * (DUR + 2.0))
BEAT = 0.5
BAR = 2.0
rng = np.random.default_rng(7)


def midi(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def tt(n):
    return np.arange(n) / SR


# ------------------------------------------------------------ filters
def sos_lp(fc, order=2):
    return ss.butter(order, min(fc, SR * 0.45), 'low', fs=SR, output='sos')


def sos_hp(fc, order=2):
    return ss.butter(order, fc, 'high', fs=SR, output='sos')


def sos_bp(lo, hi, order=2):
    return ss.butter(order, [lo, min(hi, SR * 0.45)], 'band', fs=SR, output='sos')


def lp(x, fc, order=2):
    return ss.sosfilt(sos_lp(fc, order), x, axis=0)


def hp(x, fc, order=2):
    return ss.sosfilt(sos_hp(fc, order), x, axis=0)


def bp(x, lo, hi, order=2):
    return ss.sosfilt(sos_bp(lo, hi, order), x, axis=0)


def shelf(x, fc, gain_db, kind='low', q=0.707):
    A = 10 ** (gain_db / 40)
    w = 2 * np.pi * fc / SR
    c, sn = np.cos(w), np.sin(w)
    al = sn / (2 * q)
    sq = 2 * np.sqrt(A) * al
    if kind == 'low':
        b = [A * ((A + 1) - (A - 1) * c + sq), 2 * A * ((A - 1) - (A + 1) * c), A * ((A + 1) - (A - 1) * c - sq)]
        a = [(A + 1) + (A - 1) * c + sq, -2 * ((A - 1) + (A + 1) * c), (A + 1) + (A - 1) * c - sq]
    else:
        b = [A * ((A + 1) + (A - 1) * c + sq), -2 * A * ((A - 1) + (A + 1) * c), A * ((A + 1) + (A - 1) * c - sq)]
        a = [(A + 1) - (A - 1) * c + sq, 2 * ((A - 1) - (A + 1) * c), (A + 1) - (A - 1) * c - sq]
    return ss.lfilter(np.array(b) / a[0], np.array(a) / a[0], x, axis=0)


def peak_eq(x, fc, gain_db, q=1.0):
    A = 10 ** (gain_db / 40)
    w = 2 * np.pi * fc / SR
    al = np.sin(w) / (2 * q)
    b = [1 + al * A, -2 * np.cos(w), 1 - al * A]
    a = [1 + al / A, -2 * np.cos(w), 1 - al / A]
    return ss.lfilter(np.array(b) / a[0], np.array(a) / a[0], x, axis=0)


def noise(n):
    return rng.standard_normal(n)


def st(x, pan=0.0, width=0.0):
    """mono -> stereo, constant-power pan in [-1, 1]; width decorrelates a little."""
    a = (pan + 1) * np.pi / 4
    L, R = np.cos(a) * x, np.sin(a) * x
    if width:
        d = int(0.011 * SR)
        R = (1 - width) * R + width * np.concatenate([np.zeros(d), R[:-d]])
    return np.stack([L, R], 1) * np.sqrt(2)


def fade(x, a=0.002, r=0.01):
    n = len(x)
    e = np.ones(n)
    na, nr = max(1, int(a * SR)), max(1, int(r * SR))
    e[:na] = np.linspace(0, 1, na)
    e[-nr:] *= np.linspace(1, 0, nr)
    return x * (e[:, None] if x.ndim == 2 else e)


# ------------------------------------------------------------ mixer
class Bus:
    def __init__(self):
        self.x = np.zeros((N, 2))

    def add(self, t, sig, g=1.0, pan=0.0):
        if sig.ndim == 1:
            sig = st(sig, pan)
        i = int(round(t * SR))
        if i >= N:
            return
        if i < 0:
            sig, i = sig[-i:], 0
        n = min(len(sig), N - i)
        self.x[i:i + n] += sig[:n] * g


B = {k: Bus() for k in ['kick', 'drums', 'bass', 'pad', 'keys', 'lead', 'fx', 'ui', 'rev', 'dly']}


def send(bus, t, sig, g, rev=0.0, dly=0.0, pan=0.0):
    if sig.ndim == 1:
        sig = st(sig, pan)
    B[bus].add(t, sig, g)
    if rev:
        B['rev'].add(t, sig, g * rev)
    if dly:
        B['dly'].add(t, sig, g * dly)


# ------------------------------------------------------------ oscillators
def saw(f, n, ph=0.0):
    """polyBLEP sawtooth, f may be scalar or array."""
    f = np.broadcast_to(np.asarray(f, float), (n,))
    dt = f / SR
    p = (ph + np.cumsum(dt)) % 1.0
    y = 2 * p - 1
    m = p < dt
    q = p[m] / dt[m]
    y[m] -= 2 * q - q * q - 1
    m2 = p > 1 - dt
    q = (p[m2] - 1) / dt[m2]
    y[m2] -= q * q + 2 * q + 1
    return y


def additive(freq, n, harm, decay_base, decay_slope, amp_pow=1.0, detune=0.0):
    """harmonic pluck: harmonic k decays faster (a moving low-pass for free)."""
    t = tt(n)
    y = np.zeros(n)
    for k in range(1, harm + 1):
        fk = freq * k * (1 + detune * (k % 3 - 1) * 1e-4)
        if fk > SR * 0.42:
            break
        y += np.sin(2 * np.pi * fk * t + k * 0.7) / (k ** amp_pow) * np.exp(-t * (decay_base + decay_slope * k))
    return y


# ------------------------------------------------------------ instruments
@lru_cache(maxsize=None)
def kick(v=1.0):
    n = int(0.55 * SR)
    t = tt(n)
    f = 46 + 130 * np.exp(-t / 0.035) + 60 * np.exp(-t / 0.006)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.24)
    knock = np.sin(2 * np.pi * 185 * t) * np.exp(-t / 0.034) * 0.55
    click = hp(noise(n) * np.exp(-t / 0.0018), 2500) * 0.22
    x = np.tanh(1.7 * (body + knock)) * 0.85 + click
    return fade(x * v, 0.0008, 0.05)


@lru_cache(maxsize=None)
def clap(v=1.0):
    n = int(0.45 * SR)
    t = tt(n)
    e = np.zeros(n)
    for d in (0.0, 0.010, 0.021):
        e += (t >= d) * np.exp(-np.maximum(t - d, 0) / 0.0065)
    e += 0.55 * (t >= 0.028) * np.exp(-np.maximum(t - 0.028, 0) / 0.11)
    x = bp(noise(n), 900, 5200, 2) * e
    body = np.sin(2 * np.pi * 210 * t) * np.exp(-t / 0.03) * 0.25
    return fade((x + body) * v, 0.0005, 0.03)


@lru_cache(maxsize=None)
def hat(open_=False, v=1.0):
    n = int((0.32 if open_ else 0.07) * SR)
    t = tt(n)
    m = np.zeros(n)
    for f in (205.3, 304.4, 369.6, 522.7, 540.0, 800.0):
        m += np.sign(np.sin(2 * np.pi * f * 1.62 * t + f))
    x = hp(m * 0.35 + noise(n) * 0.6, 7000, 2)
    x *= np.exp(-t / (0.11 if open_ else 0.022))
    return fade(x * v, 0.0005, 0.01)


@lru_cache(maxsize=None)
def shaker(v=1.0):
    n = int(0.09 * SR)
    t = tt(n)
    x = bp(noise(n), 5000, 12000) * (1 - np.exp(-t / 0.006)) * np.exp(-t / 0.03)
    return fade(x * v)


def crash(v=1.0, dur=2.6):
    n = int(dur * SR)
    t = tt(n)
    x = hp(noise(n), 3500, 2) * np.exp(-t / 0.9) + hp(noise(n), 7000) * np.exp(-t / 0.25) * 0.6
    return fade(st(x * v, 0, 0.6), 0.001, 0.4)


@lru_cache(maxsize=None)
def bass_note(m, dur, v=1.0):
    n = int(dur * SR)
    t = tt(n)
    f = midi(m)
    sub = np.sin(2 * np.pi * f * t)
    grit = saw(f * 2, n) * 0.45 + saw(f * 1.004, n) * 0.35
    grit = lp(grit, 1500, 2)
    e = (1 - np.exp(-t / 0.004)) * np.exp(-t / (dur * 0.9))
    x = np.tanh(1.6 * (sub * 0.9 + grit)) * e
    return fade(x * v, 0.002, 0.03)


@lru_cache(maxsize=None)
def pluck(m, dur=0.45, v=1.0, bright=1.0):
    n = int(dur * SR)
    f = midi(m)
    a = additive(f, n, 26, 4.0 / bright, 1.25 / bright, 1.0)
    b = additive(f * 1.0035, n, 26, 4.0 / bright, 1.25 / bright, 1.0)
    t = tt(n)
    atk = 1 - np.exp(-t / 0.002)
    return fade(np.stack([a, b], 1) * atk[:, None] * 0.22 * v, 0.001, 0.05)


def pad_chord(notes, dur, v=1.0, cutoff=1700, attack=0.5, release=0.9):
    n = int((dur + release) * SR)
    t = tt(n)
    L = np.zeros(n)
    R = np.zeros(n)
    for m in notes:
        f = midi(m)
        for j, c in enumerate((-11, -4, 3, 10)):
            y = saw(f * 2 ** (c / 1200), n, ph=rng.random())
            if j % 2:
                L += y
            else:
                R += y
    L, R = lp(L, cutoff, 4), lp(R, cutoff, 4)
    e = np.minimum(1, t / attack) * np.where(t < dur, 1.0, np.exp(-(t - dur) / (release / 3)))
    x = np.stack([L, R], 1) * e[:, None]
    return x * 0.07 * v / np.sqrt(len(notes))


@lru_cache(maxsize=None)
def bell(m, dur=2.5, v=1.0, bright=1.0):
    n = int(dur * SR)
    t = tt(n)
    f = midi(m)
    parts = [(1, 1.0, 1.9), (2.0, 0.42, 1.2), (2.76, 0.26 * bright, 0.7), (4.07, 0.16 * bright, 0.45), (5.43, 0.09 * bright, 0.3)]
    L = np.zeros(n)
    R = np.zeros(n)
    for i, (r, a, d) in enumerate(parts):
        L += a * np.sin(2 * np.pi * f * r * t) * np.exp(-t / d)
        R += a * np.sin(2 * np.pi * f * r * 1.0012 * t + 0.3) * np.exp(-t / d)
    atk = 1 - np.exp(-t / 0.0015)
    return fade(np.stack([L, R], 1) * atk[:, None] * 0.25 * v, 0.0005, 0.2)


@lru_cache(maxsize=None)
def lead(m, dur, v=1.0):
    n = int((dur + 0.25) * SR)
    t = tt(n)
    f = midi(m) * (1 + 0.004 * np.sin(2 * np.pi * 5.2 * t) * np.minimum(1, t / 0.3))
    ph = 2 * np.pi * np.cumsum(f) / SR
    x = np.sin(ph) + 0.28 * np.sin(2 * ph) + 0.08 * np.sin(3 * ph)
    e = np.minimum(1, t / 0.012) * np.where(t < dur, 0.75 + 0.25 * np.exp(-t / 0.15), 0.75 * np.exp(-(t - dur) / 0.08))
    return fade(x * e * 0.2 * v, 0.001, 0.03)


# ------------------------------------------------------------ sound design
def shaped_noise(dur, center, width_oct, amp, seed=0):
    """noise through a moving gaussian band. center/amp: functions of u in [0,1]."""
    n = int(dur * SR)
    x = np.random.default_rng(seed).standard_normal(n)
    f, fr, Z = ss.stft(x, SR, nperseg=1024, noverlap=768)
    u = np.clip(fr / dur, 0, 1)
    c = np.asarray(center(u), float)
    lf = np.log2(np.maximum(f, 20))[:, None]
    mask = np.exp(-0.5 * ((lf - np.log2(c)[None, :]) / width_oct) ** 2)
    Z = Z * mask * np.asarray(amp(u), float)[None, :]
    _, y = ss.istft(Z, SR, nperseg=1024, noverlap=768)
    y = y[:n]
    return y / (np.abs(y).max() + 1e-9)


def whoosh(dur, f0, f1, pan0=0.0, pan1=0.0, seed=1, peak=0.55):
    u_env = lambda u: np.where(u < peak, (u / peak) ** 2, ((1 - u) / (1 - peak)) ** 1.6)
    y = shaped_noise(dur, lambda u: f0 * (f1 / f0) ** u, 0.55, u_env, seed)
    n = len(y)
    p = np.linspace(pan0, pan1, n)
    a = (p + 1) * np.pi / 4
    return np.stack([np.cos(a) * y, np.sin(a) * y], 1) * np.sqrt(2)


def riser(dur, f0=300, f1=7000, seed=2):
    y = shaped_noise(dur, lambda u: f0 * (f1 / f0) ** (u ** 1.4), 0.5, lambda u: 0.1 + 0.9 * u ** 2.2, seed)
    n = len(y)
    t = tt(n)
    f = 110 * 2 ** (3 * (t / dur) ** 1.5)
    tone = saw(f, n) * 0.25 + saw(f * 1.5, n) * 0.15
    tone = lp(tone, 3000) * (t / dur) ** 2.5
    return st(y * 0.8 + tone, 0, 0.5)


def impact(v=1.0):
    n = int(2.2 * SR)
    t = tt(n)
    f = 38 + 70 * np.exp(-t / 0.09)
    boom = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.7)
    mid = np.sin(2 * np.pi * 150 * t) * np.exp(-t / 0.06) * 0.5
    body = lp(noise(n), 900) * np.exp(-t / 0.25) * 0.5
    air = hp(noise(n), 4000) * np.exp(-t / 0.5) * 0.25
    x = np.tanh(1.4 * (boom + mid)) + body + air
    return fade(st(x * v, 0, 0.3), 0.0005, 0.3)


def sub_boom(v=1.0, f0=60):
    n = int(1.3 * SR)
    t = tt(n)
    f = f0 * 0.75 + f0 * 0.6 * np.exp(-t / 0.08)
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.45)
    x += np.sin(2 * np.pi * f0 * 2.5 * t) * np.exp(-t / 0.05) * 0.25
    x += bp(noise(n), 200, 1200) * np.exp(-t / 0.03) * 0.25
    return fade(np.tanh(1.3 * x) * v, 0.0008, 0.2)


def tick(freq=2400, v=1.0, dur=0.05):
    n = int(dur * SR)
    t = tt(n)
    f = freq * (1 + 0.5 * np.exp(-t / 0.004))
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.012)
    return fade(x * v, 0.0003, 0.005)


def pop(freq=700, v=1.0):
    n = int(0.12 * SR)
    t = tt(n)
    f = freq * (0.75 + 0.6 * np.exp(-t / 0.012))
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * (1 - np.exp(-t / 0.002)) * np.exp(-t / 0.035)
    return fade(x * v, 0.0005, 0.02)


def shutter(v=1.0):
    n = int(0.16 * SR)
    t = tt(n)
    x = np.zeros(n)
    for d, a in ((0.0, 1.0), (0.055, 0.7)):
        m = t >= d
        x[m] += bp(noise(m.sum()), 1800, 7000)[: m.sum()] * np.exp(-(t[m] - d) / 0.006) * a
    x += np.sin(2 * np.pi * 900 * t) * np.exp(-t / 0.01) * 0.2
    return fade(x * v)


def beep(freq=2200, v=1.0, dur=0.06):
    n = int(dur * SR)
    t = tt(n)
    x = np.sin(2 * np.pi * freq * t) * np.minimum(1, t / 0.004) * np.minimum(1, (dur - t) / 0.01)
    return x * v


def purr(dur, v=1.0):
    n = int(dur * SR)
    t = tt(n)
    breath = 0.55 + 0.45 * np.sin(2 * np.pi * t / 1.7 - 1.2) ** 2
    rate = 24 + 3 * np.sin(2 * np.pi * t / 1.7)
    pulse = (0.5 + 0.5 * np.sin(2 * np.pi * np.cumsum(rate) / SR)) ** 5
    x = lp(noise(n), 520, 2) * pulse * breath
    x = x + 0.4 * lp(noise(n), 180) * pulse
    x = hp(x, 70)
    x /= np.abs(x).max() + 1e-9
    e = np.minimum(1, t / 0.4) * np.minimum(1, (dur - t) / 0.6)
    return st(x * e * v, 0, 0.25)


def laser(dur, f0=380, f1=880, v=1.0):
    n = int(dur * SR)
    t = tt(n)
    u = t / dur
    f = f0 * (f1 / f0) ** E_io(u)
    x = saw(f, n) * 0.4 + np.sin(2 * np.pi * np.cumsum(f * 2) / SR) * 0.3
    x = bp(x, 400, 5000)
    e = np.minimum(1, u / 0.1) * np.minimum(1, (1 - u) / 0.15)
    sh = hp(noise(n), 6000) * 0.25 * e
    return st((x * e + sh) * v, 0, 0.4)


def E_io(u):
    return np.where(u < .5, 4 * u ** 3, 1 - (-2 * u + 2) ** 3 / 2)


def zap(freq=1200, v=1.0):
    n = int(0.18 * SR)
    t = tt(n)
    f = freq * (1 + 1.5 * np.exp(-t / 0.02))
    x = np.sin(2 * np.pi * np.cumsum(f) / SR + 3 * np.sin(2 * np.pi * freq * 1.5 * t) * np.exp(-t / 0.03))
    return fade(x * np.exp(-t / 0.05) * v)


def reverse_swell(dur, v=1.0, seed=5):
    y = shaped_noise(dur, lambda u: 500 * 12 ** u, 0.9, lambda u: u ** 3, seed)
    return st(y * v, 0, 0.7)


# ------------------------------------------------------------ effects
def reverb_ir(rt60=2.4, dur=3.0, seed=11):
    n = int(dur * SR)
    t = tt(n)
    g = np.random.default_rng(seed)
    out = []
    for ch in range(2):
        x = g.standard_normal(n) * np.exp(-6.9 * t / rt60)
        dark = lp(x, 2500)
        w = np.clip(t / 1.2, 0, 1)
        x = x * (1 - w) + dark * w * 1.6
        x[: int(0.012 * SR)] = 0
        for d, a in ((0.013, .5), (0.021, .38), (0.034, .3), (0.047, .22)):
            x[int((d + ch * 0.003) * SR)] += a * 8
        out.append(x)
    ir = np.stack(out, 1)
    return ir / np.sqrt((ir ** 2).sum(0)).max()


def pingpong(x, delay=0.375, fb=0.38, n_rep=6, damp=3500):
    y = np.zeros_like(x)
    d = int(delay * SR)
    cur = x.copy()
    for i in range(1, n_rep + 1):
        cur = lp(cur, damp) * fb
        sh = np.zeros_like(x)
        if i * d < len(x):
            sh[i * d:] = cur[: len(x) - i * d]
        if i % 2:
            sh = sh[:, ::-1]
        y += sh
    return y


# ======================================================================
# ARRANGEMENT
# ======================================================================
IV, V, iii, vi = 0, 1, 2, 3
CH = {  # (bass root, pad voicing, pluck/arp tones)
    'Bb': (34, [58, 62, 65, 69], [70, 74, 77, 81]),
    'C': (36, [55, 60, 64, 67], [72, 76, 79, 84]),
    'Am': (33, [57, 60, 64, 67], [69, 72, 76, 79]),
    'Dm': (38, [57, 62, 65, 72], [74, 77, 81, 84]),
    'F': (29, [53, 57, 60, 64, 67], [72, 76, 79, 84]),
    'Dm9': (26, [50, 57, 62, 64, 65], [74, 76, 77, 81]),
    'Gm7/C': (36, [55, 58, 62, 65], [70, 74, 77, 79]),
}
PROG = ['Bb', 'C', 'Am', 'Dm']


def chord_at(bar):
    if bar < 2:
        return 'Dm9'
    if bar == 2:
        return 'F'
    if bar == 3:
        return 'Gm7/C'
    if 4 <= bar <= 19:
        return PROG[(bar - 4) % 4]
    if bar in (20, 21):
        return 'Dm9' if bar == 20 else 'C'
    if bar == 22:
        return 'Bb'
    if bar == 23:
        return 'C'
    return 'F'


def build():
    # ---------------- 0–4 s: teaser (dark, sub hits on each cut)
    send('pad', 0.0, pad_chord(CH['Dm9'][1], 3.6, v=0.8, cutoff=1300, attack=1.0, release=1.0), 1.3, rev=0.5)
    for i, t in enumerate((0.0, 1.0, 2.0, 3.0)):
        send('fx', t, st(sub_boom(0.9, 55 if i % 2 == 0 else 49)), 0.85, rev=0.35)
        send('fx', t + 0.02, whoosh(0.7, 2500, 900, -0.4 + 0.3 * i, 0.4 - 0.3 * i, seed=20 + i, peak=0.15), 0.18, rev=0.3)
        send('keys', t + 0.03, bell([74, 77, 81, 76][i], 1.6, v=0.55, bright=0.6), 0.75, rev=0.6, dly=0.25)
        send('fx', t, st(bp(noise(int(0.25 * SR)), 150, 900) * np.exp(-tt(int(0.25 * SR)) / 0.05)), 0.35, rev=0.4)
    send('fx', 3.42, reverse_swell(0.44, 1.0, seed=31), 0.28, rev=0.2)
    send('ui', 3.86, tick(3200, 0.8, 0.06), 0.35, rev=0.5)

    # ---------------- 4–8 s: hello
    send('pad', 4.25, pad_chord(CH['F'][1], 1.9, v=1.0, cutoff=2400, attack=0.25, release=0.8), 1.4, rev=0.55)
    for j, m in enumerate([53, 60, 64, 67, 72]):          # the startup-chime-like bloom
        send('keys', 4.3 + j * 0.012, bell(m, 3.2, v=0.9, bright=0.5), 0.75, rev=0.6, pan=(j - 2) * 0.2)
    send('pad', 6.1, pad_chord(CH['Gm7/C'][1], 1.95, v=0.9, cutoff=2600, attack=0.4, release=0.2), 1.3, rev=0.4)
    for k in range(16):                                  # gentle arpeggio while writing
        t = 4.5 + k * 0.125 * 2
        if t > 7.8:
            break
        tones = CH['F'][2] if t < 6.1 else CH['Gm7/C'][2]
        send('keys', t, pluck(tones[k % 4], 0.35, v=0.45, bright=0.8), 0.7, rev=0.4, dly=0.3)
    send('fx', 6.0, riser(2.0), 0.42, rev=0.2)
    send('fx', 6.95, whoosh(1.05, 300, 6000, 0, 0, seed=40, peak=0.92), 0.5)
    send('ui', 6.45, bell(84, 1.2, v=0.5, bright=0.4), 0.3, rev=0.6)

    # ---------------- 8–40 s: the groove
    hits = [8.0, 20.0, 43.0]
    for t in hits:
        send('fx', t, impact(1.0), 0.75, rev=0.35)
        send('drums', t, crash(0.9), 0.35, rev=0.3)
    kicks = []
    for bar in range(4, 20):
        t0 = bar * BAR
        name = chord_at(bar)
        root, voic, tones = CH[name]
        section = 0 if bar < 8 else 1 if bar < 12 else 2 if bar < 18 else 3
        # drums
        for b in range(4):
            tb = t0 + b * BEAT
            if not (bar == 19 and b == 3 and False):
                send('kick', tb, st(kick(1.0)), 0.8)
                kicks.append(tb)
            if b in (1, 3):
                send('drums', tb, st(clap(1.0), 0, 0.3), 0.55, rev=0.18)
            send('drums', tb + 0.25, st(hat(section >= 2 and b == 3, 0.9), 0.25), 0.2 if section < 2 else 0.24)
            if section >= 1:
                for s16 in (0.125, 0.375):
                    send('drums', tb + s16, st(shaker(0.7), -0.3), 0.1)
        # bass: off-beat eighths
        for b in range(4):
            send('bass', t0 + b * BEAT + 0.25, st(bass_note(root + 12, 0.22, 1.0)), 0.36)
        send('bass', t0, st(bass_note(root, 1.9, 0.9)), 0.08)
        # pads (from section 1)
        if section >= 1:
            send('pad', t0, pad_chord(voic, 1.95, v=1.0, cutoff=2200 if section < 3 else 3000, attack=0.08, release=0.25), 0.85, rev=0.35)
        # chord stabs, syncopated
        for s in (0, 3, 6, 10, 12, 14) if section >= 2 else (0, 3, 6, 10):
            for m in voic[1:]:
                send('keys', t0 + s * 0.125, pluck(m + 12, 0.3, v=0.55, bright=0.9), 0.4, rev=0.25, dly=0.15)
        # arpeggio 16ths (from section 1)
        if section >= 1:
            pat = [0, 1, 2, 3, 2, 1, 2, 3]
            for s in range(16):
                m = tones[pat[s % 8]] + (12 if (section == 3 and s % 4 == 2) else 0)
                send('keys', t0 + s * 0.125, pluck(m, 0.2, v=0.35 + 0.15 * (s % 4 == 0), bright=1.2), 0.42, rev=0.2, dly=0.22,
                     pan=0.35 * np.sin(s * 0.8))
    # lead melody over the last 8 bars of the groove (24–40 s)
    MEL = {  # (beat offset, midi, beats)
        'Bb': [(0, 77, 1), (1, 74, 0.5), (1.5, 77, 0.5), (2, 81, 1.5), (3.5, 79, 0.5)],
        'C': [(0, 79, 1), (1, 76, 0.5), (1.5, 79, 0.5), (2, 84, 1), (3, 81, 1)],
        'Am': [(0, 81, 1), (1, 79, 0.5), (1.5, 76, 0.5), (2, 72, 1.5), (3.5, 74, 0.5)],
        'Dm': [(0, 77, 1.5), (1.5, 76, 0.5), (2, 74, 1), (3, 72, 1)],
    }
    for bar in range(12, 20):
        name = chord_at(bar)
        for off, m, beats in MEL[name]:
            send('lead', bar * BAR + off * BEAT, lead(m, beats * BEAT * 0.9, 1.0), 0.45, rev=0.35, dly=0.3)
    # snare-roll fill into the break (39–40 s)
    for i in range(8):
        send('drums', 39.0 + i * 0.125, st(clap(0.5 + i * 0.07), 0, 0.3), 0.3 + i * 0.03)
    send('fx', 39.35, reverse_swell(0.6, 1.0, seed=77), 0.25)

    # ---------------- scene-change & UI sound design (8–40 s)
    send('fx', 11.65, whoosh(0.8, 500, 3500, 0.5, -0.2, seed=50), 0.4)                 # page scroll C->D
    for i, t in enumerate((12.85, 13.45, 14.05, 14.65)):                              # loupe / swatches
        send('ui', t, pop([1318.5, 1567.98, 1760.0, 2093.0][i], 1.0), 0.4, rev=0.35, pan=0.3)
        send('ui', t + 0.07, tick(3400, 0.5), 0.15, pan=0.4)
    send('ui', 15.0, bell(89, 1.0, 0.5, 0.5), 0.25, rev=0.5)
    send('fx', 15.45, reverse_swell(0.5, 1.0, seed=60), 0.3)                          # page collapses
    send('ui', 15.95, tick(2900, 0.8, 0.07), 0.3, rev=0.5)
    send('fx', 16.05, laser(0.9), 0.23, rev=0.4)                                      # drawing the M
    send('fx', 17.25, st(sub_boom(0.9, 45)), 0.6, rev=0.4)                            # chip forms
    send('ui', 17.4, bell(96, 1.4, 0.6, 1.0), 0.22, rev=0.6)
    for i in range(8):                                                                # traces
        send('ui', 17.6 + i * 0.1, zap(900 + 150 * i, 0.5), 0.1, rev=0.3, pan=(-1) ** i * 0.6)
    send('fx', 19.75, whoosh(0.3, 800, 7000, 0, 0, seed=61, peak=0.9), 0.4)          # flare
    for t in (20.72, 20.88):                                                          # AF confirm
        send('ui', t, beep(2350, 1.0, 0.05), 0.1)
    send('ui', 20.3, beep(1760, 1.0, 0.04), 0.08)
    send('fx', 21.9, whoosh(0.6, 3000, 250, 0, 0, seed=62, peak=0.3), 0.35)           # lights down
    send('ui', 22.1, shutter(1.0), 0.35, rev=0.3)
    send('ui', 22.15, pop(900, 1.0), 0.3)
    send('fx', 24.0, whoosh(0.8, 400, 2500, 0, 0, seed=63, peak=0.5), 0.2)            # sensors reveal
    send('ui', 24.55, bell(89, 1.4, 0.8, 0.4), 0.3, rev=0.7, pan=-0.85)               # spatial audio pings
    send('ui', 24.85, bell(93, 1.4, 0.8, 0.4), 0.3, rev=0.7, pan=0.85)
    send('fx', 25.4, whoosh(1.15, 2500, 6000, -0.9, 0.9, seed=64, peak=0.5), 0.3)     # LiDAR scan L->R
    for i in range(10):
        send('ui', 25.45 + i * 0.11, tick(4200, 0.4, 0.03), 0.06, pan=-0.9 + 0.2 * i)
    send('ui', 26.3, pop(1200, 1.0), 0.22)
    send('fx', 26.95, whoosh(0.8, 300, 4000, 0, 0, seed=65, peak=0.75), 0.4)          # zoom to Face ID
    for i in range(24):                                                               # ring fills
        t = 27.85 + 1.1 * (i / 24)
        send('ui', t, tick(2600 + 40 * i, 0.35, 0.025), 0.07, pan=np.sin(i / 24 * 2 * np.pi) * 0.7)
    send('ui', 29.0, bell(81, 1.6, 0.9, 0.6), 0.34, rev=0.5)                          # success
    send('ui', 29.12, bell(88, 1.6, 0.9, 0.6), 0.34, rev=0.5)
    send('fx', 29.6, whoosh(0.9, 250, 3000, 0, 0, seed=66, peak=0.6), 0.35)           # ring -> MagSafe
    send('ui', 30.5, st(sub_boom(0.6, 90)), 0.25)                                     # magnetic snap
    send('ui', 30.5, tick(1800, 1.0, 0.05), 0.35)
    send('ui', 30.56, bell(86, 1.8, 0.8, 0.7), 0.3, rev=0.5)
    send('ui', 30.68, bell(93, 1.8, 0.8, 0.7), 0.3, rev=0.5)
    send('ui', 31.6, pop(1400, 1.0), 0.25, pan=-0.5)
    send('fx', 32.85, whoosh(0.7, 2500, 300, 0, 0, seed=67, peak=0.3), 0.35)          # dim to night
    send('ui', 33.2, pop(620, 1.0), 0.35)                                             # Dynamic Island
    send('ui', 33.45, bell(86, 1.2, 0.6, 0.4), 0.18, rev=0.6)
    for i in range(20):                                                               # count to 20
        t = 34.05 + 0.9 * (1 - (1 - (i + 1) / 20) ** (1 / 3))
        send('ui', t, tick(1800 + 70 * i, 0.5, 0.03), 0.09)
    send('fx', 35.75, whoosh(0.7, 3000, 500, 0, 0, seed=68, peak=0.4), 0.35)          # into the bento
    for i in range(9):
        send('ui', 36.1 + i * 0.06, pop(800 + 90 * i, 1.0), 0.14, pan=(-1) ** i * 0.5)

    # ---------------- 40–44 s: one more thing
    send('pad', 40.3, pad_chord(CH['Dm9'][1], 1.3, v=0.6, cutoff=1400, attack=0.8, release=0.6), 1.0, rev=0.6)
    send('keys', 40.35, bell(62, 2.5, 0.8, 0.3), 0.55, rev=0.7)
    send('fx', 41.6, riser(1.4, 200, 6000, seed=9), 0.45, rev=0.2)
    for i in range(12):
        send('ui', 41.95 + i * 0.085, tick(1500 + 90 * i, 0.5, 0.03), 0.08)
    send('keys', 43.0, pluck(70, 0.6, 1.0, 1.0) + pluck(74, 0.6, 1.0, 1.0) + pluck(77, 0.6, 1.0, 1.0), 0.5, rev=0.4)
    for b in range(2):                                                                # half bar of groove
        tb = 43.0 + b * BEAT
        send('kick', tb, st(kick(1.0)), 0.95)
        kicks.append(tb)
        send('drums', tb + 0.25, st(hat(False, 0.9)), 0.22)
        send('bass', tb + 0.25, st(bass_note(46, 0.22)), 0.36)
    send('drums', 43.5, st(clap(1.0), 0, 0.3), 0.42, rev=0.2)
    send('fx', 43.9, whoosh(0.45, 4000, 600, 0, 0, seed=70, peak=0.3), 0.3)

    # ---------------- 44–50 s: finale
    for bar in (22, 23):
        t0 = bar * BAR
        root, voic, tones = CH[chord_at(bar)]
        send('pad', t0, pad_chord(voic, 1.95, v=1.0, cutoff=2800, attack=0.1, release=0.3), 0.85, rev=0.4)
        for b in range(4):
            tb = t0 + b * BEAT
            send('kick', tb, st(kick(0.95)), 0.78)
            kicks.append(tb)
            if b in (1, 3):
                send('drums', tb, st(clap(0.9), 0, 0.3), 0.36, rev=0.2)
            send('drums', tb + 0.25, st(hat(b == 3, 0.8)), 0.2)
            send('bass', tb + 0.25, st(bass_note(root + 12, 0.22)), 0.33)
        send('bass', t0, st(bass_note(root, 1.9, 0.9)), 0.08)
        for s in range(16):
            send('keys', t0 + s * 0.125, pluck(tones[[0, 1, 2, 3, 2, 1, 2, 3][s % 8]], 0.2, v=0.35, bright=1.1), 0.4, rev=0.25, dly=0.2)
    for off, m, beats in [(0, 77, 1), (1, 81, 1), (2, 84, 2)]:
        send('lead', 44.0 + off * BEAT, lead(m, beats * BEAT * 0.9), 0.42, rev=0.4, dly=0.3)
    for off, m, beats in [(0, 84, 1), (1, 79, 1), (2, 76, 1), (3, 79, 1)]:
        send('lead', 46.0 + off * BEAT, lead(m, beats * BEAT * 0.9), 0.42, rev=0.4, dly=0.3)
    send('fx', 47.4, reverse_swell(0.62, 1.0, seed=80), 0.3)
    # the resolution: Fmaj9 on the logo
    send('kick', 48.0, st(kick(1.0)), 0.9)
    send('fx', 48.0, impact(0.6), 0.45, rev=0.5)
    send('drums', 48.0, crash(0.7, 2.2), 0.3, rev=0.4)
    send('pad', 48.0, pad_chord(CH['F'][1], 1.2, v=1.0, cutoff=2600, attack=0.02, release=1.4), 1.0, rev=0.6)
    send('bass', 48.0, st(bass_note(41, 1.8, 0.9)), 0.3)
    for j, m in enumerate([65, 72, 76, 79, 84]):
        send('keys', 48.02 + j * 0.035, bell(m, 2.6, 0.9, 0.6), 0.34, rev=0.6, dly=0.2, pan=(j - 2) * 0.25)
    send('fx', 48.45, purr(1.55, 1.0), 0.16)
    return kicks


def master(kicks):
    # sidechain: duck bass/pad/keys under each kick
    sc = np.ones(N)
    t = tt(N)
    for k in kicks:
        i = int(k * SR)
        n = min(int(0.3 * SR), N - i)
        if n <= 0:
            continue
        tk = t[:n]
        sc[i:i + n] = np.minimum(sc[i:i + n], 1 - 0.55 * np.exp(-tk / 0.11) * np.minimum(1, tk / 0.004 + 0.6))
    for k in ('bass', 'pad', 'keys', 'lead'):
        B[k].x *= sc[:, None] if k != 'lead' else (0.5 + 0.5 * sc)[:, None]
    # delay and reverb returns
    dly = pingpong(B['dly'].x)
    wet = ss.fftconvolve(B['rev'].x[:, 0], REV[:, 0])[:N], ss.fftconvolve(B['rev'].x[:, 1], REV[:, 1])[:N]
    wet = np.stack(wet, 1)
    wet = hp(wet, 180)
    mix = (B['kick'].x * 1.0 + B['drums'].x * 1.0 + hp(B['bass'].x, 30) * 1.0 + B['pad'].x * 1.0 + B['keys'].x * 0.9
           + B['lead'].x * 0.9 + B['fx'].x * 1.0 + B['ui'].x * 1.0 + wet * 0.32 + dly * 0.22)
    mix = mix[: int(DUR * SR)]
    mix = hp(mix, 32, 2)
    mix = shelf(mix, 110, -4.0, 'low')
    mix = peak_eq(mix, 2800, 2.0, 0.8)
    mix = shelf(mix, 9000, 1.5, 'high')
    mix *= 0.12 / np.sqrt(np.mean(mix ** 2))
    # gentle glue compression (feed-forward, RMS)
    env = np.sqrt(lp(np.mean(mix ** 2, 1), 8, 1).clip(1e-12))
    thr = 0.2
    gain = np.where(env > thr, (env / thr) ** (1 / 2.5 - 1), 1.0)
    mix *= gain[:, None]
    # final fade in/out
    tt_ = tt(len(mix))
    mix *= np.minimum(1, tt_ / 0.01)[:, None]
    mix *= np.clip((DUR - tt_) / 0.35, 0, 1)[:, None]
    return mix


REV = reverb_ir()

if __name__ == '__main__':
    out = sys.argv[1] if len(sys.argv) > 1 else 'soundtrack.wav'
    kicks = build()
    mix = master(kicks)
    try:
        import pyloudnorm as pyln
        meter = pyln.Meter(SR)
        lufs = meter.integrated_loudness(mix)
        mix *= 10 ** ((-15.0 - lufs) / 20)
        print('loudness before', round(lufs, 2), 'LUFS -> -15.0')
    except Exception as e:  # pragma: no cover
        print('pyloudnorm unavailable', e)
        mix *= 0.5 / np.abs(mix).max()
    # look-ahead peak limiter; -2 dBFS leaves room for AAC inter-sample overs
    ceil = 10 ** (-2.0 / 20)
    need = np.minimum(1.0, ceil / np.maximum(np.abs(mix).max(1), 1e-9))
    w = int(0.004 * SR)
    g = minimum_filter1d(need, size=2 * w + 1)
    a = 1 - np.exp(-1 / (0.03 * SR))
    g = ss.lfilter([a], [1, -(1 - a)], g, zi=[g[0] * (1 - a)])[0]
    g = np.minimum(g, minimum_filter1d(need, size=2 * w + 1))
    print('max gain reduction', round(-20 * np.log10(g.min()), 2), 'dB')
    mix *= g[:, None]
    print('peak', round(20 * np.log10(np.abs(mix).max()), 2), 'dBFS')
    wavfile.write(out, SR, mix.astype(np.float32))
    print('wrote', out, mix.shape)
