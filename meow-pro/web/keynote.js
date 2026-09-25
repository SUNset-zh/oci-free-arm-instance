/* 喵 Pro — a 50 second keynote-style product film, 1080x1920.
 *
 * Everything is a pure function of time: window.seek(t) puts every element
 * where it belongs at second t, so the renderer can step frame by frame.
 * Coordinates marked "src" are pixels of the original photos in src/photos.
 */
(() => {
  'use strict';
  const W = 1080, H = 1920, DURATION = 50;
  const stage = document.getElementById('stage');
  const params = new URLSearchParams(location.search);

  // ------------------------------------------------------------------ math
  const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
  const lerp = (a, b, t) => a + (b - a) * t;
  const inv = (a, b, x) => clamp((x - a) / (b - a));
  const E = {
    lin: t => t,
    in2: t => t * t,
    out2: t => 1 - (1 - t) * (1 - t),
    in3: t => t * t * t,
    out3: t => 1 - Math.pow(1 - t, 3),
    io3: t => (t < .5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2),
    out4: t => 1 - Math.pow(1 - t, 4),
    io4: t => (t < .5 ? 8 * t ** 4 : 1 - Math.pow(-2 * t + 2, 4) / 2),
    out5: t => 1 - Math.pow(1 - t, 5),
    outExpo: t => (t >= 1 ? 1 : 1 - Math.pow(2, -10 * t)),
    inExpo: t => (t <= 0 ? 0 : Math.pow(2, 10 * t - 10)),
    ioSine: t => -(Math.cos(Math.PI * t) - 1) / 2,
    outBack: (t, s = 1.7) => 1 + (s + 1) * Math.pow(t - 1, 3) + s * Math.pow(t - 1, 2),
  };
  const back = s => t => E.outBack(t, s);
  // damped spring 0 -> 1 (zeta < 1 overshoots)
  const spring = (f = 2.2, z = 0.55) => t => {
    if (t <= 0) return 0;
    const w = 2 * Math.PI * f, wd = w * Math.sqrt(1 - z * z);
    return 1 - Math.exp(-z * w * t) * (Math.cos(wd * t) + (z * w / wd) * Math.sin(wd * t));
  };
  // eased progress of t through [a, b]
  const P = (t, a, b, e = E.lin) => e(inv(a, b, t));
  // piecewise keys: [[t, v], [t, v, ease], ...]
  function K(t, keys) {
    if (t <= keys[0][0]) return keys[0][1];
    for (let i = 1; i < keys.length; i++) {
      const [t1, v1, e = E.io3] = keys[i];
      if (t <= t1) {
        const [t0, v0] = keys[i - 1];
        const p = e(inv(t0, t1, t));
        return Array.isArray(v0) ? v0.map((v, j) => lerp(v, v1[j], p)) : lerp(v0, v1, p);
      }
    }
    return keys[keys.length - 1][1];
  }
  const frac = x => x - Math.floor(x);

  // ------------------------------------------------------------------- dom
  const imgs = [];
  function el(tag, cls, parent, style, html) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (style) Object.assign(e.style, style);
    if (html !== undefined) e.innerHTML = html;
    (parent || stage).appendChild(e);
    return e;
  }
  const NS = 'http://www.w3.org/2000/svg';
  function sv(tag, attrs, parent) {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }
  function svgLayer(parent, z) {
    const s = sv('svg', { width: W, height: H, viewBox: `0 0 ${W} ${H}` }, parent);
    Object.assign(s.style, { position: 'absolute', left: 0, top: 0, zIndex: z || 'auto' });
    return s;
  }
  function img(src, parent, style) {
    const i = el('img', 'nat', parent, style);
    i.src = src;
    i.decoding = 'sync';
    imgs.push(i);
    return i;
  }
  // put image pixel (ax, ay) at screen (cx, cy) with scale k
  function place(e, k, ax, ay, cx, cy) {
    e.style.transform = `translate(${cx - ax * k}px, ${cy - ay * k}px) scale(${k})`;
  }
  function text(parent, html, cls, top, style) {
    const t = el('div', 't ' + (cls || ''), parent, style, html);
    t.style.top = top + 'px';
    return t;
  }
  function split(t) {
    const s = t.textContent;
    t.textContent = '';
    return [...s].map(c => {
      const sp = el('span', 'ch', t);
      sp.textContent = c === ' ' ? ' ' : c;
      return sp;
    });
  }
  function charsIn(chs, t, t0, o = {}) {
    const st = o.st ?? 0.035, dur = o.dur ?? 0.55, dy = o.dy ?? 38, bl = o.blur ?? 12, ease = o.ease || E.out3;
    for (let i = 0; i < chs.length; i++) {
      const p = P(t, t0 + i * st, t0 + i * st + dur, ease);
      const c = chs[i].style;
      c.opacity = p;
      c.transform = p < 1 ? `translateY(${(1 - p) * dy}px)` : 'none';
      c.filter = p < 0.999 ? `blur(${((1 - p) * bl).toFixed(2)}px)` : 'none';
    }
  }
  // gradient text that is also split per character: give every glyph its own
  // slice of one continuous gradient (measured after the fonts load)
  const gradSplits = [];
  function gradSplit(t, gradient) {
    const chs = split(t);
    t.classList.remove('grad');
    t.style.background = 'none';
    t.style.color = '#fff';
    gradSplits.push({ t, chs, gradient });
    return chs;
  }
  function layoutGradSplits() {
    for (const g of gradSplits) {
      const sec = g.t.closest('section');
      const prev = sec.style.display;
      sec.style.display = 'block';
      const x0 = g.chs[0].offsetLeft;
      const last = g.chs[g.chs.length - 1];
      const w = last.offsetLeft + last.offsetWidth - x0;
      for (const c of g.chs) {
        Object.assign(c.style, { backgroundImage: g.gradient, backgroundSize: `${w}px 100%`, backgroundPosition: `${x0 - c.offsetLeft}px 0`,
          backgroundRepeat: 'no-repeat', webkitBackgroundClip: 'text', backgroundClip: 'text', color: 'transparent' });
      }
      sec.style.display = prev;
    }
  }

  // whole-element entrance / exit
  function lineIn(e, t, t0, o = {}) {
    const dur = o.dur ?? 0.6, dy = o.dy ?? 30, bl = o.blur ?? 10, t1 = o.out ?? 1e9, od = o.outDur ?? 0.3;
    const p = P(t, t0, t0 + dur, o.ease || E.out3);
    const q = P(t, t1, t1 + od, E.in2);
    const s = e.style;
    s.opacity = p * (1 - q);
    const y = (1 - p) * dy - q * (o.outDy ?? 12);
    const sc = o.scale ? lerp(o.scale, 1, p) : 1;
    s.transform = `translateY(${y}px)` + (sc !== 1 ? ` scale(${sc})` : '');
    const b = (1 - p) * bl + q * 8;
    s.filter = b > 0.02 ? `blur(${b.toFixed(2)}px)` : 'none';
    return p * (1 - q);
  }
  const show = (e, on) => { e.style.display = on ? '' : 'none'; };

  // velocity-driven vertical motion blur (SVG filter shared by page scrolls)
  const fx = sv('svg', { width: 0, height: 0 }, stage);
  fx.style.position = 'absolute';
  fx.innerHTML = '<defs><filter id="vblurC" x="0" y="-10%" width="100%" height="120%"><feGaussianBlur stdDeviation="0 0"/></filter>' +
    '<filter id="vblurD" x="0" y="-10%" width="100%" height="120%"><feGaussianBlur stdDeviation="0 0"/></filter></defs>';
  function vblur(e, id, px) {
    if (px < 0.4) { e.style.filter = 'none'; return; }
    fx.querySelector('#' + id + ' feGaussianBlur').setAttribute('stdDeviation', `0 ${px.toFixed(2)}`);
    e.style.filter = `url(#${id})`;
  }
  // speed of an eased progress, in units per second
  const speed = (t, a, b, e) => (P(t + 1 / 120, a, b, e) - P(t - 1 / 120, a, b, e)) * 60;

  // ----------------------------------------------------------------- icons
  const ICON = {
    paw: (fill) => `<svg viewBox="0 0 100 100" width="100%" height="100%"><g fill="${fill}">
      <ellipse cx="20" cy="44" rx="9.5" ry="12.5" transform="rotate(-20 20 44)"/>
      <ellipse cx="38" cy="25" rx="10.5" ry="13.5" transform="rotate(-7 38 25)"/>
      <ellipse cx="62" cy="25" rx="10.5" ry="13.5" transform="rotate(7 62 25)"/>
      <ellipse cx="80" cy="44" rx="9.5" ry="12.5" transform="rotate(20 80 44)"/>
      <path d="M50 49C36 49 23 61 23 74c0 12 10 17 19 14 4-1 6-3 8-3s4 2 8 3c9 3 19-2 19-14 0-13-13-25-27-25z"/></g></svg>`,
    moon: (fill) => `<svg viewBox="0 0 100 100" width="100%" height="100%"><path fill="${fill}" d="M60 10A42 42 0 1 0 90 66 34 34 0 1 1 60 10Z"/></svg>`,
    cat: (fill) => `<svg viewBox="0 0 200 200" width="100%" height="100%"><path fill="${fill}" d="M36 98C34 70 38 42 46 20c2-6 8-7 12-3l28 29c9-3 19-3 28 0l28-29c4-4 10-3 12 3 8 22 12 50 10 78-2 44-28 74-64 74S38 142 36 98Z"/></svg>`,
    check: (stroke, w) => `<svg viewBox="0 0 100 100" width="100%" height="100%"><path d="M24 53 42 71 78 33" fill="none" stroke="${stroke}" stroke-width="${w}" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
  };

  // --------------------------------------------------------------- scenes
  const scenes = [];
  function scene(id, t0, t1, z) {
    const root = el('section', 'scene', stage);
    root.id = id;
    root.style.zIndex = z;
    const s = { id, t0, t1, root, on: false, update() {} };
    scenes.push(s);
    return s;
  }

  // the chip graphic (built at 500px, scale it with a transform)
  function buildChip(parent) {
    const wrap = el('div', 'abs', parent, { width: '500px', height: '500px', transformOrigin: '50% 50%' });
    const ring = el('div', 'fill', wrap, { borderRadius: '76px', padding: '4px',
      boxShadow: '0 0 90px rgba(255,170,100,.30), 0 0 220px rgba(255,120,160,.16)' });
    const face = el('div', 'fill', ring, { inset: '4px', borderRadius: '72px', overflow: 'hidden',
      background: 'linear-gradient(150deg,#2b2825 0%,#151412 52%,#0b0a0a 100%)' });
    el('div', 'fill', face, { opacity: .5, background:
      'repeating-linear-gradient(90deg,rgba(255,255,255,.035) 0 1px,transparent 1px 22px),repeating-linear-gradient(0deg,rgba(255,255,255,.035) 0 1px,transparent 1px 22px)',
      WebkitMaskImage: 'radial-gradient(closest-side,#000 40%,transparent 100%)' });
    el('div', 'abs', face, { left: '215px', top: '66px', width: '70px', height: '70px', opacity: .9 }, ICON.paw('#d8c3a2'));
    el('div', 'abs', face, { left: 0, top: '128px', width: '492px', textAlign: 'center', fontSize: '232px', fontWeight: 800,
      lineHeight: '232px', letterSpacing: '-0.02em',
      background: 'linear-gradient(170deg,#fff1d6 10%,#f3c37f 45%,#c98a45 80%)', WebkitBackgroundClip: 'text', color: 'transparent' }, 'M');
    el('div', 'abs', face, { left: 0, top: '372px', width: '492px', textAlign: 'center', fontSize: '36px', fontWeight: 600,
      letterSpacing: '.42em', textIndent: '.42em', color: '#8e8e93' }, 'MEOW');
    const sheen = el('div', 'fill', face, { background: 'linear-gradient(120deg,transparent 35%,rgba(255,255,255,.13) 50%,transparent 65%)', backgroundSize: '300% 100%' });
    return {
      wrap,
      set(t, angle, sheenPos) {
        ring.style.background = `conic-gradient(from ${angle}deg,#ffcb8e,#ff9fb4,#ffe6c8,#c98a45,#ffcb8e)`;
        sheen.style.backgroundPosition = `${sheenPos}% 0`;
      },
    };
  }

  // ======================================================================
  // A · 0.0–4.0  Teaser: four macro details in a morphing window
  // ======================================================================
  {
    const S = scene('A', 0, 3.87, 1);
    const cx = 540, cy = 900;
    const win = el('div', 'abs', S.root, { overflow: 'hidden', background: '#000', willChange: 'transform' });
    const shots = [
      { src: 'assets/m_eye.jpg', w: 943, h: 943, fx: .5, fy: .5, word: '凝视', dx: 0, dy: -18 },
      { src: 'assets/m_stripes.jpg', w: 640, h: 1360, fx: .5, fy: .5, word: '纹理', dx: 0, dy: 40 },
      { src: 'assets/m_beans.jpg', w: 1156, h: 782, fx: .52, fy: .5, word: '触感', dx: -40, dy: 0 },
      { src: 'assets/m_nose.jpg', w: 1054, h: 992, fx: .5, fy: .55, word: '心动', dx: 0, dy: 0 },
    ];
    for (const s of shots) s.img = img(s.src, win);
    const sweep = el('div', 'fill', win, { mixBlendMode: 'soft-light', backgroundSize: '320% 100%',
      background: 'linear-gradient(112deg,rgba(255,255,255,0) 36%,rgba(255,236,210,.55) 50%,rgba(255,255,255,0) 64%)' });
    sweep.style.backgroundSize = '320% 100%';
    const vig = el('div', 'fill', win, { borderRadius: 'inherit', boxShadow: 'inset 0 0 140px 30px rgba(0,0,0,.55)' });
    const glowDot = el('div', 'fill', win, { background: 'radial-gradient(circle,#fff 0%,#ffe4c4 45%,#ffb98e 100%)' });
    const idx = text(S.root, '', '', 1548, { fontSize: '26px', fontWeight: 600, letterSpacing: '.32em', textIndent: '.32em', color: '#6e6e73' });
    const word = text(S.root, '', '', 1592, { fontSize: '54px', fontWeight: 500, letterSpacing: '.6em', textIndent: '.6em', color: '#f5f5f7' });

    const shape = t => K(t, [
      [0.0, [0, 0, 0]],
      [0.55, [820, 820, 410], E.outExpo],
      [0.9, [820, 820, 410]],
      [1.1, [520, 1180, 260], E.io4],
      [1.9, [520, 1180, 260]],
      [2.1, [960, 700, 96], E.io4],
      [2.9, [960, 700, 96]],
      [3.1, [860, 860, 250], E.io4],
      [3.42, [860, 860, 250]],
      [3.86, [26, 26, 13], E.io4],
    ]);

    S.update = t => {
      const [w, h, r] = shape(t);
      Object.assign(win.style, { left: (cx - w / 2) + 'px', top: (cy - h / 2) + 'px', width: w + 'px', height: h + 'px', borderRadius: r + 'px' });
      const i = clamp(Math.floor(t), 0, 3);
      const u = t - i;
      shots.forEach((s, j) => show(s.img, j === i));
      const s = shots[i];
      const cover = Math.max(w / s.w, h / s.h, 0.001);
      const k = cover * (1.03 + 0.07 * clamp(u));
      s.img.style.transform = `translate(${w / 2 - s.w * k * s.fx + s.dx * u}px, ${h / 2 - s.h * k * s.fy + s.dy * u}px) scale(${k})`;
      const flash = i > 0 ? 1 - P(u, 0, 0.35, E.out2) : 0;
      s.img.style.filter = flash > 0.01 ? `brightness(${1 + 0.45 * flash})` : 'none';
      sweep.style.backgroundPosition = `${lerp(100, 0, clamp(u))}% 0`;
      glowDot.style.opacity = P(t, 3.55, 3.86, E.in2);
      // captions
      const on = i < 3 ? P(u, 0.12, 0.42, E.out3) * (1 - P(u, 0.8, 0.96, E.in2)) : P(u, 0.12, 0.42, E.out3) * (1 - P(t, 3.3, 3.45, E.in2));
      idx.textContent = `0${i + 1}`;
      word.textContent = s.word;
      idx.style.opacity = on * 0.9;
      word.style.opacity = on;
      word.style.transform = `translateY(${(1 - on) * 14}px)`;
      word.style.filter = on < .99 ? `blur(${(1 - on) * 6}px)` : 'none';
    };
  }

  // ======================================================================
  // B · 3.85–8.0  "hello" — then fly through the o
  // ======================================================================
  const HW = { s: 0.9, x: 0, y: 0 };          // word placement (path coords -> screen)
  HW.x = 540 - 496 * HW.s;
  HW.y = 880 - 223 * HW.s;
  const O_PATH = [807, 334];                   // centre of the o's hole in path coords
  const O_SCR = [HW.x + O_PATH[0] * HW.s, HW.y + O_PATH[1] * HW.s];
  const O_HOLE = [45 * HW.s, 58 * HW.s];       // hole radii on screen (slightly generous)
  function oZoom(t) {                           // shared by B and C
    const p = P(t, 6.95, 8.0, E.in3);
    const s = Math.exp(Math.log(42) * p);
    const q = E.io3(inv(6.95, 8.0, t));
    return { s, x: lerp(O_SCR[0], 540, q), y: lerp(O_SCR[1], 960, q), p };
  }
  {
    const S = scene('B', 3.84, 8.0, 3);
    const svg = svgLayer(S.root);
    svg.innerHTML = `<defs>
      <linearGradient id="hg" gradientUnits="userSpaceOnUse" x1="30" y1="0" x2="962" y2="0">
        <stop offset="0" stop-color="#ffc98b"/><stop offset=".5" stop-color="#ff9fb0"/><stop offset="1" stop-color="#ffe3d3"/></linearGradient>
      <filter id="hglow" x="-20%" y="-40%" width="140%" height="180%"><feGaussianBlur stdDeviation="9"/></filter></defs>`;
    const zoom = sv('g', {}, svg);
    const word = sv('g', { transform: `translate(${HW.x} ${HW.y}) scale(${HW.s})` }, zoom);
    const d = HELLO.path();
    const glow = sv('path', { d, fill: 'none', stroke: 'url(#hg)', 'stroke-width': 19, 'stroke-linecap': 'round', 'stroke-linejoin': 'round', filter: 'url(#hglow)', opacity: .6 }, word);
    const main = sv('path', { d, fill: 'none', stroke: 'url(#hg)', 'stroke-width': 17, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }, word);
    const L = main.getTotalLength();
    for (const p of [glow, main]) p.setAttribute('stroke-dasharray', `${L} ${L}`);
    const pen = el('div', 'abs', S.root, { width: '26px', height: '26px', marginLeft: '-13px', marginTop: '-13px', borderRadius: '50%',
      background: 'radial-gradient(circle,#fff 0%,#ffe4c4 45%,#ffb98e 100%)', boxShadow: '0 0 26px 8px rgba(255,190,150,.55)' });
    const start = main.getPointAtLength(0);
    const P0 = [540, 900], P2 = [HW.x + start.x * HW.s, HW.y + start.y * HW.s], P1 = [260, 760];
    const T0 = 4.3, T1 = 6.45;

    S.update = t => {
      // pen: glide from the collapsed window to the start of the h
      let px, py, pa = 1, ps = 1;
      if (t < T0) {
        const q = P(t, 3.86, T0, E.io3);
        px = (1 - q) * (1 - q) * P0[0] + 2 * (1 - q) * q * P1[0] + q * q * P2[0];
        py = (1 - q) * (1 - q) * P0[1] + 2 * (1 - q) * q * P1[1] + q * q * P2[1];
        ps = 1 - 0.35 * Math.sin(Math.PI * q);
      } else {
        const q = P(t, T0, T1, E.ioSine);
        const pt = main.getPointAtLength(L * q);
        px = HW.x + pt.x * HW.s; py = HW.y + pt.y * HW.s;
        ps = lerp(0.9, 0.8, q);
        pa = 1 - P(t, T1 - 0.05, T1 + 0.35, E.out2);
      }
      const drawn = P(t, T0, T1, E.ioSine);
      for (const p of [glow, main]) p.setAttribute('stroke-dashoffset', L * (1 - drawn));
      pen.style.transform = `translate(${px}px,${py}px) scale(${ps})`;
      pen.style.opacity = pa;
      glow.setAttribute('opacity', 0.45 + 0.25 * P(t, T1 - .2, T1 + .3, E.out2) * (1 - P(t, 7.2, 7.8)));
      // fly through the o
      const z = oZoom(t);
      zoom.setAttribute('transform', `translate(${z.x} ${z.y}) scale(${z.s}) translate(${-O_SCR[0]} ${-O_SCR[1]})`);
      svg.style.filter = z.p > 0.35 ? `blur(${(z.p - .35) * 5}px)` : 'none';
    };
  }

  // ======================================================================
  // C · 6.95–12.4  Reveal: 喵 Pro, title tucked behind the kitten
  // ======================================================================
  {
    const S = scene('C', 6.95, 12.4, 2);
    S.root.style.background = '#000';
    const inner = el('div', 'fill', S.root);
    const glow = el('div', 'fill', inner, { background: 'radial-gradient(ellipse 70% 30% at 50% 40%,rgba(255,176,120,.30),rgba(255,130,160,.10) 50%,rgba(0,0,0,0) 76%)' });
    const eyebrow = text(inner, '全新', '', 330, { fontSize: '40px', fontWeight: 600, color: '#ff9f0a', letterSpacing: '.12em', textIndent: '.12em' });
    const title = text(inner, '喵 Pro', 'grad', 398, { fontSize: '236px', fontWeight: 700, letterSpacing: '-0.02em', lineHeight: '270px' });
    title.style.background = 'linear-gradient(100deg,rgba(255,255,255,0) 40%,rgba(255,255,255,.95) 50%,rgba(255,255,255,0) 60%),var(--grad)';
    title.style.backgroundSize = '260% 100%,100% 100%';
    title.style.webkitBackgroundClip = 'text';
    const cat = img('assets/p1_cut.webp', inner);
    cat.style.webkitMaskImage = 'linear-gradient(to bottom,#000 88%,transparent 100%)';
    const tag = text(inner, '萌得很。', 'h1', 1560, { fontSize: '96px' });
    const tagCh = split(tag);
    const FACE = [1330, 900];                  // face centre in p1_cut px

    S.update = t => {
      // camera: close-up seen through the o, then pull back
      let k, ax = FACE[0], ay = FACE[1], cxs, cys;
      if (t < 8.0) {
        const z = oZoom(t);
        k = lerp(1.55, 1.25, inv(6.95, 8.0, t));
        cxs = z.x; cys = z.y;
        const rx = O_HOLE[0] * z.s, ry = O_HOLE[1] * z.s;
        S.root.style.clipPath = `ellipse(${rx}px ${ry}px at ${z.x}px ${z.y}px)`;
        ay = 960;
      } else {
        S.root.style.clipPath = 'none';
        const q = P(t, 8.0, 9.35, E.out4);
        k = lerp(1.25, 0.62, q) + 0.025 * P(t, 9.35, 12.4);
        ay = lerp(960, 900, q);
        cxs = 540; cys = lerp(960, 1190, q);
      }
      place(cat, k, ax, ay, cxs, cys);
      const g = P(t, 7.95, 8.25, E.out2);
      glow.style.opacity = g * (0.8 + 0.2 * Math.sin((t - 8) * 2.4));
      glow.style.transform = `scale(${1 + 0.25 * (1 - P(t, 8, 9.2, E.out3))})`;
      // title rises from behind the head
      const tp = P(t, 8.3, 9.45, E.out4);
      title.style.opacity = P(t, 8.3, 8.9, E.out2);
      title.style.transform = `translateY(${(1 - tp) * 170}px) scale(${lerp(1.07, 1, tp)})`;
      title.style.filter = tp < .999 ? `blur(${(1 - tp) * 18}px)` : 'none';
      title.style.backgroundPosition = `${lerp(115, -15, P(t, 10.1, 11.3, E.io3))}% 0,0 0`;
      lineIn(eyebrow, t, 8.85, { dy: 16, blur: 6 });
      charsIn(tagCh, t, 9.55, { st: 0.06, dur: 0.6 });
      // exit: page scrolls up, parallax
      const x = P(t, 11.7, 12.35, E.io4);
      inner.style.transform = x ? `translateY(${-560 * x}px)` : 'none';
      inner.style.opacity = 1 - 0.75 * x;
      vblur(inner, 'vblurC', 560 * speed(t, 11.7, 12.35, E.io4) / 60 * 0.35);
    };
  }

  // ======================================================================
  // D · 11.7–16.25  Colourways: four colours, one kitten
  // ======================================================================
  const M_START = [0, 0];      // filled in by E: where the M stroke begins on screen at 16.05
  {
    const S = scene('D', 11.7, 16.25, 4);
    const inner = el('div', 'fill', S.root);
    const bg = el('div', 'fill', inner, { background: 'radial-gradient(ellipse 90% 60% at 30% 52%,#ffffff 0%,#f5f5f7 58%,#ebebef 100%)' });
    const head = text(inner, '四种配色，一身集齐。', 'h1', 148, { color: '#1d1d1f', fontSize: '74px' });
    const headCh = split(head);
    const KS = 0.37, OX = 71, OY = 308;      // p3_cut asset scale and screen origin
    const catWrap = el('div', 'fill', inner);
    const cat = img('assets/p3_cut.webp', catWrap);
    cat.style.transform = `translate(${OX - 0}px,${OY}px) scale(${KS})`;
    const shadow = el('div', 'abs', catWrap, { left: '120px', top: '1560px', width: '520px', height: '90px', borderRadius: '50%',
      background: 'radial-gradient(closest-side,rgba(0,0,0,.16),rgba(0,0,0,0))' });
    catWrap.insertBefore(shadow, cat);
    const scr = (sx, sy) => [OX + (sx - 470) * 2 * KS, OY + (sy - 590) * 2 * KS];
    const SW = [
      { name: '琥珀金', en: 'Amber Gold', src: [922, 873], bg: 'radial-gradient(circle at 35% 30%,#f1c67e,#c9954f 60%,#9d6f35)' },
      { name: '肉垫粉', en: 'Bean Pink', src: [997, 942], bg: 'radial-gradient(circle at 35% 30%,#ffd0d3,#f0a3ab 60%,#d98590)' },
      { name: '狸花棕', en: 'Tabby Brown', src: [690, 1320], bg: 'repeating-linear-gradient(118deg,#3a3129 0 7px,#8b7862 7px 17px)' },
      { name: '奶油白', en: 'Cream White', src: [792, 2318], bg: 'radial-gradient(circle at 35% 30%,#ffffff,#f4eee6 60%,#e2d9cc)' },
    ];
    const ROWS = [540, 770, 1000, 1230];
    SW.forEach((s, i) => {
      s.row = el('div', 'abs', inner, { left: '636px', top: (ROWS[i] - 46) + 'px', width: '420px', height: '92px' });
      s.dot = el('div', 'abs', s.row, { left: 0, top: '6px', width: '80px', height: '80px', borderRadius: '50%', background: s.bg,
        boxShadow: 'inset 0 0 0 1px rgba(0,0,0,.08), 0 6px 16px rgba(0,0,0,.12)' });
      s.nm = el('div', 'abs', s.row, { left: '108px', top: '2px', fontSize: '46px', fontWeight: 700, color: '#1d1d1f', whiteSpace: 'nowrap' }, s.name);
      s.en = el('div', 'abs', s.row, { left: '110px', top: '58px', fontSize: '28px', fontWeight: 500, color: '#86868b', letterSpacing: '.04em', whiteSpace: 'nowrap' }, s.en);
      s.pt = scr(...s.src);
    });
    // the loupe (magnifier)
    const LD = 216, MAG = 2.5;
    const loupe = el('div', 'abs', inner, { width: LD + 'px', height: LD + 'px', marginLeft: -LD / 2 + 'px', marginTop: -LD / 2 + 'px',
      borderRadius: '50%', overflow: 'hidden', background: '#f3f3f5',
      boxShadow: '0 0 0 7px #fff, 0 18px 44px rgba(0,0,0,.30), 0 0 0 8px rgba(0,0,0,.05)' });
    const lImg = img('assets/p3_cut.webp', loupe);
    el('div', 'abs', loupe, { left: LD / 2 - 14 + 'px', top: LD / 2 - 1 + 'px', width: '28px', height: '2px', background: 'rgba(255,255,255,.9)', boxShadow: '0 0 2px rgba(0,0,0,.5)' });
    el('div', 'abs', loupe, { left: LD / 2 - 1 + 'px', top: LD / 2 - 14 + 'px', width: '2px', height: '28px', background: 'rgba(255,255,255,.9)', boxShadow: '0 0 2px rgba(0,0,0,.5)' });
    const ltag = el('div', 'abs', inner, { height: '40px', marginTop: '-20px', padding: '0 16px', borderRadius: '20px', background: '#1d1d1f', color: '#fff',
      fontSize: '22px', fontWeight: 600, lineHeight: '40px', fontFamily: 'Inter', letterSpacing: '.04em', whiteSpace: 'nowrap' });
    const HEX = ['#C9954F', '#F0A3AB', '#6F5E4C', '#F4EEE6'];
    const TL = [12.85, 13.45, 14.05, 14.65];
    const limited = el('div', 'abs', inner, { left: '636px', top: '1418px', whiteSpace: 'nowrap' });
    const lim1 = el('div', '', limited, { fontSize: '44px', fontWeight: 700, color: '#1d1d1f' }, '全球限量');
    const lim2 = el('div', 'grad', limited, { fontSize: '44px', fontWeight: 700, marginTop: '6px',
      background: 'linear-gradient(96deg,#e8963f,#ef6f8a)', WebkitBackgroundClip: 'text', color: 'transparent' }, '仅此一只。');

    S.update = t => {
      const enter = P(t, 11.7, 12.35, E.io4);
      inner.style.transform = `translateY(${(1 - enter) * H}px)`;
      vblur(inner, 'vblurD', H * speed(t, 11.7, 12.35, E.io4) / 60 * 0.35);
      catWrap.style.transform = `translateY(${(1 - enter) * 120}px)`;
      charsIn(headCh, t, 12.2, { st: 0.035 });
      // loupe path
      let seg = 0;
      for (let i = 1; i < 4; i++) if (t >= TL[i] - 0.1) seg = i;
      const from = SW[Math.max(0, seg - 1)].pt, to = SW[seg].pt;
      const m = seg === 0 ? 1 : P(t, TL[seg] - 0.1, TL[seg] + 0.18, E.io3);
      const lx = lerp(from[0], to[0], m), ly = lerp(from[1], to[1], m);
      const lin = P(t, 12.72, 13.0, back(1.6)) * (1 - P(t, 15.25, 15.45, E.in3));
      loupe.style.transform = `translate(${lx}px,${ly}px) scale(${lin})`;
      loupe.style.opacity = clamp(lin * 3);
      const ax = (lx - OX) / KS, ay = (ly - OY) / KS; // asset coords under the loupe
      lImg.style.transform = `translate(${LD / 2 - ax * KS * MAG}px,${LD / 2 - ay * KS * MAG}px) scale(${KS * MAG})`;
      ltag.textContent = HEX[seg];
      ltag.style.transform = `translate(${lx + LD / 2 + 18}px,${ly - LD / 2 + 26}px) scale(${lin})`;
      ltag.style.opacity = clamp(lin * 3) * P(t, 12.95, 13.1);
      // swatches
      SW.forEach((s, i) => {
        const p = P(t, TL[i] + 0.05, TL[i] + 0.55, E.out4);
        const d = P(t, TL[i] + 0.02, TL[i] + 0.42, back(2.2));
        s.dot.style.transform = `scale(${d})`;
        s.nm.style.opacity = p; s.en.style.opacity = p * 0.95;
        s.nm.style.transform = s.en.style.transform = `translateX(${(1 - p) * 30}px)`;
      });
      lineIn(lim1, t, 15.0, { dy: 20 });
      lineIn(lim2, t, 15.12, { dy: 20 });
      // exit: dots converge into a glowing point, the page goes dark
      const x = P(t, 15.5, 16.05, E.io3);
      const fade = 1 - P(t, 15.4, 15.62, E.in2);
      head.style.opacity = catWrap.style.opacity = limited.style.opacity = fade;
      SW.forEach(s => { s.nm.style.opacity *= fade; s.en.style.opacity *= fade; });
      if (x > 0) {
        SW.forEach((s, i) => {
          const sx = 636 + 40, sy = ROWS[i];
          const tx = lerp(sx, M_START[0], x), ty = lerp(sy, M_START[1], x);
          s.dot.style.transform = `translate(${tx - sx}px,${ty - sy}px) scale(${lerp(1, 0.33, x)})`;
          s.dot.style.filter = `brightness(${1 + x * 0.6})`;
          s.dot.style.boxShadow = `0 0 ${40 * x}px ${10 * x}px rgba(255,190,140,${0.6 * x})`;
        });
      } else SW.forEach(s => { s.dot.style.filter = 'none'; s.dot.style.boxShadow = 'inset 0 0 0 1px rgba(0,0,0,.08), 0 6px 16px rgba(0,0,0,.12)'; });
      const dk = P(t, 15.45, 15.9, E.io3);
      bg.style.clipPath = dk > 0 ? `circle(${lerp(1500, 0, dk)}px at ${M_START[0]}px ${M_START[1] - (1 - enter) * 0}px)` : 'none';
      S.root.style.background = dk > 0 ? '#000' : 'transparent';
    };
  }

  // ======================================================================
  // E · 15.95–20.1  The forehead "M" becomes the M-series chip
  // ======================================================================
  {
    const S = scene('E', 15.95, 20.1, 5);
    const cam = el('div', 'abs', S.root, { transformOrigin: '0 0', width: '1980px', height: '2530px' });
    const photo = img('assets/p1_face22.jpg', cam);
    const ms = sv('svg', { width: 1980, height: 2530, viewBox: '0 0 1980 2530' }, cam);
    Object.assign(ms.style, { position: 'absolute', left: 0, top: 0 });
    ms.innerHTML = `<defs><linearGradient id="mg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#fff3d9"/><stop offset=".5" stop-color="#ffc97c"/><stop offset="1" stop-color="#ff9fb4"/></linearGradient>
      <filter id="mglow" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="14"/></filter></defs>`;
    const MD = 'M 748 1276 L 792 770 L 1023 1100 L 1254 770 L 1298 1298';
    const mG = sv('g', {}, ms);
    const mGlow = sv('path', { d: MD, fill: 'none', stroke: '#ffb070', 'stroke-width': 34, 'stroke-linecap': 'round', 'stroke-linejoin': 'round', filter: 'url(#mglow)' }, mG);
    const mLine = sv('path', { d: MD, fill: 'none', stroke: 'url(#mg)', 'stroke-width': 17, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }, mG);
    const ML = mLine.getTotalLength();
    for (const p of [mGlow, mLine]) p.setAttribute('stroke-dasharray', `${ML} ${ML}`);
    const tip = sv('circle', { r: 16, fill: '#fff' }, mG);
    const MC = [1023, 1030];
    const cam0 = { k: 0.78, x: 540, y: 800 };
    M_START[0] = cam0.x + (748 - MC[0]) * cam0.k;
    M_START[1] = cam0.y + (1276 - MC[1]) * cam0.k;

    // traces behind the chip
    const tr = svgLayer(S.root);
    const traces = [];
    const addTrace = pts => traces.push(pts);
    for (const x of [352, 448, 632, 728]) { const dx = x < 540 ? -64 : 64; addTrace([[x, 548], [x, 478], [x + dx, 414], [x + dx, -20]]); addTrace([[x, 1052], [x, 1100], [x + dx, 1150]]); }
    for (const y of [650, 752, 848, 950]) { const dy = y < 800 ? -60 : 60; addTrace([[288, y], [222, y], [162, y + dy], [-20, y + dy]]); addTrace([[792, y], [858, y], [918, y + dy], [1100, y + dy]]); }
    const trEls = traces.map(pts => {
      const d = 'M ' + pts.map(p => p.join(' ')).join(' L ');
      const base = sv('path', { d, fill: 'none', stroke: 'rgba(255,196,150,.28)', 'stroke-width': 3, 'stroke-linejoin': 'round' }, tr);
      const pulse = sv('path', { d, fill: 'none', stroke: '#ffd2a8', 'stroke-width': 4, 'stroke-linecap': 'round' }, tr);
      const len = base.getTotalLength();
      base.setAttribute('stroke-dasharray', `${len} ${len}`);
      pulse.setAttribute('stroke-dasharray', `60 ${len + 200}`);
      const dot = sv('circle', { r: 6, fill: '#ffcf9f', cx: pts[pts.length - 1][0], cy: pts[pts.length - 1][1] }, tr);
      return { base, pulse, len, dot, seed: frac(traces.indexOf(pts) * 0.618034) };
    });
    const chipHolder = el('div', 'abs', S.root, { left: '290px', top: '550px', width: '500px', height: '500px' });
    const chip = buildChip(chipHolder);
    const flash = el('div', 'fill', S.root, { background: 'radial-gradient(circle at 50% 42%,rgba(255,230,200,.9),rgba(255,180,140,.25) 30%,rgba(0,0,0,0) 60%)' });
    const l1 = text(S.root, 'M 系列芯片', 'h1', 1190, { fontSize: '100px' });
    const l2 = text(S.root, '额头自带。', 'h1', 1310, { fontSize: '100px' });
    const l3 = text(S.root, '8 核撒娇引擎 · 神经网络秒识开罐声', 'sub', 1452, { fontSize: '36px', color: '#86868b' });
    const l1c = split(l1), l2c = gradSplit(l2, 'var(--grad)');

    S.update = t => {
      const k = lerp(0.78, 1.0, P(t, 15.95, 17.3, E.io3));
      cam.style.transform = `translate(${540 - MC[0] * k}px,${800 - MC[1] * k}px) scale(${k})`;
      const po = P(t, 15.95, 16.3, E.out2) * (1 - P(t, 17.25, 17.8, E.in2));
      photo.style.opacity = po;
      const br = lerp(0.95, 0.38, P(t, 16.2, 17.0, E.io3));
      const bl = 14 * P(t, 17.2, 17.8, E.in2);
      photo.style.filter = `brightness(${br})` + (bl > .05 ? ` blur(${bl}px)` : '');
      const dp = P(t, 16.05, 16.95, E.io3);
      for (const p of [mGlow, mLine]) p.setAttribute('stroke-dashoffset', ML * (1 - dp));
      const tp = mLine.getPointAtLength(ML * dp);
      tip.setAttribute('cx', tp.x); tip.setAttribute('cy', tp.y);
      tip.setAttribute('opacity', P(t, 15.98, 16.1) * (1 - P(t, 16.9, 17.15)));
      mGlow.setAttribute('opacity', 0.9 + 0.1 * Math.sin(t * 9));
      // M shrinks into the chip
      const mm = P(t, 17.25, 17.85, E.io3);
      mG.setAttribute('transform', `translate(${MC[0]} ${MC[1] - 120 * mm}) scale(${lerp(1, 0.36, mm)}) translate(${-MC[0]} ${-MC[1]})`);
      mG.setAttribute('opacity', 1 - P(t, 17.5, 17.85));
      // chip
      const cp = P(t, 17.35, 17.95, E.out4);
      const ex = P(t, 19.72, 20.05, E.in3);
      chip.wrap.style.opacity = P(t, 17.35, 17.7) * (1 - ex);
      chip.wrap.style.transform = `scale(${lerp(0.72, 1, cp) * (1 + 0.45 * ex)})`;
      chip.wrap.style.filter = ex > 0 ? `brightness(${1 + 1.5 * ex})` : 'none';
      chip.set(t, (t - 17.35) * 70, lerp(110, -10, P(t, 17.9, 19.0, E.io3)));
      // traces
      const tprog = P(t, 17.55, 18.45, E.io3);
      const tfade = 1 - P(t, 19.6, 19.9);
      trEls.forEach((e, i) => {
        e.base.setAttribute('stroke-dashoffset', e.len * (1 - tprog));
        e.base.setAttribute('opacity', tfade);
        const ph = frac((t - 18.2) * 0.9 + e.seed);
        e.pulse.setAttribute('stroke-dashoffset', -ph * (e.len + 60) + 60);
        e.pulse.setAttribute('opacity', P(t, 18.3, 18.6) * tfade * 0.9);
        e.dot.setAttribute('opacity', P(t, 18.2 + i * 0.01, 18.45 + i * 0.01) * tfade);
      });
      flash.style.opacity = P(t, 19.82, 19.95, E.out2) * (1 - P(t, 19.95, 20.1));
      charsIn(l1c, t, 18.15, { st: 0.04 });
      charsIn(l2c, t, 18.4, { st: 0.05 });
      lineIn(l3, t, 18.8, { dy: 16 });
      const tf = 1 - P(t, 19.6, 19.85, E.in2);
      l1.style.opacity = l2.style.opacity = tf;
      l3.style.opacity *= tf;
    };
  }

  // ======================================================================
  // F · 19.95–24.4  Eyes: Super Retina, then Night mode
  // ======================================================================
  {
    const S = scene('F', 20.0, 24.4, 6);
    S.root.style.background = '#000';
    const EY1 = [546, 1239], EY2 = [855, 1176], MID = [700, 1207], ER = 75;
    const base = img('assets/p3_face3x.jpg', S.root);
    const night = el('div', 'fill', S.root, { background: 'rgba(3,7,18,1)' });
    const eyeWrap = el('div', 'fill', S.root);
    const eyes = img('assets/p3_face3x.jpg', eyeWrap);
    const shine = [0, 1].map(() => el('div', 'abs', S.root, { borderRadius: '50%', mixBlendMode: 'screen',
      background: 'radial-gradient(circle,rgba(225,255,170,.85) 0%,rgba(170,235,120,.38) 30%,rgba(120,200,90,0) 68%)' }));
    const scrim = el('div', 'fill', S.root, { background: 'linear-gradient(to bottom,rgba(0,0,0,0) 0%,rgba(0,0,0,0) 56%,rgba(0,0,0,.78) 78%,rgba(0,0,0,.92) 100%)' });
    const ui = svgLayer(S.root);
    const brackets = [0, 1, 2, 3].map(() => sv('path', { fill: 'none', stroke: '#ffd60a', 'stroke-width': 5, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }, ui));
    const h1 = text(S.root, '一眼，就沦陷。', 'h1', 1372, { fontSize: '96px' });
    const s1 = text(S.root, '琥珀色 · 超视网膜 XDR 双眸', 'sub', 1508, { color: '#d2d2d7' });
    const h2 = text(S.root, '夜间模式，天生自带。', 'h1', 1372, { fontSize: '90px' });
    const s2 = text(S.root, '只需人类约 1/6 的光线，就能看清', 'sub', 1508, { color: '#d2d2d7' });
    const h1c = split(h1), h2c = split(h2);
    const badge = el('div', 'abs', S.root, { left: '540px', top: '150px', height: '66px', padding: '0 30px 0 24px', borderRadius: '33px',
      background: '#ffd60a', color: '#000', display: 'flex', alignItems: 'center', gap: '12px', fontSize: '32px', fontWeight: 700, whiteSpace: 'nowrap',
      transformOrigin: '0 50%' });
    el('div', '', badge, { width: '34px', height: '34px' }, ICON.moon('#000'));
    el('span', '', badge, {}, '夜间模式');

    S.update = t => {
      const k = K(t, [[20.0, 0.9], [20.55, 0.8, E.out3], [24.4, 0.9, E.lin]]);
      place(base, k, MID[0], MID[1], 540, 860);
      place(eyes, k, MID[0], MID[1], 540, 860);
      const p1 = [540 + (EY1[0] - MID[0]) * k, 860 + (EY1[1] - MID[1]) * k];
      const p2 = [540 + (EY2[0] - MID[0]) * k, 860 + (EY2[1] - MID[1]) * k];
      const r = ER * k;
      const nm = P(t, 21.95, 22.45, E.io3);
      const out = P(t, 23.9, 24.2, E.in2);
      base.style.filter = `saturate(${lerp(1.05, 0.35, nm)}) brightness(${lerp(1, 0.75, nm)})`;
      base.style.opacity = 1 - out;
      night.style.opacity = 0.86 * nm;
      eyeWrap.style.display = nm > 0 ? '' : 'none';
      const m = `radial-gradient(circle ${r * 1.18}px at ${p1[0]}px ${p1[1]}px,#000 72%,transparent 100%),radial-gradient(circle ${r * 1.18}px at ${p2[0]}px ${p2[1]}px,#000 72%,transparent 100%)`;
      eyeWrap.style.webkitMaskImage = m;
      eyeWrap.style.opacity = nm * (1 - P(t, 24.12, 24.38));
      eyes.style.filter = `brightness(${1.2 + 0.25 * nm}) saturate(1.25) contrast(1.08)`;
      const gl = P(t, 22.1, 22.7, E.out2) * (0.85 + 0.15 * Math.sin(t * 5)) * (1 - P(t, 24.1, 24.38));
      [p1, p2].forEach((p, i) => {
        const d = r * 5.2;
        Object.assign(shine[i].style, { left: p[0] - d / 2 + 'px', top: p[1] - d / 2 + 'px', width: d + 'px', height: d + 'px', opacity: gl });
      });
      scrim.style.opacity = 1 - out;
      // autofocus brackets around both eyes
      const bp = P(t, 20.3, 20.6, E.out4);
      const blink = (t > 20.72 && t < 20.8) || (t > 20.88 && t < 20.96) ? 0.35 : 1;
      const bo = bp * blink * (1 - P(t, 21.8, 21.98));
      const sc = lerp(1.25, 1, bp);
      const cx = (p1[0] + p2[0]) / 2, cy = (p1[1] + p2[1]) / 2;
      const hw = ((p2[0] - p1[0]) / 2 + r * 1.9) * sc, hh = (Math.abs(p2[1] - p1[1]) / 2 + r * 1.55) * sc, c = 46;
      const corners = [[-1, -1], [1, -1], [1, 1], [-1, 1]];
      corners.forEach(([sx, sy], i) => {
        const x = cx + sx * hw, y = cy + sy * hh;
        brackets[i].setAttribute('d', `M ${x} ${y - sy * c} L ${x} ${y} L ${x - sx * c} ${y}`);
        brackets[i].setAttribute('opacity', bo);
      });
      charsIn(h1c, t, 20.5, { st: 0.05 });
      lineIn(s1, t, 20.85, { dy: 16 });
      const o1 = 1 - P(t, 21.78, 21.98, E.in2);
      h1.style.opacity = o1; s1.style.opacity *= o1;
      const bdg = P(t, 22.1, 22.55, spring(2.4, 0.5));
      badge.style.transform = `translateX(-50%) scale(${bdg})`;
      badge.style.opacity = clamp(bdg * 2) * (1 - out);
      charsIn(h2c, t, 22.35, { st: 0.045 });
      lineIn(s2, t, 22.7, { dy: 16 });
      h2.style.opacity = 1 - out; s2.style.opacity *= 1 - out;
    };
  }

  // ======================================================================
  // G · 24.05–30.5  Sensor suite, then Nose ID
  // ======================================================================
  const FID = { x: 540, y: 900, r: 400 };
  {
    const S = scene('G', 24.05, 30.5, 7);
    const light = el('div', 'fill', S.root, { background: 'radial-gradient(ellipse 70% 40% at 50% 42%,rgba(255,200,160,.14),rgba(0,0,0,0) 70%)' });
    const clip = el('div', 'fill', S.root);
    const cam = el('div', 'abs', clip, { width: '2376px', height: '1310px', transformOrigin: '0 0' });
    const cat = img('assets/p1_cut.webp', cam);
    const dots = el('div', 'abs', cam, { left: 0, top: 0, width: '2376px', height: '1310px',
      background: 'radial-gradient(circle,rgba(120,225,255,1) 0 3px,rgba(120,225,255,0) 4.4px)', backgroundSize: '30px 30px' });
    const scan = el('div', 'abs', cam, { top: 0, width: '6px', height: '1310px', marginLeft: '-3px',
      background: 'linear-gradient(to bottom,rgba(140,230,255,0),rgba(170,240,255,.95) 20%,rgba(170,240,255,.95) 80%,rgba(140,230,255,0))',
      boxShadow: '0 0 30px 8px rgba(120,220,255,.45)' });
    const sweep = el('div', 'abs', S.root, { left: 0, width: '1080px', height: '4px', marginTop: '-2px',
      background: 'linear-gradient(90deg,rgba(150,230,255,0),rgba(190,240,255,.95) 30%,rgba(190,240,255,.95) 70%,rgba(150,230,255,0))',
      boxShadow: '0 0 28px 6px rgba(120,210,255,.45)' });
    const waves = svgLayer(S.root);
    const arcs = [];
    for (let e = 0; e < 2; e++) for (let i = 0; i < 4; i++) arcs.push({ e, i, p: sv('path', { fill: 'none', stroke: '#fff', 'stroke-width': 5, 'stroke-linecap': 'round' }, waves) });
    const earDots = [0, 1].map(() => sv('circle', { r: 9, fill: '#fff' }, waves));
    const reticle = sv('circle', { r: 50, fill: 'none', stroke: '#fff', 'stroke-width': 3 }, waves);
    const ticks = svgLayer(S.root);
    const NT = 96, tk = [];
    for (let i = 0; i < NT; i++) {
      const a = -Math.PI / 2 + (i / NT) * Math.PI * 2;
      tk.push(sv('line', { x1: FID.x + Math.cos(a) * 446, y1: FID.y + Math.sin(a) * 446, x2: FID.x + Math.cos(a) * 488, y2: FID.y + Math.sin(a) * 488,
        stroke: '#3a3a3c', 'stroke-width': 7, 'stroke-linecap': 'round' }, ticks));
    }
    const checkDisc = el('div', 'abs', S.root, { left: FID.x - 105 + 'px', top: FID.y - 105 + 'px', width: '210px', height: '210px', borderRadius: '50%',
      background: 'rgba(48,209,88,.92)', boxShadow: '0 0 60px rgba(48,209,88,.55)' });
    const checkSvg = sv('svg', { viewBox: '0 0 100 100', width: 210, height: 210 }, checkDisc);
    const checkPath = sv('path', { d: 'M 27 52 L 43 68 L 74 35', fill: 'none', stroke: '#fff', 'stroke-width': 9, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }, checkSvg);
    const CL = checkPath.getTotalLength();
    checkPath.setAttribute('stroke-dasharray', `${CL} ${CL}`);
    const earT = text(S.root, '空间音频', 'h1', 196, { fontSize: '80px' });
    const earS = text(S.root, '每只耳朵 32 块肌肉，可转向 180°', 'sub', 308, { fontSize: '40px' });
    const lidT = text(S.root, '胡须 LiDAR', 'h1', 1338, { fontSize: '80px' });
    const lidS = text(S.root, '24 根触须，丈量每一道缝隙', 'sub', 1450, { fontSize: '40px' });
    const idT = text(S.root, 'Nose ID', 'h1', 1398, { fontSize: '104px', fontWeight: 700, letterSpacing: '-0.02em' });
    const idS = text(S.root, '爱心鼻头，全球独一无二。', 'sub', 1534);
    const earTc = split(earT), lidTc = split(lidT);
    const cut2scr = (cx, cy, k, a, s) => [s[0] + (cx - a[0]) * k, s[1] + (cy - a[1]) * k];
    const EARS = [[880, 330], [1810, 380]];
    const NOSE = [1320, 1112];

    S.update = t => {
      const z = P(t, 27.0, 27.75, E.io3);
      const k = lerp(lerp(0.56, 0.6, P(t, 24.05, 27.0)), 1.08, z) + 0.04 * P(t, 27.75, 30.5);
      const a = [1330, lerp(900, 985, z)], s = [540, lerp(975, FID.y, z)];
      cam.style.transform = `translate(${s[0] - a[0] * k}px,${s[1] - a[1] * k}px) scale(${k})`;
      // reveal: top-down light scan
      const rv = P(t, 24.08, 24.95, E.io3);
      const ry = lerp(330, 1330, rv);
      clip.style.webkitMaskImage = rv < 1 ? `linear-gradient(to bottom,#000 ${ry - 220}px,transparent ${ry}px)` : 'none';
      sweep.style.top = (ry - 40) + 'px';
      sweep.style.opacity = rv > 0 && rv < 1 ? Math.sin(Math.PI * rv) : 0;
      const R = lerp(1500, FID.r, z);
      clip.style.clipPath = z > 0 ? `circle(${R}px at ${FID.x}px ${FID.y}px)` : 'none';
      const idp = P(t, 29.0, 29.35, E.out3);
      cat.style.filter = `brightness(${lerp(1, 0.5, idp) * (0.92 + 0.08 * rv)})`;
      light.style.opacity = 1 - z;
      // ears: incoming sound waves
      const wv = P(t, 24.45, 24.8) * (1 - P(t, 26.85, 27.1));
      EARS.forEach((e, j) => {
        const p = cut2scr(e[0], e[1], k, a, s);
        earDots[j].setAttribute('cx', p[0]); earDots[j].setAttribute('cy', p[1]);
        earDots[j].setAttribute('opacity', wv * (0.75 + 0.25 * Math.sin(t * 8)));
      });
      arcs.forEach(A => {
        const p = cut2scr(EARS[A.e][0], EARS[A.e][1], k, a, s);
        const ph = frac(-(t - 24.4) * 0.95 + A.i / 4);
        const rr = 40 + 190 * ph;
        const mid = A.e === 0 ? -128 : -52, span = 38;
        const a0 = (mid - span) * Math.PI / 180, a1 = (mid + span) * Math.PI / 180;
        A.p.setAttribute('d', `M ${p[0] + Math.cos(a0) * rr} ${p[1] + Math.sin(a0) * rr} A ${rr} ${rr} 0 0 1 ${p[0] + Math.cos(a1) * rr} ${p[1] + Math.sin(a1) * rr}`);
        A.p.setAttribute('opacity', wv * Math.sin(Math.PI * ph) * 0.9);
      });
      charsIn(earTc, t, 24.5, { st: 0.05 });
      lineIn(earS, t, 24.75, { dy: 16 });
      // whiskers: LiDAR scan across the kitten
      const b = lerp(-8, 112, P(t, 25.4, 26.55, E.io3));
      const lv = P(t, 25.35, 25.5) * (1 - P(t, 26.7, 27.0));
      const mask = `url(assets/p1_cut.webp), linear-gradient(90deg,rgba(0,0,0,.28) ${b - 40}%,#000 ${b - 3}%,#000 ${b}%,transparent ${b + 0.5}%)`;
      dots.style.webkitMaskImage = mask;
      dots.style.webkitMaskSize = '100% 100%, 100% 100%';
      dots.style.webkitMaskComposite = 'source-in';
      dots.style.maskComposite = 'intersect';
      dots.style.opacity = lv;
      scan.style.left = (b / 100) * 2376 + 'px';
      scan.style.opacity = lv * (b > -2 && b < 104 ? 1 : 0);
      charsIn(lidTc, t, 25.45, { st: 0.05 });
      lineIn(lidS, t, 25.7, { dy: 16 });
      const lf = 1 - P(t, 26.85, 27.1, E.in2);
      [earT, lidT].forEach(e => { e.style.opacity = lf; });
      earS.style.opacity *= lf; lidS.style.opacity *= lf;
      // nose reticle
      const np = cut2scr(NOSE[0], NOSE[1], k, a, s);
      const rp = P(t, 26.25, 26.55, E.out3) * (1 - P(t, 27.05, 27.3));
      reticle.setAttribute('cx', np[0]); reticle.setAttribute('cy', np[1]);
      reticle.setAttribute('r', lerp(90, 46, rp) + 5 * Math.sin(t * 10));
      reticle.setAttribute('opacity', rp);
      // Face ID ring
      const ta = P(t, 27.55, 27.85, E.out3) * (1 - P(t, 29.62, 29.85));
      const fill = P(t, 27.85, 28.95, E.io3);
      const pulse = 1 + 0.035 * Math.sin(Math.PI * P(t, 28.95, 29.3));
      ticks.style.opacity = ta;
      ticks.style.transformOrigin = `${FID.x}px ${FID.y}px`;
      ticks.style.transform = `scale(${lerp(0.94, 1, ta) * pulse})`;
      for (let i = 0; i < NT; i++) {
        const on = clamp((fill * (NT + 6) - i) / 6);
        tk[i].setAttribute('stroke', on > 0.5 ? '#30d158' : '#3a3a3c');
        tk[i].setAttribute('stroke-opacity', on > 0.5 ? 1 : 0.9);
      }
      const cd = P(t, 29.0, 29.3, spring(2.6, 0.55)) * (1 - P(t, 29.62, 29.85));
      checkDisc.style.transform = `scale(${cd})`;
      checkDisc.style.opacity = clamp(cd * 2);
      checkPath.setAttribute('stroke-dashoffset', CL * (1 - P(t, 29.1, 29.35, E.out3)));
      lineIn(idT, t, 29.05, { dy: 24, out: 29.62, outDur: 0.25 });
      lineIn(idS, t, 29.2, { dy: 18, out: 29.62, outDur: 0.25 });
      clip.style.opacity = 1 - P(t, 30.0, 30.3);
    };
  }

  // ======================================================================
  // I · 29.6–33.4  MagSafe: snaps onto your keyboard
  // ======================================================================
  {
    const S = scene('I', 29.6, 33.4, 8);
    const clip = el('div', 'fill', S.root);
    const photo = img('assets/p2_full.jpg', clip);
    const scrim = el('div', 'fill', clip, { background: 'linear-gradient(to bottom,rgba(0,0,0,.78) 0%,rgba(0,0,0,.45) 16%,rgba(0,0,0,0) 30%)' });
    const glass = el('div', 'abs', S.root, { borderRadius: '50%', backdropFilter: 'blur(16px) saturate(1.4)', WebkitBackdropFilter: 'blur(16px) saturate(1.4)',
      background: 'rgba(255,255,255,.14)' });
    const paw = el('div', 'abs', S.root, { width: '118px', height: '118px', left: 540 - 59 + 'px', top: 900 - 59 + 'px' }, ICON.paw('#fff'));
    const ring = svgLayer(S.root);
    ring.innerHTML = `<defs><filter id="rglow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="10" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>`;
    const main = sv('circle', { cx: 540, cy: 900, r: 466, fill: 'none', stroke: '#fff', 'stroke-width': 12, filter: 'url(#rglow)' }, ring);
    const ripple = sv('circle', { cx: 540, cy: 900, r: 170, fill: 'none', stroke: '#fff', 'stroke-width': 6 }, ring);
    const beanRing = sv('circle', { r: 66, fill: 'none', stroke: '#fff', 'stroke-width': 4 }, ring);
    const beanLine = sv('path', { fill: 'none', stroke: '#fff', 'stroke-width': 3 }, ring);
    const beanTag = el('div', 'abs', S.root, { height: '64px', padding: '0 26px', borderRadius: '32px', lineHeight: '64px', fontSize: '32px', fontWeight: 600,
      background: 'rgba(20,20,22,.55)', backdropFilter: 'blur(14px)', WebkitBackdropFilter: 'blur(14px)', whiteSpace: 'nowrap', color: '#fff' }, '粉色 Q 弹肉垫');
    const h = text(S.root, 'MagSafe 磁吸设计', 'h1', 150, { fontSize: '88px' });
    const sub = text(S.root, '一靠近键盘，就自动吸附。', 'sub', 272, { color: '#e5e5ea' });
    const hc = split(h);
    const ANC = [1080, 1250];

    S.update = t => {
      const k = lerp(0.8, 0.845, P(t, 29.6, 33.4));
      place(photo, k, ANC[0], ANC[1], 540, 900);
      const R = K(t, [[29.6, 400], [30.0, 400], [30.55, 1250, E.io3]]);
      clip.style.clipPath = R < 1240 ? `circle(${R}px at 540px 900px)` : 'none';
      clip.style.opacity = P(t, 29.6, 30.0, E.io3);
      const dim = P(t, 32.85, 33.35, E.in2);
      photo.style.filter = `brightness(${0.84 * (1 - 0.8 * dim)})`;
      scrim.style.opacity = P(t, 30.3, 30.7);
      // ring: from the Face ID radius down to MagSafe size
      const rr = t < 30.05 ? 466 : lerp(466, 170, P(t, 30.05, 30.6, spring(2.1, 0.5)));
      main.setAttribute('r', rr);
      main.setAttribute('opacity', P(t, 29.62, 29.9) * (1 - dim));
      main.setAttribute('stroke-width', lerp(12, 10, P(t, 30.05, 30.5)));
      const rp = P(t, 30.5, 31.3, E.out3);
      ripple.setAttribute('r', lerp(170, 600, rp));
      ripple.setAttribute('opacity', (t > 30.5 ? 0.9 : 0) * (1 - rp));
      const gp = P(t, 30.45, 30.75, E.out3) * (1 - dim);
      Object.assign(glass.style, { left: 540 - rr + 'px', top: 900 - rr + 'px', width: 2 * rr + 'px', height: 2 * rr + 'px', opacity: gp });
      const pp = P(t, 30.55, 30.95, spring(2.4, 0.5));
      paw.style.transform = `scale(${pp})`;
      paw.style.opacity = clamp(pp * 2) * (1 - dim);
      // toe beans callout
      const bx = 540 + (660 - ANC[0]) * k, by = 900 + (2050 - ANC[1]) * k;
      const bp = P(t, 31.55, 31.9, E.out4) * (1 - dim);
      beanRing.setAttribute('cx', bx); beanRing.setAttribute('cy', by);
      beanRing.setAttribute('r', lerp(96, 66, bp)); beanRing.setAttribute('opacity', bp);
      const lx = bx + 66, ly = by - 58;
      beanLine.setAttribute('d', `M ${bx + 47} ${by - 47} L ${lerp(bx + 47, lx + 30, bp)} ${lerp(by - 47, ly - 30, bp)}`);
      beanLine.setAttribute('opacity', bp);
      beanTag.style.transform = `translate(${lx + 30}px,${ly - 62}px)`;
      beanTag.style.opacity = P(t, 31.75, 32.05, E.out3) * (1 - dim);
      charsIn(hc, t, 30.65, { st: 0.035 });
      lineIn(sub, t, 30.95, { dy: 16 });
      h.style.opacity = 1 - dim; sub.style.opacity *= 1 - dim;
    };
  }

  // ======================================================================
  // J · 32.9–36.5  Battery life, mostly by sleeping
  // ======================================================================
  const T5 = { x: 549, y: 930, w: 495, h: 260 };   // bento tile J collapses into
  {
    const S = scene('J', 32.9, 36.5, 9);
    S.root.style.background = '#000';
    const inner = el('div', 'fill', S.root, { transformOrigin: `${T5.x + T5.w / 2}px ${T5.y + T5.h / 2}px` });
    const photo = img('assets/p1_full.jpg', inner);
    el('div', 'fill', inner, { background: 'linear-gradient(180deg,rgba(40,36,120,.42),rgba(16,14,60,.5))' });
    el('div', 'fill', inner, { background: 'linear-gradient(to bottom,rgba(0,0,0,.35) 0%,rgba(0,0,0,0) 22%,rgba(0,0,0,0) 56%,rgba(0,0,0,.86) 70%,#000 86%)' });
    const stars = [];
    for (let i = 0; i < 26; i++) {
      const x = (i * 397) % 1040 + 20, y = 40 + ((i * 211) % 460);
      stars.push({ e: el('div', 'abs', inner, { left: x + 'px', top: y + 'px', width: '4px', height: '4px', borderRadius: '50%', background: '#fff', boxShadow: '0 0 8px #fff' }), ph: i * 1.7 });
    }
    const di = el('div', 'abs', inner, { left: '540px', top: '52px', background: '#000', borderRadius: '70px', overflow: 'hidden',
      boxShadow: '0 0 0 1.5px rgba(255,255,255,.14), 0 18px 50px rgba(0,0,0,.6)' });
    const diIn = el('div', 'abs', di, { left: 0, top: 0, width: '860px', height: '144px', display: 'flex', alignItems: 'center', padding: '0 34px', gap: '26px' });
    const moonDisc = el('div', '', diIn, { width: '88px', height: '88px', borderRadius: '50%', background: '#5e5ce6', display: 'flex', alignItems: 'center', justifyContent: 'center', flex: '0 0 auto' });
    el('div', '', moonDisc, { width: '46px', height: '46px' }, ICON.moon('#fff'));
    el('div', '', diIn, { fontSize: '44px', fontWeight: 700, color: '#fff', flex: '1 1 auto', whiteSpace: 'nowrap' }, '睡眠模式');
    el('div', '', diIn, { fontSize: '36px', fontWeight: 600, color: '#a9a7ff', whiteSpace: 'nowrap', paddingRight: '8px' }, '已开启');
    const h1 = text(inner, '超长续航，', 'h1', 296, { fontSize: '100px' });
    const h2 = text(inner, '主要靠睡。', 'h1', 414, { fontSize: '100px' });
    const h1c = split(h1), h2c = gradSplit(h2, 'linear-gradient(96deg,#d6d4ff,#a3a1ff 50%,#ffc2d6)');
    const pre = el('div', 't', inner, { top: '1268px', fontSize: '40px', fontWeight: 600, color: '#a1a1a6', display: 'flex', justifyContent: 'center', alignItems: 'center', gap: '18px' });
    const bat = el('div', '', pre, { position: 'relative', width: '92px', height: '44px', borderRadius: '12px', border: '4px solid #d1d1d6', flex: '0 0 auto' });
    el('div', 'abs', bat, { left: '96px', top: '11px', width: '7px', height: '14px', borderRadius: '0 4px 4px 0', background: '#d1d1d6' });
    const batFill = el('div', 'abs', bat, { left: '4px', top: '4px', height: '28px', borderRadius: '5px', background: '#30d158' });
    el('span', '', pre, {}, '最长可达');
    const big = el('div', 't', inner, { top: '1318px', whiteSpace: 'nowrap', lineHeight: '270px' });
    const num = el('span', '', big, { fontSize: '260px', fontWeight: 700, letterSpacing: '-0.03em', fontVariantNumeric: 'tabular-nums',
      background: 'linear-gradient(180deg,#ffffff 30%,#b9b7ff 100%)', WebkitBackgroundClip: 'text', color: 'transparent' }, '20');
    el('span', '', big, { fontSize: '84px', fontWeight: 700, marginLeft: '14px', color: '#fff' }, '小时');
    const post = text(inner, '每日睡眠续航', 'sub', 1596, { fontSize: '38px', color: '#a1a1a6' });

    S.update = t => {
      S.root.style.opacity = P(t, 32.9, 33.3, E.io3);
      const k = lerp(1.1, 1.16, P(t, 32.9, 36.5));
      place(photo, k, 1530, 1100, 540, 840);
      photo.style.filter = 'brightness(.6) saturate(.62) contrast(1.06)';
      stars.forEach(s => { s.e.style.opacity = (0.25 + 0.55 * (0.5 + 0.5 * Math.sin(t * 2.2 + s.ph))) * P(t, 33.2, 33.8); });
      // Dynamic Island expands
      const ap = P(t, 33.05, 33.25, E.out3);
      const ex = P(t, 33.2, 33.75, spring(2.0, 0.62));
      const w = lerp(250, 860, ex), hh = lerp(76, 144, ex);
      Object.assign(di.style, { width: w + 'px', height: hh + 'px', marginLeft: -w / 2 + 'px', opacity: ap, borderRadius: hh / 2 + 'px' });
      diIn.style.opacity = P(t, 33.45, 33.7);
      diIn.style.transform = `translateY(${(hh - 144) / 2}px) scale(${lerp(0.9, 1, P(t, 33.4, 33.7, E.out3))})`;
      charsIn(h1c, t, 33.55, { st: 0.05 });
      charsIn(h2c, t, 33.8, { st: 0.05 });
      lineIn(pre, t, 33.95, { dy: 16 });
      const c = P(t, 34.05, 34.95, E.out3);
      num.textContent = String(Math.round(20 * c)).padStart(2, ' ');
      batFill.style.width = 76 * c + 'px';
      batFill.style.background = c < 0.25 ? '#ff453a' : c < 0.55 ? '#ffd60a' : '#30d158';
      lineIn(big, t, 34.0, { dy: 30, blur: 14 });
      lineIn(post, t, 34.3, { dy: 16 });
      // collapse into the bento tile
      const cp = P(t, 35.8, 36.42, E.io4);
      if (cp > 0) {
        const top = lerp(0, T5.y, cp), left = lerp(0, T5.x, cp), right = lerp(0, W - T5.x - T5.w, cp), bottom = lerp(0, H - T5.y - T5.h, cp);
        S.root.style.clipPath = `inset(${top}px ${right}px ${bottom}px ${left}px round ${lerp(0, 36, cp)}px)`;
        inner.style.transform = `scale(${lerp(1, 0.86, cp)})`;
      } else { S.root.style.clipPath = 'none'; inner.style.transform = 'none'; }
    };
  }

  // ======================================================================
  // K · 35.8–40.2  Bento recap
  // ======================================================================
  {
    const S = scene('K', 35.8, 40.2, 10);
    const X1 = 36, X2 = 549, CW = 495, FW = 1008;
    const tiles = [];
    const tile = (x, y, w, h, bg) => {
      const e = el('div', 'tile', S.root, { left: x + 'px', top: y + 'px', width: w + 'px', height: h + 'px', background: bg || 'var(--tile)' });
      const T = { e, x, y, w, h, cx: x + w / 2, cy: y + h / 2 };
      tiles.push(T);
      return T;
    };
    const label = (T, a, b, style) => el('div', 'lbl', T.e, style, `<b>${a}</b>${b ? `<span>${b}</span>` : ''}`);
    const scrim = T => el('div', 'fill', T.e, { background: 'linear-gradient(to bottom,rgba(0,0,0,0) 45%,rgba(0,0,0,.72) 100%)' });

    // T1 hero
    const T1 = tile(X1, 94, FW, 360, 'radial-gradient(ellipse 60% 90% at 78% 70%,rgba(255,160,120,.28),rgba(0,0,0,0) 70%),#121213');
    const heroCat = img('assets/p3_cut.webp', T1.e);
    heroCat.style.transform = 'translate(560px,-6px) scale(0.36)';
    el('div', 'abs', T1.e, { left: '56px', top: '84px', fontSize: '128px', fontWeight: 700, letterSpacing: '-0.02em', lineHeight: 1,
      background: 'var(--grad)', WebkitBackgroundClip: 'text', color: 'transparent', whiteSpace: 'nowrap' }, '喵 Pro');
    el('div', 'abs', T1.e, { left: '60px', top: '236px', fontSize: '42px', fontWeight: 700, color: '#f5f5f7', whiteSpace: 'nowrap' }, '萌得很。');
    // T2 chip
    const T2 = tile(X1, 472, CW, 440);
    const chipBox = el('div', 'abs', T2.e, { left: (CW - 500) / 2 + 'px', top: '-78px', width: '500px', height: '500px', transform: 'scale(.44)' });
    const miniChip = buildChip(chipBox);
    label(T2, 'M 系列芯片', '额头自带');
    // T3 eyes
    const T3 = tile(X2, 472, CW, 440);
    const eyeImg = img('assets/p3_face3x.jpg', T3.e);
    scrim(T3);
    label(T3, '超视网膜 XDR', '琥珀色双眸 · 夜间模式');
    // T4 nose id
    const T4 = tile(X1, 930, CW, 260);
    const noseImg = img('assets/m_nose.jpg', T4.e);
    el('div', 'fill', T4.e, { background: 'linear-gradient(90deg,#161617 30%,rgba(22,22,23,0) 70%)' });
    const nChk = el('div', 'abs', T4.e, { left: '34px', top: '34px', width: '76px', height: '76px', borderRadius: '50%', background: '#30d158' });
    el('div', 'fill', nChk, {}, ICON.check('#fff', 10));
    label(T4, 'Nose ID', '爱心鼻头');
    // T5 battery (J lands here)
    const T5t = tile(T5.x, T5.y, T5.w, T5.h, 'radial-gradient(ellipse 80% 90% at 80% 20%,rgba(94,92,230,.35),rgba(0,0,0,0) 70%),#131316');
    el('div', 'abs', T5t.e, { left: '34px', top: '26px', whiteSpace: 'nowrap', lineHeight: 1 },
      '<span style="font-size:130px;font-weight:700;letter-spacing:-0.03em;background:linear-gradient(180deg,#fff 30%,#b9b7ff);-webkit-background-clip:text;color:transparent">20</span><span style="font-size:44px;font-weight:700;margin-left:8px">小时</span>');
    const tb = el('div', 'abs', T5t.e, { left: 'auto', right: '40px', top: '44px', width: '64px', height: '64px', borderRadius: '50%', background: '#5e5ce6', display: 'flex', alignItems: 'center', justifyContent: 'center' });
    el('div', '', tb, { width: '34px', height: '34px' }, ICON.moon('#fff'));
    label(T5t, '睡眠续航', '超长续航，主要靠睡');
    // T6 toe beans / MagSafe
    const T6 = tile(X1, 1208, CW, 400);
    const beanImg = img('assets/m_beans.jpg', T6.e);
    scrim(T6);
    const t6ring = el('div', 'abs', T6.e, { left: CW / 2 - 90 + 'px', top: '80px', width: '180px', height: '180px', borderRadius: '50%', border: '6px solid #fff', boxShadow: '0 0 30px rgba(255,255,255,.6)' });
    label(T6, 'MagSafe 肉垫', '粉色 · Q 弹 · 自动吸附键盘');
    // T7 ears
    const T7 = tile(X2, 1208, CW, 400);
    const earImg = img('assets/m_ear.jpg', T7.e);
    scrim(T7);
    const t7s = sv('svg', { width: CW, height: 400, viewBox: `0 0 ${CW} 400` }, T7.e);
    Object.assign(t7s.style, { position: 'absolute', left: 0, top: 0 });
    const t7arcs = [0, 1, 2].map(() => sv('path', { fill: 'none', stroke: '#fff', 'stroke-width': 5, 'stroke-linecap': 'round' }, t7s));
    label(T7, '空间音频', '32 块耳部肌肉 · 胡须 LiDAR');
    // T8 colours
    const T8 = tile(X1, 1626, 640, 200);
    ['radial-gradient(circle at 35% 30%,#f1c67e,#c9954f 60%,#9d6f35)', 'radial-gradient(circle at 35% 30%,#ffd0d3,#f0a3ab 60%,#d98590)',
      'repeating-linear-gradient(118deg,#3a3129 0 6px,#8b7862 6px 15px)', 'radial-gradient(circle at 35% 30%,#ffffff,#f4eee6 60%,#e2d9cc)']
      .forEach((bg, i) => el('div', 'abs', T8.e, { left: 34 + i * 72 + 'px', top: '40px', width: '58px', height: '58px', borderRadius: '50%', background: bg, boxShadow: 'inset 0 0 0 1px rgba(255,255,255,.12)' }));
    el('div', 'abs', T8.e, { left: '350px', top: '34px', fontSize: '38px', fontWeight: 700, whiteSpace: 'nowrap' }, '四色一体');
    el('div', 'abs', T8.e, { left: '350px', top: '86px', fontSize: '26px', fontWeight: 500, color: '#86868b', whiteSpace: 'nowrap' }, '全球限量 1 只');
    el('div', 'abs', T8.e, { left: '34px', top: '128px', fontSize: '24px', fontWeight: 500, color: '#86868b', whiteSpace: 'nowrap', letterSpacing: '.02em' }, '琥珀金 · 肉垫粉 · 狸花棕 · 奶油白');
    // T9 tail
    const T9 = tile(694, 1626, 350, 200);
    const tailImg = img('assets/p3_full.jpg', T9.e);
    scrim(T9);
    label(T9, '白色尾尖', '像蘸了一口牛奶', { bottom: '22px' });

    const imgFit = (e, natW, natH, ax, ay, k, T) => place(e, k, ax, ay, T.w / 2, T.h / 2);
    const cT5 = [T5t.cx, T5t.cy];
    const maxd = Math.max(...tiles.map(T => Math.hypot(T.cx - cT5[0], T.cy - cT5[1])));

    S.update = t => {
      const idle = P(t, 36.2, 40.2);
      imgFit(eyeImg, 1470, 2520, 700, 1210, 0.62 + 0.04 * idle, T3);
      imgFit(noseImg, 1054, 992, 600, 560, 0.42 + 0.03 * idle, { w: T4.w * 1.45, h: T4.h });
      imgFit(beanImg, 1156, 782, 560, 380, 0.55 + 0.04 * idle, T6);
      imgFit(earImg, 1000, 1400, 480, 640, 0.5 + 0.04 * idle, T7);
      imgFit(tailImg, 1932, 2576, 780, 2270, 0.62 + 0.04 * idle, T9);
      heroCat.style.transform = `translate(${566 - 8 * idle}px,${-10 - 6 * idle}px) scale(${0.36 + 0.01 * idle})`;
      miniChip.set(t, t * 60, lerp(110, -10, frac((t - 36.4) / 2.2)));
      t6ring.style.transform = `scale(${1 + 0.05 * Math.sin(t * 4)})`;
      t7arcs.forEach((a, i) => {
        const ph = frac(-(t - 36) * 0.9 + i / 3), rr = 30 + 150 * ph;
        const cx = 250, cy = 250, a0 = -150 * Math.PI / 180, a1 = -100 * Math.PI / 180;
        a.setAttribute('d', `M ${cx + Math.cos(a0) * rr} ${cy + Math.sin(a0) * rr} A ${rr} ${rr} 0 0 1 ${cx + Math.cos(a1) * rr} ${cy + Math.sin(a1) * rr}`);
        a.setAttribute('opacity', Math.sin(Math.PI * ph) * 0.9);
      });
      tiles.forEach(T => {
        const d = Math.hypot(T.cx - cT5[0], T.cy - cT5[1]) / maxd;
        let p, q;
        if (T === T5t) { p = P(t, 36.22, 36.52, E.out2); q = P(t, 39.62, 39.92, E.in3); T.e.style.transform = `scale(${1 - 0.1 * q})`; }
        else {
          const t0 = 36.05 + d * 0.55;
          p = P(t, t0, t0 + 0.55, back(1.3));
          const t1 = 39.4 + (1 - d) * 0.28;
          q = P(t, t1, t1 + 0.3, E.in3);
          T.e.style.transform = `translateY(${(1 - clamp(p)) * 30}px) scale(${lerp(0.86, 1, p) * (1 - 0.1 * q)})`;
        }
        T.e.style.opacity = clamp(p * 1.6) * (1 - q);
      });
    };
  }

  // ======================================================================
  // L · 39.95–44.35  One more thing… it's still growing. 喵 Pro Max
  // ======================================================================
  {
    const S = scene('L', 40.0, 44.35, 11);
    S.root.style.background = '#000';
    const omt = text(S.root, 'One more thing.', '', 846, { fontSize: '78px', fontWeight: 600, letterSpacing: '-0.015em', fontFamily: 'Inter' });
    const omt2 = text(S.root, '还有一件事。', '', 956, { fontSize: '40px', fontWeight: 500, color: '#86868b', letterSpacing: '.1em', textIndent: '.1em' });
    const grow = el('div', 'fill', S.root);
    const glowG = el('div', 'fill', grow, { background: 'radial-gradient(ellipse 50% 30% at 50% 58%,rgba(255,170,120,.22),rgba(0,0,0,0) 70%)' });
    const cat = img('assets/p1_cut.webp', grow);
    const gh = text(grow, '它，还在长大。', 'h1', 470, { fontSize: '96px' });
    const ghc = split(gh);
    const barWrap = el('div', 'abs', grow, { left: '300px', top: '1330px', width: '480px' });
    const barLbl = el('div', '', barWrap, { display: 'flex', justifyContent: 'space-between', fontSize: '32px', fontWeight: 600, color: '#a1a1a6', marginBottom: '18px' });
    el('span', '', barLbl, {}, '成长进度');
    const pct = el('span', '', barLbl, { color: '#fff', fontVariantNumeric: 'tabular-nums' }, '12%');
    const track = el('div', '', barWrap, { height: '12px', borderRadius: '6px', background: '#2c2c2e', overflow: 'hidden' });
    const bar = el('div', '', track, { height: '100%', borderRadius: '6px', background: 'linear-gradient(90deg,#ffc98b,#ff9fb0)' });
    const max = el('div', 'fill', S.root);
    const scrim = el('div', 'fill', max, { background: 'linear-gradient(to bottom,rgba(0,0,0,.82) 0%,rgba(0,0,0,.5) 22%,rgba(0,0,0,0) 38%)' });
    const bigCat = img('assets/p1_cut.webp', max);
    bigCat.style.webkitMaskImage = 'linear-gradient(to bottom,#000 80%,transparent 97%)';
    max.appendChild(scrim);
    const title = text(max, '喵 Pro <span class="grad">Max</span>', '', 196, { fontSize: '176px', fontWeight: 700, letterSpacing: '-0.02em', lineHeight: '200px' });
    const sub = text(max, '长大后见。', 'h1', 420, { fontSize: '60px', color: '#f5f5f7' });
    const flash = el('div', 'fill', S.root, { background: '#fff' });
    const FACE = [1330, 900];

    S.update = t => {
      lineIn(omt, t, 40.35, { dur: 0.7, dy: 18, blur: 8, out: 41.36, outDur: 0.26 });
      lineIn(omt2, t, 40.55, { dur: 0.7, dy: 14, blur: 6, out: 41.36, outDur: 0.26 });
      const gOn = t >= 41.7 && t < 43.0;
      grow.style.display = gOn ? '' : 'none';
      if (gOn) {
        const gp = P(t, 41.95, 42.95, E.io3);
        const k = lerp(0.2, 0.34, gp);
        place(cat, k, FACE[0], FACE[1], 540, 1010);
        cat.style.opacity = P(t, 41.7, 42.0, E.out2);
        glowG.style.opacity = P(t, 41.7, 42.1);
        charsIn(ghc, t, 41.8, { st: 0.05 });
        const v = Math.round(lerp(12, 37, gp));
        pct.textContent = v + '%';
        bar.style.width = lerp(12, 37, gp) + '%';
        lineIn(barWrap, t, 41.95, { dy: 14 });
      }
      const mOn = t >= 43.0;
      max.style.display = mOn ? '' : 'none';
      if (mOn) {
        const mp = P(t, 43.0, 43.5, back(1.25));
        place(bigCat, lerp(1.95, 1.45, mp), FACE[0], FACE[1] - 60, 540, 1120);
        const tp = P(t, 43.0, 43.32, E.out4);
        title.style.transform = `scale(${lerp(1.3, 1, tp)})`;
        title.style.opacity = clamp(tp * 1.5);
        lineIn(sub, t, 43.3, { dy: 16 });
        const ex = P(t, 43.95, 44.3, E.in2);
        max.style.opacity = 1 - ex;
      }
      flash.style.opacity = t >= 43.0 ? 0.55 * (1 - P(t, 43.0, 43.3, E.out2)) : 0;
    };
  }

  // ======================================================================
  // M · 44.0–50.0  Finale: product shot, price, sign-off
  // ======================================================================
  {
    const S = scene('M', 44.0, 50.01, 12);
    S.root.style.background = '#000';
    const stageLight = el('div', 'fill', S.root, { background: 'radial-gradient(ellipse 46% 40% at 38% 60%,rgba(255,236,220,.13),rgba(0,0,0,0) 70%),radial-gradient(ellipse 36% 5% at 36% 92.5%,rgba(255,220,190,.16),rgba(0,0,0,0) 100%)' });
    const cat = img('assets/p3_cut.webp', S.root);
    const title = text(S.root, '喵 Pro', 'grad', 200, { fontSize: '200px', fontWeight: 700, letterSpacing: '-0.02em', lineHeight: '230px' });
    title.style.background = 'linear-gradient(100deg,rgba(255,255,255,0) 40%,rgba(255,255,255,.95) 50%,rgba(255,255,255,0) 60%),var(--grad)';
    title.style.backgroundSize = '260% 100%,100% 100%';
    title.style.webkitBackgroundClip = 'text';
    const tag = text(S.root, '萌得很。', 'h1', 440, { fontSize: '64px' });
    const price = el('div', 'abs', S.root, { left: '676px', top: '960px', whiteSpace: 'nowrap' });
    const pr0 = el('div', '', price, { fontSize: '32px', fontWeight: 600, color: '#86868b' }, '售价');
    const pr1 = el('div', '', price, { fontSize: '96px', fontWeight: 700, color: '#f5f5f7', lineHeight: 1.1, marginTop: '4px' }, '非卖品');
    const pr2 = el('div', 'grad', price, { fontSize: '46px', fontWeight: 700, marginTop: '4px' }, '仅供宠爱。');
    const links = el('div', '', price, { fontSize: '32px', fontWeight: 500, color: '#2997ff', marginTop: '40px', lineHeight: 1.7 }, '进一步了解 ›<br>撸一下 ›');
    const logo = el('div', 'abs', S.root, { left: '445px', top: '720px', width: '190px', height: '190px' }, ICON.cat('url(#lg)'));
    logo.querySelector('svg').insertAdjacentHTML('afterbegin', '<defs><linearGradient id="lg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ffffff"/><stop offset="1" stop-color="#d2d2d7"/></linearGradient></defs>');
    const sign = text(S.root, 'Designed by Nature.', '', 962, { fontSize: '44px', fontWeight: 500, color: '#98989d', letterSpacing: '.005em' });
    const sign2 = text(S.root, '由大自然设计 · 在家里被宠爱', '', 1030, { fontSize: '31px', fontWeight: 500, color: '#6e6e73', letterSpacing: '.08em', textIndent: '.08em' });
    const foot = text(S.root, '* 所有参数均基于真实猫咪习性，外加一点点夸张。', '', 1760, { fontSize: '24px', fontWeight: 500, color: '#48484a' });
    const fade = el('div', 'fill', S.root, { background: '#000' });

    S.update = t => {
      const cp = P(t, 44.0, 44.9, E.out4);
      const k = lerp(0.35, 0.37, P(t, 44.0, 48.2)) ;
      place(cat, k, 700, 1820, 400, 1165 + (1 - cp) * 70);
      const off = P(t, 47.75, 48.1, E.in2);
      cat.style.opacity = cp * (1 - off);
      cat.style.filter = cp < .999 ? `blur(${(1 - cp) * 10}px)` : 'none';
      stageLight.style.opacity = P(t, 44.0, 44.8) * (1 - off);
      const tp = P(t, 44.45, 45.4, E.out4);
      title.style.opacity = P(t, 44.45, 44.95) * (1 - off);
      title.style.transform = `translateY(${(1 - tp) * 60}px) scale(${lerp(1.05, 1, tp)})`;
      title.style.filter = tp < .999 ? `blur(${(1 - tp) * 14}px)` : 'none';
      title.style.backgroundPosition = `${lerp(115, -15, P(t, 45.3, 46.4, E.io3))}% 0,0 0`;
      lineIn(tag, t, 45.0, { dy: 18, out: 47.75, outDur: 0.3 });
      lineIn(pr0, t, 45.65, { dy: 16, out: 47.75, outDur: 0.3 });
      lineIn(pr1, t, 45.75, { dy: 22, out: 47.75, outDur: 0.3 });
      lineIn(pr2, t, 45.95, { dy: 18, out: 47.75, outDur: 0.3 });
      lineIn(links, t, 46.4, { dy: 14, out: 47.75, outDur: 0.3 });
      // sign-off
      const lp = P(t, 48.05, 48.7, E.out4);
      logo.style.opacity = lp;
      logo.style.transform = `scale(${lerp(0.9, 1, lp)})`;
      logo.style.filter = lp < .999 ? `blur(${(1 - lp) * 8}px)` : 'none';
      lineIn(sign, t, 48.35, { dy: 12 });
      lineIn(sign2, t, 48.55, { dy: 10 });
      lineIn(foot, t, 48.7, { dy: 0, blur: 0 });
      fade.style.opacity = P(t, 49.62, 50.0, E.in2);
    };
  }

  // ------------------------------------------------------------ runtime
  let dbg = null;
  if (params.has('debug')) dbg = el('div', '', stage, {}, '');
  if (dbg) dbg.id = 'debug';
  function seek(t) {
    for (const s of scenes) {
      const on = t >= s.t0 && t < s.t1;
      if (on !== s.on) { s.root.style.display = on ? 'block' : 'none'; s.on = on; }
      if (on) s.update(t);
    }
    if (dbg) dbg.textContent = t.toFixed(2) + 's';
  }
  window.seek = seek;
  window.DURATION = DURATION;
  window.__ready = (async () => {
    await Promise.all([
      document.fonts.load('700 100px NotoSC', '喵萌得很'),
      document.fonts.load('700 100px Inter', 'Pro Max'),
    ]);
    await document.fonts.ready;
    layoutGradSplits();
    await Promise.all(imgs.map(i => (i.complete ? i.decode() : new Promise(r => { i.onload = r; i.onerror = r; }).then(() => i.decode())).catch(() => {})));
    seek(Number(params.get('t') || 0));
    return true;
  })();

  // live preview: ?play plays in real time (use for eyeballing only)
  if (params.has('play')) {
    window.__ready.then(() => {
      const t0 = performance.now() - Number(params.get('t') || 0) * 1000;
      const loop = () => { const t = ((performance.now() - t0) / 1000) % DURATION; seek(t); requestAnimationFrame(loop); };
      loop();
    });
  }
})();
