"""v0.3 reliability and trust: evidence-backed outcomes, duplicate protection, dry-run, safe recovery.
Runs on both engines against the fixture server; side effects are checked server-side."""
import json
import re
import urllib.request

import pytest

from evals.fixtures.server import serve
from lean_browser.engine import BrowserManager, find_obscura
from lean_browser.session import OBSCURA_DIALOG_SHIM, ActionError, Session, error_category, retry_safety
from lean_browser.settle import SETTLE_INIT_JS
from tests.test_fixtures import _free_port
from tests.test_session import SITE, idof

ENGINES = ["chromium"] + (["obscura"] if find_obscura() else [])


@pytest.fixture(scope="module")
def base():
    port = _free_port()
    srv = serve(port)
    yield f"http://127.0.0.1:{port}"
    srv.shutdown()


async def _session(base, engine, **kw):
    urllib.request.urlopen(base + "/api/reset").read()
    bm = BrowserManager(allow_private_network=True, prefer=engine, init_scripts=[SETTLE_INIT_JS],
                        obscura_init_scripts=[OBSCURA_DIALOG_SHIM])
    await bm.start()
    sess = Session(bm, upload_dirs=[SITE], **kw)
    sess.base = base
    return bm, sess


@pytest.fixture(params=ENGINES)
async def s(request, base):
    bm, sess = await _session(base, request.param)
    sess.engine = request.param
    yield sess
    await bm.close()


def subs(base, task=None):
    st = json.loads(urllib.request.urlopen(base + "/api/state").read())["submissions"]
    return [x for x in st if task is None or x["task"] == task]


async def events(s) -> int:
    return await s.cur.page.evaluate("window.__events")


# ---------- A. verification ----------

async def test_rejected_login_is_blocked_not_verified(s):
    out = await s.open(s.base + "/login.html")
    u, p = idof(out, 'textbox "Username"'), idof(out, 'textbox "Password"')
    res = await s.fill_form({u: "demo", p: "wrong-password"}, submit=True)
    assert res.startswith("status: blocked"), res
    assert "Invalid username or password" in res.splitlines()[0]
    o = s.last_outcome
    assert o["executed"] is True and o["status"] == "blocked" and o["retry_safety"] == "unsafe"
    assert any("Invalid username" in e for e in o["evidence"])


async def test_server_rejection_after_navigation_is_blocked(s):
    out = await s.open(s.base + "/signup.html")
    ids = [idof(out, f'textbox "{n}"') for n in ("Username", "Email", "Password", "Confirm password")]
    terms = idof(out, 'checkbox "I accept the terms"')
    res = await s.fill_form({ids[0]: "asha", ids[1]: "asha@example.com", ids[2]: "long-password-1",
                             ids[3]: "long-password-1", terms: "true"}, submit=True)
    assert res.startswith("status: blocked") and "already taken" in res.splitlines()[0], res
    assert not subs(s.base, "signup")


async def test_success_needs_a_real_signal(s):
    out = await s.open(s.base + "/order.html")
    place = idof(out, 'button "Place order"')
    res = await s.act("click", place)
    assert res.startswith('status: verified (success message "Order #1 placed.'), res
    assert len(subs(s.base, "order")) == 1


async def test_submit_like_click_with_no_effect_is_unverified(s):
    out = await s.open(s.base + "/order.html")
    res = await s.act("click", idof(out, 'button "Apply coupon"'))
    assert res.startswith("status: unverified (no visible change)"), res
    assert s.last_outcome["status"] == "unverified"


async def test_expect_postcondition(s):
    out = await s.open(s.base + "/order.html")
    place = idof(out, 'button "Place order"')
    res = await s.act("click", place, expect="Confirmation sent")
    assert res.startswith("status: verified") and "expected text 'Confirmation sent' found" in res.splitlines()[0]
    out = await s.open(s.base + "/order.html")
    res = await s.act("click", idof(out, 'button "Apply coupon"'), expect="Coupon applied")
    assert res.startswith("status: unverified") and "not seen" in res.splitlines()[0], res
    res = await s.act("fill", idof(out, 'textbox "Quantity"'), "3", expect="url:/order.html")
    assert res.startswith("status: verified (value set; expected url contains '/order.html')"), res


