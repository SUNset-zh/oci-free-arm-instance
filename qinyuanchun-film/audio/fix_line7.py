"""第 7 句单独拼接：整句里的“只识”识别稳定，“射”却常被听成“这”；
单独合成的“弯弓射大雕”则清晰。取两者之长，在“识”与“弯”之间的微停顿处拼接，并用语音识别复核。"""
import sys, numpy as np, soundfile as sf, voicecheck as vc
vc.TTSD, vc.ASRD, out = sys.argv[1], sys.argv[2], sys.argv[3]
tts, asr = vc.tts_engine(), vc.asr_engine()
def g(t, sp):
    a = tts.generate(t, sid=63, speed=sp); x = np.array(a.samples, np.float32)
    i = np.where(np.abs(x) > .012)[0]; return x[max(0, i[0] - 240): i[-1] + 600], a.sample_rate
def env(x, sr):
    fr = int(.01 * sr); return np.array([np.sqrt((x[i:i + fr] ** 2).mean()) for i in range(0, len(x) - fr, fr)]), fr
best = None
for sp in (.76, .78, .8):
    head, sr = g('一代天骄，成吉思汗，只识弯弓射大雕。', sp)
    tail, _ = g('弯弓射大雕。', sp)
    e, fr = env(head, sr)
    # 找到“只识弯弓射大雕”在整句中的起点：最后一个长停顿之后
    q = e < .06 * e.max()
    runs = []; st = None
    for i, v in enumerate(q):
        if v and st is None: st = i
        if not v and st is not None:
            if i - st >= 4: runs.append((st, i))
            st = None
    last_pause = [r for r in runs if r[0] < len(e) * .75][-1]
    ph_start = last_pause[1]
    # “只识”约占该短语 2/7，在预计位置 ±60ms 内找能量最低点作为切口
    ph_len = len(e) - ph_start
    exp = ph_start + int(ph_len * 2 / 7)
    win = range(max(ph_start + 5, exp - 8), min(len(e) - 5, exp + 8))
    cutf = min(win, key=lambda i: e[i])
    left = head[: cutf * fr]
    f = int(.01 * sr); left = left.copy(); left[-f:] *= np.linspace(1, 0, f); t2 = tail.copy(); t2[:f] *= np.linspace(0, 1, f)
    # 把前两个逗号的停顿也拉到 0.42 秒
    pieces = []; cur = 0
    for a, b in [r for r in runs if r[0] < last_pause[0]][-1:] + [last_pause]:
        mid = (a + b) // 2 * fr; pieces.append(left[cur:mid]); pieces.append(np.zeros(int(max(0, .42 - (b - a) * fr / sr) * sr), np.float32)); cur = mid
    pieces.append(left[cur:]); pieces.append(np.zeros(int(.02 * sr), np.float32)); pieces.append(t2)
    y = np.concatenate(pieces)
    h = vc.transcribe(asr, y, sr); sc = vc.score('一代天骄成吉思汗只识弯弓射大雕', h)
    print(sp, round(sc, 3), h, round(len(y) / sr, 2), flush=True)
    if best is None or sc > best[0]: best = (sc, y, sr)
sf.write(out, best[1], best[2]); print('saved', round(best[0], 3))
