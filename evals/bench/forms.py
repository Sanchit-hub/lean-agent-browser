"""Forms: labels, fieldsets, radios, checkboxes, native date/time, dependent selects, validation."""
from evals.bench.core import POST, bench, shell, want

T = "/api/submit/"


def form(task: str, inner: str, button: str = "Submit", extra: str = "") -> str:
    return f"<form method='post' action='{T}{task}' {extra}>{inner}<button type='submit'>{button}</button></form>"


# 1 contact
bench("contact", "/b/contact.html",
      "Send a message to support as Priya Nair (priya@example.com) about Billing, saying 'I was charged twice for "
      "order 5521.' Don't ask for a copy of the message.",
      want("contact", absent=("copy",), name="Priya Nair", email="priya@example.com", topic="billing",
           message="I was charged twice for order 5521."),
      lambda p, b: _contact(p), ("form",),
      shell("Contact us", "<main><h1>Contact support</h1>" + form("contact", """
<label>Full name <input name='name' autocomplete='name'></label>
<label>Email <input name='email' type='email'></label>
<label>Topic <select name='topic'><option value=''>Choose…</option><option value='general'>General</option>
<option value='billing'>Billing</option><option value='tech'>Technical support</option>
<option value='partner'>Partnerships</option></select></label>
<label>Message <textarea name='message' rows='4'></textarea></label>
<label><input type='checkbox' name='copy' checked> Email me a copy</label>""", "Send message") + "</main>"))


async def _contact(p):
    await p.fill("[name=name]", "Priya Nair")
    await p.fill("[name=email]", "priya@example.com")
    await p.select_option("[name=topic]", "billing")
    await p.fill("[name=message]", "I was charged twice for order 5521.")
    await p.uncheck("[name=copy]")
    await p.click("text=Send message")
    await p.wait_for_selector("text=submission received")
    return ""


# 2 address: two "Street" fields told apart only by their fieldset
bench("address", "/b/address.html",
      "Save the billing address 12 MG Road, Bengaluru, 560001 and a different shipping address: 4 Park Street, "
      "Kolkata, 700016.",
      want("address", b_street="12 MG Road", b_city="Bengaluru", b_pin="560001", s_street="4 Park Street",
           s_city="Kolkata", s_pin="700016"),
      lambda p, b: _address(p), ("form", "fieldset", "conditional"),
      shell("Addresses", "<main><h1>Addresses</h1>" + form("address", """
<fieldset><legend>Billing address</legend><label>Street <input name='b_street'></label>
<label>City <input name='b_city'></label><label>PIN code <input name='b_pin'></label></fieldset>
<label><input type='checkbox' id='same' name='same' checked> Shipping address is the same as billing</label>
<fieldset id='ship' class='hidden' disabled><legend>Shipping address</legend><label>Street <input name='s_street'></label>
<label>City <input name='s_city'></label><label>PIN code <input name='s_pin'></label></fieldset>""", "Save addresses") + "</main>",
            """const same = document.getElementById('same'), ship = document.getElementById('ship');
same.addEventListener('change', () => { ship.classList.toggle('hidden', same.checked); ship.disabled = same.checked; });"""))


async def _address(p):
    for k, v in (("b_street", "12 MG Road"), ("b_city", "Bengaluru"), ("b_pin", "560001")):
        await p.fill(f"[name={k}]", v)
    await p.uncheck("#same")
    for k, v in (("s_street", "4 Park Street"), ("s_city", "Kolkata"), ("s_pin", "700016")):
        await p.fill(f"[name={k}]", v)
    await p.click("text=Save addresses")
    await p.wait_for_selector("text=submission received")
    return ""


# 3 survey: radio groups
def _radios(name, legend, opts):
    return f"<fieldset><legend>{legend}</legend>" + "".join(
        f"<label><input type='radio' name='{name}' value='{v}'> {t}</label>" for v, t in opts) + "</fieldset>"


