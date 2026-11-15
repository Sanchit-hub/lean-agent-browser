"""Frames, shadow DOM and tabs: nested iframes, nested shadow roots, frame reading, tab comparison, srcdoc."""
from evals.bench.core import PAGES, answer, bench, shell, want

# 62 iframe inside an iframe
PAGES["/b/frame-outer.html"] = shell("Delivery widget", "<main><h2>Delivery options</h2><iframe src='/b/frame-inner.html' title='Instructions' width='420' height='220'></iframe></main>")
PAGES["/b/frame-inner.html"] = shell("Instructions", """<main><label>Delivery instructions <textarea id='di'></textarea></label>
<button id='s'>Save instructions</button><p id='out' role='status'></p></main>""",
                                     "document.getElementById('s').onclick = () => send('nested-frame', {text: document.getElementById('di').value}, 'Instructions saved.');")
bench("nested-frame", "/b/track.html", "In the embedded delivery widget, set the delivery instructions to 'Leave at the gate' and save.",
      want("nested-frame", text="Leave at the gate"), lambda p, b: _nf(p), ("iframe", "nested"),
      shell("Track order", "<main><h1>Order 4471 is on its way</h1><iframe src='/b/frame-outer.html' title='Delivery widget' width='480' height='300'></iframe></main>"))


async def _nf(p):
    f = p.frame_locator("iframe").frame_locator("iframe")
    await f.locator("#di").fill("Leave at the gate")
    await f.locator("#s").click()
    await f.locator("text=Instructions saved").wait_for()
    return ""


# 63 nested shadow roots
bench("shadow-nested", "/b/account-card.html", "Set the shipping PIN code in the profile card to 560034 and save it.",
      want("shadow-nested", pin="560034"), lambda p, b: _sn(p), ("shadow-dom", "nested"),
      shell("Profile", "<main><h1>Your profile</h1><user-card></user-card><p id='out' role='status'></p></main>",
            """customElements.define('address-form', class extends HTMLElement { connectedCallback() {
  const r = this.attachShadow({mode: 'open'});
  r.innerHTML = `<fieldset><legend>Shipping address</legend><label>City <input id='city' value='Bengaluru'></label>
    <label>PIN code <input id='pin' value='560001'></label><button id='s'>Save address</button></fieldset>`;
  r.getElementById('s').onclick = () => send('shadow-nested', {city: r.getElementById('city').value, pin: r.getElementById('pin').value}, 'Address saved.'); } });
customElements.define('user-card', class extends HTMLElement { connectedCallback() {
  this.attachShadow({mode: 'open'}).innerHTML = `<section><h2>Meera Iyer</h2><p>Member since 2021</p><address-form></address-form></section>`; } });"""))


async def _sn(p):
    await p.fill("address-form >> #pin", "560034")
    await p.click("address-form >> #s")
    await p.wait_for_selector("text=Address saved")
    return ""


# 64 read a value inside a same-origin frame
PAGES["/b/price-widget.html"] = shell("Prices", "<main><h2>Live prices</h2><ul><li>Silver: ₹96 / g</li><li>Gold (24K): ₹7,412 / g</li><li>Gold (22K): ₹6,794 / g</li></ul></main>")
bench("frame-read", "/b/markets.html", "What is the 24K gold price per gram shown in the price widget?",
      answer("7412", no=("6794",)), lambda p, b: _fr(p), ("iframe", "read"),
      shell("Markets", "<main><h1>Markets today</h1><p>Sensex up 0.4%.</p><iframe src='/b/price-widget.html' title='Price widget' width='400' height='200'></iframe></main>"))


async def _fr(p):
    t = await p.frame_locator("iframe").locator("main").inner_text()
    return t.split("24K): ")[1].split(" /")[0]


# 65 compare two products opened in new tabs
for _k, _n, _price in (("a", "Kettle Classic", 1849), ("b", "Kettle Smart", 1599)):
    PAGES[f"/b/kettle-{_k}.html"] = shell(_n, f"<main><h1>{_n}</h1><p>Price: ₹{_price:,}</p><button id='add'>Add to cart</button><p id='out' role='status'></p></main>",
                                          f"document.getElementById('add').onclick = () => send('compare', {{item: '{_k}'}}, 'Added {_n} to cart.');")
bench("compare-tabs", "/b/kettles.html", "Open both kettle options and add the cheaper one to the cart (only that one).",
      want("compare", once=True, item="b"), lambda p, b: _cmp(p), ("tabs", "compare"),
      shell("Kettles", "<main><h1>Electric kettles</h1><p>Prices shown on each product page.</p><ul>"
            "<li><a href='/b/kettle-a.html' target='_blank'>Kettle Classic</a></li><li><a href='/b/kettle-b.html' target='_blank'>Kettle Smart</a></li></ul></main>"))


async def _cmp(p):
    async with p.context.expect_page() as pi:
        await p.click("text=Kettle Smart")
    t = await pi.value
    await t.wait_for_load_state()
    await t.click("#add")
    await t.wait_for_selector("text=Added Kettle Smart")
    return ""


# 66 srcdoc iframe
_POLL = ("<p>Which do you prefer?</p><label><input type='radio' name='v' value='tea'> Tea</label>"
         "<label><input type='radio' name='v' value='coffee'> Coffee</label><button id='vote'>Vote</button><p id='out' role='status'></p>"
         "<script>document.getElementById('vote').onclick = async () => { const c = document.querySelector('[name=v]:checked'); if (!c) return;"
         " await fetch('/api/submit/poll', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({vote: c.value})});"
         " document.getElementById('out').textContent = 'Thanks for voting!'; };</script>")
bench("srcdoc-poll", "/b/poll.html", "Vote 'Tea' in the embedded poll.",
      want("poll", once=True, vote="tea"), lambda p, b: _poll(p), ("iframe", "srcdoc"),
      shell("Office poll", "<main><h1>Office pantry poll</h1><iframe title='Poll' width='400' height='200' srcdoc=\""
            + _POLL.replace('"', "&quot;") + "\"></iframe></main>"))


async def _poll(p):
    f = p.frame_locator("iframe")
    await f.locator("[value=tea]").check()
    await f.locator("#vote").click()
    await f.locator("text=Thanks for voting").wait_for()
    return ""
