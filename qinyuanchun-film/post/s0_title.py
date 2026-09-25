"""S0 片头（纯后期合成，不经过 Blender）：暗处飘落的六角雪花 + 标题。

    python3 post/s0_title.py 输出目录 [--frames a,b,c]

- 雪花形状用 shots/s0_snowflakes.crystal() 生成（星状枝晶，六重对称），脊线处更亮（冰晶内部散射）；
- 每片雪花有三维位置：按真实透视缩放，按弥散圆做圆盘虚化（前后景光斑），景深干净无噪点；
- 主角雪花在对焦面上缓缓旋转，最后飘向镜头、越来越虚、化成一团柔光，接 S1；
- 标题“沁园春·雪”与“毛泽东”在朗诵念出题目时淡入，然后淡出。"""
import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage, signal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

W, H = 1080, 1920
FPS = 24
NF = 98
FONTS = '/tmp/claude-0/-home-user-oci-free-arm-instance/33674d5b-35e4-5b5a-b79d-ec7ad6b62fa3/scratchpad/fonts'
LENS, SENSOR = 60.0, 36.0
FOCAL_PX = LENS / SENSOR * H
FOCUS = .12
COC_K = 4.2                       # 弥散圆半径（像素）= COC_K * |1/z - 1/focus|（z 以米计）


def crystal(seed, N=512):
    # 与 shots/s0_snowflakes.crystal 相同（那边依赖 bpy，这里复制一份纯 numpy 版本）
    rng = np.random.default_rng(seed)
    y, x = (np.mgrid[0:N, 0:N] - N / 2 + .5) / (N / 2)
    r = np.hypot(x, y); th = np.arctan2(y, x)
    a = np.mod(th, math.pi / 3); a = np.minimum(a, math.pi / 3 - a)
    u = r * np.cos(a); v = r * np.sin(a)
    arm_w = rng.uniform(.035, .06)
    alpha = ((v < arm_w * (1 - .5 * u)) & (u < .96)).astype(float)
    hgt = np.clip(1 - v / (arm_w + 1e-6), 0, 1) * (u < .96)
    for k in range(rng.integers(4, 7)):
        u0 = rng.uniform(.25, .85) if k else rng.uniform(.3, .45)
        L = (1 - u0) * rng.uniform(.35, .7); w = arm_w * rng.uniform(.5, .8)
        du = u - u0; dv = v
        s_ = du * .5 + dv * .866; t_ = np.abs(-du * .866 + dv * .5)
        side = (s_ > 0) & (s_ < L) & (t_ < w * (1 - .6 * s_ / max(L, 1e-3)))
        alpha = np.maximum(alpha, side)
        hgt = np.maximum(hgt, np.clip(1 - t_ / (w + 1e-6), 0, 1) * side * .8)
    hexr = rng.uniform(.14, .24)
    hx = r * np.cos(np.mod(th, math.pi / 3) - math.pi / 6) / math.cos(math.pi / 6)
    plate = hx < hexr
    alpha = np.maximum(alpha, plate)
    ring = np.abs(hx - hexr * .62) < .012
    hgt = np.maximum(hgt, plate * .5 + ring * .9)
    tip = np.hypot(u - .9, v) < rng.uniform(.05, .09)
    alpha = np.maximum(alpha, tip)
    alpha = ndimage.gaussian_filter(alpha, 1.0)
    hgt = ndimage.gaussian_filter(hgt * alpha, 1.5)
    return alpha.astype(np.float32), hgt.astype(np.float32)


def sprite(seed, N):
    A, Hh = crystal(seed, N)
    I = A * (.3 + 1.6 * Hh)                                  # 脊线更亮
    return I


def disc(r):
    r = max(r, .5)
    n = int(math.ceil(r))
    y, x = np.mgrid[-n:n + 1, -n:n + 1]
    k = np.clip(r + .5 - np.hypot(x, y), 0, 1)
    k *= 1 + .25 * np.clip(np.hypot(x, y) / r, 0, 1) ** 4   # 镜头光斑边缘略亮
    return k / k.sum()


def place(canvas, img, cx, cy):
    h, w = img.shape
    x0, y0 = int(round(cx - w / 2)), int(round(cy - h / 2))
    xa, ya = max(0, x0), max(0, y0); xb, yb = min(W, x0 + w), min(H, y0 + h)
    if xa >= xb or ya >= yb:
        return
    canvas[ya:yb, xa:xb] += img[ya - y0:yb - y0, xa - x0:xb - x0]


def flake_image(base, size_px, rot_deg, tilt, coc):
    """把雪花贴图缩放到 size_px、旋转、按倾斜压扁，再做圆盘虚化。"""
    size_px = max(size_px, 2.0)
    im = Image.fromarray(base).resize((int(size_px), max(1, int(size_px * max(.25, abs(math.cos(tilt)))))), Image.LANCZOS)
    im = im.rotate(rot_deg, resample=Image.BICUBIC, expand=True)
    a = np.asarray(im, np.float32)
    if coc > 1.0:
        pad = int(math.ceil(coc)) + 2
        a = np.pad(a, pad)
        a = signal.fftconvolve(a, disc(coc), mode='same')
    return np.maximum(a, 0)


