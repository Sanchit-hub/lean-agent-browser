"""Verification-honesty fixtures: pages where an action is dispatched but the wanted outcome does or doesn't
happen, built to tempt a false `verified`. Used by tests/test_verification.py and
scripts/verification_matrix.py (no LLM involved). Not agent benchmark tasks.

Each case: (id, path, action, target pattern, value, outcome_happened, note).
"""
from __future__ import annotations

from evals.bench.core import PAGES, POST, shell

CASES: list[tuple[str, str, str, str, str | None, bool, str]] = []


def case(cid, path, action, target, value, happened, note, page):
    PAGES[path] = page
    CASES.append((cid, path, action, target, value, happened, note))


# ---------- the outcome did NOT happen: anything but `verified` is honest ----------

case("spinner-then-error", "/v/spinner.html", "click", 'button "Pay ₹499"', None, False,
     "button replaced by 'Processing…', decline shown 2.5 s later",
     shell("Pay", "<main><h1>Invoice 88</h1><div id='box'><button id='pay'>Pay ₹499</button></div><p id='out' role='status'></p></main>",
           """document.getElementById('pay').onclick = () => {
  document.getElementById('box').innerHTML = '<p>Processing…</p>';
  setTimeout(() => { document.getElementById('box').innerHTML = '<p>Card declined. No money was taken.</p>'; }, 2500); };"""))

case("negated-success", "/v/not-saved.html", "click", 'button "Save changes"', None, False,
     "status says 'Your changes were not saved.'",
     shell("Settings", "<main><h1>Settings</h1><label>Nickname <input value='Ravi'></label><button id='s'>Save changes</button>"
           "<p id='out' role='status'></p></main>",
           "document.getElementById('s').onclick = () => { document.getElementById('out').textContent = 'Your changes were not saved.'; };"))

case("negated-success-2", "/v/not-sent.html", "click", 'button "Send message"', None, False,
     "status says 'Message wasn't sent'",
     shell("Message", "<main><h1>Message Priya</h1><label>Message <textarea>Hi</textarea></label><button id='s'>Send message</button>"
           "<p id='out' role='status'></p></main>",
           "document.getElementById('s').onclick = () => { document.getElementById('out').textContent = \"Message wasn't sent. Check your connection.\"; };"))

_SILENT_FORM = ("<main><h1>Change email</h1><form method='post' action='/v/api/silent'><label>New email <input name='email'></label>"
                "<button type='submit'>Update email</button></form></main>")
POST["/v/api/silent"] = lambda f, st: (200, shell("Change email", _SILENT_FORM), None)
case("same-page-reload", "/v/silent.html", "click", 'button "Update email"', None, False,
     "server answers the POST with the same empty form, no message",
     shell("Change email", _SILENT_FORM))

case("ticker-updated", "/v/ticker.html", "click", 'button "Submit feedback"', None, False,
     "button does nothing; a live 'Last updated' clock ticks every 400 ms",
     shell("Feedback", "<main><h1>Feedback</h1><p role='status' id='clock'>Last updated 0s ago</p>"
           "<form onsubmit='return false'><label>Feedback <textarea name='t'>Great</textarea></label>"
           "<button type='submit'>Submit feedback</button></form></main>",
           "let n = 0; setInterval(() => { document.getElementById('clock').textContent = `Last updated ${++n}s ago`; }, 400);"))

case("confirm-then-nothing", "/v/confirm-fail.html", "click", 'button "Delete project"', None, False,
     "confirm() accepted, then the delete silently does nothing",
     shell("Project", "<main><h1>Project Atlas</h1><button id='d'>Delete project</button><p id='out' role='status'></p></main>",
           "document.getElementById('d').onclick = () => { if (!confirm('Delete Atlas?')) return; /* request failed silently */ };"))

PAGES["/v/pay-failed.html"] = shell("Payment", "<main><h1>Payment failed</h1><p>Your bank declined the payment.</p></main>")
case("new-tab-failure", "/v/order-tab.html", "click", 'button "Place order"', None, False,
     "opens a new tab that says the payment failed",
     shell("Checkout", "<main><h1>Checkout</h1><p>Total ₹1,200</p><button id='p'>Place order</button></main>",
           "document.getElementById('p').onclick = () => window.open('/v/pay-failed.html', '_blank');"))

case("html5-required", "/v/required.html", "click", 'button "Join"', None, False,
     "native required field empty: the browser blocks the submit",
     shell("Join", "<main><h1>Join the list</h1><form method='post' action='/api/submit/v-join'><label>Email "
           "<input name='email' type='email' required></label><button type='submit'>Join</button></form></main>"))

case("stale-success-banner", "/v/old-banner.html", "click", 'button "Save address"', None, False,
     "a 'Saved' banner was already on the page; the click does nothing",
     shell("Address", "<main><h1>Address</h1><p role='status'>Saved 2 minutes ago</p><label>City <input value='Pune'></label>"
           "<button id='s'>Save address</button></main>", "document.getElementById('s').onclick = () => {};"))

case("fill-rejected", "/v/digits.html", "fill", 'textbox "PIN code"', "56A0034", False,
     "the field strips letters as you type",
     shell("PIN", "<main><h1>Delivery</h1><label>PIN code <input id='pin'></label></main>",
           "document.getElementById('pin').addEventListener('input', e => { e.target.value = e.target.value.replace(/\\D/g, ''); });"))

