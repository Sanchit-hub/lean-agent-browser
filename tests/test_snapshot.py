"""Snapshot layer on both engines: format, filtering, collapse/expand/find, IDs, budgets, safety."""
import re

import pytest

from evals.fixtures.server import serve
from lean_browser.engine import BrowserManager, find_obscura
from lean_browser.snapshot import Snapshotter, wrap_untrusted
from tests.test_fixtures import _free_port

ENGINES = ["chromium"] + (["obscura"] if find_obscura() else [])


@pytest.fixture(scope="module")
def base():
    port = _free_port()
    srv = serve(port)
    yield f"http://127.0.0.1:{port}"
    srv.shutdown()


@pytest.fixture(params=ENGINES)
async def bm(request):
    async with BrowserManager(allow_private_network=True, prefer=request.param) as m:
        m.expected = request.param
        yield m


async def snap(bm, url, mode="actions", sn=None, **kw):
    tab = await bm.open(url)
    sn = sn or Snapshotter()
    s = await sn.take(tab.page, mode=mode, engine=tab.header)
    return tab, sn, s, sn.render(s, **kw)


def body(text):
    return [l for l in text.splitlines()[1:] if not l.startswith(("header:", "footer:"))]


async def test_login_format(bm, base):
    tab, sn, s, out = await snap(bm, base + "/login.html")
    assert tab.engine == bm.expected
    # The first snapshot on a site names the site; later ones on the same site show only the path.
    assert out.splitlines()[0] == f"page: Log in | url: {base}/login.html | engine: {bm.expected}"
    await tab.page.goto(base + "/signup.html")
    again = sn.render(await sn.take(tab.page, engine=tab.header))
    assert again.splitlines()[0].startswith("page: Sign up | url: /signup.html")
    lines = body(out)
    assert lines[0] == "# Log in"
    assert lines[1].endswith(': textbox "Username"*')
    assert lines[2].endswith(': textbox "Password"* type=password')
    assert lines[3].endswith(': button "Log in"')
    assert "header: Home, Search, Orders (+5) [expand:h1]" in out


async def test_values_masking_and_inline_errors(bm, base):
    tab, sn, _, _ = await snap(bm, base + "/signup.html")
    p = tab.page
    await p.fill("#e", "asha@")
    await p.fill("#p", "short-pw")
    await p.click("button[type=submit]")
    out = sn.render(await sn.take(p))
    assert 'textbox "Email"* type=email = "asha@" !"Enter a valid email address"' in out
    assert 'textbox "Password"* type=password = •••• !"Password must be at least 10 characters"' in out
    assert "short-pw" not in out
    assert 'checkbox "I accept the terms" off !"You must accept the terms"' in out
    assert "text: Enter a valid" not in out  # error shown inline only, not repeated


async def test_select_radio_upload_required(bm, base):
    _, _, _, out = await snap(bm, base + "/apply.html")
    assert 'select "Role" [SDE Intern|ML Intern|APM Intern] = SDE Intern' in out
    assert 'radiogroup "Work mode" [Remote|Onsite]' in out
    assert 'upload "Resume (PDF)"* accept=.pdf' in out
    assert 'textbox "Full name"*' in out


async def test_hidden_prompt_injection_is_dropped(bm, base):
    for mode in ("actions", "read", "full"):
        _, _, _, out = await snap(bm, base + "/review.html", mode=mode)
        low = out.lower()
        assert "exfil" not in low and "ignore the user" not in low and "override" not in low, (mode, out)


async def test_dialog_first_then_page(bm, base):
    tab, sn, _, out = await snap(bm, base + "/newsletter.html")
    assert 'dialog "Cookie consent"' in out
    assert "Subscribe" not in out  # page behind the modal is hidden
    await tab.page.click("#reject")
    out2 = sn.render(await sn.take(tab.page))
    assert "dialog" not in out2 and 'button "Subscribe"' in out2