async def test_slow_submit_times_out_honestly_and_is_not_repeated(base):
    for engine in ENGINES:
        bm, s = await _session(base, engine, settle_cap_s=2.0)
        try:
            out = await s.open(base + "/order.html")
            send = idof(out, 'button "Send message"')
            res = await s.act("click", send)
            first = res.splitlines()[0]
            assert first.startswith("status: timed_out") and "check the page before repeating" in first, (engine, res)
            with pytest.raises(ActionError, match="duplicate"):
                await s.act("click", send)
            assert s.last_outcome["status"] == "blocked" and s.last_outcome["executed"] is False
        finally:
            await bm.close()


# ---------- B. duplicate protection and recovery ----------

async def test_duplicate_unsafe_action_is_blocked_until_repeat(s):
    out = await s.open(s.base + "/order.html")
    place = idof(out, 'button "Place order"')
    await s.act("click", place)
    with pytest.raises(ActionError, match=r'duplicate: button "Place order" was already used'):
        await s.act("click", place)
    assert len(subs(s.base, "order")) == 1
    res = await s.act("click", place, "repeat")
    assert res.startswith("status: verified") and len(subs(s.base, "order")) == 2


async def test_duplicate_form_submission_is_blocked(s):
    out = await s.open(s.base + "/login.html")
    u, p = idof(out, 'textbox "Username"'), idof(out, 'textbox "Password"')
    await s.fill_form({u: "demo", p: "demo-pass-123"}, submit=True)
    out = await s.act("back")
    u, p = idof(out, 'textbox "Username"'), idof(out, 'textbox "Password"')
    with pytest.raises(ActionError, match="duplicate: this form was already submitted"):
        await s.fill_form({u: "demo", p: "demo-pass-123"}, submit=True)
    assert len(subs(s.base, "login")) == 1


async def test_blocked_submission_can_be_fixed_and_retried(s):
    out = await s.open(s.base + "/login.html")
    u, p = idof(out, 'textbox "Username"'), idof(out, 'textbox "Password"')
    res = await s.fill_form({u: "demo", p: "nope"}, submit=True)
    assert res.startswith("status: blocked")
    out = await s.open(s.base + "/login.html")
    u, p = idof(out, 'textbox "Username"'), idof(out, 'textbox "Password"')
    res = await s.fill_form({u: "demo", p: "demo-pass-123"}, submit=True)
    assert res.startswith("status: verified"), res


def test_retry_safety_classes():
    sub = {"role": "button", "name": "Create account", "fp": {"form": "f", "sub": 1}}
    assert retry_safety("scroll", None) == "safe"
    assert retry_safety("fill", {"role": "textbox"}) == "conditional"
    assert retry_safety("click", {"role": "link", "name": "Docs"}) == "conditional"
    assert retry_safety("click", sub) == "unsafe"
    assert retry_safety("click", {"role": "button", "name": "Delete account"}) == "unsafe"
    assert retry_safety("press", {"role": "textbox", "fp": {"form": "f"}}, "Enter") == "unsafe"
    assert retry_safety("press", {"role": "textbox", "fp": {"form": "f"}}, "Tab") == "conditional"


async def test_conditional_action_retried_once_after_rerender(s):
    if s.engine != "chromium":
        pytest.skip("Obscura fills through injected JS, which can't be interrupted by a re-render")
    out = await s.open(s.base + "/order.html")
    qty = idof(out, 'textbox "Quantity"')
    # The first focus replaces the field with a fresh copy (as a framework re-render would).
    await s.cur.page.evaluate("""() => { const q = document.getElementById('qty');
        q.addEventListener('focus', () => { const n = q.cloneNode(); n.removeAttribute('data-lab-id'); n.value = '1';
        q.replaceWith(n); }, {once: true}); }""")
    res = await s.act("fill", qty, "4")
    assert res.startswith("status: verified (value set"), res
    assert await s.cur.page.input_value("#qty") == "4"


