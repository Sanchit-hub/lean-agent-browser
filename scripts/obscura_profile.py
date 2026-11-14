"""Dev helper: time individual DOM operations in Obscura vs Chromium on the big fixture page."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from evals.fixtures.server import serve  # noqa: E402
from lean_browser.engine import BrowserManager  # noqa: E402
from tests.test_fixtures import _free_port  # noqa: E402

PROBE = """() => {
  const t = {}; let t0;
  const rows = [...document.querySelectorAll('tbody > tr')];
  const time = (k, f) => { t0 = performance.now(); f(); t[k] = Math.round(performance.now() - t0); };
  time('qsa_all', () => document.querySelectorAll('*').length);
  time('innerText_rows', () => rows.forEach(r => r.innerText));
  time('textContent_rows', () => rows.forEach(r => r.textContent));
  time('gcs_rows', () => rows.forEach(r => getComputedStyle(r).display));
  time('rect_rows', () => rows.forEach(r => r.getBoundingClientRect()));
  time('qsa_in_rows', () => rows.forEach(r => r.querySelectorAll('a,button,input')));
  time('closest_rows', () => rows.forEach(r => r.closest('main,nav,form')));
  time('matches_rows', () => rows.forEach(r => r.matches('a[href],button,[role=button]')));
  time('dataset_set', () => rows.forEach((r, i) => r.dataset.x = i));
  const links = [...document.querySelectorAll('tbody a')];
  time('link_innerText', () => links.forEach(a => a.innerText));
  time('weakref', () => links.forEach(a => new WeakRef(a)));
  time('children_loop', () => { let n = 0; const w = el => { for (const c of el.children) { n++; w(c); } }; w(document.body); });
  const SEL = 'a[href],button,input:not([type=hidden]),select,textarea,summary,[contenteditable]:not([contenteditable=false]),[onclick],' +
    ['button','link','checkbox','radio','switch','tab','menuitem','menuitemcheckbox','menuitemradio','option','combobox','textbox','searchbox','slider','spinbutton','listbox','treeitem'].map(r => `[role=${r}]`).join(',');
  time('qsa_complex_rows', () => rows.forEach(r => r.querySelectorAll(SEL)));
  time('matches_complex_rows', () => rows.forEach(r => r.matches(SEL)));
  time('closest_landmark_links', () => links.forEach(a => a.closest('main,nav,header,footer,aside,form,dialog,[role=dialog],[role=main],[role=navigation]')));
  time('getAttribute_x10', () => rows.forEach(r => { for (let i = 0; i < 10; i++) r.getAttribute('role'); }));
  time('gcs_links_cursor', () => links.forEach(a => getComputedStyle(a).cursor));
  time('className_rows', () => rows.forEach(r => r.className));
  time('children_spread', () => rows.forEach(r => [...r.children]));
  return t;
}"""


async def main():
    port = _free_port()
    srv = serve(port)
    for prefer in ("obscura", "chromium"):
        async with BrowserManager(allow_private_network=True, prefer=prefer) as bm:
            tab = await bm.open(f"http://127.0.0.1:{port}/big.html")
            print(prefer, await tab.page.evaluate(PROBE))
    srv.shutdown()


asyncio.run(main())
