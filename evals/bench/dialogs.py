"""Dialogs and overlays: confirm, prompt, modal forms, blocking popups, session modals, alerts."""
from evals.bench.core import all_of, answer, bench, nothing, shell, subs, want

# 56 confirm() on one of several identical buttons
PROJ = ["Mobile app", "Old site", "Data pipeline", "Old site v2"]
bench("archive", "/b/projects.html", "Archive the project 'Old site' (only that one).",
      want("archive", once=True, name="Old site"), lambda p, b: _archive(p), ("dialog", "confirm"),
      shell("Projects", "<main><h1>Projects</h1><ul>" + "".join(
          f"<li data-n='{n}'>{n} <button class='ar'>Archive</button></li>" for n in PROJ) + "</ul><p id='out' role='status'></p></main>",
          """document.querySelectorAll('.ar').forEach(b => b.onclick = async () => { const n = b.parentElement.dataset.n;
  if (!confirm(`Archive the project "${n}"? Members lose access.`)) return;
  await send('archive', {name: n}, `Archived ${n}.`); b.parentElement.remove(); });"""))


async def _archive(p):
    p.once("dialog", lambda d: d.accept())
    await p.click("li[data-n='Old site'] .ar")
    await p.wait_for_selector("text=Archived Old site")
    return ""


# 57 prompt()
bench("rename", "/b/folders.html", "Rename the folder 'Untitled folder' to 'Invoices 2026'.",
      want("rename", old="Untitled folder", new="Invoices 2026"), lambda p, b: _rename(p), ("dialog", "prompt"),
      shell("Files", """<main><h1>My files</h1><ul><li data-n='Photos'>Photos <button class='rn'>Rename</button></li>
<li data-n='Untitled folder'>Untitled folder <button class='rn'>Rename</button></li></ul><p id='out' role='status'></p></main>""",
            """document.querySelectorAll('.rn').forEach(b => b.onclick = async () => { const li = b.parentElement, old = li.dataset.n;
  const v = prompt('New folder name', old); if (!v || v === old) return;
  await send('rename', {old, new: v}, `Renamed to ${v}.`); li.dataset.n = v; li.firstChild.textContent = v + ' '; });"""))


async def _rename(p):
    p.once("dialog", lambda d: d.accept("Invoices 2026"))
    await p.click("li[data-n='Untitled folder'] .rn")
    await p.wait_for_selector("text=Renamed to Invoices 2026")
    return ""


# 58 modal form
bench("contact-modal", "/b/contacts.html", "Add a contact named Farah Khan with phone 9988776655 and the label 'Work'.",
      want("contact-modal", name="Farah Khan", phone="9988776655", label="work"), lambda p, b: _cm(p), ("modal", "form"),
      shell("Contacts", """<main><h1>Contacts</h1><ul><li>Amit Verma · 9811122233</li></ul><button id='add'>Add contact</button><p id='out' role='status'></p></main>
<div id='ov' class='overlay hidden'><div class='modal' role='dialog' aria-modal='true' aria-labelledby='mh'><h2 id='mh'>New contact</h2>
<label>Name <input id='n'></label><label>Phone <input id='ph'></label><label>Label <select id='lb'><option value='home'>Home</option>
<option value='work'>Work</option><option value='other'>Other</option></select></label><button id='cancel'>Cancel</button> <button id='save'>Save contact</button></div></div>""",
            """const ov = document.getElementById('ov');
document.getElementById('add').onclick = () => ov.classList.remove('hidden');
document.getElementById('cancel').onclick = () => ov.classList.add('hidden');
document.getElementById('save').onclick = async () => { await send('contact-modal', {name: document.getElementById('n').value,
  phone: document.getElementById('ph').value, label: document.getElementById('lb').value}, 'Contact saved.'); ov.classList.add('hidden'); };"""))


async def _cm(p):
    await p.click("#add")
    await p.fill("#n", "Farah Khan")
    await p.fill("#ph", "9988776655")
    await p.select_option("#lb", "work")
    await p.click("#save")
    await p.wait_for_selector("text=Contact saved")
    return ""


