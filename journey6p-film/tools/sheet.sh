#!/bin/sh
# Render stills at the given times and tile them: tools/sheet.sh NAME COLS t1 t2 ...
cd "$(dirname "$0")/.." || exit 1
name=$1; cols=$2; shift 2
tools/check.sh || exit 1
node tools/shots.mjs "$@" --w ${W:-640} --h ${H:-360} > shots/$name.log 2>&1 || { tail -20 shots/$name.log; exit 1; }
files=""
for t in "$@"; do files="$files shots/t$(printf '%06.2f' $t).png"; done
python3 tools/grid.py shots/$name.png $cols $files && echo "sheet shots/$name.png" && grep -v '^/' shots/$name.log | tail -3
