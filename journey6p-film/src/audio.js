// Procedural score & sound design, synthesised with WebAudio and scheduled
// against the film clock. The same builder renders offline for video export.

const NOTE = (m) => 440 * Math.pow(2, (m - 69) / 12);
const D = { D1: 26, D2: 38, A2: 45, D3: 50, F3: 53, Fs3: 54, A3: 57, C4: 60, D4: 62, E4: 64, Fs4: 66, A4: 69, D5: 74, E5: 76, A5: 81, D6: 86 };

function makeIR(ctx, seconds = 3.2, decay = 2.6) {
  const len = Math.floor(ctx.sampleRate * seconds);
  const buf = ctx.createBuffer(2, len, ctx.sampleRate);
  for (let c = 0; c < 2; c++) {
    const d = buf.getChannelData(c);
    let lp = 0;
    for (let i = 0; i < len; i++) {
      const n = Math.random() * 2 - 1;
      lp = lp * 0.6 + n * 0.4;
      d[i] = lp * Math.pow(1 - i / len, decay);
    }
  }
  return buf;
}
function noiseBuffer(ctx, seconds = 2) {
  const len = Math.floor(ctx.sampleRate * seconds);
  const buf = ctx.createBuffer(1, len, ctx.sampleRate);
  const d = buf.getChannelData(0);
  for (let i = 0; i < len; i++) d[i] = Math.random() * 2 - 1;
  return buf;
}

