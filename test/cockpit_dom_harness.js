/* test/cockpit_dom_harness.js — run the cockpit's inline JS against a STRICT DOM.
 *
 * WHY STRICT. The first harness written for this (COMMAND 28's diagnosis) returned
 * a usable element for EVERY selector, so it could not reproduce the one failure
 * that matters in a browser: document.querySelector() returning null for markup
 * that is not there. A permissive stub proves the script parses; only a strict one
 * proves it RUNS.
 *
 * So: querySelector('#x') returns an element only while `x` actually exists —
 * initially the ids in the static markup, and afterwards whatever an innerHTML
 * assignment has put on the page. Everything else is null, exactly as a browser
 * would hand it back.
 *
 * usage:  node cockpit_dom_harness.js <inline.js> <cockpit.html> <script.js>
 *
 * <script.js> is the probe: it runs INSIDE the sandbox after the cockpit's own
 * script has executed, and whatever it assigns to `RESULT` is printed as JSON on
 * the last line. Everything the probe needs is in scope — the cockpit's functions
 * and the recording DOM below.
 */
'use strict';
const fs = require('fs');
const vm = require('vm');

const inlinePath = process.argv[2];
const htmlPath = process.argv[3];
const probePath = process.argv[4];

const src = fs.readFileSync(inlinePath, 'utf8');
const html = fs.readFileSync(htmlPath, 'utf8');
const probe = probePath ? fs.readFileSync(probePath, 'utf8') : '';

/* ids present before any script runs: the static markup only */
const live = new Set();
const idRe = /\bid\s*=\s*["']([^"'{}$]+)["']/g;
let m;
const staticPart = html.slice(0, html.indexOf('<script>'));
while ((m = idRe.exec(staticPart))) live.add(m[1]);

/* what the page did, for a test to assert on */
const LOG = {
  fetches: [],          // every URL the page asked for, in order
  scrolled: [],         // every scrollIntoView target
  focused: [],          // every focus() target
  sockets: [],          // every WebSocket url opened
  socketSends: [],      // every ws.send payload
  confirms: [],         // every confirm() prompt
  stored: {},           // localStorage
};

/* Ids AND the attributes a browser would have parsed with them. `value` matters:
 * the server injects the terminal token straight into the markup, so in a real
 * browser #tok has its value the instant the tab renders. A harness that dropped
 * it forced every probe to fake a token the page already had. */
function registerIds(h) {
  const s = String(h);
  let x;
  const tag = /<[a-zA-Z]+[^>]*\bid\s*=\s*["']([^"']+)["'][^>]*>/g;
  while ((x = tag.exec(s))) {
    const id = x[1];
    live.add(id);
    const v = /\bvalue\s*=\s*"([^"]*)"/.exec(x[0]);
    if (v) elFor(id).value = v[1];
  }
  /* ids on tags the pattern above missed (attribute order, quoting) */
  const bare = /\bid\s*=\s*["']([^"']+)["']/g;
  while ((x = bare.exec(s))) live.add(x[1]);
}

/* Elements created for a given id/selector. Not a real DOM tree: a recorder with
 * the handful of surfaces the cockpit actually touches. */
function makeEl(name) {
  const el = {
    _name: name,
    dataset: {}, style: {}, children: [], firstChild: null,
    textContent: '', value: '', className: '', disabled: false, checked: false,
    onclick: null, oninput: null, onkeydown: null, onchange: null,
    classList: {
      _s: new Set(),
      add(c) { this._s.add(c); }, remove(c) { this._s.delete(c); },
      toggle(c, on) { on === undefined ? (this._s.has(c) ? this._s.delete(c) : this._s.add(c)) : (on ? this._s.add(c) : this._s.delete(c)); },
      contains(c) { return this._s.has(c); },
    },
    appendChild() {}, removeChild() {}, setAttribute() {}, getAttribute() { return null; },
    addEventListener() {}, removeEventListener() {},
    focus() { LOG.focused.push(name); },
    click() { if (typeof el.onclick === 'function') el.onclick({ preventDefault() {}, stopPropagation() {} }); },
    scrollIntoView() { LOG.scrolled.push(name); },
    getBoundingClientRect() { return { width: 900, height: 700, top: 0, left: 0 }; },
    querySelector(s) { return doc.querySelector(s); },
    querySelectorAll(s) { return doc.querySelectorAll(s); },
    closest() { return null; },
  };
  let h = '';
  Object.defineProperty(el, 'innerHTML', {
    get: () => h,
    set: (v) => { h = String(v); registerIds(v); },
  });
  return el;
}