case("check-reverted", "/v/terms.html", "check", 'checkbox "Email me offers"', None, False,
     "the page unchecks the box right after it is checked",
     shell("Prefs", "<main><h1>Preferences</h1><label><input type='checkbox' id='c'> Email me offers</label></main>",
           "document.getElementById('c').addEventListener('change', e => setTimeout(() => { e.target.checked = false; }, 50));"))

# ---------- the outcome DID happen: `verified` is right, `unverified` is an honest miss ----------

PAGES["/v/thanks.html"] = shell("Thanks", "<main><h1>Thank you, your order is placed</h1></main>")
case("submit-navigates", "/v/buy.html", "click", 'button "Place order"', None, True,
     "goes to a thank-you page",
     shell("Buy", "<main><h1>Buy</h1><form method='get' action='/v/thanks.html'><button type='submit'>Place order</button></form></main>"))

case("save-message", "/v/save-ok.html", "click", 'button "Save changes"', None, True,
     "status says 'Changes saved'",
     shell("Settings", "<main><h1>Settings</h1><label>Nickname <input value='Ravi'></label><button id='s'>Save changes</button>"
           "<p id='out' role='status'></p></main>",
           "document.getElementById('s').onclick = () => { document.getElementById('out').textContent = 'Changes saved.'; };"))

case("spinner-then-success", "/v/spinner-ok.html", "click", 'button "Pay ₹499"', None, True,
     "'Processing…' then 'Payment successful' after 1 s",
     shell("Pay", "<main><h1>Invoice 89</h1><div id='box'><button id='pay'>Pay ₹499</button></div></main>",
           """document.getElementById('pay').onclick = () => { document.getElementById('box').innerHTML = '<p>Processing…</p>';
  setTimeout(() => { document.getElementById('box').innerHTML = '<p>Payment successful. Receipt sent.</p>'; }, 1000); };"""))

case("row-removed", "/v/rows.html", "click", 'button "Remove" \\(in "Spice box', None, True,
     "the row disappears",
     shell("Cart", "<main><h1>Cart</h1><ul><li>Steel ladle <button>Remove</button></li><li>Spice box <button>Remove</button></li></ul></main>",
           "document.querySelectorAll('li button').forEach(b => b.onclick = () => b.parentElement.remove());"))

case("todo-cleared", "/v/todo.html", "press", 'textbox "New task"', "Enter", True,
     "Enter adds the item and clears the field",
     shell("Todo", "<main><h1>Todo</h1><form id='f'><label>New task <input id='t' value='Buy milk'></label></form><ul id='l'></ul></main>",
           "document.getElementById('f').onsubmit = e => { e.preventDefault(); const li = document.createElement('li');"
           " li.textContent = document.getElementById('t').value; document.getElementById('l').appendChild(li); document.getElementById('t').value = ''; };"))

case("fill-ok", "/v/name.html", "fill", 'textbox "Full name"', "Asha Rao", True, "plain text field",
     shell("Name", "<main><h1>Profile</h1><label>Full name <input></label></main>"))

case("check-ok", "/v/check-ok.html", "check", 'checkbox "Email me offers"', None, True, "plain checkbox",
     shell("Prefs", "<main><h1>Preferences</h1><label><input type='checkbox'> Email me offers</label></main>"))

case("aria-check-ok", "/v/aria-check.html", "check", 'checkbox "I agree to the privacy policy"', None, True,
     "custom <span role=checkbox>: the 2026-11-18 benchmark found check reported it as failed on Obscura",
     shell("Waitlist", "<main><h1>Join</h1><p><span id='lbl'>I agree to the privacy policy</span> <span role='checkbox' "
           "aria-checked='false' aria-labelledby='lbl' tabindex='0' id='cb' style='display:inline-block;width:16px;height:16px;border:1px solid'></span></p></main>",
           "const cb = document.getElementById('cb'); cb.onclick = () => cb.setAttribute('aria-checked', cb.getAttribute('aria-checked') !== 'true');"))

case("tab-switch", "/v/tabs.html", "click", 'tab "Specs"', None, True, "a tab shows its panel",
     shell("Phone", "<main><h1>Phone</h1><div role='tablist'><button role='tab' aria-selected='true' id='a'>Overview</button>"
           "<button role='tab' aria-selected='false' id='b'>Specs</button></div><div role='tabpanel' id='p'>Great camera.</div></main>",
           "document.getElementById('b').onclick = () => { document.getElementById('b').setAttribute('aria-selected', 'true');"
           " document.getElementById('a').setAttribute('aria-selected', 'false'); document.getElementById('p').textContent = '6.1 inch, 128 GB'; };"))


async def run_case(sess, base: str, c) -> tuple[str, str]:
    """Open the case's page in a lean Session, perform its action, return (status word, full act output)."""
    import re
    cid, path, action, target, value, _happened, _note = c
    out = await sess.open(base + path)
    m = re.search(r"(\d+): " + target, out)
    if not m:
        return "error", f"target {target!r} not found in:\n{out}"
    try:
        res = await sess.act(action, int(m.group(1)), value)
    except Exception as e:  # noqa: BLE001 - a refusal is an honest non-verified outcome
        return "error", f"{type(e).__name__}: {e}"
    w = re.search(r"status: (\w+)", res)
    return (w.group(1) if w else "none"), res


def classify(happened: bool, status: str) -> str:
    if status == "verified":
        return "true_verified" if happened else "FALSE_VERIFIED"
    if status in ("timed_out", "ambiguous"):
        return "timed_out_or_ambiguous"
    return "false_unverified" if happened else "correctly_unverified"
