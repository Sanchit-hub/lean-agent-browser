"""Custom widgets: autocomplete, ARIA listbox, slider, switches, steppers, tag input, calendar, reorder, star radios."""
from evals.bench.core import bench, fields, shell, want

# 47 autocomplete that only accepts a picked suggestion
CITIES = [("TRV", "Thiruvananthapuram"), ("TRZ", "Tiruchirappalli"), ("TIR", "Tirupati"), ("THN", "Thane"),
          ("TNJ", "Thanjavur"), ("BLR", "Bengaluru"), ("MAA", "Chennai"), ("COK", "Kochi")]
bench("autocomplete", "/b/delivery-city.html", "Set your delivery city to Thiruvananthapuram and save.",
      want("autocomplete", code="TRV"), lambda p, b: _auto(p), ("widget", "combobox"),
      shell("Delivery city", """<main><h1>Delivery city</h1><label for='c'>City</label>
<input id='c' role='combobox' aria-autocomplete='list' aria-expanded='false' aria-controls='lb' autocomplete='off'>
<ul id='lb' role='listbox' class='opts hidden'></ul><p id='picked'>No city selected</p><p id='err' class='err' role='alert'></p>
<button id='save'>Save city</button><p id='out' role='status'></p></main>""",
            "const C = " + str([list(c) for c in CITIES]).replace("'", '"') + """;
const c = document.getElementById('c'), lb = document.getElementById('lb'); let code = null;
c.addEventListener('input', () => { code = null; document.getElementById('picked').textContent = 'No city selected';
  const q = c.value.toLowerCase(); const hits = q.length < 2 ? [] : C.filter(x => x[1].toLowerCase().startsWith(q));
  lb.innerHTML = hits.map(x => `<li role='option' class='opt' data-code='${x[0]}'>${x[1]}</li>`).join('');
  lb.classList.toggle('hidden', !hits.length); c.setAttribute('aria-expanded', !!hits.length);
  lb.querySelectorAll('li').forEach(li => li.onclick = () => { code = li.dataset.code; c.value = li.textContent;
    document.getElementById('picked').textContent = 'Selected: ' + li.textContent; lb.classList.add('hidden'); c.setAttribute('aria-expanded', false); }); });
document.getElementById('save').onclick = () => { if (!code) { document.getElementById('err').textContent = 'Pick a city from the suggestions.'; return; }
  document.getElementById('err').textContent = ''; send('autocomplete', {code}, 'Delivery city saved.'); };"""))


async def _auto(p):
    await p.fill("#c", "Thir")
    await p.click("[data-code=TRV]")
    await p.click("#save")
    await p.wait_for_selector("text=Delivery city saved")
    return ""


# 48 div-based dropdown + colour swatches
bench("variant", "/b/shirt.html", "Add the linen shirt in size L and colour olive to the cart.",
      want("variant", size="L", color="olive"), lambda p, b: _variant(p), ("widget", "listbox"),
      shell("Linen shirt", """<main><h1>Linen shirt</h1><p>₹1,899</p>
<p>Size: <button id='sz' aria-haspopup='listbox' aria-expanded='false'>Select size</button></p>
<ul id='szl' role='listbox' aria-label='Size' class='opts hidden'><li role='option' class='opt'>S</li><li role='option' class='opt'>M</li>
<li role='option' class='opt'>L</li><li role='option' class='opt'>XL</li></ul>
<p>Colour: <span id='col'>none</span></p><div><button class='sw' aria-label='White' data-c='white'>⬜</button>
<button class='sw' aria-label='Olive' data-c='olive'>🟩</button><button class='sw' aria-label='Navy' data-c='navy'>🟦</button></div>
<button id='add'>Add to cart</button><p id='out' role='status'></p></main>""",
            """let size = null, color = null; const sz = document.getElementById('sz'), l = document.getElementById('szl');
sz.onclick = () => { l.classList.toggle('hidden'); sz.setAttribute('aria-expanded', !l.classList.contains('hidden')); };
l.querySelectorAll('li').forEach(o => o.onclick = () => { size = o.textContent; sz.textContent = 'Size ' + size; l.classList.add('hidden'); });
document.querySelectorAll('.sw').forEach(b => b.onclick = () => { color = b.dataset.c; document.getElementById('col').textContent = b.getAttribute('aria-label'); });
document.getElementById('add').onclick = () => { if (!size || !color) { document.getElementById('out').textContent = 'Choose a size and colour first.'; return; }
  send('variant', {size, color}, `Added Linen shirt (${size}, ${color}) to your cart.`); };"""))


