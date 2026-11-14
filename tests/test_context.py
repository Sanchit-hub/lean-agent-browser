"""Scoped context: snapshot(within=id), extract(fields=..., new_only=...) and provenance, on both engines."""
import re
import urllib.request

import pytest

from evals.fixtures.server import serve
from lean_browser import Config, LeanBrowser, LeanBrowserError
from lean_browser.engine import find_obscura
from tests.test_fixtures import _free_port

ENGINES = ["chromium"] + (["obscura"] if find_obscura() else [])


@pytest.fixture(scope="module")
def base():
    port = _free_port()
    srv = serve(port)
    yield f"http://127.0.0.1:{port}"
    srv.shutdown()


@pytest.fixture(params=ENGINES)
async def b(request, base):
    urllib.request.urlopen(base + "/api/reset").read()
    async with LeanBrowser(Config(prefer=request.param, allow_private_network=True)) as lb:
        yield lb


def idof(text, pattern):
    return int(re.search(r"(\d+): " + pattern, text).group(1))


async def test_within_scopes_to_the_containing_form(b, base):
    page = await b.open(base + "/signup.html")
    scoped = await b.snapshot(within=idof(page, 'textbox "Email"'))
    head, body = scoped.split("\n", 1)
    assert "within " in head and "(form)" in head
    assert 'textbox "Email"' in body and 'button "Create account"' in body
    assert "header:" not in body and "footer:" not in body          # page chrome is out of scope
    # a scoped view is not the diff baseline: the next full snapshot is still "unchanged"
    assert (await b.snapshot()).startswith("unchanged")


async def test_within_pagination_nav(b, base):
    page = await b.open(base + "/orders.html")
    scoped = await b.snapshot(within=idof(page, 'link "Next"'))
    assert 'link "Next"' in scoped and 'link "2"' in scoped and "table" not in scoped.split("\n", 1)[1]


async def test_within_unknown_id_is_an_error(b, base):
    await b.open(base + "/login.html")
    with pytest.raises(LeanBrowserError, match="id 4242 not found"):
        await b.snapshot(within=4242)


async def test_extract_fields_and_provenance(b, base):
    await b.open(base + "/orders.html")
    t = await b.extract("table", fields=["order", "amount"])
    assert t["headers"] == ["Order", "Amount"]
    assert set(t["rows"][0]) == {"Order", "Amount", "_row"} and t["rows"][0]["_row"] == 1
    assert t["source"]["url"].endswith("/orders.html") and t["source"]["title"].startswith("Orders")
    t2 = await b.extract("table", fields=["nonexistent"])
    assert "no column matched" in t2["note"]
    page = await b.open(base + "/files.html")
    rows = (await b.extract("table"))["rows"]
    assert rows[1]["_ids"] == [idof(page, 'button "Delete old-report.pdf"')]   # row -> element id


async def test_extract_form_fields_filter(b, base):
    await b.open(base + "/signup.html")
    f = await b.extract("form", fields=["email"])
    assert [x["name"] for x in f["fields"]] == ["Email"] and "id" in f["fields"][0]


async def test_extract_new_only_across_infinite_scroll(b, base):
    await b.open(base + "/feed.html")
    first = await b.extract("list", new_only=True)
    assert len(first["items"]) == 10 and first["already_seen"] == 0
    await b.act("scroll", value="bottom")
    second = await b.extract("list", new_only=True)
    assert len(second["items"]) == 10 and second["already_seen"] == 10
    assert second["items"][0]["text"].startswith("#11")
    again = await b.extract("list", new_only=True)
    assert again["items"] == [] and again["already_seen"] == 20


async def test_minimal_mode_drops_headings_and_text(b, base):
    page = await b.open(base + "/misc.html", mode="minimal")
    assert "# Misc widgets" not in page and "text: 3 items in cart" not in page
    assert 'clickable "Open settings"' in page and "banner: cookies" in page
    full = await b.snapshot()
    assert full.startswith("unchanged")   # minimal and actions share the same baseline


async def test_annotated_screenshot_leaves_no_trace(b, base):
    await b.open(base + "/signup.html")
    plain = await b.screenshot()
    marked = await b.screenshot(annotate=True)
    assert marked[:4] == b"\x89PNG" and marked != plain
    assert not await b.session.cur.page.evaluate("!!document.getElementById('__lab_marks')")
    assert (await b.snapshot()).startswith("unchanged")   # the overlay never shows up in snapshots
