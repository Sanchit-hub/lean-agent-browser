"""Settle: after an action, wait until the page is quiet before taking the after-snapshot.

Quiet = no DOM mutations for 300 ms AND no fetch/XHR (or script/stylesheet added after load) in flight (requests running longer than
3 s are treated as long-polling and ignored), capped at 5 s. Navigation started by the action is
awaited to domcontentloaded. Implemented in page JS (installed as an init script) so it behaves
the same on Obscura and Chromium.
"""
from __future__ import annotations

import asyncio
import time

from playwright.async_api import Page

SETTLE_INIT_JS = r"""
(() => {
  if (window.__labSettle) return;
  const s = window.__labSettle = { pending: new Map(), seq: 0, lastMut: performance.now() };
  const bump = () => { s.lastMut = performance.now(); };
  const of = window.fetch;
  if (of) window.fetch = function (...a) {
    const k = ++s.seq; s.pending.set(k, performance.now());
    return of.apply(this, a).finally(() => { s.pending.delete(k); bump(); });
  };
  const XS = window.XMLHttpRequest && XMLHttpRequest.prototype.send;
  if (XS) XMLHttpRequest.prototype.send = function (...a) {
    const k = ++s.seq; s.pending.set(k, performance.now());
    this.addEventListener('loadend', () => { s.pending.delete(k); bump(); }, { once: true });
    return XS.apply(this, a);
  };
  // Short timers (debounced autosave, delayed validation) a page schedules in response to an action. Session arms
  // this before a field action and, if one is still pending after settle, waits for it before re-reading the field.
  s.timers = new Map(); s.armAt = Infinity;
  const ost = window.setTimeout, oct = window.clearTimeout;
  if (ost) {
    window.setTimeout = function (fn, ms, ...rest) {
      const d = Number(ms) || 0, now = performance.now();
      let id;
      const wrapped = typeof fn === 'function' ? function (...x) { s.timers.delete(id); return fn.apply(this, x); } : fn;
      id = ost.call(this, wrapped, ms, ...rest);
      if (typeof fn === 'function' && d >= 50 && d <= 3000 && now >= s.armAt) s.timers.set(id, now + d);
      return id;
    };
    window.clearTimeout = function (id) { s.timers.delete(id); return oct.call(this, id); };
  }
  const start = () => {
    try {
      // Scripts and stylesheets a page adds after load (editors and widgets loading their plugins) count as
      // requests in flight until they load or fail, like fetch/XHR.
      const track = n => {
        if (!(n.nodeName === 'SCRIPT' && n.src) && !(n.nodeName === 'LINK' && /stylesheet/i.test(n.rel || '') && n.href)) return;
        const k = ++s.seq; s.pending.set(k, performance.now());
        const done = () => { s.pending.delete(k); bump(); };
        n.addEventListener('load', done, { once: true }); n.addEventListener('error', done, { once: true });
      };
      new MutationObserver(recs => {
        let changed = false;
        for (const r of recs) {
          if (r.type === 'childList') for (const n of r.addedNodes) if (n.nodeName === 'SCRIPT' || n.nodeName === 'LINK') track(n);
          if (!(r.type === 'attributes' && r.attributeName === 'data-lab-id')) changed = true;
        }
        if (changed) bump();
      }).observe(document, { subtree: true, childList: true, attributes: true, characterData: true });
    } catch (e) {}
  };
  if (document.documentElement) start(); else document.addEventListener('DOMContentLoaded', start);
})();
"""

PROBE_JS = """() => {
  const s = window.__labSettle;
  if (!s) return null;
  const now = performance.now();
  let n = 0; for (const t of s.pending.values()) if (now - t < 3000) n++;
  return { quiet: now - s.lastMut, net: n, ready: document.readyState };
}"""


ARM_TIMERS_JS = "() => { const s = window.__labSettle; if (s && s.timers) { s.timers.clear(); s.armAt = performance.now(); } }"
# ms until the last short timer scheduled since arming fires (0 if none), then disarm.
PENDING_TIMERS_JS = """() => { const s = window.__labSettle; if (!s || !s.timers) return 0;
  const now = performance.now(); let due = 0;
  for (const t of s.timers.values()) if (t > now) due = Math.max(due, t - now);
  return due; }"""
DISARM_TIMERS_JS = "() => { const s = window.__labSettle; if (s && s.timers) { s.armAt = Infinity; s.timers.clear(); } }"


class PageUnresponsive(Exception):
    """The page no longer answers evaluate() calls; the caller should move it to another engine."""


async def settle(page: Page, quiet_ms: int = 300, cap_s: float = 5.0) -> bool:
    """Return True if the page went quiet, False if the cap was hit (caller says 'still loading')."""
    deadline = time.monotonic() + cap_s
    installed = False
    timeouts = 0
    while time.monotonic() < deadline:
        try:
            st = await asyncio.wait_for(page.evaluate(PROBE_JS), 2)
            timeouts = 0
        except asyncio.TimeoutError:
            timeouts += 1
            if timeouts >= 2:  # the page's script thread is stuck (seen on Obscura with some sites)
                raise PageUnresponsive("page stopped responding to scripts")
            continue
        except Exception:
            # execution context destroyed: a navigation is in progress
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=max(100, int((deadline - time.monotonic()) * 1000)))
            except Exception:
                pass
            continue
        if st is None:
            if not installed:
                try:
                    await page.evaluate(SETTLE_INIT_JS)
                except Exception:
                    pass
                installed = True
            await asyncio.sleep(quiet_ms / 1000)
            continue
        if st["ready"] != "loading" and st["net"] == 0 and st["quiet"] >= quiet_ms:
            return True
        await asyncio.sleep(0.05)
    return False
