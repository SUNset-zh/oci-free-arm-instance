// Monoline cursive "hello" — pen trajectory as Catmull-Rom point runs.
// Runs are joined end to end (a new run starts where the previous ended),
// so the result is one continuous stroke; run breaks give sharp cusps.
(function () {
  const strokes = [
    // h : lead-in, ascender loop, stem down to the baseline
    [[30, 392], [95, 350], [160, 280], [212, 196], [246, 122], [252, 72], [232, 46], [206, 58], [190, 104], [180, 190], [172, 290], [164, 396]],
    // h : hump + exit into e
    [[164, 396], [180, 330], [212, 284], [250, 266], [282, 282], [290, 322], [284, 370], [298, 398], [336, 396], [376, 370]],
    // e
    [[376, 370], [420, 334], [438, 298], [424, 268], [392, 262], [364, 286], [354, 338], [370, 384], [410, 400], [454, 388], [488, 350]],
    // l
    [[484, 350], [528, 280], [566, 196], [590, 118], [590, 70], [566, 50], [542, 70], [530, 130], [522, 240], [520, 340], [536, 392], [576, 398], [616, 360]],
    // l
    [[616, 360], [660, 290], [698, 204], [722, 124], [722, 76], [698, 56], [674, 76], [662, 136], [654, 246], [652, 340], [668, 392], [708, 398], [744, 370]],
    // o
    [[744, 370], [772, 322], [804, 288], [838, 270]],
    [[838, 270], [802, 268], [772, 288], [756, 328], [760, 374], [790, 400], [828, 398], [854, 368], [858, 322], [842, 286], [818, 274], [806, 290], [822, 304], [866, 300], [918, 282], [962, 258]],
  ];

  function runToBezier(pts, k) {
    // uniform Catmull-Rom -> cubic Bezier, endpoints clamped
    let d = '';
    const n = pts.length;
    for (let i = 0; i < n - 1; i++) {
      const p0 = pts[Math.max(0, i - 1)], p1 = pts[i], p2 = pts[i + 1], p3 = pts[Math.min(n - 1, i + 2)];
      const c1 = [p1[0] + (p2[0] - p0[0]) * k, p1[1] + (p2[1] - p0[1]) * k];
      const c2 = [p2[0] - (p3[0] - p1[0]) * k, p2[1] - (p3[1] - p1[1]) * k];
      d += ` C ${c1[0].toFixed(1)} ${c1[1].toFixed(1)}, ${c2[0].toFixed(1)} ${c2[1].toFixed(1)}, ${p2[0]} ${p2[1]}`;
    }
    return d;
  }

  function path(k = 1 / 6) {
    let d = `M ${strokes[0][0][0]} ${strokes[0][0][1]}`;
    for (const run of strokes) d += runToBezier(run, k);
    return d;
  }

  const api = { strokes, path, width: 980, height: 440 };
  if (typeof window !== 'undefined') window.HELLO = api;
  if (typeof module !== 'undefined') module.exports = api;
})();
