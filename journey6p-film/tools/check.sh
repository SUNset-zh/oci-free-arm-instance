#!/bin/sh
# Syntax-check every ES module (fast, catches errors the browser may swallow).
cd "$(dirname "$0")/.." && fail=0
for f in src/*.js src/worlds/*.js src/lib/*.js; do
  node --input-type=module --check < "$f" > /tmp/_chk.txt 2>&1 || { echo "== $f"; head -5 /tmp/_chk.txt; fail=1; }
done
exit $fail