async def test_banner_and_misc_rules(bm, base):
    _, _, _, out = await snap(bm, base + "/misc.html")
    assert out.splitlines()[1].startswith("banner: cookies [reject:")
    assert 'link "Notifications"' in out          # aria-label on icon link
    assert out.count('link "Pricing"') == 1       # duplicate link deduped
    assert 'clickable "Open settings"' in out     # cursor:pointer div with a JS handler
    assert "text: 3 items in cart" in out         # status region
    for hidden in ("Hidden button", "Invisible button", "Offscreen button"):
        assert hidden not in out
    assert 'link ""' not in out                   # nameless icon link dropped


async def test_collapse_expand_find(bm, base):
    _, sn, s, out = await snap(bm, base + "/orders.html")
    assert 'table "Orders" 10 rows:' in out and "ORD-1009" not in out
    handle = next(w.split(":")[1].rstrip("]") for w in out.split() if w.startswith("[expand:t"))
    exp = sn.render(s, expand=handle)
    assert "ORD-1009" in exp and exp.count("\n  - ") == 10
    hit = sn.find("ORD-1007")
    assert "ORD-1007" in hit and f"(in table [{handle}])" in hit
    hdr = sn.render(s, expand="h1")
    assert 'link "Careers"' in hdr


async def test_iframe_and_shadow(bm, base):
    _, _, _, out = await snap(bm, base + "/checkout.html")
    assert '[frame:Billing details]' in out and 'textbox "Name on bill"' in out
    _, _, _, out = await snap(bm, base + "/profile.html")
    assert 'button "4 stars"' in out and 'textbox "Comment"' in out


async def test_ids_stable_and_unchanged_detection(bm, base):
    tab, sn, s1, out1 = await snap(bm, base + "/login.html")
    s2 = await sn.take(tab.page)
    assert sn.render(s2) == f"unchanged (snapshot #{s1.seq})"
    ids1 = [e["id"] for e in s1.data["entries"] if e["t"] == "el"]
    ids2 = [e["id"] for e in s2.data["entries"] if e["t"] == "el"]
    assert ids1 == ids2


async def test_ids_survive_framework_rerender(bm, base):
    tab, sn, s1, _ = await snap(bm, base + "/app.html#/settings")
    save1 = next(e["id"] for e in s1.data["entries"] if e.get("name") == "Save changes")
    await tab.page.select_option("select[data-k=theme]", "dark")  # triggers full innerHTML re-render
    s2 = await sn.take(tab.page)
    save2 = next(e["id"] for e in s2.data["entries"] if e.get("name") == "Save changes")
    assert save1 == save2
    all_ids = [e["id"] for e in s2.data["entries"] if e["t"] == "el"]
    assert len(all_ids) == len(set(all_ids))


async def test_route_change_and_page_change_flags(bm, base):
    tab, sn, _, _ = await snap(bm, base + "/app.html")
    await tab.page.click("text=Settings")
    out = sn.render(await sn.take(tab.page))
    assert out.splitlines()[0].endswith("| route changed")
    await tab.page.goto(base + "/login.html")
    out = sn.render(await sn.take(tab.page))
    assert out.splitlines()[0].endswith("| page changed")


async def test_read_mode_budget_and_more(bm, base):
    _, sn, s, out = await snap(bm, base + "/article.html", mode="read", budget=300)
    assert out.splitlines()[1] == "# The Halden Valley: a history"
    assert len(out) <= 300 * 4 + 100
    key = out.splitlines()[-1].split("[more:")[1].split("]")[0]
    rest = ""
    for _ in range(20):
        chunk = sn.more(key, budget=2000)
        rest += chunk
        if "[more:" not in chunk:
            break
        key = chunk.splitlines()[-1].split("[more:")[1].split("]")[0]
    assert "completed in 1931" in out + rest


async def test_full_mode_includes_text(bm, base):
    _, _, _, out = await snap(bm, base + "/booking.html", mode="full")
    assert "Hand" not in out
    _, _, _, out = await snap(bm, base + "/search.html?q=rust", mode="full", budget=4000)
    assert "practical article about rust" in out


