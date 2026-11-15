"""Benchmark tasks beyond the original 20: 80 more fixture tasks across forms, multi-step flows,
reading, navigation, widgets, dialogs, frames, dynamic pages and safety. See docs/benchmark.md."""
from __future__ import annotations

from evals.bench import dialogs, dynamic, forms, frames, multistep, nav, read, safety, widgets  # noqa: F401  (register)
from evals.bench.core import PAGES, POST, REDIRECTS, REG


def get_page(path: str, q: dict):
    if path in REDIRECTS:
        return ("redirect", REDIRECTS[path])
    p = PAGES.get(path)
    if p is None:
        return None
    return p(q) if callable(p) else p


def post_hook(path: str, fields: dict, state: dict):
    h = POST.get(path)
    return h(fields, state) if h else None