def test_error_categories():
    assert error_category("id 12 not found (page changed?) — call snapshot()") == "stale"
    assert error_category('ambiguous: id 3 is gone and 2 elements match') == "ambiguous"
    assert error_category('duplicate: button "Pay" was already used') == "blocked"
    assert error_category("timed out waiting for the element to be clickable/visible") == "timeout"
    assert error_category("select needs a value (the option label)") == "invalid"


# ---------- C. dry-run ----------

async def test_dry_run_dispatches_nothing(s):
    out = await s.open(s.base + "/order.html")
    place, qty = idof(out, 'button "Place order"'), idof(out, 'textbox "Quantity"')
    n0 = await events(s)
    prev = json.loads(await s.act("click", place, dry_run=True))
    assert prev == {"executed": False, "action": "click", "value": None,
                    "target": {"id": place, "role": "button", "name": "Place order", "context": prev["target"]["context"]},
                    "recovered": None, "risk": "high", "retry_safety": "unsafe", "requires_confirmation": False,
                    "note": prev["note"]}
    assert "nothing was dispatched" in prev["note"]
    p2 = json.loads(await s.act("fill", qty, "9", dry_run=True))
    assert p2["executed"] is False and p2["retry_safety"] == "conditional"
    p3 = json.loads(await s.act("upload", qty, str(SITE / "resume.pdf"), dry_run=True))
    assert p3["executed"] is False
    assert await events(s) == n0
    assert await s.cur.page.input_value("#qty") == "1"
    assert not subs(s.base, "order")
    assert s.cur.tab.engine == s.engine  # no engine switch for the upload preview
    assert s.last_outcome is None


async def test_dry_run_form_and_confirmation(base):
    for engine in ENGINES:
        bm, s = await _session(base, engine, confirm_risky=True)
        try:
            out = await s.open(base + "/login.html")
            u, p = idof(out, 'textbox "Username"'), idof(out, 'textbox "Password"')
            prev = json.loads(await s.fill_form({u: "demo", p: "demo-pass-123"}, submit=True, dry_run=True))
            assert prev["executed"] is False and prev["submit"] is True and prev["retry_safety"] == "unsafe"
            assert prev["fields"][1]["value"] == "••••"
            assert not subs(base, "login")
            assert await s.cur.page.input_value("input[name=username]") == ""
            out = await s.open(base + "/order.html")
            prev = json.loads(await s.act("click", idof(out, 'button "Place order"'), dry_run=True))
            assert prev["requires_confirmation"] is True
        finally:
            await bm.close()


async def test_dry_run_surfaces_ambiguity(s):
    await s.open(s.base + "/recover.html")
    await s.cur.page.evaluate("""() => { document.getElementById('list').innerHTML = '<li>Draft <button>Remove</button></li>'; }""")
    out = await s.snapshot()
    rm = idof(out, 'button "Remove"')
    # Re-render into two rows identical to the original: nothing tells them apart, so Lean must not guess.
    await s.cur.page.evaluate("""() => { document.getElementById('list').innerHTML =
        '<li>Draft <button>Remove</button></li><li>Draft <button>Remove</button></li>'; }""")
    with pytest.raises(ActionError, match="ambiguous"):
        await s.act("click", rm, dry_run=True)


async def test_prompt_dialog_gets_text(s):
    out = await s.open(s.base + "/b/folders.html")
    rid = int(re.findall(r'(\d+): button "Rename"', out)[1])  # the second folder: "Untitled folder"
    assert "accepted with 'Invoices 2026'" in await s.act("dialog", None, "accept:Invoices 2026")
    res = await s.act("click", rid)
    assert "Renamed to Invoices 2026" in res, res
    assert subs(s.base, "rename")[0]["fields"] == {"old": "Untitled folder", "new": "Invoices 2026"}
    with pytest.raises(ActionError, match="accept:TEXT"):
        await s.act("dialog", None, "maybe")
