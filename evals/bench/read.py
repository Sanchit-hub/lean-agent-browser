"""Reading and extraction: tables, filters, hidden panels, delayed content, decoys."""
from evals.bench.core import PAGES, answer, bench, shell
from evals.fixtures.server import FEED, ORDERS, SEARCH_DOCS


# 21 existing laptop grid: filter on three attributes
bench("laptops", "/laptops.html",
      "Which in-stock laptop with an RTX 4060 and 16 GB of RAM is the cheapest? Reply with its name.",
      answer("bolt 15", no=("core 16", "grid 15")), lambda p, b: _fixed("Bolt 15"), ("extract", "filter"))


async def _fixed_coro(v):
    return v


def _fixed(v):
    return _fixed_coro(v)


# 22 count search results
N_PY = sum(1 for d in SEARCH_DOCS if "python" in d["topic"])
bench("search-count", "/search.html", "How many results does a search for 'python' return?",
      answer(rf"\b{N_PY}\b", regex=True), lambda p, b: _search_count(p), ("extract", "search"))


async def _search_count(p):
    await p.fill("[name=q]", "python")
    await p.click("main button")
    await p.wait_for_selector("li.result")
    return str(await p.locator("li.result").count())


# 23 aggregate across pagination
N_MEERA = sum(1 for o in ORDERS if o["customer"] == "Meera" and o["status"] == "refunded")
bench("orders-count", "/orders.html", "How many of Meera's orders have the status 'refunded'? Check every page.",
      answer(rf"\b{N_MEERA}\b", regex=True), lambda p, b: _fixed(str(N_MEERA)), ("extract", "pagination"))

# 24 first match in an infinite feed
FIRST_CRICKET = next(f["n"] for f in FEED if "cricket highlights" in f["title"])
bench("feed-first", "/feed.html", "What is the number of the first post in the feed about cricket highlights?",
      answer(rf"\b{FIRST_CRICKET}\b", regex=True), lambda p, b: _fixed(str(FIRST_CRICKET)), ("extract", "scroll"))

# 25 a second fact in the long article
bench("article-cause", "/article.html", "According to the article, what delayed the completion of the Halden bridge?",
      answer("flood", "fund"), lambda p, b: _fixed("floods and funding disputes"), ("read",))

# 26 product table: filter then max
PRODUCTS = [("Clay water jug", "Kitchen", 899, 4.1, 12), ("Brass diya set", "Decor", 1499, 4.7, 4),
            ("Steel tiffin", "Kitchen", 649, 4.3, 30), ("Silk cushion cover", "Decor", 1899, 4.8, 0),
            ("Teak serving tray", "Kitchen", 2499, 4.9, 7), ("Jute rug", "Decor", 3299, 4.6, 3),
            ("Copper bottle", "Kitchen", 1199, 4.5, 18), ("Block-print quilt", "Bedding", 4599, 4.9, 2),
            ("Cotton bedsheet", "Bedding", 1799, 4.4, 9), ("Terracotta planter", "Garden", 549, 4.2, 25),
            ("Bamboo blinds", "Decor", 2199, 4.0, 6), ("Neem comb", "Bath", 199, 4.6, 40),
            ("Herbal soap pack", "Bath", 399, 4.4, 50), ("Cast-iron tawa", "Kitchen", 1349, 4.75, 11),
            ("Rattan basket", "Decor", 999, 3.9, 14), ("Wool shawl", "Apparel", 2899, 4.85, 5)]
bench("products-table", "/b/products.html",
      "Among products priced under ₹2,000, which one has the highest rating? Reply with the product name.",
      answer("silk cushion cover"), lambda p, b: _fixed("Silk cushion cover"), ("extract", "table"),
      shell("Products", "<main><h1>Home store catalogue</h1><table><thead><tr><th>Product</th><th>Category</th><th>Price</th>"
            "<th>Rating</th><th>Stock</th></tr></thead><tbody>" + "".join(
                f"<tr><td>{n}</td><td>{c}</td><td>₹{p:,}</td><td>{r}</td><td>{s}</td></tr>" for n, c, p, r, s in PRODUCTS)
            + "</tbody></table></main>"))