// Schedule the whole score for film times >= from. `at(ft)` maps film time -> ctx time.
function buildScore(ctx, out, cues, from) {
  const at = (ft) => ctx.__base + (ft - from);
  const end = cues.duration;
  const nodes = [];
  const keep = (n) => { nodes.push(n); return n; };
  const noise = noiseBuffer(ctx, 3);

  // Buses.
  const master = keep(ctx.createGain());
  master.gain.value = 0.9;
  const comp = keep(ctx.createDynamicsCompressor());
  comp.threshold.value = -18; comp.ratio.value = 4; comp.attack.value = 0.004; comp.release.value = 0.3;
  const lim = keep(ctx.createDynamicsCompressor());
  lim.threshold.value = -3; lim.ratio.value = 20; lim.attack.value = 0.001; lim.release.value = 0.1; lim.knee.value = 0;
  master.connect(comp); comp.connect(lim); lim.connect(out);
  const verb = keep(ctx.createConvolver());
  verb.buffer = makeIR(ctx, 4.5, 2.4);
  const verbIn = keep(ctx.createGain()); verbIn.gain.value = 1;
  const verbOut = keep(ctx.createGain()); verbOut.gain.value = 0.55;
  verbIn.connect(verb); verb.connect(verbOut); verbOut.connect(master);
  const send = (node, dry = 1, wet = 0.4) => {
    const g1 = keep(ctx.createGain()); g1.gain.value = dry; node.connect(g1); g1.connect(master);
    const g2 = keep(ctx.createGain()); g2.gain.value = wet; node.connect(g2); g2.connect(verbIn);
  };
  // Automation helper: sets a param along [[ft, v], ...] from `from` onward.
  const automate = (param, pts) => {
    const val = (ft) => {
      if (ft <= pts[0][0]) return pts[0][1];
      for (let i = 1; i < pts.length; i++) if (ft <= pts[i][0]) {
        const [t0, v0] = pts[i - 1], [t1, v1] = pts[i];
        return v0 + (v1 - v0) * ((ft - t0) / (t1 - t0));
      }
      return pts[pts.length - 1][1];
    };
    param.setValueAtTime(val(from), at(from));
    for (const [ft, v] of pts) if (ft > from) param.linearRampToValueAtTime(v, at(ft));
  };
  const alive = (t0, t1) => t1 > from && t0 < end;

  // ---------------------------------------------------------------- drone bed
  const drone = (freqs, type, cutPts, gainPts, detune = 6, wet = 0.5) => {
    const g = keep(ctx.createGain()); g.gain.value = 0;
    const f = keep(ctx.createBiquadFilter()); f.type = 'lowpass'; f.Q.value = 0.7;
    automate(f.frequency, cutPts);
    automate(g.gain, gainPts);
    f.connect(g); send(g, 1, wet);
    for (const fr of freqs) for (const dt of [-detune, detune]) {
      const o = keep(ctx.createOscillator()); o.type = type; o.frequency.value = fr; o.detune.value = dt;
      o.connect(f); o.start(at(from)); o.stop(at(end + 1));
    }
  };
  // Low foundation (D), present through most of the film, gone at the atom.
  drone([NOTE(D.D1), NOTE(D.D2)], 'sawtooth',
    [[0, 90], [4.6, 140], [14.9, 380], [18, 220], [44, 260], [48.2, 90], [51.8, 60], [58.8, 700], [62, 400], [68.5, 200]],
    [[0, 0], [0.4, 0.11], [9.4, 0.12], [14.8, 0.1], [15, 0.16], [44, 0.14], [48.2, 0.02], [51.8, 0.0], [53, 0.06], [58.6, 0.16], [58.8, 0.2], [66, 0.14], [68.5, 0]], 7, 0.35);
  // Fifth + ninth colour that opens up at the hero reveal and the ending.
  drone([NOTE(D.A2), NOTE(D.E4), NOTE(D.Fs3)], 'triangle',
    [[0, 300], [14.9, 300], [15.4, 1800], [18.5, 900], [44, 1200], [48, 400], [58.8, 400], [59.2, 2600], [68.5, 900]],
    [[0, 0], [14.8, 0], [15.1, 0.07], [18.5, 0.05], [30, 0.04], [44, 0.05], [48.2, 0.0], [58.7, 0.0], [59.0, 0.09], [66, 0.08], [68.5, 0]], 9, 0.7);
  // Inside-the-chip tension: minor colour, rising filter as we descend.
  drone([NOTE(D.D3), NOTE(D.F3), NOTE(D.A3), NOTE(D.C4)], 'sawtooth',
    [[18, 200], [24, 500], [30, 900], [36, 1500], [43, 2200], [48, 300]],
    [[18, 0], [19.5, 0.025], [29, 0.035], [40, 0.045], [44, 0.03], [48, 0]], 11, 0.6);

  // ---------------------------------------------------------------- pulse
  // Computation rhythm: soft plucked 16ths from the die down to the transistor.
  const bpm = 118, step = 60 / bpm / 4;
  const scale = [D.D4, D.F3 + 12, D.A4, D.C4 + 12, D.D5, D.A4, D.E5, D.A4];
  const pluck = (ft, midi, vel, len = 0.18, type = 'triangle') => {
    if (ft < from - 0.01 || ft > end) return;
    const o = keep(ctx.createOscillator()); o.type = type; o.frequency.value = NOTE(midi);
    const f = keep(ctx.createBiquadFilter()); f.type = 'lowpass'; f.frequency.value = 2400; f.Q.value = 2;
    const g = keep(ctx.createGain()); g.gain.value = 0;
    o.connect(f); f.connect(g); send(g, 0.8, 0.5);
    const t = at(ft);
    g.gain.setValueAtTime(0, t);
    g.gain.linearRampToValueAtTime(vel, t + 0.005);
    g.gain.exponentialRampToValueAtTime(0.0001, t + len);
    f.frequency.setValueAtTime(3200, t); f.frequency.exponentialRampToValueAtTime(500, t + len);
    o.start(t); o.stop(t + len + 0.05);
  };
  for (let ft = 24.2, i = 0; ft < 43.8; ft += step, i++) {
    const depth = (ft - 24) / 20;
    const accent = i % 4 === 0 ? 1 : 0.55;
    const skip = (i % 8 === 5 && depth < 0.4) || (i % 16 === 11);
    if (skip) continue;
    const note = scale[(i * 3 + Math.floor(i / 16)) % scale.length] + (depth > 0.55 ? 12 : 0);
    pluck(ft, note, 0.028 * accent * (0.6 + depth * 0.7));
  }
  // Data ticks while sensor streams flow (sparse, high).
  for (let ft = 4.9, i = 0; ft < 14; ft += 0.07 + ((i * 37) % 11) * 0.012, i++) {
    pluck(ft, 93 + ((i * 7) % 5), 0.006, 0.04, 'sine');
  }

  // ---------------------------------------------------------------- one-shots
  const hit = (ft, amp = 1, len = 2.8) => {
    if (!alive(ft, ft + len)) return;
    if (ft < from) return;
    const t = at(ft);
    const o = keep(ctx.createOscillator()); o.type = 'sine';
    o.frequency.setValueAtTime(62, t); o.frequency.exponentialRampToValueAtTime(29, t + 1.2);
    const g = keep(ctx.createGain()); g.gain.setValueAtTime(0, t);
    g.gain.linearRampToValueAtTime(0.55 * amp, t + 0.01); g.gain.exponentialRampToValueAtTime(0.0001, t + len);
    o.connect(g); send(g, 1, 0.15); o.start(t); o.stop(t + len + 0.1);
    const n = keep(ctx.createBufferSource()); n.buffer = noise;
    const f = keep(ctx.createBiquadFilter()); f.type = 'lowpass'; f.frequency.setValueAtTime(3500, t); f.frequency.exponentialRampToValueAtTime(120, t + 0.8);
    const ng = keep(ctx.createGain()); ng.gain.setValueAtTime(0.0, t); ng.gain.linearRampToValueAtTime(0.22 * amp, t + 0.005); ng.gain.exponentialRampToValueAtTime(0.0001, t + 1.2);
    n.connect(f); f.connect(ng); send(ng, 1, 0.6); n.start(t); n.stop(t + 1.3);
  };
  const whoosh = (ft0, ft1, amp = 1, f0 = 300, f1 = 4000) => {
    if (!alive(ft0, ft1) || ft0 < from - 0.01) return;
    const t0 = at(ft0), t1 = at(ft1);
    const n = keep(ctx.createBufferSource()); n.buffer = noise; n.loop = true;
    const f = keep(ctx.createBiquadFilter()); f.type = 'bandpass'; f.Q.value = 1.4;
    f.frequency.setValueAtTime(f0, t0); f.frequency.exponentialRampToValueAtTime(f1, t1);
    const g = keep(ctx.createGain()); g.gain.setValueAtTime(0, t0);
    g.gain.linearRampToValueAtTime(0.16 * amp, t0 + (t1 - t0) * 0.7); g.gain.linearRampToValueAtTime(0, t1);
    n.connect(f); f.connect(g); send(g, 1, 0.5); n.start(t0); n.stop(t1 + 0.05);
  };
  const tick = (ft, freq = 2400, amp = 0.08) => {
    if (ft < from) return;
    const t = at(ft);
    const o = keep(ctx.createOscillator()); o.type = 'sine'; o.frequency.value = freq;
    const g = keep(ctx.createGain()); g.gain.setValueAtTime(0, t); g.gain.linearRampToValueAtTime(amp, t + 0.002); g.gain.exponentialRampToValueAtTime(0.0001, t + 0.25);
    o.connect(g); send(g, 0.8, 0.8); o.start(t); o.stop(t + 0.3);
  };

  // Hook: lidar pulses (sonar-like), then the world lights up.
  cues.tick.forEach((ft, i) => tick(ft, 1800 + i * 300, 0.05));
  for (let i = 0; i < 12; i++) tick(0.4 + i * 0.13, 3200 + (i % 3) * 400, 0.012);
  whoosh(1.8, 3.2, 0.6, 120, 900);
  cues.whoosh.forEach(([a, b], i) => whoosh(a, b, i === 1 ? 1.2 : 0.9, 180, 5200));
  hit(2.1, 0.45);
  hit(10.38, 0.6, 1.6);
  hit(14.95, 1.0, 4.5); // hero reveal
  hit(23.95, 0.5, 2.0);
  hit(29.7, 0.45, 2.0);
  // Mechanical clunks in the exploded view.
  [18.75, 19.6, 21.05].forEach((ft) => { tick(ft, 180, 0.12); tick(ft + 0.01, 90, 0.1); });
  // Transistor: blocked hum, then the switch.
  tick(cues.switchOn, 1200, 0.1); tick(cues.switchOn + 0.02, 2400, 0.06);
  whoosh(cues.switchOn, cues.switchOn + 1.4, 0.5, 600, 2400);
  // Atom: near silence and a glassy shimmer.
  const shimmer = (f, amp) => {
    const [q0, q1] = cues.quiet;
    if (!alive(q0, q1 + 1.5)) return;
    const o = keep(ctx.createOscillator()); o.type = 'sine'; o.frequency.value = f;
    const lfo = keep(ctx.createOscillator()); lfo.frequency.value = 0.35;
    const lg = keep(ctx.createGain()); lg.gain.value = 3;
    lfo.connect(lg); lg.connect(o.frequency);
    const g = keep(ctx.createGain()); g.gain.value = 0;
    automate(g.gain, [[0, 0], [q0, 0], [q0 + 1.0, amp], [q1, amp], [q1 + 0.6, 0]]);
    o.connect(g); send(g, 0.5, 1.2);
    o.start(at(from)); o.stop(at(q1 + 2)); lfo.start(at(from)); lfo.stop(at(q1 + 2));
  };
  shimmer(NOTE(D.D6), 0.022); shimmer(NOTE(D.A5) * 1.003, 0.014); shimmer(NOTE(D.E5 + 12), 0.008);

  // Hyper zoom-out: rising noise + Shepard-like ascending tones + band ticks.
  const [z0, z1] = cues.zoomOut;
  if (alive(z0, z1)) {
    const n = keep(ctx.createBufferSource()); n.buffer = noise; n.loop = true;
    const f = keep(ctx.createBiquadFilter()); f.type = 'bandpass'; f.Q.value = 0.9;
    automate(f.frequency, [[z0, 200], [z0 + 2, 600], [z1 - 0.8, 6000], [z1, 3000]]);
    const g = keep(ctx.createGain()); g.gain.value = 0;
    automate(g.gain, [[0, 0], [z0, 0], [z0 + 1.5, 0.05], [z1 - 0.4, 0.28], [z1, 0.0]]);
    n.connect(f); f.connect(g); send(g, 1, 0.4);
    n.start(at(Math.max(from, z0))); n.stop(at(z1 + 0.2));
    for (let k = 0; k < 6; k++) {
      const o = keep(ctx.createOscillator()); o.type = 'sawtooth';
      const base = NOTE(D.D2) * Math.pow(2, k);
      automate(o.frequency, [[z0, base], [z1, base * 4]]);
      const lp = keep(ctx.createBiquadFilter()); lp.type = 'lowpass'; lp.frequency.value = 1800;
      const og = keep(ctx.createGain()); og.gain.value = 0;
      const peak = 0.018 * Math.sin(((k + 0.5) / 6) * Math.PI);
      automate(og.gain, [[0, 0], [z0, 0], [z0 + 1.2, peak * 0.5], [z1 - 0.3, peak], [z1, 0]]);
      o.connect(lp); lp.connect(og); send(og, 1, 0.5);
      o.start(at(Math.max(from, z0))); o.stop(at(z1 + 0.1));
    }
    cues.bands.forEach((ft) => { tick(ft, 900, 0.09); tick(ft + 0.015, 3600, 0.05); });
  }
  hit(z1, 0.95, 5.5); // landing on the road
  whoosh(cues.laneChange[0], cues.laneChange[1], 0.5, 300, 1400);
  return { nodes, master };
}

