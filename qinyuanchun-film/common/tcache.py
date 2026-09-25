"""在独立进程里生成地形并缓存（numba 与 Blender 自带的 LLVM 不能在同一进程共存）。"""
import os
import subprocess
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get(gen_script, cache, *args):
    """gen_script: 相对 ROOT 的生成脚本，调用方式 python3 gen_script cache args...；返回 np.load 结果。"""
    if not os.path.exists(cache):
        env = dict(os.environ, PYTHONPATH=ROOT)
        subprocess.run([sys.executable, os.path.join(ROOT, gen_script), cache, *map(str, args)], check=True, env=env)
    return np.load(cache)