# 27 sum a filtered column
SHIP = [(f"SH-{300 + i}", ["Pending", "Delivered", "In transit", "Pending", "Cancelled"][i % 5], (i * 7) % 13 + 1,
         ["Pune", "Delhi", "Agra", "Goa"][i % 4]) for i in range(20)]
PENDING_QTY = sum(q for _, s, q, _ in SHIP if s == "Pending")
bench("pending-sum", "/b/shipments.html", "What is the total quantity across all pending shipments?",
      answer(rf"\b{PENDING_QTY}\b", regex=True), lambda p, b: _fixed(str(PENDING_QTY)), ("extract", "table", "math"),
      shell("Shipments", "<main><h1>Shipments</h1><table><thead><tr><th>ID</th><th>Status</th><th>Quantity</th><th>Destination</th>"
            "</tr></thead><tbody>" + "".join(f"<tr><td>{a}</td><td>{s}</td><td>{q}</td><td>{d}</td></tr>" for a, s, q, d in SHIP)
            + "</tbody></table></main>"))

# 28 flights: only 5 shown until "Show all"
FLIGHTS = [("AI 803", 6250, "2h 35m", "Non-stop"), ("6E 512", 4890, "4h 50m", "1 stop"), ("SG 141", 5480, "2h 40m", "Non-stop"),
           ("UK 871", 7120, "2h 30m", "Non-stop"), ("6E 2231", 4410, "6h 05m", "1 stop"), ("QP 1340", 5990, "2h 45m", "Non-stop"),
           ("AI 9811", 3980, "8h 20m", "2 stops"), ("IX 1174", 5150, "2h 50m", "Non-stop"), ("6E 6047", 5210, "2h 35m", "Non-stop"),
           ("SG 8152", 4720, "5h 10m", "1 stop")]
bench("flights", "/b/flights.html",
      "Find the cheapest non-stop flight from Delhi to Goa on this page and report its flight number.",
      answer("ix 1174", no=("ai 9811", "6e 2231")), lambda p, b: _fixed("IX 1174"), ("extract", "show-more"),
      shell("Flights", "<main><h1>Delhi → Goa, Fri 20 Nov</h1><ul id='fl'>" + "".join(
          f"<li class='f{' hidden' if i >= 5 else ''}'><b>{n}</b> · ₹{p:,} · {d} · {s}</li>" for i, (n, p, d, s) in enumerate(FLIGHTS))
          + "</ul><button id='more'>Show all 10 flights</button></main>",
          "document.getElementById('more').onclick = e => { document.querySelectorAll('.f').forEach(x => x.classList.remove('hidden')); e.target.remove(); };"))

# 29 specs inside a collapsed <details>
bench("specs", "/b/nimbus8.html", "What is the battery capacity of the Nimbus 8 phone?",
      answer("5000"), lambda p, b: _fixed("5000 mAh"), ("read", "collapsed"),
      shell("Nimbus 8", """<main><h1>Nimbus 8</h1><p>₹24,999 · 6.5-inch display · 50 MP camera</p>
<details><summary>Full specifications</summary><dl><dt>Display</dt><dd>6.5" AMOLED, 120 Hz</dd><dt>Processor</dt><dd>Octa-core 2.4 GHz</dd>
<dt>Battery</dt><dd>5000 mAh, 45 W charging</dd><dt>Weight</dt><dd>189 g</dd></dl></details>
<p>Charger in the box: 45 W. Battery life up to 2 days.</p></main>"""))

# 30 ARIA tabs whose panels are hidden until selected
bench("tabs", "/b/kettle.html", "How many days do you have to return the Kettle Pro?",
      answer(r"\b21\b", regex=True), lambda p, b: _fixed("21"), ("read", "tabs-widget"),
      shell("Kettle Pro", """<main><h1>Kettle Pro 1.7 L</h1><div role='tablist'>
<button role='tab' aria-selected='true' aria-controls='p1' id='t1'>Description</button>
<button role='tab' aria-selected='false' aria-controls='p2' id='t2'>Shipping</button>
<button role='tab' aria-selected='false' aria-controls='p3' id='t3'>Returns</button></div>
<div role='tabpanel' id='p1' aria-labelledby='t1'><p>Stainless steel, auto shut-off, 1500 W.</p></div>
<div role='tabpanel' id='p2' aria-labelledby='t2' hidden><p>Ships in 2 days. Free delivery over ₹999.</p></div>
<div role='tabpanel' id='p3' aria-labelledby='t3' hidden><p>Returns accepted within 21 days of delivery, unused and in original packaging.</p></div></main>""",
            """document.querySelectorAll('[role=tab]').forEach(t => t.onclick = () => document.querySelectorAll('[role=tab]').forEach(x => {
  x.setAttribute('aria-selected', x === t); document.getElementById(x.getAttribute('aria-controls')).hidden = x !== t; }));"""))

