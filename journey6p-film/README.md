# JOURNEY 6P — From Meters to Atoms

A 68-second, 16:9, single-take procedural 3D film made in Three.js.

One question drives the whole film: **how small is a car's intelligence?** The
camera starts on a car deciding its way down a wet night expressway. It dives
into the car, the driving computer and the Horizon Robotics Journey 6P (征程 6P),
then keeps going. It passes through the package, the silicon die, the copper
interconnect, a transistor and the silicon crystal, and ends on **one silicon
atom**. Then it rushes back out, in one continuous hyper zoom, to the car on the
road just as it makes its decision.

Everything is generated in code: the models, the textures, the lighting, the
post-processing and the score. The project has no image, model or audio assets.

---

## Watch it

| Way | How |
| --- | --- |
| **Double-click** | Open `dist/journey6p.html` in Chrome, Edge, Safari or Firefox. It is a single self-contained file that runs offline from `file://`. |
| **Dev server** | `npm start`, then open <http://localhost:5173/>. This serves the unbundled sources in `src/`. |
| **Render a video** | `npm run capture -- --fps 30 --w 1920 --h 1080`. This needs `ffmpeg` with libx264 (see below). |

Press **Play** (sound on; headphones recommended).

**Keys:** `Space` play/pause · `←/→` seek 3 s (`Shift` = 0.5 s) · `F` fullscreen · `M` mute · `D` debug overlay · `Home` restart.

**URL options:** `?t=24` start at 24 s · `&lang=en` / `&lang=zh` / `&lang=both`
(bilingual captions are the default) · `&q=low|med|high` pins the quality. By
default the quality adapts to hold roughly 60 fps.

---

## Director's notes

### The story arc

1. **Hook (0–5 s).** The screen is black. A LiDAR pulse ripples out and the road
   appears as the car sees it: as points. Detection boxes lock onto a car and a
   pedestrian. Then the real night world lights up around the same car.
   Caption: *How small is a car's intelligence?*
2. **Into the car (5–10 s).** Sensor data streams leave the LiDAR crown,
   cameras and radars. The car's body separates into an exploded view as we
   follow the streams inside, where every stream plugs into one box: the
   driving computer.
3. **The platform (10–15 s).** We dive between its heat-sink fins, and the fins
   fill the frame as an occlusion wipe. We come out at board level behind a
   connector. The PCB's high-speed differential pairs are a night highway;
   data packets race like tail lights toward one chip, echoing the road.
4. **Hero reveal (15–18.5 s).** We rise over the package edge. Light sweeps
   across the lid and its laser marking. Title: **JOURNEY 6P / 征程 6P**.
5. **Exploded package (18.5–24 s).** *Smaller.* The lid lifts, and the die, the
   C4 bumps and the substrate separate. The die flips over to show its active
   face, and we dive into it.
6. **Die (24–29.5 s).** *Much smaller.* We fly low over an illustrative
   floorplan: CPU cores, caches, memory PHYs, and two big parallel compute arrays
   where a systolic wavefront of activity sweeps across thousands of
   processing elements.
7. **Interconnect (29.5–34.5 s).** The die's top-metal stripes become real 3D
   copper. We sink through eight metal layers that get thinner and denser, like
   city overpasses, with current pulses running along them.
8. **Switches (34.5–40.5 s).** The metal dissolves in a cutaway. *Billions of
   switches*: a field of FinFET gates flickering on and off. We find one
   transistor. With its gate **OFF**, electrons pile up at the source. The gate
   turns **ON**, the channel lights, and they flow.
9. **Be the electron (40.5–44 s).** *Now, you are an electron.* We drop into the
   fin and ride the current under the gate, through the channel tunnel.
10. **The crystal (44–49 s).** The fin's walls resolve into atoms. We glide
    along a real ⟨110⟩ channel of diamond-cubic silicon, which is the direction
    electrons travel in a FinFET on a (001) wafer. Then we rise up an open
    [001] shaft and come out above the crystal surface. *From meters to
    nanometers.* The route is collision-free, checked numerically against every
    atom and bond.
11. **One atom (49–51.8 s).** The music drops to near silence. One surface atom
    dissolves into its electron cloud: four sp³ lobes pointing toward its bond
    partners, and a nucleus. *One silicon atom.*
12. **Hyper zoom-out (51.8–58.8 s).** One continuous pull-back through ten
    orders of magnitude: lattice, transistor, copper stack, die, package, board,
    computer, car, road. The package, the enclosure and the car body close up
    again beneath the camera as it passes each scale.
13. **The decision (58.8–68.5 s).** We land on the car as a planned-trajectory
    ribbon appears and it changes lanes around slower traffic. *From silicon to
    intelligence.*

### Transitions (each one grows out of the previous shot)

| Hand-off | Technique |
| --- | --- |
| Point cloud → real world | Match: the points lie on the surfaces that light up. |
| Car → cabin | Exploded view, following a data stream. |
| Cabin → computer → PCB | Scale match (the same enclosure model in both worlds), then a fin **occlusion wipe**. |
| Road lanes → PCB traces | Visual rhyme: "highway at every scale". |
| Package → die | Exploded view + flip, then a **macro zoom**. The die face in the board world is a render of the die world, so the two match. |
| Die → copper stack | **Morph**: the die's top-metal stripes are aligned exactly with the 3D M8/M7 wires. |
| Logic → transistor | Cutaway, then a push-in. |
| Transistor → lattice | POV fly-through; the fin surface shows atom rows before the lattice takes over. |
| Atom → road | One procedural camera through all five worlds. |

