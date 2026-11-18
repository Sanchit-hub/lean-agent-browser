"""Verification-honesty fixtures: pages where an action is dispatched but the wanted outcome does or doesn't
happen, built to tempt a false `verified`. Used by tests/test_verification.py and
scripts/verification_matrix.py (no LLM involved). Not agent benchmark tasks.

Each case: (id, path, action, target pattern, value, outcome_happened, note).
"""
from __future__ import annotations

from evals.bench.core import PAGES, POST, shell

CASES: list[tuple[str, str, str, str, str | None, bool, str]] = []


def case(cid, path, action, target, value, happened, note, page):
    PAGES[path.split("?")[0]] = page
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

# expect= postconditions: the evidence has to be new and not negated
CASES_EXPECT: list[tuple[str, str, str, str, str | None, str, bool, str]] = []


def expect_case(cid, path, action, target, value, expect, happened, note, page):
    PAGES[path.split("?")[0]] = page  # the fixture server looks pages up without the query string
    CASES_EXPECT.append((cid, path, action, target, value, expect, happened, note))


expect_case("expect-already-true", "/v/x-stale.html", "click", 'button "Save draft"', None, "Saved", False,
            "'Saved 2 minutes ago' was on the page before; the click does nothing",
            shell("Draft", "<main><h1>Draft</h1><p>Saved 2 minutes ago</p><button id='s'>Save draft</button></main>",
                  "document.getElementById('s').onclick = () => {};"))
expect_case("expect-negated", "/v/x-neg.html", "click", 'button "Save draft"', None, "saved", False,
            "the page says 'Draft not saved'",
            shell("Draft", "<main><h1>Draft</h1><button id='s'>Save draft</button><p id='o'></p></main>",
                  "document.getElementById('s').onclick = () => { document.getElementById('o').textContent = 'Draft not saved: server error'; };"))
expect_case("expect-url-already", "/v/x-url.html?step=review", "click", 'button "Confirm booking"', None, "url:step=review", False,
            "the URL already contained the expected part; the click does nothing",
            shell("Booking", "<main><h1>Review</h1><button id='c'>Confirm booking</button></main>",
                  "document.getElementById('c').onclick = () => {};"))
expect_case("expect-new-text", "/v/x-new.html", "click", 'button "Save draft"', None, "Draft saved", True,
            "the expected text appears after the click",
            shell("Draft", "<main><h1>Draft</h1><button id='s'>Save draft</button><p id='o'></p></main>",
                  "document.getElementById('s').onclick = () => { document.getElementById('o').textContent = 'Draft saved at 10:42'; };"))
expect_case("expect-again", "/v/x-again.html", "click", 'button "Add item"', None, "Item added", True,
            "'Item added' was there once and appears a second time",
            shell("List", "<main><h1>List</h1><ul id='l'><li>Item added</li></ul><button id='a'>Add item</button></main>",
                  "document.getElementById('a').onclick = () => { const li = document.createElement('li'); li.textContent = 'Item added';"
                  " document.getElementById('l').appendChild(li); };"))

expect_case("expect-new-tab", "/v/x-tab.html", "click", 'button "Place order"', None, "Payment successful", False,
            "opens a tab that says the payment failed; the expectation must be checked in that tab",
            shell("Checkout", "<main><h1>Checkout</h1><button id='p'>Place order</button></main>",
                  "document.getElementById('p').onclick = () => window.open('/v/pay-failed.html', '_blank');"))

# red team: expect= (the "{id}" in gone:{id} is the clicked element's id, filled in by run_expect_case)
expect_case("rt-expect-gone-error-alert", "/v/rt-x-gone.html", "click", 'button "Archive"', None, "gone:{id}", False,
            "the button is removed, but because archiving failed (role=alert error)",
            shell("Doc", "<main><h1>Q3 plan</h1><div id='b'><button id='a'>Archive</button></div></main>",
                  "document.getElementById('a').onclick = () => { document.getElementById('b').innerHTML ="
                  " '<p role=\"alert\">Couldn\\'t archive: permission denied.</p>'; };"))