async def _variant(p):
    await p.click("#sz")
    await p.click("#szl >> text=L")
    await p.click("[data-c=olive]")
    await p.click("#add")
    await p.wait_for_selector("text=Added Linen shirt")
    return ""


# 49 keyboard-only ARIA slider
bench("slider", "/b/display.html", "Set the screen brightness to 30% and save.",
      want("slider", brightness=30), lambda p, b: _slider(p), ("widget", "slider", "keyboard"),
      shell("Display", """<main><h1>Display</h1><p id='bl'>Brightness</p>
<div id='s' role='slider' tabindex='0' aria-labelledby='bl' aria-valuemin='0' aria-valuemax='100' aria-valuenow='50' aria-valuetext='50%'
 style='width:200px;height:12px;background:#ddd'></div><p>Use the arrow keys (5% steps), Home or End.</p><p id='val'>50%</p>
<button id='save'>Save display settings</button><p id='out' role='status'></p></main>""",
            """const s = document.getElementById('s'); let v = 50;
const set = n => { v = Math.max(0, Math.min(100, n)); s.setAttribute('aria-valuenow', v); s.setAttribute('aria-valuetext', v + '%'); document.getElementById('val').textContent = v + '%'; };
s.addEventListener('keydown', e => { const k = {ArrowRight: 5, ArrowUp: 5, ArrowLeft: -5, ArrowDown: -5}[e.key];
  if (k) { e.preventDefault(); set(v + k); } else if (e.key === 'Home') set(0); else if (e.key === 'End') set(100); });
s.addEventListener('click', e => { const r = s.getBoundingClientRect(); set(Math.round((e.clientX - r.left) / r.width * 20) * 5); });
document.getElementById('save').onclick = () => send('slider', {brightness: v}, 'Display settings saved.');"""))


async def _slider(p):
    await p.focus("#s")
    for _ in range(4):
        await p.keyboard.press("ArrowLeft")
    await p.click("#save")
    await p.wait_for_selector("text=Display settings saved")
    return ""


# 50 switches
SW = [("tfa", "Two-factor authentication", False), ("mkt", "Marketing emails", True), ("alerts", "Login alerts", False),
      ("digest", "Weekly digest", True)]
bench("switches", "/b/security.html",
      "Turn on two-factor authentication and turn off marketing emails, leave the other settings as they are, and save.",
      want("switches", tfa=True, mkt=False, alerts=False, digest=True), lambda p, b: _sw(p), ("widget", "switch"),
      shell("Security settings", "<main><h1>Account settings</h1>" + "".join(
          f"<p><button role='switch' aria-checked='{str(on).lower()}' data-k='{k}' class='sw'>{label}</button></p>" for k, label, on in SW)
          + "<button id='save'>Save settings</button><p id='out' role='status'></p></main>",
          """document.querySelectorAll('.sw').forEach(b => b.onclick = () => b.setAttribute('aria-checked', b.getAttribute('aria-checked') !== 'true'));
document.getElementById('save').onclick = () => { const d = {}; document.querySelectorAll('.sw').forEach(b => d[b.dataset.k] = b.getAttribute('aria-checked') === 'true');
  send('switches', d, 'Settings saved.'); };"""))


async def _sw(p):
    await p.click("[data-k=tfa]")
    await p.click("[data-k=mkt]")
    await p.click("#save")
    await p.wait_for_selector("text=Settings saved")
    return ""


