import sys, numpy as np
from voicecheck import tts_engine, asr_engine, transcribe, py, score
import voicecheck
voicecheck.TTSD, voicecheck.ASRD = sys.argv[1], sys.argv[2]
tts, asr = tts_engine(), asr_engine()
sid = int(sys.argv[3])
LINES = ['沁园春，雪。','北国风光，千里冰封，万里雪飘。','望长城内外，惟余莽莽；大河上下，顿失滔滔。','山舞银蛇，原驰蜡象，欲与天公试比高。',
 '须晴日，看红装素裹，分外妖娆。','江山如此多娇，引无数英雄竞折腰。','惜秦皇汉武，略输文采；唐宗宋祖，稍逊风骚。','一代天骄，成吉思汗，只识弯弓射大雕。','俱往矣，蜀风流人物，还看今朝。']
for t in LINES:
    a = tts.generate(t, sid=sid, speed=.85); x = np.array(a.samples, np.float32)
    h = transcribe(asr, x, a.sample_rate); r = t.replace('蜀','数')
    pa, pb = py(r), py(h)
    print(round(score(r,h),2), '|', r, '→', h)
    if pa != pb: print('    ref', ' '.join(pa)); print('    asr', ' '.join(pb))