def title_layer(t):
    """标题：0.7s 起淡入，2.75s 起淡出。"""
    a = np.clip((t - .7) / .6, 0, 1) * np.clip((3.3 - t) / .55, 0, 1)
    a = a * a * (3 - 2 * a)
    if a <= 0:
        return None, 0.0
    im = Image.new('L', (W, H), 0)
    d = ImageDraw.Draw(im)
    f1 = ImageFont.truetype(os.path.join(FONTS, 'NotoSerifSC-500.ttf'), 104)
    f2 = ImageFont.truetype(os.path.join(FONTS, 'NotoSansSC-300.ttf'), 40)
    text = '沁园春 · 雪'
    # 字距：逐字排
    chars = list(text)
    widths = [d.textlength(c, font=f1) for c in chars]
    gap = 26
    total = sum(widths) + gap * (len(chars) - 1)
    x = (W - total) / 2; y = H * .43
    rise = (1 - np.clip((t - .7) / 1.0, 0, 1)) * 14             # 淡入时微微上浮
    for c, wdt in zip(chars, widths):
        d.text((x, y + rise), c, font=f1, fill=255)
        x += wdt + gap
    sub = '毛  泽  东'
    sw = d.textlength(sub, font=f2)
    d.text(((W - sw) / 2, y + 170 + rise), sub, font=f2, fill=200)
    arr = np.asarray(im, np.float32) / 255.0
    glow = ndimage.gaussian_filter(arr, 6) * .35
    return np.clip(arr + glow, 0, 1.2), a


def main(out, frames=None):
    os.makedirs(out, exist_ok=True)
    rng = np.random.default_rng(1936)
    sprites = [sprite(100 + k, 1024 if k == 0 else 384) for k in range(7)]
    sprites = [(s / s.max() * 255).astype(np.uint8) for s in sprites]
    flakes = []
    for i in range(40):
        if i == 0:
            flakes.append(dict(k=0, size=.0036, hero=True))
            continue
        if i <= 9:
            dist = rng.uniform(.105, .15)
        else:
            dist = rng.uniform(.035, .075) if i % 2 else rng.uniform(.22, .7)
        flakes.append(dict(k=i % 7, size=rng.uniform(.0026, .0038), dist=dist,
                           x0=rng.uniform(-.2, .2) * dist, z0=rng.uniform(-.25, .55) * dist,
                           vx=rng.uniform(-.003, .003) * dist / .2, vz=-rng.uniform(.004, .008) * dist / .2,
                           rot0=rng.uniform(0, 360), wr=rng.uniform(-25, 25), tilt0=rng.uniform(0, 6.28), wt=rng.uniform(-.8, .8)))
    yy, xx = np.mgrid[0:H, 0:W]
    bg = np.zeros((H, W, 3), np.float32)
    g = np.clip(yy / H, 0, 1)[..., None]
    bg[:] = np.array([.004, .007, .02]) * (1 - g) + np.array([.02, .035, .075]) * g
    vign = 1 - .45 * np.clip((np.hypot((xx - W / 2) / (W / 2), (yy - H / 2) / (H / 2)) - .55) / .8, 0, 1) ** 1.5
    col = np.array([.72, .84, 1.0], np.float32)
    for f in (frames or range(1, NF + 1)):
        t = (f - 1) / FPS
        acc = np.zeros((H, W), np.float32)
        for fl in flakes:
            if fl.get('hero'):
                u = max(0.0, (t - 2.3) / 1.35); u = u * u * (3 - 2 * u)
                z = .12 - (.12 - .012) * u
                x = .0015 * (1 - u); zc = (.012 - .0015 * t) * (1 - u)
                rot = 20 * t; tilt = .3 * math.sin(.8 * t)
            else:
                z = fl['dist']; x = fl['x0'] + fl['vx'] * t; zc = fl['z0'] + fl['vz'] * t
                rot = fl['rot0'] + fl['wr'] * t; tilt = fl['tilt0'] + fl['wt'] * t
            sx = W / 2 + x / z * FOCAL_PX; sy = H / 2 - zc / z * FOCAL_PX
            size = fl['size'] / z * FOCAL_PX
            coc = COC_K * abs(1 / z - 1 / FOCUS)
            if sx < -size - coc or sx > W + size + coc or sy < -size - coc or sy > H + size + coc:
                continue
            img = flake_image(sprites[fl['k']], size, rot, tilt, coc) / 255.0
            # 能量守恒已由卷积核归一化保证；远处的雪花略暗
            gain = 1.0 if fl.get('hero') else np.clip(.12 / z, .35, 1.4)
            place(acc, img * gain * .9, sx, sy)
        rgb = bg + acc[..., None] * col
        # 柔光：亮处向外晕开
        glow = ndimage.gaussian_filter(acc, 14)[..., None] * col * .5 + ndimage.gaussian_filter(acc, 60)[..., None] * col * .3
        rgb = rgb + glow
        tl, ta = title_layer(t)
        if tl is not None:
            rgb = rgb * (1 - .85 * ta * np.clip(tl, 0, 1)[..., None]) + (tl * ta)[..., None] * np.array([.95, .97, 1.0])
        # 片尾：主角雪花贴近镜头，化成一片冷白柔光（接 S1）
        wt = np.clip((t - 3.25) / .8, 0, 1) ** 2
        rgb = rgb * (1 - wt * .6) + np.array([.8, .88, 1.0]) * wt * .6
        rgb = rgb * vign[..., None]
        disp = np.clip(rgb, 0, 1) ** (1 / 1.05)
        Image.fromarray((disp * 255 + .5).astype(np.uint8)).save(os.path.join(out, f'f{f:04d}.png'))
        print('s0', f, flush=True)


if __name__ == '__main__':
    fr = None
    if '--frames' in sys.argv:
        fr = [int(v) for v in sys.argv[sys.argv.index('--frames') + 1].split(',')]
    main(sys.argv[1], fr)