bench("survey", "/b/survey.html",
      "Fill in the shopping survey: you shop online weekly, prefer paying by UPI, and would recommend the store.",
      want("survey", freq="weekly", pay="upi", rec="yes"), lambda p, b: _survey(p), ("form", "radio"),
      shell("Survey", "<main><h1>Quick survey</h1>" + form("survey",
            _radios("freq", "How often do you shop online?", [("daily", "Daily"), ("weekly", "Weekly"), ("monthly", "Monthly"), ("rarely", "Rarely")])
            + _radios("pay", "Preferred payment method", [("card", "Card"), ("upi", "UPI"), ("cod", "Cash on delivery")])
            + _radios("rec", "Would you recommend us to a friend?", [("yes", "Yes"), ("no", "No"), ("unsure", "Not sure")]),
            "Send answers") + "</main>"))


async def _survey(p):
    for n, v in (("freq", "weekly"), ("pay", "upi"), ("rec", "yes")):
        await p.check(f"input[name={n}][value={v}]")
    await p.click("text=Send answers")
    await p.wait_for_selector("text=submission received")
    return ""


# 4 checkboxes with defaults that must change
bench("preferences", "/b/preferences.html",
      "Set your interests to only Hiking and Photography, turn off marketing offers but keep product updates on, and save.",
      want("preferences", absent=("i_cooking", "i_gaming", "marketing"), i_hiking="on", i_photo="on", updates="on"),
      lambda p, b: _prefs(p), ("form", "checkbox"),
      shell("Preferences", "<main><h1>Preferences</h1>" + form("preferences", """
<fieldset><legend>Interests</legend><label><input type='checkbox' name='i_hiking'> Hiking</label>
<label><input type='checkbox' name='i_photo'> Photography</label><label><input type='checkbox' name='i_cooking' checked> Cooking</label>
<label><input type='checkbox' name='i_gaming'> Gaming</label></fieldset>
<fieldset><legend>Emails</legend><label><input type='checkbox' name='marketing' checked> Marketing offers</label>
<label><input type='checkbox' name='updates' checked> Product updates</label></fieldset>""", "Save preferences") + "</main>"))


async def _prefs(p):
    await p.check("[name=i_hiking]")
    await p.check("[name=i_photo]")
    await p.uncheck("[name=i_cooking]")
    await p.uncheck("[name=marketing]")
    await p.click("text=Save preferences")
    await p.wait_for_selector("text=submission received")
    return ""


# 5 native date and time inputs
bench("appointment", "/b/appointment.html", "Book a dental checkup on 9 January 2027 at 10:30.",
      want("appointment", date="2027-01-09", time="10:30", reason="checkup"), lambda p, b: _appt(p),
      ("form", "date-input"),
      shell("Dental clinic", "<main><h1>Book an appointment</h1>" + form("appointment", """
<label>Reason <select name='reason'><option value='cleaning'>Cleaning</option><option value='checkup'>Checkup</option>
<option value='filling'>Filling</option></select></label>
<label>Date <input type='date' name='date' min='2026-11-16'></label>
<label>Time <input type='time' name='time' step='900'></label>""", "Book appointment") + "</main>"))


async def _appt(p):
    await p.select_option("[name=reason]", "checkup")
    await p.fill("[name=date]", "2027-01-09")
    await p.fill("[name=time]", "10:30")
    await p.click("text=Book appointment")
    await p.wait_for_selector("text=submission received")
    return ""


# 6 range input (no free typing) and a bounded number input
bench("range", "/b/alerts.html", "Set the alert volume to 70 and the number of seats to 3, then save.",
      want("range", volume="70", seats="3"), lambda p, b: _range(p), ("form", "range"),
      shell("Alert settings", "<main><h1>Alert settings</h1>" + form("range", """
<label>Alert volume <input type='range' name='volume' min='0' max='100' step='5' value='50' id='vol'></label>
<p>Current volume: <output id='vo'>50</output></p>
<label>Seats <input type='number' name='seats' min='1' max='8' value='1'></label>""", "Save settings") + "</main>",
            "const v = document.getElementById('vol'); v.addEventListener('input', () => document.getElementById('vo').textContent = v.value);"))


