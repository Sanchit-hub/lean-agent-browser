"""Dynamic pages: delayed enabling, infinite scroll, debounced live search, polling jobs, re-rendering lists."""
import json

from evals.bench.core import PAGES, bench, shell, subs, want

# 67 button enabled after a countdown
bench("countdown", "/b/confirm-email.html", "Confirm the email change.",
      want("email-change", once=True, confirmed=True), lambda p, b: _cd(p), ("dynamic", "disabled"),
      shell("Confirm email", """<main><h1>Confirm your new email</h1><p>New email: ravi.new@example.com</p>
<p id='c'>You can confirm in 4 seconds.</p><button id='ok' disabled>Confirm email change</button><p id='out' role='status'></p></main>""",
            """let n = 4; const t = setInterval(() => { n--; document.getElementById('c').textContent = n > 0 ? `You can confirm in ${n} seconds.` : 'Ready.';
  if (n <= 0) { clearInterval(t); document.getElementById('ok').disabled = false; } }, 1000);
document.getElementById('ok').onclick = async () => { document.getElementById('ok').disabled = true; await send('email-change', {confirmed: true}, 'Email address updated.'); };"""))


async def _cd(p):
    await p.wait_for_selector("#ok:not([disabled])")
    await p.click("#ok")
    await p.wait_for_selector("text=Email address updated")
    return ""


# 68 infinite scroll, then act on a card
WARES = ["Steel ladle", "Glass jar set", "Cast-iron kadai", "Spice box", "Rolling pin", "Tea strainer", "Brass lota",
         "Coconut scraper", "Idli steamer", "Copper handi", "Clay tawa", "Bamboo steamer", "Silicone spatula", "Pressure cooker",
         "Sev press", "Mortar and pestle", "Wooden spoons", "Milk pan", "Chapati box", "Mixing bowl", "Bamboo cutting board",
         "Knife set", "Grater", "Measuring cups", "Oil dispenser", "Salad spinner", "Tiffin carrier", "Water filter", "Ice tray", "Sieve"]
PAGES["/b/api/wares"] = lambda q: (json.dumps(WARES[int(q.get("offset", 0)):int(q.get("offset", 0)) + 8]).encode(), "application/json")
bench("infinite-wishlist", "/b/kitchen.html", "Add the 'Bamboo cutting board' to your wishlist (nothing else).",
      want("wishlist", once=True, item="Bamboo cutting board"), lambda p, b: _iw(p), ("dynamic", "infinite-scroll"),
      shell("Kitchen", "<main><h1>Kitchen essentials</h1><div id='g'></div><p id='ld'>Loading more…</p><p id='out' role='status'></p></main>",
            """let off = 0, busy = false;
const load = async () => { if (busy || off >= 30) return; busy = true; const r = await (await fetch('/b/api/wares?offset=' + off)).json();
  r.forEach(n => { const d = document.createElement('div'); d.className = 'item'; d.innerHTML = `<h3>${n}</h3><button>Add to wishlist</button>`;
    d.querySelector('button').onclick = () => send('wishlist', {item: n}, `${n} added to your wishlist.`); document.getElementById('g').appendChild(d); });
  off += r.length; busy = false; if (off >= 30) document.getElementById('ld').textContent = 'You have seen everything.'; };
window.addEventListener('scroll', () => { if (innerHeight + scrollY > document.body.scrollHeight - 300) load(); }); load();"""))


async def _iw(p):
    for _ in range(10):
        card = p.locator(".item:has(h3:text-is('Bamboo cutting board'))")
        if await card.count():
            await card.locator("button").click()
            break
        await p.mouse.wheel(0, 4000)
        await p.wait_for_timeout(300)
    await p.wait_for_selector("text=added to your wishlist")
    return ""


# 69 debounced live search with per-result buttons
PEOPLE = ["Zoya Ahmed", "Zoya Akhtar", "Zubin Mehta", "Zara Ali", "Zoheb Ahmed", "Ayaan Zaidi"]
PAGES["/b/api/people"] = lambda q: (json.dumps([n for n in PEOPLE if q.get("q", "").lower() and q.get("q", "").lower() in n.lower()]).encode(),
                                    "application/json")
bench("live-search", "/b/people.html", "Use the people search to find Zoya Ahmed and follow her (only her).",
      want("follow", once=True, name="Zoya Ahmed"), lambda p, b: _ls(p), ("dynamic", "debounce"),
      shell("People", "<main><h1>Find people</h1><label>Search people <input id='q'></label><ul id='r'></ul><p id='out' role='status'></p></main>",
            """let t; document.getElementById('q').addEventListener('input', e => { clearTimeout(t); t = setTimeout(async () => {
  const r = await (await fetch('/b/api/people?q=' + encodeURIComponent(e.target.value))).json();
  document.getElementById('r').innerHTML = r.map(n => `<li>${n} <button data-n='${n}'>Follow</button></li>`).join('') || '<li>No people found</li>';
  document.querySelectorAll('#r button').forEach(b => b.onclick = () => { send('follow', {name: b.dataset.n}, `You are now following ${b.dataset.n}.`); b.textContent = 'Following'; b.disabled = true; });
}, 500); });"""))