# 31 accordion FAQ
FAQ = [("How long does delivery take?", "3 to 5 working days in metro cities."),
       ("Do you ship internationally?", "Yes, we ship to 38 countries. Duties are paid by the customer."),
       ("Can I change my order?", "Within 2 hours of placing it."), ("Which payment methods work?", "UPI, cards and net banking.")]
bench("faq", "/b/faq.html", "Does the store ship internationally, and if so to how many countries?",
      answer(r"\b38\b", regex=True), lambda p, b: _fixed("Yes, 38 countries"), ("read", "accordion"),
      shell("FAQ", "<main><h1>Frequently asked questions</h1>" + "".join(
          f"<h3><button aria-expanded='false' aria-controls='a{i}' class='q'>{q}</button></h3><div id='a{i}' hidden><p>{a}</p></div>"
          for i, (q, a) in enumerate(FAQ)) + "</main>",
          "document.querySelectorAll('.q').forEach(b => b.onclick = () => { const o = b.getAttribute('aria-expanded') !== 'true';"
          " b.setAttribute('aria-expanded', o); document.getElementById(b.getAttribute('aria-controls')).hidden = !o; });"))

# 32 docs site: navigate the sidebar
DOCS = {"intro": ("Introduction", "Welcome to the Cloudly API. Every request needs an API key."),
        "auth": ("Authentication", "Send your key in the Authorization header as a bearer token."),
        "errors": ("Errors", "Errors use standard HTTP codes. 429 means you hit a rate limit."),
        "limits": ("Rate limits", "Limits per API key: Free plan 60 requests per minute; Pro plan 600 requests per minute; "
                   "Enterprise plan 6000 requests per minute. Bursts up to 2x are allowed for 10 seconds."),
        "webhooks": ("Webhooks", "Webhooks retry 5 times with exponential backoff."),
        "sdk": ("SDKs", "Official SDKs exist for Python, Go and TypeScript.")}
_side = "<nav aria-label='Docs'><ul>" + "".join(f"<li><a href='/b/docs/{k}.html'>{t}</a></li>" for k, (t, _) in DOCS.items()) + "</ul></nav>"
for _k, (_t, _body) in DOCS.items():
    PAGES[f"/b/docs/{_k}.html"] = shell(f"{_t} · Cloudly docs", f"{_side}<main><h1>{_t}</h1><p>{_body}</p></main>")
bench("docs-nav", "/b/docs/intro.html", "Using the Cloudly docs, find the API rate limit for the Pro plan in requests per minute.",
      answer(r"\b600\b", regex=True), lambda p, b: _fixed("600"), ("navigate", "docs"))

# 33 pricing comparison with check marks
bench("pricing", "/b/pricing.html", "What is the cheapest plan that includes single sign-on (SSO)? Reply with the plan name.",
      answer("business", no=("team plan",)), lambda p, b: _fixed("Business"), ("extract", "table"),
      shell("Pricing", """<main><h1>Plans</h1><table><thead><tr><th>Feature</th><th>Starter ₹499/mo</th><th>Team ₹1,499/mo</th>
<th>Business ₹3,999/mo</th><th>Enterprise (contact us)</th></tr></thead><tbody>
<tr><td>Projects</td><td>3</td><td>Unlimited</td><td>Unlimited</td><td>Unlimited</td></tr>
<tr><td>Audit log</td><td>—</td><td>✓</td><td>✓</td><td>✓</td></tr>
<tr><td>Single sign-on (SSO)</td><td>—</td><td>—</td><td>✓</td><td>✓</td></tr>
<tr><td>Priority support</td><td>—</td><td>—</td><td>—</td><td>✓</td></tr></tbody></table></main>"""))

