import * as THREE from 'three';
import { clamp, smooth, formatLength } from './lib/util.js';

// Typography layer: short captions, a few diegetic labels with leader lines,
// and a tiny scale readout. Everything is driven by the master clock.

export class Overlay {
  constructor(stage, lang = 'both') {
    this.stage = stage;
    this.lang = lang;
    this.root = document.createElement('div');
    this.root.className = 'ov';
    stage.appendChild(this.root);
    this.svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    this.svg.setAttribute('class', 'ov-svg');
    this.root.appendChild(this.svg);
    this.cues = [];
    this.labels = [];
    this.scale = document.createElement('div');
    this.scale.className = 'ov-scale';
    this.scale.innerHTML = '<div class="bar"><i></i><b></b><i></i></div><span></span>';
    this.root.appendChild(this.scale);
    this.scaleText = this.scale.querySelector('span');
    this._v = new THREE.Vector3();
  }

  addCue(c) {
    const el = document.createElement('div');
    el.className = `cue cue-${c.style || 'sub'} pos-${c.pos || 'low'}`;
    const lines = [];
    if (c.en && this.lang !== 'zh') lines.push(`<div class="en">${c.en}</div>`);
    if (c.zh && this.lang !== 'en') lines.push(`<div class="zh">${c.zh}</div>`);
    if (c.extra) lines.push(...c.extra.map((x) => `<div class="${x.cls}">${x.text}</div>`));
    el.innerHTML = `<div class="inner">${lines.join('')}</div>`;
    this.root.appendChild(el);
    this.cues.push({ fi: 0.45, fo: 0.4, ...c, el, inner: el.firstChild });
  }

  addLabel(l) {
    const el = document.createElement('div');
    el.className = 'lbl';
    const zh = l.zh && this.lang !== 'en' ? `<em>${l.zh}</em>` : '';
    el.innerHTML = `<span>${this.lang === 'zh' && l.zh ? l.zh : l.text}</span>${this.lang === 'both' ? zh : ''}`;
    this.root.appendChild(el);
    const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    const dot = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    dot.setAttribute('r', '2.2');
    this.svg.appendChild(line);
    this.svg.appendChild(dot);
    this.labels.push({ fi: 0.35, fo: 0.3, dx: 60, dy: -40, ...l, el, line, dot });
  }

  // views: { frameName -> {camera, frame} } for projecting label anchors.
  update(t, ctx) {
    const W = this.stage.clientWidth, H = this.stage.clientHeight;
    this.svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
    for (const c of this.cues) {
      let a = 0;
      if (t > c.t0 && t < c.t1) a = Math.min(smooth((t - c.t0) / c.fi), smooth((c.t1 - t) / c.fo));
      if (a <= 0.001) { c.el.style.opacity = 0; c.el.style.visibility = 'hidden'; continue; }
      c.el.style.visibility = 'visible';
      c.el.style.opacity = a.toFixed(3);
      const k = clamp((t - c.t0) / (c.fi * 1.6));
      const rise = (1 - smooth(k)) * 0.6;
      const track = (1 - smooth(k)) * 0.12;
      c.inner.style.transform = `translateY(${rise}em)`;
      c.inner.style.letterSpacing = `${track}em`;
      if (c.style !== 'fine') c.inner.style.filter = a < 0.98 ? `blur(${((1 - a) * 6).toFixed(2)}px)` : 'none';
    }
    for (const l of this.labels) {
      let a = 0;
      if (t > l.t0 && t < l.t1) a = Math.min(smooth((t - l.t0) / l.fi), smooth((l.t1 - t) / l.fo));
      const view = ctx.views[l.world];
      let ok = a > 0.001 && view;
      let x = 0, y = 0;
      if (ok) {
        const v = this._v.set(...(typeof l.at === 'function' ? l.at(t) : l.at));
        view.toWorld(v, l.frame || view.frame);
        v.project(view.camera);
        if (v.z > 1 || v.z < -1) ok = false;
        x = (v.x * 0.5 + 0.5) * W; y = (-v.y * 0.5 + 0.5) * H;
      }
      if (!ok) {
        l.el.style.opacity = 0; l.line.setAttribute('opacity', 0); l.dot.setAttribute('opacity', 0);
        continue;
      }
      const s = W / 1600;
      const lx = x + l.dx * s, ly = y + l.dy * s;
      const grow = smooth(clamp((t - l.t0) / 0.35));
      l.line.setAttribute('x1', x); l.line.setAttribute('y1', y);
      l.line.setAttribute('x2', x + (lx - x) * grow); l.line.setAttribute('y2', y + (ly - y) * grow);
      l.line.setAttribute('opacity', a * 0.8);
      l.dot.setAttribute('cx', x); l.dot.setAttribute('cy', y); l.dot.setAttribute('opacity', a);
      l.el.style.opacity = (a * smooth(clamp((t - l.t0 - 0.15) / 0.3))).toFixed(3);
      const right = l.dx >= 0;
      l.el.style.transform = `translate(${right ? lx + 6 * s : lx - 6 * s}px, ${ly}px) translate(${right ? '0' : '-100%'}, -50%)`;
      l.el.style.textAlign = right ? 'left' : 'right';
    }
    // Scale readout.
    const sa = ctx.scaleAlpha;
    this.scale.style.opacity = sa.toFixed(3);
    if (sa > 0.001 && ctx.scaleMetres) {
      const barFrac = 0.075; // bar is 7.5% of frame width
      this.scaleText.textContent = formatLength(ctx.scaleMetres * barFrac);
    }
  }
}
