"""Multi-step flows: page-to-page checkout, in-page wizards, seat maps, returns, appointments."""
from evals.bench.core import bench, shell, want

CARRY = """const f = document.querySelector('form');
for (const [k, v] of new URLSearchParams(location.search)) { if (!f.querySelector(`[name="${k}"]`)) {
  const i = document.createElement('input'); i.type = 'hidden'; i.name = k; i.value = v; f.appendChild(i); } }"""

# 15 checkout across four pages (GET forms carry the state forward)
CART = shell("Cart", """<main><h1>Your cart</h1><table><tr><th>Item</th><th>Qty</th><th>Price</th></tr>
<tr><td>Steel water bottle</td><td>2</td><td>₹1,198</td></tr><tr><td>Cotton tote bag</td><td>1</td><td>₹349</td></tr></table>
<p>Total: ₹1,547</p><form action='/b/shop/shipping.html'><button>Proceed to checkout</button></form></main>""")
SHIP = shell("Shipping", """<main><h1>Shipping details</h1><p>Step 1 of 3</p><form action='/b/shop/payment.html'>
<label>Full name <input name='name' required></label><label>Address <input name='address' required></label>
<label>City <input name='city' required></label><label>PIN code <input name='pin' required></label>
<button>Continue to payment</button></form></main>""", CARRY)
PAY = shell("Payment", """<main><h1>Payment</h1><p>Step 2 of 3</p><form action='/b/shop/review.html'>
<fieldset><legend>Payment method</legend><label><input type='radio' name='pay' value='upi' checked> UPI</label>
<label><input type='radio' name='pay' value='card'> Credit or debit card</label>
<label><input type='radio' name='pay' value='cod'> Cash on delivery (₹40 fee)</label></fieldset>
<button>Review order</button></form></main>""", CARRY)
REVIEW = shell("Review", """<main><h1>Review your order</h1><p>Step 3 of 3</p><dl id='sum'></dl>
<form method='post' action='/api/submit/checkout'><button>Place order</button></form></main>""",
               CARRY + """
const L = {name: 'Name', address: 'Address', city: 'City', pin: 'PIN code', pay: 'Payment'};
document.getElementById('sum').innerHTML = [...new URLSearchParams(location.search)].map(([k, v]) => `<dt>${L[k] || k}</dt><dd>${v}</dd>`).join('');""")
for _p, _b in (("cart", CART), ("shipping", SHIP), ("payment", PAY), ("review", REVIEW)):
    from evals.bench.core import PAGES
    PAGES[f"/b/shop/{_p}.html"] = _b
bench("checkout", "/b/shop/cart.html",
      "Buy the items in the cart, shipping to Dev Patel, 21 Ring Road, Surat 395002, paying cash on delivery.",
      want("checkout", once=True, name="Dev Patel", address="21 Ring Road", city="Surat", pin="395002", pay="cod"),
      lambda p, b: _checkout(p), ("multi-step", "form"))


async def _checkout(p):
    await p.click("text=Proceed to checkout")
    await p.wait_for_url("**/shipping.html*")
    for k, v in (("name", "Dev Patel"), ("address", "21 Ring Road"), ("city", "Surat"), ("pin", "395002")):
        await p.fill(f"[name={k}]", v)
    await p.click("text=Continue to payment")
    await p.wait_for_url("**/payment.html*")
    await p.check("[value=cod]")
    await p.click("text=Review order")
    await p.wait_for_url("**/review.html*")
    await p.click("text=Place order")
    await p.wait_for_selector("text=submission received")
    return ""


