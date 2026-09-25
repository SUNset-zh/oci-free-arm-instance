"""天山主峰群的地形规格：真实 DEM（汗腾格里一带，SRTM 30 m）+ 程序化金字塔主峰（原数据峰顶有大片空洞）。

各镜头共用同一套规格，只是最精细一级的范围随机位而变：
    spec(fine=dict(ex=.., ey=.., cx=.., cy=.., cell=..))
"""
import json
import os

from common import tcache

LON, LAT = 80.175, 42.211
PEAK = {"x": -250, "y": -600, "h0": 7010,
        "faces": [[15, 2600, 1500, 0.2], [100, 2300, 1700, 0.2], [195, 2500, 1600, 0.25], [285, 2200, 1900, 0.2]],
        "warp": 450, "warp_l": 3500, "rough": 90, "rough_l": 1600, "blend": 180}
TERRACE = {"step": 45, "amount": 0.5, "slope0": 0.85, "slope1": 1.4, "warp": 1.8, "dip": 0.12, "dip_az": 40}


def spec(fine=None, mid=None, cam=(0, 0), terrace=None, mat=None):
    fine = dict(dict(ex=8000, ey=8000, cx=-250, cy=-600, cell=5), **(fine or {}))
    mid = dict(dict(ex=26000, ey=26000, cx=2000, cy=-3000, cell=12), **(mid or {}))
    ter = dict(TERRACE, **(terrace or {}))
    mt = dict({"slope_lo": .38, "slope_hi": .55, "flute": .12, "n1": .12, "n2": .08}, **(mat or {}))
    return {"lon": LON, "lat": LAT, "cam": list(cam), "peak": PEAK, "mat": mt,
            "levels": [
                dict(fine, zoom=13, terrace=ter, detail={"noise": 2.0, "drops_per_cell": 1.2, "talus": 48},
                     snow={"depth": 2.5, "lo": .25, "hi": .5, "talus": 45, "iters": 80, "d0": .15, "d1": .6}),
                dict(mid, zoom=13, detail={"noise": 2.5, "drops_per_cell": 0.7, "talus": 44},
                     snow={"depth": 3.0, "lo": .25, "hi": .5, "talus": 45, "iters": 60, "d0": .15, "d1": .7}),
                dict(ex=100000, ey=100000, cell=50, zoom=11,
                     snow={"depth": 20, "lo": .3, "hi": .55, "talus": 45, "iters": 20, "d0": .5, "d1": 3}),
                dict(ex=420000, ey=420000, cell=420, zoom=8,
                     snow={"depth": 60, "lo": .3, "hi": .55, "talus": 40, "iters": 10, "d0": 1, "d1": 8}),
            ]}


def get(out_dir, **kw):
    os.makedirs(out_dir, exist_ok=True)
    sp = spec(**kw)
    path = os.path.join(out_dir, 'terrain_spec.json')
    cache = os.path.join(out_dir, 'terrain.npz')
    old = json.load(open(path)) if os.path.exists(path) else None
    if old != sp and os.path.exists(cache):
        os.remove(cache)
    json.dump(sp, open(path, 'w'), indent=1)
    return tcache.get('shots/tgen_dem.py', cache, path)