---

## How it works

### Nested scale worlds, one camera

You can't put a 5 m car and a 0.2 nm atom in one floating-point scene. The film
uses five **worlds**, each authored in comfortable units:

```
road  (m)  ── car (m) ── board (mm) ── die (µm) ── nano (nm) ── lattice (Å)
```

Each child world is **anchored** inside its parent by a uniformly scaled matrix
(`src/frames.js`): the board inside the car's centre console, the die on the
flipped silicon, the nano stack under one processing element, and the lattice
on the top surface of one fin. A camera pose authored in any frame can be
carried exactly into any other frame. During a hand-off both worlds render from
the *same* pose and crossfade, so scale changes are continuous rather than cuts.

Because the anchors are exact, the ten-decade **zoom-out** is a single camera
function. It pulls straight up from the atom along the camera's log-distance
curve, and the director switches worlds by distance band. Each world contains a
stand-in for its child world:

- The board's die face is a render of the die world.
- The die's processing elements carry the nano world's top-metal pattern.
- The fin shows atom rows up close.

### Master timeline

`src/director.js` is the single source of truth. Everything is a pure function
of time `t`, so any frame can be rendered in any order. This makes scrubbing,
screenshots and frame-exact video export trivial. The file holds:

- the camera rails (C¹ Hermite splines in time; log-spaced keys for dives)
- the world schedule and crossfades
- the effect tracks (exposure, LiDAR, streams, zoom blur, depth of field, cutaway)
- the captions and diegetic labels

### Rendering

- **Worlds:** `src/worlds/*.js`.
  - A lofted EV body built from designed spline sections.
  - A wet road with planar reflections and analytic light pools.
  - A PCB with a woven-fibreglass normal detail and 3D trace ribbons that carry data packets.
  - An FCBGA package with an exploded view.
  - A procedural die floorplan shader.
  - Eight instanced copper layers with a camera-safe shaft.
  - Three-sided-gate FinFETs.
  - A diamond-cubic lattice drawn as depth-correct impostors (about 30k atoms).
  - An sp³ electron-density point cloud.
- **Post** (`src/post.js`): an HDR composite of one or two worlds with signed
  circle of confusion, then half-res scatter-as-gather bokeh depth of field, a
  dual-filter bloom, radial zoom blur, chromatic aberration, ACES tone mapping,
  vignette, grain and dither.
- **Sound** (`src/audio.js`): a WebAudio score synthesised live and scheduled
  against the film clock. It has drones, a reveal chord, a computation pulse,
  whooshes, impacts, silence at the atom and a Shepard-like riser for the
  zoom-out. The same code renders offline to WAV for export.
- **Performance:** instancing everywhere, static meshes merged per material,
  small details kept out of the mirror pass, and adaptive resolution. Peak load
  is about 400 draw calls, most shots use 20–150, and the heaviest world is
  about 1.2 M triangles.

### Accuracy notes

Real, or physically faithful:

- Sensor data flowing to a central intelligent-driving computer
- Journey 6P as an intelligent-driving SoC by Horizon Robotics
- The FCBGA stack (lid, TIM, flip-chip die, C4 bumps, substrate, BGA)
- Copper damascene interconnect getting finer toward the transistors
- FinFET gates wrapping three sides of each fin
- The ⟨110⟩ channel on a (001) wafer
- The diamond-cubic silicon lattice (a = 5.431 Å, bond length 2.35 Å)
- sp³ bonding

Illustrative: the enclosure and board layout, the lid marking design, the die
floorplan, the compute-array organisation, the layer dimensions and the
transistor layout. None of these are Journey 6P's real design; Horizon Robotics
has not published them. The end card says so.

---

## Project layout

```
index.html            player shell (loads src/ via an import map)
src/main.js           boot, render loop, controls, adaptive quality, capture API
src/director.js       master timeline: cameras, worlds, fx, captions, labels
src/frames.js         nested coordinate frames + pose conversion
src/camera.js         keyframed / procedural camera rails
src/post.js           post-processing pipeline
src/overlay.js        captions, leader-line labels, scale readout
src/audio.js          procedural score (live + offline)
src/worlds/           road · car · housing · board · die · nano · lattice
src/lib/              math, env maps, geometry helpers
vendor/three/         Three.js r186 (MIT)
dist/journey6p.html   single-file build (npm run build)
tools/                dev server, build, video capture, QA renderers
```

### Tools

```
npm start                    # static server on :5173
npm run build                # → dist/journey6p.html
npm run capture -- [opts]    # → out/journey6p.mp4 (+ out/score.wav)
node tools/shots.mjs 3 17 50 # stills at given times → shots/
tools/sheet.sh NAME 4 t1 t2… # contact sheet of stills
node tools/audiocheck.mjs    # offline score render + loudness profile
tools/check.sh               # syntax-check every module
node tools/views.mjs NAME "world|frame:px,py,pz:lx,ly,lz:fov|t"  # free debug camera
```

`capture` options: `--fps`, `--w`, `--h`, `--from`, `--to`, `--lang`,
`--ffmpeg /path/to/ffmpeg`, and `--gpu` (try hardware GL; the default is
software GL, which is slow but exact).

The fonts are the system UI fonts (SF Pro / Helvetica / PingFang / YaHei). The
film has no network dependencies.
