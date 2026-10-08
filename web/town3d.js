/* =====================================================================
   Market Town in 3D.

   This file draws; it does not decide. Every height, width and count comes from
   the model that web/index.html builds out of /api/state (see `cityModel` there),
   which in turn reads mes/city.py. The plate keeps the coordinates of the flat town
   it replaced — 800 × 800 plate pixels, x east, y south — and so does the scale: one
   plate pixel is a tenth of a world unit, horizontally and vertically.

   What moves, and what it means:
     walking figures   ten agents carrying an order along their group's route; the
                       crate is green for a buy and red for a sell, in the proportion
                       the group's orders of this step actually had (`buyShare`)
     trucks            the ETF depot's scheduled purchases (green cargo, it only buys)
                       and the issuer's new shares (red cargo, it only sells); a truck
                       leaves when its group traded this step and comes back to park
     coloured lanes    a route's width is the group's order flow; the chevrons on it
                       run towards the exchanges
     smoke             the issuer is selling stock this step
     numbers           the fills of the selected market, over its tower
     red ring, beacon  a margin call
     light and rain    sentiment: warm sun when it is greedy, overcast when it is
                       fearful, rain when it is panicking

   Streets, trees and the faint town on the horizon claim nothing.
   ===================================================================== */
(function () {
  'use strict';

  const THREE = window.THREE;
  const U = 0.1;                          // world units per plate pixel
  const wx = px => (px - 400) * U;        // plate x → world x
  const wz = py => (py - 400) * U;        // plate y → world z
  const FLOOR = 0.5;                      // one floor: five plate pixels

  const COLOURS = {
    mom: '#e07434', val: '#2f9e86', noise: '#8a7fa3', etf: '#2f9e5e', lev: '#d14a3c',
    mkr: '#3d8fb5', cmp: '#8f6fd0', bank: '#5872c9', exch: '#2f5bea', exchsel: '#2f5bea',
    gold: '#c99a2e',
  };
  const BUY = '#22a556', SELL = '#e0443a';

  /* Which block types belong to which label, for anchoring the labels and the pin. */
  const GROUPS = {
    bank: ['bank'], mom: ['mom'], val: ['val'], noise: ['noise'], etf: ['etf'],
    lev: ['lev', 'levx', 'rubble'], mkr: ['mkr'], cmp: ['cmp'], exch: ['exchsel'],
  };

  /* ------------------------------------------------------------ helpers */
  function rng(seed) {
    return () => {
      seed |= 0; seed = seed + 0x6D2B79F5 | 0;
      let t = Math.imul(seed ^ seed >>> 15, 1 | seed);
      t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
      return ((t ^ t >>> 14) >>> 0) / 4294967296;
    };
  }
  const C = hex => new THREE.Color(hex);
  const mix = (a, b, t) => C(a).lerp(C(b), t);
  const mat = (color, o) => new THREE.MeshStandardMaterial(
    Object.assign({color, roughness: .85, metalness: 0, flatShading: true}, o || {}));
  const UNIT_BOX = new THREE.BoxGeometry(1, 1, 1);

  function shadowed(mesh, cast) { mesh.castShadow = cast !== false; mesh.receiveShadow = true; return mesh; }
  function box(parent, w, h, d, material, x, y, z) {
    const m = shadowed(new THREE.Mesh(new THREE.BoxGeometry(w, h, d), material));
    m.position.set(x, y, z); parent.add(m); return m;
  }
  /* A unit box scaled into place — for parts that change size with the data. */
  function part(parent, material, cast) {
    const m = shadowed(new THREE.Mesh(UNIT_BOX, material), cast);
    parent.add(m); return m;
  }
  const place = (m, w, h, d, x, y, z) => { m.scale.set(w, h, d); m.position.set(x, y, z); };
  /* A triangular prism, ridge along z, base at baseY. Used for every gable. */
  function prism(parent, w, h, d, material, x, baseY, z, rotY) {
    const g = new THREE.CylinderGeometry(1, 1, 1, 3); g.rotateX(-Math.PI / 2);
    const m = shadowed(new THREE.Mesh(g, material));
    m.scale.set(w / 1.732, h / 1.5, d); m.position.set(x, baseY + .5 * h / 1.5, z);
    m.rotation.y = rotY || 0; parent.add(m); return m;
  }
  function canvasTexture(w, h, draw, repeat) {
    const c = document.createElement('canvas'); c.width = w; c.height = h; draw(c.getContext('2d'), w, h);
    const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 4;
    if (repeat !== false) t.wrapS = t.wrapT = THREE.RepeatWrapping;
    return t;
  }

  /* Facades. One tile is four bays wide and four floors high, so the repeat count is
     simply width in units and height in floors divided by four. */
  const FACADES = {
    /* brick with punched windows */
    brick: () => canvasTexture(128, 128, g => {
      g.fillStyle = '#fff'; g.fillRect(0, 0, 128, 128);
      for (let j = 0; j < 4; j++) { g.fillStyle = 'rgba(0,0,0,.06)'; g.fillRect(0, j * 32 + 28, 128, 4); }
      for (let i = 0; i < 4; i++) for (let j = 0; j < 4; j++) {
        g.fillStyle = '#7f93b3'; g.fillRect(i * 32 + 8, j * 32 + 7, 16, 18);
        g.fillStyle = '#c9d6ea'; g.fillRect(i * 32 + 8, j * 32 + 7, 16, 5);
        g.fillStyle = 'rgba(255,255,255,.9)'; g.fillRect(i * 32 + 6, j * 32 + 25, 20, 3);
      }
    }),
    /* stone with tall paired windows */
    stone: () => canvasTexture(128, 128, g => {
      g.fillStyle = '#fff'; g.fillRect(0, 0, 128, 128);
      for (let i = 0; i < 4; i++) for (let j = 0; j < 4; j++) {
        g.fillStyle = '#6f86a8'; g.fillRect(i * 32 + 6, j * 32 + 5, 9, 22); g.fillRect(i * 32 + 17, j * 32 + 5, 9, 22);
        g.fillStyle = '#bfcfe6'; g.fillRect(i * 32 + 6, j * 32 + 5, 20, 4);
      }
    }),
    /* glass curtain wall with mullions and floor bands */
    glass: () => canvasTexture(128, 128, g => {
      const grd = g.createLinearGradient(0, 0, 128, 128);
      grd.addColorStop(0, '#dfe9ff'); grd.addColorStop(.5, '#9fb7ea'); grd.addColorStop(1, '#c9d8fb');
      g.fillStyle = grd; g.fillRect(0, 0, 128, 128);
      g.fillStyle = 'rgba(255,255,255,.85)';
      for (let i = 0; i <= 4; i++) g.fillRect(i * 32 - 1, 0, 3, 128);
      for (let j = 0; j <= 4; j++) g.fillRect(0, j * 32 - 2, 128, 4);
    }),
    /* corrugated shed wall */
    shed: () => canvasTexture(64, 64, g => {
      g.fillStyle = '#fff'; g.fillRect(0, 0, 64, 64);
      for (let i = 0; i < 16; i++) { g.fillStyle = i % 2 ? 'rgba(0,0,0,.07)' : 'rgba(255,255,255,0)'; g.fillRect(i * 4, 0, 4, 64); }
      g.fillStyle = 'rgba(0,0,0,.08)'; g.fillRect(0, 0, 64, 6);
    }),
  };
  const HATCH = col => canvasTexture(64, 64, g => {
    g.fillStyle = '#fff'; g.fillRect(0, 0, 64, 64); g.strokeStyle = col; g.lineWidth = 7;
    for (let i = -64; i < 128; i += 16) { g.beginPath(); g.moveTo(i, 64); g.lineTo(i + 64, 0); g.stroke(); }
  });
  const CHEVRON = () => canvasTexture(64, 16, g => {
    g.fillStyle = '#fff'; g.beginPath();
    g.moveTo(14, 2); g.lineTo(34, 2); g.lineTo(44, 8); g.lineTo(34, 14); g.lineTo(14, 14); g.lineTo(24, 8);
    g.closePath(); g.fill();
  });
  const DASH = () => canvasTexture(64, 8, g => { g.fillStyle = '#fff'; g.fillRect(4, 2, 30, 4); });

  /* A route: a polyline in plate pixels, walked by distance. */
  function polyline(pts) {
    const segs = []; let L = 0;
    for (let i = 0; i < pts.length - 1; i++) {
      const ax = wx(pts[i][0]), az = wz(pts[i][1]), bx = wx(pts[i + 1][0]), bz = wz(pts[i + 1][1]);
      const l = Math.hypot(bx - ax, bz - az) || 1e-6;
      segs.push({ax, az, dx: (bx - ax) / l, dz: (bz - az) / l, l, s: L});
      L += l;
    }
    return {segs, L};
  }
  function along(P, d) {
    let s = P.segs[P.segs.length - 1];
    for (const q of P.segs) if (d <= q.s + q.l) { s = q; break; }
    const u = Math.max(0, Math.min(d - s.s, s.l));
    return {x: s.ax + s.dx * u, z: s.az + s.dz * u, dx: s.dx, dz: s.dz};
  }

  /* =================================================================== */
  class Town {
    constructor(host, hooks) {
      this.host = host;
      this.hooks = hooks || {};
      this.canvas = document.createElement('canvas');
      this.canvas.className = 'gl';
      host.prepend(this.canvas);

      const r = this.renderer = new THREE.WebGLRenderer({canvas: this.canvas, antialias: true});
      r.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      r.shadowMap.enabled = true;
      r.shadowMap.type = THREE.PCFSoftShadowMap;

      this.scene = new THREE.Scene();
      this.scene.background = C('#dfe6ef');
      this.scene.fog = new THREE.Fog('#dfe6ef', 150, 340);
      this.camera = new THREE.PerspectiveCamera(30, 1, 1, 900);

      this.hemi = new THREE.HemisphereLight('#ffffff', '#b4c0d2', 1.25);
      this.sun = new THREE.DirectionalLight('#ffffff', 2.6);
      this.sun.position.set(45, 85, 30);
      this.sun.castShadow = true;
      this.sun.shadow.mapSize.set(2048, 2048);
      Object.assign(this.sun.shadow.camera, {left: -60, right: 60, top: 60, bottom: -60, near: 10, far: 240});
      this.sun.shadow.bias = -0.0004; this.sun.shadow.normalBias = .04;
      this.scene.add(this.hemi, this.sun, this.sun.target);

      this.tex = {};
      for (const k in FACADES) this.tex[k] = FACADES[k]();
      this.chevron = CHEVRON();
      this.static = new THREE.Group(); this.scene.add(this.static);
      this.city = new THREE.Group(); this.scene.add(this.city);
      this.movers = new THREE.Group(); this.scene.add(this.movers);

      /* camera: an orbit around the plate centre, isometric-ish by default */
      this.view = {theta: Math.PI / 4, phi: 0.92, R: 150, target: new THREE.Vector3(0, 0, 0)};
      this.home = Object.assign({}, this.view, {target: this.view.target.clone()});
      this.frame = {left: 0, right: 0, top: 0, bottom: 0};

      this.blocks = [];
      this.signature = '';
      this.routes = {};          // key → {P, lanes, flow, walkers, trucks, buy}
      this.switchers = [];
      this.pips = [];
      this.time = 0;
      this.tempo = 1;
      this.paused = false;
      this.moodTarget = 50; this.mood = 50;
      this.alarm = false;
      this.selected = 'mom';
      this.reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;

      this.buildSky();
      this.bindInput();
      this.resize();
      new ResizeObserver(() => this.resize()).observe(host);
      this.clock = new THREE.Clock();
      const loop = () => { requestAnimationFrame(loop); this.frameTick(); };
      loop();
    }

    /* ------------------------------------------- what does not depend on layout */
    buildSky() {
      const S = this.static;
      const ground = shadowed(new THREE.Mesh(new THREE.PlaneGeometry(1200, 1200), mat('#e5ebf2')), false);
      ground.rotation.x = -Math.PI / 2; ground.position.y = -1.45; S.add(ground);
      const side = mat('#c6cfdb'), top = mat('#f4f6f9');
      const plate = shadowed(new THREE.Mesh(new THREE.BoxGeometry(84, 1.4, 84), [side, side, top, top, side, side]), false);
      plate.position.y = -.7; S.add(plate);

      /* the horizon: a faint town that is not part of the model */
      const r = rng(9), far = mat('#eef1f6');
      for (let i = 0; i < 90; i++) {
        const a = r() * Math.PI * 2, rad = 70 + r() * 90, w = 4 + r() * 9, d = 4 + r() * 9, h = 2 + r() * 10;
        box(S, w, h, d, far, Math.cos(a) * rad * 1.2, h / 2 - 1.45, Math.sin(a) * rad).castShadow = false;
      }

      /* rain, for fear */
      const N = 1600, pos = new Float32Array(N * 3), rr = rng(5);
      for (let i = 0; i < N; i++) { pos[i * 3] = (rr() - .5) * 100; pos[i * 3 + 1] = rr() * 45; pos[i * 3 + 2] = (rr() - .5) * 100; }
      const geo = new THREE.BufferGeometry(); geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
      this.rain = new THREE.Points(geo, new THREE.PointsMaterial({color: '#7f8fa8', size: .17, transparent: true, opacity: 0, depthWrite: false}));
      S.add(this.rain);

      const pin = new THREE.Group(), pm = mat('#2f5bea', {flatShading: false, roughness: .4, emissive: '#2f5bea', emissiveIntensity: .15});
      const ph = shadowed(new THREE.Mesh(new THREE.SphereGeometry(.8, 20, 14), pm)); ph.position.y = 1.4;
      const pc = shadowed(new THREE.Mesh(new THREE.ConeGeometry(.7, 1.5, 20), pm)); pc.rotation.x = Math.PI; pc.position.y = .5;
      const pd = new THREE.Mesh(new THREE.SphereGeometry(.32, 12, 10), new THREE.MeshBasicMaterial({color: '#ffffff'}));
      pd.position.set(0, 1.45, .58);
      pin.add(ph, pc, pd); this.pin = pin; S.add(pin);
    }

    /* ----------------------------------------------- streets, plots, trees */
    buildLayout(L) {
      const S = new THREE.Group(); this.layoutGroup = S; this.static.add(S);
      const asphalt = mat('#cdd5e0'), kerb = mat('#e9edf3');

      /* district plots */
      for (const [k, [x, y, w, h]] of Object.entries(L.zones)) {
        box(S, w * U, .06, h * U, mat(mix('#f4f6f9', COLOURS[k], .14)), wx(x + w / 2), .03, wz(y + h / 2)).castShadow = false;
      }
      /* the exchange square */
      const [px, py, pw, ph] = L.plaza;
      box(S, pw * U, .1, ph * U, mat('#e4e9f1'), wx(px + pw / 2), .05, wz(py + ph / 2)).castShadow = false;

      /* the street grid: asphalt, kerbs and a dashed centre line */
      L.streets.forEach(([a, b], i) => {
        const ax = wx(a[0]), az = wz(a[1]), bx = wx(b[0]), bz = wz(b[1]);
        const len = Math.hypot(bx - ax, bz - az), horiz = Math.abs(bz - az) < 1e-6;
        const y = .07 + i * .002, mx = (ax + bx) / 2, mz = (az + bz) / 2;
        const road = box(S, horiz ? len + 2.6 : 2.6, .06, horiz ? 2.6 : len + 2.6, asphalt, mx, y, mz); road.castShadow = false;
        const curbW = .3;
        [-1, 1].forEach(sd => {
          const k = box(S, horiz ? len + 2.6 : curbW, .1, horiz ? curbW : len + 2.6, kerb,
            mx + (horiz ? 0 : sd * 1.45), y + .02, mz + (horiz ? sd * 1.45 : 0));
          k.castShadow = false;
        });
        const t = DASH(); t.repeat.set(len / 2.2, 1);
        const g = new THREE.PlaneGeometry(len, .12); g.rotateX(-Math.PI / 2);
        const line = new THREE.Mesh(g, new THREE.MeshBasicMaterial({map: t, transparent: true, opacity: .9, depthWrite: false}));
        line.position.set(mx, y + .045, mz); line.rotation.y = horiz ? 0 : Math.PI / 2; S.add(line);
      });

      /* the central bank's channel */
      this.policy = this.lane(S, polyline(L.policy), .5, COLOURS.bank, .55, 0);

      /* the margin-call ring */
      const rg = new THREE.TorusGeometry(5.5, .2, 6, 64); rg.rotateX(Math.PI / 2);
      this.ring = new THREE.Mesh(rg, new THREE.MeshBasicMaterial({color: '#ff4a3a', transparent: true, opacity: 0}));
      this.ring.position.set(wx(L.ring[0]), .25, wz(L.ring[1])); S.add(this.ring);

      this.plantTrees(S, L);
    }

    /* Trees go wherever nothing else is: empty lots, the edge of the plate, beside the
       streets. They are not a quantity, so they are placed by a fixed seed. */
    plantTrees(S, L) {
      const tr = rng(11), trunk = mat('#8b6a4c'), leaves = [mat('#7fc77d'), mat('#5fae63'), mat('#93d08a')];
      const busy = [];
      for (const z of Object.values(L.zones)) busy.push([z[0] - 6, z[1] - 6, z[0] + z[2] + 6, z[1] + z[3] + 6]);
      busy.push([L.plaza[0] - 6, L.plaza[1] - 70, L.plaza[0] + L.plaza[2] + 6, L.plaza[1] + L.plaza[3] + 6]);
      for (const [a, b] of L.streets) busy.push([Math.min(a[0], b[0]) - 17, Math.min(a[1], b[1]) - 17,
                                                 Math.max(a[0], b[0]) + 17, Math.max(a[1], b[1]) + 17]);
      const free = (x, y) => !busy.some(([x0, y0, x1, y1]) => x > x0 && x < x1 && y > y0 && y < y1);
      this.trees = [];
      for (let y = 22; y < 790; y += 30) for (let x = 22; x < 790; x += 30) {
        const px = x + (tr() - .5) * 18, py = y + (tr() - .5) * 18;
        if (!free(px, py) || tr() < .58) continue;
        const g = new THREE.Group(); g.position.set(wx(px), 0, wz(py)); g.scale.setScalar(.55 + tr() * .35); S.add(g);
        const t = shadowed(new THREE.Mesh(new THREE.CylinderGeometry(.14, .18, 1.1, 6), trunk)); t.position.y = .55; g.add(t);
        const f = shadowed(new THREE.Mesh(new THREE.IcosahedronGeometry(1, 0), leaves[(tr() * 3) | 0]));
        f.position.y = 1.8; f.scale.set(1, 1.15, 1); f.rotation.y = tr() * 3; g.add(f);
        this.trees.push({g, ph: tr() * 6});
      }
    }

    /* A coloured strip of chevrons along a route, offset to one side by its lane so
       routes sharing a street run side by side. */
    lane(parent, P, width, colour, opacity, side) {
      const parts = P.segs.map(s => {
        const t = this.chevron.clone(); t.needsUpdate = true; t.repeat.set(s.l / 1.4, 1);
        const g = new THREE.PlaneGeometry(1, 1); g.rotateX(-Math.PI / 2);
        const m = new THREE.Mesh(g, new THREE.MeshBasicMaterial({map: t, color: colour, transparent: true, opacity, depthWrite: false}));
        m.rotation.y = -Math.atan2(s.dz, s.dx);
        parent.add(m);
        return {m, t, s};
      });
      const strip = {parts, side, width};
      this.shapeLane(strip, width);
      return strip;
    }
    shapeLane(strip, width) {
      strip.width = width;
      for (const {m, s} of strip.parts) {
        const off = strip.side;
        m.scale.set(s.l + width, 1, width);
        m.position.set(s.ax + s.dx * s.l / 2 - s.dz * off, .14, s.az + s.dz * s.l / 2 + s.dx * off);
      }
    }

    /* ------------------------------------------------------ buildings */
    facade(kind, colour, w, h, extra) {
      const t = this.tex[kind].clone(); t.needsUpdate = true;
      t.repeat.set(Math.max(1, w / 4), Math.max(1, h / FLOOR / 4));
      return mat(colour, Object.assign({map: t}, extra || {}));
    }

    makeBlock(b, i) {
      const g = new THREE.Group(); g.userData = {type: b.t, index: i, cur: null, parts: {}};
      const w = b.w * U, d = b.d * U, type = b.t, P = g.userData.parts, r = rng(i * 13 + 7);
      const col = COLOURS[type] || '#9aa6b8';

      if (type === 'bank') {
        /* a temple front: the one building that holds no capital */
        const marble = mat('#eef0f3'), roof = mat('#5872c9'), dark = mat('#3b4a6b');
        box(g, w, .45, d, marble, 0, .22, 0); box(g, w - .8, .45, d - .6, marble, 0, .67, 0);
        box(g, w - 4, 3.6, d - 3.6, mat('#e3e7ee'), 0, 2.7, -.8);
        box(g, 2.2, 2.6, .1, dark, 0, 2.2, d / 2 - 2.65);
        for (let k = 0; k < 8; k++) {
          const c = shadowed(new THREE.Mesh(new THREE.CylinderGeometry(.32, .38, 3.6, 12), marble));
          c.position.set(-w / 2 + 1.6 + k * (w - 3.2) / 7, 2.7, d / 2 - 1.2); g.add(c);
        }
        box(g, w - .4, .55, d - .4, marble, 0, 4.75, 0); prism(g, w - .4, 1.7, d - .4, roof, 0, 5.0, 0, Math.PI / 2);
        g.userData.fixed = true;
      } else if (type === 'cmp') {
        /* the issuer: a hall with a sawtooth roof, two chimneys and a loading bay */
        const hh = 3.2;
        box(g, w, hh, d, this.facade('shed', mix(col, '#ffffff', .35), w, hh), 0, hh / 2, 0);
        const saw = mat(mix(col, '#ffffff', .55)), glass = mat('#b9cdf0');
        for (let k = 0; k < 4; k++) {
          prism(g, w / 4, 1.5, d, saw, -w / 2 + w / 4 * (k + .5), hh, 0, 0);
          box(g, .08, 1.0, d - .4, glass, -w / 2 + w / 4 * (k + 1) - .05, hh + .5, 0);
        }
        box(g, .15, 2.2, 2.6, mat('#3b4656'), -w / 2 - .02, 1.1, 0);
        box(g, .9, .12, 3.0, mat(col), -w / 2 - .45, 2.4, 0);
        this.chimneys = [[w / 4, -d / 4], [w / 4 + 1.6, -d / 4]].map(([cx, cz]) => {
          const c = shadowed(new THREE.Mesh(new THREE.CylinderGeometry(.45, .55, 6.5, 12), mat('#c9c2d6')));
          c.position.set(cx, 3.25, cz); g.add(c);
          box(g, 1.05, .3, 1.05, mat('#a99fbb'), cx, 6.3, cz);
          return new THREE.Vector3(wx(b.x + b.w / 2) + cx, 6.7, wz(b.y + b.d / 2) + cz);
        });
        g.userData.fixed = true;
      } else if (type === 'rubble') {
        const m = mat('#b9a9a4', {map: HATCH('#d14a3c')});
        for (let k = 0; k < 8; k++) {
          const s = .8 + r() * 1.6;
          const c = box(g, s, s * .7, s, m, (r() - .5) * (w - 1.5), s * .35, (r() - .5) * (d - 1.5));
          c.rotation.set(r(), r() * 3, r());
        }
        g.userData.fixed = true;
      } else if (type === 'noise') {
        /* a small house: walls, a gable roof, a chimney, a door with a step */
        P.body = part(g, this.facade('brick', mix(col, '#ffffff', .6), w, 2));
        P.roof = prism(g, d + .5, 1.5, w + .4, mat(mix(col, '#3f3555', .25)), 0, 0, 0, Math.PI / 2);
        P.chim = part(g, mat('#a9a0b6'));
        P.door = part(g, mat('#5a4a3c'), false);
      } else if (type === 'etf') {
        /* a depot shed: corrugated walls, a barrel roof, loading doors on the road side */
        P.body = part(g, this.facade('shed', mix(col, '#ffffff', .45), w, 3));
        const barrel = new THREE.CylinderGeometry(d / 2, d / 2, w, 20, 1, false, 0, Math.PI);
        barrel.rotateZ(Math.PI / 2);
        P.roof = shadowed(new THREE.Mesh(barrel, mat(mix(col, '#ffffff', .7), {flatShading: false}))); P.roof.scale.y = .35; g.add(P.roof);
        P.doors = [0, 1, 2].map(() => part(g, mat('#3b4656'), false));
        P.band = part(g, mat(col), false);
      } else if (type === 'exch' || type === 'exchsel') {
        /* an exchange: a glass tower with fins, a lit entrance and a price band */
        const sel = type === 'exchsel';
        P.body = part(g, this.facade('glass', sel ? '#4d76f0' : '#7d97dd', w, 6, {roughness: .3, metalness: .2,
          emissive: sel ? '#1e3fb8' : '#000000', emissiveIntensity: sel ? .22 : 0}));
        P.fins = [-1, 1].map(sx => [-1, 1].map(sz => part(g, mat(sel ? '#dfe7ff' : '#e9eef8')))).flat();
        P.base = part(g, mat('#c9d4ea'));
        P.canopy = part(g, mat(sel ? '#2f5bea' : '#5b7bd8'));
        P.cap = part(g, mat(sel ? '#dfe7ff' : '#e3e9f5'));
        const c = document.createElement('canvas'); c.width = 256; c.height = 64;
        const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace; tex.anisotropy = 4;
        const face = new THREE.MeshBasicMaterial({map: tex}), dark = new THREE.MeshBasicMaterial({color: '#141820'});
        P.band = shadowed(new THREE.Mesh(UNIT_BOX, [face, face, dark, dark, face, face]), false); g.add(P.band);
        g.userData.ticker = {c, tex, text: ''};
        P.antenna = shadowed(new THREE.Mesh(new THREE.CylinderGeometry(.05, .08, 2.4, 6), mat('#9aa3b0'))); g.add(P.antenna);
        if (sel) { P.halo = part(g, new THREE.MeshBasicMaterial({color: '#2f5bea', transparent: true, opacity: .25}), false); }
      } else {
        /* an office block whose height is a quantity: plinth, facade, corner pilasters,
           parapet and roof plant. Trend camp in brick, value camp in stone, the makers
           in glass with a quote band, the leverage tower in red brick. */
        const style = type === 'val' ? 'stone' : type === 'mkr' ? 'glass' : 'brick';
        const wall = type === 'levx' ? mat('#ffffff', {map: (() => { const t = HATCH(COLOURS.lev); t.repeat.set(2, 2); return t; })()})
          : this.facade(style, type === 'mkr' ? '#9cc2dc' : mix(col, '#ffffff', type === 'val' ? .35 : .12), w, 8,
              type === 'mkr' ? {roughness: .35, metalness: .15} : undefined);
        P.body = part(g, wall);
        const trim = mat(type === 'levx' ? '#f2c9c2' : mix(col, '#ffffff', .6));
        if (type !== 'levx') {
          P.plinth = part(g, mat(mix(col, '#2a3142', .45)));
          P.pil = [-1, 1].map(sx => [-1, 1].map(sz => { const m = part(g, trim); m.userData.c = [sx, sz]; return m; })).flat();
          P.door = part(g, mat('#2f3a4d'), false);
          P.awning = part(g, mat(col), false);
        }
        P.parapet = [0, 1, 2, 3].map(() => part(g, trim));
        P.roofDeck = part(g, mat(mix(col, '#ffffff', .75)), false);
        if (type === 'mkr') P.quote = part(g, new THREE.MeshBasicMaterial({color: '#22c55e'}), false);
        if (type !== 'levx') {
          P.units = [0, 1].map(() => { const u = part(g, mat('#dfe4ea')); u.userData.s = [.9 + r() * 1.1, .6, .9 + r() * .8, (r() - .5) * (w - 2.4), (r() - .5) * (d - 2.4)]; return u; });
          if (r() < .6) {
            P.tank = shadowed(new THREE.Mesh(new THREE.CylinderGeometry(.55, .55, 1.1, 12), mat('#b9a58f'))); g.add(P.tank);
            P.tank.userData.at = [(r() - .5) * (w - 2.2), (r() - .5) * (d - 2.2)];
          }
        }
        if (type === 'lev') {
          this.beacon = new THREE.Mesh(new THREE.SphereGeometry(.45, 14, 10), new THREE.MeshBasicMaterial({color: '#7a1a14'}));
          g.add(this.beacon); P.beacon = this.beacon;
          P.mast = shadowed(new THREE.Mesh(new THREE.CylinderGeometry(.06, .1, 1.8, 6), mat('#9aa3b0'))); g.add(P.mast);
        }
      }
      g.position.set(wx(b.x + b.w / 2), 0, wz(b.y + b.d / 2));
      g.traverse(o => { if (o.isMesh) o.userData.pick = {type, index: i}; });
      this.city.add(g);
      return g;
    }

    /* Size a block to its current (tweened) bottom and top, in world units. Only the
       parts whose size is a quantity move; the footprint never does. */
    shape(g, b, z0, top) {
      const u = g.userData, P = u.parts, w = b.w * U, d = b.d * U, h = Math.max(.05, top - z0);
      if (u.fixed) return;
      const retile = m => { const t = m.material.map; if (t) t.repeat.set(Math.max(1, w / 4), Math.max(1, h / FLOOR / 4)); };
      const t = b.t;
      if (t === 'noise') {
        place(P.body, w, h, d, 0, z0 + h / 2, 0); retile(P.body);
        P.roof.position.y = top + .5;
        place(P.chim, .4, 1.1, .4, w / 4, top + .9, -d / 4);
        place(P.door, .7, Math.min(1, h * .8), .08, 0, Math.min(1, h * .8) / 2, d / 2 + .04);
        return;
      }
      if (t === 'etf') {
        place(P.body, w, h, d, 0, z0 + h / 2, 0); retile(P.body);
        P.roof.position.y = top;
        P.doors.forEach((m, k) => place(m, 1.5, Math.min(2.2, h * .8), .1, -w / 3 + k * w / 3, Math.min(2.2, h * .8) / 2, -d / 2 - .05));
        place(P.band, w + .05, .25, d + .05, 0, top - .3, 0);
        return;
      }
      if (t === 'exch' || t === 'exchsel') {
        const base = .9;
        place(P.base, w + .6, base, d + .6, 0, base / 2, 0);
        place(P.body, w, h - base, d, 0, base + (h - base) / 2, 0); retile(P.body);
        P.fins.forEach((m, k) => { const sx = k < 2 ? -1 : 1, sz = k % 2 ? 1 : -1;
          place(m, .3, h - base, .3, sx * (w / 2 + .05), base + (h - base) / 2, sz * (d / 2 + .05)); });
        place(P.canopy, 2.4, .18, 1.4, 0, base + 1.6, d / 2 + .7);
        const bh = Math.min(1.1, h * .25);
        place(P.band, w + .3, bh, d + .3, 0, top - bh / 2 - .5, 0);
        place(P.cap, w + .4, .4, d + .4, 0, top + .2, 0);
        P.antenna.position.y = top + 1.5;
        if (P.halo) place(P.halo, w + 2.4, .04, d + 2.4, 0, .12, 0);
        return;
      }
      /* office blocks, including the borrowed floors on the leverage tower */
      const plinth = P.plinth && z0 === 0 ? Math.min(.8, h * .3) : 0;
      if (t === 'levx') { place(P.body, w - .5, h, d - .5, 0, z0 + h / 2, 0); }
      else { place(P.body, w, h, d, 0, z0 + h / 2, 0); retile(P.body); }
      if (P.plinth) place(P.plinth, w + .2, plinth || .01, d + .2, 0, (plinth || .01) / 2, 0);
      if (P.pil) P.pil.forEach(m => { const [sx, sz] = m.userData.c;
        place(m, .32, h, .32, sx * (w / 2), z0 + h / 2, sz * (d / 2)); });
      if (P.door) {
        const dh = Math.min(1.4, h * .7);
        place(P.door, 1.2, dh, .08, 0, dh / 2, d / 2 + .04);
        place(P.awning, 1.8, .1, .7, 0, dh + .1, d / 2 + .35);
      }
      const inset = t === 'levx' ? .25 : 0, pw = w - inset * 2, pd = d - inset * 2;
      place(P.parapet[0], pw + .1, .35, .22, 0, top + .17, pd / 2);
      place(P.parapet[1], pw + .1, .35, .22, 0, top + .17, -pd / 2);
      place(P.parapet[2], .22, .35, pd, pw / 2, top + .17, 0);
      place(P.parapet[3], .22, .35, pd, -pw / 2, top + .17, 0);
      place(P.roofDeck, pw - .1, .04, pd - .1, 0, top + .02, 0);
      if (P.quote) place(P.quote, w + .04, .22, d + .04, 0, Math.max(plinth + .4, top - .7), 0);
      if (P.units) P.units.forEach(m => { const [sx, sy, sz, ox, oz] = m.userData.s; place(m, sx, sy, sz, ox, top + sy / 2, oz); });
      if (P.tank) P.tank.position.set(P.tank.userData.at[0], top + .75, P.tank.userData.at[1]);
      if (P.beacon) { P.mast.position.y = top + .9; P.beacon.position.y = top + 1.9; }
    }

    paintTicker(g, m) {
      const t = g.userData.ticker;
      if (!t || !m) return;
      const text = m.sym + m.px + m.chg;
      if (t.text === text) return;
      t.text = text;
      const x = t.c.getContext('2d'), up = !String(m.chg).includes('▼');
      x.fillStyle = '#10141b'; x.fillRect(0, 0, 256, 64);
      x.fillStyle = up ? '#3fd27f' : '#ff6b5e'; x.fillRect(0, 58, 256, 6);
      x.font = '600 26px "IBM Plex Mono", ui-monospace, monospace'; x.textBaseline = 'middle';
      x.fillStyle = '#ffffff'; x.textAlign = 'left'; x.fillText(m.sym, 14, 30);
      x.fillStyle = up ? '#3fd27f' : '#ff6b5e'; x.textAlign = 'right'; x.fillText(String(m.px), 244, 30);
      t.tex.needsUpdate = true;
    }

    /* ------------------------------------------------------ movers */
    walker(colour) {
      const g = new THREE.Group(); g.scale.setScalar(1.45);
      const body = shadowed(new THREE.Mesh(new THREE.CapsuleGeometry(.2, .34, 3, 8), mat(colour)));
      body.position.y = .48; g.add(body);
      const head = shadowed(new THREE.Mesh(new THREE.SphereGeometry(.17, 10, 8), mat('#f1d3b8'))); head.position.y = .98; g.add(head);
      const crate = shadowed(new THREE.Mesh(new THREE.BoxGeometry(.42, .34, .34), mat(BUY, {emissive: BUY, emissiveIntensity: .15})));
      crate.position.set(0, .6, .3); g.add(crate);
      this.movers.add(g);
      return {g, body, crate, d: 0, dir: 1, wait: 0, ph: Math.random() * 6, jitter: (Math.random() - .5) * .5, buy: true};
    }

    truck(key) {
      const g = new THREE.Group(); g.scale.setScalar(1.15);
      const cab = mat(key === 'etf' ? '#2f5bea' : '#7b5cc4');
      box(g, 1.5, 1.2, 1.3, cab, 0, .85, 1.3);
      box(g, 1.3, .45, .1, mat('#9fc5ff'), 0, 1.05, 1.96);
      const side = canvasTexture(64, 32, x => { x.fillStyle = '#ffffff'; x.fillRect(0, 0, 64, 32); x.fillStyle = COLOURS[key]; x.fillRect(0, 20, 64, 6); }, false);
      box(g, 1.6, .25, 3.0, mat('#d8dee8'), 0, .55, -.9);
      /* the cargo: green crates for the depot's purchases, red for the issuer's shares */
      const load = key === 'etf' ? BUY : SELL, cargo = [];
      for (let k = 0; k < 4; k++) {
        const c = box(g, .66, .6, .66, mat(load, {emissive: load, emissiveIntensity: .12}), k % 2 ? .38 : -.38, 1.0, -.3 - (k >> 1) * .9 - .4);
        cargo.push(c);
      }
      box(g, .1, 1.0, 3.0, mat('#ffffff', {map: side}), .82, 1.1, -.9).castShadow = false;
      const wh = mat('#22262c');
      [[-.75, 1.2], [.75, 1.2], [-.75, -1.6], [.75, -1.6]].forEach(([x, z]) => {
        const w = shadowed(new THREE.Mesh(new THREE.CylinderGeometry(.32, .32, .25, 12), wh));
        w.rotation.z = Math.PI / 2; w.position.set(x, .32, z); g.add(w);
      });
      this.movers.add(g);
      return {g, cargo, d: 0, dir: 1, wait: 0, trip: false};
    }

    drop(obj) { this.movers.remove(obj.g); obj.g.traverse(o => { if (o.isMesh && o.geometry !== UNIT_BOX) o.geometry.dispose(); }); }

    /* ============================================================ draw */
    /* Called on every state the page receives. Cheap when nothing structural changed:
       meshes are kept and only retargeted. */
    draw(M) {
      if (!M) return;
      this.model = M;
      if (!this.layoutGroup && M.layout) this.buildLayout(M.layout);

      const sig = M.blocks.map(b => b.t + ':' + b.x + ',' + b.y).join('|');
      if (sig !== this.signature) {
        this.blocks.forEach(g => this.city.remove(g));
        this.blocks = M.blocks.map((b, i) => this.makeBlock(b, i));
        this.signature = sig;
      }
      M.blocks.forEach((b, i) => {
        const g = this.blocks[i], u = g.userData;
        u.b = b;
        u.target = {z0: b.z0 * U, top: b.top * U};
        if (!u.cur) { u.cur = Object.assign({}, u.target); this.shape(g, b, u.cur.z0, u.cur.top); }
        if (b.t === 'exch' || b.t === 'exchsel') this.paintTicker(g, M.markets[M.exchangeIndex[i]]);
      });

      const fresh = M.step !== this.lastStep && !this.paused;
      for (const r of M.roads) {
        let R = this.routes[r.key];
        if (!R) {
          const P = polyline(r.pts), side = (r.lane || 0) * .7;
          R = this.routes[r.key] = {P, side, walkers: [], trucks: [], colour: r.c,
            strip: this.lane(this.layoutGroup || this.static, P, .5, r.c, .55, side)};
          if (r.key === 'etf' || r.key === 'cmp') R.trucks = [this.truck(r.key), this.truck(r.key)];
        }
        R.flow = r.flow; R.buy = r.buy;
        this.shapeLane(R.strip, .3 + r.flow * U * .9);

        if (r.key === 'etf' || r.key === 'cmp') {
          /* a group that traded this step sends a truck; it does its trip and parks */
          if (fresh && r.n > 0) { const t = R.trucks.find(q => !q.trip); if (t) { t.trip = true; t.wait = 0; } }
          continue;
        }
        /* Figures join the road while the flow is up and leave it at their door once it
           has dropped — a figure is never removed in the middle of a walk. */
        const live = R.walkers.filter(w => !w.retire);
        if (live.length < r.n) {
          R.walkers.filter(w => w.retire).slice(0, r.n - live.length).forEach(w => { w.retire = false; });
          while (R.walkers.filter(w => !w.retire).length < r.n) {
            const w = this.walker(r.c); w.d = Math.random() * R.P.L * .9; w.dir = Math.random() < .65 ? 1 : -1;
            R.walkers.push(w);
          }
        } else if (live.length > r.n) live.slice(r.n).forEach(w => { w.retire = true; });
      }

      /* agents changing camp walk the avenue between the two halves of the quarter */
      while (this.switchers.length < M.switchers) {
        const w = this.walker(COLOURS.gold); w.crate.visible = false;
        w.P = polyline(M.layout.switchRoutes[this.switchers.length % M.layout.switchRoutes.length]);
        w.d = Math.random() * w.P.L; this.switchers.push(w);
      }
      while (this.switchers.length > M.switchers) this.drop(this.switchers.pop());

      this.moodTarget = M.mood;
      this.alarm = M.alarm;
      this.issuing = M.issuing;

      /* the fills of this step rise over the selected tower — only when time moved */
      if (fresh) {
        const i = M.blocks.findIndex(b => b.t === 'exchsel');
        if (i >= 0) {
          const b = M.blocks[i];
          M.pips.slice(0, 5).forEach((p, k) => setTimeout(() => this.pip(p,
            wx(b.x + b.w / 2) + (Math.random() - .5) * 4, b.top * U + 1.8, wz(b.y + b.d / 2) + (Math.random() - .5) * 4), k * 130));
        }
      }
      this.lastStep = M.step;
      this.select(M.selected);
    }

    pip(p, x, y, z) {
      const layer = this.hooks.pipLayer;
      if (!layer) return;
      let q = this.pips.find(o => o.life <= 0);
      if (!q) {
        if (this.pips.length > 30) return;
        const el = document.createElement('div'); el.className = 'pip'; layer.appendChild(el);
        q = {el, pos: new THREE.Vector3(), life: 0}; this.pips.push(q);
      }
      q.el.textContent = p.t; q.el.style.color = p.c; q.pos.set(x, y, z); q.life = 2.2;
    }

    setTempo(factor, paused) { this.tempo = factor; this.paused = !!paused; }

    select(key) { this.selected = key || this.selected; }

    /* The label anchors follow the buildings they name: centre of the group's
       footprint, a little above its tallest roof. */
    anchor(key) {
      const types = GROUPS[key];
      if (!types || !this.model) return null;
      let x = 0, z = 0, n = 0, top = 0;
      this.blocks.forEach(g => {
        const u = g.userData;
        if (!u.b || !types.includes(u.b.t)) return;
        x += wx(u.b.x + u.b.w / 2); z += wz(u.b.y + u.b.d / 2); n++;
        const extra = u.b.t === 'bank' ? 2.4 : u.b.t === 'cmp' ? 1.4 : u.b.t === 'noise' ? 1.6 : 1.2;
        top = Math.max(top, (u.cur ? u.cur.top : u.b.top * U) + extra);
      });
      return n ? new THREE.Vector3(x / n, top, z / n) : null;
    }

    /* ---------------------------------------------------------- camera */
    zoomBy(f) { this.moved = true; this.view.R = THREE.MathUtils.clamp(this.view.R / f, 50, 240); }
    reset() { this.moved = false; this.view = Object.assign({}, this.home, {target: this.home.target.clone()}); }
    setFrame(f) {
      const before = JSON.stringify(this.frame);
      this.frame = Object.assign(this.frame, f);
      if (JSON.stringify(this.frame) !== before) this.resize();
    }

    bindInput() {
      const cv = this.canvas;
      let drag = null;
      cv.addEventListener('contextmenu', e => e.preventDefault());
      cv.addEventListener('pointerdown', e => {
        cv.setPointerCapture(e.pointerId);
        drag = {x: e.clientX, y: e.clientY, sx: e.clientX, sy: e.clientY, pan: e.button === 2 || e.shiftKey};
        this.moved = true;
      });
      cv.addEventListener('pointermove', e => {
        if (!drag) { this.hover(e); return; }
        const dx = e.clientX - drag.x, dy = e.clientY - drag.y; drag.x = e.clientX; drag.y = e.clientY;
        if (drag.pan) {
          const s = this.view.R / 900, t = this.view.target, th = this.view.theta;
          t.x -= (dx * Math.cos(th) - dy * Math.sin(th)) * s * 1.4;
          t.z -= (-dx * Math.sin(th) - dy * Math.cos(th)) * s * 1.4;
          t.x = THREE.MathUtils.clamp(t.x, -35, 35); t.z = THREE.MathUtils.clamp(t.z, -35, 35);
        } else {
          this.view.theta -= dx * .006;
          this.view.phi = THREE.MathUtils.clamp(this.view.phi - dy * .004, .38, 1.25);
        }
      });
      cv.addEventListener('pointerup', e => {
        if (drag && Math.hypot(e.clientX - drag.sx, e.clientY - drag.sy) < 5) {
          const hit = this.pick(e);
          if (hit && this.hooks.onPick) this.hooks.onPick(hit);
        }
        drag = null;
      });
      cv.addEventListener('wheel', e => { e.preventDefault(); this.zoomBy(e.deltaY > 0 ? 1 / 1.1 : 1.1); }, {passive: false});
    }

    pick(e) {
      const r = this.canvas.getBoundingClientRect();
      const ndc = new THREE.Vector2((e.clientX - r.left) / r.width * 2 - 1, -(e.clientY - r.top) / r.height * 2 + 1);
      const ray = new THREE.Raycaster(); ray.setFromCamera(ndc, this.camera);
      const hit = ray.intersectObjects(this.city.children, true)[0];
      return hit ? hit.object.userData.pick : null;
    }

    hover(e) {
      const now = performance.now();
      if (now - (this.lastHover || 0) < 80) return;
      this.lastHover = now;
      this.canvas.classList.toggle('hover', !!this.pick(e));
    }

    resize() {
      const w = this.host.clientWidth, h = this.host.clientHeight;
      if (!w || !h) return;
      this.renderer.setSize(w, h, false);
      this.camera.aspect = w / h;
      /* The panels cover the edges of the screen. The plate is centred in what is
         left between them rather than behind a column. */
      const f = this.frame;
      this.camera.setViewOffset(w, h, -(f.left - f.right) / 2, -(f.top - f.bottom) / 2, w, h);
      this.camera.updateProjectionMatrix();
      const fw = Math.max(1, w - f.left - f.right), fh = Math.max(1, h - f.top - f.bottom);
      this.home.R = 160 * Math.max(1, 1.45 / (fw / fh)) * Math.min(1.6, Math.max(1, 560 / fh));
      /* until the reader takes the camera, it follows the frame */
      if (!this.moved) this.view.R = this.home.R;
    }

    /* ========================================================= per frame */
    frameTick() {
      const raw = Math.min(this.clock.getDelta(), .05);
      if (document.hidden) return;
      const k = 1 - Math.pow(.02, raw);
      const dt = this.paused ? 0 : raw * this.tempo * (this.reduced ? .4 : 1);
      this.time += dt;
      const time = this.time;

      /* camera */
      const v = this.view;
      this.camera.position.set(
        v.target.x + v.R * Math.sin(v.phi) * Math.sin(v.theta),
        v.target.y + v.R * Math.cos(v.phi),
        v.target.z + v.R * Math.sin(v.phi) * Math.cos(v.theta));
      this.camera.lookAt(v.target);

      /* sentiment sets the weather */
      this.mood += (this.moodTarget - this.mood) * k * .5;
      const m = this.mood, fear = THREE.MathUtils.clamp((45 - m) / 25, 0, 1), greed = THREE.MathUtils.clamp((m - 60) / 25, 0, 1);
      const sky = mix('#dfe6ef', '#b5bcc7', fear).lerp(C('#e8eef6'), greed * .5);
      this.scene.background.lerp(sky, k); this.scene.fog.color.copy(this.scene.background);
      this.sun.color.lerp(mix('#ffffff', '#dfe5ee', fear).lerp(C('#ffe7c2'), greed), k);
      this.sun.intensity += ((2.6 - 1.5 * fear + .3 * greed) - this.sun.intensity) * k;
      this.hemi.intensity += ((1.25 - .3 * fear) - this.hemi.intensity) * k;
      const wet = THREE.MathUtils.clamp((30 - m) / 12, 0, 1);
      this.rain.material.opacity += (wet * .6 - this.rain.material.opacity) * k;
      if (this.rain.material.opacity > .01) {
        const p = this.rain.geometry.attributes.position;
        for (let i = 0; i < p.count; i++) { let y = p.getY(i) - raw * 38; if (y < 0) y += 45; p.setY(i, y); }
        p.needsUpdate = true;
      }
      if (this.trees) this.trees.forEach(t => { t.g.rotation.z = Math.sin(this.time * 1.3 + t.ph) * (.03 + fear * .08); });

      /* buildings grow towards their new height rather than jumping */
      this.blocks.forEach(g => {
        const u = g.userData;
        if (!u.cur || !u.target || u.fixed) return;
        const dz = u.target.z0 - u.cur.z0, dt2 = u.target.top - u.cur.top;
        if (Math.abs(dz) + Math.abs(dt2) < .002) return;
        u.cur.z0 += dz * k * 1.5; u.cur.top += dt2 * k * 1.5;
        this.shape(g, u.b, u.cur.z0, u.cur.top);
      });

      /* order flow along the routes */
      Object.values(this.routes).forEach(R => {
        R.strip.parts.forEach(p => { p.t.offset.x -= dt * (.5 + (R.flow || 4) * .04); });
        const keep = [];
        R.walkers.forEach((w, i) => {
          const done = this.walk(w, R.P, R.side, dt, () => {
            /* the share of buyers among this group's orders decides the crates */
            const n = R.walkers.length, buy = R.buy === null || R.buy === undefined ? .5 : R.buy;
            w.buy = i < Math.round(n * buy);
          });
          if (done && w.retire) this.drop(w); else keep.push(w);
        });
        R.walkers = keep;
        R.trucks.forEach((t, i) => this.drive(t, R.P, R.side, dt, raw, i));
      });
      if (this.policy) this.policy.parts.forEach(p => { p.t.offset.x -= dt * .5; });
      this.switchers.forEach(w => this.walk(w, w.P, 0, dt, null, true));

      /* the issuer smokes while it sells stock */
      this.smoke(dt);

      /* margin call */
      const blink = (Math.sin(time * (this.alarm ? 12 : 3)) + 1) / 2;
      if (this.beacon) this.beacon.material.color.copy(this.alarm ? (blink > .5 ? C('#ff2a1f') : C('#5a0f0b')) : mix('#7a1a14', '#ff4a3a', blink * .5));
      if (this.ring) {
        this.ring.material.opacity += ((this.alarm ? .35 + blink * .5 : 0) - this.ring.material.opacity) * k * 2;
        this.ring.scale.setScalar(1 + (this.alarm ? (time * .8 % 1) * .35 : 0));
      }

      /* the pin over the selection */
      const a = this.anchor(this.selected);
      this.pin.visible = !!a;
      if (a) { this.pin.position.set(a.x, a.y + .2 + Math.sin(this.time * 3) * .25, a.z); this.pin.rotation.y = this.time * 1.4; }

      this.renderer.render(this.scene, this.camera);
      this.overlay(raw);
    }

    /* One step of a walk. Returns true when the walker is back at its door. */
    walk(w, P, side, dt, onTurn, oneWay) {
      let home = false;
      if (w.wait > 0) { w.wait -= dt; }
      else {
        w.d += w.dir * 1.8 * dt;
        if (w.d >= P.L) {
          if (oneWay) { w.d = 0; }
          else { w.d = P.L; w.dir = -1; w.wait = .6 + Math.random() * .6; }
        } else if (w.d <= 0) {
          w.d = 0; w.dir = 1; w.wait = .4 + Math.random() * 1.4; home = true;
          if (onTurn) onTurn();
        }
      }
      const q = along(P, w.d), off = side + w.jitter * .5 + (w.dir > 0 ? -.25 : .25);
      w.g.position.set(q.x - q.dz * off, .12, q.z + q.dx * off);
      w.g.rotation.y = Math.atan2(q.dx * w.dir, q.dz * w.dir);
      const moving = w.wait <= 0 && dt > 0;
      w.body.position.y = .48 + (moving ? Math.abs(Math.sin(this.time * 9 + w.ph)) * .08 : 0);
      w.g.rotation.z = moving ? Math.sin(this.time * 9 + w.ph) * .06 : 0;
      if (!oneWay) {
        w.crate.visible = w.dir > 0;
        const c = w.buy ? BUY : SELL;
        if (w.crateColour !== c) { w.crate.material.color.set(c); w.crate.material.emissive.set(c); w.crateColour = c; }
      }
      return home;
    }

    /* A truck waits parked at its depot until its group trades, then drives the route
       with its cargo, unloads at the square and drives back empty. */
    drive(t, P, side, dt, raw, i) {
      /* parked trucks queue on the road in front of the door, one behind the other */
      const home = i * 3.6;
      if (!t.trip) { t.d = home; t.dir = 1; }
      else if (t.wait > 0) t.wait -= dt;
      else {
        t.d += t.dir * 4.2 * dt;
        if (t.d >= P.L) { t.d = P.L; t.dir = -1; t.wait = 1.2; }
        else if (t.dir < 0 && t.d <= home) { t.d = home; t.dir = 1; t.trip = false; }
      }
      const q = along(P, t.d);
      const lane = side + (t.dir > 0 ? .55 : -.55);
      t.g.position.set(q.x - q.dz * lane, .12, q.z + q.dx * lane);
      const ry = Math.atan2(q.dx * t.dir, q.dz * t.dir);
      let dr = ry - t.g.rotation.y; dr = Math.atan2(Math.sin(dr), Math.cos(dr));
      t.g.rotation.y += dr * Math.min(1, raw * 8);
      t.cargo.forEach(c => { c.visible = t.dir > 0; });
    }

    smoke(dt) {
      if (!this.chimneys) return;
      if (!this.puffs) {
        this.puffs = [];
        for (let i = 0; i < 18; i++) {
          const m = new THREE.Mesh(new THREE.IcosahedronGeometry(.5, 0), mat('#ebe8f0', {transparent: true, opacity: 0, depthWrite: false}));
          this.movers.add(m); this.puffs.push({m, life: i / 18 * 4, src: i % 2});
        }
      }
      for (const s of this.puffs) {
        s.life += dt * .9;
        if (s.life > 4) s.life = 0;
        const src = this.chimneys[s.src], u = s.life / 4;
        s.m.position.set(src.x + u * 2.5, src.y + u * 5, src.z - u * 1.2);
        s.m.scale.setScalar(.5 + u * 1.6);
        const target = this.issuing ? (1 - u) * .75 : 0;
        s.m.material.opacity += (target - s.m.material.opacity) * .1;
      }
    }

    /* ---------------------------------------------- HTML over the scene */
    /* Labels stay HTML so the text is sharp and selectable; here they are only
       positioned. Overlaps are pushed apart vertically, the lower one down, the way
       the flat town decluttered its labels. */
    overlay(raw) {
      const W = this.canvas.clientWidth, H = this.canvas.clientHeight, v = new THREE.Vector3();
      const tags = this.hooks.tagLayer ? [...this.hooks.tagLayer.querySelectorAll('[data-key]')] : [];
      const boxes = [];
      for (const el of tags) {
        const a = this.anchor(el.dataset.key);
        if (!a) { el.style.display = 'none'; continue; }
        /* labels stand above the pin, so the selection stays visible under its name */
        v.copy(a).setY(a.y + 3.1).project(this.camera);
        if (v.z > 1) { el.style.display = 'none'; continue; }
        el.style.display = '';
        if (!el._size || el._sig !== el.innerHTML) { el._sig = el.innerHTML; el._size = [el.offsetWidth, el.offsetHeight]; }
        const x = (v.x * .5 + .5) * W, y = (-v.y * .5 + .5) * H;
        boxes.push({el, x, y, w: el._size[0], h: el._size[1], dy: 0});
      }
      boxes.sort((a, b) => a.y - b.y);
      for (let pass = 0; pass < 4; pass++) {
        for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
          const a = boxes[i], b = boxes[j];
          if (Math.abs(a.x - b.x) * 2 >= a.w + b.w) continue;
          const overlap = (a.y + a.dy) - ((b.y + b.dy) - b.h) + 2;
          if (overlap > 0) b.dy += overlap;
        }
      }
      for (const b of boxes) b.el.style.transform = `translate(${b.x.toFixed(1)}px, ${(b.y + b.dy).toFixed(1)}px) translate(-50%, -100%)`;

      for (const p of this.pips) {
        if (p.life <= 0) { p.el.style.opacity = 0; continue; }
        p.life -= raw; p.pos.y += raw * 1.6;
        v.copy(p.pos).project(this.camera);
        p.el.style.opacity = Math.min(1, p.life);
        p.el.style.transform = `translate(${((v.x * .5 + .5) * W).toFixed(1)}px, ${((-v.y * .5 + .5) * H).toFixed(1)}px) translate(-50%, -50%)`;
      }
      const mc = this.hooks.alarmTag;
      if (mc) {
        mc.style.display = this.alarm ? 'block' : 'none';
        const a = this.alarm && this.anchor('lev');
        if (a) {
          v.copy(a).setY(a.y + 6.5).project(this.camera);
          mc.style.transform = `translate(${((v.x * .5 + .5) * W).toFixed(1)}px, ${((-v.y * .5 + .5) * H).toFixed(1)}px) translate(-50%, -100%)`;
        }
      }
    }
  }

  /* The page asks for a town; without WebGL it gets null and says so itself. */
  window.MarketTown3D = {
    create(host, hooks) {
      if (!THREE) return null;
      try {
        const probe = document.createElement('canvas');
        if (!(probe.getContext('webgl2') || probe.getContext('webgl'))) return null;
        return new Town(host, hooks);
      } catch (err) {
        console.error('MarketTown3D', err);
        return null;
      }
    },
  };
})();