# 16 in-page onboarding wizard (one URL, steps shown and hidden)
bench("onboarding", "/b/onboarding.html",
      "Complete onboarding as a Manager with a team of 11–50 people that uses Slack and Jira.",
      want("onboarding", role="manager", size="11-50", tools=["jira", "slack"]), lambda p, b: _onb(p),
      ("multi-step", "spa"),
      shell("Welcome", """<main><h1>Welcome aboard</h1><p id='step'>Step 1 of 3</p>
<section data-s='1'><h2>What is your role?</h2><label><input type='radio' name='role' value='developer'> Developer</label>
<label><input type='radio' name='role' value='designer'> Designer</label><label><input type='radio' name='role' value='manager'> Manager</label></section>
<section data-s='2' class='hidden'><h2>How big is your team?</h2><label>Team size <select id='size'><option value=''>Choose</option>
<option value='1-10'>1–10</option><option value='11-50'>11–50</option><option value='51-200'>51–200</option></select></label></section>
<section data-s='3' class='hidden'><h2>Which tools do you use?</h2><label><input type='checkbox' value='github'> GitHub</label>
<label><input type='checkbox' value='slack'> Slack</label><label><input type='checkbox' value='jira'> Jira</label></section>
<button id='back' class='hidden'>Back</button> <button id='next'>Next</button><p id='out' role='status'></p></main>""",
            """let s = 1;
const show = () => { document.querySelectorAll('section').forEach(x => x.classList.toggle('hidden', +x.dataset.s !== s));
  document.getElementById('step').textContent = `Step ${s} of 3`; document.getElementById('back').classList.toggle('hidden', s === 1);
  document.getElementById('next').textContent = s === 3 ? 'Finish' : 'Next'; };
document.getElementById('back').onclick = () => { s--; show(); };
document.getElementById('next').onclick = async () => {
  if (s < 3) { s++; return show(); }
  const role = (document.querySelector('[name=role]:checked') || {}).value;
  const tools = [...document.querySelectorAll('[data-s="3"] input:checked')].map(i => i.value);
  await send('onboarding', {role, size: document.getElementById('size').value, tools}, 'All set! Your workspace is ready.');
  document.getElementById('next').disabled = true; };"""))


async def _onb(p):
    await p.check("[value=manager]")
    await p.click("#next")
    await p.select_option("#size", "11-50")
    await p.click("#next")
    await p.check("[value=slack]")
    await p.check("[value=jira]")
    await p.click("#next")
    await p.wait_for_selector("text=All set")
    return ""


# 17 seat map
def _seats_page():
    taken = {"A2", "B4", "C3", "C6", "D1"}
    grid = ""
    for r in "ABCD":
        grid += "<div>" + "".join(
            f"<button type='button' class='seat' data-seat='{r}{n}' aria-label='Seat {r}{n}{', taken' if f'{r}{n}' in taken else ''}'"
            f"{' disabled' if f'{r}{n}' in taken else ''} aria-pressed='false'>{r}{n}</button>" for n in range(1, 7)) + "</div>"
    return shell("Book seats", f"""<main><h1>Monsoon Wedding: book seats</h1>
<label>Day <select id='day'><option value='fri'>Friday</option><option value='sat'>Saturday</option><option value='sun'>Sunday</option></select></label>
<fieldset><legend>Show time</legend><label><input type='radio' name='time' value='16:00' checked> 4:00 PM</label>
<label><input type='radio' name='time' value='19:30'> 7:30 PM</label><label><input type='radio' name='time' value='22:15'> 10:15 PM</label></fieldset>
<p>Screen this way</p>{grid}<p>Selected: <span id='sel'>none</span></p><button id='book'>Book seats</button><p id='out' role='status'></p></main>""",
                 """const chosen = new Set();
document.querySelectorAll('.seat').forEach(b => b.onclick = () => { const s = b.dataset.seat;
  chosen.has(s) ? chosen.delete(s) : chosen.add(s); b.setAttribute('aria-pressed', chosen.has(s));
  document.getElementById('sel').textContent = [...chosen].sort().join(', ') || 'none'; });
document.getElementById('book').onclick = () => send('seats', {day: document.getElementById('day').value,
  time: document.querySelector('[name=time]:checked').value, seats: [...chosen].sort()}, 'Booking confirmed.');""")


