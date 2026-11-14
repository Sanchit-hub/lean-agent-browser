"""Settle: after an action, wait until the page is quiet before taking the after-snapshot.

Quiet = no DOM mutations for 300 ms AND no fetch/XHR in flight (requests running longer than
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
  const start = () => {
    try {
      new MutationObserver(recs => {
        for (const r of recs) if (!(r.type === 'attributes' && r.attributeName === 'data-lab-id')) { bump(); return; }
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


async def settle(page: Page, quiet_ms: int = 300, cap_s: float = 5.0) -> bool:
    """Return True if the page went quiet, False if the cap was hit (caller says 'still loading')."""
    deadline = time.monotonic() + cap_s
    installed = False
    while time.monotonic() < deadline:
        try:
            st = await page.evaluate(PROBE_JS)
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
