// Prototype lean snapshot (spike). Runs in the page via evaluate().
// Returns compact text: one line per interactive element, stable data-lab-id IDs,
// nav/footer/aside collapsed, hidden content dropped.
(() => {
  const W = window;
  W.__lab = W.__lab || { next: 1 };
  const S = W.__lab;

  const INTERACTIVE_ROLES = new Set(['button','link','checkbox','radio','switch','tab','menuitem',
    'option','combobox','textbox','slider','listbox','searchbox']);
  const SKIP = new Set(['SCRIPT','STYLE','NOSCRIPT','TEMPLATE','SVG','HEAD','META','LINK']);
  const COLLAPSE = new Set(['NAV','FOOTER','ASIDE','HEADER']);

  function hidden(el) {
    if (el.hidden || el.getAttribute('aria-hidden') === 'true') return true;
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || cs.opacity === '0') return true;
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0 && cs.position !== 'fixed' && el.children.length === 0) return true;
    if (r.right < -1000 || r.bottom < -1000) return true;
    return false;
  }
  function role(el) {
    const r = el.getAttribute('role');
    if (r) return r;
    const t = el.tagName;
    if (t === 'A' && el.hasAttribute('href')) return 'link';
    if (t === 'BUTTON') return 'button';
    if (t === 'SELECT') return 'select';
    if (t === 'TEXTAREA') return 'textbox';
    if (t === 'INPUT') {
      const ty = (el.type || 'text').toLowerCase();
      if (ty === 'checkbox' || ty === 'radio') return ty;
      if (ty === 'submit' || ty === 'button') return 'button';
      if (ty === 'file') return 'upload';
      if (ty === 'hidden') return null;
      return 'textbox';
    }
    if (el.isContentEditable && el.getAttribute('contenteditable') !== null) return 'editor';
    return null;
  }
  function clickableByStyle(el) {
    const cs = getComputedStyle(el);
    if (cs.cursor !== 'pointer') return false;
    const p = el.parentElement;
    return !(p && getComputedStyle(p).cursor === 'pointer');
  }
  function name(el) {
    const a = el.getAttribute('aria-label');
    if (a) return a.trim();
    if (el.id) {
      const root = el.getRootNode();
      const l = root.querySelector && root.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (l) return l.innerText.trim();
    }
    const wrap = el.closest('label');
    if (wrap) return wrap.innerText.replace(el.value || '', '').trim();
    if (el.placeholder) return el.placeholder;
    return (el.innerText || el.value || el.alt || el.title || '').trim();
  }
  function id(el) {
    if (!el.dataset.labId) el.dataset.labId = String(S.next++);
    return el.dataset.labId;
  }
  const q = (s, n = 40) => { s = s.replace(/\s+/g, ' ').replace(/\*$/, '').trim(); return s.length > n ? s.slice(0, n - 1) + '…' : s; };

  const lines = [];
  const seenLinks = new Set();
  const radioGroups = new Map();

  function line(el, r) {
    let n = q(name(el));
    let s = `${id(el)}: ${r === 'select' ? 'select' : r} "${n}"`;
    if (el.required) s += '*';
    if (el.type === 'email') s += ' type=email';
    if (el.type === 'password') s += el.value ? ' = ••••' : ' type=password';
    else if (r === 'textbox' && el.value) s += ` = "${q(el.value, 30)}"`;
    if (r === 'select') s += ` [${[...el.options].map(o => o.text).join('|')}]` + (el.selectedIndex > 0 ? ` = ${el.options[el.selectedIndex].text}` : '');
    if (r === 'checkbox') s += el.checked ? ' on' : ' off';
    if (r === 'combobox' && el.tagName !== 'SELECT') s += ' (custom)';
    if (r === 'upload' && el.accept) s += ` accept=${el.accept}`;
    if (r === 'upload' && el.files && el.files.length) s += ` = ${el.files[0].name}`;
    const errId = el.getAttribute('aria-describedby');
    const err = (errId && document.getElementById(errId)) || (el.parentElement && el.parentElement.nextElementSibling && el.parentElement.nextElementSibling.classList.contains('err') ? el.parentElement.nextElementSibling : null);
    if (err && err.innerText.trim()) s += ` !"${q(err.innerText, 40)}"`;
    return s;
  }

  function collapse(el) {
    const links = [...el.querySelectorAll('a[href],button')].filter(a => !hidden(a));
    if (!links.length) return;
    const tag = el.tagName.toLowerCase();
    const handle = `${tag[0]}${id(el)}`;
    const shown = links.slice(0, 3).map(a => q(a.innerText, 20)).join(', ');
    lines.push(`${tag}: ${shown}${links.length > 3 ? ` (+${links.length - 3})` : ''} [expand:${handle}]`);
  }

  function walk(node, inFrame) {
    for (const el of node.children || []) {
      if (SKIP.has(el.tagName.toUpperCase())) continue;
      if (hidden(el)) continue;
      if (COLLAPSE.has(el.tagName) && !el.closest('main')) { collapse(el); continue; }
      if (/^H[1-3]$/.test(el.tagName)) lines.push(`# ${q(el.innerText, 60)}`);
      let r = role(el);
      if (!r && clickableByStyle(el) && !el.querySelector('a,button,input,select')) r = 'clickable';
      if (r && (INTERACTIVE_ROLES.has(r) || ['select','upload','editor','clickable'].includes(r))) {
        if (r === 'radio') {
          const g = el.name || 'r';
          if (!radioGroups.has(g)) {
            const fs = el.closest('fieldset');
            const legend = fs && fs.querySelector('legend');
            const opts = [...(el.form || document).querySelectorAll(`input[type=radio][name="${CSS.escape(g)}"]`)];
            const sel = opts.find(o => o.checked);
            radioGroups.set(g, true);
            lines.push(`${id(el)}: radiogroup "${q(legend ? legend.innerText : g)}" [${opts.map(o => q(name(o), 15)).join('|')}]${sel ? ' = ' + q(name(sel), 15) : ''}`);
          }
          continue;
        }
        if (r === 'link') {
          const key = el.getAttribute('href') + '|' + el.innerText.trim();
          if (seenLinks.has(key)) continue;
          seenLinks.add(key);
        }
        lines.push((inFrame ? `[frame] ` : '') + line(el, r));
        if (r !== 'editor') continue;
      }
      if (el.shadowRoot) walk(el.shadowRoot, inFrame);
      if (el.tagName === 'IFRAME') {
        try { const d = el.contentDocument; if (d && d.body) walk(d.body, true); }
        catch (e) { lines.push(`${id(el)}: iframe (cross-origin) [frame:${id(el)}]`); }
        continue;
      }
      walk(el, inFrame);
    }
  }
  // Banners/dialogs first
  const banner = [...document.querySelectorAll('[id*=cookie],[class*=cookie],[class*=consent]')].find(e => !hidden(e));
  walk(document.body, false);
  if (banner) {
    const btns = [...banner.querySelectorAll('button')].map(b => `[${q(b.innerText, 12).toLowerCase()}:${id(b)}]`).join(' ');
    // remove banner buttons from main list
    for (let i = lines.length - 1; i >= 0; i--) if ([...banner.querySelectorAll('button')].some(b => lines[i].startsWith(b.dataset.labId + ':'))) lines.splice(i, 1);
    lines.unshift(`banner: cookies ${btns}`);
  }
  const path = location.pathname + location.hash;
  return `page: ${q(document.title, 60)} | url: ${path}\n` + lines.join('\n');
})()