expect_case("rt-expect-gone-error-plain", "/v/rt-x-gone2.html", "click", 'button "Archive"', None, "gone:{id}", False,
            "the button is removed, but because archiving failed (plain-text error)",
            shell("Doc", "<main><h1>Q3 plan</h1><div id='b'><button id='a'>Archive</button></div></main>",
                  "document.getElementById('a').onclick = () => { document.getElementById('b').innerHTML ="
                  " '<p class=\"err\">Couldn\\'t archive: permission denied.</p>'; };"))
expect_case("rt-expect-hidden-template", "/v/rt-x-hidden.html", "click", 'button "Pay ₹320"', None, "Payment successful", False,
            "the click clones a hidden success block (still display:none) and shows a decline",
            shell("Pay", "<main><h1>Invoice 91</h1><div id='ok' style='display:none'>Payment successful</div>"
                  "<button id='p'>Pay ₹320</button><div id='out'></div></main>",
                  "document.getElementById('p').onclick = () => { const c = document.getElementById('ok').cloneNode(true); c.id = '';"
                  " document.getElementById('out').appendChild(c); const e = document.createElement('p');"
                  " e.textContent = 'Card declined.'; document.getElementById('out').appendChild(e); };"))
expect_case("rt-expect-long-negation", "/v/rt-x-neg.html", "click", 'button "Save draft"', None, "saved", False,
            "'We weren't able to get your draft saved.' (the negation is more than two words before 'saved')",
            shell("Draft", "<main><h1>Draft</h1><button id='s'>Save draft</button><p id='o'></p></main>",
                  "document.getElementById('s').onclick = () => { document.getElementById('o').textContent ="
                  " 'We weren\\u2019t able to get your draft saved. Try again.'; };"))
expect_case("rt-expect-url-error-route", "/v/rt-x-route.html", "click", 'button "Continue"', None, "url:/v/rt-x-route/", False,
            "SPA pushes /v/rt-x-route/error with a plain error paragraph; the URL part matches the error route",
            shell("Checkout", "<main><h1>Shipping</h1><div id='app'><button id='c'>Continue</button></div></main>",
                  "document.getElementById('c').onclick = () => { history.pushState({}, '', '/v/rt-x-route/error');"
                  " document.getElementById('app').innerHTML = '<p>We could not save your shipping details.</p>'; };"))

# non-English error after a navigation
_FORM_DE = "<main><h1>Konto</h1><form method='post' action='/v/api/de'><label>E-Mail <input name='e' value='a@b.de'></label><button type='submit'>Speichern</button></form></main>"
POST["/v/api/de"] = lambda f, st: (200, shell("Fehler", "<main><h1>Fehler</h1><p>Die Änderung konnte nicht gespeichert werden.</p></main>"), None)
case("nav-error-german", "/v/de.html", "click", 'button "Speichern"', None, False,
     "German error page after the submit ('Fehler')", shell("Konto", _FORM_DE))

def _status_form(title, h1, label, value, button, message, lang):
    """A form whose submit stays on the page and only writes `message` into a live region: the message is the
    only evidence (no navigation, the button stays, the field keeps its value)."""
    return shell(title, f"<main lang='{lang}'><h1>{h1}</h1><form id='f'><label>{label} <input name='v' value='{value}'></label>"
                 f"<button type='submit'>{button}</button></form><p id='out' role='status'></p></main>",
                 "document.getElementById('f').onsubmit = e => { e.preventDefault();"
                 f" document.getElementById('out').textContent = {message!r}; }};")


# non-English failures that contain a success word
case("negated-spanish", "/v/es-neg.html", "click", 'button "Guardar"', None, False,
     "Spanish status 'No se ha guardado el cambio'",
     _status_form("Perfil", "Perfil", "Apodo", "Ravi", "Guardar", "No se ha guardado el cambio. Inténtelo más tarde.", "es"))
case("negated-german", "/v/de-neg.html", "click", 'button "Speichern"', None, False,
     "German status 'Nicht gespeichert'",
     _status_form("Profil", "Profil", "Spitzname", "Ravi", "Speichern", "Nicht gespeichert: Verbindung unterbrochen.", "de"))
