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


async def _session(base, engine, keep=False, **kw):
    if not keep:
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


@pytest.fixture
def keystore(tmp_path, monkeypatch):
    monkeypatch.setenv("LEANB_STATE_DIR", str(tmp_path / "state"))
    return tmp_path / "state" / "action_keys.json"


async def test_action_key_blocks_a_repeat_in_a_new_session(s, keystore):
    out = await s.open(s.base + "/order.html")
    res = await s.act("click", idof(out, 'button "Place order"'), key="order-1")
    assert res.startswith("status: verified"), res
    assert oct(keystore.stat().st_mode & 0o777) == "0o600"
    saved = json.loads(keystore.read_text())["order-1"]
    assert saved["status"] == "verified" and saved["url"].endswith("/order.html")
    bm2, s2 = await _session(s.base, s.engine, keep=True)
    try:
        out = await s2.open(s.base + "/order.html")
        place = idof(out, 'button "Place order"')
        preview = await s2.act("click", place, key="order-1", dry_run=True)
        assert json.loads(preview)["requires_confirmation"] is True
        with pytest.raises(ActionError, match=r'duplicate: key "order-1" was already used .*status: verified'):
            await s2.act("click", place, key="order-1")
        assert s2.last_outcome["status"] == "blocked" and s2.last_outcome["executed"] is False
        assert len(subs(s.base, "order")) == 1
        await s2.act("click", place)  # no key: the old per-session guard only, so it runs
        assert len(subs(s.base, "order")) == 2
        out = await s2.open(s.base + "/order.html")
        res = await s2.act("click", idof(out, 'button "Place order"'), "repeat", key="order-1")
        assert res.startswith("status: verified") and len(subs(s.base, "order")) == 3
    finally:
        await bm2.close()


async def test_action_key_does_not_block_after_blocked_or_unverified(s, keystore):
    out = await s.open(s.base + "/login.html")
    u, p = idof(out, 'textbox "Username"'), idof(out, 'textbox "Password"')
    res = await s.fill_form({u: "demo", p: "nope"}, submit=True, key="login-1")
    assert res.startswith("status: blocked"), res
    assert json.loads(keystore.read_text())["login-1"]["status"] == "blocked"
    bm2, s2 = await _session(s.base, s.engine, keep=True)
    try:
        out = await s2.open(s.base + "/login.html")
        u, p = idof(out, 'textbox "Username"'), idof(out, 'textbox "Password"')
        res = await s2.fill_form({u: "demo", p: "demo-pass-123"}, submit=True, key="login-1")
        assert res.startswith("status: verified"), res
        out = await s.open(s.base + "/login.html")  # back in the first session: only the key blocks it now
        u, p = idof(out, 'textbox "Username"'), idof(out, 'textbox "Password"')
        with pytest.raises(ActionError, match='duplicate: key "login-1"'):
            await s.fill_form({u: "demo", p: "demo-pass-123"}, submit=True, key="login-1")
        res = await s.fill_form({u: "demo", p: "demo-pass-123"}, submit="repeat", key="login-1")
        assert res.startswith("status: verified"), res
        assert len(subs(s.base, "login")) == 3  # the rejected try, the first real login and the repeat
    finally:
        await bm2.close()


def test_action_key_store_expiry_and_strongest_result(tmp_path):
    import time
    from lean_browser.action_keys import ActionKeys
    ks = ActionKeys(tmp_path)
    ks.record("a", "unverified", "https://x/")
    assert ks.get("a")["status"] == "unverified" and ks.blocking("a") is None
    ks.record("a", "timed_out", "https://x/")
    ks.record("a", "blocked", "https://x/")  # a weaker later result never erases a blocking one
    assert ks.blocking("a")["status"] == "timed_out"
    data = json.loads(ks.path.read_text())
    data["a"]["time"] = time.time() - 25 * 3600
    ks.path.write_text(json.dumps(data))
    assert ks.get("a") is None
    ks.path.write_text("not json")
    assert ks.get("a") is None


async def test_action_key_different_keys_and_omitted_key(s, keystore):
    out = await s.open(s.base + "/order.html")
    assert (await s.act("click", idof(out, 'button "Place order"'), key="order-a")).startswith("status: verified")
    bm2, s2 = await _session(s.base, s.engine, keep=True)
    try:
        out = await s2.open(s.base + "/order.html")
        res = await s2.act("click", idof(out, 'button "Place order"'), key="order-b")  # a different key is a new order
        assert res.startswith("status: verified"), res
        assert set(json.loads(keystore.read_text())) == {"order-a", "order-b"}
    finally:
        await bm2.close()
    assert len(subs(s.base, "order")) == 2


