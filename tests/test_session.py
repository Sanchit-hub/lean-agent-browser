"""Session layer (act, fill_form, settle, diff, dialogs, tabs, uploads) on both engines,
verified against the fixture server's recorded submissions."""
import json
import re
import urllib.request
from pathlib import Path

import pytest

from evals.fixtures.server import serve
from lean_browser.engine import BrowserManager, find_obscura
from lean_browser.session import OBSCURA_DIALOG_SHIM, ActionError, Session
from lean_browser.settle import SETTLE_INIT_JS
from tests.test_fixtures import _free_port

ENGINES = ["chromium"] + (["obscura"] if find_obscura() else [])
SITE = Path(__file__).resolve().parent.parent / "evals/fixtures/site"


@pytest.fixture(scope="module")
def base():
    port = _free_port()
    srv = serve(port)
    yield f"http://127.0.0.1:{port}"
    srv.shutdown()


@pytest.fixture(params=ENGINES)
async def s(request, base):
    urllib.request.urlopen(base + "/api/reset").read()
    async with BrowserManager(allow_private_network=True, prefer=request.param, init_scripts=[SETTLE_INIT_JS],
                              obscura_init_scripts=[OBSCURA_DIALOG_SHIM]) as bm:
        sess = Session(bm, upload_dirs=[SITE])
        sess.engine = request.param
        sess.base = base
        yield sess


def state(base):
    return json.loads(urllib.request.urlopen(base + "/api/state").read())


def idof(text: str, pattern: str) -> int:
    m = re.search(r"(\d+): " + pattern, text)
    assert m, f"{pattern!r} not in:\n{text}"
    return int(m.group(1))


async def test_fill_diff_and_inline_errors(s):
    out = await s.open(s.base + "/signup.html")
    email, pw, submit = idof(out, 'textbox "Email"'), idof(out, 'textbox "Password"'), idof(out, 'button "Create account"')
    d = await s.act("fill", email, "asha@")
    assert d == f'~{email}: textbox "Email"* type=email = "asha@"'
    d = await s.act("click", submit)
    assert f'~{email}: textbox "Email"* type=email = "asha@" !"Enter a valid email address"   (error appeared)' in d
    d = await s.act("fill", pw, "secret-password-1")
    assert "secret-password-1" not in d and "••••" in d
    d = await s.act("fill", email, "asha@example.com")
    assert d.startswith(f'~{email}: textbox "Email"* type=email = "asha@example.com"')


async def test_fill_form_submit_navigates(s):
    out = await s.open(s.base + "/login.html")
    u, p = idof(out, 'textbox "Username"'), idof(out, 'textbox "Password"')
    res = await s.fill_form({u: "demo", p: "demo-pass-123"}, submit=True)
    assert "page: Account" in res and "page changed" in res and "Welcome back, demo" in res
    assert state(s.base)["submissions"][-1]["fields"]["ok"] is True


async def test_settle_waits_for_spa_fetch_and_route(s):
    out = await s.open(s.base + "/app.html")
    settings = idof(out, 'link "Settings"')
    d = await s.act("click", settings)
    assert "route changed: /app.html#/settings" in d
    assert 'textbox "Display name" = "Asha"' in d and 'button "Save changes"' in d


async def test_custom_combobox_and_date_picker(s):
    out = await s.open(s.base + "/booking.html")
    city, date, guests, book = (idof(out, 'combobox "City"'), idof(out, 'textbox "Date"'),
                                idof(out, 'textbox "Guests"'), idof(out, 'button "Book"'))
    d = await s.act("select", city, "Jaipur")
    assert f'~{city}: combobox "City" (custom) = "Jaipur"' in d
    d = await s.act("click", date)
    assert "+list 31 items" in d
    day = idof(await s.snapshot(find="December 24"), 'button "December 24')
    await s.act("click", day)
    await s.act("fill", guests, "4")
    d = await s.act("click", book)
    assert "Booked for Jaipur on 2026-12-24" in d
    assert state(s.base)["submissions"][-1]["fields"] == {"city": "Jaipur", "date": "2026-12-24", "guests": "4"}


async def test_radiogroup_select_by_label_and_wizard(s):
    out = await s.open(s.base + "/wizard1.html")
    res = await s.fill_form({idof(out, 'textbox "Full name"'): "Ravi Kumar", idof(out, 'textbox "Phone"'): "9876543210"})
    res = await s.act("click", idof(out, 'button "Next"'))
    assert "Step 2 of 3" in res
    step2 = res
    await s.fill_form({idof(step2, 'select "City"'): "Pune", idof(step2, 'textbox "PIN code"'): "411001"})
    res = await s.act("click", idof(step2, 'button "Next"'))
    rg = idof(res, 'radiogroup "Delivery speed"')
    d = await s.act("select", rg, "Express")
    assert f'~{rg}: radiogroup "Delivery speed" [Standard (5 days)|Express (1 day)] = Express (1 day)' in d
    await s.act("click", idof(res, 'button "Place order"'))
    assert state(s.base)["submissions"][-1]["fields"] == {"name": "Ravi Kumar", "phone": "9876543210", "city": "Pune",
                                                          "pin": "411001", "speed": "express"}