# 51 steppers with identical buttons per row
CART = [("soap", "Sandalwood soap", 1), ("towel", "Cotton towels", 2), ("mat", "Bath mat", 2)]
bench("stepper", "/b/basket.html", "Change the quantity of the cotton towels to 4 (leave the other items alone) and update the cart.",
      want("stepper", soap=1, towel=4, mat=2), lambda p, b: _step(p), ("widget", "stepper", "repeated-controls"),
      shell("Basket", "<main><h1>Basket</h1>" + "".join(
          f"<div class='row' data-k='{k}'><h3>{n}</h3><button class='dec' aria-label='Decrease quantity'>−</button>"
          f"<input readonly value='{q}' aria-label='Quantity' size='2'><button class='inc' aria-label='Increase quantity'>+</button></div>"
          for k, n, q in CART) + "<button id='upd'>Update cart</button><p id='out' role='status'></p></main>",
          """document.querySelectorAll('.row').forEach(r => { const i = r.querySelector('input');
  r.querySelector('.inc').onclick = () => i.value = Math.min(9, +i.value + 1); r.querySelector('.dec').onclick = () => i.value = Math.max(0, +i.value - 1); });
document.getElementById('upd').onclick = () => { const d = {}; document.querySelectorAll('.row').forEach(r => d[r.dataset.k] = +r.querySelector('input').value);
  send('stepper', d, 'Cart updated.'); };"""))


async def _step(p):
    await p.click(".row[data-k=towel] .inc")
    await p.click(".row[data-k=towel] .inc")
    await p.click("#upd")
    await p.wait_for_selector("text=Cart updated")
    return ""


# 52 tag input (Enter adds a chip)
bench("tags", "/b/post-tags.html", "Tag the post with 'ml', 'python' and 'agents', remove the 'misc' tag, and save.",
      want("tags", tags=["agents", "ml", "python"]), lambda p, b: _tags(p), ("widget", "keyboard"),
      shell("Edit post", """<main><h1>Edit post: Evaluating browser agents</h1><div id='chips'></div>
<label>Add tag <input id='t' placeholder='Type a tag and press Enter'></label><button id='save'>Save tags</button><p id='out' role='status'></p></main>""",
            """let tags = ['misc']; const draw = () => { document.getElementById('chips').innerHTML = tags.map(t =>
  `<span class='chip'>${t} <button aria-label='Remove tag ${t}' data-t='${t}'>×</button></span>`).join(' ');
  document.querySelectorAll('[data-t]').forEach(b => b.onclick = () => { tags = tags.filter(x => x !== b.dataset.t); draw(); }); };
document.getElementById('t').addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault();
  const v = e.target.value.trim().toLowerCase(); if (v && !tags.includes(v)) tags.push(v); e.target.value = ''; draw(); } });
document.getElementById('save').onclick = () => send('tags', {tags}, 'Tags saved.'); draw();"""))


async def _tags(p):
    for t in ("ml", "python", "agents"):
        await p.fill("#t", t)
        await p.press("#t", "Enter")
    await p.click("[aria-label='Remove tag misc']")
    await p.click("#save")
    await p.wait_for_selector("text=Tags saved")
    return ""


# 53 calendar that needs month navigation
bench("dates", "/b/stay.html", "Search for a stay with check-in on 14 February 2027 and check-out on 16 February 2027.",
      want("dates", checkin="2027-02-14", checkout="2027-02-16"), lambda p, b: _dates(p), ("widget", "calendar"),
      shell("Find a stay", """<main><h1>Find a stay in Udaipur</h1><p>Check-in: <b id='ci'>not set</b> · Check-out: <b id='co'>not set</b></p>
<p id='hint'>Pick your check-in date.</p><div><button id='prev' aria-label='Previous month'>‹</button> <b id='mon'></b>
<button id='next' aria-label='Next month'>›</button></div><div id='cal' class='cal'></div><button id='go'>Search stays</button><p id='out' role='status'></p></main>""",
            """const M = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
let y = 2026, m = 10, ci = null, co = null;
const iso = d => `${y}-${String(m + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
const draw = () => { document.getElementById('mon').textContent = `${M[m]} ${y}`; const n = new Date(y, m + 1, 0).getDate();
  document.getElementById('cal').innerHTML = Array.from({length: n}, (_, i) => `<button aria-label='${i + 1} ${M[m]} ${y}' data-d='${iso(i + 1)}'>${i + 1}</button>`).join('');
  document.querySelectorAll('#cal button').forEach(b => b.onclick = () => { if (!ci || co) { ci = b.dataset.d; co = null; } else co = b.dataset.d;
    document.getElementById('ci').textContent = ci || 'not set'; document.getElementById('co').textContent = co || 'not set';
    document.getElementById('hint').textContent = co ? 'Dates selected.' : 'Pick your check-out date.'; }); };
document.getElementById('next').onclick = () => { m++; if (m > 11) { m = 0; y++; } draw(); };
document.getElementById('prev').onclick = () => { m--; if (m < 0) { m = 11; y--; } draw(); };
document.getElementById('go').onclick = () => send('dates', {checkin: ci, checkout: co}, 'Showing 14 stays for your dates.'); draw();"""))


