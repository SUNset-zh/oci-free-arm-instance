"""只更新某个镜头的后期参数（不重建场景）：python3 shots/write_post.py shots/s6_cloudsea.py 输出目录"""
import importlib.util
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
spec = importlib.util.spec_from_file_location('shot', sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
json.dump(m.POST, open(os.path.join(sys.argv[2], 'post.json'), 'w'))
print('post.json <-', sys.argv[1])