case("negated-japanese", "/v/ja-neg.html", "click", 'button "保存"', None, False,
     "Japanese status '保存されていません' (not saved)",
     _status_form("プロフィール", "プロフィール", "ニックネーム", "Ravi", "保存", "変更は保存されていません。", "ja"))
case("success-and-error-chinese", "/v/zh-mixed.html", "click", 'button "提交"', None, False,
     "Chinese status says saved but sending failed ('保存成功，但发送失败')",
     _status_form("留言", "留言", "内容", "你好", "提交", "保存成功，但发送失败。", "zh"))

# ---------- red team (2026-11-18): realistic pages built to get a false `verified` ----------

# A submit lands on an HTTP 200 page whose heading changed but whose body (a plain paragraph) says it failed.
_CHECKOUT = ("<main><h1>Checkout</h1><p>Total ₹2,340</p><form method='post' action='/v/api/declined'>"
             "<input type='hidden' name='cart' value='77'><button type='submit'>Place order</button></form></main>")
POST["/v/api/declined"] = lambda f, st: (200, shell("Order", "<main><h1>Order summary</h1><p>Payment declined by your bank. "
                                                    "No order was placed.</p><a href='/v/rt-declined.html'>Back to checkout</a></main>"), None)
case("rt-nav-200-body-declined", "/v/rt-declined.html", "click", 'button "Place order"', None, False,
     "POST answers 200 with a new heading 'Order summary'; only a plain paragraph says 'Payment declined'",
     shell("Checkout", _CHECKOUT))

# An SPA pushes an error route; the error is a plain paragraph, not a heading or live region.
case("rt-spa-error-route", "/v/rt-spa.html", "click", 'button "Pay now"', None, False,
     "pushState to /v/rt-spa/error, form replaced by a plain 'Something went wrong' paragraph",
     shell("Pay", "<main><h1>Checkout</h1><div id='app'><p>Total ₹980</p><button id='p'>Pay now</button></div></main>",
           "document.getElementById('p').onclick = () => { history.pushState({}, '', '/v/rt-spa/error');"
           " document.getElementById('app').innerHTML = '<p class=\"err\">Something went wrong. Your card was not charged.</p>"
           "<a href=\"/v/rt-spa.html\">Back</a>'; };"))

# A toast says "Saved" right away, then an error replaces it 1 s later (optimistic UI rolled back).
case("rt-toast-saved-then-error", "/v/rt-toast.html", "click", 'button "Save changes"', None, False,
     "optimistic 'Saved' toast, replaced 1 s later by 'Error: could not save. Changes reverted.'",
     shell("Settings", "<main><h1>Settings</h1><label>Nickname <input value='Ravi'></label><button id='s'>Save changes</button>"
           "<p id='t' role='status'></p></main>",
           "document.getElementById('s').onclick = () => { const t = document.getElementById('t'); t.textContent = 'Saved';"
           " setTimeout(() => { t.textContent = 'Error: could not save. Changes reverted.'; }, 1000); };"))

# The pay button is swapped for a plain error line and a "Try again" button, no "Processing…" step.
case("rt-button-replaced-try-again", "/v/rt-retry.html", "click", 'button "Pay ₹499"', None, False,
     "button replaced at once by a plain 'Payment failed.' line and a 'Try again' button",
     shell("Pay", "<main><h1>Invoice 90</h1><div id='box'><button id='pay'>Pay ₹499</button></div></main>",
           "document.getElementById('pay').onclick = () => { document.getElementById('box').innerHTML ="
           " '<p class=\"err\">Payment failed.</p><button>Try again</button>'; };"))

# A live region announces "Loading complete" while the real result (plain text) is a failure.
case("rt-live-loading-complete", "/v/rt-loading.html", "click", 'button "Submit application"', None, False,
     "aria-live says 'Loading complete'; the plain result line says the application could not be submitted",
     shell("Apply", "<main><h1>Apply</h1><label>Name <input value='Asha'></label><button id='s'>Submit application</button>"
           "<p aria-live='polite' id='a'></p><div id='r'></div></main>",
           "document.getElementById('s').onclick = () => { document.getElementById('a').textContent = 'Loading complete';"
           " document.getElementById('r').innerHTML = '<p>Your application could not be submitted.</p>'; };"))