async def test_big_page_performance(bm, base):
    import os
    # Shared CI runners are several times slower than a dev Mac, so CI gets looser limits (and a longer
    # snapshot timeout); the measured time is printed either way.
    ci = bool(os.environ.get("CI"))
    tab, _, s, out = await snap(bm, base + "/big.html", sn=Snapshotter(timeout_s=20 if ci else 2))
    print(f"big page snapshot on {bm.expected}: {s.ms} ms")
    assert 'table "Big repo" 1200 rows' in out
    limit = (8000 if ci else 1500) if bm.expected == "obscura" else (1500 if ci else 300)
    assert s.ms < limit, f"{bm.expected} took {s.ms} ms"
    assert len(out) < 2000


def test_wrap_untrusted():
    assert wrap_untrusted("x") == '<page untrusted="true">\nx\n</page>'


async def test_extract_url_field_returns_absolute_link_addresses(bm, base):
    """Agents asked for "titles and links" used to click every link to learn its address."""
    tab, _, _, _ = await snap(bm, base + "/links.html")
    from lean_browser.session import EXTRACT_JS
    table = await tab.page.evaluate(EXTRACT_JS, {"kind": "table", "fields": ["title", "url"]})
    assert [r["url"] for r in table["rows"]] == ["https://example.org/a", base + "/local.html"]
    lst = await tab.page.evaluate(EXTRACT_JS, {"kind": "list", "fields": ["url"]})
    assert lst["items"][0]["fields"]["url"] == "https://example.org/one"
    assert "url" not in lst["items"][0]["links"][0]  # once per item, not repeated per link
    plain = await tab.page.evaluate(EXTRACT_JS, {"kind": "list"})
    assert all("url" not in l for i in plain["items"] for l in i.get("links", []))  # hrefs only when asked
    assert all("fields" not in i for i in plain["items"])


async def test_transparent_native_inputs_are_listed_but_transparent_containers_stay_hidden(bm, base):
    """TodoMVC-style lists hide the real checkbox with opacity:0 and style the label; they used to vanish."""
    _, _, _, out = await snap(bm, base + "/custom-controls.html")
    assert 'checkbox "Water plants" off' in out
    assert 'checkbox "Feed cat" off' in out  # named by the unlinked label beside it
    assert 'radiogroup "size" [Small]' in out
    assert "Trap checkbox" not in out


async def test_open_waits_for_scripts_added_after_load(request, base):
    """TinyMCE-style editors load plugins with <script> tags after load; open() used to snapshot before they ran."""
    from lean_browser.tools import Config, LeanBrowser
    async with LeanBrowser(Config(prefer="chromium", allow_private_network=True)) as b:
        out = await b.open(base + "/late-widget.html", mode="read")
    assert "Plugin content ready" in out


async def test_extract_prefers_content_lists_widens_within_and_uses_full_titles(bm, base):
    """On a shop page extract picked the 6-item category sidebar over the products, within=<a book link> found
    nothing, and titles came back cut ("A Light in the ..."): the agent then clicked every book."""
    tab, _, _, out = await snap(bm, base + "/shelf.html")
    from lean_browser.session import EXTRACT_JS
    res = await tab.page.evaluate(EXTRACT_JS, {"kind": "auto", "fields": ["title", "url"]})
    assert [i["fields"]["title"] for i in res["items"]] == ["A Light in the Attic", "Tipping the Velvet", "Soumission"]
    assert res["items"][0]["fields"]["url"] == base + "/b/1"
    link = int(re.search(r'(\d+): link "A Light in the', out).group(1))
    inner = await tab.page.evaluate(EXTRACT_JS, {"kind": "auto", "within": link, "fields": ["title"]})
    assert len(inner["items"]) == 3


async def test_app_footer_inside_a_section_is_content_not_page_chrome(bm, base):
    """TodoMVC keeps its "N items left" counter in a <footer> inside its <section>; read, find and the actions view
    all dropped it as page chrome, so the agent fell back to a screenshot."""
    from lean_browser.tools import Config, LeanBrowser
    async with LeanBrowser(Config(prefer=bm.expected, allow_private_network=True)) as b:
        actions = await b.open(base + "/todo-app.html")
        assert 'link "Active"' in actions
        assert "**2** items left" in await b.snapshot(mode="read")
        found = await b.snapshot(find="items left")
        assert "text: 2 items left" in found