async def _range(p):
    await p.focus("#vol")
    for _ in range(4):
        await p.keyboard.press("ArrowRight")
    await p.fill("[name=seats]", "3")
    await p.click("text=Save settings")
    await p.wait_for_selector("text=submission received")
    return ""


# 7 client-side validation with a format hint
bench("phone", "/b/phone.html", "Update your phone number to +91 98765 43210.",
      want("phone", phone="9876543210"), lambda p, b: _phone(p), ("form", "validation"),
      shell("Phone number", "<main><h1>Contact details</h1>" + form("phone", """
<label>Mobile number <input name='phone' id='ph' value='9000000001' aria-describedby='hint'></label>
<p id='hint'>10 digits, no spaces or country code.</p><p id='err' class='err' role='alert'></p>""", "Update number", "id='f'") + "</main>",
            """document.getElementById('f').addEventListener('submit', e => {
  const v = document.getElementById('ph').value;
  if (!/^[0-9]{10}$/.test(v)) { e.preventDefault(); document.getElementById('err').textContent = 'Enter exactly 10 digits, without +91 or spaces.'; }
});"""))


async def _phone(p):
    await p.fill("#ph", "9876543210")
    await p.click("text=Update number")
    await p.wait_for_selector("text=submission received")
    return ""


# 8 fields revealed by a choice
bench("business", "/b/register.html",
      "Register a business account for Lakshmi Rao (lakshmi@example.com) with the company name 'Rao Textiles'.",
      want("business", type="business", name="Lakshmi Rao", email="lakshmi@example.com", company="Rao Textiles"),
      lambda p, b: _biz(p), ("form", "conditional"),
      shell("Register", "<main><h1>Create an account</h1>" + form("business", """
<fieldset><legend>Account type</legend><label><input type='radio' name='type' value='personal' checked> Personal</label>
<label><input type='radio' name='type' value='business'> Business</label></fieldset>
<label>Full name <input name='name'></label><label>Email <input name='email'></label>
<div id='biz' class='hidden'><label>Company name <input name='company' disabled></label>
<label>GSTIN (optional) <input name='gstin' disabled></label></div>""", "Create account") + "</main>",
            """document.querySelectorAll('[name=type]').forEach(r => r.addEventListener('change', () => {
  const on = document.querySelector('[name=type]:checked').value === 'business';
  document.getElementById('biz').classList.toggle('hidden', !on);
  document.querySelectorAll('#biz input').forEach(i => i.disabled = !on); }));"""))


async def _biz(p):
    await p.check("[value=business]")
    await p.fill("[name=name]", "Lakshmi Rao")
    await p.fill("[name=email]", "lakshmi@example.com")
    await p.fill("[name=company]", "Rao Textiles")
    await p.click("text=Create account")
    await p.wait_for_selector("text=submission received")
    return ""


# 9 dependent selects filled by script
bench("location", "/b/location.html", "Set your location to Kochi, Kerala, India and save it.",
      want("location", country="IN", state="KL", city="Kochi"), lambda p, b: _loc(p), ("form", "dependent-select"),
      shell("Location", "<main><h1>Your location</h1>" + form("location", """
<label>Country <select name='country' id='co'><option value=''>Select country</option><option value='IN'>India</option>
<option value='NP'>Nepal</option><option value='LK'>Sri Lanka</option></select></label>
<label>State <select name='state' id='st' disabled><option value=''>Select state</option></select></label>
<label>City <select name='city' id='ci' disabled><option value=''>Select city</option></select></label>""", "Save location") + "</main>",
            """const D = {IN: {KA: ['Bengaluru', 'Mysuru'], KL: ['Kochi', 'Kozhikode', 'Thrissur'], TN: ['Chennai', 'Madurai']},
  NP: {BA: ['Kathmandu']}, LK: {WP: ['Colombo']}};
const N = {KA: 'Karnataka', KL: 'Kerala', TN: 'Tamil Nadu', BA: 'Bagmati', WP: 'Western Province'};
const co = document.getElementById('co'), st = document.getElementById('st'), ci = document.getElementById('ci');
const fill = (sel, items, first) => { sel.innerHTML = `<option value=''>${first}</option>` + items.map(([v, t]) => `<option value='${v}'>${t}</option>`).join(''); sel.disabled = !items.length; };
co.addEventListener('change', () => { fill(st, Object.keys(D[co.value] || {}).map(k => [k, N[k]]), 'Select state'); fill(ci, [], 'Select city'); });
st.addEventListener('change', () => fill(ci, ((D[co.value] || {})[st.value] || []).map(c => [c, c]), 'Select city'));"""))