# Negation split across elements inside a live region.
case("rt-split-negation", "/v/rt-split.html", "click", 'button "Save changes"', None, False,
     "status region holds two block children: 'Changes <strong>not</strong>' and '<b>saved</b>'",
     shell("Settings", "<main><h1>Settings</h1><label>Nickname <input value='Ravi'></label><button id='s'>Save changes</button>"
           "<div id='out' role='status'></div></main>",
           "document.getElementById('s').onclick = () => { document.getElementById('out').innerHTML ="
           " '<div><span>Changes</span> <strong>not</strong></div><div><b>saved</b></div>'; };"))

# A form that clears its field on a server-side rejection, showing the error in a plain paragraph.
case("rt-form-cleared-on-reject", "/v/rt-clear.html", "click", 'button "Subscribe"', None, False,
     "server rejects the address: the field is emptied and a plain 'That email address is invalid.' appears",
     shell("Newsletter", "<main><h1>Newsletter</h1><form id='f'><label>Email <input name='e' id='e' value='asha@example'></label>"
           "<button type='submit'>Subscribe</button></form><p id='m' class='error'></p></main>",
           "document.getElementById('f').onsubmit = e => { e.preventDefault(); document.getElementById('e').value = '';"
           " document.getElementById('m').textContent = 'That email address is invalid.'; };"))

# A form inside a same-origin iframe posts to a 200 page that says the payment failed.
POST["/v/api/rt-frame"] = lambda f, st: (200, shell("Card", "<main><p>Payment declined. Try another card.</p></main>"), None)
PAGES["/v/rt-frame-inner.html"] = shell("Card", "<main><form method='post' action='/v/api/rt-frame'><label>Card "
                                                "<input name='c' value='4111 1111 1111 1111'></label>"
                                                "<button type='submit'>Pay ₹750</button></form></main>")
case("rt-iframe-declined", "/v/rt-frame.html", "click", 'button "Pay ₹750"', None, False,
     "the pay form lives in an iframe; it posts to a 200 page that says 'Payment declined'",
     shell("Checkout", "<main><h1>Checkout</h1><iframe src='/v/rt-frame-inner.html' title='Card payment' "
           "style='width:400px;height:160px'></iframe></main>"))

# A non-submit click answered by an alert() with an error.
case("rt-dialog-error", "/v/rt-coupon.html", "click", 'button "Apply coupon"', None, False,
     "alert('Coupon code is invalid'); nothing else changes",
     shell("Cart", "<main><h1>Cart</h1><p>Total ₹1,500</p><label>Coupon <input value='DIWALI50'></label>"
           "<button id='c'>Apply coupon</button></main>",
           "document.getElementById('c').onclick = () => alert('Coupon code is invalid');"))

# Login page whose heading is "Welcome back": the server re-renders it with a plain-text error.
_LOGIN = ("<main><h1>Welcome back</h1>{err}<form method='post' action='/v/api/rt-login'><label>Email "
          "<input name='u' value='asha@example.com'></label><label>Password <input type='password' name='p' value='x'></label>"
          "<button type='submit'>Sign in</button></form></main>")
POST["/v/api/rt-login"] = lambda f, st: (200, shell("Sign in", _LOGIN.format(err="<p class='error'>Incorrect password.</p>")), None)
case("rt-login-welcome-heading", "/v/rt-login.html", "click", 'button "Sign in"', None, False,
     "login page titled 'Welcome back' comes back (HTTP 200) with a plain 'Incorrect password.'",
     shell("Sign in", _LOGIN.format(err="")))

# A page with a "Saved addresses" heading silently re-renders after a rejected POST.
_ADDR = ("<main><h1>Your account</h1><h2>Saved addresses</h2><ul><li>12 MG Road, Pune</li></ul>"
         "<form method='post' action='/v/api/rt-addr'><label>New address <input name='a' value='4 Park St'></label>"
         "<button type='submit'>Add address</button></form></main>")
