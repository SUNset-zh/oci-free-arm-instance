#!/usr/bin/env bash
# 一键出片：逐帧渲染 → 合成配乐 → 混流。结果在 out/。
set -euo pipefail
cd "$(dirname "$0")"
FFMPEG="${FFMPEG:-ffmpeg}"
OUT=out
mkdir -p "$OUT"
FFMPEG="$FFMPEG" node render.js --out "$OUT"
python3 soundtrack.py "$OUT/events.json" "$OUT/soundtrack.wav"
"$FFMPEG" -y -loglevel error -i "$OUT/video_only.mp4" -i "$OUT/soundtrack.wav" \
  -c:v copy -c:a aac -b:a 192k -shortest -movflags +faststart "$OUT/zhanan_guide_1080x1920.mp4"
echo "done -> $OUT/zhanan_guide_1080x1920.mp4"