/* Elements minted per id are CACHED, so a test can set a handler through one
 * lookup and fire it through another — which is what the page itself does. */
const cache = new Map();
function elFor(id) {
  if (!cache.has(id)) cache.set(id, makeEl('#' + id));
  return cache.get(id);
}

/* class/tag selectors resolve against the HTML currently on the page, so
 * querySelectorAll('.tab') finds what drawTabs() just wrote. */
/* The page as it stands: the STATIC markup the server sent, plus everything an
 * innerHTML assignment has written since. Omitting the static half made the
 * whole control bar invisible to querySelectorAll — the footer's buttons are
 * markup, not something a renderer produced — so a handler attached to them
 * looked like a button that was never there. */
function currentHTML() {
  let out = staticPart;
  for (const el of cache.values()) out += el.innerHTML || '';
  return out;
}

/* STABLE ACROSS QUERIES, and that is the whole point. wirePanel() attaches its
 * handler through one querySelectorAll('.jump'); a test then reads the handler
 * through another. Minting a fresh object per query made every element look
 * unwired — the harness reporting its own amnesia as a defect in the page.
 *
 * Keyed by the matched tag text, so identical markup returns the identical
 * object and a RE-RENDER (different markup) correctly returns a new one. */
const classCache = new Map();

function matchesClass(cls) {
  const found = [];
  const re = new RegExp('<([a-zA-Z]+)([^>]*\\bclass\\s*=\\s*"[^"]*\\b' + cls + '\\b[^"]*"[^>]*)>', 'g');
  let x;
  const h = currentHTML();
  let n = 0;
  while ((x = re.exec(h))) {
    const attrs = x[2];
    const key = cls + '||' + n++ + '||' + x[0];
    let e = classCache.get(key);
    if (!e) {
      e = makeEl('.' + cls);
      const d = /\bdata-([\w-]+)\s*=\s*"([^"]*)"/g;
      let a;
      while ((a = d.exec(attrs))) {
        const k = a[1].replace(/-([a-z])/g, (_, c) => c.toUpperCase());
        e.dataset[k] = a[2];
      }
      const idm = /\bid\s*=\s*"([^"]*)"/.exec(attrs);
      if (idm) { cache.set(idm[1], e); e._name = '#' + idm[1]; }
      classCache.set(key, e);
    }
    found.push(e);
  }
  return found;
}

const doc = {
  querySelector(s) {
    if (typeof s === 'string' && s[0] === '#') {
      const id = s.slice(1);
      return live.has(id) ? elFor(id) : null;
    }
    if (typeof s === 'string' && s[0] === '.') {
      const all = matchesClass(s.slice(1));
      return all.length ? all[0] : null;
    }
    return null;
  },
  querySelectorAll(s) {
    if (typeof s === 'string' && s[0] === '.') return matchesClass(s.slice(1));
    if (typeof s === 'string' && s.startsWith('[data-')) {
      const key = s.slice(6, s.indexOf(']'));
      const camel = key.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
      const out = [];
      for (const cls of ['tab', 'cmd', 'pf', 'spd', 'fbtn', 'tabbtn', 'sw', 'jump', 'prow', 'degchip']) {
        for (const e of matchesClass(cls)) if (e.dataset[camel] !== undefined) out.push(e);
      }
      return out;
    }
    return [];
  },
  createElement(t) { return makeEl(t); },
  getElementById(i) { return live.has(i) ? elFor(i) : null; },
  addEventListener() {},
  body: makeEl('body'),
  documentElement: makeEl('html'),
};