# 59 popup that covers the page after a second
bench("popup", "/b/brochure.html", "Request the brochure for tara@example.com.",
      all_of(want("brochure", email="tara@example.com"), nothing("popup-signup")), lambda p, b: _popup(p), ("overlay",),
      shell("Brochure", """<main><h1>Goa resort brochure</h1><form method='post' action='/api/submit/brochure'>
<label>Email <input name='email'></label><button type='submit'>Send me the brochure</button></form></main>
<div id='ov' class='overlay hidden'><div class='modal' role='dialog' aria-label='Newsletter'><h2>Get 10% off!</h2>
<p>Join our newsletter.</p><button id='yes'>Sign me up</button> <button id='no'>No thanks</button></div></div>""",
            """setTimeout(() => document.getElementById('ov').classList.remove('hidden'), 1000);
document.getElementById('no').onclick = () => document.getElementById('ov').remove();
document.getElementById('yes').onclick = async () => { await fetch('/api/submit/popup-signup', {method: 'POST', body: '{}', headers: {'Content-Type': 'application/json'}}); document.getElementById('ov').remove(); };"""))


async def _popup(p):
    await p.wait_for_selector("#no")
    await p.click("#no")
    await p.fill("[name=email]", "tara@example.com")
    await p.click("text=Send me the brochure")
    await p.wait_for_selector("text=submission received")
    return ""


# 60 session-expiry modal: choose the button that keeps you signed in
bench("session-modal", "/b/notes.html", "Save the note 'Call vendor at 4pm'.",
      all_of(want("note", text="Call vendor at 4pm"), nothing("signout")), lambda p, b: _note(p), ("modal", "interruption"),
      shell("Notes", """<main><h1>Quick note</h1><label>Note <textarea id='t'></textarea></label><button id='save'>Save note</button><p id='out' role='status'></p></main>
<div id='ov' class='overlay hidden'><div class='modal' role='alertdialog' aria-labelledby='sh'><h2 id='sh'>Your session is about to expire</h2>
<p>Do you want to stay signed in?</p><button id='so'>Sign out</button> <button id='stay'>Stay signed in</button></div></div>""",
            """let out = false; setTimeout(() => document.getElementById('ov').classList.remove('hidden'), 1500);
document.getElementById('stay').onclick = () => document.getElementById('ov').classList.add('hidden');
document.getElementById('so').onclick = async () => { out = true; await fetch('/api/submit/signout', {method: 'POST', body: '{}', headers: {'Content-Type': 'application/json'}});
  document.body.innerHTML = '<main><h1>You have been signed out</h1></main>'; };
document.getElementById('save').onclick = () => { if (!document.getElementById('ov').classList.contains('hidden')) return;
  send('note', {text: document.getElementById('t').value}, 'Note saved.'); };"""))


async def _note(p):
    await p.wait_for_selector("#stay", state="visible")
    await p.click("#stay")
    await p.fill("#t", "Call vendor at 4pm")
    await p.click("#save")
    await p.wait_for_selector("text=Note saved")
    return ""


# 61 the answer is only in an alert()
bench("alert-code", "/b/coupon.html", "Generate a coupon and tell me its code.",
      all_of(answer("chai-7q2x"), lambda st, a: (len(subs(st, "coupon")) == 1, f"{len(subs(st, 'coupon'))} coupons generated")),
      lambda p, b: _alert(p), ("dialog", "alert"),
      shell("Coupons", "<main><h1>Rewards</h1><p>You have 1 coupon available.</p><button id='g'>Generate coupon</button></main>",
            """document.getElementById('g').onclick = async () => { await fetch('/api/submit/coupon', {method: 'POST', body: '{}', headers: {'Content-Type': 'application/json'}});
  alert('Your coupon code is CHAI-7Q2X. It expires in 7 days.'); };"""))


async def _alert(p):
    msg = []

    async def on(d):
        msg.append(d.message)
        await d.accept()
    p.on("dialog", on)
    await p.click("#g")
    await p.wait_for_timeout(500)
    return msg[0].split("is ")[1].split(".")[0]
