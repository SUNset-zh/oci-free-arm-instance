#!/usr/bin/env python3
"""离线合成《沁园春·雪》男声朗诵（sherpa-onnx + Kokoro 多语种 v1.1 模型，无需联网）。

    # 模型：https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/kokoro-multi-lang-v1_1.tar.bz2
    pip install sherpa-onnx soundfile
    python3 narration.py <模型目录> out/voice

每句单独合成并去掉首尾静音，输出 line0.wav … line8.wav 和 durations.json，由 soundtrack.py 按时间轴摆放。
"""
import json
import os
import sys

import numpy as np
import sherpa_onnx
import soundfile as sf

SPEAKER = 63      # 低沉的男声
SPEED = 0.82      # 放慢，朗诵的语速
LINES = [
    '沁园春，雪。',
    '北国风光，千里冰封，万里雪飘。',
    '望长城内外，惟余莽莽；大河上下，顿失滔滔。',
    '山舞银蛇，原驰蜡象，欲与天公试比高。',
    '须晴日，看红装素裹，分外妖娆。',
    '江山如此多娇，引无数英雄竞折腰。',
    '惜秦皇汉武，略输文采；唐宗宋祖，稍逊风骚。',
    '一代天骄，成吉思汗，只识弯弓射大雕。',
    # “数风流人物”的“数”读 shǔ，词典默认读 shù，这里用同音字“蜀”让合成读准
    '俱往矣，蜀风流人物，还看今朝。',
]


def main():
    D, out = sys.argv[1], sys.argv[2]
    os.makedirs(out, exist_ok=True)
    cfg = sherpa_onnx.OfflineTtsConfig(
        model=sherpa_onnx.OfflineTtsModelConfig(
            kokoro=sherpa_onnx.OfflineTtsKokoroModelConfig(
                model=f'{D}/model.onnx', voices=f'{D}/voices.bin', tokens=f'{D}/tokens.txt',
                data_dir=f'{D}/espeak-ng-data', dict_dir=f'{D}/dict', lexicon=f'{D}/lexicon-us-en.txt,{D}/lexicon-zh.txt'),
            num_threads=4),
        rule_fsts=f'{D}/date-zh.fst,{D}/phone-zh.fst,{D}/number-zh.fst', max_num_sentences=1)
    tts = sherpa_onnx.OfflineTts(cfg)
    durs = []
    for i, line in enumerate(LINES):
        a = tts.generate(line, sid=SPEAKER, speed=SPEED)
        x = np.array(a.samples, dtype=np.float32)
        idx = np.where(np.abs(x) > .01)[0]
        x = x[max(0, idx[0] - 240): idx[-1] + 2400]
        sf.write(f'{out}/line{i}.wav', x, a.sample_rate)
        durs.append(round(len(x) / a.sample_rate, 3))
    json.dump({'sr': a.sample_rate, 'durations': durs}, open(f'{out}/durations.json', 'w'))
    print(durs)


if __name__ == '__main__':
    main()