async def _ls(p):
    await p.fill("#q", "Zoya")
    await p.click("[data-n='Zoya Ahmed']")
    await p.wait_for_selector("text=now following Zoya Ahmed")
    return ""


# 70 polling a background job
bench("report-job", "/b/reports.html", "Generate the monthly sales report and download it.",
      want("download", once=True, report="sales-monthly"), lambda p, b: _job(p), ("dynamic", "polling"),
      shell("Reports", """<main><h1>Reports</h1><label>Report <select id='k'><option value='sales-weekly'>Weekly sales</option>
<option value='sales-monthly'>Monthly sales</option><option value='inventory'>Inventory</option></select></label>
<button id='gen'>Generate report</button><p id='st' role='status'></p><div id='dl'></div></main>""",
            """document.getElementById('gen').onclick = () => { const k = document.getElementById('k').value, st = document.getElementById('st');
  document.getElementById('dl').innerHTML = ''; st.textContent = 'Queued…';
  setTimeout(() => st.textContent = 'Processing… 40%', 1500); setTimeout(() => st.textContent = 'Processing… 85%', 3500);
  setTimeout(() => { st.textContent = 'Ready.'; document.getElementById('dl').innerHTML = `<a href='#' id='d'>Download ${k}.csv</a>`;
    document.getElementById('d').onclick = async e => { e.preventDefault(); await send('download', {report: k});
      document.getElementById('dl').innerHTML = `<p>Downloaded ${k}.csv</p>`; }; }, 5000); };"""))


async def _job(p):
    await p.select_option("#k", "sales-monthly")
    await p.click("#gen")
    await p.click("#d", timeout=10000)
    await p.wait_for_selector("text=Downloaded")
    return ""


# 71 list that re-renders (new nodes, new order) every 1.5 s
REQ = ["Arjun Nair", "Nisha Gupta", "Nisha Rao", "Vikram Singh", "Sana Mirza"]
bench("rerender", "/b/leave.html", "Approve the leave request from Nisha Gupta, and nothing else.",
      lambda st, a: (([x["fields"] for x in subs(st, "leave")] == [{"name": "Nisha Gupta", "decision": "approve"}]),
                     f"decisions: {[x['fields'] for x in subs(st, 'leave')]}"),
      lambda p, b: _rr(p), ("dynamic", "re-render", "recovery"),
      shell("Leave requests", "<main><h1>Leave requests</h1><p>Live: updates every few seconds.</p><ul id='l'></ul><p id='out' role='status'></p></main>",
            "let R = " + json.dumps(REQ) + """; const done = new Set(); let k = 0;
const draw = () => { k++; const order = R.filter(n => !done.has(n)); if (k % 2) order.reverse();
  document.getElementById('l').innerHTML = order.map(n => `<li>${n}, 2 days <button data-n='${n}' data-d='approve'>Approve</button>
    <button data-n='${n}' data-d='reject'>Reject</button></li>`).join('');
  document.querySelectorAll('#l button').forEach(b => b.onclick = () => { done.add(b.dataset.n);
    send('leave', {name: b.dataset.n, decision: b.dataset.d}, `${b.dataset.d === 'approve' ? 'Approved' : 'Rejected'} ${b.dataset.n}.`); draw(); }); };
draw(); setInterval(draw, 1500);"""))


async def _rr(p):
    await p.click("[data-n='Nisha Gupta'][data-d=approve]")
    await p.wait_for_selector("text=Approved Nisha Gupta")
    return ""


# 72 controlled form that re-renders itself on every input
bench("remount", "/b/apply-coupon.html", "Apply the coupon code SAVE20 and place the order.",
      want("coupon-order", once=True, coupon="SAVE20"), lambda p, b: _rm(p), ("dynamic", "re-render"),
      shell("Checkout", "<main><h1>Checkout</h1><p>Subtotal ₹2,400</p><div id='f'></div><p id='out' role='status'></p></main>",
            """let st = {coupon: '', applied: false};
const draw = () => { const f = document.getElementById('f');
  f.innerHTML = `<label>Coupon code <input id='cc' value='${st.coupon}'></label> <button id='ap'>Apply</button>
    <p>${st.applied ? 'Coupon SAVE20 applied: −₹480. Total ₹1,920' : 'Total ₹2,400'}</p><button id='po'>Place order</button>`;
  const i = document.getElementById('cc'); i.addEventListener('input', () => { st.coupon = i.value; st.applied = false; draw();
    const j = document.getElementById('cc'); j.focus(); j.setSelectionRange(j.value.length, j.value.length); });
  document.getElementById('ap').onclick = () => { st.applied = st.coupon.trim().toUpperCase() === 'SAVE20';
    draw(); if (!st.applied) document.getElementById('out').textContent = 'That coupon is not valid.'; };
  document.getElementById('po').onclick = () => send('coupon-order', {coupon: st.applied ? 'SAVE20' : ''}, 'Order placed. Thank you!'); };
draw();"""))


async def _rm(p):
    await p.fill("#cc", "SAVE20")
    await p.click("#ap")
    await p.click("#po")
    await p.wait_for_selector("text=Order placed")
    return ""

