#!/usr/bin/env bash
# Full pipeline: assets -> soundtrack -> frames -> MP4.
#   ./build.sh                 final quality (1080x1920, 60 fps)
#   PREVIEW=1 ./build.sh       quick 30 fps preview
#   SKIP_ASSETS=0 ./build.sh   also rebuild web/assets from src/ (needs MODELS_DIR, see README)
# MOTION_BLUR=N averages N samples per frame (180° shutter). Off by default: the
# fastest moves already carry their own directional blur, and few samples ghost.
# Needs: python3 (numpy scipy pillow pyloudnorm [+ onnxruntime for assets]), node + playwright, ffmpeg.
set -euo pipefail
cd "$(dirname "$0")"
BUILD=${BUILD:-build}
mkdir -p "$BUILD" out
if [ "${SKIP_ASSETS:-1}" = "0" ]; then python3 tools/prepare_assets.py; fi
python3 tools/compose.py "$BUILD/soundtrack.wav"
if [ "${PREVIEW:-0}" = "1" ]; then FPS=30; else FPS=60; fi
SUB=${MOTION_BLUR:-1}
rm -rf "$BUILD/frames"
node tools/render.cjs "$BUILD/frames" "$FPS" "${WORKERS:-4}" 0 50 94 "$SUB" 0.5
tools/encode.sh "$BUILD/frames" "$BUILD/soundtrack.wav" out/meow-pro.mp4 "$FPS" "$SUB" 18