async def _loc(p):
    await p.select_option("#co", "IN")
    await p.select_option("#st", "KL")
    await p.select_option("#ci", "Kochi")
    await p.click("text=Save location")
    await p.wait_for_selector("text=submission received")
    return ""


# 10 server-side password rules
PW_FORM = """<main><h1>Change password</h1>{err}<form method='post' action='/api/password'>
<label>Current password <input type='password' name='current'></label>
<label>New password <input type='password' name='new'></label>
<label>Confirm new password <input type='password' name='confirm'></label>
<p>Use at least 8 characters.</p><button type='submit'>Change password</button></form></main>"""


def _pw_post(f, state):
    if f.get("current") != "old-pass-1":
        err = "Current password is incorrect."
    elif f.get("new") != f.get("confirm"):
        err = "The new passwords don't match."
    elif len(f.get("new", "")) < 8 or not any(c.isdigit() for c in f.get("new", "")):
        err = "New password must be at least 8 characters and contain a number."
    else:
        return 200, shell("Password changed", "<main><h1>Password changed</h1><p role='status'>Your password was updated.</p></main>"), "password"
    return 400, shell("Change password", PW_FORM.format(err=f"<p role='alert' class='err'>{err}</p>")), None


POST["/api/password"] = _pw_post
bench("password", "/b/password.html",
      "Change the account password from 'old-pass-1' to 'monsoon-rain'. If the site requires something extra, "
      "append the digit 7 to the new password.",
      want("password", new="monsoon-rain7"), lambda p, b: _pw(p), ("form", "server-validation"),
      shell("Change password", PW_FORM.format(err="")))


async def _pw(p):
    for new in ("monsoon-rain", "monsoon-rain7"):
        await p.fill("[name=current]", "old-pass-1")
        await p.fill("[name=new]", new)
        await p.fill("[name=confirm]", new)
        await p.click("button[type=submit]")
        await p.wait_for_load_state()
        if await p.locator("text=Password changed").count():
            break
    return ""


# 11 gift card: same labels in two fieldsets
bench("giftcard", "/b/giftcard.html",
      "Send a ₹1000 gift card from Arjun Mehta (arjun@example.com) to Sneha Pillai (sneha@example.com) with the "
      "message 'Happy birthday!'.",
      want("giftcard", from_name="Arjun Mehta", from_email="arjun@example.com", to_name="Sneha Pillai",
           to_email="sneha@example.com", amount="1000", note="Happy birthday!"),
      lambda p, b: _gift(p), ("form", "fieldset"),
      shell("Gift cards", "<main><h1>Send a gift card</h1>" + form("giftcard", """
<fieldset><legend>From</legend><label>Name <input name='from_name'></label><label>Email <input name='from_email'></label></fieldset>
<fieldset><legend>To</legend><label>Name <input name='to_name'></label><label>Email <input name='to_email'></label></fieldset>
<fieldset><legend>Amount</legend><label><input type='radio' name='amount' value='500' checked> ₹500</label>
<label><input type='radio' name='amount' value='1000'> ₹1,000</label><label><input type='radio' name='amount' value='2000'> ₹2,000</label></fieldset>
<label>Message <textarea name='note'></textarea></label>""", "Send gift card") + "</main>"))


