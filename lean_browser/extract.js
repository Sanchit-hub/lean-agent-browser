// Deterministic structured extraction (no LLM). Called with page.evaluate(SRC, {kind, within}).
// kind: auto | table | list | form. `within` is a snapshot ID that scopes the search.
(opts) => {
  const kind = opts.kind || 'auto';
  let root = document.body;
  if (opts.within != null) {
    const r = window.__lab && window.__lab.byId.get(+opts.within);
    const el = r && r.deref();
    if (!el) return { error: `id ${opts.within} not found — call snapshot()` };
    root = el;
  }
  const clip = (s, n) => { s = (s || '').replace(/\s+/g, ' ').trim(); return s.length > n ? s.slice(0, n - 1) + '…' : s; };
  const vis = el => { if (!el.isConnected) return false; const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') return false; const r = el.getBoundingClientRect(); return r.width > 0 || r.height > 0; };
  const idOf = el => (el.dataset && el.dataset.labId) ? +el.dataset.labId : undefined;
  const links = el => [...el.querySelectorAll('a[href],button')].filter(vis).slice(0, 5)
    .map(a => { const o = { text: clip(a.innerText || a.getAttribute('aria-label'), 60) }; const i = idOf(a); if (i) o.id = i; return o; })
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
    const data = body.slice(0, 200).map(r => {
      const cells = cellsOf(r).map(c => clip(c.innerText, 120));
      return headers && headers.length === cells.length ? Object.fromEntries(headers.map((h, i) => [h || `col${i + 1}`, cells[i]])) : cells;
    });
    return { kind: 'table', headers, rows: data, total_rows: body.length };
  }
  function list() {
    let best = null, n = 0;
    for (const el of [root, ...root.querySelectorAll('ul,ol,tbody,div,section,[role=list],[role=feed]')]) {
      const kids = [...el.children].filter(vis);
      if (kids.length < 3) continue;
      const sig = new Map();
      for (const k of kids) { const s = k.tagName + '.' + (typeof k.className === 'string' ? k.className : ''); sig.set(s, (sig.get(s) || 0) + 1); }
      const top = Math.max(...sig.values());
      if (top > n && top >= 3) { n = top; best = { el, sig: [...sig].find(([, c]) => c === top)[0] }; }
    }
    if (!best) return null;
    const items = [...best.el.children].filter(k => vis(k) && (k.tagName + '.' + (typeof k.className === 'string' ? k.className : '')) === best.sig)
      .slice(0, 200).map(k => { const o = { text: clip(k.innerText, 200) }; const l = links(k); if (l.length) o.links = l; return o; });
    return { kind: 'list', items, total_items: items.length };
  }
  function form() {
    const forms = [...(root.tagName === 'FORM' ? [root] : root.querySelectorAll('form'))].filter(vis);
    const scope = forms.length ? forms : [root];
    const fields = [];
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
        fields.push(o);
      }
    }
    return fields.length ? { kind: 'form', fields } : null;
  }
  if (kind === 'table') return table() || { error: 'no visible table' };
  if (kind === 'list') return list() || { error: 'no repeated list found' };
  if (kind === 'form') return form() || { error: 'no form fields found' };
  const t = table();
  if (t && t.rows.length >= 2) return t;
  return list() || form() || { error: 'nothing structured found; use snapshot(mode="read")' };
}
