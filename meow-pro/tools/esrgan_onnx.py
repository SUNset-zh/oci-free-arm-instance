"""Convert Real-ESRGAN SRVGGNetCompact .pth weights to ONNX without torch."""
import sys, zipfile, pickle, collections, numpy as np, onnx
from onnx import helper, TensorProto, numpy_helper

def load_pth(path):
    z = zipfile.ZipFile(path)
    prefix = z.namelist()[0].split('/')[0]
    class Storage:
        def __init__(self, dtype, key): self.dtype, self.key = dtype, key
    def rebuild_tensor_v2(storage, offset, size, stride, *args):
        raw = z.read(f'{prefix}/data/{storage.key}')
        arr = np.frombuffer(raw, dtype=storage.dtype)
        n = int(np.prod(size)) if len(size) else 1
        arr = arr[offset:offset + n] if len(size) else arr[offset:offset+1]
        # assume contiguous
        return arr.reshape(size).copy()
    class U(pickle.Unpickler):
        def find_class(self, mod, name):
            if name == '_rebuild_tensor_v2': return rebuild_tensor_v2
            if name == 'OrderedDict': return collections.OrderedDict
            if name.endswith('Storage'):
                return {'FloatStorage': np.float32, 'HalfStorage': np.float16}.get(name, np.float32)
            return super().find_class(mod, name)
        def persistent_load(self, pid):
            # ('storage', storage_type, key, location, numel)
            typ, dtype, key = pid[0], pid[1], pid[2]
            return Storage(dtype, key)
    obj = U(io_bytes(z.read(f'{prefix}/data.pkl'))).load()
    return obj

import io
def io_bytes(b): return io.BytesIO(b)

def build(sd, out):
    if 'params' in sd: sd = sd['params']
    keys = list(sd.keys())
    nodes, inits = [], []
    x = 'input'
    idx = sorted({int(k.split('.')[1]) for k in keys})
    cur = x
    for i in idx:
        w = sd[f'body.{i}.weight']
        if w.ndim == 4:
            b = sd[f'body.{i}.bias']
            inits += [numpy_helper.from_array(w.astype(np.float32), f'w{i}'), numpy_helper.from_array(b.astype(np.float32), f'b{i}')]
            nodes.append(helper.make_node('Conv', [cur, f'w{i}', f'b{i}'], [f'c{i}'], pads=[1,1,1,1], kernel_shape=[3,3]))
            cur = f'c{i}'
        else:  # prelu
            inits.append(numpy_helper.from_array(w.reshape(-1,1,1).astype(np.float32), f'p{i}'))
            nodes.append(helper.make_node('PRelu', [cur, f'p{i}'], [f'a{i}']))
            cur = f'a{i}'
    nodes.append(helper.make_node('DepthToSpace', [cur], ['ps'], blocksize=4, mode='CRD'))
    inits.append(numpy_helper.from_array(np.array([1,1,4,4], dtype=np.float32), 'scales'))
    inits.append(numpy_helper.from_array(np.array([], dtype=np.float32), 'roi'))
    nodes.append(helper.make_node('Resize', ['input', 'roi', 'scales'], ['base'], mode='nearest'))
    nodes.append(helper.make_node('Add', ['ps', 'base'], ['output']))
    g = helper.make_graph(nodes, 'srvgg', [helper.make_tensor_value_info('input', TensorProto.FLOAT, [1,3,None,None])],
                          [helper.make_tensor_value_info('output', TensorProto.FLOAT, [1,3,None,None])], inits)
    m = helper.make_model(g, opset_imports=[helper.make_opsetid('', 13)], ir_version=8)
    onnx.checker.check_model(m)
    onnx.save(m, out)
    print('saved', out, len(nodes), 'nodes')

if __name__ == '__main__':
    sd = load_pth(sys.argv[1])
    build(sd, sys.argv[2])