POST["/v/api/rt-addr"] = lambda f, st: (200, shell("Account", _ADDR), None)
case("rt-silent-reload-saved-heading", "/v/rt-addr.html", "click", 'button "Add address"', None, False,
     "the POST returns the same page (nothing added); a standing 'Saved addresses' heading is on it",
     shell("Account", _ADDR))

# A lazy chat widget that greets on first interaction; the submit itself does nothing.
case("rt-chat-widget-welcome", "/v/rt-chat.html", "click", 'button "Submit feedback"', None, False,
     "the button does nothing; a chat widget loads on first click and says 'Welcome! How can we help?' in a live region",
     shell("Feedback", "<main><h1>Feedback</h1><form onsubmit='return false'><label>Feedback <textarea name='t'>Great</textarea></label>"
           "<button type='submit'>Submit feedback</button></form></main><aside id='chat'></aside>",
           "document.addEventListener('click', () => { if (document.getElementById('w')) return;"
           " document.getElementById('chat').innerHTML = '<p id=\"w\" role=\"status\">Welcome! How can we help?</p>'; }, true);"))

# A send button re-rendered as a fresh, disabled copy of itself, with a plain rate-limit message.
case("rt-button-rerendered-disabled", "/v/rt-rate.html", "click", 'button "Send invite"', None, False,
     "the button is replaced by a new disabled 'Send invite' and a plain 'Too many requests' line",
     shell("Team", "<main><h1>Invite</h1><label>Email <input value='dev@example.com'></label><div id='b'><button id='s'>Send invite</button></div>"
           "<p id='m'></p></main>",
           "document.getElementById('s').onclick = () => { document.getElementById('b').innerHTML = '<button disabled>Send invite</button>';"
           " document.getElementById('m').textContent = 'Too many requests. Please wait a minute.'; };"))

# Control that should be blocked: a generic 'Saved' toast together with a field error.
case("rt-toast-with-field-error", "/v/rt-field-err.html", "click", 'button "Save profile"', None, False,
     "generic 'Saved' toast appears but the field is marked aria-invalid with an error message",
     shell("Profile", "<main><h1>Profile</h1><label for='ph'>Phone</label> <input id='ph' value='12' aria-describedby='ph-e'>"
           "<span id='ph-e'></span><button id='s'>Save profile</button><p id='t' role='status'></p></main>",
           "document.getElementById('s').onclick = () => { document.getElementById('t').textContent = 'Saved';"
           " const i = document.getElementById('ph'); i.setAttribute('aria-invalid', 'true');"
           " document.getElementById('ph-e').textContent = 'Phone number must be 10 digits'; };"))

# A field that autosaves, gets rejected, and reverts 1.2 s later (after the page looked settled).
case("rt-fill-reverted-late", "/v/rt-revert.html", "fill", 'textbox "Display name"', "Asha R", False,
     "autosave is rejected and the field goes back to its old value 1.2 s after the fill",
     shell("Profile", "<main><h1>Profile</h1><label>Display name <input id='n' value='Asha'></label></main>",
           "const n = document.getElementById('n'); let t; n.addEventListener('input', () => { clearTimeout(t);"
           " t = setTimeout(() => { n.value = 'Asha'; }, 1200); });"))

# A submit that lands on a soft 404 (HTTP 200, heading 'Page not found').
PAGES["/v/rt-gone.html"] = shell("Not found", "<main><h1>Page not found</h1><p>The page you are looking for doesn't exist.</p></main>")
case("rt-soft-404", "/v/rt-404.html", "click", 'button "Confirm booking"', None, False,
     "the form posts to a URL that serves a 200 'Page not found' page",
     shell("Booking", "<main><h1>Review booking</h1><form method='get' action='/v/rt-gone.html'>"
           "<button type='submit'>Confirm booking</button></form></main>"))

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


# non-English success messages: the only evidence is the message, so these need the success words
case("success-german", "/v/de-ok.html", "click", 'button "Speichern"', None, True,
     "German status 'Ihre Änderungen wurden gespeichert'",
     _status_form("Profil", "Profil", "Spitzname", "Ravi", "Speichern", "Vielen Dank! Ihre Änderungen wurden gespeichert.", "de"))
