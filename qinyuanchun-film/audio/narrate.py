#!/usr/bin/env python3
"""合成《沁园春·雪》朗诵：整句合成保留自然语调，再按朗诵节奏拉长句中停顿。

    python3 narrate.py <kokoro-multi-lang-v1_1 目录> <paraformer-zh 目录> <输出目录>

1. 每句尝试多种语速与标点，用语音识别转写，按带声调拼音逐音节比对打分，取最清晰的版本；
2. 在合成音频里找到逗号/分号处的自然停顿，把它们拉长到设计的时长（逗号约 0.4 秒，分号约 0.75 秒）；
3. 输出 line_X.wav 与 lines.json（文本、得分、识别结果、时长、各短语的起止时间）。
"""
import json, os, sys
import numpy as np
import soundfile as sf
import voicecheck as vc

SID = 63
LINES = [
    '沁园春，雪。',
    '北国风光，千里冰封，万里雪飘。',
    '望长城内外，惟余莽莽；大河上下，顿失滔滔。',
    '山舞银蛇，原驰蜡象，欲与天公试比高。',
    '须晴日，看红装素裹，分外妖娆。',
    '江山如此多娇，引无数英雄竞折腰。',
    '惜秦皇汉武，略输文采；唐宗宋祖，稍逊风骚。',
    '一代天骄，成吉思汗，只识弯弓射大雕。',
    '俱往矣，蜀风流人物，还看今朝。',   # “数”读 shǔ，用同音字
]
SPEEDS = [.74, .78, .82, .86]
PAUSE = {'，': .42, '；': .78}


def gaps(x, sr, counts):
    """按各短语音节数估计逗号位置，在估计位置附近选最合适的静音段。counts: 各短语音节数。"""
    fr = int(.01 * sr)
    e = np.array([np.sqrt((x[i:i + fr] ** 2).mean()) for i in range(0, len(x) - fr, fr)])
    quiet = e < max(.006, .06 * e.max())
    runs, st = [], None
    for i, q in enumerate(quiet):
        if q and st is None: st = i
        if not q and st is not None:
            if i - st >= 4 and st > 3: runs.append((st, i))
            st = None
    tot = sum(counts); L = len(e); out = []; lo = 0
    for k in range(len(counts) - 1):
        exp = L * sum(counts[:k + 1]) / tot
        cand = [(r[1] - r[0]) * 1.0 - abs((r[0] + r[1]) / 2 - exp) * .35 for r in runs]
        best = None
        for r, c in zip(runs, cand):
            if r[0] <= lo: continue
            if best is None or c > best[0]: best = (c, r)
        if best is None: return None
        out.append(best[1]); lo = best[1][1]
    return [(a * fr, b * fr) for a, b in out]


def main():
    vc.TTSD, vc.ASRD, out = sys.argv[1], sys.argv[2], sys.argv[3]
    os.makedirs(out, exist_ok=True)
    tts, asr = vc.tts_engine(), vc.asr_engine()
    meta = []
    for li, line in enumerate(LINES):
        variants = {line, line.replace('；', '，')}
        best = None
        for text in variants:
            for sp in SPEEDS:
                a = tts.generate(text, sid=SID, speed=sp)
                x = np.array(a.samples, np.float32)
                idx = np.where(np.abs(x) > .012)[0]
                x = x[max(0, idx[0] - 360): idx[-1] + 1800]
                ref = line.replace('蜀', '数')
                hyp = vc.transcribe(asr, x, a.sample_rate)
                sc = vc.score(ref, hyp)
                key = (round(sc, 3), vc.f0_std(x, a.sample_rate)[0] - abs(sp - .8) * 5)
                if best is None or key > best[0]:
                    best = (key, x, a.sample_rate, sp, text, hyp)
        (sc, _), x, sr, sp, text, hyp = best
        # 按停顿切成短语；逐个识别，多出的首尾音用最小的裁剪去掉
        marks = [c for c in line if c in PAUSE]
        texts = [t for t in __import__('re').split('[，；。]', line.replace('蜀', '数')) if t]
        g = gaps(x, sr, [len(vc.py(t)) for t in texts])
        segs = [x]
        if g:
            bounds = [0] + [(a + b) // 2 for a, b in g] + [len(x)]
            cand = [x[bounds[i]:bounds[i + 1]] for i in range(len(bounds) - 1)]
            # 校验：每段识别出的音节数必须与该短语一致（允许多出 1 个，交给后面的裁剪）
            ok = all(len(vc.py(t)) <= len(vc.py(vc.transcribe(asr, c, sr))) <= len(vc.py(t)) + 1 for c, t in zip(cand, texts))
            if ok: segs = cand
        if len(segs) != len(texts):
            texts = [line.replace('蜀', '数')]; print('   split failed, keep natural pauses:', line, flush=True)
        fixed = []
        for seg, tgt in zip(segs, texts):
            nz = np.where(np.abs(seg) > .012)[0]
            core = seg[nz[0]:nz[-1] + 1] if len(nz) else seg
            f = int(.012 * sr)
            def cut(cs, ce):
                y = core[int(cs * sr): len(core) - int(ce * sr)].copy()
                y[:f] *= np.linspace(0, 1, f); y[-f:] *= np.linspace(1, 0, f)
                return y
            h0 = vc.transcribe(asr, core, sr)
            n_t, n_h = len(vc.py(tgt)), len(vc.py(h0))
            best_seg, sc0 = cut(0, 0), vc.score(tgt, h0)
            if n_h > n_t:   # 听出了多余的音节：只在首尾做最小裁剪，并且不能丢掉原有音节
                done = False
                for amt in (.03, .06, .09, .12, .15, .18, .21, .24):
                    for cs, ce in ((0, amt), (amt, 0)):
                        y = cut(cs, ce); h = vc.transcribe(asr, y, sr)
                        if len(vc.py(h)) == n_t and vc.score(tgt, h) >= sc0:
                            best_seg, done = y, True; break
                    if done: break
                print('   trim', tgt, h0, '->', 'fixed' if done else 'kept', flush=True)
            fixed.append(best_seg)
        pieces = []
        for i, seg in enumerate(fixed):
            pieces.append(seg)
            if i < len(marks) and len(fixed) > 1:
                pieces.append(np.zeros(int(PAUSE[marks[i]] * sr), np.float32))
        y = np.concatenate(pieces)
        hyp2 = vc.transcribe(asr, y, sr); sc = round(vc.score(line.replace('蜀', '数'), hyp2), 3); hyp = hyp2
        fn = f'line_{li}.wav'
        sf.write(os.path.join(out, fn), y, sr)
        meta.append(dict(line=li, text=line.replace('蜀', '数'), file=fn, score=sc, speed=sp, asr=hyp,
                         dur=round(len(y) / sr, 3), sr=sr, split=len(segs) > 1))
        print(sc, line, '→', hyp, sp, round(len(y) / sr, 2), 'split' if len(segs) > 1 else 'whole', flush=True)
    json.dump(meta, open(os.path.join(out, 'lines.json'), 'w'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
