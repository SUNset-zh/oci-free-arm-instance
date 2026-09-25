"""Prepare every image asset the keynote page needs.

Inputs : src/photos/*.jpg (the three original photos)
         src/masks/*_mask.png (BiRefNet alpha mattes, see tools/segment.py)
Outputs: web/assets/*  (graded photos, cutouts, super-resolved macro crops)
         web/assets/palette.json

Super resolution uses Real-ESRGAN (realesr-general-x4v3) converted to ONNX by
tools/esrgan_onnx.py; set MODELS_DIR to the folder holding realesr-x4v3.onnx.
"""
import json, os, sys
import numpy as np
from PIL import Image, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'src')
OUT = os.path.join(ROOT, 'web', 'assets')
MODELS = os.environ.get('MODELS_DIR', os.path.join(ROOT, 'build', 'models'))
os.makedirs(OUT, exist_ok=True)

# ---------------------------------------------------------------- helpers
def load(name):
    """Load a photo and convert it from its embedded profile (iPhone: Display P3) to sRGB."""
    im = Image.open(os.path.join(SRC, 'photos', name + '.jpg'))
    icc = im.info.get('icc_profile')
    im = im.convert('RGB')
    if icc:
        from io import BytesIO
        from PIL import ImageCms
        src = ImageCms.ImageCmsProfile(BytesIO(icc))
        dst = ImageCms.createProfile('sRGB')
        im = ImageCms.profileToProfile(im, src, dst, renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC, outputMode='RGB')
    return im

def mask(name):
    return Image.open(os.path.join(SRC, 'masks', name + '_mask.png')).convert('L')

def f32(im):
    return np.asarray(im).astype(np.float32) / 255.0

def u8(a):
    return Image.fromarray((np.clip(a, 0, 1) * 255 + 0.5).astype(np.uint8))

def grade(im, contrast=0.22, sat=1.08, warmth=0.0, lift=0.0):
    """Gentle keynote grade: soft S-curve, a touch of saturation."""
    a = f32(im)
    s = a * a * (3 - 2 * a)                     # smoothstep S-curve
    a = a + (s - a) * contrast
    l = (a * np.array([0.2126, 0.7152, 0.0722], np.float32)).sum(-1, keepdims=True)
    a = l + (a - l) * sat
    if warmth:
        a = a * np.array([1 + warmth, 1, 1 - warmth], np.float32)
    if lift:
        a = a * (1 - lift) + lift
    return u8(a)

_sess = None
def esrgan(im, tile=320, pad=16):
    """4x Real-ESRGAN (tiled)."""
    global _sess
    import onnxruntime as ort
    if _sess is None:
        o = ort.SessionOptions(); o.intra_op_num_threads = os.cpu_count() or 4
        _sess = ort.InferenceSession(os.path.join(MODELS, 'realesr-x4v3.onnx'), o,
                                     providers=['CPUExecutionProvider'])
    a = f32(im)
    H, W, _ = a.shape
    out = np.zeros((H * 4, W * 4, 3), np.float32)
    for y0 in range(0, H, tile):
        for x0 in range(0, W, tile):
            y1, x1 = min(y0 + tile, H), min(x0 + tile, W)
            ya, xa = max(0, y0 - pad), max(0, x0 - pad)
            yb, xb = min(H, y1 + pad), min(W, x1 + pad)
            t = np.ascontiguousarray(a[ya:yb, xa:xb].transpose(2, 0, 1)[None])
            r = _sess.run(None, {'input': t})[0][0].transpose(1, 2, 0)
            oy, ox = (y0 - ya) * 4, (x0 - xa) * 4
            out[y0 * 4:y1 * 4, x0 * 4:x1 * 4] = r[oy:oy + (y1 - y0) * 4, ox:ox + (x1 - x0) * 4]
    return u8(out)

def superres(im, size, mix=0.78):
    """Upscale `im` to `size` (w,h): ESRGAN detail blended with Lanczos texture."""
    sr = esrgan(im).resize(size, Image.LANCZOS)
    lz = im.resize(size, Image.LANCZOS)
    return Image.blend(lz, sr, mix)

def save_jpg(im, name, q=90):
    im.save(os.path.join(OUT, name), quality=q, optimize=True, progressive=True)
    print('  ', name, im.size)

def save_webp(im, name, q=90):
    im.save(os.path.join(OUT, name), quality=q, method=6)
    print('  ', name, im.size, im.mode)