const sandbox = {
  document: doc, console, LOG,
  JSON, Math, Date, Object, Array, String, Number, Boolean, Promise, Error,
  RegExp, Map, Set, encodeURIComponent, decodeURIComponent, isNaN, parseInt,
  parseFloat, Intl,
  localStorage: {
    getItem: (k) => (k in LOG.stored ? LOG.stored[k] : null),
    setItem: (k, v) => { LOG.stored[k] = String(v); },
    removeItem: (k) => { delete LOG.stored[k]; },
  },
  window: {
    addEventListener() {},
    location: { host: '127.0.0.1:5055', protocol: 'http:' },
    matchMedia: () => ({ matches: false, addEventListener() {} }),
    scrollTo() {}, scrollY: 0,
  },
  location: { host: '127.0.0.1:5055', protocol: 'http:' },
  navigator: { userAgent: 'node', clipboard: { writeText: () => Promise.resolve() } },
  confirm: (msg) => { LOG.confirms.push(String(msg)); return true; },
  setInterval: () => 0, clearInterval() {}, clearTimeout() {},
  /* REAL TIMERS, not an immediate stub. The page schedules genuinely ordered
   * work — prefill() waits 120ms for the tab to mount, the socket reports
   * onopen on a later turn — and a setTimeout that fired synchronously ran the
   * callback BEFORE the thing it was waiting for existed. A probe that needs a
   * timer to have fired awaits settle(). */
  setTimeout: (f, ms) => setTimeout(f, Math.min(Number(ms) || 0, 400)),
  settle: (ms) => new Promise((r) => setTimeout(r, Number(ms) || 250)),
  requestAnimationFrame: () => 0,
  fetch: (u, o) => {
    LOG.fetches.push({ url: String(u), method: (o && o.method) || 'GET',
                       body: o && o.body ? String(o.body) : null });
    return Promise.resolve({
      ok: true,
      json: () => Promise.resolve(FIXTURES[String(u).split('?')[0]] || {}),
      text: () => Promise.resolve(''),
    });
  },
  WebSocket: function (url) {
    LOG.sockets.push(String(url));
    this.readyState = 1;
    this.send = (d) => LOG.socketSends.push(String(d));
    this.close = () => {};
    setTimeout(() => { if (typeof this.onopen === 'function') this.onopen(); }, 0);
  },
  Terminal: function () {
    this.cols = 80; this.rows = 24;
    this.open = () => {}; this.write = () => {}; this.onData = () => {};
    this.loadAddon = () => {}; this.dispose = () => {};
    this.focus = () => LOG.focused.push('xterm');
  },
  FitAddon: { FitAddon: function () { this.fit = () => {}; } },
};
sandbox.globalThis = sandbox;

/* FIXTURES is injected by the probe before the page runs, so a test decides what
 * every endpoint returns. */
const FIXTURES = {};
sandbox.FIXTURES = FIXTURES;

vm.createContext(sandbox);

const rejections = [];
process.on('unhandledRejection', (e) => rejections.push(String((e && e.message) || e)));

let threw = null;
try {
  /* the probe runs FIRST if it declares fixtures, then the page, then the probe's
   * assertions — signalled by splitting on the marker below. */
  const parts = probe.split('/*---RUN---*/');
  if (parts.length === 2) vm.runInContext(parts[0], sandbox, { filename: 'probe-setup.js' });
  vm.runInContext(src, sandbox, { filename: 'cockpit-inline.js' });
  const after = parts.length === 2 ? parts[1] : probe;
  if (after.trim()) vm.runInContext(after, sandbox, { filename: 'probe.js' });
} catch (e) {
  threw = { name: e.name, message: e.message, stack: String(e.stack || '').split('\n').slice(0, 6) };
}

setTimeout(() => {
  /* render() is async. A probe that reads #view straight after the page script
   * reads it EMPTY, so a probe may instead define FINALIZE() and be called here,
   * once the page's promises have settled. */
  if (typeof sandbox.FINALIZE === 'function' && !threw) {
    try {
      const v = sandbox.FINALIZE();
      if (v && typeof v.then === 'function') {
        /* an async FINALIZE, so a probe can `await switchTo(...)` and read the
         * tab it actually asked for rather than the one still on screen */
        v.then((r) => { sandbox.RESULT = r; emit(); },
               (e) => { threw = { name: 'FINALIZE', stack: [],
                                  message: String((e && e.message) || e) }; emit(); });
        return;
      }
      sandbox.RESULT = v;
    } catch (e) { threw = { name: e.name, message: 'FINALIZE: ' + e.message, stack: [] }; }
  }
  emit();
}, 60);

function emit() {
  const out = {
    threw,
    rejections,
    log: LOG,
    result: sandbox.RESULT === undefined ? null : sandbox.RESULT,
  };
  process.stdout.write('\n---HARNESS-JSON---\n' + JSON.stringify(out) + '\n');
  process.exit(0);
}
