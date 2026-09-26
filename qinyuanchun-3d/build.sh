#!/usr/bin/env bash
# 一键出片：渲染 3D 画面 → 合成朗诵 → 配乐混音 → 混流。结果在 out/。
# 需要：Node + Playwright(Chromium)、Python3 + numpy + soundfile + sherpa-onnx、带 libx264 的 ffmpeg、
#       sherpa-onnx 的 kokoro-multi-lang-v1_1 模型目录（环境变量 TTS_MODEL 指向它）。
set -euo pipefail
cd "$(dirname "$0")"
FFMPEG="${FFMPEG:-ffmpeg}"
OUT=out
mkdir -p "$OUT"
FFMPEG="$FFMPEG" node render.js --out "$OUT"
python3 narration.py "${TTS_MODEL:?set TTS_MODEL to the kokoro-multi-lang-v1_1 directory}" "$OUT/voice"
python3 soundtrack.py "$OUT/voice" "$OUT/soundtrack.wav"
"$FFMPEG" -y -loglevel error -i "$OUT/video_only.mp4" -i "$OUT/soundtrack.wav" \
  -c:v copy -af loudnorm=I=-16:TP=-1.5:LRA=11 -ar 48000 -c:a aac -b:a 192k -shortest -movflags +faststart \
  "$OUT/qinyuanchun_xue_3d_1080x1920.mp4"
echo "done -> $OUT/qinyuanchun_xue_3d_1080x1920.mp4"