async def _dates(p):
    for _ in range(3):
        await p.click("#next")
    await p.click("[data-d='2027-02-14']")
    await p.click("[data-d='2027-02-16']")
    await p.click("#go")
    await p.wait_for_selector("text=Showing 14 stays")
    return ""


# 54 reorder with move up / move down buttons
def _v_reorder(st, ans):
    got = fields(st, "reorder").get("order")
    return got == ["Fix bug #12", "Plan sprint", "Write report", "Email client"], f"got {got}"


TASKS = ["Write report", "Email client", "Fix bug #12", "Plan sprint"]
bench("reorder", "/b/priorities.html",
      "Reorder the list so 'Fix bug #12' is first and 'Plan sprint' is second, keeping the rest in their current relative order, then save.",
      _v_reorder, lambda p, b: _reorder(p), ("widget", "reorder"),
      shell("Priorities", """<main><h1>Today's priorities</h1><ol id='l'></ol><button id='save'>Save order</button><p id='out' role='status'></p></main>""",
            "let L = " + str(TASKS).replace("'", '"') + """;
const draw = () => { document.getElementById('l').innerHTML = L.map((t, i) => `<li>${t} <button aria-label='Move ${t} up' data-i='${i}' data-d='-1'>↑</button>
  <button aria-label='Move ${t} down' data-i='${i}' data-d='1'>↓</button></li>`).join('');
  document.querySelectorAll('#l button').forEach(b => b.onclick = () => { const i = +b.dataset.i, j = i + +b.dataset.d;
    if (j < 0 || j >= L.length) return; [L[i], L[j]] = [L[j], L[i]]; draw(); }); };
document.getElementById('save').onclick = () => send('reorder', {order: L}, 'Order saved.'); draw();"""))


async def _reorder(p):
    for label in ("Move Fix bug #12 up", "Move Fix bug #12 up", "Move Plan sprint up", "Move Plan sprint up"):
        await p.click(f"[aria-label='{label}']")
    await p.click("#save")
    await p.wait_for_selector("text=Order saved")
    return ""


# 55 star ratings as visually hidden radios in two groups
def _stars(name, legend):
    return f"<fieldset><legend>{legend}</legend>" + "".join(
        f"<input type='radio' name='{name}' id='{name}{n}' value='{n}' class='vh'><label for='{name}{n}' title='{n} star{'s' if n > 1 else ''}'>"
        f"<span class='vh'>{n} star{'s' if n > 1 else ''}</span><span aria-hidden='true'>★</span></label>" for n in range(1, 6)) + "</fieldset>"


bench("stars", "/b/rate-order.html", "Rate the delivery 2 stars and the product 5 stars, then submit.",
      want("stars", delivery="2", product="5"), lambda p, b: _starsol(p), ("widget", "radio", "visually-hidden"),
      shell("Rate your order", "<main><h1>Rate your order</h1><form method='post' action='/api/submit/stars'>" + _stars("delivery", "Delivery")
            + _stars("product", "Product") + "<button type='submit'>Submit ratings</button></form></main>",
            head="<style>.vh{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}label{display:inline;font-size:24px}</style>"))


async def _starsol(p):
    await p.click("label[for=delivery2]")
    await p.click("label[for=product5]")
    await p.click("text=Submit ratings")
    await p.wait_for_selector("text=submission received")
    return ""