bench("seats", "/b/seats.html", "Book seats C4 and C5 for the 7:30 PM show on Saturday.",
      want("seats", day="sat", time="19:30", seats=["C4", "C5"]), lambda p, b: _seats(p), ("multi-step", "grid"),
      _seats_page())


async def _seats(p):
    await p.select_option("#day", "sat")
    await p.check("[value='19:30']")
    await p.click("[data-seat=C4]")
    await p.click("[data-seat=C5]")
    await p.click("#book")
    await p.wait_for_selector("text=Booking confirmed")
    return ""


# 18 returns: identical buttons per order, inline form
ORD = [("8807", "Yoga mat"), ("8812", "Bluetooth speaker"), ("8815", "Bluetooth speaker"), ("8820", "Desk lamp")]
bench("returns", "/b/returns.html",
      "Return the Bluetooth speaker from order 8812 because it arrived damaged; refund it as store credit.",
      want("returns", once=True, order="8812", reason="damaged", refund="credit"), lambda p, b: _ret(p),
      ("multi-step", "repeated-controls"),
      shell("Your orders", "<main><h1>Your orders</h1>" + "".join(
          f"<section class='order' data-o='{o}'><h2>Order {o}</h2><p>{item} · delivered</p>"
          f"<button class='ret'>Request return</button></section>" for o, item in ORD) + """
<form id='rf' class='hidden'><h2 id='rt'></h2><label>Reason <select id='reason'><option value=''>Choose a reason</option>
<option value='damaged'>Arrived damaged</option><option value='wrong'>Wrong item</option><option value='nolonger'>No longer needed</option></select></label>
<fieldset><legend>Refund to</legend><label><input type='radio' name='refund' value='original' checked> Original payment method</label>
<label><input type='radio' name='refund' value='credit'> Store credit</label></fieldset><button type='submit'>Submit return</button></form>
<p id='out' role='status'></p></main>""",
          """let cur = null;
document.querySelectorAll('.ret').forEach(b => b.onclick = () => { cur = b.closest('.order').dataset.o;
  document.getElementById('rt').textContent = 'Return for order ' + cur; document.getElementById('rf').classList.remove('hidden'); });
document.getElementById('rf').onsubmit = async e => { e.preventDefault();
  await send('returns', {order: cur, reason: document.getElementById('reason').value,
    refund: document.querySelector('[name=refund]:checked').value}, 'Return requested for order ' + cur + '.');
  document.getElementById('rf').classList.add('hidden'); };"""))


async def _ret(p):
    await p.click(".order[data-o='8812'] .ret")
    await p.select_option("#reason", "damaged")
    await p.check("[value=credit]")
    await p.click("text=Submit return")
    await p.wait_for_selector("text=Return requested")
    return ""