export class Score {
  constructor(cues) {
    this.cues = cues;
    this.ctx = null;
    this.muted = false;
    this.bus = null;
    this.startFilm = 0;
    this.startCtx = 0;
    this.running = false;
  }
  start(filmT) {
    if (!this.ctx) {
      const AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return;
      this.ctx = new AC({ latencyHint: 'playback' });
      this.out = this.ctx.createGain();
      this.out.gain.value = this.muted ? 0 : 1;
      this.out.connect(this.ctx.destination);
    }
    this.ctx.resume();
    this.seek(filmT, true);
  }
  seek(filmT, playing) {
    if (!this.ctx) return;
    if (this.bus) { try { this.bus.master.disconnect(); } catch (e) { /* noop */ } this.bus = null; }
    const ctx = this.ctx;
    ctx.__base = ctx.currentTime + 0.06;
    this.startCtx = ctx.__base;
    this.startFilm = filmT;
    this.bus = buildScore(ctx, this.out, this.cues, filmT);
    this.running = !!playing;
    if (playing) ctx.resume(); else ctx.suspend();
  }
  pause() { if (this.ctx) { this.ctx.suspend(); this.running = false; } }
  time() {
    if (!this.ctx || !this.running || this.ctx.state !== 'running') return null;
    return this.startFilm + Math.max(0, this.ctx.currentTime - this.startCtx);
  }
  toggleMute() {
    this.muted = !this.muted;
    if (this.out) this.out.gain.setTargetAtTime(this.muted ? 0 : 1, this.ctx.currentTime, 0.05);
  }
  // Offline render -> WAV (base64) for the video exporter.
  async renderOffline(sampleRate = 48000) {
    const len = Math.ceil(this.cues.duration * sampleRate);
    const ctx = new OfflineAudioContext(2, len, sampleRate);
    ctx.__base = 0;
    buildScore(ctx, ctx.destination, this.cues, 0);
    const buf = await ctx.startRendering();
    const L = buf.getChannelData(0), R = buf.getChannelData(1);
    const out = new DataView(new ArrayBuffer(44 + len * 4));
    const w = (o, s) => { for (let i = 0; i < s.length; i++) out.setUint8(o + i, s.charCodeAt(i)); };
    w(0, 'RIFF'); out.setUint32(4, 36 + len * 4, true); w(8, 'WAVE'); w(12, 'fmt ');
    out.setUint32(16, 16, true); out.setUint16(20, 1, true); out.setUint16(22, 2, true);
    out.setUint32(24, sampleRate, true); out.setUint32(28, sampleRate * 4, true); out.setUint16(32, 4, true); out.setUint16(34, 16, true);
    w(36, 'data'); out.setUint32(40, len * 4, true);
    for (let i = 0; i < len; i++) {
      out.setInt16(44 + i * 4, Math.max(-1, Math.min(1, L[i])) * 32767, true);
      out.setInt16(46 + i * 4, Math.max(-1, Math.min(1, R[i])) * 32767, true);
    }
    const bytes = new Uint8Array(out.buffer);
    let s = '';
    for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    return btoa(s);
  }
}
