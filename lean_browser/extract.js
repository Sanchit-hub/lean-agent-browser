// Deterministic structured extraction (no LLM). Called with page.evaluate(SRC, {kind, within}).
// kind: auto | table | list | form. `within` is a snapshot ID that scopes the search.
(opts) => {
  const kind = opts.kind || 'auto';
  let root = document.body;
  const CONTAINER_SEL = 'form,table,fieldset,[role=dialog],dialog,article,section,ul,ol,[role=list],[role=grid],nav,aside,main,[role=main]';
  if (opts.within != null) {
    const r = window.__lab && window.__lab.byId.get(+opts.within);
    const el = r && r.deref();
    if (!el || !el.isConnected) return { error: `id ${opts.within} not found — call snapshot()` };
    root = el.matches(CONTAINER_SEL) ? el : (el.closest(CONTAINER_SEL) || el);
  }
  const fields = (opts.fields || []).map(f => String(f).toLowerCase().replace(/\[.*?\]/g, '').trim()).filter(Boolean);
  // url/link/href fields return the absolute address of the item's first http(s) link (opt-in: hrefs cost tokens)
  const isUrlField = f => /^(url|urls|link|links|href|hrefs)$/.test(String(f).toLowerCase().replace(/[^a-z]/g, ''));
  const wantUrl = fields.some(isUrlField);
  const colFields = fields.filter(f => !isUrlField(f));
  const hrefOf = a => { const h = a.href || ''; return /^https?:/i.test(h) ? (h.length > 300 ? h.slice(0, 300) : h) : null; };
  // first visible http(s) link with text (skips icon-only links such as vote arrows), else the first at all
  const firstUrl = el => { let any = null;
    for (const a of el.querySelectorAll('a[href]')) { if (!vis(a)) continue; const h = hrefOf(a); if (!h) continue;
      if ((a.innerText || a.getAttribute('aria-label') || '').trim()) return h; any = any || h; }
    return any; };
  const wants = h => !fields.length || fields.some(f => String(h || '').toLowerCase().replace(/\[.*?\]/g, '').includes(f));
  const idsIn = el => [...el.querySelectorAll('[data-lab-id]')].map(e => +e.dataset.labId);
  const source = { url: location.href, title: document.title };
  // Deterministic field lookup inside one item: labelled elements (itemprop / data-field / class), then
  // "Label: value" lines, then the item's heading for *name*/*title* fields. Never guesses beyond that.
  const normf = x => String(x || '').toLowerCase().replace(/[_\-]+/g, ' ').replace(/\s+/g, ' ').trim();
  function fieldValue(item, field) {
    if (isUrlField(field)) { const u = firstUrl(item); return { value: u, conflict: false }; }
    const fn = normf(field), toks = fn.split(' ').filter(t => t.length > 1);
    const found = [];
    for (const el of item.querySelectorAll('[itemprop],[data-field],[class]')) {
      const tags = normf((el.getAttribute('itemprop') || '') + ' ' + (el.getAttribute('data-field') || '') + ' ' +
                         (typeof el.className === 'string' ? el.className : ''));
      const words = tags.split(' ');
      if (toks.length && toks.every(t => words.includes(t))) { const v = clip(el.innerText, 80); if (v) { found.push(v.replace(/^[^:]{1,30}:\s*/, '')); break; } }
    }
    for (const line of (item.innerText || '').split(/\n|·/)) {
      const m = line.match(/^\s*([^:]{1,40}):\s*(.+?)\s*$/);
      if (m && toks.some(t => normf(m[1]).split(' ').includes(t))) found.push(clip(m[2], 80));
    }
    if (!found.length && /\b(name|title)\b/.test(fn)) {
      // first heading or link with text (an image link usually comes first in product cards)
      const h = [...item.querySelectorAll('h1,h2,h3,h4,h5,a')].find(x => (x.innerText || '').trim());
      if (h) {
        // Shops often cut long titles on screen ("A Light in the ...") and keep the full one in the link's title
        let v = h.innerText.trim(); const a = h.tagName === 'A' ? h : h.querySelector('a[title]');
        const full = a && (a.getAttribute('title') || '').trim();
        if (full && /(\.\.\.|…)\s*$/.test(v) && full.toLowerCase().startsWith(v.replace(/(\.\.\.|…)\s*$/, '').trim().toLowerCase())) v = full;
        found.push(clip(v, 120));
      }
    }
    const distinct = [...new Set(found.map(v => v.toLowerCase()))];
    return { value: found.length ? found[0] : null, conflict: distinct.length > 1, values: distinct.length > 1 ? [...new Set(found)] : undefined };
  }
  const clip = (s, n) => { s = (s || '').replace(/\s+/g, ' ').trim(); return s.length > n ? s.slice(0, n - 1) + '…' : s; };
  const vis = el => { if (!el.isConnected) return false; const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') return false; const r = el.getBoundingClientRect(); return r.width > 0 || r.height > 0; };
  const idOf = el => (el.dataset && el.dataset.labId) ? +el.dataset.labId : undefined;
  const links = el => [...el.querySelectorAll('a[href],button')].filter(vis).slice(0, 5)
    .map(a => { const o = { text: clip(a.innerText || a.getAttribute('aria-label'), 60) }; const i = idOf(a); if (i) o.id = i;
      return o; })
    .filter(o => o.text);

  function table() {
    const ts = [...(root.tagName === 'TABLE' ? [root] : root.querySelectorAll('table'))].filter(vis);
    if (!ts.length) return null;
    // Obscura lacks table.rows / row.cells, so use selectors (nested tables excluded)
    const rowsOf = t => [...t.querySelectorAll('tr')].filter(r => r.closest('table') === t);
    const cellsOf = r => [...r.children].filter(c => c.tagName === 'TD' || c.tagName === 'TH');
    const t = ts.reduce((a, b) => (rowsOf(b).length > rowsOf(a).length ? b : a));
    const rows = rowsOf(t).filter(vis);
    if (!rows.length) return null;
    let headers = null, body = rows;
    if (rows[0].querySelector('th')) { headers = cellsOf(rows[0]).map(c => clip(c.innerText, 60)); body = rows.slice(1); }
    const wantsCol = h => !colFields.length ? true : colFields.some(f => String(h || '').toLowerCase().replace(/\[.*?\]/g, '').includes(f));
    const keep = headers ? headers.map(h => wantsCol(h)) : null;
    const data = body.slice(0, 200).map((r, ri) => {
      const cells = cellsOf(r).map(c => clip(c.innerText, 120));
      let row;
      if (headers && headers.length === cells.length) {
        row = {};
        headers.forEach((h, i) => { if (keep[i]) row[h || `col${i + 1}`] = cells[i]; });
      } else row = { cells };
      if (wantUrl) row.url = firstUrl(r);
      row._row = ri + 1;
      const ids = idsIn(r); if (ids.length) row._ids = ids;
      return row;
    });
    const out = { kind: 'table', source, headers: headers && keep ? headers.filter((h, i) => keep[i]) : headers, rows: data, total_rows: body.length };
    if (colFields.length && !headers) out.note = 'table has no header row; fields ignored';
    else if (colFields.length && !keep.some(Boolean)) out.note = 'no column matched fields; columns: ' + headers.join(' | ');
    return out;
  }
  // Lists in page chrome (category sidebars, menus, footers) lose to lists in the content unless nothing else repeats.
  const CHROME = 'nav,aside,header,footer,[role=navigation],[role=complementary],[role=banner],[role=contentinfo]';
  const inChrome = el => { const c = el.closest(CHROME); return !!c && !c.contains(root) && c !== root; };
  function list() {
    return listPick(false) || listPick(true);
  }
  function listPick(allowChrome) {
    let best = null, n = 0;
    for (const el of [root, ...root.querySelectorAll('ul,ol,tbody,div,section,[role=list],[role=feed]')]) {
      if (!allowChrome && el !== root && inChrome(el)) continue;
      const kids = [...el.children].filter(vis);
      if (kids.length < 3) continue;
      const sig = new Map();
      for (const k of kids) { const s = k.tagName + '.' + (typeof k.className === 'string' ? k.className : ''); sig.set(s, (sig.get(s) || 0) + 1); }
      const top = Math.max(...sig.values());
      if (top > n && top >= 3) { n = top; best = { el, sig: [...sig].find(([, c]) => c === top)[0] }; }
    }
    if (!best) return null;
    const items = [...best.el.children].filter(k => vis(k) && (k.tagName + '.' + (typeof k.className === 'string' ? k.className : '')) === best.sig)
      .slice(0, 200).map((k, i) => {
        const o = { text: clip(k.innerText, fields.length ? 120 : 200), _item: i + 1 };
        const l = links(k); if (l.length) o.links = l;
        if (fields.length) {  // structured fields per item, with explicit missing/conflicting fields
          o.fields = {}; const missing = [], conflicts = [];
          for (const f of opts.fields) {
            const r = fieldValue(k, String(f));
            o.fields[f] = r.value;
            if (r.value == null) missing.push(f);
            if (r.conflict) conflicts.push({ field: f, values: r.values });
          }
          if (missing.length) o.missing = missing;
          if (conflicts.length) o.conflicts = conflicts;
          const ids = idsIn(k); if (ids.length) o._ids = ids;
        }
        return o;
      });
    return { kind: 'list', source, items, total_items: items.length };
  }
  function form() {
    const forms = [...(root.tagName === 'FORM' ? [root] : root.querySelectorAll('form'))].filter(vis);
    const scope = forms.length ? forms : [root];
    const out = [];
    for (const f of scope) {
      for (const el of f.querySelectorAll('input:not([type=hidden]),select,textarea')) {
        if (!vis(el) && !['checkbox', 'radio', 'file'].includes(el.type)) continue;
        const lab = (el.id && document.querySelector(`label[for="${CSS.escape(el.id)}"]`)) || el.closest('label');
        const o = { name: clip((lab && lab.textContent) || el.getAttribute('aria-label') || el.name || el.placeholder, 60), type: el.type || el.tagName.toLowerCase() };
        const i = idOf(el); if (i) o.id = i;
        if (el.type === 'password') o.value = el.value ? '••••' : '';
        else if (el.type === 'checkbox' || el.type === 'radio') o.checked = el.checked;
        else if (el.tagName === 'SELECT') { o.value = el.selectedIndex >= 0 ? el.options[el.selectedIndex].text : ''; o.options = [...el.options].map(x => x.text.trim()); }
        else if (el.type !== 'file') o.value = el.value;
        if (el.required || el.hasAttribute('required')) o.required = true;
        if (wants(o.name)) out.push(o);
      }
    }
    return out.length ? { kind: 'form', source, fields: out } : null;
  }
  function run() {
    if (kind === 'table') return table() || { error: 'no visible table' };
    if (kind === 'list') return list() || { error: 'no repeated list found' };
    if (kind === 'form') return form() || { error: 'no form fields found' };
    const t = table();
    if (t && t.rows.length >= 2) return t;
    return list() || form() || { error: 'nothing structured found; use snapshot(mode="read")' };
  }
  const first = run();
  if (!first.error || opts.within == null) return first;
  // `within` named something inside one item (a book's link): widen to the nearest ancestor that holds the list
  for (let hops = 0; hops < 6 && root.parentElement && root !== document.body; hops++) {
    root = root.parentElement;
    const res = run();
    if (!res.error) return res;
  }
  return first;
}