# 19 doctor appointment: pick the earliest free slot
DOCS = [("iyer", "Dr. Suresh Iyer", "Cardiology"), ("menon", "Dr. Anjali Menon", "Dermatology"), ("roy", "Dr. Bikram Roy", "Dermatology")]
SLOTS = {"iyer": ["9:00", "9:30"], "menon": ["9:00*", "9:30*", "10:00", "10:30", "11:00*"], "roy": ["9:00", "9:30"]}
bench("doctor", "/b/doctors.html",
      "Book the earliest available slot with Dr. Anjali Menon (Dermatology) for patient Rahul Das, phone 9123456780.",
      want("doctor", doctor="menon", slot="10:00", patient="Rahul Das", phone="9123456780"), lambda p, b: _doc(p),
      ("multi-step", "disabled-options"),
      shell("Doctors", "<main><h1>Book a consultation</h1>" + "".join(
          f"<section class='doc' data-d='{k}'><h2>{n}</h2><p>{s}</p><button class='pick'>Choose</button></section>" for k, n, s in DOCS) + """
<section id='slots' class='hidden'><h2 id='who'></h2><div id='sl'></div>
<label>Patient name <input id='pn'></label><label>Phone <input id='pp'></label><button id='conf'>Confirm booking</button></section>
<p id='out' role='status'></p></main>""",
          "const SLOTS = " + str(SLOTS).replace("'", '"') + """;
let doc = null, slot = null;
document.querySelectorAll('.pick').forEach(b => b.onclick = () => { doc = b.closest('.doc').dataset.d; slot = null;
  document.getElementById('who').textContent = 'Available slots: ' + b.closest('.doc').querySelector('h2').textContent;
  document.getElementById('sl').innerHTML = SLOTS[doc].map(s => s.endsWith('*') ? `<button disabled>${s.slice(0, -1)} (booked)</button>` :
    `<button class='slot' aria-pressed='false'>${s}</button>`).join(' ');
  document.querySelectorAll('.slot').forEach(x => x.onclick = () => { slot = x.textContent;
    document.querySelectorAll('.slot').forEach(y => y.setAttribute('aria-pressed', y === x)); });
  document.getElementById('slots').classList.remove('hidden'); });
document.getElementById('conf').onclick = () => send('doctor', {doctor: doc, slot, patient: document.getElementById('pn').value,
  phone: document.getElementById('pp').value}, 'Appointment confirmed.');"""))


async def _doc(p):
    await p.click(".doc[data-d=menon] .pick")
    await p.click(".slot >> text=10:00")
    await p.fill("#pn", "Rahul Das")
    await p.fill("#pp", "9123456780")
    await p.click("#conf")
    await p.wait_for_selector("text=Appointment confirmed")
    return ""


# 20 hash-routed tax wizard with a confirmation checkbox at the end
bench("tax", "/b/tax.html",
      "File the tax return for PAN ABCDE1234F with salary income 840000 and 80C deductions of 150000.",
      want("tax", pan="ABCDE1234F", salary="840000", ded="150000", confirm=True), lambda p, b: _tax(p),
      ("multi-step", "hash-router"),
      shell("File return", """<main><h1>File your return</h1><div id='v'></div><p id='out' role='status'></p></main>""",
            """const d = {pan: '', salary: '', ded: ''};
const V = {
  '#/pan': () => `<h2>Step 1: PAN</h2><label>PAN <input id='pan' value='${d.pan}'></label><a href='#/income' id='n'>Next</a>`,
  '#/income': () => `<h2>Step 2: Income</h2><label>Salary income <input id='salary' value='${d.salary}'></label>
     <label>80C deductions <input id='ded' value='${d.ded}'></label><a href='#/pan'>Back</a> <a href='#/review' id='n'>Next</a>`,
  '#/review': () => `<h2>Step 3: Review</h2><p>PAN ${d.pan}</p><p>Taxable income ₹${(+d.salary || 0) - (+d.ded || 0)}</p>
     <label><input type='checkbox' id='ok'> I confirm these details are correct</label><a href='#/income'>Back</a> <button id='file'>File return</button>`};
const save = () => ['pan', 'salary', 'ded'].forEach(k => { const i = document.getElementById(k); if (i) d[k] = i.value.trim(); });
document.addEventListener('input', save);
const render = () => { const h = V[location.hash] ? location.hash : '#/pan'; document.getElementById('v').innerHTML = V[h]();
  const f = document.getElementById('file'); if (f) f.onclick = () => {
    if (!document.getElementById('ok').checked) { document.getElementById('out').textContent = 'Please confirm the details first.'; return; }
    send('tax', {...d, confirm: true}, 'Return filed. Acknowledgement no. 4471-22.'); }; };
window.addEventListener('hashchange', render); render();"""))


async def _tax(p):
    await p.fill("#pan", "ABCDE1234F")
    await p.click("#n")
    await p.fill("#salary", "840000")
    await p.fill("#ded", "150000")
    await p.click("#n")
    await p.check("#ok")
    await p.click("#file")
    await p.wait_for_selector("text=Return filed")
    return ""
