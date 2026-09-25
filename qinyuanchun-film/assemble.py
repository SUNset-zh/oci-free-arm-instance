#!/usr/bin/env python3
"""成片：按时间线把各镜头（已调色、1080×1920 的 PNG）接起来，镜头之间做溶解过渡，片尾叠字、淡出，加细颗粒，
与配乐一起编码成 H.264。

    python3 assemble.py 镜头根目录 配乐.wav 输出.mp4 [--crf 16] [--preview 秒起,秒止] [--bitrate 3900k]

时间线（秒）：每个镜头的起点与时长对应朗诵分句；渲染时两头都多留了“把手”，用于溶解。"""
import os
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

FPS = 24
W, H = 1080, 1920
TOTAL = 60.0
FF = '/usr/local/lib/python3.11/dist-packages/imageio_ffmpeg/binaries/ffmpeg-linux-x86_64-v7.0.2'
FONTS = '/tmp/claude-0/-home-user-oci-free-arm-instance/33674d5b-35e4-5b5a-b79d-ec7ad6b62fa3/scratchpad/fonts'

# (目录, 源帧所在子目录与文件名模板, 片中起点, 时长, 渲染帧数, 与下一镜头之间的溶解时长)
SHOTS = [
    ('s0', 'final/f{:04d}.png', 0.0, 3.6, 98, .5),
    ('s1b', 'graded/g{:04d}.png', 3.6, 6.4, 178, .5),
    ('s2', 'graded/g{:04d}.png', 10.0, 3.1, 108, .5),       # 切到黄河落在“惟余莽莽；”的停顿里
    ('s3', 'graded/g{:04d}.png', 13.1, 4.5, 125, .6),
    ('s4', 'graded/g{:04d}.png', 17.6, 6.8, 185, .5),
    ('s5', 'graded/g{:04d}.png', 24.4, 5.6, 154, .5),
    ('s6', 'graded/g{:04d}.png', 30.0, 6.4, 173, .7),
    ('s7', 'graded/g{:04d}.png', 36.4, 8.9, 233, .6),
    ('s8', 'graded/g{:04d}.png', 45.3, 7.0, 187, .8),       # 雕飞进云里：溶解长一点（S9 开头是均匀的云内）
    ('s9', 'graded/g{:04d}.png', 52.3, 7.7, 194, 0.0),
]


def pre_handle(i):
    name, pat, st, du, n, x = SHOTS[i]
    if i == 0:
        return 0.0
    if i == len(SHOTS) - 1:
        return n / FPS - du
    return (n / FPS - du) / 2


def shot_weights(t):
    """t 时刻参与画面的镜头及其权重。"""
    out = []
    for i, (name, pat, st, du, n, x) in enumerate(SHOTS):
        xin = SHOTS[i - 1][5] if i > 0 else 0.0
        a0, a1 = st - xin / 2, st + du + x / 2
        if not (a0 <= t < a1) and not (i == len(SHOTS) - 1 and t >= a0):
            continue
        w = 1.0
        if xin > 0 and t < st + xin / 2:
            u = (t - (st - xin / 2)) / xin; w *= u * u * (3 - 2 * u)
        if x > 0 and t > st + du - x / 2:
            u = (t - (st + du - x / 2)) / x; w *= 1 - u * u * (3 - 2 * u)
        out.append((i, w))
    s = sum(w for _, w in out)
    return [(i, w / s) for i, w in out] if s > 0 else out


_cache = {}


def load(root, i, t):
    name, pat, st, du, n, x = SHOTS[i]
    f = int(round((t - (st - pre_handle(i))) * FPS)) + 1
    f = min(max(f, 1), n)
    path = os.path.join(root, name, pat.format(f))
    if not os.path.exists(path):
        # 预览时允许缺帧：找最近的已有帧
        for df in range(1, n):
            for g in (f - df, f + df):
                p2 = os.path.join(root, name, pat.format(g))
                if 1 <= g <= n and os.path.exists(p2):
                    path = p2; break
            else:
                continue
            break
        else:
            return np.zeros((H, W, 3), np.float32)
    if path not in _cache:
        if len(_cache) > 8:
            _cache.pop(next(iter(_cache)))
        im = Image.open(path).convert('RGB')
        if im.size != (W, H):
            im = im.resize((W, H), Image.LANCZOS)
        _cache[path] = np.asarray(im, np.float32) / 255.0
    return _cache[path]


