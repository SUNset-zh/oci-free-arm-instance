#!/usr/bin/env bash
# Encode rendered samples + soundtrack into the final MP4.
# usage: tools/encode.sh <frames_dir> <soundtrack.wav> <out.mp4> [fps=60] [sub=1] [crf=18]
set -euo pipefail
DIR=$1; WAV=$2; OUT=$3; FPS=${4:-60}; SUB=${5:-1}; CRF=${6:-18}
FFMPEG=${FFMPEG:-ffmpeg}
"$FFMPEG" -hide_banner -loglevel error -y \
  -framerate $((FPS * SUB)) -i "$DIR/f%06d.jpg" -i "$WAV" \
  -vf "format=gbrp,tmix=frames=${SUB},select='eq(mod(n\,${SUB})\,${SUB}-1)',setpts=N/(${FPS}*TB),scale=out_color_matrix=bt709:out_range=tv,format=yuv420p" \
  -r "$FPS" -c:v libx264 -preset slow -crf "$CRF" -profile:v high -level:v 4.2 -g $((FPS * 2)) -bf 2 \
  -colorspace bt709 -color_primaries bt709 -color_trc bt709 -color_range tv \
  -c:a aac -b:a 256k -ar 48000 -shortest -movflags +faststart \
  -metadata title="喵 Pro · 发布会" "$OUT"
echo "wrote $OUT"
