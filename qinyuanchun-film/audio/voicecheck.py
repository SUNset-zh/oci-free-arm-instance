"""挑选朗诵音色：合成候选男声 → 语音识别 → 按带声调拼音逐音节比对，同时看音高起伏（表现力）。"""
import sys, json, numpy as np, sherpa_onnx
from pypinyin import lazy_pinyin, Style
TTSD = ASRD = None
def tts_engine():
    D = TTSD
    return sherpa_onnx.OfflineTts(sherpa_onnx.OfflineTtsConfig(model=sherpa_onnx.OfflineTtsModelConfig(
        kokoro=sherpa_onnx.OfflineTtsKokoroModelConfig(model=f'{D}/model.onnx', voices=f'{D}/voices.bin', tokens=f'{D}/tokens.txt',
            data_dir=f'{D}/espeak-ng-data', dict_dir=f'{D}/dict', lexicon=f'{D}/lexicon-us-en.txt,{D}/lexicon-zh.txt'), num_threads=4),
        rule_fsts=f'{D}/date-zh.fst,{D}/phone-zh.fst,{D}/number-zh.fst', max_num_sentences=1))
def asr_engine():
    return sherpa_onnx.OfflineRecognizer.from_paraformer(paraformer=f'{ASRD}/model.int8.onnx', tokens=f'{ASRD}/tokens.txt', num_threads=4)
def transcribe(asr, x, sr):
    s = asr.create_stream(); s.accept_waveform(sr, x); asr.decode_stream(s); return s.result.text
def py(t): return [p for p in lazy_pinyin(t, style=Style.TONE3, neutral_tone_with_five=True) if p.strip() and p[0].isalpha()]
def score(ref, hyp):
    a, b = py(ref), py(hyp)
    # 编辑距离
    d = np.zeros((len(a)+1, len(b)+1), int); d[:,0] = range(len(a)+1); d[0,:] = range(len(b)+1)
    for i in range(1,len(a)+1):
        for j in range(1,len(b)+1):
            d[i,j] = min(d[i-1,j]+1, d[i,j-1]+1, d[i-1,j-1]+(a[i-1]!=b[j-1]))
    return 1 - d[-1,-1]/len(a)
def f0_std(x, sr):
    fr=int(.04*sr); v=[]
    for i in range(0,len(x)-fr,fr//2):
        s=x[i:i+fr]
        if np.sqrt((s**2).mean())<.03: continue
        c=np.correlate(s,s,'full')[fr-1:]; lo,hi=int(sr/300),int(sr/65); k=lo+np.argmax(c[lo:hi])
        if c[k]>.35*c[0]: v.append(12*np.log2(sr/k))
    return float(np.std(v)) if len(v)>5 else 0, float(np.median(v)) if v else 0
if __name__ == '__main__':
    TTSD, ASRD = sys.argv[1], sys.argv[2]
    tts, asr = tts_engine(), asr_engine()
    tests = ['北国风光，千里冰封，万里雪飘。', '一代天骄，成吉思汗，只识弯弓射大雕。', '俱往矣，蜀风流人物，还看今朝。', '须晴日，看红装素裹，分外妖娆。']
    refs = [t.replace('蜀', '数') for t in tests]
    res = []
    for sid in [int(s) for s in sys.argv[3].split(',')]:
        acc, st = [], []
        for t, r in zip(tests, refs):
            a = tts.generate(t, sid=sid, speed=.85); x = np.array(a.samples, np.float32)
            acc.append(score(r, transcribe(asr, x, a.sample_rate))); st.append(f0_std(x, a.sample_rate))
        res.append((sid, round(float(np.mean(acc)),3), round(float(np.mean([s[0] for s in st])),2), round(float(np.mean([s[1] for s in st])),1)))
        print(res[-1], flush=True)