def end_title(t):
    """片尾：57.0s 起淡入“沁园春 · 雪 / 毛泽东 · 一九三六年二月”，随画面淡出。"""
    a = np.clip((t - 57.0) / .9, 0, 1)
    if a <= 0:
        return None, 0.0
    a = a * a * (3 - 2 * a)
    im = Image.new('L', (W, H), 0)
    d = ImageDraw.Draw(im)
    f1 = ImageFont.truetype(os.path.join(FONTS, 'NotoSerifSC-500.ttf'), 92)
    f2 = ImageFont.truetype(os.path.join(FONTS, 'NotoSansSC-300.ttf'), 36)
    chars = list('沁园春 · 雪')
    widths = [d.textlength(c, font=f1) for c in chars]
    gap = 22
    x = (W - (sum(widths) + gap * (len(chars) - 1))) / 2; y = H * .26 + (1 - a) * 10
    for c, wd in zip(chars, widths):
        d.text((x, y), c, font=f1, fill=255); x += wd + gap
    sub = '毛泽东  ·  一九三六年二月'
    sw = d.textlength(sub, font=f2)
    d.text(((W - sw) / 2, y + 150), sub, font=f2, fill=215)
    arr = np.asarray(im, np.float32) / 255.0
    shadow = np.asarray(im.filter(ImageFilter.GaussianBlur(10)), np.float32) / 255.0
    return (arr, shadow), a


def frame(root, k, rng):
    t = k / FPS
    img = np.zeros((H, W, 3), np.float32)
    for i, w in shot_weights(t):
        img += load(root, i, t) * w
    tl, ta = end_title(t)
    if tl is not None:
        arr, sh = tl
        img = img * (1 - .45 * ta * sh[..., None])                      # 字后面一层很淡的暗影，保证可读
        img = img * (1 - ta * arr[..., None]) + ta * arr[..., None] * np.array([.97, .97, .96])
    # 片尾淡出到黑
    img *= 1 - np.clip((t - 59.25) / .7, 0, 1)
    # 细颗粒（亮度噪声，暗部略多）
    g = rng.standard_normal((H // 2, W // 2)).astype(np.float32)
    g = np.asarray(Image.fromarray(g).resize((W, H), Image.BILINEAR))
    lum = img.mean(-1, keepdims=True)
    img = img + g[..., None] * (1.4 / 255) * (1.2 - lum)
    return (np.clip(img, 0, 1) * 255 + .5).astype(np.uint8)


def main():
    a = sys.argv[1:]
    root, wav, out = a[0], a[1], a[2]
    opt = lambda k, d=None: a[a.index(k) + 1] if k in a else d
    t0, t1 = 0.0, TOTAL
    if opt('--preview'):
        t0, t1 = map(float, opt('--preview').split(','))
    k0, k1 = int(round(t0 * FPS)), int(round(t1 * FPS))
    venc = ['-c:v', 'libx264', '-preset', 'slow', '-pix_fmt', 'yuv420p', '-profile:v', 'high', '-tune', 'film']
    if opt('--bitrate'):
        venc += ['-b:v', opt('--bitrate'), '-maxrate', opt('--bitrate'), '-bufsize', '8M']
    else:
        venc += ['-crf', opt('--crf', '16')]
    cmd = [FF, '-y', '-v', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-',
           '-ss', f'{t0}', '-t', f'{t1 - t0}', '-i', wav] + venc + ['-c:a', 'aac', '-b:a', '256k', '-movflags', '+faststart',
                                                                    '-shortest', out]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    rng = np.random.default_rng(7)
    for k in range(k0, k1):
        p.stdin.write(frame(root, k, rng).tobytes())
        if k % 48 == 0:
            print('frame', k, flush=True)
    p.stdin.close(); p.wait()
    print('->', out)


if __name__ == '__main__':
    main()
