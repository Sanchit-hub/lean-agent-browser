"""Live-site tasks: real public pages, read-only or harmless test endpoints, with answers that rarely
change. Success is judged from the agent's final answer (there is no fixture server to ask), so these
results are reported separately from the fixture suite and labelled "live" — pages and networks vary.
"""
from __future__ import annotations

import re

from evals.tasks import Task


def _has(*needles):
    def v(state, ans):
        low = ans.lower()
        missing = [n for n in needles if n.lower() not in low]
        return (not missing, f"answer missing {missing}" if missing else "ok")
    return v


def _year(y):
    def v(state, ans):
        return (re.search(rf"\b{y}\b", ans) is not None, f"want {y}")
    return v


LIVE_TASKS: list[Task] = [
    Task("live-python-designer", "https://en.wikipedia.org/wiki/Python_(programming_language)",
         "According to this Wikipedia article, who designed the Python programming language?",
         _has("guido van rossum"), ("live", "read")),
    Task("live-halley", "https://en.wikipedia.org/wiki/Halley%27s_Comet",
         "According to this article, in what year did Halley's Comet last reach perihelion?",
         _year(1986), ("live", "read")),
    Task("live-obscura-license", "https://github.com/h4ckf0r0day/obscura",
         "What open-source license is this GitHub repository published under?",
         _has("apache"), ("live", "read")),
    Task("live-example-link", "https://example.com/",
         "Follow the only link on this page and report the domain name of the page it opens.",
         _has("iana"), ("live", "navigate")),
    Task("live-httpbin-form", "https://httpbin.org/forms/post",
         "Fill this test form with customer name 'Lean Tester', telephone '5550100', a small pizza with onion, "
         "submit it, and report the customer name the server echoed back.",
         _has("lean tester"), ("live", "form")),
]
BY_ID = {t.id: t for t in LIVE_TASKS}