async def test_action_key_claim_released_or_kept_after_an_error(s, keystore, monkeypatch):
    """After the key is claimed, an error that sent nothing releases it; an error after dispatch keeps it as
    ambiguous, so a blind retry with the same key is blocked."""
    out = await s.open(s.base + "/order.html")
    place = idof(out, 'button "Place order"')
    real_perform = s._perform_guarded

    async def refused(*a, **k):
        s.last_outcome = {"executed": False, "status": "blocked"}
        raise ActionError("target went away before dispatch")
    monkeypatch.setattr(s, "_perform_guarded", refused)
    with pytest.raises(ActionError, match="went away"):
        await s.act("click", place, key="order-x")
    assert "order-x" not in json.loads(keystore.read_text())

    async def broke(*a, **k):
        s.last_outcome = None
        raise RuntimeError("engine crashed mid-click")
    monkeypatch.setattr(s, "_perform_guarded", broke)
    with pytest.raises(RuntimeError):
        await s.act("click", place, key="order-x")
    assert json.loads(keystore.read_text())["order-x"]["status"] == "ambiguous"
    # Restore only the dispatch; monkeypatch.undo() would also drop LEANB_STATE_DIR and read the real store.
    monkeypatch.setattr(s, "_perform_guarded", real_perform)
    with pytest.raises(ActionError, match='duplicate: key "order-x"'):
        await s.act("click", place, key="order-x")
    assert len(subs(s.base, "order")) == 0


def _claim_worker(args):
    directory, key = args
    from lean_browser.action_keys import ActionKeys
    return ActionKeys(directory).claim(key, "https://shop.example/checkout") is None


def test_action_key_concurrent_claims_exactly_one_wins(tmp_path):
    """Eight processes race to claim one key: exactly one may dispatch, the rest see it in use."""
    import multiprocessing as mp
    from lean_browser.action_keys import ActionKeys
    with mp.get_context("spawn").Pool(8) as pool:
        won = pool.map(_claim_worker, [(str(tmp_path), "pay-42")] * 8)
    assert won.count(True) == 1, won
    ks = ActionKeys(tmp_path)
    assert ks.get("pay-42")["status"] == "in_progress"
    ks.record("pay-42", "verified", "https://shop.example/checkout")
    assert ks.claim("pay-42", "https://shop.example/checkout")["status"] == "verified"
    assert ks.claim("pay-42", "https://shop.example/checkout", repeat=True) is None  # repeat reserves anyway
    ks.release("pay-42")
    assert ks.get("pay-42")["status"] == "verified"  # releasing a repeat claim restores the earlier result


def test_action_key_stale_claim_expires(tmp_path):
    import time
    from lean_browser.action_keys import IN_PROGRESS_TTL_S, ActionKeys
    ks = ActionKeys(tmp_path)
    assert ks.claim("k", "u") is None
    assert ks.claim("k", "u")["status"] == "in_progress"
    data = json.loads(ks.path.read_text())
    data["k"]["time"] = time.time() - IN_PROGRESS_TTL_S - 1  # left behind by a crashed process
    ks.path.write_text(json.dumps(data))
    assert ks.claim("k", "u") is None


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


# ---------- found by the 100-task benchmark ----------

def rowid(out, role_name, row):
    m = re.search(rf'(\d+): {role_name} \(in "{re.escape(row)}', out)
    assert m, out
    return int(m.group(1))


async def test_reordered_list_keeps_ids_with_their_rows(s):
    """A list that re-renders in a new order must not move an id to another row's button."""
    out = await s.open(s.base + "/b/leave.html")
    nisha = rowid(out, 'button "Approve"', "Nisha Gupta")
    await s.cur.page.wait_for_timeout(1700)  # the page re-renders (reversed) every 1.5 s
    res = await s.act("click", nisha)
    assert "Approved Nisha Gupta" in res, res
    assert [x["fields"] for x in subs(s.base, "leave")] == [{"name": "Nisha Gupta", "decision": "approve"}]


async def test_switch_state_comes_from_aria_checked(s):
    out = await s.open(s.base + "/b/security.html")
    assert 'switch "Marketing emails" on' in out and 'switch "Two-factor authentication" off' in out, out
    res = await s.act("click", idof(out, 'switch "Two-factor authentication"'))
    assert res.startswith("status: verified") and 'switch "Two-factor authentication" on' in res, res


async def test_sliders_are_set_and_verified(s):
    out = await s.open(s.base + "/b/display.html")
    assert 'slider "Brightness" = 50% (0-100)' in out, out
    res = await s.act("fill", idof(out, 'slider "Brightness"'), "30")
    assert res.startswith("status: verified (slider at 30)"), res
    with pytest.raises(ActionError, match="step"):
        await s.act("fill", idof(out, 'slider "Brightness"'), "33")
    out = await s.open(s.base + "/b/alerts.html")
    res = await s.act("fill", idof(out, 'slider "Alert volume"'), "70")
    assert res.startswith("status: verified (slider at 70)"), res
    assert await s.cur.page.input_value("#vol") == "70"


async def test_accordion_buttons_in_headings_show_what_they_open(s):
    out = await s.open(s.base + "/b/faq.html")
    q = idof(out, r'button "Do you ship internationally\?" \[closed\]')
    res = await s.act("click", q)
    assert '[open] -> "Yes, we ship to 38 countries.' in res, res


async def test_frames_obscura_cannot_drive_go_to_chromium(s):
    for page, why in (("/b/poll.html", "srcdoc-iframe"), ("/b/track.html", "nested-iframe")):
        out = await s.open(s.base + page)
        if s.engine == "obscura":
            assert f"engine: chromium (routed: {why})" in out, out
        assert "[frame:" in out, out
