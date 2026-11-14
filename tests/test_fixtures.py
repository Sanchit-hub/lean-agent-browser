"""Fixture sanity: every task is solvable by its oracle in Chromium, and every verifier rejects
an empty server state (so a do-nothing agent can never pass)."""
import json
import socket
import urllib.request

import pytest
from playwright.async_api import async_playwright

from evals.fixtures.server import serve
from evals.oracle import SOLUTIONS
from evals.tasks import TASKS


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture(scope="module")
def base():
    port = _free_port()
    srv = serve(port)
    yield f"http://127.0.0.1:{port}"
    srv.shutdown()


def _state(base):
    return json.loads(urllib.request.urlopen(f"{base}/api/state").read())


def test_every_task_has_an_oracle():
    assert {t.id for t in TASKS} == set(SOLUTIONS)


@pytest.mark.parametrize("task", TASKS, ids=lambda t: t.id)
def test_verifier_rejects_empty_state(task):
    ok, _ = task.verify({"submissions": [], "hits": []}, "")
    assert not ok


@pytest.mark.parametrize("task", TASKS, ids=lambda t: t.id)
async def test_oracle_solves_task(task, base):
    urllib.request.urlopen(f"{base}/api/reset").read()
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        ctx = await browser.new_context()
        page = await ctx.new_page()
        await page.goto(base + task.start)
        answer = await SOLUTIONS[task.id](page, base)
        await page.wait_for_timeout(200)
        ok, why = task.verify(_state(base), answer or "")
        await browser.close()
    assert ok, why