async def _gift(p):
    for k, v in (("from_name", "Arjun Mehta"), ("from_email", "arjun@example.com"), ("to_name", "Sneha Pillai"),
                 ("to_email", "sneha@example.com"), ("note", "Happy birthday!")):
        await p.fill(f"[name={k}]", v)
    await p.check("[name=amount][value='1000']")
    await p.click("text=Send gift card")
    await p.wait_for_selector("text=submission received")
    return ""


# 12 prefilled form: change one field only
bench("edit-profile", "/b/edit-profile.html", "Change only the email address to kavya@example.com and save the profile.",
      want("edit-profile", name="Kavya Sharma", email="kavya@example.com", city="Delhi",
           bio="Product designer. Loves chai and long walks."),
      lambda p, b: _edit(p), ("form", "prefilled"),
      shell("Edit profile", "<main><h1>Edit profile</h1>" + form("edit-profile", """
<label>Name <input name='name' value='Kavya Sharma'></label><label>Email <input name='email' value='kavya@old-mail.com'></label>
<label>City <input name='city' value='Delhi'></label>
<label>Bio <textarea name='bio'>Product designer. Loves chai and long walks.</textarea></label>""", "Save profile") + "</main>"))


async def _edit(p):
    await p.fill("[name=email]", "kavya@example.com")
    await p.click("text=Save profile")
    await p.wait_for_selector("text=submission received")
    return ""


# 13 placeholder-only inputs
bench("feedback", "/b/feedback.html",
      "Leave feedback as Omar for order 7781: rating 4, comment 'Fast delivery'.",
      want("feedback", name="Omar", order="7781", rating="4", comment="Fast delivery"), lambda p, b: _fb(p),
      ("form", "no-labels"),
      shell("Feedback", "<main><h1>How did we do?</h1>" + form("feedback", """
<p><input name='name' placeholder='Your name'></p><p><input name='order' placeholder='Order number'></p>
<p><select name='rating'><option value=''>Rate us</option><option>1</option><option>2</option><option>3</option>
<option>4</option><option>5</option></select></p><p><textarea name='comment' placeholder='Tell us more'></textarea></p>""",
            "Send feedback") + "</main>"))


async def _fb(p):
    await p.fill("[name=name]", "Omar")
    await p.fill("[name=order]", "7781")
    await p.select_option("[name=rating]", "4")
    await p.fill("[name=comment]", "Fast delivery")
    await p.click("text=Send feedback")
    await p.wait_for_selector("text=submission received")
    return ""


# 14 custom ARIA checkbox
bench("waitlist", "/b/waitlist.html", "Join the waitlist with nina@example.com, agreeing to the privacy policy.",
      want("waitlist", email="nina@example.com", agree="yes"), lambda p, b: _wait(p), ("form", "aria-checkbox"),
      shell("Waitlist", """<main><h1>Join the waitlist</h1><form method='post' action='/api/submit/waitlist' id='f'>
<label>Email <input name='email'></label>
<p><span id='lbl'>I agree to the privacy policy</span>
<span role='checkbox' aria-checked='false' aria-labelledby='lbl' tabindex='0' id='cb' style='display:inline-block;width:16px;height:16px;border:1px solid #444'></span></p>
<input type='hidden' name='agree' id='agree' value='no'><p id='err' class='err' role='alert'></p>
<button type='submit'>Join waitlist</button></form></main>""",
            """const cb = document.getElementById('cb');
const flip = () => { const on = cb.getAttribute('aria-checked') !== 'true'; cb.setAttribute('aria-checked', on);
  cb.textContent = on ? '✓' : ''; document.getElementById('agree').value = on ? 'yes' : 'no'; };
cb.addEventListener('click', flip); cb.addEventListener('keydown', e => { if (e.key === ' ') { e.preventDefault(); flip(); } });
document.getElementById('f').addEventListener('submit', e => { if (document.getElementById('agree').value !== 'yes') {
  e.preventDefault(); document.getElementById('err').textContent = 'Please accept the privacy policy.'; } });"""))


async def _wait(p):
    await p.fill("[name=email]", "nina@example.com")
    await p.click("#cb")
    await p.click("text=Join waitlist")
    await p.wait_for_selector("text=submission received")
    return ""
