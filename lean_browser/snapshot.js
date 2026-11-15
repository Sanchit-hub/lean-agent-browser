// Lean snapshot walker. Injected with page.evaluate(SRC, opts). Returns structured JSON that
// lean_browser/snapshot.py renders to compact text.
//
// Performance rules (Obscura's getComputedStyle is slow): one DOM walk using only tag/attribute
// checks; computed style is read lazily, only for elements we emit and their ancestors, cached.
//
// IDs: every emitted element gets data-lab-id. IDs live as long as the node. A node re-created by
// a framework re-render takes over the old ID when its fingerprint (role, name, landmark,
// occurrence index) matches an old node that is no longer connected. IDs are never handed to a
// different logical element within one document.
(opts) => {
  opts = opts || {};
  const T0 = performance.now();
  const MODE = opts.mode || 'actions';
  const W = window;
  if (!W.__lab) {
    W.__lab = { next: 1, byId: new Map(), fp: new Map(), docId: Math.random().toString(36).slice(2, 10), path: null };
  }
  const S = W.__lab;
  const path = location.pathname + location.search + location.hash;
  const routeChanged = S.path !== null && S.path !== path;
  S.path = path;

  const SKIP = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE', 'HEAD', 'META', 'LINK', 'svg', 'SVG', 'PATH', 'BR', 'HR', 'OPTION', 'OPTGROUP', 'DATALIST']);
  const REGION_TAG = { NAV: 'nav', HEADER: 'header', FOOTER: 'footer', ASIDE: 'aside' };
  const REGION_ROLE = { navigation: 'nav', banner: 'header', contentinfo: 'footer', complementary: 'aside' };
  const INTERACTIVE_ROLES = new Set(['button', 'link', 'checkbox', 'radio', 'switch', 'tab', 'menuitem', 'menuitemcheckbox',
    'menuitemradio', 'option', 'combobox', 'textbox', 'searchbox', 'slider', 'spinbutton', 'listbox', 'treeitem']);
  const TEXT_ROLES = new Set(['alert', 'status', 'log', 'alertdialog']);

  // ---------- visibility (lazy, cached) ----------
  const vcache = new Map();
  const getWin = el => (el.ownerDocument && el.ownerDocument.defaultView) || W;
  function hiddenSelf(el) {
    if (el.hidden || el.getAttribute('aria-hidden') === 'true') return true;
    const cs = getWin(el).getComputedStyle(el);
    return cs.display === 'none' || cs.visibility === 'hidden' || cs.visibility === 'collapse' || cs.opacity === '0'
      || cs.contentVisibility === 'hidden';
  }
  function parentOf(el) {
    if (el.parentElement) return el.parentElement;
    const r = el.getRootNode && el.getRootNode();
    if (r && r.host) return r.host;
    const fe = el.ownerDocument && el.ownerDocument.defaultView && el.ownerDocument.defaultView.frameElement;
    return fe || null;
  }
  // Native checkVisibility() covers display/visibility/opacity/content-visibility for the element and its
  // ancestors (through shadow roots). On Obscura it is ~1000x faster than reading several computed-style
  // properties (2 ms vs 2.2 s on a GitHub page), so it is the fast path; the manual walk is the fallback.
  const HAS_CV = typeof Element.prototype.checkVisibility === 'function';
  function visibleSlow(el) {
    if (!el || el.nodeType !== 1) return true;
    if (vcache.has(el)) return vcache.get(el);
    let v;
    if (el.tagName === 'BODY' || el.tagName === 'HTML') v = !hiddenSelf(el);
    else v = !hiddenSelf(el) && visibleSlow(parentOf(el));
    vcache.set(el, v);
    return v;
  }
  function visible(el) {
    if (!el || el.nodeType !== 1) return true;
    if (!HAS_CV) return visibleSlow(el);
    if (vcache.has(el)) return vcache.get(el);
    let v = el.checkVisibility({ opacityProperty: true, visibilityProperty: true, contentVisibilityAuto: true })
      && !el.closest('[hidden],[aria-hidden=true]');
    if (v && el.ownerDocument !== document) {  // inside an iframe: the frame element must be visible too
      const fe = el.ownerDocument.defaultView && el.ownerDocument.defaultView.frameElement;
      if (fe) v = visible(fe);
    }
    vcache.set(el, v);
    return v;
  }
  function onScreenSized(el) {
    let r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) {
      // Obscura reports 0x0 for an inline element that only wraps a replaced child (e.g. <a><svg>)
      const c = el.firstElementChild;
      if (!c) return false;
      r = c.getBoundingClientRect();
      if (r.width === 0 && r.height === 0) return false;
    }
    if (r.right < 0 || r.bottom < -100) return false;   // pushed off to the left/top (e.g. left:-9999px)
    return true;
  }
  function tinyText(el) {
    const cs = getWin(el).getComputedStyle(el);
    return parseFloat(cs.fontSize) < 4;
  }

  // ---------- names ----------
  const clip = (s, n) => { s = (s || '').replace(/\s+/g, ' ').trim(); return s.length > n ? s.slice(0, n - 1) + '…' : s; };
  function textExcluding(root, skip) {
    let out = '';
    const walk = n => {
      for (const c of n.childNodes) {
        if (c === skip) continue;
        if (c.nodeType === 3) out += c.nodeValue;
        else if (c.nodeType === 1 && !['SELECT', 'INPUT', 'TEXTAREA', 'SCRIPT', 'STYLE', 'BUTTON'].includes(c.tagName)) walk(c);
      }
    };
    walk(root);
    return out;
  }
  function byIdIn(el, id) {
    const root = el.getRootNode();
    return (root.getElementById ? root.getElementById(id) : null) || el.ownerDocument.getElementById(id);
  }
  function accName(el) {
    const lb = el.getAttribute('aria-labelledby');
    if (lb) {
      const t = lb.split(/\s+/).map(i => byIdIn(el, i)).filter(Boolean).map(x => x.innerText || x.textContent).join(' ');
      if (t.trim()) return clip(t, 60);
    }
    const al = el.getAttribute('aria-label');
    if (al && al.trim()) return clip(al, 60);
    const tag = el.tagName;
    if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') {
      if (el.id) {
        const root = el.getRootNode();
        const l = root.querySelector && root.querySelector(`label[for="${CSS.escape(el.id)}"]`);
        if (l) return clip(textExcluding(l, el), 60);
      }
      const wrap = el.closest('label');
      if (wrap) { const t = textExcluding(wrap, el); if (t.trim()) return clip(t, 60); }
      if (el.getAttribute('placeholder')) return clip(el.getAttribute('placeholder'), 60);
      if (el.getAttribute('title')) return clip(el.getAttribute('title'), 60);
      if (tag === 'INPUT' && ['submit', 'button', 'reset'].includes(el.type)) return clip(el.value || el.type, 60);
      return clip(el.getAttribute('name') || '', 60);  // last resort: the form field name (e.g. "q")
    }
    // Text-only elements (no child elements) can't hide text inside them, so textContent is safe and
    // far cheaper than innerText on Obscura (innerText costs ~0.17 ms per element there).
    let t = el.children.length === 0 ? el.textContent : el.innerText;
    if (t && t.trim()) return clip(t, 60);
    const img = el.querySelector && el.querySelector('img[alt]');
    const alt = img ? (img.getAttribute('alt') || '') : '';
    if (alt.trim()) return clip(alt, 60);
    const st = el.querySelector && el.querySelector('svg title, [aria-label]');
    if (st) { const s = st.getAttribute('aria-label') || st.textContent; if (s && s.trim()) return clip(s, 60); }
    const ti = el.getAttribute('title');
    if (ti) return clip(ti, 60);
    if (el.value && typeof el.value === 'string') return clip(el.value, 60);
    return '';
  }

  // ---------- roles ----------
  function roleOf(el) {
    const r = el.getAttribute('role');
    if (r && INTERACTIVE_ROLES.has(r)) return r;
    const tag = el.tagName;
    if (tag === 'A') return el.hasAttribute('href') ? 'link' : null;
    if (tag === 'BUTTON') return 'button';
    if (tag === 'SELECT') return 'select';
    if (tag === 'TEXTAREA') return 'textbox';
    if (tag === 'SUMMARY') return 'button';
    if (tag === 'INPUT') {
      const ty = (el.getAttribute('type') || 'text').toLowerCase();
      if (ty === 'hidden') return null;
      if (ty === 'checkbox' || ty === 'radio') return ty;
      if (['submit', 'button', 'reset', 'image'].includes(ty)) return 'button';
      if (ty === 'file') return 'upload';
      if (ty === 'range') return 'slider';
      return 'textbox';
    }
    if (el.isContentEditable && el.getAttribute('contenteditable') !== null && el.getAttribute('contenteditable') !== 'false') return 'editor';
    if (el.hasAttribute('onclick')) return 'clickable';
    if (el.getAttribute('tabindex') !== null && +el.getAttribute('tabindex') >= 0 && el.tagName !== 'DIV' && el.tagName !== 'SPAN') return 'clickable';
    return null;
  }

  // ---------- IDs ----------
  const fpCount = new Map();
  const PENDING = [];
  const flushIds = () => { for (const [el, id] of PENDING) el.dataset.labId = id; PENDING.length = 0; };
  function landmark(el) {
    const l = el.closest('main,nav,header,footer,aside,form,dialog,[role=dialog],[role=main],[role=navigation]');
    return l ? (l.tagName + (l.id ? '#' + l.id : '')) : '-';
  }
  function assignId(el, role, name) {
    const base = role + '|' + name + '|' + landmark(el);
    const k = (fpCount.get(base) || 0) + 1;
    fpCount.set(base, k);
    const fp = base + '|' + k;
    let id = el.dataset ? el.dataset.labId : undefined;
    if (id) {
      const ref = S.byId.get(+id);
      if (!(ref && ref.deref() === el)) id = undefined;  // copied attribute (cloneNode) - not ours
    }
    if (!id && S.fp.has(fp)) {
      const old = S.fp.get(fp);
      const ref = S.byId.get(old);
      const node = ref && ref.deref();
      if (!node || !node.isConnected) id = String(old);
    }
    if (!id) id = String(S.next++);
    // Writing the attribute is a DOM mutation; on Obscura each one invalidates style for the whole
    // document, so the next getComputedStyle/innerText recomputes everything. Defer all writes.
    if (!el.dataset || el.dataset.labId !== id) PENDING.push([el, id]);
    S.byId.set(+id, new WeakRef(el));
    S.fp.set(fp, +id);
    return +id;
  }

  // ---------- element entry ----------
  const consumed = new Set();
  function errorFor(el) {
    const db = el.getAttribute('aria-describedby');
    if (db) {
      for (const i of db.split(/\s+/)) {
        const e = byIdIn(el, i);
        if (e && visible(e) && (e.innerText || '').trim()) { consumed.add(e); return clip(e.innerText, 60); }
      }
    }
    const lab = el.closest('label') || el;
    let n = lab.nextElementSibling;
    if (n && (n.getAttribute('role') === 'alert' || /\b(err|error|invalid)\b/i.test(n.className || ''))) {
      if ((n.innerText || '').trim() && visible(n)) { consumed.add(n); return clip(n.innerText, 60); }
    }
    return '';
  }
  const radioDone = new Set();
  function elEntry(el, role, frame) {
    const e = { t: 'el', role };
    if (role === 'radio') {
      const g = el.name;
      const scope = el.form || el.getRootNode();
      const opts = g ? [...scope.querySelectorAll(`input[type=radio][name="${CSS.escape(g)}"]`)] : [el];
      const key = g ? (g + '@' + (el.form ? 'f' : 'r')) : null;
      if (key && radioDone.has(key)) return null;
      if (key) radioDone.add(key);
      const fs = el.closest('fieldset');
      const lg = fs && fs.querySelector('legend');
      e.role = 'radiogroup';
      e.name = clip(lg ? lg.innerText : (g || accName(el)), 50);
      e.options = opts.map(o => ({ id: assignId(o, 'radio', accName(o)), label: clip(accName(o), 30), checked: o.checked }));
      e.id = e.options[0].id;
      const sel = opts.find(o => o.checked);
      if (sel) e.val = clip(accName(sel), 30);
      if (opts.some(o => o.required || o.hasAttribute('required'))) e.req = true;
      if (frame) e.frame = frame;
      return e;
    }
    e.name = accName(el);
    if ((role === 'link' || role === 'button' || role === 'clickable') && !e.name) return null;  // nameless: drop
    e.id = assignId(el, role, e.name);
    // Fingerprint for safe stale-id recovery (not rendered): tells apart controls with the same role+name.
    const fp = {};
    const href = el.getAttribute && el.getAttribute('href');
    if (href) fp.href = href.length > 120 ? href.slice(0, 120) : href;
    const tid = el.getAttribute('data-testid') || el.getAttribute('data-test') || el.getAttribute('data-qa') || el.getAttribute('data-cy');
    if (tid) fp.testid = tid;
    if (el.getAttribute('name')) fp.nm = el.getAttribute('name');
    const form = el.form || (el.closest && el.closest('form'));
    if (form) fp.form = form.id || form.getAttribute('name') || form.getAttribute('action') || 'form';
    const row = el.closest && el.closest('tr,li,[role=row],article');
    if (row) { const rt = (row.textContent || '').replace(/\s+/g, ' ').trim(); if (rt) fp.ctx = rt.slice(0, 60); }
    fp.lm = landmark(el);
    e.fp = fp;
    if (el.required || el.hasAttribute('required') || el.getAttribute('aria-required') === 'true') e.req = true;
    if (el.disabled || el.getAttribute('aria-disabled') === 'true') e.disabled = true;
    const ty = (el.getAttribute && el.getAttribute('type') || '').toLowerCase();
    if (role === 'textbox') {
      if (['email', 'tel', 'number', 'date', 'url', 'search', 'time', 'datetime-local', 'month'].includes(ty)) e.type = ty;
      if (ty === 'password') { e.type = 'password'; if (el.value) e.val = '••••'; }
      else if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') { if (el.value) e.val = clip(el.value, 40); }
      else if (el.isContentEditable) { const v = (el.innerText || "").trim(); if (v) e.val = clip(v, 40); }
      if (el.readOnly) e.readonly = true;
    }
    if (role === 'editor') { e.role = 'textbox'; e.rich = true; const v = (el.innerText || "").trim(); if (v) e.val = clip(v, 40); }
    if (role === 'select') {
      const os = [...el.options];
      e.options = os.slice(0, 12).map(o => clip(o.text, 25));
      if (os.length > 12) e.more = os.length - 12;
      const so = el.selectedIndex >= 0 ? os[el.selectedIndex] : null;
      if (so && so.value !== '') e.val = clip(so.text, 25);
    }
    if (role === 'checkbox' || role === 'switch') e.checked = el.checked !== undefined ? !!el.checked : el.getAttribute('aria-checked') === 'true';
    if (role === 'combobox' && el.tagName !== 'INPUT' && el.tagName !== 'SELECT') {
      e.custom = true;
      const v = (el.innerText || '').trim(); if (v && v !== e.name) e.val = clip(v, 30);
      if (el.getAttribute('aria-expanded')) e.expanded = el.getAttribute('aria-expanded') === 'true';
    }
    if (role === 'option' && el.getAttribute('aria-selected') === 'true') e.selected = true;
    if (role === 'tab' && el.getAttribute('aria-selected') === 'true') e.selected = true;
    if (role === 'upload') { if (el.accept) e.accept = el.accept; if (el.files && el.files.length) e.val = el.files[0].name; }
    if (role === 'textbox' || role === 'select' || role === 'upload' || role === 'checkbox') {
      const err = errorFor(el); if (err) e.err = err;
      if (el.getAttribute('aria-invalid') === 'true' && !e.err) e.err = 'invalid';
    }
    if (frame) e.frame = frame;
    return e;
  }

  // ---------- repeated containers (long lists, tables, feeds) ----------
  function dominantChildren(el) {
    const kids = el.children;
    if (!kids || kids.length <= 8) return null;
    // table rows group by tag only (sites style alternate rows with different classes)
    const key = el.tagName === 'TBODY' || el.tagName === 'TABLE' || el.tagName === 'THEAD'
      ? (k => k.tagName)
      : (k => k.tagName + '.' + (k.className && typeof k.className === 'string' ? k.className.split(/\s+/).sort().join('.') : ''));
    const sig = new Map();
    for (const k of kids) { const s = key(k); sig.set(s, (sig.get(s) || 0) + 1); }
    let best = null, n = 0;
    for (const [s, c] of sig) if (c > n) { best = s; n = c; }
    if (n <= 8) return null;
    return [...kids].filter(k => key(k) === best);
  }
  const INTERACTIVE_SEL = 'a[href],button,input:not([type=hidden]),select,textarea,summary,[contenteditable]:not([contenteditable=false]),[onclick],' +
    [...INTERACTIVE_ROLES].map(r => `[role=${r}]`).join(',');
  function itemEntry(child, frame) {
    let text = (child.innerText || '').replace(/\t/g, ' | ').replace(/\s*\n\s*/g, ' · ');
    const refs = [];
    for (const c of child.querySelectorAll(INTERACTIVE_SEL)) {
      if (!visible(c)) continue;
      const r = roleOf(c); if (!r) continue;
      const e = elEntry(c, r, frame); if (e) refs.push(e);
    }
    if (child.matches && child.matches(INTERACTIVE_SEL)) { const r = roleOf(child); if (r) { const e = elEntry(child, r, frame); if (e) refs.push(e); } }
    return { t: 'item', text: clip(text, 140), refs };
  }
  function groupLabel(el) {
    const al = el.getAttribute('aria-label'); if (al) return clip(al, 40);
    let p = el.tagName === 'TBODY' ? el.closest('table') : el;
    const cap = p && p.querySelector && p.querySelector(':scope > caption'); if (cap) return clip(cap.innerText, 40);
    let prev = p && p.previousElementSibling;
    if (prev && /^H[1-6]$/.test(prev.tagName)) return clip(prev.innerText, 40);
    if (p && p.parentElement) { const h = p.parentElement.querySelector(':scope > h1,:scope > h2,:scope > h3,:scope > h4'); if (h) return clip(h.innerText, 40); }
    return '';
  }

  // ---------- scope (within=id): the form/table/list/section that contains element id ----------
  const CONTAINER_SEL = 'form,table,fieldset,[role=dialog],dialog,article,section,ul,ol,[role=list],[role=grid],nav,aside,main,[role=main]';
  let scopeEl = null, scopeErr = null;
  if (opts.within != null) {
    const ref = S.byId.get(+opts.within);
    const el = ref && ref.deref();
    if (!el || !el.isConnected) scopeErr = `id ${opts.within} not found — call snapshot()`;
    else scopeEl = el.matches(CONTAINER_SEL) ? el : (el.closest(CONTAINER_SEL) || el.parentElement || el);
  }
  if (scopeErr) return { v: 1, error: scopeErr };
  const PROF = {}; let PT = performance.now();
  const mark = k => { const n = performance.now(); PROF[k] = Math.round(n - PT); PT = n; };
  // ---------- dialog / banner ----------
  const DIALOG_SEL = 'dialog[open],[role=dialog],[role=alertdialog],[aria-modal=true]';
  let dialog = null;
  for (const d of document.querySelectorAll(DIALOG_SEL)) if (visible(d) && onScreenSized(d)) dialog = d;
  let banner = null;
  if (!dialog) {
    for (const b of document.querySelectorAll('[id*=cookie i],[class*=cookie i],[id*=consent i],[class*=consent i],[id*=gdpr i]')) {
      if (b.closest('script,style')) continue;
      const btns = [...b.querySelectorAll('button,a[role=button],[role=button]')].filter(x => visible(x));
      if (btns.length && visible(b) && onScreenSized(b)) {
        banner = { label: 'cookies', buttons: btns.map(x => { consumed.add(x); const n = accName(x); return { id: assignId(x, 'button', n), name: clip(n, 24) }; }) };
        break;
      }
    }
  }

  mark('dialog_banner');
  // ---------- read mode: main content as markdown ----------
  if (MODE === 'read') {
    const scope = scopeEl || dialog || document.querySelector('main article,article,main,[role=main]') || document.body;
    const lines = [];
    const inline = el => {
      let s = '';
      for (const c of el.childNodes) {
        if (c.nodeType === 3) s += c.nodeValue;
        else if (c.nodeType === 1) {
          if (SKIP.has(c.tagName) || !visible(c)) continue;
          if (c.tagName === 'A' && c.hasAttribute('href')) { const n = accName(c); if (n) s += `[${n}](#${assignId(c, 'link', n)})`; }
          else if (c.tagName === 'BR') s += '\n';
          else if (c.tagName === 'STRONG' || c.tagName === 'B') s += `**${inline(c).trim()}**`;
          else if (c.tagName === 'CODE') s += '`' + c.textContent + '`';
          else if (c.tagName === 'IMG') { if (c.alt) s += `[image: ${clip(c.alt, 40)}]`; }
          else s += inline(c);
        }
      }
      return s;
    };
    const block = el => {
      for (const n of el.childNodes) {  // bare text directly in a block (e.g. a JSON or plain-text response)
        if (n.nodeType === 3 && n.nodeValue.trim().length > 1) lines.push(clip(n.nodeValue, 3000));
      }
      for (const c of el.children) {
        const tag = c.tagName;
        if (SKIP.has(tag) || c.hidden || c.getAttribute('aria-hidden') === 'true' || !visible(c)) continue;
        if (REGION_TAG[tag] && !(scope.contains(c) && scope !== document.body)) continue;
        if (/^H[1-6]$/.test(tag)) { lines.push('#'.repeat(+tag[1]) + ' ' + clip(c.innerText, 120)); continue; }
        if (tag === 'P' || tag === 'BLOCKQUOTE' || tag === 'FIGCAPTION' || tag === 'DT' || tag === 'DD') {
          if (!onScreenSized(c) || tinyText(c)) continue;
          const t = inline(c).replace(/[ \t]+/g, ' ').trim(); if (t) lines.push((tag === 'BLOCKQUOTE' ? '> ' : '') + t); continue;
        }
        if (tag === 'UL' || tag === 'OL') {
          let i = 1;
          for (const li of c.children) { if (li.tagName !== 'LI' || !visible(li)) continue; const t = inline(li).replace(/\s+/g, ' ').trim(); if (t) lines.push((tag === 'OL' ? `${i++}. ` : '- ') + t); }
          continue;
        }
        if (tag === 'TABLE') {
          const rows = [...c.querySelectorAll('tr')].filter(visible);
          rows.forEach((tr, ri) => {
            lines.push('| ' + [...tr.children].map(td => inline(td).replace(/\s+/g, ' ').trim().replace(/\|/g, '/')).join(' | ') + ' |');
            if (ri === 0) lines.push('|' + [...tr.children].map(() => '---').join('|') + '|');
          });
          continue;
        }
        if (tag === 'PRE') { lines.push('```\n' + clip(c.innerText, 2000) + '\n```'); continue; }
        if (tag === 'IFRAME') { try { if (c.contentDocument && c.contentDocument.body) block(c.contentDocument.body); } catch (e) {} continue; }
        if (c.children.length === 0) { const t = (c.innerText || '').trim(); if (t && onScreenSized(c) && !tinyText(c)) lines.push(clip(t, 400)); continue; }
        block(c);
        if (c.shadowRoot) block(c.shadowRoot);
      }
    };
    block(scope);
    flushIds();
    return { v: 1, mode: 'read', title: clip(document.title, 80), path, origin: location.origin, docId: S.docId,
      routeChanged, markdown: lines.join('\n'), ms: Math.round(performance.now() - T0) };
  }

  // ---------- main walk ----------
  const out = [];
  let groupN = 0;
  const handleFor = kind => (kind[0]) + (++groupN);
  const seenLinks = new Set();
  const mainEl = document.querySelector('main,[role=main]');
  const root = scopeEl || dialog || document.body;
  const FULL = MODE === 'full';

  function walk(node, sink, ctx) {
    const kids = node.children || [];
    for (const el of kids) visit(el, sink, ctx);
    if (node.shadowRoot) for (const el of node.shadowRoot.children) visit(el, sink, ctx);
  }
  function visit(el, sink, ctx) {
    const tag = el.tagName;
    if (SKIP.has(tag) || el.hidden || el.getAttribute('aria-hidden') === 'true') return;
    if (consumed.has(el)) return;
    // regions outside <main> collapse into one line
    const rk = REGION_TAG[tag] || REGION_ROLE[el.getAttribute('role')];
    if (rk && !ctx.inGroup && !(mainEl && mainEl.contains(el)) && !ctx.inDialog) {
      if (!visible(el)) return;
      const g = { t: 'group', kind: rk, handle: handleFor(rk), label: groupLabel(el), items: [] };
      walk(el, g.items, { ...ctx, inGroup: true });
      const n = countEls(g.items);
      if (n) { g.count = n; sink.push(g); }
      return;
    }
    // long repeated lists/tables/feeds collapse into one line
    if (!ctx.inGroup && !FULL) {
      const rep = dominantChildren(el);
      if (rep && visible(el)) {
        const kind = (tag === 'TBODY' || tag === 'TABLE') ? 'table' : 'list';
        const items = rep.filter(c => visible(c)).map(c => itemEntry(c, ctx.frame));
        if (items.length > 8) {
          sink.push({ t: 'group', kind, handle: handleFor(kind), label: groupLabel(el), count: items.length, items });
          // anything else inside this container (non-dominant children) is still walked
          for (const c of el.children) if (!rep.includes(c)) visit(c, sink, ctx);
          return;
        }
      }
    }
    if (tag === 'IFRAME') {
      if (!visible(el)) return;
      let doc = null;
      try { doc = el.contentDocument; } catch (e) { doc = null; }
      const label = clip(el.title || el.name || el.getAttribute('aria-label') || 'frame', 30);
      if (doc && doc.body) walk(doc.body, sink, { ...ctx, frame: label });
      else sink.push({ t: 'txt', text: `iframe "${label}" (cross-origin, not readable)` });
      return;
    }
    if (/^H[1-4]$/.test(tag) && (FULL || +tag[1] <= 3)) {
      if (visible(el) && onScreenSized(el)) { const tx = clip(el.innerText, 80); if (tx) sink.push({ t: 'h', lvl: +tag[1], text: tx }); }
      return;
    }
    const r = roleOf(el);
    if (r) {
      if (visible(el) && (onScreenSized(el) || r === 'checkbox' || r === 'radio' || r === 'upload')) {
        if (r === 'link') {
          const key = el.getAttribute('href') + '|' + (el.innerText || '').trim();
          if (seenLinks.has(key)) return;
          seenLinks.add(key);
        }
        const e = elEntry(el, r, ctx.frame);
        if (e) sink.push(e);
      }
      if (r !== 'editor' && r !== 'clickable' && r !== 'listbox') return;
    }
    const ar = el.getAttribute('role');
    if ((ar && TEXT_ROLES.has(ar)) || el.hasAttribute('aria-live') || (ctx.inDialog && (tag === 'P' || tag === 'LABEL' && !el.querySelector('input,select,textarea')))) {
      if (visible(el)) { const tx = clip(el.innerText, 160); if (tx) sink.push({ t: 'txt', text: tx }); }
      if (ar && TEXT_ROLES.has(ar) && !el.querySelector(INTERACTIVE_SEL)) return;
    }
    if (FULL && (tag === 'P' || tag === 'LI' || tag === 'TD' || tag === 'DT' || tag === 'DD' || tag === 'BLOCKQUOTE' || tag === 'FIGCAPTION') && !el.querySelector(INTERACTIVE_SEL)) {
      if (visible(el) && onScreenSized(el) && !tinyText(el)) { const tx = clip(el.innerText, 200); if (tx) sink.push({ t: 'txt', text: tx }); }
      return;
    }
    walk(el, sink, ctx);
  }
  function countEls(items) { let n = 0; for (const i of items) n += i.t === 'el' ? 1 : i.t === 'group' ? (i.count || 0) : 0; return n; }

  // cursor:pointer elements with no semantic role (React-style onClick on divs), time-boxed
  const pointerExtra = new Set();
  (function findPointerTargets() {
    const scope = dialog || mainEl || document.body;
    const els = scope.querySelectorAll('div,span,li,img,td');
    const t0 = performance.now();
    let i = 0;
    for (const el of els) {
      if (++i > 1500 || performance.now() - t0 > 60) break;
      if (el.getAttribute('role') || el.hasAttribute('data-lab-skip')) continue;
      if (el.children.length > 3 || el.querySelector(INTERACTIVE_SEL)) continue;
      const cs = getWin(el).getComputedStyle(el);
      if (cs.cursor !== 'pointer') continue;
      const p = el.parentElement;
      if (p && getWin(p).getComputedStyle(p).cursor === 'pointer') continue;
      if (!(el.innerText || el.getAttribute('aria-label') || el.alt)) continue;
      pointerExtra.add(el);
    }
  })();
  mark('pointer');
  const origRole = roleOf;
  roleOf = function (el) { const r = origRole(el); return r || (pointerExtra.has(el) ? 'clickable' : null); };

  walk(root, out, { inGroup: false, inDialog: !!dialog, frame: null });
  mark('walk');
  flushIds();
  mark('flush');

  return {
    v: 1, mode: MODE, title: clip(document.title, 80), path, origin: location.origin, docId: S.docId,
    within: scopeEl ? { id: +opts.within, tag: scopeEl.tagName.toLowerCase(), label: clip(scopeEl.getAttribute('aria-label') || (scopeEl.querySelector('legend,caption,h1,h2,h3') || {}).innerText || '', 40) } : null,
    routeChanged, dialog: dialog ? { name: accName(dialog) || 'dialog' } : null, banner, entries: out, prof: PROF,
    ms: Math.round(performance.now() - T0),
  };
}