def decontaminate(rgb, alpha, radius=6):
    """Pull edge colours from the opaque interior so fur edges carry no background spill."""
    a = f32(alpha)[..., None]
    c = f32(rgb)
    solid = (a > 0.92).astype(np.float32)
    num = u8(np.clip(c * solid, 0, 1)).filter(ImageFilter.GaussianBlur(radius))
    den = u8(np.repeat(solid, 3, -1)).filter(ImageFilter.GaussianBlur(radius))
    est = f32(num) / np.maximum(f32(den), 1e-3)
    w = np.clip((0.92 - a) / 0.92, 0, 1) * (f32(den)[..., :1] > 0.02)
    return u8(c * (1 - w) + est * w)

def cutout(img, m, box, scale=1.0, sr=False):
    """RGBA cutout of `box` from img using matte m, optionally super-resolved."""
    rgb = img.crop(box); al = m.crop(box)
    # tighten the matte slightly: gamma lifts soft fur, clamps haze
    a = f32(al)
    a = np.clip((a - 0.04) / 0.92, 0, 1) ** 0.9
    al = u8(a)
    rgb = decontaminate(rgb, al)
    if scale != 1.0:
        size = (round(rgb.size[0] * scale), round(rgb.size[1] * scale))
        rgb = superres(rgb, size) if sr else rgb.resize(size, Image.LANCZOS)
        al = al.resize(size, Image.LANCZOS)
    out = rgb.convert('RGBA'); out.putalpha(al)
    return out

def mean_color(img, box):
    a = f32(img.crop(box)).reshape(-1, 3)
    return '#%02x%02x%02x' % tuple(int(v * 255 + .5) for v in a.mean(0))

# ------------------------------------------------------------------- main
def main():
    p1, p2, p3 = load('p1_loaf'), load('p2_keyboard'), load('p3_lookback')
    m1, m3 = mask('p1_loaf'), mask('p3_lookback')
    g1, g2, g3 = grade(p1, contrast=0.20, sat=1.06), grade(p2, contrast=0.18, sat=1.05), grade(p3, contrast=0.20, sat=1.08)

    print('graded full photos')
    save_jpg(g1, 'p1_full.jpg', 90)
    save_jpg(g2, 'p2_full.jpg', 90)
    save_jpg(g3, 'p3_full.jpg', 90)

    print('cutouts')
    save_webp(cutout(g1, m1, (200, 250, 2576, 1560)), 'p1_cut.webp', 92)          # origin (200,250)
    save_webp(cutout(g3, m3, (470, 590, 1150, 2420), 2.0, sr=True), 'p3_cut.webp', 92)  # origin (470,590) x2

    print('macro crops (super-resolved)')
    save_jpg(superres(g3.crop((858, 765, 1088, 995)), (943, 943)), 'm_eye.jpg', 92)       # x4.1
    save_jpg(superres(g2.crop((980, 1000, 1380, 1850)), (640, 1360)), 'm_stripes.jpg', 92)  # x1.6
    save_jpg(superres(g2.crop((520, 1930, 860, 2160)), (1156, 782)), 'm_beans.jpg', 92)    # x3.4
    save_jpg(superres(g1.crop((1360, 1180, 1700, 1500)), (1054, 992)), 'm_nose.jpg', 92)   # x3.1

    print('scene crops (super-resolved)')
    # eyes / night-mode close-up: p3 (740..1230, 460..1300) at x3
    save_jpg(superres(g3.crop((740, 460, 1230, 1300)), (1470, 2520)), 'p3_face3x.jpg', 90)
    # forehead / M-chip push-in: p1 (1100..2000, 300..1450) at x2.2
    save_jpg(superres(g1.crop((1100, 300, 2000, 1450)), (1980, 2530)), 'p1_face22.jpg', 90)
    # ear close-up for sensors / bento: p1 (860..1360, 260..960) at x2
    save_jpg(superres(g1.crop((860, 260, 1360, 960)), (1000, 1400)), 'm_ear.jpg', 90)

    pal = {
        'tabby': mean_color(g3, (600, 1150, 760, 1350)),
        'cream': mean_color(g3, (950, 1150, 1000, 1300)),
        'pink': mean_color(g1, (1500, 1290, 1560, 1330)),
        'bean': mean_color(g2, (640, 2030, 700, 2060)),
        'amber': mean_color(g3, (938, 878, 946, 890)),
        'amber2': mean_color(g3, (1034, 860, 1042, 872)),
    }
    json.dump(pal, open(os.path.join(OUT, 'palette.json'), 'w'), indent=1)
    print('palette', pal)

if __name__ == '__main__':
    main()
