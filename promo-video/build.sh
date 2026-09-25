#!/usr/bin/env bash
# 一键生成成片：4K 画面 → 合成配乐 → 混流，并额外输出 1080p 版本。
set -euo pipefail
cd "$(dirname "$0")"
FFMPEG="${FFMPEG:-ffmpeg}"
OUT=out
mkdir -p "$OUT"
FFMPEG="$FFMPEG" node render.js --scale 2 --fps 30 --out "$OUT"
python3 soundtrack.py "$OUT/events.json" "$OUT/soundtrack.wav"
"$FFMPEG" -y -loglevel error -i "$OUT/video_only.mp4" -i "$OUT/soundtrack.wav" \
  -c:v copy -c:a aac -b:a 256k -shortest -movflags +faststart "$OUT/Q1_launch_film_4K.mp4"
"$FFMPEG" -y -loglevel error -i "$OUT/Q1_launch_film_4K.mp4" -vf scale=1920:1080:flags=lanczos \
  -c:v libx264 -preset slow -crf 18 -pix_fmt yuv420p -c:a copy -movflags +faststart "$OUT/Q1_launch_film_1080p.mp4"
echo "done -> $OUT/"
