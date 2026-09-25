#!/usr/bin/env bash
# 整条流水线：朗诵 → 配乐 → 各镜头（地形、场景、渲染、后期）→ 接片编码。
#
#   S=/path/to/work ./build.sh
#
# S 是工作目录：高程瓦片缓存、地形、EXR、成片帧都在这里，体积很大，不进仓库。
# 外部素材（路径写在各脚本开头）：
#   - 朗诵：sherpa-onnx 的 kokoro-multi-lang-v1_1（TTS）与 paraformer-zh（识别校验）模型
#   - 配乐：gleitz/midi-js-soundfonts 的 MusyngKite / FluidR3_GM 采样
#   - 字体：Noto Serif SC / Noto Sans SC
#   - 骑手：three.js 示例里的 Horse.glb
# 在 4 核 CPU 上，一个镜头（720×1280，16 spp）约 1–2 小时。
set -euo pipefail
cd "$(dirname "$0")"
S=${S:?set S to a work directory}
TTS=$S/tts/kokoro-multi-lang-v1_1
ASR=$S/assets/sherpa-onnx-paraformer-zh-2024-03-09

# 1. 朗诵与配乐
python3 audio/narrate.py "$TTS" "$ASR" "$S/narr"
python3 audio/fix_line7.py "$TTS" "$ASR" "$S/narr/line_7.wav"
python3 audio/score.py "$S/narr" "$S/score.wav"

# 2. 片头（纯后期）
python3 post/s0_title.py "$S/s0/final"

# 3. 其余镜头：生成地形并搭场景 → Cycles 渲染多层 EXR → 后期、放大到 1080×1920
for spec in s1b:s1_bluehour s2:s2_greatwall s3:s3_river s4:s4_ridges s5:s5_sunrise \
            s6:s6_cloudsea s7:s7_beacon s8:s8_steppe s9:s9_today; do
  d=${spec%%:*}; m=${spec##*:}
  n=$(python3 -c "import assemble; print(dict((s[0], s[4]) for s in assemble.SHOTS)['$d'])")
  python3 "shots/$m.py" --out "$S/$d"
  python3 render.py "$S/$d/shot.blend" --range 1 "$n" --out "$S/$d/final" --res 720x1280 --samples 16
  python3 post/grade_shot.py "$S/$d"
done

# 4. 接片：母版，再两遍编码出适合手机分享的小文件
python3 assemble.py "$S" "$S/score.wav" "$S/qinyuanchun_master.mp4" --crf 14
mkdir -p release
python3 assemble.py --share "$S/qinyuanchun_master.mp4" release/qinyuanchun_xue_film_1080x1920.mp4