# 34 events grouped by month
EVENTS = {"November 2026": [("21 Nov", "Pottery workshop"), ("28 Nov", "Jazz in the park")],
          "December 2026": [("2 Dec", "Startup mixer"), ("5 Dec", "Kathakali night"), ("12 Dec", "Food truck fair")],
          "January 2027": [("5 Jan", "Kite festival"), ("17 Jan", "Book swap")]}
bench("events", "/b/events.html", "Which event is on 5 December 2026?",
      answer("kathakali", no=("kite",)), lambda p, b: _fixed("Kathakali night"), ("read",),
      shell("Events", "<main><h1>What's on</h1>" + "".join(
          f"<h2>{m}</h2><ul>" + "".join(f"<li><time>{d}</time> · {t}</li>" for d, t in ev) + "</ul>" for m, ev in EVENTS.items()) + "</main>"))

# 35 nested config with two keys of the same name
bench("config", "/b/config.html", "In the deployment config shown, what is the database connection timeout?",
      answer(r"\b5\b", regex=True), lambda p, b: _fixed("5 seconds"), ("read", "code"),
      shell("Config", """<main><h1>deploy.yaml</h1><pre>server:
  port: 8080
  timeout: 30
database:
  host: db.internal
  pool_size: 20
  timeout: 5
cache:
  ttl: 300</pre><p>All durations are in seconds.</p></main>"""))

# 36 date reasoning against a stated "today"
INV = [("INV-2031", "1 Oct 2026", "Paid"), ("INV-2038", "20 Oct 2026", "Paid"), ("INV-2043", "8 Nov 2026", "Unpaid"),
       ("INV-2047", "14 Nov 2026", "Paid"), ("INV-2051", "30 Nov 2026", "Unpaid"), ("INV-2055", "15 Dec 2026", "Unpaid")]
bench("invoices", "/b/invoices.html", "Which unpaid invoice is overdue? Reply with its number.",
      answer("inv-2043", no=("inv-2051", "inv-2055")), lambda p, b: _fixed("INV-2043"), ("extract", "dates"),
      shell("Invoices", "<main><h1>Invoices</h1><p>Today: 15 November 2026</p><table><thead><tr><th>Invoice</th><th>Due date</th>"
            "<th>Status</th></tr></thead><tbody>" + "".join(f"<tr><td>{a}</td><td>{d}</td><td>{s}</td></tr>" for a, d, s in INV)
            + "</tbody></table></main>"))

# 37 hidden decoy text must not leak into the answer. Only truly hidden text (display:none, visibility:hidden,
# [hidden]) is used: off-screen text is read by screen readers, so reading it is not a mistake.
bench("hidden-price", "/b/teapot.html", "What is the current price of the clay teapot?",
      answer(r"\b1299\b", regex=True, no=(r"\b999\b",)), lambda p, b: _fixed("₹1,299"), ("read", "hidden-text"),
      shell("Clay teapot", """<main><h1>Clay teapot, 600 ml</h1>
<p class='hidden'>Price: ₹999 (old listing)</p><p style='visibility:hidden'>Sale price ₹999</p><p hidden>Price ₹999</p>
<p class='price'>Price: ₹1,299</p><p>Hand-thrown in Khurja. Dishwasher safe.</p></main>"""))

# 38 content that loads after a delay
bench("lazy-reviews", "/b/reviews.html", "What average rating and how many reviews does the review section show for the Trek backpack?",
      answer("4.3", r"128"), lambda p, b: _lazy(p), ("read", "delayed"),
      shell("Trek backpack", """<main><h1>Trek backpack 40 L</h1><p>₹3,499</p><section id='rv'><h2>Reviews</h2><p>Loading reviews…</p></section></main>""",
            """setTimeout(() => { document.getElementById('rv').innerHTML = '<h2>Reviews</h2><p>Average rating 4.3 out of 5 (128 reviews)</p>'
  + '<p>“Comfortable on long treks.”</p><p>“Zips feel cheap.”</p>'; }, 2500);"""))


async def _lazy(p):
    await p.wait_for_selector("text=Average rating")
    return await p.inner_text("#rv")