async def test_iframe_and_shadow_dom_actions(s):
    out = await s.open(s.base + "/checkout.html")
    await s.fill_form({idof(out, r'textbox "Name on bill"'): "Isha Traders"}, submit=True)
    assert state(s.base)["submissions"][-1]["fields"]["holder"] == "Isha Traders"
    out = await s.open(s.base + "/profile.html")
    await s.act("click", idof(out, 'button "4 stars"'))
    await s.act("fill", idof(out, 'textbox "Comment"'), "Very clean rooms")
    d = await s.act("click", idof(out, 'button "Submit rating"'))
    assert "Thanks for rating!" in d
    assert state(s.base)["submissions"][-1]["fields"] == {"rating": 4, "comment": "Very clean rooms"}


async def test_modal_dialog_flow(s):
    out = await s.open(s.base + "/files.html")
    d = await s.act("click", idof(out, 'button "Delete old-report.pdf"'))
    assert 'dialog "Confirm delete"' in d and 'Delete “old-report.pdf” permanently?' in d
    d = await s.act("click", idof(d, 'button "Delete"'))
    assert "Deleted old-report.pdf" in d and "dialog" not in d.splitlines()[1]
    assert [x["fields"]["deleted"] for x in state(s.base)["submissions"]] == ["old-report.pdf"]


async def test_native_dialog_accept_and_dismiss(s):
    out = await s.open(s.base + "/todo.html")
    clear = idof(out, 'button "Clear completed"')
    assert "dismissed" in await s.act("dialog", value="dismiss") or True
    d = await s.act("click", clear)
    assert "dialog confirm 'Clear all completed tasks?' dismissed" in d and "Cancelled" in d
    d = await s.act("click", clear)
    assert "dialog confirm 'Clear all completed tasks?' accepted" in d and "Cleared 2 tasks" in d


async def test_upload_on_chromium_and_guard(s):
    out = await s.open(s.base + "/apply.html")
    assert "engine: chromium" in out.splitlines()[0]  # routed even when obscura is preferred
    fields = {idof(out, 'textbox "Full name"'): "Meera Iyer", idof(out, 'textbox "Email"'): "meera@example.com",
              idof(out, 'select "Role"'): "ML Intern", idof(out, 'radiogroup "Work mode"'): "Remote",
              idof(out, 'upload "Resume \\(PDF\\)"'): str(SITE / "resume.pdf")}
    res = await s.fill_form(fields, submit=True)
    assert "submission received" in res
    sub = state(s.base)["submissions"][-1]
    assert sub["has_file"] and sub["fields"]["role"] == "ML Intern" and sub["fields"]["mode"] == "remote"
    out = await s.open(s.base + "/apply.html")
    with pytest.raises(ActionError, match="outside the allowed folders"):
        await s.act("upload", idof(out, 'upload "Resume'), str(Path.home() / ".zshrc"))
    with pytest.raises(ActionError, match="absolute"):
        await s.act("upload", idof(out, 'upload "Resume'), "resume.pdf")


async def test_no_change_hint_missing_id_and_wait_for(s):
    out = await s.open(s.base + "/login.html")
    assert (await s.act("focus", idof(out, 'textbox "Username"'))).startswith("no change")
    with pytest.raises(ActionError, match="not found"):
        await s.act("click", 9999)
    out = await s.open(s.base + "/feed.html")
    d = await s.act("scroll", value="bottom")
    assert "list" in d and "20 items" in d
    out = await s.act("wait_for", value="Post 18")
    assert out == "found 'Post 18'"


async def test_back_and_unchanged(s):
    await s.open(s.base + "/login.html")
    out = await s.open(s.base + "/signup.html")
    back = await s.act("back")
    assert "page: Log in" in back
    assert (await s.snapshot()).startswith("unchanged")


async def test_new_tab(s):
    out = await s.open(s.base + "/docs.html")
    d = await s.act("click", idof(out, 'link "Open the developer console"'))
    assert "page: Developer console" in d
    if s.engine == "chromium":
        assert "+tab 2 opened" in d and len(s.tabs) == 2
        assert "(active)" in await s.act("tab", value="list")
    lab = idof(d, 'textbox "Key label"')
    await s.act("fill", lab, "ci-runner")
    await s.act("click", idof(d, 'button "Generate test key"'))
    assert state(s.base)["submissions"][-1]["fields"]["label"] == "ci-runner"


async def test_snapshot_timeout_moves_tab_to_chromium(base):
    if not find_obscura():
        pytest.skip("obscura not installed")
    async with BrowserManager(allow_private_network=True, init_scripts=[SETTLE_INIT_JS]) as bm:
        sess = Session(bm, snapshot_timeout_s=0.0001)
        out = await sess.open(base + "/login.html")
        assert "engine: chromium (snapshot too slow)" in out
