"""Cut the kitten out of each photo with BiRefNet (via rembg) -> src/masks/<name>_mask.png.

The masks are committed, so this only needs to run when the photos change.
BiRefNet needs ~1 GB of model weights; rembg downloads them to $U2NET_HOME on first use.
One process per photo keeps onnxruntime's memory arena from piling up.
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PHOTOS = ['p1_loaf', 'p2_keyboard', 'p3_lookback']


def one(name):
    from PIL import Image
    from rembg import new_session, remove
    session = new_session('birefnet-general')
    im = Image.open(os.path.join(ROOT, 'src', 'photos', name + '.jpg')).convert('RGB')
    mask = remove(im, session=session, only_mask=True, post_process_mask=False)
    out = os.path.join(ROOT, 'src', 'masks', name + '_mask.png')
    mask.save(out)
    print('wrote', out, mask.size)


if __name__ == '__main__':
    if len(sys.argv) > 1:
        one(sys.argv[1])
    else:
        os.makedirs(os.path.join(ROOT, 'src', 'masks'), exist_ok=True)
        for n in PHOTOS:
            subprocess.run([sys.executable, __file__, n], check=True)