case("success-chinese", "/v/zh-ok.html", "click", 'button "提交"', None, True,
     "Chinese status '保存成功' (saved)",
     _status_form("留言", "留言", "内容", "你好", "提交", "保存成功", "zh"))
case("success-japanese", "/v/ja-ok.html", "click", 'button "保存"', None, True,
     "Japanese status '保存しました' (saved)",
     _status_form("プロフィール", "プロフィール", "ニックネーム", "Ravi", "保存", "変更を保存しました。", "ja"))


# red-team controls: the outcome happened, through the same mechanisms the red-team cases abuse
PAGES["/v/rt-paid.html"] = shell("Order", "<main><h1>Order summary</h1><p>Payment received. Order #4471 is confirmed.</p></main>")
case("rt-nav-200-body-ok", "/v/rt-ok.html", "click", 'button "Place order"', None, True,
     "goes to an 'Order summary' page that says the payment was received",
     shell("Checkout", "<main><h1>Checkout</h1><form method='get' action='/v/rt-paid.html'><button type='submit'>Place order</button></form></main>"))
case("rt-toast-saved-stays", "/v/rt-toast-ok.html", "click", 'button "Save changes"', None, True,
     "'Saved' toast stays (no rollback)",
     shell("Settings", "<main><h1>Settings</h1><label>Nickname <input value='Ravi'></label><button id='s'>Save changes</button>"
           "<p id='t' role='status'></p></main>",
           "document.getElementById('s').onclick = () => { document.getElementById('t').textContent = 'Saved'; };"))


async def run_expect_case(sess, base: str, c) -> tuple[str, str]:
    import re
    cid, path, action, target, value, expect, _happened, _note = c
    out = await sess.open(base + path)
    m = re.search(r"(\d+): " + target, out)
    if not m:
        return "setup_error", f"target {target!r} not found in:\n{out}"
    expect = expect.replace("{id}", m.group(1))  # gone:{id} -> the clicked element's id
    try:
        res = await sess.act(action, int(m.group(1)), value, expect=expect)
    except Exception as e:  # noqa: BLE001
        return "error", f"{type(e).__name__}: {e}"
    w = re.search(r"status: (\w+)", res)
    return (w.group(1) if w else "none"), res


async def run_case(sess, base: str, c) -> tuple[str, str]:
    """Open the case's page in a lean Session, perform its action, return (status word, full act output)."""
    import re
    cid, path, action, target, value, _happened, _note = c
    out = await sess.open(base + path)
    m = re.search(r"(\d+): " + target, out)
    if not m:
        return "setup_error", f"target {target!r} not found in:\n{out}"
    try:
        res = await sess.act(action, int(m.group(1)), value)
    except Exception as e:  # noqa: BLE001 - a refusal is an honest non-verified outcome
        return "error", f"{type(e).__name__}: {e}"
    w = re.search(r"status: (\w+)", res)
    return (w.group(1) if w else "none"), res


def classify(happened: bool, status: str) -> str:
    if status == "setup_error":  # the case never ran (page or target missing): a broken test, not a result
        return "SETUP_ERROR"
    if status == "verified":
        return "true_verified" if happened else "FALSE_VERIFIED"
    if status in ("timed_out", "ambiguous"):
        return "timed_out_or_ambiguous"
    return "false_unverified" if happened else "correctly_unverified"


# Cases that currently get a false `verified` (release-blocking). tests/test_verification.py xfails them
# strictly, so a fix makes the test fail until the id is removed here.
KNOWN_FALSE_VERIFIED: set[str] = {
    "rt-nav-200-body-declined",
    "rt-spa-error-route",
    "rt-toast-saved-then-error",
    "rt-button-replaced-try-again",
    "rt-live-loading-complete",
    "rt-form-cleared-on-reject",
    "rt-iframe-declined",
    "rt-dialog-error",
    "rt-login-welcome-heading",
    "rt-silent-reload-saved-heading",
    "rt-fill-reverted-late",
    "rt-soft-404",
    "rt-expect-gone-error-plain",
    "rt-expect-long-negation",
    "rt-expect-url-error-route",
}
